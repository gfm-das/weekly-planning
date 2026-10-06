"""The Roster Import pages (the first page of DA Management): upload a transfer roster, check the preview, apply it.

  /         the upload form
  /preview  reads the roster (roster_file.py), shows what would change (transfer.preview), and keeps the file
  /apply    applies the checked roster (transfer.apply_roster_batch) after the "I reviewed" tick

The roster file waits in UPLOAD_DIR between /preview and /apply; the session remembers which one.
"""
import secrets
from datetime import date, timedelta
from pathlib import Path

from flask import Blueprint, flash, redirect, request, session

import page
import roster_file
import settings
import sign_in
import transfer
from page import h

pages = Blueprint("transfer_pages", __name__)

PENDING_KEYS = ("pending_file", "pending_mission_id", "pending_transfer_date", "pending_filename")


@pages.route("/")
def index():
    """Step 1: the upload form."""
    if not sign_in.allowed():
        return sign_in.go_to_login()
    return page.render(f"""
    <div class="card">
      <div class="step">1 · Upload roster</div><h2>Prepare a transfer import</h2>
      <p class="muted">Upload the complete current roster. You will review every change before applying it.</p>
      <form action="/preview" method="post" enctype="multipart/form-data">
        <input type="hidden" name="mission_id" value="{sign_in.current_mission_id()}">
        <p><label>Transfer effective date<br><input type="date" name="transfer_date" value="{date.today().isoformat()}" required></label></p>
        <p><label>Roster CSV/XLSX<br><input type="file" name="file" accept=".csv,.xlsx" required></label></p>
        <button>Preview changes</button>
      </form>
    </div>
    <div class="card"><h3>What this import updates</h3>
      <ul>
        <li>Current assignments and email addresses are updated without duplicating missionaries.</li>
        <li>Moves retain the previous assignment in history.</li>
        <li>Areas are linked to the wards and branches named in the roster.</li>
        <li>DL, ZL, STL, and AP leadership is updated from roster positions. An account whose saved role is a leadership role the roster no longer gives goes back to Missionary. DA, President, and Office access stays manually assigned.</li>
        <li>Missionaries missing from this complete roster are marked released. Review this carefully.</li>
      </ul>
    </div>""")


@pages.route("/preview", methods=["POST"])
def preview_page():
    """Step 2: reads the roster, keeps it waiting, and shows what applying it would change."""
    if not sign_in.allowed():
        return sign_in.go_to_login()
    try:
        mission_id = int(request.form["mission_id"])
        if mission_id != sign_in.current_mission_id():
            raise ValueError("The selected mission is outside your management scope.")
        transfer_date = date.fromisoformat(request.form["transfer_date"])
        upload = request.files["file"]
        path = keep_upload(upload)
        rows = roster_file.read_roster(path)
        changes = transfer.preview(rows, mission_id, transfer_date)
        session["pending_file"] = str(path)
        session["pending_mission_id"] = mission_id
        session["pending_transfer_date"] = transfer_date.isoformat()
        session["pending_filename"] = Path(upload.filename or "roster.csv").name
        loss = transfer.own_access_loss(rows, transfer_date, session.get("portal_user_id"))
        return page.render(preview_html(changes, transfer_date, loss))
    except Exception as e:
        return page.render(f"<div class='error'><b>Import blocked.</b>\n{h(e)}</div><p><a href='/'>Back</a></p>", 400)


def keep_upload(upload):
    """Saves the uploaded roster under a random name in UPLOAD_DIR, until it is applied."""
    suffix = Path(upload.filename or "roster.csv").suffix.lower() or ".csv"
    path = settings.UPLOAD_DIR / f"{secrets.token_urlsafe(16)}{suffix}"
    upload.save(path)
    return path


def bullet_list(lines):
    return "<ul>" + "".join(f"<li>{h(x)}</li>" for x in lines) + "</ul>" if lines else "<p class='muted'>None</p>"


def preview_html(p, transfer_date, loss):
    """The preview page: the numbers, every list of changes, and the Apply form."""
    notes = "".join(f"<p class='warn'>{h(n)}</p>" for n in p.get("notes", []))
    reset_note, record_note = role_notes(transfer_date)
    own_now = loss is not None and loss <= date.today()
    own_box = ("<p><label><input type='checkbox' name='own_access' value='yes' required> I understand that applying this "
               "ends my own DA Management access now and that I cannot undo it myself.</label></p>" if own_now else "")
    return f"""
        <div class="card"><div class="step">2 · Review changes</div><h2>Preview — {h(p['mission_name'])}</h2>{notes}
        <div class="grid">
          <div class="metric"><b>{p['count']}</b><br>active roster rows</div>
          <div class="metric"><b>{len(p['new_missionaries'])}</b><br>new missionaries</div>
          <div class="metric"><b>{len(p['moves'])}</b><br>area moves</div>
          <div class="metric"><b>{len(p['unit_add'])}</b><br>area-unit links added</div>
          <div class="metric"><b>{len(p['unit_remove'])}</b><br>area-unit links removed</div>
          <div class="metric"><b>{len(p['email_updates'])}</b><br>email updates</div>
        </div></div>
        <div class="card"><h3>Organization</h3><b>Zones</b>{bullet_list(p['new_zones'])}<b>Districts</b>{bullet_list(p['new_districts'])}<b>Areas</b>{bullet_list(p['new_areas'])}</div>
        <div class="card"><h3>Units from roster</h3><b>Add / reactivate</b>{bullet_list(p['unit_add'])}<b>Deactivate old area links</b>{bullet_list(p['unit_remove'])}</div>
        <div class="card"><h3>Missionaries</h3><b>New</b>{bullet_list(p['new_missionaries'])}<b>Moves</b>{bullet_list(p['moves'])}<b>Email updates</b>{bullet_list(p['email_updates'])}<b>Leaving roster</b>{bullet_list(p['finished'])}</div>
        <div class="card"><h3>Roster-managed permission changes</h3><b>Add</b>{bullet_list(p['leadership_add'])}<b>End</b>{bullet_list(p['leadership_end'])}<b>Account role goes back to Missionary</b><p class="muted">{h(reset_note)}</p>{bullet_list(p['role_resets'])}<b>Account role to record by hand</b><p class="muted">{h(record_note)}</p>{bullet_list(p['role_records'])}</div>
        {own_access_card(loss)}<div class="card"><form action="/apply" method="post"><p><label><input type="checkbox" name="confirmed" value="yes" required> I reviewed these transfer changes.</label></p>{own_box}<button>Apply transfer</button> <a href="/">Cancel</a></form></div>
        """


def role_notes(transfer_date):
    """The two explanations about saved account roles. Account roles change when the transfer is applied, not on its
    date; they say so when the date is still ahead."""
    later = transfer_date > date.today()
    on, last = transfer_date.strftime("%d %b %Y"), (transfer_date - timedelta(days=1)).strftime("%d %b %Y")
    reset_note = ("These accounts still have a DL, ZL, STL or AP role saved that this roster no longer gives them. "
                  + (f"The saved role changes as soon as you apply, not on {on}. Their assignment itself runs until {last}, "
                     f"and a former AP keeps DA Management access until {last}."
                     if later else "A former AP loses DA Management access."))
    record_note = ("The roster gives these accounts a new AP, ZL or STL role but does not change the saved account role. "
                   "Access already follows the new assignment. To keep the saved role in step, "
                   + (f"from {on} open" if later else "after applying open")
                   + " each one in Account Manager and save it without changes: the Role list already shows the new role.")
    return reset_note, record_note


def own_access_card(loss):
    """A roster that drops the signed-in AP ends their own access. Say so; when it ends at once, the Apply form asks
    for an extra tick, because they could not open Import history to undo it afterwards."""
    if loss is None:
        return ""
    if loss <= date.today():
        return ("<div class='error'><b>This transfer ends your own DA Management access as soon as you apply it.</b> The roster does not "
                "list you as AP, and your access comes only from your AP assignment. After applying you are signed out of DA "
                "Management and cannot undo this transfer yourself; only a President or Data Analyst could. Ask one of them to apply "
                "it, or tick the extra box below.</div>")
    return (f"<div class='flash'><b>This transfer ends your own DA Management access on {h(loss.strftime('%d %b %Y'))}.</b> "
            "The roster does not list you as AP. Until that date you can still undo it from Import history.</div>")


@pages.route("/apply", methods=["POST"])
def apply_page():
    """Step 3: applies the waiting roster, after the "I reviewed" tick."""
    if not sign_in.allowed():
        return sign_in.go_to_login()
    path = session.get("pending_file")
    mission_id = session.get("pending_mission_id")
    transfer_date = session.get("pending_transfer_date")
    if not path or not mission_id or not transfer_date:
        flash("No pending import.")
        return redirect("/")
    try:
        if request.form.get("confirmed") != "yes":
            raise ValueError("Review and confirm the transfer preview first.")
        rows = roster_file.read_roster(path)
        # Checked again here: the preview may be old.
        loss = transfer.own_access_loss(rows, date.fromisoformat(transfer_date), session.get("portal_user_id"))
        own_now = loss is not None and loss <= date.today()
        if own_now and request.form.get("own_access") != "yes":
            raise ValueError("This transfer ends your own DA Management access now. Open the preview again and tick the box "
                             "that confirms this, or ask a President or Data Analyst to apply it.")
        batch = transfer.apply_roster_batch(rows, int(mission_id), date.fromisoformat(transfer_date),
                                            session.get("pending_filename") or Path(path).name)
        Path(path).unlink(missing_ok=True)
        for key in PENDING_KEYS:
            session.pop(key, None)
        own = "<p class='warn'>Your own DA Management access ended with this transfer, so the links below no longer open for you.</p>" if own_now else ""
        return page.render(f"""<div class="card"><h2 class="good">Transfer applied successfully</h2><p>Roster, emails, units, assignments, and roster-managed permissions are updated.</p>{own}<p><a href="/accounts">Open Account Manager</a> · <a href="/imports/{batch}">View import batch</a> · <a href="/">Import another roster</a></p></div>""")
    except Exception as e:
        return page.render(f"<div class='error'><b>Nothing was committed.</b>\n{h(e)}</div><p><a href='/'>Back</a></p>", 500)
