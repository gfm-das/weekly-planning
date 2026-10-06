"""Historical CSV, step 3: Apply. Writes a checked Weekly Planning export into the reports, as one batch.

apply_batch() locks the tables, runs the check (historical_preview.preview) again, and refuses when anything differs
from what the manager reviewed (the state token and the choices). Then, in one transaction:
  - the original rows and answers are kept in the staging tables (historical_import.stage_rows);
  - each area/unit/week gets one report in weekly_area_reports (a new one, the existing one replaced, or an earlier
    import of the label moved here); several old areas combined into one report are added up;
  - every detail (answers, new members, friends) is kept in historical_planning_details;
  - the people become real records and appear on the weekly plans they were named on, and those who are still
    relevant are loaded into the plans of the current week (write_people);
  - every changed row is written down, so Import history can undo the whole batch (batches.py, undo.py).
"""
import hmac
import json

import psycopg2.extras
from psycopg2 import sql

import batches
import database
import historical_import as historical
import historical_preview
import people_write
import sign_in

# The staging tables of the details, and where each goes in historical_planning_details.
DETAIL_TABLES = [("answers", "import_weekly_planning_answers"), ("new_members", "import_weekly_new_members"),
                 ("baptismal_date_friends", "import_weekly_baptismal_date_friends"),
                 ("high_potential_friends", "import_weekly_high_potential_friends")]


def apply_batch(path, filename, replace_existing=True, combine_mapped=True, choices=None, state_token=None,
                expected_choices=None):
    """Applies a checked upload. The page passes the manager's choices and the check's state token; a missing, stale
    or tampered choice raises ValueError before anything is written. Returns the batch id."""
    conn = database.connect()
    try:
        with database.cursor(conn) as cur:
            cur.execute("select id from public.missions where id=%s for update", (sign_in.current_mission_id(),))
        batches.lock_tables(conn, batches.HISTORICAL_TABLES)
        checked = historical_preview.preview(path, conn, replace_existing, combine_mapped, choices)
        refuse_if_changed(checked, state_token, expected_choices)
        before = batches.snapshot(conn, batches.HISTORICAL_TABLES)
        batch = batches.create_batch(conn, "HISTORICAL", filename, None,
                                     {"reports": len(checked["rows"]), "duplicates_skipped": checked["duplicates"]})
        historical.stage_rows(conn, [item["row"] for item in checked["rows"]])
        with database.cursor(conn) as cur:
            moved, removed, written = write_reports(cur, checked, batch)
            people = write_people(cur, checked, written)
        count = batches.record_changes(conn, batch, batches.HISTORICAL_TABLES, before, batches.snapshot(conn, batches.HISTORICAL_TABLES))
        batches.add_to_summary(conn, batch, {"changed_rows": count, **people, **({"moved_reports": len(moved)} if moved else {}),
                                             **({"removed_reports": len(removed)} if removed else {})})
        conn.commit()
        return batch
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def write_people(cur, checked, written):
    """The new members, friends and high-potential friends of the rows (people_match.py, people_write.py), and then the
    plans of the current week. Returns the numbers for the batch's summary."""
    found = checked["people"]
    counts = people_write.write_people(cur, found["groups"], written)
    people_write.write_high_potentials(cur, found["high_potentials"], written, counts)
    counts["current_week_plans_filled"] = people_write.fill_current_week(cur)
    return counts


def refuse_if_changed(checked, state_token, expected_choices):
    """Raises ValueError when the check has problems or open choices, or differs from what the manager reviewed."""
    if checked["errors"] or checked["pending"]:
        raise ValueError("\n".join(checked["errors"] + checked["pending"]))
    if expected_choices is not None and json.loads(json.dumps(checked["effective_choices"], default=str)) != expected_choices:
        raise ValueError("The submitted choices do not match the reviewed preview. Recheck the preview and choose again.")
    if state_token is not None and not hmac.compare_digest(str(state_token), checked["state_token"]):
        raise ValueError("The upload, your choices, or the existing reports changed since you reviewed the preview. "
                         "Recheck the preview and choose again.")


def write_reports(cur, checked, batch):
    """One report per target area, week and unit: the existing one, else a remapped report moved here, else a new
    one. Returns (ids of the moved reports, ids of the removed reports)."""
    group_report = dict(checked["target_reports"])
    moved, removed = set(), []
    for info in checked["stale_reports"].values():
        if info["target"] not in group_report:
            group_report[info["target"]] = info["id"]
            moved.add(info["id"])
        else:
            removed.append(info["id"])
    touched = list(group_report.values()) + removed
    if touched:
        # Keys are given out again below; clear them first so they never collide half-way through the batch.
        cur.execute("update public.weekly_area_reports set historical_source_key=null where id=any(%s)", (touched,))
    if removed:
        # Only reports this importer made, without portal planning rows, get here (checked in the preview); their
        # details go with them, and the batch's record lets Undo put both back.
        cur.execute("delete from public.weekly_area_reports where id=any(%s)", (removed,))
    written = {}
    for item in checked["rows"]:
        staged = staged_report(cur, item["key"])
        target = (item["area"]["id"], item["sunday"], item["unit_id"])
        if target in written:
            add_to_report(cur, written[target], staged)
        else:
            written[target] = write_report(cur, item, staged, batch, group_report.get(target), moved)
        write_details(cur, written[target], item, staged)
    return moved, removed, written


def staged_report(cur, key):
    """The row's report as historical_import staged it (its key indicators, notes and time)."""
    cur.execute("select * from public.import_weekly_planning_reports where source_report_key=%s", (key,))
    return cur.fetchone()


def week_id(cur, sunday):
    """The reporting week of a Sunday (made when it is not there yet)."""
    cur.execute("select id from public.reporting_weeks where sunday=%s", (sunday,))
    week = cur.fetchone()
    if not week:
        cur.execute("insert into public.reporting_weeks(sunday) values(%s) returning id", (sunday,))
        week = cur.fetchone()
    return week["id"]


def metrics():
    """The key indicator columns of weekly_area_reports that the old form fills."""
    return sorted(set(historical.REPORT_COLUMNS.values()))


def add_to_report(cur, report_id, staged):
    """Combines another old area into the report already written in this batch: the numbers are added up. The first
    (alphabetical) label keeps historical_source_area and historical_source_key."""
    columns = metrics()
    sets = [sql.SQL("{}=coalesce({},0)+%s").format(sql.Identifier(m), sql.Identifier(m)) for m in columns]
    sets += [sql.SQL("notes=concat_ws(E'\\n\\n',notes,%s)"),
             sql.SQL("submitted_at=greatest(submitted_at,%s)")]
    cur.execute(sql.SQL("update public.weekly_area_reports set {},updated_at=now() where id=%s").format(sql.SQL(",").join(sets)),
                [staged[m] or 0 for m in columns] + [staged["notes"], staged["source_timestamp"], report_id])


def write_report(cur, item, staged, batch, report_id, moved):
    """Writes the report of one area, week and unit: replaces the existing one (report_id), or makes a new one.
    Returns its id."""
    values = {"reporting_week_id": week_id(cur, item["sunday"]), "status": "SUBMITTED",
              "submitted_at": staged["source_timestamp"], "notes": staged["notes"], "historical_source_area": item["source"],
              "historical_source_key": item["key"], "import_batch_id": batch, **{m: staged[m] or 0 for m in metrics()}}
    if not report_id:
        values.update(area_id=item["area"]["id"], unit_id=item["unit_id"])
        cur.execute(sql.SQL("insert into public.weekly_area_reports ({}) values ({}) returning id").format(
            sql.SQL(",").join(map(sql.Identifier, values)), sql.SQL(",").join([sql.Placeholder()] * len(values))), list(values.values()))
        return cur.fetchone()["id"]
    # The first take-over of an existing report in this batch: its details are replaced, never merged.
    cur.execute("delete from public.historical_planning_details where weekly_area_report_id=%s", (report_id,))
    if report_id in moved:
        # A remapped (or earlier unit-less) import moves to this area and unit.
        values.update(area_id=item["area"]["id"], unit_id=item["unit_id"])
    # A replaced report already belongs to this area, unit and week.
    cur.execute(sql.SQL("update public.weekly_area_reports set {},updated_at=now() where id=%s").format(
        sql.SQL(",").join(sql.SQL("{}=%s").format(sql.Identifier(c)) for c in values)), list(values.values()) + [report_id])
    return report_id


def write_details(cur, report_id, item, staged):
    """Keeps every staged detail of the row with its report. The "on conflict" part only runs when labels are combined
    within this batch (the details were deleted at the first take-over): each entry keeps its source_report_key, and
    all labels are listed in order."""
    details = {}
    for kind, table in DETAIL_TABLES:
        cur.execute(sql.SQL("select to_jsonb(t) row from public.{} t where source_report_key=%s").format(sql.Identifier(table)), (item["key"],))
        details[kind] = [r["row"] for r in cur.fetchall()]
    cur.execute("""insert into public.historical_planning_details
      (weekly_area_report_id,source_companionship,source_unit,answers,new_members,baptismal_date_friends,high_potential_friends)
      values(%s,%s,%s,%s,%s,%s,%s) on conflict(weekly_area_report_id) do update set
      source_companionship=concat_ws(' + ',public.historical_planning_details.source_companionship,excluded.source_companionship),
      source_unit=concat_ws(' + ',public.historical_planning_details.source_unit,excluded.source_unit),
      answers=public.historical_planning_details.answers||excluded.answers,
      new_members=public.historical_planning_details.new_members||excluded.new_members,
      baptismal_date_friends=public.historical_planning_details.baptismal_date_friends||excluded.baptismal_date_friends,
      high_potential_friends=public.historical_planning_details.high_potential_friends||excluded.high_potential_friends""",
                (report_id, item["source"], staged["source_unit"], *[psycopg2.extras.Json(details[k]) for k, _ in DETAIL_TABLES]))
