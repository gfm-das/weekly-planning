"""Reading uploaded CSV and XLSX files, and the small helpers every upload type needs.

Nothing here touches the database or the disk: a file is read from the bytes of the upload, so the file itself
is never saved (the owner's rule for files with personal data).
"""
import csv
import io
import re
from datetime import date, datetime, timedelta

from openpyxl import load_workbook

from data_text import plain


class FileProblem(ValueError):
    """The file cannot be read at all (wrong type, empty, no heading row). Shown to the manager as it is."""


def clean(value):
    """Text without extra spaces. None and empty cells become ''."""
    return " ".join(str(value if value is not None else "").split())


def heading_key(text):
    """A heading in a form that ignores capitals, spaces and punctuation, so 'Size (km2)' matches 'size km2'."""
    return re.sub(r"[^a-z0-9]+", " ", clean(text).casefold()).strip()


def read_table(filename, data):
    """All rows of the first sheet (XLSX) or of the CSV, as lists of cell values. Empty rows are left out."""
    name = (filename or "").lower()
    if name.endswith(".xlsx") or name.endswith(".xlsm"):
        rows = read_xlsx_rows(data)
    elif name.endswith(".csv") or name.endswith(".txt"):
        rows = read_csv_rows(data)
    else:
        raise FileProblem(plain("uploads.problem.wrongType"))
    rows = [row for row in rows if any(clean(v) for v in row)]
    if not rows:
        raise FileProblem(plain("uploads.problem.empty"))
    return rows


def read_xlsx_rows(data):
    # openpyxl is already part of DA Management (the roster import uses it). read_only keeps memory low.
    """The rows of the first sheet of an XLSX file, as lists of cell values."""
    try:
        workbook = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception as error:
        raise FileProblem(plain("uploads.problem.xlsx")) from error
    try:
        sheet = workbook.worksheets[0]
        return [list(row) for row in sheet.iter_rows(values_only=True)]
    finally:
        workbook.close()


def read_csv_rows(data):
    # Exports from the Church and from Google Sheets are UTF-8; Excel on Windows may save in cp1252.
    """The rows of a CSV file, as lists of texts."""
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            text = data.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise FileProblem(plain("uploads.problem.encoding"))
    sample = text[:5000]
    delimiter = ";" if sample.count(";") > sample.count(",") else ","
    return list(csv.reader(io.StringIO(text), delimiter=delimiter))


def find_heading_row(rows, required, look_at=10):
    """The first row (of the first `look_at`) that has every required heading. Some sheets have a title row first.

    Returns (row number, {heading key: column index}); the first column wins when a heading appears twice (the
    Church's finding export repeats several columns)."""
    wanted = [heading_key(h) for h in required]
    for number, row in enumerate(rows[:look_at]):
        columns = {}
        for index, cell in enumerate(row):
            columns.setdefault(heading_key(cell), index)
        if all(key in columns for key in wanted):
            return number, columns
    raise FileProblem(plain("uploads.problem.missingColumns", columns=", ".join(required)))


def cell(row, columns, *headings):
    """The value under the first of these headings that the file has, or None."""
    for heading in headings:
        index = columns.get(heading_key(heading))
        if index is not None and index < len(row):
            return row[index]
    return None


def read_date(value):
    """A date from a cell. Understands spreadsheet dates, 2026-09-27, 9/27/2026 (month first, as the Church's
    exports write it, with or without a time) and 27.09.2026 (day first, German). Empty gives None; anything
    else raises ValueError."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = clean(value)
    if not text:
        return None
    text = text.split(" ")[0]  # "9/27/2025 10:06:42 AM": only the day counts
    if "T" in text and re.match(r"^\d{4}-\d{2}-\d{2}T", text):
        text = text[:10]
    for pattern in ("%Y-%m-%d", "%m/%d/%Y", "%d.%m.%Y", "%m/%d/%y", "%d.%m.%y"):
        try:
            return datetime.strptime(text, pattern).date()
        except ValueError:
            pass
    raise ValueError(plain("uploads.problem.notDate", value=clean(value)))


def read_count(value):
    """A whole number of zero or more, or None for an empty cell. Raises ValueError otherwise."""
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError(plain("uploads.problem.notNumber", value=value))
    if isinstance(value, (int, float)):
        number = float(value)
    else:
        text = clean(value).replace(" ", "")
        if not text or text in {"-", "–"}:
            return None
        text = text.replace(",", ".") if re.fullmatch(r"-?\d+,\d+", text) else text.replace(",", "")
        try:
            number = float(text)
        except ValueError:
            raise ValueError(plain("uploads.problem.notNumber", value=clean(value))) from None
    if number < 0 or number != int(number):
        raise ValueError(plain("uploads.problem.notWhole", value=clean(value)))
    return int(number)


def read_decimal(value):
    """A number of zero or more that may have decimals (a size in km2), or None for an empty cell."""
    if value is None:
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        number = float(value)
    else:
        text = clean(value).replace(" ", "")
        if not text:
            return None
        # German 1.234,5 or 1.234.567 (a single dot, as in 0.135 or 1.234, is a decimal point)
        if re.fullmatch(r"\d{1,3}(\.\d{3})+,\d+", text) or re.fullmatch(r"\d{1,3}(\.\d{3}){2,}", text):
            text = text.replace(".", "").replace(",", ".")
        elif re.fullmatch(r"\d+,\d+", text):  # 12,5
            text = text.replace(",", ".")
        else:
            text = text.replace(",", "")
        try:
            number = float(text)
        except ValueError:
            raise ValueError(plain("uploads.problem.notNumber", value=clean(value))) from None
    if number < 0:
        raise ValueError(plain("uploads.problem.belowZero", value=clean(value)))
    return number


def read_rate(value):
    """A rate as a fraction: '26.00%' and 26 become 0.26, 0.26 stays 0.26. None for an empty cell."""
    if value is None:
        return None
    text = clean(value)
    if not text or text.startswith("#"):  # '#DIV/0!' from a sheet: no rate that week
        return None
    percent = text.endswith("%")
    number = read_decimal(text.rstrip("%").strip())
    if number is None:
        return None
    if percent or number > 1.5:
        number = number / 100
    return round(number, 4)


def week_of(day):
    """The Sunday that ends the Monday-Sunday week this day is in (for event dates: a lesson on Monday 21 Sep
    counts for the week that ends on Sunday 27 Sep)."""
    return day + timedelta(days=6 - day.weekday())


def week_before(day):
    """The Sunday on or before this day (a Sunday stays itself). The zone history sheet names each week by its
    Sunday, so its dates are read with this."""
    return day - timedelta(days=(day.weekday() + 1) % 7)


def week_reported_on(day):
    """The week a FindeChristus report dated `day` shows (the referral archive and the rate archive).

    The reports are made for the Monday meeting. The owner's FC Data Studio sheet: "when the report is viewed on a
    Monday, it displays data from 14 to 8 days earlier", so Monday 28 Sep shows Monday 14 to Sunday 20 Sep. But the
    archives are not always dated on a Monday. Checked on 29 Sep 2026 against the finding export and the FC Data
    Studio sheet (counts only):
      - Monday dates (most reports) show the week that ended 8 days before;
      - Sunday dates are the next Monday's report: 27 Sep 2026 holds exactly the numbers of the 28 Sep report;
      - Thursday to Saturday dates (spring 2026) show the week that ended the Sunday before;
      - the one Tuesday (3 Jun 2025) is the Monday report of the day before, a day late.
    One rule gives all of these: the report shows the last whole week that ended at least three days before it.
    Returns that week's Sunday."""
    return week_before(day - timedelta(days=3))


def as_csv(headings, rows):
    """A CSV file (bytes, UTF-8 with the mark Excel needs to show umlauts) for a template download."""
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(headings)
    writer.writerows(rows)
    return ("﻿" + out.getvalue()).encode("utf-8")
