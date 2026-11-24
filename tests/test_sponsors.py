"""Visa sponsorship facts: the posting's words, the UK register and the salary floors."""

from datetime import date

from propelo import sponsors
from propelo.gates import evaluate
from propelo.models import Job
from propelo.scan import days_open
from propelo.settings import Settings


def test_posting_says_it_sponsors():
    for text in ("Visa sponsorship is available for this role.", "We can sponsor Skilled Worker visas.",
                 "We offer visa sponsorship and relocation.", "H-1B sponsorship available.",
                 "Relocation and visa support provided."):
        v = sponsors.sponsorship(text)
        assert v["status"] == "offers", text
        assert v["quote"]


def test_posting_says_it_cannot_sponsor():
    for text in ("We are unable to sponsor visas.", "We do not offer visa sponsorship.",
                 "Candidates must have the right to work without sponsorship.",
                 "Sponsorship is not available for this role.", "No visa sponsorship."):
        assert sponsors.sponsorship(text)["status"] == "no", text


def test_no_wins_and_silence_is_empty():
    assert sponsors.sponsorship("Sponsorship is available for senior roles. This role: we cannot sponsor.")["status"] == "no"
    assert sponsors.sponsorship("Great team, free lunch.") == {}


ROWS = [
    {"Organisation Name": "Monzo Bank Ltd", "Town/City": "London", "Type & Rating": "Worker (A rating)", "Route": "Skilled Worker"},
    {"Organisation Name": "Wise Payments Limited", "Town/City": "London", "Type & Rating": "Worker (A rating)", "Route": "Skilled Worker"},
    {"Organisation Name": "Deliveroo", "Town/City": "London", "Type & Rating": "Worker (A rating)", "Route": "Skilled Worker"},
    {"Organisation Name": "Acme Farms", "Town/City": "Kent", "Type & Rating": "Temporary Worker", "Route": "Seasonal Worker"},
    {"Organisation Name": "Data Systems Ltd", "Town/City": "Leeds", "Type & Rating": "Worker (A rating)", "Route": "Skilled Worker"},
    {"Organisation Name": "Data Partners Ltd", "Town/City": "Leeds", "Type & Rating": "Worker (A rating)", "Route": "Skilled Worker"},
]


def test_register_matching():
    reg = sponsors.UkRegister(ROWS)
    assert len(reg) == 5  # the seasonal-worker row is not a Skilled Worker sponsor
    assert reg.match("Deliveroo")["match"] == "exact"
    assert reg.match("Monzo Bank")["name"] == "Monzo Bank Ltd"
    assert reg.match("Monzo")["match"] == "prefix"  # one register name starts with it
    assert reg.match("Wise")["name"] == "Wise Payments Limited"
    assert reg.match("Data") is None  # too short, and two register names start with it
    assert reg.match("Acme Farms") is None
    assert reg.match("Unknown Startup") is None


def test_register_from_csv(tmp_path):
    p = tmp_path / "uk.csv"
    p.write_text("﻿Organisation Name,Town/City,County,Type & Rating,Route\nDeliveroo,London,,Worker (A rating),Skilled Worker\n", encoding="utf-8")
    assert sponsors.UkRegister.from_csv(p).match("Deliveroo")
    assert len(sponsors.UkRegister.from_csv(tmp_path / "missing.csv")) == 0


def test_uk_salary_line():
    assert sponsors.uk_salary_line("Salary: £45,000 - £55,000 per annum")["status"] == "general"
    assert sponsors.uk_salary_line("£35k + benefits")["status"] == "new-entrant"
    assert sponsors.uk_salary_line("£28,000 a year")["status"] == "below"
    assert sponsors.uk_salary_line("£350 per day") == {}
    assert sponsors.uk_salary_line("No salary given") == {}


def test_visa_facts_and_label():
    reg = sponsors.UkRegister(ROWS)
    v = sponsors.visa_facts("Deliveroo", "London, UK", "We offer visa sponsorship. Salary £40,000.", "", reg)
    assert v["status"] == "offers" and v["uk"] and v["ukRegister"]["listed"] and v["ukSalary"]["status"] == "new-entrant"
    assert "on the UK sponsor register" in sponsors.label(v)
    v = sponsors.visa_facts("Tiny Co", "London", "Great role.", "", reg)
    assert v["ukRegister"] == {"listed": False}
    assert sponsors.visa_facts("Tiny Co", "Berlin, Germany", "Great role.", "", reg) == {}


def test_days_open():
    today = date(2026, 11, 17)
    assert days_open("2026-10-20T10:00:00Z", "2026-11-01", today) == 28
    assert days_open("", "2026-11-10", today) == 7
    assert days_open(None, "", today) is None
    assert days_open("2019-04-01T00:00:00Z", "2026-10-21", today) == 27  # an old posting date is not trusted


def _job(desc, location="London, UK"):
    return Job(company="Tiny Co", title="Software Engineer", url="https://x.example/1", source="greenhouse",
               location=location, description=desc, work_mode="onsite", posted_at="2026-11-15T00:00:00Z")


def _settings(needs: bool) -> Settings:
    s = Settings()
    s.needs_sponsorship = needs
    s.location.home = "IN"
    s.location.abroad = True
    s.salary_floor_lpa = None
    s.max_required_years = 5
    return s


def test_gate_blocks_no_sponsorship_only_when_needed():
    j = _job("Build things in Python. We are unable to sponsor visas.")
    d = evaluate(j, _settings(True), now=__import__("datetime").datetime(2026, 11, 17, tzinfo=__import__("datetime").timezone.utc))
    visa = [c for c in d.checks if c.gate in ("Visa sponsorship", "Work authorization") and not c.passed]
    assert visa and visa[0].quote
    d2 = evaluate(_job("Build things in Python. Visa sponsorship is available."), _settings(True),
                  now=__import__("datetime").datetime(2026, 11, 17, tzinfo=__import__("datetime").timezone.utc))
    vs = [c for c in d2.checks if c.gate == "Visa sponsorship"]
    assert vs and vs[0].passed and "sponsors" in vs[0].value
    d3 = evaluate(_job("Build things in Python. Visa sponsorship is available."), _settings(False),
                  now=__import__("datetime").datetime(2026, 11, 17, tzinfo=__import__("datetime").timezone.utc))
    assert not [c for c in d3.checks if c.gate == "Visa sponsorship"]


def test_gate_for_someone_on_a_uk_visa_uses_the_register():
    from datetime import datetime, timezone
    reg = sponsors.UkRegister(ROWS)
    s = _settings(True)
    s.location.home = "GB"
    s.location.places = ["London"]
    now = datetime(2026, 11, 17, tzinfo=timezone.utc)
    for company, ok in (("Deliveroo", True), ("Tiny Co", False)):
        j = _job("Build things in Python.")
        j.company = company
        facts = {"loc": "abroad", "visa": sponsors.visa_facts(company, j.location, j.description, "", reg)}
        j.raw = {"facts": facts}
        d = evaluate(j, s, now=now)
        vs = [c for c in d.checks if c.gate == "Visa sponsorship"]
        assert vs and vs[0].passed is ok, (company, [c.to_dict() for c in d.checks])


def test_euro_salaries_monthly_and_yearly():
    assert sponsors.euro_salary("Salary: €3.500 - €4.500 bruto per maand") == {"amount": 4500, "per": "month", "quote": "Salary: €3.500 - €4.500 bruto per maand"}
    assert sponsors.euro_salary("€45,000 - €55,000 per year")["amount"] == 55000
    assert sponsors.euro_salary("EUR 38k")["amount"] == 38000
    assert sponsors.euro_salary("€14.50 per hour") == {} and sponsors.euro_salary("no pay given") == {}


def test_irish_permit_minimums():
    line = sponsors.ie_salary_line
    assert line("€45,000 - €55,000 per year")["status"] == "csep"
    assert line("€38,000 a year")["status"] == "csep-graduate"
    assert line("€36,700 per annum")["status"] == "gep"
    assert line("Salary €35,000")["status"] == "gep-graduate"
    assert line("€30,000")["status"] == "below"


def test_dutch_highly_skilled_migrant_criteria():
    line = sponsors.nl_salary_line
    assert line("€6.000 bruto per maand")["status"] == "30plus"
    assert line("€3.500 - €4.500 per month")["status"] == "under30"
    assert line("€3.200 per maand")["status"] == "reduced"
    low = line("€2.800,- per maand")
    assert low["status"] == "below" and not low["fromYear"]
    year = line("€48,000 per year")
    assert year["status"] == "reduced" and year["amount"] == 4000 and year["fromYear"]


def test_visa_facts_and_label_for_ireland_and_the_netherlands():
    ie = sponsors.visa_facts("Acme", "Dublin, Ireland", "We pay €45,000 a year.")
    assert ie["ieSalary"]["status"] == "csep" and "Critical Skills" in sponsors.label(ie)
    nl = sponsors.visa_facts("Acme", "Amsterdam, Netherlands", "", "€3.500 - €4.500 per month")
    assert nl["nlSalary"]["status"] == "under30" and "under-30s" in sponsors.label(nl)
    assert "ieSalary" not in sponsors.visa_facts("Acme", "London, United Kingdom", "€45,000")
