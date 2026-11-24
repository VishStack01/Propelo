"""The Propelo Autofill extension: what it fills, what it leaves for you, and where it never runs.

The fill script runs against fixture forms in a real Chromium (skipped when Playwright or its
browser isn't installed). The manifest checks run everywhere."""

from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
EXT = ROOT / "extension"
FIX = Path(__file__).resolve().parent / "fixtures" / "extension"

APPLICANT = {"fullName": "Asha Rao", "email": "asha@example.com", "phone": "+91 98765 43210", "city": "Bengaluru",
             "linkedin": "https://www.linkedin.com/in/asha", "portfolio": "https://asha.dev", "noticePeriod": "30 days",
             "expectedCtcLpa": 14, "workAuthIndia": "Yes", "sponsorshipAbroad": "Not applicable, remote only", "gender": "Woman"}
RESUME = {"b64": base64.b64encode(b"%PDF-1.4 test").decode(), "name": "Asha-Rao.pdf", "type": "application/pdf"}


def test_manifest_asks_for_little():
    m = json.loads((EXT / "manifest.json").read_text())
    assert m["manifest_version"] == 3
    assert set(m["permissions"]) == {"activeTab", "scripting", "storage"}  # no tabs, no history, no cookies
    # No sites up front: the on-page button and the apply queue ask for their sites when you turn them on.
    assert "host_permissions" not in m and "content_scripts" not in m
    assert m["background"] == {"service_worker": "background.js"}
    for f in ("popup.html", "popup.js", "fill.js", "background.js", "content.js", "icons/icon-128.png"):
        assert (EXT / f).exists(), f
    # The Chrome Web Store's limits: a name up to 75 characters and a description up to 132.
    assert len(m["name"]) <= 75 and len(m["description"]) <= 132


def test_scripts_never_submit():
    for f in ("fill.js", "popup.js", "background.js", "content.js"):
        src = (EXT / f).read_text()
        assert ".submit(" not in src and "requestSubmit" not in src
        assert "eval(" not in src and "new Function" not in src


@pytest.fixture(scope="module")
def browser():
    sync = pytest.importorskip("playwright.sync_api")
    try:
        pw = sync.sync_playwright().start()
        b = pw.chromium.launch()
    except Exception as e:  # noqa: BLE001 - no browser on this machine
        pytest.skip(f"Chromium isn't available: {e}")
    yield b
    b.close()
    pw.stop()


def _open(browser, fixture: str, url: str):
    page = browser.new_page()
    html = (FIX / fixture).read_text()
    page.route(url, lambda route: route.fulfill(status=200, content_type="text/html", body=html))
    page.goto(url)
    page.add_script_tag(path=str(EXT / "fill.js"))
    return page


def test_fills_a_greenhouse_form_and_leaves_the_rest_to_you(browser):
    page = _open(browser, "greenhouse.html", "https://job-boards.greenhouse.io/acme/jobs/123")
    r = page.evaluate("d => window.__propeloFill(d)", {"applicant": APPLICANT, "resume": RESUME})
    val = lambda sel: page.eval_on_selector(sel, "e => e.value")  # noqa: E731
    assert val("#first_name") == "Asha" and val("#last_name") == "Rao" and val("#email") == "asha@example.com"
    assert val("#phone") == "+91 90000 00000"  # what was already typed stays
    assert val("#q1") == "https://www.linkedin.com/in/asha" and val("#q2") == "https://asha.dev"
    assert page.eval_on_selector("#q3", "e => e.options[e.selectedIndex].text") == "Yes"
    assert page.eval_on_selector('input[name=q4][value=no]', "e => e.checked")  # "remote only" means no sponsorship needed
    assert page.eval_on_selector("#q5", "e => e.options[e.selectedIndex].text") == "30 days"
    assert val("#q6") == "14"
    assert page.eval_on_selector("#resume", "e => e.files.length && e.files[0].name") == "Asha-Rao.pdf" and r["resume"] == "attached"
    assert page.eval_on_selector("#cover", "e => e.files.length") == 0
    # Never filled: voluntary questions, someone else's details, private numbers, passwords, consent boxes.
    assert page.eval_on_selector("#q8", "e => e.selectedIndex") == 0
    assert val("#q9") == "" and val("#q10") == "" and val("#q11") == "" and val("#pw") == ""
    assert not page.eval_on_selector("#consent", "e => e.checked")
    assert not page.evaluate("window.submitted")
    needs = " | ".join(n["label"] for n in r["needs"])
    assert "Why do you want to work at Acme" in needs and "PAN" in needs and "privacy notice" in needs
    assert r["skippedSensitive"] >= 2
    assert page.eval_on_selector("#first_name", "e => e.dataset.propelo") == "filled"
    assert page.eval_on_selector("#q7", "e => e.dataset.propelo") == "needs"
    info = page.evaluate("window.__propeloRead()")
    assert info["title"] == "AI Engineer" and info["company"] == "Acme"
    page.close()


def test_controlled_inputs_see_the_change(browser):
    page = _open(browser, "react.html", "https://jobs.ashbyhq.com/acme/1/application")
    page.evaluate("d => window.__propeloFill(d)", {"applicant": APPLICANT, "resume": None})
    assert page.evaluate("window.state") == {"fullName": "Asha Rao", "email": "asha@example.com", "city": "Bengaluru"}
    page.close()


@pytest.mark.parametrize("url", ["https://www.linkedin.com/jobs/view/1/apply", "https://www.naukri.com/job-listings-x",
                                 "https://in.indeed.com/viewjob?jk=1", "https://wellfound.com/jobs/1"])
def test_never_runs_on_big_job_boards(browser, url):
    page = _open(browser, "greenhouse.html", url)
    r = page.evaluate("d => window.__propeloFill(d)", {"applicant": APPLICANT, "resume": RESUME})
    assert r["blocked"] and not r["filled"]
    assert page.eval_on_selector("#first_name", "e => e.value") == ""
    page.close()


ANSWERS = [{"q": "Why do you want to work at Globex?", "a": "Globex answer.", "company": "Globex"},
           {"q": "Why do you want to work here?", "a": "I want to build developer tools that people use daily.", "company": "Acme"},
           {"q": "Tell us about a project you're proud of", "a": "I built a ticket router used by 40 support agents.", "company": ""}]


def test_campus_fields_and_saved_answers(browser):
    page = _open(browser, "campus.html", "https://jobs.lever.co/acme/123/apply")
    data = {"applicant": {**APPLICANT, "cgpa": "8.2/10", "branch": "Computer Science", "state": "Karnataka", "pinCode": "560001"},
            "resume": None, "answers": ANSWERS, "company": "Acme"}
    r = page.evaluate("d => window.__propeloFill(d)", data)
    val = lambda sel: page.eval_on_selector(sel, "e => e.value")  # noqa: E731
    assert val("#cg") == "8.2/10" and val("#br") == "Computer Science" and val("#st") == "Karnataka" and val("#pin") == "560001"
    assert val("#why") == "I want to build developer tools that people use daily."  # the Acme answer, not Globex's
    assert val("#proud").startswith("I built a ticket router")  # an any-company answer
    assert val("#leave") == ""  # "Please state..." is a question, not the State field
    assert r["fromAnswers"] == 2
    page.close()


def test_company_answers_stay_with_their_company(browser):
    page = _open(browser, "campus.html", "https://jobs.lever.co/initech/9/apply")
    page.evaluate("d => window.__propeloFill(d)", {"applicant": APPLICANT, "resume": None, "answers": ANSWERS, "company": "Initech"})
    assert page.eval_on_selector("#why", "e => e.value") == ""
    page.close()


def test_dashboard_gauge_is_the_extension_gauge():
    html = (ROOT / "dashboard" / "app.html").read_text(encoding="utf-8")
    copy = html.split("/*GAUGE*/\n", 1)[1].split("\n/*/GAUGE*/", 1)[0]
    assert copy == (EXT / "gauge.js").read_text(encoding="utf-8").strip()
    for f in ("gauge.js",):
        assert ".submit(" not in (EXT / f).read_text() and "eval(" not in (EXT / f).read_text()


def test_indian_hr_questions_dropdowns_and_late_questions(browser):
    from datetime import date, timedelta
    lwd = date.today() + timedelta(days=20)
    page = _open(browser, "india.html", "https://unstop.com/jobs/backend-engineer-acme-123")
    a = {**APPLICANT, "servingNotice": "Yes", "lastWorkingDay": lwd.isoformat(), "noticeBuyout": "Yes, partly", "currentCtcLpa": 12.5,
         "expectedCtcLpa": 18, "fixedCtcLpa": 11, "bondOk": "Prefer not to say", "preferredCities": "Bengaluru, Hyderabad", "shiftsOk": "No",
         "gapReason": "Six months caring for a family member in 2024."}
    page.evaluate("() => { window.more = []; window.__propeloOnMore = m => window.more.push(m); }")
    r = page.evaluate("d => window.__propeloFill(d)", {"applicant": a, "resume": None})
    val = lambda sel: page.eval_on_selector(sel, "e => e.value")  # noqa: E731
    text = lambda sel: page.eval_on_selector(sel, "e => e.options[e.selectedIndex].text")  # noqa: E731
    assert text("#buy") == "Yes"
    assert page.eval_on_selector("input[name=serving][value=y]", "e => e.checked")
    assert val("#lwd") == lwd.isoformat() and val("#lwd2") == f"{lwd.day} {lwd.strftime('%b')} {lwd.year}"
    assert val("#cc") == "1250000"  # the form asks in rupees
    assert val("#ec") == "18" and val("#fx") == "11"
    assert val("#mon") == ""  # monthly figures are left to you
    assert page.eval_on_selector("#bond", "e => e.selectedIndex") == 0  # "prefer not to say" stays unanswered
    assert val("#pl") == "Bengaluru, Hyderabad" and text("#pls") == "Bengaluru"
    assert page.evaluate("window.shiftPicked") == "No"  # a custom dropdown, opened and picked
    assert any(f["label"].startswith("Are you comfortable with rotational shifts") for f in r["filled"])
    # A question that appears after the fill is filled too, and the panel hears about it.
    page.evaluate("window.addLater()")
    page.wait_for_function("window.more.length > 0", timeout=5000)
    assert val("#gap").startswith("Six months caring") and val("#np") == "30 days"
    assert page.evaluate("window.more[0].filled.length") == 2
    assert not page.evaluate("window.submitted")
    page.close()


def test_past_last_working_day_is_not_used(browser):
    page = _open(browser, "india.html", "https://unstop.com/jobs/x")
    page.evaluate("d => window.__propeloFill(d)", {"applicant": {**APPLICANT, "servingNotice": "Yes", "lastWorkingDay": "2020-01-31"}, "resume": None, "watch": False})
    assert page.eval_on_selector("#lwd", "e => e.value") == "" and page.eval_on_selector("#lwd2", "e => e.value") == ""
    page.close()


def test_extension_lists_indian_portals_but_never_the_blocked_boards():
    bg = (EXT / "background.js").read_text()
    for host in ("internshala.com", "unstop.com", "instahyre.com", "cutshort.io", "joinsuperset.com", "darwinbox.in", "keka.com", "zohorecruit"):
        assert host in bg, host
    hosts = bg[bg.index("var JOB_HOSTS"):bg.index("];", bg.index("var JOB_HOSTS"))]
    for host in ("linkedin", "naukri", "indeed", "wellfound"):
        assert host not in hosts


def test_long_indian_names_and_questions_that_mention_a_field(browser):
    page = _open(browser, "greenhouse.html", "https://job-boards.greenhouse.io/acme/jobs/9")
    page.evaluate("d => window.__propeloFill(d)", {"applicant": {**APPLICANT, "fullName": "Venkata Vishnu Vardhan Raju Chakravarthula"}, "resume": None, "watch": False})
    assert page.eval_on_selector("input[name=first_name], #first_name", "e => e.value") == "Venkata Vishnu Vardhan Raju"
    assert page.eval_on_selector("input[name=last_name], #last_name", "e => e.value") == "Chakravarthula"
    page.close()
    page = _open(browser, "campus.html", "https://internshala.com/application/form/2")
    page.evaluate("d => window.__propeloFill(d)", {"applicant": {**APPLICANT, "currentTitle": "AI Product Designer"}, "resume": None, "watch": False})
    assert page.eval_on_selector("#leave", "e => e.value") == ""  # a question about your role, not your role
    page.close()


def test_shadow_dom_forms_and_slow_pickers(browser):
    """Workday-style forms keep fields inside shadow roots and load dropdown options late; both are filled."""
    page = _open(browser, "shadow.html", "https://acme.wd5.myworkdayjobs.com/en-US/External/job/London/Data-Analyst_JR1/apply")
    a = {**APPLICANT, "howHeard": "Company website", "sponsorshipAbroad": "Yes, I will need sponsorship"}
    r = page.evaluate("d => window.__propeloFill(d)", {"applicant": a, "resume": None})
    shadow = lambda sel, prop="value": page.evaluate(f"() => document.querySelector('wd-form').shadowRoot.querySelector('{sel}').{prop}")  # noqa: E731
    assert shadow("#fn") == "Asha" and shadow("#ln") == "Rao" and shadow("#em") == "asha@example.com"
    assert page.evaluate("window.sponsorPicked") == "Yes"  # options arrived after 900 ms
    assert page.evaluate("window.sourcePicked") == "Company website"  # searched on Enter
    assert shadow("#fn", "getAttribute('data-propelo')") == "filled"
    assert page.evaluate("!!document.querySelector('wd-form').shadowRoot.getElementById('propelo-marks')")  # outlines show inside the form
    assert {f["label"].split(" *")[0] for f in r["filled"]} >= {"First name", "Last name", "Email"}
    assert not page.evaluate("window.submitted")
    page.close()
