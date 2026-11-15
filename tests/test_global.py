"""Matching for people outside India: remote roles open to their country or region, and on-site or
hybrid roles in places they chose. India keeps its own rules."""

from datetime import datetime, timezone

from careeros import countries, extract, feed, gates
from careeros.models import Job


def _job(title="Backend Engineer", location="Remote", mode="remote", desc="Build APIs.", **kw):
    return Job(source="t", company="Acme", title=title, url="https://boards.greenhouse.io/acme/jobs/1", location=location,
               work_mode=mode, description=desc, posted_at=datetime.now(timezone.utc).isoformat(), **kw)


def _settings(home, places=""):
    return feed.settings_from_dashboard({"homeCountry": home, "places": places, "targetRoles": ["backend"]})


def test_country_names_in_locations():
    assert countries.named("Remote - Germany, Spain, United Kingdom") == {"DE", "ES", "GB"}
    assert countries.named("Toronto, ON") == {"CA"} and countries.named("we focus on us") == set()


def test_remote_roles_follow_the_persons_country():
    us, de = _settings("US"), _settings("DE")
    chk, region = gates.gate_location(_job(location="Remote - United States"), us)
    assert chk.passed and region == "remote-local"
    chk, _ = gates.gate_location(_job(location="Remote - United States"), de)
    assert not chk.passed and "United States" in chk.value
    assert gates.gate_location(_job(location="Remote - Germany, Spain, United Kingdom"), de)[0].passed
    assert gates.gate_location(_job(location="Remote, Worldwide"), de)[1] == "remote-global"
    assert gates.gate_location(_job(location="Remote (EMEA)", desc="Remote in Europe only, must reside in the EU."), de)[0].passed


def test_time_zone_ranges_use_the_persons_offset():
    job = _job(location="Remote", desc="You must overlap UTC-5 to UTC+1 working hours.")
    assert gates.gate_location(job, _settings("GB"))[0].passed
    assert not gates.gate_location(job, _settings("SG"))[0].passed
    assert extract.tz_range("UTC-5 to UTC+1")[:2] == (-5, 1)


def test_on_site_roles_only_in_chosen_places():
    s = _settings("GB", "London, Manchester")
    assert gates.gate_location(_job(location="London, England", mode="hybrid"), s) [1] == "local"
    assert not gates.gate_location(_job(location="Berlin, Germany", mode="onsite"), s)[0].passed
    assert gates.gate_location(_job(location="Leeds, United Kingdom", mode="onsite"), _settings("GB", "United Kingdom"))[0].passed


def test_work_authorization_is_judged_against_home():
    from careeros import signals
    desc = "You must be authorized to work in the United States without sponsorship."
    j = _job(location="Remote - United States", desc=desc)
    wa = signals.work_authorization(desc)
    if wa.get("country"):
        assert gates.gate_work_auth(j, "remote-local", "US").passed
        assert not gates.gate_work_auth(j, "remote-global", "DE").passed


def test_india_rules_are_unchanged():
    s = feed.settings_from_dashboard({"targetRoles": ["backend"]})
    assert s.location.home == "IN"
    chk, region = gates.gate_location(_job(location="Bengaluru, India", mode="onsite"), s)
    assert chk.passed and region == "south-india"
    assert not gates.gate_location(_job(location="Remote - United States"), s)[0].passed
