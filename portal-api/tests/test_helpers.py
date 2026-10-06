"""Unit checks for helpers.py (no database): fetch_rows, fetch_one, json_ready and dashboard_reader.

Run in the portal-api image (no pytest needed):
  docker run --rm -v <repo>/portal-api:/app -w /app gfm-portal-portal-api python tests/test_helpers.py
"""
import sys
import unittest
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import helpers  # noqa: E402


class FakeCursor:
    """Answers every query with the rows and column names it was given; remembers the statements."""

    def __init__(self, conn):
        self.conn = conn

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, args=()):
        self.conn.statements.append(sql)

    @property
    def description(self):
        return [(name,) for name in self.conn.columns] if self.conn.columns else None

    def fetchall(self):
        return list(self.conn.rows)


class FakeConn:
    def __init__(self, rows=(), columns=()):
        self.rows, self.columns, self.statements, self.events = rows, columns, [], []

    def cursor(self):
        return FakeCursor(self)

    def commit(self):
        self.events.append('commit')

    def rollback(self):
        self.events.append('rollback')


class FetchRows(unittest.TestCase):
    def test_plain_rows_become_dicts(self):
        # app.user_db() connections give plain rows (tuples)
        conn = FakeConn(rows=[(1, 'Zone A'), (2, 'Zone B')], columns=('id', 'name'))
        self.assertEqual(helpers.fetch_rows(conn, 'SELECT id, name FROM zones'),
                         [{'id': 1, 'name': 'Zone A'}, {'id': 2, 'name': 'Zone B'}])

    def test_dict_rows_stay_dicts(self):
        # app.db() connections already give dicts
        conn = FakeConn(rows=[{'id': 1, 'name': 'Zone A'}], columns=('id', 'name'))
        self.assertEqual(helpers.fetch_rows(conn, 'SELECT id, name FROM zones'), [{'id': 1, 'name': 'Zone A'}])

    def test_a_statement_without_rows_gives_an_empty_list(self):
        self.assertEqual(helpers.fetch_rows(FakeConn(), 'UPDATE zones SET name = name'), [])

    def test_fetch_one(self):
        self.assertEqual(helpers.fetch_one(FakeConn(rows=[(7,), (8,)], columns=('n',)), 'SELECT n'), {'n': 7})
        self.assertIsNone(helpers.fetch_one(FakeConn(rows=[], columns=('n',)), 'SELECT n'))


class JsonReady(unittest.TestCase):
    def test_dates_times_and_decimals_inside_lists_and_dicts(self):
        value = {'week': date(2026, 9, 27), 'at': datetime(2026, 9, 27, 18, 0, tzinfo=timezone.utc),
                 'numbers': [Decimal('3'), Decimal('2.5'), 4, None], 'nested': ({'x': Decimal('0')},)}
        self.assertEqual(helpers.json_ready(value), {
            'week': '2026-09-27', 'at': '2026-09-27T18:00:00+00:00', 'numbers': [3, 2.5, 4, None],
            'nested': [{'x': 0}]})

    def test_whole_decimals_become_int(self):
        self.assertIsInstance(helpers.json_ready(Decimal('12.000')), int)
        self.assertIsInstance(helpers.json_ready(Decimal('12.5')), float)

    def test_other_values_pass_unchanged(self):
        for value in ('text', 5, 2.5, True, None):
            self.assertEqual(helpers.json_ready(value), value)


class DashboardReader(unittest.TestCase):
    def test_read_only_reader_role_and_time_limit_then_rolled_back(self):
        conn = FakeConn()
        with helpers.dashboard_reader(conn, '5s') as cur:
            cur.execute('SELECT 1')
        self.assertEqual(conn.statements, ['SET TRANSACTION READ ONLY', 'SET LOCAL ROLE gfm_dashboard_reader',
                                           "SET LOCAL statement_timeout = '5s'", 'SELECT 1'])
        self.assertEqual(conn.events, ['commit', 'rollback'])

    def test_rolled_back_after_an_error_too(self):
        conn = FakeConn()
        with self.assertRaises(RuntimeError):
            with helpers.dashboard_reader(conn, '10s'):
                raise RuntimeError('a query failed')
        self.assertEqual(conn.events, ['commit', 'rollback'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
