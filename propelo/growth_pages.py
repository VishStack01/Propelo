"""Pages that bring people in from search and from shared links, built from each scan at no cost.

* `data/sponsors-uk.txt` and `data/sponsors-nl.txt`: the official sponsor registers as plain text, for the free
  sponsor check page (website/sponsor-check.html), which searches them in the browser.
* `visa-jobs.html` and one page per country (`visa-jobs-uk.html`, ...): recent junior and mid-level roles whose
  employer is on a sponsor register or whose posting says it sponsors or takes OPT/CPT, for the four countries
  Propelo covers (UK, US, Ireland, Netherlands). A page never lists a role that says it cannot sponsor. A page shows
  the newest MAX_ROWS and says how many matched in all.
* `lists/<country>.md`: the same lists as Markdown tables, for a public "sponsor jobs" list on GitHub.

Every list states what the signal is and that a register listing is not a promise for one role.
"""

from __future__ import annotations

import csv
import io
import json
import re
from datetime import datetime, timezone
from html import escape
from pathlib import Path

from . import countries


MAX_ROWS = 150
MAX_AGE_DAYS = 30
# (page slug, ISO code, name in a sentence, what counts as a signal there)
COUNTRIES = [
    ("uk", "GB", "the UK", "The employer is on the Home Office register of licensed sponsors (Skilled Worker route)."),
    ("usa", "US", "the United States", "The employer has certified H-1B applications in the latest US Department of Labor data, or the posting says it sponsors, takes OPT or CPT, or uses E-Verify."),
    ("ireland", "IE", "Ireland", "The employer was issued employment permits this year, or the posting says it sponsors."),
    ("netherlands", "NL", "the Netherlands", "The employer is on the Dutch immigration service's register of recognised sponsors, or the posting says it sponsors."),
]
TITLE = {"uk": "UK", "usa": "US", "netherlands": "Netherlands", "ireland": "Ireland"}
# The job board's visa filter values that match each country's signal (site_app.html, `vs`).
BOARD_SIGNALS = {"GB": "uk%7Csponsors", "US": "us%7Copt%7Ceverify%7Csponsors", "IE": "ie%7Csponsors", "NL": "nl%7Csponsors"}
# Pages from before Propelo narrowed to four countries: kept as redirects so old links still land somewhere.
RETIRED = ("canada", "australia", "germany")


def sponsor_data(feed_dir: Path, out: Path) -> dict:
    """Write the registers the sponsor check page searches. Returns how many employers each file holds."""
    counts = {"uk": 0, "nl": 0}
    data = out / "data"
    data.mkdir(parents=True, exist_ok=True)
    uk = feed_dir / "uk-sponsors.csv"
    if uk.exists():
        seen, lines = set(), []
        for r in csv.DictReader(io.StringIO(uk.read_bytes().decode("utf-8-sig", errors="replace"))):
            route, name = (r.get("Route") or "").strip(), re.sub(r"[\t\r\n]+", " ", (r.get("Organisation Name") or "").strip())
            if not name or (route and "skilled worker" not in route.lower()) or name.lower() in seen:
                continue
            seen.add(name.lower())
            rating = re.search(r"\(([AB]) rating\)", r.get("Type & Rating") or "")
            lines.append("\t".join([name, re.sub(r"[\t\r\n]+", " ", (r.get("Town/City") or "").strip()), f"{rating.group(1)} rating" if rating else ""]))
        if len(lines) >= 1000:
            (data / "sponsors-uk.txt").write_text("\n".join(sorted(lines, key=str.lower)) + "\n", encoding="utf-8")
            counts["uk"] = len(lines)
    for code, fname in (("us", "us-sponsors.csv"), ("ca", "ca-sponsors.csv"), ("ie", "ie-sponsors.csv")):
        counts[code] = 0
        src = feed_dir / fname
        if src.exists():
            rows = [(re.sub(r"[\t\r\n]+", " ", (r.get("name") or "").strip()), r.get("n") or "") for r in csv.DictReader(io.StringIO(src.read_bytes().decode("utf-8-sig", errors="replace")))]
            rows = [x for x in rows if x[0]]
            if len(rows) >= 300:
                (data / f"sponsors-{code}.txt").write_text("\n".join(f"{n}\t\t{c}" for n, c in rows) + "\n", encoding="utf-8")
                counts[code] = len(rows)
    nl = feed_dir / "nl-sponsors.csv"
    if nl.exists():
        lines = sorted({re.sub(r"[\t\r\n]+", " ", (r.get("name") or "").strip()) for r in csv.DictReader(io.StringIO(nl.read_bytes().decode("utf-8-sig", errors="replace")))} - {""},
                       key=str.lower)
        if len(lines) >= 1000:
            (data / "sponsors-nl.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
            counts["nl"] = len(lines)
    return counts


def signal(r: dict, code: str) -> str:
    """Why a role is on a sponsor list, in a few words, or "" when it doesn't belong there."""
    v = (r.get("facts") or {}).get("visa") or {}
    if v.get("status") == "no" or v.get("opt") == "no":
        return ""
    if v.get("status") == "offers":
        return "Says it sponsors visas"
    if code == "GB" and (v.get("ukRegister") or {}).get("listed"):
        return "UK licensed sponsor"
    if code == "NL" and (v.get("nlRegister") or {}).get("listed"):
        return "Dutch recognised sponsor"
    if code == "US" and v.get("usLca"):
        return "Has sponsored H-1B"
    if code == "CA" and v.get("caLmia"):
        return "Positive LMIA employer"
    if code == "IE" and v.get("iePermits"):
        return "Issued work permits this year"
    if code == "US" and v.get("opt") == "yes":
        return "Takes OPT / CPT"
    if code == "US" and v.get("eVerify"):
        return "Uses E-Verify"
    return ""


def _where(r: dict) -> list[str]:
    """A record's countries, read again from its location ("Holland, Michigan" is in the US)."""
    return sorted(countries.of_record(r))


_NOT_A_JOB = re.compile(r"\b(volunteers?|volunteering|unpaid)\b", re.I)


def pick(records: list[dict], code: str, now: datetime) -> list[dict]:
    """Recent junior and mid-level roles in a country with a sponsorship signal, newest first, a few per employer.
    All of them: the page shows the first MAX_ROWS and says how many there are."""
    rows, per = [], {}
    for r in records:
        if code not in _where(r) or (r.get("facts") or {}).get("senior") or (r.get("facts") or {}).get("closedQuote"):
            continue
        if ((r.get("facts") or {}).get("legit") or {}).get("tier") == "suspicious" or r.get("via") == "board":
            continue  # only roles read from the employer's own careers page
        if _NOT_A_JOB.search(r.get("title") or ""):
            continue  # volunteer and unpaid places are not what someone needing a work visa is looking for
        named = countries.named(r.get("title") or "")
        if named and code not in named:
            continue  # "relocation to New Zealand", "Field Operations Manager, APJ (Singapore)": hired elsewhere
        why = signal(r, code)
        if not why:
            continue
        try:
            posted = datetime.fromisoformat(str(r.get("postedAt") or "").replace("Z", "+00:00"))
            posted = posted if posted.tzinfo else posted.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        if (now - posted).days > MAX_AGE_DAYS:
            continue
        n = per.get(r["company"], 0)
        if n >= 4:  # one employer never fills the page
            continue
        per[r["company"]] = n + 1
        rows.append({"id": r["id"], "title": r["title"], "company": r["company"], "location": r.get("location", ""), "posted": posted,
                     "why": why, "salary": r.get("salary") or "", "url": r["url"]})
    rows.sort(key=lambda x: x["posted"], reverse=True)
    return rows


def _shell(site_dir: Path) -> tuple[str, str, str] | None:
    """(head up to the page's own styles, the menu, the footer) from the website's own pages."""
    src = site_dir / "check.html"
    if not src.is_file():
        return None
    t = src.read_text(encoding="utf-8")
    try:
        return t[:t.index("<style>")], t[t.index('<a class="skip"'):t.index('<main id="main"')], t[t.index("<footer>"):t.index("</footer>") + len("</footer>")]
    except ValueError:
        return None


STYLE = """<style>
.vj{padding-block:56px 96px}
.vj h1{font:500 clamp(36px,5vw,64px)/1.06 var(--font);letter-spacing:-.04em;color:var(--ink);max-width:18ch}
.vj .sub{margin-top:18px;max-width:42em}
.vj .meta{margin-top:10px;font-size:14.5px;color:var(--muted)}
.vj .acts{display:flex;gap:10px;flex-wrap:wrap;margin-top:22px}
.vj-tabs{display:flex;gap:8px;flex-wrap:wrap;margin-top:28px}
.vj-tabs a{display:inline-flex;align-items:center;height:38px;padding:0 14px;border-radius:999px;box-shadow:inset 0 0 0 1.5px var(--line-2);font:500 15px var(--font);color:var(--ink)}
.vj-tabs a[aria-current]{background:var(--ink);color:var(--page);box-shadow:none}
.vj-list{margin-top:24px;display:grid;gap:10px}
.vj-row{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:6px 16px;background:var(--paper);border-radius:var(--r-ctl);box-shadow:inset 0 0 0 1px var(--line);padding:14px 16px}
.vj-row a{font-weight:600;color:var(--ink)}
.vj-row a:hover{text-decoration:underline}
.vj-row .co{color:var(--muted);font-size:15px}
.vj-row .tag{justify-self:end;align-self:start;font-size:13.5px;font-weight:600;color:var(--ink);background:var(--lav-t);border-radius:999px;padding:4px 10px;white-space:nowrap}
.vj-row .age{justify-self:end;font-size:13.5px;color:var(--muted)}
.vj-note{margin-top:28px;background:var(--sand);border-radius:var(--r-card);padding:20px 22px;max-width:48em}
.vj-cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:14px;margin-top:28px}
.vj-card{background:var(--paper);border-radius:var(--r-card);box-shadow:inset 0 0 0 1px var(--line);padding:20px}
.vj-card b{display:block;font:600 20px/1.3 var(--font);color:var(--ink)}
.vj-card span{display:block;margin-top:6px;color:var(--muted);font-size:15px}
@media (max-width:600px){.vj{padding-block:28px 64px}.vj-row{grid-template-columns:1fr}.vj-row .tag,.vj-row .age{justify-self:start}}
</style>
</head>
"""


def _head(base_head: str, title: str, desc: str) -> str:
    h = re.sub(r"<title>.*?</title>", lambda _: f"<title>{escape(title)}</title>", base_head, count=1, flags=re.S)
    h = re.sub(r'<meta name="description" content="[^"]*">', lambda _: f'<meta name="description" content="{escape(desc, quote=True)}">', h, count=1)
    h = re.sub(r'<meta property="og:title" content="[^"]*">', lambda _: f'<meta property="og:title" content="{escape(title, quote=True)}">', h, count=1)
    return re.sub(r'<meta property="og:description" content="[^"]*">', lambda _: f'<meta property="og:description" content="{escape(desc, quote=True)}">', h, count=1)


def _ago(d: datetime, now: datetime) -> str:
    days = (now - d).days
    return "today" if days <= 0 else "yesterday" if days == 1 else f"{days} days ago"


def visa_pages(records: list[dict], out: Path, site_dir: Path, scan_at: datetime) -> list[str]:
    """Write the visa-jobs pages and Markdown lists. Returns the HTML page names written (for the sitemap)."""
    shell = _shell(site_dir)
    if not shell:
        return []
    base_head, nav, footer = shell
    when = f"{scan_at.day} {scan_at:%B %Y}"
    picked = {slug: pick(records, code, scan_at) for slug, code, _, _ in COUNTRIES}
    def tabs(cur: str) -> str:
        links = []
        for s, _, _, _ in COUNTRIES:
            here = ' aria-current="page"' if s == cur else ""
            links.append(f'<a href="visa-jobs-{s}.html"{here}>{TITLE[s]} <span style="opacity:.6">&nbsp;{len(picked[s]):,}</span></a>')
        return '<nav class="vj-tabs" aria-label="Country">' + "".join(links) + "</nav>"
    tail = '\n<script src="assets/site.js"></script>\n</body>\n</html>\n'
    pages = []
    (out / "lists").mkdir(exist_ok=True)
    for slug, code, name, rule in COUNTRIES:
        found = picked[slug]
        rows = found[:MAX_ROWS]
        title = f"{TITLE[slug]} jobs at employers that can sponsor a visa ({when}) | Propelo"
        desc = (f"{len(found):,} recent entry and mid-level roles in {name} with a sponsorship signal, read from company career pages. "
                f"Updated every hour. Free.")
        shown = (f"{len(found):,} roles" if len(found) <= MAX_ROWS else
                 f'Newest {MAX_ROWS} of {len(found):,} roles (<a href="jobs.html?co={code}&amp;vs={BOARD_SIGNALS[code]}">see them all on the job board</a>)')
        items = "".join(
            f'<div class="vj-row"><div><a href="jobs.html#/job/{escape(r["id"], quote=True)}">{escape(r["title"])}</a>'
            f'<div class="co">{escape(r["company"])} · {escape(r["location"][:80])}{" · " + escape(r["salary"]) if r["salary"] else ""}</div></div>'
            f'<div><span class="tag">{escape(r["why"])}</span><div class="age">{_ago(r["posted"], scan_at)}</div></div></div>' for r in rows)
        if not rows:
            items = '<p class="vj-note">No recent role here carries a sponsorship signal right now. The job board lists every role in this country.</p>'
        ld = {"@context": "https://schema.org", "@type": "ItemList", "name": f"{TITLE[slug]} jobs with a sponsorship signal", "numberOfItems": len(rows),
              "itemListElement": [{"@type": "ListItem", "position": i + 1, "name": f'{r["title"]} at {r["company"]}', "url": f'jobs.html#/job/{r["id"]}'}
                                  for i, r in enumerate(rows[:30])]}
        body = (f'<body data-page="visa-jobs">\n{nav}<main id="main" class="vj"><div class="wrap">'
                f'<h1>{TITLE[slug]} jobs at employers that can <mark>sponsor you</mark></h1>'
                f'<p class="sub">Recent entry and mid-level roles in {name}, read straight from company career pages. {escape(rule)} '
                f'Roles that say they cannot sponsor are left out.</p>'
                f'<p class="meta">{shown} · updated {when} · a signal means the employer can sponsor, not that this role is sponsored: ask before you apply.</p>'
                f'<div class="acts"><a class="btn" data-app="/signup?src=visa-{slug}" href="https://app.propelo.org/signup?src=visa-{slug}">Match these to my resume, free<svg><use href="#i-right"/></svg></a>'
                f'<a class="btn light" href="jobs.html?co={code}">All {TITLE[slug]} roles</a>'
                + (f'<a class="btn light" href="sponsor-check.html?country={ {"GB": "uk", "NL": "nl", "US": "us", "CA": "ca", "IE": "ie"}[code] }">Check one employer</a>' if code in ("GB", "NL", "US", "CA", "IE") else "") + "</div>"
                f'{tabs(slug)}<div class="vj-list">{items}</div></div></main>\n{footer}\n'
                f'<script type="application/ld+json">{json.dumps(ld, separators=(",", ":"))}</script>')
        fname = f"visa-jobs-{slug}.html"
        (out / fname).write_text(_head(base_head, title, desc) + STYLE + body + tail, encoding="utf-8")
        pages.append(fname)
        md = [f"# {TITLE[slug]} jobs at employers that can sponsor a visa", "",
              f"Updated {when} by [Propelo](https://propelo.org/?src=github-list). {rule} A signal means the employer can sponsor, not that this role is sponsored.", "",
              "| Role | Employer | Location | Signal | Posted |", "| --- | --- | --- | --- | --- |"]
        md += [f'| [{r["title"].replace("|", "/")}]({r["url"]}) | {r["company"].replace("|", "/")} | {r["location"][:60].replace("|", "/")} | {r["why"]} | {r["posted"]:%d %b} |'
               for r in rows]
        (out / "lists" / f"{slug}.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    total = sum(len(v) for v in picked.values())
    cards = "".join(f'<a class="vj-card" href="visa-jobs-{s}.html"><b>{TITLE[s]}</b><span>{len(picked[s]):,} recent roles with a sponsorship signal</span></a>' for s, _, _, _ in COUNTRIES)
    title = "Jobs abroad at employers that can sponsor your visa | Propelo"
    desc = (f"{total:,} recent entry and mid-level roles in the UK, US, Ireland and the Netherlands with a sponsorship signal, "
            "from company career pages and official sponsor registers. Updated every hour.")
    body = (f'<body data-page="visa-jobs">\n{nav}<main id="main" class="vj"><div class="wrap">'
            '<h1>Jobs abroad at employers that can <mark>sponsor you</mark></h1>'
            '<p class="sub">Propelo reads company career pages every hour and checks each role against official sponsor registers and '
            'the posting\'s own words. Pick a country.</p>'
            f'<p class="meta">{total:,} roles · updated {when}</p>'
            '<div class="acts"><a class="btn" data-app="/signup?src=visa-jobs" href="https://app.propelo.org/signup?src=visa-jobs">Match roles to my resume, free<svg><use href="#i-right"/></svg></a>'
            '<a class="btn light" href="sponsor-check.html">Check one employer</a></div>'
            f'<div class="vj-cards">{cards}</div>'
            '<div class="vj-note"><b>How to read these lists.</b> A register listing or a line in a posting shows the employer can sponsor. It is not a promise for one role, '
            'and visa rules change. Ask the employer before you apply, and check official guidance for your own case.</div></div></main>\n' + footer)
    (out / "visa-jobs.html").write_text(_head(base_head, title, desc) + STYLE + body + tail, encoding="utf-8")
    for slug in RETIRED:
        (out / f"visa-jobs-{slug}.html").write_text(redirect_page("visa-jobs.html"), encoding="utf-8")
    return ["visa-jobs.html"] + pages


def redirect_page(to: str, label: str = "") -> str:
    """A static page that sends the visitor on (GitHub Pages has no server redirects) and stays out of search."""
    to_attr = escape(to, quote=True)
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Moved | Propelo</title>'
            f'<meta name="robots" content="noindex"><link rel="canonical" href="{to_attr}">'
            f'<meta http-equiv="refresh" content="0; url={to_attr}">'
            f'<script>location.replace({json.dumps(to)} + location.search + location.hash)</script></head>'
            f'<body><p>This page moved: <a href="{to_attr}">{escape(label or to)}</a>.</p></body></html>\n')
