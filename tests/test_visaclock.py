"""The Visa-Clock: the date arithmetic, the rules file, and the dashboard's JavaScript copy giving the same answers."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from datetime import date
from pathlib import Path

import pytest

from propelo import feed, visaclock

ROOT = Path(__file__).resolve().parent.parent
TODAY = date(2026, 11, 25)


def test_every_status_is_complete_and_sourced():
    rules = visaclock.RULES
    assert [s["country"] for s in rules["statuses"] if s["country"]] and set(s["country"] for s in rules["statuses"]) <= {"", "US", "GB", "IE", "NL"}
    for s in rules["statuses"]:
        for key in s["fields"] + s["quick"] + list(s["labels"]):
            assert key in rules["fields"], (s["id"], key)
        assert set(s["quick"]) <= set(s["fields"]), s["id"]
        if s["clock"] != "none":
            assert s["sources"] and all(u.startswith("https://") for _, u in s["sources"]), s["id"]
            assert s["badge"] and s["work"] in rules["work"], s["id"]
        assert "—" not in json.dumps(s, ensure_ascii=False), s["id"]  # no em dashes in member-facing text


def test_no_status_set_means_no_clock():
    assert visaclock.clock(None, TODAY) is None
    assert visaclock.clock({"status": "made-up"}, TODAY) is None


def test_opt_counts_unemployment_from_the_start_date():
    c = visaclock.clock({"status": "us-opt", "optStart": "2026-10-26", "optEnd": "2027-10-25"}, TODAY)
    assert c["badge"]["days"] == 90 - 30 and c["badge"]["total"] == 90 and c["badge"]["tone"] == "ok"
    assert "26 Oct 2026" in c["badge"]["note"]
    assert [d["key"] for d in c["dates"]] == ["optStart", "optEnd"] and c["dates"][1]["days"] == 334


def test_opt_with_a_job_is_paused():
    c = visaclock.clock({"status": "us-opt", "optStart": "2026-06-01", "working": True, "daysUsed": 12, "asOf": "2026-09-01"}, TODAY)
    assert c["badge"]["days"] == 78 and c["badge"]["note"] == visaclock.RULES["notes"]["paused"]


def test_entered_days_keep_counting_from_the_day_they_were_entered():
    c = visaclock.clock({"status": "us-stem-opt", "daysUsed": "100", "asOf": "2026-11-05"}, TODAY)
    assert c["badge"]["days"] == 150 - 100 - 20 and c["badge"]["tone"] == "soon"


def test_unemployment_limit_reached_says_so():
    c = visaclock.clock({"status": "us-opt", "optStart": "2026-08-01"}, TODAY)
    assert c["badge"]["days"] == 0 and c["badge"]["tone"] == "over" and "DSO" in c["badge"]["note"]


def test_opt_that_has_not_started_shows_the_full_allowance():
    c = visaclock.clock({"status": "us-opt", "optStart": "2027-01-10"}, TODAY)
    assert c["badge"]["days"] == 90 and "10 Jan 2027" in c["badge"]["note"]


def test_f1_counts_to_the_program_end_then_the_grace_period():
    before = visaclock.clock({"status": "us-f1", "courseEnd": "2026-12-15"}, TODAY)
    assert before["badge"]["days"] == 20 and before["badge"]["tone"] == "urgent" and before["badge"]["total"] is None
    after = visaclock.clock({"status": "us-f1", "courseEnd": "2026-11-15"}, TODAY)
    assert after["badge"]["days"] == 50 and after["badge"]["total"] == 60 and "15 Nov 2026" in after["badge"]["note"]


def test_h1b_grace_period_ends_at_the_visa_end_date_when_sooner():
    c = visaclock.clock({"status": "us-h1b", "permitEnd": "2026-12-05", "jobEnded": "2026-11-20"}, TODAY)
    assert c["badge"]["days"] == 10 and "5 Dec 2026" in c["badge"]["note"]
    c = visaclock.clock({"status": "us-h1b", "permitEnd": "2028-09-30", "jobEnded": "2026-11-20"}, TODAY)
    assert c["badge"]["days"] == 55 and c["badge"]["total"] == 60
    c = visaclock.clock({"status": "us-h1b", "permitEnd": "2028-09-30"}, TODAY)
    assert c["badge"]["label"] == "days until your H-1B end date" and c["badge"]["tone"] == "ok"


def test_uk_student_switch_window_and_work_hours():
    c = visaclock.clock({"status": "uk-student", "permitEnd": "2027-01-31", "courseEnd": "2026-09-30"}, TODAY)
    assert c["badge"]["days"] == 67 and c["badge"]["tone"] == "soon"
    assert "full-time" in c["work"] and "Immigration Skills Charge" in c["next"]
    term = visaclock.clock({"status": "uk-student", "permitEnd": "2027-09-30", "courseEnd": "2027-05-30"}, TODAY)
    assert term["work"].startswith("Up to 20 hours")


def test_past_dates_say_they_have_passed():
    c = visaclock.clock({"status": "uk-graduate", "permitEnd": "2026-11-01"}, TODAY)
    assert c["badge"]["days"] == 0 and c["badge"]["tone"] == "over" and c["badge"]["note"] == visaclock.RULES["notes"]["over"]


def test_missing_dates_are_named_not_guessed():
    c = visaclock.clock({"status": "ie-stamp1g"}, TODAY)
    assert c["badge"] is None and c["missing"] == ["permitEnd"] and c["missingNote"]
    assert visaclock.clock({"status": "us-opt"}, TODAY)["missing"] == ["optStart"]
    assert visaclock.clock({"status": "us-stem-opt"}, TODAY)["missing"] == ["daysUsed"]
    assert visaclock.clock({"status": "us-f1", "courseEnd": "2026-02-30"}, TODAY)["missing"] == ["courseEnd"]


@pytest.mark.parametrize(("day", "forty"), [(date(2026, 11, 25), False), (date(2026, 12, 15), True), (date(2027, 1, 15), True),
                                            (date(2027, 1, 16), False), (date(2027, 6, 1), True), (date(2027, 9, 30), True)])
def test_stamp2_hours_follow_the_calendar(day, forty):
    c = visaclock.clock({"status": "ie-stamp2", "permitEnd": "2027-12-31"}, day)
    assert c["work"].startswith("Up to 40 hours a week now") is forty


def test_dutch_students_work_full_time_only_in_summer():
    assert visaclock.clock({"status": "nl-study", "permitEnd": "2027-08-31"}, date(2027, 7, 1))["work"].startswith("Full-time")
    assert visaclock.clock({"status": "nl-study", "permitEnd": "2027-08-31"}, TODAY)["work"].startswith("Up to 16 hours")


def test_part_time_mode_drops_the_sponsorship_filter_for_students_only():
    student = feed.settings_from_dashboard({"needsSponsorship": True, "jobMode": "part-time", "visa": {"status": "uk-student"}, "homeCountry": "GB"})
    graduate = feed.settings_from_dashboard({"needsSponsorship": True, "jobMode": "part-time", "visa": {"status": "uk-graduate"}, "homeCountry": "GB"})
    career = feed.settings_from_dashboard({"needsSponsorship": True, "jobMode": "career", "visa": {"status": "uk-student"}, "homeCountry": "GB"})
    assert not student.needs_sponsorship and graduate.needs_sponsorship and career.needs_sponsorship


CASES = [
    {"status": "us-opt", "optStart": "2026-10-26", "optEnd": "2027-10-25"},
    {"status": "us-opt", "optStart": "2026-06-01", "working": True, "daysUsed": 12, "asOf": "2026-09-01"},
    {"status": "us-opt", "optStart": "2026-08-01"},
    {"status": "us-opt", "optStart": "2027-01-10"},
    {"status": "us-opt"},
    {"status": "us-stem-opt", "daysUsed": "100", "asOf": "2026-11-05", "optEnd": "2028-01-01"},
    {"status": "us-stem-opt", "daysUsed": "abc"},
    {"status": "us-f1", "courseEnd": "2026-12-15"},
    {"status": "us-f1", "courseEnd": "2026-11-15"},
    {"status": "us-f1", "courseEnd": "2026-02-30"},
    {"status": "us-cpt", "courseEnd": "2027-05-20"},
    {"status": "us-h1b", "permitEnd": "2026-12-05", "jobEnded": "2026-11-20"},
    {"status": "us-h1b", "permitEnd": "2028-09-30", "jobEnded": "2026-11-20"},
    {"status": "us-h1b", "permitEnd": "2028-09-30", "jobEnded": "2027-01-01"},
    {"status": "us-h1b"},
    {"status": "uk-student", "permitEnd": "2027-01-31", "courseEnd": "2026-09-30"},
    {"status": "uk-student", "permitEnd": "2027-09-30", "courseEnd": "2027-05-30"},
    {"status": "uk-graduate", "permitEnd": "2026-11-01"},
    {"status": "uk-graduate", "permitEnd": "2027-02-01"},
    {"status": "uk-skilled", "permitEnd": "2029-03-01"},
    {"status": "ie-stamp2", "permitEnd": "2027-12-31", "courseEnd": "2027-05-31"},
    {"status": "ie-stamp1g"},
    {"status": "ie-stamp1g", "permitEnd": "2026-12-20"},
    {"status": "nl-study", "permitEnd": "2027-08-31"},
    {"status": "nl-zoekjaar", "permitEnd": "2027-03-01"},
    {"status": "abroad"},
    {"status": "settled"},
    {"status": "nope"},
]
DAYS = ["2026-11-25", "2026-12-20", "2027-01-15", "2027-07-01"]


def _js_block() -> str:
    html = (ROOT / "dashboard" / "app.html").read_text(encoding="utf-8")
    m = re.search(r"/\* visa-clock:start.*?\*/(.*?)/\* visa-clock:end \*/", html, re.S)
    assert m, "visa-clock block missing from dashboard/app.html"
    return m.group(1)


def test_dashboard_carries_the_same_rules():
    m = re.search(r"^const VISA_RULES = (.*);$", _js_block(), re.M)
    rules = dict(visaclock.RULES)
    rules.pop("_about", None)
    assert json.loads(m.group(1).replace("<\\/", "</")) == rules, "run python3 scripts/sync_visa_rules.py"


@pytest.mark.skipif(not shutil.which("node"), reason="node is not installed")
def test_dashboard_clock_matches_the_python_clock(tmp_path):
    script = tmp_path / "clock.js"
    script.write_text(_js_block() + "\nconst cases = JSON.parse(process.argv[2]), days = JSON.parse(process.argv[3]);\n"
                      "console.log(JSON.stringify(days.map(d => cases.map(c => visaClock(c, d)))));\n", encoding="utf-8")
    out = subprocess.run(["node", str(script), json.dumps(CASES), json.dumps(DAYS)], capture_output=True, text=True, timeout=60, check=True)
    js = json.loads(out.stdout)
    py = [[visaclock.clock(c, date.fromisoformat(d)) for c in CASES] for d in DAYS]
    for day, a, b in zip(DAYS, js, py):
        for case, x, y in zip(CASES, a, b):
            assert x == y, (day, case)
