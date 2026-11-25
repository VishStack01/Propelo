"""The resume defence drill: which lines get asked about, the follow-up an interviewer would ask, and the
line-by-line scorecard. The dashboard runs the same rules in JavaScript; the last test checks they agree."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from propelo import drill

VIEW = {"experience": [{"company": "Acme Labs", "bullets": ["Cut API latency by 40% by caching hot queries", "Built Airflow pipelines that load 2 TB a day",
                                                          "Mentored two interns", "Saved £50k a year in cloud costs"]}],
        "projects": [{"name": "Job radar", "bullets": ["Scans 3,000 boards a day", "Uses FastAPI and Postgres", "Written in Python 3.11"]}],
        "skills": ["FastAPI", "Python", "Airflow"]}

GOOD = ("I added a Redis cache in front of the three slowest queries. p95 went from 900 ms to 540 ms, so about 40% faster, measured on "
        "our Grafana dashboard over two weeks before and after the change. I wrote the cache layer and the invalidation myself.")
WE = "We improved it a lot as a team and our latency got much better over the quarter, everyone was happy with what we shipped together in the end."
WRONG = "I cut it by 35% using caching. I measured it on the dashboard before and after, and my manager signed it off at the end of the quarter for the team."


def test_figures_read_units_and_skip_years_and_versions():
    got = [(f["raw"], f["value"], f["kind"]) for f in drill.figures("Since 2021 cut latency by 40% in 3 months, saved £50k, 1,200 users, 10x, 200ms, Python 3.11, Java 17")]
    assert got == [("40%", 40, "percent"), ("3 months", 3, "time"), ("£50k", 50000, "money"), ("1,200", 1200, "count"), ("10x", 10, "count"), ("200ms", 200, "time")]


def test_claims_take_lines_with_figures_then_skills():
    cs = drill.claims(VIEW)
    assert [c["text"] for c in cs] == ["Cut API latency by 40% by caching hot queries", "Built Airflow pipelines that load 2 TB a day",
                                       "Saved £50k a year in cloud costs", "Scans 3,000 boards a day", "Uses FastAPI and Postgres", "Written in Python 3.11"]
    assert [c["kind"] for c in cs] == ["percent", "count", "money", "count", "tool", "tool"]
    assert cs[4]["tool"] == "FastAPI" and drill.question(cs[4]) == "You used FastAPI in Job radar. Walk me through one thing you built with it, and one problem you hit."
    assert drill.question(cs[0]).startswith('Your resume says: "Cut API latency by 40% by caching hot queries". What was the figure before and after')
    assert drill.claims({}) == [] and drill.claims(None) == []
    assert len(drill.claims({"experience": [{"company": "X", "bullets": [f"Shipped {i} features" for i in range(1, 12)]}]})) == drill.MAX_CLAIMS


def test_score_rewards_the_figure_how_you_know_and_your_part():
    c = drill.claims(VIEW)[0]
    good = drill.score(c, GOOD)
    assert good["verdict"] == "defended" and all(good["checks"].values()) and good["notes"] == []
    we = drill.score(c, WE)
    assert we["verdict"] == "not" and not we["checks"]["mine"] and "You didn't say the number" in we["notes"][0]
    wrong = drill.score(c, WRONG)
    assert wrong["verdict"] == "not" and wrong["conflict"] == "Your resume says 40%; you said 35%."


def test_one_follow_up_goes_after_the_gap():
    c = drill.claims(VIEW)[0]
    assert drill.follow_up(c, WRONG) == "Your resume says 40%. You said 35%. Which is right?"
    assert drill.follow_up(c, WE) == "What was the number, exactly?"
    assert drill.follow_up(c, "I cut it by 40% with a cache I wrote, and it was good.") == "How do you know? What did you measure, and against what?"
    assert drill.follow_up(c, GOOD) == "What would you do differently if you did it again?"
    tool = drill.claims(VIEW)[4]
    assert drill.follow_up(tool, "I built the API and deployed it on Render with Postgres behind it.") == "What did you use FastAPI for there, in one sentence?"
    assert drill.summary([drill.score(c, GOOD), drill.score(c, WE), drill.score(c, "I made it 40% faster, measured before and after.")]) == \
        {"defended": 1, "partly": 1, "not": 1}


ANSWERS = [GOOD, WE, WRONG, "", "I built the API with FastAPI and our team deployed it. " * 3, "Saved £50,000 by moving to spot instances; I tracked it in the billing report."]


@pytest.mark.skipif(not shutil.which("node"), reason="node is not installed")
def test_dashboard_drill_matches_python(tmp_path):
    html = (Path(__file__).resolve().parent.parent / "dashboard" / "app.html").read_text(encoding="utf-8")
    block = re.search(r"/\* drill:start.*?\*/(.*?)/\* drill:end \*/", html, re.S).group(1)
    script = tmp_path / "drill.js"
    script.write_text(block + "\nconst [view, answers] = JSON.parse(process.argv[2]);\nconst cs = drillClaims(view);\n"
                      "console.log(JSON.stringify({claims: cs, questions: cs.map(drillQuestion), "
                      "scores: cs.map(c => answers.map(a => drillScore(c, a))), follow: cs.map(c => answers.map(a => drillFollowUp(c, a)))}));\n", encoding="utf-8")
    out = json.loads(subprocess.run(["node", str(script), json.dumps([VIEW, ANSWERS])], capture_output=True, text=True, timeout=60, check=True).stdout)
    cs = drill.claims(VIEW)
    assert out["claims"] == cs
    assert out["questions"] == [drill.question(c) for c in cs]
    assert out["scores"] == [[drill.score(c, a) for a in ANSWERS] for c in cs]
    assert out["follow"] == [[drill.follow_up(c, a) for a in ANSWERS] for c in cs]
