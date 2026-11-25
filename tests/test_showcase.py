"""The website's examples come from real open roles at well-known companies, with their logos."""

from datetime import datetime, timedelta, timezone

from propelo import showcase

NOW = datetime(2026, 11, 16, 6, 0, tzinfo=timezone.utc)


def rec(company, title, geo="south", mode="hybrid", hours=5, **facts):
    return {"company": company, "title": title, "geo": geo, "workMode": mode, "location": "Bengaluru, KA, India",
            "postedAt": (NOW - timedelta(hours=hours)).isoformat(), "url": f"https://jobs.example/{company}", "source": "Greenhouse",
            "facts": facts}


LOGOS = {"amazon": "logos/a.png", "nvidia": "logos/n.png", "coinbase": "logos/c.png", "datadog": "logos/d.png", "razorpay": "logos/r.png"}


def test_top_name():
    assert showcase.top_name("Nxp") == "NXP" and showcase.top_name("cloudflare") == "Cloudflare"
    assert showcase.top_name("Northwind Labs") == ""


def test_roles_pick_real_recent_roles_one_per_company():
    rs = [rec("Amazon", "SDE II", salaryQuote="₹30-40 LPA", expQuote="3+ years", expMin=3),
          rec("Amazon", "SDE I"),
          rec("NVIDIA", "Deep learning engineer", geo="us", mode="onsite", hours=30),
          rec("Coinbase", "Backend engineer", mode="remote", locQuote="Office - Hyderabad"),  # remote but the posting says office: skipped
          rec("Datadog", "Way too long a title for the little phone mockup on the website ok"),
          rec("Razorpay", "Data analyst", hours=24 * 20),  # too old
          rec("Unknown Co", "Engineer"),
          rec("Amazon", "Scam", legit={"tier": "suspicious"})]
    picked = showcase.roles(rs, LOGOS, NOW)
    assert [p["company"] for p in picked] == ["NVIDIA", "Amazon"]  # roles outside India lead
    a = picked[1]
    assert a["title"] == "SDE II" and a["pay"] == "30–40 LPA" and a["exp"] == "3+ years" and a["logo"] == "logos/a.png"
    assert picked[0]["ago"] == "30 h ago"


def test_strip_and_fill():
    rs = [rec(c, "Engineer") for c in ("Amazon", "NVIDIA", "Coinbase", "Datadog", "Razorpay")] * 2
    tops = showcase.companies(rs, LOGOS)
    assert len(tops) == 5 and all(t["count"] == 2 for t in tops)
    assert showcase.strip_html(tops, 100) == ""  # fewer than six: no strip
    tops.append({"name": "Stripe", "count": 1, "logo": "logos/s.png", "q": "Stripe"})
    html = showcase.strip_html(tops, 32776)
    assert 'href="jobs.html?q=Amazon"' in html and "32,776 open roles" in html and "isn't affiliated" in html
    page = '<span class="nlogo" data-ex-logo="1">N</span><b data-ex-title="1">Backend engineer</b><small data-ex-cw="2">Kestrel</small><!--TOP_COMPANIES-->'
    out = showcase.render(page, [rec("Amazon", "SDE II")], LOGOS, 1, NOW)
    assert 'data-real="1"><img src="logos/a.png"' in out and ">SDE II</b>" in out
    assert ">Kestrel</small>" in out  # no second role: the illustration stays


def test_the_first_example_is_an_entry_role_in_the_four_countries_at_a_sponsor():
    def r(company, title, location, **facts):
        return {"company": company, "title": title, "geo": "", "workMode": "onsite", "location": location, "postedAt": (NOW - timedelta(hours=3)).isoformat(),
                "url": f"https://jobs.example/{company}", "source": "Greenhouse", "facts": facts}
    rs = [r("Amazon", "Senior Engineer", "Austin, TX", expMin=8, expQuote="8+ years", salaryQuote="$180,000 - $220,000 per year"),
          r("NVIDIA", "Graduate Data Analyst", "London, UK", expMin=0, expQuote="No experience needed", salaryQuote="salary $1",
            visa={"ukRegister": {"listed": True}}),
          r("Coinbase", "Engineer", "Bengaluru, India", expMin=1)]
    rs[1]["salary"] = "£35,000 - £40,000"
    picked = showcase.roles(rs, LOGOS, NOW)
    first = picked[0]
    assert first["company"] == "NVIDIA" and first["visa"] == "On the UK sponsor register" and first["exp"] == "Entry level"
    assert first["pay"] == "£35,000–£40,000 a year"
    assert picked[1]["company"] == "Amazon" and picked[1]["pay"] == "$180,000–$220,000 a year" and picked[1]["visa"] == ""
    page = '<b data-ex-title="1">x</b><small class="nvisa" data-ex-visa="1">On the UK sponsor register</small><small data-ex-visa="2">x</small>'
    out = showcase.fill(page, picked)
    assert '<small class="nvisa" data-ex-visa="1">On the UK sponsor register</small>' in out and '<small data-ex-visa="2"></small>' in out
