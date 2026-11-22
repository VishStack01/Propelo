# Changelog

All notable changes to CareerOS. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses [semantic versioning](https://semver.org/).

## [2.10.0] - 2026-11-22

Built for people studying or working abroad, most of all Indian students after a master's in the US, UK, Canada, Australia, Germany, Ireland and the Netherlands. No paid data sources were added: everything below reads public pages and public lists.

### Added
- **Country on every role.** The scan now works out the country a location only implies ("Austin, TX", "Toronto, ON", "Melbourne, VIC", "Eindhoven", Indian cities and states). On the 22 Nov feed this cut roles with no known country from 23,003 to 7,036. Members abroad who list a country now match on-site roles there that never name it.
- **Job board filters for Country and for Visa and sponsorship**, a Visa line on each role page and visa tags on the cards. Choosing a country shows on-site roles there.
- **US student signals from the posting's own words:** takes or refuses OPT/CPT, says it uses E-Verify (needed for the STEM OPT extension), and citizens-only or security-clearance roles, which are marked as not open to visa holders.
- **Dutch register of recognised sponsors** (the immigration service's public list), read daily like the UK register: roles in the Netherlands say whether the employer is on it. `careeros nl-sponsors`.
- `countries` on each feed record and `byCountry` in `summary.json`.

### Changed
- **Scans run back to back** instead of waiting for GitHub's schedule, which was delivering about four runs a day. Each finished scan starts the next; a scan that fails in under 20 minutes doesn't.
- **The scan fits its time as the board list grows.** Curated boards are read every run, deep-sweep boards every four hours and empty ones daily (`CAREEROS_SCAN_MAX_BOARDS`); boards not read keep their roles. The shared Greenhouse, Lever, Ashby and SmartRecruiters APIs are read at two requests a second instead of one.
- **Deep sweep keeps boards hiring in study countries.** About 21,000 inventory boards rejected in October under the India-only rule are being looked at again; boards with roles in a study country are kept.
- When the feed has to be trimmed, India and remote roles stay first, then junior and mid-level roles in study countries, then senior roles there, then the rest of the world.
- **Feed intake uses about 100 MB instead of about 3.2 GB.** It reads the small summary first and downloads nothing when the feed hasn't changed, streams the files from disk, and writes only roles that changed (migration `0012_job_rev.sql`).

## [2.9.1] - 2026-11-22

### Changed
- **Interview Guarantee: ₹4,999 (or $59) and a bigger promise.** Shortlisted for at least 3 interviews, or a second round for one role, within 45 days, or the full price back. `GUARANTEE_MIN_INTERVIEWS` (default 3) sets the number. Guarantees agreed under the earlier terms keep their one-interview promise and price. Terms version 2026-11-22.
- **Home page menu:** six links (Product, Job board, Guarantees, Pricing, For consultancies, Docs) with Sign in and Start free, the same on the docs and scam check pages. The rest stay in the footer.

## [2.9.0] - 2026-11-22

### Added
- **Two-step sign-in.** Authenticator-app codes with ten one-time recovery codes, in Settings > Account. Required for staff and admin accounts in production; an admin can reset it after checking who someone is. Migration `0011_mfa.sql`.
- **Admin console at `/admin`:** overview, find an account, grant a plan, give or remove staff access, reset two-step sign-in, suspend or restore an account (ends every session and computer key), background jobs and the audit log.
- **Product docs in `docs/product/`:** sitemap, journeys, page specs, permissions, UX, security, architecture, SEO, QA log, missing-items register, readiness scorecard and roadmap. `scripts/product_docs.py` generates the routes, tables and workflows from the code, and the test suite fails when a page is missing from the sitemap.
- Branded 404 page; `robots.txt` and `sitemap.xml` on the app and the site; canonical links, Open Graph tags and structured data on public pages; private pages marked noindex.

### Changed
- **Scan time limit.** A board that hangs no longer cancels the whole scan: after 60 minutes the scan keeps that board's roles from the last run and publishes.
- Copy says roles refresh **several times a day**, which is what the scan delivers, instead of hourly.
- Signed-out visits to `/staff`, `/partner` and `/admin` go to sign-in and come back; staff without two-step sign-in are sent to turn it on.
- Accessibility: tab roles, colour contrast and heading fixes; axe-core reports no violations on the audited pages.

### Fixed
- The confirm-email link now returns students to their consultancy's join page.
- Wrong two-step codes are counted even though the attempt fails.

## [2.8.0] - 2026-11-17

### Added
- **Business accounts.** A study-abroad consultancy or placement cell gets a branded space at `/partner`, an invite link and seats: each student who joins gets Pro while the account is active, and the consultancy sees their progress (roles matched, applications, interviews, offers, roles from sponsoring employers), never resumes, answers or messages. Students read exactly that before joining and can leave in Settings. A recruiting agency gets a filtered CSV or JSON feed of open roles (days open, the posting's sponsorship line, the UK sponsor register) with its own key. Staff create both at `/partner`. Migration `0009_partners.sql`; see `docs/business.md`.
- **Visa sponsorship on every role.** What the posting says (sponsors, cannot sponsor, or nothing, shown as unclear and never guessed), and for UK roles whether the employer is on the Home Office register of licensed sponsors (downloaded daily) and whether stated pay meets the Skilled Worker floors. A new setting, "I need visa sponsorship", skips roles that can't sponsor you.
- **How long each role has been open**, from the day the scan first saw the listing.
- `careeros sample-roles`: a free sample of the agency feed for one niche, for outreach.
- **Business plans, 30 days prepaid:** Starter Pack ₹14,999 (25 students), Growth ₹29,999 (50 students), Plus Pack ₹44,999 (100 students), and the agency roles feed ₹4,999. Buy at `/business` or ask for a free 30-day pilot; nothing renews by itself.

### Changed
- **The job feed is published as release assets** (`feed-latest`), not to a force-pushed branch, which the repository's rules block. It had not updated since 31 Oct; the scan now also fails loudly when the feed is more than 3 hours old.
- **AI actions on the service's model use the quick model** for parsing, scoring, copilot, mocks and drafts; the tailored resume and its edits stay on the main model. Your own key is unaffected.

## [2.7.0] - 2026-11-16

### Added
- **Indian HR questions.** Application details now hold: currently working, serving notice and last working day, notice buyout, fixed and variable pay, preferred cities, working from the office, night or rotational shifts, a service bond and a one-line career gap. The extension and auto-apply answer these only from what you saved; "Prefer not to say" leaves the question for you, a last working day in the past is never used, and pay goes in the form's own unit (lakhs, or rupees when the form asks in rupees; monthly figures are left to you).
- **Indian portals in the extension.** Internshala, Unstop, Instahyre, Cutshort, Hirist, iimjobs, Superset and Pod.ai can show the on-page panel and get filled when you ask; you press Submit. Auto-apply hands these roles to you instead of applying there, as it does for LinkedIn, Naukri, Indeed and Wellfound.
- **Review queue, made for phones.** One role at a time: approve (or "Apply anyway" below the 4.0 line), skip, or save for later. Roles that need you come first, with an **apply kit**: your details, the tailored resume, cover note and screening answers, each with a Copy button, for applying on a phone where extensions don't run. Nothing is submitted from the queue.

### Changed
- **More reliable autofill.** The extension now fills custom dropdowns (Workday, Angular Material, react-select and others that use a listbox), keeps filling for 15 minutes as new questions appear (a follow-up question, the next page of a Workday application), and reads job pages that draw late or change without a reload (Darwinbox, Keka, Zoho Recruit). It still never overwrites what's typed and never presses Submit.
- **Ultra's copilot and mock interviews have a stated fair-use limit:** 200 questions a day and 60 mock interviews a month, with no limit on your own AI key. Prices are unchanged.
- The hourly job scan is on again, so the job board and Fresh roles get new roles every hour.
- The website calls Concierge the Job Guarantee, by application, matching the app.

## [2.6.0] - 2026-11-16

### Changed
- **Guarantees are applied for, and the team decides.** Neither guarantee is bought directly. Pro and Ultra members apply from the Guarantees tab, a one-time pop-up or a card on Home, and a person reviews each application within 2 working days, accepting or declining with a reason. **Interview Guarantee:** once accepted, pay ₹2,999 (or $34) within 7 days for 45 days; send 25 applications in at least 3 different weeks; no interview, and the full ₹2,999 comes back (plan fees aren't part of it). **Job Guarantee:** the Concierge service under a clearer name, with nothing upfront and 8% of yearly fixed pay (6% above ₹20 lakh) only after joining. `/staff` lists applications with Accept and Decline, and Concierge cases waiting for review can be declined with a reason. Terms version 2026-11-16b; migration `0008_guarantee_review.sql`.
- **Real company logos in more places.** A checked list of 440+ well-known employers' own websites (`careeros/data/company_domains.json`) covers Workday codes like "Hpe" and "Jci" and sites that block the automatic check, roughly doubling the roles that get their company's logo on the job board. The app's role lists and application pages show the same logos (from the job board's `logos/map.json`; set `JOBS_SITE_URL`).
- **The website shows real roles and real companies.** A strip of well-known companies hiring now, with their logos and open-role counts, and the example roles on the page are real recent openings at those companies, in India, remote and abroad. The job board defaults to roles everywhere, with "Top companies" and "Well paid" lists.

### Fixed
- The phone mockups' dock showed empty squares; it has icons now.
- A test about day-7 follow-ups depended on the real clock.

## [2.5.0] - 2026-11-16

### Changed
- **The guarantees are paid add-ons, not part of Pro or Ultra.** Pro and Ultra members can buy the Interview Guarantee (₹999 or $19, once) and, with Concierge, the Job Guarantee (₹2,999, once). Buying checks eligibility first, opens a Razorpay payment link or a Dodo checkout, and the window starts when the payment webhook arrives; an unpaid checkout lapses after 2 days. If a guarantee fails and the person did their part, the refund is the add-on price plus the plan fees paid during the window. The plan cards no longer list the guarantees; `/api/plans` returns them as `addons`, and the pricing page and website show them as add-ons with prices. Operators can start one without payment (`POST /api/admin/guarantee`). Migration `0007_guarantee_addon.sql`.
- **A match score you can check.** The score is rebuilt so every point comes from something measured: skills up to 60 (required terms weigh more than "nice to have" ones, and a skill proven in a bullet with a number counts more than one only listed), experience up to 25, role up to 15. A part that can't be measured is left out, not guessed, and the score shows a margin (for example "68, could be 55 to 81"). The app and the extension show it as a big gauge that counts up while its ring fills, with the arithmetic underneath and each skill marked proven, in experience, skills list or missing. Motion is off for people who ask their system for less.

### Fixed
- The experience line read "roles asking up to 6 years (you have 4) roles"; it now says "roles for 4 years of experience (asking up to 6)".
- The New application screen didn't pass the job title to the score, and the role part compared the company name too.

## [2.4.0] - 2026-11-16

### Added
- **Match score from your real resume**, for any role in any field: `POST /api/agent/match` and `careeros/matchscore.py`. 70% skills found in your resume (a bullet or summary counts fully, the skills list half), 20% years against years asked, 10% title against your target roles, with what you have, what's missing (add only if true), the experience note and the scam check. Reads the structured resume, else the uploaded resume's text, else the Career Brain.
- **Skill terms for every field** in the keyword vocabulary (accounts and GST, sales and CRM, HR, supply chain, engineering trades and CAD, nursing and clinical, teaching, law, retail and hospitality, media), so coverage and scores work beyond tech.
- **Extension 2.4: match, fill, next.** A match card in the popup; an optional on-page panel on 19 hiring systems (Greenhouse, Lever, Ashby, Workday, SmartRecruiters, Workable, Recruitee, Teamtailor, iCIMS, Jobvite, Breezy, BambooHR, Personio, Zoho Recruit, Darwinbox, Keka, Freshteam, SuccessFactors, Taleo) with the score and a Fill button; and an **apply queue** that opens each role waiting in Propelo, fills it, notices the confirmation after you press Submit, records the application and opens the next. A background worker holds the key; the panel sits in a closed shadow root. Sites are asked for only when you switch these on.
- **More openings across countries**, India first: Adzuna (India, the US, UK, Canada, Australia, New Zealand, Singapore and western Europe; `ADZUNA_APP_ID`, `ADZUNA_APP_KEY`, `ADZUNA_COUNTRIES`, `ADZUNA_PAGES`) and USAJOBS (US federal roles; `USAJOBS_KEY`, `USAJOBS_EMAIL`), each polled once a day when its key is set. Arbeitnow's on-site roles in Germany are kept when the scan covers on-site roles worldwide, and company discovery keeps boards with roles in India or a developed country. The published feed is capped at `CAREEROS_FEED_MAX` roles (120,000), India and remote first.

### Changed
- `/api/agent/track` accepts the role's `jobId`, so the apply queue records the right role when it opened the form's own page.

## [2.3.0] - 2026-11-16

### Added
- **Interview Guarantee** on Pro and Ultra: an interview within 60 days, or the plan fees paid in that time come back. Before starting, the app checks and records eligibility (a paid plan, a profile with experience, and at least 40 roles matched in the last 30 days, so the promise is only made where Propelo finds roles). The person's part is 30 applications in at least 4 different weeks; applications to postings the scam check marks unsafe don't count. Interviews are detected from the pipeline (screen, interview or offer), recruiter screens included.
- **Job Guarantee** with Concierge: an accepted offer within 6 months, or the plan fees back, and no Concierge fee for that case.
- A Guarantees screen in the app (eligibility checklist, progress bars, claim form with a signed statement), claim review for the team in `/staff` (approve up to the plan fees, reject with a reason, mark refunded), emails at each step, the worker moving guarantees on (met, stopped when the plan ends, claimable, claim period over), guarantee terms at `/terms#guarantees`, and a Guarantees section on the website. Settings: `GUARANTEE`, `GUARANTEE_DAYS`, `GUARANTEE_MIN_APPLICATIONS`, `GUARANTEE_MIN_WEEKS`, `GUARANTEE_MIN_MATCHES`, `GUARANTEE_CLAIM_DAYS`, `JOB_GUARANTEE_DAYS`.

### Changed
- Plan prices are unchanged (Pro ₹499 or $22.50, Ultra ₹1,199 or $48.50 a month). The plan cards list the guarantees when they're on, and the website's cards follow the hosted service's settings.
- The Concierge terms no longer say "No job guarantee"; they say hiring decisions are the employer's and point to the Job Guarantee.

## [2.2.0] - 2026-11-16

### Added
- **Every field, not only tech.** New job families: Engineering & Trades (civil, mechanical, electrical, plant and site roles, electricians, technicians), Healthcare, Education, Legal, Retail & Hospitality, and Media & Writing; Operations & People now covers front office, telecalling, BPO, warehouse and delivery roles. The hourly scan keeps every role it can name a family for, and company discovery keeps boards that list any of them, not only developer roles. Titles that name software, data or chip work stay in the tech families.
- **Every level.** Settings take your years of experience (0 for freshers) instead of checkboxes that stopped at "3+ years". Roles may ask for a year more early on and two more later; from 3 years on, internships and entry-level titles are hidden.
- **"Is this job real?"** A free scam check at `check.html` on the website: paste a post, WhatsApp message or email and see the warning signs with the words that triggered them. No sign-up, and nothing leaves the browser. The same check runs on every job added with New application, and on the home screen a card invites people to add jobs they found anywhere.
- Scam rules for task scams (paid likes and reviews), "refundable" deposits, buying equipment before starting, and home-based data entry. `scripts/sync_scam_rules.py` copies the rules into the dashboard and the website; tests keep all three identical.

### Fixed
- Typed target roles were added to the built-in tech keywords, so someone who typed "nurse" was shown hundreds of software roles. Typed roles now decide on their own.
- "Staff Nurse" and "Staff Accountant" were read as senior titles, like "Staff Engineer".
- New accounts started with fresher settings and south India locations. Experience now starts open until you enter your years.

## [2.1.0] - 2026-11-15

### Added
- **Concierge**, part of Pro and Ultra, for jobs in India: a talent partner on the Propelo team runs the search. The candidate approves every company before anything is sent; partners never sign in as the candidate or automate LinkedIn. The fee is 8% of yearly fixed pay, 6% on any part above ₹20 lakh (no cliff), plus GST where it applies, only for an offer from a company the candidate approved through Concierge within 6 months, and only after joining: three monthly instalments from 30 days after the joining date, through Razorpay payment links. If the employer ends the job within 90 days, what's unpaid is cancelled. Cases pause when the plan ends. Includes the candidate's Concierge page with a fee calculator, a workspace for partners at `/staff` (queue with Ultra first, proposals, messages and private notes, offer checks, instalments), versioned terms, and an audit trail of every staff action and case view. The UK is always refused, because charging work-seekers is prohibited there.
- **Matching for everyone, wherever they live.** Outside India, roles fit when they're remote and open to the person's country or region (countries named in the location, regions, or a UTC-offset range), or on-site or hybrid in places they list. Work-authorization rules are judged against their own country. Settings ask where you live (guessed from the browser), take a salary floor in US dollars outside India, and use the browser's time zone. The hourly scan keeps on-site roles in every country (`CAREEROS_SCAN_ONSITE=world`). Matching in India is unchanged.

### Changed
- The website, job board and pricing page describe Propelo for everyone ("Built in India, works everywhere"), with a Concierge section. "Fresh roles before the big boards" became "straight from company career pages", because we haven't measured the first claim.
- `scripts/sync_plan_cards.py` writes the website's plan cards from the plan catalog.

## [2.0.0] - 2026-11-14

### Added
- **Ultra plan and dollar pricing.** Free, Pro and Ultra at ₹0 / ₹499 / ₹1,199 a month in India (Razorpay) and $0 / $22.50 / $48.50 everywhere else (Dodo Payments, the merchant of record abroad). The pricing pages pick the currency from the visitor's country or time zone, with a switch. Ultra matches new roles within 15 minutes of each scan, allows 1,500 AI actions and up to 1,000 applications a month (60 a day), unlimited copilot questions and mock interviews, and LinkedIn profile review.
- **Safe plan changes.** A new plan waits as pending until it's paid; only then is the old subscription cancelled (by a worker task), so an abandoned checkout never takes a plan away. Dodo webhooks are verified with Standard Webhooks signatures and a 5-minute window; stale and duplicate events from either provider are ignored. Dollar customers get an **Invoices and card** button.
- **Automatic recruiter emails**, off until you turn them on: Propelo sends from your own Gmail (permission to send only), using a template you approve, to recruiter addresses found on a public page, up to 10 a day on Pro and 25 on Ultra, on weekdays during working hours. Follow-ups go on day 7 and 14 in the same thread and stop when they reply or you press Stop. Every email has an opt-out link and one-click unsubscribe header that every Propelo user honours, and every send is logged on the role.
- **Scam check.** Rule-based warnings with the words that triggered them (fees, deposits, ID numbers up front, WhatsApp-only hiring, free-mail contacts, link shorteners, task-pay patterns). The same rules run on the server and in the app. Auto-apply never sends a posting marked unsafe.
- **Contacts**: the people in your search with their roles, last contact and follow-up dates, added by hand or in one click from your roles.
- **Ask Propelo**, a copilot that answers from your profile, pipeline and filters (10 questions a day on Free, 60 on Pro, unlimited on Ultra).
- **Interview prep sheets**: likely questions mapped to the story from your profile that answers each, honest answers for gaps and questions to ask. Saved on the role and printable.
- **LinkedIn profile review** from text you paste (Propelo never opens LinkedIn).
- **Application receipts**: auto-apply keeps the confirmation and the fields it filled (never sensitive ones), printable from the role.
- **Save to Propelo** in the extension reads a careers page's JobPosting data (description, location, pay) so a saved role can be scored. On LinkedIn, Naukri, Indeed and Wellfound it reads nothing from the page.
- Operators: `/api/admin/audit`, `/.well-known/security.txt`, optional error reporting (`SENTRY_DSN`, nothing personal sent), a second AI provider used when the first fails (`CAREEROS_LLM_FALLBACK`), and a k6 load test (`scripts/loadtest.js`).
- Repository: CodeQL, pip-audit, gitleaks, a private-file guard and Dependabot.
- Docs: [launch guide with the owner's to-do list](docs/launch.md), [runbook](docs/runbook.md) and [how Propelo compares](docs/competitors.md).

### Changed
- The worker ingests every 15 minutes and matches each account at its plan's pace (Free daily, Pro hourly, Ultra every ingest).
- Copilot questions and mock interviews on the service's model are counted per plan; with your own key they stay unlimited.
- The privacy notice covers Dodo Payments, contacts, the Gmail permission (with Google's Limited Use statement) and cookies; the terms cover Ultra, dollar billing and emails sent for you.
- Website source bars reveal with a clipped edge instead of stretching, so their ends stay round.

### Fixed (verification pass)
- **The app version.** Inside the Android and iOS apps, Settings shows only your own plan, with no prices, other plans, currency switch or purchase buttons, as the stores require. "Continue with LinkedIn" is hidden there and Gmail is connected from the website, because both sign-ins would finish in the phone's browser instead of the app. Calendar events and stage dots have their colours back (they had all turned to ink). The writing tools menu is one scrolling row, the Gmail sending row stacks on phones, the role page title no longer starts a line with a dot, page header buttons start on the left, and in dark mode the bottom dock and "Your plan" badge have their own surface. The native shells are versioned 2.0.0.
- Billing webhooks failed on PostgreSQL (a boolean `CASE`); caught by CI before release.
- Recruiter emails go out during the sender's own working hours (the browser's time zone is saved when sending is set up), and odd documents, line breaks in a subject or a malformed address can no longer stop the queue.
- A copilot question or mock interview isn't counted when the AI call fails.
- `careeros cloud serve` and the worker exit at once when migrations are pending, instead of hanging; `careeros cloud check` catches a malformed or console `SMTP_URL` in production and half-configured Google or Ultra settings.
- The website's plan cards are generated from the plan catalog, with a test that keeps them identical.

## [1.4.0] - 2026-11-14

### Changed
- **New look across Propelo**: the website, docs, job board, dashboard and app, sign-in, pricing and legal pages, offline screen and extension popup now share one design. It is cream and ink with one pink accent (`#FF85BA`), Figtree at weights 400 to 600, sentence-case labels and fully round buttons. Colour lives in a few moments: the role card with its fit score, the five principle notes, the best-fit card and the four Home tiles, drawn like notes on a board with an ink outline. The pass followed [unslop](https://github.com/heydamir/unslop) (CC BY 4.0); the rules are in [docs/design.md](docs/design.md).
- **Website rebuilt**: a role card with quoted checks in the hero, live numbers from the latest scan, the principles as notes, a dashboard preview, the app on two phones, pricing and a clean footer with link columns. On phones the links fold into a menu.
- **Motion**: the home page opens with the wordmark on pink, which lifts away with a curved edge (once per visit). Headlines arrive letter by letter and a highlighter stroke draws under the key phrase; panels open from the bottom with a curved edge; the source bars fill and the step line follows the scroll. The hero's dot grid reacts to the cursor. Nothing loops, and Reduce Motion shows every page at rest.
- **Brand**: the logo is the word `propelo` with a pink dot. The app, extension and phone icons are a lowercase `p` on a pink tile, and the phone app's splash is the wordmark.
- The role sheet in the dashboard takes its stage colour as pastel paper with ink text.
- Illustrations are removed for now; the prompts stay in [docs/illustrations.md](docs/illustrations.md) for later.

### Added
- `careeros site` writes `data/stats.json` (openings, companies, boards, re-listed roles and the share of each hiring system) so the website shows live numbers.

### Fixed
- Opening a role's package in the dashboard failed with an error before the sheet appeared.
- The sign-in, pricing and legal pages still said "careeros" in their logo.
- On phones, a role's pay and age on the job board could push the page sideways.

## [1.3.0] - 2026-11-11

### Changed
- **CareerOS is now Propelo** (propelo.in). The `propelo` command works alongside `careeros`, which stays for existing scripts. The repository, Python package and data folders keep their names, so nothing you have set up breaks.
- **A calmer, warmer design** on the job board, dashboard and website, following [unslop](https://github.com/heydamir/unslop) (CC BY 4.0): warm paper and ink colours with one pink accent, IBM Plex Mono for dates, figures and sources, three corner sizes, sentence-case labels and one easing curve. Dark mode has its own warm tokens.

### Added
- **Company logos on every role** of the public board. The site build finds each company's own website from evidence (its careers page, the posting itself, or a guessed domain whose homepage names the company), fetches its icon, caches it for 30 days and publishes it with the board. A company without a verified logo shows its initial instead; a wrong logo is never guessed into place.
- **Board**:
  - **Plain-English search**: "remote python internships in Bengaluru over 6 LPA" sets the filters for you, and shows what it understood with a way to undo each part.
  - **Save and hide** roles on the board (kept in your browser), with a Saved list.
  - **Where every role came from**: each card and posting says which board it was found on and when it was last checked, and the posting has "Report a problem".
- **Applications**:
  - new stages: **Assessment** (between Applied and Screen) and **No response** (closed without a reply);
  - **CSV export and import** of your applications, for a spreadsheet or another tracker.
- **Writing & interviews**:
  - six more emails: ask to reschedule an interview, ask for more time on an assessment, questions about an offer, negotiate an offer, accept an offer, withdraw an application;
  - mock interviews by round (campus or fresher, software engineering, AI and data, product and design, managerial, HR) and difficulty (warm-up, standard, tough);
  - **Saved answers**: keep your answers to common application questions, for any company or one company;
  - **Career wins**: a running list of what you did and what changed because of it, used as evidence when Claude writes for you.
- **Campus details** in your application details: CGPA or percentage, branch, active backlogs (only if a form asks, "Prefer not to say" by default), state and PIN code.
- **Job alerts by email** (Propelo Cloud): off by default; daily or weekly in Settings. Each email lists up to ten new roles that passed your filters, best fit first, each with the company's own link, and nothing is sent when there's nothing new.
- **Propelo Autofill 1.3.0**: fills the campus fields, and fills a question from your saved answers when the wording matches closely (a company's own answer is only used for that company). Backlogs are left empty unless you chose an answer.
- **Website**: a new hero with a notice-style role card, and four illustration slots that stay hidden until the images exist. [docs/illustrations.md](docs/illustrations.md) has the prompts, sizes and palette to generate them.
- Home leads with the best fit waiting for you and one line each for fresh roles, applications, replies, interviews in the next two weeks, follow-ups due and skipped roles, each a tap from its page.

### Fixed
- A question such as "Please state your reasons..." is no longer mistaken for the State field.
- Plain-English searches for internships no longer drop every internship by also setting a level.

## [1.2.0] - 2026-11-11

### Added
- **CareerOS Autofill, a Chrome extension** (`extension/`). Press "Fill this form" on a company application page:
  - fills empty fields from your application details and attaches your resume PDF;
  - outlines what it filled in pink and lists what needs you (essays, consent boxes, anything it couldn't match);
  - "Track this application" adds the role to Applications, or updates it if CareerOS already found it (`POST /api/agent/track`).
  - It never submits, never ticks consent boxes, never overwrites what you typed, never fills passwords, codes, identity numbers, bank details or dates of birth, skips voluntary questions and other people's details, and doesn't run on LinkedIn, Naukri, Indeed or Wellfound.
  - It connects with the same computer key as auto-apply and only runs when you press its button, in the tab you're on. A workflow packages it as a zip.
- **Resume score** on every application and posting: how much of the posting's language your resume covers, with matched and missing keywords. Missing keywords are never added for you.
- **Line-by-line review of AI edits**: keep each tailored line, or switch it back to your own (one by one, or all at once).
- **Job families** on the public board and in Settings: Software Engineering, AI & Data, Product & Design, Marketing & Growth, Sales & Accounts, Finance & Strategy, Operations & People. The board adds quick lists (internships, new grads, remote, 20 LPA and up, posted in the last day) and shareable links. Choosing families in Settings matches whole families instead of a keyword list.
- The search now keeps business roles (marketing, sales, finance, operations, people) as well as tech roles.
- **Writing & interviews**: cover letters, five kinds of emails (follow-up, thank-you, referral request, note to a hiring manager, reply to a recruiter), answers to application questions with a word limit, and a mock interview with feedback on each answer. All of it is written only from your profile, with unknown numbers flagged. Templates and a question bank work without AI.

### Fixed
- Solid buttons kept their colour on hover (the text used to disappear).
- An unescaped apostrophe in an AI error message no longer stops the dashboard loading.

## [1.1.1] - 2026-11-05

### Changed
- **Unslopped the website, dashboard, phone app and sign-in pages** with the Appllama app design skill. The rules are written down in [docs/design.md](docs/design.md):
  - one accent (pink) and one warm grey family; the stray saturated blues, violets and teals are gone;
  - a single corner-radius scale;
  - one label per intent;
  - a dark theme on every page.
- **Motion has one vocabulary:** strong ease-out, 280 ms entrances, 190 ms exits, 120 ms presses. Every entrance plays once, from opacity and a short rise, never from `scale(0)` or blur.
- **Decorative motion deleted:** floating and spinning shapes, the infinite marquee, word-by-word headlines, count-ups, parallax, the tilt card and the typing terminal. Tabs change instantly, and lists animate only when a filter changes them.
- **The "Add..." sheet** grows from the "+", and its backdrop fades with it.
- **Back closes before it leaves:** sheets, the job sheet and application pages each own one history entry. Signing in, signing up and confirming your email can't be stepped back into.
- **Home has designed states:**
  - a skeleton shaped like the page while loading;
  - a three-step first-run state before the first match;
  - every touch target at least 44 px, muted text at 4.9:1 contrast, and the toast lifted above the dock.
- **Pricing** is rendered on the server, so it never shows a loading state.

## [1.1.0] - 2026-11-04

### Added
- **A product you can launch.** Free and Pro plans with Razorpay subscriptions (hosted checkout, verified and idempotent webhooks, cancel at the end of the cycle), operator grants for beta testers, and plan-based limits: matching every hour on Pro and daily on Free, AI actions per month, auto-apply per day and storage.
- **AI in the hosted app.** `/api/ai` runs dashboard AI actions on the service's model within the plan's monthly allowance, or on the user's own Anthropic, OpenAI-compatible or Gemini key, stored encrypted. OpenAI-compatible addresses are limited to known providers.
- **New design for the dashboard and the app**, matching the website: black sidebar on wide screens; on phones, a home with one big number and today's highlights as shapes, a floating dock with a pink "+" and an "Add..." sheet, and coloured detail screens.
- **Installable web app** (manifest, service worker, icons, an offline screen) and **Android and iOS apps** in `mobile/` (Capacitor), with a workflow that builds the Android app.
- Sign-in, pricing and policy pages (terms, privacy, refunds, contact) in the brand; pricing and app sections on the website; `docs/launch.md`.

## [1.0.0] - 2026-11-04

### Added
- **Bring your own model.** `careeros/llm.py` calls Anthropic, OpenAI (and any OpenAI-compatible API through `OPENAI_BASE_URL`), Google Gemini or a local Ollama model with your own key, using only the standard library. Configure it in `.env`; `careeros llm` shows the provider and model (never the key) and `careeros llm test` checks it.
- **AI commands with code checks.** `careeros ai profile`, `careeros ai posting` and `careeros ai evaluate`. Values the resume doesn't contain are dropped and listed; requirements are kept only with a verbatim quote; evaluations must pass the same validator as `careeros eval-check`, with one retry.
- **Dashboard on your model.** When a key is configured, the local dashboard's AI actions run through `/api/ai`, which accepts only same-origin JSON requests.
- **Project website and docs** in `website/`, deployed to GitHub Pages with the job board at `jobs.html` and the dashboard demo at `demo/`.
- `pages.yml` workflow to publish the site on every change; security policy, code of conduct, issue and pull request templates.

## Before 1.0

### 2026-10-29

- Referral finder after each application, junior engineers first, with a drafted note per person.
- "Apply yourself" rows for roles listed only on LinkedIn, Naukri or Wellfound, with answers prepared.
- One record per role across reposts, legal-name variants and location suffixes.
- Dashboard: Auto-apply page, Inbox from Gmail, 12 resume themes and a theme builder, applications board, application pages with AI tailoring, calendar and export.

### 2026-10-23

- Scoring, posting checks, documents, tracking and interview tools (ideas adapted from career-ops, MIT).
- Hiring radar, funding radar, a deep sweep of about 20,000 ATS boards, published pay ranges and a 20 LPA+ pay tier.
- YC companies as a scanned source.

### 2026-10-13

- CareerOS Cloud: a multi-user service with accounts, per-user pipelines, a worker with a durable task queue, an agent API and Docker Compose and Render deploy files.

### 2026-10-12

- Public job board on GitHub Pages with a JSON API and RSS, rebuilt by the hourly scan.
- Auto-apply switch, application details and resume upload on the dashboard, and the scheduled apply prompt.

### 2026-10-09 (first release)

- First release: gates with quotes, the India feed (1,396 companies across 8 hiring systems and 9 remote boards), the 96-platform registry, the claims checker, the apply agent with a one-submit state machine, agent skills and the local dashboard.
