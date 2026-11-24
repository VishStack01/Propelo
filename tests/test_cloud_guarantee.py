"""The Interview Guarantee: Pro and Ultra members apply, the team reviews, an accepted member pays once ($59, through
Dodo) and gets the price back if the interviews don't come. Money back, never a promised job. (The Job Guarantee, an
India-only Concierge service, is retired and off; its backend still works with CONCIERGE=on.)"""

import base64
import hashlib
import hmac
import json
import time
from datetime import datetime, timedelta, timezone

import pytest

pytest.importorskip("fastapi")

from propelo.cloud import guarantee  # noqa: E402
from propelo.cloud.config import Config  # noqa: E402

T = {"agree": True, "termsVersion": guarantee.TERMS_VERSION}


def iso(d):
    return d.strftime("%Y-%m-%dT%H:%M:%SZ")


DODO_SECRET = "whsec_" + base64.b64encode(b"dodo-guarantee-secret-0123").decode()


@pytest.fixture
def g(cloud, monkeypatch):
    cloud.cfg.guarantee_enabled = True
    cloud.cfg.dodo_api_key, cloud.cfg.dodo_webhook_secret = "dodo_test_key", DODO_SECRET
    cloud.cfg.dodo_product_pro, cloud.cfg.dodo_product_guarantee = "pdt_PRO", "pdt_GUAR"
    links = []

    def fake_call(method, url, body, key):
        links.append(body)
        return {"session_id": f"cks_G{len(links)}", "checkout_url": f"https://test.checkout.dodopayments.com/g{len(links)}"}
    from propelo.cloud import plans
    monkeypatch.setattr(plans, "_dodo_request", fake_call)
    c = cloud.user()
    admin = cloud.user("admin@example.com")
    cloud.links = links
    return cloud, c, admin


def _paid(cloud, n, amount):
    """Dodo tells us checkout number n was paid (signed like the real Standard Webhook)."""
    gid = cloud.links[n - 1]["metadata"]["guarantee_id"]
    body = json.dumps({"type": "payment.succeeded", "timestamp": "2026-11-25T00:00:00Z",
                       "data": {"payment_id": f"pay_{n}_{amount}", "total_amount": amount, "metadata": {"guarantee_id": gid}}}).encode()
    wid, ts = f"msg_{n}_{amount}", str(int(time.time()))
    sig = base64.b64encode(hmac.new(base64.b64decode(DODO_SECRET[6:]), f"{wid}.{ts}.".encode() + body, hashlib.sha256).digest()).decode()
    return cloud.client().post("/api/billing/dodo-webhook", content=body, headers={
        "Content-Type": "application/json", "webhook-id": wid, "webhook-timestamp": ts, "webhook-signature": f"v1,{sig}"}).json()


def _applied(c, roles="Backend engineer"):
    return c.post("/api/guarantee/interview/apply", json=dict(T, roles=roles, note="Notice period 30 days."))


def _accept(admin, note=""):
    gid = [x for x in admin.get("/api/staff/guarantees").json()["claims"] if x["status"] == "applied"][0]["id"]
    assert admin.post(f"/api/staff/guarantees/{gid}/accept", json={"note": note}).status_code == 200
    return gid


def _buy(cloud, c, admin):
    """Apply, get accepted, pay through the signed webhook."""
    assert _applied(c).status_code == 200
    _accept(admin)
    v = c.post("/api/guarantee/interview/buy", json=T).json()
    assert v["payUrl"].startswith("https://test.checkout.dodopayments.com/"), v
    cur = v["interview"]["current"]
    assert cur["status"] == "pending"
    assert _paid(cloud, len(cloud.links), cur["price"])["result"] == "paid"
    return c.get("/api/guarantee").json()["interview"]["current"]


def _ready(c, matches=40):
    now = datetime.now(timezone.utc)
    c.put("/api/d/profile/resume", json={"experience": [{"company": "Acme", "title": "Engineer"}]})
    for i in range(matches):
        c.put(f"/api/d/jobs/m{i}", json={"company": f"Co {i}", "title": "Backend Engineer", "stage": "found", "foundVia": "careers-feed",
                                         "foundAt": iso(now - timedelta(days=2))})


def _apply(c, n, start, weeks=3, **extra):
    for i in range(n):
        at = start + timedelta(days=(i % weeks) * 7 + 1)
        c.put(f"/api/d/jobs/a{i}", json=dict({"company": f"Applied {i}", "title": "Backend Engineer", "stage": "applied",
                                              "appliedAt": iso(at), "jd": "Build payment APIs in Go."}, **extra))


def _age(cloud, uid, kind="interview", days=46):
    """Move a guarantee's window into the past, as if `days` had gone by."""
    with cloud.db.tx() as x:
        r = x.one("SELECT * FROM guarantees WHERE user_id = ? AND kind = ?", (uid, kind))
        start = datetime.fromisoformat(r["starts_at"].replace("Z", "+00:00")) - timedelta(days=days)
        end = datetime.fromisoformat(r["ends_at"].replace("Z", "+00:00")) - timedelta(days=days)
        x.execute("UPDATE guarantees SET starts_at = ?, ends_at = ? WHERE id = ?", (guarantee._iso(start), guarantee._iso(end), r["id"]))
        return start, end


def test_prices_and_refunds():
    cfg = Config()
    assert cfg.guarantee_days == 45 and cfg.guarantee_min_apps == 25 and cfg.guarantee_min_weeks == 3
    assert guarantee.price_for(cfg, "interview", "USD") == 5_900 and guarantee.price_for(cfg, "interview") == 5_900
    # money back: exactly the price paid for the guarantee, never the plan fees
    assert guarantee.refund_estimate(cfg, "ultra", "USD", 45, 5_900) == 5_900


def test_not_part_of_any_plan():
    from propelo.cloud import plans
    cfg = Config(guarantee_enabled=True, concierge_enabled=True)
    assert not any("Guarantee" in f for p in plans.catalog(cfg) for f in p["features"])
    ads = plans.addons(cfg)
    # Only the Interview Guarantee is offered, even where the retired Job Guarantee (Concierge) is still switched on.
    assert [a["id"] for a in ads] == ["interview"] and ads[0]["priceUsd"] == "59.00" and ads[0]["for"] == ["pro", "ultra"]
    assert "priceInr" not in ads[0] and "India" not in json.dumps(ads)
    assert plans.addons(Config()) == []


def test_nobody_is_enrolled_directly(g):
    cloud, c, admin = g
    v = c.get("/api/guarantee").json()
    checks = {x["id"]: x["ok"] for x in v["interview"]["eligibility"]["checks"]}
    assert checks == {"plan": False, "once": True, "profile": False, "matches": False} and v["planAllows"] is False
    assert "Pro or Ultra" in _applied(c).json()["error"]  # Free members can't apply
    admin.post("/api/admin/grant", json={"email": "asha@example.com", "plan": "pro"})
    _ready(c, matches=5)  # few matches: advisory, the team weighs it
    assert c.post("/api/guarantee/interview/apply", json={"agree": True, "termsVersion": "old", "roles": "Backend"}).status_code == 400
    assert c.post("/api/guarantee/interview/apply", json=dict(T, roles="")).status_code == 400
    # paying before acceptance isn't possible
    assert "Apply first" in c.post("/api/guarantee/interview/buy", json=T).json()["error"]
    v = _applied(c).json()
    cur = v["interview"]["current"]
    assert cur["status"] == "applied" and cur["application"]["roles"] == "Backend engineer" and not cloud.links
    assert any(m["subject"] == "We got your Interview Guarantee application" for m in cloud.outbox)
    assert any(m["subject"] == "New Interview Guarantee application" for m in cloud.outbox)
    assert "being reviewed" in c.post("/api/guarantee/interview/buy", json=T).json()["error"]
    assert _applied(c).status_code == 400  # one application at a time
    # the team sees it with the advisory match count, and members can't see the list
    assert c.get("/api/staff/guarantees").status_code == 404
    row = [x for x in admin.get("/api/staff/guarantees").json()["claims"] if x["status"] == "applied"][0]
    assert row["application"]["note"] == "Notice period 30 days." and any(x["id"] == "matches" and x["count"] == 5 for x in row["eligibility"]["checks"])
    # a decline needs a reason the member reads
    assert admin.post(f"/api/staff/guarantees/{row['id']}/decline", json={"note": "no"}).status_code == 400
    admin.post(f"/api/staff/guarantees/{row['id']}/decline", json={"note": "Too few roles match your filters yet. Widen your cities and apply again."})
    v = c.get("/api/guarantee").json()["interview"]
    assert v["current"]["status"] == "declined" and "Widen your cities" in v["current"]["reason"] and v["eligibility"]["ok"]
    assert any(m["subject"] == "About your Interview Guarantee application" for m in cloud.outbox)
    assert _applied(c).json()["interview"]["current"]["status"] == "applied"  # can apply again


def test_accepted_then_paid_starts_the_window(g):
    cloud, c, admin = g
    admin.post("/api/admin/grant", json={"email": "asha@example.com", "plan": "pro"})
    _ready(c)
    _applied(c)
    _accept(admin)
    assert any(m["subject"] == "Your Interview Guarantee is accepted" for m in cloud.outbox)
    v = c.get("/api/guarantee").json()["interview"]
    assert v["current"]["status"] == "accepted" and v["current"]["payBy"] and v["price"] == 5_900
    v = c.post("/api/guarantee/interview/buy", json=T).json()
    assert v["interview"]["current"]["status"] == "pending" and cloud.links[0]["product_cart"] == [{"product_id": "pdt_GUAR", "quantity": 1}]
    assert v["interview"]["current"]["currency"] == "USD"
    assert not any("has started" in m["subject"] for m in cloud.outbox)  # nothing starts before payment
    again = c.post("/api/guarantee/interview/buy", json=T).json()
    assert again["payUrl"] == v["payUrl"] and len(cloud.links) == 1  # an open checkout is reused
    assert _paid(cloud, 1, 500)["result"] == "short"  # underpaid: doesn't start
    assert _paid(cloud, 1, 5_900)["result"] == "paid"
    cur = c.get("/api/guarantee").json()["interview"]["current"]
    assert cur["status"] == "active" and cur["price"] == 5_900 and cur["estimate"] == 5_900
    days = (datetime.fromisoformat(cur["endsAt"].replace("Z", "+00:00")) - datetime.fromisoformat(cur["startsAt"].replace("Z", "+00:00"))).days
    assert days == 45
    assert c.post("/api/guarantee/interview/buy", json=T).status_code == 400


def test_an_interview_completes_the_guarantee(g):
    cloud, c, admin = g
    admin.post("/api/admin/grant", json={"email": "asha@example.com", "plan": "pro"})
    _ready(c)
    _buy(cloud, c, admin)
    now = datetime.now(timezone.utc) + timedelta(seconds=5)
    c.put("/api/d/jobs/win", json={"company": "Northwind", "title": "Backend Engineer", "stage": "screen", "appliedAt": iso(now), "screenAt": iso(now)})
    cur = c.get("/api/guarantee").json()["interview"]["current"]
    assert cur["status"] == "active" and cur["progress"]["interviews"] == 1 and cur["progress"]["needInterviews"] == 3  # one isn't enough
    c.put("/api/d/jobs/two", json={"company": "Tailspin", "title": "API Engineer", "stage": "screen", "appliedAt": iso(now), "screenAt": iso(now)})
    assert c.get("/api/guarantee").json()["interview"]["current"]["status"] == "active"
    c.put("/api/d/jobs/three", json={"company": "Contoso", "title": "Platform Engineer", "stage": "interview", "appliedAt": iso(now), "interviewStartedAt": iso(now)})
    cur = c.get("/api/guarantee").json()["interview"]["current"]
    assert cur["status"] == "met" and cur["progress"]["interviews"] == 3 and not cur["progress"]["secondRound"]


def test_a_second_round_completes_the_guarantee(g):
    cloud, c, admin = g
    admin.post("/api/admin/grant", json={"email": "asha@example.com", "plan": "pro"})
    _ready(c)
    _buy(cloud, c, admin)
    now = datetime.now(timezone.utc) + timedelta(seconds=5)
    c.put("/api/d/jobs/win", json={"company": "Northwind", "title": "Backend Engineer", "stage": "interview", "appliedAt": iso(now), "screenAt": iso(now),
                                   "interviewStartedAt": iso(now + timedelta(seconds=1))})
    cur = c.get("/api/guarantee").json()["interview"]["current"]
    assert cur["status"] == "met" and cur["progress"]["interviews"] == 1 and cur["progress"]["secondRound"] and "second round" in cur["reason"]


def test_earlier_terms_keep_the_one_interview_promise(g):
    cloud, c, admin = g
    admin.post("/api/admin/grant", json={"email": "asha@example.com", "plan": "pro"})
    _ready(c)
    _buy(cloud, c, admin)
    with cloud.db.tx() as k:
        k.execute("UPDATE guarantees SET terms_version = '2026-11-16b' WHERE user_id = ?", (c.uid,))
    now = datetime.now(timezone.utc) + timedelta(seconds=5)
    c.put("/api/d/jobs/win", json={"company": "Northwind", "title": "Backend Engineer", "stage": "screen", "appliedAt": iso(now), "screenAt": iso(now)})
    cur = c.get("/api/guarantee").json()["interview"]["current"]
    assert cur["status"] == "met" and cur["progress"]["needInterviews"] == 1


def test_claim_after_the_window_with_the_activity_done(g):
    cloud, c, admin = g
    admin.post("/api/admin/grant", json={"email": "asha@example.com", "plan": "pro", "until": "2099-01-01"})
    _ready(c)
    _buy(cloud, c, admin)
    assert c.post("/api/guarantee/interview/claim", json={"attest": True}).status_code == 400  # nothing to claim yet
    start, end = _age(cloud, c.uid)
    _apply(c, 26, start)
    c.put("/api/d/jobs/scam", json={"company": "X", "title": "Data entry", "stage": "applied", "appliedAt": iso(start + timedelta(days=3)),
                                    "jd": "Pay a registration fee of Rs 500 to join."})
    cur = c.get("/api/guarantee").json()["interview"]["current"]
    assert cur["status"] == "claimable" and cur["progress"]["applications"] == 26 and cur["progress"]["unsafeSkipped"] == 1
    assert c.post("/api/guarantee/interview/claim", json={"attest": False}).status_code == 400
    v = c.post("/api/guarantee/interview/claim", json={"attest": True, "note": "Applied every week."}).json()
    assert v["interview"]["current"]["status"] == "claimed"
    assert any(m["subject"] == "New guarantee claim" for m in cloud.outbox)
    claims = [x for x in admin.get("/api/staff/guarantees").json()["claims"] if x["status"] == "claimed"]
    gid = claims[0]["id"]
    assert admin.post(f"/api/staff/guarantees/{gid}/approve", json={"amount": 6_000}).status_code == 400  # never more than the price
    assert admin.post(f"/api/staff/guarantees/{gid}/refunded").status_code == 400  # approve first
    admin.post(f"/api/staff/guarantees/{gid}/approve", json={})
    assert c.get("/api/guarantee").json()["interview"]["current"]["refund"] == 5_900  # the full $59 back
    admin.post(f"/api/staff/guarantees/{gid}/refunded", json={"note": "Refunded in Dodo."})
    assert c.get("/api/guarantee").json()["interview"]["current"]["status"] == "refunded"
    with cloud.db.tx() as x:
        x.execute("UPDATE guarantees SET status = 'ended' WHERE id = ?", (gid,))
    assert "already had the Interview Guarantee refunded" in str(c.get("/api/guarantee").json()["interview"]["eligibility"])


def test_too_little_activity_ends_without_a_refund(g):
    cloud, c, admin = g
    admin.post("/api/admin/grant", json={"email": "asha@example.com", "plan": "pro", "until": "2099-01-01"})
    _ready(c)
    _buy(cloud, c, admin)
    start, _ = _age(cloud, c.uid)
    _apply(c, 26, start, weeks=1)  # all in one week: the guarantee asks for three
    cur = c.get("/api/guarantee").json()["interview"]["current"]
    assert cur["status"] == "ended" and "needs 25 in 3" in cur["reason"]


def test_plan_ending_early_voids_it(g):
    cloud, c, admin = g
    admin.post("/api/admin/grant", json={"email": "asha@example.com", "plan": "pro"})
    _ready(c)
    _buy(cloud, c, admin)
    with cloud.db.tx() as x:
        x.execute("DELETE FROM subscriptions WHERE user_id = ?", (c.uid,))
    with cloud.db.tx() as x:
        moved = guarantee.refresh(x, cloud.cfg)
    assert moved == [("asha@example.com", "interview", "void")]


def test_job_guarantee_has_no_upfront_price(g):
    cloud, c, admin = g
    admin.post("/api/admin/grant", json={"email": "asha@example.com", "plan": "ultra"})
    r = c.post("/api/guarantee/job/buy", json=T)
    assert r.status_code == 400 and "no upfront price" in r.json()["error"] and not cloud.links
    v = c.get("/api/guarantee").json()["job"]
    assert v["rateLow"] == cloud.cfg.concierge_rate_low and v["rateHigh"] == cloud.cfg.concierge_rate_high


def test_job_guarantee_applications_are_reviewed(g):
    cloud, c, admin = g
    cloud.cfg.concierge_enabled = True
    admin.post("/api/admin/grant", json={"email": "asha@example.com", "plan": "ultra"})
    from propelo.cloud import concierge
    r = c.post("/api/concierge/request", json={"agree": True, "termsVersion": concierge.TERMS_VERSION, "country": "IN",
                                               "intake": {"roles": "Backend", "locations": "Bengaluru", "currentCtc": 1, "expectedCtc": 2}})
    assert r.status_code == 200
    case = c.get("/api/concierge").json()["case"]
    assert case["status"] == "requested"
    assert admin.post(f"/api/staff/cases/{case['id']}/decline", json={"reason": "short"}).status_code == 400
    admin.post(f"/api/staff/cases/{case['id']}/decline", json={"reason": "We don't place backend roles in Bengaluru at this pay yet."})
    case = c.get("/api/concierge").json()["case"]
    assert case["status"] == "closed" and "Not accepted" in case["closedReason"]
    assert any("Job Guarantee" in m["subject"] or "Concierge" in m["subject"] for m in cloud.outbox)


def test_guarantees_off_by_default(cloud):
    c = cloud.user()
    assert cloud.cfg.guarantee_enabled is False
    assert _applied(c).json()["error"] == "Guarantees aren't available on this server."


def test_unpaid_acceptance_lapses_and_admin_can_grant(g):
    cloud, c, admin = g
    admin.post("/api/admin/grant", json={"email": "asha@example.com", "plan": "pro"})
    _ready(c)
    _applied(c)
    _accept(admin)
    c.post("/api/guarantee/interview/buy", json=T)
    with cloud.db.tx() as x:
        x.execute("UPDATE guarantees SET reviewed_at = ? WHERE user_id = ?", ("2020-01-01T00:00:00.000000Z", c.uid))
    v = c.get("/api/guarantee").json()["interview"]
    assert v["current"]["status"] == "void" and "wasn't paid within 7 days" in v["current"]["reason"] and v["eligibility"]["ok"]
    r = admin.post("/api/admin/guarantee", json={"email": "asha@example.com", "kind": "interview"}).json()
    assert r["status"] == "active"
    assert c.get("/api/guarantee").json()["interview"]["current"]["price"] == 0  # granted, nothing paid


def test_dollar_checkout_through_dodo(g, monkeypatch):
    cloud, c, admin = g
    from propelo.cloud import plans
    cloud.cfg.dodo_api_key, cloud.cfg.dodo_webhook_secret, cloud.cfg.dodo_product_pro, cloud.cfg.dodo_product_guarantee = "k", "whsec_dGVzdHNlY3JldA==", "pdt_P", "pdt_G"
    calls = []
    monkeypatch.setattr(plans, "_dodo_request", lambda m, u, b, k: calls.append(b) or {"checkout_url": "https://checkout.dodo.example/s1", "session_id": "cks_1"})
    admin.post("/api/admin/grant", json={"email": "asha@example.com", "plan": "pro"})
    with cloud.db.tx() as x:
        x.execute("UPDATE subscriptions SET currency = 'USD' WHERE user_id = ?", (c.uid,))
    _ready(c)
    _applied(c)
    _accept(admin)
    v = c.post("/api/guarantee/interview/buy", json=T).json()
    assert v["payUrl"] == "https://checkout.dodo.example/s1" and calls[0]["product_cart"][0]["product_id"] == "pdt_G"
    gid = v["interview"]["current"]["id"]
    assert v["interview"]["current"]["price"] == 5_900 and calls[0]["metadata"]["guarantee_id"] == gid
