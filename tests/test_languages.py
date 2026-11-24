"""Roles that need a language other than English: asked for in the posting, named in the title, or a posting
written in that language. Welcome-but-not-required never rules a role out."""

from datetime import datetime, timezone

import pytest

from propelo import feed, gates, scan, signals
from propelo.models import Job

DUTCH_POSTING = ("Wat ga je doen? Als data engineer bij ons team ben je verantwoordelijk voor het bouwen van pipelines. Je hebt ervaring "
                 "met Python en SQL. Wij bieden een goed salaris en ook een leaseauto. Je werkt met een team van tien collega's binnen onze "
                 "afdeling. Deze functie is voor jou als je minimaal drie jaar ervaring hebt met het werken in een data team.")
ENGLISH_POSTING = ("We build data pipelines for a global team. You will work with Python and SQL, and you will help our customers. Our office "
                   "is in Amsterdam with a team of 40 people from 20 countries. The working language is English and we have a hybrid setup.")


@pytest.mark.parametrize(("text", "title", "lang", "need"), [
    ("Requirements: Fluent Dutch and English. 3 years of Python.", "", "Dutch", "required"),
    ("You speak Dutch and English fluently.", "", "Dutch", "required"),
    ("Excellent command of German, written and spoken.", "", "German", "required"),
    ("Strong written and verbal communication skills in English and Dutch.", "", "Dutch", "required"),
    ("Excellent Dutch language skills", "", "Dutch", "required"),
    ("Dutch and English required.", "", "Dutch", "required"),
    ("Fluent Dutch is a must; German is a plus.", "", "Dutch", "required"),
    ("Je spreekt vloeiend Nederlands en Engels.", "", "Dutch", "required"),
    ("Support role", "German Speaking Customer Support Agent", "German", "required"),
    ("Support role", "Account Executive (Dutch)", "Dutch", "required"),
    ("Fluent English is required; Dutch is a plus.", "", "Dutch", "plus"),
    ("Knowledge of German would be an advantage.", "", "German", "plus"),
    ("Proficiency in Spanish preferred.", "", "Spanish", "plus"),
    ("You don't need to speak Dutch: our working language is English.", "", "Dutch", "not-needed"),
    ("No Dutch required.", "", "Dutch", "not-needed"),
    (DUTCH_POSTING, "Data Engineer", "Dutch", "posting"),
])
def test_language_asked_for(text, title, lang, need):
    got = signals.language_need(text, title)
    assert (got["lang"], got["need"]) == (lang, need)
    assert got["quote"]


@pytest.mark.parametrize("text", [
    "We are a strong French team building payments.",
    "An Irish company with a strong Irish presence.",
    "Serving our Dutch-speaking customers across Benelux.",
    "Native Android development experience.",
    "Speak to French customers daily.",
    ENGLISH_POSTING,
    "",
])
def test_no_language_is_read_into_ordinary_words(text):
    assert signals.language_need(text) == {}


def test_long_text_stays_fast():
    import time
    t0 = time.time()
    signals.language_need("We are looking for an engineer with strong skills and good knowledge of systems. " * 300)
    assert time.time() - t0 < 1


def test_speaks_knows_the_names_people_use():
    assert signals.speaks("Dutch", ["English", "Nederlands"]) and signals.speaks("Flemish", ["dutch"]) and signals.speaks("German", ["Deutsch"])
    assert not signals.speaks("Dutch", ["English"]) and not signals.speaks("Dutch", [])


def _job(desc, title="Backend Engineer", location="Amsterdam, Netherlands"):
    return Job(source="t", company="Acme", title=title, url="https://boards.greenhouse.io/acme/jobs/1", location=location,
               work_mode="hybrid", description=desc, posted_at=datetime.now(timezone.utc).isoformat())


def test_the_gate_skips_only_languages_you_dont_work_in():
    s = feed.settings_from_dashboard({"homeCountry": "NL", "places": "Netherlands", "targetRoles": ["backend"]})
    assert s.languages == ["English"]
    need = gates.gate_language(_job("Fluent Dutch is required."), s)
    assert not need.passed and "Asks for Dutch" in need.value and "Fluent Dutch" in need.quote
    posting = gates.gate_language(_job(DUTCH_POSTING), s)
    assert not posting.passed and "written in Dutch" in posting.value
    assert gates.gate_language(_job("Dutch is a plus."), s).passed
    assert gates.gate_language(_job("No Dutch required."), s).passed
    assert gates.gate_language(_job("Build APIs in Go."), s).value == "English"
    # Saying you work in Dutch lets the same roles through; English is always kept.
    nl = feed.settings_from_dashboard({"homeCountry": "NL", "places": "Netherlands", "targetRoles": ["backend"], "workLanguages": "Dutch"})
    assert nl.languages == ["English", "Dutch"]
    assert gates.gate_language(_job("Fluent Dutch is required."), nl).passed
    assert gates.gate_language(_job(DUTCH_POSTING), nl).passed


def test_a_role_needing_another_language_is_a_near_miss_with_the_fix():
    now = datetime.now(timezone.utc)

    def rec(i, facts, summary="Build APIs."):
        return {"id": f"l{i}", "company": f"Co {i}", "title": "Backend Engineer", "url": f"https://jobs.example.com/l{i}", "source": "Greenhouse",
                "location": "Amsterdam, Netherlands", "workMode": "hybrid", "postedAt": now.isoformat(), "summary": summary, "via": "careers",
                "facts": {"loc": "abroad", **facts}}
    records = [rec(1, {"language": {"lang": "Dutch", "need": "required", "quote": "Fluent Dutch is required."}}),
               rec(2, {"language": {"lang": "Dutch", "need": "plus", "quote": "Dutch is a plus."}}), rec(3, {})]
    s = feed.settings_from_dashboard({"homeCountry": "NL", "places": "Netherlands", "targetRoles": ["backend"]})
    res = feed.match(iter(records), s, [], None, now)
    kept = dict(res["kept"])
    assert set(kept) == {"l2", "l3"} and kept["l2"]["language"]["need"] == "plus"
    (sid, sdoc), = res["skipped"]
    assert sid == "l1" and sdoc["skip"]["wouldChange"] == "Adding Dutch to the languages you work in."


def test_the_scan_records_the_language_with_its_quote():
    job = _job("We need a fluent German speaker for our Dublin office.", title="Account Manager", location="Dublin, Ireland")
    rec = scan.to_feed(job, {"name": "Acme"})
    assert rec["facts"]["language"] == {"lang": "German", "need": "required", "quote": "We need a fluent German speaker for our Dublin office."}
    plain = scan.to_feed(_job("Build APIs in Go."), {"name": "Acme"})
    assert "language" not in plain["facts"]
