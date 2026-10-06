"""DA Management > Places: close and reopen zones, districts and areas (one place to open and close everything).

Who: the managers of DA Management (AP, President, Data Analyst), like every page here.
Rules (the owner's):
  - Closing a zone or a district does NOT close what is inside it. Each open district of the zone (or open area of the
    district) is moved first: the page asks where every one goes, and nothing is saved until each has a destination.
    The numbers follow the move: old plans show under the place their area belongs to today (step 3, Glimpse).
  - Reopening is always possible, for all three. Whatever was moved stays where it was moved.
  - Every change is one entry in Import history (kind PLACES) with every changed row before and after; Undo puts it back
    (batches.py, undo.py). "Close old area" in Area mappings is logged the same way (mappings_page.py).
  - A roster upload wins over a hand-made change (the owner, 4 Oct 2026): it switches a place back on when it names it
    (transfer.find_or_add), and it decides which areas are open by who serves there (transfer.update_active_areas).
The rules are change_place(); the page is the routes below.
"""
import psycopg2
from flask import Blueprint, flash, redirect, request

import batches
import database
import page
import sign_in
from page import h

pages = Blueprint("places_admin", __name__)


# ------------------------------------------------------------------------------------------ reading

def load_tree(cur, mission_id):
    """The mission's places: {"zone": {id: row}, "district": {...}, "area": {...}}. Rows carry active, name, their parent
    id (zone_id, district_id) and, for an area, how many missionaries serve there today."""
    cur.execute("select id,name,active from public.zones where mission_id=%s order by name", (mission_id,))
    zones = {r["id"]: r for r in cur.fetchall()}
    cur.execute("""select d.id,d.name,d.active,d.zone_id from public.districts d join public.zones z on z.id=d.zone_id
      where z.mission_id=%s order by d.name""", (mission_id,))
    districts = {r["id"]: r for r in cur.fetchall()}
    cur.execute("""select a.id,a.name,a.active,a.district_id,
        (select count(*) from public.missionary_assignments ma join public.missionaries m on m.id=ma.missionary_id
         where ma.area_id=a.id and (ma.end_date is null or ma.end_date>=current_date) and m.status='Active')::int serving
      from public.areas a join public.districts d on d.id=a.district_id join public.zones z on z.id=d.zone_id
      where z.mission_id=%s order by a.name""", (mission_id,))
    areas = {r["id"]: r for r in cur.fetchall()}
    return {"zone": zones, "district": districts, "area": areas}


def open_zones(tree):
    return {i: z for i, z in tree["zone"].items() if z["active"]}


def open_districts(tree):
    """Open districts that are in an open zone."""
    return {i: d for i, d in tree["district"].items() if d["active"] and tree["zone"][d["zone_id"]]["active"]}


# ------------------------------------------------------------------------------------------ the rules

def change_place(conn, level, place_id, action, moves=None, confirmed=False):
    """Closes or reopens one place as one batch. moves: {child id (text): destination id (text)} for what is inside a
    place that is closed. Returns the batch id; raises ValueError (nothing is saved) when a rule is broken."""
    if level not in ("zone", "district", "area") or action not in ("close", "reopen"):
        raise ValueError("Unknown change.")
    moves = moves or {}
    batches.lock_tables(conn, batches.PLACES_TABLES)
    before = batches.snapshot(conn, batches.PLACES_TABLES)
    with database.cursor(conn) as cur:
        tree = load_tree(cur, sign_in.current_mission_id())
        place = tree[level].get(place_id)
        if not place:
            raise ValueError("That place is not in your mission.")
        try:
            if action == "reopen":
                description, summary = reopen(cur, tree, level, place)
            else:
                description, summary = close(cur, tree, level, place, moves, confirmed)
        except psycopg2.errors.UniqueViolation:
            conn.rollback()
            raise ValueError("The place it moves to already has one with the same name. Rename one of them first.") from None
    return save_batch(conn, description, summary, before)


def save_batch(conn, description, summary, before):
    """Writes the change down in Import history (batches.py). The caller commits."""
    batch = batches.create_batch(conn, "PLACES", description.replace("/", "-"), None, summary)
    changed = batches.record_changes(conn, batch, batches.PLACES_TABLES, before, batches.snapshot(conn, batches.PLACES_TABLES))
    batches.add_to_summary(conn, batch, {"changed_rows": changed})
    return batch


def reopen(cur, tree, level, place):
    if place["active"]:
        raise ValueError(f"{place['name']} is already open.")
    if level == "district" and not tree["zone"][place["zone_id"]]["active"]:
        raise ValueError(f"Reopen the zone {tree['zone'][place['zone_id']]['name']} first (it is closed).")
    if level == "area":
        district = tree["district"][place["district_id"]]
        if not district["active"] or not tree["zone"][district["zone_id"]]["active"]:
            raise ValueError(f"Reopen the district {district['name']} (and its zone) first.")
    cur.execute(f"update public.{TABLE[level]} set active=true where id=%s", (place["id"],))
    return f"Reopen {level} {place['name']}", {"level": level, "action": "reopen", "name": place["name"]}


TABLE = {"zone": "zones", "district": "districts", "area": "areas"}


def close(cur, tree, level, place, moves, confirmed):
    if not place["active"]:
        raise ValueError(f"{place['name']} is already closed.")
    moved = 0
    if level == "zone":
        targets = {i: z for i, z in open_zones(tree).items() if i != place["id"]}
        if not targets:
            raise ValueError("This is the last open zone: close it only after another zone is open.")
        inside = [d for d in tree["district"].values() if d["zone_id"] == place["id"] and d["active"]]
        moved = move_children(cur, inside, moves, targets, "districts", "zone_id", "district")
    elif level == "district":
        targets = {i: d for i, d in open_districts(tree).items() if i != place["id"]}
        inside = [a for a in tree["area"].values() if a["district_id"] == place["id"] and a["active"]]
        if inside and not targets:
            raise ValueError("There is no other open district for its areas to go to.")
        moved = move_children(cur, inside, moves, targets, "areas", "district_id", "area")
    else:
        if place["serving"] and not confirmed:
            raise ValueError(f"{place['serving']} missionary(ies) serve in {place['name']} now. Tick the box to close it anyway.")
    cur.execute(f"update public.{TABLE[level]} set active=false where id=%s", (place["id"],))
    return f"Close {level} {place['name']}", {"level": level, "action": "close", "name": place["name"], "moved": moved}


def move_children(cur, children, moves, targets, table, column, noun):
    """Moves each open child to its chosen destination (an id of targets). Every child needs one; otherwise ValueError."""
    chosen = {}
    for child in children:
        raw = str(moves.get(str(child["id"]), "")).strip()
        if not raw.isdigit() or int(raw) not in targets:
            raise ValueError(f"Choose where the {noun} {child['name']} goes before closing.")
        chosen[child["id"]] = int(raw)
    for child_id, destination in chosen.items():
        cur.execute(f"update public.{table} set {column}=%s where id=%s", (destination, child_id))
    return len(chosen)


# ------------------------------------------------------------------------------------------ the page

def badge(active):
    return "<span class='badge'>Open</span>" if active else "<span class='badge' style='background:#f0e3e3;color:#9b2c2c'>Closed</span>"


def move_select(child, options):
    """One 'where does it go' list. options: [(id, label)]."""
    items = "".join(f"<option value='{i}'>{h(label)}</option>" for i, label in options)
    return (f"<label class='form-field'>{h(child['name'])} goes to <select name='move::{child['id']}' required>"
            f"<option value=''>Choose…</option>{items}</select></label>")


def change_form(level, place, action, button, body="", extra=""):
    return (f"<form action='/places/change' method='post' style='display:inline-block;margin:4px 0'>"
            f"<input type='hidden' name='level' value='{level}'><input type='hidden' name='id' value='{place['id']}'>"
            f"<input type='hidden' name='action' value='{action}'>{body}{extra}<button class='secondary'>{button}</button></form>")


def close_control(tree, level, place):
    """What the page offers to close an open place: a form listing the places inside that need a destination."""
    if level == "zone":
        targets = [(i, z["name"]) for i, z in open_zones(tree).items() if i != place["id"]]
        inside = [d for d in tree["district"].values() if d["zone_id"] == place["id"] and d["active"]]
        selects = "".join(move_select(d, targets) for d in inside)
        note = "Its open districts stay open: choose the zone each one moves to." if inside else "It has no open districts."
    elif level == "district":
        targets = [(i, f"{tree['zone'][d['zone_id']]['name']} / {d['name']}") for i, d in open_districts(tree).items() if i != place["id"]]
        inside = [a for a in tree["area"].values() if a["district_id"] == place["id"] and a["active"]]
        selects = "".join(move_select(a, targets) for a in inside)
        note = "Its open areas stay open: choose the district each one moves to." if inside else "It has no open areas."
    else:
        selects, note = "", ""
        if place["serving"]:
            selects = f"<label><input type='checkbox' name='confirmed' value='yes' required> {place['serving']} missionary(ies) serve here now. Close it anyway.</label>"
    form = change_form(level, place, "close", f"Close {level}", selects)
    if not selects:
        return form
    return f"<details><summary>Close {level}…</summary><p class='muted'>{note}</p>{form}</details>"


def place_line(tree, level, place, detail=""):
    control = close_control(tree, level, place) if place["active"] else change_form(level, place, "reopen", f"Reopen {level}")
    return f"<div class='actions' style='justify-content:space-between'><span>{h(place['name'])} {badge(place['active'])} <span class='muted'>{detail}</span></span><span>{control}</span></div>"


def places_page(tree):
    cards = []
    for zone in tree["zone"].values():
        districts = [d for d in tree["district"].values() if d["zone_id"] == zone["id"]]
        open_d = sum(1 for d in districts if d["active"])
        blocks = []
        for district in districts:
            areas = [a for a in tree["area"].values() if a["district_id"] == district["id"]]
            lines = "".join(place_line(tree, "area", a, f"{a['serving']} serving" if a["serving"] else "") for a in areas)
            open_a = sum(1 for a in areas if a["active"])
            control = close_control(tree, "district", district) if district["active"] else change_form("district", district, "reopen", "Reopen district")
            blocks.append(f"<details {'open' if district['active'] and areas else ''} style='margin:8px 0'><summary>{h(district['name'])} {badge(district['active'])} "
                          f"<span class='muted'>{open_a} open area(s)</span></summary><div style='margin-left:22px'><p>{control}</p>"
                          f"{lines or '<p class=muted>No areas.</p>'}</div></details>")
        cards.append(f"<div class='card'><h3>{place_line(tree, 'zone', zone, f'{open_d} open district(s)')}</h3>{''.join(blocks) or '<p class=muted>No districts.</p>'}</div>")
    return (f"<div class='card'><div class='step'>Places</div><h2>Close and reopen zones, districts and areas</h2>"
            "<p class='muted'>Closing a zone or district does not close what is inside it: you choose where each district (or area) goes first. "
            "The numbers follow: old plans show under the zone their area belongs to today. Every change is in "
            "<a href='/imports'>Import history</a>, where it can be undone. A roster upload wins over a change made here: "
            "it reopens a place it names and decides which areas are open by who serves there.</p></div>" + "".join(cards))


@pages.route("/places")
def places():
    if not sign_in.allowed():
        return sign_in.go_to_login()
    with database.connect() as conn:
        with database.cursor(conn) as cur:
            tree = load_tree(cur, sign_in.current_mission_id())
    return page.render(places_page(tree))


@pages.route("/places/change", methods=["POST"])
def change():
    """Closes or reopens one place (change_place), then back to the list."""
    if not sign_in.allowed():
        return sign_in.go_to_login()
    form = request.form
    conn = database.connect()
    try:
        place_id = int(form.get("id") or 0)
        moves = {k[len("move::"):]: v for k, v in form.items() if k.startswith("move::")}
        batch = change_place(conn, form.get("level", ""), place_id, form.get("action", ""), moves, form.get("confirmed") == "yes")
        conn.commit()
    except ValueError as error:
        conn.rollback()
        return page.render(f"<div class='error'><b>Nothing was changed.</b><br>{h(error)}</div><p><a href='/places'>Back to Places</a></p>", 400)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    flash("Saved. It is in Import history, where it can be undone.")
    return redirect("/places")
