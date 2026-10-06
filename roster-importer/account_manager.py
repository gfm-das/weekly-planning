"""Account Manager: the list of every missionary serving now, with the state of their sign-in, and "Send account setup".

Pages:
  /accounts        the list, with filters (zone, district, area, role, account status, search) and tick boxes
  /accounts/send   step 1: "Check before sending" shows what will happen for each ticked missionary;
                   step 2: after the manager confirms that same plan, the emails are sent

What "Send account setup" does for one missionary is decided in account_links.py (invite, link, move the sign-in to
the new roster email, password email, or skip). Emails go through Supabase Auth (supabase_auth.py). An import never
sends email by itself: only this page, after the manager confirmed the list.

Each missionary has their own settings page (account_page.py): role, area, languages.
"""
from flask import Blueprint, flash, redirect, request

import account_links
import database
import page
import roles
import sign_in
import supabase_auth
from page import h
from roster_file import clean

pages = Blueprint("account_manager", __name__)

# The account states, in the order the Status filter lists them.
STATUSES = ["Active", "Invited", "Missing", "Unlinked", "Disabled", "Email changed", "No email"]

# Check boxes: "Select all visible" and "Clear selection".
SELECT_SCRIPT = "<script>function setAll(v){document.querySelectorAll('.personBox').forEach(x=>x.checked=v)}</script>"


# ------------------------------------------------------------------------------------------ the list

def account_rows(mission_id):
    """Every Active missionary of the mission with their area, roles and account state (see account_status)."""
    with database.connect() as conn:
        with database.cursor(conn) as cur:
            cur.execute("""
                select
                  m.id missionary_id,m.missionary_number,m.display_name,m.email,m.status missionary_status,
                  a.id area_id,a.name area,d.id district_id,d.name district,z.id zone_id,z.name zone,
                  ma.roster_position,ma.roster_position_abbr,min(ma.start_date) assignment_start,
                  au.id auth_user_id,au.invited_at,au.confirmed_at,au.last_sign_in_at,
                  up.missionary_id linked_missionary_id,up.active profile_active,up.app_role,
                  up.additional_roles,
                  coalesce(string_agg(distinct la.role, ', ' order by la.role) filter (where la.role is not null),'') leadership_roles
                from public.missionaries m
                join public.missionary_assignments ma on ma.id=(
                  -- The assignment in force today, as the portal sees it; else the next one (a transfer dated ahead).
                  select x.id from public.missionary_assignments x
                  where x.missionary_id=m.id and (x.end_date is null or x.end_date>=current_date)
                  order by x.start_date>current_date,abs(x.start_date-current_date),x.id desc limit 1)
                join public.areas a on a.id=ma.area_id
                join public.districts d on d.id=a.district_id
                join public.zones z on z.id=d.zone_id
                left join auth.users au on lower(au.email)=lower(m.email)
                left join public.user_profiles up on up.id=au.id
                left join public.leadership_assignments la on la.missionary_id=m.id and la.start_date<=current_date
                  and (la.end_date is null or la.end_date>=current_date)
                where z.mission_id=%s and m.status='Active'
                group by m.id,m.missionary_number,m.display_name,m.email,m.status,
                         a.id,a.name,d.id,d.name,z.id,z.name,ma.roster_position,ma.roster_position_abbr,
                         au.id,au.invited_at,au.confirmed_at,au.last_sign_in_at,up.id,up.missionary_id,up.active,up.app_role
                order by z.name,d.name,a.name,m.display_name
            """, (mission_id,))
            rows = cur.fetchall()
    for r in rows:
        r["account_roles"] = hand_set_roles(r)
        r["account_status"] = account_status(r)
    return rows


def hand_set_roles(r):
    """'President, Data Analyst': the roles set by hand on the account page, shown next to the roster roles."""
    linked = r["linked_missionary_id"] == r["missionary_id"]
    main = [r["app_role"]] if linked and r["app_role"] in roles.HAND_SET_ROLE_NAMES else []
    extra = [x for x in (r["additional_roles"] or []) if linked and x in roles.HAND_SET_ROLE_NAMES and x not in main]
    return ", ".join(roles.HAND_SET_ROLE_NAMES[x] for x in main + extra)


def account_status(r):
    """The state of the sign-in found by the roster email. account_links.with_linked_sign_ins() then corrects it
    with the sign-in actually linked to the missionary."""
    if not r["email"]:
        return "No email"
    if not r["auth_user_id"]:
        return "Missing"
    if r["linked_missionary_id"] != r["missionary_id"]:
        return "Unlinked"
    if r["profile_active"] is False:
        return "Disabled"
    return "Active" if r["last_sign_in_at"] else "Invited"


def role_text(r):
    """All roles of a row, separated by commas (for the Role filter)."""
    return ",".join([r["leadership_roles"] or "", r["roster_position_abbr"] or "", r["account_roles"]])


def split_roles(text):
    return {x.strip() for x in text.split(",") if x.strip()}


def matches(r, filters):
    """Does this row pass every filter the manager chose?"""
    if filters["zone"] and r["zone"] != filters["zone"]:
        return False
    if filters["district"] and r["district"] != filters["district"]:
        return False
    if filters["area"] and r["area"] != filters["area"]:
        return False
    if filters["status"] and r["account_status"] != filters["status"]:
        return False
    if filters["role"] and filters["role"].upper() not in split_roles(role_text(r).upper()):
        return False
    words = f"{r['display_name']} {r['email'] or ''} {r['area']} {r['district']} {r['zone']}".casefold()
    return not filters["q"] or filters["q"] in words


def options(values, selected):
    """<option>s for a filter, starting with All."""
    return '<option value="">All</option>' + ''.join(
        f'<option value="{h(v)}" {"selected" if v == selected else ""}>{h(v)}</option>' for v in values)


def table_row(r):
    """One missionary in the Account Manager table."""
    # Each role once: the roster's DL and the DL assignment are the same role ("DL", not "DL, DL").
    role_display = ", ".join(dict.fromkeys(role.strip() for part in (r["roster_position_abbr"], r["leadership_roles"], r["account_roles"])
                                           for role in (part or "").split(",") if role.strip()))
    return f"""
              <tr>
                <td><input class="personBox" type="checkbox" name="missionary_id" value="{r['missionary_id']}"></td>
                <td>{h(r['display_name'])}<br><span class="muted">{h(r['missionary_number'])}</span></td>
                <td>{h(r['email']) or '<span class="bad">Missing email</span>'}</td>
                <td>{h(r['area'])}{account_links.upcoming(r)}</td><td>{h(r['district'])}</td><td>{h(r['zone'])}</td>
                <td>{h(role_display)}</td>
                <td class="status">{h(r['account_status'])}<br><a href="/accounts/{r['missionary_id']}">Manage settings</a></td>
              </tr>
            """


@pages.route("/accounts")
def accounts():
    """The Account Manager list, filtered as the manager chose."""
    if not sign_in.allowed():
        return sign_in.go_to_login()
    try:
        mission_id = int(request.args.get("mission_id") or sign_in.current_mission_id())
        if mission_id != sign_in.current_mission_id():
            return page.render("<div class='error'>That mission is outside your management scope.</div>", 403)
        rows = account_links.with_linked_sign_ins(account_rows(mission_id))
        filters = {name: request.args.get(name, "") for name in ("zone", "district", "area", "role", "status")}
        filters["q"] = clean(request.args.get("q", "")).casefold()
        shown = [r for r in rows if matches(r, filters)]
        return page.render(accounts_html(mission_id, rows, shown, filters))
    except Exception as e:
        return page.render(f"<div class='error'><b>Account Manager error.</b>\n{h(e)}</div>", 500)


def accounts_html(mission_id, rows, shown, filters):
    """The Account Manager page: numbers, filters, and the table with tick boxes."""
    zones = sorted({r["zone"] for r in rows})
    districts = sorted({r["district"] for r in rows})
    areas = sorted({r["area"] for r in rows})
    all_roles = sorted({x for r in rows for x in split_roles(role_text(r))})
    counts = {s: sum(1 for r in rows if r["account_status"] == s) for s in STATUSES}
    table_rows = [table_row(r) for r in shown]
    return f"""
        <div class="card"><h2>Account Manager</h2>
          <p class="muted">Filter a group, select all visible missionaries, then send account setup. Missing accounts receive an invite; existing accounts receive a password-reset email. Existing accounts are also linked to the correct roster missionary, and a sign-in whose roster email changed moves to the new address. You see what will happen for each person before anything is sent.</p>
          <div class="grid">
            <div class="metric"><b>{len(rows)}</b><br>current missionaries</div>
            <div class="metric"><b>{counts['Active']}</b><br>active accounts</div>
            <div class="metric"><b>{counts['Invited']}</b><br>invited / not signed in</div>
            <div class="metric"><b>{counts['Missing']}</b><br>missing accounts</div>
            <div class="metric"><b>{counts['Unlinked']}</b><br>unlinked accounts</div>
            <div class="metric"><b>{counts['No email']}</b><br>missing email</div>
            <div class="metric"><b>{counts['Email changed']}</b><br>email changed</div>
          </div>
        </div>
        <div class="card">
          <form method="get" class="filters">
            <input type="hidden" name="mission_id" value="{mission_id}">
            <label>Zone<select name="zone">{options(zones, filters['zone'])}</select></label>
            <label>District<select name="district">{options(districts, filters['district'])}</select></label>
            <label>Area<select name="area">{options(areas, filters['area'])}</select></label>
            <label>Role<select name="role">{options(all_roles, filters['role'])}</select></label>
            <label>Account status<select name="status">{options(STATUSES, filters['status'])}</select></label>
            <label>Search<input name="q" value="{h(request.args.get('q',''))}" placeholder="name/email"></label>
            <div><button>Apply filters</button> <a href="/accounts">Clear</a></div>
          </form>
        </div>
        <form action="/accounts/send" method="post">
          <input type="hidden" name="mission_id" value="{mission_id}">
          <div class="card actions">
            <button type="button" class="secondary" onclick="setAll(true)">Select all visible ({len(shown)})</button>
            <button type="button" class="secondary" onclick="setAll(false)">Clear selection</button>
            <button>Check and send account setup</button>
          </div>
          <div class="card scroll"><table>
            <thead><tr><th></th><th>Missionary</th><th>Email</th><th>Area</th><th>District</th><th>Zone</th><th>Role</th><th>Account</th></tr></thead>
            <tbody>{''.join(table_rows) if table_rows else '<tr><td colspan="8" class="muted">No missionaries match these filters.</td></tr>'}</tbody>
          </table></div>
        </form>
        {SELECT_SCRIPT}
        """


# ------------------------------------------------------------------------------------------ sending account setup

@pages.route("/accounts/send", methods=["POST"])
def accounts_send():
    """The button "Send account setup": first "Check before sending", then (with the same plan) the emails."""
    if not sign_in.allowed():
        return sign_in.go_to_login()
    mission_id = int(request.form.get("mission_id") or sign_in.current_mission_id())
    if mission_id != sign_in.current_mission_id():
        return page.render("<div class='error'>That mission is outside your management scope.</div>", 403)
    try:
        selected = [int(x) for x in request.form.getlist("missionary_id")]
        if not selected:
            flash("No missionaries selected.")
            return redirect(f"/accounts?mission_id={mission_id}")
        # The manager first sees what will happen; nothing is sent until they confirm exactly that plan.
        plans = plans_for(selected, mission_id)
        token = account_links.plan_token(plans)
        if request.form.get("plan") != token:
            return page.render(check_page(plans, token, mission_id))
        # Each person on their own, so one bad account cannot stop the others.
        results = [send_one(person) for person in plans]
        return page.render(results_page(results, mission_id))
    except Exception as e:
        return page.render(f"<div class='error'><b>Account Manager error.</b>\n{h(e)}</div><p><a href='/accounts'>Back</a></p>", 500)


def plans_for(selected, mission_id):
    """What "Send account setup" would do for each ticked missionary (see account_links.plan_sign_ins). Raises
    ValueError when one of them is not serving in this mission any more."""
    with database.connect() as conn:
        with database.cursor(conn) as cur:
            cur.execute("""
                select m.id missionary_id,m.display_name,m.email
                from public.missionaries m
                where m.id = any(%s) and exists (
                  select 1 from public.missionary_assignments ma
                  join public.areas a on a.id=ma.area_id join public.districts d on d.id=a.district_id
                  join public.zones z on z.id=d.zone_id
                  where ma.missionary_id=m.id and (ma.end_date is null or ma.end_date>=current_date) and z.mission_id=%s)
                order by m.display_name
            """, (selected, mission_id))
            people = cur.fetchall()
            if len(people) != len(set(selected)):
                raise ValueError("One or more selected missionaries are outside this mission or no longer assigned.")
            return account_links.plan_sign_ins(cur, people)


def check_page(plans, token, mission_id):
    """ "Check before sending": one line per missionary, and the Send button for exactly this plan."""
    changed = ("<p class='warn'>Something changed since you opened this list, so please check it again.</p>"
               if request.form.get("plan") else "")
    sending = sum(1 for p in plans if p["action"] in account_links.SENDING)
    listed = "".join(f"<tr><td>{h(p['display_name'])}</td><td>{h(account_links.describe(p))}</td></tr>" for p in plans)
    hidden = "".join(f"<input type='hidden' name='missionary_id' value='{int(p['missionary_id'])}'>" for p in plans)
    button = ((f"<button>Send {sending} email</button>" if sending == 1 else f"<button>Send {sending} emails</button>") if sending else "")
    return f"""<div class="card"><h2>Check before sending</h2>{changed}<p class="muted">This is what happens for each
              selected missionary. Nothing has been sent yet.</p><div class="scroll"><table><thead><tr><th>Missionary</th><th>What happens</th>
              </tr></thead><tbody>{listed}</tbody></table></div><form action="/accounts/send" method="post"><input type="hidden"
              name="mission_id" value="{mission_id}"><input type="hidden" name="plan" value="{token}">{hidden}<p class="actions">{button}
              <a href="/accounts?mission_id={mission_id}">Back to Account Manager</a></p></form></div>"""


def send_one(person):
    """Does the planned action for one missionary. Returns (name, action, what happened)."""
    action = person["action"]
    if action == "SKIP":
        return person["display_name"], "SKIPPED", person["reason"]
    try:
        if action == "INVITE":
            invite(person)
            return person["display_name"], "INVITE", "New account invite sent and linked"
        # Link the sign-in (or first move it to the roster email) and save that, then send the password email.
        if action == "EMAIL":
            supabase_auth.update_sign_in_email(person["auth_user_id"], person["email"])
        link_and_save(person["auth_user_id"], person["missionary_id"])
        supabase_auth.send_password_email(person["email"])
        return person["display_name"], action, (f"Sign-in moved from {person['old_email']} and password email sent" if action == "EMAIL"
                                                else "Existing sign-in linked and password email sent" if action == "LINK"
                                                else "Password setup/reset email sent")
    except Exception as person_error:
        return person["display_name"], "ERROR", str(person_error)


def invite(person):
    """A new sign-in and its invitation email, linked to the missionary."""
    auth_user_id = supabase_auth.invite(person["email"], {"missionary_id": person["missionary_id"],
                                                          "display_name": person["display_name"]})
    auth_user_id = auth_user_id or newest_sign_in_with(person["email"])
    if not auth_user_id:
        raise ValueError("Invite was accepted by Auth, but the new Auth user ID could not be resolved.")
    link_and_save(auth_user_id, person["missionary_id"])


def newest_sign_in_with(email):
    """The id of the newest sign-in with this email, or None (when Supabase did not say the new id)."""
    with database.connect() as conn:
        with database.cursor(conn) as cur:
            cur.execute("select id from auth.users where lower(email)=lower(%s) order by created_at desc limit 1", (email,))
            found = cur.fetchone()
    return found["id"] if found else None


def link_and_save(auth_user_id, missionary_id):
    with database.connect() as conn:
        with database.cursor(conn) as cur:
            ensure_profile_link(cur, auth_user_id, missionary_id)
        conn.commit()


def ensure_profile_link(cur, auth_user_id, missionary_id):
    """Links a sign-in to a missionary (user_profiles.missionary_id). Refuses a sign-in that belongs to another
    missionary or to a staff account, and a missionary that already has another sign-in."""
    cur.execute("select id,missionary_id,to_jsonb(up)->>'home_mission_id' home_mission_id from public.user_profiles up where id=%s",
                (auth_user_id,))
    profile = cur.fetchone()
    if profile and profile["missionary_id"] not in (None, missionary_id):
        raise ValueError(f"Auth user {auth_user_id} is already linked to missionary {profile['missionary_id']}.")
    if profile and profile["missionary_id"] is None and profile["home_mission_id"]:
        raise ValueError("This sign-in belongs to a staff account (President, Office or Data Analyst), so it cannot be linked to a missionary.")
    if profile and profile["missionary_id"] == missionary_id:
        return  # already linked: keep it as it is (sending a password email must not turn a turned-off account back on)

    cur.execute("select id,missionary_id from public.user_profiles where missionary_id=%s and id<>%s", (missionary_id, auth_user_id))
    other = cur.fetchone()
    if other:
        raise ValueError(f"Missionary {missionary_id} is already linked to another Auth user {other['id']}.")

    if profile:
        cur.execute("update public.user_profiles set missionary_id=%s,active=true,updated_at=now() where id=%s", (missionary_id, auth_user_id))
    else:
        cur.execute("insert into public.user_profiles(id,missionary_id,app_role,active) values(%s,%s,'MISSIONARY',true)", (auth_user_id, missionary_id))


def results_page(results, mission_id):
    rows_html = ''.join(f'<tr><td>{h(n)}</td><td>{h(a)}</td><td>{h(m)}</td></tr>' for n, a, m in results)
    failures = sum(1 for _, a, _ in results if a == "ERROR")
    heading_class = "warn" if failures else "good"
    heading = "Account batch finished with errors" if failures else "Account action complete"
    return f"""<div class="card"><h2 class="{heading_class}">{heading}</h2><table><thead><tr><th>Missionary</th><th>Action</th><th>Result</th></tr></thead><tbody>{rows_html}</tbody></table><p><a href="/accounts?mission_id={mission_id}">Back to Account Manager</a></p></div>"""
