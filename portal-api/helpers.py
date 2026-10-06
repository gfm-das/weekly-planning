"""Small tools that several files of portal-api use.

What it is: fetch_rows() reads the rows of a query as a list of dicts; json_ready() turns dates and decimal numbers
into plain values that JSON can carry; dashboard_reader() opens a read-only cursor for the dashboards views.
Who uses it: planning.py, callins.py and dashboard.py (their queries run on app.user_db() connections), app.py,
charts.py and archetypes.py.
How it fits: app.user_db() connections give plain tuples, not dicts (app.py sets cursor_factory=None there), while
app.db() connections give dicts. fetch_rows works with both, so the planning and Call-ins code does not need to know
which kind of connection it was handed.
"""
from contextlib import contextmanager
from datetime import date, datetime
from decimal import Decimal


def fetch_rows(conn, sql, args=()):
    """Run one query and return its rows as a list of dicts (an empty list for a statement without rows)."""
    with conn.cursor() as cursor:
        cursor.execute(sql, args)
        if not cursor.description:
            return []
        names = [column[0] for column in cursor.description]
        return [dict(row) if isinstance(row, dict) else dict(zip(names, row)) for row in cursor.fetchall()]


def fetch_one(conn, sql, args=()):
    """The first row of a query as a dict, or None when there is none."""
    found = fetch_rows(conn, sql, args)
    return found[0] if found else None


def json_ready(value):
    """The same value with dates and times as ISO text ('2026-09-27', '2026-09-27T18:00:00+00:00') and Decimal
    numbers as int (when whole) or float, also inside lists and dicts, so jsonify() sends them the same way
    everywhere."""
    if isinstance(value, dict):
        return {key: json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_ready(item) for item in value]
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    return value


@contextmanager
def dashboard_reader(conn, statement_timeout):
    """A cursor in a READ ONLY transaction as gfm_dashboard_reader, stopped after statement_timeout ('5s').

    Charts and Archetypal Health read the dashboards views this way: that role can read those views and nothing
    else (migrations 025 and 034 let postgres switch to it), so even a mistake in a query cannot read or change
    anything more. The transaction is always rolled back at the end."""
    conn.commit()  # ends the lookups made as postgres (context, scope); SET TRANSACTION must come first
    try:
        with conn.cursor() as cur:
            cur.execute('SET TRANSACTION READ ONLY')
            cur.execute('SET LOCAL ROLE gfm_dashboard_reader')
            cur.execute(f"SET LOCAL statement_timeout = '{statement_timeout}'")
            yield cur
    finally:
        conn.rollback()
