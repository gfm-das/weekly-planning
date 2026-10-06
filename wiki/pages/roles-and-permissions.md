---
title: Roles and permissions
slug: roles-and-permissions
lead: explains who may use each part of the portal, and how stewardship limits what they see.
summary: Roles, stewardship, and capabilities.
status: full
navboxes: [using]
infobox_title: Roles
icon: "🛡️"
infobox_rows: ["Source of truth|portal-api/roles.py + database", "Managers|AP, President, Data Analyst", "Menu hiding|Convenience only"]
tags: [users, admin, security]
---

## Usage (plain language)

Every person has **one main role**. Some also have **additional roles** (Data Analyst and/or Office) set on the account in DA Management.

**Stewardship** (which zone, district, or area you see) always follows the **main** role. Hiding a button in the menu is not security — every API call and many database rules check again.

## Main roles

| Role | Typical stewardship | Notes |
| --- | --- | --- |
| Missionary | Own area | Weekly Planning for the companionship |
| DL | District | Call-ins; unlock plans in district; presentations only if shared |
| ZL | Zone | Call-ins; zone presentations |
| STL | Zone | Zone presentations; **no** Call-ins |
| AP | Mission (manager) | Full manager tools; DA Management when assignment is current |
| Office | (hand-set main role) | Calendar + mission-wide announcements when Office applies |
| President | Mission (manager) | Hand-set |
| Data Analyst | Mission (manager) | Hand-set; DA Management |

Leadership order when main role is taken from assignments: **AP > ZL > STL > DL**, else Missionary.

## Additional roles

| Additional role | Adds |
| --- | --- |
| Data Analyst (`DATA_ADMIN`) | Manager rights (Glimpse, Dashboards, etc.) without changing stewardship of the main role |
| Office | Calendar editing and mission-wide announcement publishing |

## Capability overview

| Capability | Who |
| --- | --- |
| Weekly Planning edit | Missionaries (own area); leaders/managers per scope |
| Call-ins | Managers, DL, ZL (not STL) |
| Unlock submitted plans | Managers, DL, ZL |
| Glimpse / Dashboards | Managers (AP, President, Data Analyst) |
| Presentations | Managers; ZL/STL; DL (shared only) |
| DA Management | President, Data Analyst, AP (with current AP assignment) |
| Calendar edit | Managers and Office |
| Archetypal Health | Managers |

## How it works

- `portal-api/roles.py` is the one place for yes/no capability questions.
- Database functions and row-level security enforce planning and call-in writes.
- The portal menu mirrors these rules in `portal-enhancements.js` for convenience.

## Troubleshooting

| Problem | What to try |
| --- | --- |
| “I should see Dashboards” | Need manager role or Data Analyst additional role |
| AP lost DA Management | Transfer may have ended AP assignment and reset app_role |
| STL cannot open Call-ins | By design |

## History

| Date | Note |
| --- | --- |
| Migration 021 / round 2 | Main + additional roles |
| Round 7 | APs full DA Management rights while assigned |

## See also

- [Signing in](signing-in.html)
- [Accounts](accounts.html)
- [Presentation Library](presentation-library.html)
