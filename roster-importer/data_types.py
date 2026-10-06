"""The five kinds of data upload: which columns each file has, and how its rows become the rows we store.

Every kind turns the rows of a file into `records` (plain dicts) and a list of problems. Nothing here reads the
database: matching zone and area names to the portal happens afterwards (data_names.py), and saving happens in
data_uploads.py. Names of people are not read from a file, only the columns listed here are looked at. The one
exception is the People upload (parse_people, section 5, saved by people_upload.py): it exists to read names.
"""
from datetime import date

from data_files import (FileProblem, cell, clean, find_heading_row, heading_key, read_count, read_date, read_decimal,
                        read_rate, week_before, week_of, week_reported_on)
from data_text import plain

MAX_PROBLEMS_SHOWN = 100
# Rows that hold a total for the whole mission; totals are always added up from the zones and areas instead.
MISSION_WORDS = {"mission", "mission total", "total", "gesamt", "mission gesamt"}


class Parsed:
    """What reading a file gave: the records to store, and the problems found on the way."""

    def __init__(self):
        self.records = []
        self.problems = []  # [row number, text] of the first MAX_PROBLEMS_SHOWN problems
        self.problem_count = 0
        self.rows_read = 0
        self.left_out = 0  # rows left out on purpose (mission totals, empty rows of a sheet)

    def problem(self, row_number, text):
        self.problem_count += 1
        if len(self.problems) < MAX_PROBLEMS_SHOWN:
            self.problems.append([row_number, text])

    def as_dict(self):
        return {"records": self.records, "problems": self.problems, "problem_count": self.problem_count,
                "rows_read": self.rows_read, "left_out": self.left_out}


def is_mission_total(*names):
    """True when the row is a mission total: its zone or area says 'Mission' (or Total) and nothing else is given."""
    words = [clean(n).casefold() for n in names if clean(n)]
    return bool(words) and all(w in MISSION_WORDS for w in words)


def add_counts(total, row, fields):
    """Adds the numbers of `row` to `total`; an empty cell adds nothing, and two empty cells stay empty."""
    for field in fields:
        if row.get(field) is not None:
            total[field] = (total.get(field) or 0) + row[field]


# --------------------------------------------------------------------------------------------- 1. area data

AREA_FIELDS = {  # stored column: the headings that fill it (the first is the template's)
    "population": ["Population", "Einwohner"],
    "size_km2": ["Size (km2)", "Size km2", "Area (km2)", "km2", "Fläche (km2)"],
    "urban_type": ["Urban type", "Urban", "Stadt oder Land"],
    "assignment_type": ["Assignment type", "Assignment", "Missionaries"],
}
AREA_NAME_HEADINGS = ["Zone", "District", "Area"]
# Shown in the template only, worked out from population and km2; never read back.
AREA_INFO_HEADINGS = ["Density (people per km2)", "Density", "Active"]
URBAN_TYPES = ["Big city", "City", "Town", "Rural"]
ASSIGNMENT_TYPES = ["Elders", "Sisters", "Elders and sisters", "Senior couple"]


def area_template(areas):
    """Template rows: every current area with what is saved for it today, so the file only needs filling in."""
    extra_names = sorted({k for a in areas for k in (a.get("extra") or {})})
    headings = AREA_NAME_HEADINGS + [names[0] for names in AREA_FIELDS.values()] + [AREA_INFO_HEADINGS[0]] + extra_names
    rows = []
    for a in areas:
        extra = a.get("extra") or {}
        rows.append([a["zone"], a["district"], a["area"], none_as_blank(a.get("population")),
                     number_text(a.get("size_km2")), a.get("urban_type") or "", a.get("assignment_type") or "",
                     number_text(a.get("density_per_km2"))] + [extra.get(k, "") for k in extra_names])
    return headings, rows


def none_as_blank(value):
    return "" if value is None else value


def number_text(value):
    """12.0 -> '12', 12.5 -> '12.5', None -> ''."""
    if value is None:
        return ""
    value = float(value)
    return str(int(value)) if value == int(value) else str(round(value, 3))


def parse_area_data(rows):
    parsed = Parsed()
    start, columns = find_heading_row(rows, ["Area"])
    headings = rows[start]
    known = {heading_key(h) for names in AREA_FIELDS.values() for h in names}
    known |= {heading_key(h) for h in AREA_NAME_HEADINGS + AREA_INFO_HEADINGS}
    # Every other heading is a free extra attribute (for example "Chapel nearby" or "Languages").
    extras = [(index, clean(h)) for index, h in enumerate(headings) if clean(h) and heading_key(h) not in known]
    seen = {}
    for number, row in enumerate(rows[start + 1:], start=start + 2):
        parsed.rows_read += 1
        area = clean(cell(row, columns, "Area"))
        if not area:
            parsed.problem(number, plain("uploads.problem.noArea"))
            continue
        record = {"zone": clean(cell(row, columns, "Zone")), "district": clean(cell(row, columns, "District")),
                  "area": area, "row": number, "extra": {}}
        try:
            record["population"] = read_count(cell(row, columns, *AREA_FIELDS["population"]))
            size = read_decimal(cell(row, columns, *AREA_FIELDS["size_km2"]))
            if size == 0:
                raise ValueError(plain("uploads.problem.sizeZero"))
            record["size_km2"] = size
        except ValueError as error:
            parsed.problem(number, plain("uploads.problem.where", where=area, problem=error))
            continue
        for field in ("urban_type", "assignment_type"):
            value = clean(cell(row, columns, *AREA_FIELDS[field]))[:60]
            record[field] = value or None
        for index, name in extras:
            value = clean(row[index]) if index < len(row) else ""
            if value:
                record["extra"][name[:60]] = value[:200]
        key = (record["zone"].casefold(), area.casefold())
        if key in seen:
            parsed.problem(number, plain("uploads.problem.twiceLastWins", name=area))
            parsed.records[seen[key]] = record
        else:
            seen[key] = len(parsed.records)
            parsed.records.append(record)
    return parsed


# --------------------------------------------------------------------------------------------- 2. finding export

FINDING_DATES = {  # stored column: the Church export's headings (the first that the file has is read)
    "found_on": ["First Finding Event Date (truncated)", "First Finding Event Date", "Event Date Selected"],
    "referral_on": ["First Referral Event Date"],
    "contact_attempt_on": ["First Contact Attempt Event Date"],
    "contacted_on": ["First Successful Contact Attempt Event Date"],
    "first_lesson_on": ["First Lesson Date"],
    "second_lesson_on": ["Second Lesson Date"],
    "taught_on": ["First New Person Being Taught Date"],
    "baptismal_date_set_on": ["First Baptism Goal Date Set"],
    "first_sacrament_on": ["First Sacrament Date"],
    "confirmed_on": ["Confirmation Date"],
}
FINDING_CATEGORY = ["Finding Category (copy)", "Finding Category"]
FINDING_SOURCE = ["Finding Source"]
FINDING_AREA = ["Latest Teaching Area Name", "Teaching Area Name", "Area"]
FINDING_DISTRICT = ["Latest District Name", "District Name", "District"]
FINDING_ZONE = ["Latest Zone Name", "Zone Name", "Zone"]
FINDING_PERSON = ["Person Id", "Person ID"]


def finding_template():
    headings = (FINDING_PERSON[:1] + FINDING_CATEGORY[:1] + FINDING_SOURCE + FINDING_AREA[:1] + FINDING_DISTRICT[:1]
                + FINDING_ZONE[:1] + [names[0] for names in FINDING_DATES.values()])
    example = ["100000001", "Media", "Headquarters Paid Ad", "Bockenheim", "Frankfurt 1", "Frankfurt",
               "9/14/2026", "9/14/2026 10:15:00 AM", "9/14/2026 11:00:00 AM", "9/15/2026 9:30:00 AM",
               "9/18/2026", "", "", "", "", ""]
    return headings, [example]


def parse_finding(rows, person_key):
    """person_key(person id) gives the code stored instead of the Church person id (data_uploads.person_key)."""
    parsed = Parsed()
    start, columns = find_heading_row(rows, FINDING_PERSON[:1] + FINDING_SOURCE + FINDING_AREA[:1])
    if not any(heading_key(h) in columns for h in FINDING_CATEGORY):
        raise FileProblem(plain("uploads.problem.missingColumns", columns=FINDING_CATEGORY[0]))
    if not any(heading_key(h) in columns for h in FINDING_DATES["found_on"]):
        raise FileProblem(plain("uploads.problem.missingColumns", columns=FINDING_DATES["found_on"][0]))
    seen = set()
    for number, row in enumerate(rows[start + 1:], start=start + 2):
        parsed.rows_read += 1
        person = clean(cell(row, columns, *FINDING_PERSON))
        if not person:
            parsed.problem(number, plain("uploads.problem.noPerson"))
            continue
        code = person_key(person)
        if code in seen:
            parsed.problem(number, plain("uploads.problem.personTwice"))
            continue
        category = clean(cell(row, columns, *FINDING_CATEGORY))
        source = clean(cell(row, columns, *FINDING_SOURCE))
        if not category or not source:
            parsed.problem(number, plain("uploads.problem.noSource"))
            continue
        record = {"person_key": code, "finding_category": category[:80], "finding_source": source[:120],
                  "area": clean(cell(row, columns, *FINDING_AREA))[:120],
                  "district": clean(cell(row, columns, *FINDING_DISTRICT))[:120],
                  "zone": clean(cell(row, columns, *FINDING_ZONE))[:120]}
        for field, headings in FINDING_DATES.items():
            try:
                day = read_date(cell(row, columns, *headings))
                record[field] = day.isoformat() if day else None
            except ValueError as error:
                parsed.problem(number, plain("uploads.problem.where", where=headings[0], problem=error))
                record[field] = None
        if not record["found_on"]:
            parsed.problem(number, plain("uploads.problem.noFoundDate"))
            continue
        seen.add(code)
        parsed.records.append(record)
    return parsed


# --------------------------------------------------------------------------------------------- 3. zone history

# Stored column: the owner's "Data for Data Studio" heading first, then the Preach My Gospel one. A Goal column is the
# goal set that Sunday for the NEXT week, as in the sheet and in the portal's own <kpi>_goal (checked against the
# Weekly Planning Raw form: the sheet adds up "Goal for next week"). Dashboards measure a week against the goal of
# the week before (<kpi>_previous_goal in dashboards.zone_history_week).
ZONE_HISTORY_FIELDS = {
    "friends_found_goal": ["Friends Found Goal", "New People Being Taught Goal"],
    "friends_found_actual": ["Friends Found Actual", "New People Being Taught Actual", "New People Being Taught"],
    "members_at_lessons_goal": ["Lessons with a Mitbelehr Goal", "Lessons with a Member Participating Goal"],
    "members_at_lessons_actual": ["Lessons with a Mitbelehr Actual", "Lessons with a Member Participating Actual"],
    "sacrament_attendance_goal": ["Attendance at Church Goal", "People Being Taught Who Attend Sacrament Meeting Goal"],
    "sacrament_attendance_actual": ["Attendance at Church Actual", "People Being Taught Who Attend Sacrament Meeting Actual"],
    "baptismal_dates_goal": ["Baptismal Date Goal", "People with a Baptismal Date Goal"],
    "baptismal_dates_actual": ["Baptismal Date Actual", "People with a Baptismal Date Actual"],
    "baptisms_confirmations_goal": ["Baptism Goal", "People Who Are Baptized and Confirmed Goal"],
    "baptisms_confirmations_actual": ["Baptism Actual", "People Who Are Baptized and Confirmed Actual"],
    "new_member_sacrament_goal": ["New Member Attendance at Church Goal", "New Members Attending Sacrament Meeting Goal"],
    "new_member_sacrament_actual": ["New Member Attendance at Church Actual", "New Members Attending Sacrament Meeting Actual"],
    "follow_up_lessons_actual": ["Follow-up lessons Actual", "Follow-up Lessons"],
    "first_time_sacrament_actual": ["First Time Attendance", "First Time Attendance at Church"],
    "companionships": ["Companionships"],
}


def zone_history_template():
    headings = ["Sunday", "Zone"] + [names[0] for names in ZONE_HISTORY_FIELDS.values()]
    return headings, [["8/4/2024", "Frankfurt", 22, 18, 29, 18, 44, 26, 7, 5, 0, 1, 13, 7, 0, 2, 12]]


def parse_zone_history(rows):
    parsed = Parsed()
    start, columns = find_heading_row(rows, ["Sunday", "Zone"])
    present = {field: names for field, names in ZONE_HISTORY_FIELDS.items()
               if any(heading_key(n) in columns for n in names)}
    if not present:
        raise FileProblem(plain("uploads.problem.noIndicators"))
    seen = set()
    for number, row in enumerate(rows[start + 1:], start=start + 2):
        parsed.rows_read += 1
        zone = clean(cell(row, columns, "Zone"))
        if not zone or is_mission_total(zone):
            parsed.left_out += 1
            continue
        try:
            day = read_date(cell(row, columns, "Sunday"))
        except ValueError as error:
            parsed.problem(number, str(error))
            continue
        if not day:
            parsed.problem(number, plain("uploads.problem.noDate"))
            continue
        record = {"sunday": week_before(day).isoformat(), "zone": zone[:120]}
        for field, names in present.items():
            try:
                record[field] = read_count(cell(row, columns, *names))
            except ValueError as error:
                parsed.problem(number, plain("uploads.problem.where", where=names[0], problem=error))
                record[field] = None
        key = (record["sunday"], zone.casefold())
        if key in seen:
            parsed.problem(number, plain("uploads.problem.weekTwice", name=zone))
            continue
        seen.add(key)
        parsed.records.append(record)
    return parsed


# --------------------------------------------------------------------------------------------- 3b. referral archive

ARCHIVE_FIELDS = {
    "referrals_received": ["Referrals Received"],
    "referrals_contacted": ["Referrals Contacted"],
    "friends_made": ["Friends Made"],
    "lessons_taught": ["Lessons Taught"],
    "church_attendance": ["Church Attendance"],
    "baptismal_dates": ["Baptismal Date", "Baptismal Dates"],
    "baptisms": ["Baptisms"],
    "books_of_mormon": ["BOM Delivered", "Book of Mormon Delivered"],
    "with_member": ["With Member"],
    "follow_up_lessons": ["Follow-up Lessons", "Follow-up"],
}


def archive_template():
    headings = ["Date", "Mission", "Zone", "Area", "Source"] + [names[0] for names in ARCHIVE_FIELDS.values()]
    return headings, [["3/4/2024", "Frankfurt", "Heidelberg", "Worms", "BM Bestellung", 1, 1, 0, 0, 0, 0, 0, 1, 0, 0],
                      ["9/28/2026", "Frankfurt", "", "Bockenheim", "FindeChristus Referrals", 4, "", "", "", "", "", "", "", "", ""]]


def one_report_per_week(parsed, first_rows):
    """Keeps one report per week in the records of the referral archive or the rate archive.

    The sheets have one report per week, but sometimes two dates of a file show the same week (in the owner's rate
    archive Sunday 11 and Monday 12 Jan 2026). Adding both up would count that week twice, so the later report is
    used and the check page names both dates. first_rows: {report date: the file row where that date starts}."""
    dates_of_week = {}
    for record in parsed.records:
        dates_of_week.setdefault(record["sunday"], set()).add(record["report_date"])
    used = {}
    for sunday, dates in sorted(dates_of_week.items()):
        dates = sorted(dates)
        used[sunday] = dates[-1]
        for older in dates[:-1]:
            parsed.problem(first_rows[older], plain("uploads.problem.twoReports", older=short_day(older),
                                                    newer=short_day(dates[-1]), week=short_day(sunday)))
    parsed.records = [r for r in parsed.records if r["report_date"] == used[r["sunday"]]]


def short_day(iso):
    """'2026-09-27' -> '27 Sep 2026'."""
    return date.fromisoformat(iso).strftime("%d %b %Y")


def parse_archive(rows):
    """The FC Data Archives sheet: one row per referral (or per area and week); added up per date, zone, area and
    source. The referral number is not read. A report date counts for the week that report shows
    (data_files.week_reported_on: a Monday report shows the week that ended 8 days before), one report per week."""
    parsed = Parsed()
    start, columns = find_heading_row(rows, ["Date", "Area", "Referrals Received"])
    totals, first_rows = {}, {}
    for number, row in enumerate(rows[start + 1:], start=start + 2):
        parsed.rows_read += 1
        zone, area = clean(cell(row, columns, "Zone")), clean(cell(row, columns, "Area"))
        if is_mission_total(zone, area):
            parsed.left_out += 1
            continue
        if not zone and not area:
            parsed.problem(number, plain("uploads.problem.noZoneOrArea"))
            continue
        try:
            day = read_date(cell(row, columns, "Date"))
        except ValueError as error:
            parsed.problem(number, str(error))
            continue
        if not day:
            parsed.problem(number, plain("uploads.problem.noDate"))
            continue
        counts = {}
        for field, names in ARCHIVE_FIELDS.items():
            try:
                counts[field] = read_count(cell(row, columns, *names))
            except ValueError as error:
                parsed.problem(number, plain("uploads.problem.where", where=names[0], problem=error))
                counts[field] = None
        source = clean(cell(row, columns, "Source"))[:120]
        key = (day.isoformat(), zone[:120], area[:120], source)
        total = totals.setdefault(key, {"sunday": week_reported_on(day).isoformat(), "report_date": day.isoformat(),
                                        "zone": zone[:120], "area": area[:120], "source": source})
        add_counts(total, counts, ARCHIVE_FIELDS)
        first_rows.setdefault(day.isoformat(), number)
    parsed.records = list(totals.values())
    one_report_per_week(parsed, first_rows)
    return parsed


# --------------------------------------------------------------------------------------------- 3c. rates

def rates_template():
    return ["Date", "Zone", "Teaching Rate", "Contact Rate"], [["9/28/2026", "Mission", "26.00%", "99.30%"],
                                                              ["9/28/2026", "Frankfurt", "41.00%", "98.30%"]]


def parse_rates(rows):
    """The Teaching_Contact Rate Archive sheet: rates per report date and zone. Like the referral archive, a report
    date counts for the week the report shows (data_files.week_reported_on), one report per week."""
    parsed = Parsed()
    start, columns = find_heading_row(rows, ["Date", "Zone"])
    teaching = ["Teaching Rate"]
    contact = ["Contact Rate", "Contacting Rate"]
    if not any(heading_key(h) in columns for h in teaching + contact):
        raise FileProblem(plain("uploads.problem.missingColumns", columns="Teaching Rate, Contact Rate"))
    by_date_and_zone, first_rows = {}, {}
    for number, row in enumerate(rows[start + 1:], start=start + 2):
        parsed.rows_read += 1
        zone = clean(cell(row, columns, "Zone"))
        if not zone:
            parsed.left_out += 1
            continue
        try:
            day = read_date(cell(row, columns, "Date"))
            teaching_rate = read_rate(cell(row, columns, *teaching))
            contact_rate = read_rate(cell(row, columns, *contact))
        except ValueError as error:
            parsed.problem(number, str(error))
            continue
        if not day:
            parsed.problem(number, plain("uploads.problem.noDate"))
            continue
        if teaching_rate is None and contact_rate is None:
            parsed.left_out += 1
            continue
        mission = is_mission_total(zone)
        record = {"sunday": week_reported_on(day).isoformat(), "report_date": day.isoformat(),
                  "zone": "Mission" if mission else zone[:120], "is_mission": mission,
                  "teaching_rate": teaching_rate, "contact_rate": contact_rate}
        key = (record["report_date"], record["zone"].casefold())
        if key in by_date_and_zone:
            parsed.problem(number, plain("uploads.problem.weekTwice", name=record["zone"]))
            continue
        by_date_and_zone[key] = record
        first_rows.setdefault(record["report_date"], number)
    parsed.records = list(by_date_and_zone.values())
    one_report_per_week(parsed, first_rows)
    return parsed


# --------------------------------------------------------------------------------------------- 4. baptism history

# Three layouts are read: our template, the office's "Vollzogen" sheets and the "New Member Database Raw" form.
BAPTISM_LAYOUTS = [
    {"date": ["Baptism date"], "confirmed": ["Confirmation date"], "zone": ["Zone"], "area": ["Area"],
     "ward": ["Ward or branch"], "source": ["Finding source"]},
    {"date": ["Taufdatum"], "confirmed": ["Konfirmiert (Datum)", "Konfirmiert"], "zone": ["Zone"], "area": [],
     "ward": ["Gemeinde"], "source": ["Wie gefunden"]},
    {"date": ["Date of Baptism"], "confirmed": ["Date of Confirmation"], "zone": [],
     "area": ["Which companionship is filling out the form?"], "ward": ["Which Ward/Branch Are They in?"],
     "source": ["Finding Source, of friend baptized"]},
]


def baptism_template():
    return (["Baptism date", "Confirmation date", "Zone", "Area", "Ward or branch", "Finding source"],
            [["9/20/2026", "9/27/2026", "Frankfurt", "Bockenheim", "Frankfurt 1st", "Contacting in Public"]])


def baptism_layout(rows):
    for layout in BAPTISM_LAYOUTS:
        try:
            start, columns = find_heading_row(rows, layout["date"][:1])
        except FileProblem:
            continue
        return layout, start, columns
    raise FileProblem(plain("uploads.problem.missingColumns", columns="Baptism date / Taufdatum / Date of Baptism"))


def parse_baptisms(rows):
    """Counts only: one baptism per row in the week of the baptism, one confirmation in the week of the
    confirmation. Name, missionaries, birth date and the other personal columns are never read."""
    parsed = Parsed()
    layout, start, columns = baptism_layout(rows)
    totals = {}
    for number, row in enumerate(rows[start + 1:], start=start + 2):
        where = {part: clean(cell(row, columns, *layout[part]))[:120] if layout[part] else ""
                 for part in ("zone", "area", "ward", "source")}
        raw_date = cell(row, columns, *layout["date"])
        if not clean(raw_date) and not where["zone"] and not where["area"]:
            continue  # an empty row of the sheet
        parsed.rows_read += 1
        try:
            baptized = read_date(raw_date)
            confirmed = read_date(cell(row, columns, *layout["confirmed"])) if layout["confirmed"] else None
        except ValueError as error:
            parsed.problem(number, str(error))
            continue
        if not baptized:
            parsed.problem(number, plain("uploads.problem.noBaptismDate"))
            continue
        if not where["zone"] and not where["area"]:
            parsed.problem(number, plain("uploads.problem.noZoneOrArea"))
            continue
        for day, field in ((baptized, "baptisms"), (confirmed, "confirmations")):
            if not day:
                continue
            key = (week_of(day).isoformat(), where["zone"], where["area"], where["ward"], where["source"])
            total = totals.setdefault(key, {"sunday": key[0], "zone": where["zone"], "area": where["area"],
                                            "ward": where["ward"], "finding_source": where["source"],
                                            "baptisms": 0, "confirmations": 0})
            total[field] += 1
    parsed.records = list(totals.values())
    return parsed


# --------------------------------------------------------------------------------------------- 5. people (names read!)

# The headings of the People upload, by what they fill. The first heading of each is the template's; the others are
# the office's "Vollzogen" sheets and the "New Member Database Raw" form, which are read as they are.
PEOPLE_COLUMNS = {
    "first": ["First name", "First Name"], "last": ["Last name", "Last Name"], "full": ["Name"],
    "zone": ["Zone"], "area": ["Area", "Which companionship is filling out the form?"],
    "ward": ["Ward or branch", "Which Ward/Branch Are They in?", "Gemeinde"],
    "baptism_date": ["Baptism date", "Date of Baptism", "Taufdatum"],
    "confirmation_date": ["Confirmation date", "Date of Confirmation", "Konfirmiert (Datum)", "Konfirmiert"],
    "baptismal_date_extended": ["Baptismal date extended", "When was the Baptismal Date Extended", "Wann gesetzt"],
    "finding_source": ["Finding source", "Finding Source, of friend baptized", "Wie gefunden"],
    "date_of_birth": ["Date of birth", "Date of Birth"], "age_range": ["Age range", "Age Range"], "gender": ["Gender"],
    "marital_status": ["Marital status", "Maritial Status at time of Baptism"],
    "child_dependents": ["Child dependents", "Number of child dependents"],
    "living_situation": ["Living situation", "Living Situation"],
    "native_language": ["Native language", "1st Native Language", "Preferred Language"],
    "second_language": ["Second language", "Optional: 2nd Language in which a level of fluency is attained"],
    "mission_language_competency": ["Competency in German"],
    "country_of_origin": ["Country", "What country are they from?"],
    "conversion_success_notes": ["What went well in this person's conversion?"],
}
PEOPLE_TEXT = ("zone", "area", "ward", "finding_source", "age_range", "gender", "marital_status", "living_situation",
               "native_language", "second_language", "mission_language_competency", "country_of_origin",
               "conversion_success_notes")
PEOPLE_DATES = ("baptism_date", "confirmation_date", "baptismal_date_extended", "date_of_birth")


def people_template():
    return (["First name", "Last name", "Zone", "Area", "Ward or branch", "Baptism date", "Confirmation date",
             "Finding source", "Gender", "Age range"],
            [["Ana", "Example", "Frankfurt", "Bockenheim", "Frankfurt 1st", "9/20/2026", "9/27/2026", "Contacting in Public",
              "Female", "18-30"]])


def parse_people(rows):
    """New members with their details, one per row (a person with no baptism date in the file is left out: this upload
    is for people who were baptized). Names ARE read, they are what the upload is for. Rows are matched to portal
    areas and to people already stored afterwards (people_upload.py)."""
    parsed = Parsed()
    start = columns = None
    for heading in PEOPLE_COLUMNS["baptism_date"]:
        try:
            start, columns = find_heading_row(rows, [heading])
            break
        except FileProblem:
            continue
    if columns is None:
        raise FileProblem(plain("uploads.problem.missingColumns", columns="Baptism date / Taufdatum / Date of Baptism"))
    has_first = any(columns.get(heading_key(h)) is not None for h in PEOPLE_COLUMNS["first"])
    has_full = any(columns.get(heading_key(h)) is not None for h in PEOPLE_COLUMNS["full"])
    if not has_first and not has_full:
        raise FileProblem(plain("uploads.problem.missingColumns", columns="First name, Last name (or Name)"))
    for number, row in enumerate(rows[start + 1:], start=start + 2):
        values = {field: cell(row, columns, *headings) for field, headings in PEOPLE_COLUMNS.items()}
        first, last = clean(values["first"]), clean(values["last"])
        if not first and not last and clean(values["full"]):
            parts = clean(values["full"]).split(" ")
            first, last = (" ".join(parts[:-1]), parts[-1]) if len(parts) > 1 else (parts[0], "")
        if not first and not last:
            continue  # an empty row of the sheet
        parsed.rows_read += 1
        record = {"first": (first or last)[:100], "last": (last if first else "")[:100] or None}
        bad_baptism = None
        for field in PEOPLE_DATES:
            try:
                day = read_date(values[field])
            except ValueError as error:  # only the baptism date must be readable; "x" in a confirmation column is a mark
                day = None
                if field == "baptism_date":
                    bad_baptism = str(error)
            record[field] = day.isoformat() if day else None
        if bad_baptism:
            parsed.problem(number, bad_baptism)
            continue
        if not record["baptism_date"]:
            parsed.problem(number, plain("uploads.problem.noBaptismDate"))
            continue
        for field in PEOPLE_TEXT:
            record[field] = clean(values[field])[:200 if field != "conversion_success_notes" else 2000] or None
        children = clean(values["child_dependents"])
        try:
            record["child_dependents"] = int(float(children)) if children else None
        except ValueError:
            record["child_dependents"] = None
        parsed.records.append(record)
    return parsed
