"""Matching for people outside India: remote roles open to their country or region, and on-site or
hybrid roles in places they chose. India keeps its own rules."""

from datetime import datetime, timezone

from propelo import countries, extract, feed, gates
from propelo.models import Job


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
    from propelo import signals
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


# ---- 2.14.0: what a member abroad actually sees (found by running real profiles against the live feed)
def test_a_remote_role_placed_in_another_country_is_not_shown():
    gb = _settings("GB", "United Kingdom")
    for where in ("Almaty, Almaty Region, Kazakhstan", "Belgrade", "NYC - 12 E 49th St (Tower 49)", "Vilnius, Kaunas", "Kyiv", "Remote - Brasil"):
        chk, region = gates.gate_location(_job(location=where), gb)
        assert not chk.passed and region == "", where
    # A remote role that names no place is kept, in a region of its own so it can be shown last.
    chk, region = gates.gate_location(_job(location="Remote"), gb)
    assert chk.passed and region == "remote-unclear" and "doesn't say who can apply" in chk.value
    # India's rules keep their old region name for it.
    india = feed.settings_from_dashboard({"targetRoles": ["backend"]})
    assert gates.gate_location(_job(location="Remote"), india)[1] in ("remote-global", "")


def test_places_the_tables_now_know():
    r = countries.resolve
    assert r("Almaty, Kazakhstan") == {"KZ"} and r("NYC") == {"US"} and r("SF Bay Area") == {"US"} and r("Washington, D.C.") == {"US"}
    assert r("Belgrade") == {"RS"} and r("Espoo") == {"FI"} and r("Schweiz") == {"CH"} and r("Ciudad de México") == {"MX"}
    # A town before a written-out state is in that state.
    assert r("Belgrade, Montana") == {"US"} and r("Athens, Ohio") == {"US"} and r("Cambridge, Massachusetts") == {"US"}
    assert r("Birmingham, Alabama, United States") == {"US"} and r("Vienna, Virginia") == {"US"} and r("Paris, Texas") == {"US"}
    # A flat list of places is still a list, and a named country is never dropped.
    assert r("Berlin, London, New York") == {"DE", "GB", "US"} and r("Palo Alto, Toronto, Virginia, Miami") == {"CA", "US"}
    assert r("Canada, Utah, New York") == {"CA", "US"} and r("Paris, France") == {"FR"} and r("London, United Kingdom") == {"GB"}
    assert r("Remote") == set() and r("Atlanta, Georgia") == {"US"} and r("Tbilisi, Georgia") == set()   # Georgia stays unguessed
    assert r("Hyderabad, Telangana") == {"IN"} and r("Indianapolis, IN") == {"US"} and r("Toronto, Ontario") == {"CA"}
    a = r("London")
    a.add("XX")
    assert r("London") == {"GB"}                       # callers get their own copy of a cached answer


def test_senior_and_director_titles_follow_years_of_experience():
    def kept(title, years):
        s = feed.settings_from_dashboard({"homeCountry": "CA", "places": "Canada", "targetRoles": ["marketing", "engineer"], "yearsExperience": years})
        return gates.gate_seniority(_job(title=title), s).passed
    assert not kept("Senior Marketing Manager", 2) and kept("Senior Marketing Manager", 3)
    assert not kept("Director of Marketing", 2) and not kept("Head of Event Marketing", 5) and not kept("VP, Engineering", 7)
    assert kept("Director of Marketing", 8) and kept("Principal Engineer", 10)
    assert kept("Marketing Manager", 2) and kept("Marketing Coordinator", 0)
    assert not kept("Marketing Intern", 4)             # entry titles are still hidden from 3 years on
    # Without a stated number of years the older rule still applies.
    s = feed.settings_from_dashboard({"targetRoles": ["engineer"], "maxRequiredYears": 1})
    assert not gates.gate_seniority(_job(title="Senior Engineer"), s).passed
    s = feed.settings_from_dashboard({"targetRoles": ["engineer"], "maxRequiredYears": 4})
    assert gates.gate_seniority(_job(title="Senior Engineer"), s).passed


def test_sponsorship_counts_for_remote_roles_in_your_country_too():
    now = datetime.now(timezone.utc)
    s = feed.settings_from_dashboard({"homeCountry": "GB", "places": "United Kingdom", "targetRoles": ["backend"], "needsSponsorship": True})

    def visa(location, mode, facts):
        d = gates.evaluate(_job(location=location, mode=mode, raw={"facts": dict({"loc": "abroad"}, **facts)}), s, now)
        return [c for c in d.checks if c.gate == "Visa sponsorship"]
    no = {"visa": {"status": "no", "quote": "We are unable to sponsor visas."}}
    assert not visa("Remote - United Kingdom", "remote", no)[0].passed      # was let through: only office roles were checked
    assert not visa("London, United Kingdom", "hybrid", no)[0].passed
    assert not visa("Remote - UK", "remote", {"visa": {"ukRegister": {"listed": False}}})[0].passed
    assert visa("Remote - UK", "remote", {"visa": {"ukRegister": {"listed": True, "name": "Acme Ltd"}}})[0].passed
    assert visa("Remote, Worldwide", "remote", no) == []                     # a role open to the world is not a visa question


def test_someone_abroad_sees_local_roles_and_known_sponsors_first():
    now = datetime.now(timezone.utc)
    posted = now.isoformat()

    def rec(i, location, mode, visa=None):
        return {"id": f"r{i}", "company": f"Co {i}", "title": f"Backend Engineer {i}", "url": f"https://jobs.example.com/{i}", "source": "Greenhouse",
                "location": location, "workMode": mode, "postedAt": posted, "summary": "Build APIs.", "via": "careers",
                "facts": {"loc": "abroad", "visa": visa or {}}}
    records = [rec(1, "Remote", "remote"), rec(2, "Remote, Worldwide", "remote"), rec(3, "London, United Kingdom", "hybrid"),
               rec(4, "Leeds, United Kingdom", "onsite", {"ukRegister": {"listed": True, "name": "Co 4 Ltd"}}),
               rec(5, "Remote - United Kingdom", "remote", {"status": "offers", "quote": "We sponsor Skilled Worker visas."})]
    s = feed.settings_from_dashboard({"homeCountry": "GB", "places": "United Kingdom", "targetRoles": ["backend"], "needsSponsorship": True})
    order = [i for i, _ in feed.match(iter(records), s, [], None, now)["kept"]]
    assert order[-2:] == ["r2", "r1"]                  # worldwide remote, then the one that doesn't say who can apply
    assert set(order[:2]) == {"r4", "r5"} and order[2] == "r3"   # employers with a sponsoring record lead the local roles
    s.needs_sponsorship = False
    assert [i for i, _ in feed.match(iter(records), s, [], None, now)["kept"]][-2:] == ["r2", "r1"]
    # India keeps its own order: remote worldwide first.
    india = feed.settings_from_dashboard({"targetRoles": ["backend"]})
    first = feed.match(iter([rec(9, "Bengaluru, India", "hybrid"), rec(8, "Remote, Worldwide", "remote")]), india, [], None, now)["kept"]
    assert [i for i, _ in first][0] == "r8"


def test_match_reads_any_iterable_once():
    now = datetime.now(timezone.utc)
    s = feed.settings_from_dashboard({"targetRoles": ["backend"]})

    def gen():
        for i in range(5):
            yield {"id": f"g{i}", "company": f"Co {i}", "title": "Backend Engineer", "url": f"https://jobs.example.com/g{i}", "source": "Greenhouse",
                   "location": "Remote, Worldwide", "workMode": "remote", "postedAt": now.isoformat(), "summary": "Build APIs. Freshers welcome.",
                   "via": "careers", "facts": {}}
    res = feed.match(gen(), s, [], None, now, max_kept=3)
    assert res["feedRecords"] == 5 and len(res["kept"]) == 3 and res["more"] is True
    assert feed.match(gen(), s, [], None, now, max_kept=10)["more"] is False
    # A known role found through the feed is "gone" only if its address is no longer listed anywhere in it.
    known = [("g1", {"stage": "found", "foundVia": "careers-feed", "url": "https://jobs.example.com/g1/", "company": "Co 1", "title": "Backend Engineer", "postedAt": now.isoformat()}),
             ("zz", {"stage": "found", "foundVia": "careers-feed", "url": "https://jobs.example.com/closed", "company": "Co Z", "title": "Backend Engineer", "postedAt": now.isoformat()})]
    assert feed.match(gen(), s, known, {"erroredCompanies": []}, now)["gone"] == ["zz"]
    # When only changed roles are read, the full list of addresses says what is still listed.
    part = feed.match(iter([]), s, known, {"erroredCompanies": []}, now, feed_urls=["https://jobs.example.com/g1"])
    assert part["gone"] == ["zz"] and part["feedRecords"] == 0


def test_a_perk_is_not_read_as_open_worldwide():
    from propelo import extract
    perk = 'Take advantage of up to 2 months working outside of your country of employment over a rolling 12-month period with our "Work from Anywhere" policy.'
    reach = "We have a global presence and many of our roles offer the option to work remotely."
    assert extract.remote_scope("London", perk).scope == "" and extract.remote_scope("Melbourne, Australia; Remote", reach).scope == ""
    assert extract.remote_scope("London", "This is a fully remote role and we hire from anywhere in the world.").scope == "worldwide"
    assert extract.remote_scope("Remote - Worldwide", perk).scope == "worldwide"       # the location itself still counts
    # A feed written before this fix stored the wrong answer: the filter drops it when it reads the sentence.
    india = feed.settings_from_dashboard({"targetRoles": ["backend"]})
    old = {"loc": "remote-worldwide", "scope": "worldwide", "scopeEligible": True, "scopeQuote": perk}
    chk, region = gates.gate_location(_job(location="London", raw={"facts": old}), india)
    assert not chk.passed and "placed in London" in chk.value
    good = dict(old, scopeQuote="We hire from anywhere in the world.")
    assert gates.gate_location(_job(location="London", raw={"facts": good}), india) [1] == "remote-global"


def test_unclear_remote_roles_come_after_roles_known_to_be_open_in_india_too():
    now = datetime.now(timezone.utc)

    def rec(i, location, facts):
        return {"id": f"u{i}", "company": f"Co {i}", "title": f"Backend Engineer {i}", "url": f"https://jobs.example.com/u{i}", "source": "Greenhouse",
                "location": location, "workMode": "remote", "postedAt": now.isoformat(), "summary": "Build APIs. Freshers welcome.", "via": "careers", "facts": facts}
    india = feed.settings_from_dashboard({"targetRoles": ["backend"]})
    kept = feed.match(iter([rec(1, "Remote", {}), rec(2, "Remote, Worldwide", {})]), india, [], None, now)["kept"]
    assert [i for i, _ in kept] == ["u2", "u1"] and {d["region"] for _, d in kept} == {"remote-global"}


def test_someone_in_india_looking_abroad_gets_roles_in_the_countries_they_chose():
    doc = {"homeCountry": "IN", "workAbroad": True, "places": "United Kingdom, Germany", "targetRoles": ["backend"], "needsSponsorship": True}
    s = feed.settings_from_dashboard(doc)
    assert s.location.by_places and s.location.elsewhere and s.location.home == "IN"
    # An office role in a chosen country is kept; one in a country they did not choose is not.
    chk, region = gates.gate_location(_job(location="London, United Kingdom", mode="onsite"), s)
    assert chk.passed and region == "local"
    assert not gates.gate_location(_job(location="Toronto, Canada", mode="onsite"), s)[0].passed
    # Remote roles open to India stay; remote roles for another country only do not.
    assert gates.gate_location(_job(location="Remote - India"), s)[1] == "remote-local"
    assert not gates.gate_location(_job(location="Remote - United States"), s)[0].passed
    # A posting that refuses sponsorship rules out the office role abroad, but not remote work from India.
    refuses = "We are unable to sponsor visas for this role."
    out = gates.gate_sponsorship(_job(location="Berlin, Germany", mode="onsite", desc=refuses), "local", s)
    assert out is not None and not out.passed
    assert gates.gate_sponsorship(_job(location="Remote - India", desc=refuses), "remote-local", s) is None


def test_india_rules_stay_until_a_place_abroad_is_named():
    s = feed.settings_from_dashboard({"homeCountry": "IN", "workAbroad": True, "places": "", "targetRoles": ["backend"]})
    assert not s.location.by_places
    s = feed.settings_from_dashboard({"homeCountry": "IN", "places": "United Kingdom", "targetRoles": ["backend"]})
    assert not s.location.by_places


def test_arbeitnow_places_keep_their_own_country():
    from propelo.sources.aggregators import arbeitnow_location
    assert arbeitnow_location("Ivry-sur-Seine", "https://www.arbeitnow.fr/jobs/companies/x/data-analyst-1") == "Ivry-sur-Seine, France"
    assert arbeitnow_location("paris, Île-de-France, France", "https://www.arbeitnow.fr/jobs/x") == "paris, Île-de-France, France"
    assert arbeitnow_location("München", "https://www.arbeitnow.com/jobs/x") == "München, Germany"
    assert arbeitnow_location("Berlin", "https://www.arbeitnow.com/jobs/x") == "Berlin"
    assert arbeitnow_location("", "https://www.arbeitnow.com/jobs/x") == "Germany"
    assert arbeitnow_location("Somewhere", "https://example.com/jobs/x") == "Somewhere"


def test_pay_below_irish_or_dutch_permit_minimums_is_skipped_for_someone_who_needs_a_visa():
    doc = {"homeCountry": "IN", "workAbroad": True, "places": "Ireland, Netherlands", "targetRoles": ["backend"], "needsSponsorship": True}
    s = feed.settings_from_dashboard(doc)
    low_ie = gates.gate_sponsorship(_job(location="Dublin, Ireland", mode="onsite", desc="Salary €30,000 a year."), "local", s)
    assert low_ie is not None and not low_ie.passed and "Irish employment permit" in low_ie.value and "€30,000" in low_ie.quote
    ok_ie = gates.gate_sponsorship(_job(location="Dublin, Ireland", mode="onsite", desc="Salary €45,000 a year."), "local", s)
    assert ok_ie.passed and "Critical Skills" in ok_ie.value
    low_nl = gates.gate_sponsorship(_job(location="Amsterdam, Netherlands", mode="onsite", desc="€2.800 bruto per maand."), "local", s)
    assert low_nl is not None and not low_nl.passed and "highly skilled migrant" in low_nl.value
    # An annual Dutch figure may include holiday pay, so it is shown but never used to skip.
    year_nl = gates.gate_sponsorship(_job(location="Amsterdam, Netherlands", mode="onsite", desc="€30,000 per year."), "local", s)
    assert year_nl.passed
