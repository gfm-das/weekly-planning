"""The People upload pages (/people-upload/...): put new members in from a spreadsheet. The rules are people_upload.py.

  /people-upload           1. the template and the file form
  /people-upload/preview   reads the file (in memory) and keeps its rows waiting, then shows the check
  /people-upload/review    2. the check: numbers, names to match, pairs that may be the same person, then Apply
  /people-upload/names     saves the area names the manager matched
  /people-upload/apply     3. Apply, after the "I checked" tick (one batch in Import history, with Undo)
  /people-upload/cancel    drops the waiting rows

Names are read on purpose here (that is what this upload is for). The waiting rows are kept in a small file on the
server until Apply or Cancel, and deleted after a day at the latest (data_uploads.tidy_now_and_then).
"""
from flask import Blueprint, Response, flash, redirect, request

import data_files
import data_names
import data_types
import data_upload_pages
import data_uploads
import database
import page
import people_pages
import people_upload
import sign_in
from data_files import FileProblem
from page import h

pages = Blueprint("people_upload_pages", __name__)
SLUG = people_upload.SLUG


@pages.route("/people-upload")
def start():
    if not sign_in.allowed():
        return sign_in.go_to_login()
    waiting = data_uploads.load_pending(SLUG)
    note = (f"<div class='flash'>A checked file is waiting: {h(waiting['filename'])} "
            "<a href='/people-upload/review'>Open the check</a></div>" if waiting else "")
    return page.render(f"""{note}<div class="card"><div class="step">1 · Upload</div><h2>People upload</h2>
      <p class="muted">Put in new members with their details from a spreadsheet, for example the office's Vollzogen sheets or the
      New Member Database Raw form. People who are already stored are recognised and only get their blanks filled; nobody is
      counted twice. Anyone still relevant (a new member up to one year after the baptism) is loaded into this week's plan of
      their area.</p>
      <p><a href="/people-upload/template">Download the template (CSV)</a></p>
      <form action="/people-upload/preview" method="post" enctype="multipart/form-data">
        <label class="form-field">CSV or XLSX file<input type="file" name="file" accept=".csv,.xlsx" required></label>
        <button>Check the file</button></form></div>
      <div class="card"><h3>How it works</h3><ul>
        <li>Columns read: First name and Last name (or Name), Baptism date (Date of Baptism, Taufdatum), Zone, Area (or the
        companionship), Ward or branch (Gemeinde), Confirmation date, Finding source, Gender, Age range and the other details of the
        New Member Database. A row without a baptism date is left out.</li>
        <li>The area comes from the area name. A closed area is asked about: the standard is to move its people to a current area.
        A row with no area is placed by its ward or branch when only one open area serves it, otherwise it is left out.</li>
        <li>A name that may be someone already stored is asked about before anything is saved, and your answer is remembered.</li>
        <li>Names are stored with the person, like a New Member typed in by a missionary. Everything is one entry in
        <a href="/imports">Import history</a>, where it can be undone.</li></ul></div>""")


@pages.route("/people-upload/template")
def template():
    if not sign_in.allowed():
        return sign_in.go_to_login()
    headings, rows = data_types.people_template()
    return Response(data_files.as_csv(headings, rows), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=template-people.csv"})


@pages.route("/people-upload/preview", methods=["POST"])
def preview():
    """Reads the uploaded file in memory, keeps its rows waiting, and opens the check."""
    if not sign_in.allowed():
        return sign_in.go_to_login()
    upload = request.files.get("file")
    try:
        if not upload or not upload.filename:
            raise FileProblem("Choose a file first.")
        parsed = data_types.parse_people(data_files.read_table(upload.filename, upload.read()))
    except FileProblem as error:
        return page.render(f"<div class='error'><b>The file could not be read.</b><br>{h(error)}</div><p><a href='/people-upload'>Back</a></p>", 400)
    data_uploads.save_pending(SLUG, upload.filename, parsed)
    return redirect("/people-upload/review")


def waiting_or_start():
    pending = data_uploads.load_pending(SLUG)
    if not pending:
        flash("The waiting file is gone (applied, cancelled, or older than a day). Upload it again.")
    return pending


@pages.route("/people-upload/review")
def review():
    if not sign_in.allowed():
        return sign_in.go_to_login()
    pending = waiting_or_start()
    if not pending:
        return redirect("/people-upload")
    return page.render(review_page(pending))


def review_page(pending):
    parsed = pending["parsed"]
    records = parsed["records"]
    with database.connect() as conn:
        with database.cursor(conn) as cur:
            planned = people_upload.plan(cur, records)
            areas = people_pages.area_labels(cur)
    counts, found = planned["counts"], planned["found"]
    metrics = "".join(f"<div class='metric'><b>{value}</b><br>{label}</div>" for label, value in (
        ("rows read", parsed["rows_read"]), ("people to save", counts["people"]),
        ("already stored (joined, blanks filled)", counts["to_join"]), ("rows left out: no area", counts["unplaced"]),
        ("rows with problems", parsed["problem_count"]), ("area names to match", len(planned["names"]))))
    problems = "".join(f"<tr><td>{n}</td><td>{h(text)}</td></tr>" for n, text in parsed["problems"])
    problem_card = (f"<div class='card'><h3>Rows that are left out</h3><div class='scroll'><table><thead><tr><th>Row</th><th>Problem</th></tr></thead>"
                    f"<tbody>{problems}</tbody></table></div></div>" if problems else "")
    names_card = names_form(planned) if planned["names"] else ""
    back = "/people-upload/review"
    questions_card = people_pages.question_card(found["questions"], back, areas)
    ready = not planned["names"] and not found["questions"] and counts["people"]
    apply_card = ("""<div class="card"><form action="/people-upload/apply" method="post">
        <p><label><input type="checkbox" name="confirmed" value="yes" required> I checked the numbers above.</label></p>
        <button>Save these people</button></form></div>""" if ready else
                  "<div class='card'><p class='warn'>Answer the questions above to enable Apply.</p></div>" if (planned["names"] or found["questions"])
                  else "<div class='card'><p class='warn'>There is nobody to save in this file.</p></div>")
    notices = "".join(f"<li>{h(n)}</li>" for n in found["notices"])
    return f"""<div class="card"><div class="step">2 · Check</div><h2>{h(pending['filename'])}</h2><div class="grid">{metrics}</div>
      {f"<ul>{notices}</ul>" if notices else ""}</div>{names_card}{questions_card}{problem_card}{apply_card}
      <div class="card"><form action="/people-upload/cancel" method="post"><button class="secondary">Cancel and drop the file</button>
      <a href="/people-upload">Back</a></form></div>"""


def names_form(planned):
    """The area names of the file that are not portal areas (or are closed areas), each with a list to match it."""
    matcher = planned["matcher"]
    rows = []
    for (level, name), info in sorted(planned["names"].items(), key=lambda x: x[0][1].casefold()):
        zones = ", ".join(sorted(info["zones"]))
        where = f"<br><span class='muted'>in zone {h(zones)}</span>" if zones else ""
        rows.append(f"""<tr><td>{h(name)}{where}<input type="hidden" name="level" value="{level}">
          <input type="hidden" name="name" value="{h(name)}"></td><td>{info['rows']}</td>
          <td><select name="choice">{data_upload_pages.name_options(matcher, 'area', True, leave_out=True)}</select></td></tr>""")
    return f"""<div class="card"><div class="step">2b · Areas</div><h3>Which area is this?</h3>
      <p class="muted">Choose the current area these people belong to (the standard for a closed area). Choosing an area marked
      "Old" keeps them in that old area. "Leave out" saves nobody from these rows. Your answer is remembered.</p>
      <form action="/people-upload/names" method="post"><div class="scroll"><table><thead><tr><th>Area name in the file</th>
      <th>Rows</th><th>Portal area</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div>
      <p><button>Save &amp; recheck</button></p></form></div>"""


@pages.route("/people-upload/names", methods=["POST"])
def names():
    """Saves the area names the manager matched, then shows the check again."""
    if not sign_in.allowed():
        return sign_in.go_to_login()
    if not data_uploads.load_pending(SLUG):
        return redirect("/people-upload")
    saved = 0
    with database.connect() as conn:
        with database.cursor(conn) as cur:
            for name, choice in zip(request.form.getlist("name"), request.form.getlist("choice")):
                if choice:
                    saved += data_names.remember(cur, sign_in.current_mission_id(), "area", name, choice, sign_in.actor_name())
    flash(f"{saved} name(s) saved.")
    return redirect("/people-upload/review")


@pages.route("/people-upload/apply", methods=["POST"])
def apply():
    if not sign_in.allowed():
        return sign_in.go_to_login()
    pending = waiting_or_start()
    if not pending:
        return redirect("/people-upload")
    try:
        if request.form.get("confirmed") != "yes":
            raise ValueError("Tick the box to confirm first.")
        batch = people_upload.apply(pending)
    except ValueError as error:
        return page.render(f"<div class='error'><b>Nothing was saved.</b><br>{h(error)}</div><p><a href='/people-upload/review'>Back to the check</a></p>", 409)
    data_uploads.drop_pending(SLUG)
    if not batch:
        flash("There was nobody new to save.")
        return redirect("/people-upload")
    flash("People saved. They are on Import history, where this can be undone.")
    return redirect(f"/imports/{batch}")


@pages.route("/people-upload/cancel", methods=["POST"])
def cancel():
    if not sign_in.allowed():
        return sign_in.go_to_login()
    data_uploads.drop_pending(SLUG)
    return redirect("/people-upload")
