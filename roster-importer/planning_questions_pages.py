"""The Planning questions pages: change the questions missionaries answer every week in Weekly Planning.

Pages (all under /planning-questions):
  (home)                         every section with its questions; add, rename, move or retire sections; add questions
  /sections/new, /sections/<id>  add a section; save, move, retire or restore one
  /questions/new                 add a question
  /questions/<id>                one question: wording, help, type, section, Required, number limits, the value saved
                                 while hidden, its answer choices and grid rows, and its show/hide rules
  /questions/<id>/choices        add, save, move, retire, restore or delete an answer choice or grid row
  /questions/<id>/rules          add, turn on or off, or delete a show/hide rule
  /preview                       the form as missionaries see it
  /history                       who changed what (the latest 300 changes)

Who: whoever may open DA Management may look. Changing needs your own portal sign-in (not the shared password), so
the change history can name a person. The rules themselves are in planning_questions.py.
"""
from html import escape

import psycopg2
from flask import Blueprint, flash, redirect, request
from psycopg2 import sql

import database
import page
import settings
import sign_in
from page import mission_time
from planning_questions import (BASE, CHOICE_TYPES, KEY_PATTERN, KEY_SECTION, KEY_SECTION_STAYS, LOCK_RULES,
                                LOCKED_NOTE, LOCKED_OPTIONAL, LOCKED_REQUIRED, OPERATORS, PARENT_TYPES, PEOPLE_CARDS,
                                TABLE_NAMES, TIMING, TYPES, VALUE_PATTERN, WHOLE_LIMITS, EXPLAIN, audit, changed_fields,
                                choice_code, finite_number, friendly, hidden_value, load_catalog, make_key, number_field,
                                on_form, plain, protected_reason, quoted, reorder, row_state, rule_text, saved_answers,
                                text_field, update_row, yes_no)

pages = Blueprint("planning_questions", __name__)


# ------------------------------------------------------------------------------------------ small helpers

def pq_page(body):
    """A Planning questions page (inside <div class="pq">), with "View only" for the shared password."""
    note = "" if sign_in.portal_person() else (
        "<div class='lock'><b>View only.</b> Changes need your own sign-in: open DA Management from the portal "
        "(signed in as President, AP or Data Analyst). The shared password can only look.</div>")
    return page.render(f"<div class='pq'>{note}{body}</div>")


def refuse_without_editor():
    """None when a person is signed in through the portal; else a redirect back, saying why nothing changed."""
    if sign_in.portal_person():
        return None
    flash("Nothing was changed: open DA Management from your signed-in portal account to change planning questions.")
    return redirect(request.referrer if (request.referrer or "").startswith(request.host_url) else BASE)


def nothing_changed(error, where):
    """After a refused change: the reason at the top of the page, then back to `where`."""
    flash(f"Nothing was changed: {friendly(error) if isinstance(error, psycopg2.Error) else error}")
    return redirect(where)


def back(anchor=""):
    """Back to the page the form came from (only pages of Planning questions)."""
    target = request.form.get("back") or BASE
    if not target.startswith(BASE):
        target = BASE
    return redirect(target + anchor)


def type_select(name, current, disabled=False):
    options = "".join(f"<option value='{value}' {'selected' if value == current else ''}>{esc(label)}</option>"
                      for value, label in TYPES.items())
    return f"<select name='{name}' {'disabled' if disabled else ''}>{options}</select>"


def esc(value):
    """Text made safe for HTML. Unlike page.h, only None shows as nothing (0 and False show as they are)."""
    return escape("" if value is None else str(value))


# ------------------------------------------------------------------------------------------ home

@pages.route(BASE)
def planning_questions_home():
    """Every section with its questions."""
    if not sign_in.allowed():
        return sign_in.go_to_login()
    with database.connect() as conn:
        with database.cursor(conn) as cur:
            sections, questions, rules = load_catalog(cur)
    labels = {q["question_key"]: q["question_label"] for q in questions}
    asked = on_form(sections, questions)
    rules_by_child = {}
    for rule in rules:
        if rule["active"]:
            rules_by_child.setdefault(rule["child_question_key"], []).append(rule)
    disabled = "" if sign_in.portal_person() else "disabled"
    cards = [section_card(index, section, sections, questions, rules_by_child, labels, asked, disabled)
             for index, section in enumerate(sections)]
    add_section = f"""<div class="card"><details><summary>+ Add a section</summary><form method="post" action="{BASE}/sections/new">
          <label class="form-field">Title<input name="section_title" maxlength="120" required {disabled}></label>
          <label class="form-field">Description (optional)<textarea name="description" maxlength="500" {disabled}></textarea></label>
          <button {disabled}>Add section</button></form></details></div>"""
    return pq_page(f"""<div class="card"><div class="step">Weekly Planning</div><h2>Planning questions</h2><p class="muted">{EXPLAIN}</p>
          <p class="muted">{TIMING} {PEOPLE_CARDS}</p>
          <p class="row"><a class="button" href="{BASE}/preview">Preview the form</a> <a class="button secondary" href="{BASE}/history">Change history</a></p>
          <p class="note">{LOCKED_NOTE}</p></div>
          {''.join(cards)}{add_section}""")


def section_card(index, section, sections, questions, rules_by_child, labels, asked, disabled):
    """One section on the home page: its title, tools, rename form, questions and "Add a question"."""
    items = [q for q in questions if q["section_id"] == section["id"]]
    rows = [question_item(q, section, rules_by_child, labels, asked, disabled, first=index == 0, last=index == len(items) - 1)
            for index, q in enumerate(items)]
    add_question = add_question_form(section, disabled) if section["active"] else ""
    locked = section["active"] and (section["section_key"] == KEY_SECTION or any(q["protected"] and q["active"] for q in items))
    retire_button = ("<span class='badge' title='It holds locked questions, so it stays on the form.'>Locked</span>" if locked else
                     f"""<button class="secondary" name="action" value="{'retire' if section['active'] else 'restore'}" {disabled}>{'Retire section' if section['active'] else 'Restore section'}</button>""")
    section_tools = f"""<form method="post" action="{BASE}/sections/{section['id']}" class="inline"><input type="hidden" name="state" value="{esc(row_state(section))}">
              <button class="secondary" name="action" value="up" aria-label="Move section up" {disabled} {'hidden' if index == 0 else ''}>↑</button><button class="secondary" name="action" value="down" aria-label="Move section down" {disabled} {'hidden' if index == len(sections) - 1 else ''}>↓</button>
              {retire_button}</form>"""
    return f"""<div class="card {'retired' if not section['active'] else ''}" id="section-{esc(section['section_key'])}">
              <div class="row"><div class="grow"><div class="step">Section {index + 1}{'' if section['active'] else ' · retired'}</div><h3>{esc(section['section_title'])}</h3><p class="muted">{esc(section['description'])}</p></div><div class="tools">{section_tools}</div></div>
              <details><summary>Rename or describe this section</summary><form method="post" action="{BASE}/sections/{section['id']}"><input type="hidden" name="state" value="{esc(row_state(section))}">
                <label class="form-field">Title<input name="section_title" value="{esc(section['section_title'])}" maxlength="120" required {disabled}></label>
                <label class="form-field">Description<textarea name="description" maxlength="500" {disabled}>{esc(section['description'])}</textarea></label>
                <p class="note">Key: <code>{esc(section['section_key'])}</code> (never changes)</p><button name="action" value="save" {disabled}>Save section</button></form></details>
              <div>{''.join(rows) or "<p class='muted'>No questions yet.</p>"}</div>{add_question}</div>"""


def question_item(q, section, rules_by_child, labels, asked, disabled, first=False, last=False):
    """One question line on the home page: its label (which opens the question), badges, key, when it is shown, and
    the move buttons (no ↑ on the first question of the section and no ↓ on the last, as for sections)."""
    badges = [TYPES.get(q["question_type"], q["question_type"])]
    badges.append("required" if q["required"] else "optional")
    if q["answered"]:
        badges.append(saved_answers(q['answered']))
    shown = " and ".join(rule_text(r, labels, asked) for r in rules_by_child.get(q["question_key"], []))
    return f"""<div class="item {'retired' if not q['active'] else ''}"><div class="what"><a href="{BASE}/questions/{q['id']}"><b>{esc(q['question_label'])}</b></a>
                  {"<span class='badge'>Locked</span>" if q['protected'] else ""}{"" if q['active'] else " <span class='badge'>Retired</span>"}
                  <div class="note"><code>{esc(q['question_key'])}</code> · {esc(' · '.join(badges))}{f' · shown only when {esc(shown)}' if shown else ''}</div></div>
                  <div class="tools"><form method="post" action="{BASE}/questions/{q['id']}" class="inline"><input type="hidden" name="back" value="{BASE}#section-{esc(section['section_key'])}"><button class="secondary" name="action" value="up" aria-label="Move up" {disabled} {'hidden' if first else ''}>↑</button><button class="secondary" name="action" value="down" aria-label="Move down" {disabled} {'hidden' if last else ''}>↓</button></form></div></div>"""


def add_question_form(section, disabled):
    """The form "+ Add a question to this section"."""
    return f"""<details><summary>+ Add a question to this section</summary>
              <form method="post" action="{BASE}/questions/new"><input type="hidden" name="section_id" value="{section['id']}">
              <label class="form-field">Question (what missionaries read)<input name="question_label" maxlength="300" required {disabled}></label>
              <div class="two"><label class="form-field">Type{type_select('question_type', 'NUMBER', bool(disabled))}</label>
              <label class="form-field">Key (optional; made from the question if empty)<input name="question_key" maxlength="63" pattern="[a-z][a-z0-9_]{{2,62}}" placeholder="for example service_projects_goal" {disabled}></label></div>
              <label class="check"><input type="checkbox" name="required" value="yes" {disabled}> Required</label>
              <p class="note">The key never changes after this and is how reports find the answers. Keys ending in <code>_goal</code> or <code>_plan</code> appear in Call-ins automatically (as a goal or an action plan).</p>
              <button {disabled}>Add question</button></form></details>"""


# ------------------------------------------------------------------------------------------ sections

@pages.route(f"{BASE}/sections/new", methods=["POST"])
def planning_section_new():
    """Adds a section at the end."""
    if not sign_in.allowed():
        return sign_in.go_to_login()
    if (refused := refuse_without_editor()):
        return refused
    who = sign_in.portal_person()
    try:
        title = text_field("section_title", "Title", 120, required=True)
        description = text_field("description", "Description", 500)
        with database.connect() as conn:
            with database.cursor(conn) as cur:
                cur.execute("lock table public.planning_question_sections in share row exclusive mode")
                cur.execute("select section_key,display_order from public.planning_question_sections")
                existing = cur.fetchall()
                key = make_key(title, {row["section_key"] for row in existing}, prefix="section")
                order = max([row["display_order"] for row in existing] or [0]) + 10
                cur.execute("""insert into public.planning_question_sections(section_key,section_title,description,display_order)
                  values(%s,%s,%s,%s) returning to_jsonb(planning_question_sections.*) as row""", (key, title, description, order))
                audit(cur, who, "planning_question_sections", {"section_key": key}, None, cur.fetchone()["row"], "Section added")
        flash(f"Section “{title}” added. Add its questions below.")
        return redirect(f"{BASE}#section-{key}")
    except (ValueError, psycopg2.Error) as error:
        return nothing_changed(error, BASE)


@pages.route(f"{BASE}/sections/<int:section_id>", methods=["POST"])
def planning_section_change(section_id):
    """Saves, moves, retires or restores a section."""
    if not sign_in.allowed():
        return sign_in.go_to_login()
    if (refused := refuse_without_editor()):
        return refused
    who, action = sign_in.portal_person(), request.form.get("action", "save")
    try:
        with database.connect() as conn:
            with database.cursor(conn) as cur:
                cur.execute("select * from public.planning_question_sections where id=%s for update", (section_id,))
                section = cur.fetchone()
                if not section:
                    raise ValueError("This section no longer exists. Reload the page.")
                message = change_section(cur, who, section, action)
        if message:
            flash(message)
        return redirect(f"{BASE}#section-{section['section_key']}")
    except (ValueError, psycopg2.Error) as error:
        return nothing_changed(error, BASE)


def change_section(cur, who, section, action):
    """Moves, saves, retires or restores a section. Returns the message to show (None for a move)."""
    key = {"section_key": section["section_key"]}
    if action in {"up", "down"}:
        reorder(cur, who, "planning_question_sections", None, None, section["id"], action,
                lambda row: {"section_key": row["section_key"]})
        return None
    if request.form.get("state") != row_state(section):
        raise ValueError("Someone changed this section since you opened the page. Reload the page and try again.")
    if action == "save":
        update_row(cur, who, "planning_question_sections", section["id"], {
            "section_title": text_field("section_title", "Title", 120, required=True),
            "description": text_field("description", "Description", 500)}, key)
        return "Section saved."
    if action not in {"retire", "restore"}:
        raise ValueError("Unknown action.")
    if action == "retire" and section["section_key"] == KEY_SECTION:
        raise ValueError(KEY_SECTION_STAYS.format(title=section["section_title"]))
    update_row(cur, who, "planning_question_sections", section["id"], {"active": action == "restore"}, key,
               "Section retired" if action == "retire" else "Section restored")
    return section_retire_message(cur, section["id"], action)


def section_retire_message(cur, section_id, action):
    """What retiring or restoring a section means, also for questions in other sections whose show/hide rule looks at
    a question in it: while it is retired, Weekly Planning ignores that rule."""
    cur.execute("""select c.question_label from public.planning_question_visibility_rules v
      join public.planning_questions p on p.question_key=v.parent_question_key and p.section_id=%s and p.active
      join public.planning_questions c on c.question_key=v.child_question_key and c.active and c.section_id<>%s
      where v.active order by c.display_order,c.id""", (section_id, section_id))
    dependents = list(dict.fromkeys(row["question_label"] for row in cur.fetchall()))
    # Whole messages (one for each case), so the portal catalog can translate them.
    names = quoted(dependents) if dependents else ""
    if dependents and action == "retire" and len(dependents) == 1:
        return (f"Section retired: its questions no longer appear on the form. Saved answers stay. {names} "
                "in another section depends on its questions: while it is retired, Weekly Planning "
                "ignores those show/hide rules. Restoring the section brings them back.")
    if dependents and action == "retire":
        return (f"Section retired: its questions no longer appear on the form. Saved answers stay. {names} "
                "in other sections depend on its questions: while it is retired, Weekly Planning "
                "ignores those show/hide rules. Restoring the section brings them back.")
    if dependents:
        return (f"Section restored: its active questions appear on the form again. "
                f"The show/hide rules of {names} apply again.")
    return ("Section retired: its questions no longer appear on the form. Saved answers stay."
            if action == "retire" else "Section restored: its active questions appear on the form again.")


# ------------------------------------------------------------------------------------------ adding a question

@pages.route(f"{BASE}/questions/new", methods=["POST"])
def planning_question_new():
    """Adds a question at the end of its section."""
    if not sign_in.allowed():
        return sign_in.go_to_login()
    if (refused := refuse_without_editor()):
        return refused
    who = sign_in.portal_person()
    try:
        label = text_field("question_label", "The question", 300, required=True)
        kind = request.form.get("question_type", "")
        if kind not in TYPES:
            raise ValueError("Choose one of the listed types.")
        wanted = request.form.get("question_key", "").strip()
        if wanted and not KEY_PATTERN.match(wanted):
            raise ValueError("A key starts with a small letter and uses only small letters, digits and _ (3 to 63 characters), for example service_hours_goal.")
        with database.connect() as conn:
            with database.cursor(conn) as cur:
                cur.execute("select * from public.planning_question_sections where id=%s and active for share", (int(request.form.get("section_id") or 0),))
                section = cur.fetchone()
                if not section:
                    raise ValueError("Choose an active section.")
                cur.execute("lock table public.planning_questions in share row exclusive mode")
                cur.execute("select question_key from public.planning_questions")
                taken = {row["question_key"] for row in cur.fetchall()}
                if wanted and wanted in taken:
                    raise ValueError(f"The key {wanted} is already used by another question (keys are never reused).")
                key = wanted or make_key(label, taken)
                cur.execute("select coalesce(max(display_order),0)+10 as next from public.planning_questions where section_id=%s", (section["id"],))
                order = cur.fetchone()["next"]
                cur.execute("""insert into public.planning_questions(section_id,question_key,question_label,question_type,required,display_order)
                  values(%s,%s,%s,%s,%s,%s) returning id,to_jsonb(planning_questions.*) as row""",
                            (section["id"], key, label, kind, request.form.get("required") == "yes", order))
                created = cur.fetchone()
                audit(cur, who, "planning_questions", {"question_key": key}, None, created["row"], "Question added")
        flash(f"Question added with the key {key}." + (" Keys ending in _goal or _plan appear in Call-ins automatically." if key.endswith(("_goal", "_plan")) else "")
              + (" Add its answer choices below." if kind in CHOICE_TYPES else ""))
        return redirect(f"{BASE}/questions/{created['id']}")
    except (ValueError, psycopg2.Error) as error:
        return nothing_changed(error, BASE)


# ------------------------------------------------------------------------------------------ one question: the page

@pages.route(f"{BASE}/questions/<int:question_id>")
def planning_question_edit(question_id):
    """The page of one question."""
    if not sign_in.allowed():
        return sign_in.go_to_login()
    with database.connect() as conn:
        with database.cursor(conn) as cur:
            sections, questions, rules = load_catalog(cur)
            q = next((item for item in questions if item["id"] == question_id), None)
            if not q:
                return page.render("<div class='error'>This question does not exist.</div><p><a href='/planning-questions'>Back to the planning questions</a></p>", 404)
            cur.execute("""select o.*,public.planning_option_used(%s,o.option_value) used from public.planning_question_options o
              where o.question_id=%s order by o.display_order,o.id""", (q["question_key"], question_id))
            options = cur.fetchall()
            cur.execute("""select r.*,exists(select 1 from public.weekly_planning_answers a where a.question_key=%s
              and jsonb_typeof(a.answer_json)='object' and a.answer_json ? r.row_key) used
              from public.planning_question_grid_rows r where r.question_id=%s order by r.display_order,r.id""", (q["question_key"], question_id))
            grid_rows = cur.fetchall()
    disabled = "" if sign_in.portal_person() else "disabled"
    labels = {item["question_key"]: item["question_label"] for item in questions}
    section = next((s for s in sections if s["id"] == q["section_id"]), {})
    kind = q["question_type"]
    lock = (f"<div class='lock'><b>Locked.</b> {esc(protected_reason(q['question_key']))} {LOCK_RULES}</div>" if q["protected"] else "")
    named = named_choices(q, rules, labels)
    choices = item_list(q, "option", options, "option_value", "option_label", named, disabled) if kind in CHOICE_TYPES else ""
    rows_card = item_list(q, "row", grid_rows, "row_key", "row_label", named, disabled) if kind == "GRID" else ""
    return pq_page(f"""<p><a href="{BASE}#section-{esc(section.get('section_key'))}">← All planning questions</a></p>
          <div class="card"><div class="step">{esc(section.get('section_title'))}{'' if q['active'] else ' · retired'}</div><h2>{esc(q['question_label'])}</h2>
          <p class="note">Key <code>{esc(q['question_key'])}</code> (never changes) · {esc(TYPES.get(kind, kind))} · {saved_answers(q['answered'])}</p>{lock}{details_form(q, sections, disabled)}<p class="row">{retire_form(q, disabled)}</p></div>
          {choices}{rows_card}{rules_card(q, sections, questions, rules, labels, disabled)}""")


def details_form(q, sections, disabled):
    """The question's main form: wording, help, type, section, Required, number limits, hint, value while hidden."""
    here = f"{BASE}/questions/{q['id']}"
    kind = q["question_type"]
    type_note = ("Locked questions keep their type." if q["protected"] else
                 f"Saved plans already answered it, so its type stays. To ask it differently, add a new question and retire this one." if q["answered"] else
                 "The type can change until a plan answers this question.")
    type_locked = q["protected"] or q["answered"] > 0
    section_select = "".join(f"<option value='{s['id']}' {'selected' if s['id'] == q['section_id'] else ''}>{esc(s['section_title'])}{'' if s['active'] else ' (retired)'}</option>" for s in sections)
    number_fields = f"""<div class="two"><label class="form-field">Lowest allowed (empty: 0)<input name="min_value" inputmode="decimal" value="{esc(plain(q['min_value']))}" {disabled}></label>
          <label class="form-field">Highest allowed (empty: no limit)<input name="max_value" inputmode="decimal" value="{esc(plain(q['max_value']))}" {disabled}></label></div>
          <label class="check"><input type="checkbox" name="integer_only" value="yes" {'checked' if q['integer_only'] else ''} {disabled}> Whole numbers only</label>""" if kind == "NUMBER" else ""
    return f"""<form method="post" action="{here}"><input type="hidden" name="state" value="{esc(row_state(q))}">
          <label class="form-field">Question (what missionaries read)<input name="question_label" value="{esc(q['question_label'])}" maxlength="300" required {disabled}></label>
          <label class="form-field">Help text (shown under the question)<textarea name="help_text" maxlength="1000" {disabled}>{esc(q['help_text'])}</textarea></label>
          <div class="two"><label class="form-field">Type{type_select('question_type', kind, type_locked or bool(disabled))}<span class="note">{type_note}</span></label>
          <label class="form-field">Section<select name="section_id" {disabled}>{section_select}</select></label></div>
          {"<input type='hidden' name='question_type' value='" + esc(kind) + "'>" if type_locked else ""}
          {required_box(q, disabled)}{number_fields}
          <div class="two"><label class="form-field">Hint inside the empty box (optional)<input name="placeholder" value="{esc(q['placeholder'])}" maxlength="200" {disabled}></label>
          {hidden_field(q, disabled)}</div>
          <button name="action" value="save" {disabled}>Save question</button></form>"""


def required_box(q, disabled):
    """The Required tick box (fixed for a locked question)."""
    if q["protected"]:
        # Both ways fixed here: a locked question that became required could never be made optional again.
        return (f"<label class='check'><input type='checkbox' {'checked' if q['required'] else ''} disabled> Required</label>"
                + ("<input type='hidden' name='required' value='yes'>" if q["required"] else "")
                + f"<p class='note'>{LOCKED_REQUIRED if q['required'] else LOCKED_OPTIONAL}</p>")
    return f"<label class='check'><input type='checkbox' name='required' value='yes' {'checked' if q['required'] else ''} {disabled}> Required</label>"


def hidden_field(q, disabled):
    """The "Value saved while hidden" box. None for a locked question: it is never hidden (its Locked box says so)."""
    if q["protected"]:
        return ""
    return f"""<label class="form-field">Value saved while hidden (optional)<input name="value_when_hidden" value="{esc(q['value_when_hidden'])}" maxlength="200" {disabled}><span class="note">Only used when a show/hide rule below hides this question and the question it depends on is answered, e.g. 0 for a count. It must be an answer this question accepts{' (one of its choices)' if q['question_type'] in {'SELECT', 'RADIO'} else ''}. Otherwise a hidden question keeps its answer.</span></label>"""


def retire_form(q, disabled):
    """The Retire (or Restore) button of a question."""
    here = f"{BASE}/questions/{q['id']}"
    button = ('' if q['protected'] and q['active'] else
              f"""<button class="secondary" name="action" value="{'retire' if q['active'] else 'restore'}" {disabled}>{'Retire question' if q['active'] else 'Restore question'}</button>""")
    return f"""<form method="post" action="{here}" class="inline"><input type="hidden" name="state" value="{esc(row_state(q))}">
          {button}</form>
          <span class="note">{'Locked questions cannot be retired.' if q['protected'] and q['active'] else 'Retired questions disappear from the form; saved answers stay.' if q['active'] else 'This question is retired: it is not on the form.'}</span>"""


def named_choices(q, rules, labels):
    """{choice code: the questions whose active show/hide rule looks for it}."""
    named = {}
    for r in rules:
        if r["parent_question_key"] == q["question_key"] and r["active"]:
            named.setdefault(str(r["comparison_value"]), []).append(labels.get(r["child_question_key"], r["child_question_key"]))
    return named


def item_list(q, kind, items, value_name, label_name, named, disabled):
    """The card of the answer choices (kind "option") or grid rows (kind "row"), each with its buttons, and the
    form to add one."""
    is_row = kind == "row"
    here = f"{BASE}/questions/{q['id']}"
    rows_html = [choice_item(q, kind, index, item, items, value_name, label_name, [] if is_row else named.get(item[value_name], []), disabled)
                 for index, item in enumerate(items)]
    add = (f"<p class='note'>Locked question: no {'row' if is_row else 'choice'} can be added, because reports read exactly these.</p>" if q["protected"] else f"""<form method="post" action="{here}/choices"><input type="hidden" name="kind" value="{kind}"><input type="hidden" name="action" value="add">
              <div class="row"><label class="grow">New {'row' if is_row else 'choice'}<input name="label" maxlength="200" required {disabled}></label>
              <label class="grow">Code (optional)<input name="value" maxlength="63" placeholder="made from the label" {disabled}></label></div>
              <p><button {disabled}>Add {'row' if is_row else 'choice'}</button></p></form>""")
    title = "Grid rows" if is_row else ("Choices in each row" if q["question_type"] == "GRID" else "Answer choices")
    explain = ("Each row is one line of the grid; missionaries pick one choice per row." if is_row else
               "The code is what is saved and what reports read; the label is what missionaries see.")
    return f"<div class='card'><h3>{title}</h3><p class='note'>{explain}</p>{''.join(rows_html) or '<p class=muted>None yet.</p>'}{add}</div>"


def choice_item(q, kind, index, item, items, value_name, label_name, in_rule, disabled):
    """One answer choice or grid row with its label, code and buttons. Its code is fixed once plans used it, on a
    locked question, or while a show/hide rule looks for it."""
    here = f"{BASE}/questions/{q['id']}"
    fixed = q["protected"] or item["used"] or bool(in_rule)
    why = ("Locked question: code fixed." if q["protected"] else "Used in saved plans: code fixed." if item["used"] else "Not used yet.")
    if in_rule:
        why += f" The show/hide rule of {quoted(in_rule)} looks for it, so it stays until that rule changes."
    retire = ('' if (q['protected'] or in_rule) and item['active'] else
              f"""<button class="secondary" name="action" value="{'retire' if item['active'] else 'restore'}" {disabled}>{'Retire' if item['active'] else 'Restore'}</button>""")
    delete = '' if fixed else f'<button class="danger" name="action" value="delete" {disabled}>Delete</button>'
    return f"""<div class="item {'retired' if not item['active'] else ''}"><form method="post" action="{here}/choices" class="what">
                  <input type="hidden" name="kind" value="{kind}"><input type="hidden" name="item_id" value="{item['id']}"><input type="hidden" name="state" value="{esc(row_state(item))}">
                  <div class="row"><label class="grow">Label<input name="label" value="{esc(item[label_name])}" maxlength="200" required {disabled}></label>
                  <label class="grow">Code<input name="value" value="{esc(item[value_name])}" maxlength="63" {'disabled' if fixed or disabled else ''}></label></div>
                  <div class="note">{why}{'' if item['active'] else ' Retired.'}</div>
                  <div class="tools"><button name="action" value="save" {disabled}>Save</button>
                  <button class="secondary" name="action" value="up" aria-label="Move up" {disabled} {'hidden' if index == 0 else ''}>↑</button><button class="secondary" name="action" value="down" aria-label="Move down" {disabled} {'hidden' if index == len(items) - 1 else ''}>↓</button>
                  {retire}
                  {delete}</div></form></div>"""


def rules_card(q, sections, questions, rules, labels, disabled):
    """ "Show this question only when …": its rules, the form to add one, and the questions that depend on it."""
    here = f"{BASE}/questions/{q['id']}"
    asked = on_form(sections, questions)
    own_rules = [r for r in rules if r["child_question_key"] == q["question_key"]]
    dependents = [r for r in rules if r["parent_question_key"] == q["question_key"] and r["active"]]
    rule_items = "".join(rule_item(q, r, labels, asked, disabled) for r in own_rules)
    parents = "".join(f"<option value='{esc(p['question_key'])}'>{esc(p['question_label'])} ({esc(TYPES[p['question_type']])})</option>"
                      for p in questions if p["question_key"] in asked and p["question_type"] in PARENT_TYPES and p["id"] != q["id"])
    operators = "".join(f"<option value='{value}'>{esc(label)}</option>" for value, label in OPERATORS.items())
    add = ("<p class='note'>Locked question: its show/hide rules are fixed, so a rule can never hide it.</p>" if q['protected'] else f"""<form method="post" action="{here}/rules"><input type="hidden" name="action" value="add">
          <div class="row"><label class="grow">Question<select name="parent" required {disabled}><option value="">Choose…</option>{parents}</select></label>
          <label class="grow">Condition<select name="operator" {disabled}>{operators}</select></label>
          <label class="grow">Answer<input name="value" maxlength="200" required placeholder="a number, Yes or No, or a choice" {disabled}></label></div>
          <p class="note">Numbers can use every condition; Yes/No questions and choices use “is” or “is not” (type Yes or No, or the choice's label or code).</p>
          <p><button {disabled}>Add rule</button></p></form>""")
    depends = (('<p class="note">These questions depend on this one: ' + esc(', '.join(labels.get(r['child_question_key'], r['child_question_key']) for r in dependents)) + '.'
                + ('' if q['question_key'] in asked else ' While this question is not on the form, Weekly Planning ignores those rules.') + '</p>') if dependents else '')
    return f"""<div class="card"><h3>Show this question only when …</h3><p class="note">Without a rule the question is always shown. With rules, it is shown only when all of them are met. A hidden question is not required.</p>
          {rule_items or "<p class='muted'>No rule: always shown.</p>"}
          {add}
          {depends}</div>"""


def rule_item(q, r, labels, asked, disabled):
    """One show/hide rule with its Turn off/on and Delete buttons."""
    here = f"{BASE}/questions/{q['id']}"
    tools = ('' if q['protected'] else f"""<form method="post" action="{here}/rules" class="tools"><input type="hidden" name="rule_id" value="{r['id']}">
          <button class="secondary" name="action" value="{'off' if r['active'] else 'on'}" {disabled}>{'Turn off' if r['active'] else 'Turn on'}</button>
          <button class="danger" name="action" value="delete" {disabled}>Delete</button></form>""")
    return f"""<div class="item {'retired' if not r['active'] else ''}"><div class="what">Shown only when {esc(rule_text(r, labels, asked if r['active'] else None))}{'' if r['active'] else ' <span>(turned off)</span>'}</div>
          {tools}</div>"""


# ------------------------------------------------------------------------------------------ one question: saving

@pages.route(f"{BASE}/questions/<int:question_id>", methods=["POST"])
def planning_question_change(question_id):
    """Saves, moves, retires or restores a question."""
    if not sign_in.allowed():
        return sign_in.go_to_login()
    if (refused := refuse_without_editor()):
        return refused
    who, action = sign_in.portal_person(), request.form.get("action", "save")
    here = f"{BASE}/questions/{question_id}"
    try:
        with database.connect() as conn:
            with database.cursor(conn) as cur:
                cur.execute("select * from public.planning_questions where id=%s for update", (question_id,))
                q = cur.fetchone()
                if not q:
                    raise ValueError("This question no longer exists. Reload the page.")
                message = change_question(cur, who, q, action)
        if message:
            flash(message)
        return back() if action in {"up", "down"} else redirect(here)
    except (ValueError, psycopg2.Error) as error:
        return nothing_changed(error, here if action not in {"up", "down"} else BASE)


def change_question(cur, who, q, action):
    """Moves, retires, restores or saves a question. Returns the message to show (None for a move)."""
    key = {"question_key": q["question_key"]}
    if action in {"up", "down"}:
        reorder(cur, who, "planning_questions", "section_id", q["section_id"], q["id"], action,
                lambda row: {"question_key": row["question_key"]})
        return None
    if request.form.get("state") != row_state(q):
        raise ValueError("Someone changed this question since you opened the page. Reload the page and try again.")
    if action in {"retire", "restore"}:
        update_row(cur, who, "planning_questions", q["id"], {"active": action == "restore"}, key,
                   "Question retired" if action == "retire" else "Question restored")
        return question_retire_message(cur, q, action)
    if action == "save":
        update_row(cur, who, "planning_questions", q["id"], question_changes(cur, q), key)
        return "Question saved. Plans that are still drafts show it at once."
    raise ValueError("Unknown action.")


def question_retire_message(cur, q, action):
    """What retiring or restoring a question means. The rules that look at it stay as they are: while it is not on
    the form, Weekly Planning ignores them (see on_form), and they apply again once it is back."""
    cur.execute("""select c.question_label from public.planning_question_visibility_rules v
      join public.planning_questions c on c.question_key=v.child_question_key and c.active
      where v.parent_question_key=%s and v.active order by c.display_order,c.id""", (q["question_key"],))
    dependents = [row["question_label"] for row in cur.fetchall()]
    cur.execute("select active from public.planning_question_sections where id=%s", (q["section_id"],))
    section_active = bool((cur.fetchone() or {}).get("active"))
    if action == "retire":
        message = "Question retired: it is no longer on the form. Saved answers stay."
        # Whole sentences (one for each number), so the portal catalog can translate them.
        if len(dependents) == 1:
            message += (f" {quoted(dependents)} depends on it: while it is retired, "
                        "Weekly Planning ignores that show/hide rule. Restoring this question brings the rule back.")
        elif dependents:
            message += (f" {quoted(dependents)} depend on it: while it is retired, "
                        "Weekly Planning ignores that show/hide rule. Restoring this question brings the rule back.")
        return message
    if not section_active:
        return "Question restored. Its section is retired, so it is on the form once the section is restored."
    message = "Question restored: it is on the form again."
    if dependents:
        message += f" The show/hide rule of {quoted(dependents)} applies again."
    return message


def question_changes(cur, q):
    """The saved form of a question as {column: new value}, checked. Raises ValueError with what is wrong."""
    kind = request.form.get("question_type", q["question_type"])
    if kind not in TYPES:
        raise ValueError("Choose one of the listed types.")
    changes = {
        "question_label": text_field("question_label", "The question", 300, required=True),
        "help_text": text_field("help_text", "Help text", 1000),
        "question_type": kind,
        "required": request.form.get("required") == "yes",
        "placeholder": text_field("placeholder", "The hint", 200),
    }
    if q["protected"] and changes["required"] != q["required"]:
        raise ValueError(f"“{q['question_label']}” is locked, so it stays required." if q["required"] else
                         f"“{q['question_label']}” is locked, so it stays optional: once required, a locked question "
                         "could not be made optional again, and every draft plan that leaves it empty could not be submitted.")
    section_id = int(request.form.get("section_id") or q["section_id"])
    if section_id != q["section_id"]:
        cur.execute("select id from public.planning_question_sections where id=%s", (section_id,))
        if not cur.fetchone():
            raise ValueError("Choose one of the listed sections.")
        cur.execute("select coalesce(max(display_order),0)+10 as next from public.planning_questions where section_id=%s", (section_id,))
        changes.update(section_id=section_id, display_order=cur.fetchone()["next"])
    low, high, whole = q["min_value"], q["max_value"], q["integer_only"]
    if kind == "NUMBER" and q["question_type"] == "NUMBER":
        # The limit boxes are on the form only while the question is a number question; a question that becomes one
        # keeps its settings (whole numbers only, by default).
        low, high, whole = number_limits()
        changes.update(min_value=low, max_value=high, integer_only=whole)
    hidden = text_field("value_when_hidden", "The value saved while hidden", 200)
    if q["protected"]:
        if hidden is not None and hidden != q["value_when_hidden"]:
            raise ValueError("Locked questions are never hidden, so nothing is saved for them while hidden.")
    else:
        cur.execute("""select option_value,option_label from public.planning_question_options
          where question_id=%s and active order by display_order,id""", (q["id"],))
        choices = [(o["option_value"], o["option_label"]) for o in cur.fetchall()]
        changes["value_when_hidden"] = hidden_value(kind, hidden, low, high, whole, choices)
    return changes


def number_limits():
    """(lowest, highest, whole numbers only) from the number question's form, checked."""
    low, high = number_field("min_value", "The lowest number"), number_field("max_value", "The highest number")
    whole = request.form.get("integer_only") == "yes"
    if low is not None and high is not None and low > high:
        raise ValueError("The lowest number must not be above the highest.")
    if whole and any(limit is not None and limit != limit.to_integral_value() for limit in (low, high)):
        raise ValueError(WHOLE_LIMITS)
    return low, high, whole


# ------------------------------------------------------------------------------------------ answer choices and grid rows

@pages.route(f"{BASE}/questions/<int:question_id>/choices", methods=["POST"])
def planning_question_choices(question_id):
    """Adds or changes an answer choice or grid row."""
    if not sign_in.allowed():
        return sign_in.go_to_login()
    if (refused := refuse_without_editor()):
        return refused
    who, action = sign_in.portal_person(), request.form.get("action", "")
    here = f"{BASE}/questions/{question_id}"
    is_row = request.form.get("kind") == "row"
    noun = "row" if is_row else "choice"
    try:
        with database.connect() as conn:
            with database.cursor(conn) as cur:
                cur.execute("select * from public.planning_questions where id=%s for update", (question_id,))
                q = cur.fetchone()
                if not q or q["question_type"] not in (({"GRID"}) if is_row else CHOICE_TYPES):
                    raise ValueError(f"This question has no {noun}s. Reload the page.")
                if action == "add":
                    message = add_item(cur, who, q, is_row)
                else:
                    message = change_item(cur, who, q, is_row, action)
        if message:
            flash(message)
        return redirect(here)
    except (ValueError, psycopg2.Error) as error:
        return nothing_changed(error, here)


def item_table(is_row):
    """(table, code column, label column, noun) of answer choices or grid rows."""
    if is_row:
        return "planning_question_grid_rows", "row_key", "row_label", "row"
    return "planning_question_options", "option_value", "option_label", "choice"


def add_item(cur, who, q, is_row):
    """Adds an answer choice or grid row. Returns the message."""
    table, value_name, label_name, noun = item_table(is_row)
    if q["protected"]:
        raise ValueError(f"“{q['question_label']}” is locked: no {noun} can be added, because reports read exactly these.")
    label = text_field("label", "The label", 200, required=True)
    cur.execute(sql.SQL("select {} as value,display_order from public.{} where question_id=%s").format(
        sql.Identifier(value_name), sql.Identifier(table)), (q["id"],))
    existing = cur.fetchall()
    wanted = request.form.get("value", "").strip().lower()
    if wanted and not VALUE_PATTERN.match(wanted):
        raise ValueError("A code uses only small letters, digits and _ (up to 63 characters), for example dont_have_one.")
    taken = {row["value"] for row in existing}
    if wanted in taken:
        raise ValueError(f"This question already has a {noun} with the code {wanted}.")
    value = wanted or make_key(label, taken, pattern=VALUE_PATTERN, prefix=noun)
    order = max([row["display_order"] for row in existing] or [0]) + 10
    cur.execute(sql.SQL("insert into public.{} (question_id,{},{},display_order) values(%s,%s,%s,%s) returning to_jsonb({}.*) as row").format(
        sql.Identifier(table), sql.Identifier(value_name), sql.Identifier(label_name), sql.Identifier(table)),
        (q["id"], value, label, order))
    audit(cur, who, table, {"question_key": q["question_key"], value_name: value}, None, cur.fetchone()["row"], f"{noun.title()} added")
    return f"{noun.title()} “{label}” added (code {value})."


def change_item(cur, who, q, is_row, action):
    """Moves, saves, retires, restores or deletes an answer choice or grid row. Returns the message (None for a
    move)."""
    table, value_name, label_name, noun = item_table(is_row)
    cur.execute(sql.SQL("select * from public.{} where id=%s and question_id=%s for update").format(sql.Identifier(table)),
                (int(request.form.get("item_id") or 0), q["id"]))
    item = cur.fetchone()
    if not item:
        raise ValueError(f"This {noun} no longer exists. Reload the page.")
    removes = action in {"retire", "delete"} or (
        action == "save" and request.form.get("value", item[value_name]).strip().lower() != item[value_name])
    if not is_row and removes:
        refuse_removing_needed_choice(cur, q, item, value_name, label_name)
    key = {"question_key": q["question_key"], value_name: item[value_name]}
    if action in {"up", "down"}:
        reorder(cur, who, table, "question_id", q["id"], item["id"], action,
                lambda row: {"question_key": q["question_key"], value_name: row[value_name]})
        return None
    if request.form.get("state") != row_state(item):
        raise ValueError(f"Someone changed this {noun} since you opened the page. Reload the page and try again.")
    if action == "save":
        changes = {label_name: text_field("label", "The label", 200, required=True)}
        wanted = request.form.get("value", item[value_name]).strip().lower()
        if "value" in request.form and wanted != item[value_name]:
            if not VALUE_PATTERN.match(wanted):
                raise ValueError("A code uses only small letters, digits and _ (up to 63 characters).")
            changes[value_name] = wanted
        update_row(cur, who, table, item["id"], changes, key)
        return f"{noun.title()} saved."
    if action in {"retire", "restore"}:
        update_row(cur, who, table, item["id"], {"active": action == "restore"}, key,
                   f"{noun.title()} {'retired' if action == 'retire' else 'restored'}")
        # Whole sentences, so the portal catalog can translate each one.
        return (f"{noun.title()} retired: no longer offered. Saved answers stay." if action == "retire"
                else f"{noun.title()} restored.")
    if action == "delete":
        cur.execute(sql.SQL("delete from public.{} t where id=%s returning to_jsonb(t) as row").format(sql.Identifier(table)), (item["id"],))
        audit(cur, who, table, key, cur.fetchone()["row"], None, f"{noun.title()} deleted")
        return f"{noun.title()} deleted."
    raise ValueError("Unknown action.")


def refuse_removing_needed_choice(cur, q, item, value_name, label_name):
    """An answer choice may not go (retired, deleted or its code changed) while it is the value saved while hidden, or
    while a show/hide rule looks for it: without it, that question could never be shown."""
    if q["value_when_hidden"] == item[value_name]:
        raise ValueError(f"“{item[label_name]}” is the value saved while “{q['question_label']}” is hidden. Change that first (above), then try again.")
    cur.execute("""select c.question_label from public.planning_question_visibility_rules v
      join public.planning_questions c on c.question_key=v.child_question_key
      where v.parent_question_key=%s and v.comparison_value=%s and v.active order by c.display_order,c.id""",
                (q["question_key"], item[value_name]))
    named_by = [row["question_label"] for row in cur.fetchall()]
    if named_by:
        raise ValueError(f"The show/hide rule of {quoted(named_by)} looks for “{item[label_name]}”. Change or delete that rule "
                         "first (on that question's page), then try again.")


# ------------------------------------------------------------------------------------------ show/hide rules

@pages.route(f"{BASE}/questions/<int:question_id>/rules", methods=["POST"])
def planning_question_rules(question_id):
    """Adds or changes a show/hide rule."""
    if not sign_in.allowed():
        return sign_in.go_to_login()
    if (refused := refuse_without_editor()):
        return refused
    who, action = sign_in.portal_person(), request.form.get("action", "")
    here = f"{BASE}/questions/{question_id}"
    try:
        with database.connect() as conn:
            with database.cursor(conn) as cur:
                cur.execute("select * from public.planning_questions where id=%s for update", (question_id,))
                q = cur.fetchone()
                if not q:
                    raise ValueError("This question no longer exists. Reload the page.")
                if q["protected"]:
                    raise ValueError(f"“{q['question_label']}” is locked: its show/hide rules are fixed, so a rule can never hide it.")
                # One rule change at a time, so two people cannot build a circle of rules together.
                cur.execute("lock table public.planning_question_visibility_rules in share row exclusive mode")
                message = add_rule(cur, who, q) if action == "add" else change_rule(cur, who, q, action)
        flash(message)
        return redirect(here)
    except (ValueError, psycopg2.Error) as error:
        return nothing_changed(error, here)


def add_rule(cur, who, q):
    """Adds a show/hide rule to question q. Returns the message."""
    parent_key, operator = request.form.get("parent", ""), request.form.get("operator", "")
    # Only a question on the form (active, in an active section): other parents are ignored.
    cur.execute("""select q.* from public.planning_questions q
      join public.planning_question_sections s on s.id=q.section_id and s.active
      where q.question_key=%s and q.active""", (parent_key,))
    parent = cur.fetchone()
    if not parent or parent["question_type"] not in PARENT_TYPES:
        raise ValueError("Choose a number, yes/no or choice question that is on the form.")
    if parent["id"] == q["id"]:
        raise ValueError("A question cannot depend on itself.")
    if operator not in OPERATORS:
        raise ValueError("Choose one of the listed conditions.")
    value = rule_value(cur, parent, operator, text_field("value", "The answer", 200, required=True))
    cur.execute("""insert into public.planning_question_visibility_rules(child_question_key,parent_question_key,operator,comparison_value)
      values(%s,%s,%s,%s) returning id,to_jsonb(planning_question_visibility_rules.*) as row""", (q["question_key"], parent_key, operator, value))
    created = cur.fetchone()
    audit(cur, who, "planning_question_visibility_rules",
          {"id": created["id"], "child": q["question_key"], "parent": parent_key}, None, created["row"], "Rule added")
    return "Rule added. The question is now shown only when all its rules are met."


def rule_value(cur, parent, operator, raw):
    """The answer a rule compares with, as stored: a plain number, true/false, or a choice's code."""
    if parent["question_type"] == "NUMBER":
        number = finite_number(raw)
        if number is None:
            raise ValueError(f"“{parent['question_label']}” is a number question: type a number.")
        return plain(number)
    if operator not in {"equals", "not_equals"}:
        raise ValueError("Yes/No and choice questions can only use “is” or “is not”.")
    if parent["question_type"] == "BOOLEAN":
        value = yes_no(raw)
        if not value:
            raise ValueError("Type Yes or No.")
        return value
    cur.execute("select option_value,option_label from public.planning_question_options where question_id=%s and active", (parent["id"],))
    choices = cur.fetchall()
    value = choice_code(raw, [(o["option_value"], o["option_label"]) for o in choices])
    if not value:
        listed = ", ".join(o["option_label"] for o in choices)
        raise ValueError(f"Type one of the choices of “{parent['question_label']}”: {listed}.")
    return value


def change_rule(cur, who, q, action):
    """Deletes a rule, or turns it on or off. Returns the message."""
    cur.execute("select * from public.planning_question_visibility_rules where id=%s and child_question_key=%s for update",
                (int(request.form.get("rule_id") or 0), q["question_key"]))
    rule = cur.fetchone()
    if not rule:
        raise ValueError("This rule no longer exists. Reload the page.")
    rule_key = {"id": rule["id"], "child": rule["child_question_key"], "parent": rule["parent_question_key"]}
    if action == "delete":
        cur.execute("delete from public.planning_question_visibility_rules t where id=%s returning to_jsonb(t) as row", (rule["id"],))
        audit(cur, who, "planning_question_visibility_rules", rule_key, cur.fetchone()["row"], None, "Rule deleted")
        return "Rule deleted."
    if action not in {"on", "off"}:
        raise ValueError("Unknown action.")
    if action == "on":
        refuse_rule_without_its_choice(cur, rule)
    update_row(cur, who, "planning_question_visibility_rules", rule["id"], {"active": action == "on"}, rule_key,
               "Rule turned on" if action == "on" else "Rule turned off")
    return "Rule turned on." if action == "on" else "Rule turned off: it no longer hides the question."


def refuse_rule_without_its_choice(cur, rule):
    """The choice a rule looks for may have been retired or deleted while the rule was off."""
    cur.execute("""select p.question_label,exists(select 1 from public.planning_question_options o
      where o.question_id=p.id and o.option_value=%s and o.active) offered
      from public.planning_questions p where p.question_key=%s and p.question_type in ('SELECT','RADIO')""",
                (rule["comparison_value"], rule["parent_question_key"]))
    parent = cur.fetchone()
    if parent and not parent["offered"]:
        raise ValueError(f"“{parent['question_label']}” no longer offers the choice this rule looks for, so the question "
                         "would never be shown. Delete this rule and add a new one.")


# ------------------------------------------------------------------------------------------ preview and history

@pages.route(f"{BASE}/preview")
def planning_questions_preview():
    """The form as missionaries see it (read only)."""
    if not sign_in.allowed():
        return sign_in.go_to_login()
    with database.connect() as conn:
        with database.cursor(conn) as cur:
            sections, questions, rules = load_catalog(cur)
            cur.execute("select * from public.planning_question_options where active order by display_order,id")
            options = cur.fetchall()
            cur.execute("select * from public.planning_question_grid_rows where active order by display_order,id")
            grid_rows = cur.fetchall()
    active = on_form(sections, questions)  # rules whose parent is not on the form are ignored (as in Weekly Planning)
    labels = {q["question_key"]: q["question_label"] for q in questions}
    cards = []
    for section in (s for s in sections if s["active"]):
        items = []
        for q in (item for item in questions if item["section_id"] == section["id"] and item["active"]):
            shown = [r for r in rules if r["active"] and r["child_question_key"] == q["question_key"] and r["parent_question_key"] in active]
            items.append(f"""<div class="question"><span class="q-label">{esc(q['question_label'])}{' <span class="req">*</span>' if q['required'] else ''}</span>
                  {preview_control(q, [o for o in options if o['question_id'] == q['id']], [r for r in grid_rows if r['question_id'] == q['id']])}
                  {f"<div class='note'>{esc(q['help_text'])}</div>" if q['help_text'] else ''}
                  {f"<div class='note'><b>Shown only when</b> {esc(' and '.join(rule_text(r, labels) for r in shown))}</div>" if shown else ''}</div>""")
        cards.append(f"<div class='card'><h3>{esc(section['section_title'])}</h3><p class='muted'>{esc(section['description'])}</p>{''.join(items) or '<p class=muted>No questions.</p>'}</div>")
    return pq_page(f"""<p><a href="{BASE}">← All planning questions</a></p><div class="card"><div class="step">Preview</div><h2>Weekly Planning as missionaries see it</h2>
          <p class="muted">Read only. Questions marked <span class="req">*</span> are required. Each question also shows last week's answer (“Last week: …”) when there is one.</p></div>
          <div class="preview">{''.join(cards)}<div class="card"><h3>Friends with a Baptismal Date · New Member Follow-up · High-Potential Friends</h3><p class="muted">These person cards come after the questions. They are fixed in the portal and cannot be changed here.</p></div></div>""")


def preview_control(question, options, rows):
    """The (disabled) answer box of a question on the preview, as Weekly Planning shows it."""
    kind = question["question_type"]
    placeholder = f"placeholder='{esc(question.get('placeholder'))}'" if question.get("placeholder") else ""
    if kind == "GRID":
        head = "".join(f"<th scope='col'>{esc(o['option_label'])}</th>" for o in options)
        body = "".join(f"<tr><th scope='row'>{esc(r['row_label'])}</th>" + "".join(
            f"<td><label><input type='radio' disabled aria-label='{esc(o['option_label'])}'> <span class='muted'>{esc(o['option_label'])}</span></label></td>" for o in options) + "</tr>"
            for r in rows)
        return f"<table class='gridq'><thead><tr><th></th>{head}</tr></thead><tbody>{body}</tbody></table>"
    if kind == "BOOLEAN":
        return pills("radio", ["Yes", "No"])
    if kind in {"RADIO", "CHECKBOX"}:
        return pills("radio" if kind == "RADIO" else "checkbox", [o["option_label"] for o in options])
    if kind == "SELECT":
        return "<select disabled><option>Choose…</option>" + "".join(f"<option>{esc(o['option_label'])}</option>" for o in options) + "</select>"
    if kind == "LONG_TEXT":
        return f"<textarea disabled {placeholder}></textarea>"
    if kind == "DATE":
        return "<input type='date' disabled>"
    if kind == "TEXT":
        return f"<input type='text' disabled {placeholder}>"
    return f"<input type='number' disabled {placeholder}><div class='note'>{number_limits_text(question)}</div>"


def pills(kind, labels):
    """Round Yes/No, radio or tick-box buttons."""
    return "<div class='pills'>" + "".join(f"<label><input type='{kind}' disabled> {esc(label)}</label>" for label in labels) + "</div>"


def number_limits_text(question):
    """'whole numbers, 0 or more', 'any number, 1 to 5' (whole phrases, so the portal catalog can translate each)."""
    low = plain(question.get("min_value")) or "0"
    high = plain(question.get("max_value"))
    if question.get("integer_only") is not False:
        return f"whole numbers, {low} to {high}" if high else f"whole numbers, {low} or more"
    return f"any number, {low} to {high}" if high else f"any number, {low} or more"


@pages.route(f"{BASE}/history")
def planning_questions_history():
    """The latest 300 changes, newest first."""
    if not sign_in.allowed():
        return sign_in.go_to_login()
    with database.connect() as conn:
        with database.cursor(conn) as cur:
            cur.execute("select * from public.planning_catalog_changes order by changed_at desc,id desc limit 300")
            changes = cur.fetchall()
    items = "".join(history_item(change) for change in changes)
    return pq_page(f"""<p><a href="{BASE}">← All planning questions</a></p><div class="card history"><div class="step">Change history</div><h2>Who changed the planning questions</h2>
          <p class="muted">The latest 300 changes, newest first ({settings.TIME_ZONE_NAME} time).</p>{items or "<p class='muted'>No changes yet.</p>"}</div>""")


def history_item(change):
    """One change: what (added, changed, deleted), when, who, which row, and up to 8 changed fields."""
    before, after = change["before_row"], change["after_row"]
    what = ("added" if before is None and after is not None else "deleted" if after is None and before is not None else "changed")
    name = next((str(value) for value in ((after or {}).get("question_label"), (after or {}).get("section_title"),
                                         (after or {}).get("option_label"), (after or {}).get("row_label"),
                                         (before or {}).get("question_label"), (before or {}).get("option_label"),
                                         (before or {}).get("row_label")) if value), "")
    key = ", ".join(f"{k}: {v if not isinstance(v, list) else ', '.join(map(str, v))}" for k, v in (change["row_key"] or {}).items())
    fields = changed_fields(before, after) if what == "changed" else []
    detail = "".join(f"<li>{esc(field.replace('_', ' '))}: {esc((before or {}).get(field))} → {esc((after or {}).get(field))}</li>" for field in fields[:8])
    return f"""<div class="item"><div><b>{esc(TABLE_NAMES.get(change['table_name'], change['table_name']))} {what}</b>{f' · {esc(name)}' if name else ''}
              <div class="note">{mission_time(change['changed_at'])} · {esc(change['actor'])} · <code>{esc(key)}</code>{f' · {esc(change["note"])}' if change['note'] else ''}</div>
              {f'<ul class="change">{detail}</ul>' if detail else ''}</div></div>"""
