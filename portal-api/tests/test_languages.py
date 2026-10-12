"""Unit checks for the language list (app.language_choices, GET/PUT /api/languages rules), no database.

Managers (AP, President, Data Analyst, also as an additional role) may choose every interface language; everyone else
only the languages DA Management assigned (or the mission's default language).

Run in the portal-api image (no pytest needed):
  docker run --rm -v <repo>/portal-api:/app -w /app gfm-portal-portal-api python tests/test_languages.py
"""
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault('SUPABASE_URL', 'http://supabase.invalid')
os.environ.setdefault('SUPABASE_SERVICE_ROLE_KEY', 'unit-test-only')
import app  # noqa: E402
import roles  # noqa: E402


def fake_rows(assigned, pref, default='de'):
    def rows(conn, sql, params=()):
        if 'missionary_language_assignments' in sql:
            return [assigned] if assigned else []
        if 'user_preferences' in sql:
            return [{'language': pref}] if pref else []
        if 'default_language' in sql:
            return [{'default_language': default}]
        raise AssertionError(sql)
    return rows


def person(app_role='MISSIONARY', leader=None, *additional):
    return {'user_id': 'u1', 'missionary_id': 7, 'mission_id': 1, 'app_role': app_role, 'leadership_role': leader,
            'additional_roles': list(additional)}


class LanguageChoices(unittest.TestCase):
    def choices(self, c, assigned=None, pref=None):
        with patch.object(app, 'rows', fake_rows(assigned, pref)):
            return app.language_choices(None, c)

    def test_missionary_gets_only_assigned_languages(self):
        primary, allowed, selected = self.choices(person(), {'primary_language': 'de', 'additional_languages': ['en']},
                                                  'fa')
        self.assertEqual((primary, allowed, selected), ('de', ['de', 'en'], 'de'))

    def test_missionary_without_assignment_gets_mission_default(self):
        self.assertEqual(self.choices(person('MISSIONARY', 'ZL'))[1], ['de'])

    def test_office_is_not_widened(self):
        self.assertEqual(self.choices(person('OFFICE'))[1], ['de'])

    def test_managers_get_every_language_assigned_first(self):
        for c in (person('AP', 'AP'), person('PRESIDENT'), person('DATA_ADMIN'),
                  person('MISSIONARY', 'DL', 'DATA_ADMIN')):
            primary, allowed, selected = self.choices(c, {'primary_language': 'fa', 'additional_languages': ['en']},
                                                      'ar')
            self.assertEqual(primary, 'fa')
            self.assertEqual(allowed[:2], ['fa', 'en'])
            self.assertEqual(sorted(allowed), sorted(roles.INTERFACE_LANGUAGES))
            self.assertEqual(selected, 'ar')  # an unassigned language a manager chose is kept

    def test_manager_keeps_an_extra_assigned_code(self):
        allowed = self.choices(person('PRESIDENT'), {'primary_language': 'zh-Hant', 'additional_languages': []})[1]
        self.assertEqual(allowed[0], 'zh-Hant')
        self.assertEqual(len(allowed), len(roles.INTERFACE_LANGUAGES) + 1)


if __name__ == '__main__':
    unittest.main()
