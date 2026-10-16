"""Delete retired: a Data Analyst or other manager deletes a closed zone, district or area, or a retired Weekly Planning
question, safely. The pages are in retire_pages.py; the backup step is backups.py; every text is in retire_text.py.

The flow of a delete (the owner's, round 13):
  1. IMPACT PREVIEW. What is attached to the item, counted from the database's own foreign keys (so a table added by a later
     migration shows up without a code change): plans, people, Call-ins, uploaded numbers and history. A check runs the whole
     delete inside a transaction that is rolled back, so the page can say "this works" or why it does not.
  2. MERGE (optional). What is attached can be moved onto the item that replaced it (a renamed area, a question that took
     over). Where both have something for the same week or the same plan, nothing is moved and the check says so.
  3. BACKUP. A pg_dump is made and read back before anything changes; its file name is written into the batch. If the
     backup fails, nothing is deleted.
  4. TYPED CONFIRMATION. The manager types the item's name (a place) or key (a question).
  5. DELETE as ONE batch in Import history (kind RETIRE) with every row it moved or removed, as it was before and after.
     Undo puts them back (undo.py), or refuses when a row was changed again later.

Safety rules (they hold in the database as well as on the page):
  - Only managers signed in through the portal (roles.may_retire). Hiding a button is not security: every route checks.
  - A place must be CLOSED, and an area must have nobody serving in it. A question must be RETIRED and not locked
    (protected); the database refuses everything else (migration 048).
  - Attached plans, people, Call-ins and history are never deleted by this page: they must be MOVED onto a successor. (For a
    question, the saved answers may also be deleted on purpose: they are plain rows that Undo puts back.) A place's own
    settings (Geo data, the wards it serves, remembered name matches) are removed with it or, with a successor,
    moved unless the successor has its own.
  - Nothing is deleted before the backup exists and before the typed confirmation matches.
"""
import psycopg2
import psycopg2.errors
from psycopg2 import sql

import backups
import batches
import database
import planning_questions as pq
import roles
import sign_in
from data_files import clean
from retire_text import plain

LEVELS = {"zone": "zones", "district": "districts", "area": "areas"}
PLACE_TABLES = ["zones", "districts", "areas"]  # in this order: parents first, so Undo puts a parent back before its children
# What the tables hold, in words a manager knows (the preview groups the counts by it).
CATEGORY = {
    "weekly_area_reports": "plans",
    "missionary_assignments": "people", "leadership_assignments": "people", "companionships": "people",
    "new_members": "people", "new_member_area_assignments": "people", "baptismal_date_person_area_assignments": "people",
    "call_in_area_updates": "callins", "call_in_districts": "callins", "call_in_zones": "callins",
    "baptism_history_weeks": "history", "finding_people": "history",
    "zone_history_weeks": "history", "import_weekly_planning_area_map": "history",
    "archetype_notes": "history",
    "districts": "places", "areas": "places",
    "area_geo_data": "settings", "area_units": "settings", "data_name_matches": "settings",
    "zone_geo_data": "settings", "district_geo_data": "settings",
}
# The place's own settings: removed together with it, or (with a successor) moved unless the successor has its own.
REMOVABLE = {"area_geo_data", "area_units", "data_name_matches", "zone_geo_data", "district_geo_data"}
QUESTION_TABLES = ["planning_questions", "planning_question_options", "planning_question_grid_rows",
                   "planning_question_visibility_rules", "weekly_planning_answers"]
CHOICE_TYPES = {"SELECT", "RADIO", "CHECKBOX", "GRID"}


class Refusal(ValueError):
    """A rule of this page said no. Its text is plain words for the manager; nothing was changed."""


def say(key, **values):
    return Refusal(plain(key, **values))


def label_of(table):
    """The category word of a table for messages ('plans', 'people', ...); the table's own name when it has none."""
    return plain(f"retire.cat.{CATEGORY[table]}") if table in CATEGORY else table


# ------------------------------------------------------------------------------------------ what points at a place

def references(cur, table, schema="public"):
    """Every foreign key that points at this table: [{schema, table, column, rule, width}]. rule: c cascade, n set null,
    r restrict, a no action. width: how many columns the key has (this page handles one)."""
    cur.execute("""select n.nspname schema_name,c.relname table_name,a.attname column_name,k.confdeltype delete_rule,
        array_length(k.conkey,1) width
      from pg_constraint k join pg_class c on c.oid=k.conrelid join pg_namespace n on n.oid=c.relnamespace
      join pg_attribute a on a.attrelid=k.conrelid and a.attnum=k.conkey[1]
      where k.contype='f' and k.confrelid=%s::regclass order by n.nspname,c.relname,a.attname""", (f"{schema}.{table}",))
    return [{"schema": r["schema_name"], "table": r["table_name"], "column": r["column_name"], "rule": r["delete_rule"],
             "width": r["width"]} for r in cur.fetchall()]


def primary_key(cur, schema, table):
    """The primary key columns of a table, in order (empty when it has none)."""
    cur.execute("""select a.attname name from pg_index i join pg_attribute a on a.attrelid=i.indrelid and a.attnum=any(i.indkey)
      where i.indrelid=%s::regclass and i.indisprimary order by array_position(i.indkey::int2[],a.attnum)""",
                (f"{schema}.{table}",))
    return [r["name"] for r in cur.fetchall()]


def qualified(schema, table):
    return sql.SQL("{}.{}").format(sql.Identifier(schema), sql.Identifier(table))


def count_rows(cur, ref, value):
    cur.execute(sql.SQL("select count(*) n from {} where {}=%s").format(qualified(ref["schema"], ref["table"]),
                                                                       sql.Identifier(ref["column"])), (value,))
    return cur.fetchone()["n"]


def attached(cur, level, place_id):
    """What points at the place: [{..reference.., count, category, removable, supported}] for every key that has rows.
    supported is False for what this page cannot record for Undo (another schema, a key of several columns, no primary
    key): such rows stop the delete, they are never touched."""
    found = []
    for ref in references(cur, LEVELS[level]):
        rows = count_rows(cur, ref, place_id)
        if not rows:
            continue
        pk = primary_key(cur, ref["schema"], ref["table"]) if ref["schema"] == "public" else []
        found.append({**ref, "count": rows, "category": CATEGORY.get(ref["table"], "other"),
                      "removable": ref["table"] in REMOVABLE and ref["schema"] == "public",
                      "supported": ref["schema"] == "public" and ref["width"] == 1 and bool(pk), "pk": pk})
    return found


# ------------------------------------------------------------------------------------------ places

def place_row(cur, level, place_id, lock=False):
    """{id, name, active, mission_id, parent_id, parent_name} of a zone, district or area; None when it is not there."""
    shape = {
        "zone": "select z.id,z.name,z.active,z.mission_id,null::bigint parent_id,null::text parent_name from public.zones z where z.id=%s",
        "district": """select d.id,d.name,d.active,z.mission_id,z.id parent_id,z.name parent_name from public.districts d
          join public.zones z on z.id=d.zone_id where d.id=%s""",
        "area": """select a.id,a.name,a.active,z.mission_id,d.id parent_id,d.name parent_name from public.areas a
          join public.districts d on d.id=a.district_id join public.zones z on z.id=d.zone_id where a.id=%s"""}[level]
    cur.execute(shape + (" for update of " + {"zone": "z", "district": "d", "area": "a"}[level] if lock else ""), (place_id,))
    return cur.fetchone()


def serving_now(cur, area_id):
    """How many active missionaries have this area as their area today."""
    cur.execute("""select count(*) n from public.missionary_assignments ma join public.missionaries m on m.id=ma.missionary_id
      where ma.area_id=%s and (ma.end_date is null or ma.end_date>=current_date) and m.status='Active'""", (area_id,))
    return cur.fetchone()["n"]


def closed_places(cur, mission_id):
    """The closed zones, districts and areas of the mission: [(level, id, name, where it is)], areas last."""
    cur.execute("""select 'zone' level,z.id,z.name,'' parent from public.zones z where z.mission_id=%s and not z.active
      union all select 'district',d.id,d.name,z.name from public.districts d join public.zones z on z.id=d.zone_id
        where z.mission_id=%s and not d.active
      union all select 'area',a.id,a.name,z.name||' / '||d.name from public.areas a join public.districts d on d.id=a.district_id
        join public.zones z on z.id=d.zone_id where z.mission_id=%s and not a.active
      order by 1 desc,4,3""", (mission_id, mission_id, mission_id))
    rows = cur.fetchall()
    order = {"zone": 0, "district": 1, "area": 2}
    return sorted(rows, key=lambda r: (order[r["level"]], r["parent"].casefold(), r["name"].casefold()))


def successors(cur, level, place):
    """Open places of the same kind in the same mission that what is attached could move to: [(id, label)]."""
    shape = {
        "zone": "select z.id,z.name label from public.zones z where z.mission_id=%s and z.active and z.id<>%s order by z.name",
        "district": """select d.id,z.name||' / '||d.name label from public.districts d join public.zones z on z.id=d.zone_id
          where z.mission_id=%s and d.active and z.active and d.id<>%s order by z.name,d.name""",
        "area": """select a.id,z.name||' / '||d.name||' / '||a.name label from public.areas a join public.districts d on d.id=a.district_id
          join public.zones z on z.id=d.zone_id where z.mission_id=%s and a.active and d.active and z.active and a.id<>%s
          order by z.name,d.name,a.name"""}[level]
    cur.execute(shape, (place["mission_id"], place["id"]))
    return [(r["id"], r["label"]) for r in cur.fetchall()]


def derived_counts(cur, level, place_id):
    """For an area: how many saved answers its plans hold (shown in the preview; they move or go with the plans)."""
    if level != "area":
        return {}
    cur.execute("""select count(*) n from public.weekly_planning_answers a join public.weekly_area_reports r
      on r.id=a.weekly_area_report_id where r.area_id=%s""", (place_id,))
    return {"answers": cur.fetchone()["n"]}


def check_place(cur, level, place_id, successor_id, mission_id, lock=False):
    """The rules before a delete. Returns the place, what is attached and the successor (or None); raises Refusal."""
    place = place_row(cur, level, place_id, lock)
    if not place or place["mission_id"] != mission_id:
        raise say("retire.error.notFound")
    if place["active"]:
        raise say("retire.place.open")
    if level == "area":
        serving = serving_now(cur, place_id)
        if serving:
            raise say("retire.place.serving", count=serving)
    found = attached(cur, level, place_id)
    unsupported = [x for x in found if not x["supported"]]
    if unsupported:
        raise say("retire.error.unsupported", what=", ".join(sorted({f"{x['schema']}.{x['table']}" for x in unsupported})))
    successor = None
    if successor_id:
        successor = place_row(cur, level, successor_id, lock)
        if not successor or successor["mission_id"] != mission_id or not successor["active"] or successor["id"] == place["id"]:
            raise say("retire.error.badSuccessor")
    elif any(not x["removable"] for x in found):
        raise say("retire.place.mustMove")
    return place, found, successor


# ------------------------------------------------------------------------------------------ the rows Undo needs

def fetch_rows(cur, schema, table, where, params):
    cur.execute(sql.SQL("select to_jsonb(t) row from {} t where {}").format(qualified(schema, table), where), params)
    return [r["row"] for r in cur.fetchall()]


def key_of(pk, row):
    return batches.key_string({column: row[column] for column in pk})


def snapshot_before(cur, level, place_id, found):
    """{table: {key: row}} of the place and of every row that points at it, in the order Undo restores them (places first).
    Also returns the primary key of every table it saw."""
    rows, keys = {name: {} for name in PLACE_TABLES}, {name: ["id"] for name in PLACE_TABLES}
    for row in fetch_rows(cur, "public", LEVELS[level], sql.SQL("id=%s"), (place_id,)):
        rows[LEVELS[level]][key_of(["id"], row)] = row
    for x in found:
        keys[x["table"]] = x["pk"]
        rows.setdefault(x["table"], {})
        for row in fetch_rows(cur, "public", x["table"], sql.SQL("{}=%s").format(sql.Identifier(x["column"])), (place_id,)):
            rows[x["table"]][key_of(x["pk"], row)] = row
    return rows, keys


def snapshot_after(cur, before, keys):
    """The same rows as they are now ({} where a row is gone)."""
    after = {table: {} for table in before}
    for table, wanted in before.items():
        pk = keys[table]
        for key, row in wanted.items():
            where = sql.SQL(" and ").join(sql.SQL("{}=%s").format(sql.Identifier(column)) for column in pk)
            current = fetch_rows(cur, "public", table, where, [row[column] for column in pk])
            if current:
                after[table][key] = current[0]
    return after


def ordered(rows):
    """The tables of a snapshot in the order Undo needs: the three place tables first, the rest by name."""
    return PLACE_TABLES + sorted(t for t in rows if t not in PLACE_TABLES)


# ------------------------------------------------------------------------------------------ the delete of a place

def move_what_is_attached(cur, found, place_id, successor_id):
    """Moves every row that points at the place onto the successor. Returns {category: rows moved}."""
    moved = {}
    for x in found:
        column = sql.Identifier(x["column"])
        target = qualified(x["schema"], x["table"])
        if x["removable"]:
            moved[x["category"]] = moved.get(x["category"], 0) + move_settings(cur, x, place_id, successor_id)
            continue
        try:
            cur.execute(sql.SQL("update {} set {}=%s where {}=%s").format(target, column, column), (successor_id, place_id))
        except psycopg2.errors.UniqueViolation:
            raise say("retire.error.sameInBoth", what=label_of(x["table"])) from None
        except psycopg2.Error as error:
            raise database_refused(error) from None
        moved[x["category"]] = moved.get(x["category"], 0) + cur.rowcount
    return moved


def move_settings(cur, x, place_id, successor_id):
    """A place's own settings move one row at a time; a row the successor has its own for stays behind (and is removed)."""
    target, column = qualified(x["schema"], x["table"]), sql.Identifier(x["column"])
    cur.execute(sql.SQL("select {} from {} where {}=%s").format(
        sql.SQL(",").join(map(sql.Identifier, x["pk"])), target, column), (place_id,))
    moved = 0
    for row in cur.fetchall():
        where = sql.SQL(" and ").join(sql.SQL("{}=%s").format(sql.Identifier(c)) for c in x["pk"])
        cur.execute("savepoint settings_row")
        try:
            cur.execute(sql.SQL("update {} set {}=%s where {}").format(target, column, where), [successor_id] + [row[c] for c in x["pk"]])
            cur.execute("release savepoint settings_row")
            moved += 1
        except psycopg2.errors.UniqueViolation:
            cur.execute("rollback to savepoint settings_row")
            cur.execute("release savepoint settings_row")
    return moved


def database_refused(error):
    """The database's own refusal in the words it chose (the guards of migrations 013 to 024 speak plainly)."""
    problem = getattr(getattr(error, "diag", None), "message_primary", None) or error.__class__.__name__
    return say("retire.error.database", problem=problem)


def delete_place(conn, level, place_id, successor_id, backup=None, record=True):
    """The delete itself, inside the caller's transaction (the caller commits, or rolls back for a check).

    backup: optional backups.Backup named in the batch (round 14: usually None; the nightly backup is enough).
    record=False: dry check only (no Import-history batch). Returns {"batch": id or None, "moved": {...}, "removed": n,
    "place": name, "successor": name or None}. Raises Refusal (nothing to commit)."""
    mission_id = sign_in.current_mission_id()
    with database.cursor(conn) as cur:
        shape = attached(cur, level, place_id)
        tables = PLACE_TABLES + sorted({x["table"] for x in shape if x["schema"] == "public"} - set(PLACE_TABLES))
    batches.lock_tables(conn, tables)
    with database.cursor(conn) as cur:
        place, found, successor = check_place(cur, level, place_id, successor_id, mission_id, lock=True)
        before, keys = snapshot_before(cur, level, place_id, found)
        moved = move_what_is_attached(cur, found, place_id, successor_id) if successor else {}
        removed = 0
        for x in found:
            if x["removable"] and count_rows(cur, x, place_id):
                cur.execute(sql.SQL("delete from {} where {}=%s").format(qualified(x["schema"], x["table"]),
                                                                       sql.Identifier(x["column"])), (place_id,))
                removed += cur.rowcount
        left = [x for x in found if not x["removable"] and count_rows(cur, x, place_id)]
        if left:
            raise say("retire.error.stillAttached", what=", ".join(sorted({label_of(x["table"]) for x in left})))
        try:
            cur.execute(sql.SQL("delete from public.{} where id=%s").format(sql.Identifier(LEVELS[level])), (place_id,))
        except psycopg2.errors.ForeignKeyViolation:
            raise say("retire.error.stillAttached", what=plain("retire.cat.other")) from None
        except psycopg2.Error as error:
            raise database_refused(error) from None
        after = snapshot_after(cur, before, keys)
    result = {"batch": None, "moved": moved, "removed": removed, "place": place["name"],
              "successor": successor["name"] if successor else None}
    if not record:
        return result
    summary = {"deleted": f"{level} {place['name']}", "moved_to": successor["name"] if successor else "nothing moved",
               "settings_removed": removed, **{f"{category}_moved": n for category, n in sorted(moved.items())}}
    if backup is not None:
        summary.update(backup.as_summary())
    batch = batches.create_batch(conn, "RETIRE", f"Delete {level} {place['name']}".replace("/", "-"), None, summary)
    changed = batches.record_changes(conn, batch, ordered(before), before, after)
    batches.add_to_summary(conn, batch, {"changed_rows": changed})
    result["batch"] = batch
    return result


def check_place_delete(level, place_id, successor_id):
    """The check: runs the whole delete in a transaction that is rolled back. Returns the result dict, or raises Refusal."""
    conn = database.connect()
    try:
        return delete_place(conn, level, place_id, successor_id, backup=None, record=False)
    finally:
        conn.rollback()
        conn.close()


def run_place_delete(level, place_id, successor_id, typed, maker=None):
    """The whole delete: the rules, the typed confirmation, the check, the backup, then the delete and its batch.
    Returns the result dict (with the batch id and the backup). Raises Refusal (plain words) or PermissionError."""
    if not roles.may_retire():
        raise PermissionError(plain("retire.error.notAllowed"))
    if level not in LEVELS:
        raise say("retire.error.notFound")
    conn = database.connect()
    try:
        with database.cursor(conn) as cur:
            place = place_row(cur, level, place_id)
        if not place or place["mission_id"] != sign_in.current_mission_id():
            raise say("retire.error.notFound")
        if clean(typed) != place["name"]:
            raise say("retire.error.typeName")
        # Round 14: no per-delete dump. Nightly backup is enough; Import history still gets an Undo batch.
        delete_place(conn, level, place_id, successor_id, backup=None, record=False)
        conn.rollback()
        result = delete_place(conn, level, place_id, successor_id, backup=None, record=True)
        conn.commit()
        result["backup"] = None
        return result
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def make_backup(label, maker=None):
    """The backup, or Refusal with the reason (nothing has been changed yet)."""
    try:
        return (maker or backups.current()).make(label)
    except backups.BackupError as error:
        raise say("retire.error.backup", problem=error) from None


# ------------------------------------------------------------------------------------------ questions

def retired_questions(cur):
    """Retired questions that are not locked: [{question_key, question_label, question_type, answers}]."""
    cur.execute("""select q.question_key,q.question_label,q.question_type,
        (select count(*) from public.weekly_planning_answers a where a.question_key=q.question_key)::int answers
      from public.planning_questions q where not q.active and not q.protected order by q.question_label,q.id""")
    return cur.fetchall()


def question_row(cur, key, lock=False):
    cur.execute("select * from public.planning_questions where question_key=%s" + (" for update" if lock else ""), (key,))
    return cur.fetchone()


def question_parts(cur, question):
    """Counts of what belongs to a question: saved answers, answer choices, grid rows, show/hide rules naming it."""
    cur.execute("""select (select count(*) from public.weekly_planning_answers where question_key=%(k)s)::int answers,
        (select count(*) from public.planning_question_options where question_id=%(i)s)::int options,
        (select count(*) from public.planning_question_grid_rows where question_id=%(i)s)::int grid_rows,
        (select count(*) from public.planning_question_visibility_rules
          where child_question_key=%(k)s or parent_question_key=%(k)s)::int rules""",
                {"k": question["question_key"], "i": question["id"]})
    return cur.fetchone()


def answer_targets(cur, question):
    """Questions that can take this question's saved answers: active, same type, and (for choices) a superset of its
    answer choices and grid rows: [(key, label)]."""
    cur.execute("select * from public.planning_questions where active and question_type=%s and question_key<>%s order by question_label",
                (question["question_type"], question["question_key"]))
    return [(q["question_key"], q["question_label"]) for q in cur.fetchall() if can_take(cur, question, q)]


def can_take(cur, question, target):
    """True when every answer choice value and grid row key of `question` also exists on `target`."""
    if question["question_type"] != target["question_type"]:
        return False
    if question["question_type"] not in CHOICE_TYPES:
        return True
    for table, column in (("planning_question_options", "option_value"), ("planning_question_grid_rows", "row_key")):
        cur.execute(sql.SQL("select {c} v from public.{t} where question_id=%s").format(c=sql.Identifier(column), t=sql.Identifier(table)),
                    (question["id"],))
        wanted = {r["v"] for r in cur.fetchall()}
        cur.execute(sql.SQL("select {c} v from public.{t} where question_id=%s").format(c=sql.Identifier(column), t=sql.Identifier(table)),
                    (target["id"],))
        if not wanted <= {r["v"] for r in cur.fetchall()}:
            return False
    return True


def delete_question(conn, key, target_key, delete_answers, who, backup=None, record=True):
    """Deletes a retired question inside the caller's transaction. target_key: move the saved answers to that question;
    delete_answers: delete them instead. record=False: dry check. Returns {"batch", "moved", "deleted_answers", "parts"}."""
    batches.lock_tables(conn, QUESTION_TABLES)
    with database.cursor(conn) as cur:
        question = question_row(cur, key, lock=True)
        if not question:
            raise say("retire.error.questionGone")
        if question["protected"]:
            raise say("retire.question.locked")
        if question["active"]:
            raise say("retire.question.active")
        parts = question_parts(cur, question)
        target = None
        if parts["answers"]:
            if target_key:
                target = question_row(cur, target_key)
                if not target or not target["active"] or not can_take(cur, question, target) or target["id"] == question["id"]:
                    raise say("retire.error.badQuestion")
            elif not delete_answers:
                raise say("retire.error.answersLeft")
        before = {name: {} for name in QUESTION_TABLES}
        wheres = {
            "planning_questions": (sql.SQL("id=%s"), (question["id"],)),
            "planning_question_options": (sql.SQL("question_id=%s"), (question["id"],)),
            "planning_question_grid_rows": (sql.SQL("question_id=%s"), (question["id"],)),
            "planning_question_visibility_rules": (sql.SQL("child_question_key=%s or parent_question_key=%s"), (key, key)),
            "weekly_planning_answers": (sql.SQL("question_key=%s"), (key,))}
        for table in QUESTION_TABLES:
            for row in fetch_rows(cur, "public", table, *wheres[table]):
                before[table][key_of(["id"], row)] = row
        moved = deleted_answers = 0
        try:
            if target:  # the target's own answer wins where a plan has both
                cur.execute("""delete from public.weekly_planning_answers a where a.question_key=%s and exists (
                    select 1 from public.weekly_planning_answers b where b.weekly_area_report_id=a.weekly_area_report_id
                    and b.question_key=%s)""", (key, target_key))
                deleted_answers = cur.rowcount
                cur.execute("update public.weekly_planning_answers set question_key=%s where question_key=%s", (target_key, key))
                moved = cur.rowcount
            elif parts["answers"]:
                cur.execute("delete from public.weekly_planning_answers where question_key=%s", (key,))
                deleted_answers = cur.rowcount
            cur.execute("delete from public.planning_question_visibility_rules where child_question_key=%s or parent_question_key=%s", (key, key))
            cur.execute("delete from public.planning_question_options where question_id=%s", (question["id"],))
            cur.execute("delete from public.planning_question_grid_rows where question_id=%s", (question["id"],))
            cur.execute("select set_config('planning_catalog.allow_delete','on',true)")  # migration 048: this transaction only
            cur.execute("delete from public.planning_questions where id=%s", (question["id"],))
            cur.execute("select set_config('planning_catalog.allow_delete','',true)")
        except psycopg2.Error as error:
            raise database_refused(error) from None
        after = {table: {} for table in QUESTION_TABLES}
        for table in QUESTION_TABLES:
            for row_key, row in before[table].items():
                current = fetch_rows(cur, "public", table, sql.SQL("id=%s"), (row["id"],))
                if current:
                    after[table][row_key] = current[0]
        removed_parts = parts["options"] + parts["grid_rows"] + parts["rules"]
        if who and record:
            pq.audit(cur, who, "planning_questions", {"question_key": key}, next(iter(before["planning_questions"].values())), None,
                     "Deleted in DA Management > Delete retired (Import history has the rows)")
    result = {"batch": None, "moved": moved, "deleted_answers": deleted_answers, "parts": removed_parts, "question": key}
    if not record:
        return result
    summary = {"deleted": f"question {key}", "answers_moved_to": target_key or "nothing moved",
               "answers_moved": moved, "answers_deleted": deleted_answers, "choices_rows_and_rules_removed": removed_parts}
    if backup is not None:
        summary.update(backup.as_summary())
    batch = batches.create_batch(conn, "RETIRE", f"Delete question {key}", None, summary)
    changed = batches.record_changes(conn, batch, QUESTION_TABLES, before, after)
    batches.add_to_summary(conn, batch, {"changed_rows": changed})
    result["batch"] = batch
    return result


def check_question_delete(key, target_key, delete_answers):
    """The check for a question: the whole delete in a transaction that is rolled back."""
    conn = database.connect()
    try:
        return delete_question(conn, key, target_key, delete_answers, None, backup=None, record=False)
    finally:
        conn.rollback()
        conn.close()


def run_question_delete(key, target_key, delete_answers, typed, maker=None):
    """The whole delete of a question, like run_place_delete. The typed confirmation is the question's key."""
    if not roles.may_retire():
        raise PermissionError(plain("retire.error.notAllowed"))
    who = sign_in.portal_person()
    if not who:
        raise PermissionError(plain("retire.error.notAllowed"))
    if clean(typed) != clean(key):
        raise say("retire.error.typeName")
    conn = database.connect()
    try:
        # Round 14: no per-delete dump (nightly backup only).
        delete_question(conn, key, target_key, delete_answers, who, backup=None, record=False)
        conn.rollback()
        result = delete_question(conn, key, target_key, delete_answers, who, backup=None, record=True)
        conn.commit()
        result["backup"] = None
        return result
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ------------------------------------------------------------------------------------------ Undo

def allowed_tables(cur):
    """The tables a RETIRE batch may have changed, for Undo (undo.tables_of): the three place tables, every public table that
    points at one of them, and the question tables."""
    names = set(PLACE_TABLES) | set(QUESTION_TABLES)
    for table in PLACE_TABLES:
        names |= {ref["table"] for ref in references(cur, table) if ref["schema"] == "public"}
    return sorted(names)
