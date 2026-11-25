"""The offer sponsor brief: what hiring this member takes from the employer, for the role's country.

A recruiter who hears "I'll need sponsorship" often stops there, without knowing that a Graduate visa, Stamp 1G,
the Dutch orientation year or OPT needs nothing from them today, or that a switch from a UK Student visa skips the
Immigration Skills Charge. The brief says, for the member's visa (from the Visa-Clock) and the country the role is
in: what the employer does, what it costs and how long it takes, each figure with its official source and the date
it was checked. The member copies it into a note to HR; Propelo never sends it.

The facts live in propelo/data/sponsor_brief.json. The dashboard runs the same code in JavaScript (between the
brief markers in dashboard/app.html, with the JSON copied in by scripts/sync_sponsor_brief.py); tests compare them.
"""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

from . import visaclock

RULES = json.loads((Path(__file__).parent / "data" / "sponsor_brief.json").read_text(encoding="utf-8"))

_US_STATES = ("AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD "
              "TN TX UT VT VA WA WV WI WY DC").split()
_PLACES = [
    ("GB", r"\b(?:United Kingdom|UK|U\.K\.|Great Britain|England|Scotland|Wales|Northern Ireland|London|Manchester|Edinburgh|Glasgow|Birmingham|"
           r"Leeds|Bristol|Cambridge|Oxford|Belfast|Cardiff|Reading|Liverpool|Newcastle|Sheffield|Nottingham)\b"),
    ("IE", r"\b(?:Ireland|Dublin|Cork|Galway|Limerick|Waterford)\b"),
    ("NL", r"\b(?:Netherlands|Nederland|Amsterdam|Rotterdam|Utrecht|Eindhoven|The Hague|Den Haag|Leiden|Delft|Groningen)\b"),
    ("US", r"\b(?:United States|USA|U\.S\.A?\.?|US|New York|San Francisco|Seattle|Boston|Austin|Chicago|Los Angeles|Atlanta|Denver)\b"),
]


def role_country(location: str, job_visa: dict | None = None) -> str:
    """"GB", "IE", "NL", "US" or "" for where a role is: a US state code first ("Cambridge, MA"), then the visa
    facts the scan attached, then country and city names."""
    loc = location or ""
    m = re.search(r",\s*([A-Z]{2})\s*$", loc)
    if m and m.group(1) in _US_STATES:
        return "US"
    v = job_visa if isinstance(job_visa, dict) else {}
    for code, keys in (("GB", ("uk", "ukRegister", "ukSalary")), ("NL", ("nlRegister", "nlSalary")), ("IE", ("ieSalary", "iePermits")), ("US", ("usLca", "opt", "eVerify"))):
        if any(v.get(k) not in (None, "", False) for k in keys):
            return code
    for code, rx in _PLACES:
        if re.search(rx, loc, re.I if code != "US" else 0):
            return code
    return ""


def _until(v: dict, status: str, today: date) -> str:
    key = "optEnd" if status in ("us-opt", "us-stem-opt") else "permitEnd"
    d = visaclock._date(v.get(key))
    return f" until {visaclock.fmt(d)}" if d and d >= today else ""


def brief(v: dict | None, location: str, job_visa: dict | None = None, today: date | None = None) -> dict | None:
    """The brief for a member's visa and a role's location, or None (no visa set, settled, or a country Propelo has
    no brief for). {"id", "country", "headline", "points", "sources", "checked"}."""
    v = v if isinstance(v, dict) else {}
    status = str(v.get("status") or "")
    st = visaclock.BY_ID.get(status)
    if not st or not st["sponsor"]:
        return None
    country = role_country(location, job_visa)
    if not country:
        return None
    b = next((x for x in RULES["briefs"] if status in x["status"] and x["country"] == country), None) if st["country"] == country else None
    b = b or RULES["abroad"].get(country)
    if not b:
        return None
    until = _until(v, status, today or date.today()) if b in RULES["briefs"] else ""
    fill = lambda s: s.replace("{until}", until)  # noqa: E731
    return {"id": b["id"], "country": country, "headline": fill(b["headline"]), "points": [fill(p) for p in b["points"]],
            "sources": [{"title": t, "url": u} for t, u in b["sources"]], "checked": RULES["checked"]}


def note(b: dict, to: str = "", me: str = "", stage: str = "") -> str:
    """The note to HR: a greeting, the points, the sources and the date they were checked. The member sends it."""
    d = visaclock._date(b["checked"])
    head = RULES["intro"].replace("{name}", (to or "").split(" ")[0] or "there").replace("{context}", RULES["context"].get(stage, RULES["context"]["applied"]))
    body = "\n".join("- " + p for p in b["points"])
    src = "Sources:\n" + "\n".join(f"- {s['title']}: {s['url']}" for s in b["sources"])
    tail = RULES["outro"].replace("{checked}", visaclock.fmt(d) if d else b["checked"]).replace("{me}", (me or "").split(" ")[0])
    return f"{head}\n\n{body}\n\n{src}\n\n{tail}".rstrip()
