# The India feed: 1,400 career pages every hour

Most openings at Indian product companies never reach a job board, or reach it
days later with hundreds of applicants already in. They are first posted on the
company's own careers page, and most careers pages are a thin skin over a hiring
system (ATS) that publishes every opening as public JSON. Propelo reads those
feeds directly, for about 1,400 companies, every hour.

```mermaid
flowchart LR
  List["config/companies/<br/>companies.csv<br/>(1,396 companies)"] --> Discover["careeros discover<br/>find each company's board"]
  Discover --> Boards[("feed/boards.json")]
  Boards --> Scan["careeros scan<br/>8 hiring systems"]
  Remote["9 remote job boards<br/>(public JSON / RSS)"] --> Scan
  Scan --> Feed[("india.jsonl.gz<br/>feed-latest release")]
  Feed --> Filter["careeros filter-feed<br/>your settings, known roles"]
  Filter --> Dash["dashboard"]
  Platforms["config/platforms.toml<br/>(96 platforms)"] --> Agent["agent run<br/>login-free pages, x-ray searches"]
  Agent --> Dash
```

## 1. The company list

`config/companies/curated.txt` holds about 800 hand-picked Indian product
companies and India engineering centres, grouped by category: AI-native, dev
tools and infra, SaaS, fintech, consumer, mobility / industrial / climate /
space, global companies hiring engineers in India, remote-first global companies
and more. `scripts/build_company_list.py` merges it with
[moreThanFAANGM](https://github.com/Kaustubh-Natuskar/moreThanFAANGM) (483 product
companies and startups with their careers pages, MIT licensed; saved in
`config/companies/morethanfaangm.csv`) and the Y Combinator directory (active
Indian companies plus YC companies hiring remotely) into
`config/companies/companies.csv`: 1,396 companies after removing duplicates.

Each line is `Name | aliases | city | ats:token`. The ATS part is optional:
discovery finds it.

## 2. Discovery: which hiring system does each company use?

`careeros discover` tries each company's likely board names (its name, aliases
and website domain, slugified) on eight hiring systems, most common first:
Greenhouse, Lever, Ashby, Workable, SmartRecruiters, Recruitee, Breezy and
Personio. A board counts only if it checks out:

- the board's own company name matches ours, when the feed reports one;
- for India-headquartered companies, at least one opening is in India or remote
  (a board full of US roles under the same name is usually a different company).

Results are cached in `feed/boards.json`. Companies whose careers page runs on a
system without a public feed (Darwinbox, Keka, Zoho Recruit, Freshteam, custom
pages) are listed in `feed/unmapped.csv`; the agent visits about ten of them per
run in rotation. Discovery re-checks unmapped companies every 14 days and boards
that errored on the next run, at most 400 companies per run, about 4 requests a
second per hiring system.

## 3. The scan

`careeros scan` reads every mapped board plus nine remote job boards with
public feeds (Remote OK, Remotive, Himalayas, Jobicy, Working Nomads, We Work
Remotely, Hacker News jobs, HN "Who is hiring?", Arbeitnow). It keeps tech
roles that are in India or remote and, for each, extracts the facts the gates
need from the **full** posting once: minimum years (highest figure wins,
nice-to-haves ignored), whether freshers are welcome, who can apply to a remote
role, pay in LPA, closed notices and applicant counts. Each fact keeps the
sentence it came from.

When a remote board re-lists a role that is also on the company's own board, the
company's posting wins. Boards that ask for gentle polling are respected:
Remotive is read every 6 hours, Jobicy at most hourly.

Output, published as assets of the `feed-latest` release by `.github/workflows/scan.yml` (download from `https://github.com/VishStack01/careeros/releases/download/feed-latest/<file>`):

| File | What |
|---|---|
| `feed/india.jsonl.gz` | one open role per line, with facts and a 1,500-character summary |
| `feed/summary.json` | counts by system and region, errors, boards that failed this scan |
| `feed/boards.json` | each company's hiring system and board name |
| `feed/unmapped.csv` | companies whose careers page has no public feed |
| `feed/careeros.pyz` | the whole tool in one file, for agents that can download files but not clone: `python3 careeros.pyz filter-feed ...` |
| `feed/scan.log`, `feed/discover.log` | the last run's logs |

The feed is a public list of openings. It holds nothing about you.

### Rotation, countries and visa lines

- **Back to back.** Each scan starts the next one when it finishes, so boards are re-read about once an hour whatever GitHub's
  schedule does. `CAREEROS_SCAN_MAX_BOARDS` caps the boards read per run: curated boards every run, deep-sweep boards every
  four hours, empty ones daily, most overdue first. Boards not read keep their roles from the last run.
- **`countries`** on each record lists ISO codes for where the role is, including places that never name the country
  ("Austin, TX", "Toronto, ON", "Eindhoven"). `summary.json` has `byCountry`.
- **`facts.visa`** holds what is known about sponsorship: the posting's own words (`status`, `quote`; `why: "citizens"` for
  citizens-only or cleared roles), for US roles `opt` and `eVerify`, for UK roles `ukRegister` and `ukSalary`, and for roles in
  the Netherlands `nlRegister` (the immigration service's public register of recognised sponsors, `careeros nl-sponsors`).
  Being on a register means the employer can sponsor, not that this role is sponsored.
- **Lists of employers that have sponsored** (`registers.yml`, weekly; `careeros registers`): `us-sponsors.csv` from the US
  Department of Labor's LCA disclosure data (certified H-1B applications), `ca-sponsors.csv` from Canada's positive LMIA
  employers (Open Government Licence - Canada) and `ie-sponsors.csv` from Ireland's employment permits issued to companies.
  Roles in those countries get `facts.visa.usLca`, `caLmia` or `iePermits` when the employer matches. A missing name is never
  reported: unlike a licence register, these lists can't say an employer cannot sponsor.

## 4. Your filters

`careeros filter-feed` runs the same gates as everything else, using your
dashboard settings, and skips roles you already have (same URL, or same company
and title). It writes ready-to-store dashboard documents:

- `kept/`: roles that pass every gate, ordered remote worldwide → remote India →
  south India, newest first;
- `skipped/`: near-misses that fail exactly one gate (experience, posting age,
  location, pay or seniority), with what would change the decision;
- `index.json`: counts, plus `gone` (roles on your dashboard whose board was
  read successfully and no longer lists them, so they closed) and `expired`
  (roles posted before your window).

The scheduled agent run spot-checks roles whose remote eligibility or
experience the posting leaves unclear, writes the rest, then spends its own
budget on the platforms the feed can't read (see [platforms.md](platforms.md)).

## Running it yourself

Fork the repo and enable Actions: the `scan` workflow runs every hour on
GitHub's free runners and publishes your fork's `feed-latest` release. Or run it locally:

```bash
careeros discover            # first run: ~40 minutes for 1,396 companies
careeros scan                # a few minutes
careeros filter-feed --feed feed/india.jsonl.gz --settings config/settings.toml --out new
```

GitHub pauses scheduled workflows in repositories with no activity for 60 days;
re-enable it from the Actions tab if that happens.

## Adding companies

Add a line to `config/companies/curated.txt` and run
`python scripts/build_company_list.py`. If you know the board (for example
`ats:lever:acme`), add it; otherwise discovery finds it. Pull requests welcome.

## Sponsor sweep

The sponsor registers say who can sponsor; the sweep finds where those employers post their jobs.

- `careeros sponsor-candidates --feed feed --boards feed/boards.json --out feed/sponsor-companies.csv` writes one row per register employer that has no mapped board yet: a readable name, the country, and one or two likely board addresses ("Monzo Bank Limited" gives `monzobank` and `monzo`). Lists with counts (US, Ireland, Canada) are taken biggest first; the UK and Dutch lists put likelier names first. Takeaways, care homes, places of worship, farms and similar are left out.
- `careeros discover --extra feed/sponsor-companies.csv` tries `CAREEROS_SPONSOR_SWEEP` of them a run (500 by default, 0 turns it off), spread through the run.
- A board is kept only when it lists at least one role in that country **and** the board's own name leads back to the same register entry (exact name, or the only entry that starts with it). A board that gives no name is kept only under the employer's full name as the address, with two or more roles in the country.
- An employer with no board found is looked at again after 120 days. Only checked names are stored in `boards.json`.
- Boards found this way are read every four hours when they had roles last time, once a day when they had none.
- `summary.json` reports `sponsorSweep: {checked, kept}`.
