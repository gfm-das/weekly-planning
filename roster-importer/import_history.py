"""Import history: every applied import and every saved account change of the mission, with Undo.

Pages:
  /imports                  the latest 100 batches (times in the mission's time zone)
  /imports/<id>             one batch: its numbers, the tables it changed, and the Undo form (type UNDO)
  /imports/<id>/undo        Undo (undo.py). An undo that ends your own DA Management access asks for an extra tick
                            and then signs you out.

What a batch is: batches.py.
"""
from flask import Blueprint, flash, redirect, request, session

import account_changes
import data_uploads
import database
import page
import roles
import settings
import sign_in
import undo
from page import h, mission_time

pages = Blueprint("import_history", __name__)


def kind_label(kind):
    """How Import history names a kind of batch (the data uploads have their own names)."""
    return h(data_uploads.kind_label(kind)) if kind in data_uploads.KIND_LABELS else kind.title()


@pages.route("/imports")
def imports():
    """The latest 100 batches of the mission."""
    if not sign_in.allowed():
        return sign_in.go_to_login()
    with database.connect() as conn:
        with database.cursor(conn) as cur:
            cur.execute("select * from public.roster_import_batches where mission_id=%s order by created_at desc limit 100",
                        (sign_in.current_mission_id(),))
            listed = cur.fetchall()
    rows = "".join(f"<tr><td><a href='/imports/{b['id']}'>{h(b['filename'])}</a></td><td>{kind_label(b['kind'])}</td><td>{mission_time(b['created_at'])}</td><td>{h(b['actor'])}</td><td><span class='badge'>{b['status'].title()}</span></td></tr>" for b in listed)
    return page.render(f"<div class='card'><h2>Import history</h2><p class='muted'>Every applied transfer and historical import records its changed rows, and so does every saved account change (Staff accounts, and roles, status, area or leadership on a missionary's account page), with who made it. Undo is available only while those rows remain unchanged.</p><div class='scroll'><table><thead><tr><th>File</th><th>Type</th><th>Imported ({settings.TIME_ZONE_NAME})</th><th>By</th><th>Status</th></tr></thead><tbody>{rows or '<tr><td colspan=5>No import batches yet.</td></tr>'}</tbody></table></div></div>")


@pages.route("/imports/<uuid:batch_id>")
def import_detail(batch_id):
    """One batch: its numbers, the tables it changed, and Undo."""
    if not sign_in.allowed():
        return sign_in.go_to_login()
    with database.connect() as conn:
        with database.cursor(conn) as cur:
            cur.execute("select * from public.roster_import_batches where id=%s and mission_id=%s", (str(batch_id), sign_in.current_mission_id()))
            batch = cur.fetchone()
            if not batch:
                return page.render("<div class='error'>Import not found.</div>", 404)
            cur.execute("select table_name,count(*) changes from public.roster_import_changes where batch_id=%s group by table_name order by table_name", (str(batch_id),))
            changes = cur.fetchall()
            # Undo is offered only to someone who may make the change.
            refused = account_changes.undo_refusal(cur, batch_id) if batch["kind"] == "ACCOUNT" and batch["status"] == "APPLIED" else None
    metrics = "".join(f"<div class='metric'><b>{h(v)}</b><br>{h(k.replace('_',' '))}</div>" for k, v in batch["summary"].items())
    rows = "".join(f"<tr><td>{h(r['table_name'])}</td><td>{r['changes']}</td></tr>" for r in changes)
    return page.render(f"<div class='card'><h2>{h(batch['filename'])}</h2><p>{kind_label(batch['kind'])} · {batch['status'].title()} · {h(batch['actor'])}</p><div class='grid'>{metrics}</div></div><div class='card'><h3>Changed rows</h3><table><thead><tr><th>Data</th><th>Rows</th></tr></thead><tbody>{rows}</tbody></table></div>{undo_card(batch, batch_id, refused)}<p><a href='/imports'>Back to import history</a></p>")


def undo_card(batch, batch_id, refused):
    """The Undo form; or why this manager may not undo it; or that it is undone already."""
    if batch["status"] == "APPLIED" and not refused:
        return f"""<div class="card"><h3>Undo this import</h3><p class="muted">If any affected row was edited afterward or gained new dependent data, undo is blocked and no data is changed.</p><form action="/imports/{batch_id}/undo" method="post"><label>Type UNDO <input name="confirmation" pattern="UNDO" required></label> <button class="danger">Undo batch</button></form></div>"""
    if refused:
        return f"<div class='card'><h3>Undo this change</h3><p class='warn'>{h(refused)}</p></div>"
    return "<div class='card good'>This import has been undone.</div>"


@pages.route("/imports/<uuid:batch_id>/undo", methods=["POST"])
def import_undo(batch_id):
    """Undo, after typing UNDO (and the "I understand" tick when it ends your own access)."""
    if not sign_in.allowed():
        return sign_in.go_to_login()
    try:
        if request.form.get("confirmation") != "UNDO":
            raise ValueError("Type UNDO to confirm.")
        if undo.undo_batch(str(batch_id), own_access=request.form.get("own_access") == "yes"):
            session.clear()  # the next request would find no management access anyway
            return page.render("<div class='card'><h2 class='good'>Undone</h2><p>Your own DA Management access has ended, so you are "
                               f"signed out of DA Management. Ask {roles.WHO_GIVES_ACCESS} if you need it again.</p></div>")
        flash("Import batch undone.")
        return redirect(f"/imports/{batch_id}")
    except undo.OwnAccessError as e:
        return page.render(f"""<div class='error'>{h(e)}</div><div class="card staff"><form action="/imports/{batch_id}/undo" method="post">
              <input type="hidden" name="confirmation" value="UNDO"><label class="check"><input type="checkbox" name="own_access" value="yes" required>
              <span><b>I understand</b> Undoing this ends my own DA Management access. I cannot give it back to myself.</span></label>
              <button class="danger">Undo batch</button></form></div><p><a href='/imports/{batch_id}'>Back to import</a></p>""", 409)
    except PermissionError as e:
        return page.render(f"<div class='error'>{h(e)}</div><p><a href='/imports/{batch_id}'>Back to import</a></p>", 403)
    except Exception as e:
        return page.render(f"<div class='error'>{h(e)}</div><p><a href='/imports/{batch_id}'>Back to import</a></p>", 409)
