"""Pinpoint public postings: https://{token}.pinpointhq.com/postings.json

One keyless JSON document per employer with every open posting: {"data": [{id, title, url, location {name, city,
province}, workplace_type, employment_type, first_published_at, description, key_responsibilities, ...}]}. Pay is
shown only when the employer made it visible (compensation_visible). Many UK employers, graduate schemes among them,
recruit on Pinpoint. Field names follow the ats-scrapers project (MIT, github.com/kalil0321/ats-scrapers).
"""

from __future__ import annotations

from .. import extract
from ..models import Job
from ..textutil import html_to_text
from .http import get_json

API = "https://{token}.pinpointhq.com/postings.json"
_SECTIONS = (("key_responsibilities", "key_responsibilities_header"), ("skills_knowledge_expertise", "skills_knowledge_expertise_header"),
             ("benefits", "benefits_header"))
_SYM = {"GBP": "£", "USD": "$", "EUR": "€", "INR": "₹"}
_PER = {"yearly": "/year", "monthly": "/month", "weekly": "/week", "daily": "/day", "hourly": "/hour"}
_MODE = {"remote": "remote", "hybrid": "hybrid", "onsite": "onsite", "on_site": "onsite", "office": "onsite"}


def _location(loc) -> str:
    if not isinstance(loc, dict):
        return ""
    if str(loc.get("name") or "").strip():
        return str(loc["name"]).strip()
    return ", ".join(str(loc[k]).strip() for k in ("city", "province", "country") if str(loc.get(k) or "").strip())


def _pay(item: dict) -> str:
    if not item.get("compensation_visible"):
        return ""
    lo, hi = item.get("compensation_minimum"), item.get("compensation_maximum")
    if not lo and not hi:
        return ""
    cur = item.get("compensation_currency") or ""
    sym = _SYM.get(cur, cur + " " if cur else "")
    per = _PER.get(str(item.get("compensation_frequency") or "").lower(), "")
    amount = f"{sym}{int(float(lo)):,} - {sym}{int(float(hi)):,}" if lo and hi else f"{sym}{int(float(lo or hi)):,}"
    return amount + per


def normalize(item: dict, company: str) -> Job:
    parts = [item.get("description") or ""]
    for body, head in _SECTIONS:
        if str(item.get(body) or "").strip():
            parts.append(f"<h3>{item.get(head) or ''}</h3>{item[body]}")
    text = html_to_text("\n".join(parts))
    location = _location(item.get("location"))
    kind = str(item.get("employment_type") or "").replace("_", " ")
    if kind and kind.lower() not in text.lower():
        text = f"Employment type: {kind}\n{text}"
    return Job(
        company=company,
        title=(item.get("title") or "").strip(),
        url=item.get("url") or "",
        source="Pinpoint",
        location=location,
        work_mode=extract.work_mode(structured=_MODE.get(str(item.get("workplace_type") or "").lower(), ""), location=location, text=text),
        description=text,
        posted_at=item.get("first_published_at") or "",
        apply_by=str(item.get("deadline_at") or "")[:10],
        salary_text=_pay(item),
        req_id=str(item.get("reference") or item.get("id") or ""),
    )


def fetch(token: str, company: str | None = None) -> list[Job]:
    data = get_json(API.format(token=token))
    items = data.get("data") if isinstance(data, dict) else None
    return [normalize(j, company or token) for j in items or [] if isinstance(j, dict) and j.get("title") and j.get("url")]
