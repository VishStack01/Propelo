"""Propelo Concierge: a human-run search on Pro and Ultra, with a fee only after joining a company
the candidate approved through Concierge."""

import hashlib
import hmac
import json
from datetime import date, timedelta

import pytest

pytest.importorskip("fastapi")

from propelo.cloud import concierge  # noqa: E402
from propelo.cloud.config import Config  # noqa: E402

INTAKE = {"roles": "Backend engineer", "locations": "Bengaluru, remote", "currentCtc": "18,00,000", "expectedCtc": 2500000, "noticeDays": 30}


def test_fee_is_8_percent_up_to_20_lakh_and_6_above():
    cfg = Config(concierge_enabled=True)
    assert concierge.fee_for(cfg, 1_500_000)["fee"] == 120_000           # 8% of 15 L
    assert concierge.fee_for(cfg, 2_000_000)["fee"] == 160_000           # 8% of 20 L
    f = concierge.fee_for(cfg, 3_000_000)
    assert f["fee"] == 160_000 + 60_000 and f["effectiveRate"] == 7.33  # 8% of 20 L + 6% of 10 L
    # no cliff: a little more pay never means a much bigger fee
    assert concierge.fee_for(cfg, 2_000_001)["fee"] - concierge.fee_for(cfg, 2_000_000)["fee"] <= 1
    t = concierge.fee_for(Config(concierge_enabled=True, concierge_tax_rate=18), 1_000_000)
    assert (t["fee"], t["tax"], t["total"]) == (80_000, 14_400, 94_400)


def test_instalments_start_30_days_after_joining_and_add_up():
    plan = concierge.instalment_plan(Config(), 9_440_001, date(2027, 1, 10))
    assert [p["due_on"] for p in plan] == ["2027-02-09", "2027-03-11", "2027-04-10"]
    assert sum(p["amount"] for p in plan) == 9_440_001


@pytest.fixture
def setup(cloud):
    cloud.cfg.concierge_enabled = True
    c = cloud.user()
    admin = cloud.user("admin@example.com")
    partner = cloud.user("partner@example.com")
    admin.post("/api/admin/staff", json={"email": "partner@example.com"})
    return cloud, c, admin, partner


def _ask(c, country="IN", **kw):
    return c.post("/api/concierge/request", json={"agree": True, "termsVersion": concierge.TERMS_VERSION, "country": country, "intake": dict(INTAKE, **kw)})


def test_concierge_is_part_of_paid_plans_and_needs_the_terms(setup):
    cloud, c, admin, _ = setup
    r = _ask(c)
    assert r.status_code == 400 and "Pro and Ultra" in r.json()["error"]
    admin.post("/api/admin/grant", json={"email": "asha@example.com", "plan": "pro"})
    assert c.post("/api/concierge/request", json={"agree": False, "termsVersion": concierge.TERMS_VERSION, "country": "IN", "intake": INTAKE}).status_code == 400
    assert _ask(c, country="US").json()["error"].startswith("Concierge is available only for jobs in IN")
    v = _ask(c).json()
    assert v["case"]["status"] == "requested" and v["case"]["intake"]["currentCtc"] == 1_800_000
    assert _ask(c).status_code == 400  # one case at a time


def test_the_whole_journey(setup):
    from propelo.cloud import mailer
    cloud, c, admin, partner = setup
    admin.post("/api/admin/grant", json={"email": "asha@example.com", "plan": "ultra"})
    _ask(c)
    # the team sees it, a partner takes it, and only they (or an admin) can open it afterwards
    cases = partner.get("/api/staff/cases").json()["cases"]
    assert len(cases) == 1 and cases[0]["plan"] == "ultra"
    cid = cases[0]["id"]
    assert partner.get(f"/api/staff/cases/{cid}").json()["intake"]["roles"] == "Backend engineer"
    assert c.get("/api/staff/cases").status_code == 404  # candidates can't see the workspace
    assert partner.post(f"/api/staff/cases/{cid}/take").json()["status"] == "active"
    other = cloud.user("other@example.com")
    admin.post("/api/admin/staff", json={"email": "other@example.com"})
    assert other.get(f"/api/staff/cases/{cid}").status_code == 404

    # proposals wait for the candidate; nothing can be sent before they approve
    partner.post(f"/api/staff/cases/{cid}/propose", json={"company": "Northwind Labs", "title": "Senior Backend Engineer", "url": "https://northwind.example/jobs/1", "why": "Go and payments"})
    partner.post(f"/api/staff/cases/{cid}/propose", json={"company": "Acme", "title": "Platform Engineer"})
    subs = c.get("/api/concierge").json()["case"]["submissions"]
    acme = next(s for s in subs if s["company"] == "Acme")
    nw = next(s for s in subs if s["company"] == "Northwind Labs")
    r = partner.post(f"/api/staff/cases/{cid}/move", json={"submissionId": nw["id"], "status": "submitted"})
    assert r.status_code == 400 and "hasn't approved" in r.json()["error"]
    c.post(f"/api/concierge/roles/{nw['id']}/approve")
    c.post(f"/api/concierge/roles/{acme['id']}/decline")
    assert c.post(f"/api/concierge/roles/{nw['id']}/approve").status_code == 400  # answered once
    assert partner.post(f"/api/staff/cases/{cid}/move", json={"submissionId": nw["id"], "status": "submitted"}).status_code == 200

    # messages both ways; private notes stay private
    partner.post(f"/api/staff/cases/{cid}/note", json={"body": "Applied today. Interview likely next week."})
    partner.post(f"/api/staff/cases/{cid}/note", json={"body": "Private: strong on Go.", "shared": False})
    c.post("/api/concierge/message", json={"body": "Thanks!"})
    msgs = c.get("/api/concierge").json()["case"]["messages"]
    assert [m["body"] for m in msgs] == ["Applied today. Interview likely next week.", "Thanks!"]

    # an offer from a company they declined, or never approved, carries no fee
    r = c.post("/api/concierge/offer", json={"company": "Acme", "fixedCtc": 3_000_000, "joiningDate": "2027-01-10"}).json()
    assert r["reported"]["feeable"] is False
    # an offer from the approved company does
    r = c.post("/api/concierge/offer", json={"company": "Northwind Labs Pvt Ltd", "fixedCtc": "30,00,000", "joiningDate": "2027-01-10"}).json()
    assert r["reported"]["feeable"] is True and r["reported"]["fee"]["fee"] == 220_000
    pid = r["reported"]["id"]
    v = partner.post(f"/api/staff/cases/{cid}/verify", json={"placementId": pid}).json()
    pl = next(p for p in v["placements"] if p["id"] == pid)
    assert pl["status"] == "verified" and [i["dueOn"] for i in pl["instalments"]] == ["2027-02-09", "2027-03-11", "2027-04-10"]
    assert sum(i["amount"] for i in pl["instalments"]) == 220_000 * 100
    assert c.get("/api/concierge").json()["case"]["status"] == "placed"
    with cloud.db.tx() as t:
        kinds = {r["kind"] for r in t.all("SELECT kind FROM audit_events")}
    assert {"concierge-requested", "concierge-role-approved", "concierge-staff-verify", "concierge-case-viewed"} <= kinds


def test_instalment_payment_link_and_webhook(setup):
    cloud, c, admin, partner = setup
    admin.post("/api/admin/grant", json={"email": "asha@example.com", "plan": "pro"})
    _ask(c)
    cid = partner.get("/api/staff/cases").json()["cases"][0]["id"]
    partner.post(f"/api/staff/cases/{cid}/take")
    partner.post(f"/api/staff/cases/{cid}/propose", json={"company": "Northwind", "title": "Engineer"})
    sid = c.get("/api/concierge").json()["case"]["submissions"][0]["id"]
    c.post(f"/api/concierge/roles/{sid}/approve")
    joined = (date.today() - timedelta(days=40)).isoformat()
    pid = c.post("/api/concierge/offer", json={"company": "Northwind", "fixedCtc": 1_000_000, "joiningDate": joined}).json()["reported"]["id"]
    partner.post(f"/api/staff/cases/{cid}/verify", json={"placementId": pid})
    inst = c.get("/api/concierge").json()["case"]["placements"][0]["instalments"]
    assert inst[0]["payable"] is True and inst[1]["payable"] is False

    cloud.cfg.razorpay_key_id, cloud.cfg.razorpay_key_secret, cloud.cfg.razorpay_webhook_secret = "rzp_test_k", "s", "whs"
    sent = []
    from propelo.cloud import plans
    orig = plans._post
    plans._post = lambda url, body, kid, ks: (sent.append((url, body)), {"id": "plink_ABC123", "short_url": "https://rzp.io/i/abc"})[1]
    try:
        assert c.post(f"/api/concierge/instalments/{inst[0]['id']}/pay").json()["url"] == "https://rzp.io/i/abc"
    finally:
        plans._post = orig
    url, body = sent[0]
    assert url.endswith("/payment_links") and body["amount"] == inst[0]["amount"] and body["reference_id"] == inst[0]["id"][:40]
    ev = json.dumps({"event": "payment_link.paid", "payload": {"payment_link": {"entity": {"id": "plink_ABC123", "status": "paid"}}}}).encode()
    sig = hmac.new(b"whs", ev, hashlib.sha256).hexdigest()
    hook = lambda: cloud.client().post("/api/billing/webhook", content=ev, headers={"X-Razorpay-Signature": sig, "X-Razorpay-Event-Id": "evt_pl_1", "Content-Type": "application/json"})  # noqa: E731
    assert hook().json()["result"] == "paid"
    assert hook().json()["result"] == "duplicate"
    p = c.get("/api/concierge").json()["case"]["placements"][0]
    assert p["instalments"][0]["status"] == "paid" and p["status"] == "invoicing"


def test_employer_ending_the_job_cancels_what_is_unpaid(setup):
    cloud, c, admin, partner = setup
    admin.post("/api/admin/grant", json={"email": "asha@example.com", "plan": "pro"})
    _ask(c)
    cid = partner.get("/api/staff/cases").json()["cases"][0]["id"]
    partner.post(f"/api/staff/cases/{cid}/take")
    partner.post(f"/api/staff/cases/{cid}/propose", json={"company": "Northwind", "title": "Engineer"})
    sid = c.get("/api/concierge").json()["case"]["submissions"][0]["id"]
    c.post(f"/api/concierge/roles/{sid}/approve")
    pid = c.post("/api/concierge/offer", json={"company": "Northwind", "fixedCtc": 1_000_000, "joiningDate": date.today().isoformat()}).json()["reported"]["id"]
    partner.post(f"/api/staff/cases/{cid}/verify", json={"placementId": pid})
    v = partner.post(f"/api/staff/cases/{cid}/end-early", json={"placementId": pid, "byEmployer": True}).json()
    p = v["placements"][0]
    assert p["status"] == "waived" and {i["status"] for i in p["instalments"]} == {"waived"}


def test_cases_pause_when_the_plan_ends(setup):
    cloud, c, admin, _ = setup
    admin.post("/api/admin/grant", json={"email": "asha@example.com", "plan": "pro"})
    _ask(c)
    admin.post("/api/admin/grant", json={"email": "asha@example.com", "plan": "free"})
    with cloud.db.tx() as t:
        assert concierge.pause_lapsed(t) == 1
    v = c.get("/api/concierge").json()
    assert v["case"]["status"] == "paused" and "plan ended" in v["case"]["closedReason"]
    assert c.post("/api/concierge/pause", json={"pause": False}).status_code == 402


def test_concierge_off_by_default_and_never_in_the_uk(cloud):
    assert Config().concierge_enabled is False
    c = cloud.user()
    assert c.get("/api/concierge").json()["enabled"] is False
    cloud.cfg.concierge_enabled, cloud.cfg.concierge_countries = True, ("IN", "GB")
    assert c.get("/api/concierge").json()["countries"] == ["IN"]
    admin = cloud.user("admin@example.com")
    admin.post("/api/admin/grant", json={"email": "asha@example.com", "plan": "pro"})
    assert "only for jobs in IN" in _ask(c, country="GB").json()["error"]
