"""The Historical CSV pages: import the old Weekly Planning form export (from before the portal) into the reports.

Pages, in the order a manager uses them:
  /historical            1. upload the CSV, and choose what happens when a report already exists
  /historical/preview    2. the check (historical_preview.py): mapped areas, units, weeks, problems, choices
  /historical/choices       the choices from the check page (kept in the session), then back to the check
  /historical/review        the check again (for example after saving Area mappings)
  /historical/apply      3. Apply (historical_apply.py), after the "I reviewed" tick

The uploaded file waits in UPLOAD_DIR between the steps; the session remembers which one and the choices.
"""
import json
import uuid
from pathlib import Path

from flask import Blueprint, flash, redirect, request, session

import database
import historical_apply
import historical_preview
import page
import people_pages
import settings
import sign_in
from historical_preview import COLLISION_METRICS, METRIC_LABELS
from historical_units import unit_catalog, unit_label
from page import h

pages = Blueprint("historical_pages", __name__)

SESSION_KEYS = ("historical_file", "historical_filename", "historical_choices")


# ------------------------------------------------------------------------------------------ 1. upload

@pages.route("/historical")
def historical_home():
    """Step 1: the upload form."""
    if not sign_in.allowed():
        return sign_in.go_to_login()
    return page.render("""<div class="card"><div class="step">1 · Upload</div><h2>Historical Weekly Planning</h2>
          <p class="muted">Import a CSV export of past Weekly Planning forms. Original area labels and every answer are retained; reporting uses the current mapped area.</p>
          <form action="/historical/preview" method="post" enctype="multipart/form-data"><label class="form-field">Historical CSV<input type="file" name="file" accept=".csv" required></label><label class="form-field">When a report already exists<select name="duplicate_policy"><option value="replace">Replace it with the imported report</option><option value="stop">Stop and ask me to resolve it</option></select></label><label><input type="checkbox" name="combine_mapped" value="yes" checked> Combine old areas that report for the same current area, ward/branch and week (untick to choose in the preview)</label><p><button>Validate &amp; preview</button></p></form></div>
          <div class="card"><h3>Before you begin</h3><ul><li>Use the original form-export headings, including Timestamp, Email Address, companionship, Ward/Branch, and reporting Sunday.</li><li>The latest submission wins when an area submitted twice for the same Sunday.</li><li><a href="/mappings">Confirm area-name mappings</a> before applying.</li><li>Missionaries serving two wards/branches fill out one form per unit each week: both are imported, each as its own unit report. The preview shows which unit each Ward/Branch answer was matched to and lets you correct it.</li><li>Choose whether existing reports are replaced (Replace overwrites that unit's report) or the import stops. Old areas reporting for the same current area and unit can be combined into one report.</li></ul></div>""")


@pages.route("/historical/preview", methods=["POST"])
def historical_preview_route():
    """Keeps the uploaded CSV waiting and shows its check."""
    if not sign_in.allowed():
        return sign_in.go_to_login()
    try:
        upload = request.files["file"]
        if Path(upload.filename or "").suffix.lower() != ".csv":
            raise ValueError("Upload a CSV file.")
        path = settings.UPLOAD_DIR / (str(uuid.uuid4()) + ".csv")
        upload.save(path)
        session["historical_file"] = str(path)
        session["historical_filename"] = Path(upload.filename).name
        session["historical_duplicate_policy"] = request.form.get("duplicate_policy", "replace")
        session["historical_combine_mapped"] = request.form.get("combine_mapped") == "yes"
        session["historical_choices"] = {}
        return check_page(path)
    except Exception as e:
        return page.render(f"<div class='error'><b>Validation blocked.</b><br>{h(e)}</div><p><a href='/historical'>Back</a></p>", 400)


# ------------------------------------------------------------------------------------------ 2. the check

def check_page(path):
    """The check page for the waiting upload, with the choices made so far."""
    checked = historical_preview.preview(path, replace_existing=session.get("historical_duplicate_policy", "replace") == "replace",
                                         combine_mapped=session.get("historical_combine_mapped", True),
                                         choices=session.get("historical_choices") or {})
    rows = "".join(f"<tr><td>{h(r['source'])}</td><td>{h(r['area']['name'])}</td><td>{h(r['unit_name'] or 'no unit')}</td><td>{r['sunday']}</td><td>{h(a)}</td></tr>"
                   for r, a in zip(checked["rows"], actions(checked["rows"])))
    rows += "".join(f"<tr class='muted'><td>{h(r['source'])}</td><td>{h(r['area']['name'])}</td><td>{h(r['unit_name'] or 'no unit')}</td><td>{r['sunday']}</td><td>{h(r['skip'])}</td></tr>" for r in checked.get("skipped", []))
    notices = "<div class='card'><b>Please check</b><ul>" + "".join(f"<li>{h(n)}</li>" for n in checked.get("notices", [])) + "</ul></div>" if checked.get("notices") else ""
    blocked = "<div class='error'><b>Resolve these items first</b><ul>" + "".join(f"<li>{h(e)}</li>" for e in checked["errors"]) + "</ul><a href='/mappings'>Manage mappings</a></div>" if checked["errors"] else ""
    return page.render(f"<div class='card'><div class='step'>2 · Validation preview</div><h2>{h(session.get('historical_filename'))}</h2><div class='grid'><div class='metric'><b>{checked['source_rows']}</b><br>source rows</div><div class='metric'><b>{len(checked['rows'])}</b><br>mapped reports</div><div class='metric'><b>{checked['duplicates']}</b><br>older duplicates skipped</div></div></div>{blocked}{notices}<div class='card scroll'><table><thead><tr><th>Original area</th><th>Current reporting area</th><th>Ward/Branch (unit)</th><th>Reporting Sunday</th><th>Action</th></tr></thead><tbody>{rows}</tbody></table></div>{people_summary(checked)}{choices_card(checked)}{people_questions(checked)}{apply_card(checked)}<p><a href='/historical'>Cancel</a> · <a href='/historical/review'>Recheck after mapping changes</a></p>",
                       400 if checked["errors"] else 200)


def people_summary(checked):
    """What the import does with the people named in the forms."""
    counts = checked["people"]["counts"]
    if not counts["people"] and not counts["high_potentials"]:
        return ""
    return (f"<div class='card'><b>People in the forms</b><div class='grid'><div class='metric'><b>{counts['people']}</b><br>new members and friends with a baptismal date</div>"
            f"<div class='metric'><b>{counts['to_join']}</b><br>already stored (joined, blanks filled)</div>"
            f"<div class='metric'><b>{counts['high_potentials']}</b><br>high-potential names on plans</div></div>"
            "<p class='muted'>They are saved as real people, put on the weekly plans they were named on, and the ones who are still relevant "
            "(new members up to a year after baptism; friends and high-potential friends from last week's plan) are loaded into this week's plans.</p></div>")


def people_questions(checked):
    """The open "same person?" pairs, with the people's areas."""
    if not checked["people"]["questions"]:
        return ""
    with database.connect() as conn:
        with database.cursor(conn) as cur:
            areas = people_pages.area_labels(cur)
    return people_pages.question_card(checked["people"]["questions"], "/historical/review", areas)


def actions(items):
    """What happens to each row's report: new, replace #id, combine into the same report, or move an earlier import."""
    seen, result = set(), []
    for r in items:
        group = (r["area"]["id"], r["sunday"], r["unit_id"])
        if group in seen:
            result.append("Combine into the same report")
            continue
        seen.add(group)
        removes = f"; remove earlier import {', '.join(r['removes'])}" if r.get("removes") else ""
        if r.get("moved_from"):
            result.append(f"Move earlier import from {r['moved_from']}" + removes)
        else:
            result.append((f"Replace report #{r['existing_id']}" if r.get("existing_id") else "New report") + removes)
    return result


def apply_card(checked):
    """Step 3: the Apply form, or why it is not there yet."""
    if checked["errors"]:
        return ""
    if checked["pending"]:
        return "<div class='card'><div class='step'>3 · Confirm</div><p class='warn'>Make the choices above and click <b>Use these choices</b> to enable Apply.</p></div>"
    return f"""<div class="card"><div class="step">3 · Confirm</div><form action="/historical/apply" method="post"><input type="hidden" name="state_token" value="{checked['state_token']}"><input type="hidden" name="choices" value="{h(json.dumps(checked['effective_choices'], sort_keys=True))}"><p><label><input type="checkbox" name="confirmed" value="yes" required> I reviewed the mapped areas, reporting weeks, and my choices.</label></p><button>Apply historical import</button></form></div>"""


def choices_card(checked):
    """Step 2b: every choice the manager can or must make."""
    ui = checked["choices"]
    if not ui["collisions"] and not ui["targets"] and not ui["units"] and not ui["merges"]:
        return ""
    parts = [units_part(ui), merges_part(ui)] + [collision_part(col) for col in ui["collisions"]] + [target_part(t) for t in ui["targets"]]
    return f"""<div class="card" id="choices"><div class="step">2b · Your choices</div><h3>Choose how to import</h3><form action="/historical/choices" method="post">{''.join(parts)}<p><button>Use these choices &amp; recheck</button></p></form></div>"""


def active_units():
    with database.connect() as conn:
        with database.cursor(conn) as cur:
            return [u for u in unit_catalog(cur)[0] if u["active"]]


def units_part(ui):
    """Ward/Branch → unit: the answers still to look at first, the recognised ones folded away."""
    if not ui["units"]:
        return ""
    catalog = active_units()
    head = "<table><thead><tr><th>Ward/Branch in the file</th><th>Mapped area</th><th>Old areas</th><th>Rows</th><th>Unit used</th><th>How it was worked out</th></tr></thead><tbody>"
    check = [u for u in ui["units"] if not u["confident"] or u["overridden"]]
    sure = [u for u in ui["units"] if u["confident"] and not u["overridden"]]
    out = "<div class='choice-group'><h4>Ward/Branch → unit</h4><p class='muted'>Missionaries who serve two wards/branches fill out one form per unit each week. Each unit gets its own report, so both are imported. Change a unit here if it is wrong; the change applies to every row with that answer and area.</p>"
    if check:
        out += f"<p><b>Please check ({len(check)})</b></p>" + head + "".join(unit_row(u, catalog) for u in check) + "</tbody></table>"
    if sure:
        out += f"<details><summary>Recognised from the Ward/Branch answer ({len(sure)})</summary>" + head + "".join(unit_row(u, catalog) for u in sure) + "</tbody></table></details>"
    return out + "</div>"


def unit_row(u, catalog):
    """One Ward/Branch answer with the unit used and a list to change it."""
    options = "".join(f"<option value='{x['id']}' {'selected' if x['id'] == u['selected'] else ''}>{h(unit_label(x))}{' (suggested)' if x['id'] == u['auto'] else ''}</option>" for x in catalog)
    how = "you chose this unit" if u["overridden"] else u["how"]
    warn = "" if u["linked"] or not u["selected"] else " <span class='warn'>(not linked to this area today)</span>"
    # unitauto: the suggestion (so an unchanged choice is not kept); unitguess: the answer was a guess (so an unchanged
    # choice counts as "looked at").
    guess = "" if u["confident"] else f"<input type='hidden' name='{h('unitguess::' + u['key'])}' value='1'>"
    return (f"<tr><td>{h(u['text'] or '(blank)')}</td><td>{h(u['area'])}</td><td>{h(', '.join(u['labels']))}</td><td>{u['rows']}</td>"
            f"<td><input type='hidden' name='{h('unitauto::' + u['key'])}' value='{u['auto'] or ''}'>{guess}<select name='{h('unit::' + u['key'])}'><option value=''>— no unit —</option>{options}</select>{warn}</td><td class='muted'>{h(how)}</td></tr>")


def merges_part(ui):
    """Old areas that report for the same current area and unit: combine, or keep one (for all weeks, or per week)."""
    parts = []
    for m in ui["merges"]:
        name = "merge::" + m["key"]
        radios = f"""<label class="choice"><input type="radio" name="{h(name)}" value="combine" {'checked' if m['selected'] in (None, 'combine') else ''}> <b>Combine</b> them into one report each week (numbers are added up)</label>"""
        radios += "".join(f"""<label class="choice"><input type="radio" name="{h(name)}" value="{h('keep:' + l)}" {'checked' if m['selected'] == 'keep:' + l else ''}> Keep only <b>{h(l)}</b> each week (skip the others)</label>""" for l in m["labels"])
        weeks = "".join(f"""<tr><td>{w['sunday']}</td><td>{h(', '.join(w['labels']))}</td><td><select name="{h('merge::' + w['key'])}"><option value="">Same as above</option><option value="combine" {'selected' if w['override'] == 'combine' else ''}>Combine</option>{''.join(f"<option value='{h('keep:' + l)}' {'selected' if w['override'] == 'keep:' + l else ''}>Keep only {h(l)}</option>" for l in w['labels'])}</select>{' <span class="warn">choose for this week</span>' if w['missing'] else ''}</td></tr>""" for w in m["weeks"])
        parts.append(f"""<div class="choice-group" data-merge="{h(m['key'])}"><h4>{h(m['area'])} ({h(m['unit'])}): {len(m['weeks'])} week(s) where {len(m['labels'])} old areas report for the same unit</h4><p class="muted">Old areas: {h(', '.join(m['labels']))}. Reports for <i>different</i> units are always imported separately; this choice is only for rows of the same unit.</p>{radios}<details><summary>Change single weeks</summary><table><thead><tr><th>Sunday</th><th>Old areas</th><th>Choice</th></tr></thead><tbody>{weeks}</tbody></table></details></div>""")
    return "".join(parts)


def collision_part(col):
    """Labels that differ only by punctuation or spacing: keep one, or combine them."""
    name = "collision::" + col["key"]
    head = "".join(f"<th>{h(METRIC_LABELS.get(heading, heading.replace(' - Actual', '')))}</th>" for heading in COLLISION_METRICS)
    body = "".join(f"<tr><td><b>{h(r['label'])}</b></td><td>{h(r['area'])}</td><td>{h(r['timestamp'])}</td><td>{h(r['unit'])}</td>"
                   + "".join(f"<td>{h(r['metrics'][heading])}</td>" for heading in COLLISION_METRICS) + "</tr>" for r in col["rows"])
    radios = "".join(f"""<label class="choice"><input type="radio" name="{h(name)}" value="{h('keep:' + r['label'])}" required {'checked' if col['selected'] == 'keep:' + r['label'] else ''}> Keep only <b>{h(r['label'])}</b> (skip the other row)</label>""" for r in col["rows"])
    radios += f"""<label class="choice"><input type="radio" name="{h(name)}" value="combine" required {'checked' if col['selected'] == 'combine' else ''}> <b>Combine</b> them into one report (indicators are summed, like combining mapped areas)</label>"""
    return f"""<div class="choice-group" data-collision="{h(col['key'])}"><h4>{col['sunday']}: these labels differ only by punctuation or spacing</h4><table><thead><tr><th>Original label</th><th>Mapped area</th><th>Submitted</th><th>Ward/Branch</th>{head}</tr></thead><tbody>{body}</tbody></table>{radios}</div>"""


def target_part(t):
    """Several reports already exist for an area and week: which one this import replaces."""
    name = "target::" + t["group"]
    body = "".join(f"""<tr><td><label><input type="radio" name="{h(name)}" value="{r['id']}" required {'checked' if t['selected'] == r['id'] else ''}> Replace #{r['id']}</label></td><td>{h(r['unit_name'] or r['unit_id'] or 'none')}</td><td>{h(r['status'])}</td><td>{h(r['historical_source_key'] or '-')}</td><td>{r['friends_found_actual']}</td><td>{r['lessons_with_friends_actual']}</td><td>{r['sacrament_attendance_actual']}</td><td>{r['baptismal_dates_actual']}</td></tr>""" for r in t["reports"])
    note = " <span class='muted'>(preselected: it already holds an earlier import of this label)</span>" if t["defaulted"] else ""
    return f"""<div class="choice-group" data-target="{h(t['group'])}"><h4>{h(t['area'])}, {t['sunday']}: {len(t['reports'])} reports already exist{note}</h4><table><thead><tr><th>Choose</th><th>Unit</th><th>Status</th><th>Import key</th><th>New people being taught</th><th>Lessons w/ friends</th><th>Sacrament att.</th><th>Baptismal dates</th></tr></thead><tbody>{body}</tbody></table><p class="muted">The chosen report is replaced and keeps its unit. The other reports are not changed or deleted, and they still count in weekly totals.</p></div>"""


@pages.route("/historical/choices", methods=["POST"])
def historical_choices():
    """Keeps the choices of the check page, then shows the check again."""
    if not sign_in.allowed():
        return sign_in.go_to_login()
    if not session.get("historical_file"):
        return redirect("/historical")
    session["historical_choices"] = choices_from_form(request.form)  # checked against the upload by every check and Apply
    return redirect("/historical/review")


def choices_from_form(form):
    """The choices of the check page's form, in the shape historical_preview.preview() reads (each value shortened, so
    the session cookie stays small). A unit is kept only when it differs from the suggestion; an unchanged guessed
    unit is remembered as looked at (units_seen)."""
    chosen = {"collisions": {}, "targets": {}}
    for field, value in form.items():
        if field.startswith("collision::"):
            chosen["collisions"][field[len("collision::"):][:300]] = value[:500]
        elif field.startswith("target::"):
            chosen["targets"][field[len("target::"):][:100]] = value[:30]
        elif field.startswith("unit::"):
            key = field[len("unit::"):][:400]
            if value != form.get("unitauto::" + key, ""):
                chosen.setdefault("units", {})[key] = value[:30]
            elif form.get("unitguess::" + key):
                chosen.setdefault("units_seen", []).append(key)
        elif field.startswith("merge::"):
            if value:
                chosen.setdefault("merges", {})[field[len("merge::"):][:100]] = value[:500]
    return chosen


@pages.route("/historical/review")
def historical_review():
    """The check of the waiting upload again."""
    if not sign_in.allowed():
        return sign_in.go_to_login()
    path = session.get("historical_file")
    if not path or not Path(path).is_file():
        return redirect("/historical")
    return check_page(path)


# ------------------------------------------------------------------------------------------ 3. apply

@pages.route("/historical/apply", methods=["POST"])
def historical_apply_route():
    """Step 3: Apply, after the "I reviewed" tick."""
    if not sign_in.allowed():
        return sign_in.go_to_login()
    try:
        if request.form.get("confirmed") != "yes":
            raise ValueError("Review and confirm the preview first.")
        path = session.get("historical_file")
        if not path or not Path(path).is_file():
            raise ValueError("No historical upload is pending.")
        try:
            posted = json.loads(request.form.get("choices") or "{}")
        except ValueError:
            posted = None
        if not isinstance(posted, dict) or not request.form.get("state_token"):
            raise ValueError("The confirmation form is incomplete. Recheck the preview and choose again.")
        # The posted choices must be exactly the effective choices of the reviewed check (checked with the state token,
        # worked out again under lock). The session's own choices drive that second check.
        batch = historical_apply.apply_batch(path, session.get("historical_filename") or "historical.csv",
                                             session.get("historical_duplicate_policy", "replace") == "replace",
                                             session.get("historical_combine_mapped", True),
                                             choices=session.get("historical_choices") or {},
                                             state_token=request.form.get("state_token"), expected_choices=posted)
        Path(path).unlink(missing_ok=True)
        for key in SESSION_KEYS:
            session.pop(key, None)
        flash("Historical reports imported. Original labels and detailed answers were preserved.")
        return redirect(f"/imports/{batch}")
    except Exception as e:
        return page.render(f"<div class='error'><b>Nothing was committed.</b><br>{h(e)}</div><p><a href='/historical/review'>Back to preview</a></p>", 400)
