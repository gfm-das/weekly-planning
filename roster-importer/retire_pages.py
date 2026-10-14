"""The Delete retired pages (/retire/...): delete a closed zone, district or area, or a retired Weekly Planning question.
The rules are retire.py, the backup is backups.py, every text is retire_text.py.

Pages:
  /retire                                  the closed places and the retired questions, each with "Review and delete"
  /retire/place/<kind>/<id>                the impact preview of one place; ?into=<id> checks a merge onto another place
  /retire/place/<kind>/<id>/delete         the delete (POST): typed name, backup, one batch in Import history
  /retire/question/<key>                   the impact preview of one question; ?into=<key> or ?drop=yes for its saved answers
  /retire/question/<key>/delete            the delete (POST)
Every route checks the person itself (roles.may_retire): hiding a link is not security.
"""
from flask import Blueprint, flash, redirect, request

import database
import page
import planning_questions as pq
import retire
import roles
import sign_in
from page import h
from retire_text import plain, t

pages = Blueprint("retire_pages", __name__)
CATEGORY_ORDER = ["plans", "people", "callins", "history", "places", "settings", "other"]


def refused():
    """The page for someone who may not use Delete retired, or None."""
    if not sign_in.allowed():
        return sign_in.go_to_login()
    if not roles.may_retire():
        return page.render(f"<div class='error'>{t('retire.error.notAllowed')}</div>", 403)
    return None


def whole_number(text):
    return int(text) if str(text or "").isdigit() else None


def back_link():
    return f"<p><a href='/retire'>{t('retire.back')}</a></p>"


# ------------------------------------------------------------------------------------------ the list

def list_page():
    with database.connect() as conn:
        with database.cursor(conn) as cur:
            places = retire.closed_places(cur, sign_in.current_mission_id())
            questions = retire.retired_questions(cur)
    place_rows = "".join(
        f"<tr><td>{t('retire.kind.' + p['level'])}</td><td>{h(p['name'])}</td><td>{h(p['parent'])}</td>"
        f"<td><a href='/retire/place/{p['level']}/{p['id']}'>{t('retire.review')}</a></td></tr>" for p in places)
    question_rows = "".join(
        f"<tr><td>{h(q['question_label'])}<br><span class='muted'>{h(q['question_key'])}</span></td><td>{q['answers']}</td>"
        f"<td><a href='/retire/question/{h(q['question_key'])}'>{t('retire.review')}</a></td></tr>" for q in questions)
    places_card = (f"<div class='scroll'><table><thead><tr><th>{t('retire.col.kind')}</th><th>{t('retire.col.name')}</th>"
                   f"<th>{t('retire.col.where')}</th><th></th></tr></thead><tbody>{place_rows}</tbody></table></div>"
                   if places else f"<p class='muted'>{t('retire.places.none')}</p>")
    questions_card = (f"<div class='scroll'><table><thead><tr><th>{t('retire.col.name')}</th><th>{t('retire.col.answers')}</th><th></th>"
                      f"</tr></thead><tbody>{question_rows}</tbody></table></div>"
                      if questions else f"<p class='muted'>{t('retire.questions.none')}</p>")
    return (f"<div class='card'><h2>{t('retire.title')}</h2><p class='muted'>{t('retire.intro')}</p></div>"
            f"<div class='card'><h3>{t('retire.places.title')}</h3>{places_card}</div>"
            f"<div class='card'><h3>{t('retire.questions.title')}</h3>{questions_card}</div>")


@pages.route("/retire")
def retire_list():
    blocked = refused()
    return blocked or page.render(list_page())


# ------------------------------------------------------------------------------------------ a place

def impact_table(found):
    """The counts of what is attached, grouped by what the tables hold; the technical table names stay small."""
    by_category = {}
    for x in found:
        by_category.setdefault(x["category"], []).append(x)
    rows = []
    for category in CATEGORY_ORDER:
        items = by_category.get(category)
        if not items:
            continue
        detail = ", ".join(f"{x['table']}: {x['count']}" for x in items)
        rows.append(f"<tr><td>{t('retire.cat.' + category)}<br><span class='muted'>{h(detail)}</span></td>"
                    f"<td>{sum(x['count'] for x in items)}</td></tr>")
    return (f"<div class='scroll'><table><thead><tr><th>{t('retire.place.attached')}</th><th>{t('retire.col.rows')}</th>"
            f"</tr></thead><tbody>{''.join(rows)}</tbody></table></div>")


def place_page(level, place_id, into=None, typed_error=None):
    """Returns (html, status) for the review of one place."""
    mission_id = sign_in.current_mission_id()
    with database.connect() as conn:
        with database.cursor(conn) as cur:
            place = retire.place_row(cur, level, place_id)
            if not place or place["mission_id"] != mission_id:
                return f"<div class='error'>{t('retire.error.notFound')}</div>{back_link()}", 404
            serving = retire.serving_now(cur, place_id) if level == "area" else 0
            found = retire.attached(cur, level, place_id)
            derived = retire.derived_counts(cur, level, place_id)
            options = retire.successors(cur, level, place)
    blocked = None
    if place["active"]:
        blocked = t("retire.place.open")
    elif serving:
        blocked = t("retire.place.serving", count=serving)
    needs_move = any(not x["removable"] for x in found)
    body = [f"<div class='card'><h2>{t('retire.place.title' + level.title(), name=place['name'])}</h2>"]
    if place["parent_name"]:
        body.append(f"<p class='muted'>{h(place['parent_name'])}</p>")
    body.append(impact_table(found) if found else f"<p>{t('retire.place.nothing')}</p>")
    if derived.get("answers"):
        body.append(f"<p class='muted'>{t('retire.place.answers', count=derived['answers'])}</p>")
    if any(x["removable"] for x in found):
        body.append(f"<p class='muted'>{t('retire.place.settingsNote')}</p>")
    body.append("</div>")
    if blocked:
        body.append(f"<div class='error'>{blocked}</div>{back_link()}")
        return "".join(body), 200
    if needs_move or options:
        choices = "".join(f"<option value='{i}'{' selected' if i == into else ''}>{h(label)}</option>" for i, label in options)
        body.append(f"""<div class="card"><h3>{t('retire.place.moveTitle')}</h3>
          {f"<p class='warn'>{t('retire.place.mustMove')}</p>" if needs_move and not into else ""}
          <form method="get" action="/retire/place/{level}/{place_id}"><label class="form-field">
          <select name="into"><option value="">{t('retire.place.moveNone')}</option>{choices}</select></label>
          <p class="muted">{t('retire.place.moveHelp')}</p><button class="secondary">{t('retire.place.check')}</button></form></div>""")
    verdict, can_delete = "", False
    if into or not needs_move:
        try:
            result = retire.check_place_delete(level, place_id, into)
            verdict = (f"<div class='card'><p class='good'>{t('retire.place.checkOk', moved=sum(result['moved'].values()), removed=result['removed'])}"
                       f"</p></div>")
            can_delete = True
        except retire.Refusal as error:
            verdict = f"<div class='error'><b>{t('retire.place.checkFailed')}</b><br>{h(error)}</div>"
    body.append(verdict)
    if typed_error:
        body.append(f"<div class='error'>{h(typed_error)}</div>")
    if can_delete:
        body.append(f"""<div class="card"><h3>{t('retire.confirm.title')}</h3><p class="muted">{t('retire.confirm.backup')}</p>
          <form method="post" action="/retire/place/{level}/{place_id}/delete"><input type="hidden" name="into" value="{into or ''}">
          <label class="form-field">{t('retire.confirm.type', name=place['name'])}
          <input name="typed" autocomplete="off" required></label>
          <button class="danger">{t('retire.confirm.button')}</button></form></div>""")
    body.append(back_link())
    return "".join(body), 200


@pages.route("/retire/place/<level>/<int:place_id>")
def place_review(level, place_id):
    blocked = refused()
    if blocked:
        return blocked
    if level not in retire.LEVELS:
        return page.render(f"<div class='error'>{t('retire.error.notFound')}</div>{back_link()}", 404)
    html, status = place_page(level, place_id, whole_number(request.args.get("into")))
    return page.render(html, status)


@pages.route("/retire/place/<level>/<int:place_id>/delete", methods=["POST"])
def place_delete(level, place_id):
    blocked = refused()
    if blocked:
        return blocked
    into = whole_number(request.form.get("into"))
    try:
        result = retire.run_place_delete(level, place_id, into, request.form.get("typed", ""))
    except PermissionError as error:
        return page.render(f"<div class='error'>{h(error)}</div>", 403)
    except retire.Refusal as error:
        return page.render(f"<div class='error'><b>{t('retire.error.nothing')}</b><br>{h(error)}</div>"
                           f"<p><a href='/retire/place/{h(level)}/{place_id}{'?into=' + str(into) if into else ''}'>{t('retire.back')}</a></p>", 409)
    flash(plain("retire.done", backup=result["backup"]))
    return redirect(f"/imports/{result['batch']}")


# ------------------------------------------------------------------------------------------ a question

def question_page(key, into=None, drop=False):
    """Returns (html, status) for the review of one question."""
    with database.connect() as conn:
        with database.cursor(conn) as cur:
            question = retire.question_row(cur, key)
            if not question:
                return f"<div class='error'>{t('retire.error.questionGone')}</div>{back_link()}", 404
            parts = retire.question_parts(cur, question)
            targets = retire.answer_targets(cur, question) if parts["answers"] else []
    head = (f"<div class='card'><h2>{t('retire.question.title', name=key)}</h2><p>{h(question['question_label'])}</p>"
            f"<p class='muted'>{t('retire.question.counts', answers=parts['answers'], options=parts['options'], rows=parts['grid_rows'], rules=parts['rules'])}</p>"
            f"<p class='muted'>{t('retire.question.partsNote')}</p></div>")
    if question["protected"]:
        return head + f"<div class='error'>{t('retire.question.locked')}</div>{back_link()}", 200
    if question["active"]:
        return head + f"<div class='error'>{t('retire.question.active')}</div>{back_link()}", 200
    body = [head]
    if parts["answers"]:
        choices = "".join(f"<option value='{h(k)}'{' selected' if k == into else ''}>{h(label)}</option>" for k, label in targets)
        body.append(f"""<div class="card"><h3>{t('retire.question.answersTitle')}</h3>
          <form method="get" action="/retire/question/{h(key)}"><label class="form-field">{t('retire.question.moveTo')}
          <select name="into"><option value="">{t('retire.question.pick')}</option>{choices}</select></label>
          <p class="muted">{t('retire.question.moveHelp')}</p>
          <label class="check"><input type="checkbox" name="drop" value="yes"{' checked' if drop else ''}> {t('retire.question.deleteThem')}</label>
          <button class="secondary">{t('retire.place.check')}</button></form></div>""")
    verdict, can_delete = "", False
    if not parts["answers"] or into or drop:
        try:
            result = retire.check_question_delete(key, into, drop)
            verdict = (f"<div class='card'><p class='good'>{t('retire.question.checkOk', moved=result['moved'], deleted=result['deleted_answers'], parts=result['parts'])}"
                       f"</p></div>")
            can_delete = True
        except retire.Refusal as error:
            verdict = f"<div class='error'><b>{t('retire.place.checkFailed')}</b><br>{h(error)}</div>"
    elif parts["answers"]:
        verdict = f"<div class='warn'>{t('retire.error.answersLeft')}</div>"
    body.append(verdict)
    if can_delete:
        body.append(f"""<div class="card"><h3>{t('retire.confirm.title')}</h3><p class="muted">{t('retire.confirm.backup')}</p>
          <form method="post" action="/retire/question/{h(key)}/delete"><input type="hidden" name="into" value="{h(into or '')}">
          <input type="hidden" name="drop" value="{'yes' if drop else ''}">
          <label class="form-field">{t('retire.confirm.type', name=key)}
          <input name="typed" autocomplete="off" required></label>
          <button class="danger">{t('retire.confirm.button')}</button></form></div>""")
    body.append(back_link())
    return "".join(body), 200


def valid_key(key):
    return bool(pq.KEY_PATTERN.fullmatch(key or ""))


@pages.route("/retire/question/<key>")
def question_review(key):
    blocked = refused()
    if blocked:
        return blocked
    if not valid_key(key):
        return page.render(f"<div class='error'>{t('retire.error.questionGone')}</div>{back_link()}", 404)
    into = request.args.get("into") or None
    html, status = question_page(key, into if valid_key(into) else None, request.args.get("drop") == "yes")
    return page.render(html, status)


@pages.route("/retire/question/<key>/delete", methods=["POST"])
def question_delete(key):
    blocked = refused()
    if blocked:
        return blocked
    if not valid_key(key):
        return page.render(f"<div class='error'>{t('retire.error.questionGone')}</div>{back_link()}", 404)
    into = request.form.get("into") or None
    try:
        result = retire.run_question_delete(key, into if valid_key(into) else None, request.form.get("drop") == "yes",
                                            request.form.get("typed", ""))
    except PermissionError as error:
        return page.render(f"<div class='error'>{h(error)}</div>", 403)
    except retire.Refusal as error:
        return page.render(f"<div class='error'><b>{t('retire.error.nothing')}</b><br>{h(error)}</div>"
                           f"<p><a href='/retire/question/{h(key)}'>{t('retire.back')}</a></p>", 409)
    flash(plain("retire.done", backup=result["backup"]))
    return redirect(f"/imports/{result['batch']}")
