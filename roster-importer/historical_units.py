"""Historical CSV: which ward or branch (unit) each old Weekly Planning report was for.

A companionship that serves two wards or branches filled out one form per unit each week. Reports are kept per
area + unit + week (as in the portal), so the import works out the unit of every row from its "Which Ward/Branch Are
You in?" answer, and only treats rows as the same report when area, week AND unit are the same.

How a unit is found (resolve_unit), best first:
  1. the Ward/Branch answer names a unit ("Frankfurt 2" matches "Frankfurt 2nd (English)": ordinal endings, the words
     ward/branch/Gemeinde/Zweig, a zone prefix and, second try, a language tag in brackets are ignored);
  2. the old area name names a unit;
  3. the mapped area's only unit, or its main unit.
Only the first way counts as sure ("confident"); the check page asks the manager to look at the others.
"""
import re

import historical_import as historical
import sign_in

UNIT_WORDS = re.compile(r"\b(ward|branch|gemeinde|zweig)\b")


def unit_norm(text, drop_parens=False):
    """A unit name in a form that ignores capitals, punctuation, ordinal endings and the words ward/branch:
    'Frankfurt 2nd Ward' -> 'frankfurt 2'. drop_parens also drops '(English)'."""
    text = str(text or "").casefold()
    if drop_parens:
        text = re.sub(r"\([^)]*\)", " ", text)
    text = re.sub(r"\b(\d+)\s*(st|nd|rd|th|\.)(?=\W|$)", r"\1", text)
    text = UNIT_WORDS.sub(" ", text)
    return " ".join(re.sub(r"[^\w]+", " ", text).split())


def unit_catalog(cur):
    """(units, zone names). units: every active unit (plus any unit linked to an area) with the areas it is linked to
    (area_ids, primary_area_ids) and its name in two compared forms (norm, base). Zone names in small letters."""
    cur.execute("""select u.id,u.name,u.unit_number,u.active,
        coalesce(array_agg(au.area_id order by au.primary_unit desc,au.id) filter (where au.active),'{}') area_ids,
        coalesce(array_agg(au.area_id) filter (where au.active and au.primary_unit),'{}') primary_area_ids
      from public.units u left join public.area_units au on au.unit_id=u.id
      group by u.id having u.active or bool_or(coalesce(au.active,false)) order by u.name,u.id""")
    units = cur.fetchall()
    for u in units:
        u["norm"], u["base"] = unit_norm(u["name"]), unit_norm(u["name"], True)
    cur.execute("select name from public.zones where mission_id=%s", (sign_in.current_mission_id(),))
    zones = {historical.clean(r["name"]).casefold() for r in cur.fetchall()}
    return units, zones


def unit_label(unit):
    """'Frankfurt 1st (66230)'."""
    return f'{unit["name"]}' + (f' ({unit["unit_number"]})' if unit.get("unit_number") else "")


def strip_zone(text, zones):
    """'Kaiserslautern-Ramstein 1' -> 'Ramstein 1' when the prefix is a zone name (form answers carry the zone)."""
    head, sep, rest = str(text).partition("-")
    return rest.strip() if sep and head.strip().casefold() in zones and rest.strip() else None


def area_units(units, area_id):
    """The units linked to an area, its main unit first."""
    linked = [u for u in units if area_id in u["area_ids"]]
    return sorted(linked, key=lambda u: (area_id not in u["primary_area_ids"], u["name"]))


def pick_unit(matches, area_id):
    """One match, preferring units linked to the target area, then active units. None when it stays unclear."""
    for narrowed in (matches, [u for u in matches if area_id in u["area_ids"]], [u for u in matches if u["active"]]):
        if len(narrowed) == 1:
            return narrowed[0]
    linked = [u for u in matches if area_id in u["area_ids"] and u["active"]]
    return linked[0] if len(linked) == 1 else None


def resolve_unit(text, label, area_id, units, zones):
    """(unit or None, how it was found, confident) for one Ward/Branch answer, old area label and mapped area.
    Confident only when the Ward/Branch answer itself names the unit."""
    text = historical.clean(text)
    variants = [v for v in [strip_zone(text, zones), text] if v]
    for key, how in (("norm", "Ward/Branch name matches"), ("base", "Ward/Branch name matches (ignoring language tag)")):
        for variant in variants:
            wanted = unit_norm(variant)
            found = pick_unit([u for u in units if u[key] == wanted], area_id)
            if found:
                return found, how, True
    source = strip_zone(label, zones) or label
    words = f" {unit_norm(source)} "
    found = pick_unit([u for u in units if u["base"] and f" {u['base']} " in words], area_id)
    why = "Ward/Branch is blank" if not text else "Ward/Branch name not recognised"
    if found:
        return found, f"{why}; taken from the old area name '{label}'", False
    linked = area_units(units, area_id)
    if linked:
        which = "only unit" if len(linked) == 1 else "main unit"
        return linked[0], f"{why}; used the mapped area's {which}", False
    return None, f"{why}; the mapped area has no unit", False
