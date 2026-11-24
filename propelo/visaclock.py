"""The Visa-Clock: how much time a visa status leaves, from the dates a member enters.

Plain date arithmetic over propelo/data/visa_rules.json, where every fact carries its official source. The
dashboard runs the same logic in JavaScript (dashboard/app.html, between the visa-clock markers, with the rules
copied in by scripts/sync_visa_rules.py); tests check that both give the same answer for the same dates.

A member's visa is stored in their settings as `visa`: {"status": "us-opt", "optStart": "2026-10-01", ...}.
Nothing here guesses a date: a clock without its date says which date is missing.
"""

from __future__ import annotations

import json
import re
from datetime import date, timedelta
from pathlib import Path

RULES = json.loads((Path(__file__).parent / "data" / "visa_rules.json").read_text(encoding="utf-8"))
BY_ID = {s["id"]: s for s in RULES["statuses"]}
STATUSES = tuple(BY_ID)


def _date(v) -> date | None:
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", str(v or "")[:10])
    if not m:
        return None
    try:
        return date(int(m[1]), int(m[2]), int(m[3]))
    except ValueError:
        return None


def _num(v) -> int | None:
    if v is None or v == "" or isinstance(v, bool):
        return None
    try:
        return max(0, int(float(v)))
    except (TypeError, ValueError, OverflowError):
        return None


def fmt(d: date) -> str:
    return f"{d.day} {RULES['months'][d.month - 1]} {d.year}"


def _tone(n: int, kind: str) -> str:
    urgent, soon = RULES["tones"][kind]
    return "urgent" if n <= urgent else "soon" if n <= soon else "ok"


def _label(st: dict, key: str) -> str:
    return st["labels"].get(key) or RULES["fields"][key]["label"]


def work_line(st: dict, v: dict, today: date) -> str:
    texts = RULES["work"].get(st["work"]) or []
    if not texts:
        return ""
    k, i = st["work"], 0
    if k == "uk-student":
        ce = _date(v.get("courseEnd"))
        i = 1 if ce and ce < today else 0
    elif k == "ie-stamp2":
        m, d = today.month, today.day
        i = 1 if 6 <= m <= 9 or (m == 12 and d >= 15) or (m == 1 and d <= 15) else 0
    elif k == "nl-study":
        i = 1 if 6 <= today.month <= 8 else 0
    return texts[i]


def part_time_ok(v) -> bool:
    """True when this status allows part-time work while studying, so the part-time mode applies."""
    st = BY_ID.get(str((v or {}).get("status") or "")) if isinstance(v, dict) else None
    return bool(st and st["partTime"])


def clock(v, today: date | None = None) -> dict | None:
    """The clock for one member's visa, or None when no status is set."""
    v = v if isinstance(v, dict) else {}
    st = BY_ID.get(str(v.get("status") or ""))
    if not st:
        return None
    today = today or date.today()
    notes = RULES["notes"]
    out = {"status": st["id"], "label": st["label"], "country": st["country"], "partTime": st["partTime"], "sponsor": st["sponsor"],
           "work": work_line(st, v, today), "next": st["next"], "sources": [{"title": t, "url": u} for t, u in st["sources"]],
           "badge": None, "dates": [], "missing": []}

    def left(d: date) -> int:
        return (d - today).days

    def badge(n: int, label: str, total: int | None, kind: str, note: str = "") -> None:
        over = n <= 0 if kind == "days" else n < 0
        out["badge"] = {"days": max(0, n), "label": label, "total": total, "tone": "over" if over else _tone(n, kind),
                        "note": (notes["overDays"] if kind == "days" else notes["over"]) if over else note}

    kind = st["clock"]
    if kind == "program-end":
        ce = _date(v.get("courseEnd"))
        if not ce:
            out["missing"] = ["courseEnd"]
        elif left(ce) >= 0:
            badge(left(ce), st["badge"][0], None, "dates")
        else:
            badge(left(ce + timedelta(days=60)), st["badge"][1], 60, "days", notes["programEnded"].format(date=fmt(ce)))
    elif kind == "unemployment":
        limit, start, used = int(st["limit"]), _date(v.get("optStart")), _num(v.get("daysUsed"))
        working = v.get("working") is True
        if used is None and not start:
            out["missing"] = ["optStart" if "optStart" in st["fields"] else "daysUsed"]
        elif start and start > today:
            badge(limit, st["badge"][0], limit, "days", notes["startsOn"].format(date=fmt(start)))
        else:
            base, since = (used, _date(v.get("asOf"))) if used is not None else (0, start)
            ticking = 0 if working or not since or since > today else (today - since).days
            note = notes["paused"] if working else notes["counting"].format(date=fmt(since)) if since else ""
            badge(limit - base - ticking, st["badge"][0], limit, "days", note)
    elif kind == "h1b":
        end, gone = _date(v.get("permitEnd")), _date(v.get("jobEnded"))
        if gone and gone <= today:
            grace = gone + timedelta(days=60)
            if end and end < grace:
                grace = end
            badge(left(grace), st["badge"][1], 60, "days", notes["jobEnded"].format(date=fmt(gone), end=fmt(grace)))
        elif end:
            badge(left(end), st["badge"][0], None, "dates")
        else:
            out["missing"] = ["permitEnd"]
    elif kind == "permit-end":
        pe = _date(v.get("permitEnd"))
        if pe:
            badge(left(pe), st["badge"][0], None, "dates")
        else:
            out["missing"] = ["permitEnd"]

    for key in st["fields"]:
        d = _date(v.get(key)) if RULES["fields"][key]["type"] == "date" and key != "jobEnded" else None
        if d:
            out["dates"].append({"key": key, "label": _label(st, key), "date": d.isoformat(), "text": fmt(d), "days": left(d)})
    if out["missing"]:
        out["missingNote"] = notes["missing"]
    return out
