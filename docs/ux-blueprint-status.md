# UX blueprint: status, item by item

Checked 25 November 2026 against the live site, the app and the code. Each item says whether the blueprint's finding was true, what was done (with the pull request), what needs you, and what was declined and why. Pull requests 31 to 37 are the work.

## Done

| Blueprint item | Finding | What changed | PR |
|---|---|---|---|
| Pink splash screen before the home page | True | Removed. The page opens on its content. | 31 |
| Numbers that disagree between pages | True: 120,000 roles on the home page, 1,19,998 on the board, "about 1,800 boards" in the docs (the scan reads 26,044) | Every build writes the same numbers into every page: roles the board lists, companies with open roles, boards, hiring systems, scan date. | 31 |
| Visa-jobs pages capped at 150 per country | True | Still the newest 150 per page (page weight), but each page now says "Newest 150 of N roles" and links to all of them on the board. Canada, Australia and Germany pages now redirect: Propelo covers four countries. | 31 |
| `/scam.html`, `/pricing.html` and `propelo.org/terms`, `/privacy`, `/refunds` were dead links | True | Each now forwards: scam → scam check, pricing → plans, the policies → the app's pages. Also `/contact` and `/business`. | 31 |
| Job board shows Indian number format, LPA filters, an Indian search example and "Anywhere you work from India" | True | Opens on the US, UK, Ireland and the Netherlands; international numbers; pay as the posting states it ($, £, €); "£35k+" works in search; UK, Irish, Dutch and US cities; the website's header with Pricing and Sign in. | 32 |
| `feed.xml` shows LPA salaries | True, and worse: US dollar pay was converted to lakhs | The feed, the API and the board show the posting's own currency. Lakhs only for roles in India. | 32 |
| Some roles in the wrong country | Found while checking: "Chennai, TN, India" was read as Tennessee, "Amstelveen, NH, Netherlands" as New Hampshire, "Holland, Michigan" as the Netherlands | Fixed in the country reader; the website re-reads each role's country at every build. | 32, 33 |
| Self-hosting (git clone, Ollama) on the home page and "Self-host it" under the prices | True | Moved to the docs. The closing button is "Browse open roles". | 33 |
| Demo banner says "Run propelo serve" | True | "Use Propelo with your own resume, free", linked to sign-up. | 33 |
| Sample card "HP · Austin · 4+ years" with no sponsor badge | True | The card now prefers an entry-level role in the four countries at an employer with a sponsor record, and shows that record ("Has sponsored H-1B visas", "On the UK sponsor register"). | 33 |
| Policies bundled on one page, no subprocessor list | True | `/privacy`, `/terms`, `/refunds`, `/contact` are separate pages with the site header. Privacy lists every service that handles data and what it receives, and names the ID numbers Propelo never asks for in each country. | 34 |
| Sign-up page has no way back to the website | True | "Back to propelo.org". | 34 |
| `/business` says "Coverage is strongest in India" | True | Sponsor checks in four countries; "most roles are in the US, then the UK". | 34 |
| 17 sidebar tabs | True (17, plus 9 tools) | Five places: Today, Discover, Pipeline, Prep & outreach, Career Brain. Every screen kept. | 35 |
| Phone dock: inbox dot on Applications, review queue hidden in the + sheet, 14-item More sheet | True | Five labelled dock tabs with correct dots (a new reply marks Pipeline); each place's tabs in a row at the top; sheets removed. | 35 |
| Mode switch in the header | Partly there (on the visa card) | Sponsored career / Part-time in the top bar on every tab, for students whose visa allows term-time work. | 35 |
| Background sync fails silently | True | A notice says offline / waking up / can't reach, retries, and says "Connected again." | 36 |
| "You're caught up" state | Partly there | Says when the last scan finished and offers one next step. | 36 |
| App id `io.github.vishstack01.careeros`, `CareerOSApp` user agent, iPhone landscape, no microphone string | True | `org.propelo.app` on both stores, `PropeloApp/1.0`, portrait iPhone, microphone and speech strings for the resume drill, 16 px fields on phones. | 37 |

## Not a bug

| Blueprint item | What is true |
|---|---|
| Resume upload rejects Word and Markdown | The profile's resume import reads PDF, Word and Markdown. `POST /api/assets` is a different thing: the PDF you attach to applications, and its button says "Upload PDF". |
| The demo says "Calcutta time" | The demo shows the viewer's own time zone. Someone in India sees Calcutta. |
| Scam check mentions Aadhaar and helpline 1930 | They sit alongside the UK, US, Irish and Dutch reporting lines, on purpose: many scams aimed at students abroad start from India. |
| Two-step sign-in for staff and admins | Already required in the code. |
| Part-time mode, weekly hours, part-time CV, visa clock, warm paths, resume drill, offer brief | Already built in earlier pull requests (16 to 27). |

## Needs you

1. **www.propelo.org** fails with a certificate error. The website is on GitHub Pages, so this is DNS, not Render: add a `CNAME` record `www` → `vishstack01.github.io`, then in the repository's **Settings → Pages** check the custom domain is `propelo.org` and tick **Enforce HTTPS**. GitHub then sends www to the apex. Then add `propelo.org` in Google Search Console and request indexing.
2. **Governing law.** Which country's law governs the terms is your decision with a lawyer. The operator note at the top of `propelo/cloud/static/legal.html` says what to review.
3. **A support address on propelo.org** (for example `support@propelo.org`), then set `SUPPORT_EMAIL` in Render. The pages show whatever it is set to.
4. **A data processing agreement** for consultancies and universities: legal drafting.
5. **Store accounts** before the phone apps ship: Apple Developer and Google Play. If the iOS app offers Google or LinkedIn sign-in, check Apple's current rule on also offering Sign in with Apple.
6. **Real proof for the website**, only with permission: student quotes, university society or consultancy logos. None exist yet, and none will be invented.

## Later (bigger builds)

- A sponsor and job-link checker inside the home page hero. The sponsor check and scam check exist as their own pages and are linked from the hero.
- One application state machine across Discover and Pipeline (Queued → Needs you → Applied → Screen → Interview → Offer) instead of separate screens.
- An Ask Propelo drawer on every screen (Cmd+K) instead of a tab.
- Working offline: cached roles, pipeline and resumes (service worker and IndexedDB), and writes queued while offline.
- Pairing the extension and a desktop companion with one click instead of copying a key.
- Recruiter replies by forwarding to an address on propelo.org (needs an inbound mail domain).
- Guided metric questions during onboarding.
- Phone apps: a bundled app shell, push notifications, in-app purchases (StoreKit and Play Billing), biometrics.
- The agency feed's country list still offers more than the four countries.
- UK occupation going rates and US prevailing wage levels (already in Known gaps).

## Declined, and why

| Blueprint item | Why not |
|---|---|
| Fill Workday passwords from a vault | Propelo never handles job-site passwords or one-time codes. You sign in to each employer's site yourself. |
| "Message fellow Indian alumni" | Propelo finds people by shared school and team, never by nationality or ethnicity. |
| "Boost callback odds 5x", "~3% industry baseline", "≥ 10.5% interview rate", a "HiredScore simulator", the 60-day percentage targets | These are figures Propelo can't back. Product copy states only what it can show. The targets in the blueprint can be tracked once there is real usage. |
| Testimonials before there are real ones | Never invented. |
