"""Which kind of file was dropped on the Uploads page? Only the heading row is looked at (the same headings each reader
needs), so nothing is read or kept here. detect() returns the possible kinds, most specific first: one kind means the page
goes straight on; several kinds (a Vollzogen sheet also looks like a people list, Areas look like Geo data) mean the page
asks which one is meant, and never guesses.
"""
import data_files
import data_types
import historical_import
import roster_file
from data_files import FileProblem, find_heading_row, heading_key

# Kinds in the order the page lists them (the drop-down); the value is the one the readers use.
KINDS = ["roster", "historical", "people", "vollzogen", "baptisms", "areas", "geo", "finding", "zone-history", "rates"]
CHECKED_KINDS = [kind for kind in KINDS if kind not in ("roster", "historical")]  # kept waiting as rows (the other two as files)

HISTORICAL_COLUMNS = [historical_import.TIMESTAMP_COLUMN, historical_import.EMAIL_COLUMN,
                      historical_import.COMPANIONSHIP_COLUMN, historical_import.UNIT_COLUMN, historical_import.SUNDAY_COLUMN]


def has(rows, *required):
    """True when one of the first rows has every heading in `required`."""
    try:
        find_heading_row(rows, list(required))
        return True
    except FileProblem:
        return False


def has_any(rows, options, also=()):
    return any(has(rows, option, *also) for option in options)


def is_roster(rows):
    heads = {roster_file.HEADER_ALIASES.get(data_files.clean(h), data_files.clean(h)) for h in rows[0]}
    return all(column in heads for column in roster_file.REQUIRED_COLUMNS)


def is_historical(rows):
    return all(column in {data_files.clean(h) for h in rows[0]} for column in HISTORICAL_COLUMNS)


def is_finding(rows):
    return any(has(rows, person, *data_types.FINDING_SOURCE, data_types.FINDING_AREA[0]) for person in data_types.FINDING_PERSON)


def is_people(rows):
    names = data_types.PEOPLE_COLUMNS["first"] + data_types.PEOPLE_COLUMNS["full"]
    return any(has_any(rows, [date], also=()) and has_any(rows, [name]) for date in data_types.PEOPLE_COLUMNS["baptism_date"] for name in names)


def is_vollzogen(rows):
    return any(has(rows, name, date) for name in data_types.VOLLZOGEN_COLUMNS["name"] for date in data_types.VOLLZOGEN_COLUMNS["baptism_date"])


def is_baptisms(rows):
    return any(has(rows, layout["date"][0]) for layout in data_types.BAPTISM_LAYOUTS)


def geo_only_headings(rows):
    """True when the file has a column only Geo data has (an urban-centre class, density, households)."""
    area_names = {heading_key(h) for names in data_types.AREA_FIELDS.values() for h in names}
    geo_names = {heading_key(h) for names in data_types.GEO_FIELDS.values() for h in names} - area_names
    return any(heading_key(cell) in geo_names for row in rows[:10] for cell in row)


def detect(filename, data):
    """The possible kinds of a file, as a list of KINDS (empty: not recognised). Raises FileProblem for a file that cannot
    be read (wrong type, empty)."""
    rows = data_files.read_table(filename, data)
    strong = [kind for kind, test in (("roster", is_roster), ("historical", is_historical), ("finding", is_finding),
                                      ("zone-history", lambda r: has(r, "Sunday", "Zone")),
                                      ("rates", lambda r: has(r, "Date", "Zone"))) if test(rows)]
    if strong:
        return strong
    if data_types.geo_table_starts(rows):
        return ["geo"]
    found = [kind for kind, test in (("people", is_people), ("vollzogen", is_vollzogen), ("baptisms", is_baptisms)) if test(rows)]
    if found:
        return found
    if has(rows, "Area"):
        return ["areas", "geo"] if geo_only_headings(rows) else ["areas"]
    return []
