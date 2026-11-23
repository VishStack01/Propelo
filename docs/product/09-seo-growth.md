# 09 · SEO and growth audit

## Technical SEO (Verified on the local build, 22 Nov)
| item | site (propelo.org) | app (app.propelo.org) |
| --- | --- | --- |
| robots.txt | yes, points to sitemap | yes; private paths disallowed |
| sitemap.xml | landing, jobs, docs, scam check | login, signup, pricing, business, legal |
| canonical | every page | public pages |
| Open Graph / Twitter card | yes, absolute image | auth, pricing, business |
| JSON-LD | Organization + WebSite on landing | none |
| noindex | demo | dashboard, partner, staff, admin, verify, reset |
| 404 | generated 404.html | branded 404 |
| Titles/descriptions | distinct | distinct (legal pages fixed) |

## Gaps
| priority | gap | why | do |
| --- | --- | --- | --- |
| P2 | Roles are hash routes on one page (R-021) | The job board is the biggest search channel and none of it is indexable per role | Static pages for open roles with JobPosting JSON-LD, removed when the role closes |
| P2 | No content pages (R-023) | Searches like "visa sponsorship jobs UK for Indian graduates" or "fake job offer check" have no landing page | An About page, then 5 guides matched to the scam checker and the sponsorship data |
| P1 | No analytics (R-022) | Can't see the funnel | Server-side counts in `/admin` |
| P3 | Status page (R-026) | Trust | Free uptime page |

## Funnel (what to measure once R-022 lands)
visit → sign up → confirm email → resume uploaded → first match seen → first application → paid plan.
Business: `/business` visit → pilot request → approved → students joined → paid after 30 days.

## Growth levers already in the product
- **Free scam check** (shareable, no sign-up) and the public **job board** with sponsorship data.
- **Business seats**: one consultancy brings 25-100 students.
- **Agency feed sample** (`propelo sample-roles`) for outreach.
- Honest positioning against spray-and-pray auto-apply tools (see `docs/competitors.md`).

Missing: referral programme, email nurture beyond the welcome email, social proof (must come from real customers).
