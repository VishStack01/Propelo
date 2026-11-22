# 14 · Change history

| version | date | product version | change | why |
| --- | --- | --- | --- | --- |
| 1.3 | 22 Nov 2026 | 2.11.0 | R-020 and R-022 fixed; R-050 to R-052 added (job board sign-up link, Pro pass, sponsor check and visa-jobs pages) | 14-day growth plan |
| 1.2 | 22 Nov 2026 | 2.10.0 | Register R-045 to R-049 (feed intake memory, sponsor data per country, continuous scans, database size) | Scan expansion for students abroad |
| 1.1 | 22 Nov 2026 | 2.9.1 | Interview Guarantee now ₹4,999 for 3 interviews or a second round; simpler site menu | Founder's decision |
| 1.0 | 22 Nov 2026 | 2.9.0 | Repository created: 01-15, register (44 items), QA log (35 tests), generated routes/database/workflows, sync test | Launch audit requested by the founder |

## Decisions recorded
| date | decision | reason |
| --- | --- | --- |
| 22 Nov 2026 | Two-step sign-in required for staff and admin in production, optional for members | Staff and admin can see cases and change plans; members choose |
| 22 Nov 2026 | Copy says "several times a day", not "hourly" | Measured cadence is 5-9 h between landed feeds |
| 22 Nov 2026 | Scan stops at 60 minutes and keeps late boards' previous roles | A hung board had cancelled whole runs at the 150-minute job limit |
| 22 Nov 2026 | Register items are never deleted | Master-prompt rule: never silently remove an unresolved issue |
| 21 Nov 2026 | Site on propelo.org, app on app.propelo.org | Founder's choice |
| 17 Nov 2026 | Business plans prepaid for 30 days, nothing renews by itself | Simpler for consultancies; no surprise charges |

## How to add an entry
Bump the version (minor for new documents or sections, patch for corrections), add a row above, and note which
register items changed status.
