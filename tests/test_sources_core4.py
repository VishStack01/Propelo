"""Graduate supply for the four countries: the level tags, and the Pinpoint, Teamtailor and iCIMS readers."""

from __future__ import annotations

import pytest

from propelo import deep, discover, extract, tags
from propelo.sources import SCOUTS, icims, pinpoint, radar, teamtailor


@pytest.mark.parametrize(("title", "level"), [
    ("Graduate Scheme 2027: Technology", "Fresher"),
    ("New Grad Software Engineer", "Fresher"),
    ("Rotational Program Analyst", "Fresher"),
    ("Early Careers: Data Analyst", "Fresher"),
    ("Technology Graduate Programme", "Fresher"),
    ("Undergraduate Placement Year: Finance", "Internship"),
    ("Industrial Placement, Engineering", "Internship"),
    ("Summer Analyst 2027", "Internship"),
    ("Software Engineer Co-op", "Internship"),
    ("Junior Data Analyst", "Entry"),
    ("Entry-Level Accountant", "Entry"),
    ("Associate Software Engineer", "Entry"),
    ("Software Engineer", "Not stated"),
    ("Placement Coordinator", "Not stated"),
])
def test_early_career_titles_get_a_level(title, level):
    assert tags.level(title, {}) == level


def test_stated_years_still_decide_and_seniority_still_wins():
    assert tags.level("Graduate Software Engineer", {"expMin": 3}) == "Mid"
    assert tags.level("Senior Graduate Recruiter", {"senior": True}) == "Senior"


def test_graduate_programme_wording_counts_as_fresher_welcome():
    assert extract.extract_experience("Join our graduate programme in September 2027.").fresher_ok is True
    assert extract.extract_experience("Part of our early careers programme.").fresher_ok is True


PINPOINT = {"data": [
    {"id": "123", "title": "Graduate Analyst", "url": "https://acme.pinpointhq.com/postings/abc", "location": {"name": "London", "city": "London"},
     "workplace_type": "hybrid", "employment_type": "permanent_full_time", "first_published_at": "2026-11-20T09:00:00Z",
     "deadline_at": "2026-12-31", "description": "<p>Our 2027 graduate scheme.</p>", "key_responsibilities": "<ul><li>Model data</li></ul>",
     "key_responsibilities_header": "What you'll do", "compensation_visible": True, "compensation_minimum": 32000,
     "compensation_maximum": 36000, "compensation_currency": "GBP", "compensation_frequency": "yearly", "reference": "GA-27"},
    {"id": "124", "title": "Office Manager", "url": "https://acme.pinpointhq.com/postings/def", "location": {"city": "Leeds", "province": "West Yorkshire"},
     "workplace_type": "onsite", "compensation_visible": False, "compensation_minimum": 99999},
    {"id": "125", "title": "", "url": "https://acme.pinpointhq.com/postings/x"}]}


def test_pinpoint_reads_postings_with_pay_only_when_shown(monkeypatch):
    calls = []
    monkeypatch.setattr(pinpoint, "get_json", lambda url, **kw: calls.append(url) or PINPOINT)
    a, b = pinpoint.fetch("acme", "Acme")
    assert calls == ["https://acme.pinpointhq.com/postings.json"]
    assert (a.title, a.location, a.work_mode, a.source, a.req_id) == ("Graduate Analyst", "London", "hybrid", "Pinpoint", "GA-27")
    assert a.salary_text == "£32,000 - £36,000/year" and a.apply_by == "2026-12-31" and a.posted_at == "2026-11-20T09:00:00Z"
    assert "What you'll do" in a.description and "Model data" in a.description and "permanent full time" in a.description
    assert b.location == "Leeds, West Yorkshire" and b.salary_text == ""  # hidden pay is never shown


RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:tt="https://teamtailor.com/locations"><channel><title>Acme BV</title>
<item><title>Junior Data Engineer</title><link>https://acme.teamtailor.com/jobs/4821-junior-data-engineer</link>
<pubDate>Fri, 20 Nov 2026 09:30:04 +0100</pubDate><guid>abc-1</guid><remoteStatus>hybrid</remoteStatus>
<description>&lt;p&gt;Visa sponsorship available.&lt;/p&gt;</description>
<tt:department>Data</tt:department><tt:locations><tt:location><tt:city>Amsterdam</tt:city><tt:country>Netherlands</tt:country></tt:location>
<tt:location><tt:name>Rotterdam office</tt:name></tt:location></tt:locations></item>
<item><title>Customer Success Associate</title><link>https://acme.teamtailor.com/jobs/4822-cs</link><remoteStatus>fully</remoteStatus>
<pubDate>Thu, 19 Nov 2026 10:00:00 +0000</pubDate><description></description></item>
</channel></rss>"""


def test_teamtailor_reads_the_rss_feed(monkeypatch):
    calls = []
    monkeypatch.setattr(teamtailor, "get_text", lambda url, **kw: calls.append(url) or RSS)
    a, b = teamtailor.fetch("acme", "Acme")
    assert calls == ["https://acme.teamtailor.com/jobs.rss"]  # a short page is the last one
    assert (a.title, a.location, a.work_mode, a.req_id) == ("Junior Data Engineer", "Amsterdam, Netherlands; Rotterdam office", "hybrid", "4821")
    assert a.posted_at == "2026-11-20T08:30:04Z" and "Visa sponsorship available" in a.description
    assert b.work_mode == "remote"
    assert teamtailor.feed_url("https://careers.example.com/") == "https://careers.example.com/jobs.rss"
    with pytest.raises(ValueError):
        teamtailor.feed_url("not a/slug")


def test_teamtailor_reads_every_page_of_a_big_employer(monkeypatch):
    item = "<item><title>Role {n}</title><link>https://big.teamtailor.com/jobs/{n}-r</link></item>"
    pages = {0: 100, 100: 100, 200: 3}
    calls = []

    def page(url, **kw):
        calls.append(url)
        off = int(url.split("offset=")[1]) if "offset=" in url else 0
        return "<rss><channel>" + "".join(item.format(n=off + i) for i in range(pages[off])) + "</channel></rss>"
    monkeypatch.setattr(teamtailor, "get_text", page)
    assert len(teamtailor.fetch("big")) == 203 and calls[-1].endswith("?offset=200")


LISTING = """<ul><li class="iCIMS_JobCardItem"><div class="col-xs-6 header left"><span class="sr-only field-label">Job Locations</span>
<span> US-NY-New York</span></div><div class="col-xs-6 header right"><span title="11/20/2026 10:23 AM">5 days ago</span></div>
<div class="col-xs-12 title"><a href="https://careers-acme.icims.com/jobs/4410/graduate-analyst/job?in_iframe=1" class="iCIMS_Anchor"><h3>Graduate Analyst &amp; Associate</h3></a></div>
<div class="col-xs-12 description">Join our analyst class.</div></li>
<li class="iCIMS_JobCardItem"><div class="col-xs-12 title"><a href="https://careers-acme.icims.com/jobs/4411/volunteer/job?in_iframe=1" class="iCIMS_Anchor"><h3>Volunteer, Weekend Events</h3></a></div></li></ul>"""
DETAIL = """<html><script type="application/ld+json">{"@context": "https://schema.org", "@type": "JobPosting", "title": "Graduate Analyst",
"description": "<p>Full description. We sponsor H-1B visas.</p>", "employmentType": "FULL_TIME", "datePosted": "2026-11-20",
"validThrough": "2027-01-15T00:00:00Z", "jobLocation": {"@type": "Place", "address": {"addressLocality": "New York", "addressRegion": "NY"}}}</script></html>"""


def test_icims_reads_listing_pages_and_job_pages(monkeypatch):
    calls = []

    def get(url, **kw):
        calls.append(url)
        if "/jobs/search" in url:
            return LISTING if "pr=0" in url else LISTING  # the same roles again: the walk stops
        return DETAIL
    monkeypatch.setattr(icims, "get_text", get)
    grad, volunteer = icims.fetch("acme", "Acme")
    assert calls[:2] == ["https://careers-acme.icims.com/jobs/search?ss=1&pr=0&in_iframe=1", "https://careers-acme.icims.com/jobs/search?ss=1&pr=1&in_iframe=1"]
    assert calls[2:] == ["https://careers-acme.icims.com/jobs/4410/graduate-analyst/job?in_iframe=1"]  # only the role in a job family
    assert (grad.title, grad.location, grad.posted_at, grad.req_id) == ("Graduate Analyst & Associate", "New York, NY, United States", "2026-11-20T10:23:00Z", "4410")
    assert "We sponsor H-1B visas" in grad.description and "full time" in grad.description and grad.apply_by == "2027-01-15"
    assert volunteer.description == ""
    assert icims.base("https://uscareers-rws.icims.com/") == "https://uscareers-rws.icims.com"


def test_closed_icims_portal_gives_nothing(monkeypatch):
    monkeypatch.setattr(icims, "get_text", lambda url, **kw: '<input name="loginToAccessPortalPassword">')
    assert icims.fetch("private") == []


def test_new_sources_are_wired_in(monkeypatch):
    assert {"pinpoint", "teamtailor", "icims"} <= set(SCOUTS)
    assert {"pinpoint", "teamtailor", "icims"} <= set(deep.ATS) and {"pinpoint", "teamtailor"} <= set(discover.ATS_ORDER)
    assert radar.board_from_url("https://acme.pinpointhq.com/postings/abc") == ("pinpoint", "acme")
    assert radar.board_from_url("https://acme.teamtailor.com/jobs/1-x") == ("teamtailor", "acme")
    assert radar.board_from_url("https://careers-acme.icims.com/jobs/1/x/job") == ("icims", "acme")
    rows = deep.parse("icims", "name,slug,url,company_name\nRWS,rws,https://uscareers-rws.icims.com,RWS\nAcme,acme,https://careers-acme.icims.com,Acme\n")
    assert [r["token"] for r in rows] == ["https://uscareers-rws.icims.com", "acme"]
    monkeypatch.setattr(discover, "_get", lambda url: PINPOINT)
    got = discover.probe("pinpoint", "acme")
    assert got["titles"][:2] == ["Graduate Analyst", "Office Manager"] and got["locations"][0] == "London"
