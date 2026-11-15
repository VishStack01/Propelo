"""Interview Guarantee and Job Guarantee: paid add-ons for Pro and Ultra members, with money back on clear,
checkable conditions, never a promised job."""

import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone

import pytest

pytest.importorskip("fastapi")

from careeros.cloud import guarantee  # noqa: E402
from careeros.cloud.config import Config  # noqa: E402

T = {"agree": True, "termsVersion": guarantee.TERMS_VERSION}


def iso(d):
    return d.strftime("%Y-%m-%dT%H:%M:%SZ")


@pytest.fixture
def g(cloud, monkeypatch):
    cloud.cfg.guarantee_enabled = True
    cloud.cfg.razorpay_key_id, cloud.cfg.razorpay_key_secret, cloud.cfg.razorpay_webhook_secret = "rzp_test_k", "s", "whs"
    links = []

    def fake_post(url, body, key, secret):
        links.append(body)
        return {"id": f"plink_G{len(links)}", "short_url": f"https://rzp.io/i/g{len(links)}"}
    from careeros.cloud import plans
    monkeypatch.setattr(plans, "_post", fake_post)
    c = cloud.user()
    admin = cloud.user("admin@example.com")
    cloud.links = links
    return cloud, c, admin


def _paid(cloud, link_id, amount):
    """Razorpay tells us the payment link was paid (signed like the real webhook)."""
    ev = json.dumps({"event": "payment_link.paid", "payload": {"payment_link": {"entity": {"id": link_id, "status": "paid", "amount_paid": amount}}}}).encode()
    sig = hmac.new(b"whs", ev, hashlib.sha256).hexdigest()
    return cloud.client().post("/api/billing/webhook", content=ev, headers={"X-Razorpay-Signature": sig, "X-Razorpay-Event-Id": f"evt_{link_id}_{amount}",
                                                                            "Content-Type": "application/json"}).json()


def _buy(cloud, c, kind="interview"):
    v = c.post(f"/api/guarantee/{kind}/buy", json=T).json()
    assert v["payUrl"].startswith("https://rzp.io/"), v
    cur = v[kind]["current"]
    assert cur["status"] == "pending"
    assert _paid(cloud, f"plink_G{len(cloud.links)}", cur["price"])["result"] == "paid"
    return c.get("/api/guarantee").json()[kind]["current"]


def _ready(c, matches=40):
    now = datetime.now(timezone.utc)
    c.put("/api/d/profile/resume", json={"experience": [{"company": "Acme", "title": "Engineer"}]})
    for i in range(matches):
        c.put(f"/api/d/jobs/m{i}", json={"company": f"Co {i}", "title": "Backend Engineer", "stage": "found", "foundVia": "careers-feed",
                                         "foundAt": iso(now - timedelta(days=2))})


def _apply(c, n, start, weeks=5, **extra):
    for i in range(n):
        at = start + timedelta(days=(i % weeks) * 7 + 1)
        c.put(f"/api/d/jobs/a{i}", json=dict({"company": f"Applied {i}", "title": "Backend Engineer", "stage": "applied",
                                              "appliedAt": iso(at), "jd": "Build payment APIs in Go."}, **extra))


def _age(cloud, uid, kind="interview", days=61):
    """Move a guarantee's window into the past, as if `days` had gone by."""
    with cloud.db.tx() as x:
        r = x.one("SELECT * FROM guarantees WHERE user_id = ? AND kind = ?", (uid, kind))
        start = datetime.fromisoformat(r["starts_at"].replace("Z", "+00:00")) - timedelta(days=days)
        end = datetime.fromisoformat(r["ends_at"].replace("Z", "+00:00")) - timedelta(days=days)
        x.execute("UPDATE guarantees SET starts_at = ?, ends_at = ? WHERE id = ?", (guarantee._iso(start), guarantee._iso(end), r["id"]))
        return start, end


def test_prices_and_refunds():
    cfg = Config()
    assert guarantee.price_for(cfg, "interview", "INR") == 99_900 and guarantee.price_for(cfg, "interview", "USD") == 1_900
    assert guarantee.price_for(cfg, "job", "USD") == 299_900  # the Job Guarantee is sold in rupees only
    # money back: the add-on price plus the plan fees for the window
    assert guarantee.refund_estimate(cfg, "pro", "INR", 60, 99_900) == 2 * 49_900 + 99_900
    assert guarantee.refund_estimate(cfg, "ultra", "USD", 60, 1_900) == 2 * 4850 + 1_900
    assert guarantee.refund_estimate(cfg, "pro", "INR", 180, 299_900) == 6 * 49_900 + 299_900


def test_not_part_of_any_plan():
    from careeros.cloud import plans
    cfg = Config(guarantee_enabled=True)
    assert not any("Guarantee" in f for p in plans.catalog(cfg) for f in p["features"])
    ads = plans.addons(cfg)
    assert [a["id"] for a in ads] == ["interview", "job"] and ads[0]["priceInr"] == 999 and ads[0]["for"] == ["pro", "ultra"]
    assert plans.addons(Config()) == []


def test_eligibility_is_checked_and_shown_before_paying(g):
    cloud, c, admin = g
    v = c.get("/api/guarantee").json()
    checks = {x["id"]: x["ok"] for x in v["interview"]["eligibility"]["checks"]}
    assert checks == {"plan": False, "once": True, "profile": False, "matches": False}
    r = c.post("/api/guarantee/interview/buy", json=T)
    assert r.status_code == 400 and "Not eligible yet" in r.json()["error"] and not cloud.links  # no payment page for Free members
    admin.post("/api/admin/grant", json={"email": "asha@example.com", "plan": "pro"})
    _ready(c, matches=10)
    assert "40 roles" in c.post("/api/guarantee/interview/buy", json=T).json()["error"]  # only where Propelo finds roles for you
    _ready(c)
    assert c.post("/api/guarantee/interview/buy", json={"agree": True, "termsVersion": "old"}).status_code == 400
    v = c.post("/api/guarantee/interview/buy", json=T).json()
    assert v["interview"]["current"]["status"] == "pending" and cloud.links[0]["amount"] == 99_900 and cloud.links[0]["currency"] == "INR"
    assert not any("Interview Guarantee" in m["subject"] for m in cloud.outbox)  # nothing starts before payment
    again = c.post("/api/guarantee/interview/buy", json=T).json()
    assert again["payUrl"] == v["payUrl"] and len(cloud.links) == 1  # an open checkout is reused
    assert _paid(cloud, "plink_G1", 50_000)["result"] == "short"  # underpaid: doesn't start
    assert _paid(cloud, "plink_G1", 99_900)["result"] == "paid"
    cur = c.get("/api/guarantee").json()["interview"]["current"]
    assert cur["status"] == "active" and cur["plan"] == "pro" and cur["price"] == 99_900 and cur["estimate"] == 2 * 49_900 + 99_900
    assert any("Interview Guarantee" in m["subject"] for m in cloud.outbox)
    assert c.post("/api/guarantee/interview/buy", json=T).status_code == 400  # one at a time


def test_an_interview_completes_the_guarantee(g):
    cloud, c, admin = g
    admin.post("/api/admin/grant", json={"email": "asha@example.com", "plan": "pro"})
    _ready(c)
    _buy(cloud, c)
    now = datetime.now(timezone.utc) + timedelta(seconds=5)
    c.put("/api/d/jobs/win", json={"company": "Northwind", "title": "Backend Engineer", "stage": "screen", "appliedAt": iso(now), "screenAt": iso(now)})
    cur = c.get("/api/guarantee").json()["interview"]["current"]
    assert cur["status"] == "met" and cur["progress"]["interviews"] == 1


def test_claim_after_the_window_with_the_activity_done(g):
    cloud, c, admin = g
    admin.post("/api/admin/grant", json={"email": "asha@example.com", "plan": "pro", "until": "2099-01-01"})
    _ready(c)
    _buy(cloud, c)
    assert c.post("/api/guarantee/interview/claim", json={"attest": True}).status_code == 400  # nothing to claim yet
    start, end = _age(cloud, c.uid)
    _apply(c, 30, start)
    # applications to unsafe postings don't count
    c.put("/api/d/jobs/scam", json={"company": "X", "title": "Data entry", "stage": "applied", "appliedAt": iso(start + timedelta(days=3)),
                                    "jd": "Pay a registration fee of Rs 500 to join."})
    cur = c.get("/api/guarantee").json()["interview"]["current"]
    assert cur["status"] == "claimable" and cur["progress"]["applications"] == 30 and cur["progress"]["unsafeSkipped"] == 1
    assert c.post("/api/guarantee/interview/claim", json={"attest": False}).status_code == 400
    v = c.post("/api/guarantee/interview/claim", json={"attest": True, "note": "Applied every week."}).json()
    assert v["interview"]["current"]["status"] == "claimed"
    assert any(m["subject"] == "New guarantee claim" for m in cloud.outbox)

    # the team decides; candidates can't see the claims list
    assert c.get("/api/staff/guarantees").status_code == 404
    claims = admin.get("/api/staff/guarantees").json()["claims"]
    assert len(claims) == 1 and claims[0]["progress"]["applications"] == 30
    gid = claims[0]["id"]
    assert admin.post(f"/api/staff/guarantees/{gid}/approve", json={"amount": 999_999}).status_code == 400  # never more than add-on + fees
    assert admin.post(f"/api/staff/guarantees/{gid}/refunded").status_code == 400  # approve first
    admin.post(f"/api/staff/guarantees/{gid}/approve", json={})
    assert c.get("/api/guarantee").json()["interview"]["current"]["refund"] == 2 * 49_900 + 99_900
    admin.post(f"/api/staff/guarantees/{gid}/refunded", json={"note": "Refunded in Razorpay."})
    v = c.get("/api/guarantee").json()["interview"]
    assert v["current"]["status"] == "refunded"
    # once per account
    with cloud.db.tx() as x:
        x.execute("UPDATE guarantees SET status = 'ended' WHERE id = ?", (gid,))
    assert "already had this guarantee refunded" in str(c.get("/api/guarantee").json()["interview"]["eligibility"])


def test_too_little_activity_ends_without_a_refund(g):
    cloud, c, admin = g
    admin.post("/api/admin/grant", json={"email": "asha@example.com", "plan": "pro", "until": "2099-01-01"})
    _ready(c)
    _buy(cloud, c)
    start, _ = _age(cloud, c.uid)
    _apply(c, 30, start, weeks=2)  # all in two weeks: the guarantee asks for four
    cur = c.get("/api/guarantee").json()["interview"]["current"]
    assert cur["status"] == "ended" and "needs 30 in 4" in cur["reason"]


def test_plan_ending_early_voids_it(g):
    cloud, c, admin = g
    admin.post("/api/admin/grant", json={"email": "asha@example.com", "plan": "pro"})
    _ready(c)
    _buy(cloud, c)
    with cloud.db.tx() as x:
        x.execute("DELETE FROM subscriptions WHERE user_id = ?", (c.uid,))
    with cloud.db.tx() as x:
        moved = guarantee.refresh(x, cloud.cfg)
    assert moved == [("asha@example.com", "interview", "void")]


def test_job_guarantee_needs_concierge(g):
    cloud, c, admin = g
    assert c.post("/api/guarantee/job/buy", json=T).json()["error"].startswith("The Job Guarantee comes with Concierge")
    cloud.cfg.concierge_enabled = True
    admin.post("/api/admin/grant", json={"email": "asha@example.com", "plan": "ultra"})
    assert "open Concierge case" in c.post("/api/guarantee/job/buy", json=T).json()["error"]
    from careeros.cloud import concierge
    c.post("/api/concierge/request", json={"agree": True, "termsVersion": concierge.TERMS_VERSION, "country": "IN",
                                           "intake": {"roles": "Backend", "locations": "Bengaluru", "currentCtc": 1, "expectedCtc": 2}})
    cur = _buy(cloud, c, "job")
    assert cur["status"] == "active" and cur["price"] == 299_900 and cur["estimate"] == 6 * 119_900 + 299_900
    _age(cloud, c.uid, "job", days=181)
    assert c.get("/api/guarantee").json()["job"]["current"]["status"] == "claimable"


def test_guarantees_off_by_default(cloud):
    c = cloud.user()
    assert cloud.cfg.guarantee_enabled is False
    assert c.post("/api/guarantee/interview/buy", json=T).json()["error"] == "Guarantees aren't available on this server."


def test_unpaid_checkout_lapses_and_admin_can_grant(g):
    cloud, c, admin = g
    admin.post("/api/admin/grant", json={"email": "asha@example.com", "plan": "pro"})
    _ready(c)
    c.post("/api/guarantee/interview/buy", json=T)
    with cloud.db.tx() as x:
        x.execute("UPDATE guarantees SET agreed_at = ? WHERE user_id = ?", ("2020-01-01T00:00:00.000000Z", c.uid))
    v = c.get("/api/guarantee").json()["interview"]
    assert v["current"]["status"] == "void" and v["eligibility"]["ok"]
    r = admin.post("/api/admin/guarantee", json={"email": "asha@example.com", "kind": "interview"}).json()
    assert r["status"] == "active"
    assert c.get("/api/guarantee").json()["interview"]["current"]["price"] == 0  # granted, nothing paid


def test_dollar_checkout_through_dodo(g, monkeypatch):
    cloud, c, admin = g
    from careeros.cloud import plans
    cloud.cfg.dodo_api_key, cloud.cfg.dodo_webhook_secret, cloud.cfg.dodo_product_pro, cloud.cfg.dodo_product_guarantee = "k", "whsec_dGVzdHNlY3JldA==", "pdt_P", "pdt_G"
    calls = []
    monkeypatch.setattr(plans, "_dodo_request", lambda m, u, b, k: calls.append(b) or {"checkout_url": "https://checkout.dodo.example/s1", "session_id": "cks_1"})
    admin.post("/api/admin/grant", json={"email": "asha@example.com", "plan": "pro"})
    with cloud.db.tx() as x:
        x.execute("UPDATE subscriptions SET currency = 'USD' WHERE user_id = ?", (c.uid,))
    _ready(c)
    v = c.post("/api/guarantee/interview/buy", json=T).json()
    assert v["payUrl"] == "https://checkout.dodo.example/s1" and calls[0]["product_cart"][0]["product_id"] == "pdt_G"
    gid = v["interview"]["current"]["id"]
    assert v["interview"]["current"]["price"] == 1_900 and calls[0]["metadata"]["guarantee_id"] == gid
