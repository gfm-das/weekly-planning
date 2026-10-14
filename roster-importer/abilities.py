"""Role abilities: reading, planning, saving and reverting the switches (DA Management > Accounts > Role abilities).

What it does: public.role_abilities (migration 055) holds one switch per role and ability. This file reads it, works out what a
change would do (plan), saves a change together with its log rows in ONE transaction (save_change), and puts a saved change
back (revert_batch). The page is abilities_page.py.

The rules that no switch can change are in roles.py (cell_is_valid, shared with portal-api) and, again, in the database
(public.role_ability_ok, a CHECK on the table). This file checks them a third time before it writes: a cell that is not in
roles.SWITCHABLE is never written, and the table read back after the write must still obey every rule, or the whole change is
undone. There is no ability here for DA Management access, giving roles, deleting places or editing abilities: who may use this
page is decided by the page (managers signed in through the portal), not by the table.

The log: the database writes it (a trigger on the table), one row per changed switch, all rows of one save or revert sharing a
batch id. A revert is a new change that puts the old values back and names the batch it reverts; a batch can be reverted once,
and only while every switch in it still has the value that batch gave it.
"""
import uuid

import database
import roles

# The switches a manager can change, in page order: by ability, then by role.
DISPLAY_ROLES = ("MISSIONARY", "DL", "ZL", "STL", "OFFICE", "AP", "PRESIDENT", "DATA_ADMIN")
SWITCH_CELLS = [(role, ability) for ability in roles.ABILITIES for role in DISPLAY_ROLES if role in roles.SWITCHABLE[ability]]
CONFIRM_WORD = "CHANGE"
NOTE_LIMIT = 500


def cell_key(role, ability):
    """The name of a switch in a form: 'OFFICE|calendar.edit'."""
    return f"{role}|{ability}"


def cell_from_key(text):
    """(role, ability) of a form value, or None when it is not a switch a manager may change."""
    role, _bar, ability = str(text).partition("|")
    return (role, ability) if (role, ability) in SWITCH_CELLS else None


def read_table(cur, lock=False):
    """{(role, ability): allowed} as the database holds it, or None when the table is missing, incomplete or breaks a rule
    (then nothing may be changed here). lock=True keeps the rows for this transaction."""
    cur.execute("select to_regclass('public.role_abilities') is not null present")
    if not cur.fetchone()["present"]:
        return None
    cur.execute("select role,ability,allowed from public.role_abilities" + (" for update" if lock else ""))
    return roles.parse_ability_rows(cur.fetchall())


def read_for_roles():
    """What roles.py reads (the shared 30 second cache): the rows of the table."""
    with database.connect() as conn:
        with database.cursor(conn) as cur:
            cur.execute("select role,ability,allowed from public.role_abilities")
            return cur.fetchall()


roles.set_ability_reader(read_for_roles)


def base_token(table):
    """A short text for the switches as they are now (1 on, 0 off, in page order). The preview carries it to the save, which
    refuses when someone changed a switch in between."""
    return "".join("1" if table[cell] else "0" for cell in SWITCH_CELLS)


def wanted_from(checked):
    """The wanted value of every switch from the ticked boxes (form values). Unknown values are an error (ValueError)."""
    ticked = set()
    for text in checked:
        cell = cell_from_key(text)
        if cell is None:
            raise ValueError("That switch cannot be changed.")
        ticked.add(cell)
    return {cell: cell in ticked for cell in SWITCH_CELLS}


def plan(table, wanted):
    """The switches that would change: [{role, ability, before, after}] in page order. Only switchable cells count."""
    return [{"role": role, "ability": ability, "before": table[(role, ability)], "after": wanted[(role, ability)]}
            for role, ability in SWITCH_CELLS if table[(role, ability)] != wanted[(role, ability)]]


def table_after(table, changes):
    """The matrix with these changes made (the original is not touched)."""
    result = dict(table)
    for change in changes:
        result[(change["role"], change["ability"])] = change["after"]
    return result


def refusal(table):
    """Why this matrix may not be saved, or None: every cell must obey roles.cell_is_valid, so the managers keep every
    ability, a missionary has none and a fixed cell keeps its built-in value."""
    if set(table) != set(roles.DEFAULT_ABILITIES):
        return "The table is incomplete."
    for (role, ability), allowed in table.items():
        if not roles.cell_is_valid(role, ability, allowed):
            return f"{role} / {ability} may not be {'on' if allowed else 'off'}."
    for ability in roles.ABILITIES:
        if not all(table[(role, ability)] for role in roles.MANAGER_ROLES):
            return "The managers must keep every ability."
    return None


def apply_changes(cur, changes, batch, who, note, reverts=None):
    """Writes the changes (the database's trigger writes the log rows). Must run inside the transaction that holds the lock."""
    name, user_id = who
    cur.execute("select set_config('gfm.change_batch',%s,true),set_config('gfm.change_note',%s,true),set_config('gfm.reverts_batch',%s,true)",
                (batch, (note or "")[:NOTE_LIMIT], reverts or ""))
    for change in changes:
        cur.execute("update public.role_abilities set allowed=%s,changed_by=%s::uuid,changed_by_name=%s where role=%s and ability=%s",
                    (change["after"], user_id, name, change["role"], change["ability"]))
        if cur.rowcount != 1:
            raise RuntimeError("A role ability row is missing.")


def check_written(cur, expected):
    """Reads the table back inside the transaction: it must be exactly the expected matrix and obey every rule. Otherwise the
    caller's transaction is rolled back (an exception)."""
    table = read_table(cur)
    if table is None or table != expected or refusal(table):
        raise RuntimeError("The role abilities do not match what was meant to be saved. Nothing was saved.")


def save_change(wanted, base, note, who):
    """Saves the wanted switches. Returns (status, changes): 'saved', 'nochange', 'stale' (someone else changed a switch since
    the preview) or 'unreadable' (the table is not there). All or nothing."""
    batch = str(uuid.uuid4())
    with database.connect() as conn:
        with database.cursor(conn) as cur:
            current = read_table(cur, lock=True)
            if current is None:
                return "unreadable", []
            if base_token(current) != base:
                return "stale", []
            changes = plan(current, wanted)
            if not changes:
                return "nochange", []
            expected = table_after(current, changes)
            if refusal(expected):
                raise ValueError(refusal(expected))
            apply_changes(cur, changes, batch, who, note)
            check_written(cur, expected)
    roles.forget_abilities()
    return "saved", changes


def read_log(cur, limit=300):
    """The change log, newest batch first: [{batch, when, who, note, reverts, cells: [(role, ability, before, after)],
    reverted}]. 'reverted' is True when a later batch reverted it."""
    cur.execute("select * from public.role_abilities_log order by id desc limit %s", (limit,))
    batches, order = {}, []
    for row in cur.fetchall():
        key = str(row["batch_id"])
        if key not in batches:
            batches[key] = {"batch": key, "when": row["changed_at"], "who": row["changed_by_name"], "note": row["note"],
                            "reverts": str(row["reverts_batch"]) if row["reverts_batch"] else None, "cells": [], "reverted": False}
            order.append(key)
        batches[key]["cells"].append((row["role"], row["ability"], row["before_allowed"], row["after_allowed"]))
    reverted = {b["reverts"] for b in batches.values() if b["reverts"]}
    for key in order:
        batches[key]["cells"].reverse()  # oldest first inside a batch
        batches[key]["reverted"] = key in reverted
    return [batches[key] for key in order]


def revert_batch(batch_id, who):
    """Puts one saved change back. Returns (status, changes): 'reverted', 'missing', 'already' (reverted before), 'stale' (a
    switch of the batch was changed again since) or 'unreadable'. All or nothing."""
    batch = str(batch_id)
    new_batch = str(uuid.uuid4())
    with database.connect() as conn:
        with database.cursor(conn) as cur:
            current = read_table(cur, lock=True)
            if current is None:
                return "unreadable", []
            cur.execute("select role,ability,before_allowed,after_allowed from public.role_abilities_log where batch_id=%s order by id", (batch,))
            logged = cur.fetchall()
            if not logged:
                return "missing", []
            cur.execute("select 1 from public.role_abilities_log where reverts_batch=%s limit 1", (batch,))
            if cur.fetchone():
                return "already", []
            if any(current.get((row["role"], row["ability"])) != row["after_allowed"] for row in logged):
                return "stale", []
            changes = [{"role": row["role"], "ability": row["ability"], "before": row["after_allowed"], "after": row["before_allowed"]}
                       for row in logged]
            expected = table_after(current, changes)
            if refusal(expected):
                raise ValueError(refusal(expected))
            apply_changes(cur, changes, new_batch, who, None, reverts=batch)
            check_written(cur, expected)
    roles.forget_abilities()
    return "reverted", changes
