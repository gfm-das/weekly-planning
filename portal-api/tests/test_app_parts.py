"""Unit checks for the small named steps of app.py, reminders.py, callins.py, archetypes.py and whiteboards.py that had
no check of their own (round 9 tidy). No database, no network: every database answer is made up here.

Run in the portal-api image (no pytest needed):
  docker run --rm -v <repo>/portal-api:/app -w /app gfm-portal-portal-api python tests/test_app_parts.py
"""
import base64
import os
import sys
import unittest
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from cryptography.hazmat.primitives import serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import ec  # noqa: E402
from werkzeug.exceptions import HTTPException  # noqa: E402

import app  # noqa: E402
import archetypes  # noqa: E402
import callins  # noqa: E402
import reminders  # noqa: E402
import whiteboards  # noqa: E402

UTC = timezone.utc
START = datetime(2026, 10, 4, 10, 0, tzinfo=UTC)


class Refusals(unittest.TestCase):
    def refused(self, code, call, *args):
        with self.assertRaises(HTTPException) as caught:
            call(*args)
        self.assertEqual(caught.exception.code, code)
        return caught.exception.description


class TimesAndLinks(Refusals):
    def test_iso_needs_a_time_zone(self):
        self.assertEqual(app.iso('2026-09-27T18:00:00Z'), datetime(2026, 9, 27, 18, 0, tzinfo=UTC))
        self.assertEqual(app.iso('2026-09-27T20:00:00+02:00').utcoffset(), timedelta(hours=2))
        self.assertEqual(self.refused(400, app.iso, '2026-09-27T18:00:00'), 'Times must include a timezone.')

    def test_safe_url(self):
        self.assertEqual(app.safe_url(''), '')
        self.assertEqual(app.safe_url(None), '')
        self.assertEqual(app.safe_url('https://meet.example.org/abc'), 'https://meet.example.org/abc')
        for bad in ('ftp://example.org/x', 'javascript:alert(1)', 'https://example.org/' + 'a' * 2000):
            self.refused(400, app.safe_url, bad)


class RepeatRules(Refusals):
    def test_a_one_off_event_keeps_its_empty_rule(self):
        self.assertIsNone(app.clean_recurrence(None, START))
        self.assertEqual(app.clean_recurrence({}, START), {})

    def test_a_weekly_rule_is_cleaned(self):
        rule = app.clean_recurrence({'frequency': 'weekly', 'interval': '2', 'until': '2026-12-31T00:00:00Z',
                                     'extra': 'dropped'}, START)
        self.assertEqual(rule, {'frequency': 'weekly', 'interval': 2, 'until': '2026-12-31T00:00:00+00:00'})

    def test_refused_rules(self):
        self.refused(400, app.clean_recurrence, {'frequency': 'yearly', 'until': '2026-12-31T00:00:00Z'}, START)
        self.refused(400, app.clean_recurrence, {'frequency': 'daily', 'interval': 53, 'until': '2026-12-31T00:00:00Z'},
                     START)
        self.refused(400, app.clean_recurrence, {'frequency': 'daily', 'until': '2029-01-01T00:00:00Z'}, START)
        self.refused(400, app.clean_recurrence, {'frequency': 'daily', 'until': '2026-10-01T00:00:00Z'}, START)


class PushDevices(Refusals):
    def test_known_push_services_only(self):
        for good in ('https://fcm.googleapis.com/fcm/send/x', 'https://updates.push.services.mozilla.com/wpush/v2/x',
                     'https://wns2-par02p.notify.windows.com/w/?token=x', 'https://web.push.apple.com/x',
                     'https://fcm.googleapis.com:443/x'):
            app.check_push_provider(good)
        for bad in ('http://fcm.googleapis.com/x', 'https://evil.example/fcm.googleapis.com',
                    'https://xnotify.windows.com/w', 'https://user:pw@fcm.googleapis.com/x',
                    'https://fcm.googleapis.com:8443/x', 'https://127.0.0.1:5432'):
            self.assertEqual(self.refused(400, app.check_push_provider, bad), 'Unrecognized browser push provider.')

    @staticmethod
    def browser_keys():
        public = ec.generate_private_key(ec.SECP256R1()).public_key().public_bytes(
            serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
        encode = lambda raw: base64.urlsafe_b64encode(raw).decode().rstrip('=')  # noqa: E731
        return {'p256dh': encode(public), 'auth': encode(os.urandom(16))}

    def test_valid_keys_pass(self):
        app.check_push_keys(self.browser_keys())

    def test_invalid_keys_raise(self):
        keys = self.browser_keys()
        for bad in (dict(keys, auth=keys['auth'][:-4]), dict(keys, p256dh='%%%%'), dict(keys, p256dh=42),
                    dict(keys, p256dh=base64.urlsafe_b64encode(b'\x04' + b'\x00' * 64).decode()), {'auth': keys['auth']}):
            with self.assertRaises(Exception):
                app.check_push_keys(bad)


class SlideNumbers(Refusals):
    def test_week_count(self):
        self.assertEqual(app.kpi_week_count(26), 26)
        self.assertEqual(app.kpi_week_count('8'), 8)
        self.assertEqual(app.kpi_week_count(104), 104)
        for bad in (True, 0, 105, '8.5', None, 2.0, '-1'):
            self.assertEqual(self.refused(400, app.kpi_week_count, bad), 'Choose between 1 and 104 weeks.')


def person(main, **more):
    c = {'user_id': 'u-' + main.lower(), 'mission_id': 2, 'app_role': 'MISSIONARY', 'leadership_role': None,
         'additional_roles': []}
    if main in ('AP', 'PRESIDENT', 'DATA_ADMIN', 'OFFICE'):
        c['app_role'] = main
    if main in ('AP', 'DL', 'ZL', 'STL'):
        c['leadership_role'] = main
    return dict(c, **more)


AREAS = [{'id': 511, 'district_id': 51, 'zone_id': 5}, {'id': 521, 'district_id': 52, 'zone_id': 5}]


class AnnouncementTargets(Refusals):
    def test_a_dl_may_not_name_a_whole_zone_in_an_announcement(self):
        self.assertEqual(app.allowed_targets(person('DL'), AREAS, True)['zone_ids'], set())
        self.assertEqual(app.allowed_targets(person('DL'), AREAS, False)['zone_ids'], {5})
        self.assertEqual(app.allowed_targets(person('AP'), AREAS, True)['zone_ids'], {5})

    def test_an_office_dl_may_name_a_zone_in_a_mission_wide_announcement(self):
        office_dl = person('DL')
        office_dl['additional_roles'] = ['OFFICE']
        self.assertEqual(app.allowed_targets(office_dl, AREAS, True)['zone_ids'], {5})

    def test_a_leader_without_targets_reaches_only_their_own_stewardship(self):
        empty = {'roles': [], 'zone_ids': [], 'district_ids': [], 'area_ids': [], 'user_ids': []}
        dl = dict(empty)
        app.keep_leader_announcement_inside(person('DL'), dl, {'zone_ids': set(), 'district_ids': {52, 51}})
        self.assertEqual((dl['district_ids'], dl['zone_ids']), ([51, 52], []))
        zl = dict(empty)
        app.keep_leader_announcement_inside(person('ZL'), zl, {'zone_ids': {5}, 'district_ids': {51, 52}})
        self.assertEqual((zl['zone_ids'], zl['district_ids']), ([5], []))

    def test_named_targets_stay_as_they_are(self):
        targets = {'roles': [], 'zone_ids': [], 'district_ids': [], 'area_ids': [511], 'user_ids': []}
        app.keep_leader_announcement_inside(person('ZL'), targets, {'zone_ids': {5}, 'district_ids': {51}})
        self.assertEqual(targets['area_ids'], [511])
        self.assertEqual(targets['zone_ids'], [])

    def test_someone_who_is_not_a_leader_is_refused(self):
        self.refused(403, app.keep_leader_announcement_inside, person('MISSIONARY'),
                     {'zone_ids': [], 'district_ids': [], 'area_ids': [], 'user_ids': []}, {})


class Languages(unittest.TestCase):
    def choices(self, assigned, chosen):
        def fake_rows(conn, sql, args=()):
            if 'missionary_language_assignments' in sql:
                return assigned
            return [{'language': chosen}] if chosen else []
        with patch.object(app, 'rows', fake_rows):
            return app.language_choices(None, {'user_id': 'u', 'missionary_id': 7})

    def test_assigned_languages_and_the_chosen_one(self):
        assigned = [{'primary_language': 'de', 'additional_languages': ['en', 'de', 'fa']}]
        self.assertEqual(self.choices(assigned, 'fa'), ('de', ['de', 'en', 'fa'], 'fa'))
        self.assertEqual(self.choices(assigned, 'uk'), ('de', ['de', 'en', 'fa'], 'de'), 'no longer allowed: the first')

    def test_english_without_an_assignment(self):
        self.assertEqual(self.choices([], None), ('en', ['en'], 'en'))


class WorkedOnLately(unittest.TestCase):
    def test_the_plan_and_its_answers_saved_in_the_last_five_minutes(self):
        now = datetime(2026, 10, 4, 16, 0, tzinfo=UTC)
        asked = []

        def fake_rows(conn, sql, args=()):
            asked.append((sql, args))
            return [{'?column?': 1}] if found else []

        with patch.object(reminders, 'rows', fake_rows):
            found = True
            self.assertTrue(reminders.worked_on_lately(None, 511, date(2026, 10, 4), now))
            found = False
            self.assertFalse(reminders.worked_on_lately(None, 511, date(2026, 10, 4), now))
        sql, args = asked[0]
        cutoff = now - timedelta(minutes=5)
        self.assertEqual(args, (511, date(2026, 10, 4), cutoff, 511, date(2026, 10, 4), cutoff))
        self.assertIn('weekly_area_reports', sql)
        self.assertIn('weekly_planning_answers', sql)
        self.assertNotIn('portal.activity', sql)


class CallinsScope(Refusals):
    def test_the_stewardship_check_comes_before_the_time_limit(self):
        steps = []
        viewer = {'manager': False, 'mission_id': 2, 'zone_id': 5, 'district_id': None}
        with patch.object(callins, 'weeks_for', lambda conn, requested: steps.append('weeks') or ({'id': 9}, [])), \
                patch.object(callins, 'chain_for', lambda conn, level, i: steps.append('chain') or {'mission_id': 2, 'zone_id': i}), \
                patch.object(callins, 'statement_limit', lambda conn: steps.append('limit')):
            self.assertEqual(callins.open_scope(None, viewer, 'zone', 5, None), ({'id': 9}, [], {'mission_id': 2, 'zone_id': 5}))
            self.assertEqual(steps, ['weeks', 'chain', 'limit'])
            steps.clear()
            self.refused(403, callins.open_scope, None, viewer, 'zone', 6, None)
            self.assertEqual(steps, ['weeks', 'chain'], 'no query runs for a scope outside the stewardship')


class ArchetypeNotes(Refusals):
    def test_a_note_for_a_past_sunday(self):
        with patch.object(archetypes, 'today', lambda: date(2026, 9, 29)):
            self.assertEqual(archetypes.note_request({'area_id': 511, 'week': '2026-09-27', 'body': ' Good week '}),
                             (511, date(2026, 9, 27), ' Good week '))
            for bad in ({'area_id': 511, 'week': '2026-09-26', 'body': 'x'},   # a Saturday
                        {'area_id': 511, 'week': '2026-10-04', 'body': 'x'},   # a Sunday still to come
                        {'area_id': 511, 'week': 'last week', 'body': 'x'},
                        {'area_id': True, 'week': '2026-09-27', 'body': 'x'},
                        {'area_id': 511, 'week': '2026-09-27', 'body': 5},
                        {'area_id': 511, 'week': '2026-09-27', 'body': 'x' * (archetypes.NOTE_LIMIT + 1)}):
                self.refused(400, archetypes.note_request, bad)


class NewBoards(unittest.TestCase):
    def test_picture_source(self):
        board = str(uuid.uuid4())
        self.assertEqual(whiteboards.picture_source(board.upper()), board)
        self.assertIsNone(whiteboards.picture_source(None))
        self.assertIsNone(whiteboards.picture_source('not-a-board'))

    def test_a_new_board_without_a_drawing_is_empty(self):
        scene, files = whiteboards.new_drawing({'name': 'Plan'})
        self.assertEqual((scene['elements'], scene['style'], files), ([], 'hand', {}))


if __name__ == '__main__':
    unittest.main(verbosity=2)
