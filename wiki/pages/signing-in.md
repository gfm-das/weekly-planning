---
title: Signing in
slug: signing-in
lead: is how missionaries and leaders open the Weekly Planning 3.0 portal in a browser.
summary: How to sign in to the portal.
status: full
navboxes: [using]
infobox_title: Signing in
icon: "🔑"
infobox_rows: ["Who|Everyone with an account", "Where|Portal home", "Auth|Supabase Auth", "Office URL|localhost:8070 or office LAN"]
tags: [users, auth]
---

## Usage

1. Open the portal in a browser (phone or computer).
2. Enter the email and password for your account (created by a Data Analyst or the President in DA Management).
3. After sign-in, the menu on the left shows the pages your [role](roles-and-permissions.html) allows.
4. Use **Sign Out** when you finish on a shared computer.

### Where to open it

| Place | Address (typical) |
| --- | --- |
| On the office server itself | `http://localhost:8070` |
| Another device on the office network | Office LAN IP on port 8070 (example historically used: `192.168.1.20`) |
| Public name (if set up) | Mission public hostname via Cloudflare tunnel |

:::needs-checking
Confirm the current public hostname list with the live Cloudflare tunnel routes before publishing externally. Generic pattern: portal on 8070, dashboards on 8088, presentations on 3030, decks on 8089, management on 8090.
:::

## How it works

- The portal uses **Supabase Auth**. Your browser keeps a session token; pages call portal-api with that token.
- The shell loads your role and builds the menu. Until roles are known, only Weekly Planning is offered.
- Presentations and Dashboards get an extra short-lived session from the portal shell — you do not sign in twice for those tabs.

## Permissions

Anyone with an active portal account may sign in. What you see after that depends on [Roles and permissions](roles-and-permissions.html).

## Troubleshooting

| Problem | What to try |
| --- | --- |
| Sign-in fails | Check email spelling; ask a Data Analyst to confirm the account is active |
| Menu looks empty / wrong | Refresh; if it persists, ask an analyst to check roles on the account |
| Push reminders never arrive | Reminders need **https** or **localhost**; plain office http on a LAN IP cannot receive them |
| Session expired messages | Sign in again; Presentations may need a minute after a Slidev restart |

## History

| Date | Note |
| --- | --- |
| Round 6+ | Portal is the single sign-in; Appsmith separate login retired |
| Round 10 | Public hostnames and Secure cookies for some services (documented in handoff) |

## See also

- [Overview](overview.html)
- [Roles and permissions](roles-and-permissions.html)
- [Accounts](accounts.html)
