# Changelog

All notable changes to Propelo. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses [semantic versioning](https://semver.org/).

## [Unreleased]

### Focus: the United States, the United Kingdom, Ireland and the Netherlands
- **Dollars only for members.** The India plans (Pro ₹799, Ultra ₹1,999, with smaller AI allowances) are removed before anyone bought them. Every member pays in US dollars through Dodo Payments, which charges in their own currency. A rupee checkout or pass is refused with "Plans are priced in US dollars". Razorpay stays only for rupee payment links from consultancies and agencies in India, and for any older rupee subscription until it ends. `PRO_PRICE_INR`, `ULTRA_PRICE_INR`, `PRO_AI_CREDITS_INR`, `ULTRA_AI_CREDITS_INR`, `PASS_PRICE_INR`, `GUARANTEE_INTERVIEW_PRICE_INR`, `RAZORPAY_PLAN_PRO` and `RAZORPAY_PLAN_ULTRA` are no longer read.
- **The Job Guarantee is retired.** It was an India-only talent-partner service paid by a fee after joining. The website, pricing page, terms, privacy notice and app no longer offer it; its tab shows only to an open case or on a server that sets `CONCIERGE=on`. The Interview Guarantee ($59, three interviews in 45 days or the money back, terms and conditions apply) is the one guarantee.
- **90-day passes for Pro ($99) and Ultra ($189)**, paid once, nothing renews. On by default; each goes on sale once its Dodo product is set (`DODO_PRODUCT_PASS`, `DODO_PRODUCT_PASS_ULTRA`). Buying a second pass adds its days, and an Ultra pass never steps down to Pro. The website, pricing page and Settings show them under Pro and Ultra.
- **Your own AI key is a Pro and Ultra feature** in Propelo Cloud. On Free, saving a key answers "part of Pro and Ultra", and a key saved before moving to Free stays saved but unused. Running Propelo on your own computer with your own key stays free.
- **New accounts start from the visa they hold.** The first-run questions ask for the roles, the countries or cities to work in (the UK, US, Ireland and the Netherlands are one tap away), and the visa, and there is no India-only search any more. Someone who isn't in one of the four countries yet picks "Not living in one of these countries yet" and says where they live; someone in India is matched like any member abroad. Sponsorship follows the visa: on for every visa, off for citizens and settled residents. Accounts that chose an India-only search before keep it until they next save Settings.
- **The scam check is for everyone abroad**: the tips name passports and SSN, National Insurance, PPS and BSN numbers alongside Aadhaar, and the "Lost money?" box lists where to report in the UK (Report Fraud), the US (FTC), Ireland (Garda), the Netherlands (Fraudehelpdesk) and India (1930). A request for a passport or ID number is now flagged as a caution.
- The README plan table matches the plans: Ultra's copilot and mock interviews have the fair-use limits the app enforces (200 a day, 60 a month), not "Unlimited".

### Added
- **What hiring you takes, for HR.** From the first reply to the offer, each role's sheet says what hiring you would take from the employer, for your visa and the country the role is in, with a note to HR ready to copy. A UK Graduate visa, Irish Stamp 1G, the Dutch orientation year and OPT need nothing from the employer today, and the note says so, with your own end date; then it says what keeping you would take later. A switch from a UK Student visa skips the Immigration Skills Charge (otherwise £1,320 for the first year, £480 for a small sponsor), and the note says that too. For each case it gives the employer's steps, the fees (UK certificate of sponsorship £525, sponsor licence £611 or £1,682; Irish Critical Skills permit €1,000; Dutch highly skilled migrant permit €423 and recognised sponsor €5,080 or €2,539; H-1B registration $215), the salary floors, and how long decisions take, each linked to the government page it comes from and dated (checked 25 November 2026). The H-1B note says plainly that the $100,000 payment is blocked by federal courts and under appeal, rather than guessing how that ends. The facts are in `propelo/data/sponsor_brief.json`, read by `propelo/sponsorbrief.py` and the dashboard alike (`scripts/sync_sponsor_brief.py` copies them in; a test compares the two). You send the note; Propelo never does.
- **Resume defence: a 15-minute spoken drill.** Writing & interviews has a new "Resume defence" tool. It takes the lines on your base or tailored resume that carry a figure ("Cut API latency by 40%", "£50k saved", "1,200 users"; years and version numbers like "Python 3.11" are left out), then lines that name one of your skills, six at most. The browser reads each question aloud (British English, or American for US roles) and you answer by speaking or typing; your browser turns speech into text, and Propelo keeps the text in the tab, never audio. After each answer the interviewer asks one follow-up aimed at the gap: a different figure from your resume ("Your resume says 40%. You said 35%. Which is right?"), no figure at all, no way of knowing, or only "we". The scorecard marks each line Defended, Partly defended or Not defended, with what was checked (the figure as your resume has it, how you know, your own part, about a minute) and what to fix; a figure that contradicts your resume is never "defended". The result for a tailored resume is saved on the role. The rules are in `propelo/drill.py`, and the dashboard runs the same rules (a test compares them). Free, no AI key needed.
- **Warm paths: alumni of both your universities, and the manager of the team.** "Find a referral" on each role now searches for alumni of every school on your resume (your university at home and the one abroad, three at most), then the manager of the team the role sits in (a Data Engineer's is the data engineering manager, a Product Designer's the design manager, a nurse's the nurse manager), then people with the same role, your 2nd-degree connections, and recruiters in the city where the role is (no longer "India" for every search). Under the connection note there is a message for after they accept, 75 words at most: the school you share when it's an alumni match, one real line of your work that fits the role (picked by the words it shares with the title and the role's skills; a line that isn't written as something you did is quoted, never reworded), and a plain ask with an easy way to say no. `propelo referrals` takes `--location` and `--resume` and prints the same message. The dashboard and `propelo/referrals.py` share the logic; a test runs both on the same inputs.
- **Pay against the Irish and Dutch work-permit minimums.** Like the UK Skilled Worker floors, a role in Ireland that states pay is set against the employment permit minimums from 1 March 2026 (€40,904 Critical Skills, €36,848 for a recent graduate, €36,605 General, €34,009 General for a recent Irish graduate), and a role in the Netherlands against the 2026 highly skilled migrant criteria (€5,942 a month at 30 and over, €4,357 under 30, €3,122 reduced). Each role shows a pill ("Meets Irish Critical Skills pay", "Meets Dutch pay if under 30", "Pay below Irish permit minimums") whose tooltip gives the figure it was checked against. For someone who needs sponsorship, pay below the lowest figure skips the role. An annual Dutch salary is shown with "about" and never used to skip, since it may include holiday pay. The UK new-entrant pill now says who it is for: under 26, or switching from a Student or Graduate visa.
- **Languages you work in.** Many Dutch postings ask for Dutch, and many Dublin roles for German or French. Propelo now reads what a posting asks of a language other than English: required in so many words (in English or in Dutch), named in the title ("German Speaking Account Manager"), written in Dutch, German or French, welcome but not required, or "you don't need to speak Dutch". Settings has "Languages you work in" (English unless you add more). A role that needs a language you haven't listed goes to the skip log with "Adding Dutch to the languages you work in." as the fix; "Dutch a plus" and "No Dutch needed" show as pills and never skip a role. Ordinary words are left alone: "a strong French team", "an Irish company", "our Dutch-speaking customers".
- **The extension fills forms built from web components, and waits for slow dropdowns.** Fields inside open shadow roots (Workday and Salesforce-based career sites build their forms this way) are found, labelled, filled, outlined and watched for late questions like any other. A custom dropdown no longer gets a fixed 350 ms to show its options: Propelo looks for a matching option every 80 ms for up to 3 seconds, and a search box that only searches on Enter gets one. Version 2.9.0, ready for the Chrome Web Store: the description fits the store's 132 characters, and `extension/store/listing.md` has the listing, the reason for each permission, the privacy answers and a screenshot; the packaged zip leaves those out.
- **Part-time while studying.** Students on a visa with a weekly work limit (F-1 and CPT, a UK Student visa, Irish Stamp 2, a Dutch study permit) get three things. "Hours this week" on Home logs each shift (day, employer, hours) against the limit for that week: 20 hours, 40 in the Irish summer and Christmas periods, 16 in the Netherlands and none in the Dutch summer, with a "University vacation this week" switch where the limit depends on term dates. A week that runs into a stricter period counts at the stricter limit, every job counts together, and it warns 2 hours before the limit and says plainly when a week goes over. In part-time mode, roles that are self-employed or gig work (freelance, independent contractor, delivery or rider partner, ZZP, KvK) are marked as not allowed on a US, UK or Irish student visa ("check your permit" on a Dutch one) and kept out of the part-time list. And the base resume has a "Part-time CV" switch: one page with your own summary, an availability line from your visa ("Available up to 20 hours a week in term time, and full-time in university vacations. Right to work: Student visa, United Kingdom."), your jobs in two lines each, education and skills, as a PDF or a Word file. Free includes all of it.
- **Plain words in every AI draft.** A list of 142 stock phrases that make writing sound machine-made or empty ("spearheaded", "leveraged", "robust", "proven track record", "I am writing to express", "testament to", long dashes and the rest), each with why and what to write instead. The prompts ask the model to avoid them; then every AI draft (tailored resume, cover letter, email, form answers, inbox replies, rewritten letter parts, achievement lines) gets the safe fixes automatically: a buzzword becomes the plain word ("spearheaded" to "led", "utilised" to "used", "in order to" to "to"), and an empty word goes ("robust", "seamless", "successfully"), with "a"/"an" and capitals put right. Nothing else is changed and no fact is added. A "Wording check" under each tailored application says what was changed and lists what is left to rewrite by hand; the writing tools show the same under their draft. The resume claims gate warns on the same phrases. `propelo/data/slop_rules.json` is the one list; `propelo/writing.py` and the dashboard apply it the same way (tests compare them).
- **Word files.** The base resume and each tailored resume download as a .docx: one column, standard headings, real bullets, nothing in tables, text boxes or headers, US Letter in the US and A4 elsewhere. "Print or save as PDF" stays for the designed themes, which are also one column.
- **Pinpoint, Teamtailor and iCIMS boards.** Many UK, Irish and Dutch employers, graduate schemes among them, recruit on Pinpoint or Teamtailor, and many large US employers on iCIMS. The scan now reads Pinpoint's public postings (with pay only when the employer shows it), Teamtailor's jobs feed page by page, and iCIMS's public listing pages, with the full description from each role's own page for roles in a job family Propelo matches. Discovery tries Pinpoint and Teamtailor for named companies, the hiring radar recognises links to all three, and the deep sweep adds their boards from the ats-scrapers inventory (MIT).
- **Sign in with a mobile number.** A member adds a number in Settings (confirmed with a texted code), then can sign in with it. Codes are sent and checked by Twilio Verify, and only ever to a number already confirmed on an account, so the form can't be used to text strangers. Off until `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN` and `TWILIO_VERIFY_SID` are set.
- **The Visa-Clock on Home.** Members tell Propelo their visa (F-1, F-1 on CPT, OPT, STEM OPT or H-1B in the US; Student, Graduate or Skilled Worker in the UK; Stamp 2 or Stamp 1G in Ireland; a study permit or the orientation year in the Netherlands) and its key dates. Home pins a countdown note to the board, lilac, then yellow inside 90 days (30 for day limits), then pink inside 30 (14): OPT and STEM OPT unemployment days left of 90 or 150 (paused while you have a job), days to an F-1 program end and then the 60-day grace period, the H-1B 60-day grace period after a job ends, and days left on a UK Student visa to switch to Skilled Worker with no Immigration Skills Charge. Under it: the work your visa allows today (Stamp 2 hours follow the calendar, Dutch students see full-time in summer), the next step, and the government pages each rule comes from, checked 25 November 2026. The count also sits in the top bar on every tab. Settings has a "Your visa" panel for every date. The rules live in `propelo/data/visa_rules.json`; `propelo/visaclock.py` and the dashboard compute the same answer, and the tests check both on the same dates.
- **Part-time while studying, or sponsored career.** Students on a visa that allows term-time work switch modes on the clock card. Part-time mode puts part-time roles and internships first in Fresh roles and turns the sponsorship filter off, since the student visa itself allows those hours; Sponsored career puts full-time roles from employers that can sponsor first. Roles now carry their job type (full-time, part-time, internship or contract) from the feed.
- **"Where you want to work".** The first-run questions and Settings ask for the countries or cities. Someone living in India is matched like a member abroad: office roles in those places, remote roles open to India, and the visa sponsorship check on the office roles.
- **Application details follow that answer.** For work outside India the form asks salary with its currency, postal code, university, and "your right to work where you are applying" instead of LPA, PIN code, backlogs and notice buyout. The browser extension fills the new answers into free-text boxes and "authorised to work" questions.
- **Sign in with Google and GitHub**, next to LinkedIn and email, each shown only when its keys are set. The sign-in and sign-up page is rebuilt in the website's style, with the providers' own logos.

### Changed
- **The home page is for job seekers; running Propelo yourself lives in the docs.** The terminal section (git clone, your own key, Ollama) moved off the home page (the docs already cover it), the pricing note no longer offers self-hosting under the plans, and the closing card's second button is "Browse open roles". The first principle is now "Your data, your call": download or delete everything from Settings. The example role at the top of the page now comes from the US, UK, Ireland or the Netherlands, prefers entry-level roles at employers with a sponsor record, and says which record ("Has sponsored H-1B visas", "On the UK sponsor register"); its pay is the posting's figure in its own currency, or "Not stated" when what the posting says isn't a salary. The demo's banner says "Use Propelo with your own resume, free" and links to sign-up instead of `propelo serve`. The dashboard formats numbers and dates the international way (en-GB). A town named like a country before a US state is a town: "Holland, Michigan" and "Mexico, Missouri" are in the US, and the website reads each role's country again from its location.
- **The job board starts on the US, UK, Ireland and the Netherlands.** It opens on roles in those four countries ("Everywhere", "Remote" and each country are one choice away), numbers use international separators (119,998, not 1,19,998), and pay is shown the way the posting states it, in its own currency: "$120,000–$150,000 a year", "£45,000 a year", "€4,000–€5,000 a month". The scan's lakh figure, which converts dollars, is never shown as a role's pay outside India, so the RSS feed and the API no longer print LPA for a US role; the API adds `pay`, `pay_currency`, `pay_max_annual` and `countries`. Search reads "£35k+", "$120k or more" and "€50,000" as a pay floor and knows UK, Irish, Dutch and US cities; "Well paid" means $100k, £50k or €60k a year or more. The header is the website's own (Pricing, For consultancies, Sign in, Start free). A region code next to a named country is no longer read as a US state: "Chennai, TN, India" is India and "Amstelveen, NH, Netherlands" the Netherlands, not Tennessee and New Hampshire; the board reads each role's country again from its location at every build.
- **The website opens on its content, and every page shows the same numbers.** The pink splash screen in front of the home page is gone. Each build writes the scan's numbers into every page (open roles, companies with open roles, company job boards, hiring systems, re-listed roles, scan date), so the home page, the docs and the job board agree; "open roles" is now the number the board lists and "companies" the companies those roles are at (the docs said "about 1,800 boards"). The visa-jobs pages cover the four countries (UK, US, Ireland, Netherlands) and say how many roles matched, ("Newest 150 of …"), with a link to all of them on the job board; the Canada, Australia and Germany pages send visitors to the overview. The sponsor check searches the UK, US, Irish and Dutch lists. Old or guessed addresses now land somewhere: `/scam` goes to the scam check, `/pricing` to the plans, and `/terms`, `/privacy`, `/refunds`, `/contact` and `/business` to the app's pages.
- **The website, rewritten shorter.** Section headings on the home page were paragraphs of up to 34 words set at headline size; each is now one line or two, with the detail in a short paragraph under it where it was needed. The hero, the notes, the tools, the steps, the guarantee and the pricing copy are tighter, and the scam check, sponsor check, docs and visa jobs pages lose their longest sentences. No fact or figure changed; "several times a day" became "every hour", which is how often the scan runs. Plan feature lines are shorter too, on the website and in the app.
- **An accuracy fix:** the self-host section no longer says your resume never leaves your computer. With a hosted AI provider, the requests that read or write go to that provider; with Ollama nothing leaves.
- **Smaller fixes from an unslop pass:** one line of free-tool links under the hero buttons instead of two, steps numbered 1 to 4 instead of 01 to 04, no full stops on headings, and highlighted phrases kept on one line.
- **No people illustrations on the website.** The Open Peeps characters are gone from the home page and the scam check.
- **Every app screen checked against the design.** Page titles read the same on every tab (the highlighted word, no icon beside it on some pages and not others). "Found a job somewhere else?" is a quiet card, so colour stays with the best-fit card, the four tiles and the visa clock. Empty Outreach groups say so in a card instead of leaving a lone heading. Settings opens with "Your visa". The public demo shows a UK Graduate visa clock.
- Times are shown in the member's own time zone ("London time") instead of IST, on the auto-apply run log and in drafted interview replies. The "20 LPA+" filter and pill show only for India-only searches. Placeholders name Monzo instead of Razorpay. The AI notices on Ask Propelo, LinkedIn review and interview prep match the plans: in Propelo Cloud, AI and your own key are part of Pro and Ultra; running Propelo yourself, you add your own key.
- **People on the board.** Young characters from Open Peeps (Pablo Stanley, CC0), redrawn in Propelo's colours, now appear where a page was bare: a graduate presenting the role card in the website's hero, two people sitting on the closing card, someone checking a message on the scam check, a graduate beside the sign-up board, a shrug on the 404 page, and a person on each empty screen in the app (fresh roles, today's batch, inbox, contacts, interview prep). In dark mode each figure has a thin paper outline. `scripts/peeps` rebuilds them from the Sketch file; `scripts/peeps/cast.json` lists every character and where it is used.
- **The website loses its template tells.** No more label chips above the headings, faded section numbers (02 to 07) or "03.1" tags. The giant "32,776 open roles" card is now three sentences that say what was checked. The principle notes have short titles instead of numbers, and the fourth one now says plainly that recruiter emails go out only if you turn them on. The hero's tool links are underlined rather than highlighted, so the highlighter marks one phrase per heading.
- Numbers and dates on the website use the British format (32,776, "31 October 2026") instead of the Indian one.
- Cards and rows lift on hover only with a mouse or trackpad; a tap on a phone no longer leaves a card lifted. The principle notes arrive 70 ms apart instead of 120 ms.
- The not-found page matches the website: the board, a pinned 404 note and the pill buttons.
- **The public demo is a graduate in London who needs sponsorship**, with roles in London, Manchester, Amsterdam and Dublin, pay in pounds and euros, and UK and Dutch sponsor-register pills. It was a fresher in Bengaluru.
- For members outside India mode, the role cards drop the LPA pay pills, the pay icon is a banknote unless the pay is in rupees, the filter summary reads "in United Kingdom, Netherlands (on-site or hybrid) and remote from the United Kingdom", and the pay floor shows in dollars. Pasted postings recognise major cities abroad.
- Consultancy packs and the agency feed bought in rupees now cost the same as in dollars (Starter ₹28,599, Growth ₹54,999, Plus ₹1,07,799, feed ₹8,699), since every seat carries the global allowance. The rupee Pro pass, still off by default, is ₹2,999.

### Fixed
- The resume headline on the Base resume page sat in a large rounded box: the app's highlight-card style leaked onto the paper.
- **Workday boards read the four countries, in every field.** Workday sites were narrowed to India and only tech titles got their full description, which dropped every US, UK, Irish and Dutch role and every non-tech one. They are now narrowed to the US, UK, Ireland and the Netherlands through each site's own country filter (a site without one is read whole), and roles in any job family Propelo matches are read in full, graduate, intern and junior titles first.
- **Graduate schemes get a level.** Titles such as "Graduate Scheme", "New Grad", "Early Careers", "Rotational Program" and "Class of 2027" were tagged "Not stated" when the posting gave no years; they are now Fresher, "Undergraduate placement", "Industrial placement", "Summer Analyst" and co-op roles are Internship, and "Junior" and "Entry-level" titles are Entry. "Graduate programme" and "early careers programme" in a posting now count as welcoming freshers.
- When the published feed is over its size cap, roles in the four countries and remote roles are kept first, then India and the other study countries.
- An account made with Google, GitHub or LinkedIn has no password, so it could not be deleted (the form asked for one). Typing DELETE in a signed-in session now does it, and Settings explains how to add a password instead of showing "Change password".
- In-app plan prices read $39 rather than $39.00, and the mobile number field on the sign-in page has the same style as the others.
- Arbeitnow roles outside Germany (its French, Dutch and other sites) no longer get ", Germany" added to their place, which showed a role in a Paris suburb to someone who chose Germany. The country now comes from the place, or from the Arbeitnow site the posting is on.
- "1 are somewhere else" and similar near-miss counts now read in the singular.
- A provider sign-in on an address someone else typed into the sign-up form but never confirmed now removes that person's password and sessions.

## [2.16.2] - 2026-11-24

### Fixed
- **"Sign-up failed. Try again." with no reason.** When the server could not reach its database it answered a bare "Internal Server Error", which the sign-up and sign-in pages could not read, so they showed a sentence that said nothing. Every server fault now answers with a sentence the page shows: "Propelo can't reach its database right now" when the database is the cause, otherwise a reference number to quote to support. The log line carries the same reference. The pages also say "Propelo is starting up" when the host answers while the free instance wakes.

## [2.16.1] - 2026-11-23

### Fixed
- **The sponsor sweep slowed discovery down about six times and found nothing.** Its first run looked at 52 register employers and kept no board, while the rest of discovery checked 260 companies instead of about 1,500: register guesses were tried on every hiring system, and some take seconds to answer that a board does not exist. Guesses now go only to Greenhouse, Lever and Ashby, which answer at once, and 150 a run instead of 500. Whether the sweep is worth keeping is decided by its yield over the next few days (register item R-059).
- Visa job lists left out volunteer and unpaid places, and roles whose title places them in another country ("relocation to New Zealand").

## [2.16.0] - 2026-11-23

### Changed
- **The name is Propelo everywhere people can see it.** The Python package is now `propelo` (`propelo/` in the repository, `pip install "propelo[cloud]"`), the command is `propelo`, settings can be written `PROPELO_*`, the computer key lives in `~/.propelo/key`, and the Render blueprint names its services `propelo-web`, `propelo-worker` and `propelo-db`. The session cookie, the request header pages send on writes, file names (`propelo-export.json`, `propelo.pyz`, `propelo-autofill-*.zip`) and the user agents changed too. What keeps working: the `careeros` command, `CAREEROS_*` settings, the old request header from a page loaded before the update, and the database names of an existing deployment. Signed-in members are asked to sign in once more, because the cookie has a new name.

### Fixed (design)
- Dropdowns on the job board showed the browser's own arrow pressed against the edge. They now have one chevron with room around it, the same height and rounding as the fields beside them, in light and dark mode.
- The list chips (Top companies, Internships and the rest) wrapped onto a second line, leaving "Saved" alone below. They stay on one line and fade at the edge only while there is more to scroll.
- On a phone the search field, the place picker and the Search button fill the width, and the sort menu sits beside Filters.
- At tablet width the job board header broke onto two lines; the developer links (API, demo, GitHub) step aside there and stay in the footer.
- Big headings on the home page and the pricing page started with an indent that read as a mistake, and long headings took up to two seconds to finish appearing. No indent, and every heading is readable in about half a second.
- The footer had nine links under Product and two under Developers, and each page had its own version. One footer on every page: Product, Free tools, Developers, Legal.
- The install commands on the home page were cut off at the right edge on phones; they wrap now.
- The pricing page header wrapped "For consultancies and agencies" and the Sign in button onto two lines on phones.
- In the app, the Fresh roles tab showed a summary, four pipeline cards and the auto-apply panel before the first role. The roles come first now.
- The sign-in page said Propelo reads "about 1,800" career pages; it reads over 9,000. The job board no longer shows how many roles have a logo, and no longer calls every role a "tech" role.

## [2.15.1] - 2026-11-23

Found by importing a resume and starting an application as a new member, with no AI key on the server.

### Fixed
- **Importing a resume filled in only the name, contact details and skills,** and nothing was saved until "Save profile" was pressed, so the next screen said "Your profile is empty". The import now reads jobs (title, employer, place, dates, bullet points), education and projects from the resume's own sections, copied as written, and a first import is saved straight away. Checked on three layouts and in the page: profile strength 62 of 100 from one upload, then a tailored resume, cover letter and email for a matched role.
- A name with letters outside A to Z ("Anna Müller") was skipped and a section heading taken as the name; a date range ("2023 - 2025") was taken as a phone number; "Skills: Go, Java" on one line gave no skills.

## [2.15.0] - 2026-11-23

### Added
- **Sponsor sweep: the job boards of employers on the government sponsor lists.** The lists name about 119,000 employers that can or do sponsor work visas (UK 95,000, Netherlands 11,700, US 6,600, Ireland 4,600, Canada 900 after leaving out takeaways, care homes, farms and similar). Most of their roles were not in the feed because nobody had listed their board. `careeros sponsor-candidates` turns the lists into candidates and `discover` tries 500 of them a run (`CAREEROS_SPONSOR_SWEEP`), the countries in turn. A board is kept only when it lists roles in that country and its own name leads back to that register entry by the same rule that labels roles, so "Apex" on a hiring system is never taken for one of the dozens of Apex companies on the register. Nothing is added to the board list for a name until it has been looked at, and one board is never read under two names.
- The scan summary reports `sponsorSweep` (checked, kept).

### Fixed
- **A perk was read as "open worldwide".** "Up to 2 months a year with our Work from Anywhere policy" and "we have a global presence and many roles can be remote" made office roles in London and Melbourne appear as remote worldwide for members in India. The scanner now tells these apart, and the filters drop the wrong answer from feeds written before the fix.
- Remote roles that do not say who can apply are ranked after the ones known to be open, in India as well.

## [2.14.0] - 2026-11-23

Found by signing up as a new member against the live feed (120,000 open roles) and by running eight realistic profiles through the matcher.

### Fixed
- **A person's first match used 1.9 GB of memory and took 56 seconds.** It read every open role into memory at once. On a 512 MB server the worker would have been killed before anyone saw a match. Roles are now read as a stream, and a role is read in full only when its title fits: the same match takes 2 to 6 seconds and about 75 MB.
- **A repeat match read everything again.** It now reads only roles added, changed or reopened since the last one, with a full pass when the filters change, when the last run found more than it could add, or once a week. The settings hash that decides this now covers every filter (it left out the sponsorship and stated-pay switches).
- **New members landed on the whole Settings page** (plans, AI key, about forty application fields) when they pressed "Set your filters", and were told matches arrive "after the next scan". Home now asks three things (roles, country, years, plus a sponsorship tick abroad) and shows matches about ten seconds later.
- **Members abroad were shown roles they cannot take:** remote roles placed in another country the tables did not know (Kazakhstan, "NYC", Belgrade and about 60 more places are now known), director and "Head of" titles for someone with two years of experience, and remote roles in their own country that say they cannot sponsor.
- **Changing filters left the old matches in the list.** Roles nobody touched that no longer fit are taken back, which also clears what the starting filters matched before the person answered.
- Filters saved while a match was running were not matched until the next scheduled run.
- "Belgrade, Montana", "Athens, Ohio" and "Cambridge, Massachusetts" were read as Serbia, Greece and the UK.
- Near misses shared room with found roles, so a long skip list could stop new matches arriving. Each now has its own limit (700 found, 200 near misses).

### Changed
- For members abroad, roles where they live come first, employers with a record of sponsoring visas at the top, then remote roles open worldwide, then remote roles that do not say who can apply. India keeps its order.
- A short list now says how many roles came close and why, with a link to them.
- The first match after saving filters starts after 2 seconds instead of 15.

## [2.13.0] - 2026-11-23

### Added
- **One-server mode for a free or single-instance host (`ALL_IN_ONE=on`).** `careeros cloud serve` then brings the database up to date, runs the worker as a child process beside the web app, starts it again if it stops, and stops it when the web app stops. Measured on the live feed: 97,547 roles taken in, about 80 MB for the web app and 90 MB for the worker.
- **Uploads in the database (`STORAGE=db`).** Resumes are kept in a `blobs` table instead of on a disk, for hosts where a service has no disk of its own. The file and its listing are saved in one transaction.
- **`render.free.yaml`:** a Render blueprint with one free web service and a free database. Its header lists the limits: the service sleeps after 15 minutes without visitors, the free database is deleted after 30 days unless upgraded, and email needs the provider's alternative port.
- Emails carry `Reply-To: SUPPORT_EMAIL`, so replies reach the support inbox even when the sending address is one nobody reads.
- On Render the app uses the address Render gives the service until `PUBLIC_URL` names the real domain, and the image listens on the port the host names in `PORT`.

### Fixed
- **A hand-made Render service crashed at start with `PermissionError: 'data'`.** With no `DATABASE_URL` the app fell back to a local file it was not allowed to create. The free blueprint connects the database for you.
- The feed address pointed at the repository's old name (it worked only through GitHub's redirect).

## [2.12.1] - 2026-11-22

### Fixed
- **The deep sweep was never reached.** Discovery took due companies in list order, so curated companies that never map used up every run and the 21,000 inventory boards waited behind them. A quarter of each run now goes to the curated and radar lists and the rest to the sweep (one request per board, 3,000 companies a run), taken in turn.
- Irish permits list counted January instead of the year's total.
- Site deployments wait for the uploaded artifact and try once more; the `pages` workflow builds from the release feed instead of the retired `feed` branch.

## [2.12.0] - 2026-11-22

### Added
- **Sponsor lists for the United States, Canada and Ireland.** A weekly workflow (`registers.yml`, `careeros registers`) reads the US Department of Labor's H-1B labor condition data, Canada's list of employers with a positive LMIA and Ireland's employment permits issued to companies. Roles in those countries show when the employer has sponsored, the job board can filter on it, the visa-jobs pages use it, and the free sponsor check now covers five countries. A missing name is never reported as "cannot sponsor": only the UK and Dutch licence registers can say that. Australia, New Zealand, Singapore, Sweden and Germany publish no list that can be searched in bulk, so for those the posting's own words are used.
- **Straight to checkout.** "Get Pro" and "Get Ultra" on the site and on `/pricing` now lead through sign-up and email confirmation directly to the payment page (`/app?buy=pro`). Cards, UPI, Apple Pay and Google Pay are handled on Razorpay's and Dodo's own pages, as before. When the Pro pass is on, `/pricing` shows it too.

## [2.11.0] - 2026-11-22

Built to bring people in without ad spend and to make each channel measurable.

### Added
- **Free sponsor check** (`sponsor-check.html`): type a company name and see whether it is on the UK Home Office register of licensed sponsors or the Dutch register of recognised sponsors. Runs in the browser from the registers the scan already downloads.
- **Visa sponsor jobs pages** (`visa-jobs.html` and one page each for the UK, US, Canada, Australia, Germany, the Netherlands and Ireland): recent junior and mid-level roles with a sponsorship signal, read from employers' own career pages and rebuilt by every scan. Roles that say they cannot sponsor are never listed. The same lists are written as Markdown (`lists/*.md`) for a public list on GitHub.
- **Sign-up sources.** A link can carry a short label (`?src=reddit-ukjobs`; `utm_source` and `ref` work too). The label is kept with the sign-up, and `/admin` shows, per label, how many people signed up, confirmed, built a profile, got matches, applied and pay. A label only: no advertising cookies.
- **Pro pass, off by default (`PASS=on`).** Pro for 90 days paid once, by UPI or card in rupees or a one-time checkout in dollars; nothing renews. A second pass adds its days to the first.
- **Help from every screen:** an "email the team" link in the app's side menu.

### Fixed
- **The job board had no way to sign up.** It now has a "Get matched free" button and a line on every role page.

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
