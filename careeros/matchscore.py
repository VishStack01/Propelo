"""How well a posting matches someone's real resume: a score out of 100, with every part shown.

Used by the browser extension on any job page and by the app. It reads only what the person
already gave Propelo (their structured resume, the text of their uploaded resume, their Career Brain)
and the posting's own text, which is matched as data and never followed as instructions.

    score = 70 x skills + 20 x experience + 10 x title

* skills: the posting's terms (from keywords.VOCAB, for every field) found in the resume. A term in a
  summary or bullet counts fully; a term only in the skills list counts half. Fewer than 3 terms means
  the score is marked low-confidence.
* experience: 1 when you have at least the years asked, falling by a third for each year short.
* title: how many of the title's words appear in your target roles, headline or recent titles.

It is a keyword and experience check, not how the employer's screening software ranks anyone, and the
missing terms are only worth adding to a resume when they're true.
"""

from __future__ import annotations

import re

from . import extract, keywords

STOP = {"senior", "junior", "lead", "staff", "principal", "associate", "intern", "trainee", "manager", "executive", "specialist",
        "i", "ii", "iii", "iv", "the", "and", "of", "for", "with", "to", "in", "at", "remote", "hybrid", "onsite", "full", "time", "part",
        "contract", "sr", "jr", "head", "officer", "assistant"}


def resume_from_profile(profile: dict | None) -> dict:
    """The structured resume (profile/resume document) in the shape keywords.coverage reads."""
    p = profile or {}
    basics = p.get("basics") or {}
    bullets = []
    titles = []
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


def score(title: str, jd: str, resume: dict | str, years: float | None = None, targets: list[str] | None = None) -> dict:
    """Score a posting against a resume. `resume` is a dict from resume_from_profile/brain, or plain resume text."""
    jd = (jd or "")[:60000]
    terms = keywords.extract(f"{title}\n{jd}", limit=25)
    if isinstance(resume, str):
        resume_d = {"headline": "", "summary": resume, "bullets": [], "skills": [], "titles": []}
    else:
        resume_d = resume
    cov = keywords.coverage(terms, resume_d) if terms else {"present": [], "thin": [], "missing": []}
    n = len(terms)
    skills = (len(cov["present"]) + 0.5 * len(cov["thin"])) / n if n else 0.5

    req = extract.extract_experience(jd)
    asked = req.min_years
    ty = extract.title_years(title)
    if ty is not None and (asked is None or ty > asked):
        asked = ty
    if asked is None or years is None:
        exp, exp_note = (0.75 if years is None and asked else 1.0), ("Asks for " + req.describe() if asked is not None else "No years stated")
    else:
        gap = max(0.0, float(asked) - float(years))
        exp = max(0.0, 1 - gap / 3)
        exp_note = f"Asks for {asked:g}+ years; you have {years:g}"

    tw = _words(title)
    mine = _words(" ".join((targets or []) + [resume_d.get("headline", "")] + resume_d.get("titles", [])[:4]))
    title_fit = (len(tw & mine) / len(tw)) if tw and mine else 0.5

    total = round(100 * (0.7 * skills + 0.2 * exp + 0.1 * title_fit))
    label = "Strong match" if total >= 80 else "Good match" if total >= 65 else "Fair match" if total >= 50 else "Stretch"
    return {"score": total, "label": label, "lowConfidence": n < 3,
            "skills": {"present": cov["present"], "thin": cov["thin"], "missing": cov["missing"], "share": round(skills, 2)},
            "experience": {"asked": asked, "yours": years, "fit": round(exp, 2), "note": exp_note, "quote": req.quote},
            "title": {"fit": round(title_fit, 2)},
            "note": "A keyword and experience check against your own resume, not how the employer's software ranks you. "
                    "Add a missing term only if it's true."}
