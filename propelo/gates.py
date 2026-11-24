"""The gatekeeper: run every filter on a role and keep the reasons.

Each gate returns a Check with the deciding sentence from the posting. A role
is kept only if every gate passes. Skipped roles keep their checks too, so the
skip log can say exactly why, and you can overrule it.
"""

from __future__ import annotations

import re
from functools import lru_cache
from dataclasses import dataclass
from datetime import date, datetime, timezone

from . import countries, extract, geo, signals, sponsors, tags
from .models import Check, Job, iso
from .settings import Settings


@dataclass
class Decision:
    kept: bool
    checks: list[Check]
    region: str
    priority: bool


def _parse_dt(s: str) -> datetime | None:
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _facts(job: Job) -> dict | None:
    """Pre-extracted facts (from the India feed), if this job carries them."""
    f = job.raw.get("facts") if isinstance(job.raw, dict) else None
    return f if isinstance(f, dict) else None


def _kw_regex(words: list[str]) -> re.Pattern:
    return _kw_compiled(tuple(words))


@lru_cache(maxsize=512)
def _kw_compiled(words: tuple[str, ...]) -> re.Pattern:
    # Plurals count: "agent" matches "Creative Agents". Built once per word list, not once per role.
    parts = [r"(?<![a-z0-9])" + re.escape(w.lower()) + r"(?:s|es)?(?![a-z0-9])" for w in words if w.strip()]
    return re.compile("|".join(parts) or r"(?!x)x", re.I)


def gate_company(job: Job, s: Settings) -> Check:
    blocked = [c for c in s.company_blocklist if c.lower() in job.company.lower()]
    if blocked:
        return Check("Company", False, f"{job.company} is on your never-apply list.")
    return Check("Company", True, job.company)


def gate_role(job: Job, s: Settings) -> Check:
    title = job.title or ""
    if s.title_exclude and _kw_regex(s.title_exclude).search(title):
        return Check("Role", False, "The title matches one of your excluded words.", title)
    in_family = bool(s.families) and tags.family(title) in s.families
    if not in_family and not _kw_regex(s.role_keywords).search(title):
        why = "The title isn't in your job families or target roles." if s.families else "The title isn't one of your target roles."
        return Check("Role", False, why, title)
    if not s.allow_internships and re.search(r"\bintern(ship)?\b", title, re.I):
        return Check("Role", False, "It's an internship, and internships are switched off.", title)
    return Check("Role", True, "Target role", title)


def title_fits(title: str, s: Settings) -> bool:
    """The Role gate on a bare title. A role that fails it is never kept and never a near miss, so a caller
    with a large inventory can drop most of it on the title alone, before reading each role in full."""
    return gate_role(Job(company="", title=title or "", url="", source=""), s).passed


_ENTRY_TITLE = re.compile(r"\b(intern(ship)?|trainee|fresher|graduate (trainee|engineer|program(me)?)|apprentice|entry[- ]level)\b", re.I)


# Titles that run a function or a company, which nobody reaches in a couple of years.
_EXEC_TITLE = re.compile(r"\b(director|head of|head,|vp|vice president|chief|c[etfo]o|principal|distinguished|general manager|managing director)\b", re.I)
SENIOR_FROM_YEARS = 3    # "Senior", "Lead" and "Staff" titles are shown from this much experience
EXEC_FROM_YEARS = 8      # "Director", "Head of", "VP" and "Principal" from this much


def gate_seniority(job: Job, s: Settings) -> Check:
    level = extract.title_seniority(job.title)
    y = s.experience_years
    if y is not None:
        if _EXEC_TITLE.search(job.title or "") and y < EXEC_FROM_YEARS:
            return Check("Seniority", False, f"A director-level title, above your {y:g} years.", job.title)
        if level == "senior" and y < SENIOR_FROM_YEARS:
            return Check("Seniority", False, "The title is a senior-level role.", job.title)
    elif level == "senior" and s.max_required_years < 3:
        return Check("Seniority", False, "The title is a senior-level role.", job.title)
    if s.experience_years is not None and s.experience_years >= 3 and (level == "junior" or _ENTRY_TITLE.search(job.title or "")):
        return Check("Seniority", False, f"An entry-level title, below your {s.experience_years:g} years.", job.title)
    return Check("Seniority", True, level or "Not stated in title", job.title)


def gate_experience(job: Job, s: Settings) -> Check:
    f = _facts(job)
    if f is not None:
        req = extract.ExperienceReq(f.get("expMin"), f.get("fresherOk"), f.get("expQuote") or "")
    else:
        req = extract.extract_experience(job.description, header=str(job.raw.get("experience_header", "")))
    ty = extract.title_years(job.title)
    if ty is not None and (req.min_years is None or ty > req.min_years):
        req = extract.ExperienceReq(ty, req.fresher_ok, job.title)
    if req.min_years is not None and req.min_years > s.max_required_years:
        return Check(
            "Experience", False,
            f"Asks for {req.describe()}; your limit is {s.max_required_years:g} year(s).", req.quote,
        )
    if req.min_years is None and req.fresher_ok is False and s.max_required_years < 1:
        return Check("Experience", False, "The posting says it isn't open to freshers.", req.quote)
    return Check("Experience", True, req.describe(), req.quote)


def gate_freshness(job: Job, s: Settings, now: datetime) -> tuple[Check, bool]:
    posted = _parse_dt(job.posted_at)
    if not posted:
        return Check("Posted", True, "Posting date not shown"), False
    days = (now - posted).total_seconds() / 86400
    hours = days * 24
    label = f"{int(hours)}h ago" if hours < 48 else f"{int(days)} days ago"
    if days > s.ghost_after_days:
        return Check("Posted", False, f"Open for {int(days)} days, which usually means a stale or evergreen listing."), False
    if days > s.max_posting_age_days:
        return Check("Posted", False, f"Posted {label}; your window is {s.max_posting_age_days} days."), False
    return Check("Posted", True, f"Posted {label}"), hours <= s.priority_within_hours


def gate_open(job: Job, today: date) -> Check:
    f = _facts(job)
    q = (f.get("closedQuote") or "") if f is not None else extract.closed_signal(job.description)
    if q:
        return Check("Open", False, "The posting says it's closed.", q)
    if job.apply_by:
        try:
            deadline = date.fromisoformat(job.apply_by)
        except ValueError:
            deadline = None
        if deadline and deadline < today:
            return Check("Open", False, f"Applications closed on {deadline.isoformat()}.")
    return Check("Open", True, f"Open{', apply by ' + job.apply_by if job.apply_by else ''}")


def _believed(scope: extract.RemoteScope, job: Job) -> extract.RemoteScope:
    """A stored "open worldwide" is dropped when its sentence turns out to be a perk or a line about the
    company's reach (feeds written before the scanner learned to tell them apart)."""
    if scope.scope == "worldwide" and scope.quote and scope.quote.strip() != (job.location or "").strip() and extract.is_perk(scope.quote):
        return extract.RemoteScope(None, "", "")
    return scope


def _gate_location_elsewhere(job: Job, s: Settings) -> tuple[Check, str]:
    """For someone living outside India: remote roles open to their country or region, and on-site or
    hybrid roles in the places they listed."""
    p = s.location
    home, name = p.home, countries.name_of(p.home)
    if job.work_mode == "remote":
        if not p.remote_ok:
            return Check("Location", False, "Remote roles are switched off."), ""
        said = countries.named(job.title or "") | countries.resolve(job.location or "")
        if said:
            if home in said:
                return Check("Location", True, f"Remote, {name}", job.location or job.title), "remote-local"
            return Check("Location", False, f"Remote, but only for people in {', '.join(sorted(countries.name_of(c) for c in said))}.", job.location or job.title), ""
        m = extract.tz_range(f"{job.location}\n{job.description or ''}")
        if m:
            a, b, quote = m
            ok = a <= countries.OFFSETS.get(home, 0) <= b
            return Check("Location", ok, "Remote, in your time zone range" if ok else "Remote, but the time-zone range excludes you.", quote), "remote-global" if ok else ""
        scope = extract.remote_scope(job.location, job.description)
        fits = countries.in_region(home, scope.scope) if scope.scope else None
        if fits is True:
            return Check("Location", True, "Remote worldwide" if scope.scope == "worldwide" else f"Remote ({scope.scope}), open to {name}", scope.quote or job.location),\
                "remote-global" if scope.scope == "worldwide" else "remote-local"
        if fits is False:
            return Check("Location", False, f"Remote, but only for people in another region ({scope.scope}).", scope.quote or job.location), ""
        if p.keep_unclear_remote:
            # Kept, but in a region of its own: it is shown after the roles known to be open to this person.
            return Check("Location", True, "Remote; the posting doesn't say who can apply. Check before applying.", job.location), "remote-unclear"
        return Check("Location", False, f"Remote, but the posting doesn't say people in {name} can apply.", job.location), ""
    mode_txt = {"hybrid": "Hybrid", "onsite": "On-site"}.get(job.work_mode, "Work mode not stated")
    loc = job.location or ""
    hit = next((pl for pl in p.places if re.search(r"(?<![A-Za-z])" + re.escape(pl) + r"(?![A-Za-z])", loc, re.I)), None)
    if hit is None:
        hit = next((pl for pl in p.places if countries.resolve(pl) & countries.resolve(loc)), None)
    if hit:
        return Check("Location", True, f"{mode_txt}, {loc}", loc), "local"
    if not loc.strip():
        return Check("Location", True, "Location not stated. Check before applying.", loc), "local"
    return Check("Location", False, f"{mode_txt} in {loc}, outside the places you chose.", loc), ""


def gate_location(job: Job, s: Settings) -> tuple[Check, str]:
    p = s.location
    if p.by_places:
        return _gate_location_elsewhere(job, s)
    mode = job.work_mode
    where = geo.classify(job.location)
    if mode == "remote":
        # A country in the title ("Product Engineer (Remote/US)") outranks a vague location field.
        t = extract.remote_scope(job.title or "", "")
        if t.india_eligible is False:
            who = {"us": "people in the US or Canada", "europe": "people in Europe", "americas": "people in the Americas"}.get(t.scope, t.scope)
            return Check("Location", False, f"Remote, but only for {who} (says the title).", job.title), ""
        if t.scope == "india" and p.rest_of_india != "never":
            return Check("Location", True, "Remote, India (says the title)", job.title), "remote-india"
        f = _facts(job)
        if f is not None and "scope" in f:
            scope = _believed(extract.RemoteScope(f.get("scopeEligible"), f.get("scope") or "", f.get("scopeQuote") or ""), job)
        else:
            scope = extract.remote_scope(job.location, job.description)
        # "Remote - Berlin", "Kyiv, Ukraine", "Poland": a remote role placed in one country is almost always
        # hired in that country (payroll and employment law), unless the posting says otherwise.
        named = countries.resolve(job.location or "")
        if named and "IN" not in named and not where["india"] and scope.scope != "worldwide" and not (scope.india_eligible and scope.scope != "india"):
            return Check("Location", False, f"Remote, but placed in {job.location.strip()}; the posting doesn't say people in India can apply.", job.location), ""
        if scope.scope == "worldwide":
            if p.abroad == "never":
                return Check("Location", False, "Remote roles at companies abroad are switched off.", scope.quote), ""
            return Check("Location", True, "Remote worldwide", scope.quote), "remote-global"
        if where["india"] or scope.scope == "india":
            if p.rest_of_india == "never" and not where["south"]:
                return Check("Location", False, "Remote roles in India are switched off."), ""
            return Check("Location", True, "Remote, India", scope.quote or job.location), "remote-india"
        if scope.india_eligible is True:
            if p.abroad == "never":
                return Check("Location", False, "Remote roles at companies abroad are switched off.", scope.quote), ""
            return Check("Location", True, f"Remote ({scope.scope}), open to India", scope.quote), "remote-global"
        if scope.india_eligible is False:
            who = {"us": "people in the US", "europe": "people in Europe", "americas": "people in the Americas", "timezone": "a time-zone range that excludes India"}.get(scope.scope, scope.scope)
            return Check("Location", False, f"Remote, but only for {who}.", scope.quote), ""
        if p.abroad == "never":
            return Check("Location", False, "Remote abroad is switched off."), ""
        if p.keep_unclear_remote:
            return Check("Location", True, "Remote; the posting doesn't say who can apply. Check before applying.", job.location), "remote-global"
        return Check("Location", False, "Remote, but the posting doesn't say people in India can apply.", job.location), ""

    mode_txt = {"hybrid": "Hybrid", "onsite": "On-site"}.get(mode, "Work mode not stated")
    if where["south"]:
        if p.south_india == "any" or (p.south_india == "remote" and mode == "remote"):
            return Check("Location", True, f"{mode_txt}, {where['south'].title()} (south India)", job.location), "south-india"
        return Check("Location", False, f"{mode_txt} in south India, and you only want remote there.", job.location), ""
    if where["india"]:
        if p.rest_of_india == "any":
            return Check("Location", True, f"{mode_txt}, {job.location}", job.location), "south-india"
        return Check("Location", False, f"{mode_txt} in {job.location}. Outside south India you only want remote roles.", job.location), ""
    if where["abroad"]:
        return Check("Location", False, f"{mode_txt} abroad ({job.location}).", job.location), ""
    return Check("Location", True, "Location not stated. Check before applying.", job.location), "south-india"


def gate_pay(job: Job, s: Settings) -> tuple[Check, extract.Salary | None]:
    f = _facts(job)
    sal = extract.parse_salary(job.salary_text, s.usd_inr)
    if not sal and f is not None and f.get("salaryHigh") is not None:
        sal = extract.Salary(f.get("salaryLow") or f["salaryHigh"], f["salaryHigh"], "", "year", f.get("salaryQuote") or "")
    if not sal and f is None:
        sal = extract.parse_salary(job.description, s.usd_inr, structured=False)
    if not sal:
        from . import paydata
        band = (f or {}).get("payBand") if f is not None else paydata.band(job.company)
        floor = s.salary_floor_lpa
        if band and (floor is None or band["low"] >= floor):
            return Check("Pay", True, f"Not stated; public data: {paydata.describe(band)}", band.get("url", "")), None
        if s.require_stated_pay and floor is not None:
            why = f" Public data for freshers here: {paydata.describe(band)}." if band else ""
            return Check("Pay", False, f"Pay not stated; you only want roles that state {floor:g} LPA or more.{why}"), None
        return Check("Pay", True, "Not stated"), None
    if s.salary_floor_lpa is not None and sal.high_lpa < s.salary_floor_lpa:
        return Check("Pay", False, f"Pays {sal.describe()}, below your {s.salary_floor_lpa:g} LPA floor.", sal.quote), sal
    return Check("Pay", True, sal.describe(), sal.quote), sal


_REGION_LOC = {"remote-global": "remote-open", "remote-india": "remote-india", "south-india": "india"}


def gate_work_auth(job: Job, region: str, home: str = "IN", by_places: bool = False) -> Check:
    """Citizenship, security clearance or local work authorization for a country other than where the
    person lives rules a role out, however well it fits."""
    f = _facts(job)
    wa = (f.get("workAuth") or {}) if f is not None and "loc" in f else signals.work_authorization(job.description)
    if (home or "IN") != "IN" or by_places:
        if not wa:
            return Check("Work authorization", True, "No restriction stated")
        needs = countries.named(wa.get("country") or "")
        if wa["kind"] in ("citizenship", "local") and needs and home not in needs:
            return Check("Work authorization", False, f"Requires {'citizenship of' if wa['kind'] == 'citizenship' else 'authorization to work in'} {wa.get('country')}.", wa.get("quote", ""))
        if wa["kind"] == "clearance" and home != "US":
            return Check("Work authorization", False, "Requires a security clearance.", wa.get("quote", ""))
        if wa["kind"] == "no-sponsorship" and region == "local":
            return Check("Work authorization", True, "No visa sponsorship; check you can already work there.", wa.get("quote", ""))
        return Check("Work authorization", True, f"Needs authorization to work in {wa.get('country') or 'the country'}." if wa.get("country") else "Check the work authorization the posting asks for.", wa.get("quote", ""))
    loc = (f or {}).get("loc") or _REGION_LOC.get(region, "abroad")
    if signals.work_auth_blocks(wa, loc):
        what = {"citizenship": f"{wa.get('country') or 'local'} citizenship", "clearance": "a security clearance",
                "local": f"authorization to work in {wa.get('country') or 'another country'}",
                "no-sponsorship": "local work authorization (no visa sponsorship)"}[wa["kind"]]
        return Check("Work authorization", False, f"Requires {what}.", wa.get("quote", ""))
    if wa.get("kind") == "no-sponsorship":
        return Check("Work authorization", True, "No visa sponsorship, which remote work from India doesn't need.", wa.get("quote", ""))
    if wa:
        return Check("Work authorization", True, f"Needs authorization to work in {wa.get('country')}.", wa.get("quote", ""))
    return Check("Work authorization", True, "No restriction stated")


def gate_sponsorship(job: Job, region: str, s: Settings) -> Check | None:
    """For someone who needs a visa to work where the role is: a posting that says it cannot sponsor,
    or (UK) an employer missing from the Home Office register of licensed sponsors, rules the role out.
    A posting that says nothing passes as "unclear", with the reason shown; it is never guessed."""
    if not s.needs_sponsorship:
        return None
    f = _facts(job)
    if s.location.elsewhere:
        # Living in India, looking abroad: an office role in a chosen country needs a visa; remote work from India does not.
        on_site_abroad = region == "local" and "IN" not in countries.resolve(job.location or "")
    elif (s.location.home or "IN") != "IN":
        # Someone on a visa where they live needs sponsorship for any role based there, in an office or remote.
        on_site_abroad = region in ("local", "remote-local")
    else:
        loc = (f or {}).get("loc") if f is not None and "loc" in f else ("abroad" if geo.classify(job.location)["abroad"] else "")
        on_site_abroad = loc == "abroad" and not region.startswith("remote")
    if not on_site_abroad:
        return None
    v = (f.get("visa") or {}) if f is not None and "loc" in f else sponsors.visa_facts(job.company, job.location, job.description, job.salary_text)
    if v.get("status") == "no":
        return Check("Visa sponsorship", False, "Says it cannot sponsor a visa.", v.get("quote", ""))
    reg = v.get("ukRegister")
    if reg is not None and not reg.get("listed"):
        return Check("Visa sponsorship", False, "Not on the UK register of licensed sponsors, so it cannot sponsor a Skilled Worker visa.",
                     "Home Office register of licensed sponsors (Skilled Worker)")
    sal = v.get("ukSalary") or {}
    if sal.get("status") == "below":
        return Check("Visa sponsorship", False, f"Pays £{sal['amount']:,}, below the Skilled Worker salary floors.", sal.get("quote", ""))
    if v.get("status") == "offers":
        return Check("Visa sponsorship", True, sponsors.label(v), v.get("quote", ""))
    return Check("Visa sponsorship", True, sponsors.label(v) + ". Unclear: ask before applying.",
                 (reg or {}).get("name", "") and f"On the register as {reg['name']}")


def gate_dealbreakers(job: Job, s: Settings) -> Check:
    for word in s.dealbreakers:
        m = re.search(re.escape(word), job.description or "", re.I)
        if m:
            from .textutil import quote_around
            return Check("Dealbreaker", False, f"Mentions '{word}'.", quote_around(job.description, *m.span()))
    return Check("Dealbreaker", True, "None found")


def evaluate(job: Job, s: Settings, now: datetime | None = None) -> Decision:
    now = now or datetime.now(timezone.utc)
    checks: list[Check] = [gate_company(job, s), gate_role(job, s), gate_seniority(job, s), gate_experience(job, s)]
    fresh, priority = gate_freshness(job, s, now)
    checks += [fresh, gate_open(job, now.date())]
    loc, region = gate_location(job, s)
    pay, sal = gate_pay(job, s)
    checks += [loc, gate_work_auth(job, region, s.location.home, s.location.by_places), pay, gate_dealbreakers(job, s)]
    visa = gate_sponsorship(job, region, s)
    if visa is not None:
        checks.append(visa)
    if sal and not job.salary_text:
        job.salary_text = sal.describe()
    kept = all(c.passed for c in checks)
    return Decision(kept, checks, region if kept else "", priority if kept else False)


def apply_decision(job: Job, s: Settings, now: datetime | None = None) -> Decision:
    d = evaluate(job, s, now)
    job.checks = d.checks
    job.region = d.region
    job.priority = d.priority
    job.stage = "found" if d.kept else "skipped"
    job.found_at = job.found_at or iso(now or datetime.now(timezone.utc))
    return d
