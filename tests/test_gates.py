from datetime import datetime, timedelta, timezone

from propelo.gates import evaluate
from propelo.models import Job
from propelo.settings import Settings

NOW = datetime(2026, 10, 9, 6, 0, tzinfo=timezone.utc)
S = Settings()  # defaults: <=1 year, 25 days, 7 LPA floor, south India any / rest remote / abroad remote


def job(**kw):
    base = dict(company="Example Labs", title="AI Engineer", url="https://example.com/j/1", source="test",
                posted_at=(NOW - timedelta(days=2)).isoformat(), description="1 year of experience with Python and LLM APIs.")
    base.update(kw)
    return Job(**base)


def failed(d):
    return [c.gate for c in d.checks if not c.passed]


def test_south_india_onsite_kept():
    d = evaluate(job(location="Chennai", work_mode="onsite"), S, NOW)
    assert d.kept and d.region == "south-india"


def test_rest_of_india_onsite_skipped():
    d = evaluate(job(location="Pune", work_mode="onsite"), S, NOW)
    assert not d.kept and failed(d) == ["Location"]


def test_rest_of_india_remote_kept():
    d = evaluate(job(location="Pune, India", work_mode="remote"), S, NOW)
    assert d.kept and d.region == "remote-india"


def test_multi_city_with_bengaluru_kept():
    d = evaluate(job(location="Bengaluru, Delhi, Gurgaon or Mumbai"), S, NOW)
    assert d.kept and d.region == "south-india"


def test_remote_worldwide_is_top_priority_region():
    d = evaluate(job(location="Remote - Anywhere", work_mode="remote"), S, NOW)
    assert d.kept and d.region == "remote-global"


def test_remote_us_only_skipped():
    d = evaluate(job(location="Remote (US only)", work_mode="remote"), S, NOW)
    assert not d.kept and "Location" in failed(d)


def test_experience_gate_uses_description():
    d = evaluate(job(description="You bring 2+ years of software development experience."), S, NOW)
    assert not d.kept and failed(d) == ["Experience"]
    exp = next(c for c in d.checks if c.gate == "Experience")
    assert "2+ years" in exp.quote


def test_senior_title_skipped():
    d = evaluate(job(title="Senior AI Engineer"), S, NOW)
    assert "Seniority" in failed(d)


def test_old_posting_skipped_and_fresh_is_priority():
    old = evaluate(job(posted_at=(NOW - timedelta(days=30)).isoformat()), S, NOW)
    assert "Posted" in failed(old)
    fresh = evaluate(job(location="Hyderabad", posted_at=(NOW - timedelta(hours=10)).isoformat()), S, NOW)
    assert fresh.kept and fresh.priority


def test_pay_floor_uses_top_of_range():
    low = evaluate(job(location="Bengaluru", salary_text="₹ 3,60,000 - 6,00,000 /year"), S, NOW)
    assert failed(low) == ["Pay"]
    ok = evaluate(job(location="Bengaluru", salary_text="₹ 3,00,000 - 8,00,000 /year"), S, NOW)
    assert ok.kept


def test_closed_and_deadline():
    d = evaluate(job(location="Bengaluru", description="This job is closed."), S, NOW)
    assert "Open" in failed(d)
    d = evaluate(job(location="Bengaluru", apply_by="2026-10-01"), S, NOW)
    assert "Open" in failed(d)


def test_non_target_role_skipped():
    d = evaluate(job(title="Field Sales Executive", location="Bengaluru"), S, NOW)
    assert "Role" in failed(d)


def test_role_keywords_match_plurals():
    from propelo.gates import gate_role
    from propelo.models import Job
    from propelo.settings import Settings
    assert gate_role(Job(company="X", title="Full-stack Engineer - Creative Agents", url="", source="test"), Settings()).passed
    assert not gate_role(Job(company="X", title="Account Executive", url="", source="test"), Settings()).passed


def test_remote_country_in_title():
    from propelo.gates import gate_location
    from propelo.models import Job
    from propelo.settings import Settings
    for title in ("Product Engineer (Remote/US)", "QA Analyst (Mexico, Remote)", "Product Engineers in Canada (Remote)"):
        c, region = gate_location(Job(company="X", title=title, url="", source="t", location="Remote", work_mode="remote"), Settings())
        assert not c.passed and region == "", title
    c, region = gate_location(Job(company="X", title="Backend Engineer (Remote, India)", url="", source="t", location="Remote", work_mode="remote"), Settings())
    assert c.passed and region == "remote-india"


def test_company_age_is_not_an_experience_ask():
    from propelo import extract
    r = extract.extract_experience("PayPal has been revolutionizing commerce globally for more than 25 years. You need 2+ years of experience in Java.")
    assert r.min_years == 2
    assert extract.extract_experience("With 2200+ employees and continued investments over 25 years in India, ZEISS is growing.").min_years is None
    assert extract.extract_experience("5+ years of hands-on experience; the company has been around since 1999.").min_years == 5


def test_engineering_managers_are_senior_but_product_managers_are_not():
    from propelo import extract
    assert extract.title_seniority("Manager, Software Engineer") == "senior"
    assert extract.title_seniority("Engineering Manager - Payments") == "senior"
    assert extract.title_seniority("Associate Product Manager") == "junior"
    assert extract.title_seniority("Relationship Manager") == ""


def test_remote_role_placed_in_another_country_is_not_offered_in_india():
    from propelo.gates import gate_location
    from propelo.models import Job
    from propelo.settings import Settings
    s = Settings()
    for loc in ("Remote - Berlin", "Kyiv, Kyiv city, Ukraine", "Poland"):
        chk, _ = gate_location(Job(source="greenhouse", company="X", title="Software Engineer", url="https://x.example/1", location=loc, work_mode="remote", description="Join our team."), s)
        assert not chk.passed, loc
    ok, region = gate_location(Job(source="greenhouse", company="X", title="Software Engineer", url="https://x.example/2", location="Berlin, Germany", work_mode="remote", description="This role is fully remote and open to candidates anywhere in the world."), s)
    assert ok.passed and region == "remote-global"
    ok, region = gate_location(Job(source="greenhouse", company="X", title="Software Engineer", url="https://x.example/3", location="Remote - India", work_mode="remote", description=""), s)
    assert ok.passed and region == "remote-india"


def test_real_company_names():
    from propelo.company_names import display
    assert display("Hpe") == "HPE" and display("Cat (CaterpillarCareers)") == "Caterpillar" and display("Equifax (External)") == "Equifax"
    assert display("LSEG (London Stock Exchange Group)") == "LSEG (London Stock Exchange Group)" and display("UiPath") == "UiPath"
