# Product architecture repository

The single source of truth for what Propelo is, what exists, what is missing and what must be verified before
and after launch. It is kept in the repository, next to the code it describes, so a change to one is reviewed
with the other.

**Version:** 1.0 · **Last updated:** 22 Nov 2026 · **Product version:** 2.8.0 (+ unreleased audit fixes on `main`)

## Contents

| # | document | what it answers |
| --- | --- | --- |
| 01 | [Product understanding](01-product.md) | What it does, for whom, how it earns, how it is run; what this audit could and could not inspect |
| 02 | [Master sitemap](02-sitemap.md) | Every page, view, modal and system, with route, user, auth and status |
| 03 | [User journeys](03-journeys.md) | The main journeys as flow diagrams, with failure and recovery paths |
| 04 | [Page specifications](04-pages.md) | Purpose, entry, actions, states, security and acceptance per page |
| 05 | [Roles and permissions](05-permissions.md) | Who can do what, and where it is enforced |
| 06 | [UX and design audit](06-ux-audit.md) | What works, what doesn't, specific fixes |
| 07 | [Security and privacy audit](07-security.md) | Verified controls, risks, untested areas, compliance |
| 08 | [Technical architecture audit](08-architecture.md) | Components, data, integrations, scaling and debt |
| 09 | [SEO and growth audit](09-seo-growth.md) | Discoverability and the conversion funnel |
| 10 | [QA report](10-qa.md) and [test log](qa-tests.csv) | Every test executed, with result and evidence |
| 11 | [Missing-items register](register.csv) | Every gap: priority, solution, acceptance, status |
| 12 | [Launch readiness](12-readiness.md) | Scorecard, blockers, risks |
| 13 | [Roadmap](13-roadmap.md) | Ordered work to launch and after |
| 14 | [Change history](14-history.md) | Versions of this repository and the decisions behind them |
| 15 | [Consistency report](15-consistency.md) | Where the docs and the product disagree |
| gen | [Routes](generated/routes.md), [database](generated/database.md), [site and workflows](generated/site-and-workflows.md) | Generated from the code; never edited by hand |

## How it stays true (continuous synchronisation)

1. `python scripts/product_docs.py` regenerates `generated/` from the code: every route the app serves (with
   who may call it), every database table and column, every site page and workflow.
2. `tests/test_product_docs.py` runs it with `--check` on every test run. The suite fails when:
   - a generated file is out of date (a route, table or workflow changed and the docs were not regenerated);
   - a page route the app serves is not in [02-sitemap.md](02-sitemap.md);
   - a page in `website/` is not in the sitemap.
3. The register (`register.csv`) is never trimmed: items move to `Verified` or `Won't do` with a note, they are
   not deleted. Closed items keep their ID.

## Feature change process (every new or changed feature)

| step | what happens | where it is recorded |
| --- | --- | --- |
| 1. Request | Purpose, user, expected outcome, how we will know it worked | Issue or PR description |
| 2. Impact | Pages, journeys, roles, endpoints, tables, integrations, security, analytics, SEO, mobile, a11y, tests, docs, deploy | PR description, using the checklist below |
| 3. Docs first | Sitemap, page spec, permissions, journeys updated in the same PR | `docs/product/*` |
| 4. Requirements | Frontend, backend, security and infra requirements written down | PR description |
| 5. Tests | New tests; existing tests that change | `tests/`, `qa-tests.csv` |
| 6. Regression | Which existing journeys could break; run them | `10-qa.md` |
| 7. Verify | Implementation matches the requirements (run, click, read) | PR review |
| 8. Close | Status, test results, register and history updated | `register.csv`, `14-history.md` |

**Impact checklist** (copy into the PR): sitemap · new pages/modals/states · journeys · roles/permissions ·
frontend components · backend services · tables/migrations · APIs and third parties · auth · security and privacy ·
loading/empty/error/success states · analytics · SEO · mobile · accessibility · QA cases · help/docs · deploy/env.

## Definition of done (a feature is not complete until)

- its purpose is written in the page spec and its sitemap entry is updated;
- its journeys are documented and its permissions are tested;
- its UI is checked at phone, tablet and desktop widths, in light and dark;
- its loading, empty, error and success states exist;
- its security requirements are addressed (authorization on the server, input limits, output escaping);
- its tests run and pass, and the regression journeys still pass;
- `python scripts/product_docs.py --check` passes;
- the register and history are updated.

## Rules for this repository

- Planned and implemented are never mixed: status values are **Implemented**, **Verified** (executed and seen to
  work), **Partial**, **Missing**, **Not verified** (exists but could not be tested here), **Won't do**.
- Nothing is marked Verified without an executed test or an observed result, recorded in `qa-tests.csv`.
- Production (Render, DNS, payments, email) could not be reached from the audit environment; anything that
  depends on it is **Not verified** until someone runs the check in `12-readiness.md`.
