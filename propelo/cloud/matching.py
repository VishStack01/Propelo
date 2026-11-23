"""Match one user's filters against the shared inventory and update their pipeline.

The same decisions as `propelo filter-feed` and the scheduled search prompt:
each kept role carries the quoted checks that kept it; near-misses go to the
skip log with what would change the decision; roles that closed or aged out
leave the "found" list.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta, timezone

from .. import feed, gates
from . import repo
from ..scamcheck import check as scam_check
from .db import Database, now_iso
from .ingest import feed_state

MAX_FOUND = 700     # found roles kept per user before new ones wait
MAX_SKIPPED = 200   # near misses kept per user (older than 30 days are cleared on every run)
_ID = re.compile(r"^[A-Za-z0-9_.:@+~-]{1,200}$")


FULL_EVERY = timedelta(days=7)    # a full pass at least this often, whatever else is true
OVERLAP = timedelta(hours=3)      # a changed-roles pass looks this far behind the last match, in case an intake overlapped it


def settings_hash(doc: dict) -> str:
    """Changes whenever any filter that decides a match changes: it is taken from the match settings themselves."""
    return hashlib.sha256(repr(feed.settings_from_dashboard(doc)).encode()).hexdigest()[:16]


def _untouched(d: dict) -> bool:
    """A role the matcher added and the person has done nothing with: safe to take back when their filters change."""
    return (d.get("stage") in ("found", None, "") and d.get("foundVia") in ("careers-feed", "remote-board") and not d.get("saved")
            and not d.get("autoApply") and not d.get("needsYou") and not d.get("notes") and not d.get("decision") and not d.get("tailored"))


def _records(db: Database, since: str = "", fits=None, page: int = 5000):
    """Active roles, a page at a time, so a hundred thousand of them never sit in memory together.
    since: only roles added, changed or reopened at or after this time.
    fits: a test on the title; a role is read in full only when it passes (most of an inventory does not)."""
    last = ""
    while True:
        with db.tx() as c:
            rows = c.all("SELECT id, title FROM jobs WHERE active = 1 AND id > ? AND last_seen_at >= ? ORDER BY id LIMIT ?", (last, since, page))
            if not rows:
                return
            last = rows[-1]["id"]
            want = [r["id"] for r in rows if fits is None or fits(r["title"])]
            full = []
            for i in range(0, len(want), 500):
                part = want[i:i + 500]
                full += c.all(f"SELECT record FROM jobs WHERE active = 1 AND id IN ({','.join('?' * len(part))}) ORDER BY id", tuple(part))
        for r in full:
            yield json.loads(r["record"])


def _urls(db: Database, page: int = 20000):
    last = ""
    while True:
        with db.tx() as c:
            rows = c.all("SELECT id, url FROM jobs WHERE active = 1 AND id > ? ORDER BY id LIMIT ?", (last, page))
        if not rows:
            return
        for r in rows:
            yield r["url"]
        last = rows[-1]["id"]


def match_user(db: Database, uid: str, now: datetime | None = None, log=print) -> dict:
    now = now or datetime.now(timezone.utc)
    started = now_iso()
    with db.tx() as c:
        sdoc = repo.get_doc(c, uid, "settings", "profile")
        sdata = sdoc["data"] if sdoc else dict(repo.DEFAULT_SETTINGS)
        known = [(d["id"], d["data"]) for d in repo.list_docs(c, uid, "jobs")]
        state = feed_state(c)
        ms = c.one("SELECT settings_hash, last_match_at, full_at, more FROM match_state WHERE user_id = ?", (uid,))
        inventory = c.scalar("SELECT COUNT(*) AS n FROM jobs WHERE active = 1")
    settings = feed.settings_from_dashboard(sdata)
    shash = settings_hash(sdata)
    # Everything is read when the filters changed, when the last run had more fits than it could add,
    # or once a week. Otherwise only the roles that are new or changed since the last match.
    full = not (ms and ms["settings_hash"] == shash and ms["last_match_at"] and not ms["more"]
                and (ms["full_at"] or "") > now_iso(-FULL_EVERY))
    since = "" if full else (datetime.fromisoformat(ms["last_match_at"].replace("Z", "+00:00")) - OVERLAP).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    # Found roles and near misses have their own room, so a long skip list never stops new matches arriving.
    n_found = sum(1 for _, d in known if d.get("stage") in ("found", None, ""))
    n_skipped = sum(1 for _, d in known if d.get("stage") == "skipped")
    room, skip_room = max(0, MAX_FOUND - n_found), max(0, MAX_SKIPPED - n_skipped)
    # After a change of filters, roles found under the old ones and never touched are judged again: the ones
    # that no longer fit leave the list. (This also clears what the starting filters matched before the
    # person said what they were looking for.)
    recheck = None
    if full and ms and ms["settings_hash"] != shash:
        recheck = {i for i, d in known if _untouched(d)}
    # The title decides most roles, so only the ones whose title fits are read in full. Whether a known
    # role is still listed is asked of the whole inventory, whatever was read.
    res = feed.match(_records(db, since, lambda title: gates.title_fits(title, settings)), settings, known, state or None, now,
                     max_kept=min(150, room), max_skips=min(40, skip_room), feed_urls=_urls(db), recheck=recheck)
    known_ids = {i for i, _ in known}
    added = skipped = closed = expired = removed = 0
    with db.tx() as c:
        for did in res["unfit"]:
            cur = repo.get_doc(c, uid, "jobs", did)
            if cur and _untouched(cur["data"]):   # looked at again: the person may have acted on it meanwhile
                repo.delete_doc(c, uid, "jobs", did)
                removed += 1
        for sub in ("kept", "skipped"):
            for did, doc in res[sub]:
                if did in known_ids or not _ID.match(did) or repo.get_doc(c, uid, "jobs", did):
                    continue
                risk = scam_check(doc)
                if risk["level"] != "ok":
                    doc = dict(doc, risk=risk)
                repo.set_doc(c, uid, "jobs", did, doc)
                added += sub == "kept"
                skipped += sub == "skipped"
        for did in res["gone"]:
            cur = repo.get_doc(c, uid, "jobs", did)
            if cur and cur["data"].get("stage") in ("found", None, ""):
                d = cur["data"]
                repo.update_doc(c, uid, "jobs", did, {"stage": "skipped", "skip": {"gate": "Closed", "reason": "No longer listed on the company's job board.", "wouldChange": ""},
                                                      "timeline": repo.append_timeline(d, "Closed: no longer listed")})
                closed += 1
        for did in res["expired"]:
            cur = repo.get_doc(c, uid, "jobs", did)
            if cur and cur["data"].get("stage") in ("found", None, "") and cur["data"].get("autoApply") != "queued":
                repo.delete_doc(c, uid, "jobs", did)
                expired += 1
        # Housekeeping: skipped roles older than 30 days, and only the 60 newest runs.
        cutoff = (now - timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
        for d in repo.list_docs(c, uid, "jobs"):
            if d["data"].get("stage") == "skipped" and (d["data"].get("foundAt") or "9") < cutoff:
                repo.delete_doc(c, uid, "jobs", d["id"])
        runs = sorted(repo.list_docs(c, uid, "runs"), key=lambda d: d["data"].get("startedAt") or "", reverse=True)
        for d in runs[59:]:
            repo.delete_doc(c, uid, "runs", d["id"])
        best = next((doc for _, doc in res["kept"] if doc.get("region") == "remote-global"), None)
        summary = (f"{added} new {'role' if added == 1 else 'roles'} matched your filters"
                   + (f"; best remote-worldwide: {best['title']} at {best['company']}" if best else "") + "."
                   if added else "No new roles matched your filters this hour.")
        rid = now.strftime("%Y-%m-%dT%H%M") + "-match"
        repo.set_doc(c, uid, "runs", rid, {"startedAt": started, "finishedAt": now_iso(), "kind": "search", "scanned": inventory if full else res["feedRecords"],
                                            "added": added, "skipped": skipped, "closed": closed, "summary": summary})
        if sdoc:
            repo.update_doc(c, uid, "settings", "profile", {"coverage": {
                "companies": state.get("companies"), "companyBoards": state.get("boards"), "openings": state.get("openings"),
                "feedAt": state.get("generatedAt"), "inventory": inventory}})
        # last_match_at is when this run began reading: the next changed-roles pass starts from there.
        c.execute("INSERT INTO match_state(user_id, settings_hash, last_match_at, last_feed_at, full_at, more) VALUES (?, ?, ?, ?, ?, ?) "
                  "ON CONFLICT (user_id) DO UPDATE SET settings_hash = excluded.settings_hash, last_match_at = excluded.last_match_at, "
                  "last_feed_at = excluded.last_feed_at, full_at = COALESCE(excluded.full_at, match_state.full_at), more = excluded.more",
                  (uid, shash, started, state.get("generatedAt") or "", started if full else None, 1 if res["more"] else 0))
        # Filters saved while this run was reading (its own task blocked a second one from being queued):
        # match again with the new ones, so the person is not left waiting for the next scheduled run.
        latest = repo.get_doc(c, uid, "settings", "profile")
        if latest and settings_hash(latest["data"]) != shash:
            repo.enqueue(c, "match_user", user_id=uid, dedupe_key=f"match-again:{uid}", max_attempts=3)
    log(f"matched user {uid[:8]}: +{added} kept, +{skipped} skipped, {closed} closed, {expired} expired "
        f"{', ' + str(removed) + ' no longer fit' if removed else ''} ({'all' if full else 'changed'} roles: {res['feedRecords']} read)")
    return {"added": added, "skipped": skipped, "closed": closed, "expired": expired, "inventory": inventory, "full": full, "read": res["feedRecords"], "removed": removed}
