"""More openings across countries: Adzuna and USAJOBS (when their keys are set), on-site Arbeitnow roles,
company discovery beyond India when the scan covers the world, and a cap on the published feed."""

from propelo import discover, scan
from propelo.sources import national


def adzuna_page(cc, n=2):
    return {"results": [{"id": f"{cc}{i}", "title": "<strong>Staff Nurse</strong>" if i == 0 else "Backend Engineer (Remote)",
                         "redirect_url": f"https://www.adzuna.example/land/{cc}{i}", "company": {"display_name": "Apollo Clinics" if i == 0 else "Acme"},
                         "location": {"display_name": "Bangalore, Karnataka" if cc == "in" else "London"}, "created": "2026-11-15T10:00:00Z",
                         "description": "Care for patients on the ward." if i == 0 else "Build APIs. Fully remote, work from home.",
                         "salary_min": 300000, "salary_max": 450000} for i in range(n)]}


def test_adzuna_needs_keys_and_covers_india_first(monkeypatch):
    calls = []
    assert national.adzuna(fetch=lambda u: calls.append(u)) == [] and not calls  # no keys, no calls
    monkeypatch.setenv("ADZUNA_APP_ID", "id")
    monkeypatch.setenv("ADZUNA_APP_KEY", "key")
    monkeypatch.setenv("ADZUNA_COUNTRIES", "in,gb,xx")
    monkeypatch.setenv("ADZUNA_PAGES", "2")

    def fetch(url):
        calls.append(url)
        return adzuna_page(url.split("/jobs/")[1][:2])
    jobs = national.adzuna(fetch=fetch)
    assert [u.split("/jobs/")[1].split("?")[0] for u in calls] == ["in/search/1", "gb/search/1"]  # short pages end a country; xx isn't supported
    nurse = jobs[0]
    assert nurse.title == "Staff Nurse" and nurse.location == "Bangalore, Karnataka, India" and nurse.salary_text == "₹300,000 - ₹450,000 /year"
    assert jobs[1].work_mode == "remote" and jobs[3].location == "London, United Kingdom" and jobs[3].salary_text.startswith("£")
    assert all(j.source == "Adzuna" and j.url.startswith("https://") for j in jobs)


def test_usajobs(monkeypatch):
    monkeypatch.setenv("USAJOBS_KEY", "k")
    monkeypatch.setenv("USAJOBS_EMAIL", "ops@example.com")
    seen = {}

    def fetch(url, headers=None):
        seen.update(headers or {})
        return {"SearchResult": {"SearchResultItems": [{"MatchedObjectDescriptor": {
            "PositionTitle": "IT Specialist", "OrganizationName": "Department of Energy", "PositionLocationDisplay": "Denver, Colorado",
            "PositionURI": "https://www.usajobs.gov/job/1", "PublicationStartDate": "2026-11-14", "PositionID": "DOE-1",
            "PositionRemuneration": [{"MinimumRange": "90000", "MaximumRange": "120000", "RateIntervalCode": "PA"}],
            "UserArea": {"Details": {"JobSummary": "Support systems."}}}}]}}
    jobs = national.usajobs(fetch=fetch)
    assert seen == {"Host": "data.usajobs.gov", "User-Agent": "ops@example.com", "Authorization-Key": "k"}
    j = jobs[0]
    assert (j.title, j.company, j.location, j.salary_text) == ("IT Specialist", "Department of Energy", "Denver, Colorado, United States", "$90,000 - $120,000 /year")


def test_registered_and_polled_once_a_day():
    from propelo.sources.aggregators import AGGREGATORS, MIN_HOURS
    assert "adzuna" in AGGREGATORS and "usajobs" in AGGREGATORS and MIN_HOURS["adzuna"] == 24


def test_discovery_keeps_developed_country_boards_when_world(monkeypatch):
    co = {"name": "Northwind", "category": "deep"}
    london = {"locations": ["London, United Kingdom"], "titles": ["Account Executive"]}
    monkeypatch.setattr(scan, "ONSITE_WORLD", False)
    assert discover.accept(co, london)[0] is False
    monkeypatch.setattr(scan, "ONSITE_WORLD", True)
    assert discover.accept(co, london) == (True, "deep:1")
    assert discover.accept(co, {"locations": ["Lagos, Nigeria"], "titles": ["Account Executive"]})[0] is False  # outside the focus list


def test_feed_cap_keeps_india_and_remote_first():
    recs = [{"id": str(i), "geo": "abroad", "workMode": "", "postedAt": f"2026-11-{10 + i % 5:02d}T00:00:00Z"} for i in range(10)]
    recs += [{"id": "in", "geo": "india", "workMode": "", "postedAt": "2026-10-01T00:00:00Z"},
             {"id": "rm", "geo": "", "workMode": "remote", "postedAt": "2026-10-02T00:00:00Z"}]
    kept, trimmed = scan.cap_feed(recs, limit=5)
    assert trimmed == 7 and {"in", "rm"} <= {r["id"] for r in kept}
    assert scan.cap_feed(recs, limit=100) == (recs, 0)
