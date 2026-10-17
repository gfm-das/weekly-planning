---
title: Email (Gmail)
slug: email
lead: explains, step by step, how the system sends its sign-in emails through the mission's Gmail account, how to make or replace the Gmail app password, and what to do when emails stop arriving.
summary: Sign-in emails through Gmail: the app password, the settings, applying them, testing and fixing.
status: full
navboxes: [admin]
infobox_title: Email (Gmail)
icon: "✉️"
infobox_rows: ["Service|The mission's Gmail account", "Server|smtp.gmail.com, port 587", "Password|A Google App Password (16 letters)", "Settings|supabase/.env on the server (SMTP_*)", "Limit|About 500 emails a day", "Test|DA Management > People > Staff accounts"]
tags: [admin, email, ops]
---

## What it is for

The system sends two kinds of email, both from the mission's **Gmail account**:

- **Invitations**: a new missionary or staff member gets a link to choose a password (Account Manager, Staff accounts).
- **Password emails**: a link to choose a new password (Account Manager, Staff accounts > Manage > **Send password email**).

The sign-in service (called `supabase-auth`) sends them. It does **not** log in to Gmail in a browser. It only uses a few mail settings (SMTP settings) in the file `~/weekly-planning/supabase/.env` on the server. The password in that file is a special **Google App Password**, not the normal Gmail password.

Good to know:

- Gmail sends about **500 emails a day**. That is plenty for normal weeks; on a day with many invitations, send them in groups.
- The emails always come **from that Gmail address** (Gmail does not allow another sender address). The name people see is `Germany Frankfurt Mission`.
- **DA Management > History > Links to web services > Gmail** opens Google's App passwords page. It stores no password.

## Before you start

You need:

1. The sign-in (address and password) of the mission's Gmail account, from the previous data analyst or the mission office.
2. A way to type commands on the server (the terminal of the Ubuntu server, or SSH).
3. The owner's "go" before you change anything on the server.

Never paste the app password into a chat, a wiki page, an email or the repository. It belongs only in the `.env` file on the server.

## Make or replace the app password

Do this when you set up email for the first time, when Google shows *Username and Password not accepted*, or when the password may have been seen by someone else.

1. Sign in to the mission's Gmail account at https://myaccount.google.com.
2. Open **Security**. Make sure **2-Step Verification** is **on**. If it is off, turn it on first (Google asks for a phone). Without it, Google does not offer app passwords.
3. Open https://myaccount.google.com/apppasswords (or the **Gmail** card in DA Management > History > Links to web services).
4. Type a name you will recognise, for example `Mission system server`, and press **Create**.
5. Google shows a password of **16 letters** in four groups (for example `abcd efgh ijkl mnop`). It is shown **only once**. Keep the window open until step 6 of the next section is done.
6. Replacing an old one? In the same list, press the bin icon next to the old app password to delete it. From then on only the new one works.

## Where the settings live

On the server, in the file `~/weekly-planning/supabase/.env`:

| Setting | Value for Gmail |
| --- | --- |
| `SMTP_HOST` | `smtp.gmail.com` |
| `SMTP_PORT` | `587` |
| `SMTP_USER` | the mission's full Gmail address |
| `SMTP_PASS` | the 16-letter app password, **without spaces** |
| `SMTP_ADMIN_EMAIL` | the same Gmail address (the emails come from it) |
| `SMTP_SENDER_NAME` | `Germany Frankfurt Mission` |

The file `supabase/supabase-compose.yml` hands these to the sign-in service (as `GOTRUE_SMTP_*`). You do not change that file.

## Put the new settings in

1. On the server, open the file:

```bash
nano ~/weekly-planning/supabase/.env
```

2. Find the lines that start with `SMTP_` and set them as in the table above. Write the app password without spaces: `SMTP_PASS=abcdefghijklmnop`.
3. Save with **Ctrl+O**, then **Enter**, and close with **Ctrl+X**.
4. Make the sign-in service read the new settings:

```bash
cd ~/weekly-planning/supabase && docker compose -p gfm-beta -f supabase-compose.yml -f beta-override.yml --env-file .env up -d --no-deps --force-recreate supabase-auth
```

5. Wait about 20 seconds. `docker ps --filter name=supabase-auth` should show the container as `Up`.

A plain `docker restart` is **not** enough: it keeps the old settings. Only the command in step 4 reads the file again. It touches only the sign-in service.

## Test it

1. In DA Management open **People > Staff accounts**, press **Manage** next to your own account and press **Send password email**.
2. Within a minute the email should arrive in your inbox, from the mission's Gmail address with the name *Germany Frankfurt Mission*. Look in the spam folder too.
3. You do not have to use the link; an unused link simply expires.
4. If nothing arrives, look at the sign-in service's log on the server:

```bash
docker logs --since 10m gfm-beta-supabase-auth-1 2>&1 | grep -iE 'mail|smtp' | tail
```

The emails you sent also show in the Gmail account under **Sent**.

## Troubleshooting

| What you see | What it means | What to do |
| --- | --- | --- |
| `Username and Password not accepted` (code 535) in the log | The app password is wrong, has spaces, or was deleted | Make a new app password and put it in (the two sections above). Check `SMTP_USER` is the full address. |
| No error in the log, but no email | It went to spam, or the address is wrong | Look in the spam folder; check the person's email in Account Manager. Look in Gmail's **Sent** folder. |
| `Daily user sending limit exceeded` | More than about 500 emails today | Wait until tomorrow and send the rest then. |
| Connection refused or timed out | The server cannot reach smtp.gmail.com | Check the server's internet connection; check `SMTP_HOST` and `SMTP_PORT`. |
| Google sent a "security alert" email | Normal the first time the server signs in | Nothing; the alert only informs you. |
| The changes do nothing | The service still runs with the old settings | Run the command of "Put the new settings in", step 4 (not `docker restart`). |

If the Gmail account's normal password was changed, or 2-Step Verification was turned off, Google removes the app passwords: turn 2-Step Verification on again if needed and make a new app password.

## Switching to another email service later

Any email service that offers **SMTP** works the same way (for example a Google Workspace account, Microsoft 365, or a mail service for sending system emails).

1. Get the service's SMTP details: server name, port (usually `587`), user name and password or key. Many services call the password an *SMTP key* or *app password*.
2. If the service needs it, confirm the sender address there (some services only send from a confirmed address).
3. Put the details into the same six `SMTP_` settings, and set `SMTP_ADMIN_EMAIL` to an address the service may send from.
4. Apply and test them exactly as above.
5. Update the **Gmail** card in DA Management if you like: set `WEB_LINK_GMAIL` in `roster-importer/.env` to the new service's settings page (or `off`), and change this page.

## History

| Date | Note |
| --- | --- |
| Round 16 | Page added after emails needed a reconnect following the move to the Ubuntu server |
| Round 18 | Rewritten for Gmail (smtp.gmail.com with a Google App Password), which now sends the system's emails |

## See also

- [Troubleshooting](troubleshooting.html)
- [Management](management.html)
- [Accounts](accounts.html)
