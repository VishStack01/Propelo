"""Tags for the job board: level, contract type, category and skills.

Everything is read from the title and the posting text with small, explicit
rules, so a tag can always be traced back to a word in the posting.
"""

from __future__ import annotations

import re

CATEGORIES = [
    ("AI & ML", r"\b(ai|a\.i\.|ml|machine learning|llm|genai|gen ai|generative|deep learning|nlp|computer vision|data scientist|applied scientist|prompt|agentic|agents?)\b"),
    ("Data", r"\b(data (engineer|analyst|platform)|analytics|analyst|bi developer|etl|power bi|snowflake|dbt)\b"),
    ("Backend", r"\b(backend|back[- ]end|server[- ]side|api engineer|platform engineer|distributed systems)\b"),
    ("Frontend", r"\b(frontend|front[- ]end|ui engineer|web developer|react developer)\b"),
    ("Full stack", r"\b(full[- ]?stack|fullstack)\b"),
    ("Mobile", r"\b(mobile|android|ios|react native|flutter|swift|kotlin)\b"),
    ("DevOps & Cloud", r"\b(devops|sre|site reliability|cloud|infrastructure|kubernetes|platform ops)\b"),
    ("Security", r"\b(security|appsec|iam|soc analyst|penetration)\b"),
    ("QA", r"\b(qa|quality assurance|test engineer|sdet|tester|automation tester)\b"),
    ("Design", r"\b(designer|design engineer|ux|ui/ux|product design)\b"),
    ("Product", r"\b(product manager|product owner|apm|program manager)\b"),
    ("Solutions & support", r"\b(solutions? engineer|forward deployed|customer engineer|support engineer|implementation|sales engineer|developer success)\b"),
    ("Research", r"\b(research (engineer|scientist)|researcher)\b"),
]

# Top-level job families (the categories big job boards use). Checked in order, first match wins:
# 1. unambiguous role phrases, 2. engineering role nouns (so "Backend Engineer, Credit Cards" stays engineering),
# 3. business families by their words, 4. generic data and research words, 5. generic IT and testing words.
_FAMILY_RULES = [
    ("Sales & Accounts", r"\b(sales engineers?|solutions? (engineer|consultant|architect)s?|pre-?sales)\b"),
    ("Product & Design", r"\b(product (manager|owner|lead|management|designer)s?|apm|associate product manager|designers?|ux|ui/ux|user research(ers?)?)\b"),
    ("AI & Data", r"\b(machine learning|ml|ai|a\.i\.|genai|gen ai|llms?|llmops|mlops|nlp|computer vision|deep learning|"
                  r"data (scientists?|engineers?|analysts?|architects?|platform)|applied scientists?|analytics engineers?)\b"),
    ("Finance & Strategy", r"\b(business analysts?|founder'?s office|chief of staff)\b"),
    # Fields outside tech and business, matched by their own role nouns before the generic "engineer" rule,
    # so a civil engineer, a staff nurse or a school teacher lands in their own family.
    ("Healthcare", r"\b(nurses?|nursing|staff nurse|physicians?|doctors?|medical officers?|surgeons?|pharmacists?|pharmacy (assistants?|technicians?|managers?)|dentists?|dental|"
                   r"physiotherapists?|therapists?|paramedics?|radiographers?|radiolog(y|ists?)|sonographers?|lab(oratory)? technicians?|phlebotomists?|"
                   r"midwi(fe|ves)|optometrists?|dietitians?|nutritionists?|caregivers?|care assistants?|patient care|clinical research (associates?|coordinators?)|"
                   r"medical (coders?|coding|scribes?|transcriptionists?|representatives?)|healthcare assistants?|ward (boys?|assistants?)|icu nurses?)\b"),
    ("Education", r"\b(teachers?|teaching|tutors?|lecturers?|professors?|faculty|instructors?|educators?|trainers?|school principal|headmaster|"
                  r"curriculum (developers?|designers?)|academic (counsell?ors?|coordinators?)|school (teachers?|counsell?ors?|coordinators?|administrators?)|librarians?|counsell?ors?|pgt|tgt|prt)\b"),
    ("Legal", r"\b(lawyers?|(?<!developer )advocates?|attorneys?|paralegals?|legal|counsel|company secretary|cs executive|litigation|contracts? manager)\b"),
    ("Engineering & Trades", r"\b((mechanical|civil|electrical|electronics|chemical|structural|production|manufacturing|process|maintenance|plant|site|"
                             r"mining|petroleum|automobile|automotive|hvac|mep|instrumentation|piping|metallurg(y|ical)|aerospace|marine|safety|ehs|hse|"
                             r"quality control|qc|qa/qc) (engineers?|engineering|technicians?|supervisors?|inspectors?|managers?)|(design|r&d|tooling) engineers?|"
                             r"draughts(man|person)|drafts(man|person)|foreman|quantity surveyors?|site supervisors?|electricians?|plumbers?|welders?|fitters?|"
                             r"machinists?|mechanics?|carpenters?|machine operators?|cnc|autocad|solidworks|field service technicians?)\b"),
    ("Retail & Hospitality", r"\b(retail|store (managers?|associates?|executives?)|cashiers?|showroom|baristas?|chefs?|cooks?|commis|kitchen|(cabin|hotel|f&b) stewards?|"
                             r"waiters?|waitstaff|housekeeping|front office|front desk|hotel|restaurant|hospitality|guest relations|f&b|food and beverage|"
                             r"beauticians?|stylists?|salon|spa|cabin crew|flight attendants?|travel (consultants?|agents?))\b"),
    ("Media & Writing", r"\b(journalists?|reporters?|newsroom|editors?|editorial|video editors?|videographers?|photographers?|animators?|motion graphics|"
                        r"illustrators?|translators?|interpreters?|voice[- ]over|technical writers?|(?<!content )writers?|anchors?|producers?)\b"),
    ("Software Engineering", r"\b(engineers?|engineering|developers?|programmers?|sde|swe|devops|sre|architects?|qa|sdet|testers?|"
                             r"full[- ]?stack|backend|frontend|front[- ]end|back[- ]end|mobile|android|ios|firmware|embedded|robotics|cyber(security)?|"
                             r"tests? analysts?|qa analysts?|testing|test automation)\b"),
    ("Finance & Strategy", r"\b(finance|financial|accountants?|accounting|accounts (payable|receivable|executives?|officers?|assistants?|clerks?)|audit(or)?s?|tax|treasury|fp&a|controllers?|payroll|"
                           r"banking|loans?|credit|underwriters?|fraud|kyc|aml|pricing|strategy|strategists?|investment|investor relations|"
                           r"equity|trading|quant(itative)?|risk|compliance|legal|counsel|real estate)\b"),
    ("Marketing & Growth", r"\b(marketing|marketers?|growth|seo|sem|content|copywriters?|brand|social media|community (manager|lead)s?|"
                           r"communications|public relations|demand gen(eration)?|market research|merchandis(er|ers|ing))\b"),
    ("Sales & Accounts", r"\b(sales|account executives?|account managers?|business development|bdr|sdr|bde|partnerships?|customer success|"
                         r"key accounts?|inside sales|relationship managers?)\b"),
    ("Product & Design", r"\b(program managers?|pmo|creative|design)\b"),
    ("Operations & People", r"\b(operations|operational|supply chain|logistics|procurement|customer support|customer service|support|helpdesk|help desk|"
                            r"service desk|people (partner|operations)|hr|human resources|recruiters?|recruiting|talent acquisition|office managers?|"
                            r"admin(istrator)?|executive assistants?|process associates?|receptionists?|front office executives?|back office|data entry|"
                            r"office (assistants?|executives?|boys?)|warehouse|pickers?|packers?|forklift|drivers?|delivery (executives?|associates?|partners?|boys?)|"
                            r"riders?|couriers?|dispatch|security guards?|facility|facilities|field (executives?|officers?)|telecallers?|tele[- ]?callers?|call cent(er|re)|bpo|voice process)\b"),
    ("AI & Data", r"\b(data|analytics|analysts?|scientists?|research(ers?)?|intelligence|bi)\b"),
    ("Software Engineering", r"\b(automation|security|quality|tests?|testing|sap|erp|salesforce|servicenow|systems?|infrastructure|it|technical|platform)\b"),
]
FAMILIES = list(dict.fromkeys(name for name, _ in _FAMILY_RULES))
_DATA_ENGINEERING = re.compile(r"\bdata\b", re.I)

SKILLS = [
    ("Python", r"\bpython\b"), ("Java", r"\bjava\b(?!script)"), ("JavaScript", r"\bjavascript\b"), ("TypeScript", r"\btypescript\b"),
    ("React", r"\breact(\.js|js)?\b(?! native)"), ("Next.js", r"\bnext\.?js\b"), ("Node.js", r"\bnode(\.js|js)?\b"), ("Go", r"\b(golang|go \(golang\)|in go\b)"),
    ("Rust", r"\brust\b"), ("C++", r"c\+\+"), ("Kotlin", r"\bkotlin\b"), ("Swift", r"\bswift\b"), ("Flutter", r"\bflutter\b"),
    ("React Native", r"\breact native\b"), ("SQL", r"\bsql\b"), ("PostgreSQL", r"\bpostgres(ql)?\b"), ("AWS", r"\baws\b"),
    ("GCP", r"\b(gcp|google cloud)\b"), ("Azure", r"\bazure\b"), ("Kubernetes", r"\bkubernetes|k8s\b"), ("Docker", r"\bdocker\b"),
    ("PyTorch", r"\bpytorch\b"), ("TensorFlow", r"\btensorflow\b"), ("LLMs", r"\bllms?\b|large language model"), ("RAG", r"\brag\b|retrieval[- ]augmented"),
    ("LangChain", r"\blangchain|langgraph\b"), ("Figma", r"\bfigma\b"), ("Spark", r"\bspark\b"), ("Kafka", r"\bkafka\b"),
    ("Django", r"\bdjango\b"), ("FastAPI", r"\bfastapi\b"), ("Spring", r"\bspring( boot)?\b"), ("GraphQL", r"\bgraphql\b"),
]

_INTERN = re.compile(r"\bintern(ship)?\b|\btrainee\b|\bapprentice", re.I)
_CONTRACT = re.compile(r"\bcontract(or)?\b|\bfreelance\b|\bfixed[- ]term\b", re.I)
_PART = re.compile(r"\bpart[- ]time\b", re.I)
_VISA = re.compile(r"visa sponsorship (is )?(available|provided|offered)|we (can |will )?sponsor (your )?visa|relocation and visa", re.I)
_NO_VISA = re.compile(r"(no|not|unable to|cannot|can't|do not) (offer |provide )?(visa )?sponsor", re.I)
_RELOCATION = re.compile(r"relocation (support|assistance|package|bonus)", re.I)


def level(title: str, facts: dict) -> str:
    if _INTERN.search(title or ""):
        return "Internship"
    e = facts.get("expMin")
    if facts.get("senior") or (e is not None and e >= 5):
        return "Senior"
    if e is None:
        return "Fresher" if facts.get("fresherOk") else "Not stated"
    if e == 0:
        return "Fresher"
    if e <= 2:
        return "Entry"
    return "Mid"


def job_type(title: str, text: str) -> str:
    blob = f"{title}\n{text[:3000]}"
    if _INTERN.search(title or ""):
        return "Internship"
    if _PART.search(blob):
        return "Part-time"
    if _CONTRACT.search(title or "") or re.search(r"\b(employment type|job type)\W+(contract|freelance)", blob, re.I):
        return "Contract"
    return "Full-time"


def categories(title: str) -> list[str]:
    return [name for name, rx in CATEGORIES if re.search(rx, title or "", re.I)][:2]


# Families for fields outside tech. A title that also names software, data or chip work stays in the tech
# families ("Senior Software Engineer, Retail", "ASIC Design Engineer", "Developer Advocate").
NON_TECH = {"Healthcare", "Education", "Legal", "Engineering & Trades", "Retail & Hospitality", "Media & Writing"}
_TECH_GUARD = re.compile(r"\b(software|developer|devops|sre|data|backend|back[- ]end|frontend|front[- ]end|full[- ]?stack|cloud|platform|"
                         r"machine learning|ml|ai|security|firmware|embedded|asic|fpga|rtl|vlsi|soc|silicon|chip|cpu|gpu|analog|logic|"
                         r"physical design|design verification|verification|layout|sde|swe|qa|test)\b", re.I)


def family(title: str) -> str:
    """The job family for a title (Simplify-style top-level categories), or "Other"."""
    t = title or ""
    tech = bool(_TECH_GUARD.search(t))
    for name, rx in _FAMILY_RULES:
        if tech and name in NON_TECH:
            continue
        if re.search(rx, t, re.I):
            return name
    if _DATA_ENGINEERING.search(t):
        return "AI & Data"
    if _INTERN.search(t) or re.search(r"\b(graduate|trainee)\b", t, re.I):
        return "Software Engineering" if re.search(r"\b(tech|software|engineering|it)\b", t, re.I) else "Other"
    return "Other"


def skills(title: str, text: str, limit: int = 6) -> list[str]:
    blob = f"{title}\n{text}"
    found = []
    for name, rx in SKILLS:
        m = re.search(rx, blob, re.I)
        if m:
            found.append((m.start(), name))
    return [n for _, n in sorted(found)][:limit]


def perks(text: str) -> list[str]:
    out = []
    if _VISA.search(text or "") and not _NO_VISA.search(text or ""):
        out.append("Visa sponsorship")
    if _RELOCATION.search(text or ""):
        out.append("Relocation")
    return out


def pay_tier(facts: dict) -> str:
    """From the pay the posting states (never estimated): "20+" (20 LPA or more at the top
    of the range), "10-20", "under-10", or "" when no pay is stated."""
    hi = facts.get("salaryHigh")
    if hi is None:
        return ""
    return "20+" if hi >= 20 else "10-20" if hi >= 10 else "under-10"


def tag(title: str, text: str, facts: dict) -> dict:
    from .signals import archetype  # signals imports this module
    return {"level": level(title, facts), "type": job_type(title, text), "family": family(title), "categories": categories(title),
            "skills": skills(title, text), "perks": perks(text), "archetype": archetype(title, text), "payTier": pay_tier(facts)}
