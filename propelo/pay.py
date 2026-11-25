"""Pay as the posting states it, in the posting's own currency.

The scan keeps pay in lakhs a year (`facts.salaryHigh`) for the gates. The public job board and its feeds show
pay the way the posting wrote it: "$120,000–$150,000 a year", "£45,000 a year", "€4,000–€5,000 a month",
"12–18 LPA" for a role in India. Nothing is converted between currencies for display.
"""

from __future__ import annotations

import re

_SYM = {"$": "USD", "us$": "USD", "usd": "USD", "£": "GBP", "gbp": "GBP", "€": "EUR", "eur": "EUR", "euro": "EUR", "euros": "EUR",
        "₹": "INR", "rs": "INR", "rs.": "INR", "inr": "INR"}
SIGN = {"USD": "$", "GBP": "£", "EUR": "€", "INR": "₹"}
_CUR = r"(us\$|\$|£|€|₹|rs\.?|usd|gbp|eur|euros?|inr)"
_NUM = r"(\d{1,2}(?:,\d{2})+,\d{3}|\d{1,3}(?:[,.\s]\d{3})+(?:[.,]\d{1,2})?|\d+(?:[.,]\d{1,2})?)"
_K = r"(\s?[kK](?![a-zA-Z]))?"
_RANGE = re.compile(_CUR + r"\s?" + _NUM + _K + r"(?:\s*(?:-|–|—|to)\s*" + _CUR + r"?\s?" + _NUM + _K + r")?", re.I)
_LPA = re.compile(r"(\d+(?:\.\d+)?)\s*(?:(?:-|–|to)\s*(\d+(?:\.\d+)?)\s*)?(?:lpa|lakhs?(?: per annum)?|l\.p\.a\.?)\b", re.I)
_HOUR = re.compile(r"^\W{0,3}(?:per|an?|/)\s?(?:hour|hr|uur)\b|^\W{0,3}hourly\b|^\s*p\.?h\.?\b", re.I)
_MONTH = re.compile(r"^\W{0,3}(?:per|a|/)\s?(?:month|mo|maand)\b|^\W{0,3}monthly\b|^\s*p\.?m\.?\b|^\W{0,3}bruto per maand", re.I)
# The most a role pays, a year, for the "well paid" list and the pay filter. One table, shown on the board.
TOP = {"USD": 100_000, "GBP": 50_000, "EUR": 60_000, "INR": 2_000_000}
GOOD = {"USD": 60_000, "GBP": 30_000, "EUR": 40_000, "INR": 1_000_000}
# Rough rates, used only to order roles by pay across currencies. Never shown.
_ORDER = {"USD": 1.0, "GBP": 1.27, "EUR": 1.08, "INR": 1 / 88}
_PLAUSIBLE = {"year": (5_000, 2_000_000), "month": (400, 60_000), "hour": (5, 500)}


def _cur(s: str) -> str:
    s = (s or "").lower().rstrip(".")
    return "INR" if s.startswith("rs") else _SYM.get(s, "")


def _amount(num: str, k: bool) -> float | None:
    s = num.replace(" ", "")
    if re.fullmatch(r"\d{1,2}(?:,\d{2})+,\d{3}", s):  # Indian grouping: 12,00,000
        v = float(s.replace(",", ""))
    elif m := re.fullmatch(r"(\d{1,3}(?:[,.]\d{3})+)(?:[.,](\d{1,2}))?", s):  # 45,000 / 45.000 / 45,000.50
        v = float(re.sub(r"[,.]", "", m.group(1)) + ("." + m.group(2) if m.group(2) else ""))
    elif m := re.fullmatch(r"(\d+)(?:[.,](\d{1,2}))?", s):
        v = float(m.group(1) + ("." + m.group(2) if m.group(2) else ""))
    else:
        return None
    return v * 1000 if k else v


def _short(num: str) -> bool:
    return len(re.sub(r"[^\d]", "", num.split(".")[0])) <= 3


def native(text: str) -> dict | None:
    """The first pay figure in `text`: {"cur", "lo", "hi", "per"} where per is year, month or hour."""
    if not text:
        return None
    m = _LPA.search(text)
    r = _RANGE.search(text)
    if m and (not r or m.start() <= r.start()):
        lo = float(m.group(1)) * 1e5
        hi = float(m.group(2)) * 1e5 if m.group(2) else lo
        return {"cur": "INR", "lo": min(lo, hi), "hi": max(lo, hi), "per": "year", "lpa": True}
    if not r:
        return None
    cur = _cur(r.group(1))
    if r.group(4) and _cur(r.group(4)) != cur:
        return None  # "$100 to €200": not one range
    k_lo, k_hi = bool(r.group(3)), bool(r.group(6))
    lo = _amount(r.group(2), k_lo or (k_hi and bool(r.group(5)) and _short(r.group(2))))
    hi = _amount(r.group(5), k_hi or (k_lo and _short(r.group(5)))) if r.group(5) else lo
    if lo is None or hi is None:
        return None
    after = text[r.end():r.end() + 30]
    per = "hour" if _HOUR.search(after) else "month" if _MONTH.search(after) else "year"
    lo, hi = min(lo, hi), max(lo, hi)
    low, high = _PLAUSIBLE[per]
    if cur == "INR":
        low, high = low * 20, high * 100
    if not (low <= lo and hi <= high) or (lo and hi / lo > 6):
        return None
    return {"cur": cur, "lo": lo, "hi": hi, "per": per}


def _money(v: float, cur: str) -> str:
    if v != int(v):
        return f"{SIGN[cur]}{v:,.2f}"
    return f"{SIGN[cur]}{int(v):,}"


def label(p: dict | None) -> str:
    """'£45,000–£55,000 a year', '$25 an hour', '12–18 LPA'."""
    if not p:
        return ""
    if p["cur"] == "INR" and p["per"] == "year":
        f = lambda x: f"{x / 1e5:.1f}".rstrip("0").rstrip(".")  # noqa: E731
        return f"{f(p['lo'])}–{f(p['hi'])} LPA" if p["lo"] != p["hi"] else f"{f(p['hi'])} LPA"
    span = _money(p["lo"], p["cur"]) + ("–" + _money(p["hi"], p["cur"]) if p["hi"] != p["lo"] else "")
    return span + {"year": " a year", "month": " a month", "hour": " an hour"}[p["per"]]


def annual(p: dict | None) -> int:
    """The top of the range, a year (a month x 12, an hour x 2,080)."""
    if not p:
        return 0
    return int(p["hi"] * {"year": 1, "month": 12, "hour": 2080}[p["per"]])


def tier(p: dict | None) -> str:
    """'top', 'good' or '' from the TOP and GOOD tables."""
    a = annual(p)
    if not a:
        return ""
    return "top" if a >= TOP[p["cur"]] else "good" if a >= GOOD[p["cur"]] else ""


def order(p: dict | None) -> int:
    """A number to sort by pay across currencies (rough rates, never shown)."""
    return int(annual(p) * _ORDER.get(p["cur"], 0)) if p else 0


def of_role(r: dict) -> dict | None:
    """Pay for a feed record: its structured pay line first, then the quote the scan kept from the posting."""
    f = r.get("facts") or {}
    return native(r.get("salary") or "") or native(f.get("salaryQuote") or "")
