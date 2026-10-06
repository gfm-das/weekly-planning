"""Unit checks: shared-plan saves never lose a companion's work (no database needed).

save_planning_answers / save_planning_people / create_planning_person run against a small
in-memory stand-in for the planning tables, so the checks see exactly which rows change.

Run in the portal-api image (no pytest needed):
  docker run --rm -v <repo>/portal-api:/app -w /app gfm-portal-portal-api python tests/test_planning_safety.py
pytest works too: python -m pytest portal-api/tests/test_planning_safety.py
"""
import re
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import planning  # noqa: E402

THIS_SUNDAY, LAST_SUNDAY = date(2026, 9, 20), date(2026, 9, 13)
CONTEXT = {"area_id": 147, "user_id": "u1"}
QUESTIONS = [
    {"question_key": "friends_found_actual", "question_label": "New people being taught", "question_type": "NUMBER"},
    {"question_key": "weekly_action_plan", "question_label": "Weekly action plan", "question_type": "LONG_TEXT"},
    {"question_key": "ward_coordination_held", "question_label": "Ward coordination held", "question_type": "BOOLEAN"},
]
TABLES = {"weekly_new_members", "weekly_baptismal_date_friends", "weekly_high_potential_friends"}


class Plan:
    """In-memory report 1 with answers and person rows; records every write."""

    def __init__(self, sunday=THIS_SUNDAY, status="DRAFT", area_id=147):
        self.report = {"id": 1, "area_id": area_id, "unit_id": 5, "status": status, "sunday": sunday,
                       "current_sunday": THIS_SUNDAY}
        self.answers = {"friends_found_actual": 3, "weekly_action_plan": "Visit the Kleins"}
        self.people = {
            "weekly_new_members": [{"id": 11, "weekly_area_report_id": 1, "display_order": 1, "new_member_id": 7,
                                    "display_name": "Lena Vogel", "lessons_actual": 2, "lessons_goal": 3,
                                    "how_are_they_doing": "Good"}],
            "weekly_baptismal_date_friends": [],
            "weekly_high_potential_friends": [
                {"id": 21, "weekly_area_report_id": 1, "display_order": 1, "name": "Anna", "notes": "Met at church"},
                {"id": 22, "weekly_area_report_id": 1, "display_order": 2, "name": "Ben", "notes": None}],
        }
        self.writes, self.log = [], []

    def cursor(self):
        return Cursor(self)

    def run(self, sql, args):
        sql = " ".join(sql.split())
        self.log.append(sql)
        if "FROM public.weekly_area_reports war JOIN public.reporting_weeks" in sql:
            return [dict(self.report)] if args[0] == 1 else []
        if "FROM public.active_planning_questions" in sql:
            return [dict(q) for q in QUESTIONS]
        if sql.startswith("SELECT * FROM public.weekly_planning_answers"):
            return [{"question_key": k, "answer_number": v if isinstance(v, (int, float)) else None,
                     "answer_text": v if isinstance(v, str) else None} for k, v in self.answers.items()]
        if sql.startswith("SELECT") and "weekly_new_members wnm" in sql:
            return [dict({"display_name": "New member"}, **r) for r in self.people["weekly_new_members"]]
        if sql.startswith("SELECT") and "weekly_baptismal_date_friends wbf" in sql:
            return [dict(r, display_name="Friend") for r in self.people["weekly_baptismal_date_friends"]]
        if sql.startswith("SELECT * FROM public.weekly_high_potential_friends"):
            return [dict(r) for r in self.people["weekly_high_potential_friends"]]
        self.writes.append(sql)
        if sql.startswith("DELETE FROM public.weekly_planning_answers"):
            self.answers.pop(args[1], None)
            return []
        if sql.startswith("INSERT INTO public.weekly_planning_answers"):
            _, key, text, number, boolean, _json = args
            self.answers[key] = next(v for v in (number, text, boolean) if v is not None)
            return []
        if sql.startswith("UPDATE public.weekly_area_reports"):
            return []
        match = re.match(r"UPDATE public\.(\w+) SET (.*),updated_at=now\(\) WHERE id=%s", sql)
        if match and match.group(1) in TABLES:
            columns = [part.split("=")[0] for part in match.group(2).split(",")]
            row = next((r for r in self.people[match.group(1)] if r["id"] == args[-2] and args[-1] == 1), None)
            if row is None:
                return []
            row.update(zip(columns, args))
            return [{"id": row["id"]}]
        match = re.match(r"DELETE FROM public\.(\w+) WHERE id=%s", sql)
        if match and match.group(1) in TABLES:
            self.people[match.group(1)] = [r for r in self.people[match.group(1)] if r["id"] != args[0]]
            return []
        if sql.startswith("INSERT INTO public.weekly_high_potential_friends"):
            self.people["weekly_high_potential_friends"].append({"id": 23, "name": "New High Potential"})
            return [{"id": 23}]
        raise AssertionError("unexpected SQL: " + sql)


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


def raises(error, call, *args):
    try:
        call(*args)
    except error as caught:
        return str(caught)
    raise AssertionError(f"{call.__name__} did not raise {error.__name__}")


MARK_WORKED_ON = "UPDATE public.weekly_area_reports SET updated_at=now() WHERE id=%s"


def friends(plan):
    return {row["id"]: row["name"] for row in plan.people["weekly_high_potential_friends"]}


# What the current page sends: only its changes, marked changes_only (see planning._changes_only).
def answers(plan, values, context=CONTEXT):
    return planning.save_planning_answers(plan, context, 1, {"changes_only": True, **values})


def people(plan, groups, context=CONTEXT):
    return planning.save_planning_people(plan, context, 1, {"changes_only": True, **groups})


def add_person(plan, kind="high_potential", payload=None):
    return planning.create_planning_person(plan, CONTEXT, 1, kind, payload or {})


def test_only_sent_answers_are_written_and_the_rest_come_back():
    plan = Plan()
    result = answers(plan, {"ward_coordination_held": True})
    assert [w.split()[0] for w in plan.writes] == ["INSERT", "UPDATE"]
    assert result["answers"] == {"friends_found_actual": 3, "weekly_action_plan": "Visit the Kleins",
                                 "ward_coordination_held": True}


def test_clearing_an_answer_deletes_only_that_answer():
    plan = Plan()
    answers(plan, {"weekly_action_plan": ""})
    assert plan.answers == {"friends_found_actual": 3}


def test_an_empty_answer_save_writes_nothing():
    plan = Plan()
    result = answers(plan, {})
    assert plan.writes == [] and result["answers"]["friends_found_actual"] == 3


def test_a_page_from_before_this_fix_must_reload_and_writes_nothing():
    # Such a page re-sends every box (a blank one would delete the companion's answer) and every card.
    for call, body in ((planning.save_planning_answers, {"friends_found_actual": "", "weekly_action_plan": "stale"}),
                       (planning.save_planning_answers, {"changes_only": "yes"}),
                       (planning.save_planning_people, {"high_potential": [{"id": 21, "name": "Anna", "notes": "stale"}]}),
                       (planning.save_planning_people, {"changes_only": False, "high_potential": []})):
        plan = Plan()
        assert raises(ValueError, call, plan, CONTEXT, 1, body) == planning.RELOAD_MESSAGE
        assert plan.writes == [] and plan.answers["friends_found_actual"] == 3
        assert plan.people["weekly_high_potential_friends"][0]["notes"] == "Met at church"


def test_every_save_and_add_locks_the_plan_before_writing():
    # Two companions' saves then wait for each other instead of deadlocking on rows and the plan.
    for call in (lambda plan: answers(plan, {"friends_found_actual": 4}),
                 lambda plan: people(plan, {"high_potential": [{"id": 22, "notes": "x"}, {"id": 21, "notes": "y"}]}),
                 lambda plan: add_person(plan)):
        plan = Plan()
        call(plan)
        assert plan.log[0].startswith("SELECT war.id") and plan.log[0].endswith("FOR UPDATE OF war"), plan.log[0]
        assert plan.writes and plan.log.index(plan.writes[0]) > 0


def test_a_new_person_goes_after_the_last_one_even_after_removals():
    plan = Plan()
    add_person(plan)
    insert = next(w for w in plan.writes if w.startswith("INSERT INTO public.weekly_high_potential_friends"))
    assert "max(display_order)" in insert and "count(*)" not in insert


def test_a_word_in_a_number_answer_is_a_clear_400_not_a_500():
    import importlib
    app_module = importlib.import_module("app")
    for bad in ("abc", "NaN", True, [1]):
        message = raises(ValueError, answers, Plan(), {"friends_found_actual": bad})
        assert message == "New people being taught must be a number.", message
    assert raises(ValueError, answers, Plan(), {"friends_found_actual": -1}) == "New people being taught must be zero or greater."
    with app_module.app.test_request_context():
        try:
            answers(Plan(), {"friends_found_actual": "abc"})
        except Exception as error:  # noqa: BLE001 - the app's error handler decides the status
            response, status = app_module.error_response(error)
    assert status == 400 and response.get_json() == {"error": "New people being taught must be a number."}


def test_person_fields_not_sent_are_left_alone():
    plan = Plan()
    people(plan, {"new_members": [{"id": 11, "lessons_actual": 4}]})
    assert plan.writes == ["UPDATE public.weekly_new_members SET lessons_actual=%s,updated_at=now() "
                           "WHERE id=%s AND weekly_area_report_id=%s RETURNING id", MARK_WORKED_ON]
    row = plan.people["weekly_new_members"][0]
    assert row["lessons_actual"] == 4 and row["lessons_goal"] == 3 and row["how_are_they_doing"] == "Good"


def test_friends_not_in_the_save_are_never_deleted():
    plan = Plan()
    result = people(plan, {"high_potential": [{"id": 21, "notes": "Called"}]})
    assert friends(plan) == {21: "Anna", 22: "Ben"} and not any(w.startswith("DELETE") for w in plan.writes)
    assert [row["id"] for row in result["people"]["high_potential"]] == [21, 22]
    assert plan.people["weekly_high_potential_friends"][0]["notes"] == "Called"


def test_a_blank_friend_name_keeps_the_friend_and_the_saved_name():
    plan = Plan()
    result = people(plan, {"high_potential": [{"id": 21, "name": "  ", "notes": "x"}]})
    assert friends(plan) == {21: "Anna", 22: "Ben"}
    assert plan.people["weekly_high_potential_friends"][0]["notes"] == "x"
    assert result["missing"] == [] and not any(w.startswith("DELETE") for w in plan.writes)
    # Only a blank name: nothing to write at all.
    plan = Plan()
    people(plan, {"high_potential": [{"id": 22, "name": ""}]})
    assert plan.writes == [] and friends(plan) == {21: "Anna", 22: "Ben"}


def test_only_an_explicit_removal_deletes_a_friend():
    plan = Plan()
    result = people(plan, {"high_potential": [{"id": 22, "removed": True}]})
    assert friends(plan) == {21: "Anna"} and result["removed"] == [22]
    assert raises(ValueError, people, Plan(), {"new_members": [{"id": 11, "removed": True}]}) == \
        "Only high-potential friends can be removed here."


def test_a_row_removed_elsewhere_is_reported_and_the_rest_still_saves():
    plan = Plan()
    result = people(plan, {"high_potential": [{"id": 99, "notes": "gone"}, {"id": 21, "notes": "still here"}]})
    assert result["missing"] == [{"group": "high_potential", "id": 99}]
    assert plan.people["weekly_high_potential_friends"][0]["notes"] == "still here"
    # Removing a friend the companion already removed is fine too.
    assert people(Plan(), {"high_potential": [{"id": 99, "removed": True}]})["ok"]


def test_rows_without_an_id_or_with_bad_numbers_are_refused_before_writing():
    for bad in ({"name": "No id"}, {"id": "21"}, {"id": True}, "text"):
        plan = Plan()
        assert raises(ValueError, people, plan, {"high_potential": [bad]})
        assert plan.writes == []
    message = raises(ValueError, people, Plan(), {"new_members": [{"id": 11, "pmg_lessons_percentage": "abc"}]})
    assert message == "Lena Vogel: Preach My Gospel lessons taught (%) must be a number from 0 to 100."


def test_a_plan_from_last_week_is_refused_with_a_reload_hint_everywhere():
    for call, args in ((answers, ({"friends_found_actual": 1},)),
                       (people, ({"high_potential": [{"id": 21, "notes": "x"}]},)),
                       (add_person, ())):
        plan = Plan(sunday=LAST_SUNDAY)
        assert raises(ValueError, call, plan, *args) == planning.LAST_WEEK_MESSAGE
        assert plan.writes == []
    # Last week's plan that was also submitted still gets the reload hint, not "ask a leader".
    assert raises(ValueError, answers, Plan(sunday=LAST_SUNDAY, status="SUBMITTED"), {}) == planning.LAST_WEEK_MESSAGE


def test_submitted_plans_and_other_areas_keep_their_messages():
    assert raises(ValueError, answers, Plan(status="SUBMITTED"), {}) == \
        "This plan is closed. Ask a leader to unlock it before editing."
    assert raises(ValueError, people, Plan(status="LOCKED"), {}) == \
        "This plan is submitted. Ask a leader to unlock it before editing."
    assert raises(ValueError, add_person, Plan(status="SUBMITTED")) == \
        "This plan is submitted. Ask a leader to unlock it before adding someone."
    for call, args in ((answers, ({},)), (people, ({},)), (add_person, ())):
        assert raises(PermissionError, call, Plan(area_id=999), *args)


def test_work_on_person_cards_counts_as_activity_for_the_reminder():
    # reminders.planning_due only sees the report's (and answers') updated_at, not the person rows.
    for call in (lambda plan: people(plan, {"high_potential": [{"id": 21, "notes": "Called"}]}),
                 lambda plan: people(plan, {"new_members": [{"id": 11, "reading": True}]}),
                 lambda plan: people(plan, {"high_potential": [{"id": 22, "removed": True}]}),
                 lambda plan: add_person(plan)):
        plan = Plan()
        call(plan)
        assert plan.writes.count(MARK_WORKED_ON) == 1, plan.writes
    # Nothing written, nothing recorded: a blank name only, a row removed elsewhere, an empty save.
    for groups in ({"high_potential": [{"id": 22, "name": " "}]}, {"high_potential": [{"id": 99, "notes": "x"}]}, {}):
        plan = Plan()
        people(plan, groups)
        assert MARK_WORKED_ON not in plan.writes, (groups, plan.writes)


def test_a_value_out_of_range_names_the_person():
    plan = Plan()
    message = raises(ValueError, people, plan, {"high_potential": [{"id": 21, "notes": "other card"}],
                                                "new_members": [{"id": 11, "pmg_lessons_percentage": 150}]})
    assert message == "Lena Vogel: Preach My Gospel lessons taught (%) must be a number from 0 to 100.", message
    assert raises(ValueError, people, Plan(), {"new_members": [{"id": 11, "lessons_goal": -1}]}) ==         "Lena Vogel: Goal next week must be a number from 0 to 1000."
    assert raises(ValueError, people, Plan(), {"new_members": [{"id": 12, "lessons_actual": 5000}]}) ==         "A person on this plan: Lessons taught must be a number from 0 to 1000."
    # In range (a decimal percentage too) is saved.
    plan = Plan()
    people(plan, {"new_members": [{"id": 11, "pmg_lessons_percentage": 62.5, "lessons_actual": 1000}]})
    assert float(plan.people["weekly_new_members"][0]["pmg_lessons_percentage"]) == 62.5


def test_a_bad_person_id_is_a_clear_message():
    for bad in ("abc", None, -3, [1]):
        assert raises(ValueError, add_person, Plan(), "existing_new_member", {"person_id": bad}) == \
            "Choose a person from your list."


if __name__ == "__main__":
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_") and callable(value)]
    for test in tests:
        test()
        print("ok", test.__name__)
    print(f"{len(tests)} tests passed")
