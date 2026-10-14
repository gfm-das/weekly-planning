"""Archetypal Health "Compare" (round 13): the earlier period and the change, worked out by hand, without a database.
Made-up numbers only (no names).

What is checked:
- which weeks the three presets compare with (previous 4 weeks, previous 12 weeks, same period last year),
- the change: size, rounding, arrows (up, down, unchanged under half a point), a missing number,
- the page's answer (archetypes.build_page with the database calls replaced): off by default, the two ranges, and
  the earlier numbers and changes of the mission, zone, district and area rows, who may ask, a wrong preset,
- the page and the 14 catalogs have the texts (archetypes.compare*).

Hand calculation (finding only, "New People Being Taught"; four areas in two zones, two districts):
  Earlier week (13 Sep): 2, 4, 6, 8. Mission usual week: average 5, sample deviation sqrt(20/3) = 2.58199.
    Area 1: z = (2-5)/2.58199 = -1.16190 -> index 100 + 15 x -1.16190 = 82.5714. The peer group is the whole mission:
    the profiles are these z, average 0 and deviation 1, so score = z.   Areas 1 to 4: 82.57, 94.19, 105.81, 117.43.
  This week (20 Sep): 4, 6, 8, 10. Usual week of both weeks (2, 4, 6, 8, 4, 6, 8, 10): average 6, sample deviation
    sqrt(48/7) = 2.61861. Area 1: z = (4-6)/2.61861 = -0.76376 -> 88.5436.   Areas 1 to 4: 88.54, 100.00, 111.46, 122.91.
  Change: area 1 +5.9722 -> +5.97 -> 6.0 (up); area 2 +5.8095 -> 5.8; area 4 +5.4846 -> 5.5.
  Mission (average of the four areas' scores): earlier 0 -> 100.0; now (-0.76376 + 0 + 0.76376 + 1.52753) / 4 = 0.38188
    -> 105.7282, change +5.7282 -> 5.7 (up).
  Zone A (areas 1 and 2): earlier (-1.16190 - 0.38730) / 2 = -0.77460 -> 88.381; now (-0.76376 + 0) / 2 = -0.38188 ->
    94.2718; change +5.8908 -> 5.9.

Run from portal-api (the catalog check also needs portal/ next to portal-api):
  python tests/test_archetype_compare.py      (or: python -m unittest tests.test_archetype_compare)
"""
import json
import os
import sys
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault('SUPABASE_URL', 'http://supabase.invalid')
os.environ.setdefault('SUPABASE_SERVICE_ROLE_KEY', 'unit-test-only')
import archetype_model as model  # noqa: E402
import archetypes  # noqa: E402
from werkzeug.exceptions import BadRequest, Forbidden  # noqa: E402

THIS = date(2026, 9, 20)       # a Sunday
BEFORE = date(2026, 9, 13)
TODAY = date(2026, 9, 28)      # the Monday after: both weeks are complete


def settings():
    value = model.defaults()
    value['weights'] = {a: {} for a in model.ARCHETYPES}
    value['weights']['finding'] = {'friends_found': 100}
    value['peer_group'] = {'attributes': [], 'density_bins': [200, 500], 'minimum_size': 2, 'fallback': True}
    return value


# area -> (zone, district, friends earlier, friends now)
AREAS = {1: ('Zone A', 'District 1', 2, 4), 2: ('Zone A', 'District 1', 4, 6),
         3: ('Zone B', 'District 2', 6, 8), 4: ('Zone B', 'District 2', 8, 10)}


def rows(with_earlier=True, extra=()):
    found = []
    for area_id, (zone, district, earlier, now) in AREAS.items():
        place = {'mission_id': 1, 'zone_id': 10 if zone == 'Zone A' else 11, 'zone': zone,
                 'district_id': 20 if district == 'District 1' else 21, 'district': district, 'area_id': area_id,
                 'area': f'Area {area_id}', 'lessons_with_friends': None}
        if with_earlier:
            found.append(dict(place, sunday=BEFORE, friends_found=earlier))
        found.append(dict(place, sunday=THIS, friends_found=now))
    return found + list(extra)


MANAGER = {'user_id': 'u1', 'mission_id': 1, 'mission': 'Test Mission', 'app_role': 'DATA_ADMIN', 'display_name': 'Test'}


def page(week=None, weeks=None, compare=None, data=None, who=MANAGER):
    """build_page with the database replaced by made-up rows."""
    numbers = rows() if data is None else data
    with patch.object(archetypes, 'load_settings', return_value=(settings(), 3, None, None)), \
            patch.object(archetypes, 'load_numbers', return_value=(numbers, {})), \
            patch.object(archetypes, 'notes_for', return_value={}), \
            patch.object(archetypes, 'today', return_value=TODAY):
        return archetypes.build_page(None, who, week, weeks, compare)


class Presets(unittest.TestCase):
    def test_previous_4_weeks(self):
        # One week shown: the 4 weeks before it, 23 Aug to 13 Sep.
        self.assertEqual(model.compare_window('prev4', THIS, 1), (date(2026, 9, 13), 4))
        self.assertEqual(model.week_range(date(2026, 9, 13), 4), (date(2026, 8, 23), date(2026, 9, 13)))
        # 4 weeks shown (30 Aug to 20 Sep): the 4 weeks before that, 2 to 23 Aug.
        self.assertEqual(model.compare_window('prev4', THIS, 4), (date(2026, 8, 23), 4))
        self.assertEqual(model.week_range(date(2026, 8, 23), 4), (date(2026, 8, 2), date(2026, 8, 23)))

    def test_previous_12_weeks(self):
        self.assertEqual(model.compare_window('prev12', THIS, 1), (date(2026, 9, 13), 12))
        self.assertEqual(model.week_range(date(2026, 9, 13), 12), (date(2026, 6, 28), date(2026, 9, 13)))
        # 8 weeks shown (2 Aug to 20 Sep): the 12 weeks before that end on 26 Jul.
        self.assertEqual(model.compare_window('prev12', THIS, 8), (date(2026, 7, 26), 12))

    def test_same_period_last_year(self):
        # 52 weeks back is 364 days, so a Sunday stays a Sunday: 21 Sep 2025.
        end, count = model.compare_window('year', THIS, 4)
        self.assertEqual((end, count), (date(2025, 9, 21), 4))
        self.assertEqual(end.isoweekday(), 7)
        self.assertEqual(model.week_range(end, count), (date(2025, 8, 31), date(2025, 9, 21)))
        self.assertEqual(model.compare_window('year', THIS, 1), (date(2025, 9, 21), 1))

    def test_every_earlier_period_ends_before_the_one_shown(self):
        for preset in ('prev4', 'prev12'):
            for weeks in model.WEEK_CHOICES:
                end, _ = model.compare_window(preset, THIS, weeks)
                self.assertLess(end, model.week_range(THIS, weeks)[0], (preset, weeks))

    def test_a_preset_not_offered(self):
        self.assertFalse(model.is_compare_preset('prev8'))
        with self.assertRaises(ValueError):
            model.compare_window('prev8', THIS, 1)


class TheChange(unittest.TestCase):
    def test_up_down_and_unchanged(self):
        self.assertEqual(model.delta(105.0, 100.0), {'delta': 5.0, 'direction': 'up'})
        self.assertEqual(model.delta(92.34, 100.0), {'delta': -7.7, 'direction': 'down'})
        self.assertEqual(model.delta(100.4, 100.0)['direction'], 'flat')       # under half a point
        self.assertEqual(model.delta(99.6, 100.0)['direction'], 'flat')
        self.assertEqual(model.delta(100.5, 100.0)['direction'], 'up')         # half a point counts
        self.assertEqual(model.delta(99.5, 100.0)['direction'], 'down')

    def test_rounding_to_one_decimal_and_no_minus_zero(self):
        self.assertEqual(model.delta(88.5436, 82.5714)['delta'], 6.0)
        self.assertEqual(model.delta(100.04, 100.0)['delta'], 0.0)
        self.assertEqual(str(model.delta(99.96, 100.0)['delta']), '0.0')       # not -0.0

    def test_a_missing_number_has_no_change(self):
        self.assertIsNone(model.delta(None, 100.0))
        self.assertIsNone(model.delta(100.0, None))
        self.assertIsNone(model.change({'overall': 100.0, 'indices': {}}, None))
        now = {'overall': 90.0, 'indices': {a: None for a in model.ARCHETYPES}}
        before = {'overall': None, 'indices': {a: None for a in model.ARCHETYPES}}
        result = model.change(now, before)
        self.assertIsNone(result['overall'])
        self.assertTrue(all(value is None for value in result['indices'].values()))


class ThePageAnswer(unittest.TestCase):
    def setUp(self):
        self.data = page(compare='prev4')
        self.by_id = {a['id']: a for a in self.data['areas']}

    def test_off_by_default(self):
        plain = page()
        self.assertIsNone(plain['compare'])
        self.assertTrue(all('compare' not in row for row in plain['areas'] + plain['zones'] + plain['districts']))
        self.assertNotIn('compare', plain['mission'])
        self.assertEqual(plain['compare_presets'], ['prev4', 'prev12', 'year'])
        self.assertEqual(page(compare='')['compare'], None)

    def test_the_numbers_of_the_week_shown_do_not_change_when_compare_is_on(self):
        plain = page()
        self.assertEqual([a['indices'] for a in plain['areas']], [a['indices'] for a in self.data['areas']])
        self.assertEqual(plain['mission']['overall'], self.data['mission']['overall'])
        self.assertEqual(plain['week'], self.data['week'])

    def test_the_two_ranges(self):
        c = self.data['compare']
        self.assertEqual(c['preset'], 'prev4')
        self.assertTrue(c['has_data'])
        self.assertEqual(c['current'], {'from': '2026-09-20', 'to': '2026-09-20', 'weeks': 1})
        self.assertEqual(c['previous'], {'from': '2026-08-23', 'to': '2026-09-13', 'weeks': 4})
        year = page(compare='year', weeks='4')['compare']
        self.assertEqual(year['current'], {'from': '2026-08-30', 'to': '2026-09-20', 'weeks': 4})
        self.assertEqual(year['previous'], {'from': '2025-08-31', 'to': '2025-09-21', 'weeks': 4})
        self.assertFalse(year['has_data'])      # no numbers a year ago in this data

    def test_area_rows_by_hand(self):
        one = self.by_id[1]
        self.assertAlmostEqual(one['indices']['finding'], 88.5, places=1)
        self.assertAlmostEqual(one['compare']['previous']['overall'], 82.6, places=1)
        self.assertEqual(one['compare']['change']['overall'], {'delta': 6.0, 'direction': 'up'})
        self.assertEqual(one['compare']['change']['indices']['finding'], {'delta': 6.0, 'direction': 'up'})
        self.assertIsNone(one['compare']['change']['indices']['teaching'])   # no numbers for it in either period
        self.assertEqual(self.by_id[2]['compare']['change']['overall'], {'delta': 5.8, 'direction': 'up'})
        self.assertEqual(self.by_id[4]['compare']['change']['overall'], {'delta': 5.5, 'direction': 'up'})
        self.assertAlmostEqual(self.by_id[4]['compare']['previous']['overall'], 117.4, places=1)

    def test_mission_zone_and_district_rows_by_hand(self):
        mission = self.data['mission']['compare']
        self.assertEqual(mission['previous']['overall'], 100.0)
        self.assertAlmostEqual(self.data['mission']['overall'], 105.7, places=1)
        self.assertEqual(mission['change']['overall'], {'delta': 5.7, 'direction': 'up'})
        zones = {z['name']: z for z in self.data['zones']}
        self.assertAlmostEqual(zones['Zone A']['compare']['previous']['overall'], 88.4, places=1)
        self.assertAlmostEqual(zones['Zone A']['overall'], 94.3, places=1)
        self.assertEqual(zones['Zone A']['compare']['change']['overall'], {'delta': 5.9, 'direction': 'up'})
        districts = {d['name']: d for d in self.data['districts']}
        # District 1 holds the same two areas as Zone A in this data.
        self.assertEqual(districts['District 1']['compare']['change']['overall'], {'delta': 5.9, 'direction': 'up'})

    def test_a_down_arrow(self):
        # Everyone's numbers fall: the same four areas, this week 2, 4, 6, 8 and the week before 4, 6, 8, 10.
        falling = []
        for area_id, (zone, district, earlier, now) in AREAS.items():
            place = {'mission_id': 1, 'zone_id': 10, 'zone': 'Zone A', 'district_id': 20, 'district': 'District 1',
                     'area_id': area_id, 'area': f'Area {area_id}', 'lessons_with_friends': None}
            falling += [dict(place, sunday=BEFORE, friends_found=now), dict(place, sunday=THIS, friends_found=earlier)]
        data = page(compare='prev4', data=falling)
        by_id = {a['id']: a for a in data['areas']}
        self.assertEqual(by_id[1]['compare']['change']['overall']['direction'], 'down')
        self.assertLess(by_id[1]['compare']['change']['overall']['delta'], 0)
        self.assertEqual(data['mission']['compare']['change']['overall']['direction'], 'down')

    def test_an_area_new_this_week_has_nothing_to_compare_with(self):
        new = {'mission_id': 1, 'zone_id': 10, 'zone': 'Zone A', 'district_id': 20, 'district': 'District 1',
               'area_id': 5, 'area': 'Area 5', 'lessons_with_friends': None, 'sunday': THIS, 'friends_found': 5}
        data = page(compare='prev4', data=rows(extra=[new]))
        five = next(a for a in data['areas'] if a['id'] == 5)
        self.assertIsNone(five['compare']['previous'])
        self.assertIsNone(five['compare']['change'])
        self.assertIsNotNone(five['overall'])

    def test_no_numbers_in_the_earlier_period(self):
        data = page(compare='prev12', data=rows(with_earlier=False))
        self.assertFalse(data['compare']['has_data'])
        for row in data['areas'] + data['zones'] + data['districts'] + [data['mission']]:
            self.assertIsNone(row['compare']['previous'])
            self.assertIsNone(row['compare']['change'])

    def test_a_wrong_preset_is_refused(self):
        with self.assertRaises(BadRequest) as caught:
            page(compare='last-month')
        self.assertEqual(caught.exception.description, archetypes.BAD_COMPARE)

    def test_the_same_people_may_ask_as_before(self):
        for who in ({'user_id': 'u2', 'mission_id': 1, 'app_role': 'MISSIONARY'},
                    {'user_id': 'u3', 'mission_id': 1, 'app_role': 'MISSIONARY', 'leadership_role': 'ZL'},
                    {'user_id': 'u4', 'mission_id': 1, 'app_role': 'OFFICE'}):
            with self.assertRaises(Forbidden):
                page(compare='prev4', who=who)

    def test_the_answer_is_json_ready(self):
        json.dumps(self.data)


class TheTexts(unittest.TestCase):
    KEYS = ('archetypes.compare', 'archetypes.compareWith', 'archetypes.comparePrev4', 'archetypes.comparePrev12',
            'archetypes.compareYear', 'archetypes.compareRanges', 'archetypes.compareNoData', 'archetypes.compareLegend',
            'archetypes.changeUp', 'archetypes.changeDown', 'archetypes.changeFlat', 'archetypes.wasValue',
            'archetypes.dateRange', 'archetypes.chooseOneOfTheComparisonsOffered')

    def test_the_14_catalogs_have_them(self):
        folder = Path(__file__).resolve().parents[2] / 'portal' / 'i18n'
        if not folder.exists():
            return self.skipTest('portal/ not found next to portal-api')
        codes = ['en', 'de', 'es', 'fr', 'pt', 'uk', 'ru', 'it', 'tr', 'fa', 'ro', 'sv', 'da', 'ar']
        for code in codes:
            catalog = json.loads((folder / f'{code}.json').read_text(encoding='utf-8'))
            for key in self.KEYS:
                self.assertTrue(str(catalog.get(key, '')).strip(), f'{code} {key}')
        english = json.loads((folder / 'en.json').read_text(encoding='utf-8'))
        self.assertEqual(english['archetypes.chooseOneOfTheComparisonsOffered'], archetypes.BAD_COMPARE)

    def test_the_page_has_the_switch(self):
        html = Path(__file__).resolve().parents[2] / 'portal' / 'archetypes.html'
        if not html.exists():
            return self.skipTest('portal/ not found next to portal-api')
        text = html.read_text(encoding='utf-8')
        for piece in ('id="compare"', 'id="comparePreset"', "query.set('compare'", 'archetypes.compareRanges'):
            self.assertTrue(piece in text, f'archetypes.html lacks {piece}')
        # Off by default: nothing is asked for unless the person switched it on.
        self.assertTrue("compare: ''" in text, "archetypes.html: compare starts as ''")
        self.assertTrue("if (state.compare) query.set('compare'" in text, 'the request carries compare only when it is on')


if __name__ == '__main__':
    unittest.main()
