"""Passes: Pro bought once for a fixed number of days, with nothing that renews.

Off unless PASS=on. A job search is a season, not a subscription: a student pays once (UPI or card through a
Razorpay payment link in rupees, a Dodo one-time checkout in dollars), gets Pro for PASS_DAYS, and is never charged
again. The plan comes from a `granted` subscription row that ends on a date, the same mechanism as an operator's
grant, so every plan check in the app already understands it.

A pass can't be bought on top of a running subscription (cancel that first), and buying a second pass while one is
running adds its days to the end. The plan starts on the provider's verified webhook, never on the checkout call.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from . import plans, repo
from .config import Config
from .db import Conn, now_iso
from .security import new_id


class PassError(RuntimeError):
    pass


def offer(cfg: Config) -> dict | None:
    """What is for sale, for the pricing and billing pages; None when passes are off."""
    if not cfg.pass_enabled:
        return None
    return {"plan": "pro", "days": cfg.pass_days, "priceInr": cfg.pass_inr, "priceUsd": plans.usd(cfg.pass_usd_cents),
            "currencies": [x for x in ("INR", "USD") if _payer(cfg, x)],
            "line": f"Pro for {cfg.pass_days} days. Pay once; nothing renews and there is nothing to cancel."}


def _payer(cfg: Config, currency: str) -> str:
    if currency == "USD":
        return "dodo" if cfg.dodo_api_key and cfg.dodo_webhook_secret and cfg.dodo_product_pass else ""
    return "razorpay" if cfg.razorpay_key_id and cfg.razorpay_key_secret and cfg.razorpay_webhook_secret else ""


def _is_pass(s: dict | None) -> bool:
    return bool(s and s["status"] == "granted" and str(s.get("granted_by") or "").startswith("pass:"))


def can_buy(c: Conn, user: dict) -> str:
    """"" when this account may buy a pass, else the reason."""
    s = plans.subscription(c, user["id"])
    if s and not _is_pass(s) and plans._paid_plan(s) != "free" and s["status"] != "granted":
        return "You already have a subscription. A pass is for accounts without one."
    return ""


def start(c: Conn, cfg: Config, user: dict, currency: str, post=None) -> dict:
    """Create the checkout. Returns {url}. Nothing changes on the account until the payment webhook arrives."""
    if not cfg.pass_enabled:
        raise PassError("Passes aren't on sale right now.")
    provider = _payer(cfg, currency)
    if not provider:
        raise PassError(f"Payments in {currency} aren't switched on yet.")
    why = can_buy(c, user)
    if why:
        raise PassError(why)
    pid, price = new_id(), (cfg.pass_usd_cents if currency == "USD" else cfg.pass_inr * 100)
    if provider == "razorpay":
        r = (post or plans._post)(f"{plans.RAZORPAY_API}/payment_links", {
            "amount": int(price), "currency": "INR", "accept_partial": False, "description": f"Propelo Pro pass ({cfg.pass_days} days, no renewal)",
            "customer": {"name": (user.get("name") or "")[:80], "email": user["email"][:120]}, "notify": {"email": True, "sms": False},
            "reference_id": pid[:40], "callback_url": f"{cfg.public_url}/app#setup", "callback_method": "get",
            "notes": {"user_id": user["id"], "pass_id": pid}}, cfg.razorpay_key_id, cfg.razorpay_key_secret)
        ref, url = str(r.get("id", "")), str(r.get("short_url", ""))
        if not ref.startswith("plink_") or not url.startswith("https://"):
            raise PassError("Razorpay returned an unexpected payment link.")
    else:
        d = plans.Dodo(cfg, post)
        r = d.call("POST", f"{d.base}/checkouts", {"product_cart": [{"product_id": cfg.dodo_product_pass, "quantity": 1}],
                   "customer": {"email": user["email"][:200], "name": (user.get("name") or user["email"].split("@")[0])[:120]},
                   "return_url": f"{cfg.public_url}/app#setup", "metadata": {"user_id": user["id"], "pass_id": pid}}, cfg.dodo_api_key)
        url, ref = str(r.get("checkout_url") or ""), str(r.get("session_id") or "")
        if not url.startswith("https://") or not ref:
            raise PassError("Dodo Payments returned an unexpected checkout.")
    c.execute("INSERT INTO passes(id, user_id, plan, days, price, currency, provider, pay_ref, status, created_at) VALUES (?, ?, 'pro', ?, ?, ?, ?, ?, 'pending', ?)",
              (pid, user["id"], cfg.pass_days, int(price), currency, provider, ref, now_iso()))
    return {"url": url, "id": pid}


def mark_paid(c: Conn, cfg: Config, provider: str, ref: str = "", pass_id: str = "", amount: int | None = None) -> tuple[str, dict | None]:
    """From a verified webhook: ("paid" | "duplicate" | "short" | "unknown", the pass)."""
    p = c.one("SELECT * FROM passes WHERE pay_ref = ?", (ref,)) if ref else None
    if not p and pass_id:
        p = c.one("SELECT * FROM passes WHERE id = ?", (pass_id,))
    if not p:
        return "unknown", None
    if p["status"] != "pending":
        return "duplicate", p
    if amount is not None and int(amount) < int(p["price"]):
        return "short", p
    now = datetime.now(timezone.utc)
    s = plans.subscription(c, p["user_id"])
    if s and not _is_pass(s) and plans._paid_plan(s) != "free" and s["status"] != "granted":
        # A subscription started between checkout and payment: keep it, record the pass as paid, and let support sort it out.
        ends = now + timedelta(days=int(p["days"]))
    else:
        base = now
        if _is_pass(s) and s["current_end"] and s["current_end"] > now_iso():
            base = datetime.fromisoformat(s["current_end"].replace("Z", "+00:00"))  # a second pass adds to the first
        ends = base + timedelta(days=int(p["days"]))
        stamp = now_iso()
        c.execute("DELETE FROM subscriptions WHERE user_id = ?", (p["user_id"],))
        c.execute("INSERT INTO subscriptions(user_id, plan, status, provider, current_end, granted_by, created_at, updated_at) "
                  "VALUES (?, ?, 'granted', 'pass', ?, ?, ?, ?)", (p["user_id"], p["plan"], ends.strftime("%Y-%m-%dT%H:%M:%SZ"), "pass:" + p["id"], stamp, stamp))
    c.execute("UPDATE passes SET status = 'paid', paid_at = ?, ends_at = ? WHERE id = ?", (now_iso(), ends.strftime("%Y-%m-%dT%H:%M:%SZ"), p["id"]))
    repo.audit(c, p["user_id"], "pass-paid", "", {"pass": p["id"], "days": p["days"], "provider": provider})
    return "paid", c.one("SELECT * FROM passes WHERE id = ?", (p["id"],))


def view(c: Conn, cfg: Config, user: dict) -> dict | None:
    """The offer plus this account's running pass, for the billing page."""
    o = offer(cfg)
    s = plans.subscription(c, user["id"])
    running = {"endsAt": s["current_end"]} if _is_pass(s) and s["current_end"] and s["current_end"] > now_iso() else None
    if not o and not running:
        return None
    return {**(o or {}), "onSale": bool(o), "running": running, "blocked": can_buy(c, user) if o else ""}
