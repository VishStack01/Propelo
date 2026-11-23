"""The sweep that finds the job boards of employers on the government sponsor lists."""

from __future__ import annotations

import csv
import json

import pytest

from careeros import discover, sponsor_sweep
from careeros.sponsors import CountRegister, NlRegister, UkRegister


def _books():
    uk = UkRegister([{"Organisation Name": n, "Town/City": "London", "Type & Rating": "Worker (A rating)", "Route": "Skilled Worker"} for n in (
        "MONZO BANK LIMITED", "Apex Scaffolding Ltd", "Apex Digital Systems Ltd", "Apex Lifts Ltd", "Faculty Science Limited", "Golden Dragon Takeaway Ltd",
        "St Mary's Church", "Lawhive Ltd", "PSL Vape Ltd T/As Vape Home", "Quantum Data Labs Ltd", "Zebra Bakery Ltd")])
    ie = CountRegister()
    for n, k in (("Google Ireland Limited", 270), ("Dawn Meats Ireland UC", 293), ("Stripe Payments Europe, Limited", 120), ("Tiny Consultancy Limited", 1)):
        ie.add(n, n=k)
    nl = NlRegister()
    nl.add("Adyen N.V.", kvk="34259528")
    return {"GB": uk, "IE": ie, "NL": nl, "US": CountRegister(), "CA": CountRegister()}


def test_names_and_addresses():
    p = sponsor_sweep.pretty
    assert p("MONZO BANK LIMITED") == "Monzo Bank" and p("Google LLC") == "Google" and p("IBM UNITED KINGDOM LIMITED") == "IBM United Kingdom"
    assert p("HSBC UK BANK PLC") == "HSBC UK Bank" and p("Stripe Payments Europe, Limited") == "Stripe Payments Europe"
    assert p("JPMorgan Chase & Co.") == "JPMorgan Chase" and p("Adyen N.V.") == "Adyen" and p("Wise Payments Limited") == "Wise Payments"
    s = sponsor_sweep.slugs_for
    assert s("Monzo Bank Limited") == ["monzobank", "monzo"] and s("Lawhive Ltd") == ["lawhive"]
    assert s("A.A.B. International") == ["aab"] and s("AB Ltd") == [] and s("") == []
    assert s("Adyen N.V.", NlRegister.key("Adyen N.V.")) == ["adyen"]              # the register's own cleaned name wins
    assert s("Tata Consultancy Services Limited") == ["tataconsultancy", "tata"]


def test_candidates_skip_the_unlikely_and_the_already_covered():
    cache = {"companies": {"Lawhive": {"status": "mapped", "ats": "ashby", "token": "lawhive", "boardName": "Lawhive"},
                           "Faculty": {"status": "unmapped"}}}
    rows = sponsor_sweep.candidates(_books(), cache)
    names = [r["name"] for r in rows]
    assert "Lawhive" not in names                                   # its board is already read
    assert not any(w in " ".join(names) for w in ("Takeaway", "Church", "Vape", "Bakery", "Meats"))
    assert {"Monzo Bank", "Faculty Science", "Quantum Data Labs", "Google Ireland", "Stripe Payments Europe", "Adyen"} <= set(names)
    by = {r["name"]: r for r in rows}
    assert by["Monzo Bank"]["country"] == "GB" and by["Monzo Bank"]["category"] == "sponsor" and by["Monzo Bank"]["slugs"] == "monzobank monzo"
    assert by["Google Ireland"]["country"] == "IE" and by["Adyen"]["slugs"] == "adyen"
    # Countries take turns, and a list with counts starts with its biggest sponsor.
    assert [r["country"] for r in rows[:3]] == ["IE", "NL", "GB"] and rows[0]["name"] == "Google Ireland"
    gb = [r["name"] for r in rows if r["country"] == "GB"]
    assert gb.index("Quantum Data Labs") < gb.index("Apex Lifts")   # likelier names first where there are no counts
    assert sponsor_sweep.candidates({}, cache) == []


def test_same_employer_uses_the_rule_that_labels_roles():
    b = _books()
    same = sponsor_sweep.same_employer
    assert same(b, "GB", "Monzo Bank", "Monzo") and same(b, "GB", "Monzo Bank", "Monzo Bank Ltd")
    assert not same(b, "GB", "Apex Scaffolding", "Apex")            # three register names start with Apex: nobody's
    assert not same(b, "GB", "Monzo Bank", "Monzo Travel") and not same(b, "GB", "Monzo Bank", "")
    assert not same(b, "DE", "Monzo Bank", "Monzo") and same(b, "IE", "Google Ireland", "Google Ireland")


def _run(tmp_path, monkeypatch, boards, rows, cache=None, env=None):
    feed = tmp_path / "feed"
    feed.mkdir(exist_ok=True)
    with (feed / "uk-sponsors.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["Organisation Name", "Town/City", "County", "Type & Rating", "Route"])
        w.writeheader()
        for n in ("MONZO BANK LIMITED", "Apex Scaffolding Ltd", "Apex Digital Systems Ltd", "Lawhive Ltd", "Quantum Data Labs Ltd", "Acme Robotics Ltd"):
            w.writerow({"Organisation Name": n, "Town/City": "London", "Type & Rating": "Worker (A rating)", "Route": "Skilled Worker"})
    base = tmp_path / "companies.csv"
    base.write_text("name,category,city,website,slugs,ats,token,source\n")
    sponsor_sweep.write(rows, feed / "sponsor-companies.csv")
    (feed / "boards.json").write_text(json.dumps(cache or {"companies": {}}))
    asked = []

    def probe(ats, slug):
        asked.append((ats, slug))
        return boards.get((ats, slug))
    monkeypatch.setattr(discover, "probe", probe)
    for k, v in (env or {}).items():
        monkeypatch.setenv(k, v)
    discover.run(base, feed / "boards.json", limit=3000, log=lambda *_: None, extra=[feed / "sponsor-companies.csv"], workers=1)
    return json.loads((feed / "boards.json").read_text())["companies"], asked


def _row(name, country="GB"):
    return {"name": name, "category": "sponsor", "slugs": " ".join(sponsor_sweep.slugs_for(name)), "country": country, "source": "sponsor register"}


def test_discover_keeps_a_sponsors_board_only_when_it_is_theirs(tmp_path, monkeypatch):
    boards = {
        ("greenhouse", "monzo"): {"board_name": "Monzo", "locations": ["London", "Cardiff, UK", "Remote - US"], "titles": ["Data Analyst"] * 3},
        ("greenhouse", "apex"): {"board_name": "Apex", "locations": ["London", "New York"], "titles": ["Engineer"] * 2},            # a stranger
        ("lever", "quantumdatalabs"): {"board_name": "", "locations": ["London, UK", "Leeds"], "titles": ["Engineer"] * 2},        # no name, full address
        ("lever", "acme"): {"board_name": "", "locations": ["London, UK", "Leeds"], "titles": ["Engineer"] * 2},                   # no name, first word only
    }
    rows = [_row("Monzo Bank"), _row("Apex Scaffolding"), _row("Quantum Data Labs"), _row("Acme Robotics")]
    got, asked = _run(tmp_path, monkeypatch, boards, rows)
    assert got["Monzo Bank"]["status"] == "mapped" and got["Monzo Bank"]["token"] == "monzo" and got["Monzo Bank"]["confidence"] == "sponsor-name:2"
    assert got["Monzo Bank"]["country"] == "GB" and got["Monzo Bank"]["category"] == "sponsor"
    assert got["Quantum Data Labs"]["status"] == "mapped" and got["Quantum Data Labs"]["confidence"] == "sponsor-slug:2"
    assert got["Apex Scaffolding"] == {"category": "sponsor", "status": "unmapped", "checkedAt": got["Apex Scaffolding"]["checkedAt"],
                                       "probes": got["Apex Scaffolding"]["probes"], "retryDays": sponsor_sweep.RETRY_DAYS}
    assert got["Acme Robotics"]["status"] == "unmapped"            # a nameless board under a first word could be anyone's
    assert ("greenhouse", "monzobank") in asked and ("workable", "monzo") not in asked     # workable gets the first address only


def test_a_board_with_no_roles_in_the_country_or_already_read_is_left(tmp_path, monkeypatch):
    boards = {("greenhouse", "monzo"): {"board_name": "Monzo", "locations": ["Berlin", "Remote - US"], "titles": ["Engineer"] * 2},
              ("ashby", "lawhive"): {"board_name": "Lawhive", "locations": ["London"], "titles": ["Engineer"]}}
    cache = {"companies": {"Lawhive": {"status": "mapped", "ats": "ashby", "token": "lawhive", "category": "ai-native"}}}
    got, asked = _run(tmp_path, monkeypatch, boards, [_row("Monzo Bank"), _row("Lawhive Legal")], cache)
    assert got["Monzo Bank"]["status"] == "unmapped"               # hires elsewhere: nothing here for someone in the UK
    assert ("ashby", "lawhive") not in asked and got["Lawhive"]["category"] == "ai-native"   # never one board under two names
    # Not due again until the retry time has passed.
    again, asked2 = _run(tmp_path, monkeypatch, boards, [_row("Monzo Bank")], {"companies": got})
    assert asked2 == []


def test_only_so_many_register_employers_per_run(monkeypatch):
    spons = [{"name": f"S{i}", "category": "sponsor"} for i in range(900)]
    deep = [{"name": f"D{i}", "category": "deep"} for i in range(40)]
    rest = [{"name": f"R{i}", "category": "curated"} for i in range(10)]
    out = discover.share_out(rest + spons + deep, 3000)
    assert sum(1 for c in out if c["category"] == "sponsor") == sponsor_sweep.PER_RUN and len(out) == 50 + sponsor_sweep.PER_RUN
    assert {c["category"] for c in out[:9]} == {"deep", "curated", "sponsor"}       # spread through the run, not left for last
    monkeypatch.setenv("CAREEROS_SPONSOR_SWEEP", "0")
    assert not any(c["category"] == "sponsor" for c in discover.share_out(rest + spons + deep, 3000))


def test_sponsor_boards_are_read_on_the_slower_schedule_and_not_counted_as_companies():
    from careeros import scan
    assert scan.scan_every_hours({"category": "sponsor"}) == 0.0                                  # never read yet: now
    assert scan.scan_every_hours({"category": "sponsor", "scannedAt": "x", "roles": 3}) == 4.0
    assert scan.scan_every_hours({"category": "sponsor", "scannedAt": "x", "roles": 0}) == 24.0
    assert sponsor_sweep.stats({"companies": {"a": {"category": "sponsor", "checkedAt": "t", "status": "mapped"},
                                              "b": {"category": "sponsor", "checkedAt": "t", "status": "unmapped"}, "c": {"category": "deep"}}}) == {"checked": 2, "kept": 1}
