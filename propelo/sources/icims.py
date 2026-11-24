"""iCIMS career portals: https://careers-{token}.icims.com/jobs/search?ss=1&pr={page}&in_iframe=1

iCIMS has no public JSON for job seekers, but every portal serves its listing as plain HTML inside an iframe page:
one <li class="iCIMS_JobCardItem"> per role, with the title in <h3> inside an "iCIMS_Anchor" link to
/jobs/{id}/{slug}/job, the place as "Job Locations: US-NY-New York", and the posting time in a title attribute
("5/6/2026 10:23 AM"). Each role's own page carries a schema.org JobPosting with the full description, which is
read for the roles in a job family Propelo matches, early-career titles first. A portal on another host
("uscareers-{name}.icims.com") is given as its https address. Page shapes as documented by the ats-scrapers
project (MIT, github.com/kalil0321/ats-scrapers); the code here is Propelo's own.
"""

from __future__ import annotations

import html
import json
import re
from datetime import datetime, timezone

from .. import extract
from ..models import Job, iso
from ..textutil import html_to_text
from .http import FetchError, get_text

MAX_PAGES = 40
DETAIL_CAP = 40
_CARD = re.compile(r'<li[^>]+class="[^"]*iCIMS_JobCardItem[^"]*"[^>]*>(?P<body>.*?)</li>', re.S | re.I)
_ANCHOR = re.compile(r'<a[^>]+href="(?P<href>https?://[^"]*?/jobs/(?P<id>\d+)/[^"]*?/job[^"]*)"[^>]*class="[^"]*iCIMS_Anchor[^"]*"[^>]*>(?P<inner>.*?)</a>',
                     re.S | re.I)
_TITLE = re.compile(r"<h3[^>]*>(?P<t>.*?)</h3>", re.S | re.I)
_LOC = re.compile(r'<span[^>]+class="[^"]*field-label[^"]*"[^>]*>\s*Job Locations?\s*</span>\s*<span[^>]*>\s*(?P<loc>[^<]*?)\s*</span>', re.S | re.I)
_WHEN = re.compile(r'<span[^>]+title="(?P<d>\d{1,2}/\d{1,2}/\d{4}\s+\d{1,2}:\d{2}\s*(?:AM|PM)?)"', re.I)
_SUMMARY = re.compile(r'<div[^>]+class="[^"]*col-xs-12[^"]*description[^"]*"[^>]*>(?P<d>.*?)</div>', re.S | re.I)
_LD = re.compile(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', re.S | re.I)
_DASH = re.compile(r"^(?P<country>[A-Z]{2,3})-(?P<state>[A-Z0-9 ]{1,40})(?:-(?P<city>[^-].*))?$")
_COUNTRY = {"US": "United States", "USA": "United States", "UK": "United Kingdom", "GB": "United Kingdom", "IE": "Ireland", "NL": "Netherlands",
            "CA": "Canada", "IN": "India", "IND": "India"}
_PASSWORD = 'name="loginToAccessPortalPassword"'


def base(token: str) -> str:
    token = (token or "").strip().rstrip("/")
    if token.startswith(("https://", "http://")):
        return token
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,62}", token, re.I):
        raise ValueError(f"iCIMS token must be a portal name or an https address, got {token!r}")
    return f"https://careers-{token}.icims.com"


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()


def place(raw: str) -> str:
    """'US-NY-New York' -> 'New York, NY, United States'; anything else unchanged."""
    m = _DASH.match(raw.strip())
    if not m:
        return raw.strip()
    country = _COUNTRY.get(m["country"], m["country"])
    return ", ".join(p.strip() for p in (m["city"], m["state"], country) if p and p.strip())


def _when(raw: str) -> str:
    for fmt in ("%m/%d/%Y %I:%M %p", "%m/%d/%Y %H:%M"):
        try:
            return iso(datetime.strptime(raw.strip(), fmt).replace(tzinfo=timezone.utc))
        except ValueError:
            continue
    return ""


def parse_page(text: str, company: str) -> list[Job]:
    jobs, seen = [], set()
    for card in _CARD.finditer(text or ""):
        body = card["body"]
        a = _ANCHOR.search(body)
        t = _TITLE.search(a["inner"]) if a else None
        if not a or not t or a["id"] in seen:
            continue
        seen.add(a["id"])
        loc = _LOC.search(body)
        when = _WHEN.search(body)
        summary = _SUMMARY.search(body)
        location = place(_clean(loc["loc"])) if loc else ""
        description = _clean(summary["d"]) if summary else ""
        jobs.append(Job(company=company, title=_clean(t["t"]), url=html.unescape(a["href"]), source="iCIMS", location=location,
                        work_mode=extract.work_mode(location=location, text=description), description=description,
                        posted_at=_when(when["d"]) if when else "", req_id=a["id"]))
    return jobs


def job_posting(text: str) -> dict | None:
    """The schema.org JobPosting on a role's own page, if there is one."""
    for m in _LD.finditer(text or ""):
        try:
            data = json.loads(m.group(1).strip())
        except json.JSONDecodeError:
            continue
        stack = data if isinstance(data, list) else [data]
        for node in stack:
            if isinstance(node, dict):
                if node.get("@type") == "JobPosting":
                    return node
                stack += [g for g in node.get("@graph") or [] if isinstance(g, dict)]
    return None


def enrich(job: Job, posting: dict) -> None:
    desc = html_to_text(str(posting.get("description") or ""))
    if desc:
        job.description = desc
    kind = str(posting.get("employmentType") or "").replace("_", " ").lower()
    if kind and kind not in job.description.lower():
        job.description = f"Employment type: {kind}\n{job.description}"
    if not job.posted_at and isinstance(posting.get("datePosted"), str):
        job.posted_at = posting["datePosted"]
    if isinstance(posting.get("validThrough"), str):
        job.apply_by = posting["validThrough"][:10]
    if not job.location:
        locs = posting.get("jobLocation") if isinstance(posting.get("jobLocation"), list) else [posting.get("jobLocation")]
        for loc in locs:
            addr = loc.get("address") if isinstance(loc, dict) else None
            if isinstance(addr, dict):
                job.location = ", ".join(str(addr[k]).strip() for k in ("addressLocality", "addressRegion", "addressCountry") if addr.get(k))
                break
    job.work_mode = extract.work_mode(structured="remote" if posting.get("jobLocationType") == "TELECOMMUTE" else "", location=job.location,
                                      text=job.description)


def fetch(token: str, company: str | None = None) -> list[Job]:
    from ..scan import wanted_title
    from .workday import EARLY
    root = base(token)
    name = company or re.sub(r"^(us)?careers-", "", root.split("//", 1)[-1].split(".")[0])
    jobs, seen = [], set()
    for page in range(MAX_PAGES):
        text = get_text(f"{root}/jobs/search?ss=1&pr={page}&in_iframe=1")
        if _PASSWORD in text:
            return []  # the employer closed the portal to the public
        new = [j for j in parse_page(text, name) if j.req_id not in seen]
        if not new:
            break
        seen.update(j.req_id for j in new)
        jobs += new
    picks = sorted((j for j in jobs if wanted_title(j.title)), key=lambda j: 0 if EARLY.search(j.title) else 1)[:DETAIL_CAP]
    for j in picks:
        try:
            posting = job_posting(get_text(j.url, timeout=20, retries=1))
        except FetchError:
            continue
        if posting:
            enrich(j, posting)
    return jobs
