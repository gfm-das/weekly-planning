"""Unit checks for the planning people: add-person / Edit details validation, the weekly person answers,
the submit check and the manage-person actions (no database needed).

Run in the portal-api image (no pytest needed):
  docker run --rm -v <repo>/portal-api:/app -w /app gfm-portal-portal-api python tests/test_planning_people.py
pytest works too: python -m pytest portal-api/tests/test_planning_people.py
(The page checks at the end read ../portal/planning.html; they are skipped when the portal folder is not there.)
"""
import base64
import json
import os
import re
import sys
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import psycopg2

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("SUPABASE_URL", "http://supabase.invalid")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "unit-test-only")
import planning  # noqa: E402

TODAY = date(2026, 9, 26)
VALID_NM = {"first_name": " Lea ", "last_name": "Hoffmann", "baptismal_date_extended": "2026-08-30",
            "baptism_date": "2026-09-20", "confirmation_date": "2026-09-21", "date_of_birth": "1995-03-04",
            "age_range": "31-45", "finding_source": "Member/Member", "gender": "Female",
            "living_situation": "Student", "marital_status": "Single",
            "mission_language_competency": "Fluent/almost fluent", "native_language": "Italian",
            "country_of_origin": "Italy", "child_dependents": "0",
            "conversion_success_notes": "The ward council helped."}
PAGE_FILE = next((path for path in (Path(__file__).resolve().parents[2] / "portal" / "planning.html",
                                    Path("/portal/planning.html")) if path.exists()), None)


def raises(error, call, *args, **kwargs):
    try:
        call(*args, **kwargs)
    except error as caught:
        return caught
    raise AssertionError(f"{getattr(call, '__name__', call)} did not raise {error.__name__}")


def errors_for(kind, payload):
    return raises(planning.FieldErrors, planning.validate_new_person, kind, payload, today=TODAY).fields


# ---------- Create New Member / Add Person On Date / Edit details ----------

def test_empty_new_member_needs_everything_except_the_optional_second_language():
    fields = errors_for("new_member", {})
    assert set(fields) == set(planning.NEW_MEMBER_FIELDS) - {"second_language"}, sorted(fields)
    assert planning.NEW_MEMBER_OPTIONAL == ("second_language",)
    assert set(planning.NEW_MEMBER_REQUIRED) == set(planning.NEW_MEMBER_FIELDS) - {"second_language"}
    assert fields["first_name"] == "Enter the first name."
    assert fields["child_dependents"] == "Enter the number of children (0 if none)."
    assert fields["gender"] == "Please choose one."
    assert fields["confirmation_date"] == "Enter the confirmation date."


def test_valid_new_member_is_cleaned_for_the_rpc():
    values = planning.validate_new_person("new_member", {
        **VALID_NM, "conversion_success_notes": "  Line one\nLine two  ", "native_language": "  German  "},
        today=TODAY)
    assert values["first_name"] == "Lea" and values["native_language"] == "German"
    assert values["baptism_date"] == date(2026, 9, 20) and values["child_dependents"] == 0
    assert values["conversion_success_notes"] == "Line one\nLine two" and values["second_language"] is None
    assert set(planning.NEW_MEMBER_RPC_FIELDS) <= set(values)


def test_the_confirmation_date_is_always_required():
    """Round 12: the "Not confirmed yet" option is gone. An empty date is refused, and an old page that still sends
    "not_confirmed" cannot get around it."""
    assert set(errors_for("new_member", {**VALID_NM, "confirmation_date": ""})) == {"confirmation_date"}
    assert set(errors_for("new_member", {**VALID_NM, "confirmation_date": "", "not_confirmed": True})) == {"confirmation_date"}
    assert planning.validate_new_person("new_member", {**VALID_NM, "not_confirmed": True}, today=TODAY)["confirmation_date"] == date(2026, 9, 21)


def test_child_dependants_zero_is_an_answer_and_blank_is_not():
    values = planning.validate_new_person("new_member", {**VALID_NM, "child_dependents": 0}, today=TODAY)
    assert values["child_dependents"] == 0
    assert set(errors_for("new_member", {**VALID_NM, "child_dependents": ""})) == {"child_dependents"}


def test_new_member_field_errors():
    for field, value, message in (
            ("gender", "Other", "Choose one of the listed options."),
            ("finding_source", "Missionary/Unknown", "Choose one of the listed options."),
            ("date_of_birth", "2027-01-01", "Birth date cannot be in the future."),
            ("baptism_date", "2026-09-27", "The baptism date cannot be in the future."),
            ("confirmation_date", "2026-12-01", "The confirmation date cannot be in the future."),
            ("baptism_date", "not-a-date", "Enter a valid date."),
            ("date_of_birth", "1850-01-01", "Enter a valid date."),
            ("child_dependents", "-1", "Enter a whole number from 0 to 30."),
            ("child_dependents", "2.5", "Enter a whole number from 0 to 30."),
            ("child_dependents", "31", "Enter a whole number from 0 to 30."),
            ("last_name", "x" * 101, "Use 100 characters or fewer."),
            ("first_name", {"nested": 1}, "Enter plain text."),
            ("native_language", "   ", "Enter their native language.")):
        assert errors_for("new_member", {**VALID_NM, field: value}) == {field: message}, (field, value)


def test_date_order_rules():
    fields = errors_for("new_member", {**VALID_NM, "baptismal_date_extended": "2026-09-10",
                                       "baptism_date": "2026-09-01", "confirmation_date": "2026-08-30"})
    assert fields == {"baptism_date": "Baptism cannot be before the date it was extended.",
                      "confirmation_date": "Confirmation cannot be before the baptism date."}


def test_baptismal_person_needs_first_name_last_name_and_finding_source():
    assert errors_for("baptismal", {}) == {"first_name": "Enter the first name.", "last_name": "Enter the last name.",
                                           "finding_source": "Please choose one."}
    values = planning.validate_new_person("baptismal", {"first_name": "Mia", "last_name": " Klein ",
                                                        "finding_source": "Media/Referral", "gender": "ignored"},
                                          today=TODAY)
    assert values == {"first_name": "Mia", "last_name": "Klein", "finding_source": "Media/Referral"}


def test_baptized_form_takes_name_and_finding_source_from_the_friend():
    payload = {key: value for key, value in VALID_NM.items() if key not in planning.FROM_FRIEND_RECORD}
    values = planning.validate_new_person("convert", {**payload, "first_name": "Ignored", "finding_source": "Nope"},
                                          today=TODAY)
    assert not set(planning.FROM_FRIEND_RECORD) & set(values)
    assert set(planning.CONVERT_RPC_FIELDS) <= set(values)
    fields = errors_for("convert", {})
    assert not set(planning.FROM_FRIEND_RECORD) & set(fields) and "baptism_date" in fields


def test_unknown_person_kind_is_refused():
    assert str(raises(ValueError, planning.validate_new_person, "robot", {})) == "Unknown person type."


def test_field_errors_are_a_400_with_field_details():
    import importlib
    app_module = importlib.import_module("app")
    with app_module.app.test_request_context():
        response, status = app_module.error_response(planning.FieldErrors({"first_name": "Enter the first name."}))
    assert status == 400
    assert response.get_json() == {"error": "1 field needs attention.",
                                   "fields": {"first_name": "Enter the first name."}}


# ---------- Weekly person answers ----------

def test_person_answers_are_checked_by_kind():
    value = planning._person_value
    assert value("next_ordinance", "TB") == "TB"
    assert str(raises(ValueError, value, "next_ordinance", "Temple baptisms")) == "Choose the next ordinance from the list."
    assert value("has_calling", "not_applicable") == "not_applicable"
    assert "Yes, No or Not applicable" in str(raises(ValueError, value, "has_active_temple_recommend", "maybe"))
    assert value("reading", False) is False and value("praying", True) is True
    for bad in ("yes", 1, "true"):
        assert str(raises(ValueError, value, "reading", bad)) == 'Answer "Reading?" with Yes or No.'
    assert value("current_baptismal_date", "2026-10-04") == date(2026, 10, 4)
    assert str(raises(ValueError, value, "baptismal_date_set_on", "04.10.2026")) == "Date first set: enter a valid date."
    assert str(raises(ValueError, value, "notes", "x" * 5001)) == "Notes: use 5000 characters or fewer."
    assert value("reading", None) is None and value("how_are_they_doing", "") is None


def test_the_finding_source_is_no_longer_saved_from_the_weekly_card():
    assert "finding_source" not in planning.PEOPLE_FIELDS["baptismal_friends"]


# ---------- Submit check ----------

def full_new_member(**changes):
    row = {"id": 11, "new_member_id": 7, "display_name": "Lena Vogel", "is_current": True, "lessons_actual": 0,
           "lessons_goal": 2, "pmg_lessons_percentage": 50, "how_are_they_doing": "Well", "at_church_this_sunday": False,
           "reading": True, "praying": True, "member_involvement": False, "discussed_in_gemiko": False,
           "next_ordinance": "AP", "has_calling": "no", "has_aaronic_priesthood": "not_applicable",
           "has_melchizedek_priesthood": "not_applicable", "ministers_to_someone": "no",
           "ministered_to_by_someone": True, "has_active_temple_recommend": "no", "visited_temple_for_baptisms": "no"}
    return {**row, **changes}


def full_friend(**changes):
    row = {"id": 31, "baptismal_date_person_id": 9, "display_name": "Mia Klein", "is_current": True,
           "baptismal_date_set_on": date(2026, 9, 1), "current_baptismal_date": date(2026, 10, 4), "reading": False,
           "praying": True, "at_church_this_sunday": True, "keeping_commandments": True, "member_involvement": False}
    return {**row, **changes}


def test_complete_people_pass_and_false_or_zero_count_as_answers():
    people = {"new_members": [full_new_member()], "baptismal_friends": [full_friend()],
              "high_potential": [{"id": 21, "name": "Anna", "at_church_this_sunday": False, "notes": None}]}
    assert planning._missing_person_fields(people) == []


def test_missing_answers_are_listed_per_person_in_page_order():
    people = {"new_members": [full_new_member(reading=None, next_ordinance="", how_are_they_doing="  ")],
              "baptismal_friends": [full_friend(current_baptismal_date=None)],
              "high_potential": [{"id": 21, "name": "New High Potential", "at_church_this_sunday": None}]}
    assert planning._missing_person_fields(people) == [
        {"group": "baptismal_friends", "id": 31, "person_id": 9, "name": "Mia Klein", "fields": ["current_baptismal_date"]},
        {"group": "new_members", "id": 11, "person_id": 7, "name": "Lena Vogel",
         "fields": ["how_are_they_doing", "reading", "next_ordinance"]},
        {"group": "high_potential", "id": 21, "person_id": None, "name": "A new friend",
         "fields": ["name", "at_church_this_sunday"]}]


def test_gemiko_plan_is_required_only_when_discussed_in_gemiko():
    assert planning._missing_person_fields({"new_members": [full_new_member(gemiko_support_plan=None)]}) == []
    missing = planning._missing_person_fields({"new_members": [full_new_member(discussed_in_gemiko=True)]})
    assert missing[0]["fields"] == ["gemiko_support_plan"]


def test_people_no_longer_in_the_area_are_not_checked():
    people = {"new_members": [full_new_member(is_current=False, reading=None)],
              "baptismal_friends": [full_friend(is_current=False, baptismal_date_set_on=None)]}
    assert planning._missing_person_fields(people) == []


def test_incomplete_people_are_a_400_with_the_list():
    import importlib
    app_module = importlib.import_module("app")
    missing = planning._missing_person_fields({"new_members": [full_new_member(reading=None)]})
    error = planning.PeopleIncomplete(missing)
    with app_module.app.test_request_context():
        response, status = app_module.error_response(error)
    body = response.get_json()
    assert status == 400 and body["fields"]["people"] == missing
    assert body["error"] == ("Almost there. Some questions about Lena Vogel (new member) are not answered yet. "
                             "Answer them, then submit again.")


class Cursor:
    def __init__(self, plan):
        self.plan, self.result, self.description = plan, [], []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, args=()):
        self.result = self.plan.run(sql, args)
        self.description = [(key,) for key in (self.result[0] if self.result else {})]

    def fetchall(self):
        return self.result

    def fetchone(self):
        return self.result[0] if self.result else None


class SubmitPlan:
    """Just enough of a connection for submit_planning_report: one report of this week and its people."""

    def __init__(self, people, status="DRAFT"):
        self.people, self.status, self.log = people, status, []

    def cursor(self):
        return Cursor(self)

    def run(self, sql, args):
        sql = " ".join(sql.split())
        self.log.append(sql)
        if "FROM public.weekly_area_reports war JOIN public.reporting_weeks" in sql:
            return [{"id": 1, "area_id": 147, "unit_id": 5, "status": self.status,
                     "sunday": date(2026, 9, 27), "current_sunday": date(2026, 9, 27)}]
        if "weekly_new_members wnm" in sql:
            return self.people.get("new_members", [])
        if "weekly_baptismal_date_friends wbf" in sql:
            return self.people.get("baptismal_friends", [])
        if "weekly_high_potential_friends" in sql:
            return self.people.get("high_potential", [])
        if "submit_current_weekly_report" in sql:
            return [{"report_id": 1}]
        raise AssertionError("unexpected SQL: " + sql)


def test_submit_is_refused_before_the_plan_is_submitted():
    patch.object(planning, "_check_required_answers", lambda conn, report_id: None).start()  # tested in the other part's file
    plan = SubmitPlan({"new_members": [full_new_member(reading=None)]})
    error = raises(planning.PeopleIncomplete, planning.submit_planning_report, plan, {"area_id": 147}, 1)
    assert error.fields["people"][0]["fields"] == ["reading"]
    assert not any("submit_current_weekly_report" in sql for sql in plan.log)
    plan = SubmitPlan({"new_members": [full_new_member()]})
    assert planning.submit_planning_report(plan, {"area_id": 147}, 1)["status"] == "SUBMITTED"
    # An already submitted plan is not checked again (submitting it again changes nothing).
    plan = SubmitPlan({"new_members": [full_new_member(reading=None)]}, status="SUBMITTED")
    assert planning.submit_planning_report(plan, {"area_id": 147}, 1)["status"] == "SUBMITTED"


# ---------- Manage-person actions (the database side is in planning_people_db.py) ----------

MARK_WORKED_ON = "UPDATE public.weekly_area_reports SET updated_at=now() WHERE id=%s"


class ActionPlan:
    """A draft report 1 of area 147 with New Member 7 and friend 9 on it (both in unit 5)."""

    def __init__(self, fail=None, person_area=147):
        self.fail, self.person_area, self.log = fail, person_area, []

    def cursor(self):
        return Cursor(self)

    def run(self, sql, args):
        sql = " ".join(sql.split())
        self.log.append((sql, args))
        if "FOR UPDATE OF war" in sql:
            return [{"id": 1, "area_id": 147, "unit_id": 5, "status": "DRAFT",
                     "sunday": date(2026, 9, 27), "current_sunday": date(2026, 9, 27)}]
        if sql.startswith(("SELECT nm.display_name", "SELECT bdp.display_name")):
            known = (7 if "nm.display_name" in sql else 9) == args[1]
            return [{"display_name": "Lena Vogel", "area_id": self.person_area, "unit_id": 5}] if known else []
        if "FROM public.area_units au" in sql:
            return [{"area": "Mainz", "unit": "Mainz Ward"}] if args in ((148, 6), (147, 5)) else []
        if sql.startswith(("SELECT public.", "SELECT (public.")):
            if self.fail:
                raise self.fail
            return [{"result": None, "id": 99}]
        if sql.startswith(("DELETE", "UPDATE public.weekly_area_reports", "INSERT")):
            return []
        if " wnm" in sql or " wbf" in sql or "weekly_high_potential_friends" in sql:
            return []
        if "FROM public.current_new_members nm" in sql or "FROM public.current_baptismal_date_people b" in sql:
            return []  # "Add from database" lists, sent back after every action (see test_small_fixes.py)
        raise AssertionError("unexpected SQL: " + sql)


class DbError(psycopg2.Error):
    """A database error with a SQLSTATE and message, like the ones the people functions raise."""

    def __init__(self, code, message):
        super().__init__(message)
        self._code, self._message = code, message

    @property
    def pgcode(self):
        return self._code

    @property
    def diag(self):
        return SimpleNamespace(message_primary=self._message)


def act(plan, group, person, action, payload=None):
    return planning.manage_planning_person(plan, {"area_id": 147}, 1, group, person, action, payload or {})


def test_actions_use_named_arguments_and_take_the_row_off_this_plan():
    plan = ActionPlan()
    result = act(plan, "new_members", 7, "transfer", {"area_id": 148, "unit_id": 6})
    assert result["message"] == ("Lena Vogel was transferred to Mainz (Mainz Ward) and now appears on that area's plan. "
                                 "Consider letting those missionaries know about Lena Vogel.")
    calls = [(sql, args) for sql, args in plan.log if sql.startswith("SELECT public.")]
    assert calls == [("SELECT public.transfer_new_member(target_new_member_id => %s, target_area_id => %s, "
                      "target_unit_id => %s) AS result", (7, 148, 6))], calls
    statements = [sql for sql, _ in plan.log]
    delete = statements.index("DELETE FROM public.weekly_new_members WHERE weekly_area_report_id=%s AND new_member_id=%s")
    assert statements.index(calls[0][0]) < delete < statements.index(MARK_WORKED_ON)
    # Edit details keeps the row.
    plan = ActionPlan()
    act(plan, "baptismal_friends", 9, "edit", {"first_name": "Mia", "last_name": "Klein", "finding_source": "Member/Member"})
    assert not any(sql.startswith("DELETE") for sql, _ in plan.log)
    assert any(sql.startswith("SELECT public.update_baptismal_date_person(target_baptismal_date_person_id => %s")
               for sql, _ in plan.log)


def test_action_refusals_come_before_any_change():
    for group, person, action, payload, error, message in (
            ("new_members", 7, "drop", {}, ValueError, "This action is not available here. Reload and try again."),
            ("robots", 7, "edit", {}, ValueError, "This action is not available here. Reload and try again."),
            ("new_members", 8, "end", {"reason": "other"}, ValueError,
             "This person is no longer on this plan. Reload to see the latest list."),
            ("new_members", 7, "end", {"reason": "bored"}, planning.FieldErrors, "1 field needs attention."),
            ("new_members", 7, "transfer", {"area_id": "x"}, ValueError, "Choose the new area."),
            ("new_members", 7, "transfer", {"area_id": 148, "unit_id": 999}, planning.FieldErrors, "1 field needs attention."),
            ("new_members", 7, "transfer", {"area_id": 147, "unit_id": 5}, planning.FieldErrors, "1 field needs attention."),
            ("baptismal_friends", 9, "baptized", {}, planning.FieldErrors, None)):
        plan = ActionPlan()
        caught = raises(error, act, plan, group, person, action, payload)
        assert message is None or str(caught) == message, (action, str(caught))
        assert not any(sql.startswith(("SELECT public.", "SELECT (public.", "DELETE", "INSERT", "UPDATE"))
                       for sql, _ in plan.log), (action, plan.log)
    caught = raises(ValueError, act, ActionPlan(person_area=999), "new_members", 7, "end", {"reason": "other"})
    assert str(caught) == "Lena Vogel is no longer assigned to your area. Reload to see the latest list."


def test_database_refusals_become_plain_messages():
    kept = DbError("GF409", "This New Member is already on an earlier or submitted weekly plan, so the record is kept "
                            "for the mission's reports. Use End follow-up instead.")
    caught = raises(planning.PersonActionRefused, act, ActionPlan(fail=kept), "baptismal_friends", 9, "delete")
    assert str(caught).startswith("Lena Vogel is already on an earlier or submitted weekly plan"), str(caught)
    denied = DbError("P0001", "You do not have permission to transfer this New Member.")
    raises(PermissionError, act, ActionPlan(fail=denied), "new_members", 7, "transfer", {"area_id": 148, "unit_id": 6})
    other = DbError("P0001", "Destination area must be in the same mission.")
    assert str(raises(ValueError, act, ActionPlan(fail=other), "baptismal_friends", 9, "transfer",
                      {"area_id": 148, "unit_id": 6})) == "Destination area must be in the same mission."
    raises(DbError, act, ActionPlan(fail=DbError("23505", "duplicate key")), "new_members", 7, "end", {"reason": "other"})


class RouteCursor:
    description = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, args=()):
        pass

    def fetchall(self):
        return []


def call_route(path, body, outcome):
    import importlib
    app_module = importlib.import_module("app")

    @contextmanager
    def fake_db():
        yield SimpleNamespace(cursor=RouteCursor, cursor_factory=None)

    enc = lambda v: base64.urlsafe_b64encode(json.dumps(v).encode()).decode().rstrip("=")
    token = enc({"alg": "none"}) + "." + enc({"sub": "u", "role": "authenticated"}) + ".x"
    identity = lambda *a, **k: SimpleNamespace(status_code=200, json=lambda: {"id": "00000000-0000-0000-0000-000000000001"})
    with patch.object(app_module.requests, "get", identity), patch.object(app_module, "db", fake_db), \
            patch.object(app_module, "context_for", lambda c, u: {"user_id": "u", "area_id": 147, "mission_id": 1}), \
            patch.object(planning, "manage_planning_person", outcome):
        response = app_module.app.test_client().post(path, json=body, headers={"Authorization": "Bearer " + token})
    return response.status_code, response.get_json(silent=True)



def test_a_new_member_cannot_be_deleted():
    """Round 12: Delete is only for friends with a baptismal date. The page does not offer it and the route refuses it."""
    assert planning.PERSON_ACTIONS["new_members"] == ("edit", "transfer", "end")
    assert "delete" in planning.PERSON_ACTIONS["baptismal_friends"]
    caught = raises(ValueError, act, ActionPlan(), "new_members", 7, "delete")
    assert str(caught) == "This action is not available here. Reload and try again."


def test_the_action_route_answers_409_when_the_record_is_kept():
    def refuse(*args):
        raise planning.PersonActionRefused("Lena Vogel is already on an earlier or submitted weekly plan. Use End follow-up instead.")

    status, body = call_route("/api/planning/reports/1/people/baptismal_friends/9/delete", None, refuse)
    assert (status, body) == (409, {"error": "Lena Vogel is already on an earlier or submitted weekly plan. Use End follow-up instead.",
                                    "refused": True}), (status, body)
    seen = []
    status, body = call_route("/api/planning/reports/1/people/baptismal_friends/9/drop", {"reason": "other"},
                              lambda conn, context, *args: seen.append(args) or {"ok": True})
    assert status == 200 and seen == [(1, "baptismal_friends", 9, "drop", {"reason": "other"})], (status, seen)
    status, body = call_route("/api/planning/reports/1/people/new_members/7/end", [1, 2], refuse)
    assert (status, body) == (400, {"error": "Send the details as a JSON object."}), (status, body)


def test_delete_is_offered_by_the_same_rule_the_database_uses():
    """"Delete (added by mistake)": the page offers it (on_submitted_plan false) exactly when the delete functions of
    migration 023 allow it: no row on a plan that is not a draft, and none on a plan of an earlier week (a leader's
    Unlock makes a submitted plan a draft again, so the status alone would forget it)."""
    migration = (Path(planning.__file__).resolve().parent / "migrations" / "history" / "023_people_management.sql").read_text(encoding="utf-8")
    source = Path(planning.__file__).read_text(encoding="utf-8")
    rule = "(war.status <> 'DRAFT' OR rw.sunday < public.current_reporting_sunday())"
    functions = re.findall(r"CREATE OR REPLACE FUNCTION public\.(delete_\w+_added_by_mistake)\(.*?\$function\$;", migration, re.S)
    assert functions == ["delete_new_member_added_by_mistake", "delete_baptismal_date_person_added_by_mistake"], functions
    for body in re.findall(r"CREATE OR REPLACE FUNCTION public\.delete_\w+_added_by_mistake\(.*?\$function\$;", migration, re.S):
        assert rule in body and "JOIN public.reporting_weeks rw ON rw.id = war.reporting_week_id" in body
        assert "already on an earlier or submitted weekly plan" in body
    people_sql = source[source.index("def _report_people"):source.index("def _report_for_edit")]
    assert people_sql.count("(r2.status<>'DRAFT' OR rw2.sunday<public.current_reporting_sunday())) AS on_submitted_plan") == 2
    assert people_sql.count("JOIN public.reporting_weeks rw2 ON rw2.id=r2.reporting_week_id") == 2


# ---------- The page and the server agree ----------

def test_page_lists_match_the_server():
    if PAGE_FILE is None:
        print("   (skipped: portal/planning.html not found)")
        return
    page = PAGE_FILE.read_text(encoding="utf-8")
    codes = re.search(r"const NEXT_ORDINANCES = (\[.*?\]);", page, re.S).group(1)
    assert json.loads(codes) == [list(item) for item in planning.NEXT_ORDINANCES]
    required = json.loads(re.search(r"const PEOPLE_REQUIRED = (\{.*?\});", page, re.S).group(1))
    assert required == {group: list(keys) for group, keys in planning.PEOPLE_REQUIRED.items()}
    placeholder = re.search(r"const HIGH_POTENTIAL_PLACEHOLDER = (\".*?\");", page).group(1)
    assert json.loads(placeholder) == planning.HIGH_POTENTIAL_PLACEHOLDER
    labels = json.loads(re.search(r"const PEOPLE_LABELS = (\{.*?\});", page, re.S).group(1))
    assert labels == planning.PEOPLE_LABELS
    for name, server in (("END_REASONS", planning.END_REASONS), ("DROP_REASONS", planning.DROP_REASONS)):
        listed = json.loads(re.search(rf"const {name} = (\[.*?\]);", page, re.S).group(1))
        assert listed == [list(reason) for reason in server], name
    for key in planning.PEOPLE_YES_NO:
        assert f'"{key}", "yesno"' in page, key
    for key in planning.PEOPLE_YES_NO_NA:
        assert f'"{key}", "yesnona"' in page, key


def test_page_marks_what_the_server_lists_when_it_refuses_a_submit():
    """The submit handler hands the server's list (fields.people) to the same marking as the page's own check."""
    if PAGE_FILE is None:
        print("   (skipped: portal/planning.html not found)")
        return
    page = PAGE_FILE.read_text(encoding="utf-8")
    handler = page[page.index('$("submitBtn").onclick'):page.index('$("personCancel").onclick')]
    assert handler.count("peopleIncomplete()") == 1
    assert "if (e.fields?.people) return showServerIncomplete(e.fields.people, e.message);" in handler
    server = page[page.index("async function showServerIncomplete"):page.index("function toggleGemiko")]
    assert "showIncompletePeople(check())" in server and "await load(data.report.unit_id)" in server
    assert "[data-person-group=" in server and "[data-id=" in server
    check = page[page.index("function peopleIncomplete()"):page.index("function showIncompletePeople")]
    assert "return showIncompletePeople(incomplete);" in check
    # The server's list carries what the page needs to find each tab.
    error = planning.PeopleIncomplete([{"group": "baptismal_friends", "id": 31, "person_id": 9, "name": "Mia Klein",
                                        "fields": ["praying"]}])
    assert set(error.fields["people"][0]) >= {"group", "id", "fields"}


if __name__ == "__main__":
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_") and callable(value)]
    failed = 0
    for test in tests:
        try:
            test()
            print("ok", test.__name__)
        except Exception as exc:  # keep going so a run shows every failing check
            failed += 1
            print("FAIL", test.__name__, "-", type(exc).__name__, str(exc)[:400])
    print(f"{len(tests) - failed} of {len(tests)} tests passed")
    sys.exit(1 if failed else 0)
