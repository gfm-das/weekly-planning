"""The Data uploads pages (/uploads/...): upload a file, check it, match names, apply. The rules are in data_uploads.py.

Pages:
  /uploads                      the six uploads, with the date of the last one
  /uploads                      1. the one drop zone for every kind of file (/uploads/check finds the kind: upload_detect.py)
  /uploads/<kind>/template      the template as a CSV file
  /uploads/<kind>/review        2. the check, with the names to match (3.) and the Apply form (4.)
  /uploads/<kind>/names         saves the matched names
  /uploads/<kind>/apply         4. Apply, after the "I checked" tick
  /uploads/<kind>/cancel        drops the waiting rows
  /uploads/geo/table            the Geo data of every area as a table to edit (zones and districts: to read)
  /uploads/names                the remembered names, each can be forgotten

<kind> is one of data_uploads.UPLOADS: geo, finding, zone-history, baptisms.
Every text is from data_text.py (the portal translates it).
"""
import re
from datetime import date

from flask import Blueprint, Response, flash, redirect, request

import data_files
import data_names
import data_types
import database
import historical_pages
import page
import sign_in
import transfer_pages
import upload_detect
from data_files import FileProblem, clean, read_table
from data_text import plain, t
from data_uploads import (UPLOADS, apply_upload, check_upload, day_text, drop_pending,
                          geo_district_rows, geo_rows, geo_zone_rows, load_pending, read_upload, save_geo_table, save_pending,
                          spec_of, template_file, title_of)
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
    "geo": [("uploads.col.zone", "zone"), ("uploads.col.area", "area"), ("uploads.col.population", "population"),
            ("uploads.col.size", "size_km2"), ("uploads.col.density", "density_per_km2"),
            ("uploads.col.households", "households"), ("uploads.col.urban", "urban_type"),
            ("uploads.col.assignment", "assignment_type"), ("uploads.col.source", "source"),
            ("uploads.col.dataDate", "data_date")],
    "finding": [("uploads.col.found", "found_on"), ("uploads.col.zone", "zone"), ("uploads.col.area", "area"),
                ("uploads.col.category", "finding_category"), ("uploads.col.source", "finding_source"),
                ("uploads.col.firstLesson", "first_lesson_on")],
    "zone-history": [("uploads.col.week", "sunday"), ("uploads.col.zone", "zone"),
                     ("uploads.col.newPeopleGoal", "friends_found_goal"), ("uploads.col.newPeople", "friends_found_actual"),
                     ("uploads.col.sacrament", "sacrament_attendance_actual"),
                     ("uploads.col.baptized", "baptisms_confirmations_actual")],
    "baptisms": [("uploads.col.week", "sunday"), ("uploads.col.zone", "zone"), ("uploads.col.area", "area"),
                 ("uploads.col.ward", "ward"), ("uploads.col.source", "finding_source"),
                 ("uploads.col.baptisms", "baptisms"), ("uploads.col.confirmations", "confirmations")],
}


def sample_table(slug, records):
    """The first 8 rows the upload would store, in the columns of SAMPLE_COLUMNS."""
    columns = SAMPLE_COLUMNS[slug]
    head = "".join(f"<th>{t(key)}</th>" for key, _ in columns)
    def shown(record, field):
        if slug == "geo" and field == "area" and not record.get("area"):  # a zone or district row of the three-table file
            return record.get("district") or record.get("zone")
        return record.get(field)

    body = "".join("<tr>" + "".join(f"<td>{h(show_value(shown(r, field)))}</td>" for _, field in columns) + "</tr>"
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


def kind_title(kind, plain_text=False):
    """The name of one kind of file, as the drop-down and the notes show it."""
    say = plain if plain_text else t
    if kind in UPLOADS:
        return title_of(kind, plain_text)
    return say({"roster": "uploads.kind.roster", "historical": "uploads.kind.historical", "people": "uploads.kind.people",
                "vollzogen": "uploads.vollzogen.title"}[kind])


def review_address(kind):
    """Where the check of a waiting file of this kind is."""
    return {"people": "/people-upload/review", "vollzogen": "/uploads/vollzogen/review"}.get(kind, f"/uploads/{kind}/review")


def template_address(kind):
    return {"people": "/people-upload/template", "vollzogen": "/uploads/vollzogen/template"}.get(kind, f"/uploads/{kind}/template")


def hub_page(message="", chosen="auto"):
    """The one Uploads page: one drop zone for every file the mission imports. The kind is found from the file's headings
    (upload_detect.py) unless one is chosen; a file that could be several kinds is asked about, never guessed."""
    with database.connect() as conn:
        with database.cursor(conn) as cur:
            cur.execute("""select distinct on (kind) kind,filename,created_at from public.roster_import_batches
              where mission_id=%s and status='APPLIED' order by kind,created_at desc""", (sign_in.current_mission_id(),))
            last = {r["kind"]: r for r in cur.fetchall()}
    waiting = ""
    for kind in upload_detect.CHECKED_KINDS:
        pending = load_pending(kind)
        if pending:
            waiting += (f"<div class='flash'>{t('uploads.page.waiting', file=pending['filename'])} "
                        f"<a href='{review_address(kind)}'>{t('uploads.page.openCheck')}</a></div>")
    options = "".join(f'<option value="{kind}"{" selected" if kind == chosen else ""}>{kind_title(kind)}</option>'
                      for kind in upload_detect.KINDS)
    stored = {"roster": "ROSTER", "historical": "HISTORICAL", "people": "PEOPLE", "vollzogen": "VOLLZOGEN"}
    cards = []
    for kind in upload_detect.KINDS:
        about = (t(f"uploads.{UPLOADS[kind]['text']}.about") if kind in UPLOADS else
                 t({"roster": "uploads.kind.rosterAbout", "historical": "uploads.kind.historicalAbout",
                    "people": "uploads.kind.peopleAbout", "vollzogen": "uploads.vollzogen.about"}[kind]))
        batch = last.get(UPLOADS[kind]["kind"] if kind in UPLOADS else stored[kind])
        status = (t("uploads.hub.last", date=mission_time(batch["created_at"]), file=batch["filename"]) if batch
                  else t("uploads.hub.none"))
        link = "" if kind in ("roster", "historical") else f'<a href="{template_address(kind)}">{t("uploads.page.template")}</a>'
        tables = {"geo": ("/uploads/geo/table", "uploads.geo.editTable"),
                  "vollzogen": ("/uploads/vollzogen/table", "uploads.vollzogen.viewTable")}
        if kind in tables:
            link += f' · <a href="{tables[kind][0]}">{t(tables[kind][1])}</a>'
        how = ""
        if kind in UPLOADS:
            how = f"<li>{t('uploads.' + UPLOADS[kind]['text'] + '.columns')}</li><li>{t('uploads.' + UPLOADS[kind]['text'] + '.merge')}</li>"
            if kind == "geo":
                how += f"<li>{t('uploads.geo.peer')}</li>"
        elif kind == "people":
            how = f"<li>{t('uploads.people.fcAbout')}</li>"
        elif kind == "vollzogen":
            how = "".join(f"<li>{t('uploads.vollzogen.' + part)}</li>" for part in ("columns", "merge", "privacy", "fcAbout"))
        how = f"<details><summary>{t('uploads.page.how')}</summary><ul>{how}</ul></details>" if how else ""
        cards.append(f'<div class="card"><h3>{kind_title(kind)}</h3><p class="muted">{about}</p>'
                     f'<p class="muted">{status}</p>{how}<p>{link}</p></div>')
    return f"""{waiting}{message}<div class="card"><div class="step">{t("uploads.hub.step")}</div><h2>{t("uploads.hub.title")}</h2>
      <p class="muted">{t("uploads.hub.intro")}</p><p class="muted">{t("uploads.hub.privacy")}</p>
      <form action="/uploads/check" method="post" enctype="multipart/form-data">
        <div class="form-field"><label>{t("uploads.hub.kind")}<select name="kind"><option value="auto">{t("uploads.hub.auto")}</option>{options}</select></label></div>
        <div class="form-field"><label class="file-pick"><span>{t("uploads.page.file")}</span><span class="name" data-empty="{t("uploads.page.noneChosen")}">{t("uploads.page.noneChosen")}</span><input type="file" name="file" accept=".csv,.xlsx,.xlsm,.txt" required></label></div>
        <details><summary>{t("uploads.hub.more")}</summary>
          <p><label>{t("uploads.hub.transferDate")}<br><input type="date" name="transfer_date" value="{date.today().isoformat()}"></label></p>
          <p><label>{t("uploads.hub.duplicate")}<br><select name="duplicate_policy"><option value="replace">{t("uploads.hub.replace")}</option>
            <option value="stop">{t("uploads.hub.stop")}</option></select></label></p></details>
        <p><button>{t("uploads.page.check")}</button></p></form>
      <p><a href="/uploads/names">{t("uploads.hub.names")}</a></p></div>
      <div class="grid">{''.join(cards)}</div>"""


def check_upload_file():
    """POST /uploads/check: find the kind of the dropped file (or take the chosen one) and go to that kind's check."""
    chosen = request.form.get("kind", "auto")
    upload = request.files.get("file")
    try:
        if not upload or not upload.filename:
            raise FileProblem(plain("uploads.problem.noFile"))
        data = upload.read()
        if chosen == "auto":
            found = upload_detect.detect(upload.filename, data)
            if len(found) > 1:
                names = ", ".join(kind_title(kind, plain_text=True) for kind in found)
                return page.render(hub_page(f"<div class='error'>{h(plain('uploads.hub.ambiguous', kinds=names))}</div>", found[0]), 400)
            if not found:
                return page.render(hub_page(f"<div class='error'>{t('uploads.hub.unknown')}</div>"), 400)
            chosen = found[0]
        if chosen not in upload_detect.KINDS:
            return unknown_upload()
        upload.stream.seek(0)  # the roster and the historical CSV are kept as files; the rest was read above
        if chosen == "roster":
            return transfer_pages.start_roster(upload, request.form.get("transfer_date", ""))
        if chosen == "historical":
            return historical_pages.start_historical(upload, request.form.get("duplicate_policy", "replace"))
        if chosen == "people":
            parsed = data_types.parse_people(read_table(upload.filename, data))
        elif chosen == "vollzogen":
            parsed = data_types.parse_vollzogen(read_table(upload.filename, data))
        else:
            parsed = read_upload(chosen, upload.filename, data)  # read in memory; the file is never saved
    except FileProblem as error:
        return page.render(hub_page(f"<div class='error'><b>{t('uploads.review.notRead')}</b><br>{h(error)}</div>", chosen), 400)
    save_pending(chosen, upload.filename, parsed)
    return redirect(review_address(chosen))


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
        ("uploads.review.namesToMatch", len(questions)))
        + ((("uploads.geo.flaggedCount", len(parsed.get("flagged") or [])),) if parsed.get("flagged") else ()))
    lines = "".join(f"<li>{line}</li>" for line in check["lines"] + [t(f"uploads.{spec['text']}.merge")])
    problems = "".join(f"<tr><td>{n}</td><td>{h(text)}</td></tr>" for n, text in parsed["problems"])
    problem_card = (f"""<div class="card"><h3>{t("uploads.review.problemTitle")}</h3><p class="muted">{t("uploads.review.problemHelp")}</p>
      <div class="scroll"><table><thead><tr><th>{t("uploads.col.row")}</th><th>{t("uploads.col.problem")}</th></tr></thead>
      <tbody>{problems}</tbody></table></div>{f"<p class='muted'>{t('uploads.review.moreProblems', count=parsed['problem_count'] - len(parsed['problems']))}</p>" if parsed['problem_count'] > len(parsed['problems']) else ""}</div>"""
                    if problems else "")
    names_card = names_form(slug, spec, check) if questions else ""
    flagged = parsed.get("flagged") or []
    flagged_rows = "".join(f"<tr><td>{n}</td><td>{h(name)}</td><td>{t('uploads.col.' + level)}</td><td>{h(why)}</td></tr>"
                           for n, name, level, why in flagged)
    flagged_card = (f"""<div class="card"><h3>{t("uploads.geo.flaggedTitle")}</h3><p class="muted">{t("uploads.geo.flaggedHelp")}</p>
      <div class="scroll"><table><thead><tr><th>{t("uploads.col.row")}</th><th>{t("uploads.col.nameInFile")}</th>
      <th>{t("uploads.col.level")}</th><th>{t("uploads.col.problem")}</th></tr></thead><tbody>{flagged_rows}</tbody></table></div></div>"""
                    if flagged else "")
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
      {names_card}{flagged_card}{problem_card}{apply_card}<div class="card">{cancel}</div>"""


def names_form(slug, spec, check):
    """Step 3: the names of the file that are not portal names, each with a list to match it."""
    matcher = check["matcher"]
    rows = []
    for (level, name), info in sorted(check["questions"].items(), key=lambda x: (x[0][0], x[0][1].casefold())):
        zones = ", ".join(sorted(info["zones"]))
        where = f"<br><span class='muted'>{t('uploads.names.inZone', zones=zones)}</span>" if zones else ""
        rows.append(f"""<tr><td>{t("uploads.names." + level)}</td><td>{h(name)}{where}
          <input type="hidden" name="level" value="{level}"><input type="hidden" name="name" value="{h(name)}"></td>
          <td>{info["rows"]}</td><td><select name="choice">{name_options(matcher, level, spec["historical"])}</select></td></tr>""")
    keep_all = (f"<p><label><input type='checkbox' name='keep_rest' value='yes'> "
                f"{t('uploads.names.keepRest')}</label></p>")
    return f"""<div class="card"><div class="step">{t("uploads.names.step")}</div><h3>{t("uploads.names.title")}</h3>
      <p class="muted">{t("uploads.names.help")}</p><form action="/uploads/{slug}/names" method="post">
      <div class="scroll"><table><thead><tr><th>{t("uploads.col.level")}</th><th>{t("uploads.col.nameInFile")}</th>
      <th>{t("uploads.col.rows")}</th><th>{t("uploads.col.portal")}</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div>
      {keep_all}<button>{t("uploads.names.save")}</button></form></div>"""


GEO_URBAN_COLUMNS = [("pop_urban_centre", "uploads.col.urban130"), ("pop_dense_urban_cluster", "uploads.col.urban223"),
                     ("pop_semi_dense_urban_cluster", "uploads.col.urban222"), ("pop_suburban", "uploads.col.urban221"),
                     ("pop_rural_very_low", "uploads.col.urban311"), ("pop_rural_low", "uploads.col.urban312")]


def geo_table_html(title_key, name_columns, rows, extra_columns=()):
    """One table of the Geo data page. name_columns: [(heading key, record field)]; the figures follow, then extra_columns."""
    figure_columns = [("uploads.col.population", "population"), ("uploads.col.size", "size_km2"),
                      ("uploads.col.density", "density_per_km2"), *[(key, field) for field, key in GEO_URBAN_COLUMNS],
                      ("uploads.col.areaType", "area_type"), *extra_columns]
    head = "".join(f"<th>{t(key)}</th>" for key, _ in [*name_columns, *figure_columns])
    body = []
    for r in rows:
        old = "" if r["active"] else f" <span class='badge'>{t('uploads.names.oldBadge')}</span>"
        cells = [f"<td>{h(r[field])}{old if i == len(name_columns) - 1 else ''}</td>" for i, (_, field) in enumerate(name_columns)]
        for _, field in figure_columns:
            value = r.get(field)
            cells.append(f"<td>{h(day_text(value) if field == 'data_date' else data_types.number_text(value) if field in ('size_km2', 'density_per_km2') else data_types.none_as_blank(value))}</td>")
        body.append("<tr>" + "".join(cells) + "</tr>")
    return (f"<h3>{t(title_key)}</h3><div class='scroll'><table><thead><tr>{head}</tr></thead>"
            f"<tbody>{''.join(body)}</tbody></table></div>")


def geo_area_form(areas, error=None, values=None):
    """The areas of the Geo data table as a form to edit: population, size, households, urban type, assignment type and the
    extra attributes are typed (an empty box clears a value); the density, the urbanisation figures, the area type, the
    source and the date are shown to read (they change by upload)."""
    values = values or {}
    datalists = ("<datalist id='urbanTypes'>" + "".join(f"<option value='{h(x)}'>" for x in data_types.URBAN_TYPES)
                 + "</datalist><datalist id='assignmentTypes'>"
                 + "".join(f"<option value='{h(x)}'>" for x in data_types.ASSIGNMENT_TYPES) + "</datalist>")
    read_columns = [*GEO_URBAN_COLUMNS, ("area_type", "uploads.col.areaType"), ("source", "uploads.col.source"),
                    ("data_date", "uploads.col.dataDate")]
    rows = []
    for a in areas:
        v = values.get(str(a["area_id"])) or {
            "population": data_types.none_as_blank(a.get("population")), "size": data_types.number_text(a.get("size_km2")),
            "households": data_types.none_as_blank(a.get("households")), "urban": a.get("urban_type") or "",
            "assignment": a.get("assignment_type") or "",
            "extra": "; ".join(f"{k}: {x}" for k, x in (a.get("extra") or {}).items())}
        old = "" if a["active"] else f" <span class='badge'>{t('uploads.names.oldBadge')}</span>"
        shown = "".join(f"<td>{h(day_text(a.get(f)) if f == 'data_date' and a.get(f) else data_types.none_as_blank(a.get(f)))}</td>"
                        for f, _ in read_columns)
        rows.append(f"""<tr><td>{h(a['zone'])}</td><td>{h(a['district'])}</td><td>{h(a['area'])}{old}
          <input type="hidden" name="area_id" value="{a['area_id']}"></td>
          <td><input name="population" inputmode="numeric" value="{h(v['population'])}" size="7"></td>
          <td><input name="size" inputmode="decimal" value="{h(v['size'])}" size="6"></td>
          <td>{h(data_types.number_text(a.get('density_per_km2')))}</td>
          <td><input name="households" inputmode="numeric" value="{h(v['households'])}" size="6"></td>
          <td><input name="urban" list="urbanTypes" value="{h(v['urban'])}" size="9"></td>
          <td><input name="assignment" list="assignmentTypes" value="{h(v['assignment'])}" size="11"></td>
          <td><input name="extra" value="{h(v['extra'])}" size="22"></td>{shown}</tr>""")
    problem = f"<div class='error'>{h(error)}</div>" if error else ""
    heads = "".join(f"<th>{t(key)}</th>" for key in ("uploads.col.zone", "uploads.col.district", "uploads.col.area",
                                                      "uploads.col.population", "uploads.col.size", "uploads.col.density",
                                                      "uploads.col.households", "uploads.col.urban", "uploads.col.assignment",
                                                      "uploads.col.extra"))
    heads += "".join(f"<th>{t(key)}</th>" for _, key in read_columns)
    return f"""{problem}<h3>{t("uploads.geo.areasTitle")}</h3><p class="muted">{t("uploads.geo.editHelp")}</p>
      <p class="muted">{t("uploads.geo.extraHelp")}</p><form action="/uploads/geo/table" method="post">{datalists}
      <div class="scroll"><table><thead><tr>{heads}</tr></thead><tbody>{''.join(rows)}</tbody></table></div>
      <p><button>{t("uploads.geo.save")}</button></p></form>"""


def geo_table_page(error=None, values=None):
    """The Geo data page: the areas as a table to edit, then the zones and districts as tables to read (their figures change
    by upload, so each change has a source and is in Import history)."""
    with database.connect() as conn:
        with database.cursor(conn) as cur:
            zones, districts, areas = geo_zone_rows(cur), geo_district_rows(cur), geo_rows(cur)
    zone, district = ("uploads.col.zone", "zone"), ("uploads.col.district", "district")
    return f"""<div class="card"><h2>{t("uploads.geo.tableTitle")}</h2>{geo_area_form(areas, error, values)}</div>
      <div class="card"><p class="muted">{t("uploads.geo.tableHelp")}</p>
      {geo_table_html("uploads.geo.zonesTitle", [zone], zones)}{geo_table_html("uploads.geo.districtsTitle", [zone, district], districts)}
      <p><a href="/uploads">{t("uploads.page.back")}</a></p></div>"""


def area_table_records(form):
    """The Geo data table as records to save, with the typed values for showing the table again after a mistake.
    Raises ValueError (with the area's row) for a value that is not a number."""
    names = ["area_id", "population", "size", "households", "urban", "assignment", "extra"]
    columns = [form.getlist(n) for n in names]
    if len({len(c) for c in columns}) != 1:
        raise ValueError(plain("uploads.geo.incomplete"))
    records, typed = [], {}
    for area_id, population, size, households, urban, assignment, extra in zip(*columns):
        if not area_id.isdigit():
            raise ValueError(plain("uploads.geo.incomplete"))
        typed[area_id] = {"population": population, "size": size, "households": households, "urban": urban,
                          "assignment": assignment, "extra": extra}
        records.append({"area_id": int(area_id), "population": data_files.read_count(population),
                        "size_km2": area_size(size), "households": data_files.read_count(households),
                        "urban_type": clean(urban)[:60] or None, "assignment_type": clean(assignment)[:60] or None,
                        "extra": extra_attributes(extra)})
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
            raise ValueError(plain("uploads.geo.extraFormat", text=clean(part)))
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


@pages.route("/uploads/check", methods=["POST"])
def upload_check():
    if not sign_in.allowed():
        return sign_in.go_to_login()
    return check_upload_file()


@pages.route("/uploads/<slug>")
def upload_start(slug):
    """The old address of one upload: every kind of file is dropped on /uploads now."""
    return redirect("/uploads")


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


@pages.route("/uploads/geo/table", methods=["GET", "POST"])
def geo_table():
    """The Geo data table: shows it, or saves the typed areas as one batch in Import history."""
    if not sign_in.allowed():
        return sign_in.go_to_login()
    if request.method == "GET":
        return page.render(geo_table_page())
    try:
        records, typed = area_table_records(request.form)
    except ValueError as error:
        return page.render(geo_table_page(error=str(error)), 400)
    conn = database.connect()
    try:
        with database.cursor(conn) as cur:  # only this mission's areas may be saved here
            cur.execute("""select a.id from public.areas a join public.districts d on d.id=a.district_id
              join public.zones z on z.id=d.zone_id where z.mission_id=%s""", (sign_in.current_mission_id(),))
            mine = {r["id"] for r in cur.fetchall()}
        if any(r["area_id"] not in mine for r in records):
            raise ValueError(plain("uploads.geo.outside"))
        batch = save_geo_table(conn, records, plain("uploads.geo.tableFile"))
        conn.commit()
    except ValueError as error:
        conn.rollback()
        return page.render(geo_table_page(error=str(error), values=typed), 400)
    finally:
        conn.close()
    flash(plain("uploads.geo.tableSaved") if batch else plain("uploads.geo.tableSame"))
    return redirect("/uploads/geo/table")


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
