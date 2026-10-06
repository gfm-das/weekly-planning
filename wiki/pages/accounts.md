---
title: Accounts
slug: accounts
lead: covers missionary accounts and staff accounts (President, Office, Data Analyst) managed in DA Management.
summary: Portal and staff accounts.
status: full
navboxes: [admin]
infobox_title: Accounts
icon: "👤"
infobox_rows: ["Where|DA Management", "Staff|President, Office, Data Analyst", "Auth store|Supabase Auth"]
tags: [admin, accounts]
---

## Usage

### Missionary accounts

- Open a person’s account page in DA Management to set languages, roles, status, area, and leadership assignments.
- Role, status, area, and leadership saves are logged in **Import history** (with Undo rules). Language-only saves are not listed.

### Staff accounts

- **Staff accounts** pages manage President, Office, and Data Analyst sign-ins.
- First install path (manual today): sign into DA Management with the shared importer password from the server env file, create staff accounts, load the roster, then people use the portal.

:::needs-checking
Exact first-login UX after the planned installer creates the first Data Analyst account should be documented when the installer ships.
:::

## How it works

- Portal sign-in users live in Supabase Auth plus `user_profiles` (main `app_role`, `additional_roles`).
- Staff sign-ins are not linked as missionary emails.
- AP access to DA Management requires a **current** AP leadership assignment when AP is the main role path.

## Permissions

AP, President, and Data Analyst may manage accounts (same rules as Staff accounts).

## Troubleshooting

| Problem | What to try |
| --- | --- |
| Cannot link email to missionary | Email already belongs to a staff account — use another email |
| AP cannot open DA Management | Check current AP assignment and app_role |
| Shared importer password from internet | Public management hostname refuses the old shared password (portal sign-in only) |

## History

| Date | Note |
| --- | --- |
| Round 2 / 027 | Staff accounts |
| Round 10 | Public management hardening |

## See also

- [Roles and permissions](roles-and-permissions.html)
- [Signing in](signing-in.html)
- [Roster](roster.html)
