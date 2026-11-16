"""The Interview Guarantee: applied for, reviewed by the team, then paid for, with the price back if there's no interview.

Who and how
  - Only Pro and Ultra members can apply. Nobody is enrolled directly: the member applies (target roles, a note,
    the guarantee terms accepted), and a person on the team reviews it and accepts or declines with a reason.
  - Once accepted, the member pays GUARANTEE_INTERVIEW_PRICE_INR (or _USD_CENTS) once, through a Razorpay payment
    link or a Dodo checkout. The GUARANTEE_DAYS window starts when the payment webhook arrives. An acceptance
    that isn't paid within 7 days lapses.
  - For the window, keep the plan active and send at least GUARANTEE_MIN_APPS applications through Propelo (or
    marked as applied) in at least GUARANTEE_MIN_WEEKS different weeks. Applications to postings the scam check
    marks unsafe don't count.
  - An interview is a live conversation (phone, video or in person) with someone at the employer or its
    recruiter about a role you applied to, recruiter screens included. Online tests and recorded one-way videos
    don't count. Interviews from any source count, and an invitation you declined counts as an interview.
  - No interview by the end, with the activity done: claim within GUARANTEE_CLAIM_DAYS. A person checks it and
    the price paid is refunded to the original payment method. Once per account.

The Job Guarantee has no upfront price and isn't handled here: it is a Concierge application (concierge.py)
that the team reviews and accepts or declines, paid only by the placement fee after the member joins.

It promises money back, never a job.
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timedelta, timezone

from .. import scamcheck
from . import plans, repo
from .config import Config
from .db import Conn, now_iso

TERMS_VERSION = "2026-11-16b"
KINDS = ("interview",)
PLANS_WITH_GUARANTEE = ("pro", "ultra")
INTERVIEW_STAGES = ("screen", "interview", "offer")
FEED_SOURCES = ("careers-feed", "remote-board")
PAY_WITHIN_DAYS = 7
LIVE = ("applied", "accepted", "pending", "active", "met", "claimable", "claimed", "approved")


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


def row(c: Conn, uid: str, kind: str = "interview") -> dict | None:
    return c.one("SELECT * FROM guarantees WHERE user_id = ? AND kind = ?", (uid, kind))


def days_for(cfg: Config, kind: str = "interview") -> int:
    return cfg.guarantee_days


def price_for(cfg: Config, kind: str, currency: str) -> int:
    """The one-time price in minor units (paise or cents)."""
    return cfg.guarantee_interview_usd_cents if currency == "USD" else cfg.guarantee_interview_inr * 100


def refund_estimate(cfg: Config, plan: str, currency: str, days: int, price: int = 0) -> int:
    """What comes back if the guarantee fails: the price paid for it."""
    return int(price or 0)


def _currency(c: Conn, uid: str) -> str:
    s = plans.subscription(c, uid) or {}
    return "USD" if str(s.get("currency") or "INR").upper() == "USD" else "INR"


def _set(c: Conn, g: dict, status: str, reason: str | None = None, **extra) -> dict:
    cols = {"status": status, "reason": reason, "updated_at": now_iso(), **extra}
    c.execute("UPDATE guarantees SET " + ", ".join(f"{k} = ?" for k in cols) + " WHERE id = ?", tuple(cols.values()) + (g["id"],))
    return c.one("SELECT * FROM guarantees WHERE id = ?", (g["id"],))


# ---------------------------------------------------------------- eligibility and progress
def _jobs(c: Conn, uid: str) -> list[dict]:
    return [d["data"] for d in repo.list_docs(c, uid, "jobs")]


def _has_profile(c: Conn, uid: str) -> bool:
    d = repo.get_doc(c, uid, "profile", "resume")
    p = (d or {}).get("data") or {}
    if p.get("experience") or p.get("skills") or str(p.get("summary") or "").strip():
        return True
    # An uploaded resume we could read counts too.
    rid = ((((repo.get_doc(c, uid, "profile", "applicant") or {}).get("data") or {}).get("resume") or {}).get("id") or "")
    text = c.scalar("SELECT text FROM assets WHERE id = ? AND user_id = ?", (rid, uid)) if rid else None
    return len(str(text or "").strip()) >= 200


def eligibility(c: Conn, cfg: Config, user: dict, kind: str = "interview", now: datetime | None = None) -> dict:
    """What's needed to apply. The plan and profile are required; the matched roles help the team decide."""
    now = now or datetime.now(timezone.utc)
    plan = plans.plan_of(c, user)
    checks = [{"id": "plan", "ok": plan in PLANS_WITH_GUARANTEE, "label": "On Pro or Ultra",
               "detail": f"You're on {plan.title()}." if plan in PLANS_WITH_GUARANTEE else "Upgrade to Pro or Ultra first."}]
    old = row(c, user["id"], kind)
    used = bool(old and int(old.get("refunds") or 0) > 0)
    checks.append({"id": "once", "ok": not used, "label": "Not refunded before",
                   "detail": "Each account can be refunded once." if not used else "This account already had the Interview Guarantee refunded."})
    prof = _has_profile(c, user["id"])
    checks.append({"id": "profile", "ok": prof, "label": "Your profile has your experience",
                   "detail": "Done." if prof else "Add your resume or experience in Profile."})
    since = now - timedelta(days=30)
    matched = sum(1 for j in _jobs(c, user["id"]) if j.get("foundVia") in FEED_SOURCES and j.get("stage") != "skipped"
                  and (_dt(j.get("foundAt")) or datetime.min.replace(tzinfo=timezone.utc)) >= since)
    need = cfg.guarantee_min_matches
    checks.append({"id": "matches", "ok": matched >= need, "advisory": True, "count": matched,
                   "label": f"Roles matched to you in the last 30 days: {matched}",
                   "detail": "Plenty for the guarantee." if matched >= need else
                   f"The team looks for about {need}, so we only promise where Propelo finds roles for you. Widen your job families, places or experience in Settings."})
    return {"ok": all(x["ok"] for x in checks if not x.get("advisory")), "checks": checks, "checkedAt": _iso(now)}


def progress(c: Conn, cfg: Config, g: dict, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    start, end = _dt(g["starts_at"]), _dt(g["ends_at"])
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


def activity_done(cfg: Config, p: dict) -> bool:
    return p.get("applications", 0) >= cfg.guarantee_min_apps and p.get("weeks", 0) >= cfg.guarantee_min_weeks


# ---------------------------------------------------------------- what the member sees
def _view_row(c: Conn, cfg: Config, g: dict | None) -> dict | None:
    if not g:
        return None
    return {"id": g["id"], "kind": g["kind"], "status": g["status"], "plan": g["plan"], "currency": g["currency"],
            "startsAt": g["starts_at"], "endsAt": g["ends_at"], "agreedAt": g["agreed_at"], "termsVersion": g["terms_version"],
            "application": json.loads(g.get("application") or "{}"), "reviewedAt": g.get("reviewed_at"),
            "progress": json.loads(g["progress"] or "{}"), "reason": g["reason"], "claimedAt": g["claimed_at"], "decidedAt": g["decided_at"],
            "refund": g["refund_amount"], "price": g.get("price") or 0, "paidAt": g.get("paid_at"),
            "payUrl": g.get("pay_url") if g["status"] == "pending" else None,
            "payBy": _iso(_dt(g["reviewed_at"]) + timedelta(days=PAY_WITHIN_DAYS)) if g["status"] in ("accepted", "pending") and g.get("reviewed_at") else None,
            "claimBy": _iso(_dt(g["ends_at"]) + timedelta(days=cfg.guarantee_claim_days)) if g["status"] in ("claimable",) else None,
            "estimate": refund_estimate(cfg, g["plan"], g["currency"], cfg.guarantee_days, g.get("price") or price_for(cfg, g["kind"], g["currency"]))}


def view(c: Conn, cfg: Config, user: dict) -> dict:
    g = row(c, user["id"], "interview")
    if g:
        g = _tidy(c, cfg, g)
    cur = _currency(c, user["id"])
    price = price_for(cfg, "interview", cur)
    live = g and g["status"] in LIVE
    return {"enabled": cfg.guarantee_enabled, "termsVersion": TERMS_VERSION, "planAllows": plans.plan_of(c, user) in PLANS_WITH_GUARANTEE,
            "rules": {"days": cfg.guarantee_days, "minApplications": cfg.guarantee_min_apps, "minWeeks": cfg.guarantee_min_weeks,
                      "minMatches": cfg.guarantee_min_matches, "claimDays": cfg.guarantee_claim_days, "payWithinDays": PAY_WITHIN_DAYS},
            "interview": {"current": _view_row(c, cfg, g), "eligibility": None if live else eligibility(c, cfg, user),
                          "currency": cur, "price": price, "canPay": bool(_payer(cfg, cur))},
            "job": {"concierge": cfg.concierge_enabled, "rateLow": cfg.concierge_rate_low, "rateHigh": cfg.concierge_rate_high,
                    "band": cfg.concierge_band, "countries": [x for x in cfg.concierge_countries if x not in ("GB", "UK")]}}


# ---------------------------------------------------------------- apply, review, pay
def apply(c: Conn, cfg: Config, user: dict, application: dict, ip: str, now: datetime | None = None) -> dict:
    if not cfg.guarantee_enabled:
        raise GuaranteeError("Guarantees aren't available on this server.")
    now = now or datetime.now(timezone.utc)
    old = row(c, user["id"])
    if old:
        old = _tidy(c, cfg, old, now)
    if old and old["status"] in LIVE:
        raise GuaranteeError("You've already applied." if old["status"] in ("applied", "accepted", "pending") else "You already have the Interview Guarantee.")
    elig = eligibility(c, cfg, user, now=now)
    if not elig["ok"]:
        missing = "; ".join(x["label"] for x in elig["checks"] if not x["ok"] and not x.get("advisory"))
        raise GuaranteeError("You can't apply yet: " + missing + ".")
    roles = " ".join(str(application.get("roles") or "").split())[:300]
    if len(roles) < 3:
        raise GuaranteeError("Tell us which roles you're aiming for.")
    app = {"roles": roles, "note": " ".join(str(application.get("note") or "").split())[:1500]}
    plan, cur = plans.plan_of(c, user), _currency(c, user["id"])
    stamp = now_iso()
    vals = (plan, cur, TERMS_VERSION, stamp, ip[:64], stamp, stamp, json.dumps(elig), price_for(cfg, "interview", cur), json.dumps(app), stamp)
    if old:
        c.execute("UPDATE guarantees SET status = 'applied', plan = ?, currency = ?, terms_version = ?, agreed_at = ?, agreed_ip = ?, starts_at = ?, ends_at = ?, "
                  "eligibility = ?, price = ?, application = ?, updated_at = ?, progress = '{}', reason = NULL, met_at = NULL, claimed_at = NULL, "
                  "claim_note = NULL, decided_by = NULL, decided_at = NULL, refund_amount = NULL, pay_provider = NULL, pay_ref = NULL, pay_url = NULL, "
                  "paid_at = NULL, reviewed_by = NULL, reviewed_at = NULL WHERE id = ?", vals + (old["id"],))
        gid = old["id"]
    else:
        gid = repo.new_id()
        c.execute("INSERT INTO guarantees(id, user_id, kind, status, plan, currency, terms_version, agreed_at, agreed_ip, starts_at, ends_at, eligibility, "
                  "price, application, updated_at, created_at) VALUES (?, ?, 'interview', 'applied', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                  (gid, user["id"]) + vals + (stamp,))
    repo.audit(c, user["id"], "guarantee-interview-applied", ip, {"terms": TERMS_VERSION, "plan": plan})
    return c.one("SELECT * FROM guarantees WHERE id = ?", (gid,))


def review(c: Conn, staff_uid: str, gid: str, decision: str, note: str) -> dict:
    g = c.one("SELECT * FROM guarantees WHERE id = ?", (gid,))
    if not g:
        raise GuaranteeError("Not found.")
    if g["status"] != "applied":
        raise GuaranteeError("Only an application waiting for review can be accepted or declined.")
    note = " ".join(str(note or "").split())[:1000]
    if decision == "accept":
        g = _set(c, g, "accepted", note or f"Accepted. Pay within {PAY_WITHIN_DAYS} days to start your 45 days.", reviewed_by=staff_uid, reviewed_at=now_iso())
    elif decision == "decline":
        if len(note) < 10:
            raise GuaranteeError("Say why, in a sentence the member will read.")
        g = _set(c, g, "declined", note, reviewed_by=staff_uid, reviewed_at=now_iso())
    else:
        raise GuaranteeError("Not found.")
    repo.audit(c, staff_uid, f"guarantee-{decision}", "", {"guarantee": gid})
    return g


def _payer(cfg: Config, currency: str) -> str:
    if currency == "USD":
        return "dodo" if cfg.dodo_enabled and cfg.dodo_product_guarantee else ""
    return "razorpay" if cfg.razorpay_key_id and cfg.razorpay_key_secret else ""


def checkout(cfg: Config, user: dict, g: dict, post=None) -> dict:
    """A one-time payment: a Razorpay payment link in rupees, a Dodo checkout in dollars. Returns {provider, id, url}.
    The guarantee starts on the provider's paid webhook, never on this call."""
    if _payer(cfg, g["currency"]) == "razorpay":
        post = post or plans._post
        r = post(f"{plans.RAZORPAY_API}/payment_links", {
            "amount": int(g["price"]), "currency": "INR", "accept_partial": False, "description": f"Propelo Interview Guarantee ({cfg.guarantee_days} days)",
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
    raise GuaranteeError("Payments for the guarantee aren't set up on this server yet.")


def _tidy(c: Conn, cfg: Config, g: dict, now: datetime | None = None) -> dict:
    """Lapse unpaid acceptances and checkouts; move an active guarantee on."""
    now = now or datetime.now(timezone.utc)
    if g["status"] in ("accepted", "pending") and now - (_dt(g.get("reviewed_at")) or now) > timedelta(days=PAY_WITHIN_DAYS):
        return _set(c, g, "void", f"The acceptance lapsed because it wasn't paid within {PAY_WITHIN_DAYS} days. You can apply again.")
    if g["status"] == "pending" and now - (_dt(g["updated_at"]) or now) > timedelta(days=2):
        return _set(c, g, "accepted", "The last checkout wasn't completed. Pay again to start.", pay_url=None, pay_ref=None)
    if g["status"] in ("active", "claimable"):
        return _refresh_one(c, cfg, g, now)[0]
    return g


def buy(c: Conn, cfg: Config, user: dict, kind: str, ip: str, pay=None, now: datetime | None = None) -> dict:
    """Pay for an accepted application. A checkout still open is reused."""
    if not cfg.guarantee_enabled:
        raise GuaranteeError("Guarantees aren't available on this server.")
    if kind != "interview":
        raise GuaranteeError("The Job Guarantee has no upfront price: apply for it through Concierge.")
    g = row(c, user["id"])
    if g:
        g = _tidy(c, cfg, g, now)
    if not g or g["status"] in ("applied",):
        raise GuaranteeError("Apply first. You pay only after the team accepts your application." if not g else "Your application is still being reviewed.")
    if g["status"] == "pending" and g.get("pay_url"):
        return g
    if g["status"] != "accepted":
        raise GuaranteeError("There's nothing to pay for right now.")
    if plans.plan_of(c, user) not in PLANS_WITH_GUARANTEE:
        raise GuaranteeError("The Interview Guarantee is for Pro and Ultra members.")
    cur = _currency(c, user["id"])
    c.execute("UPDATE guarantees SET currency = ?, price = ? WHERE id = ?", (cur, price_for(cfg, "interview", cur), g["id"]))
    g = c.one("SELECT * FROM guarantees WHERE id = ?", (g["id"],))
    got = (pay or checkout)(cfg, user, g)
    g = _set(c, g, "pending", None, pay_provider=got["provider"], pay_ref=got["id"][:120], pay_url=got["url"][:600])
    repo.audit(c, user["id"], "guarantee-interview-checkout", ip, {"price": g["price"], "currency": g["currency"]})
    return g


def activate(c: Conn, cfg: Config, g: dict, provider: str, now: datetime | None = None) -> dict:
    """The payment went through: the window starts now."""
    now = now or datetime.now(timezone.utc)
    g = _set(c, g, "active", None, starts_at=_iso(now), ends_at=_iso(now + timedelta(days=cfg.guarantee_days)), paid_at=now_iso(), pay_provider=provider)
    repo.audit(c, g["user_id"], "guarantee-interview-paid", "", {"provider": provider, "price": g["price"], "currency": g["currency"]})
    return g


def mark_paid(c: Conn, cfg: Config, provider: str, ref: str = "", guarantee_id: str = "", amount: int | None = None) -> tuple[str, dict | None]:
    """From a verified webhook. Returns (result, row)."""
    g = c.one("SELECT * FROM guarantees WHERE pay_ref = ?", (ref,)) if ref else None
    if not g and guarantee_id:
        g = c.one("SELECT * FROM guarantees WHERE id = ?", (guarantee_id,))
    if not g:
        return "unknown", None
    if g["status"] not in ("pending", "accepted"):
        return "duplicate", g
    if amount is not None and int(amount) < int(g["price"] or 0):
        return "short", g
    return "paid", activate(c, cfg, g, provider)


def grant(c: Conn, cfg: Config, uid: str, kind: str, by: str) -> dict:
    """The operator starts the guarantee without application or payment (goodwill or testing)."""
    user = c.one("SELECT * FROM users WHERE id = ?", (uid,))
    g = row(c, uid)
    if not g or g["status"] not in LIVE:
        g = apply(c, cfg, user, {"roles": "Granted by the team"}, "")
    g = _set(c, g, "accepted", "Granted by the team.", reviewed_by=by, reviewed_at=now_iso())
    g = activate(c, cfg, g, "grant")
    c.execute("UPDATE guarantees SET price = 0 WHERE id = ?", (g["id"],))
    repo.audit(c, by, "guarantee-granted", "", {"user": uid})
    return c.one("SELECT * FROM guarantees WHERE id = ?", (g["id"],))


# ---------------------------------------------------------------- the window
def _refresh_one(c: Conn, cfg: Config, g: dict, now: datetime | None = None) -> tuple[dict, str | None]:
    now = now or datetime.now(timezone.utc)
    user = c.one("SELECT id, is_admin FROM users WHERE id = ?", (g["user_id"],)) or {"id": g["user_id"], "is_admin": 0}
    if g["status"] == "active":
        p = progress(c, cfg, g, now)
        c.execute("UPDATE guarantees SET progress = ?, updated_at = ? WHERE id = ?", (json.dumps(p), now_iso(), g["id"]))
        g = dict(g, progress=json.dumps(p))
        if p.get("interviews"):
            return _set(c, g, "met", "Done: you got an interview.", met_at=now_iso()), "met"
        ended = now >= _dt(g["ends_at"])
        if not ended and plans.plan_of(c, user) not in PLANS_WITH_GUARANTEE:
            return _set(c, g, "void", "Your plan ended before the guarantee window did."), "void"
        if ended:
            if activity_done(cfg, p):
                return _set(c, g, "claimable", "The window ended with no interview. You can claim your refund."), "claimable"
            return _set(c, g, "ended", f"The window ended with {p.get('applications', 0)} applications in {p.get('weeks', 0)} weeks; "
                                       f"the guarantee needs {cfg.guarantee_min_apps} in {cfg.guarantee_min_weeks}."), "ended"
    elif g["status"] == "claimable" and now >= _dt(g["ends_at"]) + timedelta(days=cfg.guarantee_claim_days):
        return _set(c, g, "ended", "The time to claim passed."), "ended"
    return g, None


def refresh(c: Conn, cfg: Config, now: datetime | None = None) -> list[tuple[str, str, str]]:
    """Run by the worker. Returns (email, kind, event) for changes worth an email."""
    out = []
    for g in c.all("SELECT * FROM guarantees WHERE status IN ('accepted', 'pending')"):
        _tidy(c, cfg, g, now)
    for g in c.all("SELECT * FROM guarantees WHERE status IN ('active', 'claimable')"):
        g2, event = _refresh_one(c, cfg, g, now)
        if event in ("met", "claimable", "void"):
            u = c.one("SELECT email FROM users WHERE id = ?", (g2["user_id"],))
            if u:
                out.append((u["email"], g2["kind"], event))
    return out


def claim(c: Conn, cfg: Config, uid: str, kind: str, attest: bool, note: str, ip: str) -> dict:
    g = row(c, uid)
    if g and g["status"] == "active":
        g = _refresh_one(c, cfg, g)[0]
    if not g or g["status"] != "claimable":
        raise GuaranteeError("There's nothing to claim yet." if not g or g["status"] == "active" else "This guarantee can't be claimed.")
    if attest is not True:
        raise GuaranteeError("Confirm that you had no interview or interview invitation in the window.")
    g = _set(c, g, "claimed", "Claim received. A person on the team checks it within 5 working days.", claimed_at=now_iso(),
             claim_note=" ".join(str(note or "").split())[:2000])
    repo.audit(c, uid, "guarantee-interview-claimed", ip, {"progress": json.loads(g["progress"] or "{}")})
    return g


# ---------------------------------------------------------------- the team's side
def staff_list(c: Conn, cfg: Config) -> list[dict]:
    rows = c.all("SELECT g.*, u.email, u.name FROM guarantees g JOIN users u ON u.id = g.user_id "
                 "WHERE g.status IN ('applied', 'claimed', 'approved') ORDER BY g.updated_at")
    return [{"id": r["id"], "kind": r["kind"], "status": r["status"], "plan": r["plan"], "currency": r["currency"], "name": r["name"], "email": r["email"],
             "startsAt": r["starts_at"], "endsAt": r["ends_at"], "claimedAt": r["claimed_at"], "appliedAt": r["agreed_at"], "note": r["claim_note"],
             "application": json.loads(r.get("application") or "{}"),
             "progress": json.loads(r["progress"] or "{}"), "eligibility": json.loads(r["eligibility"] or "{}"), "refund": r["refund_amount"],
             "price": r.get("price") or 0, "paidVia": r.get("pay_provider"), "paymentRef": r.get("pay_ref"),
             "estimate": refund_estimate(cfg, r["plan"], r["currency"], cfg.guarantee_days, r.get("price") or 0)} for r in rows]


def decide(c: Conn, cfg: Config, staff_uid: str, gid: str, decision: str, note: str, amount: int | None) -> dict:
    if decision in ("accept", "decline"):
        return review(c, staff_uid, gid, decision, note)
    g = c.one("SELECT * FROM guarantees WHERE id = ?", (gid,))
    if not g:
        raise GuaranteeError("Not found.")
    note = " ".join(str(note or "").split())[:1000]
    if decision == "approve":
        if g["status"] != "claimed":
            raise GuaranteeError("Only a claim can be approved.")
        est = refund_estimate(cfg, g["plan"], g["currency"], cfg.guarantee_days, g.get("price") or 0)
        amt = est if amount is None else int(amount)
        if not 0 < amt <= est:
            raise GuaranteeError("The refund must be more than 0 and no more than the price paid for the guarantee.")
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
