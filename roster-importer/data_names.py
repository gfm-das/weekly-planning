"""Matching the zone and area names in an uploaded file to the portal's zones and areas.

Most names match by themselves (the Church's exports and the owner's sheets use the roster's names). The rest are
asked once on the upload preview and remembered in public.data_name_matches, for this upload and every later one.
An old zone or area that is no longer in the portal can be kept as a historical name: its rows are stored with the
name as written and no portal zone or area.
"""
import re
import unicodedata

from data_files import clean

LEVELS = ("zone", "area")


def fold(name):
    """A name in a form for comparing: lower case, no accents (Nürnberg = Nurnberg), ß = ss, no punctuation."""
    text = unicodedata.normalize("NFKD", clean(name)).replace("ß", "ss")
    text = "".join(ch for ch in text if not unicodedata.combining(ch)).casefold()
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def fold_zone(name):
    """Zones are also written as 'Moroni Zone': the word zone at the end does not count."""
    return re.sub(r"\s*\bzone$", "", fold(name)).strip()


class Matcher:
    """The portal's zones and areas of one mission and the remembered matches, read once per preview or apply."""

    def __init__(self, cur, mission_id):
        self.mission_id = mission_id
        cur.execute("select id,name,active from public.zones where mission_id=%s order by active desc,name", (mission_id,))
        self.zones = cur.fetchall()
        cur.execute("""select a.id,a.name,a.active,d.name district,z.id zone_id,z.name zone
          from public.areas a join public.districts d on d.id=a.district_id join public.zones z on z.id=d.zone_id
          where z.mission_id=%s order by a.active desc,z.name,d.name,a.name""", (mission_id,))
        self.areas = cur.fetchall()
        self.area_by_id = {a["id"]: a for a in self.areas}
        # Folded once here: a finding export asks about the same few area names tens of thousands of times.
        for zone in self.zones:
            zone["key"] = fold_zone(zone["name"])
        for area in self.areas:
            area["key"], area["zone_key"] = fold(area["name"]), fold_zone(area["zone"])
        self.answers = {}
        cur.execute("select level,source_key,zone_id,area_id,historical from public.data_name_matches where mission_id=%s",
                    (mission_id,))
        self.remembered = {(r["level"], r["source_key"]): r for r in cur.fetchall()}

    def zone(self, name):
        """('zone', id), ('historical', None) or ('ask', None) for a zone name from a file."""
        if not clean(name):
            return "historical", None
        saved = self.remembered.get(("zone", fold_zone(name)))
        if saved:
            return ("historical", None) if saved["historical"] else ("zone", saved["zone_id"])
        found = [z for z in self.zones if z["key"] == fold_zone(name)]
        return self.pick(found, "zone")

    def area(self, name, zone_name=""):
        """('area', id), ('historical', None) or ('ask', None) for an area name, with its zone from the file
        to tell apart two areas of the same name."""
        key = (fold(name), fold_zone(zone_name))
        if key not in self.answers:
            self.answers[key] = self.find_area(*key)
        return self.answers[key]

    def find_area(self, name_key, zone_key):
        saved = self.remembered.get(("area", name_key))
        if saved:
            return ("historical", None) if saved["historical"] else ("area", saved["area_id"])
        found = [a for a in self.areas if a["key"] == name_key]
        if len(found) > 1 and zone_key:
            found = [a for a in found if a["zone_key"] == zone_key] or found
        return self.pick(found, "area")

    @staticmethod
    def pick(found, level):
        """One match: use it. Several: a current (active) one wins when it is the only current one. Else ask."""
        if len(found) == 1:
            return level, found[0]["id"]
        active = [x for x in found if x["active"]]
        if len(active) == 1:
            return level, active[0]["id"]
        return "ask", None

    def zone_id_quietly(self, name):
        """The portal zone for a zone name, or None. Used for rows of historical areas: never asked."""
        answer, found = self.zone(name)
        return found if answer == "zone" else None


def place(matcher, record, level):
    """Adds zone_id and area_id to a record and says whether its name still needs a match ('ask').

    level 'area': the record's area is matched (its zone comes from the portal area); a record without an area
    name is matched by its zone instead. level 'zone': only the zone is matched."""
    area_name, zone_name = record.get("area", ""), record.get("zone", "")
    if level == "area" and clean(area_name):
        answer, area_id = matcher.area(area_name, zone_name)
        if answer == "area":
            record["area_id"], record["zone_id"] = area_id, matcher.area_by_id[area_id]["zone_id"]
            return None
        record["area_id"], record["zone_id"] = None, matcher.zone_id_quietly(zone_name)
        return ("area", area_name) if answer == "ask" else None
    record["area_id"] = None
    answer, zone_id = matcher.zone(zone_name)
    record["zone_id"] = zone_id if answer == "zone" else None
    return ("zone", zone_name) if answer == "ask" else None


def place_all(matcher, records, level):
    """Places every record. Returns the names still to match: {(level, name): {"rows": n, "zones": {...}}}."""
    questions = {}
    for record in records:
        ask = place(matcher, record, level)
        if ask:
            key = (ask[0], clean(ask[1]))
            entry = questions.setdefault(key, {"rows": 0, "zones": set()})
            entry["rows"] += 1
            if ask[0] == "area" and clean(record.get("zone")):
                entry["zones"].add(clean(record["zone"]))
    return questions


def remember(cur, mission_id, level, name, choice, actor):
    """Saves a manager's choice for a name: 'historical', 'zone:<id>' or 'area:<id>' (checked against this
    mission's zones and areas). Returns False for an empty or unknown choice."""
    if level not in LEVELS or not clean(name) or not choice:
        return False
    zone_id = area_id = None
    historical = choice == "historical"
    if not historical:
        kind, _, value = choice.partition(":")
        if kind != level or not value.isdigit():
            return False
        if level == "zone":
            cur.execute("select id from public.zones where id=%s and mission_id=%s", (int(value), mission_id))
            zone_id = (cur.fetchone() or {}).get("id")
        else:
            cur.execute("""select a.id from public.areas a join public.districts d on d.id=a.district_id
              join public.zones z on z.id=d.zone_id where a.id=%s and z.mission_id=%s""", (int(value), mission_id))
            area_id = (cur.fetchone() or {}).get("id")
        if not zone_id and not area_id:
            return False
    key = fold_zone(name) if level == "zone" else fold(name)
    cur.execute("""insert into public.data_name_matches
        (mission_id,level,source_key,source_name,zone_id,area_id,historical,confirmed_by,confirmed_at)
      values(%s,%s,%s,%s,%s,%s,%s,%s,now())
      on conflict (mission_id,level,source_key) do update set source_name=excluded.source_name,
        zone_id=excluded.zone_id,area_id=excluded.area_id,historical=excluded.historical,
        confirmed_by=excluded.confirmed_by,confirmed_at=now()""",
                (mission_id, level, key, clean(name)[:120], zone_id, area_id, historical, actor))
    return True
