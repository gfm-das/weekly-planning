"""Account changes in Import history: writing them down, and who may undo them.

Every saved change to someone's roles, account status, area or leadership is an ACCOUNT batch in Import history
(batches.py): on a missionary's account page (account_page.py, account_moves.py) and on Staff accounts
(staff_accounts.py). It keeps the rows as they were before and after, with who saved them, so Import history can
show it and Undo can put the rows back (undo.py). A save that only changes the languages is not listed.

Undo follows the same rules as making the change: a change to a President's account may only be undone by an AP,
the President or a Data Analyst (check_undo).
"""
import re

import account_roles
import batches
import roles

# The rows an account page save may change: the missionary's area and leadership assignments and linked account.
ACCOUNT_ROWS = {"missionary_assignments": "missionary_id", "leadership_assignments": "missionary_id",
                "user_profiles": "missionary_id"}
# Said after an account page save that made a batch.
IN_HISTORY = "The change is in Import history, where it can be undone."
# The save refuses a page that was opened before its account, area or leadership rows changed.
STALE = "This account's role, status or assignments changed since you opened the page. Reload the page and check again."
NOT_ALLOWED_UNDO = "This change is to a President account. Only an AP, the President or a Data Analyst can undo it."


def page_state(p, leaders):
    """What the account page was built from: linked account, saved main and additional roles and status, area
    assignment, leadership rows and their dates. The save refuses a page opened before any of these changed (for
    example by a transfer, or another manager's save)."""
    return "|".join(str(x) for x in (p["profile_id"] or "", p["app_role"] or "", ",".join(account_roles.additional_of(p)),
                                      p["profile_active"], p["assignment_id"],
                                      ",".join(f"{l['id']}:{l['start_date']}:{l['end_date'] or ''}" for l in leaders)))


def account_snapshot(conn, person_id, lock=False):
    """The rows an account page save may change (see ACCOUNT_ROWS), as batches.snapshot() takes them."""
    return batches.snapshot(conn, batches.ACCOUNT_TABLES, {t: (column, person_id) for t, column in ACCOUNT_ROWS.items()}, lock)


def roles_label(profile):
    """'DL + Data Analyst': a user_profiles row's recorded main role and additional roles, for Import history."""
    if not profile:
        return "No linked account"
    main = str(profile.get("app_role") or "MISSIONARY").upper()
    extras = {str(r).upper() for r in (profile.get("additional_roles") or [])}
    return " + ".join([roles.role_name(main)] + [roles.role_name(r) for r in roles.ADDITIONAL_ROLES if r in extras and r != main])


def record_account_batch(conn, p, before, effective_date, action=None):
    """An account page save as an ACCOUNT batch: who saved it (the batch's actor), whose account (the file name), the
    roles before and after, and the missionary's rows before and after (before: account_snapshot() taken ahead of the
    save). Returns the batch id, or None when no row changed (a save of the languages only)."""
    after = account_snapshot(conn, p["id"])
    count = batches.count_changes(batches.ACCOUNT_TABLES, before, after)
    if not count:
        return None
    old, new = (next(iter(s["user_profiles"].values()), None) for s in (before, after))
    if old and new and old.get("active") != new.get("active"):
        action = "turned on" if new.get("active") else "turned off"
    elif not action:
        action = "moved" if before["missionary_assignments"] != after["missionary_assignments"] else "changed"
    role_change = roles_label(new) if roles_label(old) == roles_label(new) else f"{roles_label(old)} → {roles_label(new)}"
    label = re.sub(r"[/\\]", "-", p["display_name"] or str(p["id"]))
    batch = batches.create_batch(conn, "ACCOUNT", f"Account page - {label}",
                                 effective_date, {"action": action, "role": role_change, "changed_rows": count})
    batches.record_changes(conn, batch, batches.ACCOUNT_TABLES, before, after)
    return batch


def check_undo(changes):
    """Undo of an ACCOUNT batch follows the rule of the account pages: every recorded account row, before and after,
    must be one the signed-in manager may change. Raises PermissionError otherwise."""
    profiles = [c for c in changes if c["table_name"] == "user_profiles"]
    if any(not roles.may_change(c["before_row"]) or not roles.may_change(c["after_row"]) for c in profiles):
        raise PermissionError(NOT_ALLOWED_UNDO)


def undo_refusal(cur, batch_id):
    """Import history: why this ACCOUNT batch's Undo is not offered to the signed-in manager, or None."""
    cur.execute("select table_name,before_row,after_row from public.roster_import_changes where batch_id=%s", (str(batch_id),))
    try:
        check_undo(cur.fetchall())
    except PermissionError as e:
        return str(e)
    return None
