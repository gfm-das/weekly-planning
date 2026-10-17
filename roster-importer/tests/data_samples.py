"""Small made-up sample files with the same columns as the owner's real files (never the real files: those hold
personal data). Used by test_data_files.py and test_data_uploads.py.

The names and person ids below are invented; the tests check that none of them is ever stored."""
import csv
import io

from openpyxl import Workbook

MADE_UP_NAMES = ["Testa Beispiel", "Probe Person", "Mira Musterfrau", "Elder Sample", "Sister Example"]
MADE_UP_IDS = ["900000001", "900000002", "900000003", "900000004", "900000005"]

# The Church's MissionFindingDetail export: 31 columns, several of them twice.
FINDING_HEADINGS = [
    "Blank", "Confirmation Date", "Event Date Selected", "Event Date Selected", "Finding Category (copy)",
    "Finding Source", "Finding Source", "First Baptism Goal Date Set", "First Contact Attempt Event Date",
    "First Finding Event Date (truncated)", "First Finding Event Date (truncated)", "First Lesson Date",
    "First New Person Being Taught Date", "First Referral Event Date", "First Sacrament Date",
    "First Successful Contact Attempt Event Date", "Full Name", "Full Name", "Latest Baptism Goal Date Set",
    "Latest District Name", "Latest District Name", "Latest Sacrament Date", "Latest Teaching Area Name",
    "Latest Teaching Area Name", "Latest Zone Name", "Latest Zone Name", "Person Id",
    "Sacrament Attendance Event Count", "Second Lesson Date", "Sort", "Event Type Date"]


def csv_bytes(headings, rows):
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(headings)
    writer.writerows(rows)
    return out.getvalue().encode("utf-8")


def xlsx_bytes(rows):
    book = Workbook()
    sheet = book.active
    for row in rows:
        sheet.append(row)
    out = io.BytesIO()
    book.save(out)
    return out.getvalue()


def finding_row(person_id, name, category, source, found, area, district, zone, lesson="", taught="", referral="",
                contact="", reached="", baptismal="", sacrament="", confirmed="", second=""):
    """One export row. Dates like the export: 9/14/2026, times as 9/14/2026 10:15:00 AM."""
    return ["", confirmed, found, found, category, source, source, baptismal, contact, found, found, lesson, taught,
            referral, sacrament, reached, name, name, baptismal, district, district, "", area, area, zone, zone,
            person_id, "0", second, "2026257", "First Finding Event Date"]


def finding_file(areas, extra_rows=()):
    """A finding export with five made-up people in the given portal areas [(zone, district, area), ...].
    People 1 and 2 are FindeChristus referrals (Media, not a personal profile), 3 is a Facebook personal profile,
    4 is found by missionaries, 5 by a member. Person 1 is listed twice (the second row must be ignored)."""
    a, b = areas[0], areas[1 % len(areas)]
    rows = [
        finding_row(MADE_UP_IDS[0], MADE_UP_NAMES[0], "Media", "Headquarters Paid Ad", "9/14/2026", a[2], a[1], a[0],
                    lesson="9/16/2026", referral="9/14/2026 10:15:00 AM", contact="9/14/2026 11:00:00 AM",
                    reached="9/15/2026 9:30:00 AM"),
        finding_row(MADE_UP_IDS[1], MADE_UP_NAMES[1], "Media", "Facebook - Mission Ad", "9/20/2026", a[2], a[1], a[0],
                    referral="9/20/2026 8:00:00 PM"),
        finding_row(MADE_UP_IDS[2], MADE_UP_NAMES[2], "Media", "Facebook - Personal Profile", "9/21/2026", b[2], b[1], b[0]),
        finding_row(MADE_UP_IDS[3], MADE_UP_NAMES[3], "Missionary", "Contacting in Public", "9/22/2026", b[2], b[1], b[0],
                    lesson="9/22/2026", taught="9/27/2026", baptismal="9/27/2026"),
        finding_row(MADE_UP_IDS[4], MADE_UP_NAMES[4], "Member", "Member", "9/23/2026", b[2], b[1], b[0],
                    sacrament="9/27/2026 12:00:00 AM"),
        finding_row(MADE_UP_IDS[0], MADE_UP_NAMES[0], "Media", "Headquarters Paid Ad", "9/14/2026", b[2], b[1], b[0]),
        finding_row("", "No Id Person", "Media", "Headquarters Paid Ad", "9/14/2026", a[2], a[1], a[0]),
    ] + list(extra_rows)
    return csv_bytes(FINDING_HEADINGS, rows)


# The "Data for Data Studio" sheet (weekly zone history); the per-companionship columns at the end are ignored.
ZONE_HISTORY_HEADINGS = [
    "Sunday", "Zone", "Friends Found Goal", "Friends Found Actual", "Lessons with a Mitbelehr Goal",
    "Lessons with a Mitbelehr Actual", "Attendance at Church Goal", "Attendance at Church Actual", "Baptismal Date Goal",
    "Baptismal Date Actual", "Baptism Goal", "Baptism Actual", "New Member Attendance at Church Goal",
    "New Member Attendance at Church Actual", "Follow-up lessons Actual", "First Time Attendance",
    "First Time Week Attendance", "Companionships", "FFper Goal", "FFper"]


def zone_history_file(rows):
    """rows: [(sunday text, zone, friends found goal, friends found actual), ...]; other columns get fixed numbers."""
    return csv_bytes(ZONE_HISTORY_HEADINGS, [[s, z, g, a, 29, 18, 44, 26, 7, 5, 0, 1, 13, 7, 0, 2, 1, 12, "1.833", "1.5"]
                                             for s, z, g, a in rows])


VOLLZOGEN_HEADINGS = ["Wie gefunden", "Name", "Wann gesetzt", "Taufdatum", "Mitarbeiter", "Gemeinde", "Pfahl", "Zone",
                      "Konfirmiert", "Country", "Gender", "Preferred Language"]
# Made-up people for the Vollzogen list. Every one of them is invented; none is a real person.
VOLLZOGEN_PEOPLE = ["Testa Beispiel", "Probe Person", "Mira Musterfrau", "Alma Erfunden", "Nora Nirgends", "Ivo Imaginär",
                    "Lena Leerzeile", "Paul Platzhalter", "Dora Doppelt", "Fritz Fern"]


def vollzogen_rows(zone="Frankfurt"):
    """The rows of the office's Vollzogen sheet with the real file's shape (title row first, headings on row 2, a
    "Mission Office Info" block at the end) and its hand-typed mess: English dates with ordinals, German dates, ISO dates,
    spreadsheet dates, an X in Konfirmiert, blank lines, a placeholder, a row without a baptism date, a date that is not
    one, a year typed wrong, and one person twice."""
    from datetime import datetime
    common = ["Frankfurt 1st", "Frankfurt", zone]
    return [
        ["Taufen"] + [None] * 8 + ["Mission Office Info", None, None][:3],
        VOLLZOGEN_HEADINGS,
        ["Contacting in Public", VOLLZOGEN_PEOPLE[0], "Dec. 1st. 2025", "Dec. 15th. 2025", "Elder Sample, Sister Example", *common, "X", "Testland", "F", "German"],
        ["Member", VOLLZOGEN_PEOPLE[1], "15.11.2025", "Jan. 4th, 2026", "Elder Sample", *common, datetime(2026, 1, 11), "Testland", "M", "English"],
        ["Media", VOLLZOGEN_PEOPLE[2], datetime(2026, 1, 20), datetime(2026, 2, 1), "Sister Demo", *common, "x", "Otherland", "F", "Spanish"],
        ["Street", VOLLZOGEN_PEOPLE[3], "2026-02-02", "2026-03-07", "Elder Sample", *common, None, "Testland", "F", "German"],
        ["Street", VOLLZOGEN_PEOPLE[4], "", "7. März 2026", "Elder Example", *common, "nein", "Testland", "M", "German"],
        ["Street", VOLLZOGEN_PEOPLE[5], "", 46100, "", *common, "", "", "", ""],
        [None] * 12,
        ["Member", "TBD", "", "", "", "", "", zone, "", "", "", ""],
        ["Member", VOLLZOGEN_PEOPLE[6], "", "", "Elder Sample", *common, "", "", "", ""],      # no baptism date
        ["Member", VOLLZOGEN_PEOPLE[7], "", "sometime in spring", "", *common, "", "", "", ""],  # not a date
        ["Member", VOLLZOGEN_PEOPLE[9], "", "2062-01-01", "", *common, "", "", "", ""],      # the year typed wrong
        ["Member", VOLLZOGEN_PEOPLE[8], "", "Dec. 15th. 2025", "", *common, "", "", "", ""],
        ["Member", VOLLZOGEN_PEOPLE[8], "", "Dec. 15th. 2025", "", *common, "", "", "", ""],  # the same person twice
        [None, None, None, "Dec. 15th. 2025", None, None, None, None, None, None, None, None],  # a date but nobody's name
    ]


def vollzogen_sheet(zone="Frankfurt"):
    """The sheet as an XLSX file ("Vollzogen 2026")."""
    return xlsx_bytes(vollzogen_rows(zone))


def vollzogen_csv(zone="Frankfurt"):
    """The same sheet as a CSV file (dates as the sheet shows them)."""
    return csv_bytes(*vollzogen_rows(zone)[1:2], [[("" if v is None else v) for v in row] for row in vollzogen_rows(zone)[2:]])


def new_member_file(area):
    """The New Member Database Raw form export."""
    return xlsx_bytes([
        ["Timestamp", "Stake", "Which companionship is filling out the form?", "Which Ward/Branch Are They in?",
         "First Name", "Last Name", "When was the Baptismal Date Extended", "Date of Baptism", "Date of Confirmation",
         "Finding Source, of friend baptized", "Date of Birth", "Email Address"],
        ["9/28/2026 10:00:00", "Frankfurt", area, "Frankfurt 1st", "Testa", "Beispiel", "8/1/2026", "9/26/2026",
         "9/27/2026", "Headquarters Paid Ad", "1/1/1990", "made-up@example.invalid"],
    ])


def geo_flat_file(rows, extra_heading="Chapel nearby"):
    """A flat Geo data file (one row per area). rows: [(zone, district, area, population, km2, urban, assignment, extra), ...]"""
    return csv_bytes(["Zone", "District", "Area", "Population", "Size (km2)", "Urban type", "Assignment type",
                      "Density (people per km2)", extra_heading],
                     [[z, d, a, p, s, u, t, "", e] for z, d, a, p, s, u, t, e in rows])

# The owner's "Areas Geo Data" file: three tables side by side (Zone / District / Area), a blank column between them. The
# headings are the real file's (including its spelling "CLuster" and the class codes), the places and numbers are made up.
GEO_BLOCK = ["{name}", "Population", "Area", "Population Density", "Urban Centre(130)", "Dense Urban CLuster (223)",
             "Semi dense Urban cluster(222)", "Suburban/peri-urban grid cell (221)", "Very low density rural grid cell(311)",
             "Low density rural grid cell(312)", "Area Type"]
GEO_ZONES = [
    ["Alpha Zone", 4414139, 9036.03, 488.5, 1486250, 1285607, 201129, 833013, 26588, 221659, "City"],
    ["Beta Zone", "6.859.500", "24.298,15", "282,31", 1875543, 1493908, 394163, 1366582, 73520, 690059, "City"],
    ["Mission", 22744412, 99999.99, 227.5, 1, 2, 3, 4, 5, 6, "City"],
]
GEO_DISTRICTS = [
    ["District One", 1200000, 300.5, 3993.34, 700000, 300000, 80000, 90000, 10000, 20000, "City"],
    ["District Two", "850.000", 410.25, 2072.0, 100000, 200000, 150000, 250000, 50000, 100000, "Town"],
    ["Offstrict", 1200000, 300.5, 3993.34, 700000, 300000, 80000, 90000, 10000, 20000, "City"],  # a stand-in, same figures as One
    ["Ghost District", 1111, 2.5, 444.4, 1, 1, 1, 1, 1, 1, "Town"],  # not a district of a portal
]
GEO_AREAS = [
    ["Testville", 250000, 120.5, 2074.7, 100000, 80000, 20000, 30000, 10000, 10000, "City"],
    ["Beispielstadt", 60000, 80, 750, 10000, 10000, 10000, 10000, 10000, 10000, "Town"],
    ["Media Elders", 250000, 120.5, 2074.7, 100000, 80000, 20000, 30000, 10000, 10000, "City"],  # a stand-in copy of Testville
    ["Office Sisters", 250000, 120.5, 2074.7, 100000, 80000, 20000, 30000, 10000, 10000, "City"],
    ["Copy Town", 60000, 80, 750, 10000, 10000, 10000, 10000, 10000, 10000, "Town"],  # the same figures as Beispielstadt
    ["APs", 1, 1, 1, 1, 1, 1, 1, 1, 1, "City"],
    ["Emptyville", "", "", "", "", "", "", "", "", "", "Town"],
    ["Nord Dorf", "15.000", "12,5", 1200, 1000, 2000, 3000, 4000, 2500, 2500, "Town"],
]


def geo_tables_file(zones=None, districts=None, areas=None, as_xlsx=False):
    """The three tables side by side as the owner's file has them: one heading row, then rows as long as the longest table."""
    zones = GEO_ZONES if zones is None else zones
    districts = GEO_DISTRICTS if districts is None else districts
    areas = GEO_AREAS if areas is None else areas
    blank = [""] * 11
    headings = []
    for position, level in enumerate(("Zone", "District", "Area")):
        headings += ([""] if position else []) + [GEO_BLOCK[0].format(name=level)] + GEO_BLOCK[1:]
    rows = []
    for index in range(max(len(zones), len(districts), len(areas))):
        rows.append((zones[index] if index < len(zones) else blank) + [""] + (districts[index] if index < len(districts) else blank)
                    + [""] + (areas[index] if index < len(areas) else blank))
    return xlsx_bytes([headings, *rows]) if as_xlsx else csv_bytes(headings, rows)


GEO_HEADINGS = ["Zone", "District", "Area", "Population", "Size (km2)", "Density (people per km2)", "Households", "Source",
                "Data date", "Chapel nearby"]


def geo_file(rows, headings=GEO_HEADINGS):
    """rows: [(zone, district, area, population, km2, density, households, source, data date, extra), ...]"""
    return csv_bytes(headings, [list(r) for r in rows])
