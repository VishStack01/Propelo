# Propelo go-live checklist

Updated 25 November 2026. Pull request 16 is merged and live. Pull request 17 (branch `design/fix-and-peeps`, 690 tests passing) adds the people on the website and app, drops the India plans and the Job Guarantee, and adds the 90-day passes. What is left needs your accounts, so only you can do it. Do it in this order: merging before step 4 would show the new prices before checkout can charge them.

Every value below goes into Render, on the `propelo` service, under **Environment**. Never paste a key or password into a chat, an email or the repository.

## What is already working

- The app runs on Render's free plan, with the database on Neon.
- Sign-up creates the account. The confirmation email is held up only by step 1.

## 1. Finish email sending (Resend)

1. In Resend, open **Domains → propelo.org** and find each row still marked Pending. Last time it was `resend._domainkey`.
2. At your DNS provider, check that row: type `TXT`, name exactly `resend._domainkey` (no `.propelo.org` on the end), and the whole value pasted with Resend's copy button.
3. Press **Verify** in Resend and wait for **Verified**.
4. Check that `SMTP_URL` is `smtps://resend:YOUR_KEY@smtp.resend.com:2465` and `MAIL_FROM` is `Propelo <hello@propelo.org>`.
5. On the "Check your inbox" page press **send it again**, confirm your email, and sign in as trypropelo@gmail.com. Turn on two-step sign-in in Settings, Account: it is required for the admin account.

## 2. Point app.propelo.org at the app

1. In Render, open **propelo → Settings → Custom Domains** and check `app.propelo.org` shows **Verified**.
2. Set `PUBLIC_URL` to `https://app.propelo.org` and save. Every email link and sign-in callback uses it.

## 3. Turn on the hosted AI

Set `PROPELO_LLM` to `anthropic` and `ANTHROPIC_API_KEY` to your key. Set a monthly spending limit in the Anthropic console. Pro and Ultra sell AI actions, so this must be on before you take payments.

## 4. Payments

### Dodo Payments (everyone outside India mode, in dollars)

1. **Settings → Business:** turn on **Adaptive Currency** so each buyer pays in their own currency.
2. Create these products and copy each product id (`pdt_...`):

| Product | Price | Type | Setting |
|---|---|---|---|
| Pro | $39 a month | Subscription | `DODO_PRODUCT_PRO` |
| Ultra | $79 a month | Subscription | `DODO_PRODUCT_ULTRA` |
| Pro, 90-day pass | $99 | One-time | `DODO_PRODUCT_PASS` |
| Ultra, 90-day pass | $189 | One-time | `DODO_PRODUCT_PASS_ULTRA` |
| Interview Guarantee | $59 | One-time | `DODO_PRODUCT_GUARANTEE` |
| Consultancy Starter Pack | $325 | One-time | `DODO_PRODUCT_CONSULTANCY_STARTER` |
| Consultancy Growth | $625 | One-time | `DODO_PRODUCT_CONSULTANCY_GROWTH` |
| Consultancy Plus Pack | $1,225 | One-time | `DODO_PRODUCT_CONSULTANCY_PLUS` |
| Agency roles feed | $99 | One-time | `DODO_PRODUCT_AGENCY_FEED` |

3. **Webhooks:** add `https://app.propelo.org/api/billing/dodo-webhook`, subscribe to the `subscription.*` and `payment.*` events, and copy its secret.
4. In Render set `DODO_API_KEY`, `DODO_WEBHOOK_SECRET`, the product ids above, and `DODO_MODE=test`. Switch to `live` after step 7.
5. If Render has `PRO_PRICE_USD_CENTS` or `ULTRA_PRICE_USD_CENTS` from before, delete them. The code's defaults are the new prices.

### Razorpay (optional, consultancies in India only)

Members pay only through Dodo, in dollars. Razorpay is only for a consultancy or agency in India that wants to pay its 30 days by a rupee link. Skip it until one asks.

1. Finish Razorpay activation (KYC).
2. **Settings → API Keys:** generate a key id and secret.
3. **Settings → Webhooks:** add `https://app.propelo.org/api/billing/webhook` with a secret you choose, and tick `payment_link.paid`.
4. In Render set `RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET` and `RAZORPAY_WEBHOOK_SECRET`. Delete `RAZORPAY_PLAN_PRO`, `RAZORPAY_PLAN_ULTRA`, `PRO_PRICE_INR` and `ULTRA_PRICE_INR` if they are set: they are no longer read.

## 5. Sign-in buttons

Each button appears on the sign-in page only once its keys are set. Use `https://app.propelo.org` as the home page in each.

| Button | Where | Redirect address to enter | Settings |
|---|---|---|---|
| Google | Google Cloud console → APIs & Services → Credentials → OAuth client (web). Consent screen: scopes `openid`, `email`, `profile` only. | `https://app.propelo.org/api/auth/google/callback` | `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` |
| GitHub | github.com → Settings → Developer settings → OAuth Apps → New | `https://app.propelo.org/api/auth/github/callback` | `GITHUB_CLIENT_ID`, `GITHUB_CLIENT_SECRET` |
| LinkedIn | linkedin.com/developers → Create app → Products: "Sign In with LinkedIn using OpenID Connect" | `https://app.propelo.org/api/auth/linkedin/callback` | `LINKEDIN_CLIENT_ID`, `LINKEDIN_CLIENT_SECRET` |
| Mobile number | twilio.com → Verify → Services → Create. Turn on Fraud Guard, and under Geo permissions allow only the countries you serve. | none | `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_VERIFY_SID` |

The same Google client also sends recruiter emails from a member's Gmail. That needs the `gmail.send` scope and Google's review, which takes weeks; sign-in works without it.

Mobile number sign-in is for members who add a number in Settings. New members create their account with email, Google, GitHub or LinkedIn first. Each text costs money through Twilio.

## 6. Merge pull request 17

1. Wait for its checks to pass on GitHub.
2. Merge it into `main`. The website updates through the `pages` workflow; Render redeploys the app.
3. If Render doesn't redeploy by itself: **Manual Deploy → Deploy latest commit**.

## 7. Check it is live

- `https://app.propelo.org/api/ready` answers `"ok": true`.
- `https://app.propelo.org/pricing` shows $0, $39 and $79, the 90-day passes ($99 and $189) under Pro and Ultra, and no rupee prices.
- The sign-in page shows the buttons you set up in step 5.
- A Pro checkout in test mode opens Dodo at $39 (or the local-currency equivalent), and each pass at $99 or $189.
- Buy Pro once with a real card, then refund it from the Dodo dashboard. Then set `DODO_MODE=live` with the live product ids.

If something is wrong, revert the merge on `main` and redeploy. Nothing in this release removes data or changes the database.

## 8. Before you take real payments

- Move the Render web service to a paid plan ($7 a month) so it doesn't sleep. A sleeping app makes the first visitor wait about 50 seconds.
- Neon's free plan allows 100 compute hours a month per project. An always-on app keeps the database awake longer; watch usage in the Neon console and move to its paid plan if it gets close.
- Have a lawyer read the guarantee terms (`/terms#guarantees`).

## Decisions made for you, which you can change

| Decision | Why | To change it |
|---|---|---|
| Members pay in dollars only (no India plans, no Job Guarantee) | Propelo focuses on the US, UK, Ireland and the Netherlands; Dodo charges each buyer in their own currency | A code change: the India plans were removed in 2.17 |
| 90-day passes: Pro $99, Ultra $189, paid once | A job search is a season; students on a visa clock prefer to pay once | `PASS_PRICE_USD_CENTS`, `PASS_ULTRA_PRICE_USD_CENTS`, `PASS_DAYS`, or `PASS=off` |
| Your own AI key only on Pro and Ultra | Free stays cheap to run; self-hosting with your own key stays free | `plans.own_key_allowed` in `propelo/cloud/plans.py` |
| Consultancy packs in rupees cost the same as in dollars (Starter ₹28,599) | Every student seat carries the global allowance | `BUSINESS_PLANS` in `propelo/cloud/partners.py` |
| Mobile number sign-in only for numbers already added in Settings | Texting any number from a public form invites SMS fraud and cost | Ask for phone-first sign-up if you want it |
| Public demo is a graduate in London who needs sponsorship | The product is aimed at people looking for work abroad | `dashboard/demo-data.json` |

## Known gaps

- Roles outside the US and India are thin for some job titles. That is feed coverage, not a bug.
- The Job Guarantee is retired. Its code stays, off; turning it on again needs its terms back on `/terms`.
- The margin figures assume members use half their AI allowance. Replace the assumption with real usage after the first month.
