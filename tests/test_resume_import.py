"""The dashboard's resume reader (no AI): run the real function from the page on a few layouts."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
RUNNER = r"""
const fs = require("fs"); const h = fs.readFileSync(process.argv[process.argv.length - 1], "utf8");
const a = h.indexOf('function localImport(text){'), b = h.indexOf('function mergeImport(out){');
const f = new Function('arr', h.slice(a, b) + '; return localImport;')(v => Array.isArray(v) ? v : []);
console.log(JSON.stringify(JSON.parse(fs.readFileSync(0, 'utf8')).map(f)));
"""
R1 = """Priya Sharma
Leeds, United Kingdom | priya@example.com | Graduate visa
SUMMARY
Data analyst.
EDUCATION
MSc Data Science, University of Leeds, 2025-2026 (Merit)
B.Tech Computer Science, JNTU Hyderabad, 2020-2024
EXPERIENCE
Systems Engineer (Analytics), Infosys, Hyderabad, Jul 2024 - Aug 2025
- Built SQL pipelines
- Created Power BI dashboards
PROJECTS
Customer churn prediction (scikit-learn, XGBoost), MSc dissertation with a UK telecom dataset
SKILLS
Python, SQL, pandas"""
R2 = """RAHUL VERMA
Software Engineer
rahul.v@example.com | +91 98765 43210 | linkedin.com/in/rahulv

Work Experience
Acme Payments Pvt Ltd — Bengaluru
Senior Software Engineer                                   Jan 2022 – Present
• Led migration of the ledger service
Flipkart
Software Development Engineer I        July 2019 - December 2021
• Built the returns API

Education
Indian Institute of Technology Madras
B.Tech in Computer Science, 2015 - 2019
CGPA 8.7

Projects
OpenLedger - an open-source double-entry library in Go
• 1.2k stars on GitHub
Skills: Go, Java, Kafka"""
R3 = """Anna Müller
Berlin, Germany
anna@example.com

Profile
Mechanical engineer with two years in automotive testing.

Employment
2023 - 2025  Test Engineer at Bosch GmbH, Stuttgart
Planned and ran endurance tests for braking systems.

Qualifications
Master of Science Mechanical Engineering | Technische Universität München | 2020 – 2022"""
# What a PDF reader gives for a two-column designed resume: no bullet marks, sentences wrapped at the page edge,
# headings with a prefix ("PROFESSIONAL SUMMARY", "CORE SKILLS"), labelled skill rows split by semicolons, ligatures.
R5 = """Asha Rao
India (Remote) | asha@example.com | github.com/asharao
PROFESSIONAL SUMMARY
Machine-learning engineer (B.Tech CSE, Example University, 2026) who builds retrieval systems and evaluation
pipelines for production services, with source-
grounded answers and guardrails.
CORE SKILLS
AI / ML: LLM APIs; Retrieval-Augmented Generation (RAG); Vector Search (pgvector); Tool Calling; Structured Output; Retrieval-
Augmented Evaluation and Prompt Tests
Languages: Python, TypeScript, SQL
Product and Workflow: AI UX and interaction design, technical documentation
PROFESSIONAL EXPERIENCE
Machine Learning Engineer | Credﬁx Apr 2026 – Present
Design retrieval and ranking services that answer customer questions from contract text with citations and
measured accuracy.
Ship evaluation suites.
Data Analyst Intern | Northwind Jan 2025 – Mar 2025
Built weekly churn dashboards for the support team, cutting the time to a report from two days to an hour for every
region.
SELECTED PROJECTS
Ledger Lens | Open-source finance tool Live, 40 users
Built a tool that reads bank statements and sorts each line into a category the user can correct, with a test suite
covering every bank format it supports.
Added a review step.
Plant Doctor | Computer Vision YOLO
Built an image classifier for leaf disease with a FastAPI backend and a React frontend that works on phones.
EDUCATION
B.Tech, Computer Science & Engineering (AI & Machine Learning) | Example University 2026
CGPA: 8.1"""
R4 = "John Smith\njohn@example.com\n\nI am looking for a job. This text has no sections at all, only a paragraph about me and my hobbies."


@pytest.fixture(scope="module")
def parsed():
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    out = subprocess.run([node, "-e", RUNNER, str(ROOT / "dashboard" / "app.html")], input=json.dumps([R1, R2, R3, R4, R5]), capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def test_a_one_line_per_job_resume(parsed):
    p = parsed[0]
    assert p["basics"]["name"] == "Priya Sharma" and p["basics"]["location"] == "Leeds, United Kingdom" and p["basics"]["email"] == "priya@example.com"
    (job,) = p["experience"]
    assert (job["title"], job["company"], job["location"], job["start"], job["end"]) == ("Systems Engineer (Analytics)", "Infosys", "Hyderabad", "Jul 2024", "Aug 2025")
    assert job["bullets"] == ["Built SQL pipelines", "Created Power BI dashboards"]
    assert [(e["degree"], e["school"], e["start"], e["end"], e["note"]) for e in p["education"]] == [
        ("MSc Data Science", "University of Leeds", "2025", "2026", "Merit"), ("B.Tech Computer Science", "JNTU Hyderabad", "2020", "2024", "")]
    assert p["projects"][0]["name"] == "Customer churn prediction (scikit-learn, XGBoost)" and p["projects"][0]["bullets"] == ["MSc dissertation with a UK telecom dataset"]
    assert p["skills"] == ["Python", "SQL", "pandas"] and p["summary"] == "Data analyst."


def test_employer_on_the_line_above_the_dates(parsed):
    p = parsed[1]
    assert p["basics"]["headline"] == "Software Engineer" and p["basics"]["phone"] == "+91 98765 43210"
    assert [(j["title"], j["company"], j["location"], j["start"], j["end"]) for j in p["experience"]] == [
        ("Senior Software Engineer", "Acme Payments Pvt Ltd", "Bengaluru", "Jan 2022", "Present"),
        ("Software Development Engineer I", "Flipkart", "", "July 2019", "December 2021")]
    (edu,) = p["education"]
    assert (edu["degree"], edu["school"], edu["note"]) == ("B.Tech in Computer Science", "Indian Institute of Technology Madras", "CGPA 8.7")
    assert [x["name"] for x in p["projects"]] == ["OpenLedger"]              # "Skills: ..." on one line is not a project
    assert p["skills"] == ["Go", "Java", "Kafka"]


def test_names_beyond_ascii_and_headings_in_ordinary_case(parsed):
    p = parsed[2]
    assert p["basics"]["name"] == "Anna Müller" and p["basics"]["location"] == "Berlin, Germany"
    assert "headline" not in p["basics"] and "phone" not in p["basics"]    # the address is not a headline; "2023 - 2025" is not a phone
    (job,) = p["experience"]
    assert (job["title"], job["company"], job["location"], job["start"], job["end"]) == ("Test Engineer", "Bosch GmbH", "Stuttgart", "2023", "2025")
    assert p["education"][0]["school"] == "Technische Universität München"
    assert p["summary"] == "Mechanical engineer with two years in automotive testing."


def test_text_without_sections_adds_nothing_invented(parsed):
    p = parsed[3]
    assert p["basics"] == {"links": [], "name": "John Smith", "email": "john@example.com"}
    assert not p.get("experience") and not p.get("education") and not p.get("projects")


def test_a_pdf_with_wrapped_lines_and_no_bullet_marks(parsed):
    p = parsed[4]
    assert p["summary"].startswith("Machine-learning engineer") and "source-grounded answers and guardrails." in p["summary"]
    assert "Retrieval-Augmented Generation (RAG)" in p["skills"] and "Retrieval-Augmented Evaluation and Prompt Tests" in p["skills"]
    assert "AI UX and interaction design" in p["skills"] and "Python" in p["skills"] and not any(":" in x for x in p["skills"])
    assert [(j["title"], j["company"], j["start"], j["end"]) for j in p["experience"]] == [
        ("Machine Learning Engineer", "Credfix", "Apr 2026", "Present"), ("Data Analyst Intern", "Northwind", "Jan 2025", "Mar 2025")]
    assert p["experience"][0]["bullets"] == [
        "Design retrieval and ranking services that answer customer questions from contract text with citations and measured accuracy.",
        "Ship evaluation suites."]
    assert p["experience"][1]["bullets"] == ["Built weekly churn dashboards for the support team, cutting the time to a report from two days to an hour for every region."]
    assert [(x["name"], len(x["bullets"])) for x in p["projects"]] == [("Ledger Lens", 3), ("Plant Doctor", 2)]
    assert p["projects"][0]["bullets"][-1] == "Added a review step."
    (edu,) = p["education"]
    assert (edu["degree"], edu["school"], edu["end"], edu["note"]) == (
        "B.Tech, Computer Science & Engineering (AI & Machine Learning)", "Example University", "2026", "CGPA: 8.1")
