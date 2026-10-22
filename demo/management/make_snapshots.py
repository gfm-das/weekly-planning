"""Makes the static pages of the demo's DA Management (demo/parts/management/*.html). Run it by hand; the result is committed,
so the demo build (node demo/build-demo.mjs) needs no Python and no database.

    python demo/parts/management/make_snapshots.py          (from the repository root)

It imports the REAL DA Management program (roster-importer/), replaces the database and the sign-in with invented stand-in
rows (zones Alpha, Beta, Gamma; "Elder Sample", "Sister Demo"; addresses at example.invalid), renders the real pages with
Flask's test client and writes them as plain HTML. The menu links point at the static files. Forms and buttons do nothing but
say "This is a demo with fake data. Nothing is saved." Needs the packages of roster-importer/requirements.txt (flask, psycopg2).
Nothing here is real: no name, address, number or key. The dates are fixed (end of September 2026).
"""
import os
import re
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

HERE = Path(__file__).resolve().parent
IMPORTER = HERE.parents[2] / "roster-importer"
sys.path.insert(0, str(IMPORTER))
os.environ["DATABASE_URL"] = "postgresql://nobody@127.0.0.1:1/none"
os.environ.setdefault("GFM_SECRET_KEY", "demo-not-a-secret")
os.chdir(IMPORTER)

import abilities  # noqa: E402
import abilities_page  # noqa: E402
import account_links  # noqa: E402
import account_manager  # noqa: E402
import app  # noqa: E402
import mappings_page  # noqa: E402
import page  # noqa: E402
import places  # noqa: E402
import places_admin  # noqa: E402
import planning_questions_pages  # noqa: E402
import retire  # noqa: E402
import roles  # noqa: E402
import staff_accounts  # noqa: E402
import updates_page  # noqa: E402
import web_links  # noqa: E402
import wiki_link  # noqa: E402

TZ = timezone.utc
NOW = datetime(2026, 9, 28, 9, 30, tzinfo=TZ)
MISSION = "Demo Mission"

# ------------------------------------------------------------------------------------------------ the invented data

PLACES = {  # zone -> district -> areas
    "Alpha": {"Alpha North": ["Alpha 1", "Alpha 2", "Alpha 3"], "Alpha South": ["Alpha 4", "Alpha 5"]},
    "Beta": {"Beta Central": ["Beta 1", "Beta 2", "Beta 3"], "Beta East": ["Beta 4", "Beta 5"]},
    "Gamma": {"Gamma West": ["Gamma 1", "Gamma 2"], "Gamma Hills": ["Gamma 3", "Gamma 4"]},
}
PEOPLE = [  # name, zone, district, area, roster position, leadership role, hand-set role, account state
    ("Elder Sample", "Alpha", "Alpha North", "Alpha 1", "SC", "ZL", "", "Active"),
    ("Elder Example", "Alpha", "Alpha North", "Alpha 1", "JC", "", "", "Active"),
    ("Sister Demo", "Alpha", "Alpha North", "Alpha 2", "SC", "DL", "", "Active"),
    ("Sister Placeholder", "Alpha", "Alpha North", "Alpha 2", "JC", "", "", "Invited"),
    ("Elder Fiction", "Alpha", "Alpha South", "Alpha 4", "SC", "DL", "", "Active"),
    ("Elder Imaginary", "Alpha", "Alpha South", "Alpha 4", "JC", "", "", "Missing"),
    ("Sister Pretend", "Beta", "Beta Central", "Beta 1", "SC", "STL", "", "Active"),
    ("Sister Mock", "Beta", "Beta Central", "Beta 1", "JC", "", "", "Active"),
    ("Elder Dummy", "Beta", "Beta Central", "Beta 2", "SC", "ZL", "", "Invited"),
    ("Elder Specimen", "Beta", "Beta Central", "Beta 2", "JC", "", "", "Unlinked"),
    ("Sister Model", "Beta", "Beta East", "Beta 4", "SC", "DL", "", "Active"),
    ("Sister Faux", "Beta", "Beta East", "Beta 4", "JC", "", "", "Missing"),
    ("Elder Trial", "Gamma", "Gamma West", "Gamma 1", "SC", "ZL", "", "Active"),
    ("Elder Prototype", "Gamma", "Gamma West", "Gamma 1", "JC", "", "", "Active"),
    ("Sister Draft", "Gamma", "Gamma Hills", "Gamma 3", "SC", "DL", "", "Disabled"),
    ("Sister Outline", "Gamma", "Gamma Hills", "Gamma 3", "JC", "", "", "No email"),
    ("Elder Staff-Sample", "Alpha", "Alpha North", "Alpha 3", "SC", "", "Data Analyst", "Active"),
]


def account_rows(_mission_id):
    rows = []
    for number, (name, zone, district, area, position, lead, hand, state) in enumerate(PEOPLE, start=1):
        slug = name.lower().replace(" ", ".")
        rows.append({"missionary_id": 9000 + number, "missionary_number": f"DEMO-{number:04d}", "display_name": name,
                     "last_name": name.split()[-1], "first_name": None, "email": None if state == "No email" else f"{slug}@example.invalid", "area": area, "district": district,
                     "zone": zone, "roster_position_abbr": position, "leadership_roles": lead, "account_roles": hand,
                     "account_status": state, "assignment_start": None})
    return rows


def staff_rows(_cur, profile_id=None):
    def row(n, name, role, active, signed_in):
        return {"id": f"00000000-0000-4000-8000-00000000000{n}", "app_role": role, "active": active, "display_name": name,
                "home_mission_id": 1, "updated_at": NOW, "additional_roles": [], "email": f"{name.lower().replace(' ', '.')}@example.invalid",
                "invited_at": NOW - timedelta(days=60), "last_sign_in_at": NOW - timedelta(days=2) if signed_in else None}
    return [row(1, "President Example", "PRESIDENT", True, True), row(2, "Office Sample", "OFFICE", True, True),
            row(3, "Analyst Demo", "DATA_ADMIN", True, True), row(4, "Office Placeholder", "OFFICE", True, False),
            row(5, "Office Retired", "OFFICE", False, True)]


def load_tree(_cur, _mission_id):
    tree = {"zone": {}, "district": {}, "area": {}}
    zone_id = district_id = area_id = 0
    for zone, districts in PLACES.items():
        zone_id += 1
        tree["zone"][zone_id] = {"id": zone_id, "name": zone, "active": True}
        for district, areas in districts.items():
            district_id += 1
            tree["district"][district_id] = {"id": district_id, "name": district, "active": True, "zone_id": zone_id}
            for area in areas:
                area_id += 1
                tree["area"][area_id] = {"id": area_id, "name": area, "active": True, "district_id": district_id,
                                         "serving": 2 if area_id % 4 else 0}
    zone_id += 1  # one closed zone, one closed district and one closed area, so the Reopen buttons show
    tree["zone"][zone_id] = {"id": zone_id, "name": "Delta (closed)", "active": False}
    district_id += 1
    tree["district"][district_id] = {"id": district_id, "name": "Delta Old", "active": False, "zone_id": zone_id}
    area_id += 1
    tree["area"][area_id] = {"id": area_id, "name": "Delta 1", "active": False, "district_id": district_id, "serving": 0}
    return tree


def current_areas(_cur):
    out = []
    ident = 0
    zone_id = district_id = 0
    for zone, districts in PLACES.items():
        zone_id += 1
        for district, areas in districts.items():
            district_id += 1
            for area in areas:
                ident += 1
                out.append({"id": ident, "name": area, "district_id": district_id, "district": district, "zone_id": zone_id, "zone": zone})
    return out


def mission_areas(_cur):
    """Every area, the closed "Delta 1" (zone "Delta (closed)") too."""
    areas = [{"id": a["id"], "name": a["name"], "zone": a["zone"], "active": True} for a in current_areas(None)]
    return areas + [{"id": 15, "name": "Delta 1", "zone": "Delta (closed)", "active": False}], list(PLACES) + ["Delta (closed)"]


MAPPINGS = [  # old label, target area id (or None), notes, confirmed, kind
    ("Alpha-Alpha 1", 1, "", True, "CONFIRMED"), ("Alpha Old Center", 2, "Renamed in 2025", True, "CONFIRMED"),
    ("Beta-Beta 2", 6, "", True, "CONFIRMED"), ("Beta Old North", 7, "Taken over by Beta 3", True, "CONFIRMED"),
    ("Beta Old South", 7, "One companionship served Beta 3 and Beta Old South", True, "COMBINED"),
    ("Delta (closed)-Delta 1", 15, "Closed in 2024", True, "CLOSED"), ("Delta 1", None, "", False, None),
    ("Gamma-Gamma 1", 11, "", False, "CONFIRMED"), ("Gamma Old Hill", None, "", False, None),
    # Round 21: new labels of a waiting upload get a suggestion (same name, without the zone prefix, similar spelling).
    ("Alpha-Alpha 3", None, "", False, None), ("Gama 4", None, "", False, None), ("Gamma 2", None, "", False, None),
]


def catalog(_cur):
    def section(i, key, title, text):
        return {"id": i, "section_key": key, "section_title": title, "description": text, "active": True, "display_order": i, "updated_at": NOW}
    sections = [section(1, "key_indicators_conversion", "Key indicators", "The six numbers that come first every week."),
                section(2, "other_goals", "Other goals", "Goals the area may add for the week."),
                section(3, "reflection", "Reflection", "Short answers for the week.")]
    sections.append({**section(4, "old_section", "Old section (retired)", "No longer on the form."), "active": False})

    def question(i, section_id, key, label, kind, required=True, protected=False, active=True, answered=0):
        return {"id": i, "section_id": section_id, "question_key": key, "question_label": label, "question_type": kind,
                "required": required, "protected": protected, "active": active, "answered": answered, "display_order": i,
                "updated_at": NOW, "help_text": "", "hidden_value": None}
    questions = [
        question(1, 1, "new_people_goal", "New people to find this week", "NUMBER", protected=True, answered=312),
        question(2, 1, "lessons_goal", "Lessons to teach this week", "NUMBER", protected=True, answered=312),
        question(3, 1, "baptismal_date_goal", "People to set a baptismal date with", "NUMBER", protected=True, answered=298),
        question(4, 2, "service_projects_goal", "Service projects to hold", "NUMBER", required=False, answered=120),
        question(5, 2, "member_visits_plan", "Plan for visiting members", "LONG_TEXT", required=False, answered=96),
        question(6, 3, "week_highlight", "Best moment of the week", "TEXT", required=False, answered=210),
        question(7, 3, "need_help", "Does the area need help from the district?", "BOOLEAN", answered=205),
        question(8, 4, "old_question", "A question that is retired", "TEXT", required=False, active=False, answered=14),
    ]
    return sections, questions, []


def retired_questions(_cur):
    return [{"question_key": "old_question", "question_label": "A question that is retired", "question_type": "TEXT", "answers": 14},
            {"question_key": "old_goal", "question_label": "Another retired question", "question_type": "NUMBER", "answers": 0}]


def closed_places(_cur, _mission_id):
    return [{"level": "zone", "id": 4, "name": "Delta (closed)", "parent": ""},
            {"level": "district", "id": 7, "name": "Delta Old", "parent": "Delta (closed)"},
            {"level": "area", "id": 15, "name": "Delta 1", "parent": "Delta (closed) / Delta Old"}]


def ability_screen():
    table = roles.parse_ability_rows([(role, ability, allowed) for (role, ability), allowed in roles.DEFAULT_ABILITIES.items()])
    batch = lambda n, when, who, note, cells: {"batch": f"00000000-0000-4000-8000-0000000001{n:02d}", "when": when, "who": who,
                                               "note": note, "reverts": None, "cells": cells, "reverted": False}
    log = [batch(2, NOW - timedelta(days=3), "Analyst Demo", "Office may publish announcements", [("OFFICE", "announcements.publish", False, True)]),
           batch(1, NOW - timedelta(days=21), "President Example", "", [("ZL", "plans.unlock", False, True)])]
    log[1]["reverted"] = False
    return table, log


STATUS = {  # the updater's status file, invented
    "updater_seen_at": NOW.isoformat(), "state": "idle", "follows": "Track: tags", "checked_at": (NOW - timedelta(hours=3)).isoformat(),
    "check_result": "updates", "can_update": True,
    "current": {"date": "2026-09-14T10:00:00+00:00", "subject": "Release v1.4.0 (demo)", "short": "a1b2c3d"},
    "remote": {"commit": "d4e5f6a7b8c9"},
    "new_changes": [{"date": "2026-09-24T12:00:00+00:00", "subject": "Call-ins shows the last four weeks", "short": "d4e5f6a"},
                    {"date": "2026-09-21T08:00:00+00:00", "subject": "Calendar: month view on phones", "short": "c3d4e5f"}],
    "last_update": {"result": "done", "finished_at": "2026-09-14T10:20:00+00:00", "from": "9f8e7d6c5b4a", "to": "a1b2c3d4e5f6"},
}

BATCHES = [  # id, filename, kind, minutes ago, actor, status
    ("Roster transfer 2026-09-27", "ROSTER", 1500, "Analyst Demo", "APPLIED"), ("Staff account - Office Sample", "ACCOUNT", 3200, "President Example", "APPLIED"),
    ("area-data-demo.csv", "AREA_DATA", 6000, "Analyst Demo", "APPLIED"), ("people-demo.csv", "PEOPLE", 9800, "Analyst Demo", "APPLIED"),
    ("historical-demo.csv", "HISTORICAL", 14500, "Analyst Demo", "UNDONE"), ("Role change - Elder Example", "ACCOUNT", 21000, "Sister Demo", "APPLIED"),
]


def batch_rows():
    return [{"id": f"00000000-0000-4000-8000-0000000002{n:02d}", "filename": name, "kind": kind, "created_at": NOW - timedelta(minutes=minutes),
             "actor": actor, "status": status, "mission_id": 1} for n, (name, kind, minutes, actor, status) in enumerate(BATCHES)]


class FakeCursor:
    """Answers the few questions the pages ask that are not replaced above."""

    def __init__(self):
        self.rows = []

    def execute(self, query, params=None):
        q = " ".join(str(query).split()).lower()
        self.rows = []
        if "distinct on (kind)" in q:
            seen = {}
            for b in batch_rows():
                if b["status"] == "APPLIED" and b["kind"] not in seen:
                    seen[b["kind"]] = b
            self.rows = list(seen.values())
        elif "from public.roster_import_batches" in q:
            self.rows = batch_rows()
        elif "import_weekly_planning_area_map" in q:
            self.rows = [{"source_companionship": s, "target_area_id": t, "notes": n, "confirmed_at": NOW if c else None,
                          "current_target_name": None, "mission_id": 1, "match_status": k} for s, t, n, c, k in MAPPINGS]
        elif "from public.missions" in q:
            self.rows = [{"name": MISSION}]

    def fetchall(self):
        return self.rows

    def fetchone(self):
        return self.rows[0] if self.rows else None


# ------------------------------------------------------------------------------------------------ the static pages

# The real address -> the static file. Anything else that points at a page of the real program says "not in this demo".
FILES = {"/uploads": "index.html", "/accounts": "people.html", "/staff": "staff.html", "/abilities": "abilities.html",
         "/places": "places.html", "/mappings": "mappings.html", "/planning-questions": "planning-questions.html",
         "/retire": "retire.html", "/imports": "history.html", "/updates": "updates.html", "/links": "links.html"}

HEAD_SCRIPT = """<script>/* demo: the theme from the portal (same place the portal keeps it), before the first paint */(function(){var t="mission";try{var s=JSON.parse(localStorage.getItem("gfm_portal_layout_v1")||"{}");if(s&&/^(mission|light|dark)$/.test(s.theme))t=s.theme}catch(e){}document.documentElement.setAttribute("data-theme",t)})()</script>"""
DEMO_SCRIPT = """<script>/* demo: nothing is saved */(function(){
var box;function say(){if(!box){box=document.createElement("div");box.setAttribute("role","status");
box.setAttribute("style","position:fixed;left:50%;bottom:64px;transform:translateX(-50%);z-index:99;max-width:90vw;background:#b45309;color:#fff;padding:10px 16px;border-radius:12px;font:700 13px system-ui,sans-serif;box-shadow:0 4px 16px #0005;display:none");
box.textContent="This is a demo with fake data. Nothing is saved.";document.body.appendChild(box)}
box.style.display="block";clearTimeout(box.t);box.t=setTimeout(function(){box.style.display="none"},3500)}
document.addEventListener("submit",function(e){e.preventDefault();say()},true);
document.addEventListener("click",function(e){var b=e.target.closest&&e.target.closest("button,input[type=submit],a[data-demo]");if(!b||b.type==="button"&&!b.closest("form")&&!b.hasAttribute("data-demo"))return;
if(b.tagName==="A"||b.closest("form")&&b.type!=="button"){e.preventDefault();e.stopImmediatePropagation();say()}},true);
document.addEventListener("change",function(e){if(e.target.type==="file"){e.target.value="";say()}},true);
addEventListener("message",function(e){if(e.data&&e.data.type==="portal-theme"&&/^(mission|light|dark)$/.test(e.data.theme)){try{document.documentElement.setAttribute("data-theme",e.data.theme)}catch(x){}}});
})()</script>"""


def make_static(html):
    """The real page with its menu and links pointing at the static files, no database-only parts and the demo scripts."""
    # The portal's translation script: the demo ships it one folder up (the loader line of the real frame looks for port 8070).
    html = re.sub(r"<script>/\* Interface translation.*?</script>", '<script src="../i18n.js"></script>', html, count=1, flags=re.S)
    html = html.replace("<head>", "<head>" + HEAD_SCRIPT, 1)
    html = re.sub(r'<input type="hidden" name="csrf_token" value="[^"]*">', "", html)

    def link(found):
        address = found.group(3)
        quote = found.group(2)
        path = address.split("?")[0].split("#")[0]
        if path in FILES:
            return f'{found.group(1)}{quote}{FILES[path]}{quote}'
        if path == "/":
            return f'{found.group(1)}{quote}index.html{quote}'
        return f'{found.group(1)}{quote}#{quote} data-demo="1"'

    html = re.sub(r"""(<a\b[^>]*?\bhref=)(["'])(/[^"']*)\2""", link, html)
    return html.replace("</body>", DEMO_SCRIPT + "</body>")


def render(client, path):
    response = client.get(path)
    if response.status_code != 200:
        sys.exit(f"{path}: {response.status_code}")
    return make_static(response.get_data(as_text=True))


def main():
    fake = FakeCursor()
    conn = MagicMock()
    patches = [
        patch("sign_in.allowed", return_value=True), patch("sign_in.current_mission_id", return_value=1),
        patch("sign_in.portal_person", return_value=("Sister Demo", "00000000-0000-4000-8000-000000000999")),
        patch("database.connect"), patch("database.cursor"),
        patch.object(account_manager, "account_rows", account_rows), patch.object(account_links, "with_linked_sign_ins", lambda rows: rows),
        patch.object(staff_accounts, "staff_rows", staff_rows), patch.object(places_admin, "load_tree", load_tree),
        patch.object(places, "current_areas", current_areas), patch.object(mappings_page, "mission_areas", mission_areas),
        patch.object(mappings_page.historical_separate, "summed_labels", lambda _cur: {"beta old south": 4}),
        patch.object(planning_questions_pages, "load_catalog", catalog), patch.object(retire, "retired_questions", retired_questions),
        patch.object(retire, "closed_places", closed_places), patch.object(abilities_page, "read_screen", ability_screen),
        patch.object(updates_page, "read_status", lambda: STATUS), patch.object(updates_page, "request_waiting", lambda: False),
        patch.object(web_links.settings, "WEB_SERVICE_URLS",
                     {"gmail": "https://myaccount.google.com/apppasswords", "porkbun": "https://porkbun.com/", "cloudflare": "https://dash.cloudflare.com/"}),
        patch.object(wiki_link, "current_address", lambda: ("../wiki/index.html", False)),
    ]
    started = [p.start() for p in patches]
    started[3].return_value.__enter__.return_value = conn
    started[4].return_value.__enter__.return_value = fake
    try:
        client = app.app.test_client()
        with client.session_transaction() as session:
            session["portal_role"] = "DATA_ADMIN"
            session["portal_user"] = "Sister Demo"
            session["portal_user_id"] = "00000000-0000-4000-8000-000000000999"
        for path, name in FILES.items():
            (HERE / name).write_text(render(client, path), encoding="utf-8", newline="\n")
            print("wrote", name)
    finally:
        for p in patches:
            p.stop()


if __name__ == "__main__":
    main()
