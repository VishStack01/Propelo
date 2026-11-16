# Launching Propelo

The code is ready. What's left needs accounts, money or a signature that only you can provide. Work through the list in order: each step says where to click and which setting it fills in.

## Your to-do list

| # | What | Time | Cost | Blocks |
|---|---|---|---|---|
| 1 | [Deploy on Render](#1-deploy-on-render) | 1 hour | Paid plan for web, worker and database | Everything |
| 2 | [Domain and email sending](#2-domain-and-email) | 1 hour + DNS wait | Domain, SMTP provider | Sign-ups, Razorpay review |
| 3 | [Hosted AI and a fallback](#3-hosted-ai) | 15 min | Model usage | AI allowance on paid plans |
| 4 | [Razorpay for India](#4-razorpay-rupees) | 1 to 5 days (KYC) | Fee per payment | Rupee checkout |
| 5 | [Dodo Payments for everyone else](#5-dodo-payments-dollars) | 1 to 3 days (review) | Fee per payment | Dollar checkout |
| 6 | [Google OAuth for recruiter emails](#6-gmail-sending) | 1 hour, then Google's review (weeks) | Free | Automatic recruiter emails for the public |
| 7 | [Business and tax](#7-business-and-tax) | Varies | Accountant | Live payments |
| 8 | [Backups, monitoring and a security test](#8-backups-monitoring-security) | Half a day | Small | Inviting people |
| 9 | [Store listings](#9-phone-apps) | 1 to 2 weeks with review | Play and Apple fees | The phone apps |
| 10 | [Repository settings and launch](#10-repository-and-launch) | 30 min | Free | Discovery |
| 11 | [Concierge](#11-concierge) | 1 to 2 weeks | Staff time, lawyer | The human-run service |
| 12 | [Guarantees](#12-guarantees) | 1 day, plus a lawyer's review | Refunds you budget for | The Interview and Job Guarantees, by application |
| 13 | [More job sources and the extension](#13-sources-and-extension) | 1 hour, plus Chrome review | Free keys; $5 Chrome fee | Openings outside company boards; the extension for everyone |

## 1. Deploy on Render

1. In Render, choose **New > Blueprint** and pick this repository. It creates `careeros-web`, `careeros-worker` and `careeros-db`. The free tier isn't enough (workers and disks aren't free, and free databases expire); check prices at render.com/pricing before you confirm.
2. On `careeros-web`, set `PUBLIC_URL`, `SMTP_URL`, `MAIL_FROM`, `SUPPORT_EMAIL`, `BOOTSTRAP_ADMIN_EMAIL` (your own email: it becomes the operator) and `COMPANY_NAME`. `SECRETS_KEY` is generated for you. **Never change it** after users save keys or connect Gmail: everything encrypted with it becomes unreadable.
3. The worker copies most values from the web service. Set `PUBLIC_URL`, `SMTP_URL`, `MAIL_FROM`, `SUPPORT_EMAIL` and `BOOTSTRAP_ADMIN_EMAIL` on it too.
4. Redeploy. The release step runs `careeros cloud migrate`. `https://<your-app>/api/ready` should answer `"ok": true`.

## 2. Domain and email

1. Buy a domain and point `app.yourdomain` at Render (Settings > Custom Domains). Update `PUBLIC_URL` on both services.
2. Pick an SMTP provider (Resend, Brevo, Zoho Mail, Amazon SES). Add its **SPF**, **DKIM** and a **DMARC** record (start with `p=none`, move to `quarantine` after two clean weeks). Without them, confirmation emails land in spam.
3. Create `support@` and `security@` mailboxes and set `SUPPORT_EMAIL` and `SECURITY_EMAIL`. The second appears in `/.well-known/security.txt`.

## 3. Hosted AI

Set `CAREEROS_LLM=anthropic` and `ANTHROPIC_API_KEY` on `careeros-web` (or `openai` / `gemini` with their key). Add a second provider for outages: `CAREEROS_LLM_FALLBACK=openai` plus `OPENAI_API_KEY`. Set a monthly spending limit in each provider's console. Allowances: Free 15, Pro 400, Ultra 1,500 AI actions a month (`FREE_AI_CREDITS`, `PRO_AI_CREDITS`, `ULTRA_AI_CREDITS`). People's own keys cost you nothing.

Rough cost check before you set prices: an AI action is one model call of a few thousand tokens. Multiply your provider's price per call by 1,500 and make sure Ultra still leaves margin after payment fees and tax.

## 4. Razorpay (rupees)

1. Sign up and complete activation (KYC). Razorpay reviews your website: give it the app's address and these pages, which the app serves: `/terms`, `/privacy`, `/refunds`, `/contact`, `/pricing`. Have the policy text reviewed for your situation first; it's a plain-language starting point, not legal advice.
2. In **Test mode**, under Subscriptions > Plans, create two monthly plans: **Pro at ₹499** and **Ultra at ₹1,199**. Copy their `plan_...` ids.
3. Settings > API Keys: generate a key id and secret.
4. Settings > Webhooks: add `https://<your-app>/api/billing/webhook`, choose a secret, select the `subscription.*` events.
5. Set `RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET`, `RAZORPAY_WEBHOOK_SECRET`, `RAZORPAY_PLAN_PRO` and `RAZORPAY_PLAN_ULTRA` on `careeros-web` and redeploy.
6. Test with a test card or UPI id: upgrade to Pro, then switch to Ultra (Pro stays on until Ultra is paid, then Pro is cancelled for you), cancel, and check that Razorpay's webhook log shows 200s.
7. Go **Live**: create the same plans and webhook in live mode (the ids differ) and replace the values.

## 5. Dodo Payments (dollars)

Dodo is the merchant of record for sales outside India: it charges, files VAT and sales tax, and pays you out.

1. Sign up at dodopayments.com and complete business verification.
2. In test mode, create two subscription products: **Pro at $22.50 a month** and **Ultra at $48.50 a month**. Copy their `pdt_...` ids.
3. Developer > API keys: create a key. Developer > Webhooks: add `https://<your-app>/api/billing/dodo-webhook` and copy the `whsec_...` secret. Subscribe to the `subscription.*` events.
4. Set `DODO_API_KEY`, `DODO_WEBHOOK_SECRET`, `DODO_PRODUCT_PRO`, `DODO_PRODUCT_ULTRA` and `DODO_MODE=test`. Redeploy and run the same tests as for Razorpay, plus **Invoices and card** in Settings, which opens Dodo's customer portal.
5. Go live: create live products and webhook, replace the values and set `DODO_MODE=live`.

Two things in the Dodo integration follow its documentation as of this release but weren't tested against a live account: cancelling (`PATCH /subscriptions/{id}` with `cancel_at_next_billing_date`) and the customer portal link. Check both in test mode before going live.

## 6. Gmail sending

Automatic recruiter emails send from each person's own Gmail with the `gmail.send` permission only.

1. In Google Cloud console, create a project, enable the **Gmail API**, and set up the **OAuth consent screen** (External): app name Propelo, your support email, your domain, links to `/privacy` and `/terms`, scopes `openid`, `email` and `.../auth/gmail.send`.
2. Credentials > Create OAuth client (Web): redirect URI `https://<your-app>/api/mailbox/google/callback`. Set `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` on the web service (the worker copies them).
3. While the app is in **Testing**, only the test users you list (up to 100) can connect. That's enough for a beta.
4. To open it to everyone, submit the app for **verification**. `gmail.send` is a sensitive scope, so Google reviews the privacy policy (already includes the Limited Use statement), a demo video of the connect flow and the domain. Plan for a few weeks.
5. Keep sending reputation healthy: the limits are 10 a day on Pro and 25 on Ultra, only to addresses found on a public page, with an opt-out link and header on every email. Watch for complaints in `/api/admin/audit?kind=email-sent` and lower the limits if needed.

## 7. Business and tax

- **India:** charging for a service usually means GST registration once you cross the threshold, and Razorpay needs a business or individual KYC. Ask an accountant whether to start as a sole proprietor or register a company, and whether to show prices including GST (the pages say "includes GST where it applies").
- **Abroad:** Dodo handles sales tax and VAT as merchant of record, so you don't register in each country.
- Keep the refund promise on `/refunds` (7 days for mistakes and first payments) and answer `SUPPORT_EMAIL` within two working days.

## 8. Backups, monitoring, security

- **Backups:** turn on daily backups and point-in-time recovery for the database (Render PostgreSQL paid plans include them). Restore one into a scratch database once, following [the runbook](runbook.md).
- **Errors:** create a Sentry project and set `SENTRY_DSN` on both services (the Docker image includes the client). Only the error and route are sent.
- **Uptime:** point an uptime monitor at `/api/ready` every minute, alerting your phone.
- **Load:** run `k6 run scripts/loadtest.js` against a staging copy with 50 virtual users. The thresholds in the script are the bar: under 1% errors, reads under 400 ms at the 95th percentile.
- **Security:** the repository runs CodeQL, pip-audit, gitleaks and Dependabot. Before the public launch, get an independent penetration test of the web app, the billing webhooks and the Gmail flow, and turn on GitHub's private vulnerability reporting (Settings > Security).
- Work through [the release checklist](cloud-release-checklist.md).

## 9. Phone apps

The web app is installable already. For the stores, see [mobile/README.md](../mobile/README.md). Payments stay on the web: the apps hide upgrade buttons, because Apple and Google require their own billing for in-app digital subscriptions. Fill in Play's Data safety form and Apple's privacy labels from `/privacy`, and give reviewers a demo account.

## 10. Repository and launch

- In GitHub, set the repository's About: description, website `https://vishstack01.github.io/careeros/`, topics `job-search`, `ai-agent`, `india`, `open-source`, `career`, `resume`.
- Turn on the hourly scan: `gh workflow enable scan.yml`. The worker ingests every 15 minutes; Ultra accounts are matched on every ingest.
- `website/index.html` has `<meta name="careeros-app" content="https://careeros-web.onrender.com">`. Change it if the app lives on your domain.
- Start with `SIGNUP_MODE=allowlist` for a private beta, then open sign-ups.

To give someone a plan without payment, sign in as the operator and run in the browser console:

```js
fetch("/api/admin/grant", {method: "POST", headers: {"Content-Type": "application/json", "X-CareerOS-CSRF": "1"},
  body: JSON.stringify({email: "friend@example.com", plan: "ultra", until: "2026-12-31"})}).then(r => r.json())
```

## 11. Concierge

Concierge is a person on your team running a candidate's search, paid by a share of the fixed pay after they join. The software is ready; the service needs people and paperwork.

1. **Have a lawyer review the Concierge terms** at `/terms#concierge` (fee, instalments, the 90-day rule, the 6-month attribution window, and the clause on hidden offers) before the first case. Charging candidates a placement fee is legal in India, but the terms are your contract with them.
2. **GST:** placement services are usually taxable. Ask your accountant, then set `CONCIERGE_TAX_RATE` (for example 18) once you're registered.
3. **Partners:** create accounts for your talent partners, then as the operator run `fetch("/api/admin/staff", {method: "POST", headers: {"Content-Type": "application/json", "X-CareerOS-CSRF": "1"}, body: JSON.stringify({email: "partner@yourdomain"})})`. They work at `https://<your-app>/staff`. Unassigned Ultra requests show first.
4. **Turn it on** once steps 1 to 3 are done: set `CONCIERGE=on` on both services (the blueprint starts with it off). Requests email every partner.
5. **Collecting fees:** instalments use Razorpay payment links. In the Razorpay dashboard, add the `payment_link.paid` event to the same webhook. Keep each offer letter you verify.
6. **Other countries:** `CONCIERGE_COUNTRIES` widens it, but only after legal advice for each country. The UK prohibits charging work-seekers and is always refused; most EU countries restrict it; many US states license and cap fees.
7. **Train partners on the rules** shown at the bottom of the workspace: never sign in as the candidate, never automate LinkedIn, send nothing the candidate hasn't approved, write only what's true.

## 12. Guarantees

Two guarantees sit outside the plans. Pro and Ultra members apply for them (the app offers both in a one-time pop-up and on Home), and a person on the team reviews every application. Nobody is enrolled directly. The blueprint turns them on with `GUARANTEE=on` and `CONCIERGE=on`.

- **Interview Guarantee:** if accepted, the member pays ₹2,999 (or $34) once (`GUARANTEE_INTERVIEW_PRICE_INR`, `GUARANTEE_INTERVIEW_PRICE_USD_CENTS`) within 7 days, and gets 45 days (`GUARANTEE_DAYS`). Their part: 25 applications (`GUARANTEE_MIN_APPLICATIONS`) in at least 3 different weeks (`GUARANTEE_MIN_WEEKS`). No interview by day 45: the full ₹2,999 comes back. Plan fees are never refunded.
- **Job Guarantee:** this is Concierge. Nothing upfront; the member applies, the team accepts or declines with a reason, and the fee is 8% of yearly fixed pay (6% on the part above ₹20 lakh) only after they join (`CONCIERGE_RATE_LOW`, `CONCIERGE_RATE_HIGH`, `CONCIERGE_BAND`). Not placed, nothing to pay.

1. **Have the lawyer read `/terms#guarantees`** with the Concierge terms. India's consumer authority (CCPA) acts against "100% placement" and "guaranteed job" claims, so every page words these as money back or a fee after placement, with the conditions next to them. Keep it that way in ads and posts: "an interview in 45 days or your ₹2,999 back", never "guaranteed job".
2. **Reviewing applications.** Interview Guarantee applications email every partner and show in `/staff` under Interview Guarantee, with the roles they're aiming for, their note and how many roles Propelo matched them in the last 30 days (about 40 is a healthy sign). Accept only where an interview in 45 days is realistic; a decline needs a sentence they'll read. Job Guarantee applications are Concierge cases in `requested`: "Accept and take this case" or "Decline application" with a reason. Answer within 2 working days, as the app promises.
3. **Payments.** Rupees use Razorpay payment links (the same webhook, with the `payment_link.paid` event). For dollars, create a one-time product in Dodo priced at $34 and set `DODO_PRODUCT_GUARANTEE`; the existing Dodo webhook needs the `payment.succeeded` event. Test both in test mode: apply, accept in `/staff`, pay, and check the guarantee shows "In progress". An acceptance not paid within 7 days lapses.
4. **Budget for refunds.** A refund is at most the ₹2,999 paid. Watch the claim rate in the first two months and tune who you accept before tuning the rules (change `GUARANTEE_MIN_APPLICATIONS` or `GUARANTEE_MIN_WEEKS` only with notice).
5. **Deciding claims.** Claims show in `/staff` under Interview Guarantee. Before approving, look at the person's pipeline and inbox for an interview, invitation or offer in the window. Approve (the amount defaults to the price paid and can't exceed it), issue the refund in the Razorpay or Dodo dashboard to the original payment, then mark it refunded. Answer within 5 working days, as the terms promise.
6. **Goodwill or testing:** `POST /api/admin/guarantee {email, kind: "interview"}` starts one without payment for an eligible member.
7. **Track the promise.** `/api/admin/audit?kind=guarantee` lists applications, reviews, payments, claims and decisions.

## 13. Sources and extension

1. **Adzuna** (India, US, UK, Canada, Australia, New Zealand, Singapore, western Europe): register at developer.adzuna.com, then add `ADZUNA_APP_ID` and `ADZUNA_APP_KEY` as repository secrets (Settings, Secrets and variables, Actions). The scan reads them once a day. Read Adzuna's terms: listings link to Adzuna's own page, which is how the feed uses them.
2. **USAJOBS** (US federal roles): request a key at developer.usajobs.gov and add `USAJOBS_KEY` and `USAJOBS_EMAIL` (the email you registered with).
3. **Watch the feed size** after turning on the hourly scan: `feed/summary.json` shows `openings` and `trimmed`. Raise or lower `CAREEROS_FEED_MAX` in `scan.yml` to keep `full.jsonl.gz` well under 100 MB.
4. **Chrome Web Store:** zip the `extension` folder (the extension workflow builds it), pay the one-time developer fee, and describe the permissions as the extension's README does: no sites up front, the hiring sites only when the person switches on the panel, and never LinkedIn, Naukri, Indeed or Wellfound. Store review asks why each permission is needed; the README's table is the answer.
