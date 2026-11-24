"""Business accounts: a consultancy's branded student portal with seats, and an agency's roles feed."""

import json

import pytest

pytest.importorskip("fastapi")

from propelo.cloud import partners  # noqa: E402
from propelo.cloud.db import now_iso  # noqa: E402


def _consultancy(cloud, admin, owner_email="owner@consult.example", seats=2):
    owner = cloud.user(owner_email, name="Counsellor")
    r = admin.post("/api/staff/partners", json={"kind": "consultancy", "name": "Bright Abroad", "adminEmail": owner_email, "seats": seats,
                                                "status": "active", "billing": {"amount": "24999", "currency": "INR"}})
    assert r.status_code == 201, r.text
    return owner, r.json()["partner"]


def test_only_staff_create_accounts(cloud):
    c = cloud.user()
    assert c.post("/api/staff/partners", json={"kind": "agency", "name": "X"}).status_code == 404
    admin = cloud.user("admin@example.com")
    r = admin.post("/api/staff/partners", json={"kind": "consultancy", "name": "Y", "adminEmail": "nobody@example.com"})
    assert r.status_code == 400 and "sign up first" in r.json()["error"]


def test_student_joins_gets_a_seat_and_the_plan(cloud):
    admin = cloud.user("admin@example.com")
    owner, p = _consultancy(cloud, admin)
    code = p["inviteCode"]
    info = cloud.client().get(f"/api/join/{code}").json()
    assert info["name"] == "Bright Abroad" and info["open"] and "will not see your resume" in info["consent"]
    assert cloud.client().get("/join/" + code).status_code == 200

    s = cloud.user("student@example.com", name="Ravi")
    assert s.get("/api/me").json()["plan"] == "free"
    assert s.post("/api/partner/join", json={"code": code}).status_code == 400  # consent is required
    r = s.post("/api/partner/join", json={"code": code, "consent": True})
    assert r.status_code == 200, r.text
    me = s.get("/api/me").json()
    assert me["plan"] == "pro" and me["partner"]["name"] == "Bright Abroad"

    # Progress: the consultancy sees counts and interview roles, never the resume.
    assert s.put("/api/d/jobs/j1", json={"company": "Monzo", "title": "Engineer", "foundVia": "careers-feed", "appliedAt": now_iso(),
                                         "stage": "interview", "visa": {"status": "offers"}}).status_code == 200
    s.put("/api/d/profile/resume", json={"summary": "secret resume text"})
    v = owner.get("/api/partner").json()["partners"][0]
    assert v["seatsUsed"] == 1 and v["totals"]["applied"] == 1 and v["totals"]["interviews"] == 1
    st = v["students"][0]
    assert st["email"] == "student@example.com" and st["sponsorRoles"] == 1
    assert "secret resume text" not in json.dumps(v)

    # Leaving drops the seat plan.
    assert s.post("/api/partner/leave").status_code == 200
    assert s.get("/api/me").json()["plan"] == "free"


def test_seats_run_out_and_paused_accounts_stop_granting(cloud):
    admin = cloud.user("admin@example.com")
    owner, p = _consultancy(cloud, admin, seats=1)
    a = cloud.user("a@example.com")
    b = cloud.user("b@example.com")
    assert a.post("/api/partner/join", json={"code": p["inviteCode"], "consent": True}).status_code == 200
    r = b.post("/api/partner/join", json={"code": p["inviteCode"], "consent": True})
    assert r.status_code == 400 and "seats" in r.json()["error"]
    assert admin.patch(f"/api/staff/partners/{p['id']}", json={"status": "paused"}).status_code == 200
    assert a.get("/api/me").json()["plan"] == "free"
    assert cloud.client().get(f"/api/join/{p['inviteCode']}").json()["open"] is False


def test_partner_admin_rights_are_scoped(cloud):
    admin = cloud.user("admin@example.com")
    owner, p = _consultancy(cloud, admin)
    stranger = cloud.user("stranger@example.com")
    assert stranger.patch(f"/api/partner/{p['id']}", json={"brand": {"color": "#000000"}}).status_code == 404
    assert owner.patch(f"/api/partner/{p['id']}", json={"brand": {"color": "#1F6F5C", "tagline": "UK study experts"}}).status_code == 200
    assert owner.patch(f"/api/partner/{p['id']}", json={"brand": {"color": "red"}}).status_code == 400
    png = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
    assert owner.post(f"/api/partner/{p['id']}/logo", json={"dataUrl": png}).status_code == 200
    r = cloud.client().get(f"/api/partner-logo/{p['slug']}")
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    assert owner.post(f"/api/partner/{p['id']}/logo", json={"dataUrl": "data:image/svg+xml;base64,PHN2Zz4="}).status_code == 400
    old = p["inviteCode"]
    owner.post(f"/api/partner/{p['id']}/rotate-invite")
    assert cloud.client().get(f"/api/join/{old}").status_code == 404


def _add_job(cloud, jid, company, title, location, days_open, visa=None, mode="onsite"):
    rec = {"id": jid, "company": company, "title": title, "url": f"https://jobs.example/{jid}", "location": location, "workMode": mode,
           "postedAt": "2026-10-01T00:00:00Z", "salary": "", "facts": {"loc": "abroad", "daysOpen": days_open, "firstSeen": "2026-10-01",
                                                                      **({"visa": visa} if visa else {})}}
    with cloud.db.tx() as c:
        c.execute("INSERT INTO jobs(id, company, title, url, source, posted_at, record, text, active, first_seen_at, last_seen_at) "
                  "VALUES (?, ?, ?, ?, 'greenhouse', ?, ?, '', 1, ?, ?)",
                  (jid, company, title, rec["url"], rec["postedAt"], json.dumps(rec), now_iso(), now_iso()))


def test_agency_feed_filters_and_key(cloud):
    admin = cloud.user("admin@example.com")
    owner = cloud.user("ops@agency.example")
    r = admin.post("/api/staff/partners", json={"kind": "agency", "name": "Talent Bridge", "adminEmail": "ops@agency.example", "status": "pilot",
                                                "filters": {"keywords": "engineer", "countries": ["GB"], "minDaysOpen": 21, "remote": "exclude"}})
    assert r.status_code == 201
    p, key = r.json()["partner"], r.json()["feedKey"]
    assert key.startswith("cos_f_")
    _add_job(cloud, "a", "Monzo", "Backend Engineer", "London, UK", 30, {"status": "offers", "quote": "Visa sponsorship is available.", "uk": True,
                                                                          "ukRegister": {"listed": True, "name": "Monzo Bank Ltd"}})
    _add_job(cloud, "b", "Wise", "Frontend Engineer", "London, UK", 5)                         # too new
    _add_job(cloud, "c", "Stripe", "Data Engineer", "New York, US", 40)                        # wrong country
    _add_job(cloud, "d", "Deliveroo", "Product Manager", "London, UK", 40)                     # wrong title
    _add_job(cloud, "e", "Revolut", "=cmd Engineer", "London, United Kingdom", 22, {"status": "no", "quote": "We cannot sponsor."})
    _add_job(cloud, "f", "Remote Co", "Platform Engineer", "Remote, UK", 50, mode="remote")    # remote left out

    url = f"/api/partner-feed/{p['slug']}.json"
    assert cloud.client().get(url).status_code == 401
    assert cloud.client().get(url, params={"key": "cos_f_wrong"}).status_code == 401
    d = cloud.client().get(url, headers={"Authorization": "Bearer " + key}).json()
    assert [x["company"] for x in d["roles"]] == ["Monzo", "Revolut"]  # longest open first
    assert d["roles"][0]["sponsorship"] == "says it sponsors" and d["roles"][0]["uk_sponsor_register"] == "listed"

    csv = cloud.client().get(f"/api/partner-feed/{p['slug']}.csv", params={"key": key})
    assert csv.status_code == 200 and csv.text.splitlines()[0].startswith("company,title,location")
    assert ",'=cmd Engineer," in csv.text  # no spreadsheet formulas from posting titles

    owner.patch(f"/api/partner/{p['id']}", json={"filters": {"keywords": "engineer", "countries": ["GB"], "minDaysOpen": 21, "sponsor": "offers"}})
    assert [x["company"] for x in owner.get(f"/api/partner/{p['id']}/preview").json()["rows"]] == ["Monzo"]

    new = owner.post(f"/api/partner/{p['id']}/rotate-key").json()["key"]
    assert cloud.client().get(url, params={"key": key}).status_code == 401
    assert cloud.client().get(url, params={"key": new}).status_code == 200
    admin.patch(f"/api/staff/partners/{p['id']}", json={"status": "paused"})
    assert cloud.client().get(url, params={"key": new}).status_code == 403


def test_clean_filters_rejects_nonsense():
    with pytest.raises(partners.PartnerError):
        partners.clean_filters({"remote": "sometimes"})
    with pytest.raises(partners.PartnerError):
        partners.clean_filters({"sponsor": "maybe"})
    f = partners.clean_filters({"keywords": "Engineer, ,Data", "countries": ["gb", "XX"], "minDaysOpen": 900})
    assert f["keywords"] == ["engineer", "data"] and f["countries"] == ["GB"] and f["minDaysOpen"] == 365


# ---------------------------------------------------------------- buying online and free pilots

import hashlib  # noqa: E402
import hmac  # noqa: E402
from datetime import datetime, timedelta, timezone  # noqa: E402


@pytest.fixture
def pay(cloud, monkeypatch):
    cloud.cfg.razorpay_key_id, cloud.cfg.razorpay_key_secret, cloud.cfg.razorpay_webhook_secret = "rzp_test_k", "s", "whs"
    links = []

    def fake_post(url, body, key, secret):
        links.append(body)
        return {"id": f"plink_B{len(links)}", "short_url": f"https://rzp.io/i/b{len(links)}"}
    from propelo.cloud import plans
    monkeypatch.setattr(plans, "_post", fake_post)
    cloud.links = links
    return cloud


def _paid(cloud, link_id, amount, n=1):
    ev = json.dumps({"event": "payment_link.paid", "payload": {"payment_link": {"entity": {"id": link_id, "status": "paid", "amount_paid": amount}}}}).encode()
    sig = hmac.new(b"whs", ev, hashlib.sha256).hexdigest()
    return cloud.client().post("/api/billing/webhook", content=ev, headers={"X-Razorpay-Signature": sig, "X-Razorpay-Event-Id": f"evt_{link_id}_{n}",
                                                                            "Content-Type": "application/json"}).json()


def test_business_page_and_catalog(cloud):
    assert cloud.client().get("/business").status_code == 200
    cat = cloud.client().get("/api/business/plans?currency=INR").json()
    ids = {p["id"]: p for p in cat["plans"]}
    assert ids["consultancy-growth"]["price"] == 5_499_900 and ids["consultancy-growth"]["seats"] == 50
    assert ids["agency-feed"]["kind"] == "agency"
    assert cloud.client().get("/terms").status_code == 200


def test_buy_a_consultancy_plan_online(pay):
    cloud = pay
    owner = cloud.user("owner@consult.example")
    body = {"plan": "consultancy-growth", "name": "Bright Abroad", "currency": "INR", "details": {"website": "brightabroad.example", "city": "Hyderabad"}}
    assert owner.post("/api/business/start", json=body).status_code == 400  # terms first
    r = owner.post("/api/business/start", json=dict(body, agree=True))
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["url"] == "https://rzp.io/i/b1" and cloud.links[0]["amount"] == 5_499_900
    assert d["partner"]["status"] == "pending" and not d["partner"]["live"]
    # Not live before payment: no seats yet.
    code = owner.get("/api/partner").json()["partners"][0]["inviteUrl"].rsplit("/", 1)[1]
    assert cloud.client().get(f"/api/join/{code}").json()["open"] is False
    # Asking again reuses the open link.
    assert owner.post("/api/business/start", json=dict(body, agree=True)).json()["url"] == "https://rzp.io/i/b1"

    assert _paid(cloud, "plink_B1", 1_000)["result"] == "short"
    assert _paid(cloud, "plink_B1", 5_499_900, 2)["result"] == "paid"
    assert _paid(cloud, "plink_B1", 5_499_900, 3)["result"] == "duplicate"
    v = owner.get("/api/partner").json()["partners"][0]
    assert v["status"] == "active" and v["live"] and v["seats"] == 50 and v["payments"][0]["amount"] == 5_499_900
    end1 = datetime.fromisoformat(v["endsAt"].replace("Z", "+00:00"))
    assert timedelta(days=29) < end1 - datetime.now(timezone.utc) <= timedelta(days=30)
    assert cloud.client().get(f"/api/join/{code}").json()["open"] is True
    assert any("Payment received" in m["subject"] for m in cloud.outbox)

    # Paying again extends from the current end date.
    pay_url = owner.post(f"/api/partner/{v['id']}/pay", json={}).json()["url"]
    assert pay_url == "https://rzp.io/i/b2"
    assert _paid(cloud, "plink_B2", 5_499_900, 4)["result"] == "paid"
    end2 = datetime.fromisoformat(owner.get("/api/partner").json()["partners"][0]["endsAt"].replace("Z", "+00:00"))
    assert timedelta(days=29, hours=23) < end2 - end1 <= timedelta(days=30, minutes=1)


def test_free_pilot_request_and_approval(pay):
    cloud = pay
    admin = cloud.user("admin@example.com")
    owner = cloud.user("agency@talent.example")
    r = owner.post("/api/business/start", json={"plan": "agency-feed", "name": "Talent Bridge", "pilot": True, "agree": True,
                                               "details": {"note": "IT staffing, Bengaluru"}})
    assert r.status_code == 200 and "url" not in r.json()
    assert r.json()["partner"]["status"] == "requested"
    assert any("pilot request" in m["subject"].lower() for m in cloud.outbox)
    row = [p for p in admin.get("/api/staff/partners").json()["partners"] if p["name"] == "Talent Bridge"][0]
    assert row["request"]["note"] == "IT staffing, Bengaluru"
    assert owner.post(f"/api/staff/partners/{row['id']}/approve-pilot").status_code == 404  # staff only
    assert admin.post(f"/api/staff/partners/{row['id']}/approve-pilot").status_code == 200
    v = owner.get("/api/partner").json()["partners"][0]
    assert v["status"] == "pilot" and v["live"]
    key = owner.post(f"/api/partner/{v['id']}/rotate-key").json()["key"]
    assert cloud.client().get(f"/api/partner-feed/{v['slug']}.json", params={"key": key}).status_code == 200
    # A second pilot for the same kind is refused once one is running.
    r = owner.post("/api/business/start", json={"plan": "agency-feed", "name": "Again", "pilot": True, "agree": True})
    assert r.status_code == 400


def test_reminders_once_per_end_date(cloud):
    from propelo.cloud import partners
    admin = cloud.user("admin@example.com")
    cloud.user("owner@x.example")
    r = admin.post("/api/staff/partners", json={"kind": "consultancy", "name": "Soon Co", "adminEmail": "owner@x.example", "seats": 5, "status": "active",
                                                "endsAt": (datetime.now(timezone.utc) + timedelta(days=3)).strftime("%Y-%m-%dT%H:%M:%SZ")})
    pid = r.json()["partner"]["id"]
    with cloud.db.tx() as c:
        assert partners.reminders(c) == [(pid, "soon")]
        assert partners.reminders(c) == []
        later = datetime.now(timezone.utc) + timedelta(days=4)
        assert partners.reminders(c, now=later) == [(pid, "ended")]
        assert partners.reminders(c, now=later) == []


def test_dollar_checkout_needs_a_product(pay, monkeypatch):
    cloud = pay
    owner = cloud.user("us@agency.example")
    r = owner.post("/api/business/start", json={"plan": "agency-feed", "name": "US Agency", "agree": True, "currency": "USD"})
    assert r.status_code == 400 and "isn't set up" in r.json()["error"]


def test_signup_keeps_where_to_go_after_confirming(cloud):
    c = cloud.client()
    assert c.post("/api/auth/signup", json={"email": "new@student.example", "password": "correct horse battery", "next": "/join/abc123"}).status_code == 202
    assert "/verify#token=" in cloud.outbox[-1]["text"] and "&next=%2Fjoin%2Fabc123" in cloud.outbox[-1]["text"]
    assert c.post("/api/auth/signup", json={"email": "evil@student.example", "password": "correct horse battery", "next": "//evil.example"}).status_code == 202
    assert "next=" not in cloud.outbox[-1]["text"]
