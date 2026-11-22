"""Scan every mapped company board and publish the India feed.

Sources: every mapped company board (feed/boards.json) plus the remote job
boards with public feeds (sources/aggregators.py).

Output (in `out_dir`):
  india.jsonl.gz   one line per open role in India or remote (every job family), with
                   pre-extracted facts (experience, remote scope, pay, closed)
  full.jsonl.gz    id + the full posting text, for the job board
  summary.json     counts by hiring system and region, errors
  unmapped.csv     companies whose career site isn't on a public feed; the
                   agent visits these in rotation

The feed is deliberately not filtered by anyone's personal settings: it is a
public list of openings. `careeros filter-feed` applies your filters.
"""

from __future__ import annotations

import csv
import gzip
import hashlib
import json
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from concurrent.futures import TimeoutError as FuturesTimeout
from datetime import datetime, timezone
from pathlib import Path

from . import company_names, extract, geo, paydata, signals, sponsors, tags
from .dedupe import canonical_url, fingerprint, job_id
from .models import Job, iso
from .sources import SCOUTS, greenhouse, smartrecruiters
from .sources.aggregators import AGGREGATORS, MIN_HOURS

TECH = re.compile(
    r"engineer|developer|scientist|machine learning|\bml\b|\bai\b|genai|\bllm|data|analyst|research|designer|"
    r"product manager|automation|\bsde\b|\bswe\b|devops|\bsre\b|platform|backend|back end|front ?end|full[ -]?stack|"
    r"mobile|android|\bios\b|\bqa\b|\btest|security|intern|graduate|trainee|architect|prompt|nlp|vision|robotics|"
    r"forward deployed|solutions? engineer|applied",
    re.I,
)
# Business families scanned too (marketing, sales, finance and strategy, operations and people, product and design),
# so the board covers the same job families as the big US boards, not only engineering.
BUSINESS = re.compile(
    r"marketing|growth|\bseo\b|content (writer|strategist|marketing)|copywriter|\bbrand\b|social media|communications|"
    r"\bsales\b|account (executive|manager)|business development|\b(bdr|sdr|bde)\b|partnership|customer success|presales|"
    r"finance|financial|accountant|accounting|\baudit|\btax\b|treasury|fp&a|strategy|business analyst|investment|\brisk\b|compliance|\blegal\b|counsel|"
    r"chief of staff|founder'?s office|operations|supply chain|logistics|procurement|customer support|customer service|"
    r"\bhr\b|human resources|people (partner|operations)|recruit|talent acquisition|product owner|program manager|\bux\b|user research",
    re.I,
)


def wanted_title(title: str) -> bool:
    """Every role we can name a family for: tech, business, and fields like healthcare, education,
    law, engineering trades, retail and hospitality, media. Titles no rule recognises are left out."""
    t = title or ""
    return bool(TECH.search(t) or BUSINESS.search(t)) or tags.family(t) != "Other"


# The published feed is capped so its files stay well under GitHub's 100 MB file limit as sources grow.
# India and remote roles are kept first; the rest of the world fills what's left, newest first.
FEED_MAX = int(os.environ.get("CAREEROS_FEED_MAX", "120000") or 120000)


def cap_feed(records: list[dict], limit: int | None = None) -> tuple[list[dict], int]:
    limit = FEED_MAX if limit is None else limit
    if len(records) <= limit:
        return records, 0
    first = [r for r in records if r.get("geo") in ("south", "india") or r.get("workMode") == "remote"]
    rest = [r for r in records if not (r.get("geo") in ("south", "india") or r.get("workMode") == "remote")]
    keep = (first + rest)[:limit]
    keep.sort(key=lambda r: -_ts(r.get("postedAt")))
    return keep, len(records) - len(keep)


def _ts(s: str | None) -> float:
    try:
        dt = datetime.fromisoformat(str(s or "").replace("Z", "+00:00"))
        return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).timestamp()
    except (ValueError, TypeError, OverflowError):
        return 0.0


# CAREEROS_SCAN_ONSITE=world keeps on-site and hybrid roles in every country, for people searching
# outside India. Without it the feed keeps India plus remote roles, as it always has.
ONSITE_WORLD = os.environ.get("CAREEROS_SCAN_ONSITE", "").strip().lower() == "world"


def relevant_location(job: Job) -> bool:
    where = geo.classify(job.location)
    if ONSITE_WORLD and (job.location or "").strip():
        return True
    return where["india"] or job.work_mode == "remote" or bool(re.search(r"remote|anywhere|worldwide|apac|asia", job.location or "", re.I))


def loc_class(job: Job, f: dict) -> tuple[str, str]:
    """Where a role can be done from, independent of anyone's preferences.

    remote-worldwide | remote-open (open to India or APAC) | remote-india |
    remote-unclear | remote-excluded | south | india | abroad | unknown,
    with the text that decided it. Personal filters map these to keep/skip."""
    where = geo.classify(job.location)
    if job.work_mode == "remote":
        t = extract.remote_scope(job.title or "", "")
        if t.india_eligible is False:
            return "remote-excluded", job.title
        if t.scope == "india":
            return "remote-india", job.title
        if f.get("scope") == "worldwide":
            return "remote-worldwide", f.get("scopeQuote") or job.location
        if where["india"] or f.get("scope") == "india":
            return "remote-india", f.get("scopeQuote") or job.location
        if f.get("scopeEligible") is True:
            return "remote-open", f.get("scopeQuote") or job.location
        if f.get("scopeEligible") is False:
            return "remote-excluded", f.get("scopeQuote") or job.location
        return "remote-unclear", job.location
    if where["south"]:
        return "south", job.location
    if where["india"]:
        return "india", job.location
    if where["abroad"]:
        return "abroad", job.location
    return "unknown", job.location


def days_open(posted_at, first_seen: str, today) -> int | None:
    """Days since the listing went up: the earlier of the posting's own date and the day the scan first
    saw it. A posting date more than POSTED_TRUST_DAYS old is not trusted (evergreen listings and boards
    that keep a requisition's original date), so the first-seen date decides. None when neither is known."""
    days = []
    for i, raw in enumerate((str(posted_at or "")[:10], first_seen or "")):
        try:
            d = (today - datetime.strptime(raw, "%Y-%m-%d").date()).days
        except ValueError:
            continue
        if i == 0 and d > POSTED_TRUST_DAYS:
            continue
        days.append(d)
    return max(0, max(days)) if days else None


POSTED_TRUST_DAYS = 120


def to_feed(job: Job, company: dict, via: str = "careers") -> dict:
    url = canonical_url(job.url)
    f = extract.facts(job.description, str(job.raw.get("experience_header", "")), job.location, job.salary_text)
    f["senior"] = extract.title_seniority(job.title) == "senior"
    ty = extract.title_years(job.title)
    if ty is not None and (f.get("expMin") is None or ty > f["expMin"]):
        f["expMin"], f["expQuote"] = ty, job.title  # the title's own figure, when the text gave none or less
    f["loc"], f["locQuote"] = loc_class(job, f)
    band = paydata.band(job.company)
    if band:
        f["payBand"] = band  # public entry-level pay for this company; an estimate, used only when the posting states none
    summary = re.sub(r"\s+", " ", job.description or "").strip()[:1500]
    text = re.sub(r"\n{3,}", "\n\n", (job.description or "").strip())[:20000]
    where = geo.classify(job.location)
    return {
        "id": job_id(job.company, job.title)[:70] + "-" + hashlib.sha1(url.encode()).hexdigest()[:6],
        "company": company_names.display(job.company), "title": job.title, "url": url, "source": job.source,
        "location": job.location, "workMode": job.work_mode, "postedAt": job.posted_at,
        "salary": job.salary_text, "experienceHeader": str(job.raw.get("experience_header", "")),
        "category": company.get("category", ""), "hq": company.get("city", ""),
        "geo": "south" if where["south"] else "india" if where["india"] else "abroad" if where["abroad"] else "",
        "facts": f, "summary": summary, "via": via,
        "tags": tags.tag(job.title, text, f),
        "text": text,  # full posting; kept out of india.jsonl.gz, published for the job board
        **({"applyTo": job.raw["apply"]} if job.raw.get("apply") else {}),  # where the post says to apply (HN posts)
    }


def greenhouse_pay(job: Job, token: str, cache: dict, budget: list[int]) -> None:
    """Fill job.salary_text from the board's pay_transparency ranges (cached per job, once)."""
    jid = job.raw.get("id")
    if job.salary_text or not jid:
        return
    key = f"{token}:{jid}"
    if key not in cache:
        if budget[0] <= 0 or extract.parse_salary(job.description, structured=False):
            return
        budget[0] -= 1
        try:
            cache[key] = greenhouse.pay(token, jid, geo.classify(job.location)["india"])
        except Exception:
            return
    job.salary_text = cache[key]
    cache.setdefault("_seen", set()).add(key)


def scan_board(name: str, entry: dict, detail_budget: list[int], pay_cache: dict | None = None,
               pay_budget: list[int] | None = None) -> tuple[list[dict], str | None]:
    scout = SCOUTS.get(entry.get("ats", ""))
    if not scout:
        return [], f"{name}: unknown ATS {entry.get('ats')}"
    try:
        jobs = scout(entry["token"], name)
    except Exception as e:  # one odd board never stops the scan
        return [], f"{name} ({entry.get('ats')}:{entry.get('token')}): {type(e).__name__}: {e}"[:300]
    out = []
    for j in jobs:
        try:
            j.company = name
            if not wanted_title(j.title) or not relevant_location(j):
                continue
            if j.raw.get("needs_detail") and detail_budget[0] > 0:
                detail_budget[0] -= 1
                try:
                    smartrecruiters.describe(j)
                except Exception:
                    pass
            if entry.get("ats") == "greenhouse" and pay_cache is not None:
                greenhouse_pay(j, entry["token"], pay_cache, pay_budget or [0])
            out.append(to_feed(j, entry))
        except Exception:
            continue  # skip one malformed posting, keep the rest of the board
    return out, None


def scan_aggregator(name: str, cache_dir: Path, now: datetime) -> tuple[list[dict], str | None, bool]:
    """(records, error, fresh). Reuses the last result until the board's polling interval has passed."""
    cache = cache_dir / f"{name}.json.gz"
    prev = None
    if cache.exists():
        try:
            with gzip.open(cache, "rt", encoding="utf-8") as f:
                prev = json.load(f)
        except (OSError, ValueError):
            prev = None
    if prev:
        age_h = (now - datetime.fromisoformat(prev["fetchedAt"].replace("Z", "+00:00"))).total_seconds() / 3600
        if age_h < MIN_HOURS.get(name, 3) - 0.25:
            return prev["records"], None, False
    try:
        jobs = AGGREGATORS[name]()
    except Exception as e:  # keep the last good result when a board is down
        return (prev or {}).get("records", []), f"{name}: {type(e).__name__}: {e}"[:300], False
    recs = []
    for j in jobs:
        try:
            if j.title and j.url and wanted_title(j.title) and relevant_location(j):
                recs.append(to_feed(j, {"category": "remote-board"}, via="board"))
        except Exception:
            continue
    cache_dir.mkdir(parents=True, exist_ok=True)
    with gzip.open(cache, "wt", encoding="utf-8") as f:
        json.dump({"fetchedAt": iso(now), "records": recs}, f, ensure_ascii=False, default=str)
    return recs, None, True


def _load_pay_cache(path: Path) -> dict:
    try:
        with gzip.open(path, "rt", encoding="utf-8") as f:
            return {k: v for k, v in json.load(f).items() if isinstance(v, str)}
    except (OSError, ValueError):
        return {}


def _save_pay_cache(path: Path, cache: dict) -> None:
    seen = cache.pop("_seen", set())
    keep = {k: v for k, v in cache.items() if k in seen}  # only jobs still listed
    with gzip.open(path, "wt", encoding="utf-8") as f:
        json.dump(keep, f)


def _previous(out_dir: Path, names: set[str]) -> list[dict]:
    """Last run's roles for these companies (with their text), so a board the scan ran out of time for
    keeps its roles for one more run instead of vanishing from everyone's matches."""
    want = {company_names.display(n) for n in names}
    try:
        with gzip.open(out_dir / "india.jsonl.gz", "rt", encoding="utf-8") as f:
            old = [r for r in (json.loads(x) for x in f if x.strip()) if r.get("company") in want]
    except (OSError, ValueError):
        return []
    if not old:
        return []
    ids = {r["id"] for r in old}
    texts: dict[str, str] = {}
    try:
        with gzip.open(out_dir / "full.jsonl.gz", "rt", encoding="utf-8") as f:
            for x in f:
                d = json.loads(x)
                if d.get("id") in ids:
                    texts[d["id"]] = d.get("text", "")
    except (OSError, ValueError):
        pass
    return [{**r, "text": texts.get(r["id"], r.get("summary", "")), "facts": dict(r.get("facts") or {})} for r in old]


def run(boards_path: str | Path, out_dir: str | Path, workers: int = 16, detail_cap: int = 400,
        aggregators: bool = True, log=print, pay_cap: int = 200, deadline_min: float = 0) -> dict:
    boards = json.loads(Path(boards_path).read_text())
    companies = boards.get("companies", {})
    mapped = {n: e for n, e in companies.items() if e.get("status") == "mapped"}
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    records: list[dict] = []
    errors: list[str] = []
    budget = [detail_cap]
    # Greenhouse publishes pay ranges only per job; look each up once and remember it.
    pay_path = out_dir / "greenhouse-pay.json.gz"
    pay_cache, pay_budget = _load_pay_cache(pay_path), [pay_cap]
    pay_cache["_seen"] = set()
    log(f"Scanning {len(mapped)} company boards…")
    pool = ThreadPoolExecutor(max_workers=workers)
    futs = {pool.submit(scan_board, n, e, budget, pay_cache, pay_budget): n for n, e in mapped.items()}
    done: set = set()

    def take(fut) -> None:
        done.add(fut)
        try:
            recs, err = fut.result()
        except Exception as e:
            recs, err = [], f"{futs[fut]}: {type(e).__name__}: {e}"[:300]
        records.extend(recs)
        if err:
            errors.append(err)
            companies[futs[fut]]["stale"] = True  # re-discover next time
        else:
            companies[futs[fut]].pop("stale", None)
    late: list[str] = []
    try:
        for fut in as_completed(futs, timeout=deadline_min * 60 if deadline_min else None):
            take(fut)
    except FuturesTimeout:
        for fut in [f for f in futs if f.done() and f not in done]:
            take(fut)
        late = sorted(futs[f] for f in futs if f not in done)
        kept = _previous(out_dir, set(late))
        records.extend(kept)
        errors.append(f"{len(late)} boards not finished within {deadline_min:g} minutes; kept their {len(kept)} roles from the last run")
        log(errors[-1])
    finally:
        pool.shutdown(wait=not late, cancel_futures=True)
    looked_up = pay_cap - pay_budget[0]
    stated = sum(1 for k in pay_cache["_seen"] if pay_cache.get(k))
    _save_pay_cache(pay_path, pay_cache)
    board_counts: dict[str, int] = {}
    if aggregators and AGGREGATORS:
        now = datetime.now(timezone.utc)
        with ThreadPoolExecutor(max_workers=len(AGGREGATORS)) as pool:
            futs = {pool.submit(scan_aggregator, n, out_dir / "boards-cache", now): n for n in AGGREGATORS}
            for fut in as_completed(futs):
                recs, err, _fresh = fut.result()
                board_counts[futs[fut]] = len(recs)
                records += recs
                if err:
                    errors.append(err)
    # Company pages first: when a remote board re-lists a company's role, keep the company's own posting.
    seen, fps, unique = set(), set(), []
    for r in sorted(records, key=lambda r: (r.get("via") == "board", -_ts(r.get("postedAt")))):
        fp = fingerprint(r["company"], r["title"])
        if r["url"] in seen or (r.get("via") == "board" and fp in fps):
            continue
        seen.add(r["url"])
        fps.add(fp)
        unique.append(r)
    unique.sort(key=lambda r: -_ts(r.get("postedAt")))
    unique, trimmed = cap_feed(unique)
    # Remember every listing so a role that is taken down and listed again is noticed, then rate
    # each posting's legitimacy (age, re-listing, closure banner, vague or contradictory asks).
    history = signals.RepostHistory(out_dir / "history.json.gz")
    history.observe(unique)
    for r in unique:
        rp = history.reposts(r["company"], r["title"], r["url"])
        r["facts"]["reposts"] = rp
        r["facts"]["legit"] = signals.legitimacy(r["title"], r.get("text", ""), r["facts"], r.get("postedAt", ""), rp)
    history.prune()
    history.save()
    # How long each listing has been open, and what we know about visa sponsorship (the posting's own
    # words; for UK roles also the Home Office sponsor register and the Skilled Worker salary floors).
    register = sponsors.UkRegister.from_csv(out_dir / "uk-sponsors.csv")
    today = datetime.now(timezone.utc).date()
    for r in unique:
        first = history.first_seen(r["company"], r["title"], r["url"])
        r["facts"]["firstSeen"] = first
        r["facts"]["daysOpen"] = days_open(r.get("postedAt"), first, today)
        v = sponsors.visa_facts(r["company"], r.get("location") or "", r.get("text") or r.get("summary") or "", r.get("salary") or "", register)
        if v:
            r["facts"]["visa"] = v
    with gzip.open(out_dir / "india.jsonl.gz", "wt", encoding="utf-8") as f, \
            gzip.open(out_dir / "full.jsonl.gz", "wt", encoding="utf-8") as full:
        for r in unique:
            text = r.pop("text", "")
            f.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")
            full.write(json.dumps({"id": r["id"], "text": text or r.get("summary", "")}, ensure_ascii=False) + "\n")
    with (out_dir / "unmapped.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["name", "category", "city", "website"])
        for n, e in sorted(companies.items()):
            if e.get("status") != "mapped" and e.get("category") != "deep":  # swept boards with no India roles aren't leads
                w.writerow([n, e.get("category", ""), e.get("city", ""), e.get("website", "")])
    summary = {
        "generatedAt": iso(datetime.now(timezone.utc)),
        "legitimacy": {t: sum(1 for r in unique if r["facts"]["legit"]["tier"] == t) for t in ("high", "caution", "suspicious")},
        "relisted": sum(1 for r in unique if r["facts"]["reposts"].get("count")),
        "visa": {"offers": sum(1 for r in unique if (r["facts"].get("visa") or {}).get("status") == "offers"),
                 "no": sum(1 for r in unique if (r["facts"].get("visa") or {}).get("status") == "no"),
                 "ukRoles": sum(1 for r in unique if (r["facts"].get("visa") or {}).get("uk")),
                 "ukOnRegister": sum(1 for r in unique if ((r["facts"].get("visa") or {}).get("ukRegister") or {}).get("listed")),
                 "registerSize": len(register)},
        "companies": sum(1 for e in companies.values() if e.get("category") != "deep" or e.get("status") == "mapped"),
        "boards": len(mapped), "openings": len(unique),
        "deepSweep": {"checked": sum(1 for e in companies.values() if e.get("category") == "deep" and e.get("checkedAt")),
                      "kept": sum(1 for e in companies.values() if e.get("category") == "deep" and e.get("status") == "mapped")},
        "greenhousePay": {"lookedUp": looked_up, "withPay": stated},
        "remoteBoards": board_counts, "trimmed": trimmed, "byAts": {}, "byGeo": {}, "errors": len(errors), "errorSamples": errors[:20], "lateBoards": len(late),
        "erroredCompanies": sorted(n for n, e in companies.items() if e.get("stale")),
    }
    for r in unique:
        summary["byAts"][r["source"]] = summary["byAts"].get(r["source"], 0) + 1
        summary["byGeo"][r["geo"] or "remote/unknown"] = summary["byGeo"].get(r["geo"] or "remote/unknown", 0) + 1
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    Path(boards_path).write_text(json.dumps(boards, indent=1, ensure_ascii=False), encoding="utf-8")
    log(f"Feed: {len(unique)} open roles ({trimmed} older ones left out to keep the files small) from {len(mapped)} company boards "
        f"and {len(board_counts)} remote job boards ({len(errors)} errors).")
    for e in errors[:40]:
        log(f"  ! {e}")
    return summary
