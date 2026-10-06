"""One missionary's account page ("Manage settings" in Account Manager).

Pages:
  /accounts/<id>             the page: account access (main role, additional roles, account active), assigned
                             languages, and the area with an effective date. "What saving will change" lists what
                             a save would end or start (account_roles.role_plan), and refreshes while you choose.
  /accounts/<id>/role-plan   the refresh: the same plan as JSON, for the choices on the page right now
  /accounts/<id>/update      the save

Every save that changes a role, the account status, the area or a leadership assignment is written down as an
ACCOUNT batch in Import history (account_changes.py), so it can be undone. A move already saved for a later day can
be taken back with "stay here" (account_moves.py).
"""
import re
from datetime import date, timedelta

from flask import Blueprint, flash, redirect, request, session

import account_changes
import account_moves
import account_roles
import database
import page
import places
import roles
import sign_in
from account_roles import leader_label
from page import day, h

pages = Blueprint("account_page", __name__)

# The Main role list spells the leadership roles out; everywhere else the short codes stay (DL, ZL, STL, AP).
MAIN_ROLE_LABELS = {"MISSIONARY": "Missionary", "DL": "District leader (DL)", "STL": "Sister training leader (STL)",
                    "ZL": "Zone leader (ZL)", "AP": "Assistant to the President (AP)", "PRESIDENT": "President"}
# One line each, in the wording of the Preach My Gospel guide (round 3); the rights are in portal-api/roles.py.
ADDITIONAL_HELP = {"DATA_ADMIN": "Keeps the mission's data and the portal working: accounts, imports, planning questions and "
                                 "reports. Sees the whole mission, with Dashboards and DA Management.",
                   "OFFICE": "Office missionary: edits the mission calendar and records meeting attendance."}
ADDITIONAL_NOTE = ("These add to the main role and never end a leadership assignment. A district leader who is also a "
                   "Data Analyst keeps their district.")
PRESIDENT_HELP = "the mission president, who sees and helps manage everything in the mission."
OWN_ACCESS_MESSAGE = ("Saving this ends your own DA Management access{when}. Use another administrator, or tick "
                      "\"I understand\" under What saving will change to confirm it.")
LANGUAGE_CODE = re.compile(r"^[a-zA-Z]{2,3}(?:-[a-zA-Z0-9]{2,8})*$")

# The page's script: refresh "What saving will change" when the role, the additional roles, area or date change.
# Saving with a change first fetches the plan for exactly those values (never an older, still-loading one) and asks
# before an assignment ends; if the plan cannot be fetched, a changed role or area still asks. When the save would end
# your own DA Management access, the plan shows a box to tick first.
ACCOUNT_SCRIPT = """<script>(()=>{const f=document.getElementById('accountForm'),box=document.getElementById('rolePlan'),own=document.getElementById('ownAccess'),el=f.elements;let seq=0,sent=false;
const extra=()=>[...f.querySelectorAll('input[name=additional]')].filter(x=>x.checked).map(x=>x.value).join(',');
const vals=()=>({role:el.role.value,additional:extra(),area_id:el.area_id.value,effective_date:el.effective_date.value}),start=vals(),same=(a,b)=>Object.keys(a).every(k=>a[k]===b[k]);
const show=p=>{const ul=document.createElement('ul');[...(p.errors||[]).map(t=>[t,'bad']),...(p.lines||[]).map(t=>[t,''])].forEach(([t,k])=>{const li=document.createElement('li');li.textContent=t;if(k)li.className=k;ul.append(li)});box.querySelector('ul').replaceWith(ul);box.dataset.ends=p.ends||0;own.hidden=!+p.own;if(p.own_text)document.getElementById('ownAccessText').textContent=p.own_text};
const plan=async()=>{const n=++seq,c=new AbortController(),t=setTimeout(()=>c.abort(),8000);try{const r=await fetch(location.pathname+'/role-plan?'+new URLSearchParams(vals()),{headers:{Accept:'application/json'},signal:c.signal});const p=await r.json();if(n===seq)show(p);return n===seq?p:null}catch(_){return null}finally{clearTimeout(t)}};
f.addEventListener('change',e=>{if(['role','additional','area_id','effective_date'].includes(e.target.name))plan()});
f.addEventListener('submit',async e=>{if(sent)return;const now=vals();if(same(now,start))return;e.preventDefault();const p=await plan();if(!same(now,vals()))return;
  if(p&&+p.own&&!el.own_access.checked){own.hidden=false;el.own_access.focus();return}
  const ends=p?+p.ends:now.role!==start.role||now.area_id!==start.area_id,text=p?[...box.querySelectorAll('li')].map(li=>li.textContent).join('\\n'):'Changing the role or area can end a leadership assignment.';
  if(ends&&!confirm(text+'\\n\\nSave these changes?'))return;sent=true;f.submit()})})()</script>"""

# The languages offered in the Primary mission language box: the portal's 14, and one more example code.
LANGUAGE_LIST = """<datalist id="languages"><option value="en">English</option><option value="de">German</option><option value="es">Spanish</option><option value="fr">French</option><option value="pt">Portuguese</option><option value="uk">Ukrainian</option><option value="ru">Russian</option><option value="it">Italian</option><option value="tr">Turkish</option><option value="fa">Persian</option><option value="ro">Romanian</option><option value="sv">Swedish</option><option value="da">Danish</option><option value="ar">Arabic</option><option value="zh-Hant">Chinese (Traditional)</option></datalist>"""


# ------------------------------------------------------------------------------------------ reading

def person(cur, person_id):
    """The missionary with their area assignment (the one in force today, else the next one), district, zone, linked
    account (profile_id, app_role, profile_active, additional_roles) and languages. None outside this mission."""
    cur.execute("""select m.*,ma.id assignment_id,ma.start_date assignment_start,ma.end_date assignment_end,ma.area_id,a.name area,
      d.id district_id,d.name district,z.id zone_id,z.name zone,up.id profile_id,up.app_role,up.active profile_active,
      coalesce(to_jsonb(up)->'additional_roles','[]'::jsonb) additional_roles,
      l.primary_language,coalesce(l.additional_languages,'{}') additional_languages
      from public.missionaries m join public.missionary_assignments ma on ma.missionary_id=m.id and (ma.end_date is null or ma.end_date>=current_date)
      join public.areas a on a.id=ma.area_id join public.districts d on d.id=a.district_id join public.zones z on z.id=d.zone_id
      left join public.user_profiles up on up.missionary_id=m.id
      left join public.missionary_language_assignments l on l.missionary_id=m.id
      where m.id=%s and z.mission_id=%s order by ma.start_date>current_date,ma.start_date desc limit 1""",
                (person_id, sign_in.current_mission_id()))
    return cur.fetchone()


def area_of(p, areas):
    """The missionary's own area from the list (or made from their row, when nobody else serves there)."""
    return next((a for a in areas if a["id"] == p["area_id"]), {"id": p["area_id"], "name": p["area"], "district_id": p["district_id"],
                                                                "district": p["district"], "zone_id": p["zone_id"], "zone": p["zone"]})


def parse_languages(primary, additional):
    """(primary language code, [learning language codes]) from the two boxes. Raises ValueError for a code that is not
    a language code, or the primary language also listed as a learning language."""
    primary = primary.strip().lower()
    extras = list(dict.fromkeys(v.strip().lower() for v in re.split(r"[,;\s]+", additional) if v.strip()))
    if not LANGUAGE_CODE.fullmatch(primary) or any(not LANGUAGE_CODE.fullmatch(v) for v in extras):
        raise ValueError("Use language codes such as en, de, es, or zh-Hant.")
    if primary in extras:
        raise ValueError("The primary language must not also appear in learning languages.")
    return primary, extras


# ------------------------------------------------------------------------------------------ the page

@pages.route("/accounts/<int:person_id>")
def account_detail(person_id):
    """The account page of one missionary."""
    if not sign_in.allowed():
        return sign_in.go_to_login()
    today = date.today()
    with database.connect() as conn:
        with database.cursor(conn) as cur:
            p = person(cur, person_id)
            if not p:
                return page.render("<div class='error'>Missionary not found in this mission.</div>", 404)
            move = account_moves.upcoming_move(cur, p)  # an area change recorded for a later day
            areas = account_moves.with_stay_option(places.current_areas(cur), p, move)
            leaders = account_roles.open_leaders(cur, person_id, today)
    current = account_roles.effective_role(p["app_role"], leaders, today)
    plan = account_roles.role_plan(p, leaders, current, area_of(p, areas), today, today)
    return page.render(account_html(p, leaders, move, areas, current, plan, today) + ACCOUNT_SCRIPT)


def current_role_text(p, leaders, move, current, today):
    """The "Current role" line: the role and where it comes from, what starts later, a move ahead, the recorded role
    and the additional roles."""
    held = "; ".join(since(l) for l in leaders if account_roles.holds(l, today))
    upcoming = "; ".join(leader_label(l["role"], l["district"], l["zone"], "from", date=day(l["start_date"]))
                         for l in leaders if not account_roles.holds(l, today))
    now = (f"{roles.role_name(current)}, set by hand on this page" + (f". Also holds the {held}" if held else "")
           if current in roles.HAND_SET_ROLES else f"{current}, from the {held}" if held else "Missionary (no current leadership assignment)")
    now += f". Starting later: {upcoming}" if upcoming else ""
    now += account_moves.note(move)
    now += f". Recorded account role: {roles.role_name(p['app_role'] or 'MISSIONARY')}" if p["profile_id"] else ""
    extras = account_roles.additional_of(p)
    now += f". Additional roles: {', '.join(roles.role_name(r) for r in extras)}" if extras else ""
    return now


def since(l):
    """'ZL assignment for North zone since 01 Jan 2026' (with ', ending ...' when it ends)."""
    if l["end_date"]:
        return leader_label(l["role"], l["district"], l["zone"], "since_ending", date=day(l["start_date"]), end=day(l["end_date"]))
    return leader_label(l["role"], l["district"], l["zone"], "since", date=day(l["start_date"]))


def plan_list(plan):
    """The list inside "What saving will change": errors in red first."""
    return "<ul>" + "".join(f"<li class='bad'>{h(e)}</li>" for e in plan["errors"]) + "".join(f"<li>{h(l)}</li>" for l in plan["lines"]) + "</ul>"


def account_note(p):
    """A warning at the top: no linked account yet, or an account the signed-in manager may not change."""
    note = "" if p["profile_id"] else "<p class='warn'>No linked account yet. Invite or link the account from Account Manager before changing account access.</p>"
    if p["profile_id"] and not roles.may_change(p):  # e.g. an AP on the President's page: languages only
        note += f"<p class='warn'>{h(roles.NOT_ALLOWED_ACCOUNT)}</p>"
    return note


def account_html(p, leaders, move, areas, current, plan, today):
    """The middle of the account page: access, languages, area, "What saving will change"."""
    area_options = "".join(f'<option value="{a["id"]}" {"selected" if a["id"] == p["area_id"] else ""}>{h(a["zone"])} / {h(a["name"])}</option>' for a in areas)
    role_options = "".join(f'<option value="{r}" {"selected" if r == current else ""}>{MAIN_ROLE_LABELS.get(r, roles.role_name(r))}</option>'
                           for r in account_roles.main_role_choices(p))
    disabled = "disabled" if not p["profile_id"] else ""
    saved_extras = account_roles.additional_of(p)
    extras = "".join(f"""<label class="role-choice"><input type="checkbox" name="additional" value="{r}" {'checked' if r in saved_extras else ''} {disabled}><span><b>{roles.role_name(r)}</b><br>{h(ADDITIONAL_HELP[r])}</span></label>""" for r in roles.ADDITIONAL_ROLES)
    now = current_role_text(p, leaders, move, current, today)
    return f"""<div class="card"><h2>{h(p['display_name'])}</h2><p class="muted">{h(p['email'])} · {h(p['missionary_number'])}</p>{account_note(p)}<form id="accountForm" action="/accounts/{p['id']}/update" method="post"><input type="hidden" name="state" value="{h(account_changes.page_state(p, leaders))}"><div class="split"><div><h3>Account access</h3><p>Current role: <b>{h(now)}</b>.</p><label class="form-field">Main role<select name="role" {disabled}>{role_options}</select></label><fieldset class="role-group"><legend>Additional roles (optional)</legend><p class="muted">{ADDITIONAL_NOTE}</p><input type="hidden" name="additional_shown" value="yes">{extras}</fieldset><label class="role-choice"><input type="checkbox" name="active" value="yes" {'checked' if p['profile_active'] else ''} {disabled}><span><b>Account active</b></span></label><p class="muted"><b>President</b>: {PRESIDENT_HELP} Set only here. District, zone and sister training leaders and APs come from leadership assignments and follow the selected area; the next transfer roster may change them.</p></div><div><h3>Assigned languages</h3><label class="form-field">Primary mission language<input name="primary_language" list="languages" value="{h(p['primary_language'])}" required></label><label class="form-field">Additional learning languages<input name="additional_languages" value="{h(', '.join(p['additional_languages']))}" placeholder="es, fr"></label><p class="muted">Users may switch among these assigned codes. The portal, DA Management and Presentations are translated into these 14: en, de, es, fr, pt, uk, ru, it, tr, fa, ro, sv, da and ar; other codes show English.</p>{LANGUAGE_LIST}</div></div><h3>Area &amp; leadership assignment</h3><div class="split"><label class="form-field">Assigned area<select name="area_id">{area_options}</select></label><label class="form-field">Effective date<input type="date" name="effective_date" value="{today}" required></label></div><div class="plan" id="rolePlan" data-ends="{len(plan['end'])}" aria-live="polite"><b>What saving will change</b>{plan_list(plan)}</div><label class="role-choice" id="ownAccess" {'' if plan['own'] else 'hidden'}><input type="checkbox" name="own_access" value="yes"><span><b>I understand</b><br><span id="ownAccessText">{h(account_roles.own_tick_text(plan, today))}</span></span></label><button>Save management changes</button></form></div><p><a href="/accounts">Back to Account Manager</a></p>"""


# ------------------------------------------------------------------------------------------ the plan, while choosing

@pages.route("/accounts/<int:person_id>/role-plan")
def account_role_plan(person_id):
    """The "What saving will change" box for the choices on the page right now (JSON for the page's script)."""
    if not sign_in.allowed():
        return {"errors": ["Your management session ended. Reload the page."], "lines": [], "ends": 0}, 401
    try:
        try:
            effective = date.fromisoformat(request.args.get("effective_date", ""))
        except ValueError:
            raise ValueError("Choose an effective date.")
        with database.connect() as conn:
            with database.cursor(conn) as cur:
                p = person(cur, person_id)
                if not p:
                    return {"errors": ["Missionary not found in this mission."], "lines": [], "ends": 0}, 404
                area_id = int(request.args.get("area_id") or 0)
                if area_id < 0:  # "stay here": take back a move saved for a later day
                    return account_moves.stay_plan(cur, p, -area_id)
                area = {a["id"]: a for a in places.current_areas(cur)}.get(area_id)
                if not area:
                    raise ValueError("Choose an area in this mission.")
                if area["id"] != p["area_id"] and p["assignment_end"]:  # a change is already recorded for a later day
                    return {"errors": [account_moves.move_refusal(cur, p)], "lines": [], "ends": 0}
                today = date.today()
                leaders = account_roles.open_leaders(cur, person_id, today)
        role = request.args.get("role") or account_roles.effective_role(p["app_role"], leaders, today)
        if role not in account_roles.main_role_choices(p):
            raise ValueError("Choose a role from the list.")
        additional = account_roles.clean_additional(request.args["additional"].split(","), role) if "additional" in request.args else None
        plan = account_roles.role_plan(p, leaders, role, area, effective, today, additional)
        refused = account_roles.account_refusal(p, plan, role)  # the save refuses it too; the box says so before saving
        if refused:
            plan["errors"].append(refused)
        return {"errors": plan["errors"], "lines": plan["lines"], "ends": len(plan["end"]), "own": int(plan["own"]),
                "own_text": account_roles.own_tick_text(plan, today)}
    except ValueError as e:
        return {"errors": [str(e)], "lines": [], "ends": 0}, 400


# ------------------------------------------------------------------------------------------ the save

@pages.route("/accounts/<int:person_id>/update", methods=["POST"])
def account_update(person_id):
    """Saves the account page: roles, Account active, area, leadership and languages."""
    if not sign_in.allowed():
        return sign_in.go_to_login()
    try:
        primary, extras = parse_languages(request.form.get("primary_language", ""), request.form.get("additional_languages", ""))
        effective = date.fromisoformat(request.form["effective_date"])
        today = date.today()
        with database.connect() as conn:
            with database.cursor(conn) as cur:
                cur.execute("select id from public.missions where id=%s for update", (sign_in.current_mission_id(),))
                p = person(cur, person_id)
                if not p:
                    raise ValueError("Missionary is outside this mission.")
                areas = {a["id"]: a for a in places.current_areas(cur)}
                if int(request.form["area_id"]) < 0:  # "stay here": only takes back the move saved for a later day
                    return account_moves.cancel(cur, p, -int(request.form["area_id"]), request.form.get("state"))
                area = areas.get(int(request.form["area_id"]))
                if not area:
                    raise ValueError("Area is outside this mission.")
                if area["id"] != p["area_id"] and p["assignment_end"]:  # a change is already recorded for a later day
                    raise ValueError(account_moves.move_refusal(cur, p))
                leaders = account_roles.open_leaders(cur, person_id, today, lock=True)
                if request.form.get("state") != account_changes.page_state(p, leaders):
                    raise ValueError(account_changes.STALE)
                role, plan, active, own_confirmed = checked_plan(p, leaders, area, effective, today)
                before = account_changes.account_snapshot(conn, person_id, lock=True)  # for the ACCOUNT batch below
                save_account(cur, p, plan, active)
                save_assignments(cur, p, plan, role, area, effective)
                if sign_in.is_me(p["profile_id"]) and not own_confirmed:
                    check_own_access_stays(cur, p)
                # Who changed which role, status or assignment, in Import history (with Undo), as on Staff accounts.
                batch = account_changes.record_account_batch(conn, p, before, effective)
                save_languages(cur, person_id, primary, extras)
        if own_confirmed and plan["own_from"] <= today:
            session.clear()  # the next request would find no management access anyway
            return page.render("<div class='card'><h2 class='good'>Saved</h2><p>Your own DA Management access has ended, so you are "
                               f"signed out of DA Management. Ask {roles.WHO_GIVES_ACCESS} if you need it again.</p></div>")
        say_what_was_saved(p, plan, area, batch, own_confirmed)
        return redirect(f"/accounts/{person_id}")
    except Exception as e:
        return page.render(f"<div class='error'><b>Nothing was committed.</b><br>{h(e)}</div><p><a href='/accounts/{person_id}'>Back</a></p>", 400)


def checked_plan(p, leaders, area, effective, today):
    """The plan for the sent form, after every check. Returns (role, plan, account active, own access confirmed).
    Raises ValueError with the reason when the save may not happen."""
    # The page preselects the effective role, so a save that only edits languages keeps every leadership row.
    role = request.form.get("role") or account_roles.effective_role(p["app_role"], leaders, today)
    if role not in account_roles.main_role_choices(p):
        raise ValueError("Choose a role from the list.")
    # A page from before the additional roles (no marker) keeps the saved ones.
    additional = (account_roles.clean_additional(request.form.getlist("additional"), role)
                  if request.form.get("additional_shown") == "yes" else None)
    plan = account_roles.role_plan(p, leaders, role, area, effective, today, additional)
    if plan["errors"]:
        raise ValueError("\n".join(plan["errors"]))
    active = request.form.get("active") == "yes"
    # Same rules as Staff accounts: an AP, the President or a Data Analyst may give or take away every role, also
    # their own (APs have full rights); ending your own access needs the tick.
    refused = account_roles.account_refusal(p, plan, role, active)
    if refused:
        raise ValueError(refused)
    own_confirmed = plan["own"] and request.form.get("own_access") == "yes"
    if plan["own"] and not own_confirmed:
        raise ValueError(OWN_ACCESS_MESSAGE.format(when=account_roles.own_when(plan, today)))
    return role, plan, active, own_confirmed


def save_account(cur, p, plan, active):
    """Saves the recorded main role, the additional roles and Account active (only when something differs)."""
    if not p["profile_id"]:
        return
    if sign_in.is_me(p["profile_id"]) and not active:
        raise ValueError("Use another administrator to remove your own management access.")
    record = plan["record"]  # never a DL/ZL/STL/AP role before its assignment starts (see account_roles.recorded_role)
    extra_roles = plan["additional"]
    cur.execute("""update public.user_profiles set app_role=%s,additional_roles=%s,active=%s,updated_at=now()
      where id=%s and (app_role,additional_roles,active) is distinct from (%s,%s::text[],%s)""",
                (record, extra_roles, active, p["profile_id"], record, extra_roles, active))


def save_assignments(cur, p, plan, role, area, effective):
    """A new area from the effective date, and the leadership assignments the plan ends or starts."""
    last_day = effective - timedelta(days=1)
    if area["id"] != p["area_id"]:
        cur.execute("update public.missionary_assignments set end_date=%s where id=%s", (last_day, p["assignment_id"]))
        cur.execute("insert into public.missionary_assignments(missionary_id,area_id,start_date) values(%s,%s,%s)", (p["id"], area["id"], effective))
    for leader in plan["end"]:
        cur.execute("update public.leadership_assignments set end_date=%s where id=%s", (last_day, leader["id"]))
    if plan["start"]:
        scope = roles.LEADER_SCOPE[role]
        cur.execute("""insert into public.leadership_assignments(missionary_id,role,district_id,zone_id,mission_id,start_date)
          values(%s,%s,%s,%s,%s,%s)""", (p["id"], role, area["district_id"] if scope == "district" else None,
                                         area["zone_id"] if scope == "zone" else None,
                                         sign_in.current_mission_id() if scope == "mission" else None, effective))


def check_own_access_stays(cur, p):
    """Your own account, saved without the "I understand" tick: this uncommitted save, as the next request would see
    it, must leave you your DA Management access."""
    context = sign_in.management_context(cur, p["profile_id"])
    if not context or int(context["mission_id"]) != sign_in.current_mission_id():
        raise ValueError(OWN_ACCESS_MESSAGE.format(when=""))


def save_languages(cur, person_id, primary, extras):
    cur.execute("""insert into public.missionary_language_assignments(missionary_id,primary_language,additional_languages,assigned_by)
      values(%s,%s,%s,%s) on conflict(missionary_id) do update set primary_language=excluded.primary_language,
      additional_languages=excluded.additional_languages,assigned_by=excluded.assigned_by,updated_at=now()""",
                (person_id, primary, extras, sign_in.actor_name()))


def say_what_was_saved(p, plan, area, batch, own_confirmed):
    """The short messages at the top of the page after a save."""
    if plan["end"] or plan["start"] or area["id"] != p["area_id"]:
        flash("Account, assignment and language settings saved.")
    else:
        flash(f"Account saved. {p['display_name']}'s leadership assignment is unchanged.")
    changes = [line for line in plan["changes"] if line != plan["own_line"]]
    if changes:
        flash(" ".join(changes))
    if own_confirmed:  # it ends later: you stay signed in until then
        flash(f"You keep your own DA Management access until {day(plan['own_from'] - timedelta(days=1))}. "
              f"From {day(plan['own_from'])} you no longer have it; ask {roles.WHO_GIVES_ACCESS} if you need it again.")
    if batch:
        flash(account_changes.IN_HISTORY)
