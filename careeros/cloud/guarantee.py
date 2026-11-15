"""Money-back guarantees: the Interview Guarantee and the Job Guarantee, paid add-ons for Pro and Ultra.

They aren't part of any plan. A Pro or Ultra member who's eligible buys one with a one-time payment
(GUARANTEE_INTERVIEW_PRICE_INR / _USD_CENTS, JOB_GUARANTEE_PRICE_INR); the window starts when the payment
goes through. If it fails, the refund is the add-on price plus the plan fees paid during the window.
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


def price_for(cfg: Config, kind: str, currency: str) -> int:
    """The add-on's one-time price in minor units (paise or cents). The Job Guarantee is sold in rupees only."""
    if kind == "job":
        return cfg.guarantee_job_inr * 100
    return cfg.guarantee_interview_usd_cents if currency == "USD" else cfg.guarantee_interview_inr * 100


def refund_estimate(cfg: Config, plan: str, currency: str, days: int, price: int = 0) -> int:
    """The add-on price plus the plan fees for the window, in minor units: one monthly price per started 30 days."""
    months = max(1, math.ceil(days / 30))
    if currency == "USD":
        each = cfg.ultra_price_usd_cents if plan == "ultra" else cfg.pro_price_usd_cents
    else:
        each = (cfg.ultra_price_inr if plan == "ultra" else cfg.pro_price_inr) * 100
    return months * each + int(price or 0)


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
            "price": g.get("price") or 0, "payUrl": g.get("pay_url") if g["status"] == "pending" else None, "paidAt": g.get("paid_at"),
            "estimate": refund_estimate(cfg, g["plan"], g["currency"], days_for(cfg, g["kind"]), g.get("price") or 0)}


def view(c: Conn, cfg: Config, user: dict) -> dict:
    out = {"enabled": cfg.guarantee_enabled, "termsVersion": TERMS_VERSION,
           "rules": {"days": cfg.guarantee_days, "minApplications": cfg.guarantee_min_apps, "minWeeks": cfg.guarantee_min_weeks,
                     "minMatches": cfg.guarantee_min_matches, "claimDays": cfg.guarantee_claim_days, "jobDays": cfg.job_guarantee_days},
           "conciergeEnabled": cfg.concierge_enabled}
    for kind in KINDS:
        g = row(c, user["id"], kind)
        if g and g["status"] == "active":
            g = _refresh_one(c, cfg, g)[0]
        if g and g["status"] == "pending":
            g = _expire_pending(c, g)
        live = g and g["status"] not in ("void", "ended", "rejected", "refunded")
        cur = "INR" if kind == "job" else _currency(c, user["id"])
        price = price_for(cfg, kind, cur)
        plan = plans.plan_of(c, user)
        out[kind] = {"current": _view_row(c, cfg, g), "eligibility": None if live else eligibility(c, cfg, user, kind),
                     "currency": cur, "price": price, "canPay": bool(_payer(cfg, cur)),
                     "estimate": refund_estimate(cfg, plan if plan in PLANS_WITH_GUARANTEE else "pro", cur, days_for(cfg, kind), price)}
    return out


# ---------------------------------------------------------------- enrol, refresh, claim
def _payer(cfg: Config, currency: str) -> str:
    if currency == "USD":
        return "dodo" if cfg.dodo_enabled and cfg.dodo_product_guarantee else ""
    return "razorpay" if cfg.razorpay_key_id and cfg.razorpay_key_secret else ""


def checkout(cfg: Config, user: dict, g: dict, post=None) -> dict:
    """A one-time payment for the add-on: a Razorpay payment link in rupees, a Dodo checkout in dollars.
    Returns {provider, id, url}. The guarantee starts on the provider's paid webhook, never on this call."""
    name = "Interview Guarantee" if g["kind"] == "interview" else "Job Guarantee"
    if _payer(cfg, g["currency"]) == "razorpay":
        post = post or plans._post
        r = post(f"{plans.RAZORPAY_API}/payment_links", {
            "amount": int(g["price"]), "currency": "INR", "accept_partial": False, "description": f"Propelo {name} (one time)",
            "customer": {"name": (user.get("name") or "")[:80], "email": user["email"][:120]}, "notify": {"email": True, "sms": False},
            "reference_id": g["id"][:40], "callback_url": f"{cfg.public_url}/app#guarantee", "callback_method": "get",
            "notes": {"user_id": user["id"], "guarantee_id": g["id"]}}, cfg.razorpay_key_id, cfg.razorpay_key_secret)
        if not str(r.get("id", "")).startswith("plink_") or not str(r.get("short_url", "")).startswith("https://"):
            raise GuaranteeError("Razorpay returned an unexpected payment link.")
        return {"provider": "razorpay", "id": r["id"], "url": r["short_url"]}
    if _payer(cfg, g["currency"]) == "dodo":
        d = plans.Dodo(cfg, post)
        r = d.call("POST", f"{d.base}/checkouts", {"product_cart": [{"product_id": cfg.dodo_product_guarantee, "quantity": 1}],
                   "customer": {"email": user["email"][:200], "name": (user.get("name") or user["email"].split("@")[0])[:120]},
                   "return_url": f"{cfg.public_url}/app#guarantee", "metadata": {"user_id": user["id"], "guarantee_id": g["id"]}}, cfg.dodo_api_key)
        url, sid = str(r.get("checkout_url") or ""), str(r.get("session_id") or "")
        if not url.startswith("https://") or not sid:
            raise GuaranteeError("Dodo Payments returned an unexpected checkout.")
        return {"provider": "dodo", "id": sid, "url": url}
    raise GuaranteeError("Payments for add-ons aren't set up on this server yet.")


def _expire_pending(c: Conn, g: dict, now: datetime | None = None) -> dict:
    """An unpaid checkout lapses after 2 days, so the person can start again later."""
    now = now or datetime.now(timezone.utc)
    if g["status"] == "pending" and now - (_dt(g["agreed_at"]) or now) > timedelta(days=2):
        return _set(c, g, "void", "The payment wasn't completed, so the guarantee didn't start.")
    return g


def buy(c: Conn, cfg: Config, user: dict, kind: str, ip: str, pay=None, now: datetime | None = None) -> dict:
    """Start buying the add-on: check eligibility, record the terms, and return a payment page.
    A checkout still open is reused."""
    if not cfg.guarantee_enabled:
        raise GuaranteeError("Guarantees aren't available on this server.")
    if kind not in KINDS:
        raise GuaranteeError("Not found.")
    if kind == "job" and not cfg.concierge_enabled:
        raise GuaranteeError("The Job Guarantee comes with Concierge, which isn't available yet.")
    now = now or datetime.now(timezone.utc)
    old = row(c, user["id"], kind)
    if old and old["status"] == "pending":
        old = _expire_pending(c, old, now)
        if old["status"] == "pending" and old.get("pay_url"):
            return old
    if old and old["status"] in ("active", "claimable", "claimed", "approved"):
        raise GuaranteeError("You already have this guarantee.")
    elig = eligibility(c, cfg, user, kind, now)
    if not elig["ok"]:
        missing = "; ".join(x["label"] for x in elig["checks"] if not x["ok"])
        raise GuaranteeError("Not eligible yet: " + missing + ".")
    plan = plans.plan_of(c, user)
    cur = "INR" if kind == "job" else _currency(c, user["id"])
    price = price_for(cfg, kind, cur)
    stamp = now_iso()
    gid = old["id"] if old else repo.new_id()
    if old:
        c.execute("UPDATE guarantees SET status = 'pending', plan = ?, currency = ?, terms_version = ?, agreed_at = ?, agreed_ip = ?, starts_at = ?, "
                  "ends_at = ?, eligibility = ?, progress = '{}', reason = NULL, met_at = NULL, claimed_at = NULL, claim_note = NULL, decided_by = NULL, "
                  "decided_at = NULL, refund_amount = NULL, price = ?, pay_provider = NULL, pay_ref = NULL, pay_url = NULL, paid_at = NULL, updated_at = ? WHERE id = ?",
                  (plan, cur, TERMS_VERSION, stamp, ip[:64], stamp, stamp, json.dumps(elig), price, stamp, gid))
    else:
        c.execute("INSERT INTO guarantees(id, user_id, kind, status, plan, currency, terms_version, agreed_at, agreed_ip, starts_at, ends_at, "
                  "eligibility, price, created_at, updated_at) VALUES (?, ?, ?, 'pending', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                  (gid, user["id"], kind, plan, cur, TERMS_VERSION, stamp, ip[:64], stamp, stamp, json.dumps(elig), price, stamp, stamp))
    g = c.one("SELECT * FROM guarantees WHERE id = ?", (gid,))
    got = (pay or checkout)(cfg, user, g)
    c.execute("UPDATE guarantees SET pay_provider = ?, pay_ref = ?, pay_url = ? WHERE id = ?", (got["provider"], got["id"][:120], got["url"][:600], gid))
    repo.audit(c, user["id"], f"guarantee-{kind}-checkout", ip, {"terms": TERMS_VERSION, "plan": plan, "price": price, "currency": cur})
    return c.one("SELECT * FROM guarantees WHERE id = ?", (gid,))


def activate(c: Conn, cfg: Config, g: dict, provider: str, now: datetime | None = None) -> dict:
    """The payment went through: the window starts now."""
    now = now or datetime.now(timezone.utc)
    g = _set(c, g, "active", None, starts_at=_iso(now), ends_at=_iso(now + timedelta(days=days_for(cfg, g["kind"]))),
             paid_at=now_iso(), pay_provider=provider)
    repo.audit(c, g["user_id"], f"guarantee-{g['kind']}-paid", "", {"provider": provider, "price": g["price"], "currency": g["currency"]})
    return g


def mark_paid(c: Conn, cfg: Config, provider: str, ref: str = "", guarantee_id: str = "", amount: int | None = None) -> tuple[str, dict | None]:
    """From a verified webhook. Returns (result, row)."""
    g = None
    if ref:
        g = c.one("SELECT * FROM guarantees WHERE pay_ref = ?", (ref,))
    if not g and guarantee_id:
        g = c.one("SELECT * FROM guarantees WHERE id = ?", (guarantee_id,))
    if not g:
        return "unknown", None
    if g["status"] != "pending":
        return "duplicate", g
    if amount is not None and int(amount) < int(g["price"] or 0):
        return "short", g
    return "paid", activate(c, cfg, g, provider)


def grant(c: Conn, cfg: Config, uid: str, kind: str, by: str) -> dict:
    """The operator starts a guarantee without payment (a goodwill gesture or a test)."""
    user = c.one("SELECT * FROM users WHERE id = ?", (uid,))
    g = buy(c, cfg, user, kind, "", pay=lambda *_: {"provider": "grant", "id": "grant-" + repo.new_id()[:12], "url": ""})
    g = activate(c, cfg, g, "grant")
    c.execute("UPDATE guarantees SET price = 0 WHERE id = ?", (g["id"],))
    repo.audit(c, by, "guarantee-granted", "", {"user": uid, "kind": kind})
    return c.one("SELECT * FROM guarantees WHERE id = ?", (g["id"],))


def enroll(c: Conn, cfg: Config, user: dict, kind: str, ip: str, now: datetime | None = None) -> dict:
    """Kept for older callers: guarantees are bought now (see buy)."""
    return buy(c, cfg, user, kind, ip, now=now)


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
    for g in c.all("SELECT * FROM guarantees WHERE status = 'pending'"):
        _expire_pending(c, g, now)
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
def staff_list(c: Conn, cfg: Config) -> list[dict]:
    rows = c.all("SELECT g.*, u.email, u.name FROM guarantees g JOIN users u ON u.id = g.user_id "
                 "WHERE g.status IN ('claimed', 'approved') ORDER BY g.claimed_at")
    return [{"id": r["id"], "kind": r["kind"], "status": r["status"], "plan": r["plan"], "currency": r["currency"], "name": r["name"], "email": r["email"],
             "startsAt": r["starts_at"], "endsAt": r["ends_at"], "claimedAt": r["claimed_at"], "note": r["claim_note"],
             "progress": json.loads(r["progress"] or "{}"), "eligibility": json.loads(r["eligibility"] or "{}"), "refund": r["refund_amount"],
             "price": r.get("price") or 0, "paidVia": r.get("pay_provider"), "paymentRef": r.get("pay_ref"),
             "estimate": refund_estimate(cfg, r["plan"], r["currency"], days_for(cfg, r["kind"]), r.get("price") or 0)} for r in rows]


def decide(c: Conn, cfg: Config, staff_uid: str, gid: str, decision: str, note: str, amount: int | None) -> dict:
    g = c.one("SELECT * FROM guarantees WHERE id = ?", (gid,))
    if not g:
        raise GuaranteeError("Not found.")
    note = " ".join(str(note or "").split())[:1000]
    if decision == "approve":
        if g["status"] != "claimed":
            raise GuaranteeError("Only a claim can be approved.")
        est = refund_estimate(cfg, g["plan"], g["currency"], days_for(cfg, g["kind"]), g.get("price") or 0)
        amt = est if amount is None else int(amount)
        if not 0 < amt <= est:
            raise GuaranteeError("The refund must be more than 0 and no more than the add-on price plus the plan fees for the window.")
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
