"""The offer sponsor brief: the right brief for a visa and the role's country, the member's dates in it, every
fact with an official source, a plain note to HR, and the dashboard giving the same answer."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from datetime import date
from pathlib import Path

import pytest

from propelo import sponsorbrief, visaclock

ROOT = Path(__file__).resolve().parent.parent
TODAY = date(2026, 11, 25)
OFFICIAL = ("https://www.gov.uk/", "https://enterprise.gov.ie/", "https://www.irishimmigration.ie/", "https://workplacerelations.ie/",
            "https://ind.nl/", "https://www.uscis.gov/", "https://www.ice.gov/", "https://studyinthestates.dhs.gov/",
            "https://content.govdelivery.com/accounts/USDHSCIS/")


@pytest.mark.parametrize(("location", "visa", "code"), [
    ("London, United Kingdom", None, "GB"), ("Belfast, Northern Ireland", None, "GB"), ("Dublin, Ireland", None, "IE"),
    ("Amsterdam, Netherlands", None, "NL"), ("Cambridge, MA", None, "US"), ("Dublin, OH", None, "US"), ("New York, NY", None, "US"),
    ("Remote", {"ukRegister": {"listed": True}}, "GB"), ("Remote", None, ""), ("Berlin, Germany", None, ""), ("Cambridge, England", None, "GB"),
])
def test_role_country(location, visa, code):
    assert sponsorbrief.role_country(location, visa) == code


def test_each_visa_gets_its_own_brief_in_its_own_country():
    want = {"uk-student": "gb-student", "uk-graduate": "gb-graduate", "uk-skilled": "gb-skilled", "ie-stamp2": "ie-stamp2", "ie-stamp1g": "ie-stamp1g",
            "nl-study": "nl-study", "nl-zoekjaar": "nl-zoekjaar", "us-f1": "us-student", "us-cpt": "us-student", "us-opt": "us-opt",
            "us-stem-opt": "us-stem-opt", "us-h1b": "us-h1b"}
    where = {"GB": "London, United Kingdom", "IE": "Dublin, Ireland", "NL": "Amsterdam, Netherlands", "US": "Austin, TX"}
    for status, bid in want.items():
        st = visaclock.BY_ID[status]
        assert sponsorbrief.brief({"status": status}, where[st["country"]], today=TODAY)["id"] == bid, status
    # In another country, or not living in one of the four yet: the new-hire brief for the role's country.
    assert sponsorbrief.brief({"status": "uk-graduate"}, "Dublin, Ireland", today=TODAY)["id"] == "ie-abroad"
    assert sponsorbrief.brief({"status": "abroad"}, "Amsterdam, Netherlands", today=TODAY)["id"] == "nl-abroad"
    assert sponsorbrief.brief({"status": "abroad"}, "Seattle, WA", today=TODAY)["id"] == "us-abroad"
    # No brief without a visa, for someone settled, or for a country Propelo doesn't cover.
    assert sponsorbrief.brief({}, "London", today=TODAY) is None
    assert sponsorbrief.brief({"status": "settled"}, "London", today=TODAY) is None
    assert sponsorbrief.brief({"status": "abroad"}, "Berlin, Germany", today=TODAY) is None


def test_the_members_own_dates_go_in_and_past_dates_stay_out():
    b = sponsorbrief.brief({"status": "uk-graduate", "permitEnd": "2027-09-30"}, "Manchester, UK", today=TODAY)
    assert b["headline"] == "Nothing now: my Graduate visa lets me work for you without sponsorship until 30 Sep 2027."
    assert b["points"][0] == "My Graduate visa lets me work for any employer until 30 Sep 2027. You don't need a sponsor licence to hire me now."
    past = sponsorbrief.brief({"status": "uk-graduate", "permitEnd": "2026-01-01"}, "Manchester, UK", today=TODAY)
    assert "until" not in past["headline"] and "{until}" not in " ".join(past["points"])
    opt = sponsorbrief.brief({"status": "us-opt", "optEnd": "2027-06-01", "permitEnd": "2030-01-01"}, "Austin, TX", today=TODAY)
    assert "until 1 Jun 2027" in opt["points"][0]


def test_every_fact_has_an_official_source_and_no_long_dashes():
    rules = sponsorbrief.RULES
    briefs = rules["briefs"] + list(rules["abroad"].values())
    for b in briefs:
        assert b["sources"] and all(url.startswith(OFFICIAL) for _, url in b["sources"]), b["id"]
        assert all("—" not in x for x in [b["headline"], *b["points"]]), b["id"]
    text = json.dumps(rules, ensure_ascii=False)
    assert "guarantee" not in text.lower()
    # The student switch is the one place the UK charge is waived; the graduate switch still pays it.
    assert "you pay no Immigration Skills Charge" in " ".join(next(b for b in briefs if b["id"] == "gb-student")["points"])
    assert "Immigration Skills Charge (£1,320" in " ".join(next(b for b in briefs if b["id"] == "gb-graduate")["points"])


def test_note_to_hr_is_plain_and_dated():
    b = sponsorbrief.brief({"status": "nl-zoekjaar", "permitEnd": "2027-08-31"}, "Utrecht, Netherlands", today=TODAY)
    n = sponsorbrief.note(b, to="Sanne de Vries", me="Asha Rao", stage="offer")
    assert n.startswith("Hi Sanne,\n\nThanks for the offer. As sponsorship can be a question")
    assert "- My orientation year lets me work for any employer with no work permit until 31 Aug 2027." in n
    assert "Sources:\n- IND: orientation year: https://ind.nl/" in n and n.endswith("Checked 25 Nov 2026. Happy to talk it through.\n\nAsha")
    assert sponsorbrief.note(b).startswith("Hi there,\n\nThanks for looking at my application.")


CASES = [
    ({"status": "uk-student", "permitEnd": "2027-01-31"}, "London, United Kingdom", None),
    ({"status": "uk-graduate", "permitEnd": "2027-09-30"}, "Leeds", {"ukRegister": {"listed": True}}),
    ({"status": "uk-graduate"}, "Dublin, Ireland", None),
    ({"status": "ie-stamp1g", "permitEnd": "2027-03-01"}, "Cork, Ireland", None),
    ({"status": "nl-zoekjaar", "permitEnd": "2026-01-01"}, "Amsterdam, Netherlands", None),
    ({"status": "us-stem-opt", "optEnd": "2028-05-01"}, "Cambridge, MA", None),
    ({"status": "us-h1b", "permitEnd": "2029-01-01"}, "Remote", {"usLca": {"n": 4}}),
    ({"status": "abroad"}, "Rotterdam", None),
    ({"status": "settled"}, "London", None),
    ({}, "London", None),
]


@pytest.mark.skipif(not shutil.which("node"), reason="node is not installed")
def test_dashboard_brief_matches_python(tmp_path):
    html = (ROOT / "dashboard" / "app.html").read_text(encoding="utf-8")
    clock = re.search(r"/\* visa-clock:start.*?\*/(.*?)/\* visa-clock:end \*/", html, re.S).group(1)
    block = re.search(r"/\* brief:start.*?\*/(.*?)/\* brief:end \*/", html, re.S).group(1)
    data = json.loads(re.search(r"^const SPONSOR_BRIEF = (.*);$", block, re.M).group(1).replace("<\\/", "</"))
    assert data == {k: v for k, v in sponsorbrief.RULES.items() if k != "_about"}, "run python3 scripts/sync_sponsor_brief.py"
    script = tmp_path / "brief.js"
    script.write_text(clock + block + "\nconst cases = JSON.parse(process.argv[2]);\nconsole.log(JSON.stringify(cases.map(([v, loc, jv]) => { const b = sponsorBrief(v, loc, jv, '2026-11-25'); "
                      "return {b, note: b ? sponsorNote(b, 'Sam Lee', 'Asha Rao', 'screen') : null}; })));\n", encoding="utf-8")
    out = json.loads(subprocess.run(["node", str(script), json.dumps(CASES)], capture_output=True, text=True, timeout=60, check=True).stdout)
    for (v, loc, jv), got in zip(CASES, out):
        want = sponsorbrief.brief(v, loc, jv, today=TODAY)
        assert got["b"] == want, (v, loc)
        assert got["note"] == (sponsorbrief.note(want, "Sam Lee", "Asha Rao", "screen") if want else None), (v, loc)
