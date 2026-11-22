# 01 · Product understanding

Written from the code, the running app (local copy of `main`), the public site built from the live feed, the
GitHub Actions history and the published feed. 22 Nov 2026.

## What this audit could and could not inspect

| source | inspected? | how |
| --- | --- | --- |
| Source code (app, worker, scanner, site, extension, mobile shell) | Yes | Read and run |
| Web app (every page, every dashboard tab) | Yes, **local copy** | Ran `main` on PostgreSQL 16 with dev mail; drove it with a browser |
| Public site (landing, jobs, docs, scam check, demo) | Yes, **local build** | Built with `careeros site` from the live feed release |
| Live job feed | Yes | Downloaded `feed-latest` release assets (22 Nov 01:32 UTC: 95,212 roles) |
| GitHub Actions (scan, tests, security, pages) | Yes | Run history and logs |
| Production app (`app.propelo.org` / Render) | **No** | The audit environment's network can't reach it; health, env vars, DB plan, backups unknown |
| DNS for propelo.org, GitHub Pages custom domain | **No** | Not reachable / API path not permitted |
| Razorpay, Dodo, SMTP, Google, LinkedIn accounts | **No** | No credentials (by design); flows tested with signed test webhooks and dev mail |
| Mobile app builds (Android/iOS) | **No** | Shell code read only; no device or store build |
| Chrome extension in a real browser profile | Partial | Unit tests and code; not installed in a real Chrome profile here |
| Firefox, Safari/WebKit, Edge | **No** | Only Chromium is available in this environment |

## What the product does

Propelo is an AI job-search service. It reads open roles straight from employers' own career pages
(Greenhouse, Lever, Ashby, Workday, SmartRecruiters, Workable and others: 1,842 boards, 5,041 companies tracked,
95,212 open roles on 22 Nov), checks each role against a person's rules and real resume with a quote from the
posting, and helps them apply truthfully: tailored resumes and answers that only use what is true, an autofill
extension that never presses Submit, an optional auto-apply agent that runs on the person's own computer, a
pipeline, follow-ups and interview preparation. Since 2.8 it also states what each posting says about visa
sponsorship and, for UK roles, whether the employer is on the Home Office sponsor register.

## Who it is for

| customer | what they buy | status |
| --- | --- | --- |
| Job seekers in India (freshers, early-career) | Free; Pro ₹499 / Ultra ₹1,199 a month; Interview Guarantee ₹4,999; Job Guarantee (8% of salary after joining) | Built |
| Job seekers abroad (incl. Indian graduates on post-study visas) | Same plans in dollars ($22.50 / $48.50) | Built |
| Study-abroad consultancies and college placement cells | Branded portal with student seats: Starter ₹14,999 (25), Growth ₹29,999 (50), Plus ₹44,999 (100) per 30 days | Built in 2.8; no customers yet |
| Recruiting agencies | Filtered roles feed (CSV/JSON, key) ₹4,999 / $99 per 30 days | Built in 2.8; no customers yet |

## The problem it solves

Applying is slow and noisy: portals repost stale roles, auto-apply tools spray applications that get no
interviews and invent resume lines, and international graduates waste applications on employers that can't
sponsor them. Propelo's position is "the honest one": roles from the employer's own site, a quote for every
decision, nothing invented, nothing submitted below the person's apply line.

## Main journeys (detail in 03)

1. Visitor → site → sign up → confirm email → resume and settings → first matches → apply (kit, extension or agent).
2. Visitor → pricing → checkout (Razorpay / Dodo) → plan on → faster matching and more AI.
3. Member → Interview Guarantee application → staff review → pay → 45 days → 3 interviews or a second round, or refund.
4. Member → Job Guarantee request → staff partner proposes roles → member approves → placed → fee instalments.
5. Business → `/business` → free pilot request or buy → staff approves / payment → invite students or set feed.
6. Student → consultancy invite link → sign up → consent → seat with Pro.
7. Operator → `/admin`, `/staff`, `/partner` → accounts, guarantees, cases, business accounts.

## How people find it (today)

The public site (`propelo.org`, GitHub Pages) with the job board, the free scam checker and the docs; the README
on GitHub; the outreach plan in the private founder pack. There is no blog, no paid acquisition, no product
analytics and no referral programme in the product.

## How it makes money

Subscriptions (Razorpay subscriptions in rupees, Dodo in dollars), one-off Interview Guarantee payments,
Job Guarantee placement fees (manual instalment links), and business plans (30 days prepaid, payment link or
checkout). No paying customers are recorded anywhere this audit could see.

## How it is run

- **Admins** (`is_admin`): `/admin` (overview, account lookup, grant plans, staff access, suspend, two-step reset,
  audit log), plus everything staff can do.
- **Staff** (`is_staff`): `/staff` (Job Guarantee cases, Interview Guarantee applications and refund claims) and
  `/partner` (business accounts, pilot approvals).
- **Infrastructure**: Render web service + worker + PostgreSQL (blueprint `render.yaml`); GitHub Actions for the
  scan, Pages, tests, security; GitHub Releases host the feed.
