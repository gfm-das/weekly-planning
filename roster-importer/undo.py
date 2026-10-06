"""Undo in Import history: putting every row of a batch back as it was before.

A batch (batches.py) keeps each changed row as it was before and after. undo_batch() reverses the whole batch in one
transaction, or nothing at all:
  1. It checks that every row is still exactly as the batch left it. A row edited later, or new data that points to
     a row the batch added, blocks the undo ("Undo blocked: ..."), and nothing is changed.
  2. It removes the rows the batch added (newest first), and puts back the rows it changed or removed.
  3. It marks the batch UNDONE, with who undid it.

Data uploads that keep their own rows (the finding export, zone history, ...) are undone by removing those rows
(data_uploads.undo_rows). An account change may only be undone by someone who may make it (account_changes.py). An
undo that would end the signed-in manager's own DA Management access needs the "I understand" tick.
"""
import psycopg2.extras
from psycopg2 import sql

import account_changes
import batches
import data_uploads
import database
import sign_in


class OwnAccessError(ValueError):
    """Undo would end the signed-in manager's own DA Management access: Import history asks for an extra tick."""


def undo_batch(batch_id, own_access=False):
    """Reverses a batch. Returns True when this ended the signed-in manager's own DA Management access (allowed only
    with own_access=True, the "I understand" tick); the page then signs them out."""
    ends_own = False
    conn = database.connect()
    try:
        with database.cursor(conn) as cur:
            batch = applied_batch(cur, batch_id)
            cur.execute("select * from public.roster_import_changes where batch_id=%s order by sequence", (batch_id,))
            changes = cur.fetchall()
            tables = tables_of(cur, batch, changes)
            for table in tables:
                cur.execute(sql.SQL("lock table public.{} in share row exclusive mode").format(sql.Identifier(table)))
            me = session_user()
            had_access = bool(me) and sign_in.management_context(cur, me) is not None
            for change in changes:
                if not same_as_recorded(current_row(cur, change["table_name"], change["row_key"]), change["after_row"]):
                    raise ValueError(f"Undo blocked: {change['table_name']} changed after this import. No data was reversed.")
            put_rows_back(cur, batch, changes)
            cur.execute("update public.roster_import_batches set status='UNDONE',undone_at=now(),undone_by=%s where id=%s",
                        (sign_in.actor_name(), batch_id))
            if had_access:  # this uncommitted undo, as the next request would see it (e.g. undoing the batch that added your account)
                context = sign_in.management_context(cur, me)
                ends_own = not context or int(context["mission_id"]) != sign_in.current_mission_id()
                if ends_own and not own_access:
                    raise OwnAccessError("Undoing this ends your own DA Management access, and you could not give it back to "
                                         "yourself. Tick \"I understand\" to go ahead, or ask another administrator to undo it.")
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return ends_own


def session_user():
    """The signed-in portal user's id as text, or None (the old shared password)."""
    person = sign_in.portal_person()
    return person[1] if person else None


def applied_batch(cur, batch_id):
    """The batch (locked), if it belongs to this mission and is not undone yet; else ValueError."""
    cur.execute("select * from public.roster_import_batches where id=%s and mission_id=%s for update",
                (batch_id, sign_in.current_mission_id()))
    batch = cur.fetchone()
    if not batch or batch["status"] != "APPLIED":
        raise ValueError("This batch does not exist or has already been undone.")
    return batch


def tables_of(cur, batch, changes):
    """The tables whose rows this undo puts back. A data upload with its own rows removes them here and puts back
    no table rows. Raises ValueError for a batch that changed a table of another kind, and PermissionError for an
    account change the signed-in manager may not undo."""
    tables = batches.TABLES_OF_KIND.get(batch["kind"], batches.HISTORICAL_TABLES)
    if batch["kind"] in data_uploads.ROW_KINDS:  # a data upload keeps its own rows: Undo removes them
        data_uploads.undo_rows(cur, batch)
        tables = []
    if any(c["table_name"] not in tables for c in changes):
        raise ValueError("Undo blocked: the audit contains an unsupported table.")
    if batch["kind"] == "ACCOUNT":  # the rules of Staff accounts and the account page apply to Undo too
        account_changes.check_undo(changes)
    return tables


def put_rows_back(cur, batch, changes):
    """Removes the rows the batch added (newest first) and puts back the rows it changed or removed."""
    for change in reversed(changes):
        if change["before_row"] is None:
            refuse_if_referenced(cur, change["table_name"], change["after_row"])
            cur.execute(sql.SQL("delete from public.{} where {}").format(sql.Identifier(change["table_name"]),
                        key_predicate(change["row_key"])), list(change["row_key"].values()))
    if batch["kind"] == "HISTORICAL":
        # Restored rows may swap historical_source_key values (remapped labels); clear the keys of the rows being
        # restored first, so the unique index cannot fail half-way.
        ids = [c["row_key"]["id"] for c in changes if c["table_name"] == "weekly_area_reports"
               and c["before_row"] is not None and c["after_row"] is not None]
        if ids:
            cur.execute("update public.weekly_area_reports set historical_source_key=null where id=any(%s)", (ids,))
    for change in changes:
        if change["before_row"] is not None:
            restore_row(cur, change["table_name"], change["before_row"], change["row_key"], change["after_row"] is None)


def same_as_recorded(current, recorded):
    """True when a row is still as the batch left it. Records written before a migration added a column (for example
    user_profiles.additional_roles in 021) do not have it, so only the recorded columns are compared."""
    if current is None or recorded is None:
        return current is None and recorded is None
    return {k: current.get(k) for k in recorded} == recorded


def key_predicate(key):
    """SQL for "this row": every key column equals its value (NULLs count as equal)."""
    return sql.SQL(" and ").join(sql.SQL("{} is not distinct from %s").format(sql.Identifier(k)) for k in key)


def current_row(cur, table, key):
    """The row as it is now (locked), or None when it is gone."""
    cur.execute(sql.SQL("select to_jsonb(t) row from public.{} t where {} for update").format(
        sql.Identifier(table), key_predicate(key)), list(key.values()))
    rows = cur.fetchall()
    if len(rows) > 1:
        raise ValueError("Undo blocked: the affected row key is no longer unique.")
    return rows[0]["row"] if rows else None


def refuse_if_referenced(cur, table, row):
    """A row the batch added may only be removed when no other row points to it (for example a report that got
    Weekly Planning entries after the import)."""
    cur.execute("""select n.nspname schema_name,cl.relname table_name,
      array(select a.attname from unnest(c.conkey) with ordinality x(num,ord)
        join pg_attribute a on a.attrelid=c.conrelid and a.attnum=x.num order by x.ord) child_columns,
      array(select a.attname from unnest(c.confkey) with ordinality x(num,ord)
        join pg_attribute a on a.attrelid=c.confrelid and a.attnum=x.num order by x.ord) parent_columns
      from pg_constraint c join pg_class cl on cl.oid=c.conrelid join pg_namespace n on n.oid=cl.relnamespace
      where c.contype='f' and c.confrelid=%s::regclass""", ("public." + table,))
    for ref in cur.fetchall():
        predicates = sql.SQL(" and ").join(sql.SQL("{}=%s").format(sql.Identifier(c)) for c in ref["child_columns"])
        cur.execute(sql.SQL("select exists(select 1 from {}.{} where {}) present").format(
            sql.Identifier(ref["schema_name"]), sql.Identifier(ref["table_name"]), predicates),
            [row[c] for c in ref["parent_columns"]])
        if cur.fetchone()["present"]:
            raise ValueError(f"Undo blocked: {ref['table_name']} now references a row created by this import.")


def restore_row(cur, table, row, key, insert=False):
    """Puts one row back as recorded: inserts it again (insert=True) or overwrites the recorded columns. A column
    added to the table after the batch was recorded keeps its default or its current value."""
    columns = list(row)
    column_list = sql.SQL(",").join(map(sql.Identifier, columns))
    if insert:
        cur.execute(sql.SQL("insert into public.{} ({}) overriding system value select {} from jsonb_populate_record(null::public.{},%s)").format(
            sql.Identifier(table), column_list, column_list, sql.Identifier(table)), (psycopg2.extras.Json(row),))
    else:
        cur.execute(sql.SQL("update public.{} set ({})=(select {} from jsonb_populate_record(null::public.{},%s)) where {}").format(
            sql.Identifier(table), column_list, column_list, sql.Identifier(table), key_predicate(key)),
            [psycopg2.extras.Json(row)] + list(key.values()))
