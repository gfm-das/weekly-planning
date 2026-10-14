"""The Vollzogen pages (/uploads/vollzogen/...): put in the office's list of baptized and confirmed people. The rules are
vollzogen_upload.py; the reading of the sheet is data_types.parse_vollzogen.

  /uploads/vollzogen            1. the template and the file form, and the uploads so far
  /uploads/vollzogen/template   the template as a CSV file
  /uploads/vollzogen/preview    reads the file (in memory) and keeps its rows waiting, then shows the check
  /uploads/vollzogen/review     2. the check: numbers, people who may be the same as someone in the portal, then Apply
  /uploads/vollzogen/apply      3. Apply, after the "I checked" tick (one batch in Import history, with Undo)
  /uploads/vollzogen/cancel     drops the waiting rows
  /uploads/vollzogen/table      the stored list, to read

These routes are more exact than the generic /uploads/<kind> ones of data_upload_pages.py, so Flask picks these. Names ARE
read and stored here (that is what the list is for); the waiting rows are kept in a small file on the server until Apply or
Cancel, and deleted after a day at the latest (data_uploads.tidy_now_and_then). Every text is from data_text.py.
"""
from flask import Blueprint, Response, flash, redirect, request

import data_files
import data_types
import data_upload_pages
import data_uploads
import database
import page
import sign_in
import vollzogen_upload
from data_files import FileProblem
from data_text import plain, t
from page import h, mission_time

pages = Blueprint("vollzogen_pages", __name__)
SLUG = vollzogen_upload.SLUG
BASE = "/uploads/vollzogen"


def day_cell(iso):
    return h(data_uploads.day_text(iso)) if iso else ""


def confirmed_cell(record):
    """A tick, with the date when the sheet gave one."""
    if not record.get("confirmed"):
        return ""
    return "✓ " + day_cell(record.get("confirmed_on"))


def sample_table(records, names):
    """The first 8 people the upload would store. names: {record_key: the portal person it is linked to}."""
    head = "".join(f"<th>{t(key)}</th>" for key in ("uploads.col.name", "uploads.col.baptismDate", "uploads.col.confirmed",
                                                      "uploads.col.zone", "uploads.col.unit", "uploads.col.linkedTo"))
    body = "".join(f"<tr><td>{h(r['full_name'])}</td><td>{day_cell(r['baptism_date'])}</td><td>{confirmed_cell(r)}</td>"
                   f"<td>{h(r.get('zone'))}</td><td>{h(r.get('unit'))}</td><td>{h(names.get(r['record_key']))}</td></tr>"
                   for r in records[:8])
    return f"<div class='scroll'><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>"


def person_text(name, zone, day):
    bits = [bit for bit in (zone, data_uploads.day_text(day) if day else "") if bit]
    return f"<b>{h(name)}</b><br><span class='muted'>{h(' · '.join(str(b) for b in bits))}</span>"


def question_card(questions):
    """One same / different choice per open pair (the answers go to /people/decide, which remembers them)."""
    if not questions:
        return ""
    reasons = {"same_name_unsure": t("uploads.vollzogen.reasonName"), "alike_name": t("uploads.vollzogen.reasonAlike")}
    rows = []
    for q in questions:
        record, member = q["record"], q["member"]
        field = h("decide::" + "|".join(q["keys"]))
        rows.append(f"""<tr><td>{person_text(record['full_name'], record.get('zone'), record['baptism_date'])}</td>
          <td>{person_text(member['label'], member['zone'], member['baptism_date'])}</td><td class="muted">{reasons[q['reason']]}</td>
          <td><label><input type="radio" name="{field}" value="same"> {t("uploads.vollzogen.samePerson")}</label><br>
          <label><input type="radio" name="{field}" value="different"> {t("uploads.vollzogen.differentPeople")}</label></td></tr>""")
    return f"""<div class="card" id="people-questions"><div class="step">{t("uploads.vollzogen.questionsStep")}</div>
      <h3>{t("uploads.vollzogen.questionsTitle", count=len(questions))}</h3><p class="muted">{t("uploads.vollzogen.questionsHelp")}</p>
      <form action="/people/decide" method="post"><input type="hidden" name="back" value="{BASE}/review">
      <div class="scroll"><table><thead><tr><th>{t("uploads.vollzogen.inList")}</th><th>{t("uploads.vollzogen.inPortal")}</th>
      <th>{t("uploads.vollzogen.why")}</th><th>{t("uploads.vollzogen.answer")}</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div>
      <p><button>{t("uploads.vollzogen.saveAnswers")}</button></p></form></div>"""


# ------------------------------------------------------------------------------------------ the pages

def start_page():
    with database.connect() as conn:
        with database.cursor(conn) as cur:
            recent = data_upload_pages.recent_uploads(cur, vollzogen_upload.KIND)
    rows = "".join(f"<tr><td><a href='/imports/{r['id']}'>{h(r['filename'])}</a></td><td>{mission_time(r['created_at'])}</td>"
                   f"<td>{h(r['actor'])}</td><td>{t('uploads.status.' + r['status'].lower())}</td></tr>" for r in recent)
    history = (f"<div class='scroll'><table><thead><tr><th>{t('uploads.col.file')}</th><th>{t('uploads.col.when')}</th>"
               f"<th>{t('uploads.col.by')}</th><th>{t('uploads.col.status')}</th></tr></thead><tbody>{rows}</tbody></table></div>"
               if rows else f"<p class='muted'>{t('uploads.hub.none')}</p>")
    return f"""{data_upload_pages.pending_card(SLUG)}<div class="card"><div class="step">{t("uploads.page.step1")}</div>
      <h2>{t("uploads.vollzogen.title")}</h2><p class="muted">{t("uploads.vollzogen.about")}</p>
      <p><a href="{BASE}/template">{t("uploads.page.template")}</a></p><p><a href="{BASE}/table">{t("uploads.vollzogen.viewTable")}</a></p>
      <form action="{BASE}/preview" method="post" enctype="multipart/form-data">
        <div class="form-field"><label class="file-pick"><span>{t("uploads.page.file")}</span><input type="file" name="file" accept=".csv,.xlsx" required></label></div>
        <button>{t("uploads.page.check")}</button></form></div>
      <div class="card"><h3>{t("uploads.page.how")}</h3><ul><li>{t("uploads.vollzogen.columns")}</li>
        <li>{t("uploads.vollzogen.merge")}</li><li>{t("uploads.vollzogen.privacy")}</li><li>{t("uploads.vollzogen.fcAbout")}</li>
        <li>{t("uploads.page.never")}</li></ul></div>
      <div class="card"><h3>{t("uploads.page.recent")}</h3>{history}<p><a href="/uploads">{t("uploads.page.back")}</a></p></div>"""


def review_page(pending):
    parsed = pending["parsed"]
    records = parsed["records"]
    with database.connect() as conn:
        with database.cursor(conn) as cur:
            planned = vollzogen_upload.plan(cur, records)
            members = {m["id"]: m["label"] for m in vollzogen_upload.stored_members(cur, sign_in.current_mission_id())}
    counts, found = planned["counts"], planned["found"]
    names = {key: members.get(link["member_id"], "") for key, link in found["links"].items()}
    metrics = "".join(f"<div class='metric'><b>{value}</b><br>{t(key)}</div>" for key, value in (
        ("uploads.review.rowsRead", parsed["rows_read"]), ("uploads.review.rowsToStore", len(records)),
        ("uploads.review.leftOut", parsed["left_out"]), ("uploads.review.problems", parsed["problem_count"]),
        ("uploads.vollzogen.metricLinked", counts["linked"]), ("uploads.vollzogen.metricAsk", len(found["questions"]))))
    lines = [t("uploads.vollzogen.people", new=counts["new"], changed=counts["changed"], same=counts["same"]),
             t("uploads.vollzogen.linked", linked=counts["linked"], fc=counts["by_fc"], name=counts["by_name"],
               asked=counts["asked"]),
             t("uploads.vollzogen.notLinked", count=counts["unlinked"]), t("uploads.vollzogen.merge")]
    lines += [h(n) for n in found["notices"]]
    problems = "".join(f"<tr><td>{n}</td><td>{h(text)}</td></tr>" for n, text in parsed["problems"])
    more = (f"<p class='muted'>{t('uploads.review.moreProblems', count=parsed['problem_count'] - len(parsed['problems']))}</p>"
            if parsed["problem_count"] > len(parsed["problems"]) else "")
    problem_card = (f"""<div class="card"><h3>{t("uploads.review.problemTitle")}</h3><p class="muted">{t("uploads.review.problemHelp")}</p>
      <div class="scroll"><table><thead><tr><th>{t("uploads.col.row")}</th><th>{t("uploads.col.problem")}</th></tr></thead>
      <tbody>{problems}</tbody></table></div>{more}</div>""" if problems else "")
    ready = not found["questions"] and records
    apply_card = (f"""<div class="card"><form action="{BASE}/apply" method="post">
        <p><label><input type="checkbox" name="confirmed" value="yes" required> {t("uploads.review.confirm")}</label></p>
        <button>{t("uploads.review.apply")}</button></form></div>""" if ready else
                  f"<div class='card'><p class='warn'>{t('uploads.vollzogen.answerFirst' if found['questions'] else 'uploads.vollzogen.allPlaceholders' if parsed['left_out'] and not records else 'uploads.review.nothing')}</p></div>")
    cancel = (f"<form action='{BASE}/cancel' method='post'><button class='secondary'>{t('uploads.review.cancel')}</button>"
              f" <a href='{BASE}'>{t('uploads.page.back')}</a></form>")
    return f"""<div class="card"><div class="step">{t("uploads.review.step")}</div><h2>{t("uploads.vollzogen.title")}: {h(pending['filename'])}</h2>
      <div class="grid">{metrics}</div><ul>{''.join(f'<li>{line}</li>' for line in lines)}</ul>{sample_table(records, names) if records else ""}</div>
      {question_card(found["questions"])}{problem_card}{apply_card}<div class="card">{cancel}</div>"""


def table_page():
    """The stored list, to read (the newest 1000 baptisms)."""
    with database.connect() as conn:
        with database.cursor(conn) as cur:
            rows = vollzogen_upload.table_rows(cur)
    head = "".join(f"<th>{t(key)}</th>" for key in (
        "uploads.col.foundHow", "uploads.col.name", "uploads.col.dateSet", "uploads.col.baptismDate", "uploads.col.workers",
        "uploads.col.unit", "uploads.col.stake", "uploads.col.zone", "uploads.col.confirmed", "uploads.col.country",
        "uploads.col.gender", "uploads.col.language", "uploads.col.linkedTo"))
    body = "".join(f"""<tr><td>{h(r['found_how'])}</td><td>{h(r['full_name'])}</td>
      <td>{day_cell(r['baptismal_date_set_on'].isoformat() if r['baptismal_date_set_on'] else '')}</td>
      <td>{day_cell(r['baptism_date'].isoformat())}</td><td>{h(r['workers'])}</td><td>{h(r['unit'])}</td><td>{h(r['stake'])}</td>
      <td>{h(r['zone'])}</td><td>{confirmed_cell({'confirmed': r['confirmed'], 'confirmed_on': r['confirmed_on'].isoformat() if r['confirmed_on'] else ''})}</td>
      <td>{h(r['country'])}</td><td>{h(r['gender'])}</td><td>{h(r['preferred_language'])}</td><td>{h(r['linked_name'])}</td></tr>"""
                   for r in rows)
    return f"""<div class="card"><h2>{t("uploads.vollzogen.tableTitle")}</h2><p class="muted">{t("uploads.vollzogen.tableHelp")}</p>
      <div class="scroll"><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>
      <p><a href="{BASE}">{t("uploads.page.back")}</a></p></div>"""


# ------------------------------------------------------------------------------------------ routes

@pages.route(BASE)
def start():
    if not sign_in.allowed():
        return sign_in.go_to_login()
    return page.render(start_page())


@pages.route(f"{BASE}/template")
def template():
    if not sign_in.allowed():
        return sign_in.go_to_login()
    headings, rows = data_types.vollzogen_template()
    return Response(data_files.as_csv(headings, rows), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=template-vollzogen.csv"})


@pages.route(f"{BASE}/preview", methods=["POST"])
def preview():
    """Reads the uploaded file in memory, keeps its rows waiting, and opens the check."""
    if not sign_in.allowed():
        return sign_in.go_to_login()
    upload = request.files.get("file")
    try:
        if not upload or not upload.filename:
            raise FileProblem(plain("uploads.problem.noFile"))
        parsed = data_types.parse_vollzogen(data_files.read_table(upload.filename, upload.read()))
    except FileProblem as error:
        return page.render(f"<div class='error'><b>{t('uploads.review.notRead')}</b><br>{h(error)}</div>"
                           f"<p><a href='{BASE}'>{t('uploads.page.back')}</a></p>", 400)
    data_uploads.save_pending(SLUG, upload.filename, parsed)
    return redirect(f"{BASE}/review")


@pages.route(f"{BASE}/review")
def review():
    if not sign_in.allowed():
        return sign_in.go_to_login()
    pending = data_uploads.load_pending(SLUG)
    if not pending:
        return data_upload_pages.upload_gone()
    return page.render(review_page(pending))


@pages.route(f"{BASE}/apply", methods=["POST"])
def apply():
    if not sign_in.allowed():
        return sign_in.go_to_login()
    pending = data_uploads.load_pending(SLUG)
    if not pending:
        return data_upload_pages.upload_gone()
    try:
        if request.form.get("confirmed") != "yes":
            raise ValueError(plain("uploads.review.confirmFirst"))
        batch = vollzogen_upload.apply(pending)
    except ValueError as error:
        return page.render(f"<div class='error'><b>{t('uploads.review.notSaved')}</b><br>{h(error)}</div>"
                           f"<p><a href='{BASE}/review'>{t('uploads.page.openCheck')}</a></p>", 409)
    data_uploads.drop_pending(SLUG)
    if not batch:
        flash(plain("uploads.review.nothingNew"))
        return redirect(BASE)
    flash(plain("uploads.review.saved"))
    return redirect(f"/imports/{batch}")


@pages.route(f"{BASE}/cancel", methods=["POST"])
def cancel():
    if not sign_in.allowed():
        return sign_in.go_to_login()
    data_uploads.drop_pending(SLUG)
    return redirect(BASE)


@pages.route(f"{BASE}/table")
def table():
    if not sign_in.allowed():
        return sign_in.go_to_login()
    return page.render(table_page())
