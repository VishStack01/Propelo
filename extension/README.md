# Propelo for Chrome: match score, autofill and apply queue

Shows how well a role matches your real resume, fills application forms from your Propelo profile, and walks your apply queue one role at a time. You review every answer and press Submit yourself.

## Install

1. Get the zip from the latest **extension** workflow run (GitHub Actions tab), or use this folder directly.
2. Open `chrome://extensions`, turn on **Developer mode**, press **Load unpacked** and pick the `extension` folder (unzipped).
3. In Propelo: Settings, Your computer, **Create computer key**. Copy the key (it starts with `cos_k_`).
4. Click the Propelo icon in Chrome, enter your Propelo address and the key, press **Connect**.

## Use

**Match score.** On a job page, the popup (or the on-page panel) scores the role against your real resume: the resume in Propelo, else the text of the resume you uploaded, else your Career Brain. 70% is the posting's skills found in your resume (in a bullet or summary counts fully, only in your skills list counts half), 20% your years against the years asked, 10% the title against your target roles. It lists what you have and what the posting asks that your resume doesn't, to add only if true. It's a keyword and experience check, not how the employer's screening software ranks you. Scam warnings show on the same card.

**On job pages.** Switch on **Show Propelo on job pages** in the popup and allow the sites it lists (Greenhouse, Lever, Ashby, Workday, SmartRecruiters, Workable, Recruitee, Teamtailor, iCIMS, Jobvite, Breezy, BambooHR, Personio, Zoho Recruit, Darwinbox, Keka, Freshteam, SuccessFactors, Taleo). A small panel then shows your match and a **Fill this form** button. **×** hides it on that site.

**Apply queue.** The popup lists the roles waiting in your Propelo queue (ones you approved, and, with auto-apply on, roles above your apply line that pass the scam check), within your plan's daily limit. **Start applying** opens the first in a tab, waits for the form and fills it. Check it and press Submit: when the page confirms the application, Propelo records it as applied and opens the next role. **I submitted it, next**, **Skip** and **Stop** are on the panel. On Greenhouse, Lever and Ashby, Propelo Cloud's auto-apply can also send applications for you without a browser; the queue is for every other site, and for when you'd rather check each one.

**Fill a form.** Open an application form and press **Fill this form**.

- Filled fields get a pink outline. Fields that need you get an orange dashed outline and are listed in the popup.
- Your resume PDF is attached to the resume upload when the form has one.
- Campus questions (CGPA or percentage, branch, state, PIN code) are filled from your application details. Active backlogs stay empty unless you chose an answer in Propelo.
- A question that closely matches one of your **Saved answers** (Writing & interviews) gets that answer, and the popup says how many came from them. An answer saved for one company is only used on that company's forms; essays you haven't saved an answer for are listed for you.
- **Track this application** adds the role to your Propelo applications (or updates it if Propelo already found it).

## What it never does

- Press Submit, tick consent boxes, or overwrite something already typed.
- Fill passwords, one-time codes, Aadhaar, PAN, bank details, passport numbers or dates of birth.
- Answer voluntary questions (gender, disability and the like) or fill in someone else's details (a referrer, a reference).
- Run on LinkedIn, Naukri, Indeed or Wellfound. Those sites don't allow automated filling and it can get your account restricted, so the popup only offers to track the role.
- Read pages you didn't allow. Without the on-page switch it reads a page only when you press a button in the popup, and only the tab you're on (`activeTab`). With it, it runs only on the hiring sites listed above, and only after you allow them.
- Show your key to a page. The server address and computer key stay in the extension's background; the on-page panel lives in a closed shadow root and asks the background for everything.

## Permissions

| Permission | Why |
|---|---|
| `activeTab`, `scripting` | Fill the tab you're looking at, when you press the button |
| `storage` | Keep your Propelo address and computer key in this browser |
| Your Propelo address (asked when you connect) | Read your application details and resume, and track roles |
| A form's frame host (asked only if a form is embedded from another site) | Fill forms embedded from Greenhouse, Lever and similar |
| The hiring sites listed above (asked when you switch on the on-page panel or start the apply queue) | Show your match and fill forms on those sites |
| The sites of the roles in your queue (asked when you press Start applying) | Fill each role's form when it opens |

The computer key can only read your application details and report applications. Remove it any time in Propelo (Settings, Your computer) or press **Disconnect**.

## Works best on

Built and tested on Greenhouse, Lever and Ashby style forms and plain HTML forms. Other sites vary: whatever it can't match is listed under Needs you. Workday's custom dropdowns are left for you; its text fields are filled.

## Tests

`python -m pytest tests/test_extension.py` runs the fill script against fixture forms in Chromium.
