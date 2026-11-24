# Chrome Web Store listing: Propelo

Everything the Chrome Web Store developer dashboard asks for, ready to paste. The package is the zip from the
`extension` workflow (GitHub Actions), which leaves this `store/` folder out.

## Store listing

**Name** (from the manifest): Propelo: autofill, match score and apply queue

**Summary** (the manifest description, 132 characters at most; this is 122):
See how well a role matches your real resume, fill application forms from your Propelo profile, and press Submit yourself.

**Category**: Productivity (Workflow and planning)

**Language**: English (United Kingdom)

**Description**:

Propelo helps you apply for jobs honestly and faster, on each company's own careers site.

Match score. On a job page, see how well the role matches your real resume, out of 100, with the arithmetic: which required skills you can prove, which only appear in your skills list, and which are missing. It's a keyword and experience check, not how the employer's software ranks you.

Fill forms. Press Fill this form and Propelo fills the empty fields from your Propelo profile: name, contact details, links, education, work history, notice period, right to work, and answers you saved. Your resume PDF is attached where the form asks for one. Filled fields get a pink outline; anything it can't answer from your profile gets an orange outline and is listed for you. It works on Greenhouse, Lever, Ashby, Workday, SmartRecruiters, Workable, iCIMS and most other career sites, including forms built from web components and dropdowns that load their options late.

Apply queue. Work through the roles you approved in Propelo one at a time: each opens, fills, and waits for you. When the page confirms your application, Propelo records it and opens the next.

What it never does:
• Press Submit, tick consent boxes, or overwrite anything you typed.
• Fill passwords, one-time codes, identity numbers, bank details, passport numbers or dates of birth.
• Answer voluntary questions such as gender or disability.
• Run on LinkedIn, Naukri, Indeed or Wellfound, which don't allow automated filling.
• Read a page you didn't allow.

You need a Propelo account (free at propelo.org) and a computer key from Propelo's Settings.

**Website**: https://propelo.org
**Support**: https://app.propelo.org/contact

## Privacy practices tab

**Single purpose**: Fill job application forms and show a match score from the user's own Propelo profile, on pages the user chooses.

**Permission justifications**

| Permission | Justification |
|---|---|
| activeTab | Reads and fills the job page the user is on, only when they press a button in the popup. |
| scripting | Runs the form filler and the match reader in that tab when the user asks. |
| storage | Keeps the user's Propelo address and computer key in this browser, and the sites they hid the panel on. |
| Host permissions (optional, asked at run time) | The user's Propelo address, to read their profile and record applications; and the hiring sites the user allows when they turn on the on-page panel or start the apply queue, to fill forms there. Nothing is requested at install. |

**Remote code**: No. All code ships in the package; nothing is loaded from elsewhere or evaluated.

**Data usage** (tick these in the form):

| Data type | Collected? | Why |
|---|---|---|
| Personally identifiable information (name, email, phone, address) | Yes | Read from the user's own Propelo account to fill the forms they choose. Not sent anywhere else. |
| Authentication information | Yes | The Propelo computer key, kept in this browser to talk to the user's Propelo account. Never shown to web pages. |
| Website content | Yes | The job title, company and description of a page the user scores or tracks, sent to their own Propelo account. |
| Health, financial and payment information, personal communications, location, web history, user activity | No | |

**Certify**: the data is not sold to third parties, not used or transferred for purposes unrelated to the single purpose, and not used or transferred to determine creditworthiness or for lending.

**Privacy policy URL**: https://app.propelo.org/privacy

## Images

- Icon: `icons/icon-128.png` (already in the package).
- Screenshots (1280×800): `store/screenshot-fill.png`, a Workday-style application form after Fill this form, with filled fields outlined in pink and the ones left for the user in orange.
- Small promo tile (440×280): optional; not made.

## After review

Reviews usually take a few days. Once it's live, put the store link on the website (Tools section) and in Propelo's Settings, Your computer, in place of the Load unpacked steps.
