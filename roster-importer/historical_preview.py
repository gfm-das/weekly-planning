"""Historical CSV, step 2: the check ("preview") of an uploaded Weekly Planning export, before anything is saved.

The file is the old Weekly Planning form export (read by historical_import.read_csv_rows). preview() works out what
the import would do, step by step:

  1. Units: which ward or branch each row reports for (historical_units.resolve_unit). The manager can correct it.
  2. Latest only: when a companionship sent the form twice for the same Sunday and unit, the latest counts.
  3. Look-alike labels: labels that differ only by punctuation or spacing ('Frankfurt-Darmstadt S' and 'Frankfurt
     Darmstadt S') would share one report key. The manager keeps one, or combines them.
  4. Rows: each row's old label must be mapped to a current area (Area mappings), its date must be a Sunday, and its
     key indicators whole numbers.
  5. Same unit: without "Combine", old areas that report for the same current area, unit and week need a choice.
  6. Target reports: the report each area/unit/week writes to (a new one, or the existing one it replaces).
  7. Moved labels: a label imported earlier into another area or unit is moved (or removed) in the same batch, so it
     is never counted twice.

The manager's choices come back from the page (see historical_pages.py) as `choices`:
    {"collisions": {report key: "keep:<label>" | "combine"},
     "targets": {"<area_id>|<sunday>": report id},
     "units": {"<ward/branch text>|<area_id>": unit id},
     "merges": {"<area_id>|<unit_id>": "combine" | "keep:<label>", "<area_id>|<unit_id>|<sunday>": the same}}

The result carries a state token (an HMAC, see state_token): Apply (historical_apply.py) runs the check again under
lock and refuses anything that changed since the manager looked at it.
"""
import hashlib
import hmac
import json
from pathlib import Path

from psycopg2 import sql

import database
import historical_import as historical
import people_csv
import people_match
import places
import settings
import sign_in
from historical_units import resolve_unit, unit_catalog, unit_label

# The old spreadsheet's column names: how the file is read, never renamed.
COLLISION_METRICS = ["Friends Found - Actual", "Lessons with Friends - Actual", "Sacrament Attendance - Actual",
                     "Baptismal Dates - Actual"]
# What the choices table shows for them (Friends Found is New People Being Taught since round 3).
METRIC_LABELS = {"Friends Found - Actual": "New people being taught", "Lessons with Friends - Actual": "Lessons with friends",
                 "Sacrament Attendance - Actual": "Sacrament attendance", "Baptismal Dates - Actual": "Baptismal dates"}


class Check:
    """Everything the steps of one check share: what the database knows, the manager's choices, and what the check
    found so far (errors block Apply; pending are choices still to make; notices are for reading)."""

    def __init__(self, cur, choices, replace_existing, combine_mapped):
        self.areas = {r["id"]: r for r in places.current_areas(cur)}
        cur.execute("select * from public.import_weekly_planning_area_map where mission_id=%s or mission_id is null",
                    (sign_in.current_mission_id(),))
        self.mappings = {historical.clean(r["source_companionship"]).casefold(): r for r in cur.fetchall()}
        self.units, self.zones = unit_catalog(cur)
        self.units_by_id = {u["id"]: u for u in self.units}
        self.replace_existing = replace_existing
        self.combine_mapped = combine_mapped
        self.choices = choices or {}
        self.errors, self.pending, self.notices = [], [], []
        # What the page offers to choose (ui), the choices that are in force (effective), and the upload's facts the
        # choices depend on (state, part of the state token).
        self.ui = {"collisions": [], "targets": [], "units": [], "merges": []}
        self.effective = {"collisions": {}, "targets": {}, "units": {}, "merges": {}}
        self.state = {"collisions": {}, "targets": {}, "units": {}, "merges": {}}

    def chosen(self, kind):
        """The manager's choices of one kind ({} when there are none)."""
        return dict(self.choices.get(kind) or {})

    def area_of_label(self, label):
        """The current area an old label is mapped to, or None."""
        return self.areas.get((self.mappings.get(label.casefold()) or {}).get("target_area_id"))


def preview(path, connection=None, replace_existing=True, combine_mapped=True, choices=None):
    """Checks an upload (see the top of this file). connection: Apply passes its own locked connection."""
    rows = historical.read_csv_rows(path)
    conn = connection or database.connect()
    owns = connection is None
    try:
        with database.cursor(conn) as cur:
            check = Check(cur, choices, replace_existing, combine_mapped)
            find_units(check, rows)
            selected, duplicates = historical.deduplicate_rows(
                rows, unit_of=lambda r: r["_unit_id"] if r["_unit_id"] else historical.clean(r.get(historical.UNIT_COLUMN)).casefold())
            if not selected:
                raise ValueError("No dated Weekly Planning reports were found in the CSV.")
            units_of_key = units_per_report_key(selected)
            dropped, extra_keys, combined = choose_look_alike_labels(check, selected, units_of_key)
            items = report_items(check, selected, dropped, extra_keys, units_of_key)
            check_combined_areas(check, items, combined)
            items, skipped = choose_same_unit_rows(check, items)
            groups = {}
            for item in items:
                groups.setdefault((item["area"]["id"], item["sunday"], item["unit_id"]), []).append(item)
            target_reports, taken, owner = choose_target_reports(check, cur, groups)
            stale = find_moved_labels(check, cur, items, groups, target_reports, taken, owner)
            people = check_people(check, cur, items)
            token = state_token(path, replace_existing, combine_mapped, check.state, check.effective)
            return {"rows": items, "duplicates": len(duplicates), "source_rows": len(rows), "skipped": skipped,
                    "errors": sorted(set(check.errors)), "pending": check.pending, "notices": check.notices,
                    "choices": check.ui, "effective_choices": check.effective, "state_token": token,
                    "target_reports": target_reports, "stale_reports": stale, "people": people}
    finally:
        if owns:
            conn.close()


def check_people(check, cur, items):
    """The people of the rows (people_csv.py, people_match.py). Pairs that may be the same person are a choice still to
    make (pending), asked on the check page and remembered; the answers are part of the state token."""
    appearances, high_potentials = people_csv.people_of_rows(items)
    mission = sign_in.current_mission_id()
    decisions = people_match.load_decisions(cur, mission)
    found = people_match.resolve(people_match.group_people(appearances), people_match.stored_people(cur, mission), decisions)
    found["high_potentials"] = high_potentials
    found["counts"] = {"people": len(found["groups"]), "to_join": sum(1 for g in found["groups"] if g["stored_id"]),
                       "high_potentials": len(high_potentials)}
    check.state["people"] = {"decisions": sorted(f"{a}|{b}|{same}" for (a, b), same in decisions.items()),
                             "questions": [list(q["keys"]) for q in found["questions"]]}
    if found["questions"]:
        check.pending.append(f"Answer the {len(found['questions'])} question(s) about people who may be the same person.")
    return found


def state_token(path, replace_existing, combine_mapped, state, effective):
    """An HMAC over the upload, the options, the choice-relevant database state and the effective choices.

    Apply recomputes it inside its locked transaction; any difference (another file, changed reports, tampered or
    stale choices) refuses the apply before anything is written."""
    payload = json.dumps({"file": hashlib.sha256(Path(path).read_bytes()).hexdigest(), "replace": bool(replace_existing),
                          "combine": bool(combine_mapped), "state": state, "choices": effective},
                         sort_keys=True, default=str)
    secret = str(settings.SECRET_KEY or "").encode("utf-8")
    return hmac.new(secret, payload.encode("utf-8"), hashlib.sha256).hexdigest()


# ------------------------------------------------------------------------------------------ 1. units

def find_units(check, rows):
    """Which ward or branch (unit) each row reports for. Sets row["_unit_id"] and row["_unit_confident"]. The page
    shows every answer with its unit; a correction applies to every row with that answer and area."""
    resolutions = resolve_answers(check, rows)
    use_unit_corrections(check, resolutions)
    seen = set(check.choices.get("units_seen") or [])
    for res in resolutions.values():
        chosen = res.get("override", res["auto"])
        res["confirmed"] = res["key"] in seen
        res["unit"] = check.units_by_id.get(chosen)
        check.ui["units"].append({"key": res["key"], "text": res["text"], "area": res["area"]["name"],
                                  "labels": sorted(res["labels"]), "rows": res["rows"], "how": res["how"],
                                  "confident": res["confident"], "auto": res["auto"], "selected": chosen,
                                  "overridden": "override" in res, "confirmed": res["confirmed"],
                                  "linked": bool(chosen) and res["area"]["id"] in check.units_by_id[chosen]["area_ids"]})
    for row in rows:
        res = resolutions.get(row.get("_unit_key"))
        if res and res["unit"]:
            row["_unit_id"] = res["unit"]["id"]
            row["_unit_confident"] = res["confident"] or "override" in res
    check.ui["units"].sort(key=lambda u: (u["confident"] or u["overridden"], u["area"], u["text"]))
    add_unit_notices(check)


def resolve_answers(check, rows):
    """{"<answer>|<area id>": how that Ward/Branch answer resolves for that mapped area}, one entry per answer and area."""
    resolutions = {}
    for row in rows:
        label = historical.clean(row[historical.COMPANIONSHIP_COLUMN])
        area = check.area_of_label(label)
        text = historical.clean(row.get(historical.UNIT_COLUMN))
        row["_unit_id"], row["_unit_confident"] = None, False
        if not area:
            continue
        key = f"{text}|{area['id']}"
        if key not in resolutions:
            unit, how, confident = resolve_unit(text, label, area["id"], check.units, check.zones)
            resolutions[key] = {"key": key, "text": text, "area": area, "labels": set(), "rows": 0,
                                "auto": unit["id"] if unit else None, "how": how, "confident": confident}
            check.state["units"][key] = resolutions[key]["auto"]
        resolutions[key]["labels"].add(label)
        resolutions[key]["rows"] += 1
        row["_unit_key"] = key
    return resolutions


def use_unit_corrections(check, resolutions):
    """The units the manager chose instead of the suggested ones."""
    for key, raw in check.chosen("units").items():
        res = resolutions.get(key)
        if res is None:
            check.errors.append(f"A saved Ward/Branch choice ('{key.rsplit('|', 1)[0] or 'blank'}') no longer matches this upload. Recheck the preview and choose again.")
            continue
        if str(raw) in ("", "auto") or (str(raw).isdigit() and int(raw) == res["auto"]):
            continue
        if not str(raw).isdigit() or int(raw) not in check.units_by_id:
            check.errors.append(f"The unit chosen for Ward/Branch '{res['text'] or 'blank'}' ({res['area']['name']}) is not a known unit. Choose again.")
            continue
        res["override"] = int(raw)
        check.effective["units"][key] = int(raw)


def add_unit_notices(check):
    """Notes about units that were guessed, and units not linked to their mapped area."""
    guessed = [u for u in check.ui["units"] if not u["confident"] and not u["overridden"] and not u["confirmed"]]
    if guessed:
        check.notices.append(f"{len(guessed)} Ward/Branch answer(s) did not name a known unit, so the unit was worked out from the "
                             "old area name or the mapped area. Check them under “Ward/Branch → unit” and correct any that are wrong.")
    unlinked = sorted({(u["area"], check.units_by_id[u["selected"]]["name"]) for u in check.ui["units"] if u["selected"] and not u["linked"]})
    if unlinked:
        check.notices.append("These units are not currently linked to the mapped area, so the portal's area page will not list "
                             "those reports (they still count in weekly totals and dashboards): "
                             + "; ".join(f"{unit} → {area}" for area, unit in unlinked) + ".")


# ------------------------------------------------------------------------------------------ 2. and 3. report keys

def units_per_report_key(selected):
    """{report key: the units reported under it}. A label reporting for two units in one week needs one key per unit."""
    units_of_key = {}
    for row in selected:
        base = historical.make_report_key(historical.clean(row[historical.COMPANIONSHIP_COLUMN]), row["_sunday"])
        units_of_key.setdefault(base, set()).add(row["_unit_id"])
    return units_of_key


def report_key(label, sunday, unit_id, units_of_key):
    """The report key of a label, week and unit: '<label>:<sunday>', plus '@u<unit id>' when the label reports for
    two units that week."""
    base = historical.make_report_key(label, sunday)
    return f"{base}@u{unit_id}" if len(units_of_key.get(base, ())) > 1 else base


def choose_look_alike_labels(check, selected, units_of_key):
    """Labels that differ only by punctuation or spacing share one report key (per unit). The manager keeps one row,
    or combines them (the extra labels then get their own staging key). Returns (dropped rows, extra keys, combined
    labels per key); rows are named by (label in small letters, sunday, unit id)."""
    dropped, extra_keys, combined = set(), {}, {}
    chosen = check.chosen("collisions")
    for key, bucket in sorted(look_alike_buckets(selected, units_of_key).items()):
        if len(bucket) < 2:
            continue
        bucket.sort(key=lambda x: x[0])
        labels = [label for label, _ in bucket]
        sunday, unit_id = bucket[0][1]["_sunday"], bucket[0][1]["_unit_id"]
        check.state["collisions"][key] = labels
        options = [f"keep:{label}" for label in labels] + ["combine"]
        choice = chosen.get(key)
        check.ui["collisions"].append({"key": key, "sunday": sunday, "rows": [collision_row(check, label, row) for label, row in bucket],
                                       "options": options, "selected": choice if choice in options else None})
        everything = {(label.casefold(), sunday, unit_id) for label in labels}
        if choice is None:
            check.pending.append(f"Choose how to import {', '.join(repr(l) for l in labels)} ({sunday}): they share report key '{key}'.")
            dropped |= everything
        elif choice not in options:
            check.errors.append(f"The choice submitted for report key '{key}' is not valid for this upload. Choose again.")
            dropped |= everything
        elif choice == "combine":
            check.effective["collisions"][key] = choice
            combined[key] = labels
            for label in labels[1:]:
                extra_keys[(label.casefold(), sunday, unit_id)] = f"{key}~{hashlib.sha1(label.encode('utf-8')).hexdigest()[:8]}"
        else:
            check.effective["collisions"][key] = choice
            dropped |= everything - {(choice[5:].casefold(), sunday, unit_id)}
    for key in chosen:
        if key not in check.state["collisions"]:
            check.errors.append(f"A saved choice for report key '{key}' no longer matches this upload. Recheck the preview and choose again.")
    return dropped, extra_keys, combined


def look_alike_buckets(selected, units_of_key):
    """{report key: [(label, row), ...]} with each differently written label once."""
    buckets = {}
    for row in selected:
        label = historical.clean(row[historical.COMPANIONSHIP_COLUMN])
        bucket = buckets.setdefault(report_key(label, row["_sunday"], row["_unit_id"], units_of_key), [])
        if label.casefold() not in {r[0].casefold() for r in bucket}:
            bucket.append((label, row))
    return buckets


def collision_row(check, label, row):
    """One row of a look-alike labels table on the page."""
    area = check.area_of_label(label)
    return {"label": label, "area": area["name"] if area else "(not mapped to a current area)",
            "timestamp": row["_timestamp"], "unit": historical.clean(row.get(historical.UNIT_COLUMN)),
            "row_number": row["_source_row_number"],
            "metrics": {heading: historical.clean(row.get(heading)) for heading in COLLISION_METRICS}}


# ------------------------------------------------------------------------------------------ 4. rows

def report_items(check, selected, dropped, extra_keys, units_of_key):
    """The rows the import would write, each with its current area, Sunday, unit and report key. Rows that cannot be
    imported add an error."""
    items = []
    for row in selected:
        source = historical.clean(row[historical.COMPANIONSHIP_COLUMN])
        sunday = row["_sunday"]
        ident = (source.casefold(), sunday, row["_unit_id"])
        if ident in dropped:
            continue
        mapping = check.mappings.get(source.casefold())
        area = check.areas.get((mapping or {}).get("target_area_id"))
        if not area:
            if mapping and mapping.get("target_area_id"):
                check.errors.append(f"The mapping for '{source}' points to '{mapping.get('target_area_name') or mapping['target_area_id']}', "
                                    "which is no longer a current area. Choose a new target area before importing.")
            else:
                check.errors.append(f"Map '{source}' to a current area before importing.")
            continue
        check_row(check, row, source, mapping, sunday)
        key = extra_keys.get(ident) or report_key(source, sunday, row["_unit_id"], units_of_key)
        row["_report_key"] = key
        unit = check.units_by_id.get(row["_unit_id"])
        items.append({"source": source, "area": area, "sunday": sunday, "key": key, "row": row, "existing_id": None,
                      "unit_id": row["_unit_id"], "unit_name": unit_label(unit) if unit else None,
                      "collision_extra": ident in extra_keys})
    return items


def check_row(check, row, source, mapping, sunday):
    """A confirmed mapping, a Sunday, and whole numbers for the key indicators."""
    if not mapping.get("confirmed_at"):
        check.errors.append(f"Confirm the suggested mapping for '{source}' before importing.")
    if sunday.weekday() != 6:
        check.errors.append(f"Row {row['_source_row_number']}: reporting date {sunday} is not a Sunday.")
    for heading in historical.REPORT_COLUMNS:
        value = historical.clean(row.get(heading))
        number = historical.number(value)
        if value and (number is None or number < 0 or number != int(number)):
            now = " (now New people being taught)" if heading.startswith("Friends Found") else ""
            check.errors.append(f"Row {row['_source_row_number']}: '{heading}'{now} must be a nonnegative whole number.")


def check_combined_areas(check, items, combined):
    """Combined look-alike labels must be mapped to the same area."""
    for key, labels in combined.items():
        folded = {label.casefold() for label in labels}
        targets_of = {item["area"]["id"] for item in items if item["source"].casefold() in folded
                      and (item["key"] == key or item["collision_extra"])}
        if len(targets_of) > 1:
            check.errors.append(f"{', '.join(repr(l) for l in labels)} are mapped to different areas, so they cannot be combined. "
                                "Keep one of them or change the mappings.")


# ------------------------------------------------------------------------------------------ 5. same area, unit and week

def choose_same_unit_rows(check, items):
    """Different old areas reporting for the same current area, week AND unit. With "Combine" they are summed into
    one report; otherwise the manager decides once per area and unit (and may change single weeks). Returns (the rows
    to import, the rows skipped)."""
    if check.combine_mapped:
        return items, []
    same_unit = {}
    for item in items:
        if not item["collision_extra"]:
            same_unit.setdefault((item["area"]["id"], item["unit_id"], item["sunday"]), []).append(item)
    keep_out = set()
    for (area_id, unit_id), weeks in same_unit_scopes(same_unit).items():
        keep_out |= choose_for_scope(check, items, same_unit, area_id, unit_id, weeks)
    chosen = check.chosen("merges")
    for key in chosen:
        if key not in check.state["merges"] and not any(key == m["key"] for m in check.ui["merges"]):
            check.errors.append("A saved choice for old areas sharing one unit no longer matches this upload. Recheck the preview and choose again.")
            break
    for item in items:
        if not item.get("skip") and (item["area"]["id"], item["unit_id"], item["sunday"]) in keep_out:
            item["skip"] = "Waiting for your choice below"
    # Rows of weeks still waiting for a choice stay out of the report plan (Apply is disabled anyway).
    return [i for i in items if not i.get("skip")], [i for i in items if i.get("skip")]


def same_unit_scopes(same_unit):
    """{(area id, unit id): [(sunday, [labels]), ...]} for every week where several old areas report for one unit."""
    scopes = {}
    for (area_id, unit_id, sunday), items in sorted(same_unit.items(), key=lambda x: (x[0][0], str(x[0][1]), x[0][2])):
        if len(items) > 1:
            scopes.setdefault((area_id, unit_id), []).append((sunday, sorted(i["source"] for i in items)))
    return scopes


def choose_for_scope(check, items, same_unit, area_id, unit_id, weeks):
    """Applies the manager's choice for one area and unit (and its single weeks). Returns the weeks still waiting."""
    scope_key = f"{area_id}|{unit_id if unit_id is not None else 'none'}"
    labels = sorted({label for _, week_labels in weeks for label in week_labels})
    options = ["combine"] + [f"keep:{label}" for label in labels]
    chosen = check.chosen("merges")
    scope_choice = chosen.get(scope_key)
    area_name = check.areas[area_id]["name"]
    if scope_choice is not None and scope_choice not in options:
        check.errors.append(f"The choice submitted for {area_name} is not valid for this upload. Choose again.")
        scope_choice = None
    waiting, week_ui = set(), []
    for sunday, week_labels in weeks:
        week_key = f"{scope_key}|{sunday}"
        check.state["merges"][week_key] = week_labels
        week_options = ["combine"] + [f"keep:{label}" for label in week_labels]
        override = chosen.get(week_key)
        if override in ("", None):
            override = None
        elif override not in week_options:
            check.errors.append(f"The choice submitted for {area_name}, {sunday} is not valid for this upload. Choose again.")
            override = None
        choice = override or scope_choice
        missing = choice is not None and choice not in week_options
        week_ui.append({"key": week_key, "sunday": sunday, "labels": week_labels, "override": override, "missing": missing})
        if choice is None or missing:
            what = (f"'{choice[5:]}' did not report that week" if missing else "choose combine or which old area to keep")
            check.pending.append(f"{area_name}, {sunday}: {len(week_labels)} old areas report for the same unit — {what}.")
            waiting.add((area_id, unit_id, sunday))
            continue
        check.effective["merges"][week_key] = choice
        if choice != "combine":
            skip_other_labels(items, same_unit[(area_id, unit_id, sunday)], choice[5:])
    unit = check.units_by_id.get(unit_id)
    check.ui["merges"].append({"key": scope_key, "area": area_name, "unit": unit_label(unit) if unit else "no unit",
                               "labels": labels, "weeks": week_ui, "selected": scope_choice})
    return waiting


def skip_other_labels(items, week_items, keep):
    """The choice "Keep only <label>" for one week: the other old areas' rows are skipped, with look-alike labels combined into
    them."""
    for item in (i for i in week_items if i["source"].casefold() != keep.casefold()):
        item["skip"] = f"Skipped: you chose to keep {keep}"
        for extra in items:
            if extra["collision_extra"] and extra["key"].split("~")[0] == item["key"]:
                extra["skip"] = item["skip"]


# ------------------------------------------------------------------------------------------ 6. target reports

def choose_target_reports(check, cur, groups):
    """The existing report each area/unit/week group replaces (when there is one). Returns (target reports by group,
    the ids of every existing report of these groups, the group of each of those reports)."""
    target_reports, taken, owner = {}, set(), {}
    chosen_targets = check.chosen("targets")
    for group, items in groups.items():
        existing = existing_reports(cur, group)
        taken |= {r["id"] for r in existing}
        owner.update({r["id"]: group for r in existing})
        chosen = pick_target(check, group, items, existing, chosen_targets)
        if chosen is not None:
            target_reports[group] = chosen
            for item in items:
                item["existing_id"] = chosen
    for group_key in chosen_targets:
        if group_key not in check.state["targets"]:
            check.errors.append(f"A saved report choice for {group_key.replace('|', ', ')} no longer matches this upload. Recheck the preview and choose again.")
    return target_reports, taken, owner


def existing_reports(cur, group):
    """The reports that already exist for an area, Sunday and unit."""
    area_id, sunday, unit_id = group
    cur.execute("""select r.id,r.unit_id,u.name unit_name,r.status,r.historical_source_key,r.friends_found_actual,
        r.lessons_with_friends_actual,r.sacrament_attendance_actual,r.baptismal_dates_actual
      from public.weekly_area_reports r join public.reporting_weeks w on w.id=r.reporting_week_id
      left join public.units u on u.id=r.unit_id
      where r.area_id=%s and w.sunday=%s and r.unit_id is not distinct from %s order by r.id""", (area_id, sunday, unit_id))
    return cur.fetchall()


def pick_target(check, group, items, existing, chosen_targets):
    """The report this group replaces, or None (a new report, or a choice still to make)."""
    area_id, sunday, _ = group
    name = items[0]["area"]["name"]
    chosen = existing[0]["id"] if len(existing) == 1 else None
    unit_note = f" ({items[0]['unit_name']})" if items[0]["unit_name"] else ""
    if existing and not check.replace_existing:
        for item in items:
            check.errors.append(f"{item['source']}, {sunday}: a report already exists for {name}{unit_note}. Choose Replace existing reports to continue.")
    elif len(existing) > 1:
        # Only reports without a unit can repeat per area/week: the manager picks the one to replace.
        group_key = f"{area_id}|{sunday}"
        ids = [r["id"] for r in existing]
        check.state["targets"][group_key] = ids
        batch_keys = {item["key"] for item in items}
        holders = [r["id"] for r in existing if r["historical_source_key"] in batch_keys]
        choice = chosen_targets.get(group_key)
        defaulted = False
        if choice is not None:
            chosen = int(choice) if str(choice).isdigit() and int(choice) in ids else None
            if chosen is None:
                check.errors.append(f"The report chosen for {name}, {sunday} is not one of its current reports. Choose again.")
        elif len(holders) == 1:
            chosen, defaulted = holders[0], True  # the report that already holds this earlier import
        else:
            check.pending.append(f"Choose which existing report for {name}, {sunday} this import replaces.")
        if chosen is not None:
            check.effective["targets"][group_key] = chosen
            if any(held != chosen for held in holders):
                check.errors.append(f"{name}, {sunday}: report #{holders[0]} already holds an earlier import of this label. "
                                    f"Choose report #{holders[0]}, or undo that import first.")
        check.ui["targets"].append({"group": group_key, "area": name, "sunday": sunday, "reports": existing,
                                    "selected": chosen, "defaulted": defaulted})
    return chosen


# ------------------------------------------------------------------------------------------ 7. labels imported elsewhere

def find_moved_labels(check, cur, items, groups, target_reports, taken, owner):
    """Reports that already hold one of these labels for the same week under a DIFFERENT area or unit (the label was
    remapped, or an earlier import stored it without a unit). They are moved or removed inside the batch, so the
    unique historical_source_key never collides and nothing is counted twice. Returns {report id: {id, area_name,
    target group}}."""
    batch_labels = {}
    for item in items:
        batch_labels.setdefault(item["sunday"], set()).add(item["source"].casefold())
    group_labels = {g: {i["source"].casefold() for i in group_items} for g, group_items in groups.items()}
    refs, stale = None, {}
    claimed = set(target_reports)  # groups that already have their report; later stale ones are removed
    for item in items:
        group = (item["area"]["id"], item["sunday"], item["unit_id"])
        for found in reports_with_label(cur, item):
            labels = report_labels(found["details_labels"]) or [historical.clean(found["historical_source_area"])]
            folded = {label.casefold() for label in labels}
            if found["historical_source_key"] == item["key"] and item["source"].casefold() not in folded:
                check.errors.append(f"'{item['source']}' and '{found['historical_source_area']}' share report key '{item['key']}' "
                                    f"(report #{found['id']}). Use one spelling for this companionship in the CSV and upload again.")
                continue
            if found["id"] in stale or found["id"] == target_reports.get(group):
                continue
            if found["id"] in taken:
                # Another unit's report of this batch holds this label; it is fine when that report is re-imported
                # with this label too (its details are replaced).
                if item["source"].casefold() not in group_labels.get(owner[found["id"]], set()):
                    check.errors.append(f"{item['source']}, {item['sunday']}: this label was already imported into report #{found['id']} "
                                        f"({found['unit_name'] or 'no unit'}), which this upload does not re-import. Choose that unit for "
                                        f"its Ward/Branch answer, or undo import batch {found['import_batch_id']} first.")
                continue
            refs = report_dependency_refs(cur) if refs is None else refs
            if not may_move(check, cur, item, found, labels, batch_labels, refs):
                continue
            stale[found["id"]] = {"id": found["id"], "area_name": found["area_name"], "target": group}
            if group in claimed:
                item.setdefault("removes", []).append(f"#{found['id']} ({found['area_name']})")
            else:
                claimed.add(group)
                item["moved_from"] = found["area_name"] + (f" ({found['unit_name']})" if found["unit_name"] else " (no unit)")
    return stale


def reports_with_label(cur, item):
    """Reports that hold this row's label for its week: by report key, by a unit key of the same label, or listed in
    their historical details."""
    base = historical.make_report_key(item["source"], item["sunday"])
    like = base.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "@u%"
    cur.execute(r"""select r.id,r.area_id,a.name area_name,r.unit_id,u.name unit_name,r.import_batch_id,r.historical_source_key,
        r.historical_source_area,d.source_companionship details_labels
      from public.weekly_area_reports r join public.reporting_weeks w on w.id=r.reporting_week_id
      join public.areas a on a.id=r.area_id left join public.units u on u.id=r.unit_id
      left join public.historical_planning_details d on d.weekly_area_report_id=r.id
      where r.historical_source_key=%s or (w.sunday=%s and r.historical_source_key like %s)
        or (w.sunday=%s and d.source_companionship is not null and
        lower(%s)=any(select lower(btrim(x)) from regexp_split_to_table(d.source_companionship,' \+ ') x))
      order by r.id""", (item["key"], item["sunday"], like, item["sunday"], item["source"]))
    return cur.fetchall()


def may_move(check, cur, item, found, labels, batch_labels, refs):
    """Whether an earlier report of this label may be moved into this import. Adds the reason as an error when not:
    Replace is not chosen, it also holds labels this upload does not have, or portal planning rows depend on it."""
    where = (f"{item['source']}, {item['sunday']}: this label was already imported into {found['area_name']}"
             f"{' (' + found['unit_name'] + ')' if found['unit_name'] else ''} (report #{found['id']})")
    if not check.replace_existing:
        check.errors.append(f"{where}. Choose Replace existing reports to move it to {item['area']['name']}.")
        return False
    others = [label for label in labels if label.casefold() not in batch_labels[item["sunday"]]]
    if others:
        check.errors.append(f"{where}, which also contains {', '.join(repr(o) for o in others)}. Include those labels in the "
                            f"same upload or undo import batch {found['import_batch_id']} first.")
        return False
    blocked = external_dependents(cur, refs, found["id"])
    if blocked:
        check.errors.append(f"{where}, which also has Weekly Planning entries ({', '.join(blocked)}). It cannot be moved "
                            f"safely; undo import batch {found['import_batch_id']} or map the label back first.")
        return False
    return True


def report_labels(source_companionship):
    """Original labels recorded on one historical_planning_details row (combined labels use ' + ')."""
    return [historical.clean(x) for x in str(source_companionship or "").split(" + ") if historical.clean(x)]


def report_dependency_refs(cur):
    """Tables (other than the historical details table) whose rows point to weekly_area_reports: the portal's
    Weekly Planning entries."""
    cur.execute("""select cl.relname table_name,a.attname column_name
      from pg_constraint c join pg_class cl on cl.oid=c.conrelid join pg_namespace n on n.oid=cl.relnamespace
      join pg_attribute a on a.attrelid=c.conrelid and a.attnum=c.conkey[1]
      where c.contype='f' and c.confrelid='public.weekly_area_reports'::regclass and cardinality(c.conkey)=1
        and n.nspname='public' and cl.relname<>'historical_planning_details' order by 1""")
    return cur.fetchall()


def external_dependents(cur, refs, report_id):
    """The names of the tables that have rows pointing to this report."""
    found = []
    for ref in refs:
        cur.execute(sql.SQL("select exists(select 1 from public.{} where {}=%s) present").format(
            sql.Identifier(ref["table_name"]), sql.Identifier(ref["column_name"])), (report_id,))
        if cur.fetchone()["present"]:
            found.append(ref["table_name"])
    return found
