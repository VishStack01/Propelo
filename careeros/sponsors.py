"""Visa sponsorship: what the posting says, and (UK) whether the employer can sponsor at all.

Three independent facts, each with its evidence:

- `sponsorship(text)`: the posting's own words. "offers" when it says it sponsors visas, "no" when it
  says it can't, "" when it says nothing (shown as "unclear", never guessed).
- `UkRegister`: the Home Office register of licensed sponsors (Skilled Worker route), a public CSV
  published daily at https://www.gov.uk/government/publications/register-of-licensed-sponsors-workers.
  An employer missing from it cannot sponsor a Skilled Worker visa today, whatever the posting says.
- `uk_salary_line(text)`: an annual salary in pounds stated in the posting, against the Skilled
  Worker floors (general and new entrant). The floors only; the occupation's own going rate also
  applies and is not checked here.
"""

from __future__ import annotations

import csv
import io
import re
import urllib.request
from pathlib import Path

from .textutil import quote_around

# ---------------------------------------------------------------- what the posting says

_NO = re.compile(
    r"\b(?:not|no|unable to|cannot|can't|won't|will not|do not|does not|don't|doesn't|are not able to|is not able to)\s+"
    r"(?:currently\s+|be able to\s+)?(?:provide|offer|support|sponsor|consider)?\s*(?:candidates who require\s+)?(?:any\s+)?"
    r"(?:visa|work permit|employment|immigration|h-?1b)?\s*sponsor(?:ship|ing)?\b"
    r"|\bwithout (?:the need for |requiring |needing )?(?:current or future |now or in the future )?(?:visa |employer |immigration )?sponsorship\b"
    r"|\bsponsorship (?:is |will )?not (?:be )?(?:available|offered|provided|possible)\b"
    r"|\bno (?:visa |immigration )?sponsorship\b|\bunable to sponsor\b",
    re.I)

_OFFERS = re.compile(
    r"\b(?:visa|work permit|immigration|skilled worker(?: visa)?|h-?1b|tier 2) sponsorship (?:is |can be |will be )?"
    r"(?:available|offered|provided|possible|supported)\b"
    r"|\bwe (?:can|will|are able to|do|happily|offer to|are happy to|are open to) (?:provide |offer |support )?(?:visa |work permit |skilled worker )?sponsor(?:ship)?\b"
    r"|\b(?:we )?(?:offer|provide|support) (?:visa|work permit|skilled worker visa|h-?1b|immigration) sponsorship\b"
    r"|\bsponsorship (?:is )?available\b|\bopen to sponsoring\b|\bvisa sponsorship (?:and|&) relocation\b"
    r"|\brelocation (?:and|&) visa (?:sponsorship|support)\b|\bwill sponsor (?:a |the |your )?(?:visa|work permit)\b",
    re.I)


def sponsorship(text: str) -> dict:
    """{"status": "offers"|"no", "quote"} from the posting's own words, or {} when it says nothing.
    A clear "no" wins over a hopeful line elsewhere: being wrong in that direction costs an applicant
    a wasted application, being wrong the other way costs them a visa."""
    text = text or ""
    m = _NO.search(text)
    if m:
        return {"status": "no", "quote": quote_around(text, *m.span())}
    m = _OFFERS.search(text)
    if m:
        return {"status": "offers", "quote": quote_around(text, *m.span())}
    return {}


# ---------------------------------------------------------------- UK register of licensed sponsors

REGISTER_PAGE = "https://www.gov.uk/government/publications/register-of-licensed-sponsors-workers"
_CSV_LINK = re.compile(r'href="(https://assets\.publishing\.service\.gov\.uk/[^"]+\.csv)"', re.I)

_SUFFIX = re.compile(
    r"\b(?:ltd|limited|plc|llp|llc|inc|incorporated|corp|corporation|co|company|group|holdings?|uk|u\.k\.|"
    r"gb|international|intl|the|and|services|technologies|technology|t/a|trading as)\b", re.I)


def name_key(name: str) -> str:
    """Company name without legal suffixes, punctuation or 'the', for matching a careers-page name
    ("Monzo") to a register name ("Monzo Bank Ltd" stays distinct from "Monzo"; see `match`)."""
    s = re.sub(r"\([^)]*\)", " ", (name or "").lower()).replace("&", " and ")
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    s = _SUFFIX.sub(" ", s)
    return re.sub(r"\s+", " ", s).strip()


class UkRegister:
    """Skilled Worker sponsors from the Home Office CSV, keyed by `name_key`."""

    def __init__(self, rows: list[dict] | None = None):
        self.by_key: dict[str, dict] = {}
        self.by_first: dict[str, list[str]] = {}
        for r in rows or []:
            route = (r.get("Route") or "").strip()
            if route and "skilled worker" not in route.lower():
                continue
            name = (r.get("Organisation Name") or "").strip()
            k = name_key(name)
            if not k:
                continue
            self.by_key.setdefault(k, {"name": name, "town": (r.get("Town/City") or "").strip(),
                                       "rating": (r.get("Type & Rating") or "").strip()})
            self.by_first.setdefault(k.split()[0], []).append(k)

    def __len__(self) -> int:
        return len(self.by_key)

    @classmethod
    def from_csv(cls, path: str | Path) -> "UkRegister":
        p = Path(path)
        if not p.exists():
            return cls()
        text = p.read_bytes().decode("utf-8-sig", errors="replace")
        return cls(list(csv.DictReader(io.StringIO(text))))

    def match(self, company: str) -> dict | None:
        """The register entry for an employer, or None. Exact match on the cleaned name first; then a
        register name that is the company's name plus extra words ("Wise" -> "Wise Payments"), only when
        exactly one register entry starts that way, so a common word never matches a stranger."""
        k = name_key(company)
        if not k:
            return None
        if k in self.by_key:
            return {**self.by_key[k], "match": "exact"}
        if len(k) < 4:
            return None
        starts = [x for x in self.by_first.get(k.split()[0], []) if x.startswith(k + " ")]
        if len(starts) == 1:
            return {**self.by_key[starts[0]], "match": "prefix"}
        return None


def fetch_register(dest: str | Path, timeout: int = 60) -> int:
    """Download today's register CSV to `dest`. Returns the number of Skilled Worker sponsors, or
    raises OSError. Run daily; the file is public data (organisation names and towns)."""
    req = urllib.request.Request(REGISTER_PAGE, headers={"User-Agent": "careeros"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        page = r.read().decode("utf-8", errors="replace")
    m = _CSV_LINK.search(page)
    if not m:
        raise OSError("No CSV link on the register page")
    req = urllib.request.Request(m.group(1), headers={"User-Agent": "careeros"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read(80 * 1024 * 1024)
    reg = UkRegister(list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig", errors="replace")))))
    if len(reg) < 1000:
        raise OSError(f"The register looks wrong ({len(reg)} sponsors); keeping the old file")
    Path(dest).write_bytes(raw)
    return len(reg)


# ---------------------------------------------------------------- UK salary floors

# Skilled Worker minimums from 22 July 2025 (GOV.UK, "Skilled Worker visa: your job"). Check them
# yearly: they change with the immigration rules.
UK_GENERAL_FLOOR = 41_700
UK_NEW_ENTRANT_FLOOR = 33_400

_GBP = re.compile(r"£\s?(\d{2,3})(?:[,.](\d{3})|\s?(k)\b)(?:\s?(?:-|–|to)\s?£?\s?(\d{2,3})(?:[,.](\d{3})|\s?(k)\b))?", re.I)
_NOT_ANNUAL = re.compile(r"per (?:hour|day|month|week)|/\s?(?:hr|hour|day|month)|an hour|a day|daily rate|hourly", re.I)


def uk_salary_line(text: str) -> dict:
    """The top of the first annual £ salary in the text against the Skilled Worker floors:
    {"status": "general"|"new-entrant"|"below", "amount", "quote"}, or {} when no annual figure."""
    text = text or ""
    for m in _GBP.finditer(text):
        tail = text[m.end(): m.end() + 30]
        if _NOT_ANNUAL.search(tail):
            continue

        def val(a, b, k):
            return int(a) * 1000 if (k or b is None) else int(a + b)
        low = val(m.group(1), m.group(2), m.group(3))
        high = val(m.group(4), m.group(5), m.group(6)) if m.group(4) else low
        if not 10_000 <= high <= 1_000_000:
            continue
        status = "general" if high >= UK_GENERAL_FLOOR else "new-entrant" if high >= UK_NEW_ENTRANT_FLOOR else "below"
        return {"status": status, "amount": high, "quote": quote_around(text, *m.span())}
    return {}


# ---------------------------------------------------------------- one record

def visa_facts(company: str, location: str, text: str, salary_text: str = "", register: UkRegister | None = None) -> dict:
    """Everything above for one role. UK checks only for roles located in the UK."""
    from . import countries
    out: dict = {}
    sp = sponsorship(text)
    if sp:
        out.update(sp)
    if "GB" in countries.named(location or ""):
        out["uk"] = True
        if register is not None and len(register):
            hit = register.match(company)
            out["ukRegister"] = {"listed": bool(hit), **({"name": hit["name"], "rating": hit["rating"], "match": hit["match"]} if hit else {})}
        line = uk_salary_line(salary_text) or uk_salary_line(text)
        if line:
            out["ukSalary"] = line
    return out


def label(v: dict) -> str:
    """One line a person reads: what we know about sponsorship for this role."""
    if not v:
        return "Sponsorship: not stated"
    parts = []
    if v.get("status") == "offers":
        parts.append("Says it sponsors visas")
    elif v.get("status") == "no":
        parts.append("Says it cannot sponsor")
    else:
        parts.append("Sponsorship not stated")
    reg = v.get("ukRegister")
    if reg is not None:
        parts.append("on the UK sponsor register" if reg.get("listed") else "not on the UK sponsor register")
    sal = v.get("ukSalary")
    if sal:
        parts.append({"general": f"£{sal['amount']:,} meets the Skilled Worker floor",
                      "new-entrant": f"£{sal['amount']:,} meets the new-entrant floor only",
                      "below": f"£{sal['amount']:,} is below the Skilled Worker floors"}[sal["status"]])
    return "; ".join(parts)
