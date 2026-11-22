# 06 · UX and design audit

Method: every page at 390, 820 and 1280 px in Chromium (screenshots in the audit run), axe-core WCAG 2 A/AA,
keyboard pass on sign-in, sign-up and Settings, and a read of the copy against what the product really does.

## What works
- One clear promise per page; the landing shows live numbers from the feed rather than typed-in claims.
- Every role decision shows a quote from the posting, which makes the "honest" position visible, not just stated.
- Empty states say what to do next (getting-started card, empty tabs with one action).
- Business pages say plainly what a consultancy sees and never sees; students read the same text before joining.
- No sideways scrolling on any audited page at any width; light and dark themes on every page.
- After fixes, axe reports **0 violations** on all 23 audited pages (22 Nov).

## Fixed in this audit
| issue | fix |
| --- | --- |
| Copy promised hourly refresh; real scans land every 5-9 hours | "several times a day" everywhere; plan feature reworded |
| Unknown links showed raw JSON | Branded 404 with links home, business and contact |
| Signed-out `/staff`, `/admin` showed JSON 401 | Redirect to sign-in and back |
| Dashboard tabs: `aria-selected` on non-tabs, missing tablist | Proper `tablist`/`tab` roles |
| Low contrast on "good" green and tile text | Darker token; higher text opacity |
| Decorative section numerals read as low-contrast text | Drawn by CSS, hidden from assistive tech |
| Pricing had no H1 | H1 added |
| Confirm link lost the join/business return path | Return path read before clearing the URL |

## Still to improve (in the register)
| priority | issue | recommendation |
| --- | --- | --- |
| P1 | No way to ask for help inside the app (R-020) | A Help link on every tab opening a prefilled email; ticket form later |
| P2 | First matches can arrive after the new member leaves (R-031) | Email "your first matches are ready"; progress on the getting-started card |
| P2 | Dashboard is long: 16 tabs in the sidebar | Group into Find (Fresh roles, Queue, Skipped), Apply (Applications, Auto-apply, Outreach, Contacts), Prepare (Writing, Calendar, Ask), Guarantees, Settings; hide tabs a Free member can't use yet |
| P3 | Console 404s for empty documents (R-030) | Return an empty document instead of 404 |
| P3 | Hidden views keep extra H1s on the job board (R-044) | One H1 per visible view |
| P2 | Firefox and Safari not checked (R-027) | Run J1 and J2 on both before launch |

## Design-system notes
Tokens (colours, radius, type scale) are defined per page in CSS variables, and they match across site, auth pages
and dashboard. There is no shared component file, so a button change has to be made in four places; acceptable for
now, worth a shared stylesheet when a designer joins.
