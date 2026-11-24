"""Apply your personal filters to the public India feed.

  propelo filter-feed --feed <url-or-path> --settings-json settings.json \
      --known known/ --out new/

Writes one JSON document per kept role to new/kept/, near-misses (in your field,
failing exactly one gate) to new/skipped/, and new/index.json with counts. Each
file is a dashboard job document, ready to store.
"""

from __future__ import annotations

import gzip
import io
import json
import re
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from .dedupe import canonical_url, fingerprint
from .gates import apply_decision
from .models import Job
from .settings import LocationPolicy, Settings
from . import visaclock

NEAR_MISS_GATES = {"Experience", "Posted", "Location", "Pay", "Seniority"}


def load_feed(src: str) -> list[dict]:
    if re.match(r"https?://", src):
        raw = urllib.request.urlopen(urllib.request.Request(src, headers={"User-Agent": "careeros"}), timeout=60).read()
    else:
        raw = Path(src).read_bytes()
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    return [json.loads(line) for line in io.StringIO(raw.decode("utf-8")) if line.strip()]


def tagger_families() -> list[str]:
    from .tags import FAMILIES
    return FAMILIES


def settings_from_dashboard(doc: dict) -> Settings:
    """Turn the dashboard's settings/profile document into gate settings."""
    s = Settings()
    if doc.get("maxRequiredYears") is not None:
        s.max_required_years = float(doc["maxRequiredYears"])
    years = doc.get("yearsExperience")
    if years not in (None, ""):
        try:
            y = max(0.0, min(50.0, float(years)))
        except (TypeError, ValueError):
            y = None
        if y is not None:
            # Roles may ask for a little more than you have: a year of stretch early on, two later.
            s.experience_years = y
            s.max_required_years = y + (1 if y < 3 else 2)
            s.allow_internships = y < 2
    if doc.get("maxPostingAgeDays"):
        s.max_posting_age_days = int(doc["maxPostingAgeDays"])
    floor = doc.get("salaryFloorLpa")
    s.salary_floor_lpa = float(floor) if floor not in (None, "", 0) else None
    s.require_stated_pay = bool(doc.get("requireStatedPay"))
    s.needs_sponsorship = bool(doc.get("needsSponsorship"))
    if doc.get("jobMode") == "part-time" and visaclock.part_time_ok(doc.get("visa")):
        # Part-time work while studying is allowed by the student visa itself: no sponsor needed.
        s.needs_sponsorship = False
    fams = [f for f in (doc.get("families") or []) if f in tagger_families()]
    if fams:
        # Families chosen: they decide, plus any target roles typed in (the built-in tech keywords no longer apply).
        s.families = fams
        s.role_keywords = [r.lower() for r in doc.get("targetRoles") or []]
    elif doc.get("targetRoles"):
        # The roles typed in decide on their own. (Adding the built-in tech keywords here showed a nurse
        # who typed "nurse" hundreds of software roles.)
        s.role_keywords = [r.lower() for r in doc["targetRoles"] if str(r).strip()] or s.role_keywords
    if doc.get("titleExclude"):
        s.title_exclude = [t.strip().lower() for t in doc["titleExclude"] if str(t).strip()]
    if doc.get("dealbreakers"):
        s.dealbreakers = [d.strip() for d in re.split(r"[,\n]", str(doc["dealbreakers"])) if d.strip()]
    if doc.get("companyBlocklist"):
        s.company_blocklist = list(doc["companyBlocklist"])
    home = str(doc.get("homeCountry") or "IN").upper()[:2]
    raw = doc.get("places") or []
    places = [x.strip() for x in (raw if isinstance(raw, list) else re.split(r"[,;\n]", str(raw))) if str(x).strip()][:20]
    # In India and looking abroad: only once they have said where, otherwise the India rules still apply.
    seeking = home == "IN" and bool(doc.get("workAbroad")) and bool(places)
    if home != "IN" or seeking:
        s.location = LocationPolicy(home=home, places=places, remote_ok=doc.get("remoteOk", True) is not False, elsewhere=seeking,
                                    keep_unclear_remote=True, south_india="never", rest_of_india="never", abroad="remote")
        return s
    locs = " ".join(doc.get("locations") or []).lower()
    if locs:
        s.location = LocationPolicy(
            south_india="any" if "south india (any" in locs or "bengaluru" in locs or "hyderabad" in locs else ("remote" if "south india (remote" in locs else "never"),
            rest_of_india="any" if "rest of india (any" in locs else ("remote" if "rest of india (remote" in locs or "remote (india)" in locs else "never"),
            abroad="remote" if "worldwide" in locs or "global" in locs else "never",
        )
    return s


def load_known(path: str | None) -> tuple[set[str], set[str], set[str]]:
    """(ids, canonical urls, company+title fingerprints) of roles already on the dashboard."""
    ids, urls, fps = set(), set(), set()
    if not path:
        return ids, urls, fps
    p = Path(path)
    files = list(p.rglob("*.json")) if p.is_dir() else [p]
    for f in files:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        items = data if isinstance(data, list) else [data]
        for it in items:
            doc = it.get("data", it) if isinstance(it, dict) else {}
            ids.add(it.get("id") or f.stem)
            if doc.get("url"):
                urls.add(canonical_url(doc["url"]))
            if doc.get("company") and doc.get("title"):
                fps.add(fingerprint(doc["company"], doc["title"]))
    return ids, urls, fps


def _known_docs(path: str | None) -> list[tuple[str, dict]]:
    if not path:
        return []
    p = Path(path)
    out = []
    for f in (list(p.rglob("*.json")) if p.is_dir() else [p]):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        for it in (data if isinstance(data, list) else [data]):
            if isinstance(it, dict):
                out.append((it.get("id") or f.stem, it.get("data", it)))
    return out


def load_summary(feed_src: str) -> dict | None:
    """summary.json next to the feed (same folder or URL), or None."""
    src = re.sub(r"india\.jsonl\.gz$", "summary.json", feed_src)
    if src == feed_src:
        return None
    try:
        if re.match(r"https?://", src):
            raw = urllib.request.urlopen(urllib.request.Request(src, headers={"User-Agent": "careeros"}), timeout=30).read()
        else:
            raw = Path(src).read_bytes()
        return json.loads(raw)
    except (OSError, ValueError):
        return None


def stale(known: list[tuple[str, dict]], feed_urls: set[str], summary: dict | None, settings: Settings, now: datetime) -> dict:
    """Roles on the dashboard the feed shows are gone or past your window.

    gone: found via the feed, still at stage "found", and no longer listed on a
          board that was read successfully this scan (so it closed).
    expired: still at stage "found" and posted before your window."""
    gone, expired = [], []
    errored = set((summary or {}).get("erroredCompanies", []))
    for doc_id, d in known:
        if d.get("stage") not in ("found", None, ""):
            continue
        posted = "" if d.get("autoApply") == "queued" or d.get("needsYou") else (d.get("postedAt") or "")
        try:
            dt = datetime.fromisoformat(posted.replace("Z", "+00:00"))
            dt = dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
            if (now - dt).days > settings.max_posting_age_days:
                expired.append(doc_id)
                continue
        except ValueError:
            pass
        if (summary and d.get("foundVia") in ("careers-feed", "remote-board") and d.get("url")
                and canonical_url(d["url"]) not in feed_urls and d.get("company") not in errored):
            gone.append(doc_id)
    return {"gone": gone, "expired": expired}


def _about(summary: str) -> str:
    s = re.sub(r"\s+", " ", summary or "").strip()
    m = re.match(r"(.{40,260}?[.!?])\s", s + " ")
    return m.group(1) if m else s[:240]


def match(records, settings: Settings, known: list[tuple[str, dict]], summary: dict | None = None,
          now: datetime | None = None, max_kept: int = 400, max_skips: int = 60, feed_urls=None, recheck=None) -> dict:
    """The decision core: which feed records are new kept roles, which are near-misses worth
    showing as skipped, and which known roles closed or aged out.

    records: any iterable of feed records, read once and never held, so a hundred thousand roles
             can be streamed from a database without filling memory.
    known: (doc id, dashboard document) pairs already in the user's pipeline.
    feed_urls: when `records` is only part of the feed (the roles that changed since the last match),
             the addresses of every role still listed, so an unchanged role is not taken for closed.
    Returns {"kept": [(id, doc)], "skipped": [(id, doc)], "gone": [...], "expired": [...],
             "feedRecords", "alreadyKnown", "duplicates", "byRegion", "more"}. alreadyKnown and duplicates
    count roles that fit; a role that fails the filters is dropped before either is looked at.
    more: there were more fits than max_kept allowed, so another full pass would add some.
    recheck: ids of known roles to judge again (after the filters changed); "unfit" lists the ones that
             no longer pass, or are no longer in `records` at all."""
    now = now or datetime.now(timezone.utc)
    ids, urls, fps = set(), set(), set()
    watch: set[str] = set()  # roles stale() may call closed: only these need their address looked for in the feed
    for doc_id, d in known:
        ids.add(doc_id)
        if d.get("url"):
            urls.add(canonical_url(d["url"]))
            if d.get("stage") in ("found", None, "") and d.get("foundVia") in ("careers-feed", "remote-board"):
                watch.add(canonical_url(d["url"]))
        if d.get("company") and d.get("title"):
            fps.add(fingerprint(d["company"], d["title"]))
    kept, skipped, n_known, dupes, n_records = [], [], 0, 0, 0
    seen_fp: set[str] = set()
    listed: set[str] = set()
    still: set[str] = set()
    if feed_urls is not None and watch:
        listed = {u for u in map(canonical_url, feed_urls) if u in watch}
    in_loop = bool(watch) and feed_urls is None
    for r in records:
        n_records += 1
        cu = None
        if in_loop:
            cu = canonical_url(r["url"])
            if cu in watch:
                listed.add(cu)
        again = False
        if r["id"] in ids:
            n_known += 1
            if recheck is None or r["id"] not in recheck:
                continue
            again = True
        board = r.get("via") == "board"
        job = Job(company=r["company"], title=r["title"], url=r["url"],
                  source=r["source"] if board else f"{r['source']} (company careers page)",
                  location=r.get("location", ""), work_mode=r.get("workMode", ""), description=r.get("summary", ""),
                  posted_at=r.get("postedAt", ""), salary_text=r.get("salary", ""),
                  raw={"facts": r.get("facts") or {}, "experience_header": r.get("experienceHeader", "")})
        d = apply_decision(job, settings, now)
        if again:
            if d.kept:
                still.add(r["id"])
            continue
        failed = [c.gate for c in d.checks if not c.passed]
        role_ok = "Role" not in failed and "Company" not in failed
        if not d.kept and not (role_ok and len(failed) == 1 and failed[0] in NEAR_MISS_GATES):
            continue
        # Only now the costlier identity checks: most records never get here.
        fp = fingerprint(r["company"], r["title"])
        if (cu if cu is not None else canonical_url(r["url"])) in urls or fp in fps:
            n_known += 1
            continue
        if fp in seen_fp:  # the same role listed once per city: one card is enough
            dupes += 1
            continue
        seen_fp.add(fp)
        doc = job.to_record()
        doc["brief"] = {"about": _about(r.get("summary", "")),
                        "sources": [{"title": f"{r['source']} listing" if board else f"{r['company']} careers page", "url": r["url"]}]}
        doc["foundVia"] = "remote-board" if board else "careers-feed"
        if r.get("facts", {}).get("applicants"):
            doc["applicants"] = r["facts"]["applicants"]
        if r.get("facts", {}).get("legit"):
            doc["legitimacy"] = r["facts"]["legit"]
        if r.get("facts", {}).get("reposts", {}).get("count"):
            doc["reposts"] = r["facts"]["reposts"]
        if (r.get("tags") or {}).get("archetype"):
            doc["archetype"] = r["tags"]["archetype"]
        if (r.get("tags") or {}).get("skills"):
            doc["skills"] = r["tags"]["skills"]
        if (r.get("tags") or {}).get("type"):
            doc["jobType"] = r["tags"]["type"]  # Full-time, Part-time, Internship or Contract
        if (r.get("tags") or {}).get("payTier"):
            doc["payTier"] = r["tags"]["payTier"]
        if (r.get("facts") or {}).get("visa"):
            doc["visa"] = r["facts"]["visa"]  # sponsorship: the posting's words, UK register, salary floor
        if (r.get("facts") or {}).get("daysOpen") is not None:
            doc["daysOpen"] = r["facts"]["daysOpen"]
        if (r.get("facts") or {}).get("payBand"):
            doc["payBand"] = r["facts"]["payBand"]
        if d.kept:
            kept.append((r["id"], doc))
        else:
            doc["skip"]["wouldChange"] = {
                "Experience": "Raising your experience limit.", "Posted": "A wider posting window.",
                "Location": "Allowing this location or work mode.", "Pay": "A lower pay floor.", "Seniority": "Allowing senior titles.",
            }.get(failed[0], "")
            if failed[0] == "Seniority" and settings.experience_years is not None and any(
                    c.gate == "Seniority" and c.value.startswith("An entry-level") for c in d.checks):
                continue  # too junior for them: not worth showing as a near miss
            if failed[0] == "Pay" and settings.require_stated_pay and not (r.get("facts") or {}).get("salaryHigh"):
                doc["skip"]["wouldChange"] = "Allowing roles that don't state pay."
            skipped.append((r["id"], doc))
    order = {"remote-global": 0, "remote-india": 1, "remote-local": 1, "south-india": 2, "local": 2, "remote-unclear": 3}
    abroad = settings.location.by_places
    if abroad:
        # Someone living abroad is looking for work where they live: roles there first, then remote roles
        # open to the world, and last the remote roles that don't say who can apply.
        order = {"local": 0, "remote-local": 0, "remote-global": 1, "remote-unclear": 2}

    def sponsor_rank(doc):  # for someone who needs a visa: an employer with a record of sponsoring comes first
        if not settings.needs_sponsorship:
            return 0
        v = doc.get("visa") or {}
        if v.get("status") == "no" or v.get("opt") == "no" or (v.get("ukRegister") or {}).get("listed") is False:
            return 2
        if (v.get("status") == "offers" or v.get("opt") == "yes" or (v.get("ukRegister") or {}).get("listed") or (v.get("nlRegister") or {}).get("listed")
                or v.get("usLca") or v.get("caLmia") or v.get("iePermits") or v.get("eVerify")):
            return 0
        return 1

    def posted_ts(doc):
        try:
            return datetime.fromisoformat(doc["postedAt"].replace("Z", "+00:00")).timestamp() if doc.get("postedAt") else 0
        except ValueError:
            return 0
    def top_pay(doc):  # stated 20 LPA+, or public data says freshers get 20 LPA+ at the low end
        return doc.get("payTier") == "20+" or (not doc.get("payTier") and (doc.get("payBand") or {}).get("low", 0) >= 20)
    def unclear(doc):  # a remote role that doesn't say who can apply comes after the ones known to be open
        return 1 if any(c.get("gate") == "Location" and "doesn't say who can apply" in (c.get("value") or "") for c in doc.get("checks") or []) else 0
    kept.sort(key=lambda x: (order.get(x[1].get("region", ""), 9), unclear(x[1]), sponsor_rank(x[1]), 0 if top_pay(x[1]) else 1, -posted_ts(x[1])))
    more = len(kept) > max_kept
    kept, skipped = kept[:max_kept], skipped[:max_skips]
    out = {"more": more, "feedRecords": n_records, "alreadyKnown": n_known, "duplicates": dupes, "kept": kept, "skipped": skipped,
           "byRegion": {k: sum(1 for _, d in kept if d.get("region") == k) for k in order}}
    out.update(stale(known, listed, summary, settings, now))
    out["unfit"] = sorted(set(recheck) - still - set(out["gone"]) - set(out["expired"])) if recheck is not None else []
    return out


def run(feed_src: str, settings: Settings, known_path: str | None, out_dir: str | Path,
        max_skips: int = 60, max_kept: int = 400, now: datetime | None = None, summary: dict | None = None) -> dict:
    records = load_feed(feed_src)
    summary = summary if summary is not None else load_summary(feed_src)
    res = match(records, settings, _known_docs(known_path), summary, now, max_kept=max_kept, max_skips=max_skips)
    out = Path(out_dir)
    (out / "kept").mkdir(parents=True, exist_ok=True)
    (out / "skipped").mkdir(parents=True, exist_ok=True)
    for sub in ("kept", "skipped"):
        for doc_id, doc in res[sub]:
            (out / sub / f"{doc_id}.json").write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    index = dict(res, kept=[i for i, _ in res["kept"]], skipped=[i for i, _ in res["skipped"]])
    if summary:
        index["feed"] = {k: summary.get(k) for k in ("generatedAt", "companies", "boards", "openings", "remoteBoards")}
    (out / "index.json").write_text(json.dumps(index, indent=2), encoding="utf-8")
    return index
