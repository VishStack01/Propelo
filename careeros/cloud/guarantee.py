"""Money-back guarantees: the Interview Guarantee and the Job Guarantee.

Both promise money back, never a job. The rules are written so a job seeker can check them before
relying on them, and so the app can track them without anyone's word:

Interview Guarantee (Pro and Ultra)
  - Before enrolling, the app checks and records eligibility: a paid plan, a profile with your
    experience, and at least GUARANTEE_MIN_MATCHES roles matched to you in the last 30 days (so the
    promise is only made where Propelo actually finds roles for you).
  - For GUARANTEE_DAYS from enrolling, keep the plan active and send at least GUARANTEE_MIN_APPS
    applications through Propelo or marked as applied, in at least GUARANTEE_MIN_WEEKS different
    weeks. Applications to postings the scam check marks unsafe don't count.
  - An interview is a live conversation (phone, video or in person) with someone at the employer or
    its recruiter about a role you applied to, recruiter screens included. Online tests and recorded
    one-way videos don't count. Interviews from any source count, and an invitation you declined
    counts as an interview.
  - If the window ends with the activity done and no interview, you can claim within
    GUARANTEE_CLAIM_DAYS. A person on the team checks the claim; approved claims get back the plan fees
    paid during the window, to the original payment method. Once per account.

Job Guarantee (with Concierge, Pro and Ultra)
  - With an open Concierge case, enrol and for JOB_GUARANTEE_DAYS keep the plan active, answer the
    partner's proposals within 7 days, attend the interviews you agreed to, and don't turn down an offer
    that meets the pay and location you gave in your intake.
  - No accepted offer by the end: the plan fees paid during those days come back, and no Concierge fee
    is ever owed for that case. Once per account.

The fees refunded are the monthly plan price for each month the window covers (two for 60 days); the
person deciding a claim confirms the actual payments in the payment provider before refunding.
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timedelta, timezone

from .. import scamcheck
from . import concierge, plans, repo
from .config import Config
from .db import Conn, now_iso

TERMS_VERSION = "2026-11-16"
KINDS = ("interview", "job")
PLANS_WITH_GUARANTEE = ("pro", "ultra")
OPEN = ("active",)
INTERVIEW_STAGES = ("screen", "interview", "offer")
FEED_SOURCES = ("careers-feed", "remote-board")


class GuaranteeError(ValueError):
    pass


def _dt(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        d = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _iso(d: datetime) -> str:
    return d.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def row(c: Conn, uid: str, kind: str) -> dict | None:
    return c.one("SELECT * FROM guarantees WHERE user_id = ? AND kind = ?", (uid, kind))


def days_for(cfg: Config, kind: str) -> int:
    return cfg.guarantee_days if kind == "interview" else cfg.job_guarantee_days


def refund_estimate(cfg: Config, plan: str, currency: str, days: int) -> int:
    """Plan fees for the window, in minor units: one monthly price per started 30 days."""
    months = max(1, math.ceil(days / 30))
    if currency == "USD":
        each = cfg.ultra_price_usd_cents if plan == "ultra" else cfg.pro_price_usd_cents
    else:
        each = (cfg.ultra_price_inr if plan == "ultra" else cfg.pro_price_inr) * 100
    return months * each


def _currency(c: Conn, uid: str) -> str:
    s = plans.subscription(c, uid) or {}
    return "USD" if str(s.get("currency") or "INR").upper() == "USD" else "INR"


# ---------------------------------------------------------------- eligibility and progress
def _jobs(c: Conn, uid: str) -> list[dict]:
    return [d["data"] for d in repo.list_docs(c, uid, "jobs")]


def _has_profile(c: Conn, uid: str) -> bool:
    d = repo.get_doc(c, uid, "profile", "resume")
    p = (d or {}).get("data") or {}
    return bool(p.get("experience") or p.get("skills") or str(p.get("summary") or "").strip())


def eligibility(c: Conn, cfg: Config, user: dict, kind: str, now: datetime | None = None) -> dict:
    """Each condition, checked now, with what the person can do about it."""
    now = now or datetime.now(timezone.utc)
    plan = plans.plan_of(c, user)
    checks = [{"id": "plan", "ok": plan in PLANS_WITH_GUARANTEE, "label": "On Pro or Ultra",
               "detail": f"You're on {plan.title()}." if plan in PLANS_WITH_GUARANTEE else "Upgrade to Pro or Ultra first."}]
    old = row(c, user["id"], kind)
    used = bool(old and int(old.get("refunds") or 0) > 0)
    checks.append({"id": "once", "ok": not used, "label": "Not refunded before",
                   "detail": "Each account can be refunded once." if not used else "This account already had this guarantee refunded."})
    if kind == "interview":
        prof = _has_profile(c, user["id"])
        checks.append({"id": "profile", "ok": prof, "label": "Your profile has your experience",
                       "detail": "Done." if prof else "Add your resume or experience in Profile."})
        since = now - timedelta(days=30)
        matched = sum(1 for j in _jobs(c, user["id"]) if j.get("foundVia") in FEED_SOURCES and j.get("stage") != "skipped"
                      and (_dt(j.get("foundAt")) or datetime.min.replace(tzinfo=timezone.utc)) >= since)
        need = cfg.guarantee_min_matches
        checks.append({"id": "matches", "ok": matched >= need, "label": f"At least {need} roles matched to you in the last 30 days",
                       "detail": f"{matched} matched so far." + ("" if matched >= need else " Widen your job families, locations or experience in Settings, or wait for more matches.")})
    else:
        case = concierge.case_of(c, user["id"])
        open_case = bool(case and case["status"] in ("requested", "active"))
        checks.append({"id": "case", "ok": open_case, "label": "An open Concierge case",
                       "detail": "Done." if open_case else "Ask for Concierge first (India only for now)."})
    return {"ok": all(x["ok"] for x in checks), "checks": checks, "checkedAt": _iso(now)}


def progress(c: Conn, cfg: Config, g: dict, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    start, end = _dt(g["starts_at"]), _dt(g["ends_at"])
    if g["kind"] == "job":
        case = concierge.case_of(c, g["user_id"])
        placed = bool(case and case["status"] in ("offer", "placed"))
        days_left = max(0, math.ceil(((end or now) - now).total_seconds() / 86400))
        return {"offer": placed, "daysLeft": days_left, "caseStatus": (case or {}).get("status")}
    apps, weeks, unsafe, interviews = 0, set(), 0, []
    for j in _jobs(c, g["user_id"]):
        at = _dt(j.get("appliedAt"))
        if at and start <= at <= end:
            if scamcheck.check(j)["level"] == "high":
                unsafe += 1
            else:
                apps += 1
                iso = at.isocalendar()
                weeks.add(f"{iso[0]}-{iso[1]}")
        hit = [_dt(j.get(k)) for k in ("screenAt", "interviewStartedAt", "offerAt")]
        if any(h and start <= h for h in hit) or (j.get("stage") in INTERVIEW_STAGES and at and at >= start):
            interviews.append({"company": str(j.get("company") or "")[:80], "title": str(j.get("title") or "")[:120]})
    return {"applications": apps, "needApplications": cfg.guarantee_min_apps, "weeks": len(weeks), "needWeeks": cfg.guarantee_min_weeks,
            "unsafeSkipped": unsafe, "interviews": len(interviews), "interviewRoles": interviews[:5],
            "daysLeft": max(0, math.ceil(((end or now) - now).total_seconds() / 86400))}


def activity_done(cfg: Config, g: dict, p: dict) -> bool:
    if g["kind"] == "job":
        return True  # the partner checks the Job Guarantee conditions when deciding the claim
    return p.get("applications", 0) >= cfg.guarantee_min_apps and p.get("weeks", 0) >= cfg.guarantee_min_weeks


# ---------------------------------------------------------------- what the person sees
def _view_row(c: Conn, cfg: Config, g: dict | None) -> dict | None:
    if not g:
        return None
    p = json.loads(g["progress"] or "{}")
    return {"id": g["id"], "kind": g["kind"], "status": g["status"], "plan": g["plan"], "currency": g["currency"],
            "startsAt": g["starts_at"], "endsAt": g["ends_at"], "agreedAt": g["agreed_at"], "termsVersion": g["terms_version"],
            "progress": p, "reason": g["reason"], "claimedAt": g["claimed_at"], "decidedAt": g["decided_at"],
            "refund": g["refund_amount"], "claimBy": _iso(_dt(g["ends_at"]) + timedelta(days=cfg.guarantee_claim_days)) if g["ends_at"] else None,
            "estimate": refund_estimate(cfg, g["plan"], g["currency"], days_for(cfg, g["kind"]))}


def view(c: Conn, cfg: Config, user: dict) -> dict:
    out = {"enabled": cfg.guarantee_enabled, "termsVersion": TERMS_VERSION,
           "rules": {"days": cfg.guarantee_days, "minApplications": cfg.guarantee_min_apps, "minWeeks": cfg.guarantee_min_weeks,
                     "minMatches": cfg.guarantee_min_matches, "claimDays": cfg.guarantee_claim_days, "jobDays": cfg.job_guarantee_days},
           "conciergeEnabled": cfg.concierge_enabled}
    for kind in KINDS:
        g = row(c, user["id"], kind)
        if g and g["status"] == "active":
            g = _refresh_one(c, cfg, g)[0]
        live = g and g["status"] not in ("void", "ended", "rejected")
        out[kind] = {"current": _view_row(c, cfg, g), "eligibility": None if live else eligibility(c, cfg, user, kind),
                     "currency": _currency(c, user["id"]),
                     "estimate": refund_estimate(cfg, plans.plan_of(c, user) if plans.plan_of(c, user) in PLANS_WITH_GUARANTEE else "pro",
                                                 _currency(c, user["id"]), days_for(cfg, kind))}
    return out


# ---------------------------------------------------------------- enrol, refresh, claim
def enroll(c: Conn, cfg: Config, user: dict, kind: str, ip: str, now: datetime | None = None) -> dict:
    if not cfg.guarantee_enabled:
        raise GuaranteeError("Guarantees aren't available on this server.")
    if kind not in KINDS:
        raise GuaranteeError("Not found.")
    if kind == "job" and not cfg.concierge_enabled:
        raise GuaranteeError("The Job Guarantee comes with Concierge, which isn't available yet.")
    now = now or datetime.now(timezone.utc)
    old = row(c, user["id"], kind)
    if old and old["status"] in ("active", "claimable", "claimed", "approved"):
        raise GuaranteeError("You're already enrolled.")
    elig = eligibility(c, cfg, user, kind, now)
    if not elig["ok"]:
        missing = "; ".join(x["label"] for x in elig["checks"] if not x["ok"])
        raise GuaranteeError("Not eligible yet: " + missing + ".")
    plan = plans.plan_of(c, user)
    start, end = now, now + timedelta(days=days_for(cfg, kind))
    stamp = now_iso()
    values = (plan, _currency(c, user["id"]), TERMS_VERSION, stamp, ip[:64], _iso(start), _iso(end), json.dumps(elig), stamp)
    if old:
        c.execute("UPDATE guarantees SET status = 'active', plan = ?, currency = ?, terms_version = ?, agreed_at = ?, agreed_ip = ?, starts_at = ?, "
                  "ends_at = ?, eligibility = ?, progress = '{}', reason = NULL, met_at = NULL, claimed_at = NULL, claim_note = NULL, "
                  "decided_by = NULL, decided_at = NULL, refund_amount = NULL, updated_at = ? WHERE id = ?", values + (old["id"],))
    else:
        c.execute("INSERT INTO guarantees(id, user_id, kind, status, plan, currency, terms_version, agreed_at, agreed_ip, starts_at, ends_at, "
                  "eligibility, created_at, updated_at) VALUES (?, ?, ?, 'active', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                  (repo.new_id(), user["id"], kind) + values[:8] + (stamp, stamp))
    repo.audit(c, user["id"], f"guarantee-{kind}-enrolled", ip, {"terms": TERMS_VERSION, "plan": plan})
    return row(c, user["id"], kind)


def _set(c: Conn, g: dict, status: str, reason: str | None = None, **extra) -> dict:
    cols = {"status": status, "reason": reason, "updated_at": now_iso(), **extra}
    c.execute("UPDATE guarantees SET " + ", ".join(f"{k} = ?" for k in cols) + " WHERE id = ?", tuple(cols.values()) + (g["id"],))
    return c.one("SELECT * FROM guarantees WHERE id = ?", (g["id"],))


def _refresh_one(c: Conn, cfg: Config, g: dict, now: datetime | None = None) -> tuple[dict, str | None]:
    """Move one guarantee on: met, void, claimable or ended. Returns (row, event to tell the person about)."""
    now = now or datetime.now(timezone.utc)
    user = c.one("SELECT id, is_admin FROM users WHERE id = ?", (g["user_id"],)) or {"id": g["user_id"], "is_admin": 0}
    if g["status"] == "active":
        p = progress(c, cfg, g, now)
        c.execute("UPDATE guarantees SET progress = ?, updated_at = ? WHERE id = ?", (json.dumps(p), now_iso(), g["id"]))
        g = dict(g, progress=json.dumps(p))
        if (g["kind"] == "interview" and p.get("interviews")) or (g["kind"] == "job" and p.get("offer")):
            return _set(c, g, "met", "Done: " + ("you got an interview." if g["kind"] == "interview" else "you have an offer."), met_at=now_iso()), "met"
        ended = now >= _dt(g["ends_at"])
        if not ended and g["kind"] == "job" and p.get("caseStatus") in (None, "closed"):
            return _set(c, g, "void", "The Concierge case was closed before the guarantee window ended."), "void"
        if not ended and plans.plan_of(c, user) not in PLANS_WITH_GUARANTEE:
            return _set(c, g, "void", "Your plan ended before the guarantee window did."), "void"
        if ended:
            if activity_done(cfg, g, p):
                return _set(c, g, "claimable", "The window ended with no " + ("interview" if g["kind"] == "interview" else "accepted offer") + ". You can claim your refund."), "claimable"
            return _set(c, g, "ended", f"The window ended with {p.get('applications', 0)} applications in {p.get('weeks', 0)} weeks; "
                                       f"the guarantee needs {cfg.guarantee_min_apps} in {cfg.guarantee_min_weeks}."), "ended"
    elif g["status"] == "claimable" and now >= _dt(g["ends_at"]) + timedelta(days=cfg.guarantee_claim_days):
        return _set(c, g, "ended", "The time to claim passed."), "ended"
    return g, None


def refresh(c: Conn, cfg: Config, now: datetime | None = None) -> list[tuple[str, str, str]]:
    """Run by the worker. Returns (user email, kind, event) for each change worth an email."""
    out = []
    for g in c.all("SELECT * FROM guarantees WHERE status IN ('active', 'claimable')"):
        g2, event = _refresh_one(c, cfg, g, now)
        if event in ("met", "claimable", "void"):
            u = c.one("SELECT email FROM users WHERE id = ?", (g2["user_id"],))
            if u:
                out.append((u["email"], g2["kind"], event))
    return out


def claim(c: Conn, cfg: Config, uid: str, kind: str, attest: bool, note: str, ip: str) -> dict:
    g = row(c, uid, kind)
    if g and g["status"] == "active":
        g = _refresh_one(c, cfg, g)[0]
    if not g or g["status"] != "claimable":
        raise GuaranteeError("There's nothing to claim yet." if not g or g["status"] == "active" else "This guarantee can't be claimed.")
    if attest is not True:
        raise GuaranteeError("Confirm that you had no interview" + (" or accepted offer" if kind == "job" else "") + " in the window.")
    g = _set(c, g, "claimed", "Claim received. A person on the team checks it within 5 working days.", claimed_at=now_iso(),
             claim_note=" ".join(str(note or "").split())[:2000])
    repo.audit(c, uid, f"guarantee-{kind}-claimed", ip, {"progress": json.loads(g["progress"] or "{}")})
    return g


# ---------------------------------------------------------------- the team's side
def staff_list(c: Conn) -> list[dict]:
    rows = c.all("SELECT g.*, u.email, u.name FROM guarantees g JOIN users u ON u.id = g.user_id "
                 "WHERE g.status IN ('claimed', 'approved') ORDER BY g.claimed_at")
    return [{"id": r["id"], "kind": r["kind"], "status": r["status"], "plan": r["plan"], "currency": r["currency"], "name": r["name"], "email": r["email"],
             "startsAt": r["starts_at"], "endsAt": r["ends_at"], "claimedAt": r["claimed_at"], "note": r["claim_note"],
             "progress": json.loads(r["progress"] or "{}"), "eligibility": json.loads(r["eligibility"] or "{}"), "refund": r["refund_amount"]} for r in rows]


def decide(c: Conn, cfg: Config, staff_uid: str, gid: str, decision: str, note: str, amount: int | None) -> dict:
    g = c.one("SELECT * FROM guarantees WHERE id = ?", (gid,))
    if not g:
        raise GuaranteeError("Not found.")
    note = " ".join(str(note or "").split())[:1000]
    if decision == "approve":
        if g["status"] != "claimed":
            raise GuaranteeError("Only a claim can be approved.")
        est = refund_estimate(cfg, g["plan"], g["currency"], days_for(cfg, g["kind"]))
        amt = est if amount is None else int(amount)
        if not 0 < amt <= est:
            raise GuaranteeError("The refund must be more than 0 and no more than the plan fees for the window.")
        g = _set(c, g, "approved", note or "Approved. The refund goes to your original payment method.", decided_by=staff_uid, decided_at=now_iso(), refund_amount=amt)
    elif decision == "reject":
        if g["status"] != "claimed":
            raise GuaranteeError("Only a claim can be rejected.")
        if len(note) < 10:
            raise GuaranteeError("Say why, in a sentence the person will read.")
        g = _set(c, g, "rejected", note, decided_by=staff_uid, decided_at=now_iso())
    elif decision == "refunded":
        if g["status"] != "approved":
            raise GuaranteeError("Approve the claim first.")
        g = _set(c, g, "refunded", note or "Refunded.", refunds=int(g["refunds"] or 0) + 1)
    else:
        raise GuaranteeError("Not found.")
    repo.audit(c, staff_uid, f"guarantee-{decision}", "", {"guarantee": gid, "amount": g["refund_amount"]})
    return g
