"""The website's examples, from the real feed: top companies hiring now, with their logos, and real open roles.

`propelo site` calls `render` on the published index.html. It:

* fills the logo strip (<!--TOP_COMPANIES-->) with well-known companies (data/top_companies.json) that have
  open roles in the scan and a logo fetched from their own website (see logos.py), with each one's count;
* fills the example roles (elements with data-ex-*="N") with real open roles at those companies: title,
  company, logo, place, how long ago it was posted, the posting's own experience and pay quotes, and the
  employer's sponsor record. Roles in the US, UK, Ireland and the Netherlands come first, and among them
  entry-level roles at employers that can sponsor, so the first example fits a graduate on a visa.

Personal examples (fit scores, replies, interviews) stay illustrations and are labelled as examples. If the
scan has no suitable role, the page keeps its built-in illustration, so the site always renders.
"""

from __future__ import annotations

import html
import json
import re
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

from . import countries, pay

DATA = Path(__file__).resolve().parent / "data" / "top_companies.json"
CORE4 = {"US", "GB", "IE", "NL"}


def visa_line(r: dict) -> str:
    """The employer's sponsor record for the role's country, in a few words, or ''."""
    v = (r.get("facts") or {}).get("visa") or {}
    if v.get("status") == "no" or v.get("opt") == "no":
        return ""
    co = countries.of_record(r)
    for code, ok, words in (("GB", (v.get("ukRegister") or {}).get("listed"), "On the UK sponsor register"),
                            ("NL", (v.get("nlRegister") or {}).get("listed"), "Dutch recognised sponsor"),
                            ("IE", v.get("iePermits"), "Issued Irish work permits this year"),
                            ("US", v.get("usLca"), "Has sponsored H-1B visas"),
                            ("US", v.get("opt") == "yes", "Takes OPT and CPT")):
        if ok and code in co:
            return words
    return "Says it sponsors visas" if v.get("status") == "offers" else ""


@lru_cache(maxsize=1)
def _top() -> dict[str, str]:
    raw = json.loads(DATA.read_text(encoding="utf-8"))["companies"]
    return {k.strip().lower(): v for k, v in raw.items()}


def top_name(company: str) -> str:
    """The display name when `company` is one of the top companies, else ''."""
    return _top().get((company or "").strip().lower(), "")


def _ts(s: str) -> float:
    try:
        d = datetime.fromisoformat(str(s or "").replace("Z", "+00:00"))
        return (d if d.tzinfo else d.replace(tzinfo=timezone.utc)).timestamp()
    except ValueError:
        return 0.0


def ago(posted: str, now: datetime) -> str:
    t = _ts(posted)
    if not t:
        return ""
    h = max(0, (now.timestamp() - t) / 3600)
    return f"{max(1, int(h))} h ago" if h < 48 else f"{int(h // 24)} days ago"


def place(r: dict) -> str:
    """A short place: 'Bengaluru, hybrid', 'Remote, worldwide', 'London, UK'."""
    f = r.get("facts") or {}
    loc = re.split(r"[;|]", r.get("location") or "")[0].strip()
    loc = re.sub(r"\s*\(.*?\)", "", loc)
    if r.get("workMode") == "remote" or f.get("loc", "").startswith("remote"):
        scope = {"worldwide": "worldwide", "india": "India", "us": "US", "europe": "Europe", "apac": "Asia-Pacific"}.get(f.get("scope") or "", "")
        return "Remote" + (f", {scope}" if scope else "")
    parts = [p.strip() for p in loc.split(",") if p.strip() and not re.fullmatch(r"[A-Z]{2,3}|\d+", p.strip())]
    short = ", ".join(parts[:2]) if parts else loc
    mode = r.get("workMode") or ""
    return (short[:40] + (f", {mode}" if mode in ("hybrid",) else "")).strip(", ")


def companies(records: list[dict], logos: dict[str, str], limit: int = 18) -> list[dict]:
    """Top companies with open roles and a logo, most roles first. logos: company slug -> published logo path."""
    counts: dict[str, dict] = {}
    for r in records:
        name = top_name(r.get("company", ""))
        lg = logos.get(_slug(r.get("company", "")))
        if not name or not lg:
            continue
        c = counts.setdefault(name, {"name": name, "count": 0, "logo": lg, "q": name})
        c["count"] += 1
    return sorted(counts.values(), key=lambda c: -c["count"])[:limit]


def roles(records: list[dict], logos: dict[str, str], now: datetime, k: int = 5) -> list[dict]:
    """Real, recent, legitimate roles at top companies with a logo: one per company, a mix of places,
    preferring postings that state pay and experience (so the example quotes are the posting's own)."""
    pool = []
    for r in records:
        name = top_name(r.get("company", ""))
        lg = logos.get(_slug(r.get("company", "")))
        f = r.get("facts") or {}
        if not name or not lg or (f.get("legit") or {}).get("tier") == "suspicious" or f.get("closedQuote"):
            continue
        age_h = (now.timestamp() - _ts(r.get("postedAt"))) / 3600 if _ts(r.get("postedAt")) else 999
        if age_h > 14 * 24 or len(r.get("title", "")) > 48:
            continue
        if r.get("workMode") == "remote" and re.search(r"\boffice\b|\bon[- ]?site\b", f.get("locQuote") or "", re.I):
            continue  # the place shown and the posting's own words would disagree
        co = countries.of_record(r)
        entry = f.get("fresherOk") or (f.get("expMin") is not None and f["expMin"] <= 2)
        rank = ((0 if pay.of_role(r) else 1) + (0 if f.get("expQuote") else 1) + age_h / 240
                + (0 if co & CORE4 else 2) + (0 if visa_line(r) else 1) + (0 if entry else 1))
        pool.append((rank, r, name, lg))
    pool.sort(key=lambda x: x[0])
    picked, seen, kinds = [], set(), {}
    for rank, r, name, lg in pool:
        if name in seen:
            continue
        co = countries.of_record(r)
        kind = ("india" if r.get("geo") in ("south", "india") else "core4" if co & CORE4 else
                "remote" if r.get("workMode") == "remote" else "abroad")
        slot = kind if kind != "core4" else "core4-" + sorted(co & CORE4)[0]
        if kinds.get(slot, 0) >= (2 if kind == "core4" else 1) and len(pool) > k * 3:
            continue  # mostly the four countries Propelo covers, two from each at most, and one remote role or one elsewhere
        seen.add(name)
        kinds[slot] = kinds.get(slot, 0) + 1
        f = r.get("facts") or {}
        exp = f.get("expMin")
        quote = f.get("salaryQuote") or r.get("salary") or ""
        stated = pay.label(pay.of_role(r))  # only a pay figure we could read; a stipend or a bonus line is not the pay
        picked.append({"kind": kind, "title": r["title"], "company": name, "logo": lg, "where": place(r), "ago": ago(r.get("postedAt", ""), now),
                       "url": r.get("url", ""), "source": r.get("source", ""),
                       "exp": "" if exp is None else ("Entry level" if exp == 0 else f"{exp:g}+ years"), "expQuote": f.get("expQuote") or "",
                       "pay": stated, "payQuote": quote if stated and quote != stated else "",
                       "whereQuote": f.get("locQuote") or "", "visa": visa_line(r)})
        if len(picked) >= k:
            break
    order = {"core4": 0, "remote": 1, "abroad": 2, "india": 3}  # the four countries first
    return sorted(picked, key=lambda x: order[x["kind"]])


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")[:80]


def _logo(src: str, name: str, cls: str = "") -> str:
    return f'<img src="{html.escape(src)}" alt="" loading="lazy" width="40" height="40"{f" class={chr(34)}{cls}{chr(34)}" if cls else ""}>'


def strip_html(tops: list[dict], openings: int) -> str:
    if len(tops) < 6:
        return ""
    items = "".join(f'<a class="tc" href="jobs.html?q={html.escape(t["q"])}"><span class="tcl">{_logo(t["logo"], t["name"])}</span>'
                    f'<b>{html.escape(t["name"])}</b><small>{t["count"]:,} open {"role" if t["count"] == 1 else "roles"}</small></a>' for t in tops)
    return (f'<section id="companies" class="trust"><div class="wrap">'
            f'<h2 class="lede">Open roles right now at companies like these, around the world.</h2>'
            f'<div class="tgrid reveal">{items}</div>'
            f'<p class="fine">Counts from the last scan of {openings:,} open roles. Logos belong to their companies and link to their roles on the '
            f'job board; Propelo isn\'t affiliated with them.</p></div></section>')


_SLOT = re.compile(r'(<(\w+)\b[^>]*\bdata-ex-(logo|title|company|cw|where|ago|exp|expq|pay|payq|wq|src|visa)="(\d)"[^>]*>)(.*?)(</\2>)', re.S)


def fill(page: str, picked: list[dict]) -> str:
    def sub(m):
        open_tag, field, n = m.group(1), m.group(3), int(m.group(4)) - 1
        if n >= len(picked):
            return m.group(0)
        r = picked[n]
        val = {"title": r["title"], "company": r["company"], "cw": f'{r["company"]} · {r["where"]}', "where": r["where"], "ago": r["ago"],
               "exp": r["exp"] or "Not stated", "expq": f'“{r["expQuote"][:120]}”' if r["expQuote"] else "",
               "pay": r["pay"][:90] or "Not stated", "payq": f'“{r["payQuote"][:90]}”' if r.get("payQuote") else "", "visa": r.get("visa", ""),
               "wq": f'“{r["whereQuote"][:90]}”' if r["whereQuote"] else "", "src": f'{r["source"]} · posted {r["ago"]}'}.get(field)
        if field == "logo":
            return open_tag.replace(">", ' data-real="1">', 1) + _logo(r["logo"], r["company"]) + m.group(6)
        return open_tag + html.escape(val or "") + m.group(6)
    return _SLOT.sub(sub, page)


def render(page: str, records: list[dict], logos: dict[str, str], openings: int, now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    page = page.replace("<!--TOP_COMPANIES-->", strip_html(companies(records, logos), openings))
    return fill(page, roles(records, logos, now))
