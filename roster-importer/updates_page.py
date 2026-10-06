"""DA Management > Updates: this computer's version, "Check for updates", what is new, and "Update now".

The page never runs git or a shell, and nothing from it reaches a shell. It talks to the updater on the host
computer (updater/gfm-updater.ps1, started by Windows Task Scheduler) through two folders that docker-compose.yml
mounts into this container:

  /updates/requests  The page writes one small file here, request.json:
                       {"action": "check", ...}  or  {"action": "update", "target": <the version shown>,
                       "confirmed": true, ...}
                     plus who asked (role and user id, for the updater's log).
  /updates/status    Read-only here. status.json, written by the updater: this computer's version, the result of
                     the last check (what is new), and the result of the last update.

The updater checks every field of a request again itself; the checks here only explain things early and kindly.

Who: the managers of the mission (AP, President, Data Analyst) signed in through the portal, checked on every
request against the database (sign_in.allowed). The old password sign-in has no person behind it, so it cannot use
this page.

Texts: every visible text is in TEXT below and, with the same English, in the portal's catalog
(portal/i18n/catalogs.json, keys updates.*). Each is marked with data-i18n, so the portal's i18n.js can translate it.
"""
import json
import os
import re
import uuid
from datetime import datetime, timezone
from html import escape
from pathlib import Path

from flask import Blueprint, flash, redirect, request, session

import page
import roles
import settings
import sign_in

pages = Blueprint("updates_page", __name__)

UPDATES_DIR = settings.UPDATES_DIR
CONFIRM_WORD = "UPDATE"
VERSION = re.compile(r"^[0-9a-f]{40}$")
WRAP = ' style="overflow-wrap:anywhere"'  # long folder names break on a phone instead of widening the page
# The updater writes into its status file at least every minute while it waits, and at every step of an update.
# One step (a rebuild) can take a while, so a busy updater gets longer before the page says it is not running.
QUIET_MINUTES = 10
BUSY_MINUTES = 60
BUSY_STATES = {"checking", "testing", "updating", "rolling_back"}
# The reasons an update cannot happen now, as the updater names them (see Get-BlockedReason there).
BLOCKED = {"local_ahead", "diverged", "changed_by_hand", "not_on_branch", "by_hand"}

TEXT = {
    "updates.title": "Updates",
    "updates.intro": "New versions of the mission system come from GitHub. Check for updates, read what is new, "
                     "and install it when it suits the mission.",
    "updates.thisComputer": "This computer runs",
    "updates.comesFrom": "Updates come from",
    "updates.lastChecked": "Last checked",
    "updates.neverChecked": "Not checked yet",
    "updates.check": "Check for updates",
    "updates.asked": "Thank you. The updater on this computer picks this up within a few seconds; this page "
                     "refreshes by itself.",
    "updates.state.checking": "Looking on GitHub for updates…",
    "updates.state.testing": "Testing the new version before installing it…",
    "updates.state.updating": "Installing the update. Please keep this computer on. DA Management restarts in "
                              "between; this page comes back by itself.",
    "updates.state.rolling_back": "Putting the previous version back…",
    "updates.result.up_to_date": "This computer is up to date.",
    "updates.result.updates": "There is a new version. Read what is new below.",
    "updates.result.no_remote": "This computer is not connected to GitHub yet. The one-time setup is in "
                                "docs/handoff/round7/updater.md.",
    "updates.result.fetch_failed": "GitHub could not be reached, or this computer is not signed in to GitHub. "
                                   "Please try again later; the Data Analyst can check the one-time setup.",
    "updates.result.check_failed": "The last check stopped part-way. Please try again; the updater's log says more.",
    "updates.result.stale": "This computer's version changed since the last check. Please check for updates again.",
    "updates.blocked.local_ahead": "This computer has changes that GitHub does not have yet, so it cannot update by "
                                   "itself. The Data Analyst decides how to bring them together.",
    "updates.blocked.diverged": "This computer and GitHub each have changes the other does not have, so it cannot "
                                "update by itself. The Data Analyst decides how to bring them together.",
    "updates.blocked.changed_by_hand": "Some files on this computer were changed by hand and not saved in Git, so it "
                                       "cannot update by itself. The Data Analyst can look at them with git status.",
    "updates.blocked.not_on_branch": "The code on this computer is not on a branch, so it cannot update by itself.",
    "updates.blocked.by_hand": "This update has a database change that a person installs by hand (see its notes), "
                               "so it cannot be installed from here.",
    "updates.newChanges": "What is new",
    "updates.changeDate": "Date of the change",
    "updates.changeText": "What changed",
    "updates.version": "Version",
    "updates.migrations": "Database changes in this update:",
    "updates.otherParts": "Parts of this update that a person installs by hand (see its notes):",
    "updates.install": "Install the update",
    "updates.installHelp": "Installing takes a few minutes. First the new version is tested and the database is "
                           "backed up. If anything does not work afterwards, the previous version is put back by "
                           "itself.",
    "updates.typeToConfirm": "To install, type UPDATE here",
    "updates.updateNow": "Update now",
    "updates.notRunning": "The updater on this computer is not running at the moment, so requests wait. The Data "
                          "Analyst can start it (docs/handoff/round7/updater.md).",
    "updates.neverRan": "The updater has not run on this computer yet. The one-time setup is in "
                        "docs/handoff/round7/updater.md.",
    "updates.settingsProblem": "The updater cannot start because its settings (updater/settings.json) need a look. "
                               "The Data Analyst finds the reason in the updater's log (updater/logs).",
    "updates.lastUpdate": "Last update",
    "updates.last.done": "The update was installed and everything is running well.",
    "updates.last.tests_failed": "The update was not installed: the new version did not pass its tests. Nothing was "
                                 "changed.",
    "updates.last.refused": "The update was not installed, and nothing was changed.",
    "updates.last.rolled_back": "The update did not start correctly, so the previous version was put back by itself. "
                                "Nothing was lost.",
    "updates.last.needs_person": "The update needs a person to look at it. Please tell the Data Analyst; the "
                                 "updater's log names every step.",
    "updates.reason.list_changed": "New changes arrived after the list was shown. Please look at the list again.",
    "updates.reason.not_healthy": "The mission system was not fully running before the update, so the update waited.",
    "updates.reason.rollback_point_failed": "The way back (database backup and copies) could not be saved, so the "
                                            "update did not start.",
    "updates.reason.stopped": "The update stopped before anything was changed. The updater's log says why.",
    "updates.reason.interrupted": "The computer or the updater stopped in the middle of the update.",
    "updates.logFile": "The updater's log on this computer:",
    "updates.backupFolder": "The way back is kept in:",
    "updates.typeWrong": "Please type UPDATE to confirm.",
    "updates.alreadyAsked": "The updater is already working on a request. Please wait a moment.",
    "updates.cannotNow": "An update cannot be installed right now. Please check for updates again.",
    "updates.managersOnly": "Updates are for the AP, the President and the Data Analyst. Please open DA Management "
                            "from your portal account.",
}


# Small pieces of HTML --------------------------------------------------------------------------------------------
def say(key, tag="span", extra=""):
    """A text of the page, marked for the portal's translation (i18n.js looks at data-i18n)."""
    return f'<{tag} data-i18n="{key}"{extra}>{escape(TEXT[key])}</{tag}>'


def data(value, tag="span", extra=""):
    """Mission data (a version, a date, a commit title): shown as it is and never translated."""
    return f"<{tag} data-i18n-ignore{extra}>{escape(str(value or ''))}</{tag}>"


def when(iso):
    """'2026-09-29T14:05:00+02:00' -> '29 Sep 2026, 14:05' (in the updater's own time zone). Empty if unreadable."""
    moment = parse_time(iso)
    return moment.strftime("%d %b %Y, %H:%M") if moment else ""


def parse_time(iso):
    try:
        return datetime.fromisoformat(str(iso))
    except (TypeError, ValueError):
        return None


# The two folders ------------------------------------------------------------------------------------------------
def request_file():
    return UPDATES_DIR / "requests" / "request.json"


def read_status():
    """The updater's status file, or {} when there is none yet (or it cannot be read)."""
    try:
        status = json.loads((UPDATES_DIR / "status" / "status.json").read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {}
    return status if isinstance(status, dict) else {}


def request_waiting():
    return request_file().exists()


def write_request(fields):
    """Leaves one request for the updater. Written to a temporary file first, so the updater never reads half."""
    folder = request_file().parent
    folder.mkdir(parents=True, exist_ok=True)
    temporary = folder / f".request-{uuid.uuid4().hex}.tmp"
    temporary.write_text(json.dumps(fields), encoding="utf-8")
    os.replace(temporary, request_file())


def asked_by():
    """Who asks, for the updater's log: the portal role and the portal user id (no name, no email)."""
    return {"role": session.get("portal_role"), "user_id": str(session.get("portal_user_id") or "")}


def updater_running(status):
    """Whether the updater wrote into its status file recently enough (longer while it is busy)."""
    if status.get("settings_problem"):
        return False  # it wrote only to say that it stops at start-up (Task Scheduler tries again every 5 minutes)
    seen = parse_time(status.get("updater_seen_at"))
    if not seen or not seen.tzinfo:
        return False
    limit = BUSY_MINUTES if status.get("state") in BUSY_STATES else QUIET_MINUTES
    return (datetime.now(timezone.utc) - seen).total_seconds() < limit * 60


def may_use():
    """Managers signed in through the portal, checked against the database on every request (sign_in.allowed)."""
    return sign_in.allowed() and session.get("portal_role") in roles.MANAGER_ROLES


# The page -------------------------------------------------------------------------------------------------------
def page_html(status):
    """The Updates page from the updater's status."""
    parts = [overview_card(status)]
    changes = status.get("new_changes") or []
    if changes and status.get("check_result") in ("updates", "diverged"):
        parts.append(changes_card(status, changes))
    if status.get("can_update") and updater_running(status) and not busy(status):
        parts.append(install_card(status))
    if isinstance(status.get("last_update"), dict):
        parts.append(last_update_card(status["last_update"]))
    # Look again only while the updater is there to answer; otherwise the page would reload every 5 s for nothing.
    if updater_running(status) and (busy(status) or request_waiting()):
        parts.append(LOOK_AGAIN)
    return "".join(parts)


# While the updater works, the page looks again every 5 seconds. DA Management itself restarts during an update,
# so it first asks quietly whether the page answers, and only then reloads (a plain reload would end on an error
# page while DA Management is starting and stop looking).
LOOK_AGAIN = """<script>(function(){function again(){fetch(location.href,{cache:"no-store"}).then(function(r){
if(r.ok){location.reload()}else{setTimeout(again,5000)}}).catch(function(){setTimeout(again,5000)})}
setTimeout(again,5000)})()</script>"""


def busy(status):
    return status.get("state") in BUSY_STATES


def overview_card(status):
    """This computer's version, where updates come from, the last check, and "Check for updates"."""
    current = status.get("current") or {}
    version = (data(current.get("short"), "b") + " " + data(when(current.get("date")), extra=' class="muted"')
               + "<br>" + data(current.get("subject"), extra=' class="muted"')) if current else data("-", "b")
    checked = data(when(status.get("checked_at")), "b") if status.get("checked_at") else say("updates.neverChecked", "b")
    return f"""<div class="card">{say('updates.title', 'h2')}{say('updates.intro', 'p', ' class="muted"')}{notice_html(status)}
      <div class="grid"><div class="metric">{say('updates.thisComputer')}<br>{version}</div>
      <div class="metric">{say('updates.comesFrom')}<br>{data(status.get('follows') or '-', 'b')}</div>
      <div class="metric">{say('updates.lastChecked')}<br>{checked}</div></div>
      <form method="post" action="/updates/check" class="actions" style="margin-top:14px">
      <button class="secondary" data-i18n="updates.check">{escape(TEXT['updates.check'])}</button></form></div>"""


def notice_html(status):
    """One line on what is happening now, or on the result of the last check."""
    if not status:
        return say("updates.neverRan", "p", ' class="warn"')
    running = updater_running(status)
    lines = []
    if status.get("settings_problem"):
        lines.append(say("updates.settingsProblem", "p", ' class="warn"'))
    elif not running:
        lines.append(say("updates.notRunning", "p", ' class="warn"'))
    # "Working on it" only while the updater runs; a stopped one would leave "Looking on GitHub…" on the page for ever.
    if running and busy(status):
        lines.append(say(f"updates.state.{status['state']}", "p", ' class="status"'))
    elif running and request_waiting():
        lines.append(say("updates.asked", "p", ' class="status"'))
    else:
        lines.append(check_result_html(status))
    return "".join(lines)


def check_result_html(status):
    """The result of the last check, or why an update cannot happen now."""
    result = status.get("check_result") or ""
    blocked = status.get("blocked") or ""
    if blocked in BLOCKED:
        return say(f"updates.blocked.{blocked}", "p", ' class="warn"')
    if f"updates.result.{result}" in TEXT:
        tone = "good" if result == "up_to_date" else ("status" if result == "updates" else "warn")
        return say(f"updates.result.{result}", "p", f' class="{tone}"')
    if status.get("checked_at"):
        return say("updates.result.stale", "p", ' class="muted"')
    return ""


def changes_card(status, changes):
    """The card "What is new": the changes of the new version."""
    rows = "".join(
        f"<tr><td>{data(when(c.get('date')))}</td><td>{data(c.get('subject'))}</td><td>{data(c.get('short'), 'code')}</td></tr>"
        for c in changes if isinstance(c, dict))
    extra = ""
    if status.get("migrations"):
        extra += f"<p>{say('updates.migrations')} {data(', '.join(Path(m).name for m in status['migrations']))}</p>"
    if status.get("other_parts"):
        extra += f"<p class='warn'>{say('updates.otherParts')} {data(', '.join(status['other_parts']))}</p>"
    return f"""<div class="card">{say('updates.newChanges', 'h3')}<div class="scroll"><table><thead><tr>
      <th>{say('updates.changeDate')}</th><th>{say('updates.changeText')}</th><th>{say('updates.version')}</th>
      </tr></thead><tbody>{rows}</tbody></table></div>{extra}</div>"""


def install_card(status):
    target = (status.get("remote") or {}).get("commit") or ""
    return f"""<div class="card">{say('updates.install', 'h3')}{say('updates.installHelp', 'p', ' class="muted"')}
      <form method="post" action="/updates/install"><input type="hidden" name="target" value="{escape(target)}">
      <label class="form-field">{say('updates.typeToConfirm')}<input name="confirm" autocomplete="off" required
      style="max-width:220px"></label><button data-i18n="updates.updateNow">{escape(TEXT['updates.updateNow'])}</button></form></div>"""


def last_update_card(last):
    """The result of the last update."""
    result = last.get("result") or ""
    lines = [say(f"updates.last.{result}", "p", ' class="status"')] if f"updates.last.{result}" in TEXT else []
    reason = last.get("reason") or ""
    if reason in BLOCKED:
        lines.append(say(f"updates.blocked.{reason}", "p"))
    elif f"updates.reason.{reason}" in TEXT:
        lines.append(say(f"updates.reason.{reason}", "p"))
    elif f"updates.result.{reason}" in TEXT:
        lines.append(say(f"updates.result.{reason}", "p"))
    versions = " → ".join(v[:7] for v in (last.get("from"), last.get("to")) if v)
    lines.append(f"<p class='muted'>{data(when(last.get('finished_at')))} {data(versions, 'code') if versions else ''}</p>")
    if last.get("rollback_folder"):
        lines.append(f"<p class='muted'>{say('updates.backupFolder')} {data(last['rollback_folder'], 'code', WRAP)}</p>")
    if last.get("log"):
        lines.append(f"<p class='muted'>{say('updates.logFile')} {data(last['log'], 'code', WRAP)}</p>")
    return f"<div class='card'>{say('updates.lastUpdate', 'h3')}{''.join(lines)}</div>"


# Routes ---------------------------------------------------------------------------------------------------------
def refused():
    """Not a manager signed in through the portal: portal users are sent to sign in, the password sign-in is told."""
    if not sign_in.allowed():
        return redirect("/login")
    return page.render(f"<div class='error'>{say('updates.managersOnly')}</div>", 403)


@pages.route("/updates")
def updates_home():
    if not may_use():
        return refused()
    return page.render(page_html(read_status()))


@pages.route("/updates/check", methods=["POST"])
def updates_check():
    """The button "Check for updates": leaves a check request for the updater."""
    if not may_use():
        return refused()
    if request_waiting():
        # The request already waits; say whether the updater is at it or not running.
        flash(TEXT["updates.alreadyAsked"] if updater_running(read_status()) else TEXT["updates.notRunning"])
    else:
        write_request({"action": "check", **asked_by()})
    return redirect("/updates")


@pages.route("/updates/install", methods=["POST"])
def updates_install():
    """The button "Update now": leaves an update request for the version that was shown."""
    if not may_use():
        return refused()
    problem = install_problem(read_status(), request.form.get("target", ""), request.form.get("confirm", ""))
    if problem:
        flash(TEXT[problem])
    else:
        write_request({"action": "update", "target": request.form["target"], "confirmed": True, **asked_by()})
    return redirect("/updates")


def install_problem(status, target, confirm):
    """The text key of why "Update now" cannot be asked for now, or None when it can."""
    if confirm.strip().upper() != CONFIRM_WORD:
        return "updates.typeWrong"
    if not updater_running(status):
        return "updates.notRunning"
    if request_waiting() or busy(status):
        return "updates.alreadyAsked"
    if not status.get("can_update"):
        return "updates.cannotNow"
    if not VERSION.match(target or "") or target != (status.get("remote") or {}).get("commit"):
        return "updates.reason.list_changed"
    return None
