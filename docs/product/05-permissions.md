# 05 · Roles and permissions

Enforced on the server in `propelo/cloud/app.py` by dependencies (`session_only`, `principal`, `staff_only`,
`admin_only`); the generated [routes list](generated/routes.md) shows which one guards every endpoint. The UI only
hides what the server already refuses.

| role | how someone gets it | can | cannot |
| --- | --- | --- | --- |
| Visitor | none | read site, job board, pricing, business, legal; sign up | any `/api/me/*`, dashboard |
| Member (Free/Pro/Ultra) | sign up + confirm email; plan from billing, a grant or a business seat | own data only: profile, resume, roles, applications, outreach, guarantees, export, delete | other members' data (IDOR probes: 404), staff/admin APIs (403) |
| Computer key (agent/extension) | member creates a key in Settings | the agent and extension endpoints for that member | account settings, billing, other members |
| Business admin | creates or is added to a partner account | own business account: seats, invite link, branding, feed key, student progress counts | student resumes, answers, messages; other businesses |
| Student in a business | joins with consent | as Member (Pro while the seat is active); leave any time | |
| Agency feed key | business account with the feed | read its own filtered feed | anything else |
| Staff | admin grants in `/admin` | `/staff` cases, `/partner` all accounts, pilot approvals | admin console, grants, suspend |
| Admin | `BOOTSTRAP_ADMIN_EMAIL` at first start, or another admin | everything staff can, plus `/admin`: grant plans, staff access, two-step reset, suspend/restore, audit log | suspend themselves; turn off own two-step in production |

**Two-step sign-in:** optional for members; required for staff and admin in production (`needs_mfa`): without it,
staff/admin APIs return `403 mfa_required` and the pages send them to Settings to turn it on.

**Suspension:** sets `disabled`; deletes sessions and computer keys; sign-in refused. Restoring does not restore keys.

**Audit log:** sign-ins, failed sign-ins, password changes, two-step changes, grants, staff changes, suspensions,
guarantee and business actions. Readable by admins at `/admin`.

**Verified in this audit:** member A cannot read or change member B's resume, jobs, applications, documents (404);
members get 403 on staff/admin APIs; staff get 403 on admin APIs; staff/admin without two-step get 403 in
production mode; writes without the CSRF header get 403; suspended accounts cannot sign in.
