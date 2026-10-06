"""The Overview's key indicators compare this week's result with the goal the week before set (as the dashboards do),
and still show next week's goal as the big number. Two weeks of data, no database needed.

Run in the portal-api image: python tests/test_overview_previous_goal.py
"""
import os
import sys
from collections import defaultdict
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("SUPABASE_URL", "http://supabase.invalid")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "unit-test-only")
import planning  # noqa: E402

THIS_WEEK = {"sunday": "2026-09-27"}
# Last week's plans: ward 1 aimed at 4 and 3, ward 2 at 2 and (no answer) for sacrament attendance.
LAST_WEEK = [
    {"id": 11, "report_id": 11, "unit_id": 1, "friends_found_goal": None, "sacrament_attendance_goal": None},
    {"id": 12, "report_id": 12, "unit_id": 2, "friends_found_goal": None, "sacrament_attendance_goal": None},
]
LAST_WEEK_ANSWERS = [
    {"weekly_area_report_id": 11, "question_key": "friends_found_goal", "answer_number": 4},
    {"weekly_area_report_id": 11, "question_key": "sacrament_attendance_goal", "answer_number": 3},
    {"weekly_area_report_id": 12, "question_key": "friends_found_goal", "answer_number": 2},
]
# This week's plans: results of the week just ended, and the goals for next week (deliberately different).
THIS_REPORTS = [{"report_id": 21, "unit_id": 1, "unit": "Ward A"}, {"report_id": 22, "unit_id": 2, "unit": "Ward B"}]
THIS_ANSWERS = defaultdict(dict, {
    21: {"friends_found_actual": 5, "friends_found_goal": 9, "sacrament_attendance_actual": 20, "sacrament_attendance_goal": 30},
    22: {"friends_found_actual": 1, "friends_found_goal": 8},
})


def fake_fetch_rows(rows, answers):
    def fetch(conn, sql, args=()):
        return answers if "weekly_planning_answers" in sql else rows
    return fetch


def indicators(last_week_rows, last_week_answers):
    with patch.object(planning, "fetch_rows", fake_fetch_rows(last_week_rows, last_week_answers)):
        previous = planning._previous_goals(None, 7, THIS_WEEK)
    return planning._key_indicator_summaries(THIS_REPORTS, THIS_ANSWERS, previous), previous


def tile(result, key):
    return next(item for item in result if item["key"] == key)


def test_goal_is_last_weeks_not_this_weeks():
    result, _ = indicators(LAST_WEEK, LAST_WEEK_ANSWERS)
    friends = tile(result, "friends_found")
    assert friends["actual"] == 6 and friends["goal"] == 17, friends  # this week's result, next week's goal
    assert friends["previous_goal"] == 6, friends  # 4 + 2 set last week: not the 17 typed this week
    assert [unit["previous_goal"] for unit in friends["units"]] == [4, 2], friends["units"]


def test_unit_without_a_goal_last_week_is_empty_not_zero():
    result, _ = indicators(LAST_WEEK, LAST_WEEK_ANSWERS)
    sacrament = tile(result, "sacrament_attendance")
    assert sacrament["previous_goal"] == 3 and [u["previous_goal"] for u in sacrament["units"]] == [3, None]


def test_empty_previous_week_gives_none_everywhere():
    result, previous = indicators([], [])
    assert previous == {}
    for item in result:
        assert item["previous_goal"] is None, item
        assert all(unit["previous_goal"] is None for unit in item["units"]), item
    assert tile(result, "friends_found")["goal"] == 17  # next week's goal is unaffected


def test_asks_for_the_week_before():
    seen = []
    def fetch(conn, sql, args=()):
        seen.append((sql, args))
        return []
    with patch.object(planning, "fetch_rows", fetch):
        planning._previous_goals(None, 7, THIS_WEEK)
    assert "sunday = %s::date - 7" in seen[0][0] and seen[0][1] == (7, "2026-09-27")
    with patch.object(planning, "fetch_rows", fetch):
        assert planning._previous_goals(None, None, THIS_WEEK) == {}


def test_page_shows_dash_and_no_bar():
    page = (Path(__file__).resolve().parents[2] / "portal" / "home.html")
    if not page.exists():
        return
    text = page.read_text(encoding="utf-8")
    assert "k.previous_goal" in text and "Goal for next week" in text and "hasPrevious ?" in text
    assert "Goal for the week" not in text


if __name__ == "__main__":
    for name, function in sorted(globals().items()):
        if name.startswith("test_") and callable(function):
            function()
            print("ok", name)
