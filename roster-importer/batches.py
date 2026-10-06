"""Batches: how DA Management writes down every change it makes, so it can be shown and undone later.

Every import (a transfer, a historical CSV, a data upload) and every saved account change is one BATCH
(public.roster_import_batches: what kind, which file, who, when). For most kinds we also write down every row the
batch changed, as it was before and after (public.roster_import_changes). The way to do that:

    before = snapshot(conn, tables)          # every row of these tables, before
    batch = create_batch(conn, "TRANSFER", filename, day, summary)
    ... make the changes ...
    record_changes(conn, batch, tables, before, snapshot(conn, tables))

Import history (import_history.py) lists the batches, and Undo (undo.py) puts the "before" rows back.
Data uploads that keep their own rows (the finding export, zone history, ...) do not record rows here: each row
carries its batch id instead (data_uploads.py).
"""
import json
import uuid
from pathlib import Path

import psycopg2.extras
from psycopg2 import sql

import database
import sign_in

# The tables each kind of batch may change.
TRANSFER_TABLES = ["zones", "districts", "units", "areas", "missionaries", "area_units",
                   "missionary_assignments", "leadership_assignments", "user_profiles"]
# An ACCOUNT batch: one saved change on Staff accounts (the profile row only) or on a missionary's account page (that
# missionary's area and leadership rows and linked profile).
ACCOUNT_TABLES = ["missionary_assignments", "leadership_assignments", "user_profiles"]
# DA Management > Places and "Close old area": the places a closing or reopening may change.
PLACES_TABLES = ["zones", "districts", "areas"]
# People come first and the weekly person rows last, so Undo can remove rows in reverse order without breaking a link.
PEOPLE_TABLES = ["baptismal_date_people", "baptismal_date_person_area_assignments", "new_members",
                 "new_member_area_assignments"]
WEEKLY_PEOPLE_TABLES = ["weekly_new_members", "weekly_baptismal_date_friends", "weekly_high_potential_friends"]
HISTORICAL_TABLES = PEOPLE_TABLES + ["reporting_weeks", "weekly_area_reports", "historical_planning_details",
                     "import_weekly_planning_reports", "import_weekly_planning_answers",
                     "import_weekly_new_members", "import_weekly_baptismal_date_friends",
                     "import_weekly_high_potential_friends"] + WEEKLY_PEOPLE_TABLES
# A "People" data upload (names and details of new members and friends, no weekly forms): no import_* staging tables.
PEOPLE_UPLOAD_TABLES = PEOPLE_TABLES + ["reporting_weeks", "weekly_area_reports"] + WEEKLY_PEOPLE_TABLES
AREA_DATA_TABLES = ["area_profiles"]  # Data uploads > Area data (data_uploads.py)
# The tables Undo may put back, for each kind of batch (any other kind: HISTORICAL_TABLES).
TABLES_OF_KIND = {"TRANSFER": TRANSFER_TABLES, "ACCOUNT": ACCOUNT_TABLES, "AREA_DATA": AREA_DATA_TABLES,
                  "PEOPLE": PEOPLE_UPLOAD_TABLES, "PLACES": PLACES_TABLES}

# How a row of each table is found again: its key columns ("id" unless listed here).
KEYS = {"historical_planning_details": ["weekly_area_report_id"],
        "area_profiles": ["area_id"],
        "import_weekly_planning_reports": ["source_report_key"],
        "import_weekly_planning_answers": ["source_report_key", "source_column"],
        "import_weekly_new_members": ["source_report_key", "display_order"],
        "import_weekly_baptismal_date_friends": ["source_report_key", "display_order"],
        "import_weekly_high_potential_friends": ["source_report_key", "display_order"]}


def row_key(table, row):
    """{key column: value} of a row, e.g. {"id": 42}."""
    return {k: row[k] for k in KEYS.get(table, ["id"])}


def key_string(key):
    """A row key as text, the same text every time (so it can be looked up in a dict)."""
    return json.dumps(key, sort_keys=True, separators=(",", ":"))


def snapshot(conn, tables, rows_of=None, lock=False):
    """Every row of these tables: {table: {key string: row as a dict}}.

    rows_of: {table: (column, value)} keeps only the rows where column = value (an account page save records one
    missionary's rows, not whole tables). lock: also locks those rows (FOR UPDATE) until the transaction ends."""
    output = {}
    with database.cursor(conn) as cur:
        for table in tables:
            query, params = sql.SQL("select to_jsonb(t) as row from public.{} t").format(sql.Identifier(table)), []
            if rows_of and table in rows_of:
                column, value = rows_of[table]
                query, params = query + sql.SQL(" where t.{}=%s").format(sql.Identifier(column)), [value]
            if lock:
                query += sql.SQL(" for update")
            cur.execute(query, params)
            output[table] = {key_string(row_key(table, r["row"])): r["row"] for r in cur.fetchall()}
    return output


def lock_tables(conn, tables):
    """Nobody else may change these tables until the transaction ends, so the before/after snapshots only show this
    batch's own changes."""
    with database.cursor(conn) as cur:
        for table in tables:
            cur.execute(sql.SQL("lock table public.{} in share row exclusive mode").format(sql.Identifier(table)))


def record_changes(conn, batch_id, tables, before, after):
    """Writes down every row that differs between the two snapshots. Returns how many rows changed."""
    sequence = 0
    with database.cursor(conn) as cur:
        for table in tables:
            for key in sorted(set(before[table]) | set(after[table])):
                old, new = before[table].get(key), after[table].get(key)
                if old == new:
                    continue
                sequence += 1
                cur.execute("""insert into public.roster_import_changes
                  (batch_id,sequence,table_name,row_key,before_row,after_row) values(%s,%s,%s,%s,%s,%s)""",
                            (str(batch_id), sequence, table, psycopg2.extras.Json(json.loads(key)),
                             psycopg2.extras.Json(old) if old is not None else None,
                             psycopg2.extras.Json(new) if new is not None else None))
    return sequence


def count_changes(tables, before, after):
    """How many rows differ between two snapshots (without writing anything)."""
    return sum(before[t].get(k) != after[t].get(k) for t in tables for k in set(before[t]) | set(after[t]))


def create_batch(conn, kind, filename, effective_date, summary):
    """A new batch of the signed-in manager's mission, named after the file. Returns its id."""
    batch = str(uuid.uuid4())
    with database.cursor(conn) as cur:
        cur.execute("""insert into public.roster_import_batches
          (id,mission_id,kind,filename,effective_date,actor,summary) values(%s,%s,%s,%s,%s,%s,%s)""",
                    (batch, sign_in.current_mission_id(), kind, Path(filename).name, effective_date, sign_in.actor_name(),
                     psycopg2.extras.Json(summary)))
    return batch


def add_to_summary(conn, batch_id, values):
    """Adds numbers to a batch's summary (shown on its Import history page)."""
    with database.cursor(conn) as cur:
        cur.execute("update public.roster_import_batches set summary=summary||%s where id=%s",
                    (psycopg2.extras.Json(values), batch_id))
