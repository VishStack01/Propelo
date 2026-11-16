"""Company logos: a logo only for a company whose own website the evidence names, never a guess."""

import json
import struct
import zlib

from careeros import logos


def png(width: int) -> bytes:
    raw = b"".join(b"\x00" + b"\xff\xff\xff" * width for _ in range(width))
    def chunk(t, d): return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, width, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


def test_registrable_domains():
    assert logos.registrable("careers.airbnb.com") == "airbnb.com"
    assert logos.registrable("jobs.tcs.co.in") == "tcs.co.in"
    assert logos.registrable("localhost") == ""


def test_names_match_their_own_domains_only():
    assert logos.matches("Sarvam AI", "sarvam.ai")
    assert logos.matches("HG Insights", "hginsights.com")
    assert logos.matches("Motive", "gomotive.com")
    assert logos.matches("Lingo.dev", "lingo.dev")
    assert not logos.matches("Spenmo", "summitglobal.com")
    assert not logos.matches("Acme", "greenhouse.io")


def test_domain_comes_from_evidence():
    # The company's own careers host
    assert logos.domain_for("Airbnb", ["https://careers.airbnb.com/positions/1"], []) == "airbnb.com"
    # A hiring system's host is never the company's site; the posting's own link or email is
    assert logos.domain_for("Kyndryl", ["https://kyndryl.wd5.myworkdayjobs.com/x"], ["Apply at careers@kyndryl.com. See www.linkedin.com/company/kyndryl"]) == "kyndryl.com"
    # A domain that names another company isn't used
    assert logos.domain_for("Acme", ["https://boards.greenhouse.io/acme/jobs/1"], ["We partner with stripe.com and openai.com"]) == ""
    # The website on record wins
    assert logos.domain_for("Spenmo", [], [], website="https://summitglobal.com/") == "summitglobal.com"


def test_guesses_are_checked_against_the_site(tmp_path):
    seen = []

    def get(url):
        seen.append(url)
        if url == "https://kyndryl.com/":
            return 200, "text/html", b"<html><title>Kyndryl | Infrastructure services</title></html>"
        if url == "https://acmerobotics.com/":
            return 200, "text/html", b"<title>Parked domain for sale</title>"
        if "s2/favicons" in url:
            return 200, "image/png", png(64)
        return 404, "", b""
    mapping = {"kyndryl": "?" + ",".join(logos.guesses("Kyndryl")) + "|Kyndryl",
               "acme-robotics": "?" + ",".join(logos.guesses("Acme Robotics")) + "|Acme Robotics",
               "airbnb": "airbnb.com"}
    res = logos.update(tmp_path, mapping, get=get, log=lambda *_: None)
    assert res["withLogo"] == 2
    files = logos.for_site(tmp_path)
    assert set(files) == {"kyndryl", "airbnb"}  # the parked domain didn't name the company
    # A second run within the refresh window fetches nothing
    seen.clear()
    logos.update(tmp_path, mapping, get=get, log=lambda *_: None)
    assert seen == []


def test_tiny_or_broken_icons_are_skipped():
    calls = iter([(200, "image/png", png(16)), (200, "text/html", b"<html>not an image</html>"), (404, "", b"")])
    assert logos.fetch_icon("tiny.com", get=lambda url: next(calls)) is None
    assert logos.fetch_icon("ok.com", get=lambda url: (200, "image/png", png(96)))[1] == "png"


def test_site_publishes_logos(tmp_path):
    from conftest import feed_record, write_feed
    from careeros import site
    feed = tmp_path / "feed"
    write_feed(feed, [feed_record(1, company="Company 1"), feed_record(2, company="Company 2")])
    cache = tmp_path / "cache"
    logos.update(cache, {"company-1": "company1.com"}, get=lambda url: (200, "image/png", png(64)), log=lambda *_: None)
    site.build(feed, tmp_path / "out", log=lambda *_: None, website=None, logos_dir=cache)
    jobs = json.loads((tmp_path / "out" / "data" / "jobs.json").read_text())["jobs"]
    by = {j["c"]: j for j in jobs}
    assert by["Company 1"]["lo"].startswith("logos/") and (tmp_path / "out" / by["Company 1"]["lo"]).exists()
    assert "lo" not in by["Company 2"]
    # the app shows the same logos: a map of company slug -> file next to them
    lmap = json.loads((tmp_path / "out" / "logos" / "map.json").read_text())
    assert lmap == {"company-1": by["Company 1"]["lo"][len("logos/"):]}


def test_well_known_employers_get_their_own_site():
    """Workday codes and sites that block the automatic check still get the company's own logo."""
    assert logos.known_domain("Hpe") == "hpe.com" and logos.known_domain("Jci") == "johnsoncontrols.com"
    assert logos.known_domain("Medtronic (Redeploymentmedtroniccareers)") == "medtronic.com"
    assert logos.known_domain("‎ConnectWise") == "connectwise.com"
    assert logos.known_domain("Some Startup Nobody Knows") == ""
    m = logos.discover([{"id": "1", "company": "NVIDIA", "url": "https://nvidia.wd5.myworkdayjobs.com/x"}], {})
    assert m == {"nvidia": "nvidia.com"}  # not a guess to verify


def test_known_domains_are_plain_websites():
    import re
    from pathlib import Path
    data = json.loads((Path(logos.__file__).parent / "data" / "company_domains.json").read_text())["domains"]
    assert len(data) > 300
    for name, d in data.items():
        assert re.fullmatch(r"[a-z0-9-]+(\.[a-z0-9-]+)*\.[a-z]{2,6}", d), (name, d)
        assert not logos.NOT_COMPANY.search(d) or name.lower() in ("ashby", "workday", "rippling"), (name, d)  # ATS makers hire too
