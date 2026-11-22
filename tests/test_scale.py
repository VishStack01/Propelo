"""Scale: countries a location only implies, visa signals beyond the UK, reading a rotating share of boards,
and a feed intake that neither holds the feed in memory nor rewrites roles that didn't change."""

import gzip
import json
from datetime import datetime, timedelta, timezone

import pytest

from careeros import countries, scan, sponsors
from tests.conftest import feed_record, write_feed


@pytest.mark.parametrize("loc,want", [
    ("Austin, TX", {"US"}), ("Sunnyvale", {"US"}), ("Tulsa, Oklahoma", {"US"}), ("Cambridge, MA", {"US"}), ("Dublin, CA", {"US"}),
    ("Indianapolis, IN", {"US"}), ("Bangalore, IN", {"IN"}), ("Bengaluru, Karnataka, IND", {"IN"}), ("IN - Chennai", {"IN"}),
    ("Toronto, ON", {"CA"}), ("Vancouver, CA", {"CA"}), ("Melbourne, VIC", {"AU"}), ("Perth, WA", {"AU"}), ("Seattle, WA", {"US"}),
    ("Berlin, DE", {"DE"}), ("Wilmington, DE", {"US"}), ("London; Austin, TX", {"GB", "US"}), ("Eindhoven", {"NL"}),
    ("Doha, Doha, Qatar", {"QA"}), ("Remote", set()), ("2 Locations", set()), ("Tbilisi, Georgia", set()),
])
def test_resolve_reads_the_country_a_location_only_implies(loc, want):
    assert countries.resolve(loc) == want


def test_study_countries_are_real_codes():
    assert set(countries.STUDY) <= set(countries.NAMES) and "IN" not in countries.STUDY


def test_citizens_only_and_student_work_lines():
    assert sponsors.sponsorship("Must be a US citizen with an active Secret clearance.") ["why"] == "citizens"
    assert sponsors.sponsorship("U.S. citizenship is required.")["status"] == "no"
    assert sponsors.sponsorship("We value security and the clearance of obstacles.") == {}
    assert sponsors.student_work("OPT/CPT candidates are welcome. We participate in E-Verify.") == {
        "opt": "yes", "optQuote": "OPT/CPT candidates are welcome.", "eVerify": True}
    assert sponsors.student_work("We do not accept OPT or CPT.")["opt"] == "no"
    assert sponsors.student_work("Please opt in to our newsletter and opt for the best plan.") == {}
    v = sponsors.visa_facts("Acme", "Austin, TX", "OPT candidates are welcome.")
    assert v["opt"] == "yes" and "accepts OPT/CPT" in sponsors.label(v)
    assert "opt" not in sponsors.visa_facts("Acme", "London", "OPT candidates are welcome.")  # a US rule, checked for US roles only


def test_dutch_register_from_a_table_or_plain_lines(tmp_path):
    table = "<table><tr><th>Organisation</th><th>KVK number</th></tr>" + "".join(
        f"<tr><td>Company {i} B.V.</td><td>{10000000 + i}</td></tr>" for i in range(120)) + \
        "<tr><td>Booking.com B.V.</td><td>31047344</td></tr><tr><td>Adyen N.V.</td><td>34259528</td></tr></table>"
    rows = sponsors.parse_nl_register(table)
    assert len(rows) == 122 and rows[-1] == ("Adyen N.V.", "34259528")
    lines = "".join(f"<li>Firm {i} B.V. {20000000 + i}</li>" for i in range(120)) + "<li>ASML Netherlands B.V. 17085815</li>"
    assert sponsors.parse_nl_register(lines)[-1] == ("ASML Netherlands B.V.", "17085815")
    p = tmp_path / "nl.csv"
    p.write_text("name,kvk\n" + "\n".join(f'"{n}",{k}' for n, k in rows + sponsors.parse_nl_register(lines)), encoding="utf-8")
    reg = sponsors.NlRegister.from_csv(p)
    assert reg.match("Booking.com")["match"] == "exact" and reg.match("ASML")["name"] == "ASML Netherlands B.V." and reg.match("Stripe") is None
    v = sponsors.visa_facts("Adyen", "Amsterdam", "Great team.", nl_register=reg)
    assert v["nlRegister"]["listed"] and "recognised sponsor in the Netherlands" in sponsors.label(v)
    assert "nlRegister" not in sponsors.visa_facts("Adyen", "Berlin", "Great team.", nl_register=reg)


def test_pick_boards_reads_everything_until_there_are_too_many():
    now = datetime(2026, 11, 22, 12, tzinfo=timezone.utc)
    ago = lambda h: (now - timedelta(hours=h)).strftime("%Y-%m-%dT%H:%M:%SZ")  # noqa: E731
    boards = {"curated": {"category": "ai-native", "scannedAt": ago(1), "roles": 5},
              "new": {"category": "deep"},
              "deep-due": {"category": "deep", "scannedAt": ago(9), "roles": 3},
              "deep-fresh": {"category": "deep", "scannedAt": ago(1), "roles": 3},
              "deep-empty": {"category": "deep", "scannedAt": ago(20), "roles": 0},
              "deep-very-late": {"category": "deep", "scannedAt": ago(40), "roles": 2}}
    todo, kept = scan.pick_boards(boards, 0, now)
    assert set(todo) == set(boards) and kept == []
    todo, kept = scan.pick_boards(boards, 4, now)
    assert set(todo) == {"curated", "new", "deep-very-late", "deep-due"}  # never-skipped first, then the most overdue
    assert kept == ["deep-empty", "deep-fresh"]
    todo, kept = scan.pick_boards(boards, 5, now)
    assert "deep-fresh" not in todo and "deep-empty" not in todo  # read an hour ago / empty and checked today: not due


def test_feed_keeps_study_countries_ahead_of_the_rest_when_trimmed():
    mk = lambda i, **k: {"id": str(i), "postedAt": f"2026-11-{10 + i:02d}T00:00:00Z", "facts": {}, **k}  # noqa: E731
    recs = [mk(1, countries=["BR"]), mk(2, countries=["US"], facts={"senior": True}), mk(3, countries=["GB"]), mk(4, geo="india"),
            mk(5, workMode="remote"), mk(6, countries=["MX"])]
    kept, cut = scan.cap_feed(recs, 4)
    assert {r["id"] for r in kept} == {"4", "5", "3", "2"} and cut == 2
    assert [r["id"] for r in kept] == ["5", "4", "3", "2"]  # newest first in what is published


def test_intake_skips_unchanged_roles_and_reads_texts_out_of_order(cloud, tmp_path):
    from careeros.cloud.ingest import ingest
    records = [feed_record(i) for i in range(12)]
    write_feed(tmp_path / "feed", records)
    first = ingest(cloud.db, cloud.cfg.feed_url, log=lambda *_: None)
    assert first["records"] == 12 and first["changed"] == 12
    assert ingest(cloud.db, cloud.cfg.feed_url, log=lambda *_: None)["status"] == "unchanged"  # same summary: nothing downloaded
    # A newer feed with one changed role, one new role, and the text file in a different order.
    records[3]["summary"] = "Now hiring in Hyderabad too."
    records.append(feed_record(50))
    write_feed(tmp_path / "feed", records, generated="2099-01-01T00:00:00Z")
    full = tmp_path / "feed" / "full.jsonl.gz"
    with gzip.open(full, "rt") as f:
        lines = [json.loads(x) for x in f]
    with gzip.open(full, "wt") as f:
        for x in reversed(lines):
            f.write(json.dumps(x) + "\n")
    second = ingest(cloud.db, cloud.cfg.feed_url, log=lambda *_: None)
    assert second["records"] == 13 and second["closed"] == 0 and second["changed"] <= 2 + 1
    with cloud.db.tx() as c:
        assert c.scalar("SELECT COUNT(*) AS n FROM jobs WHERE active = 1") == 13
        row = c.one("SELECT text, rev FROM jobs WHERE id = ?", (records[0]["id"],))
        assert row["rev"] and row["text"] == next(x["text"] for x in lines if x["id"] == records[0]["id"])


# ---------------------------------------------------------------- growth: sources, funnel, passes, pages

def test_signup_source_is_kept_and_the_funnel_counts_by_it(cloud, tmp_path):
    from careeros.cloud import repo
    assert repo.clean_source("Reddit UKJobs!!") == "reddit-ukjobs" and repo.clean_source("x" * 80) == "x" * 40 and repo.clean_source(None) == ""
    admin = cloud.user("admin@example.com")
    c = cloud.client()
    r = c.post("/api/auth/signup", json={"name": "Asha", "email": "asha2@example.com", "password": "correct horse 42 staple", "src": "Reddit UKJobs"},
               headers={"X-CareerOS-CSRF": "1"})
    assert r.status_code == 202
    cloud.user("bala@example.com")
    f = admin.get("/api/admin/funnel?days=14").json()
    by = {x["source"]: x for x in f["bySource"]}
    assert by["reddit-ukjobs"]["signups"] == 1 and by["reddit-ukjobs"]["confirmed"] == 0
    assert by["direct"]["signups"] >= 2 and by["direct"]["confirmed"] >= 2 and f["total"]["signups"] == 3 and f["total"]["paying"] == 0
    assert cloud.user("carol@example.com").get("/api/admin/funnel").status_code == 404  # admin routes are hidden from members


def _pass_cloud(cloud, monkeypatch):
    from careeros.cloud import plans
    for k, v in dict(pass_enabled=True, razorpay_key_id="rzp_test", razorpay_key_secret="s", razorpay_webhook_secret="whsec").items():
        object.__setattr__(cloud.cfg, k, v)
    links = []

    def post(url, body, key_id, key_secret):
        links.append(body)
        return {"id": f"plink_P{len(links)}", "short_url": f"https://rzp.io/i/P{len(links)}"}
    monkeypatch.setattr(plans, "_post", post)
    return links


def _rzp_paid(cloud, link_id, amount):
    import hashlib
    import hmac
    ev = json.dumps({"event": "payment_link.paid", "payload": {"payment_link": {"entity": {"id": link_id, "status": "paid", "amount_paid": amount}}}}).encode()
    sig = hmac.new(b"whsec", ev, hashlib.sha256).hexdigest()
    return cloud.client().post("/api/billing/webhook", content=ev, headers={"X-Razorpay-Signature": sig, "X-Razorpay-Event-Id": f"evt_{link_id}_{amount}",
                                                                          "Content-Type": "application/json"}).json()


def test_pass_is_off_by_default_and_sells_pro_once(cloud, monkeypatch):
    a = cloud.user("asha@example.com")
    assert a.get("/api/billing").json()["pass"] is None
    assert a.post("/api/billing/pass", json={"currency": "INR"}).status_code == 503  # off until PASS=on
    links = _pass_cloud(cloud, monkeypatch)
    offer = a.get("/api/billing").json()["pass"]
    assert offer["onSale"] and offer["days"] == 90 and offer["priceInr"] == 1199 and offer["currencies"] == ["INR"] and not offer["running"]
    r = a.post("/api/billing/pass", json={"currency": "INR"})
    assert r.status_code == 200 and r.json()["url"].startswith("https://rzp.io/") and links[0]["amount"] == 119_900
    assert a.get("/api/me").json()["plan"] == "free"  # nothing until the payment webhook
    assert _rzp_paid(cloud, "plink_P1", 100)["result"] == "short" and a.get("/api/me").json()["plan"] == "free"
    assert _rzp_paid(cloud, "plink_P1", 119_900)["result"] == "paid"
    assert a.get("/api/me").json()["plan"] == "pro"
    assert _rzp_paid(cloud, "plink_P1", 119_900)["result"] == "duplicate"
    first = a.get("/api/billing").json()["pass"]["running"]["endsAt"]
    # A second pass adds its days to the end of the first.
    a.post("/api/billing/pass", json={"currency": "INR"})
    assert _rzp_paid(cloud, "plink_P2", 119_900)["result"] == "paid"
    second = a.get("/api/billing").json()["pass"]["running"]["endsAt"]
    assert second > first and (datetime.fromisoformat(second.replace("Z", "+00:00")) - datetime.fromisoformat(first.replace("Z", "+00:00"))).days == 90
    admin = cloud.user("admin@example.com")
    assert admin.get("/api/admin/funnel").json()["total"]["paying"] == 1


def test_sponsor_check_data_and_visa_pages(tmp_path):
    from careeros import growth_pages
    feed, out, site = tmp_path / "feed", tmp_path / "out", tmp_path / "website"
    feed.mkdir(); out.mkdir(); site.mkdir()
    rows = ["Organisation Name,Town/City,County,Type & Rating,Route"] + [f"Firm {i} Ltd,Leeds,,Worker (A rating),Skilled Worker" for i in range(1200)]
    rows += ['"Monzo Bank Ltd",London,,Worker (A rating),Skilled Worker', "Circus Ltd,Bath,,Temporary Worker (A rating),Creative Worker"]
    (feed / "uk-sponsors.csv").write_text("\n".join(rows), encoding="utf-8")
    counts = growth_pages.sponsor_data(feed, out)
    text = (out / "data" / "sponsors-uk.txt").read_text(encoding="utf-8")
    assert counts == {"uk": 1201, "nl": 0} and "Monzo Bank Ltd\tLondon\tA rating" in text and "Circus" not in text
    (site / "check.html").write_text('<html><head><title>x</title><meta name="description" content="d"><meta property="og:title" content="t">'
                                     '<meta property="og:description" content="d"><style></style></head><body><a class="skip" href="#main">s</a><nav></nav>'
                                     '<main id="main"></main><footer>f</footer></body></html>', encoding="utf-8")
    now = datetime(2026, 11, 22, tzinfo=timezone.utc)
    mk = lambda i, **k: {"id": f"r{i}", "title": f"Engineer {i}", "company": f"Co {i}", "url": f"https://x.example/{i}", "location": "London",  # noqa: E731
                         "countries": ["GB"], "postedAt": "2026-11-20T00:00:00Z", "via": "careers", "facts": {"visa": {"ukRegister": {"listed": True}}}, **k}
    recs = [mk(1), mk(2, facts={"visa": {"status": "no", "ukRegister": {"listed": True}}}), mk(3, facts={"senior": True, "visa": {"ukRegister": {"listed": True}}}),
            mk(4, postedAt="2026-08-01T00:00:00Z"), mk(5, via="board"), mk(6, countries=["US"], location="Austin, TX", facts={"visa": {"opt": "yes"}}),
            mk(7, countries=["US"], location="Austin, TX", facts={"visa": {"status": "no", "why": "citizens"}})]
    pages = growth_pages.visa_pages(recs, out, site, now)
    assert pages[0] == "visa-jobs.html" and "visa-jobs-uk.html" in pages and len(pages) == 8
    uk = (out / "visa-jobs-uk.html").read_text(encoding="utf-8")
    assert "Engineer 1" in uk and all(f"Engineer {i}<" not in uk for i in (2, 3, 4, 5))  # says no, senior, old, and from a job board are left out
    us = (out / "lists" / "usa.md").read_text(encoding="utf-8")
    assert "Engineer 6" in us and "Takes OPT / CPT" in us and "Engineer 7" not in us
    assert "src=visa-uk" in uk and "not that this role is sponsored" in uk
