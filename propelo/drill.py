"""Resume defence drill: an interviewer that cross-examines the figures and tools on your resume.

More employers now add a spoken screen or a human check that the candidate can defend what the resume says.
This drill takes the resume lines that carry a figure ("Cut latency by 40%", "1,200 users", "£50k saved") or a
named tool, asks about each one the way an interviewer would, asks one follow-up where the answer left a gap,
and scores each line on what was actually said:

* the figure: did you say a number, and does it match the resume? A different figure of the same kind
  ("40%" on the resume, "35%" in the answer) is a conflict, the thing an interviewer remembers;
* how you know: what was measured, against what;
* your part: "I", not only "we";
* length: long enough to carry a story, short enough to keep.

Everything is plain text rules, so the dashboard runs the same code in JavaScript (between the drill markers in
dashboard/app.html) and tests check both agree. Nothing is sent anywhere; the browser turns speech into text.
"""

from __future__ import annotations

import re

MAX_CLAIMS = 6
MINUTES = 15

_UNITS_TIME = r"hours?|hrs?|days?|weeks?|months?|minutes?|mins?|seconds?|secs?|ms|milliseconds?"
_FIGURE = re.compile(
    r"(?<![\w.,])(?P<cur>[$£€₹])?\s?(?P<num>\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)(?:\s?(?P<mult>k|m|bn|million|billion|thousand)\b)?\s?"
    r"(?P<unit>%|percent\b|per cent\b|x\b|times\b|tb\b|gb\b|mb\b|(?:" + _UNITS_TIME + r")\b)?",
    re.I)
_YEAR = re.compile(r"^(?:19|20)\d\d$")
_NAMED = re.compile(r"\s[A-Z][\w+#.-]*\s$")  # "in Python 3.11", "on Java 17": a version, not a result (a capital at the start is just the sentence)
_HOW = re.compile(r"\b(?:measur\w*|baseline|before|after|compar\w*|dashboard|metric\w*|track\w*|logged|logs|monitor\w*|a/b|ab test|benchmark\w*|"
                  r"survey\w*|report\w*|analytics|p9[059]|went (?:down |up )?from|from \d|down from|up from|instrument\w*|counted|count)\b", re.I)
_I = re.compile(r"\bI\b|\bmy\b|\bmyself\b")
_WE = re.compile(r"\bwe\b|\bour\b|\bthe team\b", re.I)

OPEN = {
    "percent": 'Your resume says: "{text}". What was the figure before and after, and how did you measure it?',
    "money": 'Your resume says: "{text}". Where does that figure come from, and how much of it was down to you?',
    "time": 'Your resume says: "{text}". What took the time before, and what exactly did you change?',
    "count": 'Your resume says: "{text}". Where does that number come from, and what did you do yourself to get there?',
    "tool": "You used {tool} {place}. Walk me through one thing you built with it, and one problem you hit.",
}
FOLLOW = {
    "conflict": "Your resume says {claimed}. You said {said}. Which is right?",
    "figure": "What was the number, exactly?",
    "how": "How do you know? What did you measure, and against what?",
    "mine": "Which part of that did you do yourself?",
    "tool": "What did you use {tool} for there, in one sentence?",
    "deeper": "What would you do differently if you did it again?",
}


def _value(m: re.Match) -> float:
    v = float(m.group("num").replace(",", ""))
    mult = (m.group("mult") or "").lower()
    return v * {"k": 1e3, "thousand": 1e3, "m": 1e6, "million": 1e6, "bn": 1e9, "billion": 1e9}.get(mult, 1)


def _kind(m: re.Match) -> str:
    unit = (m.group("unit") or "").lower()
    if m.group("cur"):
        return "money"
    if unit in ("%", "percent", "per cent"):
        return "percent"
    if unit and re.fullmatch(_UNITS_TIME, unit):
        return "time"
    return "count"


def figures(text: str) -> list[dict]:
    """The figures in a line: [{"raw", "value", "kind"}], years left out."""
    out = []
    for m in _FIGURE.finditer(text or ""):
        bare = not m.group("cur") and not m.group("unit") and not m.group("mult")
        if bare and (_YEAR.match(m.group("num")) or _NAMED.search(text[:m.start()])):
            continue
        out.append({"raw": m.group(0).strip(), "value": _value(m), "kind": _kind(m)})
    return out


def claims(view: dict | None, skills: list[str] | None = None) -> list[dict]:
    """Resume lines worth defending, in resume order: lines with a figure first, then lines naming a skill.
    [{"text", "where", "figures", "kind", "tool"}], six at most."""
    v = view if isinstance(view, dict) else {}
    lines: list[tuple[str, str, str]] = []
    for ex in v.get("experience") or []:
        if isinstance(ex, dict):
            at = str(ex.get("company") or ex.get("title") or "").strip()
            lines += [(str(b).strip(), at, f"at {at}" if at else "at work") for b in ex.get("bullets") or [] if isinstance(b, str) and b.strip()]
    for pr in v.get("projects") or []:
        if isinstance(pr, dict):
            name = str(pr.get("name") or "").strip()
            lines += [(str(b).strip(), name, f"in {name}" if name else "in a project") for b in pr.get("bullets") or [] if isinstance(b, str) and b.strip()]
    out: list[dict] = []
    for text, where, place in lines:
        f = figures(text)
        if f:
            out.append({"text": text, "where": where, "place": place, "figures": f, "kind": f[0]["kind"], "tool": ""})
        if len(out) >= MAX_CLAIMS:
            return out
    tools = [str(s).strip() for s in (skills if skills is not None else v.get("skills") or []) if isinstance(s, str) and len(str(s).strip()) > 1]
    used = {c["text"] for c in out}
    for text, where, place in lines:
        if len(out) >= MAX_CLAIMS:
            break
        if text in used:
            continue
        tool = next((t for t in tools if re.search(r"(?<![\w])" + re.escape(t) + r"(?![\w])", text, re.I)), "")
        if tool:
            out.append({"text": text, "where": where, "place": place, "figures": [], "kind": "tool", "tool": tool})
            used.add(text)
    return out[:MAX_CLAIMS]


def question(claim: dict) -> str:
    return OPEN[claim["kind"]].format(text=claim["text"].rstrip("."), tool=claim.get("tool", ""), place=claim.get("place") or "there")


def score(claim: dict, answer: str) -> dict:
    """What the answer did for this resume line: {"checks": {...}, "conflict", "said", "words", "verdict", "notes"}.
    verdict: "defended", "partly" or "not"."""
    a = answer or ""
    said = figures(a)
    words = len(a.split())
    claimed = claim.get("figures") or []
    same = [s for s in said if any(s["kind"] == c["kind"] for c in claimed)]
    match = any(abs(s["value"] - c["value"]) < 1e-9 and s["kind"] == c["kind"] for s in said for c in claimed)
    conflict = ""
    if claimed and same and not match:
        c, s = next((c, s) for s in same for c in claimed if c["kind"] == s["kind"])
        conflict = f"Your resume says {c['raw']}; you said {s['raw']}."
    mine = len(_I.findall(a)) >= 1 and len(_I.findall(a)) >= len(_WE.findall(a))
    checks = {
        "figure": match if claimed else bool(re.search(re.escape(claim.get("tool") or "\0"), a, re.I)),
        "how": bool(_HOW.search(a)) if claimed else words >= 40,
        "mine": mine,
        "length": 25 <= words <= 250,
    }
    notes = []
    if conflict:
        notes.append(conflict + " Fix the resume line or bring the proof.")
    elif claimed and not said:
        notes.append("You didn't say the number. Say it, as it is on your resume.")
    elif claimed and not match:
        notes.append("Say the figure the way your resume has it.")
    if claimed and not checks["how"]:
        notes.append("Say how you know: what you measured, and against what.")
    if not claimed and not checks["figure"]:
        notes.append(f"Name {claim.get('tool')} and what you did with it.")
    if not mine:
        notes.append('Say what you did yourself: "I", not only "we".')
    if words < 25:
        notes.append("Too short to carry a story. Aim for about a minute.")
    elif words > 250:
        notes.append("Too long. Keep it to a minute or two.")
    n = sum(1 for k in ("figure", "how", "mine") if checks[k])
    verdict = "not" if conflict or n == 0 else "defended" if n == 3 and checks["length"] else "partly"
    return {"checks": checks, "conflict": conflict, "said": [s["raw"] for s in said], "words": words, "verdict": verdict, "notes": notes}


def follow_up(claim: dict, answer: str) -> str:
    """The one follow-up an interviewer would ask after this answer."""
    s = score(claim, answer)
    if s["conflict"]:
        c = next(x for x in claim["figures"] if any(x["kind"] == f["kind"] for f in figures(answer)))
        said = next(f["raw"] for f in figures(answer) if f["kind"] == c["kind"])
        return FOLLOW["conflict"].format(claimed=c["raw"], said=said)
    if claim.get("figures") and not s["said"]:
        return FOLLOW["figure"]
    if claim.get("figures") and not s["checks"]["how"]:
        return FOLLOW["how"]
    if not s["checks"]["mine"]:
        return FOLLOW["mine"]
    if not claim.get("figures") and not s["checks"]["figure"]:
        return FOLLOW["tool"].format(tool=claim.get("tool", ""))
    return FOLLOW["deeper"]


def summary(results: list[dict]) -> dict:
    """Counts of each verdict across a session."""
    out = {"defended": 0, "partly": 0, "not": 0}
    for r in results:
        out[r.get("verdict", "not")] = out.get(r.get("verdict", "not"), 0) + 1
    return out
