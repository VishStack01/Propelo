"""Interview Guarantee and Job Guarantee: money back on clear, checkable conditions, never a promised job."""

from datetime import datetime, timedelta, timezone

import pytest

pytest.importorskip("fastapi")

from careeros.cloud import guarantee  # noqa: E402
from careeros.cloud.config import Config  # noqa: E402

T = {"agree": True, "termsVersion": guarantee.TERMS_VERSION}


def iso(d):
    return d.strftime("%Y-%m-%dT%H:%M:%SZ")


@pytest.fixture
def g(cloud):
    cloud.cfg.guarantee_enabled = True
    c = cloud.user()
    admin = cloud.user("admin@example.com")
    return cloud, c, admin


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


def test_refund_is_the_plan_fees_for_the_window():
    cfg = Config()
    assert guarantee.refund_estimate(cfg, "pro", "INR", 60) == 2 * 499 * 100
    assert guarantee.refund_estimate(cfg, "ultra", "USD", 60) == 2 * 4850
    assert guarantee.refund_estimate(cfg, "pro", "INR", 180) == 6 * 499 * 100


def test_eligibility_is_checked_and_shown_before_enrolling(g):
    cloud, c, admin = g
    v = c.get("/api/guarantee").json()
    checks = {x["id"]: x["ok"] for x in v["interview"]["eligibility"]["checks"]}
    assert checks == {"plan": False, "once": True, "profile": False, "matches": False}
    r = c.post("/api/guarantee/interview/enroll", json=T)
    assert r.status_code == 400 and "Not eligible yet" in r.json()["error"]
    admin.post("/api/admin/grant", json={"email": "asha@example.com", "plan": "pro"})
    _ready(c, matches=10)
    assert "40 roles" in c.post("/api/guarantee/interview/enroll", json=T).json()["error"]  # only where Propelo finds roles for you
    _ready(c)
    assert c.post("/api/guarantee/interview/enroll", json={"agree": True, "termsVersion": "old"}).status_code == 400
    v = c.post("/api/guarantee/interview/enroll", json=T).json()
    cur = v["interview"]["current"]
    assert cur["status"] == "active" and cur["plan"] == "pro" and cur["estimate"] == 99_800
    assert any("Interview Guarantee" in m["subject"] for m in cloud.outbox)
    assert c.post("/api/guarantee/interview/enroll", json=T).status_code == 400  # once at a time


def test_an_interview_completes_the_guarantee(g):
    cloud, c, admin = g
    admin.post("/api/admin/grant", json={"email": "asha@example.com", "plan": "pro"})
    _ready(c)
    c.post("/api/guarantee/interview/enroll", json=T)
    now = datetime.now(timezone.utc) + timedelta(seconds=5)
    c.put("/api/d/jobs/win", json={"company": "Northwind", "title": "Backend Engineer", "stage": "screen", "appliedAt": iso(now), "screenAt": iso(now)})
    cur = c.get("/api/guarantee").json()["interview"]["current"]
    assert cur["status"] == "met" and cur["progress"]["interviews"] == 1


def test_claim_after_the_window_with_the_activity_done(g):
    cloud, c, admin = g
    admin.post("/api/admin/grant", json={"email": "asha@example.com", "plan": "pro", "until": "2099-01-01"})
    _ready(c)
    c.post("/api/guarantee/interview/enroll", json=T)
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
    assert admin.post(f"/api/staff/guarantees/{gid}/approve", json={"amount": 999_999}).status_code == 400  # never more than the fees
    assert admin.post(f"/api/staff/guarantees/{gid}/refunded").status_code == 400  # approve first
    admin.post(f"/api/staff/guarantees/{gid}/approve", json={})
    assert c.get("/api/guarantee").json()["interview"]["current"]["refund"] == 99_800
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
    c.post("/api/guarantee/interview/enroll", json=T)
    start, _ = _age(cloud, c.uid)
    _apply(c, 30, start, weeks=2)  # all in two weeks: the guarantee asks for four
    cur = c.get("/api/guarantee").json()["interview"]["current"]
    assert cur["status"] == "ended" and "needs 30 in 4" in cur["reason"]


def test_plan_ending_early_voids_it(g):
    cloud, c, admin = g
    admin.post("/api/admin/grant", json={"email": "asha@example.com", "plan": "pro"})
    _ready(c)
    c.post("/api/guarantee/interview/enroll", json=T)
    with cloud.db.tx() as x:
        x.execute("DELETE FROM subscriptions WHERE user_id = ?", (c.uid,))
    with cloud.db.tx() as x:
        moved = guarantee.refresh(x, cloud.cfg)
    assert moved == [("asha@example.com", "interview", "void")]


def test_job_guarantee_needs_concierge(g):
    cloud, c, admin = g
    assert c.post("/api/guarantee/job/enroll", json=T).json()["error"].startswith("The Job Guarantee comes with Concierge")
    cloud.cfg.concierge_enabled = True
    admin.post("/api/admin/grant", json={"email": "asha@example.com", "plan": "ultra"})
    assert "open Concierge case" in c.post("/api/guarantee/job/enroll", json=T).json()["error"]
    from careeros.cloud import concierge
    c.post("/api/concierge/request", json={"agree": True, "termsVersion": concierge.TERMS_VERSION, "country": "IN",
                                           "intake": {"roles": "Backend", "locations": "Bengaluru", "currentCtc": 1, "expectedCtc": 2}})
    cur = c.post("/api/guarantee/job/enroll", json=T).json()["job"]["current"]
    assert cur["status"] == "active" and cur["estimate"] == 6 * 1199 * 100
    _age(cloud, c.uid, "job", days=181)
    assert c.get("/api/guarantee").json()["job"]["current"]["status"] == "claimable"


def test_guarantees_off_by_default(cloud):
    c = cloud.user()
    assert cloud.cfg.guarantee_enabled is False
    assert c.post("/api/guarantee/interview/enroll", json=T).json()["error"] == "Guarantees aren't available on this server."
