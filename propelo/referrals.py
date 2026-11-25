"""Referral finder: who to ask for a referral at a company, and what to say.

    propelo referrals --company "Razorpay" --title "SDE 1" \
        [--connections Connections.csv] [--people people.json] [--applicant applicant.json] [--json]

A referral is the single biggest lift to being shortlisted, so for each role
Propelo finds the people most likely to refer you, in this order:

1. people you already know there (your LinkedIn Connections.csv export);
2. alumni of the schools you studied at (your university at home and the one
   abroad) working there, then the manager of the team the role sits in, then
   people on that team and recruiters where the role is, found by
   * LinkedIn people-search links you open in your own signed-in browser, and
   * public web search (site:linkedin.com/in), whose results the agent passes
     in as --people [{name, headline, url, location, degree}].

It ranks them, explains each pick, and drafts a short connection note and a
message of 75 words at most for after they accept, which names something real
you share (the school) and one project of yours that fits the role. The
dashboard runs the same bridge in JavaScript (between the bridge markers in
dashboard/app.html); tests check both give the same links and message. You send every message yourself: Propelo
never signs in to LinkedIn, never scrapes it and never sends anything there.
"""

from __future__ import annotations

import re
from urllib.parse import quote, urlencode

from . import connections as conn
from .dedupe import company_key

NOTE_LIMIT = 300  # LinkedIn's limit for a connection-request note

_ENG = re.compile(r"\b(engineer|developer|sde|swe|programmer|scientist|ml|ai|backend|frontend|full[ -]?stack|devops|sre|platform|data)\b", re.I)
_MGR = re.compile(r"\b(engineering manager|em\b|head of engineering|tech lead|team lead|lead engineer|director of engineering|hiring manager)\b", re.I)
_RECRUIT = re.compile(r"\b(recruiter|talent acquisition|talent partner|sourcer|hiring|people partner|ta\b)", re.I)
_JUNIOR = re.compile(r"\b(junior|jr\.?|associate|graduate|trainee|entry[- ]level|(sde|swe|software engineer|software developer|engineer|developer)[ -]?(1|i)\b)", re.I)
_TOO_SENIOR = re.compile(r"\b(vp|vice president|chief|cto|ceo|cfo|founder|co-founder|partner|president)\b", re.I)


def _college_words(college: str) -> list[str]:
    key = re.sub(r"\b(university|institute|of|technology|college|engineering|the|and|deemed|to|be)\b", " ", (college or "").lower())
    return [w for w in re.findall(r"[a-z]{3,}", key)][:2]


# Team words in a job title, and who usually hires for that team. First match wins.
TEAMS = [
    (r"\bdata engineer", "data engineering manager"),
    (r"\b(?:machine learning|ml|ai|llm|applied scien|nlp|computer vision)", "machine learning manager"),
    (r"\bdata scien", "data science manager"),
    (r"\b(?:data|business|bi|product|marketing) analyst|\banalytics\b", "analytics manager"),
    (r"\b(?:devops|sre|site reliability|infrastructure|platform|cloud)\b", "platform engineering manager"),
    (r"\b(?:frontend|front[- ]end|web)\b", "frontend engineering manager"),
    (r"\b(?:ios|android|mobile)\b", "mobile engineering manager"),
    (r"\b(?:backend|back[- ]end|api)\b", "backend engineering manager"),
    (r"\b(?:security|cyber)", "security engineering manager"),
    (r"\b(?:qa|test|quality)\b", "quality engineering manager"),
    (r"\bproduct (?:manager|owner)", "group product manager"),
    (r"\b(?:designer|ux|ui)\b", "design manager"),
    (r"\b(?:marketing|growth|seo|content)", "marketing manager"),
    (r"\b(?:sales|account executive|business development|sdr|bdr)\b", "sales manager"),
    (r"\b(?:customer success|support)\b", "head of customer success"),
    (r"\b(?:finance|financial|accountant|accounting|audit)", "finance manager"),
    (r"\b(?:hr|people|talent|recruit)", "head of people"),
    (r"\b(?:nurse|nursing)\b", "nurse manager"),
    (r"\b(?:software|developer|engineer|swe|sde|programmer)\b", "engineering manager"),
]
_SENIORITY = re.compile(r"\b(?:senior|sr|junior|jr|graduate|grad|new grad|entry[- ]level|associate|intern(?:ship)?|trainee|lead|principal|staff|i{1,3}|[1-3])\b\.?", re.I)


def manager_for(title: str) -> str:
    """Who usually hires for the team a job title names: "data engineering manager" for a Data Engineer."""
    for rx, who in TEAMS:
        if re.search(rx, title or "", re.I):
            return who
    return "hiring manager"


def role_words(title: str) -> str:
    """A title without seniority, brackets or trailing detail: "Data Engineer" from "Graduate Data Engineer (Python) - London"."""
    t = re.split(r"\s[-–|,/]\s|\(", title or "")[0]
    t = re.sub(r"\s+", " ", _SENIORITY.sub(" ", t)).strip(" -,")
    return t.lower()


def place_of(location: str) -> str:
    """The city a role is in, or "" for a remote role."""
    first = (location or "").split(",")[0].strip()
    return "" if not first or re.search(r"\b(?:remote|anywhere|worldwide|hybrid|multiple)\b", first, re.I) else first[:40]


def schools(applicant: dict | None = None, profile: dict | None = None) -> list[str]:
    """The schools to look for alumni of: the applicant's college, then every school in the resume. Three at most."""
    out: list[str] = []
    names = [(applicant or {}).get("college", "")] + [e.get("school", "") for e in ((profile or {}).get("education") or []) if isinstance(e, dict)]
    for n in names:
        n = re.sub(r"\s*\([^)]*\)\s*$", "", str(n or "")).strip()[:60]
        if n and n.lower() not in (x.lower() for x in out):
            out.append(n)
    return out[:3]


def bridge_links(company: str, title: str, location: str = "", applicant: dict | None = None, profile: dict | None = None) -> list[dict]:
    """The warm paths into a company, most useful first: alumni of each of your schools, the manager of the team the
    role sits in, people on that team, your 2nd-degree connections, and recruiters where the role is. Each is a
    LinkedIn people search the member opens in their own signed-in browser."""
    li = "https://www.linkedin.com/search/results/people/?"
    city, role, mgr = place_of(location), role_words(title), manager_for(title)
    q = lambda kw, **x: li + urlencode({"keywords": re.sub(r"\s+", " ", kw).strip(), "origin": "GLOBAL_SEARCH_HEADER", **x})  # noqa: E731
    out = [{"kind": "alumni", "label": f"{s} alumni at {company}", "url": q(f'"{company}" "{s}"')} for s in schools(applicant, profile)]
    out.append({"kind": "manager", "label": f"The {mgr} at {company}" if mgr != "hiring manager" else f"Hiring managers at {company}",
                "url": q(f'"{company}" "{mgr}" {city}')})
    if role:
        out.append({"kind": "team", "label": f"{role.title()}s at {company}" + (f" in {city}" if city else ""), "url": q(f'"{company}" "{role}" {city}')})
    out.append({"kind": "second", "label": f"2nd-degree connections at {company}", "url": li + urlencode({"keywords": f'"{company}"', "network": '["S"]', "origin": "FACETED_SEARCH"})})
    out.append({"kind": "recruiter", "label": f"Recruiters at {company}" + (f" in {city}" if city else ""), "url": q(f'"{company}" recruiter {city}')})
    return out


def search_links(company: str, title: str, applicant: dict | None = None, location: str = "", profile: dict | None = None) -> list[dict]:
    """People-search links to open in your own browser, most useful first, then a public web search."""
    out = [{"label": l["label"], "url": l["url"]} for l in bridge_links(company, title, location, applicant, profile)]
    first = schools(applicant, profile)
    xr = f'site:linkedin.com/in "{company}" "{role_words(title) or title}"' + (f' "{first[0]}"' if first else "")
    out.append({"label": "Web search for public profiles", "url": "https://www.google.com/search?q=" + quote(xr)})
    return out


_WORD = re.compile(r"[a-z0-9+#]{2,}")
_STOPWORDS = {"and", "the", "for", "with", "of", "to", "in", "on", "at", "a", "an", "by", "from", "engineer", "senior", "junior", "graduate", "role"}


def _overlap(text: str, want: set[str]) -> int:
    return len(set(_WORD.findall((text or "").lower())) & want)


def _lower_first(s: str) -> str:
    s = (s or "").strip().rstrip(".")
    return s[:1].lower() + s[1:] if s[:1].isupper() and not s[1:2].isupper() else s


_PAST = {"built", "led", "ran", "wrote", "made", "cut", "grew", "drove", "won", "taught", "set", "sold", "found", "began", "brought",
         "thought", "kept", "met", "took", "gave", "shot", "spoke", "bought", "held", "rebuilt", "rewrote", "overtook", "undertook"}


def _is_past(sentence: str) -> bool:
    w = (sentence or "").split(" ")[0].lower()
    return w in _PAST or (len(w) > 3 and w.endswith("ed"))


def best_work(title: str, skills: list[str] | None = None, profile: dict | None = None) -> str:
    """One sentence about real work of the applicant's that fits the role, from the resume only, or "". A resume
    line that shares the most words with the title and the role's skills wins; a project wins a tie."""
    want = (set(_WORD.findall((title or "").lower())) | {w.lower() for w in (skills or []) if isinstance(w, str)}) - _STOPWORDS
    best, top = "", 0.0
    for pr in (profile or {}).get("projects") or []:
        if not isinstance(pr, dict) or not str(pr.get("name") or "").strip():
            continue
        b = next((x for x in pr.get("bullets") or [] if isinstance(x, str) and x.strip()), "")
        n = _overlap(f"{pr['name']} {b}", want) + 0.5
        if n > top and b:
            best, top = f"I built {pr['name'].strip()} ({_lower_first(b)}).", n
    for ex in (profile or {}).get("experience") or []:
        if not isinstance(ex, dict):
            continue
        co = str(ex.get("company") or "").strip()
        for b in ex.get("bullets") or []:
            if not isinstance(b, str) or not b.strip():
                continue
            n = _overlap(b, want)
            if n > top:
                line = _lower_first(b) if _is_past(b) else ""
                best, top = ((f"At {co} I {line}." if co else f"I {line}.") if line else (f"At {co}: {b.strip().rstrip('.')}." if co else "")), n
    return best


def _school_name(s: str) -> str:
    return ("the " + s) if re.match(r"(?:University|Institute|College) of\b", s or "") else s


MESSAGE_WORDS = 75


def message(company: str, title: str, applicant: dict | None = None, person: dict | None = None, profile: dict | None = None,
            job_url: str = "", skills: list[str] | None = None) -> str:
    """The note for after they accept: 75 words at most, one real thing you share, one piece of your work that fits,
    and a plain ask with an easy way to say no. Facts come from the profile only."""
    a = applicant or {}
    me = (a.get("fullName") or "").split(" ")[0]
    them = ((person or {}).get("name") or "").split(" ")[0] or "there"
    shared = shared_school(person)
    work = best_work(title, skills, profile)
    ask = "If my CV looks right for the team, would you be comfortable referring me?"
    out_ = " If not, one line on what the team looks for would help just as much."
    head = f"Hi {them}, thanks for connecting." + (f" We both studied at {_school_name(shared)}." if shared else "")
    role = f" I'm applying for the {title} role at {company}" + (f" ({job_url})" if job_url else "") + "."
    sign = f"\n\n{me}" if me else ""

    def words(s: str) -> int:
        return len(s.split())
    for body in (head + role + (" " + work if work else "") + " " + ask + out_, head + role + (" " + work if work else "") + " " + ask,
                 head + role + " " + ask + out_, head + role + " " + ask):
        if words(body) <= MESSAGE_WORDS:
            return body + sign
    return (head + role + " " + ask) + sign


def shared_school(person: dict | None) -> str:
    """The school a ranked person shares with the applicant, from their reasons ("Alumni of X"), or ""."""
    return next((w[len("Alumni of "):] for w in ((person or {}).get("why") or []) if str(w).startswith("Alumni of ")), "")


def score(person: dict, company: str, title: str, applicant: dict | None = None, profile: dict | None = None) -> tuple[int, list[str]]:
    """How likely this person is to refer you for this role, with the reasons."""
    a = applicant or {}
    head = " ".join(str(person.get(k) or "") for k in ("headline", "position", "title"))
    where = f"{person.get('company') or ''} {head}"
    s, why = 0, []
    tier = conn.tier(company, person.get("company") or "") if person.get("company") else ""
    if tier in ("exact", "strong") or (not person.get("company") and company_key(company) and company_key(company) in company_key(where)):
        if not tier and re.search(r"\b(ex[- ]?|former(ly)?\s+(at\s+)?|previously\s+(at\s+)?)@?\s*" + re.escape(company.split()[0]), head, re.I):
            return 0, ["Used to work there"]
        s += 40
        why.append(f"Works at {company}")
    else:
        return 0, ["Doesn't appear to work there now"]
    degree = str(person.get("degree") or ("1st" if person.get("connectedOn") else "")).lower()
    if degree.startswith("1"):
        s += 30
        why.append("Already a connection")
    elif degree.startswith("2"):
        s += 10
        why.append("2nd-degree: you share a connection")
    text = f"{head} {person.get('education') or ''}".lower()
    for school in schools(a, profile):
        words = _college_words(school)
        if (words and all(w in text for w in words)) or school.lower() in text:
            s += 25
            why.append(f"Alumni of {school}")
            break
    if _MGR.search(head):
        s += 15
        why.append("Engineering manager or lead: can refer and often hires")
    elif _ENG.search(head):
        s += 20 if _ENG.search(title or "") else 10
        why.append("Engineer, likely on a similar team")
    elif _RECRUIT.search(head):
        s += 12
        why.append("Recruiter: can move your application to a hiring manager")
    if _JUNIOR.search(head) and not _MGR.search(head):
        s += 12
        why.append("Junior or associate level: close to your role and quick to reply")
    if _TOO_SENIOR.search(head):
        s -= 15
        why.append("Very senior; less likely to reply")
    city = (a.get("city") or "").lower()
    if city and city[:5] in f"{person.get('location') or ''} {head}".lower():
        s += 5
        why.append(f"Also in {a.get('city')}")
    return max(s, 0), why


def rank(company: str, title: str, applicant: dict | None = None, connections: list[dict] | None = None,
         people: list[dict] | None = None, limit: int = 8, profile: dict | None = None) -> list[dict]:
    pool: dict[str, dict] = {}
    for r in conn.matches(company, connections or [], limit=50):
        pool[(r.get("url") or r["name"]).lower()] = dict(r, headline=r.get("position", ""), degree="1st", via="Your connections")
    for p in people or []:
        if not p.get("name"):
            continue
        key = (p.get("url") or p["name"]).lower()
        pool.setdefault(key, dict(p, via=p.get("via") or "Public web search"))
    out = []
    for p in pool.values():
        sc, why = score(p, company, title, applicant, profile)
        if sc > 0:
            out.append({"name": p["name"], "headline": p.get("headline") or p.get("position", ""), "url": p.get("url", ""),
                        "via": p["via"], "score": sc, "why": why})
    out.sort(key=lambda x: -x["score"])
    return out[:limit]


def drafts(company: str, title: str, applicant: dict | None = None, person: dict | None = None, job_url: str = "",
           profile: dict | None = None, skills: list[str] | None = None) -> dict:
    """A connection note (300 characters at most), a referral ask, and the 75-word message for after they accept,
    from facts in the profile only."""
    a = applicant or {}
    me = (a.get("fullName") or "").split(" ")[0] or "I"
    them = ((person or {}).get("name") or "").split(" ")[0] or "there"
    now = " ".join(x for x in (a.get("currentTitle"), f"at {a['currentCompany']}" if a.get("currentCompany") else "") if x)
    shared = shared_school(person)
    school = shared or a.get("college", "")
    hook = f"Fellow {shared} grad here. " if shared else ""
    note = (f"Hi {them}, {hook}I'm {me}, {now + ', ' if now else ''}applying for the {title} role at {company}. "
            f"Would you be open to a quick chat about the team, or referring me if I seem a fit? Thanks!")
    if len(note) > NOTE_LIMIT:
        note = f"Hi {them}, {hook}I'm {me}, applying for {title} at {company}. Open to a quick chat or a referral if I fit? Thanks!"
    note = note[:NOTE_LIMIT]
    ask = (f"Hi {them},\n\nThanks for connecting. I'm applying for the {title} role at {company}"
           + (f" ({job_url})" if job_url else "") + ". "
           + (f"I'm currently {now}" + (f" and studied at {school}" if school else "") + ". " if now else "")
           + "I've attached my resume. If you think I'd be a fit, would you be willing to refer me? "
           "If not, any advice on the team or the process would help a lot.\n\nThank you,\n" + (a.get("fullName") or ""))
    return {"connectionNote": note, "referralAsk": ask.strip(), "message": message(company, title, a, person, profile, job_url, skills)}


def plan(company: str, title: str, applicant: dict | None = None, connections: list[dict] | None = None,
         people: list[dict] | None = None, job_url: str = "", location: str = "", profile: dict | None = None) -> dict:
    ranked = rank(company, title, applicant, connections, people, profile=profile)
    return {"company": company, "title": title, "people": ranked, "searchLinks": search_links(company, title, applicant, location, profile),
            "drafts": drafts(company, title, applicant, ranked[0] if ranked else None, job_url, profile)}
