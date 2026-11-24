"""The wording check: 140-odd stock phrases, the safe fixes made to AI drafts, and the dashboard doing the same."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from propelo import writing

ROOT = Path(__file__).resolve().parent.parent


def test_rules_are_many_and_well_formed():
    rules = writing.RULES
    assert len(rules) >= 120
    for r in rules:
        assert ("pattern" in r) != ("delete" in r) and r["why"] and r["instead"]
        assert r["_find"].search("") is None  # no rule matches empty text


@pytest.mark.parametrize(("draft", "clean"), [
    ("Spearheaded the move to Postgres.", "Led the move to Postgres."),
    ("Leveraged dbt and utilised Airflow in order to cut costs.", "Used dbt and used Airflow to cut costs."),
    ("Built a robust API.", "Built an API."),
    ("An innovative tool for a robust user base.", "A tool for a user base."),
    ("Successfully shipped the app.", "Shipped the app."),
    ("We use a cutting-edge GPU cluster and an exceptional hour of training.", "We use a GPU cluster and an hour of training."),
    ("Data Scientist — London", "Data Scientist, London"),
    ("Cut latency by 40% — the team's goal.", "Cut latency by 40%, the team's goal."),
])
def test_safe_fixes(draft, clean):
    assert writing.clean(draft)[0] == clean


def test_fixes_never_touch_facts_and_say_what_changed():
    draft = "Spearheaded a robust migration of 1,200 users at Acme, cutting cost 30%."
    text, fixed = writing.clean(draft)
    assert text == "Led a migration of 1,200 users at Acme, cutting cost 30%."
    assert {"from": "Spearheaded", "to": "Led"} in fixed and {"from": "robust", "to": ""} in fixed
    plain = "Your support team triages 2,000 tickets a week by hand. I built TicketRouter, which tags them at 94% accuracy."
    assert writing.clean(plain) == (plain, [])


def test_what_cannot_be_fixed_safely_is_flagged():
    found = {f.phrase.lower() for f in writing.check("A passionate, results-driven engineer with a proven track record who delves deep.")}
    assert {"passionate", "results-driven", "proven track record"} <= found
    assert writing.check("Optimised the build.") and not writing.check("Optimised the build from 9 to 4 minutes.")


def test_articles_follow_the_sound():
    assert [writing.article(w) for w in ("API", "GPU", "MBA", "hour", "user", "European", "apple", "one", "honest", "SQL")] == \
        ["an", "a", "an", "an", "a", "a", "an", "a", "an", "an"]


DRAFTS = [
    "Spearheaded a robust migration of 1,200 users at Acme, cutting cost 30%.",
    "I am writing to express my interest. I am passionate about AI and a results-driven team player!! Thank you for your consideration.",
    "Leveraged dbt and utilised Airflow in order to cut costs.\nAn innovative tool for a robust user base.\nSuccessfully shipped the app.",
    "We use a cutting-edge GPU cluster — and an exceptional hour of training — every week — with a robust MBA.",
    "Moreover, I delved into the data landscape and harnessed the power of LLMs to unlock the full potential of our team.",
    "Your support team triages 2,000 tickets a week by hand. I built TicketRouter, which tags them at 94% accuracy.",
    "Optimised the build. Optimised the build from 9 to 4 minutes. Not only fast but also cheap.",
    "",
]


def _js_block() -> str:
    html = (ROOT / "dashboard" / "app.html").read_text(encoding="utf-8")
    m = re.search(r"/\* slop:start.*?\*/(.*?)/\* slop:end \*/", html, re.S)
    assert m, "slop block missing from dashboard/app.html"
    return m.group(1)


def test_dashboard_carries_the_same_rules():
    m = re.search(r"^const SLOP_RULES = (.*);$", _js_block(), re.M)
    plain = [{k: v for k, v in r.items() if not k.startswith("_")} for r in writing.RULES]
    assert json.loads(m.group(1).replace("<\\/", "</")) == plain, "run python3 scripts/sync_slop_rules.py"


@pytest.mark.skipif(not shutil.which("node"), reason="node is not installed")
def test_dashboard_wording_check_matches_python(tmp_path):
    script = tmp_path / "slop.js"
    script.write_text(_js_block() + "\nconst drafts = JSON.parse(process.argv[2]);\n"
                      "console.log(JSON.stringify(drafts.map(d => ({clean: slopClean(d), check: slopCheck(d)}))));\n", encoding="utf-8")
    out = subprocess.run(["node", str(script), json.dumps(DRAFTS)], capture_output=True, text=True, timeout=60, check=True)
    for draft, got in zip(DRAFTS, json.loads(out.stdout)):
        text, fixed = writing.clean(draft)
        assert got["clean"] == {"text": text, "fixed": fixed}, draft
        assert got["check"] == [f.to_dict() for f in writing.check(draft)], draft


# ------------------------------------------------------------------ the Word file

VIEW = {"basics": {"name": "Asha Rao", "headline": "AI Engineer", "email": "asha@example.com", "phone": "+44 7700 900123", "location": "London",
                   "links": ["https://github.com/asha-example"]},
        "summary": "AI engineer who ships retrieval systems & evals <fast>.",
        "experience": [{"title": "AI Engineer", "company": "Acme Labs", "location": "London", "start": "Jan 2026", "end": "Present",
                        "bullets": ["Built a retrieval service serving 1,200 users", "Cut evaluation time by 40%"], "skills": ["Python", "FastAPI"]}],
        "projects": [{"name": "Job radar", "url": "https://github.com/asha-example/radar", "when": "2026", "bullets": ["Scans 3,000 boards"]}],
        "education": [{"degree": "MSc, Data Science", "school": "Example University", "start": "2024", "end": "2025", "note": "Merit"}],
        "skills": ["Python", "RAG"], "languages": [{"language": "English", "level": "Fluent"}], "publications": [], "references": []}


@pytest.mark.skipif(not shutil.which("node"), reason="node is not installed")
def test_word_file_is_one_column_with_real_text_and_bullets(tmp_path):
    import io
    import zipfile
    import xml.etree.ElementTree as ET
    html = (ROOT / "dashboard" / "app.html").read_text(encoding="utf-8")
    block = re.search(r"/\* docx:start.*?\*/(.*?)/\* docx:end \*/", html, re.S).group(1)
    script = tmp_path / "docx.js"
    script.write_text(block + "\nconst v = JSON.parse(process.argv[2]);\nprocess.stdout.write(Buffer.from(resumeDocx(v, {paper: process.argv[3], "
                      "order: ['summary', 'experience', 'projects', 'education', 'skills', 'languages'], headings: {summary: 'Profile'}})).toString('base64'));\n",
                      encoding="utf-8")
    import base64
    for paper, width in (("a4", "11906"), ("letter", "12240")):
        raw = base64.b64decode(subprocess.run(["node", str(script), json.dumps(VIEW), paper], capture_output=True, text=True, timeout=60, check=True).stdout)
        z = zipfile.ZipFile(io.BytesIO(raw))
        assert z.testzip() is None
        assert {"[Content_Types].xml", "_rels/.rels", "word/document.xml", "word/styles.xml", "word/numbering.xml", "docProps/core.xml"} <= set(z.namelist())
        for name in z.namelist():
            ET.fromstring(z.read(name))  # every part is well-formed XML
        doc = z.read("word/document.xml").decode()
        w = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
        root = ET.fromstring(doc)
        paras = root.iter(w + "p")
        text = ["".join(t.text or "" for t in p.iter(w + "t")) for p in paras]
        assert text[:3] == ["Asha Rao", "AI Engineer", "asha@example.com · +44 7700 900123 · London · github.com/asha-example"]
        assert "Profile" in text and "AI engineer who ships retrieval systems & evals <fast>." in text
        assert text.index("Experience") < text.index("Projects") < text.index("Education") < text.index("Skills")
        assert "Built a retrieval service serving 1,200 users" in text and "Python, RAG" in text and "English (Fluent)" in text
        assert root.find(f".//{w}tbl") is None and "w:cols" not in doc and "txbxContent" not in doc  # no tables, columns or text boxes
        bullets = [p for p in root.iter(w + "p") if (p.find(f"{w}pPr/{w}pStyle") is not None and p.find(f"{w}pPr/{w}pStyle").get(w + "val") == "ListBullet")]
        assert len(bullets) == 3
        assert root.find(f".//{w}pgSz").get(w + "w") == width
