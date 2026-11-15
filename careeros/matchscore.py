"""How well a posting matches someone's real resume: a score out of 100 with the arithmetic shown.

Used by the browser extension on any job page and by the app. It reads only what the person already
gave Propelo (their structured resume, else the text of their uploaded resume, else their Career Brain)
and the posting's text, which is matched as data and never followed as instructions.

Nothing is assumed. A part that can't be measured (the posting states no years, you haven't said yours,
you have no titles to compare) is left out and the others are scaled to 100, and the card says so.

1. Skills, up to 60 points. Each skill term the posting names (keywords.VOCAB covers every field) gets a
   weight: 1 if it's asked for, 0.5 if it's only "nice to have" or "a plus"; x1.5 if it's in the job
   title; +25% for each extra mention, up to two. Each gets credit from your resume:
     proven    1.0  in a bullet that has a number ("cut costs 20% with SQL")
     mentioned 0.8  in a bullet, summary or headline
     listed    0.4  only in your skills list
     missing   0
   (Plain resume text has no structure, so a term found there counts 0.7.)
   Skills = 60 x sum(weight x credit) / sum(weight).
2. Experience, up to 25 points. You have at least the years asked: 25. Short by g years of an ask of A:
   25 x (1 - g / max(A, 2)), never below 0. Five or more years over the ask for a junior or intern
   title: 18 (likely overqualified).
3. Role, up to 15 points: the share of the job title's words found in your recent titles, headline and
   target roles.

The margin (+/-) reflects how much there was to compare: 24 / sqrt(number of terms) + 3, plus 5 when
experience couldn't be measured, capped at 20. It is a keyword and experience check against your own
resume, not how the employer's screening software ranks anyone.
"""

from __future__ import annotations

import math
import re

from . import extract, keywords

MAX = {"skills": 60, "experience": 25, "role": 15}
CREDIT = {"proven": 1.0, "mentioned": 0.8, "listed": 0.4, "found": 0.7, "missing": 0.0}
STOP = {"senior", "junior", "lead", "staff", "principal", "associate", "intern", "trainee", "manager", "executive", "specialist",
        "i", "ii", "iii", "iv", "the", "and", "of", "for", "with", "to", "in", "at", "remote", "hybrid", "onsite", "full", "time", "part",
        "contract", "sr", "jr", "head", "officer", "assistant", "a", "an", "or", "new", "grad", "level", "entry"}
_NICE = re.compile(r"nice[- ]to[- ]have|good[- ]to[- ]have|\bpreferred\b|\bbonus\b|\ba plus\b|is a plus|\bplus if\b|\bdesirable\b|\bideally\b|\boptional\b", re.I)
_JUNIOR = re.compile(r"\b(intern(ship)?|trainee|fresher|junior|jr\.?|graduate|entry[- ]level|apprentice)\b", re.I)


def resume_from_profile(profile: dict | None) -> dict:
    """The structured resume (profile/resume document) as headline, summary, bullets, skills and titles."""
    p = profile or {}
    basics = p.get("basics") or {}
    bullets, titles = [], []
    for e in (p.get("experience") or []) + (p.get("projects") or []):
        if not isinstance(e, dict):
            continue
        if e.get("title") or e.get("role"):
            titles.append(str(e.get("title") or e.get("role")))
        for b in e.get("bullets") or []:
            bullets.append({"text": str(b.get("text") if isinstance(b, dict) else b)})
        if e.get("summary"):
            bullets.append({"text": str(e["summary"])})
    skills = []
    for s in p.get("skills") or []:
        if isinstance(s, dict):
            skills += [str(x) for x in (s.get("items") or s.get("keywords") or [])] + ([str(s["name"])] if s.get("name") else [])
        else:
            skills.append(str(s))
    return {"headline": str(basics.get("headline") or p.get("headline") or ""), "summary": str(p.get("summary") or ""),
            "bullets": bullets, "skills": skills, "titles": titles}


def resume_from_brain(brain: dict | None) -> dict:
    b = brain or {}
    bullets = []
    for item in (b.get("experiences") or b.get("items") or b.get("claims") or []):
        if isinstance(item, dict):
            bullets.append({"text": " ".join(str(item.get(k) or "") for k in ("problem", "action", "outcome", "tools", "text", "title"))})
    return {"headline": str(b.get("headline") or ""), "summary": str(b.get("summary") or ""), "bullets": bullets,
            "skills": [str(x) for x in (b.get("skills") or [])], "titles": []}


def _words(s: str) -> set[str]:
    return {w for w in re.findall(r"[a-z][a-z+#.]{1,}", (s or "").lower()) if w not in STOP}


def _sentences(text: str) -> list[str]:
    return [x for x in re.split(r"(?<=[.!?;])\s+|\n+", text or "") if x.strip()]


def _weights(title: str, jd: str, terms: list[str]) -> dict[str, dict]:
    sents = _sentences(jd)
    # A line under a "Nice to have" / "Preferred" heading counts as nice to have until the next heading.
    nice_lines, in_nice = set(), False
    for i, s in enumerate(sents):
        if len(s) < 60 and re.search(r":\s*$|^#+\s|^[A-Z][A-Za-z ]{2,40}$", s.strip()):
            in_nice = bool(_NICE.search(s))
        if in_nice or _NICE.search(s):
            nice_lines.add(i)
    out = {}
    for t in terms:
        rx = re.compile(keywords._rx(t), re.I)
        hits = [i for i, s in enumerate(sents) if rx.search(s)]
        mentions = sum(len(rx.findall(s)) for s in sents)
        required = not hits or any(i not in nice_lines for i in hits)
        w = (1.0 if required else 0.5) * (1.5 if rx.search(title or "") else 1.0) * (1 + 0.25 * min(max(mentions - 1, 0), 2))
        out[t] = {"weight": round(w, 3), "required": required, "mentions": mentions}
    return out


def _evidence(term: str, resume: dict | str) -> str:
    rx = re.compile(keywords._rx(term), re.I)
    if isinstance(resume, str):
        return "found" if rx.search(resume) else "missing"
    best = "missing"
    for b in resume.get("bullets") or []:
        text = str(b.get("text") if isinstance(b, dict) else b)
        if rx.search(text):
            if re.search(r"\d", text):
                return "proven"
            best = "mentioned"
    if best == "missing" and (rx.search(resume.get("summary") or "") or rx.search(resume.get("headline") or "")):
        best = "mentioned"
    skills = [str(x) for x in resume.get("skills") or []]
    if best == "missing" and (rx.search(" ".join(skills)) or any(x.strip().lower() == term.lower() for x in skills)):
        best = "listed"
    return best


def score(title: str, jd: str, resume: dict | str, years: float | None = None, targets: list[str] | None = None) -> dict:
    jd = (jd or "")[:60000]
    terms = keywords.extract(f"{title}\n{jd}", limit=25)
    weights = _weights(title, jd, terms)
    rows = []
    for t in terms:
        ev = _evidence(t, resume)
        rows.append({"term": t, "status": ev, "required": weights[t]["required"], "weight": weights[t]["weight"]})
    parts = []

    # 1. skills
    if rows:
        wsum = sum(r["weight"] for r in rows)
        got = sum(r["weight"] * CREDIT[r["status"]] for r in rows)
        share = got / wsum if wsum else 0
        n = {k: sum(1 for r in rows if r["status"] == k) for k in CREDIT}
        found = len(rows) - n["missing"]
        how = ", ".join(f"{n[k]} {k}" for k in ("proven", "mentioned", "listed", "found") if n[k])
        parts.append({"id": "skills", "label": "Skills the posting asks for", "max": MAX["skills"], "points": MAX["skills"] * share,
                      "detail": f"{found} of {len(rows)} found" + (f" ({how})" if how else "")})
    else:
        parts.append({"id": "skills", "label": "Skills the posting asks for", "max": MAX["skills"], "points": None,
                      "detail": "The posting names no skills we can compare"})

    # 2. experience
    req = extract.extract_experience(jd)
    asked = req.min_years
    ty = extract.title_years(title)
    if ty is not None and (asked is None or ty > asked):
        asked = ty
    if asked is None or years is None:
        parts.append({"id": "experience", "label": "Experience", "max": MAX["experience"], "points": None,
                      "detail": "The posting states no years" if asked is None else f"Asks for {asked:g}+ years; add your years in Settings to compare"})
    else:
        a, y = float(asked), float(years)
        if y >= a:
            pts = MAX["experience"]
            if y - a >= 5 and _JUNIOR.search(title or ""):
                pts, note = 18, f"Asks for {a:g}+ years; you have {y:g}, so you may be overqualified"
            else:
                note = f"Asks for {a:g}+ years; you have {y:g}"
        else:
            pts = max(0.0, MAX["experience"] * (1 - (a - y) / max(a, 2)))
            note = f"Asks for {a:g}+ years; you have {y:g}"
        parts.append({"id": "experience", "label": "Experience", "max": MAX["experience"], "points": pts, "detail": note, "quote": req.quote})

    # 3. role ("Backend Engineer at Northwind" is compared as "Backend Engineer")
    tw = _words(re.sub(r"\s+(at|@)\s+[A-Z][\w&.,' ]*$", "", title or ""))
    mine_src = (targets or []) + ([resume.get("headline", "")] + (resume.get("titles") or [])[:4] if isinstance(resume, dict) else [])
    mine = _words(" ".join(mine_src))
    if tw and mine:
        hit = tw & mine
        parts.append({"id": "role", "label": "Role", "max": MAX["role"], "points": MAX["role"] * len(hit) / len(tw),
                      "detail": f"{len(hit)} of {len(tw)} title words match your titles and target roles"})
    else:
        parts.append({"id": "role", "label": "Role", "max": MAX["role"], "points": None,
                      "detail": "The posting has no job title to compare" if not tw else "Add your job titles or target roles to compare"})

    measured = [p for p in parts if p["points"] is not None]
    if not measured:
        total = None
    else:
        got = sum(p["points"] for p in measured)
        room = sum(p["max"] for p in measured)
        total = round(100 * got / room)
    for p in parts:
        if p["points"] is not None:
            p["points"] = round(p["points"], 1)
    margin = min(20, round(24 / math.sqrt(max(len(rows), 1)) + 3 + (5 if parts[1]["points"] is None else 0)))
    label = None if total is None else "Strong match" if total >= 75 else "Good match" if total >= 60 else "Fair match" if total >= 45 else "Low match"
    present = [r["term"] for r in rows if r["status"] in ("proven", "mentioned", "found")]
    thin = [r["term"] for r in rows if r["status"] == "listed"]
    missing = [r["term"] for r in rows if r["status"] == "missing"]
    return {"score": total, "label": label, "margin": margin, "lowConfidence": len(rows) < 3, "parts": parts, "terms": rows,
            "scaled": len(measured) < len(parts),
            "skills": {"present": present, "thin": thin, "missing": missing, "requiredMissing": [r["term"] for r in rows if r["status"] == "missing" and r["required"]]},
            "experience": {"asked": asked, "yours": years, "note": parts[1]["detail"], "quote": req.quote},
            "note": "A keyword and experience check against your own resume, not how the employer's software ranks you. "
                    "Add a missing skill only if it's true."}
