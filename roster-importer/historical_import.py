"""Historical CSV: reading the old Weekly Planning form export, and keeping every answer of it ("staging").

Before the portal, companionships filled out a Google form every Sunday. Its export (one row per form sent) is what
DA Management > Historical CSV imports. This file:
  - reads the export (read_csv_rows): the headings it needs are the *_COLUMN names below; each row gets its Sunday
    (_sunday), when it was sent (_timestamp) and its row number (_source_row_number);
  - keeps the latest form of each companionship, Sunday and unit (deduplicate_rows);
  - gives each report a key (make_report_key): 'frankfurt-darmstadt-s:2026-08-09';
  - copies every row into the staging tables (stage_rows): the report and its key indicators, the new
    members, the friends with a baptismal date, the high-potential friends, and every other answer, so nothing of the
    old forms is lost.

The check and Apply that use it: historical_preview.py and historical_apply.py.
"""
import csv
import io
import re
from datetime import datetime
from pathlib import Path

import database

# The headings of the old form's export that every file must have.
SUNDAY_COLUMN = "Which Sunday is this form being filled-out for? (This Week's)"
COMPANIONSHIP_COLUMN = "Which companionship is filling out the form?"
UNIT_COLUMN = "Which Ward/Branch Are You in?"
TIMESTAMP_COLUMN = "Timestamp"
EMAIL_COLUMN = "Email Address"

# The key indicators of the old form: its heading -> the column of the report (weekly_area_reports and staging).
# The headings are written as the old form wrote them (some with two spaces); never rename them.
REPORT_COLUMNS = {
    "Baptisms and Confirmations - Actual": "baptisms_confirmations_actual",
    "Baptisms and Confirmations - Goal for Next Week": "baptisms_confirmations_goal",
    "KI: New Member Sacrament Attendance - Actual": "new_member_sacrament_actual",
    "KI: New Member Sacrament Attendance -  Goal for Next Week": "new_member_sacrament_goal",
    "Baptismal Dates - Actual": "baptismal_dates_actual",
    "Baptismal Dates - Goal for Next Week": "baptismal_dates_goal",
    "Friends Found - Actual": "friends_found_actual",
    "Friends Found - Goal for next week": "friends_found_goal",
    "Lessons with Friends - Actual": "lessons_with_friends_actual",
    "Lessons with Friends -  Goal for next week": "lessons_with_friends_goal",
    "Follow-Up Lessons - Actual": "follow_up_lessons_actual",
    "Follow-Up Lessons -  Goal for next week": "follow_up_lessons_goal",
    "Lessons with a Member Participating - Actual": "lessons_with_members_actual",
    "Lessons with a Member Participating -  Goal for next week": "lessons_with_members_goal",
    "Sacrament Attendance - Actual": "sacrament_attendance_actual",
    "Sacrament Attendance -  Goal for next week": "sacrament_attendance_goal",
    "Number of People who Attended Sacrament for the First time": "first_time_sacrament_actual",
}

# The action plans of the old form: they become the report's notes, in this order (a list, not a set, so the notes
# of the same file always come out the same).
ACTION_PLAN_COLUMNS = (
    "Optional: Baptisms and Confirmations Action Plan",
    "Optional: New Member Action Plan",
    "Optional: Baptismal Dates Action Plan",
    "Optional: Friends Found Action Plan",
    "Optional: Lessons with a Member Participating Action Plan",
    "Optional: Sacrament Attendance Action Plan",
    "Weekly Action Plan",
)

# Headings that start like these belong to the person cards (new members, friends); they are staged in their own
# tables, not as plain answers.
STRUCTURED_PREFIXES = (
    "First & Last Name pt.",
    "Gender pt.",
    "Age pt.",
    "Lessons with New Member",
    "Percentage of New Member",
    "What is their next ordinance",
    "Grid Multiple Choice NM",
    "Do you have any additional New Member",
    "First Name pt.",
    "Last Name pt.",
    "When was the baptismal date set?",
    "Finding Source, of friend on baptismal date",
    "Baptismal Date Friend Commitments",
    "For which date is their baptismal date currently set?",
    "In which Stake is this baptismal date set for?",
    "Do you have any additional friend",
    "Optional: High potential",
    "How are they doing? pt.",
    "Did You discuss them in Gemiko this week? pt.",
    "How will the Gemiko support them this week? pt.",
)

# Headings that are already kept elsewhere (the report itself), so they are not staged as answers again.
META_COLUMNS = {TIMESTAMP_COLUMN, EMAIL_COLUMN, COMPANIONSHIP_COLUMN, UNIT_COLUMN, SUNDAY_COLUMN,
                *REPORT_COLUMNS.keys(), *ACTION_PLAN_COLUMNS}

# The staging tables, cleared of a report's earlier rows before it is staged again.
STAGING_TABLES = ["import_weekly_planning_answers", "import_weekly_new_members",
                  "import_weekly_baptismal_date_friends", "import_weekly_high_potential_friends",
                  "import_weekly_planning_reports"]


# ------------------------------------------------------------------------------------------ reading cells

def clean(value):
    """Text without extra spaces; None becomes ''."""
    return " ".join(str(value or "").strip().split())


def integer(value):
    """A whole number from a cell ('3', '3.0', '1,200', '40%'), or None when empty or not a number."""
    value = clean(value)
    if not value:
        return None
    try:
        return int(float(value.replace("%", "").replace(",", "")))
    except ValueError:
        return None


def number(value):
    """A number from a cell ('2.5', '1,200', '40%' -> 40.0), or None when empty or not a number."""
    value = clean(value)
    if not value:
        return None
    try:
        return float(value.replace("%", "").replace(",", ""))
    except ValueError:
        return None


def parse_boolean(value):
    """True for yes/true/1/y, False for no/false/0/n (any capitals), else None."""
    value = clean(value).casefold()
    if value in {"yes", "true", "1", "y"}:
        return True
    if value in {"no", "false", "0", "n"}:
        return False
    return None


def parse_three_state(value):
    """'yes', 'no' or 'not_applicable' (also from 'n/a' or 'na'), else None."""
    value = clean(value).casefold()
    if value in {"yes", "no"}:
        return value
    if value in {"not applicable", "not_applicable", "n/a", "na"}:
        return "not_applicable"
    return None


def parse_source_date(value):
    """A date written as 9/14/2026, 9/14/26, 2026-09-14 or 14.09.2026; None when empty. Raises ValueError otherwise."""
    value = clean(value)
    if not value:
        return None
    for date_format in ("%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d", "%d.%m.%Y"):
        try:
            return datetime.strptime(value, date_format).date()
        except ValueError:
            pass
    raise ValueError(f"Could not parse date: {value}")


def parse_source_timestamp(value):
    """The time a form was sent (the export's Timestamp); None when empty. Raises ValueError when unreadable."""
    value = clean(value)
    if not value:
        return None
    for time_format in ("%m/%d/%Y %H:%M:%S", "%m/%d/%Y %H:%M", "%m/%d/%Y %I:%M:%S %p", "%m/%d/%Y %I:%M %p",
                        "%Y-%m-%d %H:%M:%S", "%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M"):
        try:
            return datetime.strptime(value, time_format)
        except ValueError:
            pass
    raise ValueError(f"Could not parse timestamp: {value}")


# ------------------------------------------------------------------------------------------ reading the file

def read_csv_rows(path):
    """Every row of the export that names a companionship and a Sunday, as a dict {heading: value} plus _sunday,
    _timestamp and _source_row_number. Raises ValueError for a missing heading or a broken row."""
    text = Path(path).read_text(encoding="utf-8-sig")
    # StringIO, not splitlines(): planning answers and action plans can contain quoted line breaks, and splitting the
    # text into lines first would break those records and shift later answers into the wrong columns.
    reader = csv.DictReader(io.StringIO(text), strict=True)
    required = {TIMESTAMP_COLUMN, EMAIL_COLUMN, COMPANIONSHIP_COLUMN, UNIT_COLUMN, SUNDAY_COLUMN}
    missing = required - set(reader.fieldnames or [])
    if missing:
        raise ValueError("Weekly Planning CSV is missing required columns: " + ", ".join(sorted(missing)))
    rows = []
    for row_number, row in enumerate(reader, start=2):
        if None in row:
            raise ValueError(f"Row {row_number} has more values than the CSV header.")
        sunday = clean(row.get(SUNDAY_COLUMN))
        if not clean(row.get(COMPANIONSHIP_COLUMN)) or not sunday:
            continue
        row["_source_row_number"] = row_number
        row["_timestamp"] = parse_source_timestamp(row.get(TIMESTAMP_COLUMN))
        row["_sunday"] = parse_source_date(sunday)
        rows.append(row)
    return rows


def deduplicate_rows(rows, unit_of=None):
    """(the rows to keep, the older rows left out): one report per companionship and Sunday (and unit, when unit_of
    gives each row's unit). When a form was sent twice, the one sent last counts. A companionship that serves two
    wards or branches sends one form per unit, so with unit_of both are kept."""
    winners, duplicates = {}, []
    for row in rows:
        key = (clean(row.get(COMPANIONSHIP_COLUMN)).casefold(), row["_sunday"], unit_of(row) if unit_of else None)
        previous = winners.get(key)
        if previous is None:
            winners[key] = row
        elif (row["_timestamp"] or datetime.min) >= (previous["_timestamp"] or datetime.min):
            duplicates.append(previous)
            winners[key] = row
        else:
            duplicates.append(row)
    selected = sorted(winners.values(), key=lambda r: (r["_sunday"], clean(r.get(COMPANIONSHIP_COLUMN)),
                                                        str(unit_of(r)) if unit_of else ""))
    return selected, duplicates


def make_report_key(companionship, sunday):
    """'frankfurt-darmstadt-s:2026-08-09': the label in small letters with every run of other characters as one '-',
    and the Sunday. (So 'Frankfurt-Darmstadt S' and 'Frankfurt Darmstadt S' get the same key: the check asks which
    to keep.)"""
    safe = re.sub(r"[^a-z0-9]+", "-", companionship.casefold()).strip("-")
    return f"{safe}:{sunday.isoformat()}"


# ------------------------------------------------------------------------------------------ staging

def stage_rows(conn, selected):
    """Stages the rows the check selected (after the manager's choices), in the caller's transaction: each row's
    report, person cards and answers. The earlier staging rows of the same report keys are replaced first, so
    re-importing a file never doubles them. Raises ValueError when a label has no mapped area."""
    with database.cursor(conn) as cur:
        mappings = area_mapping(cur)
        check_mappings(selected, mappings)
        keys = [row.get("_report_key") or make_report_key(clean(row.get(COMPANIONSHIP_COLUMN)), row["_sunday"]) for row in selected]
        for table in STAGING_TABLES:
            cur.execute(f"delete from public.{table} where source_report_key = any(%s)", (keys,))
        for row in selected:
            key = stage_report(cur, row, mappings)
            stage_new_members(cur, key, row)
            stage_baptismal_date_friends(cur, key, row)
            stage_high_potentials(cur, key, row)
            stage_planning_answers(cur, key, row)


def area_mapping(cur):
    """{old label in small letters: its mapping (target_area_name, match_status)} from Area mappings."""
    cur.execute("""
        select
          source_companionship,
          coalesce(a.name,m.target_area_name) as target_area_name,
          match_status
        from public.import_weekly_planning_area_map m
        left join public.areas a on a.id=m.target_area_id
    """)
    return {clean(row["source_companionship"]).casefold(): row for row in cur.fetchall()}


def check_mappings(selected, mappings):
    """Every label must have a mapping with a target area; raises ValueError listing the ones that do not."""
    labels = {clean(row.get(COMPANIONSHIP_COLUMN)) for row in selected}
    missing = sorted(label for label in labels if label.casefold() not in mappings)
    unresolved = sorted(label for label in labels
                        if label.casefold() in mappings and not clean(mappings[label.casefold()]["target_area_name"]))
    messages = []
    if missing:
        messages.append("Missing area mappings:\n" + "\n".join(missing))
    if unresolved:
        messages.append("Unresolved area mappings:\n" + "\n".join(unresolved))
    if messages:
        raise ValueError("\n\n".join(messages))


def stage_report(cur, row, area_map):
    """Stages one form as a report (import_weekly_planning_reports): its key indicators and action plans. Returns its
    report key."""
    companionship = clean(row.get(COMPANIONSHIP_COLUMN))
    mapping = area_map.get(companionship.casefold())
    if not mapping:
        raise ValueError(f"No area mapping exists for '{companionship}'.")
    target_area = clean(mapping["target_area_name"])
    if not target_area:
        raise ValueError(f"Area mapping for '{companionship}' has no target area.")
    sunday = row["_sunday"]
    # The check gives a look-alike label its own key when the manager chose to combine labels whose keys collide.
    key = row.get("_report_key") or make_report_key(companionship, sunday)
    values = {
        "source_report_key": key,
        "source_row_number": row["_source_row_number"],
        "source_timestamp": row["_timestamp"],
        "source_email": clean(row.get(EMAIL_COLUMN)) or None,
        "source_companionship": companionship,
        "target_area_name": target_area,
        "source_unit": clean(row.get(UNIT_COLUMN)) or None,
        "reporting_sunday": sunday,
        "status": "SUBMITTED",
    }
    for source_column, target_column in REPORT_COLUMNS.items():
        values[target_column] = integer(row.get(source_column))
    notes = [f"{column}: {clean(row.get(column))}" for column in ACTION_PLAN_COLUMNS if clean(row.get(column))]
    values["notes"] = "\n\n".join(notes) if notes else None
    columns = list(values)
    cur.execute(f"insert into public.import_weekly_planning_reports ({','.join(columns)}) values ({','.join(['%s'] * len(columns))})",
                tuple(values[column] for column in columns))
    return key


def new_member_column(row, part, template):
    """The cell of new member number `part` for a heading template ('Gender pt.{part}'). The 5th new member's
    headings are sometimes written 'pt5' instead of 'pt.5'."""
    candidates = [template.format(part=part)]
    if part == 5:
        candidates.append(template.format(part="5").replace("pt.5", "pt5"))
    for candidate in candidates:
        if candidate in row:
            return row.get(candidate)
    return None


def stage_new_members(cur, report_key, row):
    """Stages the (up to 10) new members of one form (import_weekly_new_members)."""
    for part in range(1, 11):
        name = clean(new_member_column(row, part, "First & Last Name pt.{part}"))
        if name:
            cur.execute("""
                insert into public.import_weekly_new_members (
                  source_report_key, display_order, source_name, source_gender, source_age_range, lessons_actual,
                  lessons_goal, pmg_lessons_percentage, next_ordinance, at_church_this_sunday, has_calling,
                  has_aaronic_priesthood, has_melchizedek_priesthood, ministers_to_someone, ministered_to_by_someone,
                  has_active_temple_recommend, visited_temple_for_baptisms, reading, praying, member_involvement,
                  how_are_they_doing, discussed_in_gemiko, gemiko_support_plan)
                values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """, (report_key, part, name) + new_member_answers(row, part))


def new_member_answers(row, part):
    """The answers about new member number `part`, in the order of the columns above (after the name)."""
    def cell(template):
        return new_member_column(row, part, template)

    return (
        clean(cell("Gender pt.{part}")) or None,
        clean(cell("Age pt.{part}")) or None,
        integer(cell("Lessons with New Member - Actual pt.{part}")),
        integer(cell("Lessons with New Member - Next week's Goal pt.{part}")),
        number(cell("Percentage of New Member lessons taught as listed in PMG pt.{part}")),
        clean(cell("What is their next ordinance pt.{part}")) or None,
        parse_boolean(cell("Grid Multiple Choice NM questions pt.{part} [Were they at church this Sunday?]")),
        parse_three_state(cell("Grid Multiple Choice NM questions pt.{part} [Does this new member have a calling?]")),
        parse_three_state(cell("Grid Multiple Choice NM questions pt.{part} [Aaronic Priesthood]")),
        parse_three_state(cell("Grid Multiple Choice NM questions pt.{part} [Melchizedek Priesthood]")),
        parse_three_state(cell("Grid Multiple Choice NM questions pt.{part} [Are they officially a minister to someone else]")),
        parse_boolean(cell("Grid Multiple Choice NM questions pt.{part} [Are they officially being ministered to by someone else]")),
        parse_three_state(cell("Grid Multiple Choice NM questions pt.{part} [Does this new member have an active temple recommend]")),
        parse_three_state(cell("Grid Multiple Choice NM questions pt.{part} [Have they previously visited the temple for Baptisms for the Dead]")),
        parse_boolean(cell("Grid Multiple Choice NM questions pt.{part} [Reading?]")),
        parse_boolean(cell("Grid Multiple Choice NM questions pt.{part} [Praying?]")),
        parse_boolean(cell("Grid Multiple Choice NM questions pt.{part} [Do they have member involvement?]")),
        clean(row.get(f"How are they doing? pt.{part}")) or None,
        parse_boolean(row.get(f"Did You discuss them in Gemiko this week? pt.{part}")),
        clean(row.get(f"How will the Gemiko support them this week? pt.{part}")) or None,
    )


def stage_baptismal_date_friends(cur, report_key, row):
    """Stages the (up to 12) friends with a baptismal date of one form (import_weekly_baptismal_date_friends)."""
    for part in range(1, 13):
        first_name = clean(row.get(f"First Name pt.{part}"))
        last_name = clean(row.get(f"Last Name pt.{part}"))
        if not first_name and not last_name:
            continue
        # The old form asked "Reading and Praying?" as one question: it fills both columns.
        reading_and_praying = parse_boolean(row.get(f"Baptismal Date Friend Commitments pt.{part} [Reading and Praying?]"))
        cur.execute("""
            insert into public.import_weekly_baptismal_date_friends (
              source_report_key, display_order, source_first_name, source_last_name, baptismal_date_set_on,
              finding_source, reading, praying, at_church_this_sunday, keeping_commandments, member_involvement,
              current_baptismal_date, source_stake_name)
            values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """, (
            report_key,
            part,
            first_name or None,
            last_name or None,
            parse_source_date(row.get(f"When was the baptismal date set? pt.{part}")),
            clean(row.get(f"Finding Source, of friend on baptismal date pt.{part}")) or None,
            reading_and_praying,
            reading_and_praying,
            parse_boolean(row.get(f"Baptismal Date Friend Commitments pt.{part} [Were they at church this Sunday?]")),
            parse_boolean(row.get(f"Baptismal Date Friend Commitments pt.{part} [Keeping the Commandments?]")),
            parse_boolean(row.get(f"Baptismal Date Friend Commitments pt.{part} [Member Involvement?]")),
            parse_source_date(row.get(f"For which date is their baptismal date currently set? pt.{part}")),
            clean(row.get(f"In which Stake is this baptismal date set for? pt.{part}")) or None,
        ))


def stage_high_potentials(cur, report_key, row):
    """Stages the (up to 10) high-potential friends of one form (import_weekly_high_potential_friends)."""
    for part in range(1, 11):
        name = clean(row.get(f"Optional: High potential {part}, first and last name"))
        if name:
            cur.execute("""
                insert into public.import_weekly_high_potential_friends
                  (source_report_key, display_order, name, at_church_this_sunday, notes)
                values (%s,%s,%s,%s,%s)
            """, (report_key, part, name, parse_boolean(row.get(f"Optional: High potential {part}, were they at church?")), None))


def should_stage_as_answer(column):
    """Is this heading a plain question of the form (not the report itself, and not a person card)?"""
    if column in META_COLUMNS:
        return False
    return not column.startswith(STRUCTURED_PREFIXES)


def typed_answer(raw):
    """(yes/no, number, text) of an answer: exactly one is filled (or none for an empty answer)."""
    raw = clean(raw)
    if not raw:
        return None, None, None
    if raw.casefold() in {"yes", "no", "true", "false"}:
        return parse_boolean(raw), None, None
    numeric = number(raw)
    if numeric is not None and re.fullmatch(r"-?\d+(?:\.\d+)?%?", raw.replace(",", "")):
        return None, numeric, None
    return None, None, raw


def stage_planning_answers(cur, report_key, row):
    """Stages every other answer of one form (import_weekly_planning_answers), with its heading as the question."""
    for column, raw_value in row.items():
        if column.startswith("_") or not should_stage_as_answer(column):
            continue
        raw = clean(raw_value)
        if not raw:
            continue
        answer_boolean, answer_number, answer_text = typed_answer(raw)
        cur.execute("""
            insert into public.import_weekly_planning_answers
              (source_report_key, source_column, source_question_label, answer_raw, answer_boolean, answer_number, answer_text)
            values (%s,%s,%s,%s,%s,%s,%s)
        """, (report_key, column, column, raw, answer_boolean, answer_number, answer_text))
