"""Business accounts: a consultancy's branded student portal with seats, and an agency's roles feed."""

import json

import pytest

pytest.importorskip("fastapi")

from careeros.cloud import partners  # noqa: E402
from careeros.cloud.db import now_iso  # noqa: E402


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
