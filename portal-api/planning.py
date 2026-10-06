"""Weekly Planning: a companionship's plan for the week, and the planning numbers on the Overview.

What it is: plain functions that read and write the weekly plans. app.py's /api/planning/... and /api/overview
routes call them; they never answer HTTP themselves (a refusal is a ValueError, PermissionError or one of the error
classes below, which app.error_response turns into a 400, 403 or 409).
Who uses it: missionaries (their own plan in portal/planning.html), leaders and managers (the Overview in
portal/home.html, with the plans of their stewardship).
How it fits: every function gets a connection from app.user_db(), which runs as the signed-in person with their
sign-in claims, so the database's row-level security checks every row too. No read here starts a plan or creates a
reporting week; only planning_form() starts this week's shared draft (public.start_current_weekly_report).

The parts of this file, top to bottom:
1. Small helpers.
2. The Overview: planning_overview() and the stewardship list of plans.
3. The plan's questions: planning_form(), save_planning_answers() and the show/hide rules (DA Management keeps the
   questions in the database, migration 024).
4. People on the plan: the weekly person cards (save_planning_people).
5. New people: the New Member and baptismal-date forms (validate_new_person, create_planning_person).
6. Managing a person: edit, transfer, end follow-up, drop, baptized, and delete (friends only) (manage_planning_person).
7. Submit and unlock.
"""

from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

import psycopg2
from psycopg2.extras import Json

import mission_time
import roles
from helpers import fetch_one, fetch_rows, json_ready

# The six key indicators: (key, label, answer key of the result, answer key of the goal, report column of the result,
# report column of the goal, answer key of the action plan). The answer wins; the report column is the fallback for
# plans saved before the question catalogue.
KEY_INDICATORS = (
    ("new_member_sacrament", "New member sacrament attendance", "nm_sacrament_attendance", "nm_sacrament_attendance_goal", "new_member_sacrament_actual", "new_member_sacrament_goal", "nm_sacrament_attendance_plan"),
    ("baptisms_confirmations", "Baptisms and confirmations", "baptisms_confirmations_actual", "baptisms_confirmations_goal", "baptisms_confirmations_actual", "baptisms_confirmations_goal", "baptisms_confirmations_plan"),
    ("baptismal_dates", "Baptismal dates", "baptismal_dates_actual", "baptismal_dates_goal", "baptismal_dates_actual", "baptismal_dates_goal", "baptismal_dates_plan"),
    ("sacrament_attendance", "Sacrament attendance", "sacrament_attendance_actual", "sacrament_attendance_goal", "sacrament_attendance_actual", "sacrament_attendance_goal", "sacrament_attendance_plan"),
    ("members_at_lessons", "Members at lessons", "members_at_lessons_actual", "members_at_lessons_goal", "lessons_with_members_actual", "lessons_with_members_goal", "members_at_lessons_plan"),
    ("friends_found", "New people being taught", "friends_found_actual", "friends_found_goal", "friends_found_actual", "friends_found_goal", "friends_found_plan"),
)

# Other goals on the Overview: the goal's answer key and the answer keys whose sum is its result.
OTHER_ACTUAL_KEYS = {
    "member_meals_goal": ("member_meals_active_actual", "member_meals_less_active_actual", "member_meals_part_member_actual"),
    "member_visits_goal": ("member_visits_active_actual", "member_visits_less_active_actual", "member_visits_part_member_actual"),
    "youth_activities_goal": ("youth_activities_actual",),
    "mini_mission_goal": ("mini_mission_actual",),
    "service_hours_goal": ("service_hours_actual",),
}
COMPLETE_STATUSES = {"SUBMITTED", "LOCKED"}
# Shown when a page stayed open over the Sunday rollover and still points at the old week's plan.
LAST_WEEK_MESSAGE = "This plan is for last week. Reload to open this week's plan."
# Shown to a page opened before saves were limited to changes (see _changes_only).
RELOAD_MESSAGE = "This page was updated. Reload to keep saving."
# The report placeholder for a ward or branch (or an area without one) that has no plan this week yet.
NOT_STARTED = "NOT_STARTED"


# ================================================================================================ 1. small helpers

def _number(value):
    """A number from an answer (int when whole, else float); None for no answer, true/false or text."""
    if isinstance(value, bool) or value is None or value == "":
        return None
    try:
        number = Decimal(str(value))
        if not number.is_finite():
            return None
        return int(number) if number == number.to_integral_value() else float(number)
    except (ValueError, ArithmeticError):
        return None


def _is_blank(value):
    """No answer: None, or text of only spaces. (Saved answers are never empty lists or objects: a save removes
    them instead, see _clean_answer.)"""
    return value is None or (isinstance(value, str) and not value.strip())


def _answer_value(row):
    """The saved answer of a weekly_planning_answers row, from whichever column holds it."""
    for field in ("answer_json", "answer_boolean", "answer_number", "answer_text"):
        if row.get(field) is not None:
            return row[field]
    return None


def _sum(values):
    """The sum of the numbers among values; None when there is none."""
    numbers = [_number(value) for value in values]
    numbers = [value for value in numbers if value is not None]
    return sum(numbers) if numbers else None


def _metric(answers, report, question_key, column):
    """A key indicator: the answer when there is one, else the report column (plans from before migration 024)."""
    value = _number(answers.get(question_key))
    return value if value is not None else _number(report.get(column))


def _status(reports, expected_count):
    """(status, complete, submitted count) of an area's plans: SUBMITTED once every ward's plan is in, DRAFT once one
    was started, else NOT_STARTED."""
    submitted = sum(report.get("status") in COMPLETE_STATUSES for report in reports)
    complete = expected_count > 0 and submitted == expected_count
    if complete:
        return "SUBMITTED", True, submitted
    if any(report.get("report_id") for report in reports):
        return "DRAFT", False, submitted
    return NOT_STARTED, False, submitted


def _placeholder(unit_id=None, unit="Area plan"):
    """A plan that was not started yet, for the Overview's lists."""
    return {"report_id": None, "unit_id": unit_id, "unit": unit, "status": NOT_STARTED}


def _report_answers(conn, report_id):
    """{question key: answer} of one plan."""
    rows = fetch_rows(conn, "SELECT * FROM public.weekly_planning_answers WHERE weekly_area_report_id=%s", (report_id,))
    return {row["question_key"]: _answer_value(row) for row in rows}


# ================================================================================================ 2. the Overview

def _scoped_areas(conn, context):
    """(scope, areas) a leader may look at: their DL district, ZL zone or (managers) mission, as explicit leadership
    assignments, on top of the database's row-level security. (None, []) for everyone else."""
    stewardship = roles.planning_scope(context)  # managers: mission; otherwise the main role's DL/ZL stewardship
    if stewardship is None:
        return None, []
    scopes = fetch_rows(conn, "SELECT * FROM public.current_user_scope WHERE user_id = %s", (context["user_id"],))
    if stewardship == "district":
        ids = {row.get("leadership_district_id") for row in scopes if row.get("leadership_role") == "DL"}
        ids.discard(None)
        if not ids:
            return "district", []
        predicate, args = "d.id = ANY(%s)", (list(ids),)
        scope = "district"
    elif stewardship == "zone":
        ids = {row.get("leadership_zone_id") for row in scopes if row.get("leadership_role") == "ZL"}
        ids.discard(None)
        if not ids:
            return "zone", []
        predicate, args = "z.id = ANY(%s)", (list(ids),)
        scope = "zone"
    else:
        mission_ids = {row.get("leadership_mission_id") or row.get("mission_id") for row in scopes}
        if context.get("mission_id"):
            mission_ids.add(context["mission_id"])
        mission_ids.discard(None)
        predicate, args = ("z.mission_id = ANY(%s)", (list(mission_ids),)) if mission_ids else ("TRUE", ())
        scope = "mission"
    areas = fetch_rows(conn, f"""
        SELECT a.id AS area_id, a.name AS area, d.id AS district_id,
               d.name AS district, z.id AS zone_id, z.name AS zone
        FROM public.areas a
        JOIN public.districts d ON d.id = a.district_id
        JOIN public.zones z ON z.id = d.zone_id
        WHERE a.active AND public.can_access_area(a.id) AND {predicate}
        ORDER BY z.name, d.name, a.name
    """, args)
    return scope, areas


def _stewardship(conn, context, week):
    """The leader's list on the Overview: every area of their stewardship with how far its plans are this week."""
    scope, areas = _scoped_areas(conn, context)
    if scope is None:
        return None
    area_ids = [area["area_id"] for area in areas]
    if not area_ids:
        return {"scope": scope, "label": "Your stewardship", "total_areas": 0, "complete_areas": 0, "incomplete_areas": 0, "areas": []}
    units = fetch_rows(conn, """
        SELECT au.area_id, u.id AS unit_id, u.name AS unit
        FROM public.area_units au JOIN public.units u ON u.id = au.unit_id
        WHERE au.active AND u.active AND au.area_id = ANY(%s)
        ORDER BY au.primary_unit DESC, u.name
    """, (area_ids,))
    reports = fetch_rows(conn, """
        SELECT war.id AS report_id, war.area_id, war.unit_id,
               u.name AS unit, war.status, war.submitted_at
        FROM public.weekly_area_reports war
        JOIN public.reporting_weeks rw ON rw.id = war.reporting_week_id
        LEFT JOIN public.units u ON u.id = war.unit_id
        WHERE rw.sunday = %s AND war.area_id = ANY(%s)
    """, (week["sunday"], area_ids))
    units_by_area, reports_by_area = defaultdict(list), defaultdict(list)
    for unit in units:
        units_by_area[unit["area_id"]].append(unit)
    for report in reports:
        reports_by_area[report["area_id"]].append(report)
    for area in areas:
        found = reports_by_area[area["area_id"]]
        expected = units_by_area[area["area_id"]]
        by_unit = {report["unit_id"]: report for report in found}
        if expected:
            attached = {unit["unit_id"] for unit in expected}
            area_reports = [by_unit.get(unit["unit_id"], _placeholder(unit["unit_id"], unit["unit"])) for unit in expected]
            area_reports += [report for unit_id, report in by_unit.items() if unit_id not in attached]  # see _one_plan_per_unit
        else:
            area_reports = found or [_placeholder()]
        status, complete, submitted = _status(area_reports, len(area_reports))
        area.update(status=status, complete=complete, completed_units=submitted,
                    unit_count=len(area_reports), reports=area_reports)
    complete_count = sum(area["complete"] for area in areas)
    label = {"district": "District planning", "zone": "Zone planning", "mission": "Mission planning"}[scope]
    return {"scope": scope, "label": label, "total_areas": len(areas),
            "complete_areas": complete_count, "incomplete_areas": len(areas) - complete_count,
            "areas": areas}


def _overview_week(conn, week_sunday):
    """The reporting week to show: the one asked for (it must not be in the future), else the current one. Without
    a row for the current week yet (no plan started), a stand-in with only its Sunday."""
    week = fetch_one(conn, """
        SELECT id, sunday, planning_open_at, planning_due_at
        FROM public.reporting_weeks WHERE sunday = COALESCE(%s::date,public.current_reporting_sunday())
          AND sunday <= public.current_reporting_sunday()
    """, (week_sunday,))
    if week is None and week_sunday:
        raise ValueError("That reporting week is not available.")
    return week or fetch_one(conn, "SELECT NULL::bigint AS id, public.current_reporting_sunday() AS sunday, NULL::timestamptz AS planning_open_at, NULL::timestamptz AS planning_due_at")


def _area_to_show(conn, context, area_id):
    """(area id, viewing_area): the person's own area, or another area of their stewardship they asked for (then
    viewing_area holds its names). PermissionError for an area outside their stewardship."""
    own_area_id = context.get("area_id")
    if area_id is None or area_id == own_area_id:
        return own_area_id, None
    _, accessible_areas = _scoped_areas(conn, context)
    viewing_area = next((area for area in accessible_areas if area["area_id"] == area_id), None)
    if viewing_area is None:
        raise PermissionError("This area is outside your stewardship.")
    return area_id, viewing_area


def _area_details(conn, context, area_id, viewing_area, week):
    """(units, companions, reports) of the area shown: its wards and branches, the missionaries serving there (a
    leader looking at another area sees all of them; on the own area the person is left out) and this week's plans."""
    if viewing_area:
        units = fetch_rows(conn, """
            SELECT u.id AS unit_id, u.name AS unit, u.unit_type, au.primary_unit
            FROM public.area_units au JOIN public.units u ON u.id = au.unit_id
            WHERE au.area_id = %s AND au.active AND u.active
            ORDER BY au.primary_unit DESC, u.name
        """, (area_id,))
    else:
        units = fetch_rows(conn, "SELECT unit_id, unit, unit_type, primary_unit FROM public.current_user_area_units WHERE area_id = %s", (area_id,))
    companions = fetch_rows(conn, """
        SELECT DISTINCT m.id AS missionary_id, m.display_name, m.missionary_type
        FROM public.missionary_assignments ma JOIN public.missionaries m ON m.id = ma.missionary_id
        WHERE ma.area_id = %s AND ma.start_date <= CURRENT_DATE
          AND (ma.end_date IS NULL OR ma.end_date >= CURRENT_DATE)
          AND (%s OR m.id <> %s)
        ORDER BY m.display_name
    """, (area_id, bool(viewing_area), context.get("missionary_id") or -1))
    reports = fetch_rows(conn, """
        SELECT war.*, war.id AS report_id, u.name AS unit
        FROM public.weekly_area_reports war
        JOIN public.reporting_weeks rw ON rw.id = war.reporting_week_id
        LEFT JOIN public.units u ON u.id = war.unit_id
        WHERE war.area_id = %s AND rw.sunday = %s
        ORDER BY war.updated_at DESC, war.id DESC
    """, (area_id, week["sunday"]))
    return units, companions, reports


def _one_plan_per_unit(reports, units, area_id):
    """One plan (or a not-started placeholder) per ward or branch of the area, the newest plan when there are two;
    an area without wards shows its plans, or one "Area plan" placeholder. A plan of a unit that is not attached to the
    area (any more), or with no unit, still counts, after the attached units: Glimpse and the dashboards add it too."""
    by_unit = {}
    for report in reports:
        by_unit.setdefault(report["unit_id"], report)
    if units:
        attached = {unit["unit_id"] for unit in units}
        shown = [by_unit.get(unit["unit_id"], _placeholder(unit["unit_id"], unit["unit"])) for unit in units]
        return shown + [report for unit_id, report in by_unit.items() if unit_id not in attached]
    if area_id is not None and not reports:
        return [_placeholder()]
    return reports


def _answers_by_report(conn, report_ids):
    """({report id: {question key: answer}}, the times answers were saved)."""
    answers_by_report, saved_at = defaultdict(dict), []
    if report_ids:
        for row in fetch_rows(conn, "SELECT * FROM public.weekly_planning_answers WHERE weekly_area_report_id = ANY(%s)", (report_ids,)):
            answers_by_report[row["weekly_area_report_id"]][row["question_key"]] = _answer_value(row)
            if row.get("updated_at"):
                saved_at.append(row["updated_at"])
    return answers_by_report, saved_at


def _previous_goals(conn, area_id, week):
    """{unit id: {indicator key: the goal}} the area's plans of the week before `week` set, the goals this week's results
    are measured against (the same rule as the dashboards and Call-ins: "goal set the week before"). The newest plan
    counts when a unit has two. Empty when the week before has no plan."""
    if area_id is None or not week.get("sunday"):
        return {}
    rows = fetch_rows(conn, """
        SELECT war.*, war.id AS report_id
        FROM public.weekly_area_reports war
        JOIN public.reporting_weeks rw ON rw.id = war.reporting_week_id
        WHERE war.area_id = %s AND rw.sunday = %s::date - 7
        ORDER BY war.updated_at DESC, war.id DESC
    """, (area_id, week["sunday"]))
    newest = {}
    for row in rows:
        newest.setdefault(row["unit_id"], row)
    answers_by_report, _ = _answers_by_report(conn, [row["report_id"] for row in newest.values()])
    return {unit_id: {key: _metric(answers_by_report[row["report_id"]], row, goal_key, goal_column)
                      for key, _, _, goal_key, _, goal_column, _ in KEY_INDICATORS}
            for unit_id, row in newest.items()}


def _key_indicator_summaries(reports, answers_by_report, previous_goals=None):
    """The six key indicators: the result and the next week's goal added up over the area's plans, with each plan's own
    numbers. previous_goal is the goal the week before set for this week's result (None when it set none)."""
    previous_goals = previous_goals or {}
    key_indicators = []
    for key, label, actual_key, goal_key, actual_column, goal_column, plan_key in KEY_INDICATORS:
        details = []
        for report in reports:
            answers = answers_by_report[report.get("report_id")]
            before = previous_goals.get(report.get("unit_id"), {}).get(key)
            details.append({"unit": report.get("unit"), "report_id": report.get("report_id"),
                            "actual": _metric(answers, report, actual_key, actual_column),
                            "goal": _metric(answers, report, goal_key, goal_column),
                            "previous_goal": before})
        key_indicators.append({"key": key, "label": label, "actual": _sum(detail["actual"] for detail in details),
                               "goal": _sum(detail["goal"] for detail in details),
                               "previous_goal": _sum(goals.get(key) for goals in previous_goals.values()), "units": details})
    return key_indicators


def _other_goal_summaries(conn, questions, reports, answers_by_report, report_ids):
    """Every other goal of the plans: the catalogue's *_goal questions, the two lesson goals of the first planning
    form, and each New Member's lesson goal."""
    indicator_goals = {indicator[3] for indicator in KEY_INDICATORS}
    other_definitions = [question for question in questions if question["question_key"].endswith("_goal") and question["question_key"] not in indicator_goals]
    other_goals = []
    for question in other_definitions:
        key = question["question_key"]
        details = []
        for report in reports:
            answers = answers_by_report[report.get("report_id")]
            actual = _sum(answers.get(actual_key) for actual_key in OTHER_ACTUAL_KEYS.get(key, ()))
            details.append({"unit": report.get("unit"), "actual": actual, "goal": _number(answers.get(key))})
        label = question["question_label"].split("—")[0].strip()
        other_goals.append({"key": key, "label": label, "section": question["section_title"],
                            "actual": _sum(detail["actual"] for detail in details), "goal": _sum(detail["goal"] for detail in details), "units": details})
    # Goals saved by the first planning form stay visible even though the question catalogue no longer asks them.
    for key, label in (("lessons_with_friends", "Lessons with friends"), ("follow_up_lessons", "Follow-up lessons")):
        details = [{"unit": report.get("unit"), "actual": _number(report.get(key + "_actual")), "goal": _number(report.get(key + "_goal"))} for report in reports]
        other_goals.append({"key": key, "label": label, "section": "Teaching and follow-up",
                            "actual": _sum(detail["actual"] for detail in details), "goal": _sum(detail["goal"] for detail in details), "units": details})
    if report_ids:
        member_goals = fetch_rows(conn, """
            SELECT wnm.weekly_area_report_id, wnm.new_member_id, nm.display_name,
                   wnm.lessons_actual, wnm.lessons_goal, u.name AS unit
            FROM public.weekly_new_members wnm
            JOIN public.weekly_area_reports war ON war.id = wnm.weekly_area_report_id
            LEFT JOIN public.new_members nm ON nm.id = wnm.new_member_id
            LEFT JOIN public.units u ON u.id = war.unit_id
            WHERE wnm.weekly_area_report_id = ANY(%s) AND wnm.lessons_goal IS NOT NULL
            ORDER BY u.name, wnm.display_order, wnm.id
        """, (report_ids,))
        other_goals.extend({"key": f"new_member_lessons_{member['weekly_area_report_id']}_{member['new_member_id']}",
                            "label": "New member lessons" + (f" · {member['display_name']}" if member.get("display_name") else ""),
                            "section": "New member follow-up", "actual": member["lessons_actual"],
                            "goal": member["lessons_goal"], "unit": member["unit"]} for member in member_goals)
    return other_goals


def _action_plans(reports, answers_by_report, definition_by_key):
    """(the action plans written for single goals, the weekly action plan of each ward's plan)."""
    action_plans, weekly_action_plans = [], []
    for report in reports:
        answers = answers_by_report[report.get("report_id")]
        for key, value in answers.items():
            if key.endswith("_plan") and key != "weekly_action_plan" and isinstance(value, str) and value.strip():
                definition = definition_by_key.get(key, {})
                label = definition.get("question_label", key.replace("_", " ").title()).replace("Optional: ", "").replace(" — Action Plan", "")
                action_plans.append({"key": key, "label": label, "unit": report.get("unit"), "text": value.strip()})
        weekly_action_plans.append({"report_id": report.get("report_id"), "unit_id": report.get("unit_id"),
                                    "unit": report.get("unit"), "text": answers.get("weekly_action_plan") or ""})
    return action_plans, weekly_action_plans


def _recent_weeks(conn, context, area_id):
    """Every reporting week that has at least one plan in what the person may look at (the area shown, plus their
    district, zone or mission), newest first, and always the current week (the week picker). Older weeks appear by
    themselves when older plans are uploaded. report_count and submitted_count are for the area shown; scope_plans is
    for everything the person may look at."""
    _, scoped = _scoped_areas(conn, context)
    area_ids = sorted({row["area_id"] for row in scoped} | ({area_id} if area_id is not None else set()))
    return fetch_rows(conn, """
        SELECT rw.id, rw.sunday,
               (rw.sunday < public.current_reporting_sunday()) AS is_closed,
               count(war.id) FILTER (WHERE war.area_id = %s)::integer AS report_count,
               count(war.id) FILTER (WHERE war.area_id = %s AND war.status IN ('SUBMITTED','LOCKED'))::integer AS submitted_count,
               count(war.id)::integer AS scope_plans
        FROM public.reporting_weeks rw
        LEFT JOIN public.weekly_area_reports war ON war.reporting_week_id = rw.id AND war.area_id = ANY(%s)
        WHERE rw.sunday <= public.current_reporting_sunday()
        GROUP BY rw.id, rw.sunday
        HAVING count(war.id) > 0 OR rw.sunday = public.current_reporting_sunday()
        ORDER BY rw.sunday DESC
    """, (area_id, area_id, area_ids))


def _assignment(context, units, companions, viewing_area):
    """Who is looking and where: the person's assignment, or the area they are looking at."""
    assignment = {key: context.get(key) for key in ("display_name", "missionary_id", "missionary_type", "role", "app_role", "leadership_role", "area_id", "area_code", "area", "district_id", "district", "zone_id", "zone", "mission_id", "mission")}
    assignment.update(roles=roles.roles(context), role_label=roles.describe(context))
    assignment.update(units=units, companions=companions)
    if viewing_area:
        assignment.update(viewing_area)
    return assignment


def planning_overview(conn, context, area_id=None, week_sunday=None):
    """The Overview's planning part: the assignment, the week's shared plan of one area (numbers, goals, action
    plans) and, for leaders, how far every area of their stewardship is."""
    week = _overview_week(conn, week_sunday)
    area_id, viewing_area = _area_to_show(conn, context, area_id)
    units, companions, reports = [], [], []
    if area_id is not None:
        units, companions, reports = _area_details(conn, context, area_id, viewing_area, week)
    reports = _one_plan_per_unit(reports, units, area_id)
    report_ids = [report["report_id"] for report in reports if report.get("report_id")]
    answers_by_report, answers_saved_at = _answers_by_report(conn, report_ids)
    activity_dates = [report["updated_at"] for report in reports if report.get("updated_at")] + answers_saved_at
    questions = fetch_rows(conn, "SELECT * FROM public.active_planning_questions ORDER BY section_order, question_order")
    definition_by_key = {question["question_key"]: question for question in questions}
    key_indicators = _key_indicator_summaries(reports, answers_by_report, _previous_goals(conn, area_id, week))
    other_goals = _other_goal_summaries(conn, questions, reports, answers_by_report, report_ids)
    action_plans, weekly_action_plans = _action_plans(reports, answers_by_report, definition_by_key)
    recent_weeks = _recent_weeks(conn, context, area_id)
    status, complete, submitted = _status(reports, len(reports))
    report_summaries = [{key: report.get(key) for key in ("report_id", "unit_id", "unit", "status", "submitted_at")} for report in reports]
    payload = {"assignment": _assignment(context, units, companions, viewing_area),
               "planning": {"week": week, "status": status,
                            "complete": complete, "completed_units": submitted, "unit_count": len(reports),
                            "key_indicators": key_indicators, "other_goals": other_goals,
                            "action_plans": action_plans, "weekly_action_plans": weekly_action_plans,
                            "reports": report_summaries, "recent_weeks": recent_weeks,
                            "activity_at": max(activity_dates) if activity_dates else None},
               "stewardship": _stewardship(conn, context, week), "viewing_area": viewing_area}
    return json_ready(payload)


# ================================================================================================ 3. the plan's questions

def _report_people(conn, report_id):
    """The people on a plan. New Member and friend rows also carry:
    is_current: the person is still assigned to the plan's area (only these are checked at submit and can be
    managed); on_submitted_plan: the person is on a submitted or locked plan, or on any plan of an earlier week
    (a leader's Unlock makes a plan a draft again, so the status alone forgets it was submitted); then "Delete"
    is refused, as in the delete functions of migration 023; person: their record, for the read-only details and
    the Edit details dialog."""
    new_members = fetch_rows(conn, """
        SELECT wnm.*, COALESCE(nm.display_name,'New member') AS display_name,
               EXISTS (SELECT 1 FROM public.new_member_area_assignments a
                       WHERE a.new_member_id=wnm.new_member_id AND a.end_date IS NULL AND a.area_id=war.area_id) AS is_current,
               EXISTS (SELECT 1 FROM public.weekly_new_members w2
                       JOIN public.weekly_area_reports r2 ON r2.id=w2.weekly_area_report_id
                       JOIN public.reporting_weeks rw2 ON rw2.id=r2.reporting_week_id
                       WHERE w2.new_member_id=wnm.new_member_id
                         AND (r2.status<>'DRAFT' OR rw2.sunday<public.current_reporting_sunday())) AS on_submitted_plan,
               CASE WHEN nm.id IS NOT NULL THEN jsonb_build_object(
                   'first_name',nm.first_name,'last_name',nm.last_name,
                   'baptismal_date_extended',nm.baptismal_date_extended,'baptism_date',nm.baptism_date,
                   'confirmation_date',nm.confirmation_date,'finding_source',nm.finding_source,
                   'date_of_birth',nm.date_of_birth,'age_range',nm.age_range,'gender',nm.gender,
                   'marital_status',nm.marital_status,'child_dependents',nm.child_dependents,
                   'living_situation',nm.living_situation,'native_language',nm.native_language,
                   'second_language',nm.second_language,'mission_language_competency',nm.mission_language_competency,
                   'country_of_origin',nm.country_of_origin,'conversion_success_notes',nm.conversion_success_notes) END AS person
        FROM public.weekly_new_members wnm
        JOIN public.weekly_area_reports war ON war.id=wnm.weekly_area_report_id
        LEFT JOIN public.new_members nm ON nm.id=wnm.new_member_id
        WHERE wnm.weekly_area_report_id=%s ORDER BY wnm.display_order,wnm.id
    """, (report_id,))
    baptismal_friends = fetch_rows(conn, """
        SELECT wbf.*, COALESCE(bdp.display_name,'Friend') AS display_name,
               EXISTS (SELECT 1 FROM public.baptismal_date_person_area_assignments a
                       WHERE a.baptismal_date_person_id=wbf.baptismal_date_person_id AND a.end_date IS NULL
                         AND a.area_id=war.area_id) AS is_current,
               EXISTS (SELECT 1 FROM public.weekly_baptismal_date_friends w2
                       JOIN public.weekly_area_reports r2 ON r2.id=w2.weekly_area_report_id
                       JOIN public.reporting_weeks rw2 ON rw2.id=r2.reporting_week_id
                       WHERE w2.baptismal_date_person_id=wbf.baptismal_date_person_id
                         AND (r2.status<>'DRAFT' OR rw2.sunday<public.current_reporting_sunday())) AS on_submitted_plan,
               CASE WHEN bdp.id IS NOT NULL THEN jsonb_build_object(
                   'first_name',bdp.first_name,'last_name',bdp.last_name,'finding_source',bdp.finding_source) END AS person
        FROM public.weekly_baptismal_date_friends wbf
        JOIN public.weekly_area_reports war ON war.id=wbf.weekly_area_report_id
        LEFT JOIN public.baptismal_date_people bdp ON bdp.id=wbf.baptismal_date_person_id
        WHERE wbf.weekly_area_report_id=%s ORDER BY wbf.display_order,wbf.id
    """, (report_id,))
    high_potential = fetch_rows(conn, """
        SELECT * FROM public.weekly_high_potential_friends
        WHERE weekly_area_report_id=%s ORDER BY display_order,id
    """, (report_id,))
    return {"new_members": new_members, "baptismal_friends": baptismal_friends, "high_potential": high_potential}


def _report_for_edit(conn, context, report_id, denied, not_draft):
    """The report, if the caller may still edit it: own area, this reporting week, still a draft.

    The report row stays locked until the save ends. The planning table triggers lock it too, but
    only after the answer or person row they change; taking it first makes two companions' saves of
    the same plan wait for each other instead of deadlocking when they touch rows in another order.
    """
    report = fetch_one(conn, """
        SELECT war.id, war.area_id, war.unit_id, war.status, rw.sunday,
               public.current_reporting_sunday() AS current_sunday
        FROM public.weekly_area_reports war JOIN public.reporting_weeks rw ON rw.id=war.reporting_week_id
        WHERE war.id=%s
        FOR UPDATE OF war
    """, (report_id,))
    if not report or report["area_id"] != context.get("area_id"):
        raise PermissionError(denied)
    # Checked before the status: a page left open over the Sunday rollover needs a reload, not a leader.
    if report["sunday"] != report["current_sunday"]:
        raise ValueError(LAST_WEEK_MESSAGE)
    if report["status"] != "DRAFT":
        raise ValueError(not_draft)
    return report


def _mark_worked_on(conn, report_id):
    """Record that the plan was just worked on. The Sunday planning reminder (reminders.planning_due)
    and the Overview's activity time read weekly_area_reports.updated_at, which person rows never
    change on their own, so every save or add that writes something calls this."""
    with conn.cursor() as cursor:
        cursor.execute("UPDATE public.weekly_area_reports SET updated_at=now() WHERE id=%s", (report_id,))


def _changes_only(values):
    """The saved values without their "changes_only": true marker, which every current page sends.

    A save without it comes from a page opened before saves were limited to changes. Such a page
    re-sends its whole, possibly stale copy (blank boxes included), which would overwrite or delete
    what the companion saved meanwhile, so it must reload first. Services from before this rule
    refuse the marker, so a current page can never make an older service delete anything either.
    """
    if not isinstance(values, dict) or values.get("changes_only") is not True:
        raise ValueError(RELOAD_MESSAGE)
    return {key: value for key, value in values.items() if key != "changes_only"}


# The question catalogue (planning_question_* tables; managed in DA Management, migration 024). Every question comes
# with its answer choices ("options"), grid rows ("rows"), show/hide rules ("rules": all must pass), number limits,
# placeholder and value_when_hidden. Rules whose parent question is retired are left out (the rules' read policy of
# migration 024 hides them from signed-in users too).
CATALOG_SQL = """
    SELECT apq.*, q.min_value, q.max_value, q.integer_only, q.placeholder, q.value_when_hidden, q.protected,
           COALESCE((SELECT jsonb_agg(jsonb_build_object('value', o.option_value, 'label', o.option_label)
                                      ORDER BY o.display_order, o.id)
                     FROM public.planning_question_options o WHERE o.question_id = apq.question_id AND o.active), '[]') AS options,
           COALESCE((SELECT jsonb_agg(jsonb_build_object('key', r.row_key, 'label', r.row_label) ORDER BY r.display_order, r.id)
                     FROM public.planning_question_grid_rows r WHERE r.question_id = apq.question_id AND r.active), '[]') AS rows,
           COALESCE((SELECT jsonb_agg(jsonb_build_object('parent', v.parent_question_key, 'operator', v.operator,
                                                         'value', v.comparison_value) ORDER BY v.id)
                     FROM public.planning_question_visibility_rules v
                     WHERE v.child_question_key = apq.question_key AND v.active
                       AND EXISTS (SELECT 1 FROM public.active_planning_questions p WHERE p.question_key = v.parent_question_key)),
                    '[]') AS rules
    FROM public.active_planning_questions apq JOIN public.planning_questions q ON q.id = apq.question_id
    ORDER BY apq.section_order, apq.question_order, apq.question_id
"""
# A page from before catalogue versions (it sends no "catalog_version") answered a question that is no longer on
# the form: it cannot show the new questions, so it must reload.
FORM_CHANGED_MESSAGE = "The planning form changed. Reload and try again."
TEXT_LIMITS = {"TEXT": 1000, "LONG_TEXT": 10000}
NUMBER_RULES = {"greater_than", "greater_than_or_equal", "less_than", "less_than_or_equal"}


def _catalog_questions(conn):
    """Every active question with its choices, rows and show/hide rules, in form order."""
    return fetch_rows(conn, CATALOG_SQL)


def _catalog_version(conn):
    """The catalogue version. Read it BEFORE the questions: each statement sees what was committed when it
    started, so a DA Management change committed in between then makes the page's next save stale (one extra
    refresh), instead of pairing old questions with the new version, which would never be refreshed."""
    row = fetch_one(conn, "SELECT version FROM public.planning_catalog_version")
    return int(row["version"]) if row else None


def _form_questions(conn, unit_id):
    """The active questions, each with last week's answer of this unit ("previous"; None when there is none)."""
    questions = _catalog_questions(conn)
    previous = {}
    if unit_id:
        previous = {row["question_key"]: _answer_value(row)
                    for row in fetch_rows(conn, "SELECT * FROM public.get_previous_planning_answers(%s)", (unit_id,))}
    for question in questions:
        question["previous"] = previous.get(question["question_key"])
    return questions


def _rule_text(value):
    """A value as the show/hide rules compare it (the page's ruleText): String(value ?? "")."""
    value = json_ready(value)
    if isinstance(value, bool):
        return "true" if value else "false"
    return "" if value is None else str(value)


def _rule_passes(rule, value):
    """One show/hide rule, evaluated exactly like the portal page (rulePasses in portal/planning.html)."""
    operator, expected = str(rule.get("operator") or "").strip(), rule.get("value")
    if operator == "equals":
        wanted = str(expected).lower()
        if wanted in {"true", "false"}:
            return value is (wanted == "true") or _rule_text(value).lower() == wanted
        return _rule_text(value) == str(expected)
    if operator == "not_equals":
        return _rule_text(value) != str(expected)
    if operator in NUMBER_RULES:
        actual, limit = _number(value), _number(expected)
        if _is_blank(value) or actual is None or limit is None:
            return False
        return {"greater_than": actual > limit, "greater_than_or_equal": actual >= limit,
                "less_than": actual < limit, "less_than_or_equal": actual <= limit}[operator]
    return True  # an unknown rule shows the question rather than hiding it


def _rule_order(questions):
    """Question keys with every rule's parent before its child (the order of the form otherwise)."""
    keys = [question["question_key"] for question in questions]
    known = set(keys)
    parents = {question["question_key"]: [rule.get("parent") for rule in question.get("rules") or [] if rule.get("parent") in known]
               for question in questions}
    order, seen = [], set()

    def visit(key, path):
        if key in seen or key in path:  # path: a rule loop is walked only once
            return
        for parent in parents[key]:
            visit(parent, path | {key})
        seen.add(key)
        order.append(key)

    for key in keys:
        visit(key, frozenset())
    return order


def _visibility(questions, answers):
    """(hidden keys, values) for these answers: a question is hidden when one of its rules fails or a parent is
    hidden. A hidden question with value_when_hidden counts as that value for the questions below it (as blank
    when a parent it depends on is blank), which is also what the page saves for it."""
    by_key = {question["question_key"]: question for question in questions}
    values, hidden = dict(answers), set()
    for key in _rule_order(questions):
        rules = [rule for rule in by_key[key].get("rules") or [] if rule.get("parent") in by_key]
        failing = [rule for rule in rules if rule["parent"] in hidden or not _rule_passes(rule, values.get(rule["parent"]))]
        if not failing:
            continue
        hidden.add(key)
        fallback = by_key[key].get("value_when_hidden")
        if fallback not in (None, ""):
            answered = any(not _is_blank(values.get(rule["parent"])) for rule in failing)
            values[key] = fallback if answered else None
    return hidden, values


def _missing_question_answers(questions, answers):
    """Keys of the required questions this plan has not answered, in form order. Questions hidden by their
    show/hide rules are not required; a yes/no question needs an explicit Yes or No; a grid needs every row.
    A choice question without choices (or a grid without rows) cannot be answered, so it never blocks a submit.
    The page checks the same before submitting (requiredMissing in portal/planning.html)."""
    hidden, _ = _visibility(questions, answers)
    missing = []
    for question in questions:
        key = question["question_key"]
        if not question.get("required") or key in hidden:
            continue
        value, kind = answers.get(key), str(question.get("question_type") or "TEXT").upper()
        rows = [row["key"] for row in question.get("rows") or []]
        if kind in {"SELECT", "RADIO", "CHECKBOX", "GRID"} and (not question.get("options") or (kind == "GRID" and not rows)):
            continue
        if kind == "BOOLEAN":
            answered = isinstance(value, bool)
        elif kind == "GRID":
            answered = isinstance(value, dict) and all(not _is_blank(value.get(row)) for row in rows)
        elif kind == "CHECKBOX":
            answered = isinstance(value, list) and bool(value)
        elif kind == "NUMBER":
            answered = _number(value) is not None
        else:
            answered = isinstance(value, str) and bool(value.strip())
        if not answered:
            missing.append(key)
    return missing


def _check_required_answers(conn, report_id):
    """Refuse a submit while a required question is unanswered: a 400 whose "fields" name each one by key."""
    missing = _missing_question_answers(_catalog_questions(conn), _report_answers(conn, report_id))
    if missing:
        error = FieldErrors({key: "Answer this question." for key in missing})
        count = len(missing)
        error.args = (f"{count} question{'s still need' if count != 1 else ' still needs'} an answer. Each one is marked below.",)
        raise error


def _decimal(value):
    """A Decimal from a number or number text; None for no value, true/false, text or infinity."""
    if value is None or value == "" or isinstance(value, bool):
        return None
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return number if number.is_finite() else None


def _plain(number):
    """A Decimal as people write it: 3, 2.5 (never 3.0 or 2.50)."""
    return str(int(number)) if number == number.to_integral_value() else format(number.normalize(), "f")


def _is_value_when_hidden(question, value):
    """True when the page sent the question's own "value saved while hidden" (it sends it for a follow-up that a
    show/hide rule hides). DA Management checks that value against the question, but one set in Studio may not fit
    (-1 or 1.5 for a count, a code that is not a choice): save_planning_answers then skips it instead of refusing
    the whole save because of a question the missionary cannot see."""
    fallback = question.get("value_when_hidden")
    if fallback is None or str(fallback).strip() == "":
        return False
    if str(question.get("question_type") or "").upper() == "NUMBER":
        number = _decimal(value) if not isinstance(value, (list, dict)) else None
        return number is not None and number == _decimal(str(fallback).strip().replace(",", "."))
    return _rule_text(value).strip() == str(fallback).strip()


def _still_offered(question, value):
    """For a page whose questions changed since it loaded them: (the grid or tick-box answer without the rows and
    choices no longer offered, the removed row keys and choice codes). The rest of the answer is then saved; a
    grid row whose choice was retired counts as removed. Other types come back unchanged."""
    kind = str(question.get("question_type") or "").upper()
    options = {option["value"] for option in question.get("options") or []}
    if kind == "GRID" and isinstance(value, dict):
        rows = {row["key"] for row in question.get("rows") or []}
        kept = {row: choice for row, choice in value.items()
                if row in rows and (choice is None or choice == "" or (isinstance(choice, str) and choice in options))}
        return kept, [row for row in value if row not in kept]
    if kind == "CHECKBOX" and isinstance(value, list):
        kept = [item for item in value if isinstance(item, str) and item in options]
        return kept, [item for item in value if item not in kept]
    return value, []


def _clean_number(question, value, label):
    """A NUMBER answer: a whole number (unless the question allows decimals) within the question's limits."""
    number = _decimal(value) if not isinstance(value, (list, dict)) else None
    if number is None:
        raise ValueError(f"{label} must be a number.")
    low, high = _decimal(question.get("min_value")), _decimal(question.get("max_value"))
    low = Decimal(0) if low is None else low
    if question.get("integer_only") is not False and number != number.to_integral_value():
        raise ValueError(f"{label} must be a whole number.")
    if number < low or (high is not None and number > high):
        if high is not None:
            raise ValueError(f"{label} must be a number from {_plain(low)} to {_plain(high)}.")
        raise ValueError(f"{label} must be zero or greater." if low == 0 else f"{label} must be {_plain(low)} or more.")
    return number


def _clean_grid(question, value, stored, label, options):
    """A GRID answer merged into the stored one: only the rows changed on the page come (null clears a row), so
    companions answering different rows keep each other's. None when no row is left."""
    rows = {row["key"] for row in question.get("rows") or []}
    if isinstance(value, list):  # the shape pages from before migration 024 sent
        raise ValueError(f"{label}: this page is out of date. Reload the page to answer it.")
    if not isinstance(value, dict):
        raise ValueError(f"{label}: choose an answer in each row.")
    merged = dict(stored) if isinstance(stored, dict) else {}
    for row, choice in value.items():
        if row not in rows:
            raise ValueError(f"{label}: a row on this page is no longer asked. Reload the page.")
        if choice is None or choice == "":
            merged.pop(row, None)
        elif not isinstance(choice, str) or choice not in options:
            raise ValueError(f"{label}: choose one of the listed answers in each row.")
        else:
            merged[row] = choice
    return merged or None


def _clean_answer(question, value, stored=None):
    """The answer columns (text, number, boolean, json) for a value the page sent, or None to delete the answer.

    Each type has its own column: TEXT, LONG_TEXT, SELECT, RADIO and DATE as text, NUMBER as a number, BOOLEAN as
    a boolean, CHECKBOX as a list of choice values, GRID as {row key: choice value} (see _clean_grid). Raises
    ValueError with the question's label."""
    label = question.get("question_label") or question["question_key"]
    kind = str(question.get("question_type") or "TEXT").upper()
    options = [option["value"] for option in question.get("options") or []]
    if kind == "NUMBER":
        return None, _clean_number(question, value, label), None, None
    if kind == "BOOLEAN":
        if isinstance(value, str) and value.strip().lower() in {"true", "false"}:
            value = value.strip().lower() == "true"
        if not isinstance(value, bool):
            raise ValueError(f"{label}: choose Yes or No.")
        return None, None, value, None
    if kind == "CHECKBOX":
        chosen = value if isinstance(value, list) else None
        if chosen is None or any(not isinstance(item, str) or item not in options for item in chosen):
            raise ValueError(f"{label}: choose from the listed answers.")
        chosen = [option for option in options if option in chosen]
        return (None, None, None, Json(chosen)) if chosen else None
    if kind == "GRID":
        merged = _clean_grid(question, value, stored, label, options)
        return (None, None, None, Json(merged)) if merged else None
    if isinstance(value, (bool, list, dict)):
        raise ValueError(f"{label}: enter text.")
    text = str(value).strip()
    if kind in {"SELECT", "RADIO"}:
        if text not in options:
            raise ValueError(f"{label}: choose one of the listed answers.")
        return text, None, None, None
    if kind == "DATE":
        try:
            day = date.fromisoformat(text) if len(text) == 10 else None
        except ValueError:
            day = None
        if day is None or day.year < 1900:
            raise ValueError(f"{label}: enter a date.")
        return day.isoformat(), None, None, None
    text = text[:TEXT_LIMITS.get(kind, 10000)]
    return (text, None, None, None) if text else None


def _available_new_members(conn, area_id, unit_id, report_id):
    """The area's New Members of this ward or branch who are not on this plan yet ("Add from database")."""
    return fetch_rows(conn, """
        SELECT nm.id,nm.display_name FROM public.current_new_members nm
        WHERE nm.area_id=%s AND nm.unit_id=%s
          AND NOT EXISTS (SELECT 1 FROM public.weekly_new_members w
                          WHERE w.weekly_area_report_id=%s AND w.new_member_id=nm.id)
        ORDER BY nm.display_name
    """, (area_id, unit_id, report_id))


def _available_baptismal_friends(conn, area_id, report_id):
    """The area's friends with a baptismal date who are not on this plan yet ("Add from database")."""
    return fetch_rows(conn, """
        SELECT b.id,b.display_name FROM public.current_baptismal_date_people b
        WHERE b.area_id=%s AND NOT EXISTS (SELECT 1 FROM public.weekly_baptismal_date_friends w
              WHERE w.weekly_area_report_id=%s AND w.baptismal_date_person_id=b.id)
        ORDER BY b.display_name
    """, (area_id, report_id))


def _available_people(conn, area_id, unit_id, report_id):
    """The "Add from database" lists, built as the form builds them. Sent after every person action too, so the
    counts on the buttons are right at once (a transfer can make someone available)."""
    return {"new_members": _available_new_members(conn, area_id, unit_id, report_id),
            "baptismal_friends": _available_baptismal_friends(conn, area_id, report_id)}


def planning_form(conn, context, unit_id=None):
    """Everything the Weekly Planning page needs for this week's plan of one ward or branch (the first one when
    none is chosen): the questions, the answers, the people, the lists to add from. Starts the shared draft."""
    units = fetch_rows(conn, "SELECT unit_id, unit, unit_type, primary_unit FROM public.current_user_area_units ORDER BY primary_unit DESC, unit")
    if not units:
        raise ValueError("No ward or branch is assigned to your area yet. Ask the office to check your area.")
    allowed = {row["unit_id"] for row in units}
    chosen = unit_id or units[0]["unit_id"]
    if chosen not in allowed:
        raise PermissionError("This ward or branch is not assigned to your area.")
    started = fetch_one(conn, "SELECT public.start_current_weekly_report(%s) AS report_id", (chosen,))
    report = fetch_one(conn, """
        SELECT war.id AS report_id, war.unit_id, war.status, war.submitted_at,
               war.updated_at, rw.sunday, rw.planning_due_at
        FROM public.weekly_area_reports war JOIN public.reporting_weeks rw ON rw.id=war.reporting_week_id
        WHERE war.id=%s
    """, (started["report_id"],))
    version = _catalog_version(conn)  # before the questions (see _catalog_version)
    questions = _form_questions(conn, chosen)
    available_new_members = _available_new_members(conn, context.get("area_id"), chosen, report["report_id"])
    available_baptismal = _available_baptismal_friends(conn, context.get("area_id"), report["report_id"])
    return json_ready({"units": units, "report": report, "questions": questions,
                       "answers": _report_answers(conn, report["report_id"]),
                       "people": _report_people(conn, report["report_id"]),
                       "available_people": {"new_members": available_new_members,
                                            "baptismal_friends": available_baptismal},
                       "catalog_version": version,
                       "person_options": {**{key: list(choices) for key, choices in PERSON_CHOICES.items()},
                                          "new_member_required": list(NEW_MEMBER_REQUIRED)},
                       "can_edit": report["status"] == "DRAFT"})


def _answer_changes(supplied, definitions, stored, page_version, stale):
    """(changes {key: answer columns or None to delete}, dropped keys, dropped parts) for the answers a page sent.
    See save_planning_answers for what is dropped and why."""
    changes, dropped, dropped_parts = {}, [], {}
    for key, value in supplied.items():
        if key not in definitions:
            if page_version is None:
                raise ValueError(FORM_CHANGED_MESSAGE)
            dropped.append(key)
            continue
        if stale:  # only the grid rows and tick-box choices no longer offered are left out, not the whole answer
            value, removed = _still_offered(definitions[key], value)
            if removed:
                dropped_parts[key] = removed
                if value == {}:
                    continue  # nothing left of this grid save: the saved rows stay as they are
        try:
            changes[key] = None if value is None or value == "" else _clean_answer(definitions[key], value, stored.get(key))
        except ValueError:
            if _is_value_when_hidden(definitions[key], value):
                continue  # a "value saved while hidden" that does not fit its own question is never saved
            if not stale:
                raise
            dropped.append(key)
    return changes, dropped, dropped_parts


def _write_answers(conn, report_id, changes):
    """Store (or, for None, delete) each changed answer of the plan."""
    for key, columns in changes.items():
        with conn.cursor() as cursor:
            if columns is None:
                cursor.execute("DELETE FROM public.weekly_planning_answers WHERE weekly_area_report_id=%s AND question_key=%s", (report_id, key))
                continue
            cursor.execute("""
                INSERT INTO public.weekly_planning_answers
                    (weekly_area_report_id,question_key,answer_text,answer_number,answer_boolean,answer_json)
                VALUES (%s,%s,%s,%s,%s,%s)
                ON CONFLICT (weekly_area_report_id,question_key) DO UPDATE SET
                    answer_text=excluded.answer_text, answer_number=excluded.answer_number,
                    answer_boolean=excluded.answer_boolean, answer_json=excluded.answer_json, updated_at=now()
            """, (report_id, key, *columns))


def save_planning_answers(conn, context, report_id, supplied):
    """Save only the answers the page sends (the ones changed there); "" or null clears one.

    supplied also carries "changes_only": true (see _changes_only) and, from current pages, "catalog_version":
    the version of the questions the page shows. When the questions changed since (DA Management), the save
    still writes every answer whose question is on the form, leaves out the ones that are no longer asked (or no
    longer fit their question), lists them in "dropped", and returns the new questions with "catalog_changed":
    true, so the page can show the new form and keep what was typed. A grid or tick-box answer loses only the rows
    and choices no longer offered ("dropped_parts": {key: [row keys or choice codes]}); the rest of it is saved.

    Answers a companion saved meanwhile are left alone and come back in "answers", which
    holds every answer of the report after this save so the page can show them.
    """
    supplied = _changes_only(supplied)
    page_version = supplied.pop("catalog_version", None)
    if page_version is not None and (isinstance(page_version, bool) or not isinstance(page_version, int)):
        page_version = -1  # not a version this service gave out: treat the page's questions as out of date
    report = _report_for_edit(conn, context, report_id, "You can edit only your companionship's plan.",
                              "This plan is closed. Ask a leader to unlock it before editing.")
    version = _catalog_version(conn) if page_version is not None else None  # before the questions
    questions = _catalog_questions(conn)
    definitions = {row["question_key"]: row for row in questions}
    stale = page_version is not None and page_version != version
    # A grid save is merged into the stored grid answer, so it needs the stored answers.
    stored = _report_answers(conn, report_id) if any(
        str(definitions.get(key, {}).get("question_type")).upper() == "GRID" for key in supplied) else {}
    changes, dropped, dropped_parts = _answer_changes(supplied, definitions, stored, page_version, stale)
    _write_answers(conn, report_id, changes)
    if changes:
        _mark_worked_on(conn, report_id)
    result = {"ok": True, "report_id": report_id, "answers": _report_answers(conn, report_id)}
    if page_version is not None:
        result["catalog_version"] = version
    if stale:
        result.update(catalog_changed=True, questions=_form_questions(conn, report.get("unit_id")))
    if dropped_parts:
        result["dropped_parts"] = dropped_parts  # {key: [row keys or choice codes]} of answers saved without them
    if dropped or dropped_parts:
        result.update(dropped=dropped, note="Some answers were not saved because their questions changed or are no longer asked.")
    return json_ready(result)


# ================================================================================================ 4. people on the plan

# The friend's finding source is not a weekly answer: it is shown from the friend's record and changed
# with Edit details (update_baptismal_date_person), so it is not saved from the card.
PEOPLE_FIELDS = {
    "new_members": {"lessons_actual", "lessons_goal", "pmg_lessons_percentage", "how_are_they_doing",
                    "discussed_in_gemiko", "gemiko_support_plan", "next_ordinance", "at_church_this_sunday",
                    "has_calling", "has_aaronic_priesthood", "has_melchizedek_priesthood",
                    "ministers_to_someone", "ministered_to_by_someone", "has_active_temple_recommend",
                    "visited_temple_for_baptisms", "reading", "praying", "member_involvement"},
    "baptismal_friends": {"baptismal_date_set_on", "current_baptismal_date", "reading",
                          "praying", "at_church_this_sunday", "keeping_commandments", "member_involvement"},
    "high_potential": {"name", "at_church_this_sunday", "notes"},
}
PEOPLE_TABLES = {"new_members": "weekly_new_members", "baptismal_friends": "weekly_baptismal_date_friends",
                 "high_potential": "weekly_high_potential_friends"}
# Typed number fields on the person cards: label and highest sensible value.
PEOPLE_NUMBERS = {"lessons_actual": ("Lessons taught", 1000), "lessons_goal": ("Goal next week", 1000),
                  "pmg_lessons_percentage": ("Preach My Gospel lessons taught (%)", 100)}
# Next ordinance: the code is stored (Call-ins and Dashboards read it), the page shows the name.
NEXT_ORDINANCES = (("SA", "Sacrament"), ("AP", "Aaronic Priesthood"), ("TB", "Temple baptisms"),
                   ("MP", "Melchizedek Priesthood"), ("PB", "Patriarchal blessing"), ("TE", "Temple endowment"))
# Yes / No / Not applicable (text columns with that CHECK) and Yes / No (boolean columns).
PEOPLE_YES_NO_NA = {"has_calling", "has_aaronic_priesthood", "has_melchizedek_priesthood", "ministers_to_someone",
                    "has_active_temple_recommend", "visited_temple_for_baptisms"}
PEOPLE_YES_NO = {"discussed_in_gemiko", "at_church_this_sunday", "ministered_to_by_someone", "reading", "praying",
                 "member_involvement", "keeping_commandments"}
PEOPLE_DATES = {"baptismal_date_set_on", "current_baptismal_date"}
PEOPLE_TEXT_LIMITS = {"how_are_they_doing": 5000, "gemiko_support_plan": 5000, "notes": 5000, "name": 200}
# What the page shows for each person question (for messages and the submit check).
PEOPLE_LABELS = {
    "lessons_actual": "Lessons taught", "lessons_goal": "Goal next week",
    "pmg_lessons_percentage": "Preach My Gospel lessons taught (%)", "how_are_they_doing": "How are they doing?",
    "at_church_this_sunday": "At church on Sunday?", "reading": "Reading?", "praying": "Praying?",
    "member_involvement": "Member involvement?", "discussed_in_gemiko": "Discussed in GEMIKO?",
    "gemiko_support_plan": "How will GEMIKO support them?", "next_ordinance": "Next ordinance",
    "has_calling": "Do they have a calling?", "has_aaronic_priesthood": "Do they hold the Aaronic Priesthood?",
    "has_melchizedek_priesthood": "Do they hold the Melchizedek Priesthood?",
    "ministers_to_someone": "Do they have a ministering assignment?",
    "ministered_to_by_someone": "Do they have ministering brothers or sisters?",
    "has_active_temple_recommend": "Do they have an active temple recommend?",
    "visited_temple_for_baptisms": "Have they been to the temple for baptisms?",
    "baptismal_date_set_on": "Date first set", "current_baptismal_date": "Current baptismal date",
    "keeping_commandments": "Keeping commandments?", "name": "Name", "notes": "Notes",
}
# Required at submit for every person still assigned to the area (see _missing_person_fields). "How will GEMIKO
# support them?" is required only when "Discussed in GEMIKO?" is Yes; high-potential notes are optional.
PEOPLE_REQUIRED = {
    "new_members": ("lessons_actual", "lessons_goal", "pmg_lessons_percentage", "how_are_they_doing",
                    "at_church_this_sunday", "reading", "praying", "member_involvement", "discussed_in_gemiko",
                    "next_ordinance", "has_calling", "has_aaronic_priesthood", "has_melchizedek_priesthood",
                    "ministers_to_someone", "ministered_to_by_someone", "has_active_temple_recommend",
                    "visited_temple_for_baptisms"),
    "baptismal_friends": ("baptismal_date_set_on", "current_baptismal_date", "reading", "praying",
                          "at_church_this_sunday", "keeping_commandments", "member_involvement"),
    "high_potential": ("name", "at_church_this_sunday"),
}
PEOPLE_GROUP_LABELS = {"new_members": "new member", "baptismal_friends": "friend with a baptismal date",
                       "high_potential": "high-potential friend"}
# The name a new high-potential friend gets (the column needs one); it counts as "no name yet".
HIGH_POTENTIAL_PLACEHOLDER = "New High Potential"


def _person_value(key, value):
    """One person-card field cleaned for its column; None clears it. ValueError with the field's label."""
    if value is None or value == "":
        return None
    label = PEOPLE_LABELS.get(key, key)
    if key in PEOPLE_NUMBERS:
        label, highest = PEOPLE_NUMBERS[key]
        try:
            number = None if isinstance(value, bool) else Decimal(str(value))
        except (InvalidOperation, ValueError):
            number = None
        if number is None or not number.is_finite() or not 0 <= number <= highest:
            raise ValueError(f"{label} must be a number from 0 to {highest}.")
        return number
    if key == "next_ordinance":
        if value not in [code for code, _ in NEXT_ORDINANCES]:
            raise ValueError("Choose the next ordinance from the list.")
        return value
    if key in PEOPLE_YES_NO_NA:
        if value not in ("yes", "no", "not_applicable"):
            raise ValueError(f"Answer \"{label}\" with Yes, No or Not applicable.")
        return value
    if key in PEOPLE_YES_NO:
        if not isinstance(value, bool):
            raise ValueError(f"Answer \"{label}\" with Yes or No.")
        return value
    if key in PEOPLE_DATES:
        try:
            parsed = date.fromisoformat(str(value))
        except ValueError:
            parsed = None
        if parsed is None or parsed.year < 1900:
            raise ValueError(f"{label}: enter a valid date.")
        return parsed
    if key in PEOPLE_TEXT_LIMITS:
        if not isinstance(value, str):
            raise ValueError(f"{label}: enter plain text.")
        if len(value) > PEOPLE_TEXT_LIMITS[key]:
            raise ValueError(f"{label}: use {PEOPLE_TEXT_LIMITS[key]} characters or fewer.")
    return value


def _person_name(conn, report_id, group, row_id):
    """The name on a person card (for messages); "A person on this plan" if the row is gone."""
    row = next((row for row in _report_people(conn, report_id)[group] if row["id"] == row_id), {})
    return row.get("display_name") or row.get("name") or "A person on this plan"


def _update_person_row(conn, report_id, group, row_id, record):
    """Save one person card's changed fields. Returns True when a row was changed, False when it was already gone,
    None when there was nothing to save."""
    table, allowed = PEOPLE_TABLES[group], PEOPLE_FIELDS[group]
    try:
        values = {key: _person_value(key, value) for key, value in record.items() if key in allowed}
    except ValueError as error:
        raise ValueError(f"{_person_name(conn, report_id, group, row_id)}: {error}") from None
    if group == "high_potential" and "name" in values:
        name = str(values.pop("name") or "").strip()
        if name:  # A blank name is not saved (the column needs one); the friend keeps the old name.
            values["name"] = name
    if not values:
        return None
    assignments = ",".join(f"{key}=%s" for key in values)
    try:
        with conn.cursor() as cursor:
            cursor.execute(f"UPDATE public.{table} SET {assignments},updated_at=now() WHERE id=%s AND weekly_area_report_id=%s RETURNING id",
                           list(values.values()) + [row_id, report_id])
            found = cursor.fetchone()
    except (psycopg2.DataError, psycopg2.IntegrityError):
        raise ValueError("A value on a person card is not valid. Check its numbers, dates and choices, then try again.") from None
    return bool(found)


def save_planning_people(conn, context, report_id, groups):
    """Save only the person fields the page sends, and remove only the friends it names.

    groups also carries "changes_only": true (see _changes_only). Each row is
    {"id": <weekly row id>, <field>: <value>, ...}; {"id": ..., "removed": true}
    removes a high-potential friend. Nothing else is ever deleted: a blank friend name keeps
    the saved name, and rows a companion added meanwhile are left alone. A row that no longer
    exists (a companion removed it) is skipped and listed in "missing" instead of failing the
    save. "people" holds every person of the report after this save so the page can show them.
    A value that is not valid is refused with the person's name, so the page can say where it is.
    """
    groups = _changes_only(groups)
    _report_for_edit(conn, context, report_id, "You can edit only your companionship's plan.",
                     "This plan is submitted. Ask a leader to unlock it before editing.")
    missing, removed, wrote = [], [], False
    for group, records in groups.items():
        if group not in PEOPLE_TABLES or not isinstance(records, list):
            raise ValueError("The people section is invalid.")
        for record in records:
            row_id = record.get("id") if isinstance(record, dict) else None
            if isinstance(row_id, bool) or not isinstance(row_id, int) or row_id <= 0:
                raise ValueError("The people section is invalid. Reload and try again.")
            if record.get("removed") is True:
                if group != "high_potential":
                    raise ValueError("Only high-potential friends can be removed here.")
                with conn.cursor() as cursor:
                    cursor.execute(f"DELETE FROM public.{PEOPLE_TABLES[group]} WHERE id=%s AND weekly_area_report_id=%s", (row_id, report_id))
                removed.append(row_id)
                wrote = True
                continue
            saved = _update_person_row(conn, report_id, group, row_id, record)
            if saved:
                wrote = True
            elif saved is False:
                missing.append({"group": group, "id": row_id})
    if wrote:
        _mark_worked_on(conn, report_id)
    return json_ready({"ok": True, "report_id": report_id, "missing": missing, "removed": removed,
                       "people": _report_people(conn, report_id)})


# ================================================================================================ 5. new people

# The choices of the New Member and "Person on date" forms. Call-ins, Dashboards and DA Management read the stored
# values, so the texts stay exactly as they are.
FINDING_SOURCES = (
    "Missionary/Contacting in Public", "Missionary/Home to Home Contacting",
    "Missionary/Through Person Being Taught", "Missionary/Service",
    "Missionary/Sought out Church or Missionaries", "Missionary/English Class", "Missionary/Family History",
    "Member/Member", "Member/New Member", "Member/Less Active", "Member/Ward Council",
    "Member/Friend attended an activity hosted by the ward or stake", "Media/Referral", "Visitor's Center",
)
AGE_RANGES = ("0-8", "9-11", "12-17", "18-30", "31-45", "46-59", "60+")
GENDERS = ("Male", "Female")
LIVING_SITUATIONS = (
    "Student", "Bachelor/Bachelorette", "Living with Spouse and or Children", "Living with Parents",
    "Living in Germany alone, with Family in Native Country",
)
MARITAL_STATUSES = (
    "Single", "Serious Dating and or Courtship/Engaged", "Married in First Marriage",
    "Deceased Spouse and Single", "Deceased Spouse and in Serious Dating and or Courting/Engaged",
    "Deceased Spouse and Remarried", "Divorced and Single",
    "Divorced and in Serious Dating and or Courting/Engaged", "Divorced and Remarried",
)
LANGUAGE_COMPETENCIES = ("Minimal", "Conversational/basic", "Conversational/complex",
                         "Fluent/almost fluent", "Native Born/raised")
PERSON_CHOICES = {"finding_source": FINDING_SOURCES, "age_range": AGE_RANGES, "gender": GENDERS,
                  "living_situation": LIVING_SITUATIONS, "marital_status": MARITAL_STATUSES,
                  "mission_language_competency": LANGUAGE_COMPETENCIES}
# Every field of the New Member form is required except the ones marked "(optional)". The friend with a baptismal
# date needs first name, last name and finding source.
NEW_MEMBER_FIELDS = ("first_name", "last_name", "baptismal_date_extended", "baptism_date", "confirmation_date",
                     "date_of_birth", "age_range", "finding_source", "gender", "living_situation", "marital_status",
                     "mission_language_competency", "native_language", "second_language", "country_of_origin",
                     "child_dependents", "conversion_success_notes")
NEW_MEMBER_OPTIONAL = ("second_language",)
NEW_MEMBER_REQUIRED = tuple(key for key in NEW_MEMBER_FIELDS if key not in NEW_MEMBER_OPTIONAL)
BAPTISMAL_REQUIRED = ("first_name", "last_name", "finding_source")
# "Baptized": the name and finding source come from the friend's record, not from the form.
FROM_FRIEND_RECORD = ("first_name", "last_name", "finding_source")
REQUIRED_MESSAGES = {
    "first_name": "Enter the first name.", "last_name": "Enter the last name.",
    "baptismal_date_extended": "Enter the date the baptismal invitation was extended.",
    "baptism_date": "Enter the baptism date.",
    "confirmation_date": "Enter the confirmation date.",
    "date_of_birth": "Enter the birth date.",
    "native_language": "Enter their native language.", "country_of_origin": "Enter their country of origin.",
    "child_dependents": "Enter the number of children (0 if none).",
    "conversion_success_notes": "Tell what went well in their conversion.",
}
NEW_MEMBER_DATES = ("baptismal_date_extended", "baptism_date", "confirmation_date", "date_of_birth")
DATE_LABELS = {"baptismal_date_extended": "The baptismal invitation date", "baptism_date": "The baptism date",
               "confirmation_date": "The confirmation date", "date_of_birth": "Birth date"}
NEW_MEMBER_TEXT = {"native_language": 100, "second_language": 100, "country_of_origin": 100,
                   "conversion_success_notes": 5000}
# Order of create_new_member() arguments after (first, last, stake, unit).
NEW_MEMBER_RPC_FIELDS = ("baptismal_date_extended", "baptism_date", "confirmation_date", "finding_source",
                         "date_of_birth", "age_range", "gender", "marital_status", "child_dependents",
                         "living_situation", "native_language", "second_language",
                         "mission_language_competency", "country_of_origin", "conversion_success_notes")


class FieldErrors(ValueError):
    """A 400 error that also names the form fields to mark (see app.error_response)."""

    def __init__(self, fields):
        self.fields = fields
        count = len(fields)
        super().__init__(f"{count} field{'s need' if count != 1 else ' needs'} attention.")


def _mission_today():
    """Today in the mission (its time zone), so a date entered just after midnight is not "in the future"."""
    return datetime.now(mission_time.ZONE).date()


class _PersonForm:
    """One person form being checked: the cleaned values, and a message for each field that needs attention."""

    def __init__(self, payload, required):
        self.payload, self.required = payload, required
        self.values, self.errors = {}, {}

    def missing(self, key, fallback):
        """Mark a required field that was left empty (a field with another problem keeps that message)."""
        if key in self.required and key not in self.errors:
            self.errors[key] = REQUIRED_MESSAGES.get(key, fallback)

    def text(self, key, limit, keep_lines=False):
        """A text field: spaces tidied (line breaks kept for long notes), at most limit characters."""
        raw = self.payload.get(key)
        if raw is not None and not isinstance(raw, (str, int, float)):
            self.errors[key] = "Enter plain text."
            return None
        value = str(raw or "").strip() if keep_lines else " ".join(str(raw or "").split())
        if len(value) > limit:
            self.errors[key] = f"Use {limit} characters or fewer."
        if not value:
            self.missing(key, "Please fill this in.")
        return value or None

    def choices(self, keys):
        """Fields answered from a list (PERSON_CHOICES)."""
        for key in keys:
            value = self.payload.get(key)
            value = value.strip() if isinstance(value, str) else value
            if value in (None, ""):
                self.values[key] = None
                self.missing(key, "Please choose one.")
            elif value not in PERSON_CHOICES[key]:
                self.errors[key] = "Choose one of the listed options."
            else:
                self.values[key] = value

    def dates(self, today):
        """The four New Member dates: real dates, not in the future, in a possible order."""
        values, errors = self.values, self.errors
        for key in NEW_MEMBER_DATES:
            raw = self.payload.get(key)
            values[key] = None
            if raw in (None, ""):
                self.missing(key, "Enter a date.")
                continue
            try:
                values[key] = date.fromisoformat(str(raw))
            except ValueError:
                errors[key] = "Enter a valid date."
                continue
            if values[key].year < 1900:
                errors[key] = "Enter a valid date."
            elif values[key] > today:
                errors[key] = f"{DATE_LABELS[key]} cannot be in the future."
        # Order checks only between dates that are fine on their own.
        if (values.get("baptism_date") and values.get("confirmation_date")
                and not {"baptism_date", "confirmation_date"} & set(errors)
                and values["confirmation_date"] < values["baptism_date"]):
            errors["confirmation_date"] = "Confirmation cannot be before the baptism date."
        if (values.get("baptismal_date_extended") and values.get("baptism_date")
                and not {"baptismal_date_extended", "baptism_date"} & set(errors)
                and values["baptism_date"] < values["baptismal_date_extended"]):
            errors["baptism_date"] = "Baptism cannot be before the date it was extended."

    def children(self):
        """The number of children: a whole number from 0 to 30."""
        raw = self.payload.get("child_dependents")
        self.values["child_dependents"] = None
        if raw in (None, ""):
            self.missing("child_dependents", "Enter a number.")
            return
        try:
            number = Decimal(str(raw))
            if not number.is_finite() or number != number.to_integral_value() or not 0 <= number <= 30:
                raise ValueError
            self.values["child_dependents"] = int(number)
        except (ValueError, ArithmeticError):
            self.errors["child_dependents"] = "Enter a whole number from 0 to 30."


def validate_new_person(kind, payload, today=None):
    """Clean and check a person form. Returns values ready for the RPC or raises FieldErrors.

    kind: "new_member" (Create New Member / Edit details), "baptismal" (Add Person On Date / Edit details) or
    "convert" ("Baptized": the New Member form without the name and finding source, which come from the
    friend's record). Everything is required except NEW_MEMBER_OPTIONAL; see NEW_MEMBER_REQUIRED.
    """
    if not isinstance(payload, dict):
        raise ValueError("The person details are invalid.")
    if kind not in {"new_member", "baptismal", "convert"}:
        raise ValueError("Unknown person type.")
    today = today or _mission_today()
    required = set(BAPTISMAL_REQUIRED) if kind == "baptismal" else set(NEW_MEMBER_REQUIRED)
    if kind == "convert":
        required -= set(FROM_FRIEND_RECORD)
    form = _PersonForm(payload, required)
    if kind != "convert":
        form.values["first_name"] = form.text("first_name", 100)
        form.values["last_name"] = form.text("last_name", 100)
    choice_keys = ("finding_source",) if kind == "baptismal" else tuple(PERSON_CHOICES)
    if kind == "convert":
        choice_keys = tuple(key for key in choice_keys if key not in FROM_FRIEND_RECORD)
    form.choices(choice_keys)
    if kind != "baptismal":
        form.dates(today)
        for key, limit in NEW_MEMBER_TEXT.items():
            form.values[key] = form.text(key, limit, keep_lines=(key == "conversion_success_notes"))
        form.children()
    if form.errors:
        raise FieldErrors(form.errors)
    return form.values


def _new_weekly_row_id(row):
    """The id RETURNING gave back, for dict and tuple cursors alike; None when no row was added."""
    if not row:
        return None
    return next(iter(row.values())) if isinstance(row, dict) else row[0]


# The database function that fills a new weekly row of each kind of person from their latest earlier row (042).
PREFILL_FUNCTIONS = {"weekly_new_members": "prefill_weekly_new_members",
                     "weekly_baptismal_date_friends": "prefill_weekly_friends"}


def _insert_weekly_person(conn, report_id, table, column, person_id):
    """Put a New Member or friend on the plan (at the end of the list); nothing happens when they are already on
    it. Returns the new weekly row's id, or None when they were already on the plan."""
    with conn.cursor() as cursor:
        cursor.execute(f"""INSERT INTO public.{table}(weekly_area_report_id,{column},display_order)
            VALUES(%s,%s,(SELECT COALESCE(max(display_order),0)+1 FROM public.{table} WHERE weekly_area_report_id=%s))
            ON CONFLICT (weekly_area_report_id,{column}) WHERE {column} IS NOT NULL DO NOTHING RETURNING id""",
            (report_id, person_id, report_id))
        row_id = _new_weekly_row_id(cursor.fetchone())
        if row_id and table in PREFILL_FUNCTIONS:  # round 12: start from the person's latest earlier answers (migration 042)
            cursor.execute(f"SELECT public.{PREFILL_FUNCTIONS[table]}(ARRAY[%s]::bigint[])", (row_id,))
        return row_id


def _add_high_potential(conn, report_id):
    """"+ Add friend": a new high-potential friend with the placeholder name."""
    with conn.cursor() as cursor:
        cursor.execute("""INSERT INTO public.weekly_high_potential_friends
            (weekly_area_report_id,display_order,name) VALUES
            (%s,(SELECT COALESCE(max(display_order),0)+1 FROM public.weekly_high_potential_friends WHERE weekly_area_report_id=%s),'New High Potential')
            RETURNING id""", (report_id, report_id))
        created_id = _new_weekly_row_id(cursor.fetchone())
    _mark_worked_on(conn, report_id)
    return {"ok": True, "id": created_id}


def _add_existing_person(conn, report_id, area_id, kind, payload):
    """"Add from database": a New Member or friend of the area who is not on the plan yet."""
    try:
        person_id = int(payload.get("person_id") or 0)
    except (TypeError, ValueError):
        person_id = 0
    if person_id <= 0:
        raise ValueError("Choose a person from your list.")
    if kind == "existing_new_member":
        table, column, available = "weekly_new_members", "new_member_id", "current_new_members"
    else:
        table, column, available = "weekly_baptismal_date_friends", "baptismal_date_person_id", "current_baptismal_date_people"
    values = fetch_one(conn, f"SELECT id FROM public.{available} WHERE id=%s AND area_id=%s", (person_id, area_id))
    if not values:
        raise PermissionError("That person is not currently assigned to this area.")
    _insert_weekly_person(conn, report_id, table, column, person_id)
    _mark_worked_on(conn, report_id)
    return {"ok": True, "id": person_id}


def _create_person_record(conn, kind, values, unit_id):
    """The new person's id, from the database function that creates a New Member or a friend with a date."""
    try:
        if kind == "baptismal":
            return fetch_one(conn, "SELECT (public.create_baptismal_date_person(%s,%s,%s,%s)).id AS id",
                             (values["first_name"], values["last_name"], values["finding_source"], unit_id))["id"]
        args = (values["first_name"], values["last_name"], None, unit_id) + tuple(
            values[key] for key in NEW_MEMBER_RPC_FIELDS)
        placeholders = ",".join(["%s"] * len(args))
        return fetch_one(conn, f"SELECT (public.create_new_member({placeholders})).id AS id", args)["id"]
    except psycopg2.Error as error:
        # These functions raise plain exceptions for access and area problems; show their message.
        detail = getattr(getattr(error, "diag", None), "message_primary", None)
        if getattr(error, "pgcode", None) == "P0001" and detail:
            if "unit" in detail.lower() or "area" in detail.lower() or "authenticated" in detail.lower():
                raise PermissionError(detail) from None
            raise ValueError(detail) from None
        raise


def create_planning_person(conn, context, report_id, kind, payload):
    """Add someone to the plan: kind "high_potential" (+ Add friend), "existing_new_member" or "existing_baptismal"
    (Add from database), "new_member" or "baptismal" (the forms: a new record, then onto the plan)."""
    report = _report_for_edit(conn, context, report_id, "You can add people only to your companionship's plan.",
                              "This plan is submitted. Ask a leader to unlock it before adding someone.")
    if not report.get("unit_id"):
        raise ValueError("Choose your ward or branch before adding someone.")
    if kind == "high_potential":
        return _add_high_potential(conn, report_id)
    if kind in {"existing_new_member", "existing_baptismal"}:
        return _add_existing_person(conn, report_id, report["area_id"], kind, payload)
    if kind not in {"new_member", "baptismal"}:
        raise ValueError("Unknown person type.")
    values = validate_new_person(kind, payload)
    person_id = _create_person_record(conn, kind, values, report["unit_id"])
    table, column = (("weekly_baptismal_date_friends", "baptismal_date_person_id") if kind == "baptismal"
                     else ("weekly_new_members", "new_member_id"))
    weekly_id = _insert_weekly_person(conn, report_id, table, column, person_id)
    _mark_worked_on(conn, report_id)
    return {"ok": True, "id": person_id, "weekly_id": weekly_id}


# ================================================================================================ 6. managing a person

# POST /api/planning/reports/<id>/people/<group>/<person id>/<action>.
PERSON_ACTIONS = {"new_members": ("edit", "transfer", "end"),   # round 12: a New Member cannot be deleted
                  "baptismal_friends": ("baptized", "transfer", "drop", "edit", "delete")}
END_REASONS = (("moved_out_of_mission", "Moved out of the mission"), ("record_removed", "Membership record removed"),
               ("deceased", "Passed away"), ("duplicate", "Listed twice"), ("other", "Other reason"))
DROP_REASONS = (("no_longer_on_date", "Not preparing for this date now"), ("moved_out_of_mission", "Moved out of the mission"),
                ("duplicate", "Listed twice"), ("other", "Other reason"))
# convert_baptismal_date_person_to_new_member() arguments after the friend (named, from validate_new_person).
CONVERT_RPC_FIELDS = ("baptismal_date_extended", "baptism_date", "confirmation_date", "date_of_birth", "age_range",
                      "gender", "marital_status", "child_dependents", "living_situation", "native_language",
                      "second_language", "mission_language_competency", "country_of_origin",
                      "conversion_success_notes")


class PersonActionRefused(ValueError):
    """The record is kept (for example, the person was already on a submitted plan). The page then offers
    End follow-up or No longer on date instead; app.py answers 409."""


def _rpc(conn, name, args):
    """SELECT public.<name>(key => value, ...): named arguments, so the order of the SQL signature never matters."""
    placeholders = ", ".join(f"{key} => %s" for key in args)
    row = fetch_one(conn, f"SELECT public.{name}({placeholders}) AS result", tuple(args.values()))
    return row["result"] if row else None


def _person_rpc_error(error, name):
    """Turn a people function's refusal into a message the missionary can act on."""
    code = getattr(error, "pgcode", None)
    detail = getattr(getattr(error, "diag", None), "message_primary", None) or ""
    detail = detail.replace("This New Member", name).replace("This friend", name)
    # The database (migration 023) still names the old "Drop" button; the page now says "No longer on date".
    detail = detail.replace("Use Drop instead.", 'Use "No longer on date" instead.')
    if code == "GF409":
        return PersonActionRefused(detail)
    if code == "42501" or "permission" in detail.lower():
        return PermissionError(detail or "You cannot change this person.")
    if code == "P0001" and detail:
        return ValueError(detail)
    return None


def _positive_id(value, message):
    """A positive whole number from the request (not true/false, not 1.5); ValueError(message) otherwise."""
    if isinstance(value, bool):
        raise ValueError(message)
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise ValueError(message) from None
    if number <= 0 or str(number) != str(value).strip():
        raise ValueError(message)
    return number


def _person_on_plan(conn, report_id, group, person_id):
    """The person's name, current area and ward of a New Member or friend on this plan, or None."""
    if group == "new_members":
        return fetch_one(conn, """
            SELECT nm.display_name, a.area_id, nm.unit_id
            FROM public.weekly_new_members w
            LEFT JOIN public.new_members nm ON nm.id=w.new_member_id
            LEFT JOIN public.new_member_area_assignments a ON a.new_member_id=w.new_member_id AND a.end_date IS NULL
            WHERE w.weekly_area_report_id=%s AND w.new_member_id=%s
        """, (report_id, person_id))
    return fetch_one(conn, """
        SELECT bdp.display_name, a.area_id, a.unit_id
        FROM public.weekly_baptismal_date_friends w
        LEFT JOIN public.baptismal_date_people bdp ON bdp.id=w.baptismal_date_person_id
        LEFT JOIN public.baptismal_date_person_area_assignments a
          ON a.baptismal_date_person_id=w.baptismal_date_person_id AND a.end_date IS NULL
        WHERE w.weekly_area_report_id=%s AND w.baptismal_date_person_id=%s
    """, (report_id, person_id))


def _edit_person(conn, group, key, person_id, payload):
    """Edit details: the person's record, checked like the form that made it."""
    values = validate_new_person("new_member" if group == "new_members" else "baptismal", payload)
    args = {key: person_id, "new_first_name": values["first_name"], "new_last_name": values["last_name"]}
    if group == "new_members":
        args.update({f"new_{field}": values[field] for field in NEW_MEMBER_RPC_FIELDS})
        _rpc(conn, "update_new_member_profile", args)
    else:
        args["new_finding_source"] = values["finding_source"]
        _rpc(conn, "update_baptismal_date_person", args)
    return f"Details saved for {' '.join(filter(None, (values['first_name'], values['last_name'])))}."


def _transfer_person(conn, group, key, person_id, person, name, payload):
    """Move the person to another area and ward of the mission (they then appear on that area's plan)."""
    area_id = _positive_id(payload.get("area_id"), "Choose the new area.")
    unit_id = _positive_id(payload.get("unit_id"), "Choose the ward or branch.")
    target = fetch_one(conn, """
        SELECT a.name AS area, u.name AS unit FROM public.area_units au
        JOIN public.areas a ON a.id=au.area_id JOIN public.units u ON u.id=au.unit_id
        WHERE au.area_id=%s AND au.unit_id=%s AND au.active AND u.active AND a.active
    """, (area_id, unit_id))
    if not target:
        raise FieldErrors({"unit_id": "Choose a ward or branch of the new area."})
    if area_id == person.get("area_id") and unit_id == person.get("unit_id"):
        raise FieldErrors({"area_id": f"{name} is already in this area and ward or branch. Choose another one."})
    _rpc(conn, "transfer_new_member" if group == "new_members" else "transfer_baptismal_date_person",
         {key: person_id, "target_area_id": area_id, "target_unit_id": unit_id})
    return (f"{name} was transferred to {target['area']} ({target['unit']}) and now appears on that area's plan. "
            f"Consider letting those missionaries know about {name}.")


def _end_or_drop_person(conn, action, key, person_id, name, payload):
    """End follow-up (a New Member) or No longer on date (a friend), with a reason from the list."""
    reasons = dict(END_REASONS if action == "end" else DROP_REASONS)
    reason = payload.get("reason")
    if not isinstance(reason, str) or reason not in reasons:
        raise FieldErrors({"reason": "Choose a reason."})
    _rpc(conn, "archive_new_member" if action == "end" else "archive_baptismal_date_person",
         {key: person_id, "archive_reason": reason})
    return (f"Follow-up for {name} has ended." if action == "end"
            else f"{name} is off the baptismal date list.")


def _baptized(conn, report_id, key, person_id, name, payload, extra):
    """"Baptized": the friend becomes a New Member (the New Member form without the name) on this plan."""
    values = validate_new_person("convert", payload)
    args = {key: person_id, **{f"new_{field}": values[field] for field in CONVERT_RPC_FIELDS}}
    created = fetch_one(conn, "SELECT (public.convert_baptismal_date_person_to_new_member({})).id AS id".format(
        ", ".join(f"{arg} => %s" for arg in args)), tuple(args.values()))
    _insert_weekly_person(conn, report_id, "weekly_new_members", "new_member_id", created["id"])
    extra["new_member_id"] = created["id"]
    return f"{name} is now in New Member Follow-up. What a blessing!"


def _delete_person(conn, report_id, group, key, person_id, name, extra):
    """Delete a friend with a baptismal date who was added by mistake. (A New Member cannot be deleted: round 12.)"""
    _rpc(conn, "delete_baptismal_date_person_added_by_mistake", {key: person_id})
    return f"{name} was deleted."


def manage_planning_person(conn, context, report_id, group, person_id, action, payload):
    """Edit, transfer, end follow-up / drop, "Baptized" or (friends only) delete a person on the companionship's current draft.

    The person must be on this plan and still assigned to its area. Everything runs in one transaction as the
    signed-in user through the people functions (023), which check access again. Afterwards the person's row
    leaves this plan (except for Edit details; "Baptized" adds the new New Member instead). Returns the plan's
    people, so the page updates without reloading, and a message for the missionary.
    """
    if group not in PERSON_ACTIONS or action not in PERSON_ACTIONS[group]:
        raise ValueError("This action is not available here. Reload and try again.")
    if not isinstance(payload, dict):
        raise ValueError("The details are invalid.")
    report = _report_for_edit(conn, context, report_id, "You can change people only on your companionship's plan.",
                              "This plan is submitted. Ask a leader to unlock it before changing people on it.")
    if group == "new_members":
        table, column = "weekly_new_members", "new_member_id"
    else:
        table, column = "weekly_baptismal_date_friends", "baptismal_date_person_id"
    person = _person_on_plan(conn, report_id, group, person_id)
    if not person:
        raise ValueError("This person is no longer on this plan. Reload to see the latest list.")
    name = person.get("display_name") or ("This New Member" if group == "new_members" else "This friend")
    if person.get("area_id") != report["area_id"]:
        raise ValueError(f"{name} is no longer assigned to your area. Reload to see the latest list.")
    key = "target_new_member_id" if group == "new_members" else "target_baptismal_date_person_id"
    extra = {}
    try:
        if action == "edit":
            message = _edit_person(conn, group, key, person_id, payload)
        elif action == "transfer":
            message = _transfer_person(conn, group, key, person_id, person, name, payload)
        elif action in {"end", "drop"}:
            message = _end_or_drop_person(conn, action, key, person_id, name, payload)
        elif action == "baptized":
            message = _baptized(conn, report_id, key, person_id, name, payload, extra)
        else:  # delete
            message = _delete_person(conn, report_id, group, key, person_id, name, extra)
    except psycopg2.Error as error:
        mapped = _person_rpc_error(error, name)
        if mapped is None:
            raise
        raise mapped from None
    if action != "edit":  # the person leaves this plan
        with conn.cursor() as cursor:
            cursor.execute(f"DELETE FROM public.{table} WHERE weekly_area_report_id=%s AND {column}=%s",
                           (report_id, person_id))
    _mark_worked_on(conn, report_id)
    return json_ready({"ok": True, "action": action, "message": message, **extra,
                       "people": _report_people(conn, report_id),
                       "available_people": _available_people(conn, report["area_id"], report["unit_id"], report_id)})


def planning_transfer_targets(conn, context):
    """The active areas of the caller's mission with their wards and branches, for the Transfer dialogs.

    Areas come in zone, district and area order (the page groups them); an area without an active ward or
    branch is left out, because a transfer needs one.
    """
    rows = fetch_rows(conn, """
        SELECT z.id AS zone_id, z.name AS zone, d.id AS district_id, d.name AS district,
               a.id AS area_id, a.name AS area, u.id AS unit_id, u.name AS unit
        FROM public.areas a
        JOIN public.districts d ON d.id=a.district_id
        JOIN public.zones z ON z.id=d.zone_id
        JOIN public.area_units au ON au.area_id=a.id AND au.active
        JOIN public.units u ON u.id=au.unit_id AND u.active
        WHERE a.active AND z.mission_id=%s
        ORDER BY z.name, d.name, a.name, au.primary_unit DESC, u.name
    """, (context.get("mission_id"),))
    areas = {}
    for row in rows:
        area = areas.setdefault(row["area_id"], {**{key: row[key] for key in (
            "zone_id", "zone", "district_id", "district", "area_id", "area")}, "units": []})
        area["units"].append({"unit_id": row["unit_id"], "unit": row["unit"]})
    return json_ready({"current_area_id": context.get("area_id"), "areas": list(areas.values())})


# ================================================================================================ 7. submit and unlock

class PeopleIncomplete(ValueError):
    """Submit refused: people with unanswered questions. A 400 whose "fields" holds {"people": [...]}, one entry
    per person: {group, id (weekly row), person_id, name, fields: [question keys]} (see app.error_response)."""

    def __init__(self, people):
        self.fields = {"people": people}
        names = ", ".join(f"{person['name']} ({PEOPLE_GROUP_LABELS[person['group']]})" for person in people[:5])
        more = f" and {len(people) - 5} more" if len(people) > 5 else ""
        super().__init__(f"Almost there. Some questions about {names}{more} are not answered yet. Answer them, then submit again.")


def _missing_person_fields(people):
    """The people whose weekly questions are not all answered (PEOPLE_REQUIRED), in page order.

    people is _report_people(...). New Members and friends who are no longer assigned to the plan's area
    (is_current false, e.g. transferred by a leader) are not checked.
    """
    missing = []
    for group in ("baptismal_friends", "new_members", "high_potential"):
        for row in people.get(group, []):
            if group != "high_potential" and not row.get("is_current"):
                continue
            keys = list(PEOPLE_REQUIRED[group])
            if group == "new_members" and row.get("discussed_in_gemiko") is True:
                keys.append("gemiko_support_plan")
            fields = [key for key in keys if _is_blank(row.get(key))
                      or (key == "name" and str(row.get(key)).strip() == HIGH_POTENTIAL_PLACEHOLDER)]
            if fields:
                name = (row.get("name") if group == "high_potential" else row.get("display_name")) or "A person"
                if name == HIGH_POTENTIAL_PLACEHOLDER:
                    name = "A new friend"
                missing.append({"group": group, "id": row["id"], "name": name, "fields": fields,
                                "person_id": row.get("new_member_id") or row.get("baptismal_date_person_id")})
    return missing


def _check_people_complete(conn, report):
    """Refuse to submit a draft while a person on it has unanswered questions (raises PeopleIncomplete)."""
    if report.get("status") != "DRAFT":
        return
    missing = _missing_person_fields(_report_people(conn, report["id"]))
    if missing:
        raise PeopleIncomplete(missing)


def submit_planning_report(conn, context, report_id):
    """Submit the companionship's plan of this week, once every required question and person card is answered."""
    report = fetch_one(conn, """
        SELECT war.id, war.area_id, war.unit_id, war.status, rw.sunday,
               public.current_reporting_sunday() AS current_sunday
        FROM public.weekly_area_reports war JOIN public.reporting_weeks rw ON rw.id = war.reporting_week_id
        WHERE war.id = %s
    """, (report_id,))
    if not report or report["area_id"] != context.get("area_id"):
        raise PermissionError("You can submit only your companionship's current plan.")
    if report["sunday"] != report["current_sunday"]:
        raise ValueError("Open the current reporting week to submit your plan.")
    if report["status"] == "LOCKED":
        raise ValueError("This plan is locked. Ask a leader to review it.")
    if report["unit_id"] is None:
        raise ValueError("Choose your ward or branch in Weekly Planning before submitting.")
    _check_required_answers(conn, report_id)
    _check_people_complete(conn, report)
    result = fetch_one(conn, "SELECT public.submit_current_weekly_report(%s) AS report_id", (report["unit_id"],))
    return {"report_id": result["report_id"], "status": "SUBMITTED", "shared": True}


def unlock_planning_report(conn, context, report_id):
    """Reopen a submitted plan (DLs, ZLs and managers); the database checks the stewardship again."""
    if not roles.can_unlock_plans(context):
        raise PermissionError("A leader must unlock a submitted plan.")
    report = fetch_one(conn, "SELECT id, status FROM public.weekly_area_reports WHERE id = %s", (report_id,))
    if not report:
        raise PermissionError("This plan is outside your stewardship.")
    if report["status"] != "SUBMITTED":
        raise ValueError("Only a submitted plan can be reopened.")
    result = fetch_one(conn, "SELECT * FROM public.unsubmit_weekly_report(%s)", (report_id,))
    return json_ready({"report_id": result["weekly_report_id"], "status": result["status"], "shared": True})
