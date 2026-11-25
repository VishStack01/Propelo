"""The public job board: pay in the posting's own currency, the four countries first, international numbers."""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from propelo import pay, site

ROOT = Path(__file__).resolve().parents[1]
BOARD = ROOT / "propelo" / "site_app.html"


@pytest.mark.parametrize("text,label,tier", [
    ("$120,000 - $150,000", "$120,000–$150,000 a year", "top"),
    ("$120K–$150K", "$120,000–$150,000 a year", "top"),
    ("USD 120,000 to 150,000 per year", "$120,000–$150,000 a year", "top"),
    ("£45k-£55k", "£45,000–£55,000 a year", "top"),
    ("£45,000 per annum", "£45,000 a year", "good"),
    ("€4.000 - €5.000 per maand", "€4,000–€5,000 a month", "top"),
    ("€55.000,00 bruto per jaar", "€55,000 a year", "good"),
    ("$25 - $30/hr", "$25–$30 an hour", "good"),
    ("£12.71 per hour", "£12.71 an hour", ""),
    ("12-18 LPA", "12–18 LPA", "good"),
    ("₹12,00,000 - ₹18,00,000", "12–18 LPA", "good"),
])
def test_pay_is_read_in_its_own_currency(text, label, tier):
    p = pay.native(text)
    assert pay.label(p) == label and pay.tier(p) == tier


def test_money_that_is_not_one_pay_range_is_left_alone():
    assert pay.native("We raised $50M from investors") is None
    assert pay.native("$100 to €200") is None
    assert pay.native("") is None


def _rec(**kw):
    r = {"id": "r1", "title": "Data Analyst", "company": "Acme", "url": "https://acme.example/1", "location": "London, UK", "countries": ["GB"],
         "postedAt": "2026-11-24T00:00:00Z", "facts": {"loc": "abroad"}}
    r.update(kw)
    return r


def test_the_board_never_shows_a_converted_figure_as_pay():
    # The scan keeps dollars as lakhs for its own gates; the board shows the posting's dollars, or nothing.
    us = _rec(location="Austin, TX", countries=["US"], facts={"loc": "abroad", "salaryLow": 105.6, "salaryHigh": 132.0, "salaryQuote": "pay range $120,000 - $150,000 per year"})
    c = site.compact(us)
    assert c["sal"] == "$120,000–$150,000 a year" and c["pc"] == "USD" and c["pa"] == 150_000 and c["pt"] == "top"
    no_quote = _rec(location="Austin, TX", countries=["US"], facts={"loc": "abroad", "salaryLow": 105.6, "salaryHigh": 132.0})
    assert site.compact(no_quote)["sal"] == ""
    india = _rec(location="Bengaluru, India", countries=["IN"], facts={"loc": "india", "salaryLow": 12, "salaryHigh": 18})
    assert site.compact(india)["sal"] == "12–18 LPA"
    uk = _rec(salary="£45,000 - £55,000")
    assert site.compact(uk)["sal"] == "£45,000–£55,000 a year"
    d = site.detail(uk, "text")
    assert any(f["k"] == "Where" and f["v"] == "On-site or hybrid in United Kingdom" for f in d["facts"])
    api = site.api_item(uk, "text")
    assert api["pay"] == "£45,000–£55,000 a year" and api["pay_currency"] == "GBP" and api["pay_max_annual"] == 55_000


def test_the_board_starts_on_the_four_countries_with_international_numbers():
    html = BOARD.read_text(encoding="utf-8")
    assert "toLocaleString('en-IN')" not in html and "toLocaleString('en-GB')" in html
    assert "where:'core4'" in html and "LPA" not in re.search(r'placeholder="([^"]*)"', html).group(1)
    assert "India" not in re.search(r"<h1 id=\"h1\">([^<]*)</h1>", html).group(1)
    for label in ("Pricing", "Sign in", "Start free"):  # the same way out as every other page
        assert f">{label}</a>" in html


@pytest.mark.skipif(not shutil.which("node"), reason="needs Node")
def test_board_search_reads_pay_and_places(tmp_path):
    html = BOARD.read_text(encoding="utf-8")
    script = html[html.index("<script>") + 8:html.rindex("</script>")]
    start, end = script.index("const CORE4"), script.index("/* Saved and hidden roles")
    places = script[start:end]
    cities = script[script.index("const CITIES"):script.index("function levelsFor")]
    countries = script[script.index("const COUNTRIES"):script.index("const VISA =")]
    js = (f"{countries}\n{places}\n{cities}\n"
          "const out = {q1: parseQuery('London data analyst, graduate, £35k+'), q2: parseQuery('remote python $120k or more'), q3: parseQuery('Dublin 8 LPA'),\n"
          "  core: whereHit({co: ['GB'], w: 'a'}, 'core4'), india: whereHit({co: ['IN'], w: 'i'}, 'core4'), remote: whereHit({co: [], w: 'ww'}, 'remote'),\n"
          "  tag1: placeTag({co: ['IE'], w: 'a'}), tag2: placeTag({co: ['US'], w: 'rx'}), tag3: placeTag({co: [], w: 'ww'})};\n"
          "console.log(JSON.stringify(out));")
    f = tmp_path / "board.js"
    f.write_text(js, encoding="utf-8")
    got = json.loads(subprocess.run(["node", str(f)], capture_output=True, text=True, check=True).stdout)
    assert got["q1"]["city"] == "London" and got["q1"]["minpay"] == "GBP:35000" and got["q1"]["list"] == "newgrad" and got["q1"]["q"] == "data analyst"
    assert got["q2"]["minpay"] == "USD:120000" and got["q2"]["where"] == "remote" and got["q2"]["q"] == "python"
    assert got["q3"]["city"] == "Dublin" and got["q3"]["minpay"] == "INR:800000"
    assert got["core"] is True and got["india"] is False and got["remote"] is True
    assert got["tag1"] == "Ireland" and got["tag2"] == "Remote, United States" and got["tag3"] == "Remote worldwide"
