"""Job search APIs that cover whole countries, used when their keys are set.

* Adzuna (https://developer.adzuna.com): one free key covers India, the UK, the US, Canada, Australia,
  New Zealand, Singapore and most of western Europe. Listings link to Adzuna's own page for the job,
  which is what its terms ask for. Results carry a snippet of the description, not the full text.
  Set ADZUNA_APP_ID and ADZUNA_APP_KEY. ADZUNA_COUNTRIES picks countries (India first by default) and
  ADZUNA_PAGES the pages of 50 newest roles per country (India gets twice as many).
* USAJOBS (https://developer.usajobs.gov): US federal government roles. Set USAJOBS_KEY and
  USAJOBS_EMAIL (the email you registered the key with; USAJOBS asks for it in the User-Agent).

Without keys these return nothing, so the scan works the same as before. Both are polled once a day
(see aggregators.MIN_HOURS), well inside their free limits.
"""

from __future__ import annotations

import os
import re
from urllib.parse import urlencode

from .. import countries
from ..models import Job
from ..textutil import html_to_text
from .http import get_json

ADZUNA_ALL = ("in", "us", "gb", "ca", "au", "de", "nl", "fr", "sg", "nz", "ch", "at", "be", "it", "es", "pl", "br", "mx", "za")
ADZUNA_SUPPORTED = {"gb", "us", "at", "au", "be", "br", "ca", "ch", "de", "es", "fr", "in", "it", "mx", "nl", "nz", "pl", "sg", "za"}
CURRENCY = {"in": "INR", "us": "USD", "gb": "GBP", "ca": "CAD", "au": "AUD", "nz": "NZD", "sg": "SGD", "ch": "CHF", "pl": "PLN",
            "br": "BRL", "mx": "MXN", "za": "ZAR"}
SYMBOL = {"INR": "₹", "USD": "$", "GBP": "£", "EUR": "€"}
_REMOTE = re.compile(r"\b(remote|work from home|wfh|home[- ]based|anywhere)\b", re.I)


def _strip(s: str) -> str:
    return re.sub(r"\s+", " ", html_to_text(str(s or ""))).strip()


def _pay(lo, hi, cur: str) -> str:
    try:
        lo, hi = float(lo or 0), float(hi or 0)
    except (TypeError, ValueError):
        return ""
    if not (lo or hi):
        return ""
    sym = SYMBOL.get(cur, cur + " ")
    lo, hi = lo or hi, hi or lo
    return f"{sym}{int(lo):,}" + (f" - {sym}{int(hi):,}" if hi != lo else "") + " /year"


def adzuna_countries() -> list[str]:
    raw = os.environ.get("ADZUNA_COUNTRIES", "")
    want = [c.strip().lower() for c in raw.split(",") if c.strip()] or list(ADZUNA_ALL)
    return [c for c in want if c in ADZUNA_SUPPORTED]


def adzuna(fetch=get_json) -> list[Job]:
    app_id, key = os.environ.get("ADZUNA_APP_ID", "").strip(), os.environ.get("ADZUNA_APP_KEY", "").strip()
    if not (app_id and key):
        return []
    try:
        pages = max(1, min(int(os.environ.get("ADZUNA_PAGES", "4")), 20))
    except ValueError:
        pages = 4
    out: list[Job] = []
    for cc in adzuna_countries():
        cur = CURRENCY.get(cc, "EUR")
        cname = countries.name_of(cc.upper())
        for page in range(1, (pages * 2 if cc == "in" else pages) + 1):
            q = urlencode({"app_id": app_id, "app_key": key, "results_per_page": 50, "sort_by": "date", "max_days_old": 14,
                           "content-type": "application/json"})
            data = fetch(f"https://api.adzuna.com/v1/api/jobs/{cc}/search/{page}?{q}")
            items = (data or {}).get("results") or []
            for it in items:
                title, url = _strip(it.get("title")), str(it.get("redirect_url") or "")
                if not title or not url.startswith("https://"):
                    continue
                where = _strip((it.get("location") or {}).get("display_name"))
                if cname.lower() not in where.lower():
                    where = f"{where}, {cname}" if where else cname
                text = _strip(it.get("description"))
                remote = bool(_REMOTE.search(title + " " + text[:400]))
                out.append(Job(company=_strip((it.get("company") or {}).get("display_name")) or "Company not named", title=title, url=url,
                               source="Adzuna", location=where, work_mode="remote" if remote else "", description=text,
                               posted_at=str(it.get("created") or ""), salary_text=_pay(it.get("salary_min"), it.get("salary_max"), cur),
                               req_id=str(it.get("id") or "")))
            if len(items) < 50:
                break
    return out


def usajobs(fetch=get_json) -> list[Job]:
    key, email = os.environ.get("USAJOBS_KEY", "").strip(), os.environ.get("USAJOBS_EMAIL", "").strip()
    if not (key and email):
        return []
    headers = {"Host": "data.usajobs.gov", "User-Agent": email, "Authorization-Key": key}
    out: list[Job] = []
    for page in range(1, 4):
        data = fetch(f"https://data.usajobs.gov/api/Search?{urlencode({'DatePosted': 14, 'ResultsPerPage': 500, 'Page': page})}", headers=headers)
        items = ((data or {}).get("SearchResult") or {}).get("SearchResultItems") or []
        for it in items:
            d = it.get("MatchedObjectDescriptor") or {}
            url = str(d.get("PositionURI") or "")
            if not d.get("PositionTitle") or not url.startswith("https://"):
                continue
            pay = (d.get("PositionRemuneration") or [{}])[0] or {}
            per = {"PA": "year", "PH": "hour"}.get(str(pay.get("RateIntervalCode") or ""), "year")
            salary = _pay(pay.get("MinimumRange"), pay.get("MaximumRange"), "USD").replace("/year", "/" + per) if pay else ""
            where = _strip(d.get("PositionLocationDisplay"))
            summary = _strip(((d.get("UserArea") or {}).get("Details") or {}).get("JobSummary"))
            remote = bool(_REMOTE.search(where + " " + summary[:300]))
            out.append(Job(company=_strip(d.get("OrganizationName")) or "US federal government", title=_strip(d.get("PositionTitle")), url=url,
                           source="USAJOBS", location=(where + ", United States") if where and "united states" not in where.lower() else (where or "United States"),
                           work_mode="remote" if remote else "", description=summary, posted_at=str(d.get("PublicationStartDate") or ""),
                           salary_text=salary, req_id=str(d.get("PositionID") or "")))
        if len(items) < 500:
            break
    return out
