# Business accounts

Two kinds, both run from `/partner` and created by staff.

## Consultancy (study-abroad consultancies, college placement cells)

- Staff create the account at `/partner` (staff section): name, admin email (the admin signs up first),
  seats, status (`pilot` or `active`), end date and the agreed amount, for the record.
- The admin shares the invite link (`/join/<code>`). A student signs up or signs in, reads exactly what
  the consultancy will see, agrees, and joins. Each student uses one seat and gets the paid plan
  (`pro` by default) while the account is `pilot` or `active` and before its end date.
- The admin sees, per student: roles matched, applications, interviews and offers (company and role),
  roles from sponsoring employers, and last activity. Never the resume, answers or messages.
- Students see "Provided by <name>" in the app and can leave in Settings. Leaving or being removed frees
  the seat and returns them to their own plan; their account and data stay theirs.
- Pausing or ending the account stops the seat plans at once.

## Agency (recruiting agencies)

- A filtered feed of open roles from the shared inventory, as CSV or JSON:
  `/api/partner-feed/<slug>.csv` or `.json`, with `Authorization: Bearer <key>` or `?key=<key>`.
- Columns: company, title, location, work mode, days open, first seen, posted at, what the posting
  says about visa sponsorship (with the quote), UK sponsor register, salary, ATS and the posting URL.
  Roles only; no personal data. No hiring-manager contacts: add those with your own tools.
- Filters: title keywords (any of) and exclusions, countries, cities, remote (include, leave out, only),
  minimum days open, sponsorship (says it sponsors, leave out "cannot sponsor", on the UK register) and
  a row limit. The admin edits them at `/partner` and sees a 50-row preview.
- The key is shown once; making a new one stops the old one. 120 requests an hour.

**Days open** is the earlier of the posting's own date and the day the scan first saw that listing.
Some hiring systems update the posting date when a role is edited, so the first-seen date is the
dependable one; it counts from 21 Oct 2026, when the scan started keeping history.

## Free samples for outreach

```
propelo sample-roles --keywords engineer,developer --countries GB --remote exclude --min-days 21 --out sample.csv
```

Reads the public feed (or `--feed <folder>`) and writes the same columns as the agency feed, longest
open first, plus a one-line summary to paste into an email.

## Plans

| plan | students | price for 30 days |
| --- | ---: | ---: |
| Starter Pack | 25 | $325 (₹28,599) |
| Growth | 50 | $625 (₹54,999) |
| Plus Pack | 100 | $1,225 (₹1,07,799) |
| Agency roles feed | n/a | $99 (₹8,699) |

Set in `BUSINESS_PLANS` (`propelo/cloud/partners.py`). Dollar checkout needs a Dodo product per plan:
`DODO_PRODUCT_CONSULTANCY_STARTER`, `DODO_PRODUCT_CONSULTANCY_GROWTH`, `DODO_PRODUCT_CONSULTANCY_PLUS`, `DODO_PRODUCT_AGENCY_FEED`.

## Billing

Bought online at `/business` (Razorpay payment link in rupees, Dodo checkout in dollars): each payment adds 30 days
from the current end date. Reminders go a week before the end and at the end. Staff can still set status,
seats and end dates by hand at `/partner` for deals agreed outside the site.

## Visa sponsorship facts

See `propelo/sponsors.py`. The posting's own words ("offers", "no", or nothing, shown as unclear and
never guessed); for UK roles, the Home Office register of licensed sponsors (downloaded daily by the
scan) and the Skilled Worker salary floors (£41,700 general, £33,400 new entrant, from 22 July 2025;
the occupation's going rate is not checked). On the 31 Oct feed, 94% of UK postings said nothing about
sponsorship, so for UK roles the register is the signal that matters.
