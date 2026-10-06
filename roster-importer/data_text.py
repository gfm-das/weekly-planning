"""The English texts of DA Management > Data uploads.

Every text a person sees on the upload pages comes from here, each under a key (uploads.*) in the style of the
portal's translation catalog. {name} marks a value filled in on the page.

Translation (round 6): DA Management loads the portal's i18n.js, which translates these English texts on the page.
They are in the portal's catalogs (portal/i18n/en.json and the 13 other languages), under uploads.* or, where the portal
already had the same English text ('Cancel', 'Area', 'Zone'), under the portal's own key: i18n.js finds a key by its
English text and the first key keeps it. A new text here needs its key in the catalogs too
(docs/handoff/round6/i18n.md section 8; tests/test_data_files.py checks it).
"""
from html import escape

import settings

TEXT = {
    # The Data uploads page
    "uploads.hub.step": "Data uploads",
    "uploads.hub.title": "Put in the numbers the portal does not collect",
    "uploads.hub.intro": "Area data for peer groups, the Church's finding export, and the history of the zones going back years. Each upload is checked first, then applied as one entry in Import history, where it can be undone.",
    "uploads.hub.privacy": "Names are never stored. Uploaded files are read and then let go; only the numbers are kept.",
    "uploads.hub.names": "Remembered names",
    "uploads.hub.open": "Open",
    "uploads.hub.last": "Last upload: {date} · {file}",
    "uploads.hub.none": "Nothing uploaded yet.",

    # The six uploads
    "uploads.areas.title": "Area data",
    "uploads.areas.about": "Population, size in km2, urban type and assignment type of each area, plus any extra attributes you want. Peer groups compare areas that are alike. Density is worked out for you.",
    "uploads.areas.columns": "Columns: Zone, District, Area, Population, Size (km2), Urban type, Assignment type. Every other column becomes an extra attribute (for example Chapel nearby). The template lists every area with what is saved today.",
    "uploads.areas.merge": "An empty cell keeps what is saved. To clear a value, use the area table.",
    "uploads.finding.title": "Finding export",
    "uploads.finding.about": "The Church's finding export (Mission Finding Detail). It gives the finding sources per area and week: new people found, referrals, contact attempts, lessons and baptismal dates.",
    "uploads.finding.columns": "Columns of the export: Person Id, Finding Category, Finding Source, Latest Teaching Area Name, Latest District Name, Latest Zone Name and the First ... Date columns. Names in the export are not read.",
    "uploads.finding.merge": "Each person is recognised by a code made from the Church person id, so uploading a newer export adds new people and updates the dates of people already stored. Nobody is counted twice.",
    "uploads.zoneHistory.title": "Zone history",
    "uploads.zoneHistory.about": "Goals and results of each zone per week, going back as far as your sheets go (the Data for Data Studio sheet).",
    "uploads.zoneHistory.columns": "Columns: Sunday, Zone, then a Goal and an Actual column for each key indicator, Follow-up lessons Actual, First Time Attendance and Companionships. Rows for the whole mission are left out: the mission is added up from the zones. A Goal is the goal set that Sunday for the next week, as in the sheet; each week is measured against the goal set the week before.",
    "uploads.zoneHistory.merge": "For a zone and week the portal already has weekly plans for, the portal's own numbers are used and the uploaded row is not counted. A newer upload of the same weeks replaces the older one.",
    "uploads.referralArchive.title": "Referral archive",
    "uploads.referralArchive.about": "The FindeChristus referral archive since 2022 (the FC Data Archives sheet): referrals per week, area and source, and how far they came.",
    "uploads.referralArchive.columns": "Columns: Date, Zone, Area, Source, Referrals Received, Referrals Contacted, Friends Made, Lessons Taught, Church Attendance, Baptismal Date, Baptisms, BOM Delivered, With Member, Follow-up Lessons. Referral numbers are not read.",
    "uploads.referralArchive.merge": "A newer upload of the same weeks replaces the older one. For weeks the finding export has, the FindeChristus referral counts come from the finding export.",
    "uploads.rates.title": "Teaching and contact rates",
    "uploads.rates.about": "The teaching rate and contact rate of each zone and of the mission per week (the Teaching_Contact Rate Archive sheet).",
    "uploads.rates.columns": "Columns: Date, Zone (Mission for the whole mission), Teaching Rate, Contact Rate. 26% and 0.26 are both read as 26 %.",
    "uploads.rates.merge": "A newer upload of the same weeks replaces the older one.",
    "uploads.baptisms.title": "Baptism history",
    "uploads.baptisms.about": "Baptisms and confirmations per week, zone or area, ward and finding source, from the Vollzogen sheets or the New Member Database. Only the counts are kept.",
    "uploads.baptisms.columns": "Columns: Baptism date, Confirmation date, Zone, Area, Ward or branch, Finding source. The Vollzogen sheet (Taufdatum, Zone, Gemeinde, Wie gefunden) and the New Member Database Raw sheet are read as they are. Names and other personal columns are not read.",
    "uploads.baptisms.merge": "A newer upload of the same weeks replaces the older one, so upload one sheet for a stretch of weeks, not two.",

    # Import history names of the uploads
    "uploads.kind.areas": "Area data",
    "uploads.kind.finding": "Finding export",
    "uploads.kind.zoneHistory": "Zone history",
    "uploads.kind.referralArchive": "Referral archive",
    "uploads.kind.rates": "Rates",
    "uploads.kind.baptisms": "Baptism history",
    "uploads.status.applied": "Applied",
    "uploads.status.undone": "Undone",

    # Step 1: upload
    "uploads.page.step1": "1 · Upload",
    "uploads.page.template": "Download the template",
    "uploads.page.file": "CSV or XLSX file",
    "uploads.page.check": "Check the file",
    "uploads.page.how": "How it works",
    "uploads.page.weeks": "Weeks run Monday to Sunday and are named by their Sunday.",
    "uploads.page.reportWeek": "A report counts for the week it shows. A report dated Sunday, Monday or Tuesday is for the Monday meeting and shows the week before last: Sunday 27 and Monday 28 Sep show Monday 14 to Sunday 20 Sep. A report dated Wednesday to Saturday shows the week that ended the Sunday before.",
    "uploads.page.oneReport": "Each week has one report. If two dates of the file show the same week, the later report is used and the check says so.",
    "uploads.page.never": "Nothing is saved until you apply the checked upload. Every applied upload is listed in Import history and can be undone there.",
    "uploads.page.recent": "Uploads so far",
    "uploads.page.back": "Back to Data uploads",
    "uploads.page.waiting": "A checked file is waiting: {file}.",
    "uploads.page.openCheck": "Open the check",
    "uploads.page.unknown": "This upload page does not exist.",

    # Step 2: check
    "uploads.review.step": "2 · Check",
    "uploads.review.rowsRead": "rows read",
    "uploads.review.rowsToStore": "rows to store",
    "uploads.review.leftOut": "left out on purpose",
    "uploads.review.problems": "problems",
    "uploads.review.namesToMatch": "names to match",
    "uploads.review.people": "People: {new} new, {changed} with new dates or a new area, {same} already stored as they are.",
    "uploads.review.foundBetween": "Found between {first} and {last}.",
    # Archived (migration 038, Oct 2026): no longer shown on the check of a finding export; kept for its translations.
    "uploads.review.findechristus": "FindeChristus referrals (Media, without Facebook - Personal Profile): {count}.",
    "uploads.review.weeks": "{count} weeks, from {first} to {last}.",
    "uploads.review.weeksReplaced": "{count} of these weeks were uploaded before. This upload replaces them; the older upload stays in Import history.",
    "uploads.review.replacedFrom": "From {file} ({date}): {weeks} weeks, {rows} rows stop counting.",
    "uploads.review.replacedMissing": "{rows} of these rows are for a zone or area this file does not have in that week, so they no longer show on the dashboards. To keep them, put them into this file too.",
    "uploads.review.olderFile": "This file looks older than what is stored: its newest finding date is {file_last}, the stored ones go up to {stored_last}. People whose area or source differ would get the older one back. Dates that are stored already are kept.",
    "uploads.review.olderConfirm": "I know this file is older and still want to apply it.",
    "uploads.review.olderConfirmFirst": "This file is older than what is stored. Tick that you still want to apply it.",
    "uploads.review.datesKept": "A date the file leaves empty keeps the date that is stored.",
    "uploads.review.portalWins": "The portal already has weekly plans for {count} of these zone weeks. For those, the portal's own numbers are used.",
    "uploads.review.areasBlank": "Empty cells keep what is saved; only filled cells change anything.",
    "uploads.review.problemTitle": "Rows with a problem",
    "uploads.review.problemHelp": "These rows are left out, or the cell is left empty. Everything else can be applied. To include them, correct the file and check it again.",
    "uploads.review.moreProblems": "And {count} more.",
    "uploads.review.confirm": "I checked this upload.",
    "uploads.review.apply": "Apply",
    "uploads.review.cancel": "Cancel",
    "uploads.review.namesLeft": "Some names still need a match. Choose them above, then apply.",
    "uploads.review.nothing": "There is nothing in this file to store.",
    "uploads.review.confirmFirst": "Tick that you checked the upload, then apply.",
    "uploads.review.notRead": "This file could not be read.",
    "uploads.review.notSaved": "Nothing was saved.",
    "uploads.review.gone": "There is no checked upload waiting. Upload the file again.",
    "uploads.review.nothingNew": "Nothing new: everything in this file is already stored like this.",
    "uploads.review.saved": "Saved. It is in Import history, where it can be undone.",

    # Step 3: names
    "uploads.names.step": "3 · Match names",
    "uploads.names.title": "Names that are not in the portal",
    "uploads.names.help": "Choose the portal zone or area each name means. An old zone or area that is no longer in the portal can be kept as a historical name. Your choices are remembered for later uploads.",
    "uploads.names.helpAreas": "Choose the portal area each name means, or leave its rows out. Your choices are remembered for later uploads.",
    "uploads.names.zone": "Zone",
    "uploads.names.area": "Area",
    "uploads.names.inZone": "In the file under: {zones}",
    "uploads.names.choose": "Choose…",
    "uploads.names.keepHistorical": "Keep as a historical name",
    "uploads.names.leaveOut": "Leave these rows out",
    "uploads.names.keepRest": "Keep every name I did not choose as a historical name.",
    "uploads.names.leaveRest": "Leave out the rows of every name I did not choose.",
    "uploads.names.old": "(old)",
    "uploads.names.oldBadge": "old",
    "uploads.names.save": "Save choices",
    "uploads.names.saved": "{count} choices saved.",
    "uploads.names.historical": "Historical name",
    "uploads.names.savedTitle": "Remembered names",
    "uploads.names.savedHelp": "Names from uploaded files and the portal zone or area they mean. Forget a choice to be asked again on the next upload; data already applied keeps its match.",
    "uploads.names.noneSaved": "No names remembered yet.",
    "uploads.names.forget": "Forget",
    "uploads.names.forgotten": "The choice is forgotten. The next upload asks again.",

    # Area table
    "uploads.areas.editTable": "Edit the area table",
    "uploads.areas.tableTitle": "Area table",
    "uploads.areas.tableHelp": "Type the data of each area and save. Empty boxes are fine. Density is worked out from population and km2. Each save is listed in Import history and can be undone there.",
    "uploads.areas.extraHelp": "Extra attributes: name: value, separated by semicolons, for example Chapel: yes; Languages: German, Arabic.",
    "uploads.areas.save": "Save the table",
    "uploads.areas.tableSaved": "Area table saved. It is in Import history, where it can be undone.",
    "uploads.areas.tableSame": "Nothing changed.",
    "uploads.areas.tableFile": "Area table - edited in DA Management",
    "uploads.areas.incomplete": "The table was not sent completely. Reload the page and try again.",
    "uploads.areas.outside": "One of these areas is outside your stewardship. Reload the page and try again.",
    "uploads.areas.extraFormat": "'{text}' needs a name and a value, like Chapel: yes.",

    # Column headings on the pages
    "uploads.col.zone": "Zone",
    "uploads.col.district": "District",
    "uploads.col.area": "Area",
    "uploads.col.population": "Population",
    "uploads.col.size": "Size (km2)",
    "uploads.col.density": "People per km2",
    "uploads.col.urban": "Urban type",
    "uploads.col.assignment": "Assignment type",
    "uploads.col.extra": "Extra attributes",
    "uploads.col.found": "Found",
    "uploads.col.category": "Finding category",
    "uploads.col.source": "Source",
    "uploads.col.firstLesson": "First lesson",
    "uploads.col.week": "Week (Sunday)",
    "uploads.col.newPeopleGoal": "New People Being Taught: goal for next week",
    "uploads.col.newPeople": "New People Being Taught",
    "uploads.col.sacrament": "People Being Taught Who Attend Sacrament Meeting",
    "uploads.col.baptized": "People Who Are Baptized and Confirmed",
    "uploads.col.referrals": "Referrals received",
    "uploads.col.teachingRate": "Teaching rate",
    "uploads.col.contactRate": "Contact rate",
    "uploads.col.ward": "Ward or branch",
    "uploads.col.baptisms": "Baptisms",
    "uploads.col.confirmations": "Confirmations",
    "uploads.col.file": "File",
    "uploads.col.when": f"When ({settings.TIME_ZONE_NAME})",
    "uploads.col.by": "By",
    "uploads.col.status": "Status",
    "uploads.col.row": "Row",
    "uploads.col.problem": "Problem",
    "uploads.col.rows": "Rows",
    "uploads.col.level": "Kind",
    "uploads.col.nameInFile": "Name in the file",
    "uploads.col.portal": "In the portal",

    # Finding export: the person code
    "uploads.finding.noSecret": "Finding uploads need the secret for person codes (PERSON_KEY_SECRET), and this server does not have it yet. Ask the person who runs the server to add it; the other uploads work already.",
    "uploads.finding.keyChanged": "The secret for person codes has changed since the last finding upload, so everyone would be counted twice. Ask the person who runs the server to put the earlier PERSON_KEY_SECRET back.",
    "uploads.undo.newerFirst": "Undo the newer finding upload first: {files}.",

    # Problems in a file
    "uploads.problem.noFile": "Choose a file first.",
    "uploads.problem.wrongType": "Choose a CSV or XLSX file.",
    "uploads.problem.empty": "The file is empty.",
    "uploads.problem.xlsx": "This XLSX file cannot be opened. Save it again from the spreadsheet and try once more.",
    "uploads.problem.encoding": "This CSV file cannot be read. Save it as CSV UTF-8 and try again.",
    "uploads.problem.missingColumns": "These columns were not found: {columns}. Download the template to see the headings.",
    "uploads.problem.noIndicators": "No key indicator columns were found. Download the template to see the headings.",
    "uploads.problem.notDate": "'{value}' is not a date",
    "uploads.problem.notNumber": "'{value}' is not a number",
    "uploads.problem.notWhole": "'{value}' is not a whole number of 0 or more",
    "uploads.problem.belowZero": "'{value}' is below 0",
    "uploads.problem.where": "{where}: {problem}",
    "uploads.problem.sizeZero": "the size must be more than 0 km2",
    "uploads.problem.noArea": "No area name.",
    "uploads.problem.noDate": "No date.",
    "uploads.problem.noZoneOrArea": "No zone or area.",
    "uploads.problem.noPerson": "No person id: this row is left out.",
    "uploads.problem.personTwice": "This person is in the file twice: the first row is used.",
    "uploads.problem.noSource": "No finding category or source: this row is left out.",
    "uploads.problem.noFoundDate": "No finding date: this row is left out.",
    "uploads.problem.noBaptismDate": "No baptism date: this row is left out.",
    "uploads.problem.twiceLastWins": "{name} is in the file twice: the last row is used.",
    "uploads.problem.weekTwice": "{name} has this week twice: the first row is used.",
    "uploads.problem.twoReports": "The reports of {older} and {newer} both show the week ending {week}. Only the report of {newer} is used.",
}


def plain(key, **values):
    """The English text of a key with its {values} filled in, as plain text (for messages and errors)."""
    text = TEXT[key]
    for name, value in values.items():
        text = text.replace("{" + name + "}", str(value))
    return text


def t(key, **values):
    """The same text made safe to put into a page (the text and every value are HTML-escaped)."""
    text = escape(TEXT[key])
    for name, value in values.items():
        text = text.replace("{" + name + "}", escape(str(value)))
    return text
