"""Data uploads: the numbers the portal does not collect itself (the rules; the pages are data_upload_pages.py).

Six uploads, each with the same four steps:
  1. Upload: download the template, pick a CSV or XLSX file. The file is read in memory and never saved.
  2. Check: row counts, problems, and how the data joins what is already stored (check_upload).
  3. Match names: zone and area names that are not portal names are matched once (or kept as historical names)
     and remembered for later uploads (data_names.py).
  4. Apply: one batch in Import history, where it can be undone (apply_upload, undo_rows).

How the files are read: data_files.py (CSV and XLSX cells) and data_types.py (each kind of upload). Every text the
pages show: data_text.py. Where the numbers are stored and how dashboards read them:
portal-api/migrations/history/033_data_uploads.sql.

No names are ever stored. A Church person id (finding export) is stored only as a code made with a secret
(person_key), so it cannot be read back.
"""
import hashlib
import hmac
import json
import os
import re
import secrets
import time
from datetime import date
from pathlib import Path

import psycopg2.extras
from flask import session
from psycopg2 import sql

import batches
import data_files
import data_names
import data_types
import database
import page
import settings
import sign_in
from data_files import FileProblem, clean
from data_text import plain, t

# Batches whose rows live in their own table (each row carries its batch id; Undo removes them). Area data instead
# records its changed rows like every other batch (batches.py).
ROW_KINDS = {"FINDING", "ZONE_HISTORY", "REFERRAL_ARCHIVE", "RATES", "BAPTISMS"}
AREA_TABLES = batches.AREA_DATA_TABLES
# How Import history names each kind (text keys of data_text.py).
KIND_LABELS = {"AREA_DATA": "uploads.kind.areas", "FINDING": "uploads.kind.finding",
               "ZONE_HISTORY": "uploads.kind.zoneHistory", "REFERRAL_ARCHIVE": "uploads.kind.referralArchive",
               "RATES": "uploads.kind.rates", "BAPTISMS": "uploads.kind.baptisms"}

# One entry per upload page. level: which names are matched ('area' falls back to the zone when a row has no
# area). historical: whether a name may be kept as a historical name (for area data this means "leave the row
# out": area data is only stored for portal areas). table: where the rows of a finding or weekly upload go.
UPLOADS = {
    "areas": {"kind": "AREA_DATA", "text": "areas", "level": "area", "historical": True},
    "finding": {"kind": "FINDING", "text": "finding", "level": "area", "historical": True, "table": "finding_people"},
    "zone-history": {"kind": "ZONE_HISTORY", "text": "zoneHistory", "level": "zone", "historical": True,
                     "table": "zone_history_weeks"},
    "referral-archive": {"kind": "REFERRAL_ARCHIVE", "text": "referralArchive", "level": "area", "historical": True,
                         "table": "referral_archive_weeks"},
    "rates": {"kind": "RATES", "text": "rates", "level": "zone", "historical": True, "table": "finding_rate_weeks"},
    "baptisms": {"kind": "BAPTISMS", "text": "baptisms", "level": "area", "historical": True,
                 "table": "baptism_history_weeks"},
}
TABLE_OF_KIND = {spec["kind"]: spec["table"] for spec in UPLOADS.values() if "table" in spec}
# Archived uploads (migration 038, Oct 2026: FindeChristus is archived). The Data uploads page no longer offers them;
# their page, template, check and Apply still work at their address, and Import history keeps (and can undo) every
# earlier upload. Put a slug back by removing it here.
ARCHIVED_UPLOADS = {"referral-archive"}

# The columns of each weekly table and the record field that fills each one.
WEEKLY_COLUMNS = {
    "zone-history": [("sunday", "sunday"), ("zone_id", "zone_id"), ("zone_name", "zone")]
                    + [(f, f) for f in data_types.ZONE_HISTORY_FIELDS],
    "referral-archive": [("sunday", "sunday"), ("report_date", "report_date"), ("zone_id", "zone_id"),
                         ("area_id", "area_id"), ("zone_name", "zone"), ("area_name", "area"), ("source", "source")]
                        + [(f, f) for f in data_types.ARCHIVE_FIELDS],
    "rates": [("sunday", "sunday"), ("report_date", "report_date"), ("zone_id", "zone_id"), ("zone_name", "zone"),
              ("is_mission", "is_mission"), ("teaching_rate", "teaching_rate"), ("contact_rate", "contact_rate")],
    "baptisms": [("sunday", "sunday"), ("zone_id", "zone_id"), ("area_id", "area_id"), ("zone_name", "zone"),
                 ("area_name", "area"), ("ward", "ward"), ("finding_source", "finding_source"),
                 ("baptisms", "baptisms"), ("confirmations", "confirmations")],
}
FINDING_FIELDS = ["zone_id", "area_id", "zone_name", "district_name", "area_name", "finding_category", "finding_source",
                  *data_types.FINDING_DATES]
PENDING_TOKEN = re.compile(r"^[A-Za-z0-9_-]{16,64}$")
PENDING_HOURS = 24


def day_text(iso):
    """'2026-09-27' -> '27 Sep 2026' (the date style of Import history)."""
    return date.fromisoformat(str(iso)[:10]).strftime("%d %b %Y") if iso else ""


def spec_of(slug):
    """The UPLOADS entry of an upload page ('zone-history'); LookupError for an unknown one."""
    spec = UPLOADS.get(slug)
    if not spec:
        raise LookupError(slug)
    return spec


def title_of(slug):
    """The page title of an upload, for example 'Zone history'."""
    return t(f"uploads.{spec_of(slug)['text']}.title")


def kind_label(kind):
    """How Import history names a kind of batch."""
    key = KIND_LABELS.get(kind)
    return plain(key) if key else kind.replace("_", " ").title()


# --------------------------------------------------------------------------------------------- person codes

def person_secret():
    """The secret for person codes: PERSON_KEY_SECRET from the server's .env, at least 16 characters, never in the
    database. Without it a person code could be worked back from a Church person id."""
    secret = os.environ.get("PERSON_KEY_SECRET", "")
    return secret if len(secret) >= 16 else None


def person_key(person_id):
    """The code stored instead of a Church person id: the first 32 characters of HMAC-SHA256(secret, id). The same
    id always gives the same code, so a re-upload finds the person again; the id itself cannot be read back."""
    secret = person_secret()
    if not secret:
        raise FileProblem(plain("uploads.finding.noSecret"))
    return hmac.new(secret.encode(), f"gfm-person:{clean(person_id)}".encode(), hashlib.sha256).hexdigest()[:32]


def person_code_check():
    """A short fingerprint of the secret, saved with each finding upload: if the secret ever changes, the codes
    change too and a re-upload would count everyone twice, so Apply stops instead."""
    return hmac.new(person_secret().encode(), b"gfm-person-code-check", hashlib.sha256).hexdigest()[:12]


# --------------------------------------------------------------------------------------------- the waiting upload
# Between the check and Apply, the rows read from the file wait in a small JSON file on the server (never the
# uploaded file itself; person ids are already codes, names were never read). Apply or Cancel deletes it; any
# left behind are deleted once they are a day old, by the next DA Management request (tidy_now_and_then).

def pending_path(token):
    """The file where the rows of a checked upload wait for Apply."""
    return settings.UPLOAD_DIR / f"data-{token}.json"


def clear_old_pending():
    """Deletes waiting files older than PENDING_HOURS."""
    limit = time.time() - PENDING_HOURS * 3600
    for path in settings.UPLOAD_DIR.glob("data-*.json"):
        try:
            if path.stat().st_mtime < limit:
                path.unlink()
        except OSError:
            pass


last_tidy = 0.0  # when this worker last looked for old waiting files (seconds since 1970)


def tidy_now_and_then():
    """Runs before every DA Management request: at most every ten minutes it deletes waiting files older than a day.
    So a check that was left without Apply or Cancel is gone a day later, as soon as anyone uses DA Management,
    and not only at the next upload."""
    global last_tidy
    if time.time() - last_tidy > 600:
        last_tidy = time.time()
        clear_old_pending()


def save_pending(slug, filename, parsed):
    """Keeps the rows read from a file waiting (a small JSON file) until Apply or Cancel."""
    clear_old_pending()
    drop_pending(slug)
    token = secrets.token_urlsafe(24)
    content = {"slug": slug, "filename": Path(filename or "upload").name[:200], "mission_id": sign_in.current_mission_id(),
               "parsed": parsed.as_dict()}
    pending_path(token).write_text(json.dumps(content), encoding="utf-8")
    session[f"data_pending_{slug}"] = token


def load_pending(slug):
    """The waiting rows of this upload in this session and mission, or None."""
    token = session.get(f"data_pending_{slug}", "")
    if not PENDING_TOKEN.fullmatch(token or ""):
        return None
    try:
        content = json.loads(pending_path(token).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if content.get("slug") != slug or content.get("mission_id") != sign_in.current_mission_id():
        return None
    return content


def drop_pending(slug):
    token = session.pop(f"data_pending_{slug}", "")
    if PENDING_TOKEN.fullmatch(token or ""):
        pending_path(token).unlink(missing_ok=True)


# --------------------------------------------------------------------------------------------- reading a file

def read_upload(slug, filename, data):
    """The rows of an uploaded file as records (data_types.Parsed)."""
    rows = data_files.read_table(filename, data)
    if slug == "areas":
        return data_types.parse_area_data(rows)
    if slug == "finding":
        if not person_secret():
            raise FileProblem(plain("uploads.finding.noSecret"))
        return data_types.parse_finding(rows, person_key)
    if slug == "zone-history":
        return data_types.parse_zone_history(rows)
    if slug == "referral-archive":
        return data_types.parse_archive(rows)
    if slug == "rates":
        return data_types.parse_rates(rows)
    return data_types.parse_baptisms(rows)


def template_file(slug, cur):
    """(file name, headings, rows) of the template for an upload."""
    if slug == "areas":
        headings, rows = data_types.area_template(area_rows(cur))
    elif slug == "finding":
        headings, rows = data_types.finding_template()
    elif slug == "zone-history":
        headings, rows = data_types.zone_history_template()
    elif slug == "referral-archive":
        headings, rows = data_types.archive_template()
    elif slug == "rates":
        headings, rows = data_types.rates_template()
    else:
        headings, rows = data_types.baptism_template()
    return f"template-{slug}.csv", headings, rows


# --------------------------------------------------------------------------------------------- names

def place_records(matcher, slug, records):
    """Adds zone_id and area_id to every record; returns the names that still need a manager's match."""
    spec = spec_of(slug)
    to_place = [r for r in records if not r.get("is_mission")]  # rate rows of the whole mission have no zone
    for record in records:
        if record.get("is_mission"):
            record["zone_id"] = None
    return data_names.place_all(matcher, to_place, spec["level"])


# --------------------------------------------------------------------------------------------- saving

def area_rows(cur):
    """Every area of the mission with its area data: current areas first, older areas only when they have data."""
    cur.execute("""select a.id area_id,a.name area,d.name district,z.name zone,a.active,p.population,p.size_km2,
        case when p.population is not null and p.size_km2>0 then round(p.population/p.size_km2,1) end density_per_km2,
        p.urban_type,p.assignment_type,coalesce(p.extra,'{}'::jsonb) extra
      from public.areas a join public.districts d on d.id=a.district_id join public.zones z on z.id=d.zone_id
      left join public.area_profiles p on p.area_id=a.id
      where z.mission_id=%s and (a.active or p.area_id is not null)
      order by a.active desc,z.name,d.name,a.name""", (sign_in.current_mission_id(),))
    return cur.fetchall()


def save_area_records(conn, records, blank_keeps, filename):
    """Saves area data; returns the batch id, or None when nothing changed.

    blank_keeps=True (an upload): an empty cell keeps what is saved, and extra attributes are added to the saved
    ones. blank_keeps=False (the area table): the row is saved exactly as shown, so an empty box clears a value."""
    batches.lock_tables(conn, AREA_TABLES)
    before = batches.snapshot(conn, AREA_TABLES)
    if blank_keeps:
        new = ("coalesce(excluded.population,p.population)", "coalesce(excluded.size_km2,p.size_km2)",
               "coalesce(excluded.urban_type,p.urban_type)", "coalesce(excluded.assignment_type,p.assignment_type)",
               "p.extra||excluded.extra")
    else:
        new = ("excluded.population", "excluded.size_km2", "excluded.urban_type", "excluded.assignment_type",
               "excluded.extra")
    upsert = f"""insert into public.area_profiles as p
        (area_id,population,size_km2,urban_type,assignment_type,extra,updated_at,updated_by)
      values(%(area_id)s,%(population)s,%(size_km2)s,%(urban_type)s,%(assignment_type)s,%(extra)s,now(),%(actor)s)
      on conflict (area_id) do update set population={new[0]},size_km2={new[1]},urban_type={new[2]},
        assignment_type={new[3]},extra={new[4]},updated_at=now(),updated_by=excluded.updated_by
      where (p.population,p.size_km2,p.urban_type,p.assignment_type,p.extra)
        is distinct from ({new[0]},{new[1]},{new[2]},{new[3]},{new[4]})"""
    with database.cursor(conn) as cur:
        cur.execute("select area_id from public.area_profiles")
        saved = {r["area_id"] for r in cur.fetchall()}
        for r in records:
            empty = all(r.get(f) is None for f in ("population", "size_km2", "urban_type", "assignment_type")) \
                and not r.get("extra")
            if empty and r["area_id"] not in saved:
                continue  # never add a row that says nothing
            cur.execute(upsert, {**r, "extra": psycopg2.extras.Json(r.get("extra") or {}), "actor": sign_in.actor_name()})
    after = batches.snapshot(conn, AREA_TABLES)
    changed = batches.count_changes(AREA_TABLES, before, after)
    if not changed:
        return None
    batch = batches.create_batch(conn, "AREA_DATA", filename, None, {"areas_in_file": len(records), "areas_changed": changed})
    batches.record_changes(conn, batch, AREA_TABLES, before, after)
    return batch


def finding_row(record):
    """The stored fields of a finding record, in FINDING_FIELDS order (to compare with what is stored)."""
    names = {"zone_name": record.get("zone", ""), "district_name": record.get("district", ""),
             "area_name": record.get("area", "")}
    return tuple(names[f] if f in names else record.get(f) for f in FINDING_FIELDS)


def stored_finding_rows(cur):
    """{person code: stored fields} of the newest stored version of every person of this mission."""
    cur.execute(sql.SQL("select person_key,{} from public.finding_people_latest where mission_id=%s").format(
        sql.SQL(",").join(map(sql.Identifier, FINDING_FIELDS))), (sign_in.current_mission_id(),))
    stored = {}
    for r in cur.fetchall():
        stored[r["person_key"]] = tuple(r[f].isoformat() if isinstance(r[f], date) else r[f] for f in FINDING_FIELDS)
    return stored


def with_stored_dates(record, before):
    """The record with every date the file leaves empty filled from the stored version of that person.

    Each date is a "first ..." date (first lesson, baptismal date set ...), which never goes away once it happened.
    An empty cell means the file is older than what is stored, or left it out, so the stored date is kept."""
    if not before:
        return record
    stored = dict(zip(FINDING_FIELDS, before))
    merged = dict(record)
    for field in data_types.FINDING_DATES:
        if not merged.get(field) and stored.get(field):
            merged[field] = stored[field]
    return merged


def finding_changes(cur, records):
    """Which people are new, changed or the same as stored. Returns (records to store, counts)."""
    stored = stored_finding_rows(cur)
    to_store, counts = [], {"new": 0, "changed": 0, "same": 0}
    for record in records:
        before = stored.get(record["person_key"])
        record = with_stored_dates(record, before)
        if before == finding_row(record):
            counts["same"] += 1
            continue
        counts["changed" if before else "new"] += 1
        to_store.append(record)
    return to_store, counts


def newest_stored_finding(cur):
    """The newest first-finding date stored for this mission (None before the first finding upload)."""
    cur.execute("select max(found_on) newest from public.finding_people_latest where mission_id=%s", (sign_in.current_mission_id(),))
    newest = cur.fetchone()["newest"]
    return newest.isoformat() if newest else None


def older_than_stored(cur, records):
    """(newest date of the file, newest stored date) when the file ends before what is stored, else None.

    An older export (last month's file uploaded after this month's) would give people their older area or source
    back, so the check page warns and Apply needs an extra tick."""
    stored_last = newest_stored_finding(cur)
    file_last = max((r["found_on"] for r in records), default=None)
    if stored_last and file_last and file_last < stored_last:
        return file_last, stored_last
    return None


def save_finding(conn, records, filename, rows_read, older_ok=False):
    """Stores the new and changed people of a finding export as one batch; None when nothing is new."""
    with database.cursor(conn) as cur:
        cur.execute("lock table public.finding_people in share row exclusive mode")
        cur.execute("""select summary->>'person_code_check' code from public.roster_import_batches
          where mission_id=%s and kind='FINDING' and status='APPLIED' order by created_at desc limit 1""", (sign_in.current_mission_id(),))
        last = cur.fetchone()
        if last and last["code"] and last["code"] != person_code_check():
            raise ValueError(plain("uploads.finding.keyChanged"))
        if older_than_stored(cur, records) and not older_ok:
            raise ValueError(plain("uploads.review.olderConfirmFirst"))
        to_store, counts = finding_changes(cur, records)
        if not to_store:
            return None
        found = sorted(r["found_on"] for r in records)
        summary = {"rows_in_file": rows_read, "people_new": counts["new"], "people_changed": counts["changed"],
                   "people_unchanged": counts["same"], "first_found": found[0], "last_found": found[-1],
                   "person_code_check": person_code_check()}
        batch = batches.create_batch(conn, "FINDING", filename, None, summary)
        columns = ["batch_id", "mission_id", "person_key"] + FINDING_FIELDS
        values = [(batch, sign_in.current_mission_id(), r["person_key"]) + finding_row(r) for r in to_store]
        psycopg2.extras.execute_values(cur, sql.SQL("insert into public.finding_people ({}) values %s").format(
            sql.SQL(",").join(map(sql.Identifier, columns))).as_string(cur), values, page_size=1000)
    return batch


def one_row_per_zone_week(records):
    """Zone history: when two names of one week mean the same portal zone (say 'Nürnberg' and 'Nurnberg Zone'),
    only the first row is kept, so that zone is not counted twice in the mission's totals."""
    kept, seen = [], set()
    for record in records:
        key = (record["sunday"], record.get("zone_id") or data_names.fold_zone(record["zone"]))
        if key not in seen:
            seen.add(key)
            kept.append(record)
    return kept


def save_weekly(conn, slug, records, filename, rows_read):
    """Stores every row of a weekly upload with its batch; the newest upload of each week counts (see 033)."""
    if slug == "zone-history":
        records = one_row_per_zone_week(records)
    if not records:
        return None
    spec = spec_of(slug)
    pairs = WEEKLY_COLUMNS[slug]
    weeks = sorted({r["sunday"] for r in records})
    with database.cursor(conn) as cur:
        cur.execute(sql.SQL("lock table public.{} in share row exclusive mode").format(sql.Identifier(spec["table"])))
        replaced = weeks_already_uploaded(cur, spec["kind"], weeks)
        summary = {"rows_in_file": rows_read, "rows_saved": len(records), "weeks": len(weeks),
                   "first_week": weeks[0], "last_week": weeks[-1], "weeks_replacing_an_older_upload": replaced}
        batch = batches.create_batch(conn, spec["kind"], filename, None, summary)
        columns = ["batch_id", "mission_id"] + [column for column, _ in pairs]
        values = [(batch, sign_in.current_mission_id()) + tuple(r.get(field) for _, field in pairs) for r in records]
        psycopg2.extras.execute_values(cur, sql.SQL("insert into public.{} ({}) values %s").format(
            sql.Identifier(spec["table"]), sql.SQL(",").join(map(sql.Identifier, columns))).as_string(cur),
            values, page_size=1000)
    return batch


def weeks_already_uploaded(cur, kind, weeks):
    cur.execute("""select count(*) n from public.data_upload_week_batches
      where kind=%s and mission_id=%s and sunday=any(%s::date[])""", (kind, sign_in.current_mission_id(), weeks))
    return cur.fetchone()["n"]


def apply_upload(slug, pending, older_ok=False):
    """Applies a checked upload in one transaction. Returns the batch id, or None when there was nothing new.
    older_ok: the manager ticked that an older finding export may still be applied (see older_than_stored)."""
    conn = database.connect()
    try:
        with database.cursor(conn) as cur:
            cur.execute("select id from public.missions where id=%s for update", (sign_in.current_mission_id(),))
            records = pending["parsed"]["records"]
            if place_records(data_names.Matcher(cur, sign_in.current_mission_id()), slug, records):
                raise ValueError(plain("uploads.review.namesLeft"))
        rows_read = pending["parsed"]["rows_read"]
        if slug == "areas":  # rows whose name was left out have no portal area
            batch = save_area_records(conn, [r for r in records if r.get("area_id")], True, pending["filename"])
        elif slug == "finding":
            batch = save_finding(conn, records, pending["filename"], rows_read, older_ok)
        else:
            batch = save_weekly(conn, slug, records, pending["filename"], rows_read)
        if batch:
            conn.commit()
        else:
            conn.rollback()
        return batch
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def undo_rows(cur, batch):
    """Import history > Undo for a finding or weekly upload (called by undo.undo_batch inside its
    transaction): removes the batch's rows. The older upload of those weeks (or people) counts again."""
    kind = batch["kind"]
    if kind == "FINDING":
        cur.execute("""select filename from public.roster_import_batches
          where mission_id=%s and kind='FINDING' and status='APPLIED' and (created_at,id::text)>(%s,%s)
          order by created_at""", (batch["mission_id"], batch["created_at"], str(batch["id"])))
        newer = [r["filename"] for r in cur.fetchall()]
        if newer:
            raise ValueError(plain("uploads.undo.newerFirst", files=", ".join(newer)))
    cur.execute(sql.SQL("delete from public.{} where batch_id=%s").format(sql.Identifier(TABLE_OF_KIND[kind])),
                (str(batch["id"]),))


# --------------------------------------------------------------------------------------------- the check page

def check_upload(cur, slug, pending):
    """What the check page shows: the names to match and lines about how the upload joins the stored data."""
    records = pending["parsed"]["records"]
    matcher = data_names.Matcher(cur, sign_in.current_mission_id())
    questions = place_records(matcher, slug, records)
    lines, older = [], None
    if slug == "areas":
        lines.append(t("uploads.review.areasBlank"))
    elif slug == "finding" and records:
        to_store, counts = finding_changes(cur, records)
        found = sorted(r["found_on"] for r in records)
        lines.append(t("uploads.review.people", new=counts["new"], changed=counts["changed"], same=counts["same"]))
        lines.append(t("uploads.review.foundBetween", first=day_text(found[0]), last=day_text(found[-1])))
        # The FindeChristus line (Media without "Facebook - Personal Profile") is archived (migration 038): the rows
        # are still stored as before, and dashboards.findechristus_referrals_week still counts them.
        lines.append(t("uploads.review.datesKept"))
        older = older_than_stored(cur, records)
        if older:
            lines.append(t("uploads.review.olderFile", file_last=day_text(older[0]), stored_last=day_text(older[1])))
    elif records:
        weeks = sorted({r["sunday"] for r in records})
        lines.append(t("uploads.review.weeks", count=len(weeks), first=day_text(weeks[0]), last=day_text(weeks[-1])))
        replaced = weeks_already_uploaded(cur, spec_of(slug)["kind"], weeks)
        if replaced:
            lines.append(t("uploads.review.weeksReplaced", count=replaced))
            lines += replaced_lines(cur, slug, records)
        if slug == "zone-history":
            lines.append(t("uploads.review.portalWins", count=portal_zone_weeks(cur, records)))
    return {"matcher": matcher, "questions": questions, "lines": lines, "older": older}


# Where a stored row of each weekly table is, in the same shape as a record of the file (see place_key).
PLACE_COLUMNS = {
    "zone-history": "t.zone_id, t.zone_name zone, null::bigint area_id, '' area, false is_mission",
    "rates": "t.zone_id, t.zone_name zone, null::bigint area_id, '' area, t.is_mission",
    "referral-archive": "t.zone_id, t.zone_name zone, t.area_id, t.area_name area, false is_mission",
    "baptisms": "t.zone_id, t.zone_name zone, t.area_id, t.area_name area, false is_mission",
}


def place_key(row):
    """Where a row counts, to compare a stored row with the rows of the file: its portal area, the mission, or its
    portal zone (with the area name as written, for historical areas)."""
    if row.get("area_id"):
        return ("area", row["area_id"])
    if row.get("is_mission"):
        return ("mission",)
    zone = row.get("zone_id") or clean(row.get("zone")).casefold()
    return ("zone", zone, clean(row.get("area")).casefold())


def replaced_lines(cur, slug, records):
    """Lines for the check page about the older uploads this one replaces in some weeks.

    For each week the newest upload counts with all its rows (033, data_upload_week_batches), so every row of the
    older upload in those weeks stops counting. Rows for a zone or area that this file does not have in that week
    then disappear from the dashboards; the manager should know before applying."""
    weeks = sorted({r["sunday"] for r in records})
    in_file = {(r["sunday"], place_key(r)) for r in records}
    cur.execute(sql.SQL("""select b.filename, b.created_at, t.sunday, {columns}
        from public.{table} t
        join public.data_upload_week_batches w on w.kind=%s and w.batch_id=t.batch_id and w.mission_id=t.mission_id
         and w.sunday=t.sunday
        join public.roster_import_batches b on b.id=t.batch_id
        where t.mission_id=%s and t.sunday=any(%s::date[])
        order by b.created_at""").format(columns=sql.SQL(PLACE_COLUMNS[slug]),
                                         table=sql.Identifier(spec_of(slug)["table"])),
                (spec_of(slug)["kind"], sign_in.current_mission_id(), weeks))
    older = {}
    for row in cur.fetchall():
        upload = older.setdefault(row["filename"], {"date": row["created_at"], "weeks": set(), "rows": 0, "missing": 0})
        upload["weeks"].add(row["sunday"])
        upload["rows"] += 1
        if (row["sunday"].isoformat(), place_key(row)) not in in_file:
            upload["missing"] += 1
    lines = []
    for filename, upload in older.items():
        lines.append(t("uploads.review.replacedFrom", file=filename, date=page.mission_time(upload["date"]),
                       weeks=len(upload["weeks"]), rows=upload["rows"]))
        if upload["missing"]:
            lines.append(t("uploads.review.replacedMissing", rows=upload["missing"]))
    return lines


def portal_zone_weeks(cur, records):
    """How many zone-weeks of the file the portal already has weekly plans for (the portal's numbers are used)."""
    pairs = {(r["sunday"], r["zone_id"]) for r in records if r.get("zone_id")}
    if not pairs:
        return 0
    cur.execute("""select count(*) n from dashboards.kpi_zone_week k
      join unnest(%s::date[],%s::bigint[]) x(sunday,zone_id) on x.sunday=k.sunday and x.zone_id=k.zone_id
      where k.mission_id=%s and k.reports>0""", ([p[0] for p in pairs], [p[1] for p in pairs], sign_in.current_mission_id()))
    return cur.fetchone()["n"]
