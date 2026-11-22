# 07 · Security and privacy audit

Scope: application code, local running copy, CI and git history. Production configuration could not be inspected
(Not verified). No production change, payment setting or security configuration was changed outside the code in
this repository.

## Verified controls (executed, see `qa-tests.csv`)
| control | how it is enforced | evidence |
| --- | --- | --- |
| Authorization on every endpoint | FastAPI dependencies; generated routes list shows the guard per route | QA-005, QA-007 |
| No cross-account reads (IDOR) | every query filtered by the session user | QA-005 |
| CSRF | custom header + Origin check on every write | QA-006 |
| Passwords | PBKDF2-SHA256, 600,000 iterations, per-user salt | code + tests |
| Sign-in throttling | per IP and per email, 429 | QA-008 |
| Two-step sign-in | TOTP (RFC 6238, ±30 s, no replay) + 10 hashed recovery codes; secret encrypted with SECRETS_KEY; required for staff/admin in production | QA-013..QA-015 |
| Sessions | HttpOnly, SameSite=Lax, Secure in production; password reset ends other sessions; suspension ends all sessions and keys | QA-011, QA-017 |
| Headers | CSP with nonce (no inline script without it), XFO DENY, nosniff, COOP, Referrer-Policy, Permissions-Policy; HSTS in production | QA-010 |
| Uploads | PDF/DOCX only by content, size caps, served owner-only from `/_blob/` | QA-009 |
| Open redirects | `next` limited to same-site paths | QA-012 |
| Webhooks | Razorpay and Dodo signatures checked; replays idempotent | QA-028 |
| Secrets in git | gitleaks over all history: 0 leaks; CI runs it on every push | QA-004 |
| Audit log | security and money events, admin-readable | QA-016 |

## Risks and gaps
| id | risk | priority |
| --- | --- | --- |
| R-001 | Database backups not confirmed (render.yaml sets no plan) | P0 |
| R-006 | Admin account without two-step would be locked out of staff tools in production; turn it on first | P0 |
| R-007 | Losing SECRETS_KEY loses stored AI keys and two-step secrets | P0 |
| R-034 | Live headers, TLS and cookies on app.propelo.org not seen | P1 |
| R-033 | Some token-check limits reset on failure (tokens are 256-bit; impractical to brute force) | P3 |
| R-035 | No error monitoring until SENTRY_DSN is set | P2 |
| R-024 | Google Fonts sends visitor IPs to Google | P2 |

## Privacy and compliance
- **Data collected:** name, email, resume and what the member types; no passwords for other sites, OTPs,
  Aadhaar, PAN, bank details, passport numbers or date of birth (product rule, enforced in the agent prompts).
- **Member rights:** export (JSON) and delete (password + typing DELETE) in Settings. Business students see what is
  shared before consenting and can leave.
- **DPDP Act 2023 (India):** needs a named grievance contact in the privacy policy (R-039).
- **GDPR (EU members):** lawful basis is contract; fonts (R-024) are the one third-party request on page load.
- **Payments:** card data never touches the app (Razorpay/Dodo hosted pages), so PCI scope is SAQ-A.
- **Legal review** of terms, refunds and both guarantees is required before charging for guarantees (R-040).

## Not tested
Penetration test by a third party; production infrastructure; email provider configuration (SPF/DKIM/DMARC);
denial-of-service limits at the proxy.
