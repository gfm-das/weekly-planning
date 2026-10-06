"""Unit checks for staff accounts in context_for (President, Office or Data Analyst with no missionary link).

Run in the portal-api image (no database needed):
  docker run --rm -v <repo>/portal-api:/app -w /app gfm-portal-portal-api python tests/test_staff_accounts.py
"""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from werkzeug.exceptions import Forbidden

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app as api  # noqa: E402

BASE = {'user_id': 'u1', 'user_active': True, 'app_role': 'PRESIDENT', 'missionary_id': None, 'mission_id': None,
        'mission': None, 'leadership_role': None, 'leadership_mission_id': None, 'area_id': None, 'display_name': 'President Test'}


def fake_rows(context_row):
    def rows(conn, sql, args=()):
        if 'current_user_context' in sql:
            return [dict(context_row)] if context_row else []
        if 'public.missions' in sql:
            return [{'name': f'Mission {args[0]}'}]
        raise AssertionError(sql)
    return rows


def context(row):
    with patch.object(api, 'rows', side_effect=fake_rows(row)):
        return api.context_for(None, 'u1')


class StaffContext(unittest.TestCase):
    def test_staff_account_uses_its_home_mission(self):
        c = context(BASE | {'home_mission_id': 2})
        self.assertEqual((c['mission_id'], c['mission'], c['role']), (2, 'Mission 2', 'PRESIDENT'))

    def test_office_and_data_analyst_staff_accounts_sign_in_too(self):
        for role in ('OFFICE', 'DATA_ADMIN'):
            self.assertEqual(context(BASE | {'app_role': role, 'home_mission_id': 3})['mission_id'], 3)

    def test_without_a_home_mission_it_is_still_refused(self):
        with self.assertRaises(Forbidden):
            context(BASE | {'home_mission_id': None})
        with self.assertRaises(Forbidden):
            context(BASE)  # a database without migration 027 has no home_mission_id column

    def test_a_missionary_never_uses_a_home_mission(self):
        # The view shows NULL for a linked account; even if a value came through, the assignment decides.
        with self.assertRaises(Forbidden):
            context(BASE | {'missionary_id': 7, 'app_role': 'MISSIONARY', 'home_mission_id': 2})
        c = context(BASE | {'missionary_id': 7, 'app_role': 'MISSIONARY', 'mission_id': 5, 'mission': 'Five', 'home_mission_id': 2})
        self.assertEqual((c['mission_id'], c['mission']), (5, 'Five'))

    def test_inactive_staff_account_is_refused(self):
        with self.assertRaises(Forbidden):
            context(BASE | {'home_mission_id': 2, 'user_active': False})


if __name__ == '__main__':
    unittest.main(verbosity=2)
