"""Area mappings: which current area each old area name ("label") of the Historical CSV stands for.

Areas get new names over the years; the old Weekly Planning export still uses the old ones. Here a manager maps
each old label to a current area once, and every later upload reuses the confirmed mapping. The labels themselves
are never changed.

Pages:
  /mappings           every remembered label (and the new labels of the upload waiting in Historical CSV)
  /mappings/save      saves new or changed mappings; optionally closes the old area ("Close old area")
  /mappings/separate  takes a label's numbers out of the reports they were added to (historical_separate.py)

What a mapping means (round 19), stored in match_status:
  CONFIRMED  this label IS that current area (one to one). Two labels' numbers are never added together.
  CLOSED     the label's area no longer exists. Its rows are kept under the area of the same name (an active one is
             closed on save, a closed one stays closed); without such an area they stay in the import tables only.
  COMBINED   "Combined companionship": one companionship served this area and the chosen one, so its numbers ARE added
             to the chosen area's report. The only way numbers are added; Separate takes them out again.

"Close old area" is optional and never ticked for you. It turns off the active area whose name equals the label, or
the label without its zone prefix ('Frankfurt-Darmstadt S' -> 'Darmstadt S'). The mapped target area is never turned
off, and turning an area off is not part of Import history's Undo.
"""
from functools import lru_cache
from pathlib import Path

from flask import Blueprint, flash, redirect, request, session

import batches
import database
import historical_import as historical
import historical_separate
import page
import places
import places_admin
import sign_in
from page import h

pages = Blueprint("mappings_page", __name__)

# Every row has its own "Current area" list. Written out in full, these lists made the page almost 1 MB (round 9), so
# a row's list first holds only its chosen area; the whole list is on the page once (<template id="areaOptions">) and
# the script puts it into a row's list the first time that list is clicked or reached with the Tab key.
# The search box shows the rows whose old label or chosen current area contains what you type.
PAGE_SCRIPT = """<script>(()=>{const all=document.getElementById('areaOptions'),table=document.getElementById('mappingTable');
const fill=s=>{if(s.tagName!=='SELECT'||!s.dataset.short)return;const v=s.value;[...s.options].forEach(o=>{if(o.value)o.remove()});s.append(all.content.cloneNode(true));s.value=v;delete s.dataset.short};
['pointerdown','focusin'].forEach(n=>table.addEventListener(n,e=>fill(e.target),true));
document.getElementById('mappingSearch').addEventListener('input',e=>{const q=e.target.value.trim().toLowerCase();document.querySelectorAll('[data-mapping-row]').forEach(row=>{const s=row.querySelector('select');row.hidden=q&&!(row.cells[0].innerText+' '+s.options[s.selectedIndex].text).toLowerCase().includes(q)})})})()</script>"""


def mission_areas(cur):
    """(every area of this mission, active or closed, with its zone name, every zone name), for "Close old area",
    "Closed area" and Separate."""
    cur.execute("""select a.id,a.name,a.active,z.name zone from public.areas a join public.districts d on d.id=a.district_id
      join public.zones z on z.id=d.zone_id where z.mission_id=%s order by a.id""", (sign_in.current_mission_id(),))
    areas = cur.fetchall()
    cur.execute("select name from public.zones where mission_id=%s", (sign_in.current_mission_id(),))
    return areas, [r["name"] for r in cur.fetchall()]


@lru_cache(maxsize=4096)
def fold(name):
    """A name for comparing: extra spaces removed, small letters. Remembered, because the page compares every label
    with every active area and zone name (thousands of times for the same few names)."""
    return historical.clean(name).casefold()


def old_area_match(label, areas, zone_names):
    """The old area a label refers to. Returns (area, None) or (None, why not).

    Rule: an area of this mission whose name equals the label, or equals the label with a leading zone name plus '-'
    or space removed ('Frankfurt-Darmstadt S' -> 'Darmstadt S'). Active areas come before closed ones (an area without
    "active" counts as active). When several match, the one inside the named zone is preferred; otherwise nothing is
    chosen."""
    folded = fold(label)
    names = {folded: None}  # {area name to look for: the zone named in front of it}
    for zone in zone_names:
        zone_folded = fold(zone)
        for sep in (" - ", "-", " "):
            prefix = zone_folded + sep
            if zone_folded and folded.startswith(prefix) and historical.clean(folded[len(prefix):]):
                names.setdefault(historical.clean(folded[len(prefix):]), zone_folded)
    matches = [a for a in areas if fold(a["name"]) in names]
    matches = [a for a in matches if a.get("active", True)] or matches
    if len(matches) > 1:
        preferred = [a for a in matches if names[fold(a["name"])] == fold(a["zone"])]
        if len(preferred) == 1:
            return preferred[0], None
        return None, "several active areas match this label"
    if not matches:
        return None, "no active area matches this label"
    return matches[0], None


# ------------------------------------------------------------------------------------------ the page

@pages.route("/mappings")
def mappings():
    """Every remembered label, and the new labels of the waiting upload."""
    if not sign_in.allowed():
        return sign_in.go_to_login()
    with database.connect() as conn:
        with database.cursor(conn) as cur:
            areas = places.current_areas(cur)
            all_areas, zone_names = mission_areas(cur)
            summed = historical_separate.summed_labels(cur)
            cur.execute("""select m.*,a.name current_target_name from public.import_weekly_planning_area_map m
              left join public.areas a on a.id=m.target_area_id
              where m.mission_id=%s or m.mission_id is null order by m.source_companionship""", (sign_in.current_mission_id(),))
            saved = cur.fetchall()
    waiting = new_labels_of_waiting_upload(saved)
    saved += waiting or []
    current_ids = {a["id"] for a in areas}
    rows = "".join(mapping_row(r, areas, current_ids, all_areas, zone_names, summed) for r in saved)
    # Back to the Historical CSV check, only when an upload is waiting there.
    back = ' <a href="/historical/review">Return to pending import</a>' if waiting is not None else ""
    every_area = "".join(area_option(a) for a in areas)
    return page.render(f"""<div class="card"><h2>Remembered area mappings</h2><p class="muted">Map historical labels to areas in the newest accepted roster. Historical labels remain unchanged, and future uploads reuse confirmed mappings. Only new or changed rows are saved.</p><p class="muted">Each old label stands for one area, and its numbers are never added to another label's. Choose Closed area for an area that no longer exists. Only a Combined companionship (one companionship serving two areas) adds numbers together, and Separate takes them apart again.</p><p class="muted"><b>Close old area</b> is optional and never preselected. It deactivates the active area whose name equals the label, or the label without its zone prefix (for example <i>Frankfurt-Darmstadt S</i> &rarr; <i>Darmstadt S</i>). The mapped target area is never deactivated, and area deactivation is not part of import undo.</p><label class="form-field">Search mappings<input id="mappingSearch" type="search" placeholder="Old or current area name"></label><form action="/mappings/save" method="post"><div class="scroll"><table id="mappingTable"><thead><tr><th>Original label</th><th>Current area</th><th>Notes</th><th>Close old area (optional)</th><th>Status</th></tr></thead><tbody>{rows}</tbody></table></div><p><button>Save confirmed mappings</button>{back}</p></form></div><div class="card"><h3>Add an old area name</h3><form action="/mappings/save" method="post"><div class="split"><label class="form-field">Original label<input name="source" required></label><label class="form-field">Current area<select name="target" required>{area_options(areas, None)}</select></label></div><input type="hidden" name="notes" value=""><button>Remember mapping</button></form></div><template id="areaOptions">{closed_option(False)}{every_area}</template>{PAGE_SCRIPT}""")


def new_labels_of_waiting_upload(saved):
    """The labels of the upload waiting in Historical CSV that have no mapping yet (each once). None when no upload is
    waiting."""
    pending = session.get("historical_file")
    if not pending or not Path(pending).is_file():
        return None
    existing = {historical.clean(r["source_companionship"]).casefold() for r in saved}
    new = []
    for row in historical.read_csv_rows(pending):
        source = historical.clean(row[historical.COMPANIONSHIP_COLUMN])
        if source.casefold() not in existing:
            new.append({"source_companionship": source, "target_area_id": None, "notes": "", "confirmed_at": None})
            existing.add(source.casefold())
    return new


def area_option(a, selected=None):
    return f'<option value="{a["id"]}" {"selected" if a["id"] == selected else ""}>{h(a["zone"])} / {h(a["name"])}</option>'


def closed_option(selected):
    return f'<option value="closed"{" selected" if selected else ""}>Closed area (keep its history under the closed area)</option>'


def area_options(areas, selected):
    """The whole "Current area" list."""
    return '<option value="">Choose current area</option>' + "".join(area_option(a, selected) for a in areas)


def mapping_row(r, areas, current_ids, all_areas, zone_names, summed=None):
    """One remembered label. Its list holds only the chosen area (and "Closed area") until it is used (see PAGE_SCRIPT)."""
    label, kind = r["source_companionship"], r.get("match_status")
    chosen = [] if kind == "CLOSED" else [a for a in areas if a["id"] == r.get("target_area_id")]
    options = area_options(chosen, r.get("target_area_id")).replace("</option>", "</option>" + closed_option(kind == "CLOSED"), 1)
    combined = f"""<label class="muted"><input type="checkbox" name="combined" value="{h(label)}" {'checked' if kind == 'COMBINED' else ''}> Combined companionship (one companionship served both areas: its numbers are added to this area and can be separated later)</label>"""
    return f"""<tr data-mapping-row><td>{h(label)}<input type="hidden" name="source" value="{h(label)}"></td><td><select name="target" data-short="1">{options}</select><br>{combined}</td><td><input name="notes" value="{h(r.get('notes'))}" placeholder="Rename / merge notes"></td><td>{close_cell(r, all_areas, zone_names)}</td><td>{status_cell(r, current_ids, (summed or {}).get(fold(label)))}</td></tr>"""


def close_cell(r, all_areas, zone_names):
    area, reason = old_area_match(r["source_companionship"], all_areas, zone_names)
    if not area:
        return f"<span class='muted'>Nothing to close ({h(reason)}). If the area no longer exists, choose Closed area in the list.</span>"
    if not area.get("active", True):
        return f"<span class='muted'>Already closed: <b>{h(area['zone'])} / {h(area['name'])}</b></span>"
    note = " <span class='muted'>(currently the target: choose another area first)</span>" if area["id"] == r.get("target_area_id") else ""
    return f"""<label><input type="checkbox" name="deactivate" value="{h(r['source_companionship'])}"> Deactivate old area <b>{h(area['zone'])} / {h(area['name'])}</b> on save</label>{note}"""


def status_cell(r, current_ids, summed=None):
    """Confirmed / Review / Closed / Combined companionship, a stale target, and Separate when the label's numbers were
    added to another label's (a Combined companionship, or an import from before round 19)."""
    separate = (f"""<br><span class="warn">Added together with another area in {summed} report(s)</span> <button class="secondary" formaction="/mappings/separate" formnovalidate name="separate" value="{h(r['source_companionship'])}">Separate</button>""" if summed else "")
    if r.get("match_status") == "CLOSED":
        return ("Closed" if r.get("target_area_id") else "Closed (no area record: its rows stay in the import tables)") + separate
    if r.get("match_status") == "COMBINED":
        return "Combined companionship" + separate
    if r.get("target_area_id") and r["target_area_id"] not in current_ids:
        return f"<span class='warn'>&#9888; Target '{h(r.get('current_target_name') or r.get('target_area_name'))}' is no longer a current area. Choose a new one.</span>"
    return ('Confirmed' if r.get('confirmed_at') else 'Review') + separate


# ------------------------------------------------------------------------------------------ saving

@pages.route("/mappings/save", methods=["POST"])
def mappings_save():
    """Saves new or changed mappings (and closes old areas when ticked or chosen), all or nothing."""
    if not sign_in.allowed():
        return sign_in.go_to_login()
    try:
        sources, targets, notes = request.form.getlist("source"), request.form.getlist("target"), request.form.getlist("notes")
        deactivate = {historical.clean(v).casefold() for v in request.form.getlist("deactivate")}
        combined = {historical.clean(v).casefold() for v in request.form.getlist("combined")}
        if len(sources) != len(targets) or len(notes) != len(sources):
            raise ValueError("Mapping form is incomplete.")
        saved = closed = 0
        with database.connect() as conn:
            batches.lock_tables(conn, batches.PLACES_TABLES)
            before = batches.snapshot(conn, batches.PLACES_TABLES)
            with database.cursor(conn) as cur:
                areas = {a["id"]: a for a in places.current_areas(cur)}
                all_areas, zone_names = mission_areas(cur)
                for source, target, note in zip(sources, targets, notes):
                    if not target:
                        continue
                    source = historical.clean(source)
                    kind = "CLOSED" if target == "closed" else "COMBINED" if source.casefold() in combined else "CONFIRMED"
                    area = None if kind == "CLOSED" else areas.get(int(target)) if target.isdigit() else None
                    changed, closed_now = save_mapping(cur, source, area, note, deactivate, all_areas, zone_names, kind)
                    saved += changed
                    closed += closed_now
            if closed:  # "Close old area" is written down in Import history (kind PLACES), so it can be undone
                places_admin.save_batch(conn, f"Close old area (Area mappings, {closed})", {"action": "close", "level": "area", "closed": closed}, before)
        flash(f"Area mappings saved ({saved} changed" + (f", {closed} old area deactivated" if closed else "") + ").")
        return redirect("/mappings")
    except Exception as e:
        return page.render(f"<div class='error'>{h(e)}</div><p><a href='/mappings'>Back</a></p>", 400)


def save_mapping(cur, source, area, note, deactivate, all_areas, zone_names, kind="CONFIRMED"):
    """Saves one mapping (and closes its old area when ticked, or when the label is marked Closed). Returns (1 when
    saved else 0, areas closed). Raises ValueError, and then nothing of the form is saved."""
    if kind == "CLOSED":  # the area of the same name, when there is one (active or already closed)
        area = old_area_match(source, all_areas, zone_names)[0]
    if not source or (not area and kind != "CLOSED"):
        raise ValueError("Invalid source name or area outside this mission.")
    cur.execute("""select mission_id,source_companionship,target_area_id,match_status,notes,confirmed_at from public.import_weekly_planning_area_map where lower(source_companionship)=lower(%s) for update""", (source,))
    existing = cur.fetchone()
    if existing and existing["mission_id"] not in (None, sign_in.current_mission_id()):
        raise ValueError("That original label belongs to another mission.")
    if existing:
        source = existing["source_companionship"]
    closed = 0
    if kind == "CLOSED":
        if area and area.get("active", True):
            cur.execute("update public.areas set active=false where id=%s and active", (area["id"],))
            closed = cur.rowcount
    elif source.casefold() in deactivate:
        closed = close_old_area(cur, source, area, all_areas, zone_names)
    if not closed and (existing and existing["confirmed_at"] and existing["target_area_id"] == (area or {}).get("id")
                       and (existing["match_status"] or "CONFIRMED") == kind and (existing["notes"] or "").strip() == note.strip()):
        return 0, 0  # an unchanged confirmed row keeps its original confirmation
    cur.execute("""insert into public.import_weekly_planning_area_map
      (source_companionship,target_area_name,target_area_id,mission_id,match_status,notes,confirmed_at,confirmed_by)
      values(%s,%s,%s,%s,%s,%s,now(),%s) on conflict(source_companionship) do update
      set target_area_name=excluded.target_area_name,target_area_id=excluded.target_area_id,mission_id=excluded.mission_id,
          match_status=excluded.match_status,notes=excluded.notes,confirmed_at=now(),confirmed_by=excluded.confirmed_by""",
                (source, area and area["name"], area and area["id"], sign_in.current_mission_id(), kind, note.strip(), sign_in.actor_name()))
    return 1, closed


def close_old_area(cur, source, area, all_areas, zone_names):
    """Turns off the old area a label names ("Close old area"). Returns how many areas were turned off (0 or 1)."""
    old, reason = old_area_match(source, all_areas, zone_names)
    if not old:
        raise ValueError(f"Cannot close an old area for '{source}': {reason}. Nothing was saved.")
    if old["id"] == area["id"]:
        raise ValueError(f"'{source}' is mapped to {old['name']}, the area it would close. Choose the new target area first. Nothing was saved.")
    cur.execute("update public.areas set active=false where id=%s and active", (old["id"],))
    return cur.rowcount


@pages.route("/mappings/separate", methods=["POST"])
def mappings_separate():
    """Separate: the label's numbers leave the reports they were added to and go back to its own area (the area of
    the same name, active or closed). One HISTORICAL batch in Import history, so it can be undone."""
    if not sign_in.allowed():
        return sign_in.go_to_login()
    label = historical.clean(request.form.get("separate"))
    try:
        with database.connect() as conn:
            with database.cursor(conn) as cur:
                current_ids = {a["id"] for a in places.current_areas(cur)}
                area, reason = old_area_match(label, *mission_areas(cur))
            if not area:
                raise ValueError(f"'{label}' cannot be separated: {reason}. Nothing was changed.")
            _, count = historical_separate.separate_batch(conn, label, area)
            with database.cursor(conn) as cur:
                cur.execute("""update public.import_weekly_planning_area_map set match_status=%s,target_area_id=%s,target_area_name=%s,
                  confirmed_at=now(),confirmed_by=%s where lower(source_companionship)=lower(%s)""",
                            ("CONFIRMED" if area["id"] in current_ids else "CLOSED", area["id"], area["name"], sign_in.actor_name(), label))
        flash(f"Separated '{label}': {count} report(s) back to {area['name']}.")
        return redirect("/mappings")
    except Exception as e:
        return page.render(f"<div class='error'>{h(e)}</div><p><a href='/mappings'>Back</a></p>", 400)
