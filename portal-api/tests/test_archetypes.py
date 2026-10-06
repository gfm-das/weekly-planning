"""Archetypal Health calculation (archetype_model.py), without a database. Made-up numbers only.

Run from portal-api (the catalog check also needs portal/ next to portal-api):
  python tests/test_archetypes.py      (or: python -m unittest tests.test_archetypes)
"""
import json
import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import archetype_model as model  # noqa: E402

WEEK = date(2026, 9, 20)
EARLIER = date(2026, 9, 13)


def simple_settings(**changes):
    """The defaults with small weights, so every number below can be worked out by hand."""
    settings = model.defaults()
    settings['weights'] = {
        'finding': {'friends_found': 50, 'lessons_with_friends': 50},
        'teaching': {'lessons_with_friends': 100},
        'bringing': {'sacrament_attendance': 100},
        'baptizing': {'baptismal_dates': 100},
        'fellowshipping': {'new_member_sacrament_share': 100},
        'reactivating': {'member_meals_less_active': 100},
    }
    settings['peer_group'] = {'attributes': [], 'density_bins': [200, 500], 'minimum_size': 2, 'fallback': True}
    settings.update(changes)
    return settings


def row(area, friends, lessons, sunday=WEEK):
    return {'sunday': sunday, 'area_id': area, 'friends_found': friends, 'lessons_with_friends': lessons}


# Four areas, one week: New People Being Taught 2, 4, 6, 8 and lessons with friends 10, 12, 8, 14.
ROWS = [row(1, 2, 10), row(2, 4, 12), row(3, 6, 8), row(4, 8, 14)]


class HandCheck(unittest.TestCase):
    """Area 1 worked out by hand.

    Mission usual week (all area-weeks up to 20 Sep):
      New People Being Taught: average 5, sample deviation sqrt((9+1+1+9)/3) = 2.58199
      Lessons with friends:    average 11, sample deviation sqrt((1+1+9+9)/3) = 2.58199
    Area 1: z(new people) = (2-5)/2.58199 = -1.16190; z(lessons) = (10-11)/2.58199 = -0.38730
    Finding profile = 0.5 x -1.16190 + 0.5 x -0.38730 = -0.77460
    Finding profiles of the four areas: -0.77460, 0.0, -0.38730, 1.16190 -> average 0,
      sample deviation sqrt((0.6 + 0 + 0.15 + 1.35)/3) = sqrt(0.7) = 0.83666
    Finding score = -0.77460 / 0.83666 = -0.92582 -> index 100 + 15 x -0.92582 = 86.11
    Teaching (lessons only): score = z = -0.38730 -> index 94.19
    Overall = (86.11 + 94.19) / 2 = 90.15; every score below 0 -> "stalled"
    """

    def setUp(self):
        self.result = model.score_week(ROWS, {}, simple_settings(), WEEK, 1)
        self.area = self.result['areas'][1]

    def test_finding_index(self):
        self.assertAlmostEqual(self.area['profiles']['finding'], -0.774597, places=5)
        self.assertAlmostEqual(self.area['scores']['finding'], -0.925820, places=5)
        self.assertAlmostEqual(self.area['indices']['finding'], 86.1127, places=3)

    def test_teaching_overall_and_label(self):
        self.assertAlmostEqual(self.area['indices']['teaching'], 94.1905, places=3)
        self.assertAlmostEqual(self.area['overall'], (86.1127 + 94.1905) / 2, places=3)
        self.assertEqual(self.area['label'], 'stalled')

    def test_kpis_without_numbers_are_skipped(self):
        self.assertIn('sacrament_attendance', self.result['skipped'])
        self.assertIsNone(self.area['indices']['bringing'])

    def test_strongest_area_and_balance_threshold(self):
        # Area 4: finding 1.16190 / 0.83666 = 1.38873, teaching 1.16190: ahead by 0.2268
        self.assertEqual(self.result['areas'][4]['label'], 'finding')
        wider = model.score_week(ROWS, {}, simple_settings(balance_threshold=0.3), WEEK, 1)
        self.assertEqual(wider['areas'][4]['label'], 'balanced')


class SettingsChangeTheScores(unittest.TestCase):
    def test_weights(self):
        settings = simple_settings()
        settings['weights']['finding'] = {'friends_found': 100}
        area = model.score_week(ROWS, {}, settings, WEEK, 1)['areas'][1]
        # Finding is now only New People Being Taught: score = z = -1.16190 -> 82.57
        self.assertAlmostEqual(area['indices']['finding'], 82.5714, places=3)

    def test_peer_groups(self):
        attributes = {1: {'urban_type': 'City'}, 2: {'urban_type': 'City'},
                      3: {'urban_type': 'Town'}, 4: {'urban_type': 'Town'}}
        peer = {'attributes': ['urban_type'], 'density_bins': [200], 'minimum_size': 2, 'fallback': True}
        area = model.score_week(ROWS, attributes, simple_settings(peer_group=peer), WEEK, 1)['areas'][1]
        # City: profiles -0.77460 and 0 -> average -0.38730, deviation 0.54772 -> score -0.70711 -> 89.39
        self.assertEqual(area['peer_group'], 'City')
        self.assertAlmostEqual(area['indices']['finding'], 89.3934, places=3)
        too_small = dict(peer, minimum_size=3)
        area = model.score_week(ROWS, attributes, simple_settings(peer_group=too_small), WEEK, 1)['areas'][1]
        self.assertEqual(area['peer_group'], model.WHOLE_MISSION)
        self.assertAlmostEqual(area['indices']['finding'], 86.1127, places=3)
        no_fallback = dict(too_small, fallback=False)
        area = model.score_week(ROWS, attributes, simple_settings(peer_group=no_fallback), WEEK, 1)['areas'][1]
        self.assertIsNone(area['indices']['finding'])

    def test_fallback_compares_with_every_area(self):
        """One lone Town area next to four City areas (minimum size 3): the Town area is compared with all five areas,
        not only with itself.

        New People Being Taught 2, 4, 6, 8 (City) and 30 (Town): average 10, sample deviation sqrt(520/4) = 11.40175.
        Town: z = 20 / 11.40175 = 1.75412. The whole mission's Finding profiles are these z-scores (average 0,
        deviation 1), so score = 1.75412 -> index 100 + 15 x 1.75412 = 126.31. (Compared only with itself it read 100.)
        """
        rows = [row(1, 2, None), row(2, 4, None), row(3, 6, None), row(4, 8, None), row(5, 30, None)]
        attributes = {a: {'urban_type': 'City'} for a in (1, 2, 3, 4)}
        attributes[5] = {'urban_type': 'Town'}
        settings = simple_settings(peer_group={'attributes': ['urban_type'], 'density_bins': [200],
                                               'minimum_size': 3, 'fallback': True})
        settings['weights']['finding'] = {'friends_found': 100}
        town = model.score_week(rows, attributes, settings, WEEK, 1)['areas'][5]
        self.assertEqual(town['peer_group'], model.WHOLE_MISSION)
        self.assertAlmostEqual(town['indices']['finding'], 126.3118, places=3)
        city = model.score_week(rows, attributes, settings, WEEK, 1)['areas'][1]
        self.assertEqual(city['peer_group'], 'City')  # the City group is big enough and stays on its own

    def test_weeks_to_average(self):
        earlier = [row(1, 4, 10, EARLIER), row(2, 4, 12, EARLIER), row(3, 6, 8, EARLIER), row(4, 8, 14, EARLIER)]
        one = model.score_week(earlier + ROWS, {}, simple_settings(), WEEK, 1)['areas'][1]
        four = model.score_week(earlier + ROWS, {}, simple_settings(), WEEK, 4)['areas'][1]
        self.assertEqual(four['values']['friends_found'], 3.0)  # (4 + 2) / 2
        self.assertNotAlmostEqual(one['indices']['finding'], four['indices']['finding'], places=2)

    def test_density_bands(self):
        self.assertEqual(model.density_band(150, [200, 500, 700, 1200]), '< 200')
        self.assertEqual(model.density_band(800, [200, 500, 700, 1200]), '700 – 1200')
        self.assertEqual(model.density_band(1200, [200, 500, 700, 1200]), '>= 1200')
        self.assertEqual(model.density_band(None, [200]), model.MISSING)

    def test_rolled_up_is_the_average_of_the_areas(self):
        areas = model.score_week(ROWS, {}, simple_settings(), WEEK, 1)['areas']
        rolled = model.roll_up(areas, [1, 2], 0.2)
        self.assertAlmostEqual(rolled['overall'], (areas[1]['overall'] + areas[2]['overall']) / 2, places=6)
        self.assertEqual(rolled['areas_scored'], 2)


class Validation(unittest.TestCase):
    def test_defaults_are_valid(self):
        self.assertEqual(model.validate_settings(model.defaults()), model.defaults())

    def test_weights_must_total_100(self):
        settings = model.defaults()
        settings['weights']['finding']['friends_found'] = 40
        with self.assertRaises(model.SettingsError) as caught:
            model.validate_settings(settings)
        self.assertEqual(caught.exception.fields, {'weights.finding': 'The weights must add up to 100 %.'})

    def test_other_mistakes_are_named(self):
        settings = model.defaults()
        settings['weights']['teaching'] = {'no_such_number': 100}
        settings['bands'][2]['from'] = 125
        settings['bands'][0]['color'] = 'green'
        settings['balance_threshold'] = 5
        settings['weeks_to_average'] = 3
        settings['peer_group']['density_bins'] = [500, 200]
        settings['diagnoses']['patterns']['stalled']['steps'] = []
        with self.assertRaises(model.SettingsError) as caught:
            model.validate_settings(settings)
        self.assertEqual(set(caught.exception.fields), {
            'weights.teaching', 'bands', 'bands.0', 'balance_threshold', 'weeks_to_average',
            'peer_group.density_bins', 'diagnoses.patterns.stalled'})

    def test_a_number_can_be_added(self):
        settings = model.defaults()
        settings['weights']['finding'] = {'friends_found': 40, 'finding_people_found': 60}
        self.assertEqual(model.validate_settings(settings)['weights']['finding']['finding_people_found'], 60)

    def test_saved_settings_that_weight_an_archived_number_stay_valid(self):
        # Migration 038 archived Facebook and FindeChristus; settings saved before keep working and keep their scores.
        settings = model.defaults()
        settings['weights']['finding'] = {'friends_found': 40, 'findechristus_referrals': 60}
        self.assertEqual(model.validate_settings(settings)['weights']['finding']['findechristus_referrals'], 60)


class Archived(unittest.TestCase):
    """Facebook and FindeChristus numbers are archived (migration 038): never offered, never newly added."""

    def test_the_archived_numbers(self):
        self.assertEqual(model.ARCHIVED_SOURCES,
                         {'facebook_finding_days', 'facebook_friends_found', 'findechristus_referrals'})
        self.assertTrue(model.ARCHIVED_SOURCES <= set(model.SOURCES))  # kept, so old settings keep their labels

    def test_the_defaults_use_no_archived_number_or_tip(self):
        self.assertEqual(model.archived_used(model.defaults()), set())
        steps = [step for pattern in model.defaults()['diagnoses']['patterns'].values() for step in pattern['steps']]
        self.assertEqual([s for s in steps if s in model.ARCHIVED_STEPS or 'FindeChristus' in s], [])
        self.assertEqual(len(model.defaults()['diagnoses']['patterns']['finding_low_teaching_strong']['steps']), 2)

    def test_used(self):
        settings = model.defaults()
        settings['weights']['finding'] = {'friends_found': 40, 'findechristus_referrals': 60}
        settings['weights']['teaching']['facebook_friends_found'] = 0
        self.assertEqual(model.archived_used(settings), {'findechristus_referrals', 'facebook_friends_found'})
        self.assertEqual(model.archived_used({}), set())

    def test_adding_one_is_refused_where_it_was_not_weighted_before(self):
        before = model.defaults()
        after = model.defaults()
        after['weights']['finding'] = {'friends_found': 40, 'findechristus_referrals': 60}
        self.assertEqual(model.archived_added(before, after),
                         {'weights.finding': 'This number is archived and can no longer be added.'})
        # Moving it to another archetype counts as adding it there.
        moved = model.defaults()
        moved['weights']['teaching'] = dict(moved['weights']['teaching'], findechristus_referrals=0)
        self.assertEqual(set(model.archived_added(after, moved)), {'weights.teaching'})

    def test_keeping_lowering_or_removing_one_is_fine(self):
        before = model.defaults()
        before['weights']['finding'] = {'friends_found': 40, 'findechristus_referrals': 60}
        lower = model.defaults()
        lower['weights']['finding'] = {'friends_found': 90, 'findechristus_referrals': 10}
        self.assertEqual(model.archived_added(before, before), {})
        self.assertEqual(model.archived_added(before, lower), {})
        self.assertEqual(model.archived_added(before, model.defaults()), {})
        self.assertEqual(model.archived_added(None, model.defaults()), {})

    def test_weeks_to_average_must_be_a_whole_number(self):
        # True == 1 and 4.0 == 4 in Python; a saved 4.0 would break every page later.
        for wrong in (True, 4.0, 3, '4'):
            settings = model.defaults()
            settings['weeks_to_average'] = wrong
            with self.assertRaises(model.SettingsError, msg=repr(wrong)) as caught:
                model.validate_settings(settings)
            self.assertEqual(set(caught.exception.fields), {'weeks_to_average'})

    def test_change_summary(self):
        after = model.defaults()
        after['weeks_to_average'] = 4
        after['weights']['baptizing'] = {'baptisms_confirmations': 100}
        self.assertEqual(model.change_summary(model.defaults(), after), 'Weights: Baptizing, Weeks to average: 1 → 4')


class Diagnosis(unittest.TestCase):
    def result(self, **indices):
        values = {a: indices.get(a, 100.0) for a in model.ARCHETYPES}
        scores = {a: (v - 100) / 15 for a, v in values.items()}
        return model.summary(scores, 0.2)

    def test_strengths_first_then_the_pattern(self):
        found = model.diagnosis(self.result(finding=85, teaching=115), model.defaults())
        self.assertEqual(found['strengths'][0]['archetype'], 'teaching')
        self.assertEqual([p['id'] for p in found['patterns']], ['finding_low_teaching_strong'])
        self.assertEqual(len(found['patterns'][0]['steps']), 2)  # 3 before the FindeChristus tip was archived (038)

    def test_stalled_and_single_lows(self):
        found = model.diagnosis(self.result(**dict({a: 95 for a in model.ARCHETYPES}, bringing=70)), model.defaults())
        self.assertEqual(found['strengths'], [])
        self.assertEqual([p['id'] for p in found['patterns']], ['stalled', 'bringing_low'])

    def test_balanced_at_exactly_the_threshold(self):
        # Balanced when no strength stands out by MORE than the threshold: a lead of exactly 0.25 is still balanced.
        self.assertEqual(model.label_for({'finding': 1.0, 'teaching': 0.75}, 0.25), 'balanced')
        self.assertEqual(model.label_for({'finding': 1.0, 'teaching': 0.5}, 0.25), 'finding')

    def test_no_index_no_pattern(self):
        # Nothing measured (no numbers or no peer group): no "steady work" claim, the page says there is not enough.
        found = model.diagnosis(model.summary({a: None for a in model.ARCHETYPES}, 0.2), model.defaults())
        self.assertEqual(found, {'strengths': [], 'patterns': []})

    def test_steady(self):
        found = model.diagnosis(self.result(finding=104, teaching=96), model.defaults())
        self.assertEqual([p['id'] for p in found['patterns']], ['steady'])

    def test_complete_weeks_and_default_week(self):
        counts = {date(2026, 9, 13): 80, date(2026, 9, 20): 87, date(2026, 9, 27): 3}
        weeks = model.complete_weeks(counts, date(2026, 9, 29))
        self.assertEqual(weeks[0], date(2026, 9, 27))
        self.assertEqual(model.default_week(counts, weeks), date(2026, 9, 20))  # 27 Sep: plans still coming in
        self.assertEqual(model.complete_weeks(counts, date(2026, 9, 27))[0], date(2026, 9, 20))  # Sunday not over


class Stewardship(unittest.TestCase):
    """roles.archetype_scope: APs, the President and Data Analysts see the mission; nobody else does."""

    def test_scopes(self):
        import roles
        self.assertEqual(roles.archetype_scope({'leadership_role': 'AP'}), 'mission')
        self.assertEqual(roles.archetype_scope({'app_role': 'PRESIDENT'}), 'mission')
        self.assertEqual(roles.archetype_scope({'leadership_role': 'DL', 'additional_roles': ['DATA_ADMIN']}), 'mission')
        self.assertIsNone(roles.archetype_scope({'leadership_role': 'ZL'}))
        self.assertIsNone(roles.archetype_scope({'leadership_role': 'STL'}))
        self.assertIsNone(roles.archetype_scope({'leadership_role': 'DL'}))
        self.assertIsNone(roles.archetype_scope({}))
        self.assertIsNone(roles.archetype_scope({'app_role': 'OFFICE'}))
        self.assertFalse(roles.capabilities({'leadership_role': 'STL'})['archetypes'])
        self.assertFalse(roles.capabilities({})['archetypes'])


def english_catalog(test):
    """The portal's English texts: portal/i18n/en.json since the round-6 interface translation (one catalog per
    language, catalogs.json lists the languages), or the older single catalogs.json with every language."""
    folder = Path(__file__).resolve().parents[2] / 'portal' / 'i18n'
    if not (folder / 'catalogs.json').exists():
        test.skipTest('portal/i18n/catalogs.json is not next to portal-api here')
    index = json.loads((folder / 'catalogs.json').read_text(encoding='utf-8'))
    english = index['messages']['en'] if 'messages' in index else json.loads((folder / 'en.json').read_text(encoding='utf-8'))
    return {value for value in english.values() if isinstance(value, str)}


class Translations(unittest.TestCase):
    """Every English default text is in the portal catalog, so it is translated while nobody has changed it."""

    def test_default_texts_are_in_the_catalog(self):
        english = english_catalog(self)
        texts = [band['name'] for band in model.DEFAULT_SETTINGS['bands']]
        texts += [label for label, _ in model.SOURCES.values()]
        diagnoses = model.DEFAULT_SETTINGS['diagnoses']
        texts += list(diagnoses['strengths'].values())
        for pattern in diagnoses['patterns'].values():
            texts += [pattern['title'], pattern['meaning'], *pattern['steps']]
        self.assertEqual([t for t in texts if t not in english], [])

    def test_server_messages_are_in_the_catalog(self):
        # Messages the pages show as they come from the server (abort texts and settings checks).
        import re
        english = english_catalog(self)
        found = []
        for name in ('archetypes.py', 'archetype_model.py'):
            source = (Path(__file__).resolve().parents[1] / name).read_text(encoding='utf-8')
            found += re.findall(r"^[A-Z_]+ = '([^']+)'", source, re.M)
            found += re.findall(r"problems\[[^\]]+\] = '([^']+)'", source)
            found += re.findall(r"super\(\).__init__\('([^']+)'\)", source)
        self.assertGreater(len(found), 25)
        self.assertEqual([m for m in found if ' ' in m and m not in english], [])  # one-word values are not texts


if __name__ == '__main__':
    unittest.main()
