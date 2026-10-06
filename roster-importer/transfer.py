"""A transfer: putting a new, complete transfer roster into the database.

Two steps, like every import in DA Management:
  1. preview(): compares the roster (from roster_file.read_roster) with the database and lists what would change:
     new zones, districts, areas and missionaries, moves, email changes, who leaves, ward and branch links, and
     leadership (DL, ZL, STL, AP). Nothing is written.
  2. apply_roster_batch(): writes all of it in one transaction, recorded as one batch in Import history, so it can
     be undone there (batches.py, import_history.py).

A roster says who serves where FROM its transfer date. Rows that are "in force on" a day started on or before it and
have not ended before it. What the roster no longer gives ends the day before the transfer date. A transfer dated
ahead leaves everyone in today's area and role until that date.
"""
from datetime import date, timedelta

import database
import batches
import roles
import sign_in
from roster_file import clean

# The saved account role (app_role) the preview suggests recording by hand, highest first. Since migration 021 the
# database's zone and mission checks follow the leadership assignment itself; the saved role is only kept in step.
ROLE_TO_RECORD = ["AP", "ZL", "STL"]
PREVIEW_LISTS = ["new_missionaries", "moves", "finished", "leadership_add", "leadership_end", "role_resets",
                 "role_records", "unit_add", "unit_remove", "email_updates"]


def in_force_on(alias):
    """SQL for "this row is in force on the day": it started on or before it and has not ended before it. Needs the
    day twice as parameters."""
    return f"{alias}.start_date<=%s and ({alias}.end_date is null or {alias}.end_date>=%s)"


def unit_key(unit):
    """Two ward or branch entries are the same unit when they have the same unit number (or, without one, name)."""
    return unit["unit_number"] or unit["name"].casefold()


def unit_text(unit):
    """'Frankfurt 1st (66230)'."""
    return unit["name"] + (f' ({unit["unit_number"]})' if unit["unit_number"] else "")


def units_by_area(rows):
    """{(zone, district, area): {"has_unit_data": bool, "units": [...]}} from the roster rows: every ward and branch
    named for an area (by anyone serving there), once each, in the order they first appear."""
    result = {}
    for r in rows:
        entry = result.setdefault((r["zone"], r["district"], r["area"]), {"has_unit_data": False, "units": []})
        if r["units"]:
            entry["has_unit_data"] = True
        known = {unit_key(u) for u in entry["units"]}
        for unit in r["units"]:
            if unit_key(unit) not in known:
                entry["units"].append(unit)
                known.add(unit_key(unit))
    return result


# ------------------------------------------------------------------------------------------ dates already recorded

def later_change_date(cur, mission_id, transfer_date):
    """The first day after the transfer date on which an assignment or leadership row of this mission starts."""
    cur.execute("""select min(x.start_date) first_date from (
          select ma.start_date from public.missionary_assignments ma
          join public.areas a on a.id=ma.area_id join public.districts d on d.id=a.district_id
          join public.zones z on z.id=d.zone_id where z.mission_id=%s and ma.start_date>%s
          union all
          select la.start_date from public.leadership_assignments la
          left join public.districts d on d.id=la.district_id
          left join public.zones z on z.id=coalesce(la.zone_id,d.zone_id)
          where coalesce(la.mission_id,z.mission_id)=%s and la.start_date>%s) x""",
                (mission_id, transfer_date, mission_id, transfer_date))
    return cur.fetchone()["first_date"]


def later_change_source(cur, mission_id, day):
    """Who recorded the rows that start on `day`: the applied transfer that added one (preferred), else the missionary
    of a row saved on an account page (an area row first). Keys: t (table), display_name, filename (or None)."""
    cur.execute("""select * from (select x.t,m.display_name,(select b.filename from public.roster_import_batches b
            join public.roster_import_changes c on c.batch_id=b.id
            where b.kind='TRANSFER' and b.status='APPLIED' and b.mission_id=%s and c.table_name=x.t
              and c.row_key->>'id'=x.id::text and c.before_row is null order by b.created_at desc limit 1) filename
        from (select 'missionary_assignments' t,ma.id,ma.missionary_id from public.missionary_assignments ma
              join public.areas a on a.id=ma.area_id join public.districts d on d.id=a.district_id
              join public.zones z on z.id=d.zone_id where z.mission_id=%s and ma.start_date=%s
              union all
              select 'leadership_assignments',la.id,la.missionary_id from public.leadership_assignments la
              left join public.districts d on d.id=la.district_id left join public.zones z on z.id=coalesce(la.zone_id,d.zone_id)
              where coalesce(la.mission_id,z.mission_id)=%s and la.start_date=%s) x
        join public.missionaries m on m.id=x.missionary_id) s
        order by s.filename is null,s.t desc,s.display_name limit 1""", (mission_id, mission_id, day, mission_id, day))
    return cur.fetchone()


def check_no_later_change(cur, mission_id, transfer_date):
    """A roster must never be put underneath a change recorded for a later day (a later transfer, or a move saved on
    an account page): raises ValueError saying which change and what to do."""
    later = later_change_date(cur, mission_id, transfer_date)
    if not later:
        return
    on, first = transfer_date.strftime("%d %b %Y"), later.strftime("%d %b %Y")
    source = later_change_source(cur, mission_id, later)
    if source["filename"]:
        raise ValueError(f"Changes from {first} are already recorded by the transfer \"{source['filename']}\". A roster dated {on} "
                         f"cannot be applied underneath them. Use {first} or a later date, or first undo that transfer in "
                         "Import history.")
    take_back = (f" If that move was a mistake, open {source['display_name']} in Account Manager and choose \"stay here\" "
                 "under Assigned area to take it back." if source["t"] == "missionary_assignments" else "")
    raise ValueError(f"A change for {source['display_name']} from {first} is already recorded (saved on the account page). "
                     f"A roster dated {on} cannot be applied underneath it. Use {first} or a later date.{take_back}")


def same_day_changes(cur, mission_id, transfer_date):
    """How many assignment and leadership rows of this mission start on the transfer date itself."""
    cur.execute("""select (select count(*) from public.missionary_assignments ma join public.areas a on a.id=ma.area_id
          join public.districts d on d.id=a.district_id join public.zones z on z.id=d.zone_id
          where z.mission_id=%s and ma.start_date=%s)
        + (select count(*) from public.leadership_assignments la left join public.districts d on d.id=la.district_id
          left join public.zones z on z.id=coalesce(la.zone_id,d.zone_id)
          where coalesce(la.mission_id,z.mission_id)=%s and la.start_date=%s) n""",
                (mission_id, transfer_date, mission_id, transfer_date))
    return cur.fetchone()["n"]


# ------------------------------------------------------------------------------------------ 1. the preview

def preview(rows, mission_id, transfer_date=None):
    """What applying these roster rows on the transfer date would change, as lists of short lines for the page.
    Raises ValueError when the roster cannot be applied at all."""
    transfer_date = transfer_date or date.today()
    with database.connect() as conn:
        with database.cursor(conn) as cur:
            cur.execute("select id,name from public.missions where id=%s", (mission_id,))
            mission = cur.fetchone()
            if not mission:
                raise ValueError(f"Mission ID {mission_id} does not exist.")
            check_no_later_change(cur, mission_id, transfer_date)
            replaced = same_day_changes(cur, mission_id, transfer_date)
            now = database_today(cur, mission_id, transfer_date)
    changes = {"mission_name": mission["name"], "count": len(rows), "new_zones": set(), "new_districts": set(),
               "new_areas": set(), **{name: [] for name in PREVIEW_LISTS}}
    for r in rows:
        add_place_and_person_changes(changes, r, now)
        add_leadership_changes(changes, r, now, mission["name"])
    add_email_changes(changes, rows, now)
    add_people_leaving(changes, rows, now)
    add_unit_changes(changes, rows, now)
    for name in ("new_zones", "new_districts", "new_areas"):
        changes[name] = sorted(changes[name])
    changes["notes"] = preview_notes(changes, replaced, transfer_date)
    return changes


def database_today(cur, mission_id, transfer_date):
    """What the database holds now, in the shapes the preview compares the roster with."""
    def fetch(query, params=()):
        cur.execute(query, params)
        return cur.fetchall()

    zones = fetch("select id,name from public.zones where mission_id=%s", (mission_id,))
    districts = fetch("""select d.id,d.name,z.name zone_name from public.districts d join public.zones z on z.id=d.zone_id
        where z.mission_id=%s""", (mission_id,))
    areas = fetch("""select a.id,a.name,d.name district_name,z.name zone_name from public.areas a
        join public.districts d on d.id=a.district_id join public.zones z on z.id=d.zone_id where z.mission_id=%s""", (mission_id,))
    missionaries = fetch("select id,missionary_number,display_name,status,email from public.missionaries")
    assignments = fetch(f"""select ma.id,ma.missionary_id,ma.area_id,m.missionary_number,m.display_name,
            a.name area_name,d.name district_name,z.name zone_name
        from public.missionary_assignments ma join public.missionaries m on m.id=ma.missionary_id
        join public.areas a on a.id=ma.area_id join public.districts d on d.id=a.district_id join public.zones z on z.id=d.zone_id
        where z.mission_id=%s and {in_force_on('ma')} order by ma.start_date,ma.id""", (mission_id, transfer_date, transfer_date))
    leaders = fetch(f"""select la.id,la.missionary_id,la.role,la.district_id,la.zone_id,la.mission_id,m.missionary_number,m.display_name
        from public.leadership_assignments la join public.missionaries m on m.id=la.missionary_id
        where {in_force_on('la')} and la.role = any(%s)""", (transfer_date, transfer_date, list(roles.LEADER_ROLES)))
    saved_roles = fetch("""select m.missionary_number,up.app_role
        from public.user_profiles up join public.missionaries m on m.id=up.missionary_id""")
    area_units = fetch("""select a.id area_id,a.name area_name,d.name district_name,z.name zone_name,
            u.id unit_id,u.name unit_name,u.unit_number,au.active,au.primary_unit
        from public.areas a join public.districts d on d.id=a.district_id join public.zones z on z.id=d.zone_id
        left join public.area_units au on au.area_id=a.id and au.active=true left join public.units u on u.id=au.unit_id
        where z.mission_id=%s""", (mission_id,))
    now = {
        "zones": {x["name"] for x in zones},
        "districts": {(x["zone_name"], x["name"]) for x in districts},
        "areas": {(x["zone_name"], x["district_name"], x["name"]) for x in areas},
        "missionary_by_number": {str(x["missionary_number"]): x for x in missionaries if x["missionary_number"] is not None},
        "assignments": assignments,
        # The latest assignment in force of each missionary (the rows are sorted by start date).
        "assignment_by_number": {str(x["missionary_number"]): x for x in assignments},
        "leaders_by_number": {},
        "saved_role_by_number": {str(x["missionary_number"]): x["app_role"] for x in saved_roles},
        "units_by_area": {},
    }
    for x in leaders:
        now["leaders_by_number"].setdefault(str(x["missionary_number"]), []).append(x)
    for x in area_units:
        if x["unit_id"]:
            key = (x["zone_name"], x["district_name"], x["area_name"])
            now["units_by_area"].setdefault(key, []).append({"name": x["unit_name"], "unit_number": x["unit_number"]})
    return now


def add_place_and_person_changes(changes, r, now):
    """New zone, district, area and missionary, and a move to another area."""
    if r["zone"] not in now["zones"]:
        changes["new_zones"].add(r["zone"])
    if (r["zone"], r["district"]) not in now["districts"]:
        changes["new_districts"].add(f'{r["zone"]} / {r["district"]}')
    if (r["zone"], r["district"], r["area"]) not in now["areas"]:
        changes["new_areas"].add(f'{r["zone"]} / {r["district"]} / {r["area"]}')
    if r["missionary_number"] not in now["missionary_by_number"]:
        changes["new_missionaries"].append(f'{r["display_name"]} ({r["missionary_number"]})')
    old = now["assignment_by_number"].get(r["missionary_number"])
    if old and (old["zone_name"], old["district_name"], old["area_name"]) != (r["zone"], r["district"], r["area"]):
        changes["moves"].append(f'{r["display_name"]}: {old["area_name"]} → {r["area"]}')


def add_leadership_changes(changes, r, now, mission_name):
    """Leadership that starts or ends, and saved account roles that go back to Missionary or that a manager should
    record by hand."""
    existing = {x["role"] for x in now["leaders_by_number"].get(r["missionary_number"], [])}
    desired = set(r["roles"])
    for role in sorted(desired - existing):
        scope = roles.LEADER_SCOPE[role]
        target = r["district"] if scope == "district" else r["zone"] if scope == "zone" else mission_name
        changes["leadership_add"].append(f'{r["display_name"]}: {role} → {target}')
    for role in sorted(existing - desired):
        changes["leadership_end"].append(f'{r["display_name"]}: {role}')
    saved = now["saved_role_by_number"].get(r["missionary_number"])  # None: no linked account
    if saved in roles.LEADER_ROLES and saved not in desired:
        changes["role_resets"].append(f'{r["display_name"]}: {saved} → Missionary')
        saved = "MISSIONARY"
    top = next((x for x in ROLE_TO_RECORD if x in desired), None)
    if top and saved in roles.LEADER_ROLES | {"MISSIONARY"} and saved != top:
        shown = "Missionary" if saved == "MISSIONARY" else saved
        changes["role_records"].append(f'{r["display_name"]}: {top} (account role: {shown})')


def add_email_changes(changes, rows, now):
    for r in rows:
        existing = now["missionary_by_number"].get(r["missionary_number"])
        old_email = clean(existing.get("email")) if existing else ""
        if r["email"] and old_email.casefold() != r["email"].casefold():
            changes["email_updates"].append(f'{r["display_name"]}: {old_email or "(blank)"} → {r["email"]}')


def add_people_leaving(changes, rows, now):
    """Everyone serving now who is not in the roster leaves (a complete roster decides about everyone)."""
    incoming = {r["missionary_number"] for r in rows}
    for a in now["assignments"]:
        number = str(a["missionary_number"])
        if number in incoming:
            continue
        changes["finished"].append(f'{a["display_name"]} ({a["missionary_number"]})')
        saved = now["saved_role_by_number"].get(number)
        if saved in roles.LEADER_ROLES:
            changes["role_resets"].append(f'{a["display_name"]}: {saved} → Missionary')


def add_unit_changes(changes, rows, now):
    """Ward and branch links of each area that the roster adds or removes (only for areas the roster names units for)."""
    for key, spec in units_by_area(rows).items():
        if not spec["has_unit_data"]:
            continue
        current = now["units_by_area"].get(key, [])
        current_keys = {unit_key(u) for u in current}
        wanted_keys = {unit_key(u) for u in spec["units"]}
        label = " / ".join(key)
        changes["unit_add"] += [f"{label}: + {unit_text(u)}" for u in spec["units"] if unit_key(u) not in current_keys]
        changes["unit_remove"] += [f"{label}: − {unit_text(u)}" for u in current if unit_key(u) not in wanted_keys]


def preview_notes(changes, replaced, transfer_date):
    """Sentences shown at the top of the preview."""
    on = transfer_date.strftime("%d %b %Y")
    notes = []
    if replaced:
        notes.append(f"A transfer dated {on} is already recorded. This roster replaces it: the assignments and leadership "
                     f"recorded for {on} are changed to match this roster, and the changes above are compared with them. "
                     "Both imports stay in Import history; to go back, undo this one first.")
    if transfer_date > date.today():
        notes.append(f"Assignments and leadership change on {on}; until then everyone keeps today's area and role. "
                     "Names, emails and ward or branch links change as soon as you apply.")
    if changes["email_updates"]:
        notes.append("A new roster email does not change anyone's sign-in by itself. After applying, select these "
                     "missionaries in Account Manager and send account setup: it moves their sign-in to the new address.")
    return notes


def own_access_loss(rows, transfer_date, user_id):
    """The first day without DA Management access for the signed-in portal user if this roster ends it, else None.
    Only access through an AP assignment can end here (President and Data Analyst are set by hand): the roster ends
    their AP assignment the day before the transfer date unless it lists them as AP again."""
    if not user_id:
        return None
    with database.connect() as conn:
        with database.cursor(conn) as cur:
            context = sign_in.management_context(cur, str(user_id))
            if not context or context["management_role"] != "AP":
                return None
            cur.execute("""select m.missionary_number from public.user_profiles up
              join public.missionaries m on m.id=up.missionary_id where up.id=%s""", (str(user_id),))
            found = cur.fetchone()
    number = str((found or {}).get("missionary_number") or "")
    if any(r["missionary_number"] == number and "AP" in r["roles"] for r in rows):
        return None
    return transfer_date


# ------------------------------------------------------------------------------------------ 2. applying it

def apply_roster_batch(rows, target_mission_id, transfer_date, filename):
    """Writes the roster in one transaction, as one TRANSFER batch in Import history (with every changed row, so it
    can be undone). Returns the batch id."""
    if target_mission_id != sign_in.current_mission_id():
        raise ValueError("The selected mission is outside your management scope.")
    conn = database.connect()
    try:
        with database.cursor(conn) as cur:
            cur.execute("select id from public.missions where id=%s for update", (target_mission_id,))
            if not cur.fetchone():
                raise ValueError("Mission not found.")
        tables = batches.TRANSFER_TABLES
        batches.lock_tables(conn, tables)
        before = batches.snapshot(conn, tables)
        batch = batches.create_batch(conn, "TRANSFER", filename, transfer_date, {"roster_rows": len(rows)})
        write_transfer(conn, rows, target_mission_id, transfer_date)
        count = batches.record_changes(conn, batch, tables, before, batches.snapshot(conn, tables))
        batches.add_to_summary(conn, batch, {"changed_rows": count})
        conn.commit()
        return batch
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def write_transfer(conn, rows, mission_id, transfer_date):
    """Writes the roster (the caller commits): places, missionaries, their areas and leadership, and who leaves."""
    incoming = {r["missionary_number"] for r in rows}
    with database.cursor(conn) as cur:
        cur.execute("select id from public.missions where id=%s for update", (mission_id,))
        if not cur.fetchone():
            raise ValueError(f"Mission ID {mission_id} does not exist.")
        check_no_later_change(cur, mission_id, transfer_date)
        area_ids = save_places(cur, mission_id, rows)
        covered = []  # everyone this roster decides about: the listed missionaries and those it releases
        for r in rows:
            zone_id, district_id, area_id = area_ids[(r["zone"], r["district"], r["area"])]
            person_id = save_missionary(cur, r)
            covered.append(person_id)
            save_area_assignment(cur, person_id, area_id, r, mission_id, transfer_date)
            save_leadership(cur, person_id, r["roles"], (district_id, zone_id, mission_id), transfer_date)
        covered += release_people_not_listed(cur, incoming, mission_id, transfer_date)
        release_people_whose_date_passed(cur, incoming, mission_id)
        reset_old_leader_roles(cur, covered, transfer_date)
        update_active_areas(cur, mission_id)


def save_places(cur, mission_id, rows):
    """Makes sure every zone, district and area of the roster exists and is active, and links each area to the wards
    and branches the roster names. Returns {(zone, district, area): (zone_id, district_id, area_id)}."""
    area_ids = {}
    for key, spec in units_by_area(rows).items():
        zone, district, area = key
        zone_id = find_or_add(cur, "zones", "mission_id", mission_id, zone)
        district_id = find_or_add(cur, "districts", "zone_id", zone_id, district)
        area_id = find_or_add(cur, "areas", "district_id", district_id, area)
        area_ids[key] = (zone_id, district_id, area_id)
        if spec["has_unit_data"]:
            link_area_units(cur, area_id, spec["units"])
    return area_ids


def find_or_add(cur, table, parent_column, parent_id, name):
    """The id of the zone, district or area with this name under its parent (made active again), or a new one."""
    assert table in {"zones", "districts", "areas"} and parent_column in {"mission_id", "zone_id", "district_id"}
    cur.execute(f"select id from public.{table} where {parent_column}=%s and name=%s", (parent_id, name))
    found = cur.fetchone()
    if found:
        cur.execute(f"update public.{table} set active=true where id=%s", (found["id"],))
        return found["id"]
    cur.execute(f"insert into public.{table}({parent_column},name,active) values(%s,%s,true) returning id", (parent_id, name))
    return cur.fetchone()["id"]


def save_unit(cur, unit):
    """The id of this ward or branch (found by unit number, else by name), brought up to date, or a new one."""
    number, name, found = unit.get("unit_number"), unit["name"], None
    if number:
        cur.execute("select id,name from public.units where unit_number=%s", (number,))
        found = cur.fetchone()
    if not found:
        cur.execute("select id,name from public.units where lower(name)=lower(%s) order by active desc,id limit 1", (name,))
        found = cur.fetchone()
    if found:
        cur.execute("update public.units set name=%s,unit_number=coalesce(%s,unit_number),active=true where id=%s", (name, number, found["id"]))
        return found["id"]
    cur.execute("insert into public.units(stake_id,name,unit_type,active,unit_number) values(null,%s,null,true,%s) returning id", (name, number))
    return cur.fetchone()["id"]


def link_area_units(cur, area_id, units):
    """The area's active ward and branch links become exactly these units (the first is the main unit); other links
    are turned off, never deleted."""
    if not units:
        return
    unit_ids = [save_unit(cur, unit) for unit in units]
    for position, unit_id in enumerate(unit_ids):
        cur.execute("select id from public.area_units where area_id=%s and unit_id=%s order by id limit 1", (area_id, unit_id))
        link = cur.fetchone()
        if link:
            cur.execute("update public.area_units set active=true,primary_unit=%s where id=%s", (position == 0, link["id"]))
        else:
            cur.execute("insert into public.area_units(area_id,unit_id,primary_unit,active) values(%s,%s,%s,true)", (area_id, unit_id, position == 0))
    cur.execute("""
        update public.area_units
        set active=false,primary_unit=false
        where area_id=%s and active=true and not (unit_id = any(%s))
    """, (area_id, unit_ids))
    cur.execute("update public.areas set unit_id=%s where id=%s", (unit_ids[0], area_id))


def save_missionary(cur, r):
    """The missionary's id (found by missionary number), with name, type, dates and email brought up to date."""
    cur.execute("select id from public.missionaries where missionary_number=%s", (r["missionary_number"],))
    found = cur.fetchone()
    if found:
        cur.execute("""
            update public.missionaries
            set first_name=%s,last_name=%s,display_name=%s,missionary_type=%s,status='Active',
                arrival_date=%s,release_date=%s,email=%s,updated_at=now()
            where id=%s
        """, (r["first_name"], r["last_name"], r["display_name"], r["missionary_type"],
              r["arrival_date"], r["release_date"], r["email"], found["id"]))
        return found["id"]
    cur.execute("""
        insert into public.missionaries
          (missionary_number,first_name,last_name,display_name,missionary_type,status,arrival_date,release_date,email)
        values(%s,%s,%s,%s,%s,'Active',%s,%s,%s) returning id
    """, (r["missionary_number"], r["first_name"], r["last_name"], r["display_name"],
          r["missionary_type"], r["arrival_date"], r["release_date"], r["email"]))
    return cur.fetchone()["id"]


def end_or_remove(cur, table, row, transfer_date):
    """The roster no longer gives this row: it ends the day before the transfer date. A row that starts on the
    transfer date itself never took effect (an earlier import for the same date added it), so it is removed; the
    batch audit keeps it, and Undo restores it."""
    assert table in {"missionary_assignments", "leadership_assignments"}
    if row["start_date"] >= transfer_date:
        cur.execute(f"delete from public.{table} where id=%s", (row["id"],))
    else:
        cur.execute(f"update public.{table} set end_date=%s where id=%s", (transfer_date - timedelta(days=1), row["id"]))


def reopen(cur, table, conditions, params, transfer_date):
    """A row that an earlier import for the same date ended on the day before, and that this roster keeps, is opened
    again instead of adding a second row from the transfer date. Returns the re-opened row's id, or None."""
    assert table in {"missionary_assignments", "leadership_assignments"}
    cur.execute(f"""update public.{table} set end_date=null where id=(
          select id from public.{table} where {conditions} and end_date=%s order by start_date desc,id desc limit 1)
        returning id""", (*params, transfer_date - timedelta(days=1)))
    found = cur.fetchone()
    return found["id"] if found else None


def save_area_assignment(cur, person_id, area_id, r, mission_id, transfer_date):
    """The missionary serves in this area from the transfer date: other areas end, the same area keeps its row (with
    the roster's position), else a new row starts."""
    cur.execute(f"""
        select ma.id,ma.area_id,ma.start_date
        from public.missionary_assignments ma
        join public.areas a on a.id=ma.area_id
        join public.districts d on d.id=a.district_id
        join public.zones z on z.id=d.zone_id
        where ma.missionary_id=%s and {in_force_on('ma')} and z.mission_id=%s
    """, (person_id, transfer_date, transfer_date, mission_id))
    in_force = cur.fetchall()
    same = [a for a in in_force if a["area_id"] == area_id]
    for other in (a for a in in_force if a["area_id"] != area_id):
        end_or_remove(cur, "missionary_assignments", other, transfer_date)
    if not same:  # a correction for the same date: re-open the row the earlier import ended
        reopened = reopen(cur, "missionary_assignments", "missionary_id=%s and area_id=%s", (person_id, area_id), transfer_date)
        same = [{"id": reopened}] if reopened else []
    if same:
        # The same assignment: the roster data goes onto the existing row, never a second row.
        cur.execute("""
            update public.missionary_assignments
            set roster_position=%s,roster_position_abbr=%s,special_assignment=%s
            where id=%s
        """, (r["position"], r["position_abbr"], r["special_assignment"], same[0]["id"]))
    else:
        cur.execute("""
            insert into public.missionary_assignments
              (missionary_id,area_id,start_date,roster_position,roster_position_abbr,special_assignment)
            values(%s,%s,%s,%s,%s,%s)
        """, (person_id, area_id, transfer_date, r["position"], r["position_abbr"], r["special_assignment"]))


def save_leadership(cur, person_id, wanted_roles, place_ids, transfer_date):
    """The missionary's DL/ZL/STL/AP rows become the roster's roles for their new district, zone or the mission:
    rows it no longer gives end, missing ones start (or an ended one is re-opened). place_ids: (district, zone,
    mission)."""
    leaders_sql = f"""
        select id,role,district_id,zone_id,mission_id,start_date
        from public.leadership_assignments la
        where missionary_id=%s and {in_force_on('la')} and role = any(%s)
    """
    params = (person_id, transfer_date, transfer_date, list(roles.LEADER_ROLES))
    wanted = set(wanted_roles)
    cur.execute(leaders_sql, params)
    for leader in cur.fetchall():
        if leader["role"] not in wanted or not roles.leads_the_same(leader, leader["role"], place_ids):
            end_or_remove(cur, "leadership_assignments", leader, transfer_date)
    cur.execute(leaders_sql, params)
    remaining = cur.fetchall()
    for role in sorted(wanted):
        if any(x["role"] == role and roles.leads_the_same(x, role, place_ids) for x in remaining):
            continue
        start_leadership(cur, person_id, role, place_ids, transfer_date)


def start_leadership(cur, person_id, role, place_ids, transfer_date):
    """A new DL/ZL/STL/AP row from the transfer date (or the same row, ended by an earlier import for this date, again)."""
    district_id, zone_id, mission_id = place_ids
    scope = roles.LEADER_SCOPE[role]
    scope_ids = (district_id if scope == "district" else None, zone_id if scope == "zone" else None,
                 mission_id if scope == "mission" else None)
    if reopen(cur, "leadership_assignments", "missionary_id=%s and role=%s and district_id is not distinct from %s "
              "and zone_id is not distinct from %s and mission_id is not distinct from %s",
              (person_id, role, *scope_ids), transfer_date):
        return
    cur.execute("""
        insert into public.leadership_assignments
          (missionary_id,role,district_id,zone_id,mission_id,start_date)
        values(%s,%s,%s,%s,%s,%s)
    """, (person_id, role, *scope_ids, transfer_date))


def release_people_not_listed(cur, incoming, mission_id, transfer_date):
    """Everyone serving in the mission on the transfer date who is not in the roster: their area and leadership rows
    end, and they are marked Released (a release dated ahead waits until its date). Returns their ids."""
    cur.execute(f"""
        select distinct m.id,m.missionary_number
        from public.missionaries m
        join public.missionary_assignments ma on ma.missionary_id=m.id and {in_force_on('ma')}
        join public.areas a on a.id=ma.area_id
        join public.districts d on d.id=a.district_id
        join public.zones z on z.id=d.zone_id
        where z.mission_id=%s
    """, (transfer_date, transfer_date, mission_id))
    released = []
    for person in cur.fetchall():
        if str(person["missionary_number"]) in incoming:
            continue
        cur.execute(f"""
            select ma.id,ma.start_date from public.missionary_assignments ma
            join public.areas a on a.id=ma.area_id join public.districts d on d.id=a.district_id
            join public.zones z on z.id=d.zone_id
            where ma.missionary_id=%s and {in_force_on('ma')} and z.mission_id=%s
        """, (person["id"], transfer_date, transfer_date, mission_id))
        for assignment in cur.fetchall():
            end_or_remove(cur, "missionary_assignments", assignment, transfer_date)
        cur.execute(f"select id,start_date from public.leadership_assignments la where missionary_id=%s and {in_force_on('la')}",
                    (person["id"], transfer_date, transfer_date))
        for leader in cur.fetchall():
            end_or_remove(cur, "leadership_assignments", leader, transfer_date)
        if transfer_date <= date.today():  # a release dated ahead keeps them Active until it happens (see below)
            cur.execute("update public.missionaries set status='Released',updated_at=now() where id=%s", (person["id"],))
        released.append(person["id"])
    return released


def release_people_whose_date_passed(cur, incoming, mission_id):
    """Released by an earlier transfer that was dated ahead: now that its date has passed, mark them Released."""
    cur.execute("""
        update public.missionaries m set status='Released',updated_at=now()
        where m.status='Active' and m.missionary_number <> all(%s)
          and exists (select 1 from public.missionary_assignments ma join public.areas a on a.id=ma.area_id
                      join public.districts d on d.id=a.district_id join public.zones z on z.id=d.zone_id
                      where ma.missionary_id=m.id and z.mission_id=%s)
          and not exists (select 1 from public.missionary_assignments ma
                          where ma.missionary_id=m.id and (ma.end_date is null or ma.end_date>=current_date))
    """, (sorted(incoming), mission_id))


def reset_old_leader_roles(cur, covered, transfer_date):
    """A saved account role DL/ZL/STL/AP that this roster no longer gives (a former AP, a released leader) goes back
    to MISSIONARY, so it grants nothing later. The batch audit records it, so Undo restores it. PRESIDENT, DATA_ADMIN
    and OFFICE are set by hand and never changed here. It happens now, not on a later transfer date, because nothing
    would reset it on that date; the preview warns when the date is still ahead. (Until then the assignment itself
    still gives the access, as the database's checks follow it.)"""
    cur.execute("""
        update public.user_profiles up set app_role='MISSIONARY',updated_at=now()
        where up.missionary_id = any(%s) and up.app_role = any(%s)
          and not exists (select 1 from public.leadership_assignments la
                          where la.missionary_id=up.missionary_id and la.role=up.app_role
                            and (la.end_date is null or la.end_date>=%s))
    """, (covered, list(roles.LEADER_ROLES), transfer_date))


def update_active_areas(cur, mission_id):
    """A complete roster decides which areas are current. Old areas stay for history but leave the lists of the
    portal, planning and dashboards. An area stays active while someone serves there today or later, so a transfer
    dated ahead does not hide an area its missionaries still serve in."""
    cur.execute("""update public.areas a set active=exists(
          select 1 from public.missionary_assignments ma
          join public.missionaries m on m.id=ma.missionary_id
          where ma.area_id=a.id and (ma.end_date is null or ma.end_date>=current_date) and m.status='Active')
        from public.districts d,public.zones z
        where d.id=a.district_id and z.id=d.zone_id and z.mission_id=%s""", (mission_id,))
