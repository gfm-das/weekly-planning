"""The Role abilities page (/abilities): a table of roles and abilities with a switch in every cell that a manager may change,
a preview of what a change would do, a typed confirmation, and the change log with a revert button.

For managers only: the AP, the President and the Data Analyst, signed in through the portal (the old shared password has no
person behind it, and every change must name who made it, so it is refused here). Everyone else gets "403". The page checks
this itself on every request (gate), in addition to the check every DA Management page makes. Nothing on this page can give
access to DA Management, change a role, delete a place or change this page's own rule: those are not abilities in the table
(see abilities.py and roles.py). Every text is abilities_text.py.

Pages:
  /abilities                 the matrix and the change log
  /abilities/preview (POST)  "What saving will change" for the ticked switches, with the confirmation form
  /abilities/save (POST)     saves (type CHANGE), then back to /abilities
  /abilities/revert/<batch>  (POST) puts one saved change back
"""
from uuid import UUID

from flask import Blueprint, flash, redirect, request, session

import abilities
import database
import page
import roles
import sign_in
from abilities_text import plain, t
from page import h, mission_time

pages = Blueprint("abilities_page", __name__)


def deny(status=403):
    return page.render(f"<div class='card'><div class='error'><b>{t('abil.denied')}</b></div></div>", status)


def gate(write=False):
    """None when this person may use the page, else the answer to send (a redirect to the sign-in for a page that was opened
    without a session, 403 for everyone else). write=True also needs a person behind the sign-in."""
    if not sign_in.allowed():
        return sign_in.go_to_login() if request.method == "GET" and not session.get("portal_role") else deny()
    if session.get("portal_role") not in roles.MANAGER_ROLES:
        return deny()
    if write and not sign_in.portal_person():
        return page.render(f"<div class='card'><div class='error'>{t('abil.needPerson')}</div></div>", 403)
    return None


def role_cell(role):
    return f"<th scope='col'>{h(roles.role_name(role))}</th>"


def fixed_cell(value):
    return f"<td class='cell muted'>{t('abil.alwaysOn' if value else 'abil.alwaysOff')}</td>"


def matrix_html(table):
    """The matrix: abilities down, roles across. A switch where a manager may decide, 'Always on' / 'Always off' elsewhere."""
    head = "".join(role_cell(role) for role in abilities.DISPLAY_ROLES)
    body = ""
    for ability in roles.ABILITIES:
        cells = ""
        for role in abilities.DISPLAY_ROLES:
            value = table[(role, ability)]
            if (role, ability) in abilities.SWITCH_CELLS:
                label = h(page_text(ability))
                cells += (f"<td class='cell'><input type='checkbox' name='on' value='{h(abilities.cell_key(role, ability))}'"
                          f"{' checked' if value else ''} aria-label='{label}'></td>")
            else:
                cells += fixed_cell(value)
        body += (f"<tr><th scope='row'>{t('abil.ability.' + ability)}<br><span class='muted'>{t('abil.about.' + ability)}</span></th>"
                 f"{cells}</tr>")
    return (f"<div class='scroll'><table class='abil'><thead><tr><th>{t('abil.col.ability')}</th>{head}</tr></thead>"
            f"<tbody>{body}</tbody></table></div>")


def page_text(ability):
    """The ability's name as plain text (for an aria-label, which the page translation reads from the catalog)."""
    return plain("abil.ability." + ability)


def log_html(log):
    if not log:
        return f"<p class='muted'>{t('abil.log.empty')}</p>"
    rows = ""
    for batch in log:
        changes = "".join(
            f"<li><span>{h(roles.role_name(role))}</span> &middot; <span>{t('abil.ability.' + ability)}</span>: "
            f"<span>{t('abil.on' if before else 'abil.off')}</span> &rarr; <span>{t('abil.on' if after else 'abil.off')}</span></li>"
            for role, ability, before, after in batch["cells"])
        note = f"<br><span class='muted'>{h(batch['note'])}</span>" if batch["note"] else ""
        marks = (f"<br><span class='badge'>{t('abil.log.isRevert')}</span>" if batch["reverts"] else "")
        if batch["reverted"]:
            action = f"<span class='badge'>{t('abil.log.wasReverted')}</span>"
        else:
            action = (f"<form method='post' action='/abilities/revert/{h(batch['batch'])}' class='inline'>"
                      f"<button class='secondary' onclick=\"return confirm('{t('abil.log.confirm')}')\">{t('abil.log.revert')}</button></form>")
        rows += (f"<tr><td>{h(mission_time(batch['when']))}</td><td>{h(batch['who'])}</td>"
                 f"<td><ul>{changes}</ul>{note}{marks}</td><td>{action}</td></tr>")
    return (f"<div class='scroll'><table><thead><tr><th>{t('abil.log.when')}</th><th>{t('abil.log.who')}</th>"
            f"<th>{t('abil.log.what')}</th><th></th></tr></thead><tbody>{rows}</tbody></table></div>")


def read_screen():
    """(matrix or None, change log) as the database says now."""
    with database.connect() as conn:
        with database.cursor(conn) as cur:
            table = abilities.read_table(cur)
            log = abilities.read_log(cur) if table is not None else []
    return table, log


@pages.route("/abilities")
def screen():
    refused = gate()
    if refused:
        return refused
    table, log = read_screen()
    intro = (f"<div class='card'><h2>{t('abil.title')}</h2><p>{t('abil.intro')}</p><p class='muted'>{t('abil.managersNote')}</p>"
             f"<p class='muted'>{t('abil.delay')}</p></div>")
    if table is None:
        return page.render(intro + f"<div class='card'><p class='warn'>{t('abil.builtIn')}</p></div>")
    form = (f"<div class='card abil-card'><form method='post' action='/abilities/preview'>{matrix_html(table)}"
            f"<input type='hidden' name='base' value='{abilities.base_token(table)}'>"
            f"<div class='actions' style='margin-top:14px'><button>{t('abil.preview')}</button></div></form></div>")
    return page.render(intro + form + f"<div class='card'><h2>{t('abil.log.title')}</h2>{log_html(log)}</div>")


def wanted_or_none():
    """The wanted switches from the ticked boxes of the form, or None when a value is not a switch."""
    try:
        return abilities.wanted_from(request.form.getlist("on"))
    except ValueError:
        return None


@pages.route("/abilities/preview", methods=["POST"])
def preview():
    """What saving would change, in a table (role, ability, now, after, what it means), and the form that confirms it."""
    refused = gate(write=True)
    if refused:
        return refused
    wanted = wanted_or_none()
    if wanted is None:
        flash(abilities_message("abil.badCell"))
        return redirect("/abilities")
    with database.connect() as conn:
        with database.cursor(conn) as cur:
            table = abilities.read_table(cur)
    if table is None:
        return page.render(f"<div class='card'><p class='warn'>{t('abil.builtIn')}</p></div>")
    if request.form.get("base") != abilities.base_token(table):
        flash(abilities_message("abil.stale"))
        return redirect("/abilities")
    changes = abilities.plan(table, wanted)
    if not changes:
        return page.render(f"<div class='card'><h2>{t('dam.whatSavingWillChange')}</h2><p>{t('abil.nothing')}</p>"
                           f"<div class='nav'><a href='/abilities'>{t('abil.back')}</a></div></div>")
    rows = ""
    for change in changes:
        effect = t("abil.effect." + change["ability"]) if not change["after"] else t("abil.effect.back")
        rows += (f"<tr><td>{h(roles.role_name(change['role']))}</td><td>{t('abil.ability.' + change['ability'])}</td>"
                 f"<td>{t('abil.on' if change['before'] else 'abil.off')}</td><td><b>{t('abil.on' if change['after'] else 'abil.off')}</b></td>"
                 f"<td>{effect}</td></tr>")
    hidden = "".join(f"<input type='hidden' name='on' value='{h(abilities.cell_key(role, ability))}'>"
                     for (role, ability), value in wanted.items() if value)
    body = (f"<div class='card'><h2>{t('dam.whatSavingWillChange')}</h2><div class='scroll'><table><thead><tr><th>{t('dam.role')}</th>"
            f"<th>{t('abil.col.ability')}</th><th>{t('abil.col.now')}</th><th>{t('abil.col.after')}</th><th>{t('abil.col.meaning')}</th></tr></thead>"
            f"<tbody>{rows}</tbody></table></div>"
            f"<form method='post' action='/abilities/save'>{hidden}<input type='hidden' name='base' value='{h(abilities.base_token(table))}'>"
            f"<div class='form-field'><label>{t('abil.reason')}<input name='note' maxlength='{abilities.NOTE_LIMIT}' autocomplete='off'></label></div>"
            f"<div class='form-field'><label>{t('abil.typeChange')}<input name='confirm' autocomplete='off' required></label></div>"
            f"<div class='actions'><button>{t('abil.save')}</button><a href='/abilities'>{t('abil.back')}</a></div></form></div>")
    return page.render(body)


def abilities_message(key):
    return plain(key)


@pages.route("/abilities/save", methods=["POST"])
def save():
    refused = gate(write=True)
    if refused:
        return refused
    wanted = wanted_or_none()
    if wanted is None:
        flash(abilities_message("abil.badCell"))
        return redirect("/abilities")
    if request.form.get("confirm", "").strip() != abilities.CONFIRM_WORD:
        flash(abilities_message("abil.badWord"))
        return redirect("/abilities")
    status, _changes = abilities.save_change(wanted, request.form.get("base", ""), request.form.get("note", "").strip(),
                                             sign_in.portal_person())
    flash(abilities_message({"saved": "abil.saved", "nochange": "abil.noChange", "stale": "abil.stale",
                             "unreadable": "abil.builtIn"}[status]))
    return redirect("/abilities")


@pages.route("/abilities/revert/<batch_id>", methods=["POST"])
def revert(batch_id):
    refused = gate(write=True)
    if refused:
        return refused
    try:
        batch = str(UUID(batch_id))
    except ValueError:
        flash(abilities_message("abil.revertMissing"))
        return redirect("/abilities")
    status, _changes = abilities.revert_batch(batch, sign_in.portal_person())
    flash(abilities_message({"reverted": "abil.reverted", "missing": "abil.revertMissing", "already": "abil.revertDone",
                             "stale": "abil.revertStale", "unreadable": "abil.builtIn"}[status]))
    return redirect("/abilities")
