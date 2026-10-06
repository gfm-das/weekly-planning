"""The People upload: new members (names and details) from a spreadsheet, for example the office's "Vollzogen" sheets
or the "New Member Database Raw" form. The rules are here, the pages are in people_upload_pages.py.

Steps, like the other uploads:
  1. Upload: a CSV or XLSX is read in memory (data_types.parse_people) and its rows wait for Apply.
  2. Check: each row gets its area (the area name, or else the ward or branch), and people_match works out who is
     already stored. A name of the file that is not a portal area is asked once and remembered (data_names.py).
  3. Apply: in one batch in Import history (kind PEOPLE, Undo puts everything back): people are made or, when already
     stored, only their blanks are filled (people_write.py); then the people who are still relevant are loaded into
     the plans of the current week.

A person is placed in the area named in the file. When that area is closed, the standard is to move them to a current
area: the check asks for it ("Old" areas are in the list, so keeping them there is possible too) and remembers the answer.
A row with no area is placed by its ward or branch when only one open area serves it; otherwise it is left out and
counted.
"""
from datetime import date

import batches
import data_names
import database
import historical_units
import people_match as match
import people_write
import sign_in

KIND = "PEOPLE"
SLUG = "people"


def as_day(text):
    return date.fromisoformat(text) if text else None


def place_records(cur, matcher, records):
    """Gives every record area_id (and unit_id). Returns (names still to match, rows with no area).
    names: {(level, name): {"rows": n, "zones": {...}}} as data_names.place_all gives them."""
    mapped = mapped_labels(cur)
    left = []
    for record in records:
        area_id = mapped.get(" ".join(str(record.get("area") or "").split()).casefold())
        if area_id in matcher.area_by_id:  # the old companionship name is already in Area mappings: use that
            record["area_id"], record["zone_id"] = area_id, matcher.area_by_id[area_id]["zone_id"]
        elif record.get("area"):
            left.append(record)
    questions = data_names.place_all(matcher, left, "area")
    for record in records:
        if not record.get("area"):  # no area named: the ward or branch decides (below); a zone name is never asked about
            record["area_id"], record["zone_id"] = None, matcher.zone_id_quietly(record.get("zone") or "")
    units, zones = historical_units.unit_catalog(cur)
    unplaced = 0
    for record in records:
        area_id = record.get("area_id")
        if area_id and not matcher.area_by_id[area_id]["active"] and ("area", data_names.fold(record["area"])) not in matcher.remembered:
            # A closed area that no manager has answered for yet: ask where its people go (the standard: a current area).
            entry = questions.setdefault(("area", record["area"]), {"rows": 0, "zones": set()})
            entry["rows"] += 1
            if record.get("zone"):
                entry["zones"].add(record["zone"])
        if not area_id and not record.get("area"):
            record["area_id"] = area_from_ward(record, units, matcher)
        area_id = record.get("area_id")
        if not area_id:
            if not any(q[1] == record.get("area") for q in questions):
                unplaced += 1
            continue
        unit, _how, _sure = historical_units.resolve_unit(record.get("ward"), record.get("area") or "", area_id, units, zones)
        record["unit_id"] = unit["id"] if unit else None
    return questions, unplaced


def mapped_labels(cur):
    """{old companionship name in small letters: area id} of the confirmed Area mappings (the page the Historical CSV
    uses), so one name is matched once for both."""
    cur.execute("""select source_companionship,target_area_id from public.import_weekly_planning_area_map
      where (mission_id=%s or mission_id is null) and target_area_id is not null and confirmed_at is not null""",
                (sign_in.current_mission_id(),))
    return {" ".join(r["source_companionship"].split()).casefold(): r["target_area_id"] for r in cur.fetchall()}


def area_from_ward(record, units, matcher):
    """The one open area that serves the ward or branch of a row without an area name (inside its zone when the
    file gives one); None when it is not clear."""
    ward = historical_units.unit_norm(record.get("ward"))
    if not ward:
        return None
    found = [u for u in units if ward in (u["norm"], u["base"])]
    areas = {a for u in found for a in u["area_ids"] if a in matcher.area_by_id and matcher.area_by_id[a]["active"]}
    zone_id = record.get("zone_id")
    if zone_id and len(areas) > 1:
        areas = {a for a in areas if matcher.area_by_id[a]["zone_id"] == zone_id}
    return next(iter(areas)) if len(areas) == 1 else None


def appearances_of(records):
    """The records that have an area, as appearances for people_match."""
    out = []
    for number, record in enumerate(records, start=1):
        if not record.get("area_id"):
            continue
        profile = {k: record.get(k) for k in people_write.PROFILE_FIELDS}
        for field in ("baptismal_date_extended", "baptism_date", "confirmation_date", "date_of_birth"):
            profile[field] = as_day(record.get(field))
        out.append({"kind": match.NEW_MEMBER, "name": " ".join(x for x in (record["first"], record["last"]) if x),
                    "first": record["first"], "last": record["last"], "area_id": record["area_id"],
                    "unit_id": record.get("unit_id"), "sunday": None, "order": number, "target": None,
                    "baptism_date": as_day(record["baptism_date"]), "profile": profile, "weekly": None})
    return out


def plan(cur, records):
    """What the upload would do: the names to match, the people question pairs, and the numbers.
    Returns {matcher, names, unplaced, found (people_match.resolve), counts}."""
    mission = sign_in.current_mission_id()
    matcher = data_names.Matcher(cur, mission)
    names, unplaced = place_records(cur, matcher, records)
    decisions = match.load_decisions(cur, mission)
    found = match.resolve(match.group_people(appearances_of(records)), match.stored_people(cur, mission), decisions)
    counts = {"people": len(found["groups"]), "to_join": sum(1 for g in found["groups"] if g["stored_id"]),
              "unplaced": unplaced}
    return {"matcher": matcher, "names": names, "unplaced": unplaced, "found": found, "counts": counts}


def apply(pending):
    """Applies a checked upload in one batch. Returns the batch id. Raises ValueError when names or pairs are still open."""
    conn = database.connect()
    try:
        with database.cursor(conn) as cur:
            cur.execute("select id from public.missions where id=%s for update", (sign_in.current_mission_id(),))
        batches.lock_tables(conn, batches.PEOPLE_UPLOAD_TABLES)
        with database.cursor(conn) as cur:
            planned = plan(cur, pending["parsed"]["records"])
            if planned["names"]:
                raise ValueError("Match the names of the file to areas first.")
            if planned["found"]["questions"]:
                raise ValueError("Answer the questions about people who may be the same person first.")
            if not planned["found"]["groups"]:
                conn.rollback()
                return None
            before = batches.snapshot(conn, batches.PEOPLE_UPLOAD_TABLES)
            batch = batches.create_batch(conn, KIND, pending["filename"], None, {"rows": len(pending["parsed"]["records"])})
            counts = people_write.write_people(cur, planned["found"]["groups"], {})
            counts["current_week_plans_filled"] = people_write.fill_current_week(cur)
            counts["rows_without_area"] = planned["unplaced"]
        changed = batches.record_changes(conn, batch, batches.PEOPLE_UPLOAD_TABLES, before,
                                         batches.snapshot(conn, batches.PEOPLE_UPLOAD_TABLES))
        batches.add_to_summary(conn, batch, {"changed_rows": changed, **counts})
        conn.commit()
        return batch
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
