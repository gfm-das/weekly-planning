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


ARCHIVE_HEADINGS = ["Date", "Mission", "Zone", "Area", "Source", "Referral Number", "Referrals Received",
                    "Referrals Contacted", "Friends Made", "Lessons Taught", "Church Attendance", "Baptismal Date",
                    "Baptisms", "BOM Delivered", "With Member", "Extra 2", "Follow-up Lessons", "Extra 4"]


def archive_file(old_zone, old_area, portal_area):
    return csv_bytes(ARCHIVE_HEADINGS, [
        ["3/4/2024", "Frankfurt", old_zone, old_area, "Lead-Ads", "11033", 1, 1, 0, 0, 0, 0, 0, "", "", "", "", ""],
        ["3/4/2024", "Frankfurt", old_zone, old_area, "Lead-Ads", "11034", 1, "", 1, 1, 0, 0, 0, "", "", "", "", ""],
        ["3/4/2024", "Frankfurt", old_zone, old_area, "BM Bestellung", "11035", 1, "", "", "", "", "", "", 1, "", "", "", ""],
        ["9/28/2026", "Frankfurt", "", portal_area, "FindeChristus Referrals", "", 4, "", "", "", "", "", "", "", "", "", "", ""],
        ["9/28/2026", "", "Mission", "", "", "", 76, "", "", "", "", "", "", "", "", "", "", ""],
    ])


def rates_file(zone):
    """Dated like the owner's rate archive: Mondays, then Sundays from August 2026 on."""
    return csv_bytes(["Date", "Zone", "Teaching Rate", "Contact Rate"], [
        ["7/1/2024", "Mission", "0.135", ""],  # a Monday report: the week of 17-23 Jun 2024
        ["7/27/2026", "Mission", "0.27", "0.98"],  # Monday 27 Jul: the week of 13-19 Jul
        ["8/2/2026", "Mission", "0.28", "0.97"],  # Sunday 2 Aug is the report of Monday 3 Aug: 20-26 Jul
        ["9/27/2026", "Mission", "26.00%", "99.30%"],  # Sunday 27 Sep = the 28 Sep report: 14-20 Sep
        ["9/27/2026", zone, "41.00%", "98.30%"],
        ["1/11/2026", zone, "0.21", "1"],  # Sunday 11 and Monday 12 Jan show the same week (29 Dec - 4 Jan):
        ["1/12/2026", zone, "0.22", "1"],  # the later report is used and the check names both dates
        ["4/4/2026", "Mission", "0.20", "0.99"],  # a Saturday report shows the week that just ended (23-29 Mar)
        ["12/9/2024", zone, "#DIV/0!", ""],  # no rate that week: left out
    ])


def vollzogen_file(zone):
    """The office's Vollzogen sheet: a title row first, then the headings, then rows with names (never read)."""
    return xlsx_bytes([
        ["Taufen", None, None, None, None, None, None, None, None, None, "Mission Office Info", None],
        ["Wie gefunden", "Name", "Wann gesetzt", "Taufdatum", "Mitarbeiter", "Gemeinde", "Pfahl", "Zone",
         "Konfirmiert (Datum)", "Country", "Gender", "Preferred Language"],
        ["Contacting in Public", MADE_UP_NAMES[0], "8/30/2026", "9/20/2026", MADE_UP_NAMES[3], "Frankfurt 1st",
         "Frankfurt", zone, "9/27/2026", "Testland", "F", "German"],
        ["Contacting in Public", MADE_UP_NAMES[1], "8/30/2026", "9/19/2026", MADE_UP_NAMES[4], "Frankfurt 1st",
         "Frankfurt", zone, "", "Testland", "M", "German"],
        [None] * 12,
        ["Member", MADE_UP_NAMES[2], "", "", "", "", "", zone, "", "", "", ""],  # no baptism date: a problem
    ])


def new_member_file(area):
    """The New Member Database Raw form export."""
    return xlsx_bytes([
        ["Timestamp", "Stake", "Which companionship is filling out the form?", "Which Ward/Branch Are They in?",
         "First Name", "Last Name", "When was the Baptismal Date Extended", "Date of Baptism", "Date of Confirmation",
         "Finding Source, of friend baptized", "Date of Birth", "Email Address"],
        ["9/28/2026 10:00:00", "Frankfurt", area, "Frankfurt 1st", "Testa", "Beispiel", "8/1/2026", "9/26/2026",
         "9/27/2026", "Headquarters Paid Ad", "1/1/1990", "made-up@example.invalid"],
    ])


def area_file(rows, extra_heading="Chapel nearby"):
    """rows: [(zone, district, area, population, km2, urban, assignment, extra), ...]"""
    return csv_bytes(["Zone", "District", "Area", "Population", "Size (km2)", "Urban type", "Assignment type",
                      "Density (people per km2)", extra_heading],
                     [[z, d, a, p, s, u, t, "", e] for z, d, a, p, s, u, t, e in rows])
