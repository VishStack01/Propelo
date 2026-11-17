"""Business accounts.

Consultancy: a study-abroad consultancy (or a college placement cell) gets a branded space, an invite
link and a number of seats. Each student who joins gets the paid plan while the partner is active and a
seat is free. The consultancy sees each student's progress (roles matched, applications, interviews,
offers) and nothing else: no resume, no messages, no answers. The student agrees to that when joining
and can leave at any time.

Agency: a recruiting agency gets a filtered feed of open roles from the shared inventory (company,
title, place, how long it has been open, what the posting says about visa sponsorship, the UK sponsor
register), as CSV or JSON, with its own key. No personal data is in it: roles only.

Billing for business accounts is agreed and invoiced by hand at first (payment links); `billing` keeps
what was agreed and `status` / `ends_at` switch access on and off.
"""

from __future__ import annotations

import base64
import csv
import io
import json
import re
import secrets
import uuid
from datetime import datetime, timezone

from .. import countries
from . import repo
from .db import Conn, now_iso
from .security import new_token, token_hash

KINDS = ("consultancy", "agency")
STATUSES = ("pilot", "active", "paused", "ended")
LIVE = ("pilot", "active")
STUDENT_PLANS = ("pro", "ultra")
CONSENT = ("{name} will see your progress: how many roles were matched to you, how many you applied to, and "
           "your interviews and offers (company and role). They will not see your resume, answers or messages. "
           "You can leave at any time in Settings.")
LOGO_MAX = 200 * 1024
_LOGO = re.compile(r"^data:image/(png|jpeg|webp);base64,([A-Za-z0-9+/=]+)$")
_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")
INTERVIEW_STAGES = ("screen", "interview", "offer")
FEED_SOURCES = ("careers-feed", "remote-board")
FEED_COLUMNS = ["company", "title", "location", "work_mode", "days_open", "first_seen", "posted_at", "sponsorship",
                "sponsorship_quote", "uk_sponsor_register", "salary", "ats", "url"]


class PartnerError(ValueError):
    pass


# ---------------------------------------------------------------- records

def _load(r: dict | None) -> dict | None:
    if not r:
        return None
    out = dict(r)
    for k in ("brand", "filters", "billing"):
        try:
            out[k] = json.loads(r.get(k) or "{}")
        except (TypeError, ValueError):
            out[k] = {}
    return out


def get(c: Conn, pid: str) -> dict | None:
    return _load(c.one("SELECT * FROM partners WHERE id = ?", (pid,)))


def by_code(c: Conn, code: str) -> dict | None:
    return _load(c.one("SELECT * FROM partners WHERE invite_code = ?", ((code or "")[:40],)))


def by_slug(c: Conn, slug: str) -> dict | None:
    return _load(c.one("SELECT * FROM partners WHERE slug = ?", ((slug or "")[:60],)))


def is_live(p: dict | None, now: str | None = None) -> bool:
    return bool(p) and p["status"] in LIVE and (not p.get("ends_at") or p["ends_at"] > (now or now_iso()))


def slugify(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")[:40]
    return s or "partner"


def _code() -> str:
    return secrets.token_urlsafe(9).replace("-", "x").replace("_", "y")


def clean_brand(b: dict) -> dict:
    b = b or {}
    out = {}
    color = str(b.get("color") or "").strip()
    if color:
        if not _COLOR.match(color):
            raise PartnerError("The colour must look like #1F6F5C.")
        out["color"] = color
    for k, n in (("tagline", 140), ("website", 200), ("contactEmail", 120)):
        v = str(b.get(k) or "").strip()[:n]
        if v:
            if k == "website" and not re.match(r"^https://", v):
                raise PartnerError("The website must start with https://")
            out[k] = v
    return out


def clean_filters(f: dict) -> dict:
    """Agency feed filters. Every field optional."""
    f = f or {}
    out: dict = {}
    words = lambda v: [w.strip().lower()[:40] for w in (v if isinstance(v, list) else re.split(r"[,\n]", str(v or ""))) if w.strip()][:30]
    if words(f.get("keywords")):
        out["keywords"] = words(f.get("keywords"))
    if words(f.get("exclude")):
        out["exclude"] = words(f.get("exclude"))
    cs = [str(x).upper()[:2] for x in (f.get("countries") or []) if str(x).upper()[:2] in countries.NAMES][:20]
    if cs:
        out["countries"] = cs
    if words(f.get("cities")):
        out["cities"] = words(f.get("cities"))
    remote = str(f.get("remote") or "any")
    if remote not in ("any", "exclude", "only"):
        raise PartnerError("Remote must be any, exclude or only.")
    out["remote"] = remote
    try:
        out["minDaysOpen"] = max(0, min(365, int(f.get("minDaysOpen") or 0)))
    except (TypeError, ValueError):
        raise PartnerError("Minimum days open must be a number.")
    sponsor = str(f.get("sponsor") or "")
    if sponsor not in ("", "offers", "not-no", "uk-register"):
        raise PartnerError("Sponsorship filter must be offers, not-no or uk-register.")
    if sponsor:
        out["sponsor"] = sponsor
    try:
        out["limit"] = max(1, min(2000, int(f.get("limit") or 500)))
    except (TypeError, ValueError):
        out["limit"] = 500
    return out


def create(c: Conn, kind: str, name: str, by: str, seats: int = 0, status: str = "pilot", ends_at: str | None = None,
           brand: dict | None = None, filters: dict | None = None, billing: dict | None = None,
           student_plan: str = "pro") -> tuple[dict, str | None]:
    """A new business account. Returns (partner, feed_key); the feed key (agencies) is shown only once."""
    if kind not in KINDS:
        raise PartnerError("Kind must be consultancy or agency.")
    name = (name or "").strip()[:80]
    if len(name) < 2:
        raise PartnerError("Give the business a name.")
    if status not in STATUSES:
        raise PartnerError("Unknown status.")
    if student_plan not in STUDENT_PLANS:
        raise PartnerError("Students get pro or ultra.")
    base, slug, n = slugify(name), slugify(name), 1
    while c.one("SELECT 1 AS x FROM partners WHERE slug = ?", (slug,)):
        n += 1
        slug = f"{base}-{n}"
    key = new_token("cos_f_") if kind == "agency" else None
    now = now_iso()
    pid = uuid.uuid4().hex
    c.execute("INSERT INTO partners(id, kind, name, slug, status, seats, student_plan, invite_code, brand, filters, feed_key_hash, billing, ends_at, "
              "created_by, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
              (pid, kind, name, slug, status, max(0, min(5000, int(seats or 0))), student_plan, _code(),
               json.dumps(clean_brand(brand or {})), json.dumps(clean_filters(filters or {}) if kind == "agency" else {}),
               token_hash(key) if key else None, json.dumps(billing or {}), ends_at, by, now, now))
    return get(c, pid), key


def update(c: Conn, pid: str, changes: dict) -> dict:
    p = get(c, pid)
    if not p:
        raise PartnerError("Not found.")
    sets, vals = [], []
    if "status" in changes:
        if changes["status"] not in STATUSES:
            raise PartnerError("Unknown status.")
        sets.append("status = ?"); vals.append(changes["status"])
    if "seats" in changes:
        sets.append("seats = ?"); vals.append(max(0, min(5000, int(changes["seats"] or 0))))
    if "endsAt" in changes:
        sets.append("ends_at = ?"); vals.append(changes["endsAt"] or None)
    if "name" in changes and str(changes["name"]).strip():
        sets.append("name = ?"); vals.append(str(changes["name"]).strip()[:80])
    if "brand" in changes:
        sets.append("brand = ?"); vals.append(json.dumps(clean_brand(changes["brand"])))
    if "filters" in changes and p["kind"] == "agency":
        sets.append("filters = ?"); vals.append(json.dumps(clean_filters(changes["filters"])))
    if "billing" in changes:
        b = changes["billing"] or {}
        sets.append("billing = ?"); vals.append(json.dumps({k: str(b.get(k) or "")[:200] for k in ("amount", "currency", "note")}))
    if "studentPlan" in changes:
        if changes["studentPlan"] not in STUDENT_PLANS:
            raise PartnerError("Students get pro or ultra.")
        sets.append("student_plan = ?"); vals.append(changes["studentPlan"])
    if sets:
        c.execute(f"UPDATE partners SET {', '.join(sets)}, updated_at = ? WHERE id = ?", (*vals, now_iso(), pid))
    return get(c, pid)


def set_logo(c: Conn, pid: str, data_url: str | None) -> None:
    if not data_url:
        c.execute("UPDATE partners SET logo = NULL, updated_at = ? WHERE id = ?", (now_iso(), pid))
        return
    m = _LOGO.match(data_url.strip())
    if not m:
        raise PartnerError("The logo must be a PNG, JPEG or WebP image.")
    if len(base64.b64decode(m.group(2))) > LOGO_MAX:
        raise PartnerError("The logo must be under 200 KB.")
    c.execute("UPDATE partners SET logo = ?, updated_at = ? WHERE id = ?", (data_url.strip(), now_iso(), pid))


def logo_bytes(p: dict | None) -> tuple[bytes, str] | None:
    m = _LOGO.match((p or {}).get("logo") or "")
    return (base64.b64decode(m.group(2)), "image/" + m.group(1)) if m else None


def rotate_code(c: Conn, pid: str) -> str:
    code = _code()
    c.execute("UPDATE partners SET invite_code = ?, updated_at = ? WHERE id = ?", (code, now_iso(), pid))
    return code


def rotate_key(c: Conn, pid: str) -> str:
    key = new_token("cos_f_")
    c.execute("UPDATE partners SET feed_key_hash = ?, updated_at = ? WHERE id = ?", (token_hash(key), now_iso(), pid))
    return key


def by_key(c: Conn, key: str) -> dict | None:
    if not (key or "").startswith("cos_f_"):
        return None
    return _load(c.one("SELECT * FROM partners WHERE feed_key_hash = ? AND kind = 'agency'", (token_hash(key),)))


# ---------------------------------------------------------------- members

def add_admin(c: Conn, pid: str, uid: str) -> None:
    now = now_iso()
    if c.one("SELECT 1 AS x FROM partner_members WHERE partner_id = ? AND user_id = ?", (pid, uid)):
        c.execute("UPDATE partner_members SET role = 'admin', status = 'active', updated_at = ? WHERE partner_id = ? AND user_id = ?", (now, pid, uid))
    else:
        c.execute("INSERT INTO partner_members(partner_id, user_id, role, status, consent, joined_at, updated_at) VALUES (?, ?, 'admin', 'active', '', ?, ?)",
                  (pid, uid, now, now))


def seats_used(c: Conn, pid: str) -> int:
    return int(c.scalar("SELECT COUNT(*) FROM partner_members WHERE partner_id = ? AND role = 'student' AND status = 'active'", (pid,)) or 0)


def join(c: Conn, code: str, uid: str, consent: bool) -> dict:
    p = by_code(c, code)
    if not p or p["kind"] != "consultancy" or not is_live(p):
        raise PartnerError("This invite link isn't valid any more. Ask your consultancy for a new one.")
    if not consent:
        raise PartnerError("Agree to what your consultancy will see first.")
    cur = c.one("SELECT partner_id FROM partner_members WHERE user_id = ? AND role = 'student' AND status = 'active'", (uid,))
    if cur and cur["partner_id"] != p["id"]:
        raise PartnerError("You're already with another consultancy. Leave it in Settings first.")
    row = c.one("SELECT status FROM partner_members WHERE partner_id = ? AND user_id = ?", (p["id"], uid))
    if row and row["status"] == "active":
        return p
    if seats_used(c, p["id"]) >= int(p["seats"] or 0):
        raise PartnerError(f"{p['name']} has used all its seats. Ask them to add more.")
    now = now_iso()
    note = json.dumps({"text": CONSENT.format(name=p["name"]), "at": now})
    if row:
        c.execute("UPDATE partner_members SET role = 'student', status = 'active', consent = ?, joined_at = ?, updated_at = ? WHERE partner_id = ? AND user_id = ?",
                  (note, now, now, p["id"], uid))
    else:
        c.execute("INSERT INTO partner_members(partner_id, user_id, role, status, consent, joined_at, updated_at) VALUES (?, ?, 'student', 'active', ?, ?, ?)",
                  (p["id"], uid, note, now, now))
    return p


def leave(c: Conn, uid: str) -> None:
    c.execute("UPDATE partner_members SET status = 'left', updated_at = ? WHERE user_id = ? AND role = 'student' AND status = 'active'", (now_iso(), uid))


def remove(c: Conn, pid: str, uid: str) -> None:
    c.execute("UPDATE partner_members SET status = 'removed', updated_at = ? WHERE partner_id = ? AND user_id = ? AND role = 'student'", (now_iso(), pid, uid))


def student_of(c: Conn, uid: str) -> dict | None:
    """The live consultancy a student belongs to, or None."""
    r = c.one("SELECT partner_id FROM partner_members WHERE user_id = ? AND role = 'student' AND status = 'active'", (uid,))
    p = get(c, r["partner_id"]) if r else None
    return p if is_live(p) else None


def seat_plan(c: Conn, uid: str) -> str | None:
    """The plan a student gets from their consultancy right now, or None. Called by plans.plan_of."""
    p = student_of(c, uid)
    return p["student_plan"] if p else None


def admin_partners(c: Conn, uid: str) -> list[dict]:
    rows = c.all("SELECT partner_id FROM partner_members WHERE user_id = ? AND role = 'admin' AND status = 'active'", (uid,))
    return [p for p in (get(c, r["partner_id"]) for r in rows) if p]


def branding(p: dict | None) -> dict | None:
    if not p:
        return None
    return {"name": p["name"], "slug": p["slug"], "logo": f"/api/partner-logo/{p['slug']}" if p.get("logo") else "",
            **{k: v for k, v in p["brand"].items() if k in ("color", "tagline", "website", "contactEmail")}}


# ---------------------------------------------------------------- what a consultancy sees

def _dt(s) -> datetime | None:
    try:
        d = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def student_progress(c: Conn, uid: str) -> dict:
    jobs = [d["data"] for d in repo.list_docs(c, uid, "jobs")]
    matched = sum(1 for j in jobs if j.get("foundVia") in FEED_SOURCES and j.get("stage") != "skipped")
    applied = [j for j in jobs if j.get("appliedAt")]
    interviews = [j for j in jobs if j.get("stage") in INTERVIEW_STAGES or j.get("screenAt") or j.get("interviewStartedAt")]
    offers = [j for j in jobs if j.get("stage") == "offer" or j.get("offerAt")]
    sponsor = sum(1 for j in jobs if (j.get("visa") or {}).get("status") == "offers" or ((j.get("visa") or {}).get("ukRegister") or {}).get("listed"))
    last = max((d for d in (_dt(j.get(k)) for j in jobs for k in ("appliedAt", "updatedAt", "foundAt")) if d), default=None)
    return {"matched": matched, "applied": len(applied), "interviews": len(interviews), "offers": len(offers), "sponsorRoles": sponsor,
            "interviewRoles": [{"company": str(j.get("company") or "")[:80], "title": str(j.get("title") or "")[:120], "stage": j.get("stage") or ""}
                               for j in interviews][:10],
            "lastActive": last.isoformat() if last else None}


def view(c: Conn, p: dict, public_url: str) -> dict:
    """What the partner's admins see."""
    out = {"id": p["id"], "kind": p["kind"], "name": p["name"], "slug": p["slug"], "status": p["status"], "live": is_live(p),
           "endsAt": p.get("ends_at"), "brand": p["brand"], "logo": bool(p.get("logo")), "branding": branding(p)}
    if p["kind"] == "consultancy":
        rows = c.all("SELECT m.user_id, m.joined_at, m.status, u.name, u.email FROM partner_members m JOIN users u ON u.id = m.user_id "
                     "WHERE m.partner_id = ? AND m.role = 'student' AND m.status = 'active' ORDER BY m.joined_at", (p["id"],))
        students = [{"id": r["user_id"], "name": r["name"], "email": r["email"], "joinedAt": r["joined_at"], **student_progress(c, r["user_id"])} for r in rows]
        out.update({"seats": int(p["seats"] or 0), "seatsUsed": len(students), "studentPlan": p["student_plan"],
                    "inviteUrl": f"{public_url}/join/{p['invite_code']}", "students": students,
                    "totals": {k: sum(s[k] for s in students) for k in ("matched", "applied", "interviews", "offers")}})
    else:
        out.update({"filters": p["filters"], "hasKey": bool(p.get("feed_key_hash")),
                    "feedUrl": f"{public_url}/api/partner-feed/{p['slug']}.csv", "feedJsonUrl": f"{public_url}/api/partner-feed/{p['slug']}.json"})
    return out


def staff_row(c: Conn, p: dict) -> dict:
    admins = c.all("SELECT u.email FROM partner_members m JOIN users u ON u.id = m.user_id WHERE m.partner_id = ? AND m.role = 'admin' AND m.status = 'active'", (p["id"],))
    return {"id": p["id"], "kind": p["kind"], "name": p["name"], "slug": p["slug"], "status": p["status"], "seats": int(p["seats"] or 0),
            "seatsUsed": seats_used(c, p["id"]) if p["kind"] == "consultancy" else None, "endsAt": p.get("ends_at"),
            "billing": p["billing"], "admins": [a["email"] for a in admins], "filters": p["filters"], "createdAt": p["created_at"],
            "inviteCode": p["invite_code"] if p["kind"] == "consultancy" else None, "live": is_live(p)}


# ---------------------------------------------------------------- the agency feed

def _record(r: dict) -> dict:
    try:
        return json.loads(r.get("record") or "{}")
    except (TypeError, ValueError):
        return {}


def _days_open(rec: dict, first_seen_at: str, today: datetime) -> int | None:
    f = rec.get("facts") or {}
    if f.get("daysOpen") is not None:
        return int(f["daysOpen"])
    starts = [d for d in (_dt(rec.get("postedAt")), _dt(first_seen_at)) if d]
    return max(0, (today - min(starts)).days) if starts else None


def match_record(rec: dict, f: dict, today: datetime, first_seen_at: str = "") -> dict | None:
    """One feed record as an agency row when it passes the filters, else None."""
    title = (rec.get("title") or "").lower()
    kw, ex = f.get("keywords") or [], f.get("exclude") or []
    if kw and not any(k in title for k in kw):
        return None
    if ex and any(k in title for k in ex):
        return None
    loc = rec.get("location") or ""
    mode = (rec.get("workMode") or "").lower()
    remote = mode == "remote" or "remote" in loc.lower()
    if (f.get("remote") == "exclude" and remote) or (f.get("remote") == "only" and not remote):
        return None
    cs, cities = set(f.get("countries") or []), f.get("cities") or []
    if cs and not (countries.named(loc) & cs):
        return None
    if cities and not any(x in loc.lower() for x in cities):
        return None
    days = _days_open(rec, first_seen_at, today)
    if f.get("minDaysOpen") and (days is None or days < f["minDaysOpen"]):
        return None
    facts = rec.get("facts") or {}
    visa = facts.get("visa") or {}
    sp = f.get("sponsor")
    if (sp == "offers" and visa.get("status") != "offers") or (sp == "not-no" and visa.get("status") == "no") \
            or (sp == "uk-register" and not (visa.get("ukRegister") or {}).get("listed")):
        return None
    reg = visa.get("ukRegister")
    return {
        "company": rec.get("company") or "", "title": rec.get("title") or "", "location": loc, "work_mode": mode,
        "days_open": days if days is not None else "", "first_seen": facts.get("firstSeen") or str(first_seen_at or "")[:10],
        "posted_at": str(rec.get("postedAt") or "")[:10],
        "sponsorship": {"offers": "says it sponsors", "no": "says it cannot sponsor"}.get(visa.get("status"), "not stated"),
        "sponsorship_quote": visa.get("quote", ""),
        "uk_sponsor_register": "" if reg is None else ("listed" if reg.get("listed") else "not listed"),
        "salary": rec.get("salary") or "", "ats": rec.get("source") or "", "url": rec.get("url") or "",
    }


def _sort_cut(rows: list[dict], f: dict) -> list[dict]:
    rows.sort(key=lambda x: (-(x["days_open"] if isinstance(x["days_open"], int) else -1), x["company"]))
    return rows[: int(f.get("limit") or 500)]


def feed_rows(c: Conn, filters: dict, now: datetime | None = None) -> list[dict]:
    """Open roles from the shared inventory that match an agency's filters, longest-open first."""
    today = now or datetime.now(timezone.utc)
    f = filters or {}
    out = []
    for r in c.all("SELECT company, title, url, source, posted_at, record, first_seen_at FROM jobs WHERE active = 1"):
        rec = {**_record(r), "company": r["company"], "title": r["title"], "url": r["url"], "source": r["source"],
               "postedAt": _record(r).get("postedAt") or r["posted_at"]}
        row = match_record(rec, f, today, r["first_seen_at"])
        if row:
            out.append(row)
    return _sort_cut(out, f)


def records_rows(records: list[dict], filters: dict, now: datetime | None = None) -> list[dict]:
    """The same, straight from feed records (india.jsonl.gz): for free samples sent in outreach."""
    today = now or datetime.now(timezone.utc)
    f = clean_filters(filters or {})
    return _sort_cut([row for row in (match_record(r, f, today) for r in records) if row], f)


def to_csv(rows: list[dict]) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=FEED_COLUMNS, extrasaction="ignore")
    w.writeheader()
    for r in rows:
        # Spreadsheet formula injection: a cell starting with = + - @ is read as a formula.
        w.writerow({k: ("'" + v if isinstance(v, str) and v[:1] in ("=", "+", "-", "@") else v) for k, v in r.items()})
    return buf.getvalue()
