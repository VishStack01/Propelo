"""Propelo Concierge: an optional, human-run job search, paid only after the candidate joins.

How it works, and the rules the code holds to:
  - Concierge is part of the paid plans (Pro and Ultra): the monthly plan is the service charge. The
    candidate asks for it, fills an intake and accepts the Concierge terms (version and time
    recorded). A talent partner on the Propelo team takes the case. If the plan ends, the case
    pauses until the candidate is on a paid plan again.
  - The partner proposes companies and roles. Nothing is sent anywhere until the candidate approves
    each one in the app; the approval time is the record of who introduced the role.
  - Partners work through Propelo and the candidate's approvals. They never sign in as the candidate
    on any site, and LinkedIn is never automated.
  - When the candidate accepts an offer from a company they approved through Concierge (within
    ATTRIBUTION_DAYS of approving it), a fee is due: RATE_LOW% of the fixed CTC up to the band and
    RATE_HIGH% of the part above it, plus tax where it applies. Bonuses, stock and joining bonuses
    are not counted.
  - Nothing is paid upfront. The fee is split into instalments; the first is due 30 days after the
    joining date. If the employer ends the job within 90 days, unpaid instalments are cancelled.
  - Concierge runs only in CONCIERGE_COUNTRIES (India by default): charging job seekers a placement
    fee is banned or licensed in many countries.
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta, timezone

from . import plans, repo
from .config import Config
from .db import Conn, now_iso

TERMS_VERSION = "2026-11-15"
CASE_STATUSES = ("requested", "active", "paused", "offer", "placed", "closed")
SUB_STATUSES = ("proposed", "approved", "declined", "submitted", "interviewing", "offer", "rejected", "withdrawn")
STAFF_SUB_MOVES = {"approved": "submitted", "submitted": "interviewing", "interviewing": "offer"}
OPEN_CASE = ("requested", "active", "paused", "offer")
COUNTRY_CURRENCY = {"IN": "INR"}
# Charging a job seeker for finding work is prohibited here, whatever CONCIERGE_COUNTRIES says.
NEVER = {"GB", "UK"}


def countries(cfg: Config) -> tuple:
    return tuple(x for x in cfg.concierge_countries if x not in NEVER)


class ConciergeError(ValueError):
    pass


# ---------------------------------------------------------------- the fee
def fee_for(cfg: Config, fixed_ctc: int) -> dict:
    """Fee on a yearly fixed CTC: RATE_LOW% up to the band, RATE_HIGH% above it. Whole rupees."""
    ctc = max(0, int(fixed_ctc))
    band = cfg.concierge_band
    low = min(ctc, band) * cfg.concierge_rate_low / 100
    high = max(0, ctc - band) * cfg.concierge_rate_high / 100
    fee = int(round(low + high))
    tax = int(round(fee * cfg.concierge_tax_rate / 100))
    return {"fixedCtc": ctc, "fee": fee, "tax": tax, "total": fee + tax, "effectiveRate": round(100 * fee / ctc, 2) if ctc else 0,
            "rateLow": cfg.concierge_rate_low, "rateHigh": cfg.concierge_rate_high, "band": band, "taxRate": cfg.concierge_tax_rate}


def instalment_plan(cfg: Config, total_minor: int, joining: date) -> list[dict]:
    """Equal instalments in paise; the last absorbs the rounding. First due 30 days after joining."""
    n = max(1, cfg.concierge_instalments)
    part = total_minor // n
    out = []
    for i in range(n):
        amount = part if i < n - 1 else total_minor - part * (n - 1)
        out.append({"n": i + 1, "amount": amount, "due_on": (joining + timedelta(days=30 * (i + 1))).isoformat()})
    return out


# ---------------------------------------------------------------- reading
def case_of(c: Conn, uid: str) -> dict | None:
    return c.one("SELECT * FROM concierge_cases WHERE user_id = ?", (uid,))


def _sub_view(s: dict) -> dict:
    return {"id": s["id"], "company": s["company"], "title": s["title"], "url": s["url"], "why": s["why"], "status": s["status"],
            "proposedAt": s["proposed_at"], "approvedAt": s["approved_at"], "submittedAt": s["submitted_at"]}


def _placement_view(c: Conn, p: dict) -> dict:
    inst = c.all("SELECT * FROM concierge_instalments WHERE placement_id = ? ORDER BY n", (p["id"],))
    return {"id": p["id"], "company": p["company"], "fixedCtc": p["fixed_ctc"], "currency": p["currency"], "joiningDate": p["joining_date"],
            "fee": p["fee"], "taxRate": p["tax_rate"], "status": p["status"], "verifiedAt": p["verified_at"],
            "instalments": [{"id": i["id"], "n": i["n"], "amount": i["amount"], "currency": i["currency"], "dueOn": i["due_on"], "status": i["status"],
                             "paidAt": i["paid_at"], "payable": i["status"] in ("due", "link_sent") and i["due_on"] <= date.today().isoformat()} for i in inst]}


def view(c: Conn, cfg: Config, user: dict, country_hint: str = "") -> dict:
    """What the candidate sees."""
    case = case_of(c, user["id"])
    base = {"enabled": cfg.concierge_enabled, "countries": list(countries(cfg)), "termsVersion": TERMS_VERSION,
            "planAllows": plan_allows(c, user), "plans": list(PLANS_WITH_CONCIERGE),
            "eligibleHere": (country_hint or "IN").upper() in countries(cfg),
            "fee": {"rateLow": cfg.concierge_rate_low, "rateHigh": cfg.concierge_rate_high, "band": cfg.concierge_band,
                    "taxRate": cfg.concierge_tax_rate, "instalments": cfg.concierge_instalments, "attributionDays": cfg.concierge_attribution_days}}
    if not case:
        return dict(base, case=None)
    partner = c.one("SELECT name FROM users WHERE id = ?", (case["partner_id"],)) if case["partner_id"] else None
    subs = c.all("SELECT * FROM concierge_submissions WHERE case_id = ? ORDER BY proposed_at DESC", (case["id"],))
    notes = c.all("SELECT n.*, u.name AS author FROM concierge_notes n LEFT JOIN users u ON u.id = n.author_id "
                  "WHERE n.case_id = ? AND n.shared = 1 ORDER BY n.at", (case["id"],))
    places = c.all("SELECT * FROM concierge_placements WHERE case_id = ? ORDER BY created_at DESC", (case["id"],))
    return dict(base, case={
        "id": case["id"], "status": case["status"], "country": case["country"], "currency": case["currency"], "intake": json.loads(case["intake"]),
        "partner": {"name": (partner or {}).get("name") or "Your talent partner"} if case["partner_id"] else None,
        "agreedAt": case["agreed_at"], "termsVersion": case["terms_version"], "closedReason": case["closed_reason"],
        "submissions": [_sub_view(s) for s in subs],
        "messages": [{"id": n["id"], "from": "you" if n["author_id"] == user["id"] else (n["author"] or "Propelo"), "body": n["body"], "at": n["at"]} for n in notes],
        "placements": [_placement_view(c, p) for p in places]})


# ---------------------------------------------------------------- candidate actions
_PHONE = re.compile(r"^\+?[0-9][0-9 -]{7,18}$")


def clean_intake(raw: dict) -> dict:
    def text(k, n):
        return re.sub(r"\s+", " ", str(raw.get(k) or "")).strip()[:n]

    def money(k):
        try:
            v = int(float(str(raw.get(k) or 0).replace(",", "")))
        except ValueError:
            raise ConciergeError(f"{k} must be a number.") from None
        if v < 0 or v > 1_000_000_000:
            raise ConciergeError(f"{k} looks wrong.")
        return v
    out = {"roles": text("roles", 300), "locations": text("locations", 300), "currentCtc": money("currentCtc"), "expectedCtc": money("expectedCtc"),
           "noticeDays": max(0, min(180, int(raw.get("noticeDays") or 0))), "phone": text("phone", 20), "notes": str(raw.get("notes") or "").strip()[:2000]}
    if not out["roles"]:
        raise ConciergeError("Tell us which roles you want.")
    if out["phone"] and not _PHONE.match(out["phone"]):
        raise ConciergeError("That phone number looks wrong.")
    return out


PLANS_WITH_CONCIERGE = ("pro", "ultra")


def plan_allows(c: Conn, user: dict) -> bool:
    return plans.plan_of(c, user) in PLANS_WITH_CONCIERGE


def pause_lapsed(c: Conn) -> int:
    """Pause open cases whose plan ended. Run hourly by the worker."""
    n = 0
    for r in c.all("SELECT k.id, u.id AS uid, u.is_admin FROM concierge_cases k JOIN users u ON u.id = k.user_id WHERE k.status IN ('requested', 'active')"):
        if not plan_allows(c, {"id": r["uid"], "is_admin": r["is_admin"]}):
            set_status(c, r["id"], "paused", "Your plan ended. Concierge resumes when you're on Pro or Ultra again.")
            n += 1
    return n


def request(c: Conn, cfg: Config, uid: str, country: str, intake: dict, ip: str, user: dict | None = None) -> dict:
    if not cfg.concierge_enabled:
        raise ConciergeError("Concierge isn't available on this server.")
    if user is not None and not plan_allows(c, user):
        raise ConciergeError("Concierge is part of Pro and Ultra. Upgrade in Settings, then ask for it here.")
    country = (country or "").upper()
    if country not in countries(cfg):
        raise ConciergeError("Concierge is available only for jobs in " + ", ".join(countries(cfg)) + " for now.")
    existing = case_of(c, uid)
    if existing and existing["status"] in OPEN_CASE:
        raise ConciergeError("You already have a Concierge case.")
    now = now_iso()
    cid = existing["id"] if existing else repo.new_id()
    if existing:
        c.execute("UPDATE concierge_cases SET status = 'requested', country = ?, currency = ?, intake = ?, partner_id = NULL, terms_version = ?, "
                  "agreed_at = ?, agreed_ip = ?, closed_reason = NULL, updated_at = ? WHERE id = ?",
                  (country, COUNTRY_CURRENCY.get(country, "INR"), json.dumps(intake), TERMS_VERSION, now, ip[:64], now, cid))
    else:
        c.execute("INSERT INTO concierge_cases(id, user_id, status, country, currency, intake, terms_version, agreed_at, agreed_ip, created_at, updated_at) "
                  "VALUES (?, ?, 'requested', ?, ?, ?, ?, ?, ?, ?, ?)",
                  (cid, uid, country, COUNTRY_CURRENCY.get(country, "INR"), json.dumps(intake), TERMS_VERSION, now, ip[:64], now, now))
    repo.audit(c, uid, "concierge-requested", ip, {"terms": TERMS_VERSION, "country": country})
    return case_of(c, uid)


def decide(c: Conn, uid: str, sid: str, approve: bool) -> dict:
    case = case_of(c, uid)
    s = c.one("SELECT * FROM concierge_submissions WHERE id = ? AND case_id = ?", (sid, case["id"] if case else ""))
    if not s:
        raise ConciergeError("That role isn't in your Concierge list.")
    if s["status"] != "proposed":
        raise ConciergeError("You've already answered for this role.")
    now = now_iso()
    c.execute("UPDATE concierge_submissions SET status = ?, approved_at = ?, updated_at = ? WHERE id = ?",
              ("approved" if approve else "declined", now if approve else None, now, sid))
    repo.audit(c, uid, "concierge-role-approved" if approve else "concierge-role-declined", "", {"submission": sid, "company": s["company"]})
    return s


def attributable(c: Conn, cfg: Config, case_id: str, company_key: str, on: str) -> dict | None:
    """The approved submission that makes an offer from this company feeable, if any."""
    since = (datetime.fromisoformat(on[:10]) - timedelta(days=cfg.concierge_attribution_days)).date().isoformat()
    return c.one("SELECT * FROM concierge_submissions WHERE case_id = ? AND company_key = ? AND approved_at IS NOT NULL AND approved_at >= ? "
                 "ORDER BY approved_at DESC LIMIT 1", (case_id, company_key, since))


def report_offer(c: Conn, cfg: Config, uid: str, company: str, fixed_ctc: int, joining: str, offer_doc: str = "") -> dict:
    from ..dedupe import company_key
    case = case_of(c, uid)
    if not case or case["status"] not in OPEN_CASE:
        raise ConciergeError("You don't have an open Concierge case.")
    try:
        jd = date.fromisoformat(joining[:10])
    except ValueError:
        raise ConciergeError("Add your joining date.") from None
    if fixed_ctc <= 0:
        raise ConciergeError("Add the yearly fixed pay from your offer.")
    sub = attributable(c, cfg, case["id"], company_key(company), now_iso())
    now = now_iso()
    pid = repo.new_id()
    f = fee_for(cfg, fixed_ctc)
    c.execute("INSERT INTO concierge_placements(id, case_id, submission_id, company, fixed_ctc, currency, joining_date, fee, tax_rate, status, offer_doc, created_at, updated_at) "
              "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
              (pid, case["id"], sub["id"] if sub else None, company.strip()[:160], int(fixed_ctc), case["currency"], jd.isoformat(),
               f["fee"] if sub else 0, cfg.concierge_tax_rate, "reported" if sub else "waived", offer_doc[:64] or None, now, now))
    if sub:
        c.execute("UPDATE concierge_submissions SET status = 'offer', updated_at = ? WHERE id = ?", (now, sub["id"]))
        c.execute("UPDATE concierge_cases SET status = 'offer', updated_at = ? WHERE id = ?", (now, case["id"]))
    repo.audit(c, uid, "concierge-offer-reported", "", {"placement": pid, "company": company[:80], "feeable": bool(sub)})
    return {"id": pid, "feeable": bool(sub), "fee": f if sub else None}


def set_status(c: Conn, case_id: str, status: str, reason: str = "") -> None:
    if status not in CASE_STATUSES:
        raise ConciergeError("Unknown status.")
    c.execute("UPDATE concierge_cases SET status = ?, closed_reason = ?, updated_at = ? WHERE id = ?",
              (status, reason[:300] or None, now_iso(), case_id))


def add_note(c: Conn, case_id: str, author: str, body: str, shared: bool = True) -> None:
    body = body.strip()[:4000]
    if not body:
        raise ConciergeError("Write a message first.")
    c.execute("INSERT INTO concierge_notes(id, case_id, author_id, shared, body, at) VALUES (?, ?, ?, ?, ?, ?)",
              (repo.new_id(), case_id, author, 1 if shared else 0, body, now_iso()))


# ---------------------------------------------------------------- staff actions
def propose(c: Conn, case_id: str, staff_id: str, company: str, title: str, url: str = "", why: str = "") -> str:
    from ..dedupe import company_key
    if not company.strip() or not title.strip():
        raise ConciergeError("Add the company and the role.")
    if url and not re.match(r"^https://", url):
        raise ConciergeError("Links must start with https://.")
    sid, now = repo.new_id(), now_iso()
    c.execute("INSERT INTO concierge_submissions(id, case_id, company, company_key, title, url, why, status, proposed_by, proposed_at, updated_at) "
              "VALUES (?, ?, ?, ?, ?, ?, ?, 'proposed', ?, ?, ?)",
              (sid, case_id, company.strip()[:160], company_key(company), title.strip()[:200], url[:500] or None, why.strip()[:1000] or None, staff_id, now, now))
    return sid


def move(c: Conn, case_id: str, sid: str, status: str) -> None:
    s = c.one("SELECT * FROM concierge_submissions WHERE id = ? AND case_id = ?", (sid, case_id))
    if not s:
        raise ConciergeError("Not found.")
    if status not in ("submitted", "interviewing", "offer", "rejected", "withdrawn"):
        raise ConciergeError("Unknown status.")
    if s["status"] in ("proposed", "declined") and status in ("submitted", "interviewing", "offer"):
        raise ConciergeError("The candidate hasn't approved this role. Nothing can be sent before they do.")
    now = now_iso()
    c.execute("UPDATE concierge_submissions SET status = ?, submitted_at = COALESCE(submitted_at, CASE WHEN ? = 'submitted' THEN ? END), updated_at = ? WHERE id = ?",
              (status, status, now, now, sid))


def verify_placement(c: Conn, cfg: Config, pid: str, staff_id: str, fixed_ctc: int | None = None, joining: str | None = None) -> dict:
    """A partner checks the offer letter; the fee is fixed and the instalments are scheduled."""
    p = c.one("SELECT * FROM concierge_placements WHERE id = ?", (pid,))
    if not p:
        raise ConciergeError("Not found.")
    if p["status"] != "reported":
        raise ConciergeError("This offer was already handled.")
    ctc = int(fixed_ctc or p["fixed_ctc"])
    jd = date.fromisoformat((joining or p["joining_date"])[:10])
    f = fee_for(cfg, ctc)
    now = now_iso()
    c.execute("UPDATE concierge_placements SET fixed_ctc = ?, joining_date = ?, fee = ?, tax_rate = ?, status = 'verified', verified_by = ?, verified_at = ?, updated_at = ? WHERE id = ?",
              (ctc, jd.isoformat(), f["fee"], cfg.concierge_tax_rate, staff_id, now, now, pid))
    for i in instalment_plan(cfg, f["total"] * 100, jd):
        c.execute("INSERT INTO concierge_instalments(id, placement_id, n, amount, currency, due_on, status) VALUES (?, ?, ?, ?, ?, ?, 'due')",
                  (repo.new_id(), pid, i["n"], i["amount"], p["currency"], i["due_on"]))
    c.execute("UPDATE concierge_cases SET status = 'placed', updated_at = ? WHERE id = ?", (now, p["case_id"]))
    return f


def end_early(c: Conn, pid: str, by_employer: bool) -> int:
    """The job ended within 90 days. If the employer ended it, unpaid instalments are cancelled."""
    p = c.one("SELECT * FROM concierge_placements WHERE id = ?", (pid,))
    if not p:
        raise ConciergeError("Not found.")
    if not by_employer:
        return 0
    if date.today() > date.fromisoformat(p["joining_date"]) + timedelta(days=90):
        raise ConciergeError("The 90 days after joining have passed.")
    n = c.execute("UPDATE concierge_instalments SET status = 'waived' WHERE placement_id = ? AND status IN ('due', 'link_sent')", (pid,)).rowcount
    c.execute("UPDATE concierge_placements SET status = 'waived', updated_at = ? WHERE id = ?", (now_iso(), pid))
    return n


# ---------------------------------------------------------------- payments (Razorpay payment links)
def payment_link(cfg: Config, inst: dict, user: dict, company: str, post=None) -> dict:
    if not cfg.razorpay_key_id or not cfg.razorpay_key_secret:
        raise ConciergeError("Payments aren't set up yet. Your partner will send you a link.")
    post = post or plans._post
    body = {"amount": int(inst["amount"]), "currency": inst["currency"], "accept_partial": False,
            "description": f"Propelo Concierge, instalment {inst['n']} ({company[:60]})"[:240],
            "customer": {"name": (user.get("name") or "")[:80], "email": user["email"][:120]},
            "notify": {"email": True, "sms": False}, "reminder_enable": True, "reference_id": inst["id"][:40],
            "callback_url": f"{cfg.public_url}/app#concierge", "callback_method": "get",
            "notes": {"user_id": user["id"], "instalment_id": inst["id"]}}
    r = post(f"{plans.RAZORPAY_API}/payment_links", body, cfg.razorpay_key_id, cfg.razorpay_key_secret)
    if not str(r.get("id", "")).startswith("plink_") or not str(r.get("short_url", "")).startswith("https://"):
        raise ConciergeError("Razorpay returned an unexpected payment link.")
    return {"id": r["id"], "url": r["short_url"]}


def mark_paid(c: Conn, link_id: str) -> str:
    inst = c.one("SELECT * FROM concierge_instalments WHERE provider_link_id = ?", (link_id,))
    if not inst:
        return "unknown"
    if inst["status"] == "paid":
        return "duplicate"
    c.execute("UPDATE concierge_instalments SET status = 'paid', paid_at = ? WHERE id = ?", (now_iso(), inst["id"]))
    left = c.scalar("SELECT COUNT(*) AS n FROM concierge_instalments WHERE placement_id = ? AND status IN ('due', 'link_sent')", (inst["placement_id"],))
    c.execute("UPDATE concierge_placements SET status = ?, updated_at = ? WHERE id = ?",
              ("paid" if not left else "invoicing", now_iso(), inst["placement_id"]))
    return "paid"


# ---------------------------------------------------------------- staff views
def staff_cases(c: Conn, staff: dict, status: str = "") -> list[dict]:
    q = ("SELECT k.id, k.status, k.country, k.intake, k.partner_id, k.created_at, k.updated_at, u.name, u.email, p.name AS partner "
         "FROM concierge_cases k JOIN users u ON u.id = k.user_id LEFT JOIN users p ON p.id = k.partner_id ")
    args: list = []
    where = []
    if status:
        where.append("k.status = ?")
        args.append(status)
    if not staff.get("is_admin"):  # partners see their own cases and the unassigned queue
        where.append("(k.partner_id = ? OR k.partner_id IS NULL)")
        args.append(staff["id"])
    rows = c.all(q + ("WHERE " + " AND ".join(where) + " " if where else "") + "ORDER BY k.updated_at DESC LIMIT 300", tuple(args))
    out = []
    for r in rows:
        waiting = c.scalar("SELECT COUNT(*) AS n FROM concierge_submissions WHERE case_id = ? AND status = 'proposed'", (r["id"],))
        u = c.one("SELECT id, is_admin FROM users WHERE email = ?", (r["email"],))
        out.append({"id": r["id"], "status": r["status"], "country": r["country"], "name": r["name"], "email": r["email"],
                    "plan": plans.plan_of(c, u) if u else "free",
                    "roles": json.loads(r["intake"]).get("roles", ""), "partner": r["partner"], "mine": r["partner_id"] == staff["id"],
                    "waitingOnCandidate": waiting, "updatedAt": r["updated_at"]})
    # Unassigned Ultra requests first: Ultra includes priority for a talent partner.
    out.sort(key=lambda x: (x["partner"] is not None, x["plan"] != "ultra"))
    return out


def can_open(case: dict, staff: dict) -> bool:
    return bool(staff.get("is_admin")) or case["partner_id"] in (None, staff["id"])


def staff_case(c: Conn, cfg: Config, case_id: str, staff: dict) -> dict:
    case = c.one("SELECT * FROM concierge_cases WHERE id = ?", (case_id,))
    if not case or not can_open(case, staff):
        raise ConciergeError("Not found.")
    u = c.one("SELECT id, name, email, created_at FROM users WHERE id = ?", (case["user_id"],))
    prof = (repo.get_doc(c, u["id"], "profile", "applicant") or {}).get("data") or {}
    jobs = [d["data"] for d in repo.list_docs(c, u["id"], "jobs")]
    notes = c.all("SELECT n.*, a.name AS author FROM concierge_notes n LEFT JOIN users a ON a.id = n.author_id WHERE n.case_id = ? ORDER BY n.at", (case_id,))
    subs = c.all("SELECT * FROM concierge_submissions WHERE case_id = ? ORDER BY proposed_at DESC", (case_id,))
    places = c.all("SELECT * FROM concierge_placements WHERE case_id = ? ORDER BY created_at DESC", (case_id,))
    keep = ("fullName", "headline", "location", "linkedin", "github", "portfolio", "summary", "skills", "experience", "education", "projects")
    return {"id": case["id"], "status": case["status"], "country": case["country"], "currency": case["currency"], "intake": json.loads(case["intake"]),
            "agreedAt": case["agreed_at"], "termsVersion": case["terms_version"], "partnerId": case["partner_id"],
            "candidate": {"name": u["name"], "email": u["email"], "since": u["created_at"], "plan": plans.plan_of(c, {"id": u["id"], "is_admin": 0})},
            "profile": {k: prof[k] for k in keep if k in prof},
            "pipeline": [{"company": j.get("company"), "title": j.get("title"), "stage": j.get("stage"), "appliedAt": j.get("appliedAt")}
                         for j in jobs if j.get("stage") not in (None, "skipped")][:200],
            "submissions": [_sub_view(s) for s in subs],
            "notes": [{"id": n["id"], "author": n["author"] or "Candidate", "shared": bool(n["shared"]), "body": n["body"], "at": n["at"],
                       "fromCandidate": n["author_id"] == u["id"]} for n in notes],
            "placements": [_placement_view(c, p) | {"feeable": p["submission_id"] is not None} for p in places],
            "feePreview": fee_for(cfg, json.loads(case["intake"]).get("expectedCtc") or 0)}
