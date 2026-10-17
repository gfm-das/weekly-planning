"""Separate: take one old label's numbers out of the reports they were added to, and give them back to its own area.

Numbers of two old labels end up in one report only through a "Combined companionship" mapping (or through the
"Combine" choice that imports had before round 19). Every label of such a report is listed in its
historical_planning_details row ('Idar + Baumholder'), and the label's own numbers, notes and answers are still in the
import tables (import_weekly_planning_reports and the detail tables, by report key). So separate():
  1. takes the label's numbers off the combined report (never below 0) and its notes and details out of it;
  2. writes them into a new report of the label's own area (same week and unit), with the label's report key;
  3. refuses, changing nothing, when the label's original numbers are missing or that area already has a report.
separate_batch() records the change as a batch in Import history, so Undo puts everything back.
"""
from psycopg2 import sql

import batches
import database
import historical_apply
import historical_preview
import sign_in

TABLES = ["weekly_area_reports", "historical_planning_details"]
DETAILS = [kind for kind, _ in historical_apply.DETAIL_TABLES]


def summed_labels(cur):
    """{label in small letters: how many reports of this mission hold its numbers added to another label's}."""
    cur.execute(r"""select lower(btrim(x)) label,count(*) n from public.historical_planning_details d
      join public.weekly_area_reports r on r.id=d.weekly_area_report_id join public.areas a on a.id=r.area_id
      join public.districts di on di.id=a.district_id join public.zones z on z.id=di.zone_id
      cross join lateral regexp_split_to_table(d.source_companionship,' \+ ') x
      where z.mission_id=%s and d.source_companionship like '%% + %%' group by 1""", (sign_in.current_mission_id(),))
    return {r["label"]: r["n"] for r in cur.fetchall()}


def staged(cur, label, report):
    """The label's own staged report for the week (and unit) of a report, or None when it is missing or unclear."""
    cur.execute("""select * from public.import_weekly_planning_reports
      where lower(source_companionship)=lower(%s) and reporting_sunday=%s order by source_report_key""", (label, report["sunday"]))
    rows = cur.fetchall()
    rows = [r for r in rows if r["source_report_key"] == report["historical_source_key"]] or \
        [r for r in rows if r["source_report_key"].endswith(f"@u{report['unit_id']}")] or rows
    return rows[0] if len(rows) == 1 else None


def details_sql(keep):
    """[(column, its list with only the entries of one report key (keep) or without them)] for the four detail lists."""
    test = "=" if keep else "<>"
    return [(sql.Identifier(c), sql.SQL("(select coalesce(jsonb_agg(e),'[]'::jsonb) from jsonb_array_elements({c}) e "
                                         "where e->>'source_report_key'" + test + "%(key)s)").format(c=sql.Identifier(c))) for c in DETAILS]


def separate(cur, label, area):
    """Separates the label (see the top of this file) into area. Returns how many reports were separated. Raises
    ValueError (and the caller saves nothing) when it cannot be done completely."""
    cur.execute(r"""select r.*,w.sunday,d.source_companionship labels,d.source_unit units from public.weekly_area_reports r
      join public.reporting_weeks w on w.id=r.reporting_week_id join public.historical_planning_details d on d.weekly_area_report_id=r.id
      where d.source_companionship like '%% + %%' and lower(%s)=any(select lower(btrim(x)) from regexp_split_to_table(d.source_companionship,' \+ ') x)
      order by w.sunday,r.id for update of r""", (label,))
    reports = cur.fetchall()
    if not reports:
        raise ValueError(f"'{label}' is not added together with another area in any report. Nothing was changed.")
    metrics = historical_apply.metrics()
    for r in reports:
        labels = historical_preview.report_labels(r["labels"])
        mine = staged(cur, label, r)
        rest = [x for x in labels if x.casefold() != label.casefold()]
        holder = staged(cur, rest[0], r) if mine and r["historical_source_key"] == mine["source_report_key"] else None
        if not mine or (r["historical_source_key"] == mine["source_report_key"] and not holder):
            raise ValueError(f"The original numbers of '{label}' for {r['sunday']} are not in the import tables. Nothing was changed.")
        cur.execute("select id from public.weekly_area_reports where area_id=%s and reporting_week_id=%s and unit_id is not distinct from %s",
                    (area["id"], r["reporting_week_id"], r["unit_id"]))
        if cur.fetchone():
            raise ValueError(f"{area['name']} already has a report for {r['sunday']}, so '{label}' cannot be separated into it. Nothing was changed.")
        units = (r["units"] or "").split(" + ")
        if mine["source_unit"] in units:
            units.remove(mine["source_unit"])
        values = {"key": mine["source_report_key"], "id": r["id"], "area": area["id"], "label": label, "unit": mine["source_unit"],
                  "rest": " + ".join(rest), "rest_units": " + ".join(units) or None, "notes": mine["notes"] or "",
                  "holder_key": holder["source_report_key"] if holder else r["historical_source_key"],
                  "holder_area": rest[0] if holder else r["historical_source_area"], **{f"m_{m}": mine[m] or 0 for m in metrics}}
        # 1. the combined report without the label's numbers, notes and report key
        sets = [sql.SQL("{c}=greatest(coalesce({c},0)-%({p})s,0)").format(c=sql.Identifier(m), p=sql.SQL(f"m_{m}")) for m in metrics]
        cur.execute(sql.SQL("""update public.weekly_area_reports set {},historical_source_key=null,
          notes=nullif(btrim(regexp_replace(replace(coalesce(notes,''),%(notes)s,''),'\\n{{3,}}',E'\\n\\n','g'),E'\\n'),''),
          updated_at=now() where id=%(id)s""").format(sql.SQL(",").join(sets)), values)
        # 2. the label's own report and details, in its own area
        cur.execute(sql.SQL("""insert into public.weekly_area_reports (area_id,unit_id,reporting_week_id,status,submitted_at,notes,
          historical_source_area,historical_source_key,import_batch_id,{}) select %(area)s,unit_id,reporting_week_id,'SUBMITTED',%(ts)s,
          nullif(%(notes)s,''),%(label)s,%(key)s,import_batch_id,{} from public.weekly_area_reports where id=%(id)s returning id""").format(
            sql.SQL(",").join(map(sql.Identifier, metrics)), sql.SQL(",").join(sql.Placeholder(f"m_{m}") for m in metrics)),
            {**values, "ts": mine["source_timestamp"]})
        values["new"] = cur.fetchone()["id"]
        cur.execute(sql.SQL("""insert into public.historical_planning_details (weekly_area_report_id,source_companionship,source_unit,{})
          select %(new)s,%(label)s,%(unit)s,{} from public.historical_planning_details where weekly_area_report_id=%(id)s""").format(
            sql.SQL(",").join(map(sql.Identifier, DETAILS)), sql.SQL(",").join(f for _, f in details_sql(True))), values)
        cur.execute(sql.SQL("update public.historical_planning_details set source_companionship=%(rest)s,source_unit=%(rest_units)s,{} "
                            "where weekly_area_report_id=%(id)s").format(sql.SQL(",").join(sql.SQL("{}={}").format(c, f) for c, f in details_sql(False))), values)
        cur.execute("update public.weekly_area_reports set historical_source_key=%(holder_key)s,historical_source_area=%(holder_area)s where id=%(id)s", values)
    return len(reports)


def separate_batch(conn, label, area):
    """separate() as one HISTORICAL batch of Import history (so it can be undone). Returns (batch id, reports). The
    caller commits."""
    batches.lock_tables(conn, TABLES)
    before = batches.snapshot(conn, TABLES)
    with database.cursor(conn) as cur:
        count = separate(cur, label, area)
    batch = batches.create_batch(conn, "HISTORICAL", f"Separate {label}".replace("/", "-"), None, {"separated": label, "reports": count})
    batches.add_to_summary(conn, batch, {"changed_rows": batches.record_changes(conn, batch, TABLES, before, batches.snapshot(conn, TABLES))})
    return batch, count
