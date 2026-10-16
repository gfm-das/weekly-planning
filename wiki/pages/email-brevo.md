---
title: Email (Brevo)
slug: email-brevo
lead: explains how the system sends invitation and password emails through Brevo, and how to fix it when they stop arriving.
summary: How email works, and a step-by-step fix when Brevo needs to be reconnected.
status: full
navboxes: [admin]
infobox_title: Email (Brevo)
icon: "✉️"
infobox_rows: ["Service|Brevo (app.brevo.com)", "Used for|Invitations and password emails", "Settings|supabase/.env (SMTP_*)", "Test|DA Management > People > Staff accounts"]
tags: [admin, email, ops]
---

## Usage

The system sends two kinds of email: **invitations** and **password emails**. They come from Account Manager and from Staff accounts in DA Management. Brevo is the service that delivers them.

Brevo is **not** logged in anywhere inside the portal. The only connection is a set of mail settings (called SMTP settings) in the file `supabase/.env` on the server. The card **Links to web services > Brevo** is just a shortcut to Brevo's page for email keys. It stores no password.

**Signs that Brevo needs to be reconnected:** a person says no invitation or password email arrived, and the check below shows an error.

## How to fix it (in this order)

1. **Look for warnings in Brevo.** Sign in at app.brevo.com. A red banner can mean a suspended account, no email credits left, or a sender that is not verified.
2. **Allow the server (Authorised IPs).** In Brevo open **Security > Authorised IPs**. If blocking is on, the server's public address must be in the list, or blocking must be turned off. After the move to the Ubuntu server the address is new, so this is a likely cause. To find the address, type this on the server: `curl -s https://ifconfig.me`
3. **Check the SMTP details.** In Brevo open **SMTP & API > SMTP** (the card in Links opens the SMTP keys page directly). Note the server name `smtp-relay.brevo.com`, the port `587` and the login shown there.
4. **Make a new SMTP key.** On the same page create a **new SMTP key**. It must be an SMTP key, not an API key. Copy it once; Brevo shows it only one time. Never paste it into chat or into a document.
5. **Check the sender.** In Brevo open **Senders, Domains & Dedicated IPs** and make sure the address the system sends from (`SMTP_ADMIN_EMAIL`) is verified.
6. **Put the new details on the server (only after the owner says go).** On the server edit `~/weekly-planning/supabase/.env` and set `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASS`, `SMTP_ADMIN_EMAIL` and `SMTP_SENDER_NAME`. Then make the sign-in service pick them up:

```bash
cd ~/weekly-planning
docker compose -p gfm-beta --env-file supabase/.env -f supabase/supabase-compose.yml -f supabase/beta-override.yml up -d --no-deps --force-recreate supabase-auth
```

A plain `docker restart` is **not** enough: it keeps the old settings.

## Testing

1. In DA Management open **People > Staff accounts** and send a password email to yourself.
2. On the server look at the log:

```bash
docker logs --since 10m gfm-beta-supabase-auth-1 2>&1 | grep -iE 'mail|smtp' | tail
```

| What the log says | Meaning |
| --- | --- |
| `535 Authentication failed` | The key or login is wrong or was deleted: make a new SMTP key (step 4). |
| Connection refused or timed out | The server's address is blocked: step 2. |
| Sender not valid or not verified | Step 5. |
| Quota or account suspended | Look at the banner in Brevo (step 1). |

## Troubleshooting

- The email is "sent" but nothing arrives: check the spam folder, then Brevo's **Transactional > Logs** for the address.
- Never put the SMTP key into the repository, a wiki page or a chat.

## History

| Date | Note |
| --- | --- |
| Round 16 | Page added after emails needed a reconnect following the move to the Ubuntu server |

## See also

- [Troubleshooting](troubleshooting.html)
- [Management](management.html)
- [Accounts](accounts.html)
