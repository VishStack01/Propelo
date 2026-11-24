"""Teamtailor career sites: the public RSS feed at https://{token}.teamtailor.com/jobs.rss

Each <item> has title, link, pubDate, guid, an HTML description, <remoteStatus> (fully, hybrid, temporary or none)
and Teamtailor's own <tt:locations>/<tt:location> with city and country, plus <tt:department>. A page holds 100
items; larger employers are read with ?offset=100, 200, ... A site on the employer's own domain has the same feed:
the token is then the address, e.g. "https://careers.example.com". Teamtailor is common with employers in the
Netherlands, Ireland and the UK. Format as in the ats-scrapers project (MIT, github.com/kalil0321/ats-scrapers).
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

from .. import extract
from ..models import Job, iso
from ..textutil import html_to_text
from .http import get_text

TT = {"tt": "https://teamtailor.com/locations"}
PAGE = 100
MAX_PAGES = 20
_MODE = {"fully": "remote", "hybrid": "hybrid", "none": "onsite"}


def feed_url(token: str) -> str:
    token = (token or "").strip().rstrip("/")
    if token.startswith(("https://", "http://")):
        return token + "/jobs.rss"
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,62}", token, re.I):
        raise ValueError(f"Teamtailor token must be a subdomain or an https address, got {token!r}")
    return f"https://{token}.teamtailor.com/jobs.rss"


def _date(s: str) -> str:
    try:
        return iso(parsedate_to_datetime(s.strip()))
    except (TypeError, ValueError, IndexError):
        return ""


def _location(item: ET.Element) -> str:
    out = []
    for loc in item.findall("tt:locations/tt:location", TT):
        parts = [(loc.findtext(f"tt:{k}", namespaces=TT) or "").strip() for k in ("city", "country")]
        label = ", ".join(p for p in parts if p) or (loc.findtext("tt:name", namespaces=TT) or "").strip()
        if label and label not in out:
            out.append(label)
    return "; ".join(out)


def normalize(item: ET.Element, company: str) -> Job:
    link = (item.findtext("link") or "").strip()
    text = html_to_text(item.findtext("description") or "")
    location = _location(item)
    m = re.search(r"/jobs/(\d+)", link)
    return Job(
        company=company,
        title=(item.findtext("title") or "").strip(),
        url=link,
        source="Teamtailor",
        location=location,
        work_mode=extract.work_mode(structured=_MODE.get((item.findtext("remoteStatus") or "").strip().lower(), ""), location=location, text=text),
        description=text,
        posted_at=_date(item.findtext("pubDate") or ""),
        req_id=m.group(1) if m else (item.findtext("guid") or "").strip(),
    )


def fetch(token: str, company: str | None = None) -> list[Job]:
    url, jobs, seen = feed_url(token), [], set()
    name = company or re.sub(r"^https?://", "", token).split("/")[0]
    for page in range(MAX_PAGES):
        root = ET.fromstring(get_text(url + (f"?offset={page * PAGE}" if page else "")))
        items = root.findall("./channel/item")
        added = 0
        for it in items:
            job = normalize(it, name)
            if job.title and job.url and job.url not in seen:
                seen.add(job.url)
                jobs.append(job)
                added += 1
        if len(items) < PAGE or not added:
            break
    return jobs
