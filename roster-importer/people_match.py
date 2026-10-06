"""People in uploads: working out who is the same person (no database writes except saving a manager's answer).

An upload names the same new member or friend again and again (one row per week). Before anything is saved this file:
  1. groups the rows of the upload into PEOPLE: same kind, same area, same name (capitals, accents and punctuation do
     not count). Two people with different known baptism dates are never the same person;
  2. looks at the people already stored (typed in by hand, or from an earlier upload) and decides for each pair:
       - same name, same area, no clashing date  -> the same person (joined without asking);
       - same name in another area, or a very similar name in the same area -> ASK the manager;
       - anything else -> different people;
  3. remembers each answer in people_match_decisions, so a pair is asked once.
A new member who was first a friend with a baptismal date (same name, same area) is linked to that friend's record.

The pages that ask are in people_pages.py; the saving is in people_write.py. High-potential friends are only a name on
a weekly plan: they are never matched.
"""
import difflib
from datetime import date

import data_names

NEW_MEMBER, FRIEND = "new_member", "baptismal"
KIND_CODE = {NEW_MEMBER: "nm", FRIEND: "bd"}
NAME_LIKE = 0.86  # how alike two names in one area must be to be asked about


def fold(name):
    """A name in a form for comparing: lower case, no accents, ß = ss, no punctuation."""
    return data_names.fold(name)


def split_name(full):
    """'Anna Maria Meier' -> ('Anna Maria', 'Meier'); one word -> (word, None)."""
    parts = " ".join(str(full or "").split()).split(" ")
    parts = [p for p in parts if p]
    if len(parts) < 2:
        return (parts[0] if parts else ""), None
    return " ".join(parts[:-1]), parts[-1]


def person_key(kind, area_id, folded, bapt=None):
    """The key of a person of the upload: 'p:nm:12:anna meier' (plus ':2026-05-31' when the baptism date is known)."""
    return f"p:{KIND_CODE[kind]}:{area_id}:{folded}" + (f":{bapt}" if bapt else "")


def stored_key(kind, person_id):
    return f"id:{KIND_CODE[kind]}:{person_id}"


def pair_key(a, b):
    """The two keys of a pair in a fixed order (as people_match_decisions stores them)."""
    return (a, b) if a < b else (b, a)


# ------------------------------------------------------------------------------------------ people of the upload

def group_people(appearances):
    """The people of an upload. appearances: dicts with kind, name (full), first, last, area_id, unit_id, sunday
    (date or None), baptism_date (date or None) and anything else to keep. Returns a list of people:
    {key, kind, area_id, folded, first, last, baptism_date, unit_id, appearances, first_seen, last_seen}."""
    people = {}
    for item in appearances:
        folded = fold(item["name"])
        if not folded:
            continue
        key = person_key(item["kind"], item["area_id"], folded, item.get("baptism_date"))
        person = people.get(key)
        if person is None:
            person = people[key] = {"key": key, "kind": item["kind"], "area_id": item["area_id"], "folded": folded,
                                    "first": item["first"], "last": item["last"], "baptism_date": item.get("baptism_date"),
                                    "unit_id": None, "appearances": [], "stored_id": None}
        person["appearances"].append(item)
    for person in people.values():
        person["appearances"].sort(key=lambda a: (a.get("sunday") or date.min, a.get("order") or 0))
        dated = [a for a in person["appearances"] if a.get("sunday")]
        person["first_seen"] = dated[0]["sunday"] if dated else None
        person["last_seen"] = dated[-1]["sunday"] if dated else None
        units = [a["unit_id"] for a in person["appearances"] if a.get("unit_id")]
        person["unit_id"] = units[-1] if units else None
    return list(people.values())


# ------------------------------------------------------------------------------------------ people already stored

def stored_people(cur, mission_id):
    """New members and friends already in the database (this mission): same shape as group_people's people, with
    stored_id set. Their area is the area they are assigned to now."""
    out = []
    cur.execute("""select nm.id,nm.first_name,nm.last_name,nm.display_name,nm.baptism_date,a.area_id,a.unit_id
      from public.new_members nm
      join public.new_member_area_assignments a on a.new_member_id=nm.id and a.end_date is null
      join public.areas ar on ar.id=a.area_id join public.districts d on d.id=ar.district_id
      join public.zones z on z.id=d.zone_id where z.mission_id=%s""", (mission_id,))
    for r in cur.fetchall():
        out.append(stored_person(NEW_MEMBER, r, r["baptism_date"]))
    cur.execute("""select f.id,f.first_name,f.last_name,f.display_name,a.area_id,a.unit_id
      from public.baptismal_date_people f
      join public.baptismal_date_person_area_assignments a on a.baptismal_date_person_id=f.id and a.end_date is null
      join public.areas ar on ar.id=a.area_id join public.districts d on d.id=ar.district_id
      join public.zones z on z.id=d.zone_id where z.mission_id=%s""", (mission_id,))
    for r in cur.fetchall():
        out.append(stored_person(FRIEND, r, None))
    return out


def stored_person(kind, row, baptism_date):
    return {"key": stored_key(kind, row["id"]), "kind": kind, "area_id": row["area_id"], "folded": fold(row["display_name"]),
            "first": row["first_name"], "last": row["last_name"], "baptism_date": baptism_date, "unit_id": row["unit_id"],
            "appearances": [], "stored_id": row["id"], "first_seen": None, "last_seen": None, "label": row["display_name"]}


# ------------------------------------------------------------------------------------------ remembered answers

def load_decisions(cur, mission_id):
    """{(key_a, key_b): True (same person) or False (different people)} of this mission."""
    cur.execute("select key_a,key_b,same from public.people_match_decisions where mission_id=%s", (mission_id,))
    return {(r["key_a"], r["key_b"]): r["same"] for r in cur.fetchall()}


def save_decision(cur, mission_id, key_a, key_b, same, actor):
    """Remembers one answer. Returns False for keys that are not person keys."""
    if not (valid_key(key_a) and valid_key(key_b)) or key_a == key_b:
        return False
    a, b = pair_key(key_a, key_b)
    cur.execute("""insert into public.people_match_decisions(mission_id,key_a,key_b,same,decided_by)
      values(%s,%s,%s,%s,%s) on conflict(mission_id,key_a,key_b) do update set same=excluded.same,
      decided_by=excluded.decided_by,decided_at=now()""", (mission_id, a, b, bool(same), actor))
    return True


def valid_key(key):
    return isinstance(key, str) and len(key) < 300 and key.startswith(("p:nm:", "p:bd:", "id:nm:", "id:bd:"))


# ------------------------------------------------------------------------------------------ deciding

def dates_clash(a, b):
    """Both baptism dates are known and differ: two different people (a person is baptized once)."""
    return bool(a["baptism_date"] and b["baptism_date"] and a["baptism_date"] != b["baptism_date"])


def on_same_plan(a, b):
    """Both are named on the same weekly plan of the upload: one form lists two different people, so they are not one."""
    plans = {x.get("target") for x in a["appearances"] if x.get("target")}
    return any(x.get("target") in plans for x in b["appearances"])


def similar_names(a, b):
    """Very alike but not the same: a word more or less ('Maria Muller' / 'Maria Anna Muller'), or a typo."""
    if a == b:
        return False
    wa, wb = a.split(), b.split()
    small, large = (wa, wb) if len(wa) <= len(wb) else (wb, wa)
    if len(small) >= 2 and set(small) <= set(large):
        return True
    return difflib.SequenceMatcher(None, a, b).ratio() >= NAME_LIKE


def classify_pair(a, b, decisions):
    """'same', 'ask' or None (different) for two people of the same kind; at least one is from the upload."""
    answer = decisions.get(pair_key(a["key"], b["key"]))
    if answer is not None:
        return "same" if answer else None
    if dates_clash(a, b) or on_same_plan(a, b):
        return None
    if a["folded"] == b["folded"]:
        return "same" if a["area_id"] == b["area_id"] else "ask"
    if a["area_id"] == b["area_id"] and similar_names(a["folded"], b["folded"]):
        return "ask"
    return None


def resolve(upload_people, stored, decisions, area_names=None):
    """The result of matching.
    groups: the people to save, each {kind, members (people of the upload, joined), stored_id (or None), area_id,
            unit_id, first, last, baptism_date, appearances (all of the members, oldest first), bapt_from (a friend
            group or stored friend id this new member was before, or None)}.
    questions: the pairs still to ask: {a, b (people), reason}, each pair once, sorted.
    notices: lines to read (for example two stored people matched one person)."""
    area_names = area_names or {}
    pool = list(upload_people) + list(stored)
    by_key = {p["key"]: p for p in pool}
    parent = {p["key"]: p["key"] for p in pool}

    def find(k):
        while parent[k] != k:
            parent[k] = parent[parent[k]]
            k = parent[k]
        return k

    questions, notices, seen = [], [], set()
    buckets_exact, buckets_area = {}, {}
    for p in pool:
        buckets_exact.setdefault((p["kind"], p["folded"]), []).append(p)
        buckets_area.setdefault((p["kind"], p["area_id"]), []).append(p)
    candidate_pairs = {}
    for bucket in list(buckets_exact.values()) + list(buckets_area.values()):
        for i, a in enumerate(bucket):
            for b in bucket[i + 1:]:
                if a["stored_id"] and b["stored_id"]:
                    continue  # two stored people are never joined here
                candidate_pairs[pair_key(a["key"], b["key"])] = (a, b)
    for key in sorted(candidate_pairs):
        a, b = candidate_pairs[key]
        verdict = classify_pair(a, b, decisions)
        if verdict == "same":
            ra, rb = find(a["key"]), find(b["key"])
            if ra != rb:
                parent[rb] = ra
        elif verdict == "ask" and key not in seen:
            seen.add(key)
            questions.append({"a": a, "b": b, "keys": key,
                              "reason": "same_name_other_area" if a["folded"] == b["folded"] else "alike_name"})
    # Joined people -> groups.
    members = {}
    for p in upload_people:
        members.setdefault(find(p["key"]), []).append(p)
    stored_of = {}
    for p in stored:
        root = find(p["key"])
        if root in members:
            stored_of.setdefault(root, []).append(p)
    groups = []
    for root, people in members.items():
        owners = sorted(stored_of.get(root, []), key=lambda s: s["stored_id"])
        if len(owners) > 1:
            notices.append("Two stored people look like " + people[0]["first"] + ": the older record is used.")
        appearances = sorted((a for p in people for a in p["appearances"]),
                             key=lambda a: (a.get("sunday") or date.min, a.get("order") or 0))
        newest = max(people, key=lambda p: (p["last_seen"] or date.min))
        dates = [p["baptism_date"] for p in people if p["baptism_date"]]
        groups.append({"kind": people[0]["kind"], "members": people, "stored_id": owners[0]["stored_id"] if owners else None,
                       "area_id": newest["area_id"], "unit_id": newest["unit_id"], "first": newest["first"],
                       "last": newest["last"], "baptism_date": dates[0] if dates else None,
                       "appearances": appearances, "bapt_from": None, "keys": [p["key"] for p in people]})
    link_friends_to_new_members(groups, stored)
    questions.sort(key=lambda q: q["keys"])
    return {"groups": groups, "questions": questions, "notices": notices}


def link_friends_to_new_members(groups, stored):
    """A new member with the same name and area as a friend with a baptismal date was that friend: set bapt_from to
    the friend's group (in this upload) or stored friend id. Only the first match counts."""
    friends = [g for g in groups if g["kind"] == FRIEND]
    stored_friends = [s for s in stored if s["kind"] == FRIEND]
    for group in groups:
        if group["kind"] != NEW_MEMBER:
            continue
        names = {(p["area_id"], p["folded"]) for p in group["members"]}
        for friend in friends:
            if any((p["area_id"], p["folded"]) in names for p in friend["members"]):
                group["bapt_from"] = friend
                break
        else:
            for s in stored_friends:
                if (s["area_id"], s["folded"]) in names:
                    group["bapt_from"] = s["stored_id"]
                    break
