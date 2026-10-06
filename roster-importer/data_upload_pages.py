"""The Data uploads pages (/uploads/...): upload a file, check it, match names, apply. The rules are in data_uploads.py.

Pages:
  /uploads                      the six uploads, with the date of the last one
  /uploads/<kind>               1. one upload: the template, the file form, how it works, uploads so far
  /uploads/<kind>/template      the template as a CSV file
  /uploads/<kind>/preview       reads the file (in memory) and keeps its rows waiting, then shows the check
  /uploads/<kind>/review        2. the check, with the names to match (3.) and the Apply form (4.)
  /uploads/<kind>/names         saves the matched names
  /uploads/<kind>/apply         4. Apply, after the "I checked" tick
  /uploads/<kind>/cancel        drops the waiting rows
  /uploads/areas/table          the area data as a table to edit
  /uploads/names                the remembered names, each can be forgotten

<kind> is one of data_uploads.UPLOADS: areas, finding, zone-history, referral-archive, rates, baptisms.
Every text is from data_text.py (the portal translates it).
"""
import re

from flask import Blueprint, Response, flash, redirect, request

import data_files
import data_names
import data_types
import database
import page
import sign_in
from data_files import FileProblem, clean
from data_text import plain, t
from data_uploads import (ARCHIVED_UPLOADS, UPLOADS, apply_upload, area_rows, check_upload, day_text, drop_pending,
                          load_pending, person_secret, read_upload, save_area_records, save_pending, spec_of,
                          template_file, title_of)
from page import h, mission_time

pages = Blueprint("data_upload_pages", __name__)


# ------------------------------------------------------------------------------------------ small pieces

def name_options(matcher, level, historical, leave_out=False):
    """<option>s for one name: keep as historical (or leave out), then current zones or areas, then old ones."""
    options = [f"<option value=''>{t('uploads.names.choose')}</option>"]
    if historical:
        label = t("uploads.names.leaveOut") if leave_out else t("uploads.names.keepHistorical")
        options.append(f"<option value='historical'>{label}</option>")
    places = matcher.zones if level == "zone" else matcher.areas
    for x in places:
        label = x["name"] if level == "zone" else f"{x['zone']} / {x['district']} / {x['name']}"
        old = "" if x["active"] else " " + t("uploads.names.old")
        options.append(f"<option value='{level}:{x['id']}'>{h(label)}{old}</option>")
    return "".join(options)


SAMPLE_COLUMNS = {  # the columns of "First rows to store" on the check page: (text key, record field)
    "areas": [("uploads.col.zone", "zone"), ("uploads.col.area", "area"), ("uploads.col.population", "population"),
              ("uploads.col.size", "size_km2"), ("uploads.col.urban", "urban_type"),
              ("uploads.col.assignment", "assignment_type")],
    "finding": [("uploads.col.found", "found_on"), ("uploads.col.zone", "zone"), ("uploads.col.area", "area"),
                ("uploads.col.category", "finding_category"), ("uploads.col.source", "finding_source"),
                ("uploads.col.firstLesson", "first_lesson_on")],
    "zone-history": [("uploads.col.week", "sunday"), ("uploads.col.zone", "zone"),
                     ("uploads.col.newPeopleGoal", "friends_found_goal"), ("uploads.col.newPeople", "friends_found_actual"),
                     ("uploads.col.sacrament", "sacrament_attendance_actual"),
                     ("uploads.col.baptized", "baptisms_confirmations_actual")],
    "referral-archive": [("uploads.col.week", "sunday"), ("uploads.col.zone", "zone"), ("uploads.col.area", "area"),
                         ("uploads.col.source", "source"), ("uploads.col.referrals", "referrals_received")],
    "rates": [("uploads.col.week", "sunday"), ("uploads.col.zone", "zone"), ("uploads.col.teachingRate", "teaching_rate"),
              ("uploads.col.contactRate", "contact_rate")],
    "baptisms": [("uploads.col.week", "sunday"), ("uploads.col.zone", "zone"), ("uploads.col.area", "area"),
                 ("uploads.col.ward", "ward"), ("uploads.col.source", "finding_source"),
                 ("uploads.col.baptisms", "baptisms"), ("uploads.col.confirmations", "confirmations")],
}


def sample_table(slug, records):
    """The first 8 rows the upload would store, in the columns of SAMPLE_COLUMNS."""
    columns = SAMPLE_COLUMNS[slug]
    head = "".join(f"<th>{t(key)}</th>" for key, _ in columns)
    body = "".join("<tr>" + "".join(f"<td>{h(show_value(r.get(field)))}</td>" for _, field in columns) + "</tr>"
                   for r in records[:8])
    return f"<div class='scroll'><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>"


def show_value(value):
    """A stored value as the check page shows it: dates as 27 Sep 2026, numbers without needless decimals."""
    if value is None:
        return ""
    if isinstance(value, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return day_text(value)
    if isinstance(value, float):
        return data_types.number_text(value)
    return value


# ------------------------------------------------------------------------------------------ the pages

def pending_card(slug):
    """A note when a checked file of this upload is still waiting, with a link to its check."""
    pending = load_pending(slug)
    if not pending:
        return ""
    return (f"<div class='flash'>{t('uploads.page.waiting', file=pending['filename'])} "
            f"<a href='/uploads/{slug}/review'>{t('uploads.page.openCheck')}</a></div>")


def recent_uploads(cur, kind, limit=5):
    """The latest batches of one kind of upload."""
    cur.execute("""select id,filename,created_at,actor,status from public.roster_import_batches
      where mission_id=%s and kind=%s order by created_at desc limit %s""", (sign_in.current_mission_id(), kind, limit))
    return cur.fetchall()


def hub_page():
    """The Data uploads page: the uploads it offers (not the archived ones), each with the date of the last one."""
    with database.connect() as conn:
        with database.cursor(conn) as cur:
            cur.execute("""select distinct on (kind) kind,filename,created_at from public.roster_import_batches
              where mission_id=%s and status='APPLIED' and kind=any(%s) order by kind,created_at desc""",
                        (sign_in.current_mission_id(), [s["kind"] for s in UPLOADS.values()]))
            last = {r["kind"]: r for r in cur.fetchall()}
    cards = []
    for slug, spec in UPLOADS.items():
        if slug in ARCHIVED_UPLOADS:  # archived (migration 038): not offered here; its page still works
            continue
        latest = last.get(spec["kind"])
        status = (t("uploads.hub.last", date=mission_time(latest["created_at"]), file=latest["filename"]) if latest
                  else t("uploads.hub.none"))
        cards.append(f"""<div class="card"><h3>{title_of(slug)}</h3><p class="muted">{t(f"uploads.{spec['text']}.about")}</p>
          <p class="muted">{status}</p><p><a href="/uploads/{slug}">{t("uploads.hub.open")}</a></p></div>""")
    return f"""<div class="card"><div class="step">{t("uploads.hub.step")}</div><h2>{t("uploads.hub.title")}</h2>
      <p class="muted">{t("uploads.hub.intro")}</p><p class="muted">{t("uploads.hub.privacy")}</p>
      <p><a href="/uploads/names">{t("uploads.hub.names")}</a></p></div>
      <div class="grid">{''.join(cards)}</div>"""


def upload_page(slug):
    """Step 1 of one upload: the template, the file form, how it works, and the uploads so far."""
    spec = spec_of(slug)
    with database.connect() as conn:
        with database.cursor(conn) as cur:
            recent = recent_uploads(cur, spec["kind"])
    rows = "".join(f"<tr><td><a href='/imports/{r['id']}'>{h(r['filename'])}</a></td><td>{mission_time(r['created_at'])}</td>"
                   f"<td>{h(r['actor'])}</td><td>{t('uploads.status.' + r['status'].lower())}</td></tr>" for r in recent)
    history = (f"<div class='scroll'><table><thead><tr><th>{t('uploads.col.file')}</th><th>{t('uploads.col.when')}</th>"
               f"<th>{t('uploads.col.by')}</th><th>{t('uploads.col.status')}</th></tr></thead><tbody>{rows}</tbody></table></div>"
               if rows else f"<p class='muted'>{t('uploads.hub.none')}</p>")
    secret_note = (f"<div class='error'>{t('uploads.finding.noSecret')}</div>"
                   if slug == "finding" and not person_secret() else "")
    table_link = (f"<p><a href='/uploads/areas/table'>{t('uploads.areas.editTable')}</a></p>" if slug == "areas" else "")
    text = spec["text"]
    report_week = (f"<li>{t('uploads.page.reportWeek')}</li><li>{t('uploads.page.oneReport')}</li>"
                   if slug in ("referral-archive", "rates") else "")
    return f"""{pending_card(slug)}{secret_note}<div class="card"><div class="step">{t("uploads.page.step1")}</div>
      <h2>{title_of(slug)}</h2><p class="muted">{t(f"uploads.{text}.about")}</p>
      <p><a href="/uploads/{slug}/template">{t("uploads.page.template")}</a></p>{table_link}
      <form action="/uploads/{slug}/preview" method="post" enctype="multipart/form-data">
        <label class="form-field">{t("uploads.page.file")}<input type="file" name="file" accept=".csv,.xlsx" required></label>
        <button>{t("uploads.page.check")}</button></form></div>
      <div class="card"><h3>{t("uploads.page.how")}</h3><ul><li>{t(f"uploads.{text}.columns")}</li>
        <li>{t(f"uploads.{text}.merge")}</li><li>{t("uploads.page.weeks")}</li>{report_week}<li>{t("uploads.page.never")}</li></ul></div>
      <div class="card"><h3>{t("uploads.page.recent")}</h3>{history}<p><a href="/uploads">{t("uploads.page.back")}</a></p></div>"""


def review_page(slug, pending):
    """Step 2: the check of the waiting upload, with the names to match and the Apply form."""
    spec = spec_of(slug)
    parsed = pending["parsed"]
    with database.connect() as conn:
        with database.cursor(conn) as cur:
            check = check_upload(cur, slug, pending)
    questions = check["questions"]
    metrics = "".join(f"<div class='metric'><b>{value}</b><br>{t(key)}</div>" for key, value in (
        ("uploads.review.rowsRead", parsed["rows_read"]), ("uploads.review.rowsToStore", len(parsed["records"])),
        ("uploads.review.leftOut", parsed["left_out"]), ("uploads.review.problems", parsed["problem_count"]),
        ("uploads.review.namesToMatch", len(questions))))
    lines = "".join(f"<li>{line}</li>" for line in check["lines"] + [t(f"uploads.{spec['text']}.merge")])
    problems = "".join(f"<tr><td>{n}</td><td>{h(text)}</td></tr>" for n, text in parsed["problems"])
    problem_card = (f"""<div class="card"><h3>{t("uploads.review.problemTitle")}</h3><p class="muted">{t("uploads.review.problemHelp")}</p>
      <div class="scroll"><table><thead><tr><th>{t("uploads.col.row")}</th><th>{t("uploads.col.problem")}</th></tr></thead>
      <tbody>{problems}</tbody></table></div>{f"<p class='muted'>{t('uploads.review.moreProblems', count=parsed['problem_count'] - len(parsed['problems']))}</p>" if parsed['problem_count'] > len(parsed['problems']) else ""}</div>"""
                    if problems else "")
    names_card = names_form(slug, spec, check) if questions else ""
    ready = not questions and parsed["records"]
    # An older finding export needs a second tick (the server checks it again in save_finding).
    older_tick = (f"""<p class="warn"><label><input type="checkbox" name="older_ok" value="yes" required>
        {t("uploads.review.olderConfirm")}</label></p>""" if check["older"] else "")
    apply_card = (f"""<div class="card"><form action="/uploads/{slug}/apply" method="post">
        <p><label><input type="checkbox" name="confirmed" value="yes" required> {t("uploads.review.confirm")}</label></p>
        {older_tick}<button>{t("uploads.review.apply")}</button></form></div>""" if ready else
                  f"<div class='card'><p class='warn'>{t('uploads.review.namesLeft' if questions else 'uploads.review.nothing')}</p></div>")
    cancel = (f"<form action='/uploads/{slug}/cancel' method='post'><button class='secondary'>{t('uploads.review.cancel')}</button>"
              f" <a href='/uploads/{slug}'>{t('uploads.page.back')}</a></form>")
    return f"""<div class="card"><div class="step">{t("uploads.review.step")}</div><h2>{title_of(slug)}: {h(pending['filename'])}</h2>
      <div class="grid">{metrics}</div><ul>{lines}</ul>{sample_table(slug, parsed["records"]) if parsed["records"] else ""}</div>
      {names_card}{problem_card}{apply_card}<div class="card">{cancel}</div>"""


def names_form(slug, spec, check):
    """Step 3: the names of the file that are not portal names, each with a list to match it."""
    matcher = check["matcher"]
    rows = []
    for (level, name), info in sorted(check["questions"].items(), key=lambda x: (x[0][0], x[0][1].casefold())):
        zones = ", ".join(sorted(info["zones"]))
        where = f"<br><span class='muted'>{t('uploads.names.inZone', zones=zones)}</span>" if zones else ""
        rows.append(f"""<tr><td>{t("uploads.names." + level)}</td><td>{h(name)}{where}
          <input type="hidden" name="level" value="{level}"><input type="hidden" name="name" value="{h(name)}"></td>
          <td>{info["rows"]}</td><td><select name="choice">{name_options(matcher, level, spec["historical"], slug == "areas")}</select></td></tr>""")
    keep_all = (f"<p><label><input type='checkbox' name='keep_rest' value='yes'> "
                f"{t('uploads.names.leaveRest' if slug == 'areas' else 'uploads.names.keepRest')}</label></p>")
    return f"""<div class="card"><div class="step">{t("uploads.names.step")}</div><h3>{t("uploads.names.title")}</h3>
      <p class="muted">{t("uploads.names.helpAreas" if slug == "areas" else "uploads.names.help")}</p><form action="/uploads/{slug}/names" method="post">
      <div class="scroll"><table><thead><tr><th>{t("uploads.col.level")}</th><th>{t("uploads.col.nameInFile")}</th>
      <th>{t("uploads.col.rows")}</th><th>{t("uploads.col.portal")}</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div>
      {keep_all}<button>{t("uploads.names.save")}</button></form></div>"""


def area_table_page(error=None, values=None):
    """The area data of every area as a table to edit (an empty box clears a value)."""
    with database.connect() as conn:
        with database.cursor(conn) as cur:
            areas = area_rows(cur)
    values = values or {}
    datalists = ("<datalist id='urbanTypes'>" + "".join(f"<option value='{h(x)}'>" for x in data_types.URBAN_TYPES)
                 + "</datalist><datalist id='assignmentTypes'>"
                 + "".join(f"<option value='{h(x)}'>" for x in data_types.ASSIGNMENT_TYPES) + "</datalist>")
    rows = []
    for a in areas:
        v = values.get(str(a["area_id"])) or {
            "population": data_types.none_as_blank(a["population"]), "size": data_types.number_text(a["size_km2"]),
            "urban": a["urban_type"] or "", "assignment": a["assignment_type"] or "",
            "extra": "; ".join(f"{k}: {x}" for k, x in (a["extra"] or {}).items())}
        old = "" if a["active"] else f" <span class='badge'>{t('uploads.names.oldBadge')}</span>"
        rows.append(f"""<tr><td>{h(a['zone'])}</td><td>{h(a['district'])}</td><td>{h(a['area'])}{old}
          <input type="hidden" name="area_id" value="{a['area_id']}"></td>
          <td><input name="population" inputmode="numeric" value="{h(v['population'])}" size="7"></td>
          <td><input name="size" inputmode="decimal" value="{h(v['size'])}" size="6"></td>
          <td>{h(data_types.number_text(a['density_per_km2']))}</td>
          <td><input name="urban" list="urbanTypes" value="{h(v['urban'])}" size="9"></td>
          <td><input name="assignment" list="assignmentTypes" value="{h(v['assignment'])}" size="11"></td>
          <td><input name="extra" value="{h(v['extra'])}" size="22"></td></tr>""")
    problem = f"<div class='error'>{h(error)}</div>" if error else ""
    return f"""{problem}<div class="card"><h2>{t("uploads.areas.tableTitle")}</h2><p class="muted">{t("uploads.areas.tableHelp")}</p>
      <p class="muted">{t("uploads.areas.extraHelp")}</p><form action="/uploads/areas/table" method="post">{datalists}
      <div class="scroll"><table><thead><tr><th>{t("uploads.col.zone")}</th><th>{t("uploads.col.district")}</th>
      <th>{t("uploads.col.area")}</th><th>{t("uploads.col.population")}</th><th>{t("uploads.col.size")}</th>
      <th>{t("uploads.col.density")}</th><th>{t("uploads.col.urban")}</th><th>{t("uploads.col.assignment")}</th>
      <th>{t("uploads.col.extra")}</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div>
      <p><button>{t("uploads.areas.save")}</button> <a href="/uploads/areas">{t("uploads.page.back")}</a></p></form></div>"""


def area_table_records(form):
    """The area table as records to save, with the typed values for showing the table again after a mistake.
    Raises ValueError (with the area's row) for a value that is not a number."""
    names = ["area_id", "population", "size", "urban", "assignment", "extra"]
    columns = [form.getlist(n) for n in names]
    if len({len(c) for c in columns}) != 1:
        raise ValueError(plain("uploads.areas.incomplete"))
    records, typed = [], {}
    for area_id, population, size, urban, assignment, extra in zip(*columns):
        if not area_id.isdigit():
            raise ValueError(plain("uploads.areas.incomplete"))
        typed[area_id] = {"population": population, "size": size, "urban": urban, "assignment": assignment,
                          "extra": extra}
        records.append({"area_id": int(area_id), "population": data_files.read_count(population),
                        "size_km2": area_size(size), "urban_type": clean(urban)[:60] or None,
                        "assignment_type": clean(assignment)[:60] or None, "extra": extra_attributes(extra)})
    return records, typed


def area_size(text):
    size = data_files.read_decimal(text)
    if size == 0:
        raise ValueError(plain("uploads.problem.sizeZero"))
    return size


def extra_attributes(text):
    """'Chapel: yes; Languages: German, Arabic' -> {'Chapel': 'yes', 'Languages': 'German, Arabic'}."""
    extra = {}
    for part in str(text or "").split(";"):
        name, _, value = part.partition(":")
        if clean(name) and clean(value):
            extra[clean(name)[:60]] = clean(value)[:200]
        elif clean(part):
            raise ValueError(plain("uploads.areas.extraFormat", text=clean(part)))
    return extra


def names_page():
    """The remembered names of earlier uploads; each can be forgotten."""
    with database.connect() as conn:
        with database.cursor(conn) as cur:
            cur.execute("""select m.id,m.level,m.source_name,m.historical,m.confirmed_by,m.confirmed_at,
                z.name zone,a.name area,ad.name area_district,az.name area_zone
              from public.data_name_matches m left join public.zones z on z.id=m.zone_id
              left join public.areas a on a.id=m.area_id left join public.districts ad on ad.id=a.district_id
              left join public.zones az on az.id=ad.zone_id
              where m.mission_id=%s order by m.level desc,lower(m.source_name)""", (sign_in.current_mission_id(),))
            matches = cur.fetchall()
    rows = []
    for r in matches:
        target = (t("uploads.names.historical") if r["historical"] else h(r["zone"]) if r["level"] == "zone"
                  else h(f"{r['area_zone']} / {r['area_district']} / {r['area']}"))
        rows.append(f"""<tr><td>{t("uploads.names." + r["level"])}</td><td>{h(r['source_name'])}</td><td>{target}</td>
          <td>{h(r['confirmed_by'])}<br><span class="muted">{mission_time(r['confirmed_at'])}</span></td>
          <td><form action="/uploads/names/forget" method="post"><input type="hidden" name="id" value="{r['id']}">
          <button class="secondary">{t("uploads.names.forget")}</button></form></td></tr>""")
    table = (f"""<div class="scroll"><table><thead><tr><th>{t("uploads.col.level")}</th><th>{t("uploads.col.nameInFile")}</th>
      <th>{t("uploads.col.portal")}</th><th>{t("uploads.col.by")}</th><th></th></tr></thead><tbody>{''.join(rows)}</tbody></table></div>"""
             if rows else f"<p class='muted'>{t('uploads.names.noneSaved')}</p>")
    return f"""<div class="card"><h2>{t("uploads.names.savedTitle")}</h2><p class="muted">{t("uploads.names.savedHelp")}</p>
      {table}<p><a href="/uploads">{t("uploads.page.back")}</a></p></div>"""


# ------------------------------------------------------------------------------------------ routes

def unknown_upload():
    return page.render(f"<div class='error'>{t('uploads.page.unknown')}</div>", 404)


def upload_gone():
    """The waiting rows are gone (applied, cancelled, or older than a day): back to the list of uploads."""
    flash(plain("uploads.review.gone"))
    return redirect("/uploads")


@pages.route("/uploads")
def uploads_hub():
    if not sign_in.allowed():
        return sign_in.go_to_login()
    return page.render(hub_page())


@pages.route("/uploads/<slug>")
def upload_start(slug):
    if not sign_in.allowed():
        return sign_in.go_to_login()
    if slug not in UPLOADS:
        return unknown_upload()
    return page.render(upload_page(slug))


@pages.route("/uploads/<slug>/template")
def upload_template(slug):
    """The template of an upload as a CSV file."""
    if not sign_in.allowed():
        return sign_in.go_to_login()
    if slug not in UPLOADS:
        return unknown_upload()
    with database.connect() as conn:
        with database.cursor(conn) as cur:
            filename, headings, rows = template_file(slug, cur)
    return Response(data_files.as_csv(headings, rows), mimetype="text/csv",
                    headers={"Content-Disposition": f"attachment; filename={filename}"})


@pages.route("/uploads/<slug>/preview", methods=["POST"])
def upload_preview(slug):
    """Reads the uploaded file in memory, keeps its rows waiting, and opens the check."""
    if not sign_in.allowed():
        return sign_in.go_to_login()
    if slug not in UPLOADS:
        return unknown_upload()
    upload = request.files.get("file")
    try:
        if not upload or not upload.filename:
            raise FileProblem(plain("uploads.problem.noFile"))
        parsed = read_upload(slug, upload.filename, upload.read())  # read in memory; the file is never saved
    except FileProblem as error:
        return page.render(f"<div class='error'><b>{t('uploads.review.notRead')}</b><br>{h(error)}</div>"
                           f"<p><a href='/uploads/{slug}'>{t('uploads.page.back')}</a></p>", 400)
    save_pending(slug, upload.filename, parsed)
    return redirect(f"/uploads/{slug}/review")


@pages.route("/uploads/<slug>/review")
def upload_review(slug):
    """The check of the waiting upload."""
    if not sign_in.allowed():
        return sign_in.go_to_login()
    pending = load_pending(slug) if slug in UPLOADS else None
    if not pending:
        return upload_gone()
    return page.render(review_page(slug, pending))


@pages.route("/uploads/<slug>/names", methods=["POST"])
def upload_names(slug):
    """Saves the names the manager matched, then shows the check again."""
    if not sign_in.allowed():
        return sign_in.go_to_login()
    pending = load_pending(slug) if slug in UPLOADS else None
    if not pending:
        return upload_gone()
    spec = spec_of(slug)
    levels, names, choices = request.form.getlist("level"), request.form.getlist("name"), request.form.getlist("choice")
    keep_rest = spec["historical"] and request.form.get("keep_rest") == "yes"
    saved = 0
    with database.connect() as conn:
        with database.cursor(conn) as cur:
            for level, name, choice in zip(levels, names, choices):
                if level != spec["level"] and level != "zone":
                    continue
                if not choice and keep_rest:
                    choice = "historical"
                if choice == "historical" and not spec["historical"]:
                    continue
                saved += data_names.remember(cur, sign_in.current_mission_id(), level, name, choice, sign_in.actor_name())
    flash(plain("uploads.names.saved", count=saved))
    return redirect(f"/uploads/{slug}/review")


@pages.route("/uploads/<slug>/apply", methods=["POST"])
def upload_apply(slug):
    """Applies the checked upload as one batch in Import history."""
    if not sign_in.allowed():
        return sign_in.go_to_login()
    pending = load_pending(slug) if slug in UPLOADS else None
    if not pending:
        return upload_gone()
    try:
        if request.form.get("confirmed") != "yes":
            raise ValueError(plain("uploads.review.confirmFirst"))
        batch = apply_upload(slug, pending, older_ok=request.form.get("older_ok") == "yes")
    except ValueError as error:
        return page.render(f"<div class='error'><b>{t('uploads.review.notSaved')}</b><br>{h(error)}</div>"
                           f"<p><a href='/uploads/{slug}/review'>{t('uploads.page.openCheck')}</a></p>", 409)
    drop_pending(slug)
    if not batch:
        flash(plain("uploads.review.nothingNew"))
        return redirect(f"/uploads/{slug}")
    flash(plain("uploads.review.saved"))
    return redirect(f"/imports/{batch}")


@pages.route("/uploads/<slug>/cancel", methods=["POST"])
def upload_cancel(slug):
    """Drops the waiting rows."""
    if not sign_in.allowed():
        return sign_in.go_to_login()
    if slug not in UPLOADS:
        return redirect("/uploads")
    drop_pending(slug)
    return redirect(f"/uploads/{slug}")


@pages.route("/uploads/areas/table", methods=["GET", "POST"])
def area_table():
    """The area table: shows it, or saves it as one batch in Import history."""
    if not sign_in.allowed():
        return sign_in.go_to_login()
    if request.method == "GET":
        return page.render(area_table_page())
    try:
        records, typed = area_table_records(request.form)
    except ValueError as error:
        return page.render(area_table_page(error=str(error)), 400)
    conn = database.connect()
    try:
        with database.cursor(conn) as cur:  # only this mission's areas may be saved here
            cur.execute("""select a.id from public.areas a join public.districts d on d.id=a.district_id
              join public.zones z on z.id=d.zone_id where z.mission_id=%s""", (sign_in.current_mission_id(),))
            mine = {r["id"] for r in cur.fetchall()}
        if any(r["area_id"] not in mine for r in records):
            raise ValueError(plain("uploads.areas.outside"))
        batch = save_area_records(conn, records, False, plain("uploads.areas.tableFile"))
        conn.commit()
    except ValueError as error:
        conn.rollback()
        return page.render(area_table_page(error=str(error), values=typed), 400)
    finally:
        conn.close()
    flash(plain("uploads.areas.tableSaved") if batch else plain("uploads.areas.tableSame"))
    return redirect("/uploads/areas/table")


@pages.route("/uploads/names")
def upload_names_list():
    if not sign_in.allowed():
        return sign_in.go_to_login()
    return page.render(names_page())


@pages.route("/uploads/names/forget", methods=["POST"])
def upload_names_forget():
    """Forgets one remembered name."""
    if not sign_in.allowed():
        return sign_in.go_to_login()
    with database.connect() as conn:
        with database.cursor(conn) as cur:
            cur.execute("delete from public.data_name_matches where id=%s and mission_id=%s",
                        (int(request.form.get("id") or 0), sign_in.current_mission_id()))
    flash(plain("uploads.names.forgotten"))
    return redirect("/uploads/names")
