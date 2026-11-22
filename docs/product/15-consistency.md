# 15 · Consistency report

Checks run on 22 Nov 2026 between the docs, the code and what the running app does.

| check | result |
| --- | --- |
| Every page route the app serves is in the sitemap | Pass (`product_docs.py --check`) |
| Every `website/*.html` page is in the sitemap | Pass |
| Generated routes, tables and workflows match the code | Pass |
| Prices: `plans.py`, `/pricing`, `/business`, README, register | Consistent: Pro ₹499 / $22.50, Ultra ₹1,199 / $48.50; Starter ₹14,999 (25), Growth ₹29,999 (50), Plus ₹44,999 (100), feed ₹4,999 / $99 |
| Scan frequency claims vs reality | Fixed: was "hourly" in site, app, plans, README, competitors doc; now "several times a day" |
| Interview Guarantee terms: dashboard, terms page, staff desk | Consistent (₹4,999; 3 interviews or a second round in 45 days; refund on claim) |
| "Never submits" claim vs extension code | Consistent: no submit call in the extension |
| Permissions doc vs route guards | Consistent with the generated routes list |
| Feed counts in docs vs live feed | 01-product uses the 22 Nov feed (95,212 roles); the site shows the live value |

## Known differences (left on purpose)
- `README.md` describes the open-source CLI first; the product docs describe the hosted service.
- Job board shows 58,001 roles (deduplicated, open, with a link) while the feed counts 95,212 openings
  (including duplicates across locations). Both are labelled; worth one sentence on the job board explaining it.
