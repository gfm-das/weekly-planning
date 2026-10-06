"""People in uploads: saving them (the matching is people_match.py).

write_people() takes the people people_match.resolve() worked out and, in the caller's transaction:
  - makes the new member or friend (or, for a person that is already stored, only fills the blanks: nothing a
    missionary typed is ever overwritten);
  - gives them their area (a new member is placed in the area of their newest appearance);
  - puts them on the weekly plan of every week they appear in, as if typed in by hand (weekly_new_members,
    weekly_baptismal_date_friends); high-potential friends become a name on the plan;
  - links a new member to the friend with a baptismal date they used to be, and ends that friend's tracking.
Then fill_current_week() makes the plans of the current week (database function fill_current_week_plans, migration 039):
people who are still relevant are loaded into each open area's plan.

Relevant means (the rules of the owner): a new member until one year after the baptism; a friend with a baptismal date
who was on last week's plan and whose date has not passed; a high-potential friend who was on last week's plan.
"""
from datetime import date, timedelta

from psycopg2 import sql

import people_match as match

PROFILE_FIELDS = ("baptismal_date_extended", "baptism_date", "confirmation_date", "finding_source", "date_of_birth",
                  "age_range", "gender", "marital_status", "child_dependents", "living_situation", "native_language",
                  "second_language", "mission_language_competency", "country_of_origin", "conversion_success_notes")


def insert_row(cur, table, values):
    """Inserts one row and returns its id."""
    cur.execute(sql.SQL("insert into public.{} ({}) values ({}) returning id").format(
        sql.Identifier(table), sql.SQL(",").join(map(sql.Identifier, values)),
        sql.SQL(",").join([sql.Placeholder()] * len(values))), list(values.values()))
    return cur.fetchone()["id"]


def fill_blanks(cur, table, row_id, values):
    """Sets the columns of a row that are still empty; a column that has a value is left as it is."""
    values = {k: v for k, v in values.items() if v is not None}
    if not values:
        return
    sets = sql.SQL(",").join(sql.SQL("{c}=coalesce({t}.{c},%s)").format(c=sql.Identifier(k), t=sql.Identifier(table)) for k in values)
    cur.execute(sql.SQL("update public.{t} set {s} where id=%s").format(t=sql.Identifier(table), s=sets), list(values.values()) + [row_id])


def newest_values(appearances, key):
    """For each field of appearance[key]: the newest non-empty value over all appearances."""
    merged = {}
    for appearance in appearances:  # oldest first, so later ones win
        for field, value in (appearance.get(key) or {}).items():
            if value is not None and value != "":
                merged[field] = value
    return merged


def write_people(cur, groups, report_ids, today=None):
    """Saves the people of an upload. report_ids: {(area_id, sunday, unit_id): weekly report id} of the reports the
    caller wrote (appearances carry their own 'target'). Returns counts for the batch summary."""
    today = today or date.today()
    counts = {"new_members_added": 0, "new_members_joined": 0, "friends_added": 0, "friends_joined": 0,
              "high_potential_rows": 0, "weekly_rows": 0}
    done = {}  # group index -> person id, so a new member can find the friend group they came from
    ordered = sorted(range(len(groups)), key=lambda i: groups[i]["kind"] != match.FRIEND)  # friends first
    for index in ordered:
        group = groups[index]
        if group["kind"] == match.FRIEND:
            done[index] = write_friend(cur, group, report_ids, counts)
    for index in ordered:
        group = groups[index]
        if group["kind"] == match.NEW_MEMBER:
            done[index] = write_new_member(cur, group, report_ids, counts, today, groups, done)
    return counts


def stake_of(cur, unit_id):
    if not unit_id:
        return None
    cur.execute("select stake_id from public.units where id=%s", (unit_id,))
    row = cur.fetchone()
    return row["stake_id"] if row else None


def first_day(group, fallback):
    seen = [a["sunday"] for a in group["appearances"] if a.get("sunday")]
    return min(seen) if seen else fallback


def write_new_member(cur, group, report_ids, counts, today, groups, done):
    profile = newest_values(group["appearances"], "profile")
    if group["baptism_date"]:
        profile["baptism_date"] = group["baptism_date"]
    if group["stored_id"]:
        person_id = group["stored_id"]
        fill_blanks(cur, "new_members", person_id, profile)
        counts["new_members_joined"] += 1
    else:
        baptized = profile.get("baptism_date")
        ended = bool(baptized and baptized <= today - timedelta(days=365))
        values = {"area_id": group["area_id"], "unit_id": group["unit_id"], "stake_id": stake_of(cur, group["unit_id"]),
                  "first_name": group["first"], "last_name": group["last"],
                  "display_name": " ".join(x for x in (group["first"], group["last"]) if x),
                  **{f: profile.get(f) for f in PROFILE_FIELDS}}
        values.update(follow_up_status="current", active=True)
        if ended:
            values.update(follow_up_status="ended", follow_up_end_reason="one_year", active=False, inactive_reason="one_year")
        person_id = insert_row_ended(cur, values, ended)
        start = baptized or first_day(group, today)
        cur.execute("""insert into public.new_member_area_assignments(new_member_id,area_id,unit_id,start_date,end_date,transfer_reason)
          values(%s,%s,%s,%s,%s,%s)""", (person_id, group["area_id"], group["unit_id"], min(start, today),
                                         today if ended else None, "one_year" if ended else None))
        counts["new_members_added"] += 1
    link_former_friend(cur, group, person_id, done, groups, today)
    for appearance in group["appearances"]:
        report = report_ids.get(appearance.get("target"))
        if report and appearance.get("weekly") is not None:
            weekly_row(cur, "weekly_new_members", "new_member_id", report, person_id, appearance["weekly"])
            counts["weekly_rows"] += 1
    return person_id


def insert_row_ended(cur, values, ended):
    """A new member row. The table's checks want a time on an ended follow-up (and on a not active person)."""
    if ended:
        values = {**values, "follow_up_ended_at": sql.SQL("now()"), "inactive_at": sql.SQL("now()")}
    columns = list(values)
    placeholders = [v if isinstance(v, sql.Composable) else sql.Placeholder() for v in values.values()]
    cur.execute(sql.SQL("insert into public.new_members ({}) values ({}) returning id").format(
        sql.SQL(",").join(map(sql.Identifier, columns)), sql.SQL(",").join(placeholders)),
        [v for v in values.values() if not isinstance(v, sql.Composable)])
    return cur.fetchone()["id"]


def link_former_friend(cur, group, person_id, done, groups, today):
    """A new member who was a friend with a baptismal date: link the records and end the friend's tracking."""
    source = group.get("bapt_from")
    friend_id = None
    if isinstance(source, dict):
        friend_id = next((done[i] for i, g in enumerate(groups) if g is source and i in done), None)
    elif source:
        friend_id = source
    if not friend_id:
        return
    cur.execute("select baptismal_date_person_id from public.new_members where id=%s", (person_id,))
    if cur.fetchone()["baptismal_date_person_id"]:
        return
    cur.execute("select 1 from public.new_members where baptismal_date_person_id=%s", (friend_id,))
    if cur.fetchone():
        return  # that friend already became another new member
    cur.execute("update public.new_members set baptismal_date_person_id=%s where id=%s", (friend_id, person_id))
    cur.execute("""update public.baptismal_date_person_area_assignments set end_date=greatest(start_date,%s),transfer_reason='baptized'
      where baptismal_date_person_id=%s and end_date is null""", (today, friend_id))
    cur.execute("""update public.baptismal_date_people set tracking_status='ended',tracking_ended_at=now(),
      tracking_end_reason='baptized',updated_at=now() where id=%s and tracking_status='current'""", (friend_id,))


def write_friend(cur, group, report_ids, counts):
    finding = newest_values(group["appearances"], "profile").get("finding_source")
    if group["stored_id"]:
        person_id = group["stored_id"]
        fill_blanks(cur, "baptismal_date_people", person_id, {"finding_source": finding})
        counts["friends_joined"] += 1
    else:
        person_id = insert_row(cur, "baptismal_date_people", {
            "first_name": group["first"] or group["last"] or "", "last_name": group["last"] if group["first"] else None,
            "display_name": " ".join(x for x in (group["first"], group["last"]) if x), "finding_source": finding})
        cur.execute("""insert into public.baptismal_date_person_area_assignments(baptismal_date_person_id,area_id,unit_id,start_date)
          values(%s,%s,%s,%s)""", (person_id, group["area_id"], group["unit_id"], min(first_day(group, date.today()), date.today())))
        counts["friends_added"] += 1
    for appearance in group["appearances"]:
        report = report_ids.get(appearance.get("target"))
        if report and appearance.get("weekly") is not None:
            weekly_row(cur, "weekly_baptismal_date_friends", "baptismal_date_person_id", report, person_id, appearance["weekly"])
            counts["weekly_rows"] += 1
    return person_id


def weekly_row(cur, table, column, report_id, person_id, values):
    """The person on one plan. A row that is already there keeps what it has; only its empty answers are filled."""
    columns = ["weekly_area_report_id", column, "display_order"] + list(values)
    order = sql.SQL("(select coalesce(max(display_order),0)+1 from public.{} where weekly_area_report_id=%s)").format(sql.Identifier(table))
    placeholders = [sql.Placeholder(), sql.Placeholder(), order] + [sql.Placeholder()] * len(values)
    updates = sql.SQL(",").join(sql.SQL("{c}=coalesce({t}.{c},excluded.{c})").format(c=sql.Identifier(k), t=sql.Identifier(table)) for k in values) \
        if values else sql.SQL("display_order={}.display_order").format(sql.Identifier(table))
    cur.execute(sql.SQL("""insert into public.{t} ({cols}) values ({vals})
      on conflict (weekly_area_report_id,{col}) where {col} is not null do update set {upd}""").format(
        t=sql.Identifier(table), cols=sql.SQL(",").join(map(sql.Identifier, columns)), vals=sql.SQL(",").join(placeholders),
        col=sql.Identifier(column), upd=updates), [report_id, person_id, report_id] + list(values.values()))


def write_high_potentials(cur, items, report_ids, counts=None):
    """High-potential friends: a name on each plan they appear on (once per plan). items: dicts with target, name,
    at_church_this_sunday, order."""
    added = 0
    for item in items:
        report = report_ids.get(item.get("target"))
        if not report or not item.get("name"):
            continue
        cur.execute("""select 1 from public.weekly_high_potential_friends where weekly_area_report_id=%s
          and lower(btrim(name))=lower(btrim(%s))""", (report, item["name"]))
        if cur.fetchone():
            continue
        cur.execute("""insert into public.weekly_high_potential_friends(weekly_area_report_id,display_order,name,at_church_this_sunday)
          values(%s,(select coalesce(max(display_order),0)+1 from public.weekly_high_potential_friends where weekly_area_report_id=%s),%s,%s)""",
                    (report, report, item["name"], item.get("at_church_this_sunday")))
        added += 1
    if counts is not None:
        counts["high_potential_rows"] = counts.get("high_potential_rows", 0) + added
    return added


def fill_current_week(cur):
    """Loads the relevant people into the plans of the current week. Returns how many plans were filled."""
    cur.execute("select public.fill_current_week_plans() n")
    return cur.fetchone()["n"]
