"""Staff accounts: sign-ins for the mission president, office staff and Data Analysts who are not missionaries.

They serve in no area, so they are not in the roster, and Account Manager (which lists missionaries) cannot invite
them. Here they get a sign-in with a home mission (user_profiles.home_mission_id, migration 027), a name and one main
role: President, Office or Data Analyst.

Pages:
  /staff                 the list, and "Add a staff account" (sends an invitation)
  /staff/<id>            one staff account: name, email, role, Account active
  /staff/<id>/update     its save
  /staff/<id>/send       a new password email (for example after an invitation expired)

Who may do what (roles.py): an AP, the President or a Data Analyst may give or take away every role, also on their
own account (APs have full rights, owner 28 Sep); a change that ends your own DA Management access needs the
"I understand" tick. Every saved change is an ACCOUNT batch in Import history, so it can be undone like a transfer
(the sign-in itself and any email already sent stay).
"""
import hashlib
import json
import re
from datetime import date

from flask import Blueprint, request, session

import batches
import database
import page
import roles
import sign_in
import supabase_auth
from page import h

pages = Blueprint("staff_accounts", __name__)

STAFF_ROLES = {"PRESIDENT": "President", "DATA_ADMIN": "Data Analyst", "OFFICE": "Office"}
# One line each, in the wording of the Preach My Gospel guide (round 3), with what the role opens.
ROLE_HELP = {
    "PRESIDENT": "Mission president. Sees and helps manage everything in the mission: Dashboards, Presentations, "
                 "Call-ins, the calendar and DA Management.",
    "DATA_ADMIN": "Keeps the mission's data and the portal working: accounts, imports, planning questions and reports. "
                  "Sees the whole mission, like the President.",
    "OFFICE": "Edits the mission calendar and records meeting attendance. No Dashboards, Call-ins or DA Management.",
}
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
NOT_ALLOWED = "Only an AP, the President or a Data Analyst can give the President role, or change the President's account."
NOT_ALLOWED_REUSE = ("This email already has a sign-in with the President role. Only an AP, the President or a Data Analyst can make "
                     "it a staff account.")
OWN_ACCESS = "Saving this ends your own DA Management access. Tick \"I understand\" to go ahead, or ask {who} to make the change."
NOT_IN_MISSION = "This staff account is not in your mission."


# ------------------------------------------------------------------------------------------ reading

def staff_rows(cur, profile_id=None):
    """The staff accounts of the signed-in manager's mission (or only the one with this id, locked for a save)."""
    cur.execute("""select up.id,up.app_role,up.active,up.display_name,up.home_mission_id,up.updated_at,
        coalesce(up.additional_roles,'{}') additional_roles,au.email,au.invited_at,au.last_sign_in_at
      from public.user_profiles up left join auth.users au on au.id=up.id
      where up.missionary_id is null and up.home_mission_id=%s and (%s::uuid is null or up.id=%s::uuid)
      order by lower(up.display_name),up.id""" + (" for update of up" if profile_id else ""),
                (sign_in.current_mission_id(), profile_id, profile_id))
    return cur.fetchall()


def sign_in_for(cur, email):
    """The sign-in (Auth user) with this email and its profile, if any."""
    cur.execute("""select au.id,au.email,up.id profile_id,up.missionary_id,up.home_mission_id,up.app_role,up.active,
        coalesce(up.additional_roles,'{}') additional_roles
      from auth.users au left join public.user_profiles up on up.id=au.id where lower(au.email)=lower(%s)""", (email,))
    return cur.fetchone()


def profile_row(cur, profile_id):
    """The whole user_profiles row as it is now (for Import history), or None."""
    cur.execute("select to_jsonb(t) row_data from public.user_profiles t where id=%s", (str(profile_id),))
    found = cur.fetchone()
    return found["row_data"] if found else None


def status(r):
    if not r["active"]:
        return "Turned off"
    return "Active" if r["last_sign_in_at"] else "Invited"


def role_label(r):
    """The main role, plus an additional role the sign-in still has (e.g. from before it became a staff account)."""
    extras = [STAFF_ROLES.get(x, x) for x in roles.additional_roles_of(r) if x != r["app_role"]]
    return STAFF_ROLES.get(r["app_role"], r["app_role"]) + "".join(f" + {x}" for x in extras)


def has_access(role, active, additional=()):
    """Does a staff account with this role give DA Management access?"""
    return bool(active) and (role in roles.HIGH_ROLES or "DATA_ADMIN" in (additional or []))


def state_of(r):
    """What the account page was built from: the save refuses a page opened before any of these changed."""
    data = [str(r["id"]), r["app_role"], r["active"], r["display_name"], r["home_mission_id"], (r["email"] or "").lower(),
            r["updated_at"].isoformat() if r["updated_at"] else "", sorted(roles.additional_roles_of(r))]
    return hashlib.sha256(json.dumps(data).encode("utf-8")).hexdigest()[:32]


def read_form():
    """(name, email, role) from the sent form, checked. Raises ValueError with what is wrong."""
    name = " ".join(request.form.get("display_name", "").split())
    email = request.form.get("email", "").strip()
    role = request.form.get("role", "")
    if not 1 <= len(name) <= 120:
        raise ValueError("Enter the person's name (at most 120 characters).")
    if not EMAIL.fullmatch(email) or len(email) > 254:
        raise ValueError("Enter a valid email address. The person signs in with it.")
    if role not in STAFF_ROLES:
        raise ValueError("Choose President, Office or Data Analyst.")
    return name, email, role


def write_history(conn, cur, profile_id, before, name, summary):
    """One ACCOUNT batch with the profile's row before and after, so Import history can show and undo it."""
    key = batches.key_string({"id": str(profile_id)})
    after = profile_row(cur, profile_id)
    label = re.sub(r"[/\\]", "-", name)
    batch = batches.create_batch(conn, "ACCOUNT", f"Staff account - {label}", date.today(), summary)
    batches.record_changes(conn, batch, ["user_profiles"], {"user_profiles": {key: before} if before else {}},
                           {"user_profiles": {key: after} if after else {}})
    return batch


# ------------------------------------------------------------------------------------------ pieces of the pages

def staff_page(body, code=200):
    """A Staff accounts page (the "staff" box gives its fields the size for a phone)."""
    return page.render(f"<div class='staff'>{body}</div>", code)


def failed(error, back="/staff"):
    return staff_page(f"<div class='error'><b>Nothing was saved.</b><br>{h(error)}</div><p><a href='{back}'>Back</a></p>", 400)


def role_options(selected):
    """The Main role list: only roles the signed-in manager may give (and the account's own role)."""
    return "".join(f'<option value="{r}" {"selected" if r == selected else ""}>{label}</option>'
                   for r, label in STAFF_ROLES.items() if roles.may_give(r) or r == selected)


def role_help():
    return "".join(f"<li><b>{STAFF_ROLES[r]}:</b> {ROLE_HELP[r]}</li>" for r in STAFF_ROLES)


# ------------------------------------------------------------------------------------------ the list, and adding one

@pages.route("/staff")
def staff_list():
    """The staff accounts of the mission, and the form to add one."""
    if not sign_in.allowed():
        return sign_in.go_to_login()
    with database.connect() as conn:
        with database.cursor(conn) as cur:
            rows = staff_rows(cur)
            cur.execute("select name from public.missions where id=%s", (sign_in.current_mission_id(),))
            mission = (cur.fetchone() or {}).get("name") or ""
    listed = "".join(f"""<tr><td>{h(r['display_name'])}</td><td>{h(r['email'])}</td><td>{h(role_label(r))}</td>
            <td class="status">{status(r)}<br><a href="/staff/{r['id']}">Manage</a></td></tr>""" for r in rows)
    return staff_page(f"""<div class="card"><h2>Staff accounts</h2><p class="muted">Sign-ins for the mission president, office staff and Data
          Analysts who do not serve in an area. Staff accounts do not have a weekly plan. Missionaries get their sign-in from
          Account Manager.</p><div class="scroll"><table><thead><tr><th>Name</th><th>Email</th><th>Role</th><th>Account</th></tr></thead>
          <tbody>{listed or '<tr><td colspan="4" class="muted">No staff accounts yet.</td></tr>'}</tbody></table></div></div>
          <div class="card"><h3>Add a staff account</h3><form action="/staff/new" method="post" id="staffForm">
          <div class="split"><label class="form-field">Name<input name="display_name" maxlength="120" autocomplete="off" required placeholder="President Muster"></label>
          <label class="form-field">Email<input name="email" type="email" maxlength="254" autocomplete="off" required></label>
          <label class="form-field">Main role<select name="role">{role_options('OFFICE')}</select></label>
          <label class="form-field">Mission<input value="{h(mission)}" disabled></label></div>
          <ul class="muted">{role_help()}</ul>
          <p class="muted">An invitation email goes to this address. If the address already has a sign-in without a missionary, that
          sign-in is used and gets a password email instead.{'' if roles.may_give('PRESIDENT') else ' Only an AP, the President or a Data Analyst can add a President.'}</p>
          <button>Send invitation</button></form></div>""")


@pages.route("/staff/new", methods=["POST"])
def staff_new():
    """Adds a staff account: an invitation (or a password email for an existing sign-in)."""
    if not sign_in.allowed():
        return sign_in.go_to_login()
    try:
        name, email, role = read_form()
        if not roles.may_give(role):
            raise PermissionError(NOT_ALLOWED)
        conn = database.connect()
        try:
            with database.cursor(conn) as cur:
                found = usable_sign_in(cur, email)
                auth_user_id = found["id"] if found else invite(cur, email, name)
                before = profile_row(cur, auth_user_id)
                make_staff_profile(cur, auth_user_id, before, role, name)
                write_history(conn, cur, auth_user_id, before, name, {"action": "added", "role": STAFF_ROLES[role]})
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        if found:  # an existing sign-in: send it a password email (after the commit, as in Account Manager)
            supabase_auth.send_password_email(email)
        return staff_page(f"""<div class="card"><h2 class="good">Staff account added</h2><p>{h(name)} ({STAFF_ROLES[role]}):
              {'a password email was sent to the existing sign-in' if found else 'an invitation was sent'} at {h(email)}.
              The change is in Import history, where it can be undone.</p><p><a href="/staff">Back to Staff accounts</a></p></div>""")
    except Exception as e:
        return failed(e)


def usable_sign_in(cur, email):
    """The existing sign-in with this email, if it may become a staff account (else ValueError or PermissionError),
    or None when there is none."""
    found = sign_in_for(cur, email)
    if found and found["missionary_id"]:
        raise ValueError("This email is the sign-in of a missionary in the roster. Use another email, or manage "
                         "that missionary in Account Manager.")
    if found and found["home_mission_id"]:
        raise ValueError("There is already a staff account with this email. Open it from the list below.")
    if found and found["profile_id"] and not roles.may_change(found):  # e.g. a turned-off President sign-in
        raise PermissionError(NOT_ALLOWED_REUSE)
    return found


def invite(cur, email, name):
    """A new sign-in and its invitation email. Returns the new sign-in's id. Invited first, so the profile can point
    to it."""
    auth_user_id = supabase_auth.invite(email, {"display_name": name})
    if not auth_user_id:
        found = sign_in_for(cur, email)
        auth_user_id = found["id"] if found else None
    if not auth_user_id:
        raise ValueError("The invitation was sent, but the new sign-in could not be found. Reload the list "
                         "and add the account again: the existing sign-in is then used.")
    return auth_user_id


def make_staff_profile(cur, auth_user_id, before, role, name):
    """The sign-in's profile becomes this staff account (or a new profile is made)."""
    if before:  # a sign-in without a missionary and without a mission: make it this staff account
        # A staff account has one role: any earlier additional role goes (the history keeps it for Undo).
        cur.execute("""update public.user_profiles set app_role=%s,additional_roles='{}',display_name=%s,
          home_mission_id=%s,active=true,updated_at=now() where id=%s""", (role, name, sign_in.current_mission_id(), auth_user_id))
    else:
        cur.execute("""insert into public.user_profiles(id,missionary_id,app_role,active,display_name,home_mission_id)
          values(%s,null,%s,true,%s,%s)""", (auth_user_id, role, name, sign_in.current_mission_id()))


# ------------------------------------------------------------------------------------------ one staff account

def account_html(r, error=""):
    """The page of one staff account."""
    own = sign_in.is_me(r["id"])
    locked = not roles.may_change(r)
    disabled = "disabled" if locked else ""
    note = f"<p class='warn'>{h(NOT_ALLOWED)}</p>" if locked else ""
    extras = [STAFF_ROLES.get(x, x) for x in roles.additional_roles_of(r) if x != r["app_role"]]
    if extras and not locked:  # e.g. a sign-in that had an additional role before it became a staff account
        note += (f"<p class='warn'>This account also has the additional role {h(', '.join(extras))}. A staff account has one "
                 "role: saving this page removes it.</p>")
    own_box = ("""<label class="check"><input type="checkbox" name="own_access" value="yes"><span><b>I understand</b>
          If this change ends my own DA Management access, I cannot give it back to myself.</span></label>""" if own and not locked else "")
    # Only an active account can get a password email, so a turned-off account shows no such card.
    send = ("" if not r["active"] else f"""<div class="card"><form action="/staff/{r['id']}/send" method="post"><p>Send a password email to
          {h(r['email'])}, for example after an invitation expired.</p><button class="secondary">Send password email</button></form></div>""")
    return staff_page(f"""{error}<div class="card"><h2>{h(r['display_name'])}</h2><p class="muted">{h(role_label(r))}
          · {status(r)}</p>{note}<form action="/staff/{r['id']}/update" method="post"><input type="hidden" name="state" value="{state_of(r)}">
          <div class="split"><label class="form-field">Name<input name="display_name" maxlength="120" value="{h(r['display_name'])}" required {disabled}></label>
          <label class="form-field">Email (sign-in)<input name="email" type="email" maxlength="254" value="{h(r['email'])}" required {disabled}></label>
          <label class="form-field">Main role<select name="role" {disabled}>{role_options(r['app_role'])}</select></label></div>
          <label class="check"><input type="checkbox" name="active" value="yes" {'checked' if r['active'] else ''} {disabled}><span><b>Account active</b>
          Untick to turn the account off: the person can no longer use the portal.</span></label>
          <ul class="muted">{role_help()}</ul>{own_box}{'' if locked else '<button>Save changes</button>'}</form></div>
          {send}<p><a href="/staff">Back to Staff accounts</a></p>""")


@pages.route("/staff/<uuid:profile_id>")
def staff_detail(profile_id):
    """One staff account."""
    if not sign_in.allowed():
        return sign_in.go_to_login()
    with database.connect() as conn:
        with database.cursor(conn) as cur:
            rows = staff_rows(cur, str(profile_id))
    if not rows:
        return staff_page(f"<div class='error'>{NOT_IN_MISSION}</div><p><a href='/staff'>Back</a></p>", 404)
    return account_html(rows[0])


@pages.route("/staff/<uuid:profile_id>/update", methods=["POST"])
def staff_update(profile_id):
    """Saves one staff account (name, email, role, Account active)."""
    if not sign_in.allowed():
        return sign_in.go_to_login()
    back = f"/staff/{profile_id}"
    try:
        name, email, role = read_form()
        active = request.form.get("active") == "yes"
        conn = database.connect()
        try:
            with database.cursor(conn) as cur:
                r, ends_own = checked_change(cur, profile_id, email, role, active)
                changed = save_change(conn, cur, profile_id, name, role, active)
                email_changed = email.lower() != (r["email"] or "").lower()
                if email_changed:  # last, so a refused change leaves the database untouched
                    supabase_auth.update_sign_in_email(str(profile_id), email)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        if ends_own:
            session.clear()
            return staff_page("<div class='card'><h2 class='good'>Saved</h2><p>Your own DA Management access has ended, so you are "
                              f"signed out of DA Management. Ask {roles.WHO_GIVES_ACCESS} if you need it again.</p></div>")
        return staff_page(saved_html(changed, email_changed, email, back))
    except PermissionError as e:
        return staff_page(f"<div class='error'>{h(e)}</div><p><a href='{back}'>Back</a></p>", 403)
    except Exception as e:
        return failed(e, back)


def checked_change(cur, profile_id, email, role, active):
    """The staff account (locked), after every check of the change. Returns (row, whether it ends your own access).
    Raises ValueError or PermissionError with the reason when the change may not be saved."""
    rows = staff_rows(cur, str(profile_id))
    if not rows:
        raise ValueError(NOT_IN_MISSION)
    r = rows[0]
    if request.form.get("state") != state_of(r):
        raise ValueError("This account changed since you opened the page. Reload the page and check again.")
    if not roles.may_change(r) or not roles.may_give(role):
        raise PermissionError(NOT_ALLOWED)
    # A save keeps only the main role: an additional role left from before goes (the page says so).
    ends_own = sign_in.is_me(profile_id) and has_access(r["app_role"], r["active"], r["additional_roles"]) and not has_access(role, active)
    if ends_own and request.form.get("own_access") != "yes":
        raise ValueError(OWN_ACCESS.format(who=roles.WHO_GIVES_ACCESS))
    if email.lower() != (r["email"] or "").lower():
        other = sign_in_for(cur, email)
        if other and str(other["id"]) != str(profile_id):
            raise ValueError("Another sign-in already uses this email. Choose a different email.")
    return r, ends_own


def save_change(conn, cur, profile_id, name, role, active):
    """Saves name, role and Account active (only when something differs), with its Import history. Returns whether
    anything changed."""
    before = profile_row(cur, profile_id)
    cur.execute("""update public.user_profiles set app_role=%s,display_name=%s,active=%s,additional_roles='{}',
      updated_at=now() where id=%s and (app_role,display_name,active,additional_roles) is distinct from (%s,%s,%s,'{}')""",
                (role, name, active, str(profile_id), role, name, active))
    if cur.rowcount > 0:
        write_history(conn, cur, profile_id, before, name, {"action": "changed" if active else "turned off",
                                                            "role": STAFF_ROLES[role]})
        return True
    return False


def saved_html(changed, email_changed, email, back):
    """What the save did."""
    notes = []
    if changed:
        notes.append("Saved. The change is in Import history, where it can be undone.")
    if email_changed:
        notes.append(f"The sign-in email is now {email}; the password stays the same. Undo in Import history does not "
                     "change the email back.")
    return (f"<div class='card'><h2 class='good'>{'Saved' if notes else 'Nothing to save'}</h2><p>{h(' '.join(notes) or 'No changes.')}</p>"
            f"<p><a href='{back}'>Back to the account</a> · <a href='/staff'>Staff accounts</a></p></div>")


@pages.route("/staff/<uuid:profile_id>/send", methods=["POST"])
def staff_send(profile_id):
    """Sends a new password email."""
    if not sign_in.allowed():
        return sign_in.go_to_login()
    back = f"/staff/{profile_id}"
    try:
        with database.connect() as conn:
            with database.cursor(conn) as cur:
                rows = staff_rows(cur, str(profile_id))
        if not rows:
            raise ValueError(NOT_IN_MISSION)
        if not rows[0]["active"]:
            raise ValueError("This account is turned off. Turn it on first.")
        supabase_auth.send_password_email(rows[0]["email"])
        return staff_page(f"<div class='card'><h2 class='good'>Password email sent</h2><p>Sent to {h(rows[0]['email'])}.</p>"
                          f"<p><a href='{back}'>Back to the account</a></p></div>")
    except Exception as e:
        return failed(e, back)
