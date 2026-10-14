"""The Vollzogen upload: the office's list of people who were baptized and confirmed (the rules; the pages are
vollzogen_pages.py, the reading of the sheet is data_types.parse_vollzogen).

Steps, like the other uploads:
  1. Upload: the sheet is read in memory (loose dates, an X in Konfirmiert, blank and placeholder lines skipped) and its
     rows wait for Apply.
  2. Check: every person of the list is looked for among the new members already in the portal. An FC number matches first
     and exactly. Without one, the same name counts as the same person when the zone or the baptism date agrees; a same
     name with nothing to back it up, or a very alike name, is ASKED (people_pages /people/decide, remembered for later).
  3. Apply: one batch in Import history (kind VOLLZOGEN) with every changed row of public.vollzogen_records as it was before
     and after, and Undo (batches.py, undo.py).

What it never does: it does not write to the portal's people (new_members and the rest). A person's typed answers are
untouched; the list only keeps a link (vollzogen_records.new_member_id). Uploading the same person again updates the
record: an empty cell keeps what is saved, an FC number or a link already saved is never replaced, and "confirmed" never
goes back to "not confirmed".
"""
from datetime import date

import psycopg2.extras
from psycopg2 import sql

import batches
import data_names
import database
import people_match as match
import sign_in
from data_text import plain

KIND = "VOLLZOGEN"
SLUG = "vollzogen"
TABLE = "vollzogen_records"
# The columns a file can change on a stored record (the order of the table), and which of them are dates.
FIELDS = ["found_how", "baptismal_date_set_on", "workers", "unit", "stake", "zone", "confirmed", "confirmed_on", "country",
          "gender", "preferred_language", "fc_number", "new_member_id", "matched_how"]
DATES = {"baptismal_date_set_on", "confirmed_on"}
TEXTS = ["found_how", "workers", "unit", "stake", "zone", "country", "gender", "preferred_language"]


def as_day(value):
    """A date from an ISO text, a date or nothing."""
    if not value:
        return None
    return value if isinstance(value, date) else date.fromisoformat(str(value)[:10])


# --------------------------------------------------------------------------------------------- who is who

def person_key(record):
    """The key of a person of the list in the "same person?" answers: 'p:nm:vz:anna meier:2026-09-20'."""
    return f"p:nm:vz:{data_names.fold(record['full_name'])}:{record['baptism_date']}"


def stored_members(cur, mission_id):
    """The new members already in the portal (this mission), with the zone they are in and what is known for matching."""
    cur.execute("""select nm.id,nm.first_name,nm.last_name,nm.display_name,nm.baptism_date,nm.fc_number,z.name zone
      from public.new_members nm join public.areas ar on ar.id=nm.area_id join public.districts d on d.id=ar.district_id
      join public.zones z on z.id=d.zone_id where z.mission_id=%s""", (mission_id,))
    members = []
    for r in cur.fetchall():
        members.append({"id": r["id"], "label": r["display_name"], "folded": data_names.fold(r["display_name"]),
                        "baptism_date": r["baptism_date"], "fc": r["fc_number"], "zone": r["zone"],
                        "zone_key": data_names.fold_zone(r["zone"])})
    return members


def judge(record, member, decisions):
    """'same', 'ask' or None (different people) for a person of the list and a stored new member.

    Order: the same FC number is the same person (this is decided before, in match_records); two different FC numbers are
    never joined; a manager's remembered answer; a clashing baptism date means different people; then the name:
    the same name with the same zone or the same baptism date is the same person, the same name with nothing to back
    it up, or a very alike name with the zone or the date agreeing, is asked."""
    if record.get("fc_number") and member["fc"] and record["fc_number"] != member["fc"]:
        return None
    answer = decisions.get(match.pair_key(person_key(record), match.stored_key(match.NEW_MEMBER, member["id"])))
    if answer is not None:
        return "same" if answer else None
    day = as_day(record["baptism_date"])
    if member["baptism_date"] and day and member["baptism_date"] != day:
        return None
    same_zone = bool(record.get("zone")) and data_names.fold_zone(record["zone"]) == member["zone_key"]
    same_day = bool(member["baptism_date"] and day and member["baptism_date"] == day)
    folded = data_names.fold(record["full_name"])
    if folded == member["folded"]:
        return "same" if same_zone or same_day else "ask"
    if (same_zone or same_day) and match.similar_names(folded, member["folded"]):
        return "ask"
    return None


def match_records(records, members, decisions):
    """Who each person of the list is among the stored new members.
    Returns {links: {record_key: {member_id, how}}, questions: [{keys, record, member, reason}], notices: [text]}.
    A person with an FC number that a stored member has is linked at once (the lowest id when several have it, with a
    notice). Otherwise one sure match is linked (how NAME, or ASKED after a manager's remembered answer); two sure
    matches, or only unsure ones, become questions."""
    links, questions, notices = {}, [], []
    by_fc = {}
    for member in members:
        if member["fc"]:
            by_fc.setdefault(member["fc"], []).append(member)
    for fc, owners in sorted(by_fc.items()):
        if len(owners) > 1:
            notices.append(plain("uploads.people.fcTwiceStored", fc=fc, count=len(owners),
                                 names=", ".join(sorted(o["label"] for o in owners))))
    for record in records:
        key = record["record_key"]
        owners = sorted(by_fc.get(record.get("fc_number"), []), key=lambda m: m["id"]) if record.get("fc_number") else []
        if owners:
            links[key] = {"member_id": owners[0]["id"], "how": "FC"}
            continue
        verdicts = [(judge(record, member, decisions), member) for member in members]
        same = [m for v, m in verdicts if v == "same"]
        ask = [m for v, m in verdicts if v == "ask"]
        if len(same) == 1 and not ask:
            remembered = decisions.get(match.pair_key(person_key(record), match.stored_key(match.NEW_MEMBER, same[0]["id"])))
            links[key] = {"member_id": same[0]["id"], "how": "ASKED" if remembered else "NAME"}
            continue
        for member in same + ask:
            questions.append({"keys": match.pair_key(person_key(record), match.stored_key(match.NEW_MEMBER, member["id"])),
                              "record": record, "member": member,
                              "reason": "same_name_unsure" if member["folded"] == data_names.fold(record["full_name"])
                              else "alike_name"})
    questions.sort(key=lambda q: q["keys"])
    return {"links": links, "questions": questions, "notices": notices}


# --------------------------------------------------------------------------------------------- what is stored

def stored_records(cur, mission_id):
    """{record_key: stored row} of this mission."""
    cur.execute("select * from public.vollzogen_records where mission_id=%s", (mission_id,))
    return {r["record_key"]: r for r in cur.fetchall()}


def merged_values(old, record, link):
    """The columns of a record after this upload: {column: value} for FIELDS. old: the stored row or None. The file's
    filled cells win; an empty cell keeps what is saved; "confirmed" never goes back; an FC number and a link already
    saved are kept."""
    values = {}
    for field in FIELDS:
        stored = old[field] if old else None
        if field == "new_member_id":
            values[field] = stored if stored else (link["member_id"] if link else None)
        elif field == "matched_how":
            values[field] = stored if (old and old["new_member_id"]) else (link["how"] if link else None)
        elif field == "fc_number":
            values[field] = stored or record.get("fc_number")
        elif field == "confirmed":
            values[field] = bool(stored) or bool(record.get("confirmed"))
        elif field in DATES:
            values[field] = as_day(record.get(field)) or (as_day(stored) if stored else None)
        else:
            values[field] = record.get(field) or stored
    return values


def plan(cur, records):
    """What the upload would do: the matching, the questions and the numbers.
    Returns {found (match_records), stored, counts {new, changed, same, linked, by_fc, by_name, asked, unlinked}}."""
    mission = sign_in.current_mission_id()
    members = stored_members(cur, mission)
    decisions = match.load_decisions(cur, mission)
    found = match_records(records, members, decisions)
    stored = stored_records(cur, mission)
    counts = {"new": 0, "changed": 0, "same": 0}
    for record in records:
        old = stored.get(record["record_key"])
        values = merged_values(old, record, found["links"].get(record["record_key"]))
        if not old:
            counts["new"] += 1
        elif any(values[f] != (old[f] if f not in DATES else as_day(old[f])) for f in FIELDS):
            counts["changed"] += 1
        else:
            counts["same"] += 1
    linked = [merged_values(stored.get(r["record_key"]), r, found["links"].get(r["record_key"]))
              for r in records]
    counts.update(linked=sum(1 for v in linked if v["new_member_id"]),
                  by_fc=sum(1 for v in linked if v["new_member_id"] and v["matched_how"] == "FC"),
                  by_name=sum(1 for v in linked if v["new_member_id"] and v["matched_how"] == "NAME"),
                  asked=sum(1 for v in linked if v["new_member_id"] and v["matched_how"] == "ASKED"))
    counts["unlinked"] = len(records) - counts["linked"]
    return {"found": found, "stored": stored, "counts": counts}


def apply(pending):
    """Applies a checked upload in one batch. Returns the batch id, or None when nothing is new or changed.
    Raises ValueError while a "same person?" question is open."""
    conn = database.connect()
    try:
        with database.cursor(conn) as cur:
            cur.execute("select id from public.missions where id=%s for update", (sign_in.current_mission_id(),))
        batches.lock_tables(conn, [TABLE])
        records = pending["parsed"]["records"]
        with database.cursor(conn) as cur:
            planned = plan(cur, records)
            if planned["found"]["questions"]:
                raise ValueError(plain("uploads.vollzogen.answerFirst"))
            before = batches.snapshot(conn, [TABLE])
            save_records(cur, records, planned)
        after = batches.snapshot(conn, [TABLE])
        if not batches.count_changes([TABLE], before, after):
            conn.rollback()
            return None
        counts = planned["counts"]
        batch = batches.create_batch(conn, KIND, pending["filename"], None, {
            "rows_in_file": pending["parsed"]["rows_read"], "people_new": counts["new"], "people_changed": counts["changed"],
            "people_unchanged": counts["same"], "linked_to_people": counts["linked"], "linked_by_fc": counts["by_fc"]})
        changed = batches.record_changes(conn, batch, [TABLE], before, after)
        batches.add_to_summary(conn, batch, {"changed_rows": changed})
        conn.commit()
        return batch
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def save_records(cur, records, planned):
    """Inserts the new people of the list and updates the changed ones (the merge is merged_values)."""
    mission = sign_in.current_mission_id()
    for record in records:
        old = planned["stored"].get(record["record_key"])
        values = merged_values(old, record, planned["found"]["links"].get(record["record_key"]))
        if old is None:
            columns = ["mission_id", "record_key", "full_name", "baptism_date"] + FIELDS + ["updated_by"]
            params = [mission, record["record_key"], record["full_name"], as_day(record["baptism_date"])] \
                + [values[f] for f in FIELDS] + [sign_in.actor_name()]
            cur.execute(sql.SQL("insert into public.vollzogen_records ({}) values ({})").format(
                sql.SQL(",").join(map(sql.Identifier, columns)), sql.SQL(",").join(sql.Placeholder() * len(columns))), params)
        elif any(values[f] != (old[f] if f not in DATES else as_day(old[f])) for f in FIELDS):
            cur.execute(sql.SQL("update public.vollzogen_records set {},updated_at=now(),updated_by=%s where id=%s").format(
                sql.SQL(",").join(sql.SQL("{}=%s").format(sql.Identifier(f)) for f in FIELDS)),
                [values[f] for f in FIELDS] + [sign_in.actor_name(), old["id"]])


def table_rows(cur, limit=1000):
    """The stored list for the read-only table page, newest baptism first, with the name of the linked person."""
    cur.execute("""select v.*,nm.display_name linked_name from public.vollzogen_records v
      left join public.new_members nm on nm.id=v.new_member_id where v.mission_id=%s
      order by v.baptism_date desc,v.full_name limit %s""", (sign_in.current_mission_id(), limit))
    return cur.fetchall()
