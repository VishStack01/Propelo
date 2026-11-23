"""Propelo for every role and every level: job families beyond tech, typed roles, years of experience,
and the free "Is this job real?" check shared by the app and the website."""

import json
import re
from datetime import datetime, timezone
from pathlib import Path

import pytest

from propelo import feed, scamcheck, tags
from propelo.gates import evaluate
from propelo.models import Job
from propelo.scan import wanted_title

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 11, 16, tzinfo=timezone.utc)


@pytest.mark.parametrize("title,family", [
    ("Staff Nurse", "Healthcare"), ("Hospital Pharmacist", "Healthcare"), ("PGT Mathematics Teacher", "Education"),
    ("School Counsellor", "Education"), ("Civil Site Engineer", "Engineering & Trades"), ("Electrician", "Engineering & Trades"),
    ("Legal Counsel", "Legal"), ("Store Manager", "Retail & Hospitality"), ("Chef de Partie", "Retail & Hospitality"),
    ("Video Editor", "Media & Writing"), ("Telecaller", "Operations & People"), ("Delivery Executive", "Operations & People"),
    ("Accounts Executive", "Finance & Strategy"),
    # Tech titles that mention another field stay in the tech families.
    ("Senior Software Engineer, Backend (Retail)", "Software Engineering"), ("Principal Engineer", "Software Engineering"),
    ("Developer Advocate", "Software Engineering"), ("ASIC Design Engineer", "Software Engineering"),
    ("Machine Learning Engineer, Healthcare", "AI & Data"), ("Software Engineer - School Platform", "Software Engineering"),
])
def test_families_cover_every_field(title, family):
    assert tags.family(title) == family


def test_scan_keeps_every_named_role():
    for t in ("Staff Nurse", "Civil Engineer", "Primary Teacher", "Store Manager", "Backend Engineer", "Account Executive"):
        assert wanted_title(t), t
    assert not wanted_title("Volunteer, Weekend Events")  # nothing we can name a family for


def test_dashboard_lists_every_family():
    for name in ("dashboard/app.html", "propelo/site_app.html"):
        html = (ROOT / name).read_text(encoding="utf-8")
        js = json.loads(re.search(r"const FAMILIES = (\[.*?\]);", html).group(1).replace("'", '"'))
        assert set(js) == set(tags.FAMILIES), name


def _job(title, text="", **kw):
    return Job(company="Acme", title=title, source="test", url="https://acme.example/jobs/1", location=kw.get("location", "Bengaluru, India"),
               work_mode=kw.get("mode", "onsite"), description=text, posted_at="2026-11-14T00:00:00Z")


def test_typed_roles_decide_on_their_own():
    s = feed.settings_from_dashboard({"targetRoles": ["nurse"], "locations": ["South India (any work mode)"]})
    assert evaluate(_job("Staff Nurse"), s, NOW).kept
    assert not evaluate(_job("Backend Engineer"), s, NOW).kept  # used to pass: the tech keywords were added to typed roles


def test_years_of_experience_opens_senior_roles_and_hides_entry_ones():
    s = feed.settings_from_dashboard({"yearsExperience": 8, "families": ["Software Engineering"], "locations": ["South India (any work mode)"]})
    assert s.max_required_years == 10 and s.allow_internships is False
    assert evaluate(_job("Senior Backend Engineer", "You have 8+ years of experience."), s, NOW).kept
    assert not evaluate(_job("Software Engineering Intern"), s, NOW).kept
    d = evaluate(_job("Graduate Engineer Trainee"), s, NOW)
    assert not d.kept and any(c.gate == "Seniority" and "entry-level" in c.value for c in d.checks)
    fresher = feed.settings_from_dashboard({"yearsExperience": 0, "families": ["Software Engineering"], "locations": ["South India (any work mode)"]})
    assert fresher.max_required_years == 1 and fresher.allow_internships
    assert not evaluate(_job("Senior Backend Engineer", "You have 8+ years of experience."), fresher, NOW).kept


def test_old_settings_without_years_still_work():
    s = feed.settings_from_dashboard({"maxRequiredYears": 1, "experienceLevels": ["Fresher", "1+ years"]})
    assert s.max_required_years == 1 and s.experience_years is None


@pytest.mark.parametrize("text,rule", [
    ("Part time job: like YouTube videos and earn Rs 3000 daily, paid per task.", "task-scam"),
    ("Pay a refundable amount of Rs 2,000 for your ID card.", "refundable"),
    ("You must purchase a laptop from our vendor before you start.", "buy-kit"),
    ("Data entry work from home, daily payment.", "data-entry"),
])
def test_common_indian_scams(text, rule):
    assert rule in [r["id"] for r in scamcheck.check({"jd": text})["reasons"]]


def test_website_check_uses_the_same_rules():
    html = (ROOT / "website" / "check.html").read_text(encoding="utf-8")
    page = json.loads(re.search(r'<script id="scam-rules" type="application/json">(.*?)</script>', html, re.S).group(1).replace("<\\/", "</"))
    rules = json.loads((ROOT / "propelo" / "data" / "scam_rules.json").read_text(encoding="utf-8"))["rules"]
    assert page == rules
    assert "—" not in html  # no em dashes in website text


def test_staff_nurse_is_not_a_senior_title():
    from propelo.extract import title_seniority
    assert title_seniority("Staff Nurse") == "" and title_seniority("Staff Accountant") == ""
    assert title_seniority("Staff Software Engineer") == "senior"


def test_match_score_from_a_real_resume_for_any_field():
    from propelo import matchscore
    nurse = matchscore.resume_from_profile({"basics": {"headline": "Staff Nurse"}, "summary": "ICU nurse with BLS and ACLS.",
                                            "experience": [{"title": "Staff Nurse", "bullets": ["Patient care for 12 ICU beds", "Trained 6 new nurses"]}],
                                            "skills": ["Nursing", "Hindi"]})
    jd = ("Staff Nurse, ICU. Requirements: GNM or B.Sc Nursing, BLS and ACLS certification, 2+ years of ICU experience, "
          "patient care, good communication skills. Hindi preferred.")
    r = matchscore.score("Staff Nurse - ICU", jd, nurse, years=3)
    terms = {t["term"]: t for t in r["terms"]}
    assert terms["Patient care"]["status"] == "proven" and terms["BLS"]["status"] == "mentioned" and terms["Nursing"]["status"] == "listed"
    assert terms["Hindi"]["required"] is False and terms["Hindi"]["weight"] == 0.5  # "preferred" weighs half
    parts = {p["id"]: p for p in r["parts"]}
    assert parts["experience"]["points"] == 25 and parts["role"]["points"] == 7.5  # "staff" is skipped; "nurse" matches, "icu" not
    # the total is exactly the parts added up
    assert r["score"] == round(sum(p["points"] for p in r["parts"]))
    assert 60 <= r["score"] <= 90 and r["label"] in ("Good match", "Strong match")
    short = matchscore.score("Staff Nurse - ICU", jd, nurse, years=0)
    assert {p["id"]: p for p in short["parts"]}["experience"]["points"] == 0 and short["score"] == r["score"] - 25
    dev = matchscore.score("Backend Engineer", "We need Go, Kubernetes, PostgreSQL and Kafka experience to build payment APIs at scale.", nurse, years=3)
    assert dev["score"] < 45 and dev["label"] == "Low match" and set(dev["skills"]["missing"]) >= {"Kubernetes", "Kafka"}


def test_unmeasured_parts_are_left_out_not_guessed():
    from propelo import matchscore
    res = matchscore.resume_from_profile({"summary": "Accountant using Tally, GST and TDS.", "experience": [{"bullets": ["Reconciled 40 vendor accounts monthly"]}]})
    jd = "Accounts Executive. Tally, GST and TDS filing, bank reconciliation."
    r = matchscore.score("Accounts Executive", jd, res, years=None)  # no years stated, no titles to compare
    parts = {p["id"]: p for p in r["parts"]}
    assert parts["experience"]["points"] is None and parts["role"]["points"] is None and r["scaled"]
    assert r["score"] == round(100 * parts["skills"]["points"] / 60)  # skills alone, scaled to 100
    assert r["margin"] >= 10  # fewer things measured, wider margin
    assert matchscore.score("Clerk", "Some text without skills or years at all, just a long description of the office.", "", None)["score"] is None


def test_match_endpoint(cloud):
    c = cloud.user()
    jd = "Accounts Executive. Tally Prime, GST and TDS filing, bank reconciliation, accounts payable, advanced Excel. 1-3 years of experience."
    assert c.post("/api/agent/match", json={"title": "Accounts Executive", "jd": "short"}).status_code == 400
    r = c.post("/api/agent/match", json={"title": "Accounts Executive", "jd": jd}).json()
    assert r["needsResume"] is True
    c.put("/api/d/profile/resume", json={"summary": "Accountant handling GST, TDS and reconciliation in Tally.",
                                         "experience": [{"title": "Accounts Assistant", "bullets": ["Cleared accounts payable for 40 vendors in Excel"]}]})
    c.put("/api/d/settings/profile", json={"yearsExperience": 2})
    r = c.post("/api/agent/match", json={"title": "Accounts Executive", "jd": jd}).json()
    assert r["source"] == "your Propelo resume" and r["score"] >= 70 and r["risk"]["level"] == "ok"
    assert [p["id"] for p in r["parts"]] == ["skills", "experience", "role"] and r["margin"] > 0
