"""TEST ONLY: the portal's Weekly Planning and Overview pages over made-up people, for browser checks without a
database and without personal data.

Serves portal/ (mounted at /portal) on port 8080 and answers the /api/ calls planning.html and home.html make. It
uses this worktree's planning.py for the checks and wording (validation, the submit check, the reasons, the key
indicator names), so the page shows the real messages. Every change is kept in memory; POST /__reset starts again,
/__complete answers every person question, /__no_new_members takes every new member off the plan (and the area's
list stays empty, as for an area with no new members yet), /__fail_saves makes every save fail and offers a second
ward or branch (for the "not saved" and "not changed" messages), /__many_sections adds five more question sections
like the mission's own (for the section bar check, tests/edge_planning_nav.ps1). Bearer tokens are not checked.
Supabase is never contacted.

  docker run --rm --name gfm-test-<stream>-planning --memory 256m -p 127.0.0.1:18197:8080 \
      -v <repo>/portal-api:/app -v <repo>/portal:/portal:ro -w /app gfm-portal-portal-api python tests/planning_stub_api.py
Then open http://127.0.0.1:18197/planning.html?portal_token=stub or /home.html?portal_token=stub
(see tests/edge_planning_wording.ps1).
"""
import json
import re
import sys
from copy import deepcopy
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, "/app")
import helpers  # noqa: E402
import planning  # noqa: E402

UNITS = [{"unit_id": 5, "unit": "Sample Ward", "unit_type": "WARD", "primary_unit": True}]
SECOND_UNIT = {"unit_id": 6, "unit": "Sample Branch", "unit_type": "BRANCH", "primary_unit": False}
INDICATOR = next(row for row in planning.KEY_INDICATORS if row[0] == "friends_found")
QUESTIONS = [
    # The wording of the live planning form (round 6: the translation screenshots show it translated).
    {"section_key": "key_indicators_conversion", "section_title": "Key Indicators of Conversion",
     "section_description": "How the people you are teaching progressed this week, and your goals and plans for next week.",
     "question_key": "friends_found_actual", "question_label": "New People Being Taught — Actual", "question_type": "NUMBER",
     "required": True, "help_text": None},
]


def _question(section_key, title, key, label, kind="NUMBER", required=False):
    return {"section_key": section_key, "section_title": title, "section_description": "Made-up questions for a test.",
            "question_key": key, "question_label": label, "question_type": kind, "required": required, "help_text": None}


# Five more sections with the mission's section names and made-up questions (/__many_sections).
MORE_SECTIONS = [
    _question("social_media", "Social Media", "posts_shared", "Posts shared"),
    _question("social_media", "Social Media", "online_lessons", "Lessons taught online"),
    _question("social_media", "Social Media", "online_plan", "Online plan for next week", "LONG_TEXT"),
    _question("member_work", "Member Work", "member_meals", "Meals with members", required=True),
    _question("member_work", "Member Work", "member_visits", "Visits with members"),
    _question("member_work", "Member Work", "member_plan", "Plan with members", "LONG_TEXT"),
    _question("ward_coordination", "Ward Coordination", "gemiko_held", "GEMIKO held this week", "TEXT"),
    _question("ward_coordination", "Ward Coordination", "gemiko_notes", "Who came, and what was decided", "LONG_TEXT"),
    _question("youth_service", "Youth Service", "youth_activities", "Youth activities"),
    _question("youth_service", "Youth Service", "service_hours", "Service hours"),
    _question("weekly_plans", "Weekly Plans", "next_week_plan", "Your plan for the coming week", "LONG_TEXT"),
    _question("weekly_plans", "Weekly Plans", "information_up_chain", "Information for leaders (optional)", "LONG_TEXT"),
]
NM_EMPTY = {key: None for key in planning.PEOPLE_FIELDS["new_members"]}
PEOPLE = {
    "new_members": [
        {**NM_EMPTY, "id": 11, "new_member_id": 7, "display_name": "Lena Vogel", "is_current": True, "on_submitted_plan": True,
         "lessons_actual": 2, "lessons_goal": 3, "pmg_lessons_percentage": 40, "how_are_they_doing": "Coming every week.",
         "reading": True, "next_ordinance": "TB", "has_calling": "no",
         "person": {"first_name": "Lena", "last_name": "Vogel", "baptism_date": "2026-08-30", "confirmation_date": "2026-09-06",
                    "baptismal_date_extended": "2026-08-01", "finding_source": "Member/Member", "date_of_birth": "1990-05-02",
                    "age_range": "31-45", "gender": "Female", "marital_status": "Single", "child_dependents": 0,
                    "living_situation": "Student", "native_language": "German", "second_language": None,
                    "mission_language_competency": "Native Born/raised", "country_of_origin": "Germany",
                    "conversion_success_notes": "The ward council helped."}},
        {**NM_EMPTY, "id": 12, "new_member_id": 8, "display_name": "Jonas Weber", "is_current": True, "on_submitted_plan": False,
         "person": {"first_name": "Jonas", "last_name": "Weber", "baptism_date": "2026-09-20", "confirmation_date": None,
                    "finding_source": "Media/Referral"}},
    ],
    "baptismal_friends": [
        {"id": 31, "baptismal_date_person_id": 9, "display_name": "Mia Klein", "is_current": True, "on_submitted_plan": True,
         "baptismal_date_set_on": "2026-09-06", "current_baptismal_date": "2026-10-11", "reading": True, "praying": None,
         "at_church_this_sunday": None, "keeping_commandments": None, "member_involvement": None,
         "person": {"first_name": "Mia", "last_name": "Klein", "finding_source": "Member/Member"}},
        {"id": 32, "baptismal_date_person_id": 10, "display_name": "Tom Braun", "is_current": True, "on_submitted_plan": False,
         "baptismal_date_set_on": None, "current_baptismal_date": None, "reading": None, "praying": None,
         "at_church_this_sunday": None, "keeping_commandments": None, "member_involvement": None,
         "person": {"first_name": "Tom", "last_name": "Braun", "finding_source": None}},
    ],
    "high_potential": [
        {"id": 21, "name": "Anna", "at_church_this_sunday": True, "notes": "Met at the ward party."},
        {"id": 22, "name": planning.HIGH_POTENTIAL_PLACEHOLDER, "at_church_this_sunday": None, "notes": None},
    ],
}
STATE = {}
TARGETS = {"current_area_id": 147, "areas": [
    {"zone_id": 1, "zone": "North", "district_id": 11, "district": "Riverside", "area_id": 147, "area": "Riverside North",
     "units": [{"unit_id": 5, "unit": "Sample Ward"}, {"unit_id": 6, "unit": "Sample Branch"}]},
    {"zone_id": 1, "zone": "North", "district_id": 11, "district": "Riverside", "area_id": 148, "area": "Riverside South",
     "units": [{"unit_id": 7, "unit": "South Ward"}]},
]}


def reset():
    STATE.clear()
    STATE.update(people=deepcopy(PEOPLE), answers={"friends_found_actual": 3}, status="DRAFT", next=100,
                 units=list(UNITS), fail_saves=False, questions=list(QUESTIONS))


def form():
    return {"units": STATE["units"], "report": {"report_id": 1, "unit_id": 5, "status": STATE["status"], "sunday": "2026-09-27",
                                       "planning_due_at": None, "submitted_at": None, "updated_at": None},
            "questions": STATE["questions"], "answers": STATE["answers"], "people": STATE["people"],
            "available_people": {"new_members": [], "baptismal_friends": [{"id": 50, "display_name": "Sara Lang"}]},
            "catalog_version": 1,
            "person_options": {**{key: list(values) for key, values in planning.PERSON_CHOICES.items()},
                               "new_member_required": list(planning.NEW_MEMBER_REQUIRED)},
            "can_edit": STATE["status"] == "DRAFT"}


def overview():
    """What /api/overview answers for a district leader: the six key indicators with planning.py's names."""
    indicators = [{"key": key, "label": label, "goal": 4 + index, "actual": 2 + index, "units": []}
                  for index, (key, label, *_rest) in enumerate(planning.KEY_INDICATORS)]
    areas = [{"area_id": 147, "area": "Riverside North", "district": "Riverside", "zone": "North", "complete": True,
              "completed_units": 1, "unit_count": 1, "reports": [{"report_id": 1, "unit": "Sample Ward", "status": "SUBMITTED"}]},
             {"area_id": 148, "area": "Riverside South", "district": "Riverside", "zone": "North", "complete": False,
              "completed_units": 0, "unit_count": 1, "reports": [{"report_id": 2, "unit": "South Ward", "status": "DRAFT"}]}]
    return {"assignment": {"display_name": "Elder Sample", "role": "DL", "role_label": "DL", "area": "Riverside North",
                           "district": "Riverside", "zone": "North", "units": UNITS, "companions": []},
            "planning": {"week": {"sunday": "2026-09-27"}, "status": "DRAFT", "complete": False, "completed_units": 0,
                         "unit_count": 1, "key_indicators": indicators, "other_goals": [], "action_plans": [],
                         "weekly_action_plans": [], "reports": [], "recent_weeks": []},
            "stewardship": {"scope": "district", "label": "District planning", "total_areas": 2, "complete_areas": 1,
                            "incomplete_areas": 1, "areas": areas},
            "events": [], "announcements": [], "mission_focus": {"focus": None, "can_edit": False},
            "inspiration": {"source": "Mission thought",
                            "text": "Every number is a person. Ask how they are doing before asking how many."}}


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory="/portal", **kwargs)

    def log_message(self, *args):
        pass

    def end_headers(self):
        self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def reply(self, status, body):
        data = json.dumps(helpers.json_ready(body)).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def body(self):
        length = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(length) or b"{}") if length else {}

    def do_GET(self):
        if self.path.startswith("/api/planning/form"):
            return self.reply(200, form())
        if self.path.startswith("/api/planning/transfer-targets"):
            return self.reply(200, TARGETS)
        if self.path.startswith("/api/overview"):
            return self.reply(200, overview())
        if self.path.startswith("/api/"):
            return self.reply(404, {"error": "Not in the stub."})
        return super().do_GET()

    def do_PUT(self):
        body = self.body()
        if STATE["fail_saves"]:
            return self.reply(503, {"error": "The planning service is not reachable right now."})
        if self.path.endswith("/answers"):
            STATE["answers"].update({k: v for k, v in body["answers"].items() if k not in ("changes_only", "catalog_version")})
            return self.reply(200, {"ok": True, "report_id": 1, "answers": STATE["answers"]})
        if self.path.endswith("/people"):
            try:
                for group, rows in body["people"].items():
                    if group == "changes_only":
                        continue
                    for row in rows:
                        target = next((p for p in STATE["people"][group] if p["id"] == row["id"]), None)
                        if row.get("removed"):
                            STATE["people"][group] = [p for p in STATE["people"][group] if p["id"] != row["id"]]
                        elif target:
                            for key, value in row.items():
                                if key in planning.PEOPLE_FIELDS[group]:
                                    target[key] = planning._person_value(key, value)
            except ValueError as error:
                return self.reply(400, {"error": str(error)})
            return self.reply(200, {"ok": True, "report_id": 1, "missing": [], "removed": [], "people": STATE["people"]})
        return self.reply(404, {"error": "Not in the stub."})

    def do_POST(self):
        body, path = self.body(), self.path
        if path == "/api/planning/reports/1/submit":
            missing = planning._missing_person_fields(STATE["people"])
            if missing:
                error = planning.PeopleIncomplete(missing)
                return self.reply(400, {"error": str(error), "fields": error.fields})
            STATE["status"] = "SUBMITTED"
            return self.reply(200, {"report_id": 1, "status": "SUBMITTED", "shared": True})
        match = re.fullmatch(r"/api/planning/reports/1/people/(\w+)/(\d+)/(\w+)", path)
        if match:
            return self.person_action(match.group(1), int(match.group(2)), match.group(3), body)
        match = re.fullmatch(r"/api/planning/reports/1/people/(\w+)", path)
        if match:
            return self.add_person(match.group(1), body)
        if path == "/__complete":
            full = {"new_members": {"lessons_actual": 1, "lessons_goal": 2, "pmg_lessons_percentage": 40,
                                    "how_are_they_doing": "Well", "at_church_this_sunday": True, "reading": True,
                                    "praying": True, "member_involvement": True, "discussed_in_gemiko": False,
                                    "next_ordinance": "TB", "has_calling": "no", "has_aaronic_priesthood": "yes",
                                    "has_melchizedek_priesthood": "no", "ministers_to_someone": "no",
                                    "ministered_to_by_someone": True, "has_active_temple_recommend": "no",
                                    "visited_temple_for_baptisms": "no"},
                    "baptismal_friends": {"baptismal_date_set_on": "2026-09-06", "current_baptismal_date": "2026-10-11",
                                          "reading": True, "praying": True, "at_church_this_sunday": True,
                                          "keeping_commandments": True, "member_involvement": False},
                    "high_potential": {"name": "Ben", "at_church_this_sunday": False}}
            for group, values in full.items():
                for row in STATE["people"][group]:
                    row.update(values)
            return self.reply(200, {"ok": True})
        if path == "/__reset":
            reset()
            return self.reply(200, {"ok": True})
        if path == "/__many_sections":
            STATE["questions"] = list(QUESTIONS) + MORE_SECTIONS
            return self.reply(200, {"ok": True})
        if path == "/__no_new_members":
            STATE["people"]["new_members"] = []
            return self.reply(200, {"ok": True})
        if path == "/__fail_saves":
            STATE.update(fail_saves=True, units=list(UNITS) + [SECOND_UNIT])
            return self.reply(200, {"ok": True})
        return self.reply(404, {"error": "Not in the stub."})

    def person_action(self, group, person_id, action, body):
        column = "new_member_id" if group == "new_members" else "baptismal_date_person_id"
        row = next((p for p in STATE["people"][group] if p[column] == person_id), None)
        if row is None:
            return self.reply(400, {"error": "This person is no longer on this plan. Reload to see the latest list."})
        name = row["display_name"]
        try:
            if action == "edit":
                values = planning.validate_new_person("new_member" if group == "new_members" else "baptismal", body)
                row["person"].update(values)
                row["display_name"] = " ".join(filter(None, (values["first_name"], values["last_name"])))
                return self.reply(200, {"ok": True, "message": f"Details saved for {row['display_name']}.",
                                        "people": STATE["people"]})
            if action == "delete" and row.get("on_submitted_plan"):
                # What migration 023 says, turned into the page's words by planning._person_rpc_error.
                refusal = (f"This {'New Member' if group == 'new_members' else 'friend'} is already on an earlier or "
                           f"submitted weekly plan, so the record is kept for the mission's reports. Use "
                           f"{'End follow-up' if group == 'new_members' else 'Drop'} instead.")
                error = type("DbError", (), {"pgcode": "GF409", "diag": type("Diag", (), {"message_primary": refusal})()})()
                return self.reply(409, {"error": str(planning._person_rpc_error(error, name)), "refused": True})
            extra = {}
            if action == "baptized":
                values = planning.validate_new_person("convert", body)
                STATE["next"] += 1
                STATE["people"]["new_members"].append({**NM_EMPTY, "id": STATE["next"], "new_member_id": STATE["next"],
                                                       "display_name": name, "is_current": True, "on_submitted_plan": False,
                                                       "person": {**row["person"], **values}})
                extra["new_member_id"] = STATE["next"]
            if action == "transfer" and (not body.get("area_id") or not body.get("unit_id")):
                raise planning.FieldErrors({"unit_id": "Choose the ward or branch."})
            if action in ("end", "drop"):
                reasons = dict(planning.END_REASONS if action == "end" else planning.DROP_REASONS)
                if body.get("reason") not in reasons:
                    raise planning.FieldErrors({"reason": "Choose a reason."})
        except ValueError as error:
            return self.reply(400, {"error": str(error), **({"fields": error.fields} if getattr(error, "fields", None) else {})})
        STATE["people"][group] = [p for p in STATE["people"][group] if p is not row]
        messages = {"transfer": f"{name} was transferred to Riverside South (South Ward) and now appears on that area's plan. "
                                f"Consider letting those missionaries know about {name}.",
                    "end": f"Follow-up for {name} has ended.", "drop": f"{name} is off the baptismal date list.",
                    "delete": f"{name} was deleted.", "baptized": f"{name} is now in New Member Follow-up. What a blessing!"}
        return self.reply(200, {"ok": True, "action": action, "message": messages[action], **extra, "people": STATE["people"]})

    def add_person(self, kind, body):
        STATE["next"] += 1
        if kind == "high_potential":
            STATE["people"]["high_potential"].append({"id": STATE["next"], "name": planning.HIGH_POTENTIAL_PLACEHOLDER,
                                                      "at_church_this_sunday": None, "notes": None})
            return self.reply(201, {"ok": True, "id": STATE["next"]})
        try:
            values = planning.validate_new_person(kind, body)
        except planning.FieldErrors as error:
            return self.reply(400, {"error": str(error), "fields": error.fields})
        name = " ".join(filter(None, (values["first_name"], values["last_name"])))
        group, column = (("new_members", "new_member_id") if kind == "new_member"
                         else ("baptismal_friends", "baptismal_date_person_id"))
        STATE["people"][group].append({"id": STATE["next"], column: STATE["next"], "display_name": name, "is_current": True,
                                       "on_submitted_plan": False, "person": values})
        return self.reply(201, {"ok": True, "id": STATE["next"]})


if __name__ == "__main__":
    reset()
    ThreadingHTTPServer(("0.0.0.0", 8080), Handler).serve_forever()
