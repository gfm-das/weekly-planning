"""The rules of a missionary's account page: which role they have, and what saving a change would do.

A missionary's MAIN role comes from their leadership assignments (DL, ZL, STL, AP), or is set by hand (President).
Data Analyst and Office are ADDITIONAL roles on top (roles.py explains every role).

role_plan() is the heart of it. It works out, in plain sentences, what saving the account page would change:
which leadership assignment ends or starts and on which day, which role is recorded, and whether someone gets or
loses DA Management access (and whether that is the manager's OWN access). The page shows these sentences under
"What saving will change" before saving, and the save itself uses the same plan, so what you read is what happens.

Used by account_page.py (the page and its save) and account_moves.py (taking back a move saved for a later day).
"""
from datetime import date, timedelta

import roles
import sign_in
from page import day

# A leadership assignment's name in each form the account page uses, as whole phrases for a district, a zone and the
# mission, so the portal's catalog can translate each one (dam.leader.*; role, district, zone, date and end are values).
LEADER_FORMS = {
    "bare": ("{role} assignment for {district} district", "{role} assignment for {zone} zone",
             "{role} assignment for the whole mission"),
    "current": ("the current {role} assignment for {district} district", "the current {role} assignment for {zone} zone",
                "the current {role} assignment for the whole mission"),
    "starts": ("the {role} assignment for {district} district (starts {date})",
               "the {role} assignment for {zone} zone (starts {date})",
               "the {role} assignment for the whole mission (starts {date})"),
    "the": ("the {role} assignment for {district} district", "the {role} assignment for {zone} zone",
            "the {role} assignment for the whole mission"),
    "since": ("{role} assignment for {district} district since {date}", "{role} assignment for {zone} zone since {date}",
              "{role} assignment for the whole mission since {date}"),
    "since_ending": ("{role} assignment for {district} district since {date}, ending {end}",
                     "{role} assignment for {zone} zone since {date}, ending {end}",
                     "{role} assignment for the whole mission since {date}, ending {end}"),
    "from": ("{role} assignment for {district} district from {date}", "{role} assignment for {zone} zone from {date}",
             "{role} assignment for the whole mission from {date}"),
}


# ------------------------------------------------------------------------------------------ leadership assignments

def open_leaders(cur, person_id, today, lock=False):
    """DL/ZL/STL/AP rows of one missionary that have not ended before `today`: current ones, ones set to end later
    (a transfer dated ahead) and ones that start later. With the names of their district or zone."""
    cur.execute("""select la.id,la.role,la.district_id,la.zone_id,la.mission_id,la.start_date,la.end_date,d.name district,z.name zone
      from public.leadership_assignments la left join public.districts d on d.id=la.district_id
      left join public.zones z on z.id=la.zone_id
      where la.missionary_id=%s and (la.end_date is null or la.end_date>=%s) and la.role=any(%s) order by la.start_date,la.id"""
                + (" for update of la" if lock else ""), (person_id, today, list(roles.LEADER_ROLES)))
    return cur.fetchall()


def holds(leader, when):
    """True when the assignment is in force on `when`, as the database's access checks count it."""
    return leader["start_date"] <= when and (leader["end_date"] is None or leader["end_date"] >= when)


def top_role(leaders):
    """The highest leadership role of these rows (AP, then ZL, STL, DL), or MISSIONARY."""
    held = {l["role"] for l in leaders}
    return next((r for r in roles.LEADER_ORDER if r in held), "MISSIONARY")


def effective_role(app_role, leaders, today):
    """The main role an account really has today. President (and an older Data Analyst or Office main role) is set by
    hand and comes first, as in portal-api's roles.main_role(). DL/ZL/STL/AP come only from assignments in force today
    (not ones that start later): a saved app_role such as a former AP's counts for nothing. Additional roles (Data
    Analyst, Office) are separate: see role_plan."""
    if app_role in roles.HAND_SET_ROLES:
        return app_role
    return top_role([l for l in leaders if holds(l, today)])


def recorded_role(role, leaders, today):
    """The app_role a save stores. President (or an older Office/Data Analyst main role) as chosen. Otherwise the
    highest assignment in force today, as public.sync_user_profile_roles() records it, but never above the chosen
    role: so a role is never recorded before its assignment starts, and a lower chosen role is recorded at once. AP
    counts only while its assignment has no end date: the database's zone and mission checks trust app_role AP on its
    own, and nothing resets it when the assignment ends (their ZL/STL checks also need the assignment itself)."""
    if role in roles.HAND_SET_ROLES:
        return role
    held = top_role([l for l in leaders if holds(l, today) and (l["role"] != "AP" or l["end_date"] is None)])
    # The lower of the two: MISSIONARY lowest, then DL, STL, ZL, AP.
    return min(held, role, key=lambda r: roles.LEADER_ORDER[::-1].index(r) + 1 if r in roles.LEADER_ORDER else 0)


def leader_label(role, district=None, zone=None, form="bare", **values):
    """'ZL assignment for North zone' (form bare), or another form of LEADER_FORMS."""
    scope = roles.LEADER_SCOPE[role]
    template = LEADER_FORMS[form][0 if scope == "district" else 1 if scope == "zone" else 2]
    return template.format(role=role, district=district, zone=zone, **values)


def leader_name(l, today, dated=True):
    """'the current ZL assignment for X zone', or 'the AP assignment for the whole mission (starts 01 Jan 2099)'."""
    if l["start_date"] <= today:
        return leader_label(l["role"], l["district"], l["zone"], "current")
    if dated:
        return leader_label(l["role"], l["district"], l["zone"], "starts", date=day(l["start_date"]))
    return leader_label(l["role"], l["district"], l["zone"], "the")


def capital(text):
    """The text with a capital first letter."""
    return text[:1].upper() + text[1:]


# ------------------------------------------------------------------------------------------ the roles of an account

def additional_of(p):
    """The saved additional roles of the account, in page order (an empty list without migration 021)."""
    saved = {str(r).upper() for r in (p.get("additional_roles") or [])}
    return [r for r in roles.ADDITIONAL_ROLES if r in saved]


def main_role_choices(p):
    """The Role list for this account: the main roles, plus an older Data Analyst or Office main role it still has
    (from before migration 021), so the page shows it as it is."""
    legacy = p.get("app_role") if p.get("app_role") in roles.HAND_SET_ROLES - {"PRESIDENT"} else None
    return roles.MAIN_ROLES + ([legacy] if legacy else [])


def clean_additional(values, role):
    """The ticked additional roles, checked and in page order; one that is already the main role is dropped."""
    wanted = {str(v).strip().upper() for v in values if str(v).strip()}
    if wanted - set(roles.ADDITIONAL_ROLES):
        raise ValueError("Choose Data Analyst or Office as additional roles.")
    return [r for r in roles.ADDITIONAL_ROLES if r in wanted and r != role]


def account_refusal(p, plan, role, active=None):
    """Why the signed-in manager may not save this account page change, or None. Same rules as Staff accounts: an AP,
    the President or a Data Analyst (or the old shared password) may give or take away the President and Data Analyst
    roles, also on their own account, and turn off or change a President's account (APs have full rights, owner
    28 Sep). active: the Account active box (None: not known)."""
    before = roles.all_roles_of(p)
    after = {str(plan["record"] or "").upper(), role} | {str(r).upper() for r in (plan["additional"] or [])}
    if not all(roles.may_give(r) for r in (before ^ after) & roles.HIGH_ROLES):
        return "Only an AP, the President or a Data Analyst can give or take away the President or Data Analyst role."
    roles_change = (plan["record"] or "") != (p["app_role"] or "") or set(plan["additional"] or []) != set(additional_of(p))
    active_change = active is not None and active != bool(p["profile_active"])
    if p["profile_id"] and not roles.may_change(p) and (roles_change or active_change):
        return roles.NOT_ALLOWED_ACCOUNT
    return None


# ------------------------------------------------------------------------------------------ what saving will change

def role_plan(p, leaders, role, area, effective, today=None, additional=None):
    """What saving the account page does, in plain sentences. The page text and the save share this one rule:
    leadership rows change only when the chosen main role, or the scope of the chosen area, differs from today's.
    Additional roles (Data Analyst, Office; None = keep the saved ones) never change a leadership row.

    p: the missionary (account_page.person), leaders: open_leaders(), role: the chosen main role, area: the chosen
    area, effective: the chosen effective date. Returns a dict: lines (what the box shows), changes, errors, end
    (assignments that end), start (a role that starts), record (the app_role to save), additional, own, own_from,
    own_line (about the manager's own access)."""
    today = today or date.today()
    saved_additional = additional_of(p)
    additional = saved_additional if additional is None else additional
    plan = {"current": effective_role(p["app_role"], leaders, today), "end": [], "start": None, "record": p["app_role"],
            "additional": additional, "own": False, "own_from": None, "own_line": None, "lines": [], "changes": [],
            "errors": []}
    moved = area["id"] != p["area_id"]
    if moved and effective <= p["assignment_start"]:
        plan["errors"].append(f"A move date must be after {day(p['assignment_start'])}, when the current area assignment started.")
    if not p["profile_id"]:
        plan["lines"].append("No linked account yet, so the role and leadership assignments are not changed here.")
        return plan
    kept = plan_leaders(plan, leaders, role, area, effective, today, moved)
    if role in roles.LEADER_ROLES and not any(l["role"] == role for l in kept):
        plan["start"] = role
        plan["changes"].append(f"A new {leader_label(role, area['district'], area['zone'])} starts on {day(effective)}.")
    after = assignments_after(plan, leaders, role, effective)
    plan_recorded_role(plan, p, role, after, effective, today)
    plan_additional_roles(plan, additional, saved_additional)
    explain_recorded_role(plan, role, after, today)
    plan_access(plan, p, (saved_additional, leaders), (additional, after), effective, today)
    plan["lines"] = plan["changes"] + plan["lines"] or ([] if plan["errors"] else ["No change to the role or leadership assignments."])
    return plan


def plan_leaders(plan, leaders, role, area, effective, today, moved):
    """Each open leadership assignment stays, already ends, cannot end on that date (an error), or ends the day before
    the effective date. Returns the ones that stay."""
    changed = role != plan["current"]
    last_day = effective - timedelta(days=1)
    place_ids = (area["district_id"], area["zone_id"], sign_in.current_mission_id())
    kept = []
    for l in leaders:
        name = leader_name(l, today)
        other_role = changed and l["role"] != role
        if not (other_role or ((changed or moved) and not roles.leads_the_same(l, l["role"], place_ids))):
            kept.append(l)
            plan["lines"].append(f"{capital(name)} stays as it is and ends on {day(l['end_date'])}." if l["end_date"]
                                 else f"{capital(name)} stays as it is.")
        elif effective <= l["start_date"]:  # only the error: this save cannot end it on that date
            when, first = leader_name(l, today, False), day(l["start_date"])
            plan["errors"].append(f"The effective date must be after {first}, when {when} started." if l["start_date"] <= today
                                  else f"The effective date must be after {first}, when {when} starts.")
        elif l["end_date"] and l["end_date"] <= last_day:
            plan["lines"].append(f"{capital(name)} already ends on {day(l['end_date'])}.")
        else:
            plan["end"].append(l)
            # Whole sentences (here and below), so the portal catalog can translate each one.
            plan["changes"].append(f"Changing the role ends {name} on {day(last_day)}." if other_role
                                   else f"Moving to {area['name']} ends {name} on {day(last_day)}.")
    return kept


def assignments_after(plan, leaders, role, effective):
    """The leadership assignments as they will be after this save (for the recorded role and the access)."""
    ending = {l["id"] for l in plan["end"]}
    last_day = effective - timedelta(days=1)
    after = [dict(l, end_date=last_day) if l["id"] in ending else l for l in leaders]
    if plan["start"]:
        after.append({"role": role, "start_date": effective, "end_date": None})
    return after


def plan_recorded_role(plan, p, role, after, effective, today):
    """The app_role this save records, and a line when it changes."""
    plan["record"] = recorded_role(role, after, today)
    saved = p["app_role"] or "MISSIONARY"
    if saved != plan["record"]:
        plan["changes"].append(f"Recorded account role: {roles.role_name(saved)} → {roles.role_name(plan['record'])}"
                               + (f". This takes effect today, not on {day(effective)}." if effective > today else "."))


def plan_additional_roles(plan, additional, saved_additional):
    for extra in roles.ADDITIONAL_ROLES:
        if (extra in additional) != (extra in saved_additional):
            plan["changes"].append(f"Adds the additional role {roles.role_name(extra)}." if extra in additional
                                   else f"Removes the additional role {roles.role_name(extra)}.")


def explain_recorded_role(plan, role, after, today):
    """The portal's zone-wide (ZL, STL) and mission-wide (AP) views use the recorded role: say why it is not the
    chosen leadership role (its assignment starts later, or ends)."""
    if role not in roles.LEADER_ROLES or plan["record"] == role:
        return
    mine = [l for l in after if l["role"] == role]
    starts = min((l["start_date"] for l in mine if l["start_date"] > today), default=None)
    ends = min((l["end_date"] for l in mine if holds(l, today) and l["end_date"]), default=None)
    if starts:
        plan["lines"].append(f"The recorded account role changes to {role} only when this page is saved again on or after "
                             f"{day(starts)}, when the {role} assignment starts.")
    elif ends:
        plan["lines"].append(f"The recorded account role is not {role} because the {role} assignment ends on {day(ends)}.")


def has_access(app_role, additional, leaders, when):
    """DA Management access, as sign_in.management_context() grants it: President recorded by hand, Data Analyst as the
    main or an additional role, or an AP assignment in force (Office gives none)."""
    return (app_role in roles.HIGH_ROLES or "DATA_ADMIN" in additional
            or any(l["role"] == "AP" and holds(l, when) for l in leaders))


def plan_access(plan, p, before, after, effective, today):
    """Lines when the account gets or loses DA Management access, today or from the effective date. before and after:
    (additional roles, leadership assignments) without and with this save. When it is the manager's OWN access that
    ends, the save needs the "I understand" tick (plan["own"])."""
    later = max(effective, today)
    now_before, now_after = has_access(p["app_role"], before[0], before[1], today), has_access(plan["record"], after[0], after[1], today)
    later_before, later_after = has_access(p["app_role"], before[0], before[1], later), has_access(plan["record"], after[0], after[1], later)
    # Whole sentences for lose and get, so the interface translation has each one in the catalog (dam.theyLose…).
    if now_before != now_after:
        plan["changes"].append("They lose DA Management access now." if now_before else "They get DA Management access now.")
    if later > today and later_before != later_after and later_after != now_after:
        plan["changes"].append(f"They lose DA Management access from {day(later)}." if later_before
                               else f"They get DA Management access from {day(later)}.")
    lose_now, lose_later = now_before and not now_after, later_before and not later_after
    if (lose_now or lose_later) and sign_in.is_me(p["profile_id"]):
        # own_from is the first day without access: today, or the effective date when only a later end of your AP
        # assignment removes it (you keep access until then, but this page cannot reopen an ending assignment, so you
        # could not simply undo it yourself).
        plan["own"], plan["own_from"] = True, today if lose_now else later
        plan["own_line"] = (f"This ends your own DA Management access{own_when(plan, today)}. Tick the box below to confirm, "
                            "or ask another administrator to make this change.")
        plan["changes"].insert(0, plan["own_line"])


def own_when(plan, today):
    """'' when saving ends your own DA Management access at once, else ' from 04 Oct 2026'."""
    return f" from {day(plan['own_from'])}" if plan["own_from"] and plan["own_from"] > today else ""


def own_tick_text(plan, today):
    """The sentence next to the "I understand" box on the account page."""
    if own_when(plan, today):
        return f"Saving ends my own DA Management access{own_when(plan, today)}. After that I cannot give it back to myself."
    return "Saving ends my own DA Management access. I cannot give it back to myself."
