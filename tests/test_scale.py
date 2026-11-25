"""Scale: countries a location only implies, visa signals beyond the UK, reading a rotating share of boards,
and a feed intake that neither holds the feed in memory nor rewrites roles that didn't change."""

import gzip
import json
from datetime import datetime, timedelta, timezone

import pytest

from propelo import countries, scan, sponsors
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
    from propelo.cloud.ingest import ingest
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
    from propelo.cloud import repo
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


DODO_SECRET = "whsec_" + __import__("base64").b64encode(b"dodo-pass-secret-0123456789").decode()


def _pass_cloud(cloud, monkeypatch):
    from propelo.cloud import plans
    for k, v in dict(pass_enabled=True, dodo_api_key="dodo_test", dodo_webhook_secret=DODO_SECRET, dodo_product_pro="pdt_PRO",
                     dodo_product_pass="pdt_PASS", dodo_product_pass_ultra="pdt_PASS_ULTRA").items():
        object.__setattr__(cloud.cfg, k, v)
    checkouts = []

    def call(method, url, body, key):
        checkouts.append(body)
        return {"session_id": f"cks_P{len(checkouts)}", "checkout_url": f"https://test.checkout.dodopayments.com/P{len(checkouts)}"}
    monkeypatch.setattr(plans, "_dodo_request", call)
    return checkouts


def _pass_paid(cloud, checkout, amount, n=0):
    import base64
    import hashlib
    import hmac
    import time
    body = json.dumps({"type": "payment.succeeded", "timestamp": "2026-11-25T00:00:00Z",
                       "data": {"payment_id": f"pay_{n}", "total_amount": amount, "metadata": checkout["metadata"]}}).encode()
    wid, ts = f"msg_{checkout['metadata']['pass_id']}_{amount}_{n}", str(int(time.time()))
    sig = base64.b64encode(hmac.new(base64.b64decode(DODO_SECRET[6:]), f"{wid}.{ts}.".encode() + body, hashlib.sha256).digest()).decode()
    return cloud.client().post("/api/billing/dodo-webhook", content=body, headers={
        "Content-Type": "application/json", "webhook-id": wid, "webhook-timestamp": ts, "webhook-signature": f"v1,{sig}"}).json()


def test_90_day_passes_for_pro_and_ultra(cloud, monkeypatch):
    a = cloud.user("asha@example.com")
    offer = a.get("/api/billing").json()["pass"]
    assert offer["days"] == 90 and [(x["plan"], x["priceUsd"], x["onSale"]) for x in offer["passes"]] == [("pro", "99.00", False), ("ultra", "189.00", False)]
    assert not offer["onSale"] and a.post("/api/billing/pass", json={"plan": "pro"}).status_code == 503  # not on sale until the Dodo products exist
    object.__setattr__(cloud.cfg, "pass_enabled", False)
    assert a.get("/api/billing").json()["pass"] is None and a.post("/api/billing/pass").status_code == 503  # PASS=off
    checkouts = _pass_cloud(cloud, monkeypatch)
    offer = a.get("/api/billing").json()["pass"]
    assert offer["onSale"] and all(x["onSale"] for x in offer["passes"]) and not offer["running"]
    assert a.post("/api/billing/pass", json={"plan": "gold"}).status_code == 400
    assert a.post("/api/billing/pass", json={"plan": "pro", "currency": "INR"}).json()["code"] == "bad_currency"
    r = a.post("/api/billing/pass", json={"plan": "pro"})
    assert r.status_code == 200 and r.json()["url"].startswith("https://test.checkout.dodopayments.com/")
    assert checkouts[0]["product_cart"] == [{"product_id": "pdt_PASS", "quantity": 1}] and checkouts[0]["metadata"]["plan"] == "pro"
    assert a.get("/api/me").json()["plan"] == "free"  # nothing until the payment webhook
    assert _pass_paid(cloud, checkouts[0], 100)["result"] == "short" and a.get("/api/me").json()["plan"] == "free"
    assert _pass_paid(cloud, checkouts[0], 9_900, 1)["result"] == "paid"
    assert a.get("/api/me").json()["plan"] == "pro"
    assert _pass_paid(cloud, checkouts[0], 9_900, 2)["result"] == "duplicate"
    first = a.get("/api/billing").json()["pass"]["running"]
    assert first["plan"] == "pro"
    assert any(m["subject"] == "Your Pro pass has started" for m in cloud.outbox)
    # An Ultra pass adds its 90 days to the end and switches the account to Ultra.
    a.post("/api/billing/pass", json={"plan": "ultra"})
    assert checkouts[1]["product_cart"] == [{"product_id": "pdt_PASS_ULTRA", "quantity": 1}]
    assert _pass_paid(cloud, checkouts[1], 18_900, 3)["result"] == "paid"
    second = a.get("/api/billing").json()["pass"]["running"]
    assert second["plan"] == "ultra" and a.get("/api/me").json()["plan"] == "ultra"
    assert (datetime.fromisoformat(second["endsAt"].replace("Z", "+00:00")) - datetime.fromisoformat(first["endsAt"].replace("Z", "+00:00"))).days == 90
    # A Pro pass bought during an Ultra pass adds days without stepping down.
    a.post("/api/billing/pass", json={"plan": "pro"})
    assert _pass_paid(cloud, checkouts[2], 9_900, 4)["result"] == "paid" and a.get("/api/me").json()["plan"] == "ultra"
    admin = cloud.user("admin@example.com")
    assert admin.get("/api/admin/funnel").json()["total"]["paying"] == 1


def test_sponsor_check_data_and_visa_pages(tmp_path):
    from propelo import growth_pages
    feed, out, site = tmp_path / "feed", tmp_path / "out", tmp_path / "website"
    feed.mkdir(); out.mkdir(); site.mkdir()
    rows = ["Organisation Name,Town/City,County,Type & Rating,Route"] + [f"Firm {i} Ltd,Leeds,,Worker (A rating),Skilled Worker" for i in range(1200)]
    rows += ['"Monzo Bank Ltd",London,,Worker (A rating),Skilled Worker', "Circus Ltd,Bath,,Temporary Worker (A rating),Creative Worker"]
    (feed / "uk-sponsors.csv").write_text("\n".join(rows), encoding="utf-8")
    counts = growth_pages.sponsor_data(feed, out)
    text = (out / "data" / "sponsors-uk.txt").read_text(encoding="utf-8")
    assert counts["uk"] == 1201 and counts["nl"] == 0 and counts["us"] == 0 and "Monzo Bank Ltd\tLondon\tA rating" in text and "Circus" not in text
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
    assert pages == ["visa-jobs.html", "visa-jobs-uk.html", "visa-jobs-usa.html", "visa-jobs-ireland.html", "visa-jobs-netherlands.html"]
    assert "location.replace" in (out / "visa-jobs-canada.html").read_text(encoding="utf-8")  # retired pages send visitors on
    uk = (out / "visa-jobs-uk.html").read_text(encoding="utf-8")
    assert "Engineer 1" in uk and all(f"Engineer {i}<" not in uk for i in (2, 3, 4, 5))  # says no, senior, old, and from a job board are left out
    us = (out / "lists" / "usa.md").read_text(encoding="utf-8")
    assert "Engineer 6" in us and "Takes OPT / CPT" in us and "Engineer 7" not in us
    assert "src=visa-uk" in uk and "not that this role is sponsored" in uk


def test_visa_pages_say_how_many_matched_when_the_list_is_cut(tmp_path):
    from propelo import growth_pages
    out, site = tmp_path / "out", tmp_path / "website"
    out.mkdir(); site.mkdir()
    (site / "check.html").write_text('<html><head><title>x</title><style></style></head><body><a class="skip" href="#main">s</a><nav></nav>'
                                     '<main id="main"></main><footer>f</footer></body></html>', encoding="utf-8")
    now = datetime(2026, 11, 22, tzinfo=timezone.utc)
    recs = [{"id": f"r{i}", "title": f"Analyst {i}", "company": f"Co {i}", "url": f"https://x.example/{i}", "location": "Dublin", "countries": ["IE"],
             "postedAt": "2026-11-20T00:00:00Z", "via": "careers", "facts": {"visa": {"iePermits": 3}}} for i in range(growth_pages.MAX_ROWS + 40)]
    growth_pages.visa_pages(recs, out, site, now)
    ie = (out / "visa-jobs-ireland.html").read_text(encoding="utf-8")
    assert f"Newest {growth_pages.MAX_ROWS} of {growth_pages.MAX_ROWS + 40} roles" in ie and "jobs.html?co=IE&amp;vs=ie%7Csponsors" in ie
    assert ie.count('class="vj-row"') == growth_pages.MAX_ROWS
    assert f"{growth_pages.MAX_ROWS + 40} recent roles" in (out / "visa-jobs.html").read_text(encoding="utf-8")


# ---------------------------------------------------------------- lists of employers that have sponsored

def test_register_links_are_found_on_the_official_pages():
    from propelo import registers
    page = ('<a href="/sites/dolgov/files/ETA/oflc/pdfs/LCA_Disclosure_Data_FY2026_Q2.xlsx">Q2</a>'
            '<a href="/sites/dolgov/files/ETA/oflc/pdfs/LCA_Disclosure_Data_FY2026_Q3.xlsx">Q3</a>'
            '<a href="/sites/dolgov/files/ETA/oflc/pdfs/LCA_Disclosure_Data_FY2025_Q4.xlsx">old</a><a href="/x/PERM_Disclosure_Data_FY2026_Q3.xlsx">perm</a>')
    assert [u[-14:] for u in registers.us_links(page)] == ["FY2026_Q3.xlsx", "FY2026_Q2.xlsx", "FY2025_Q4.xlsx"]
    api = json.dumps({"result": {"resources": [
        {"url": "https://open.canada.ca/x/download/tfwp_2026q1_pos_en.xlsx"}, {"url": "https://open.canada.ca/x/download/tfwp_2026q2_pos_en.xlsx"},
        {"url": "https://open.canada.ca/x/download/tfwp_2026q2_pos_fr.xlsx"}, {"url": "https://open.canada.ca/x/download/tfwp_2025q4_positive_en.csv"}]}})
    assert [u.rsplit("/", 1)[1] for u in registers.ca_links(api)] == ["tfwp_2026q2_pos_en.xlsx", "tfwp_2026q1_pos_en.xlsx", "tfwp_2025q4_positive_en.csv"]
    ie = ('<h3>Employment permits by nationality 2026</h3><a href="https://assets.gov.ie/static/documents/aaa.xlsx">Download</a>'
          + "x" * 900 + '<h3>Employment permits issued to companies 2026</h3><a href="https://assets.gov.ie/static/documents/bbb.xlsx">Download</a>')
    assert registers.ie_link(ie, "https://www.gov.ie/x/") == "https://assets.gov.ie/static/documents/bbb.xlsx"


def test_register_spreadsheets_are_tallied_and_used(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    from propelo import registers
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["CASE_NUMBER", "CASE_STATUS", "VISA_CLASS", "EMPLOYER_NAME"])
    for row in (["1", "Certified", "H-1B", "Acme Robotics Inc"], ["2", "Certified - Withdrawn", "H-1B", "Acme Robotics Inc"], ["3", "Denied", "H-1B", "Acme Robotics Inc"],
                ["4", "Certified", "E-3 Australian", "Koala LLC"], ["5", "Certified", "H-1B", "Globex Corporation"]):
        ws.append(row)
    us = tmp_path / "lca.xlsx"
    wb.save(us)
    got = registers.tally(registers.rows_of(us), (r"employer_name",), keep=lambda r: r.get("case_status", "").lower().startswith("certified")
                          and r.get("visa_class", "").upper().startswith("H-1B"), need=("case_status", "visa_class"))
    assert got == {"Acme Robotics Inc": 2, "Globex Corporation": 1}
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Employers who were issued a positive LMIA, 2026Q2"])
    ws.append([])
    ws.append(["Province/Territory", "Program Stream", "Employer", "Address", "Occupation", "Approved LMIAs", "Approved Positions"])
    ws.append(["Ontario", "High Wage", "Maple Software Ltd.", "Toronto", "21231", "2", "5"])
    ws.append(["Ontario", "High Wage", "Maple Software Ltd.", "Toronto", "21232", "1", "1"])
    ca = tmp_path / "lmia"  # downloads are saved without an extension
    wb.save(ca)
    assert registers.tally(registers.rows_of(ca), (r"^employer$", r"employer"), (r"approved positions", r"positions")) == {"Maple Software Ltd.": 6}
    ie = tmp_path / "ie.csv"
    ie.write_text("Employer Name,Permits Issued Jan,Permits Issued Feb,Permits Issued Grand Total\nShamrock Tech Ltd,2,3,5\nGrand Total,2,3,5\n", encoding="utf-8")
    assert registers.tally(registers.rows_of(ie), (r"employer", r"company"), (r"grand total", r"total")) == {"Shamrock Tech Ltd": 5}  # the total, not January
    with pytest.raises(OSError):
        registers._write(tmp_path / "us.csv", got, "us")  # far too few employers: the old file is kept
    (tmp_path / "us-sponsors.csv").write_text("name,n\nAcme Robotics Inc,2\n", encoding="utf-8")
    (tmp_path / "ca-sponsors.csv").write_text("name,n\nMaple Software Ltd.,6\n", encoding="utf-8")
    counts = sponsors.load_count_registers(tmp_path)
    v = sponsors.visa_facts("Acme Robotics", "Austin, TX", "Great team.", counts=counts)
    assert v["usLca"] == {"listed": True, "name": "Acme Robotics Inc", "n": 2, "match": "exact"} and "has sponsored H-1B workers" in sponsors.label(v)
    assert "usLca" not in sponsors.visa_facts("Acme Robotics", "London", "Great team.", counts=counts)  # a US list, used for US roles only
    assert "usLca" not in sponsors.visa_facts("Initech", "Austin, TX", "Great team.", counts=counts)  # no match is never reported as a "no"
    assert sponsors.visa_facts("Maple Software", "Toronto, ON", "x", counts=counts)["caLmia"]["n"] == 6


def test_pricing_page_goes_straight_to_checkout_when_payments_are_on(cloud):
    c = cloud.client()
    assert "buy%3Dpro" not in c.get("/pricing").text  # payments off: every card starts free
    for k, v in dict(dodo_api_key="dodo_test", dodo_webhook_secret="whsec_x", dodo_product_pro="pdt_PRO", dodo_product_ultra="pdt_ULTRA",
                     dodo_product_pass="pdt_PASS", pass_enabled=True).items():
        object.__setattr__(cloud.cfg, k, v)
    page = c.get("/pricing").text
    assert 'href="/signup?next=%2Fapp%3Fbuy%3Dpro">Get Pro</a>' in page and "Get the pass" in page and "buy%3Dpass-pro" in page
    assert "buy%3Dpass-ultra" not in page  # the Ultra pass's product isn't set
    # The sign-up form carries that destination through the confirm link.
    r = c.post("/api/auth/signup", json={"name": "Asha", "email": "buyer@example.com", "password": "correct horse 42 staple", "next": "/app?buy=pro"})
    assert r.status_code == 202 and "next=%2Fapp%3Fbuy%3Dpro" in json.dumps(cloud.outbox[-1])


def test_discovery_gives_the_deep_sweep_most_of_each_run():
    from propelo import discover
    rest = [{"name": f"curated {i}", "category": "ai-native"} for i in range(50)]
    deep = [{"name": f"deep {i}", "category": "deep"} for i in range(500)]
    got = discover.share_out(rest + deep, 40)
    assert len(got) == 40 and sum(1 for c in got if c["category"] == "deep") == 30 and got[0]["category"] == "deep" and got[3]["category"] != "deep"
    assert len(discover.share_out(rest + deep[:5], 40)) == 40  # few deep boards due: the curated lists take the room
    assert [c["name"] for c in discover.share_out(rest[:2], 40)] == ["curated 0", "curated 1"]


def test_visa_lists_leave_out_volunteer_places_and_roles_hired_elsewhere():
    from datetime import datetime, timezone
    from propelo import growth_pages
    now = datetime.now(timezone.utc)

    def rec(i, title):
        return {"id": f"v{i}", "title": title, "company": f"Co {i}", "location": "London, United Kingdom", "postedAt": now.isoformat(), "url": f"https://x.example/{i}",
                "via": "careers", "facts": {"visa": {"ukRegister": {"listed": True, "name": f"Co {i} Ltd"}}}}
    rows = growth_pages.pick([rec(1, "Data Analyst"), rec(2, "Investor Relations Event Volunteer"), rec(3, "Brand Manager (relocation to New Zealand)"),
                              rec(4, "Unpaid Marketing Intern"), rec(5, "Software Engineer, UK")], "GB", now)
    assert [r["title"] for r in rows] == ["Data Analyst", "Software Engineer, UK"]
