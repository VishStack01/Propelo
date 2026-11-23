"""Find the job boards of employers with a record of sponsoring visas.

The government lists (see sponsors.py and registers.py) name who can or does sponsor: about 120,000 licensed
UK sponsors, the Dutch recognised sponsors, and the employers behind US, Canadian and Irish work visas. Most of
those employers' roles are not in the feed, because nobody ever listed their job board. This module turns the
lists into candidates for `propelo discover`, which tries each employer's likely board address on the public
hiring systems and keeps a board only when it is that employer's and lists roles in that country.

    propelo sponsor-candidates --feed feed --boards feed/boards.json --out feed/sponsor-companies.csv

Public data only: organisation names from government publications. No request is made here.
"""

from __future__ import annotations

import csv
import re
from itertools import zip_longest
from pathlib import Path

from .sponsors import CountRegister, NlRegister, Register, UkRegister, name_key

FIELDS = ["name", "category", "city", "website", "slugs", "ats", "token", "source", "country"]
# (country, file next to the feed, loader, how many to take: the lists with counts are sorted biggest first,
# and past these numbers they are mostly employers with one visa and no careers page on a hiring system)
SOURCES = (
    ("IE", "ie-sponsors.csv", CountRegister, 6000),
    ("NL", "nl-sponsors.csv", NlRegister, 0),
    ("US", "us-sponsors.csv", CountRegister, 8000),
    ("CA", "ca-sponsors.csv", CountRegister, 1500),
    ("GB", "uk-sponsors.csv", UkRegister, 0),
)
PER_RUN = 150        # employers tried per discover run: up to six quick requests each, on three hiring systems
RETRY_DAYS = 120     # an employer with no board found is looked at again after this long

# Employers that are licensed sponsors but do not post on the hiring systems we read: asking would be wasted requests.
UNLIKELY = re.compile(
    r"\b(restaurant|take ?away|kebab|pizza|tandoori|curry|grill|cafe|café|bakery|catering|butchers?|"
    r"care ?homes?|nursing ?homes?|home ?care|homecare|domiciliary|residential care|care services|dental|dentist|pharmacy|"
    r"surgery|medical centre|medical practice|veterinary|opticians?|"
    r"church|mosque|masjid|temple|gurdwara|synagogue|parish|diocese|ministries|mission|"
    r"primary school|high school|academy trust|nursery|pre-?school|college of|"
    r"football club|cricket club|rugby|golf club|sports club|f\.?c\.?|"
    r"hotel|guest ?house|salon|barber|beauty|nails|car wash|garage|taxi|minicabs?|newsagents?|off licen[cs]e|"
    r"farm|farms|poultry|meats?|abattoir|fishing|orchards?|produce|greenhouses?|fruits?|vineyards?|landscaping|"
    r"trucking|haulage|drywall|roofing|scaffolding|plumbing|carpentry|cleaning|builders?|"
    r"foods?|food (?:and|&) wine|vape|supermarket|convenience|cash (?:and|&) carry|news|"
    r"t/as?|trading as)\b|^\d", re.I)
# In the UK list of a hundred thousand names, the ones most likely to post on a hiring system go first.
LIKELY = re.compile(
    r"\b(tech|technolog|software|digital|data|systems?|labs?|cloud|cyber|analytics|ai|robotics|games?|studios?|media|"
    r"consult|capital|bank|financ|insur|invest|payments?|fintech|trading|partners|advis|"
    r"pharma|bio|therapeutics|medical devices?|health|diagnostics|"
    r"engineering|energy|aerospace|automotive|semiconductor|electronics|telecom|networks?|"
    r"university|research|institute|solutions|global|group|international|plc)", re.I)
_LEGAL_TAIL = re.compile(
    r"[\s,]+(?:ltd|limited|plc|llp|llc|l\.l\.c\.|inc|inc\.|incorporated|corp|corp\.|corporation|co\.|company|"
    r"unlimited company|uc|dac|clg|b\.?v\.?|n\.?v\.?|gmbh|pty|lp|l\.p\.|pc|p\.c\.)\.?$", re.I)


def pretty(name: str) -> str:
    """A register's legal name as people write it: "MONZO BANK LIMITED" -> "Monzo Bank", "Google LLC" -> "Google"."""
    s = re.sub(r"\s+", " ", (name or "").strip())
    for _ in range(3):
        s = _LEGAL_TAIL.sub("", s).strip(" ,.&")
    if s.isupper() and len(s) > 4:
        def word(w: str) -> str:   # initials stay as they are: "IBM", "UK", "HSBC", "KPMG"
            short = len(w) <= 3 and w.isalpha() and w not in ("THE", "AND", "FOR", "OF")
            return w if short or (w.isalpha() and len(w) <= 5 and not re.search(r"[AEIOUY]", w)) else w.capitalize()
        s = " ".join(word(w) for w in s.split(" "))
        s = re.sub(r"\b(And|Of|For|The)\b", lambda m: m.group(1).lower(), s)
        s = s[:1].upper() + s[1:]
    return s


def slugs_for(name: str, key: str | None = None) -> list[str]:
    """Likely board addresses for an employer, most specific first. "Monzo Bank Limited" -> monzobank, monzo.
    The first word alone is tried too, since that is what most boards are called; discover accepts such a board
    only when the board's own name leads back to this register entry. `key` is the register's own cleaned name
    when it has one (the Dutch register also drops "B.V.")."""
    words = (key if key is not None else name_key(name)).split()
    if not words:
        return []
    out = ["".join(words)]
    if len(words) > 1 and len(words[0]) >= 4:
        out.append(words[0])
    return [s for i, s in enumerate(out) if 3 <= len(s) <= 40 and s not in out[:i]][:2]


def load(feed_dir: str | Path) -> dict[str, Register]:
    """The registers found next to the feed, by country code. A missing file is an empty register."""
    feed_dir = Path(feed_dir)
    return {cc: cls.from_csv(feed_dir / fname) for cc, fname, cls, _ in SOURCES}


def candidates(books: dict[str, Register], cache: dict) -> list[dict]:
    """Company-list rows for discover: register employers not already covered by a mapped board, the countries
    taken in turn so every run tries some from each."""
    companies = cache.get("companies", {})
    mapped = [(n, e) for n, e in companies.items() if e.get("status") == "mapped"]
    per_country: list[list[dict]] = []
    seen_names = set(companies)
    for cc, _, _, limit in SOURCES:
        reg = books.get(cc)
        if not reg or not len(reg):
            continue
        covered = set()
        for n, e in mapped:           # an employer whose board is already read needs no second one
            for label in (n, e.get("boardName") or ""):
                m = reg.match(label) if label else None
                if m:
                    covered.add(reg.key(m["name"]))
        entries = list(reg.by_key.items())
        if limit:
            entries = sorted(entries, key=lambda kv: -int(kv[1].get("n") or 0))[:limit]
        rows = []
        for key, e in entries:
            if key in covered or UNLIKELY.search(e["name"]):
                continue
            name, slugs = pretty(e["name"]), slugs_for(e["name"], key)
            if not slugs or not name or reg.key(name) != key:
                continue
            if name in seen_names and (companies.get(name) or {}).get("category") != "sponsor":
                continue              # the same name is already on another list
            seen_names.add(name)
            rows.append({"name": name, "category": "sponsor", "city": "", "website": "", "slugs": " ".join(slugs), "ats": "", "token": "",
                         "source": f"sponsor register ({cc})", "country": cc})
        if not limit:                 # no counts to sort by: likelier names first
            rows.sort(key=lambda r: 0 if LIKELY.search(r["name"]) else 1)
        per_country.append(rows)
    return [r for group in zip_longest(*per_country) for r in group if r]


def write(rows: list[dict], path: str | Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in FIELDS})


def same_employer(books: dict[str, Register], country: str, candidate: str, board_name: str) -> bool:
    """Does the board's own name lead to this register entry, by the same rule that later labels its roles?
    "Monzo" -> "Monzo Bank" when that is the only entry starting so; "Apex" -> nobody, there are dozens."""
    reg = books.get(country)
    if not reg or not board_name:
        return False
    m = reg.match(board_name)
    return bool(m) and reg.key(m["name"]) == reg.key(candidate)


def stats(cache: dict) -> dict:
    rows = [e for e in cache.get("companies", {}).values() if e.get("category") == "sponsor"]
    return {"checked": sum(1 for e in rows if e.get("checkedAt")), "kept": sum(1 for e in rows if e.get("status") == "mapped")}
