# 04 · Page specifications

One block per page. Every page shares: CSP with a per-request nonce, no third-party scripts, light and dark themes,
layouts checked at 390, 820 and 1280 px with no sideways scrolling (audit 22 Nov), keyboard reachable controls.
"Acceptance" is what a reviewer checks before a change to that page ships.

### Landing · propelo.org/index.html
- **Purpose:** explain the product in one screen and prove it with live counts from the feed. **Users:** visitors.
- **Entry:** search, links, GitHub. **Actions:** Start free (→ app signup), For consultancies (→ /business), Browse jobs, pricing anchors.
- **Content:** live role count and scan time, how it works, guarantees with their exact terms, pricing, FAQ.
- **States:** feed missing → counts hidden, copy still reads. **SEO:** title, description, canonical, Open Graph, JSON-LD Organization/WebSite.
- **Acceptance:** numbers come from the feed (never typed in); no "hourly" or "guaranteed job" claims; CTA works signed out.

### Job board · jobs.html
- **Purpose:** browse and filter the open roles; a role page with quotes from the posting. **Users:** visitors.
- **Actions:** search, filters (country, remote, sponsorship, seniority), open a role, apply on the employer's site.
- **States:** loading, no results, feed error. **Gaps:** one HTML page with hash routes, so roles are not indexable individually (R-021).
- **Acceptance:** filter results match the feed; outbound link goes to the employer's own posting.

### Sign in · /login
- **Purpose:** sign in. **Actions:** email+password, LinkedIn, forgot password, create account.
- **States:** wrong details (generic message), unconfirmed email (resend), throttled (429 after about 10 tries), two-step code step.
- **Security:** CSRF header + Origin check, throttle by IP and email, safe `next` (same-site path only).
- **Acceptance:** `next` cannot redirect off-site; the code step accepts TOTP or a recovery code once.

### Create account · /signup
- **Purpose:** create an account. **Fields:** name, email, password (8+), terms consent.
- **States:** closed or invite-only, email taken (neutral), sent. **Acceptance:** confirm link returns to `next` (join or business page).

### Confirm, forgot, reset · /verify, /forgot, /reset
- Token in the URL fragment (never sent to logs). Expired/used token → clear message and resend. Reset signs out all other sessions.

### Pricing · /pricing
- **Purpose:** plans and limits, INR and USD. **Actions:** choose plan → checkout or signup. **SEO:** H1 "Pricing", canonical.
- **Acceptance:** prices match `plans.py` and the env values (₹499 / ₹1,199; $22.50 / $48.50).

### For business · /business
- **Purpose:** sell the consultancy portal and agency feed; free pilot request. **Prices:** $325 / $625 / $1,225; feed $99.
- **Acceptance:** says what consultancies see (counts) and never see (resumes, answers, messages); nothing auto-renews.

### Dashboard · /app
- **Purpose:** the member's workspace (tabs in 02 §4). **Auth:** session; signed-out visit redirects to `/login?next=/app`.
- **States per tab:** loading skeleton, empty with the next step, error with retry, success toast.
- **Security:** all reads scoped to the session's user (IDOR probes passed), CSRF on writes, uploads PDF/DOCX only with size caps.
- **Acceptance:** each tab renders with an empty account and with seeded data; no console errors (one known: 404s for empty docs, R-030).

### Business account · /partner
- **Purpose:** partner admins manage seats, invite link, branding, feed key; staff see all accounts and approve pilots.
- **Auth:** session; staff section only for staff/admin, two-step required in production.

### Student join · /join/{code}
- **Purpose:** explain exactly what is shared, then join. **States:** bad code (404 page), seats full, already a member.

### Staff desk · /staff
- **Purpose:** Interview Guarantee applications and claims (and Job Guarantee cases where a server still runs it). **Auth:** staff/admin + two-step in production. Every action audited.

### Admin console · /admin
- **Purpose:** overview, account lookup, grant plan, make staff, reset two-step, suspend/restore, background jobs, audit log.
- **Auth:** admin + two-step in production. **Safety:** confirm dialogs; cannot suspend yourself; suspend ends sessions and API keys.

### Legal · /privacy, /terms, /refunds, /contact, /optout
- Distinct titles, descriptions and canonicals. Content needs review by a lawyer before taking payments at scale (R-040, R-041).

### 404
- App: any unknown page path returns the branded 404 (API paths keep JSON errors). Site: generated 404.html.
