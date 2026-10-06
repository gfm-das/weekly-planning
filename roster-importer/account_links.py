"""Which sign-in belongs to a missionary, and what "Send account setup" (Account Manager) will do for them.

A sign-in is a Supabase Auth user (auth.users: an email and a password). A missionary's sign-in is the one linked
to them in public.user_profiles.missionary_id. Looking it up only by the roster email (as the Account Manager did
before) missed a sign-in whose roster email had changed: the invite then made a second, orphan sign-in. So the plan
below starts from the linked sign-in, and says before anything is sent what will happen:

  INVITE  no sign-in yet: a new one is made and an invitation is sent
  LINK    a free sign-in already has the roster email: it is linked to the missionary, then a password email is sent
  RESET   the linked sign-in has the roster email: a password email is sent
  EMAIL   the linked sign-in has an older email: it moves to the roster email, then a password email is sent there
  SKIP    nothing can be sent (no email, the account is turned off, the email belongs to someone else, ...)

Used by account_manager.py (the list and the send pages).
"""
import hashlib
import json
from datetime import date

import database
import roles

# What each action does, in the words the confirmation page shows.
ACTIONS = {
    "INVITE": "Invite: a new sign-in is created and an invitation is sent to {email}.",
    "LINK": "Link: the existing sign-in {email} is linked to this missionary, then a password email is sent.",
    "RESET": "Password email to {email}.",
    "EMAIL": "Move sign-in: the sign-in changes from {old_email} to {email} (the roster email), then a password email is sent there.",
    "SKIP": "Skip: {reason}",
}
SENDING = {"INVITE", "LINK", "RESET", "EMAIL"}


def plan_sign_ins(cur, people):
    """people: dicts with missionary_id, display_name, email. Returns one plan dict per person (same order), with
    action, auth_user_id, old_email and reason."""
    linked = linked_sign_ins(cur, [p["missionary_id"] for p in people])
    by_email = sign_ins_by_email(cur, [p["email"].lower() for p in people if p.get("email")])
    return [plan_one(p, linked.get(p["missionary_id"]), by_email) for p in people]


def linked_sign_ins(cur, missionary_ids):
    """{missionary id: their linked sign-in (id, active, email, roles)}."""
    # to_jsonb(up): additional_roles once migration 021 is applied (none before).
    cur.execute("""select up.missionary_id,up.id,up.active,au.email,up.app_role,to_jsonb(up)->'additional_roles' additional_roles
      from public.user_profiles up join auth.users au on au.id=up.id where up.missionary_id=any(%s)""", (missionary_ids,))
    return {r["missionary_id"]: r for r in cur.fetchall()}


def sign_ins_by_email(cur, emails):
    """{email in small letters: [every sign-in with that email, with its profile if it has one]}."""
    cur.execute("""select au.id,lower(au.email) email,up.missionary_id,up.id profile_id,
        (to_jsonb(up)->>'home_mission_id') home_mission_id,up.app_role,to_jsonb(up)->'additional_roles' additional_roles
      from auth.users au left join public.user_profiles up on up.id=au.id where lower(au.email)=any(%s)""", (emails,))
    by_email = {}
    for r in cur.fetchall():
        by_email.setdefault(r["email"], []).append(r)
    return by_email


def plan_one(p, own, by_email):
    """The plan for one missionary. own: their linked sign-in, or None."""
    plan = {"missionary_id": p["missionary_id"], "display_name": p["display_name"], "email": p.get("email") or "",
            "auth_user_id": None, "old_email": None, "reason": None}
    email = (p.get("email") or "").strip()
    other = next((s for s in by_email.get(email.lower(), []) if not own or str(s["id"]) != str(own["id"])), None)
    plan.update(choose_action(email, own, other))
    # Moving or linking a sign-in would let whoever controls the new address take it over: only someone who may change
    # that account on the Staff accounts pages may do it (today every AP, President and Data Analyst may).
    target = own if plan["action"] == "EMAIL" else other if plan["action"] == "LINK" and other["profile_id"] else None
    if target and not roles.may_change(target):
        plan.update(action="SKIP", reason=f"this sign-in has the President role, so only an AP, the President or a Data "
                                          f"Analyst can {'move it to a new email' if plan['action'] == 'EMAIL' else 'link it'}. "
                                          "Ask one of them to send the account setup.")
    return plan


def choose_action(email, own, other):
    """The action (and the sign-in it is for), from the roster email, the missionary's own linked sign-in and another
    sign-in that already has the roster email."""
    if not email:
        return {"action": "SKIP", "reason": "the roster has no email for this missionary."}
    if own and own["active"] is False:
        return {"action": "SKIP", "auth_user_id": own["id"], "reason": "this account is turned off. Turn it on in Manage settings first."}
    if own and (own["email"] or "").lower() == email.lower():
        return {"action": "RESET", "auth_user_id": own["id"]}
    if own and other:
        return {"action": "SKIP", "auth_user_id": own["id"], "old_email": own["email"],
                "reason": f"the roster email {email} already belongs to another sign-in, so this missionary's sign-in "
                          f"({own['email']}) cannot move there. Ask the data office to remove the other sign-in first."}
    if own:
        return {"action": "EMAIL", "auth_user_id": own["id"], "old_email": own["email"]}
    if other and other["missionary_id"] is not None:
        return {"action": "SKIP", "auth_user_id": other["id"],
                "reason": f"{email} is already the sign-in of another missionary. Check the roster emails."}
    if other and other["profile_id"] and other["home_mission_id"]:
        return {"action": "SKIP", "auth_user_id": other["id"],
                "reason": f"{email} is the sign-in of a staff account. Give the missionary another email."}
    if other:
        return {"action": "LINK", "auth_user_id": other["id"]}
    return {"action": "INVITE"}


def describe(plan):
    """The line "Check before sending" shows for one missionary."""
    return ACTIONS[plan["action"]].format(email=plan["email"], old_email=plan["old_email"] or "", reason=plan["reason"] or "")


def plan_token(plans):
    """A short fingerprint of the plans. It changes when anything the manager confirmed would be done differently,
    so the Send button only sends what was shown."""
    data = [[p["missionary_id"], p["action"], str(p["auth_user_id"] or ""), p["email"].lower(), (p["old_email"] or "").lower()]
            for p in plans]
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode("utf-8")).hexdigest()[:32]


def with_linked_sign_ins(rows):
    """Account Manager rows: use the sign-in linked to each missionary (not only one found by the roster email), and
    show "Email changed" when that sign-in still has an older address than the roster."""
    ids = [r["missionary_id"] for r in rows]
    if not ids:
        return rows
    with database.connect() as conn:
        with database.cursor(conn) as cur:
            cur.execute("""select up.missionary_id,up.id,up.active,au.email,au.invited_at,au.confirmed_at,au.last_sign_in_at
              from public.user_profiles up join auth.users au on au.id=up.id where up.missionary_id=any(%s)""", (ids,))
            linked = {r["missionary_id"]: r for r in cur.fetchall()}
    for r in rows:
        own = linked.get(r["missionary_id"])
        if own:
            use_linked_sign_in(r, own)
    return rows


def use_linked_sign_in(r, own):
    """Puts the linked sign-in's dates and state into an Account Manager row."""
    r.update(auth_user_id=own["id"], invited_at=own["invited_at"], confirmed_at=own["confirmed_at"],
             last_sign_in_at=own["last_sign_in_at"], linked_missionary_id=r["missionary_id"], profile_active=own["active"],
             sign_in_email=own["email"])
    if not r["email"]:
        r["account_status"] = "No email"  # as account_manager.account_status says: nothing can be sent without it
    elif own["active"] is False:
        r["account_status"] = "Disabled"
    elif (own["email"] or "").lower() != r["email"].lower():
        r["account_status"] = "Email changed"
    else:
        r["account_status"] = "Active" if own["last_sign_in_at"] else "Invited"


def upcoming(r):
    """Account Manager: the area column says when an assignment only starts later (a transfer dated ahead)."""
    start = r.get("assignment_start")
    if start and start > date.today():
        return f"<br><span class='muted'>from {start.strftime('%d %b %Y')}</span>"
    return ""
