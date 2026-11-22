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
