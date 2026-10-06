"""A missionary's account page: an area change already recorded for a later day, and "stay here" to take it back.

The account page shows the area assignment in force today, as the portal does. A move saved on the page with a date
ahead ends today's row on the day before and adds the new area from that day; a transfer dated ahead does the same.

A move saved on the page can be taken back there: the Assigned area list offers "<area> - stay here", which removes
what was saved for that day (the new area row and the leadership rows that start on it) and lets the rows that were
ended on the day before run on. A change recorded by a transfer is changed with a corrected roster for its date, or
undone in Import history, and the page says so. Taking a move back is an ACCOUNT batch in Import history, like every
account page save that changes a row.

Used by account_page.py.
"""
from datetime import date, timedelta

from flask import flash, redirect

import account_changes
import account_roles
import roles
import sign_in
from account_roles import leader_label
from page import day


def recorded_by(cur, table, row):
    """The file name of the applied transfer whose change left this row as it is now, or None."""
    cur.execute("""select b.filename from public.roster_import_batches b join public.roster_import_changes c on c.batch_id=b.id
      where b.kind='TRANSFER' and b.status='APPLIED' and b.mission_id=%s and c.table_name=%s and c.row_key->>'id'=%s
        and c.after_row->>'start_date'=%s and coalesce(c.after_row->>'end_date','')=%s
      order by b.created_at desc limit 1""",
                (sign_in.current_mission_id(), table, str(row["id"]), row["start_date"].isoformat(),
                 row["end_date"].isoformat() if row["end_date"] else ""))
    found = cur.fetchone()
    return found["filename"] if found else None


def upcoming_move(cur, p, today=None):
    """The area change recorded after today for the missionary of the account page (p from account_page.person), or
    None. A dict: day (the first day of the change), next (the new area row, or None when the assignment just ends),
    starting / ending (leadership rows that start on that day / end the day before), file (the transfer that
    recorded it) and refusal (why the page cannot take it back: "release", "transfer", "more", or None)."""
    today = today or date.today()
    if not p or not p.get("assignment_end") or p["assignment_start"] > today:
        return None
    first_day = p["assignment_end"] + timedelta(days=1)
    cur.execute("""select ma.id,ma.area_id,ma.start_date,ma.end_date,a.name area,z.name zone from public.missionary_assignments ma
      join public.areas a on a.id=ma.area_id join public.districts d on d.id=a.district_id join public.zones z on z.id=d.zone_id
      where ma.missionary_id=%s and ma.start_date>%s order by ma.start_date,ma.id""", (p["id"], today))
    later = cur.fetchall()
    move = {"day": first_day, "next": later[0] if later else None, "starting": [], "ending": [], "file": None, "refusal": None}
    current = {"id": p["assignment_id"], "start_date": p["assignment_start"], "end_date": p["assignment_end"]}
    move["file"] = recorded_by(cur, "missionary_assignments", current)
    if not later:  # released on that day (by a transfer dated ahead), not moved: nothing here to take back
        move["refusal"] = "release"
        return move
    leaders = account_roles.open_leaders(cur, p["id"], today)
    move["starting"] = [l for l in leaders if l["start_date"] == first_day]
    move["ending"] = [l for l in leaders if l["end_date"] == first_day - timedelta(days=1)]
    move["file"] = (move["file"] or recorded_by(cur, "missionary_assignments", later[0])
                    or next((f for f in (recorded_by(cur, "leadership_assignments", l) for l in move["starting"] + move["ending"]) if f), None))
    if move["file"]:
        move["refusal"] = "transfer"
    elif later[0]["start_date"] != first_day or len(later) > 1 or later[0]["end_date"] or any(l["start_date"] > first_day for l in leaders):
        move["refusal"] = "more"
    return move


def area_name(row):
    return f"{row['zone']} / {row['area']}"


def note(move):
    """Added to the account page's "Current role" line: the recorded change, in plain words."""
    if not move:
        return ""
    if not move["next"]:
        return f". Area: the assignment ends on {day(move['day'] - timedelta(days=1))}" + (f" (transfer \"{move['file']}\")" if move["file"] else "")
    text = f". Area: moves to {area_name(move['next'])} on {day(move['day'])}"
    if move["file"]:
        return text + f" (transfer \"{move['file']}\")"
    return text + (" (saved on this page; to take it back, choose \"stay here\" under Assigned area)" if not move["refusal"] else "")


def with_stay_option(areas, p, move):
    """The Assigned area list, plus "<area> - stay here" right after today's area when a move saved on this page can be
    taken back. Its value is minus the id of the new area row (the save checks that it is still that move)."""
    if not move or move["refusal"] or not move["next"]:
        return areas
    stay = {"id": -int(move["next"]["id"]), "zone": p["zone"],
            "name": f"{p['area']} - stay here (take back the move on {day(move['day'])})"}
    at = next((i + 1 for i, a in enumerate(areas) if a["id"] == p["area_id"]), len(areas))
    return areas[:at] + [stay] + areas[at:]


def move_refusal(cur, p):
    """Why the account page cannot move the missionary now: an area change is already recorded for a later day."""
    move = upcoming_move(cur, p)
    if not move:
        return f"This assignment already ends on {day(p['assignment_end'])}. Keep the area, or change it with a transfer roster."
    first_day = day(move["day"])
    if not move["next"]:
        by = f"The transfer \"{move['file']}\"" if move["file"] else "A transfer"
        return (f"{by} already ends this assignment on {day(p['assignment_end'])}. Keep the area, or change it with a "
                f"corrected roster dated {first_day}.")
    if move["refusal"] == "transfer":
        return (f"The transfer \"{move['file']}\" already moves them to {area_name(move['next'])} on {first_day}. Keep the area here. To "
                f"change the move, apply a corrected roster dated {first_day}, or undo that transfer in Import history.")
    if move["refusal"] == "more":
        return (f"More than one change is already recorded from {first_day}. Keep the area here, and change it with a transfer roster "
                f"dated {first_day} or later.")
    return (f"A move to {area_name(move['next'])} on {first_day} is already saved. This page keeps one move ahead at a time: to move "
            f"them elsewhere, first choose \"{p['area']} - stay here\" under Assigned area and save, then save the new move. "
            f"From {first_day} on, the next move can be saved here as usual.")


def stay_lines(move):
    """What taking the move back does, in plain sentences."""
    last = move["day"] - timedelta(days=1)
    lines = [f"Takes back the move to {area_name(move['next'])} on {day(move['day'])}: the current area stays."]
    lines += [f"Removes the {leader_label(l['role'], l['district'], l['zone'])} that starts on {day(move['day'])}." for l in move["starting"]]
    lines += [f"The {leader_label(l['role'], l['district'], l['zone'])} no longer ends on {day(last)}." for l in move["ending"]]
    return lines


def checked_move(cur, p, next_id):
    """The recorded move whose new area row is next_id, if the page may still take it back; else ValueError."""
    move = upcoming_move(cur, p)
    if not move or not move["next"] or int(move["next"]["id"]) != int(next_id):
        raise ValueError("That move is no longer recorded. Reload the page and check again.")
    if move["refusal"]:
        raise ValueError(move_refusal(cur, p))
    return move


def stay_plan(cur, p, next_id):
    """The "What saving will change" box for "stay here" (the account page's role-plan request)."""
    try:
        move = checked_move(cur, p, next_id)
    except ValueError as e:
        return {"errors": [str(e)], "lines": [], "ends": 0}
    lines = stay_lines(move) + ["Only this is saved: other changes on the page are not."]
    return {"errors": [], "lines": lines, "ends": 1}  # ends: the page asks before saving


def cancel(cur, p, next_id, state):
    """Saves "stay here": removes the move saved for a later day, and only that. Returns the page's redirect."""
    today = date.today()
    leaders = account_roles.open_leaders(cur, p["id"], today, lock=True)
    if state != account_changes.page_state(p, leaders):
        raise ValueError(account_changes.STALE)
    cur.execute("select id from public.missionary_assignments where missionary_id=%s for update", (p["id"],))
    move = checked_move(cur, p, next_id)
    before = account_changes.account_snapshot(cur.connection, p["id"], lock=True)  # for the ACCOUNT batch in Import history
    remove_move(cur, p, move)
    lines = stay_lines(move)
    if p["profile_id"]:
        lines += record_role_again(cur, p, today)
    flash(" ".join(lines))
    if account_changes.record_account_batch(cur.connection, p, before, move["day"], "move taken back"):  # Undo moves again
        flash(account_changes.IN_HISTORY)
    return redirect(f"/accounts/{p['id']}")


def remove_move(cur, p, move):
    """Removes the new area row and the leadership rows that start on the move's day, and lets the rows that were
    ended on the day before run on (unless the same role already runs on in another row)."""
    last, leader_roles = move["day"] - timedelta(days=1), list(roles.LEADER_ROLES)
    cur.execute("delete from public.missionary_assignments where id=%s", (move["next"]["id"],))
    cur.execute("update public.missionary_assignments set end_date=null where id=%s and end_date=%s", (p["assignment_id"], last))
    cur.execute("delete from public.leadership_assignments where missionary_id=%s and start_date=%s and role=any(%s)",
                (p["id"], move["day"], leader_roles))
    cur.execute("""update public.leadership_assignments la set end_date=null where la.missionary_id=%s and la.end_date=%s and la.role=any(%s)
      and not exists (select 1 from public.leadership_assignments o where o.missionary_id=la.missionary_id and o.id<>la.id
                      and o.role=la.role and o.end_date is null)""", (p["id"], last, leader_roles))


def record_role_again(cur, p, today):
    """Records the account role as saving the page again unchanged would. Returns a line when it changed. Refuses when
    this ends the signed-in manager's own access."""
    lines = []
    leaders = account_roles.open_leaders(cur, p["id"], today)
    record = account_roles.recorded_role(account_roles.effective_role(p["app_role"], leaders, today), leaders, today)
    cur.execute("update public.user_profiles set app_role=%s,updated_at=now() where id=%s and app_role is distinct from %s",
                (record, p["profile_id"], record))
    if cur.rowcount:
        lines.append(f"Recorded account role: {roles.role_name(p['app_role'] or 'MISSIONARY')} → {roles.role_name(record)}.")
    if sign_in.is_me(p["profile_id"]):
        context = sign_in.management_context(cur, p["profile_id"])  # this uncommitted change, as the next request would see it
        if not context or int(context["mission_id"]) != sign_in.current_mission_id():
            raise ValueError("This ends your own DA Management access. Ask another administrator to make this change.")
    return lines
