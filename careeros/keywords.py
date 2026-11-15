"""Which of the posting's terms your resume uses, and where.

    careeros keywords --jd jd.txt --resume packages/<id>/resume.json [--terms "Python,RAG,..."]

This is a coverage list, never an "ATS score": no one outside the company can
know how its screening software ranks a resume, and a number would invite
keyword stuffing. Each term is one of:

* present: in your summary or a bullet, so it is backed by a claim;
* thin:    only in your skills list (a recruiter skimming bullets won't see it);
* missing: nowhere. Add it only if the brain has a claim that uses it.
"""

from __future__ import annotations

import re
from collections import Counter

from .tags import SKILLS

EXTRA = [
    ("LLM agents", r"\bagent(s|ic)?\b"), ("Evals", r"\bevals?\b|\bevaluation (set|harness|framework)s?\b"),
    ("Prompt engineering", r"\bprompt(ing| engineering| design)\b"), ("Fine-tuning", r"\bfine[- ]?tun(e|ed|ing)\b"),
    ("Vector databases", r"\bvector (db|database|store|search)s?\b|\bpinecone|weaviate|qdrant|pgvector|chroma(db)?\b"),
    ("OpenAI API", r"\bopenai\b"), ("Anthropic API", r"\banthropic|claude api\b"), ("Hugging Face", r"\bhugging ?face\b"),
    ("LlamaIndex", r"\bllama ?index\b"), ("MLOps", r"\bmlops|llmops\b"), ("CI/CD", r"\bci/?cd\b|\bcontinuous (integration|delivery)\b"),
    ("REST APIs", r"\brest(ful)? apis?\b"), ("Microservices", r"\bmicro-?services?\b"), ("Airflow", r"\bairflow\b"), ("dbt", r"\bdbt\b"),
    ("Pandas", r"\bpandas\b"), ("NumPy", r"\bnumpy\b"), ("scikit-learn", r"\bscikit|sklearn\b"), ("Redis", r"\bredis\b"),
    ("MongoDB", r"\bmongo(db)?\b"), ("Git", r"\bgit\b(?!hub)"), ("Linux", r"\blinux\b"), ("Terraform", r"\bterraform\b"),
    ("n8n", r"\bn8n\b"), ("Zapier", r"\bzapier\b"), ("Make", r"\bmake\.com\b"), ("Tableau", r"\btableau\b"), ("Power BI", r"\bpower ?bi\b"),
    ("Machine learning", r"\bmachine learning\b|\bml\b"), ("NLP", r"\bnlp\b|natural language processing"), ("Computer vision", r"\bcomputer vision\b"),
    ("Data pipelines", r"\b(data|etl|elt) pipelines?\b"), ("System design", r"\bsystem design\b"), ("A/B testing", r"\ba/b test"),
    ("Product discovery", r"\bproduct discovery\b|\buser research\b"), ("Prototyping", r"\bprototyp(e|es|ing)\b"),
    ("Design systems", r"\bdesign systems?\b"), ("Stakeholder management", r"\bstakeholders?\b"),
]
# Skills outside tech, so coverage and the match score work for every field.
EVERY_FIELD = [
    # finance and accounts
    ("Tally", r"\btally( prime| erp)?\b"), ("GST", r"\bgst\b"), ("TDS", r"\btds\b"), ("Accounts payable", r"\baccounts? payable\b"),
    ("Accounts receivable", r"\baccounts? receivable\b"), ("Reconciliation", r"\breconcil(e|iation|ing)\b"), ("Financial reporting", r"\bfinancial (reporting|statements)\b"),
    ("Budgeting", r"\bbudget(ing|s)?\b"), ("Auditing", r"\baudit(ing|s)?\b"), ("Taxation", r"\btax(ation)?\b"), ("IFRS", r"\bifrs|ind as\b"),
    ("QuickBooks", r"\bquickbooks\b"), ("SAP", r"\bsap( fico| mm| sd| hana| s/4)?\b"), ("Excel", r"\b(ms |advanced )?excel\b"), ("Payroll", r"\bpayroll\b"),
    # sales, marketing and service
    ("Lead generation", r"\blead gen(eration)?\b"), ("Cold calling", r"\bcold[- ]call(s|ing)?\b"), ("B2B sales", r"\bb2b\b"), ("B2C sales", r"\bb2c\b"),
    ("Negotiation", r"\bnegotiat(e|ion|ing)\b"), ("Account management", r"\baccount management\b"), ("CRM", r"\bcrm\b"), ("HubSpot", r"\bhubspot\b"),
    ("Salesforce CRM", r"\bsalesforce\b"), ("Customer service", r"\bcustomer (service|support|care)\b"), ("SEO", r"\bseo\b"), ("Google Ads", r"\bgoogle ads|adwords\b"),
    ("Meta Ads", r"\b(meta|facebook) ads\b"), ("Content writing", r"\bcontent writ(ing|er)\b"), ("Copywriting", r"\bcopywrit(ing|er)\b"), ("Social media", r"\bsocial media\b"),
    ("Google Analytics", r"\bgoogle analytics|\bga4\b"), ("Email marketing", r"\bemail marketing\b"), ("Market research", r"\bmarket research\b"),
    # people and operations
    ("Recruitment", r"\brecruit(ment|ing)\b"), ("Onboarding", r"\bonboarding\b"), ("HRMS", r"\bhrms|hris\b"), ("Employee relations", r"\bemployee relations\b"),
    ("Labour law", r"\blabou?r laws?\b"), ("Inventory management", r"\binventory\b"), ("Supply chain", r"\bsupply chain\b"), ("Procurement", r"\bprocurement|purchasing\b"),
    ("Logistics", r"\blogistics\b"), ("Warehouse management", r"\bwarehous(e|ing)\b"), ("Vendor management", r"\bvendor management\b"), ("Six Sigma", r"\bsix sigma\b"),
    ("Lean", r"\blean (manufacturing|management|principles)\b"), ("Project management", r"\bproject management|\bpmp\b"), ("MS Office", r"\bms office|microsoft office\b"),
    # engineering trades
    ("AutoCAD", r"\bautocad\b"), ("SolidWorks", r"\bsolidworks\b"), ("CATIA", r"\bcatia\b"), ("Revit", r"\brevit\b"), ("STAAD Pro", r"\bstaad\b"),
    ("PLC", r"\bplc\b"), ("SCADA", r"\bscada\b"), ("HVAC", r"\bhvac\b"), ("Quality control", r"\bquality (control|assurance)\b|\bqa/qc\b"),
    ("ISO 9001", r"\biso ?9001\b"), ("Preventive maintenance", r"\bpreventive maintenance\b"), ("Site supervision", r"\bsite (supervision|execution)\b"),
    ("Health and safety", r"\b(ehs|hse|health and safety)\b"),
    # healthcare
    ("Patient care", r"\bpatient care\b"), ("BLS", r"\bbls\b|basic life support"), ("ACLS", r"\bacls\b"), ("ICU", r"\bicu\b|intensive care"),
    ("Nursing", r"\bnursing\b|\bgnm\b|\bb\.?sc nursing\b"), ("Medical coding", r"\bmedical coding|\bicd-?10\b"), ("Pharmacology", r"\bpharmacolog"),
    ("Clinical research", r"\bclinical (research|trials?)\b"), ("Phlebotomy", r"\bphlebotom"),
    # education
    ("Teaching", r"\bteach(ing)?\b"), ("Lesson planning", r"\blesson plan"), ("Classroom management", r"\bclassroom management\b"), ("CBSE", r"\bcbse\b"),
    ("ICSE", r"\bicse\b"), ("B.Ed", r"\bb\.?\s?ed\b"), ("Curriculum development", r"\bcurriculum\b"),
    # law, retail, hospitality, media
    ("Contract drafting", r"\b(contract|legal) drafting\b|\bdraft(ing)? contracts\b"), ("Litigation", r"\blitigation\b"), ("Legal research", r"\blegal research\b"),
    ("Corporate law", r"\bcorporate law\b"), ("Visual merchandising", r"\bvisual merchandis"), ("Retail operations", r"\bretail operations\b"),
    ("Point of sale", r"\bpos\b|point of sale"), ("Food safety", r"\bfood safety|\bhaccp\b|\bfssai\b"), ("Front office", r"\bfront office\b"),
    ("Video editing", r"\bvideo editing\b"), ("Premiere Pro", r"\bpremiere pro\b"), ("After Effects", r"\bafter effects\b"), ("Photoshop", r"\bphotoshop\b"),
    ("Canva", r"\bcanva\b"), ("Illustrator", r"\badobe illustrator\b"),
    # languages and general
    ("English communication", r"\b(english|verbal and written) communication\b|\bcommunication skills\b"), ("Hindi", r"\bhindi\b"),
    ("Driving licence", r"\bdriving licen[cs]e\b"),
]
VOCAB = list(SKILLS) + EXTRA + EVERY_FIELD


def _rx(term: str) -> str:
    for name, rx in VOCAB:
        if name.lower() == term.lower():
            return rx
    esc = re.escape(term.strip()).replace(r"\ ", r"[\s-]+")
    return rf"(?<![A-Za-z0-9]){esc}(?:s|es)?(?![A-Za-z0-9])"


def extract(jd: str, limit: int = 20) -> list[str]:
    """The posting's terms from the shared vocabulary, most mentioned first, then earliest."""
    hits = []
    for name, rx in VOCAB:
        found = list(re.finditer(rx, jd or "", re.I))
        if found:
            hits.append((-len(found), found[0].start(), name))
    return [n for *_, n in sorted(hits)][:limit]


def _resume_parts(resume: dict | str) -> tuple[str, str]:
    if isinstance(resume, str):
        return resume, ""
    body = " ".join([resume.get("headline", ""), resume.get("summary", "")] + [b.get("text", "") for b in resume.get("bullets", [])])
    return body, " ".join(resume.get("skills", []))


def coverage(terms: list[str], resume: dict | str) -> dict:
    body, skills = _resume_parts(resume)
    present, thin, missing = [], [], []
    for t in dict.fromkeys(x.strip() for x in terms if x and x.strip()):
        rx = _rx(t)
        if re.search(rx, body, re.I):
            present.append(t)
        elif re.search(rx, skills, re.I):
            thin.append(t)
        else:
            missing.append(t)
    n = len(present) + len(thin) + len(missing)
    return {"present": present, "thin": thin, "missing": missing,
            "summary": f"{len(present)} of {n} posting terms appear in your summary or bullets"
                       + (f", {len(thin)} only in your skills list" if thin else "") + "."}


def repeated(resume: dict) -> list[str]:
    """Terms used in more than half the bullets: likely stuffing."""
    bullets = [b.get("text", "") for b in resume.get("bullets", [])]
    if len(bullets) < 4:
        return []
    c = Counter()
    for b in bullets:
        for name, rx in VOCAB:
            if re.search(rx, b, re.I):
                c[name] += 1
    return [k for k, v in c.items() if v > len(bullets) / 2]
