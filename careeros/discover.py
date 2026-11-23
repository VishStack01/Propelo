"""Find each company's public job board.

For every company in config/companies/companies.csv we try its likely board
slugs on each hiring system's public feed, in order of how common they are
among Indian product companies. The first board that checks out is recorded.

"Checks out" means: the feed exists, the board's own company name matches
ours when the feed reports one, and for India-headquartered companies at least
one opening is in India or remote (a board full of US-only roles under the same
slug is usually a different company with the same name).

Results are cached in feed/boards.json. Unmapped companies are re-tried after
`refresh_days`; they use career sites the scan can't read (Darwinbox, Keka,
Zoho Recruit, custom pages) and are visited by the agent instead.
"""

from __future__ import annotations

import csv
import json
import os
import re
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import countries, geo
from .models import iso
from .sources import http

ATS_ORDER = ["greenhouse", "lever", "ashby", "smartrecruiters", "recruitee", "breezy", "personio", "workable"]
# Workable rate-limits hard and answers for any name with an empty board, so it
# is tried last and with the first slug only, unless the company list names it.
SLUGS_PER_ATS = {"workable": 1}
GLOBAL_CATEGORIES = {"global-india-engineering", "remote-first-global", "yc-remote"}
PROBE_INTERVAL = 0.25  # seconds between requests to one host while discovering
_deadline = [float("inf")]  # time.monotonic() after which no new company is started
_books: dict = {}          # sponsor registers by country, loaded for a run that has sponsor candidates
_taken: set = set()        # (hiring system, board) pairs already mapped: never map one board under two names


def _norm(s: str) -> str:
    s = re.sub(r"\b(ai|labs?|technologies|technology|inc|pvt|ltd|private|limited|india|hq|app|the|careers|jobs)\b", " ", (s or "").lower())
    return re.sub(r"[^a-z0-9]", "", s)


def names_match(a: str, b: str) -> bool:
    na, nb = _norm(a), _norm(b)
    if not na or not nb:
        return False
    return na == nb or (len(min(na, nb, key=len)) >= 4 and (na in nb or nb in na))


def _get(url):
    return http.get_json(url, timeout=10, retries=1, min_interval=PROBE_INTERVAL)


def probe(ats: str, slug: str) -> dict | None:
    """Return {"board_name", "locations": [..]} if `slug` is a live board on `ats`, else None."""
    try:
        if ats == "greenhouse":
            jobs = _get(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs").get("jobs", [])
            try:
                name = _get(f"https://boards-api.greenhouse.io/v1/boards/{slug}").get("name", "")
            except http.FetchError:
                name = ""
            return {"board_name": name, "locations": [(j.get("location") or {}).get("name", "") for j in jobs],
                    "titles": [j.get("title", "") for j in jobs]}
        if ats == "lever":
            data = _get(f"https://api.lever.co/v0/postings/{slug}?mode=json")
            if not isinstance(data, list):
                return None
            return {"board_name": "", "locations": [((j.get("categories") or {}).get("location") or "") + (" remote" if j.get("workplaceType") == "remote" else "") for j in data],
                    "titles": [j.get("text", "") for j in data]}
        if ats == "ashby":
            data = _get(f"https://api.ashbyhq.com/posting-api/job-board/{slug}")
            if "jobs" not in data:
                return None
            return {"board_name": "", "locations": [(j.get("location") or "") + (" remote" if j.get("isRemote") else "") for j in data["jobs"]],
                    "titles": [j.get("title", "") for j in data["jobs"]],
                    "extra": [", ".join(x.get("location", "") for x in (j.get("secondaryLocations") or []) if isinstance(x, dict)) for j in data["jobs"]]}
        if ats == "workable":
            data = _get(f"https://apply.workable.com/api/v1/widget/accounts/{slug}")
            if "jobs" not in data:
                return None
            locs = [", ".join(x for x in (j.get("city"), j.get("country")) if x) + (" remote" if j.get("telecommuting") else "") for j in data["jobs"]]
            return {"board_name": data.get("name", ""), "locations": locs, "titles": [j.get("title", "") for j in data["jobs"]]}
        if ats == "smartrecruiters":
            data = _get(f"https://api.smartrecruiters.com/v1/companies/{slug}/postings?limit=100")
            content = data.get("content", [])
            if not content:
                return None  # unknown ids also answer 200 with nothing in them
            name = (content[0].get("company") or {}).get("name", "")
            locs = [((j.get("location") or {}).get("fullLocation") or (j.get("location") or {}).get("country", "")) + (" remote" if (j.get("location") or {}).get("remote") else "") for j in content]
            return {"board_name": name, "locations": locs, "titles": [j.get("name", "") for j in content]}
        if ats == "recruitee":
            data = _get(f"https://{slug}.recruitee.com/api/offers/")
            if "offers" not in data:
                return None
            return {"board_name": "", "locations": [(o.get("location") or o.get("country") or "") + (" remote" if o.get("remote") else "") for o in data["offers"]],
                    "titles": [o.get("title", "") for o in data["offers"]]}
        if ats == "breezy":
            data = _get(f"https://{slug}.breezy.hr/json")
            if not isinstance(data, list):
                return None
            return {"board_name": "", "locations": [((j.get("location") or {}).get("name") or "") + (" remote" if (j.get("location") or {}).get("is_remote") else "") for j in data],
                    "titles": [j.get("name", "") for j in data]}
        if ats == "workday":
            from .sources import workday
            first = http.post_json(workday.api(slug) + "/jobs", {"appliedFacets": {}, "limit": 20, "offset": 0, "searchText": ""},
                                   timeout=10, retries=1, min_interval=PROBE_INTERVAL)
            if "jobPostings" not in first:
                return None
            hit = workday.india_facet(first.get("facets") or [])
            page = http.post_json(workday.api(slug) + "/jobs", {"appliedFacets": {hit[0]: [hit[1]]} if hit else {}, "limit": 20, "offset": 0,
                                  "searchText": "" if hit else "India"}, timeout=10, retries=1, min_interval=PROBE_INTERVAL)
            posts = page.get("jobPostings") or []
            return {"board_name": "", "locations": [(j.get("locationsText") or "") + (" India" if hit else "") for j in posts],
                    "titles": [j.get("title", "") for j in posts]}
        if ats == "amazon":
            data = _get(f"https://www.amazon.jobs/en/search.json?result_limit=20&normalized_country_code[]={slug or 'IND'}")
            jobs = data.get("jobs") or []
            return {"board_name": "Amazon", "locations": [j.get("normalized_location") or j.get("location") or "" for j in jobs],
                    "titles": [j.get("title", "") for j in jobs]}
        if ats == "personio":
            text = http.get_text(f"https://{slug}.jobs.personio.de/xml", timeout=10, retries=1, min_interval=PROBE_INTERVAL)
            if "<workzag-jobs" not in text:
                return None
            root = ET.fromstring(text)
            return {"board_name": "", "locations": [(p.findtext("office") or "") for p in root.findall("position")],
                    "titles": [(p.findtext("name") or "") for p in root.findall("position")]}
    except (http.FetchError, ET.ParseError, ValueError, AttributeError):
        return None
    return None


def _india_or_remote(loc: str) -> bool:
    return geo.classify(loc)["india"] or bool(re.search(r"remote|anywhere|worldwide|apac", loc or "", re.I))


# Deep sweep: boards from the open ATS company inventories are kept only when they
# list a role in one of our job families (every field, not only developers) in India or open to it. A bare "Remote" usually means
# remote in the company's own country, so it doesn't count on its own.
DEV_TITLE = re.compile(r"engineer|developer|\bsde\b|\bswe\b|machine learning|\bml\b|\bai\b|data scientist|devops|\bsre\b|"
                       r"full[ -]?stack|back[ -]?end|front[ -]?end|mobile|android|\bios\b|forward deployed|programmer", re.I)
_OPEN_TO_INDIA = re.compile(r"\b(india|anywhere|worldwide|global|apac|asia)\b", re.I)


def _wanted(title: str) -> bool:
    """A role in any job family we match (see scan.wanted_title), not only developer roles."""
    from .scan import wanted_title
    return wanted_title(title)


# Countries whose on-site roles count when the scan covers on-site roles worldwide
# (CAREEROS_SCAN_ONSITE=world): India first, then developed economies.
FOCUS = {"IN", "US", "GB", "CA", "AU", "NZ", "DE", "NL", "FR", "IE", "CH", "AT", "BE", "SE", "DK", "NO", "FI", "ES", "IT", "PT", "PL",
         "SG", "JP", "KR", "AE", "IL", "HK"}


def _in_scope(loc: str) -> bool:
    from .scan import ONSITE_WORLD
    if geo.classify(loc)["india"] or _OPEN_TO_INDIA.search(loc):
        return True
    return ONSITE_WORLD and bool(countries.resolve(loc) & FOCUS)


def deep_fit(found: dict) -> int:
    """How many roles in a job family we match are on this board, in India or open to it (or, when the scan
    covers on-site roles worldwide, in India or a developed country)."""
    locs, titles = found.get("locations", []), found.get("titles", [])
    extra = found.get("extra") or [""] * len(locs)
    n = 0
    for i, title in enumerate(titles):
        loc = (locs[i] if i < len(locs) else "") + " " + (extra[i] if i < len(extra) else "")
        if _wanted(title or "") and _in_scope(loc):
            n += 1
    return n


def accept(company: dict, found: dict) -> tuple[bool, str]:
    """Is this board really this company's? Returns (ok, confidence).

    A board with no openings is never accepted: some systems (Workable,
    Breezy) answer for any name with an empty board, so an empty board proves
    nothing. Those companies are re-checked after a few days instead."""
    if not found.get("locations"):
        return False, "empty"
    if found.get("explicit"):
        # Our own list names this exact board (big employers on Workday or their own site).
        return (True, "listed") if any(_india_or_remote(l) or _in_scope(l) for l in found.get("locations", [])) else (False, "no-india-roles")
    if company.get("category") == "sponsor":
        # An employer from a government sponsor list, its board address guessed from its name. Keep the board only
        # if it lists roles in that country and is provably that employer's.
        from . import sponsor_sweep
        cc = company.get("country") or ""
        local = sum(1 for l in found.get("locations", []) if cc in countries.resolve(l or ""))
        if not local:
            return False, "no-local-roles"
        if found.get("board_name"):
            ok = sponsor_sweep.same_employer(_books, cc, company["name"], found["board_name"])
            return (True, f"sponsor-name:{local}") if ok else (False, "name-mismatch")
        # No name on the board to compare: only the employer's full name as the address counts, with several local roles.
        full = found.get("slug") == (company.get("slugs") or [""])[0] and len(found.get("slug") or "") >= 6
        return (True, f"sponsor-slug:{local}") if full and local >= 2 else (False, "unsure")
    if company.get("category") == "deep":
        # The inventory gives the exact board, so the board's own name may be a brand name.
        n = deep_fit(found)
        return (True, f"deep:{n}") if n else (False, "no-india-dev-roles")
    if found.get("board_name"):
        if not names_match(company["name"], found["board_name"]):
            return False, "name-mismatch"
        conf = "name"
    else:
        conf = "slug"
    locs = found.get("locations", [])
    if company.get("category") in GLOBAL_CATEGORIES and (conf == "name" or any(_india_or_remote(l) for l in locs)):
        # A slug guess without a board name to compare must at least list roles in India or remote;
        # "google" on Recruitee or "linkedin" on Lever are other companies' (or test) boards.
        return True, conf
    if any(_india_or_remote(l) for l in locs):
        return True, conf + "+india"
    return (True, conf) if conf == "name" else (False, "no-india-roles")


def discover_one(company: dict) -> dict | None:
    if time.monotonic() > _deadline[0]:
        return None  # out of time this run; it stays due for the next one
    now = iso(datetime.now(timezone.utc))
    tried = 0
    pairs: list[tuple[str, str]] = []
    if company.get("ats") == "custom":
        # Own career site (Google, Microsoft, Flipkart...): the agent reads it; never guess slugs.
        return {"status": "unmapped", "checkedAt": now, "probes": 0, "custom": True}
    explicit = (company.get("ats"), company.get("token")) if company.get("ats") and company.get("token") else None
    if explicit:
        pairs.append(explicit)
    slugs = [s for s in company.get("slugs", []) if s][:4]
    sponsor = company.get("category") == "sponsor"
    for ats in ATS_ORDER:
        for slug in slugs[: SLUGS_PER_ATS.get(ats, len(slugs))]:
            pairs.append((ats, slug))
    empty = False
    for ats, slug in pairs:
        if time.monotonic() > _deadline[0] + 180:
            return None  # well past the time budget: leave the rest of this company for the next run
        if sponsor and (ats, slug.lower()) in _taken:
            continue     # that board is already read under another company's name
        tried += 1
        found = probe(ats, slug)
        if not found:
            continue
        if (ats, slug) == explicit and company.get("category") != "deep":
            found = dict(found, explicit=True)
        ok, conf = accept(company, dict(found, slug=slug))
        if ok:
            out = {"status": "mapped", "ats": ats, "token": slug, "confidence": conf,
                   "boardName": found.get("board_name", ""), "openings": len(found.get("locations", [])), "checkedAt": now}
            if sponsor:
                out["country"] = company.get("country") or ""
            return out
        empty = empty or conf == "empty"
    out = {"status": "unmapped", "checkedAt": now, "probes": tried}
    if sponsor:
        from .sponsor_sweep import RETRY_DAYS
        return dict(out, retryDays=RETRY_DAYS)
    if empty:
        out["retryDays"] = 3  # an empty board may be real and start hiring soon
    if company.get("category") == "deep":
        out["retryDays"] = 21  # hiring changes; look at the board again in three weeks
    return out


def load_companies(path: str | Path) -> list[dict]:
    rows = []
    with open(path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            r["slugs"] = (r.get("slugs") or "").split()
            rows.append(r)
    return rows


def share_out(todo: list[dict], limit: int) -> list[dict]:
    """Which due companies a run checks, and in what order. Deep-sweep boards need one request each and are where
    new boards come from, but they sit at the end of the list: left to list order, the curated companies that never
    map (own career sites) used up every run and the sweep was never reached. So a quarter of each run goes to the
    curated and radar lists and the rest to the sweep, taken in turn so neither waits for the other."""
    from .sponsor_sweep import PER_RUN
    per_run = int(os.environ.get("CAREEROS_SPONSOR_SWEEP") or PER_RUN)
    # Employers from the sponsor registers take many requests each (the board address is a guess), so a fixed
    # number per run, spread through it: enough to cover the registers in days without leaning on any one system.
    spons = [c for c in todo if c.get("category") == "sponsor"][:max(0, per_run)]
    todo = [c for c in todo if c.get("category") != "sponsor"]
    deep = [c for c in todo if c.get("category") == "deep"]
    rest = [c for c in todo if c.get("category") != "deep"]
    n_rest = min(len(rest), max(limit // 4, limit - len(deep)))
    rest, deep = rest[:n_rest], deep[:limit - n_rest]
    out: list[dict] = []
    i = j = k = 0
    while i < len(deep) or j < len(rest) or k < len(spons):
        out += deep[i:i + 3]
        i += 3
        if j < len(rest):
            out.append(rest[j])
            j += 1
        if k < len(spons):
            out.append(spons[k])
            k += 1
    return out


def run(companies_csv: str | Path, cache_path: str | Path, refresh_days: int = 14, workers: int = 32,
        limit: int | None = None, max_minutes: float | None = None, log=print, extra: list[str | Path] | None = None) -> dict:
    companies = load_companies(companies_csv)
    seen = {c["name"] for c in companies}
    for path in extra or []:  # e.g. feed/radar-companies.csv: companies the hiring radar saw hiring
        if Path(path).exists():
            for c in load_companies(path):
                if c["name"] not in seen:
                    companies.append(c)
                    seen.add(c["name"])
    cache_path = Path(cache_path)
    cache = json.loads(cache_path.read_text()) if cache_path.exists() else {"companies": {}}
    known = cache.setdefault("companies", {})
    now = datetime.now(timezone.utc)

    def due(c):
        e = known.get(c["name"])
        if not e:
            return True
        if c.get("ats") == "custom":
            return e.get("status") == "mapped" or not e.get("custom")  # drop an old slug guess
        if c.get("ats") and c.get("token") and e.get("status") == "mapped" and (e.get("ats"), str(e.get("token"))) != (c["ats"], c["token"]):
            return True  # the list now names a different board
        if e.get("status") == "mapped":
            # Re-check boards that errored, and boards accepted while empty by older versions.
            return bool(e.get("stale")) or str(e.get("confidence", "")).endswith("-empty")
        try:
            last = datetime.fromisoformat(e.get("checkedAt", "").replace("Z", "+00:00"))
        except ValueError:
            return True
        return now - last > timedelta(days=e.get("retryDays", refresh_days))

    todo = [c for c in companies if due(c)]
    if limit:
        todo = share_out(todo, limit)
    _books.clear()
    _taken.clear()
    if any(c.get("category") == "sponsor" for c in todo):
        from . import sponsor_sweep
        _books.update(sponsor_sweep.load(cache_path.parent))
        _taken.update((e.get("ats"), str(e.get("token", "")).lower()) for e in known.values() if e.get("status") == "mapped" and e.get("token"))
    log(f"Discovering boards for {len(todo)} of {len(companies)} companies…")
    _deadline[0] = time.monotonic() + max_minutes * 60 if max_minutes else float("inf")
    skipped = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = {pool.submit(discover_one, c): c for c in todo}
        for i, fut in enumerate(as_completed(futs), 1):
            c = futs[fut]
            try:
                res = fut.result()
            except Exception as e:  # one bad company never stops the run
                res = {"status": "error", "error": str(e)[:200], "checkedAt": iso(now)}
            if res is None:
                skipped += 1
                continue
            if c.get("category") == "sponsor" and res.get("status") != "mapped":
                # A hundred thousand of these: keep only what says when to look again.
                known[c["name"]] = {"category": "sponsor", **res}
                continue
            if res.get("status") == "mapped" and res.get("token"):
                _taken.add((res.get("ats"), str(res["token"]).lower()))
            known[c["name"]] = {"category": c.get("category", ""), "city": c.get("city", ""), "website": c.get("website", ""), **res}
            if i % 50 == 0:
                log(f"  {i}/{len(todo)} checked")
                cache_path.parent.mkdir(parents=True, exist_ok=True)  # keep progress if the run is cut short
                cache_path.write_text(json.dumps(cache, indent=1, ensure_ascii=False), encoding="utf-8")
    listed = 0
    for c in companies:  # keep metadata current for every company
        if c.get("category") == "sponsor":
            # Register names are candidates, not companies we list: no entry until one has been looked at.
            if c["name"] in known:
                known[c["name"]]["category"] = "sponsor"
            continue
        listed += 1
        e = known.setdefault(c["name"], {"status": "pending"})
        e["category"], e["city"] = c.get("category", ""), c.get("city", "")
    cache["generatedAt"] = iso(datetime.now(timezone.utc))
    mapped = sum(1 for e in known.values() if e.get("status") == "mapped")
    cache["stats"] = {"companies": listed, "mapped": mapped,
                      "byAts": {a: sum(1 for e in known.values() if e.get("ats") == a and e.get("status") == "mapped") for a in ATS_ORDER}}
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(cache, indent=1, ensure_ascii=False), encoding="utf-8")
    if skipped:
        log(f"  time budget reached; {skipped} companies left for the next run")
    log(f"Mapped {mapped} of {listed} companies to a public job board.")
    if len(companies) > listed:
        from . import sponsor_sweep
        st = sponsor_sweep.stats(cache)
        log(f"Sponsor registers: {st['checked']} of {len(companies) - listed} employers looked at so far, {st['kept']} boards found.")
    return cache
