"""Read the hourly scan's feed into the shared `jobs` table.

Fails closed: an empty, unreadable or suspiciously small feed changes nothing,
so a bad scan can never wipe the inventory. A role is closed only when its
company's board was read successfully and no longer lists it.

The table keeps only what the hosted product uses: roles in the US, the UK, Ireland and the Netherlands, and
remote roles, each as its feed record. The full posting text is not stored: nothing in the hosted app reads it
(matching, the business feeds and the admin counts read the record), and it made up most of the database.
A database that still holds posting text from before is emptied once and refilled from the feed (`slim`).
"""

from __future__ import annotations

import gzip
import hashlib
import json
import tempfile
import urllib.request
from pathlib import Path

from .. import countries
from .db import Database, now_iso

MAX_BYTES = 200 * 1024 * 1024


class IngestError(RuntimeError):
    pass


def _fetch(base: str, name: str) -> bytes | None:
    """A small feed file, whole (summary.json)."""
    src = base.rstrip("/") + "/" + name
    try:
        if src.startswith(("http://", "https://")):
            req = urllib.request.Request(src, headers={"User-Agent": "propelo-cloud"})
            with urllib.request.urlopen(req, timeout=120) as r:
                raw = r.read(MAX_BYTES + 1)
        else:
            raw = Path(src).read_bytes()
    except (OSError, ValueError):
        return None
    if len(raw) > MAX_BYTES:
        raise IngestError(f"{name} is larger than {MAX_BYTES // 1024 // 1024} MB")
    return raw


def _local(base: str, name: str, tmp: Path) -> Path | None:
    """A big feed file as a path on disk: the file itself for a local feed, a download for a URL. It is
    never held in memory, so the worker's memory use doesn't grow with the feed."""
    src = base.rstrip("/") + "/" + name
    if not src.startswith(("http://", "https://")):
        return Path(src) if Path(src).exists() else None
    dest, size = tmp / name, 0
    try:
        req = urllib.request.Request(src, headers={"User-Agent": "propelo-cloud"})
        with urllib.request.urlopen(req, timeout=300) as r, open(dest, "wb") as f:
            while True:
                chunk = r.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_BYTES:
                    raise IngestError(f"{name} is larger than {MAX_BYTES // 1024 // 1024} MB")
                f.write(chunk)
    except (OSError, ValueError):
        return None
    return dest


def _lines(path: Path | None):
    """Parsed lines of a .jsonl or .jsonl.gz file, one at a time. Unreadable lines are skipped."""
    if path is None:
        return
    try:
        with open(path, "rb") as probe:
            gz = probe.read(2) == b"\x1f\x8b"
        with (gzip.open(path, "rt", encoding="utf-8") if gz else open(path, encoding="utf-8")) as f:
            for line in f:
                if line.strip():
                    try:
                        yield json.loads(line)
                    except json.JSONDecodeError:
                        continue
    except (OSError, EOFError, UnicodeDecodeError):
        return


CORE4 = {"US", "GB", "IE", "NL"}


def _ok(r: dict) -> bool:
    return bool(r.get("id") and r.get("company") and r.get("title") and r.get("url") and "loc" in (r.get("facts") or {}))


def wanted(r: dict) -> bool:
    """A role the hosted product can match: in one of the four countries, or remote."""
    if r.get("workMode") == "remote" or str((r.get("facts") or {}).get("loc", "")).startswith("remote"):
        return True
    return bool(countries.of_record(r) & CORE4)


def slim(db: Database, log=print) -> bool:
    """Empty a jobs table that still stores posting text, so the next read of the feed refills it small.
    Emptying (not deleting row by row) gives the space back at once, which matters on a database at its size
    limit. Members' own roles, applications and documents live in other tables and are not touched; matching
    waits while the table is empty (matching.match_user). Returns True when it emptied the table."""
    with db.tx() as c:
        if not c.one("SELECT id FROM jobs WHERE text <> '' LIMIT 1"):
            return False
    with db.tx() as c:
        c.execute("TRUNCATE jobs" if db.kind == "postgres" else "DELETE FROM jobs")
    log("jobs table emptied to drop stored posting text; refilling from the feed")
    return True


def _summary(base: str) -> dict:
    raw = _fetch(base, "summary.json")
    try:
        return json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        return {}


BATCH = 500


def ingest(db: Database, feed_url: str, log=print, force: bool = False) -> dict:
    # The summary is a few kilobytes: when it shows the feed we already have, nothing else is downloaded.
    summary = _summary(feed_url)
    with db.tx() as c:
        prev = c.one("SELECT value FROM feed_state WHERE key = 'feed'")
    prev = json.loads(prev["value"]) if prev else {}
    if summary.get("generatedAt") and prev.get("generatedAt") == summary["generatedAt"] and not force:
        return {"status": "unchanged", "generatedAt": summary["generatedAt"]}
    with tempfile.TemporaryDirectory(prefix="propelo-feed-") as tmp:
        rec_path = _local(feed_url, "india.jsonl.gz", Path(tmp))
        total = sum(1 for r in _lines(rec_path) if _ok(r) and wanted(r))
        if not total:
            raise IngestError("The feed is empty or unreadable; keeping the current inventory.")
        if not summary.get("generatedAt"):
            raise IngestError("The feed has no summary.json; keeping the current inventory.")
        # Only now, with a good feed on disk: drop stored posting text once, then refill.
        if slim(db, log=log):
            force = True
        now = now_iso()
        with db.tx() as c:
            known = {a["id"]: a for a in c.all("SELECT id, company, rev, active FROM jobs")}
            active = [a for a in known.values() if a["active"]]
            if not force and len(active) > 200 and total < 0.5 * len(active):
                raise IngestError(f"The feed shrank from {len(active)} to {total} roles; keeping the current inventory until a scan confirms it.")
            seen: set[str] = set()
            rows: list[tuple] = []
            written = 0

            def flush() -> None:
                c.many("INSERT INTO jobs(id, company, title, url, source, posted_at, record, text, rev, active, first_seen_at, last_seen_at) "
                       "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?) ON CONFLICT (id) DO UPDATE SET company = excluded.company, title = excluded.title, "
                       "url = excluded.url, source = excluded.source, posted_at = excluded.posted_at, record = excluded.record, text = excluded.text, "
                       "rev = excluded.rev, active = 1, last_seen_at = excluded.last_seen_at, closed_at = NULL", rows)
                rows.clear()
            for r in _lines(rec_path):
                if not _ok(r) or not wanted(r) or r["id"] in seen:
                    continue
                seen.add(r["id"])
                text = ""  # not stored: see the module note
                rec = {k: v for k, v in r.items() if k != "text"}
                facts = dict(rec.get("facts") or {})
                if (facts.get("salaryHigh") or 0) > 450:  # no fresher role pays 450+ LPA: a funding or revenue figure misread as pay
                    for k in ("salaryLow", "salaryHigh", "salaryQuote"):
                        facts.pop(k, None)
                    rec["facts"] = facts
                record = json.dumps(rec, ensure_ascii=False, separators=(",", ":"))
                rev = hashlib.sha1((record + "\x00" + text).encode("utf-8")).hexdigest()[:20]
                old = known.get(r["id"])
                if old and old["active"] and old["rev"] == rev:
                    continue  # nothing about this role changed since the last feed: no write at all
                rows.append((r["id"], r["company"][:200], r["title"][:300], r["url"][:2000], str(r.get("source", ""))[:100],
                             r.get("postedAt") or "", record, text, rev, now, now))
                written += 1
                if len(rows) >= BATCH:
                    flush()
            if rows:
                flush()
            errored = set(summary.get("erroredCompanies") or [])
            closing = [(now, a["id"]) for a in active if a["id"] not in seen and a["company"] not in errored]
            c.many("UPDATE jobs SET active = 0, closed_at = ? WHERE id = ?", closing)
            state = {k: summary.get(k) for k in ("generatedAt", "companies", "boards", "openings", "remoteBoards", "erroredCompanies")}
            state.update(records=len(seen), closed=len(closing), changed=written, ingestedAt=now)
            c.execute("INSERT INTO feed_state(key, value, updated_at) VALUES ('feed', ?, ?) "
                      "ON CONFLICT (key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
                      (json.dumps(state), now))
    log(f"ingested {len(seen)} roles ({written} new or changed, {len(closing)} closed) from feed generated {summary['generatedAt']}")
    return {"status": "ingested", "records": len(seen), "changed": written, "closed": len(closing), "generatedAt": summary["generatedAt"]}


def feed_state(c) -> dict:
    row = c.one("SELECT value FROM feed_state WHERE key = 'feed'")
    return json.loads(row["value"]) if row else {}
