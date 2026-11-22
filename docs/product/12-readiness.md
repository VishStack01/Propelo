# 12 · Launch readiness

**Verdict (22 Nov 2026): the code is ready for free pilots with hand-picked businesses now, and for a public paid
launch once the seven owner actions below are done.** Nothing in the code blocks launch; what blocks it is
configuration and checks that can only be done with access to Render, DNS, Razorpay and email, which this audit
did not have.

## Scorecard (out of 10; "Not verified" where it could not be tested here)
| category | score | basis |
| --- | --- | --- |
| Product clarity | 8 | One promise, consistent across site, app and business pages |
| Sitemap completeness | 8 | Every page documented and checked by a test; About, blog, status page missing |
| User journeys | 7 | J1, J5, J6, J7 driven end to end locally; J2 payments only with test webhooks |
| UX | 7 | Clear empty states; dashboard navigation is long; no in-app help |
| UI consistency | 7 | Shared tokens; no shared component file |
| Accessibility | 8 | axe 0 violations on 23 pages; keyboard pass on key forms; screen readers not tested |
| Mobile responsiveness | 8 | No overflow at 390/820; mobile apps Not verified |
| Security | 8 | Controls verified locally (07); production headers Not verified |
| Privacy | 6 | Export/delete exist; grievance contact, self-hosted fonts and legal review pending |
| Performance | 7 | Pages load in about 2 s locally including fonts; no production measurement |
| SEO | 6 | Technical basics done; no per-role pages, no content |
| Architecture | 7 | Simple and tested on two databases; single-disk uploads |
| Testing | 8 | Large automated suite on SQLite and PostgreSQL plus journey scripts; other browsers not run |
| Documentation | 8 | This repository, generated parts checked in CI |
| Analytics | 2 | None in the product |
| Operations / admin | 7 | Admin console, staff desk, audit log; no ticketing |
| Production readiness | Not verified | Production could not be reached |

## Owner actions before a public paid launch (P0)
1. **Database:** paid Render PostgreSQL with backups; test one restore (R-001).
2. **Email:** `SMTP_URL`, `MAIL_FROM` on propelo.org, SPF/DKIM/DMARC; confirm a sign-up email lands in the inbox (R-003).
3. **Domains:** propelo.org → GitHub Pages, app.propelo.org → Render, repository variable `SITE_URL`, `PUBLIC_URL` (R-004).
4. **Payments:** Razorpay live keys and webhook; one real purchase and refund (R-005). Dodo for USD if wanted.
5. **Admin:** sign in, turn on two-step sign-in, store recovery codes (R-006); keep a copy of `SECRETS_KEY` (R-007).
6. **Health check:** `/api/ready`, headers (`curl -I`), one full sign-up on production (R-002, R-034).
7. **Legal:** lawyer review of terms, refunds, privacy and both guarantees before charging for guarantees (R-040).

## Fine to start without
Free pilots with 3-5 consultancies can start as soon as 1-3 and 5-6 are done (no payments needed: pilots are free
and approved by staff). GST invoices (R-036) become necessary at the first business purchase.

## Top risks
| risk | likelihood | impact | mitigation |
| --- | --- | --- | --- |
| No one buys (R-042) | High | High | Pilots first; convert with real usage numbers |
| Confirm emails go to spam | Medium | High | DKIM/DMARC; test with Gmail and Outlook |
| Feed gaps when the scan is slow | Medium | Medium | Deadline + carry-over (R-011); stale banner |
| Guarantee claims disputed | Medium | High | Legal review; keep guarantees invite-only until then |
| Data loss | Low with backups | Critical | R-001, R-043 |
