"""Unit checks: Weekly Planning built from the question list in the database (no database needed).

Covers every question type on save, number limits, show/hide rules (the same rules as Beta and the page), the
required check at submit, and a save from a page whose questions changed in DA Management meanwhile (a stale
catalogue version). A small in-memory stand-in plays the database, as in test_planning_safety.py.

Run in the portal-api image (no pytest needed):
  docker run --rm -v <repo>/portal-api:/app -w /app gfm-portal-portal-api python tests/test_planning_catalog.py
"""
import copy
from unittest.mock import patch
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import planning  # noqa: E402

THIS_SUNDAY = date(2026, 9, 27)
CONTEXT = {"area_id": 147, "user_id": "u1"}


def question(key, kind, label=None, required=True, **extra):
    return {"question_key": key, "question_label": label or key.replace("_", " ").capitalize(), "question_type": kind,
            "required": required, "options": [], "rows": [], "rules": [], "min_value": None, "max_value": None,
            "integer_only": True, "placeholder": None, "value_when_hidden": None, **extra}


YES_NO = [{"value": "yes", "label": "Yes"}, {"value": "no", "label": "No"}]
CATALOG = [
    question("sacrament_attendance_actual", "NUMBER", "Sacrament attendance"),
    question("sacrament_first_time", "NUMBER", "1st Time", value_when_hidden="0",
             rules=[{"parent": "sacrament_attendance_actual", "operator": "greater_than", "value": "0"}]),
    question("sacrament_first_time_first_week", "NUMBER", "1st Time 1st Week", value_when_hidden="0",
             rules=[{"parent": "sacrament_attendance_actual", "operator": "greater_than", "value": "0"},
                    {"parent": "sacrament_first_time", "operator": "greater_than", "value": "0"}]),
    question("service_hours_goal", "NUMBER", "Service hours", min_value=Decimal("1"), max_value=Decimal("40"), integer_only=False),
    question("ward_coordination_held", "BOOLEAN", "Meeting held"),
    question("ward_coordination_attendance", "GRID", "Who was there?", options=YES_NO + [{"value": "dont_have_one", "label": "Don't have one"}],
             rows=[{"key": "bishop", "label": "Bishop"}, {"key": "gemiko_leader", "label": "GEMIKO leader"}],
             rules=[{"parent": "ward_coordination_held", "operator": "equals", "value": "true"}]),
    question("contact_method", "SELECT", "How did you contact them?", options=[{"value": "phone", "label": "Phone"}, {"value": "visit", "label": "Visit"}]),
    question("lesson_place", "RADIO", "Where?", options=[{"value": "home", "label": "At home"}, {"value": "church", "label": "At church"}]),
    question("topics", "CHECKBOX", "Topics", options=[{"value": "faith", "label": "Faith"}, {"value": "prayer", "label": "Prayer"}, {"value": "tithing", "label": "Tithing"}]),
    question("next_visit", "DATE", "Next visit"),
    question("companion_note", "TEXT", "A short note", required=False),
    question("weekly_action_plan", "LONG_TEXT", "Weekly action plan"),
]


class Plan:
    """Report 1 of this week with its answers; the question list and its version; records every write."""

    def __init__(self, answers=None, catalog=None, version=7, status="DRAFT"):
        self.report = {"id": 1, "area_id": 147, "unit_id": 5, "status": status, "sunday": THIS_SUNDAY,
                       "current_sunday": THIS_SUNDAY}
        self.answers = dict(answers or {})
        self.catalog = copy.deepcopy(catalog if catalog is not None else CATALOG)
        self.version = version
        self.previous = {"sacrament_attendance_actual": 11, "ward_coordination_held": True}
        self.writes = []

    def cursor(self):
        return Cursor(self)

    @staticmethod
    def row(key, value):
        return {"question_key": key, "answer_json": value if isinstance(value, (dict, list)) else None,
                "answer_boolean": value if isinstance(value, bool) else None,
                "answer_number": value if isinstance(value, (int, float, Decimal)) and not isinstance(value, bool) else None,
                "answer_text": value if isinstance(value, str) else None}

    def run(self, sql, args):
        sql = " ".join(sql.split())
        if "FROM public.weekly_area_reports war JOIN public.reporting_weeks" in sql:
            return [dict(self.report)]
        if "FROM public.active_planning_questions apq" in sql:
            return copy.deepcopy(self.catalog)
        if sql.startswith("SELECT version FROM public.planning_catalog_version"):
            return [{"version": self.version}]
        if sql.startswith("SELECT * FROM public.get_previous_planning_answers"):
            return [self.row(key, value) for key, value in self.previous.items()]
        if sql.startswith("SELECT * FROM public.weekly_planning_answers"):
            return [self.row(key, value) for key, value in self.answers.items()]
        self.writes.append((sql, args))
        if sql.startswith("DELETE FROM public.weekly_planning_answers"):
            self.answers.pop(args[1], None)
            return []
        if sql.startswith("INSERT INTO public.weekly_planning_answers"):
            _, key, text, number, boolean, json = args
            self.answers[key] = next(v for v in (getattr(json, "adapted", None), boolean, number, text) if v is not None)
            return []
        if sql.startswith("UPDATE public.weekly_area_reports"):
            return []
        if sql.startswith("SELECT public.submit_current_weekly_report"):
            return [{"report_id": 1}]
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
        return caught
    raise AssertionError(f"{call.__name__} did not raise {error.__name__}")


def save(plan, values, version=None):
    body = {"changes_only": True, **values}
    if version is not None:
        body["catalog_version"] = version
    return planning.save_planning_answers(plan, CONTEXT, 1, body)


def by_key(key):
    return next(q for q in CATALOG if q["question_key"] == key)


def test_every_type_is_stored_like_beta():
    plan = Plan()
    result = save(plan, {"sacrament_attendance_actual": "12", "service_hours_goal": 2.5, "ward_coordination_held": False,
                         "ward_coordination_attendance": {"bishop": "yes"}, "contact_method": "visit", "lesson_place": "home",
                         "topics": ["prayer", "faith", "prayer"], "next_visit": "2026-10-02", "companion_note": "  Call Anna ",
                         "weekly_action_plan": "Plan the week"}, version=7)
    assert result["answers"] == {"sacrament_attendance_actual": 12, "service_hours_goal": 2.5, "ward_coordination_held": False,
                                 "ward_coordination_attendance": {"bishop": "yes"}, "contact_method": "visit", "lesson_place": "home",
                                 "topics": ["faith", "prayer"], "next_visit": "2026-10-02", "companion_note": "Call Anna",
                                 "weekly_action_plan": "Plan the week"}, result["answers"]
    assert result["catalog_version"] == 7 and "catalog_changed" not in result and "dropped" not in result
    columns = {args[1]: args[2:] for sql, args in plan.writes if sql.startswith("INSERT")}
    assert columns["ward_coordination_held"][:3] == (None, None, False)          # answer_boolean
    assert columns["next_visit"][0] == "2026-10-02"                             # DATE as text
    assert columns["sacrament_attendance_actual"][1] == Decimal(12)             # NUMBER as number


def test_bad_values_name_the_question_and_write_nothing():
    cases = [
        ("sacrament_attendance_actual", "abc", "Sacrament attendance must be a number."),
        ("sacrament_attendance_actual", 2.5, "Sacrament attendance must be a whole number."),
        ("sacrament_attendance_actual", -1, "Sacrament attendance must be zero or greater."),
        ("service_hours_goal", 0, "Service hours must be a number from 1 to 40."),
        ("service_hours_goal", 41, "Service hours must be a number from 1 to 40."),
        ("ward_coordination_held", "maybe", "Meeting held: choose Yes or No."),
        ("contact_method", "letter", "How did you contact them?: choose one of the listed answers."),
        ("lesson_place", ["home"], "Where?: enter text."),
        ("topics", ["faith", "fasting"], "Topics: choose from the listed answers."),
        ("topics", "faith", "Topics: choose from the listed answers."),
        ("next_visit", "2. Oktober", "Next visit: enter a date."),
        ("ward_coordination_attendance", ["Bishop"], "Who was there?: this page is out of date. Reload the page to answer it."),
        ("ward_coordination_attendance", "Bishop", "Who was there?: choose an answer in each row."),
        ("ward_coordination_attendance", {"bishop": "maybe"}, "Who was there?: choose one of the listed answers in each row."),
        ("ward_coordination_attendance", {"stake_president": "yes"}, "Who was there?: a row on this page is no longer asked. Reload the page."),
    ]
    for key, value, message in cases:
        plan = Plan()
        error = raises(ValueError, save, plan, {"weekly_action_plan": "kept?", key: value}, 7)
        assert str(error) == message, (key, value, str(error))
        assert plan.writes == [], (key, plan.writes)


def test_a_grid_save_merges_rows_so_companions_keep_theirs():
    plan = Plan(answers={"ward_coordination_attendance": {"bishop": "yes"}})
    save(plan, {"ward_coordination_attendance": {"gemiko_leader": "dont_have_one"}}, 7)
    assert plan.answers["ward_coordination_attendance"] == {"bishop": "yes", "gemiko_leader": "dont_have_one"}
    save(plan, {"ward_coordination_attendance": {"bishop": None}}, 7)
    assert plan.answers["ward_coordination_attendance"] == {"gemiko_leader": "dont_have_one"}
    save(plan, {"ward_coordination_attendance": {"gemiko_leader": ""}}, 7)
    assert "ward_coordination_attendance" not in plan.answers  # no row left: the answer is removed
    plan = Plan(answers={"topics": ["faith"]})
    save(plan, {"topics": []}, 7)
    assert "topics" not in plan.answers


def test_blank_clears_and_old_pages_keep_their_message():
    plan = Plan(answers={"weekly_action_plan": "old"})
    save(plan, {"weekly_action_plan": ""})
    assert "weekly_action_plan" not in plan.answers
    # A page from before catalogue versions, answering a question no longer asked, is told to reload.
    assert str(raises(ValueError, save, Plan(), {"retired_question": 3})) == planning.FORM_CHANGED_MESSAGE


def test_a_stale_page_saves_what_is_still_asked_and_gets_the_new_questions():
    catalog = [q for q in CATALOG if q["question_key"] != "companion_note"]  # retired in DA Management
    plan = Plan(catalog=catalog, version=8)
    result = save(plan, {"companion_note": "typed before the change", "weekly_action_plan": "still asked",
                         "topics": ["faith"]}, version=7)
    assert plan.answers == {"weekly_action_plan": "still asked", "topics": ["faith"]}
    assert result["catalog_changed"] is True and result["catalog_version"] == 8
    assert result["dropped"] == ["companion_note"] and result["note"]
    keys = [q["question_key"] for q in result["questions"]]
    assert "companion_note" not in keys and "weekly_action_plan" in keys
    assert next(q for q in result["questions"] if q["question_key"] == "sacrament_attendance_actual")["previous"] == 11
    # A value that no longer fits its (changed) question is left out too instead of failing the whole save.
    changed = copy.deepcopy(catalog)
    next(q for q in changed if q["question_key"] == "contact_method")["options"] = [{"value": "phone", "label": "Phone"}]
    plan = Plan(catalog=changed, version=9)
    result = save(plan, {"contact_method": "visit", "weekly_action_plan": "saved"}, version=8)
    assert plan.answers == {"weekly_action_plan": "saved"} and result["dropped"] == ["contact_method"]
    # A current page with a key that is not on the form (e.g. retired in the same second) loses only that key.
    plan = Plan(catalog=catalog, version=8)
    result = save(plan, {"companion_note": "x", "weekly_action_plan": "y"}, version=8)
    assert plan.answers == {"weekly_action_plan": "y"} and result["dropped"] == ["companion_note"] and "catalog_changed" not in result
    # An empty save from a stale page still brings the new questions (and writes nothing).
    plan = Plan(catalog=catalog, version=8)
    result = save(plan, {}, version=7)
    assert result["catalog_changed"] and plan.writes == []


def test_a_stale_page_keeps_the_rest_of_a_grid_or_tick_box_answer():
    # Review: when one grid row or one tick-box choice was retired, a stale save dropped the whole answer.
    catalog = copy.deepcopy(CATALOG)
    grid = next(q for q in catalog if q["question_key"] == "ward_coordination_attendance")
    grid["rows"] = [row for row in grid["rows"] if row["key"] != "gemiko_leader"]           # a row retired
    grid["options"] = [o for o in grid["options"] if o["value"] != "dont_have_one"]          # a grid choice retired
    topics = next(q for q in catalog if q["question_key"] == "topics")
    topics["options"] = [o for o in topics["options"] if o["value"] != "tithing"]            # a tick-box choice retired
    plan = Plan(answers={"ward_coordination_attendance": {"bishop": "no"}}, catalog=catalog, version=8)
    result = save(plan, {"ward_coordination_attendance": {"bishop": "yes", "gemiko_leader": "no"},
                         "topics": ["faith", "tithing"], "weekly_action_plan": "kept"}, version=7)
    assert plan.answers == {"ward_coordination_attendance": {"bishop": "yes"}, "topics": ["faith"], "weekly_action_plan": "kept"}, plan.answers
    assert result["dropped"] == [] and result["dropped_parts"] == {"ward_coordination_attendance": ["gemiko_leader"], "topics": ["tithing"]}
    assert result["catalog_changed"] is True and result["note"]
    # A row whose choice was retired is left out; a grid save with nothing left keeps the saved rows untouched.
    plan = Plan(answers={"ward_coordination_attendance": {"bishop": "no"}}, catalog=catalog, version=8)
    result = save(plan, {"ward_coordination_attendance": {"bishop": "dont_have_one"}}, version=7)
    assert plan.answers == {"ward_coordination_attendance": {"bishop": "no"}} and plan.writes == []
    assert result["dropped_parts"] == {"ward_coordination_attendance": ["bishop"]}
    # Only the retired choices: the tick boxes left are what the page chose (none), so the answer is cleared.
    plan = Plan(answers={"topics": ["faith"]}, catalog=catalog, version=8)
    result = save(plan, {"topics": ["tithing"]}, version=7)
    assert "topics" not in plan.answers and result["dropped_parts"] == {"topics": ["tithing"]}
    # A current page still gets the clear message for a row that is not asked (nothing is filtered then).
    plan = Plan(catalog=catalog, version=8)
    assert "no longer asked" in str(raises(ValueError, save, plan, {"ward_coordination_attendance": {"gemiko_leader": "no"}}, 8))


def test_the_version_is_read_before_the_questions():
    # Review: planning_form read the questions, then the version. A DA Management change committed in between gave
    # the page the old questions with the new version, so it was never sent the new ones. A change committed while
    # the questions are read must make the page's next save stale.
    class ChangedWhileReading(Plan):
        def run(self, sql, args):
            result = super().run(sql, args)
            if "FROM public.active_planning_questions apq" in " ".join(sql.split()):
                self.version += 1  # the change commits right after this statement took its snapshot
            return result

    plan = ChangedWhileReading(version=7)
    first = save(plan, {"weekly_action_plan": "a"}, version=7)
    assert first["catalog_version"] == 7 and "catalog_changed" not in first, first
    second = save(plan, {"weekly_action_plan": "b"}, version=first["catalog_version"])
    assert second["catalog_changed"] is True  # planning_form is checked the same way in tests/planning_catalog_db.py


def test_rules_work_like_beta():
    rule = lambda operator, value: {"parent": "p", "operator": operator, "value": value}
    passes = planning._rule_passes
    assert passes(rule("equals", "true"), True) and passes(rule("equals", "TRUE"), "true") and not passes(rule("equals", "true"), None)
    assert passes(rule("equals", "false"), False) and not passes(rule("equals", "false"), "")
    assert passes(rule("equals", "visit"), "visit") and not passes(rule("equals", "visit"), "phone")
    assert passes(rule("not_equals", "visit"), None)  # like Beta: String(undefined ?? "") !== "visit"
    assert passes(rule("equals", "3"), Decimal("3")) and passes(rule("equals", "3"), 3)
    assert passes(rule("greater_than", "0"), 1) and not passes(rule("greater_than", "0"), 0)
    assert not passes(rule("greater_than", "0"), None) and not passes(rule("greater_than", "0"), "")
    assert not passes(rule("greater_than", "0"), True)
    assert passes(rule("greater_than_or_equal", "2"), "2") and passes(rule("less_than", "2"), 1.5)
    assert passes(rule("less_than_or_equal", "2"), 2) and not passes(rule("less_than", "x"), 1)
    assert passes(rule("contains", "x"), None)  # an unknown rule shows the question, as in Beta


def test_hidden_follow_ups_count_as_their_value_when_hidden():
    visibility = lambda answers: planning._visibility(CATALOG, answers)
    hidden, values = visibility({"sacrament_attendance_actual": 0})
    assert hidden == {"sacrament_first_time", "sacrament_first_time_first_week", "ward_coordination_attendance"}
    assert values["sacrament_first_time"] == "0" and values["sacrament_first_time_first_week"] == "0"
    hidden, values = visibility({})  # attendance blank: both follow-ups hidden and blank
    assert values["sacrament_first_time"] is None and values["sacrament_first_time_first_week"] is None
    hidden, values = visibility({"sacrament_attendance_actual": 5, "sacrament_first_time": 0})
    assert hidden == {"sacrament_first_time_first_week", "ward_coordination_attendance"} and values["sacrament_first_time_first_week"] == "0"
    hidden, _ = visibility({"sacrament_attendance_actual": 5, "sacrament_first_time": 2, "ward_coordination_held": True})
    assert hidden == set()
    # A rule on a question that is not on the form (retired) is ignored by the API (planning.CATALOG_SQL); a
    # parent that is hidden hides its children too.
    chain = [question("a", "NUMBER"), question("b", "NUMBER", rules=[{"parent": "a", "operator": "greater_than", "value": "0"}]),
             question("c", "BOOLEAN", rules=[{"parent": "b", "operator": "less_than", "value": "100"}])]
    assert planning._visibility(chain, {"a": 0, "b": 5})[0] == {"b", "c"}
    # Children listed before their parents are still evaluated after them.
    assert planning._visibility(list(reversed(chain)), {"a": 0, "b": 5})[0] == {"b", "c"}


def test_a_value_when_hidden_that_does_not_fit_never_blocks_a_save():
    # Set in Studio (DA Management refuses these). The page sends the follow-up's value when its parent hides it,
    # together with the parent: the parent and everything else must still be saved.
    for key, fallback, sent in (("sacrament_first_time", "-1", -1), ("sacrament_first_time", "1.5", 1.5),
                                ("contact_method", "None", "None")):
        catalog = copy.deepcopy(CATALOG)
        next(q for q in catalog if q["question_key"] == key)["value_when_hidden"] = fallback
        kept = 2 if key == "sacrament_first_time" else "phone"
        plan = Plan(catalog=catalog, answers={"sacrament_attendance_actual": 5, key: kept})
        result = save(plan, {"sacrament_attendance_actual": 0, key: sent, "weekly_action_plan": "Saved"}, 7)
        assert plan.answers["sacrament_attendance_actual"] == 0 and plan.answers["weekly_action_plan"] == "Saved", (key, fallback)
        assert plan.answers[key] == kept and "dropped" not in result, (key, plan.answers, result)
    # Values a missionary typed are still checked.
    assert str(raises(ValueError, save, Plan(), {"sacrament_first_time": -1}, 7)) == "1st Time must be zero or greater."
    assert planning._is_value_when_hidden(by_key("sacrament_first_time"), 0)
    assert planning._is_value_when_hidden(by_key("sacrament_first_time"), "0.0")
    assert not planning._is_value_when_hidden(by_key("sacrament_first_time"), -1)
    assert not planning._is_value_when_hidden(by_key("contact_method"), "None")


def test_required_check_skips_hidden_questions_and_needs_explicit_answers():
    complete = {"sacrament_attendance_actual": 0, "service_hours_goal": 3, "ward_coordination_held": False,
                "contact_method": "phone", "lesson_place": "church", "topics": ["faith"], "next_visit": "2026-10-01",
                "weekly_action_plan": "Plan"}
    missing = planning._missing_question_answers
    assert missing(CATALOG, complete) == []  # follow-ups and the grid are hidden; the note is optional
    assert missing(CATALOG, {**complete, "ward_coordination_held": None}) == ["ward_coordination_held"]
    assert missing(CATALOG, {k: v for k, v in complete.items() if k != "ward_coordination_held"}) == ["ward_coordination_held"]
    assert missing(CATALOG, {**complete, "ward_coordination_held": True}) == ["ward_coordination_attendance"]
    assert missing(CATALOG, {**complete, "ward_coordination_held": True, "ward_coordination_attendance": {"bishop": "yes"}}) == \
        ["ward_coordination_attendance"]  # every row needs an answer
    assert missing(CATALOG, {**complete, "ward_coordination_held": True,
                             "ward_coordination_attendance": {"bishop": "yes", "gemiko_leader": "no"}}) == []
    assert missing(CATALOG, {**complete, "ward_coordination_held": True, "ward_coordination_attendance": []}) == \
        ["ward_coordination_attendance"]  # the old empty-list shape counts as unanswered
    # "1st Time 1st Week" waits for "1st Time" (hidden until it is above 0).
    assert missing(CATALOG, {**complete, "sacrament_attendance_actual": 4}) == ["sacrament_first_time"]
    assert missing(CATALOG, {**complete, "sacrament_attendance_actual": 4, "sacrament_first_time": 1}) == ["sacrament_first_time_first_week"]
    assert missing(CATALOG, {**complete, "sacrament_attendance_actual": 4, "sacrament_first_time": 0}) == []
    assert missing(CATALOG, {**complete, "topics": [], "weekly_action_plan": "  "}) == ["topics", "weekly_action_plan"]
    assert missing(CATALOG, {}) == ["sacrament_attendance_actual", "service_hours_goal", "ward_coordination_held",
                                    "contact_method", "lesson_place", "topics", "next_visit", "weekly_action_plan"]


def test_submit_refuses_missing_answers_with_their_keys():
    patch.object(planning, "_check_people_complete", lambda conn, report: None).start()  # tested in the other part's file
    import importlib
    app_module = importlib.import_module("app")
    plan = Plan(answers={"sacrament_attendance_actual": 0, "weekly_action_plan": "Plan"})
    error = raises(planning.FieldErrors, planning.submit_planning_report, plan, CONTEXT, 1)
    assert set(error.fields) == {"service_hours_goal", "ward_coordination_held", "contact_method", "lesson_place", "topics", "next_visit"}
    assert str(error) == "6 questions still need an answer. Each one is marked below."
    assert not any("submit_current_weekly_report" in sql for sql, _ in plan.writes)
    with app_module.app.test_request_context():
        response, status = app_module.error_response(error)
    assert status == 400 and response.get_json()["fields"]["contact_method"] == "Answer this question."
    complete = Plan(answers={"sacrament_attendance_actual": 0, "service_hours_goal": 3, "ward_coordination_held": False,
                             "contact_method": "phone", "lesson_place": "church", "topics": ["faith"],
                             "next_visit": "2026-10-01", "weekly_action_plan": "Plan"})
    assert planning.submit_planning_report(complete, CONTEXT, 1)["status"] == "SUBMITTED"
    one = Plan(answers={**{k: v for k, v in complete.answers.items() if k != "topics"}})
    assert str(raises(planning.FieldErrors, planning.submit_planning_report, one, CONTEXT, 1)) == \
        "1 question still needs an answer. Each one is marked below."


def test_the_form_carries_the_questions_with_last_week_and_the_version():
    questions = planning._form_questions(Plan(), 5)
    held = next(q for q in questions if q["question_key"] == "ward_coordination_held")
    assert held["previous"] is True and held["rules"] == [] and next(
        q for q in questions if q["question_key"] == "topics")["previous"] is None
    grid = next(q for q in questions if q["question_key"] == "ward_coordination_attendance")
    assert [row["key"] for row in grid["rows"]] == ["bishop", "gemiko_leader"] and grid["options"][2]["value"] == "dont_have_one"
    assert planning._catalog_version(Plan(version=12)) == 12


if __name__ == "__main__":
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_") and callable(value)]
    for test in tests:
        test()
        print("ok", test.__name__)
    print(f"{len(tests)} tests passed")
