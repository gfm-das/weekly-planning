"""Unit checks for database charts (charts.py) without a database: the spec (shared vectors with the Slidev
manager), the SQL whitelist, audience filtering, the pivot and transforms, and who may ask for what.

Run in the portal-api image (no pytest needed), with the slidev test vectors mounted:
  docker run --rm -v <repo>/portal-api:/app -v <repo>/slidev/tests/fixtures:/fixtures -w /app gfm-portal-portal-api python tests/test_charts.py
(CHART_SPEC_VECTORS may name the vectors file instead; without it the vector checks look next to the repo.)
"""
import json
import os
import sys
import time
import unittest
import uuid
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from unittest.mock import patch

from psycopg2 import sql

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault('SUPABASE_URL', 'http://supabase.invalid')
os.environ.setdefault('SUPABASE_SERVICE_ROLE_KEY', 'unit-test-only')
os.environ['PORTAL_SERVICE_KEY'] = 'unit-service-key'
import app  # noqa: E402
import charts  # noqa: E402
import roles  # noqa: E402


def vectors_file():
    for candidate in (os.environ.get('CHART_SPEC_VECTORS'), '/fixtures/chart-spec-vectors.json',
                      Path(__file__).resolve().parents[2] / 'slidev' / 'tests' / 'fixtures' / 'chart-spec-vectors.json'):
        if candidate and Path(candidate).is_file():
            return Path(candidate)
    return None


def render(query):
    """psycopg2.sql objects as text without a connection (identifiers in double quotes)."""
    if isinstance(query, sql.Composed):
        return ''.join(render(part) for part in query.seq)
    if isinstance(query, sql.SQL):
        return query.string
    if isinstance(query, sql.Identifier):
        return '.'.join('"%s"' % s.replace('"', '""') for s in query.strings)
    if isinstance(query, sql.Literal):
        return repr(query.wrapped)
    raise TypeError(type(query))


class Spec(unittest.TestCase):
    def test_shared_vectors(self):
        path = vectors_file()
        if not path:
            self.skipTest('slidev/tests/fixtures/chart-spec-vectors.json is not mounted')
        data = json.loads(path.read_text(encoding='utf-8'))
        self.assertGreaterEqual(len(data['valid']), 9)
        for v in data['valid']:
            spec = charts.normalize_spec(v['input'])  # every valid vector uses real measure names
            self.assertEqual(charts.canonical_json(spec), v['canonical'], v['name'])
            self.assertEqual(charts.spec_hash(spec), v['sha256'], v['name'])
            self.assertEqual(charts.canonical_json(charts.normalize_spec(spec)), v['canonical'], v['name'])
        for v in data['invalid']:
            with self.assertRaises(ValueError, msg=v['name']) as caught:
                charts.normalize_spec(v['input'], whitelist=False)
            self.assertEqual(str(caught.exception), v['error'], v['name'])

    def test_whitelist(self):
        with self.assertRaisesRegex(ValueError, 'Unknown number: people.names'):
            charts.normalize_spec({'measures': ['people.names']})
        with self.assertRaisesRegex(ValueError, 'also choose a goal'):
            charts.normalize_spec({'measures': ['friends_found.actual'], 'transform': 'pct_of_goal'})
        with self.assertRaisesRegex(ValueError, 'numbers with a goal'):
            charts.normalize_spec({'measures': ['new_members.total'], 'transform': 'pct_of_goal'})
        ok = charts.normalize_spec({'measures': ['lessons_with_friends.actual', 'lessons_with_friends.goal'],
                                    'transform': 'pct_of_goal'})
        self.assertEqual(charts.goal_pairs(ok['measures']), [('lessons_with_friends.actual', 'lessons_with_friends.goal')])
        both = ['friends_found.actual', 'friends_found.goal', 'friends_found.previous_goal']
        self.assertEqual(charts.goal_pairs(both), [('friends_found.actual', 'friends_found.previous_goal')],
                         'the goal set the week before comes first, as in Call-ins')

    def test_a_long_measure_list_is_refused_before_it_is_read(self):
        started = time.perf_counter()
        for size in (33, 60000, 400000):
            with self.assertRaisesRegex(ValueError, r'^Choose at most 8 numbers for one chart\.$'):
                charts.normalize_spec({'measures': [f'm{i}.actual' for i in range(size)]})
        self.assertLess(time.perf_counter() - started, 2, 'no work per entry beyond building the list')
        repeats = charts.normalize_spec({'measures': ['friends_found.actual'] * 20 + ['friends_found.goal'] * 12})
        self.assertEqual(repeats['measures'], ['friends_found.actual', 'friends_found.goal'])
        with self.assertRaisesRegex(ValueError, 'not written like'):
            charts.normalize_spec({'measures': ['friends_found.actual\n']})

    def test_labels_are_what_people_see_and_ids_stay(self):
        # Round 3: "Friends found" is called "New people being taught" (Preach My Gospel); the id stays.
        self.assertEqual(charts.MEASURES['friends_found.actual']['label'], 'New people being taught')
        self.assertEqual(charts.MEASURES['friends_found.previous_goal']['label'],
                         'New people being taught: goal set the week before')
        self.assertEqual(charts.MEASURES['friends_found.goal']['label'], "New people being taught: next week's goal")
        self.assertEqual(charts.MEASURES['friends_found.goal']['short'], "Next week's goal")
        self.assertEqual(charts.MEASURES['friends_found.actual']['column'], 'friends_found_actual')
        self.assertEqual(charts.MEASURES['new_members.with_minister']['short'], 'Ministering brothers or sisters')
        for m in charts.MEASURES.values():
            self.assertNotRegex(m['label'] + m['short'], r'(?i)friends found')

    def test_a_label_is_not_part_of_the_pinned_hash(self):
        # Hashes of charts written before the rename (README example and the showcase's stewardship chart,
        # computed with the round-2 code): decks pin these, so they must never change because of a label.
        example = charts.normalize_spec({'measures': ['friends_found.actual', 'friends_found.previous_goal']})
        self.assertEqual(charts.spec_hash(example), '0cd9a7321eddf1507cdfa1b5857dd2595ebff2cd7fb39fe18671f5e1ea759784')
        steward = charts.normalize_spec({'measures': ['friends_found.actual'], 'level': 'area', 'by': 'unit', 'weeks': 4,
                                         'sort': 'desc', 'top': 10, 'audience': 'stewardship'})
        self.assertEqual(charts.spec_hash(steward), '01da168c434e99ed234629172b04ad83eb264bcd3812ddc957554ae09956d854')
        self.assertNotIn('label', charts.canonical_json(example))

    def test_measures_are_counts_or_key_indicators_only(self):
        for m in charts.MEASURES.values():
            self.assertRegex(m['column'], r'^[a-z0-9_]+$')
            self.assertNotRegex(m['column'], r'name|note|email|person|user')
        self.assertEqual(charts.MEASURES['friends_found.previous_goal']['kind'], 'goal')
        self.assertEqual(charts.MEASURES['new_members.at_church']['source'], 'people')


class Queries(unittest.TestCase):
    def test_data_query_uses_only_whitelisted_names(self):
        spec = charts.normalize_spec({'measures': ['friends_found.actual', 'friends_found.previous_goal', 'new_members.total'],
                                      'level': 'district', 'filter': {'zones': [5], 'districts': [51, 52]}})
        query, args, columns = charts.data_query('kpi', 'district', spec['measures'], 2, ['2026-09-20'], spec['filter'], {51})
        text = render(query)
        self.assertEqual(text, 'SELECT "sunday", "district_id", "district", "areas_reporting", "friends_found_actual", '
                               '"friends_found_previous_goal" FROM "dashboards"."kpi_district_week" WHERE mission_id = %s '
                               'AND sunday = ANY(%s::date[]) AND "zone_id" = ANY(%s::bigint[]) AND "district_id" = '
                               'ANY(%s::bigint[]) AND "district_id" = ANY(%s::bigint[]) ORDER BY sunday, "district_id" '
                               'LIMIT 20001')
        self.assertEqual(args, [2, ['2026-09-20'], [5], [51, 52], [51]])
        people, _, _ = charts.data_query('people', 'area', spec['measures'], 2, [], {}, None)
        self.assertIn('FROM "dashboards"."people_area_week"', render(people))
        self.assertIn('"new_members"', render(people))
        self.assertNotIn('friends_found', render(people))
        area_kpi, _, cols = charts.data_query('kpi', 'area', ['plans.started'], 2, [], {}, None)
        self.assertIn('"kpi_area_total_week"', render(area_kpi))
        self.assertEqual(cols.count('reports'), 1, 'the plan count doubles as the per-area denominator')

    def test_every_measure_and_level_names_a_view_column(self):
        for level in charts.LEVELS:
            for m in charts.MEASURES:
                source = charts.MEASURES[m]['source']
                query, _, columns = charts.data_query(source, level, [m], 1, [], {}, None)
                self.assertIn(charts.MEASURES[m]['column'], columns)
                self.assertIn(f'"dashboards"."{(charts.KPI_VIEWS if source == "kpi" else charts.PEOPLE_VIEWS)[level]}"',
                              render(query))

    def test_week_query(self):
        query, args = charts.week_query(2, date(2026, 9, 27), 12, False)
        self.assertEqual(render(query), 'SELECT sunday FROM "dashboards"."people_mission_week" WHERE mission_id = %s AND '
                                        'sunday < %s ORDER BY sunday DESC LIMIT %s')
        self.assertEqual(args, [2, date(2026, 9, 27), 12])


AREAS = [{'id': 511, 'district_id': 51, 'zone_id': 5}, {'id': 512, 'district_id': 51, 'zone_id': 5},
         {'id': 521, 'district_id': 52, 'zone_id': 5}, {'id': 611, 'district_id': 61, 'zone_id': 6}]


class Audience(unittest.TestCase):
    def test_whole_mission_keeps_the_chart(self):
        self.assertEqual(charts.stewardship_units('zone', AREAS, {511, 512, 521, 611}), ('zone', None))

    def test_zone_leader(self):
        zl = {511, 512, 521}
        self.assertEqual(charts.stewardship_units('zone', AREAS, zl), ('zone', {5}))
        self.assertEqual(charts.stewardship_units('mission', AREAS, zl), ('zone', {5}))
        self.assertEqual(charts.stewardship_units('district', AREAS, zl), ('district', {51, 52}))
        self.assertEqual(charts.stewardship_units('area', AREAS, zl), ('area', {511, 512, 521}))

    def test_district_leader_never_gets_a_partial_zone(self):
        dl = {511, 512}
        self.assertEqual(charts.stewardship_units('zone', AREAS, dl), ('district', {51}))
        self.assertEqual(charts.stewardship_units('mission', AREAS, dl), ('district', {51}))
        self.assertEqual(charts.stewardship_units('area', AREAS, dl), ('area', {511, 512}))

    def test_nobody(self):
        self.assertEqual(charts.stewardship_units('zone', AREAS, set()), ('area', set()))


def kpi_row(sunday, unit, name, actual, goal, areas=2):
    return {'sunday': date.fromisoformat(sunday), 'zone_id': unit, 'zone': name, 'areas_reporting': areas,
            'friends_found_actual': actual, 'friends_found_previous_goal': goal}


class Table(unittest.TestCase):
    weeks = ['2026-09-06', '2026-09-13', '2026-09-20']

    def rows(self):
        return {'kpi': [kpi_row(w, u, n, a, g) for w, u, n, a, g in [
            ('2026-09-06', 5, 'South', 4, 5), ('2026-09-06', 6, 'North', 10, 8),
            ('2026-09-13', 5, 'South', 6, 5), ('2026-09-13', 6, 'North', None, 8),
            ('2026-09-20', 5, 'South', 8, 10), ('2026-09-20', 6, 'North', 2, 4)]]}

    def spec(self, **extra):
        return charts.normalize_spec({'measures': ['friends_found.actual', 'friends_found.previous_goal'],
                                      'level': 'zone', **extra})

    def test_by_week_one_series_per_unit_and_measure(self):
        table, units = charts.build_table(self.spec(), 'zone', self.weeks, self.rows(), set())
        self.assertEqual(units, 2)
        self.assertEqual(table['labels'], self.weeks)
        self.assertEqual([s['name'] for s in table['series']],
                         ['North · New people being taught', 'North · Goal set the week before',
                          'South · New people being taught', 'South · Goal set the week before'])
        self.assertEqual(table['series'][0]['values'], [10, None, 2])
        self.assertEqual(table['series'][1]['role'], 'goal')

    def test_by_unit_sorted_top_and_percent(self):
        spec = self.spec(by='unit', transform='pct_of_goal', sort='desc', top=1)
        table, _ = charts.build_table(spec, 'zone', self.weeks, self.rows(), set())
        # North 12/12 = 100 % (its week without a number is left out on both sides) beats South 18/20 = 90 %.
        self.assertEqual(table['labels'], ['North'])
        self.assertEqual(table['series'], [{'name': 'New people being taught', 'values': [100]}])
        ascending, _ = charts.build_table(self.spec(by='unit', transform='pct_of_goal', sort='asc'), 'zone', self.weeks,
                                          self.rows(), set())
        self.assertEqual(ascending['labels'], ['South', 'North'])
        self.assertEqual(ascending['series'][0]['values'], [90, 100])

    def test_percent_by_unit_uses_only_weeks_with_a_goal(self):
        """A week with a number but no goal (nobody set one) must not inflate '% of goal' per unit."""
        rows = {'kpi': [kpi_row('2026-09-13', 5, 'South', 5, None), kpi_row('2026-09-20', 5, 'South', 5, 5),
                        kpi_row('2026-09-13', 6, 'North', 3, 0), kpi_row('2026-09-20', 6, 'North', 2, 4)]}
        weeks = ['2026-09-13', '2026-09-20']
        by_week, _ = charts.build_table(self.spec(transform='pct_of_goal'), 'zone', weeks, rows, set())
        self.assertEqual([s['values'] for s in by_week['series']], [[None, 50], [None, 100]])  # North, South
        by_unit, _ = charts.build_table(self.spec(by='unit', transform='pct_of_goal'), 'zone', weeks, rows, set())
        self.assertEqual(by_unit['labels'], ['North', 'South'])
        self.assertEqual(by_unit['series'][0]['values'], [50, 100], 'not 125 % and 200 %')
        no_goal = {'kpi': [kpi_row('2026-09-20', 5, 'South', 5, None)]}
        empty, _ = charts.build_table(self.spec(by='unit', transform='pct_of_goal'), 'zone', ['2026-09-20'], no_goal, set())
        self.assertEqual(empty['series'][0]['values'], [None], 'no goal in any week: nothing to compare with')

    def test_cumulative_rolling_and_per_area(self):
        cumulative, _ = charts.build_table(self.spec(transform='cumulative'), 'zone', self.weeks, self.rows(), set())
        self.assertEqual(cumulative['series'][0]['values'], [10, 10, 12], 'a week without a plan adds nothing')
        per_area, _ = charts.build_table(self.spec(transform='per_area'), 'zone', self.weeks, self.rows(), set())
        self.assertEqual(per_area['series'][2]['values'], [2, 3, 4])
        four = ['2026-08-16', '2026-08-23', '2026-08-30'] + self.weeks
        rows = self.rows()
        rows['kpi'] += [kpi_row(w, 5, 'South', 2, 1) for w in four[:3]]
        rolling, _ = charts.build_table(self.spec(transform='rolling4'), 'zone', four, rows, set())
        self.assertEqual(rolling['labels'], self.weeks)
        self.assertEqual(rolling['series'][2]['values'], [2.5, 3.5, 5])

    def test_hidden_people_numbers_stay_hidden(self):
        spec = charts.normalize_spec({'measures': ['new_members.total'], 'level': 'area', 'by': 'unit', 'weeks': 2,
                                      'audience': 'deck'})
        rows = {'people': [
            {'sunday': date(2026, 9, 13), 'area_id': 1, 'area': 'A', 'areas_reporting': 1, 'new_members': 5},
            {'sunday': date(2026, 9, 20), 'area_id': 1, 'area': 'A', 'areas_reporting': 1, 'new_members': None},
            {'sunday': date(2026, 9, 13), 'area_id': 2, 'area': 'B', 'areas_reporting': 1, 'new_members': 4},
            {'sunday': date(2026, 9, 20), 'area_id': 2, 'area': 'B', 'areas_reporting': 1, 'new_members': 3}]}
        table, _ = charts.build_table(spec, 'area', ['2026-09-13', '2026-09-20'], rows, {'new_members.total'})
        self.assertEqual(table['series'][0]['values'], [None, 7], 'a sum over a hidden number is hidden too')
        weekly = charts.normalize_spec({**spec, 'by': 'week', 'transform': 'cumulative', 'sort': 'none', 'top': 0})
        table, _ = charts.build_table(weekly, 'area', ['2026-09-13', '2026-09-20'], rows, {'new_members.total'})
        self.assertEqual(table['series'][0]['values'], [5, None])

    def test_a_goal_nobody_set_is_left_out(self):
        rows = {'kpi': [kpi_row('2026-09-13', 5, 'South', 4, 0), kpi_row('2026-09-20', 5, 'South', 6, 5)]}
        table, _ = charts.build_table(self.spec(), 'zone', ['2026-09-13', '2026-09-20'], rows, set())
        self.assertEqual(table['series'][1]['values'], [None, 5])
        pct, _ = charts.build_table(self.spec(transform='pct_of_goal'), 'zone', ['2026-09-13', '2026-09-20'], rows, set())
        self.assertEqual(pct['series'][0]['values'], [None, 120])

    def test_too_many_series(self):
        rows = {'kpi': [kpi_row('2026-09-20', u, f'Z{u:02}', 1, 1) for u in range(30)]}
        with self.assertRaisesRegex(ValueError, r'would draw 60 lines. Choose some zones \(at most 20\), or show one bar per zone'):
            charts.build_table(self.spec(), 'zone', ['2026-09-20'], rows, set())
        by_unit, _ = charts.build_table(self.spec(by='unit'), 'zone', ['2026-09-20'], rows, set())
        self.assertEqual(len(by_unit['labels']), 30)


# ---- the endpoints, with stand-ins for the database ------------------------------------------------------------

CONTEXTS = {
    'ap': {'user_active': True, 'mission_id': 1, 'app_role': 'AP', 'leadership_role': 'AP', 'zone_id': 6, 'district_id': 61, 'area_id': 611},
    'dl': {'user_active': True, 'mission_id': 1, 'app_role': 'MISSIONARY', 'leadership_role': 'DL', 'leadership_district_id': 51, 'zone_id': 5, 'district_id': 51, 'area_id': 511},
    'zl': {'user_active': True, 'mission_id': 1, 'app_role': 'MISSIONARY', 'leadership_role': 'ZL', 'leadership_zone_id': 5, 'zone_id': 5, 'district_id': 51, 'area_id': 512},
    'stl': {'user_active': True, 'mission_id': 1, 'app_role': 'MISSIONARY', 'leadership_role': 'STL', 'leadership_zone_id': 5, 'zone_id': 5, 'district_id': 52, 'area_id': 521},
    'zl6': {'user_active': True, 'mission_id': 1, 'app_role': 'MISSIONARY', 'leadership_role': 'ZL', 'leadership_zone_id': 6, 'zone_id': 6, 'district_id': 61, 'area_id': 611},
    'dl_da': {'user_active': True, 'mission_id': 1, 'app_role': 'MISSIONARY', 'leadership_role': 'DL', 'leadership_district_id': 51, 'zone_id': 5, 'district_id': 51, 'area_id': 511, 'additional_roles': ['DATA_ADMIN']},
    'missionary': {'user_active': True, 'mission_id': 1, 'app_role': 'MISSIONARY', 'leadership_role': None, 'zone_id': 5, 'district_id': 51, 'area_id': 511},
    'office': {'user_active': True, 'mission_id': 1, 'app_role': 'OFFICE', 'leadership_role': None, 'zone_id': 6, 'area_id': 611},
}


class FakeCursor:
    def __init__(self, conn):
        self.conn = conn
        self.result = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, query, args=None):
        text = render(query) if not isinstance(query, str) else query
        self.conn.log.append(text)
        if 'GROUP BY sunday' in text:  # charts.stewardship_kpis: a leader's own totals
            self.conn.kpi_calls.append((text, args))
            self.result = [dict({f'{k}_{f}': None for k in app.KPI_KEYS for f in ('actual', 'previous_goal')},
                                sunday=date(2026, 9, 20), friends_found_actual=7, friends_found_previous_goal=6)]
        elif 'people_mission_week' in text and text.startswith('SELECT sunday FROM'):
            self.result = [{'sunday': date(2026, 9, 20)}, {'sunday': date(2026, 9, 13)}]
        elif 'FROM "dashboards"' in text:
            self.conn.data_args.append(args)
            unit_filter = args[-1] if len(args) > 2 and isinstance(args[-1], list) else None
            rows = [{'sunday': date(2026, 9, 13), 'district_id': 51, 'district': 'D51', 'zone_id': 5, 'zone': 'Z5',
                     'mission_id': 1, 'areas_reporting': 2, 'friends_found_actual': 3},
                    {'sunday': date(2026, 9, 20), 'district_id': 51, 'district': 'D51', 'zone_id': 5, 'zone': 'Z5',
                     'mission_id': 1, 'areas_reporting': 2, 'friends_found_actual': 4},
                    {'sunday': date(2026, 9, 20), 'district_id': 61, 'district': 'D61', 'zone_id': 6, 'zone': 'Z6',
                     'mission_id': 1, 'areas_reporting': 1, 'friends_found_actual': 9}]
            self.result = [r for r in rows if not unit_filter or r.get('district_id') in unit_filter or r.get('zone_id') in unit_filter]
        else:
            self.result = []

    def fetchall(self):
        return self.result


class FakeConn:
    def __init__(self):
        self.log, self.data_args, self.kpi_calls, self.commits, self.rollbacks = [], [], [], 0, 0

    def cursor(self):
        return FakeCursor(self)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


class Endpoints(unittest.TestCase):
    def setUp(self):
        self.conn = FakeConn()
        self.who = 'ap'
        self.rule = None

        @contextmanager
        def fake_db():
            yield self.conn

        def fake_rows(conn, query, args=()):
            if 'kpi_mission_week' in query:  # the mission totals (managers only)
                self.conn.log.append(query)
                return [dict({f'{k}_{f}': None for k in app.KPI_KEYS for f in ('actual', 'previous_goal')},
                             sunday=date(2026, 9, 20), friends_found_actual=99, friends_found_previous_goal=90)]
            if 'current_reporting_sunday' in query:
                return [{'sunday': date(2026, 9, 20)}]
            if 'presentation_access' in query:
                return [dict({'deck_slug': 'council', 'owner_zone_id': None}, **self.rule)] if self.rule else []
            if query.startswith('SELECT id, name FROM public.zones'):  # the chart builder's lists
                return [{'id': 5, 'name': 'Z5'}, {'id': 6, 'name': 'Z6'}]
            if query.startswith('SELECT d.id, d.name, d.zone_id FROM public.districts'):
                return [{'id': d, 'name': f'D{d}', 'zone_id': d // 10} for d in (51, 52, 61)]
            if query.startswith('SELECT a.id, a.name, a.district_id'):
                return [dict(a, name=f"A{a['id']}") for a in AREAS]
            if 'FROM public.areas' in query and 'z.mission_id = %s' in query:
                return AREAS
            if 'FROM public.zones' in query:
                return [{'id': 5, 'name': 'Z5'}]
            return []

        def fake_scope(conn, c, *args):
            # app.scope_areas: managers the mission, DL the district, ZL/STL the zone, else the own area.
            if roles.is_manager(c):
                return AREAS
            if c.get('leadership_role') == 'DL':
                return [a for a in AREAS if a['district_id'] == 51]
            if c.get('leadership_role') in ('ZL', 'STL'):
                return [a for a in AREAS if a['zone_id'] == 5]
            return [a for a in AREAS if a['id'] == c.get('area_id')]

        def fake_context(conn, user_id):
            return dict(CONTEXTS[self.who], user_id=user_id)

        patches = [patch.object(app, 'db', fake_db), patch.object(app, 'rows', fake_rows),
                   patch.object(app, 'scope_areas', fake_scope), patch.object(app, 'context_for', fake_context)]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.client = app.app.test_client()

    def post(self, path, body, key='unit-service-key'):
        headers = {'X-Service-Key': key} if key else {}
        response = self.client.post(path, json={'user_id': str(uuid.uuid4()), **body}, headers=headers)
        return response.status_code, response.get_json()

    def data(self, spec, **extra):
        return self.post('/internal/presentations/chart-data', {'spec': spec, **extra})

    def test_service_key_is_required(self):
        self.assertEqual(self.data({'measures': ['friends_found.actual']}, )[0], 200)
        self.assertEqual(self.post('/internal/presentations/chart-data', {'spec': {}}, key=None)[0], 403)
        self.assertEqual(self.post('/internal/presentations/chart-data', {'spec': {}}, key='wrong')[0], 403)
        self.assertEqual(self.post('/internal/presentations/chart-catalog', {}, key=None)[0], 403)

    def test_manager_gets_any_whitelisted_chart_as_the_reader(self):
        status, body = self.data({'measures': ['friends_found.actual'], 'level': 'district', 'audience': 'deck'})
        self.assertEqual(status, 200)
        self.assertEqual(body['meta']['level'], 'district')
        self.assertEqual([s['name'] for s in body['table']['series']], ['D51', 'D61'])
        self.assertEqual(body['meta']['hash'], charts.spec_hash(charts.normalize_spec(
            {'measures': ['friends_found.actual'], 'level': 'district', 'audience': 'deck'})))
        log = self.conn.log
        start = log.index('SET TRANSACTION READ ONLY')
        self.assertEqual(log[start:start + 3], ['SET TRANSACTION READ ONLY', 'SET LOCAL ROLE gfm_dashboard_reader',
                                                "SET LOCAL statement_timeout = '5s'"])
        self.assertTrue(all('"dashboards".' in q for q in log[start + 3:]), log)
        self.assertEqual(self.conn.rollbacks, 1)
        self.assertEqual(self.data({'measures': ['people.names']})[0], 400)

    def test_viewer_needs_a_pinned_chart_of_a_deck_they_may_open(self):
        self.who = 'stl'
        spec = {'measures': ['friends_found.actual'], 'level': 'mission'}
        self.assertEqual(self.data(spec)[0], 403, 'no deck')
        self.assertEqual(self.data(spec, deck='council', pinned=False)[0], 403, 'not pinned')
        self.assertEqual(self.data(spec, deck='council', pinned=True)[0], 403, 'deck not shared with STLs')
        self.rule = {'roles': ['STL'], 'zone_ids': [], 'district_ids': [], 'user_ids': [], 'everyone': False}
        self.assertEqual(self.data(spec, deck='council', pinned='yes')[0], 403, 'pinned must be true')
        status, body = self.data(spec, deck='council', pinned=True)
        self.assertEqual(status, 200)
        # Round 6: a mission chart ("deck" audience by default) shows an STL only their zone, never the mission.
        self.assertTrue(body['meta']['stewardship'])
        self.assertEqual(body['meta']['level'], 'zone')
        self.assertEqual(self.conn.data_args[-1][-1], [5])

    def test_dls_open_shared_decks_with_only_their_district(self):
        # A DL opens a deck shared with them (as since round 2) and sees only their own district's numbers; they
        # build no charts (round 7: the chart builder is for managers and a zone's ZL/STL).
        self.who = 'dl'
        self.rule = {'roles': ['DL', 'ZL', 'STL'], 'zone_ids': [], 'district_ids': [], 'user_ids': [], 'everyone': True}
        status, body = self.data({'measures': ['friends_found.actual'], 'level': 'mission'}, deck='council', pinned=True)
        self.assertEqual((status, body['meta']['level'], body['meta']['stewardship']), (200, 'district', True))
        self.assertEqual(self.conn.data_args[-1][-1], [51])
        self.assertEqual(self.post('/internal/presentations/chart-catalog', {})[0], 403)

    def test_zone_deck_editors_may_try_any_chart_and_see_only_their_zone(self):
        # Round 7: the ZL and STL of the zone that owns the deck build its charts (not pinned yet).
        self.rule = {'roles': [], 'zone_ids': [], 'district_ids': [], 'user_ids': [], 'everyone': False, 'owner_zone_id': 5}
        mission = {'measures': ['friends_found.actual'], 'level': 'mission'}
        for who in ('zl', 'stl'):
            self.who = who
            status, body = self.data(mission, deck='council')
            self.assertEqual((status, body['meta']['level'], body['meta']['stewardship']), (200, 'zone', True), who)
            self.assertEqual(self.conn.data_args[-1][-1], [5], who)
            # Another zone's districts: nothing of that zone (their filter AND the leader's own districts).
            status, body = self.data({'measures': ['friends_found.actual'], 'level': 'district',
                                      'filter': {'zones': [6]}}, deck='council')
            self.assertEqual(status, 200, who)
            self.assertEqual(self.conn.data_args[-1][-2:], [[6], [51, 52]], who)
        # The ZL of another zone may not build in this deck, and it is not shared with them.
        self.who = 'zl6'
        self.assertEqual(self.data(mission, deck='council')[0], 403)
        self.assertEqual(self.data(mission, deck='council', pinned=True)[0], 403)
        # A deck without an owner (a mission deck) is no zone's to build in.
        self.rule = dict(self.rule, owner_zone_id=None)
        self.who = 'zl'
        self.assertEqual(self.data(mission, deck='council')[0], 403)

    def test_catalog_for_zone_leaders_holds_only_their_zone(self):
        for who in ('zl', 'stl'):
            self.who = who
            status, body = self.post('/internal/presentations/chart-catalog', {})
            self.assertEqual(status, 200, who)
            self.assertEqual(body['scope'], 'zone')
            self.assertEqual([lv['id'] for lv in body['levels']], ['zone', 'district', 'area'])
            self.assertEqual([z['id'] for z in body['zones']], [5])
            self.assertEqual([d['id'] for d in body['districts']], [51, 52])
            self.assertEqual(sorted(a['id'] for a in body['areas']), [511, 512, 521])
        self.who = 'ap'
        status, body = self.post('/internal/presentations/chart-catalog', {})
        self.assertEqual((body['scope'], len(body['levels']), len(body['zones']), len(body['areas'])), ('mission', 4, 2, 4))

    def test_no_leader_gets_mission_or_other_zone_numbers_whatever_the_audience(self):
        self.rule = {'roles': ['DL', 'ZL', 'STL'], 'zone_ids': [], 'district_ids': [], 'user_ids': [], 'everyone': True}
        for audience in ('deck', 'stewardship'):
            mission = {'measures': ['friends_found.actual'], 'level': 'mission', 'audience': audience}
            for who, level, units in (('zl', 'zone', [5]), ('stl', 'zone', [5])):
                self.who = who
                status, body = self.data(mission, deck='council', pinned=True)
                self.assertEqual((status, body['meta']['level'], body['meta']['stewardship']), (200, level, True), (who, audience))
                self.assertEqual(self.conn.data_args[-1][-1], units, (who, audience))
                self.assertNotIn('kpi_mission_week', self.conn.log[-1])
            # A ZL asking for the districts of the whole mission gets only their zone's districts.
            self.who = 'zl'
            status, body = self.data({'measures': ['friends_found.actual'], 'level': 'district', 'by': 'unit',
                                      'audience': audience}, deck='council', pinned=True)
            self.assertEqual((status, body['table']['labels']), (200, ['D51']), audience)
            self.assertEqual(self.conn.data_args[-1][-1], [51, 52])
            # A chart limited to another zone shows a ZL nothing: the zone filter AND their own zone (the stand-in
            # cursor applies only the last list, so the SQL arguments are checked).
            status, body = self.data({'measures': ['friends_found.actual'], 'level': 'zone', 'filter': {'zones': [6]},
                                      'audience': audience}, deck='council', pinned=True)
            self.assertEqual(status, 200)
            self.assertEqual(self.conn.data_args[-1][-2:], [[6], [5]])
            self.assertIn('"zone_id" = ANY(%s::bigint[]) AND "zone_id" = ANY(%s::bigint[])', self.conn.log[-1])
        # The AP still gets the whole mission, with either audience.
        self.who = 'ap'
        for audience in ('deck', 'stewardship'):
            status, body = self.data({'measures': ['friends_found.actual'], 'level': 'mission', 'audience': audience})
            self.assertEqual((status, body['meta']['level'], body['meta']['stewardship']), (200, 'mission', False))

    def test_a_zone_deck_shows_only_its_zone_to_everyone_managers_too(self):
        # Round 8: managers now see zone decks (they run on the deck address). A zone deck's slides are page code its
        # zone's leaders wrote, so its charts never show more than that zone, whoever opens it.
        self.rule = {'roles': ['DL'], 'zone_ids': [], 'district_ids': [], 'user_ids': [], 'everyone': True, 'owner_zone_id': 5}
        mission = {'measures': ['friends_found.actual'], 'level': 'mission'}
        status, body = self.data(mission, deck='council', pinned=True)
        self.assertEqual((status, body['meta']['level'], body['meta']['stewardship']), (200, 'zone', True))
        self.assertEqual(self.conn.data_args[-1][-1], [5])
        self.assertEqual([s['name'] for s in body['table']['series']], ['Z5'])
        # A district chart of the whole mission: only that zone's districts (also in the builder's preview).
        status, body = self.data({'measures': ['friends_found.actual'], 'level': 'district'}, deck='council')
        self.assertEqual((status, body['meta']['level']), (200, 'district'))
        self.assertEqual(self.conn.data_args[-1][-1], [51, 52])
        # A DL of that zone (the deck is shared with DLs): still only their own district.
        self.who = 'dl'
        status, body = self.data(mission, deck='council', pinned=True)
        self.assertEqual((status, body['meta']['level']), (200, 'district'))
        self.assertEqual(self.conn.data_args[-1][-1], [51])
        # The same chart in a mission deck (no owner zone): a manager sees the whole mission, as before.
        self.who = 'ap'
        self.rule = dict(self.rule, owner_zone_id=None)
        status, body = self.data(mission, deck='council', pinned=True)
        self.assertEqual((status, body['meta']['level'], body['meta']['stewardship']), (200, 'mission', False))
        # Without a deck (the Whiteboard): unchanged.
        status, body = self.data(mission)
        self.assertEqual((status, body['meta']['stewardship']), (200, False))

    def test_kpis_in_a_zone_deck_are_that_zones_totals_for_everyone(self):
        self.rule = {'roles': [], 'zone_ids': [], 'district_ids': [], 'user_ids': [], 'everyone': False, 'owner_zone_id': 5}
        status, body = self.post('/internal/presentations/kpis', {'weeks': 8, 'deck': 'council'})
        self.assertEqual((status, body[-1]['friends_found']), (200, {'actual': 7, 'goal': 6}))
        text, args = self.conn.kpi_calls[-1]
        self.assertIn('"dashboards"."kpi_zone_week"', text)
        self.assertEqual(args, [1, [5], 8], "a manager gets the zone's totals in the zone's deck")
        self.assertFalse(any('kpi_mission_week' in q for q in self.conn.log))
        # Someone who may not open the deck gets nothing (a ZL of another zone).
        self.who = 'zl6'
        self.assertEqual(self.post('/internal/presentations/kpis', {'weeks': 8, 'deck': 'council'})[0], 403)
        # A mission deck, or no deck: the mission totals for managers, as before.
        self.who = 'ap'
        self.rule = dict(self.rule, owner_zone_id=None)
        for extra in ({'deck': 'council'}, {}):
            self.conn.log.clear()
            status, body = self.post('/internal/presentations/kpis', {'weeks': 8, **extra})
            self.assertEqual((status, body[-1]['friends_found']), (200, {'actual': 99, 'goal': 90}), extra)

    def kpis(self, weeks=12):
        return self.post('/internal/presentations/kpis', {'weeks': weeks})

    def test_mission_kpis_are_mission_totals_for_managers_only(self):
        status, body = self.kpis()
        self.assertEqual((status, body[-1]['friends_found']), (200, {'actual': 99, 'goal': 90}))
        self.assertEqual(self.conn.kpi_calls, [])
        for who, view, column, units in (('zl', 'kpi_zone_week', 'zone_id', [5]), ('stl', 'kpi_zone_week', 'zone_id', [5])):
            self.who = who
            self.conn.log.clear()
            status, body = self.kpis(8)
            self.assertEqual((status, body[-1]['friends_found']), (200, {'actual': 7, 'goal': 6}), who)
            text, args = self.conn.kpi_calls[-1]
            self.assertIn(f'"dashboards"."{view}"', text, who)
            self.assertIn(f'"{column}" = ANY(%s::bigint[])', text, who)
            self.assertEqual(args, [1, units, 8], who)
            self.assertFalse(any('kpi_mission_week' in q for q in self.conn.log), who)
        # A DL gets their own district's totals, never the mission's.
        self.who = 'dl'
        self.conn.log.clear()
        status, body = self.kpis(8)
        self.assertEqual(status, 200)
        text, args = self.conn.kpi_calls[-1]
        self.assertIn('"dashboards"."kpi_district_week"', text)
        self.assertEqual(args, [1, [51], 8])
        self.assertFalse(any('kpi_mission_week' in q for q in self.conn.log))
        for who in ('missionary', 'office'):
            self.who = who
            self.assertEqual(self.kpis()[0], 403, who)

    def test_stewardship_filters_to_the_viewers_units(self):
        self.who = 'zl'
        self.rule = {'roles': ['ZL'], 'zone_ids': [], 'district_ids': [], 'user_ids': [], 'everyone': True}
        status, body = self.data({'measures': ['friends_found.actual'], 'level': 'zone', 'audience': 'stewardship'},
                                 deck='council', pinned=True)
        self.assertEqual(status, 200)
        self.assertEqual(body['meta']['level'], 'zone', 'a ZL gets their own zone only')
        self.assertTrue(body['meta']['stewardship'])
        self.assertEqual(self.conn.data_args[-1][-1], [5])
        self.assertEqual([s['name'] for s in body['table']['series']], ['Z5'])
        # A DL who is also a Data Analyst manages presentations: the whole mission.
        self.who = 'dl_da'
        status, body = self.data({'measures': ['friends_found.actual'], 'level': 'zone', 'audience': 'stewardship'})
        self.assertEqual((status, body['meta']['level'], body['meta']['stewardship']), (200, 'zone', False))

    def test_others_are_refused(self):
        for who in ('missionary', 'office', 'dl'):
            self.who = who
            self.assertEqual(self.data({'measures': ['friends_found.actual']}, deck='x', pinned=True)[0], 403, who)
        self.who = 'dl'
        self.assertEqual(self.post('/internal/presentations/chart-catalog', {})[0], 403)

    def test_catalog_for_managers(self):
        status, body = self.post('/internal/presentations/chart-catalog', {})
        self.assertEqual(status, 200)
        ids = {m['id'] for m in body['measures']}
        self.assertIn('new_members.at_church', ids)
        self.assertNotIn('column', body['measures'][0])
        self.assertEqual(body['weeks']['current'], '2026-09-20')
        self.assertIn('SET LOCAL ROLE gfm_dashboard_reader', self.conn.log)


class ZoneDecks(unittest.TestCase):
    """app.deck_allowed (open) and app.deck_editable (change): round 7, zone presentations."""

    def rule(self, **values):
        base = {'roles': [], 'zone_ids': [], 'district_ids': [], 'user_ids': [], 'everyone': False, 'owner_zone_id': None}
        return dict(base, **values)

    def person(self, who):
        return dict(CONTEXTS[who], user_id=str(uuid.uuid4()))

    def test_managers_open_and_change_every_deck(self):
        for who in ('ap', 'dl_da'):
            for rule in (None, self.rule(), self.rule(owner_zone_id=5)):
                self.assertTrue(app.deck_allowed(rule, self.person(who)), who)
                self.assertTrue(app.deck_editable(rule, self.person(who)), who)

    def test_zone_leaders_change_only_their_own_zones_decks(self):
        own, other, mission = self.rule(owner_zone_id=5), self.rule(owner_zone_id=6), self.rule()
        for who in ('zl', 'stl'):
            c = self.person(who)
            self.assertTrue(app.deck_allowed(own, c) and app.deck_editable(own, c), who)
            self.assertFalse(app.deck_allowed(other, c) or app.deck_editable(other, c), who)
            self.assertFalse(app.deck_allowed(mission, c) or app.deck_editable(mission, c), who)
            self.assertFalse(app.deck_allowed(None, c) or app.deck_editable(None, c), who)
        c = self.person('zl6')
        self.assertTrue(app.deck_editable(other, c))
        self.assertFalse(app.deck_allowed(own, c))

    def test_a_shared_deck_opens_but_stays_read_only(self):
        shared = self.rule(roles=['ZL', 'STL'], everyone=True)
        zone_five_zls = self.rule(roles=['ZL'], zone_ids=[5])
        for who in ('zl', 'stl'):
            c = self.person(who)
            self.assertTrue(app.deck_allowed(shared, c), who)
            self.assertFalse(app.deck_editable(shared, c), who)
        self.assertTrue(app.deck_allowed(zone_five_zls, self.person('zl')))
        self.assertFalse(app.deck_editable(zone_five_zls, self.person('zl')))
        self.assertFalse(app.deck_allowed(zone_five_zls, self.person('stl')), 'shared with ZLs only')

    def test_a_zone_deck_never_opens_in_another_zone(self):
        # Its slides are page code its own zone's leaders wrote (review finding, round 7): whatever its rule says, only
        # managers and people of that zone open it.
        everyone = self.rule(roles=['DL', 'ZL', 'STL'], everyone=True, owner_zone_id=6)
        named = self.rule(owner_zone_id=6, zone_ids=[5], district_ids=[51])
        for who in ('zl', 'stl', 'dl'):
            c = self.person(who)
            self.assertFalse(app.deck_allowed(everyone, c), who)
            self.assertFalse(app.deck_allowed(named, c), who)
            self.assertFalse(app.deck_allowed(dict(everyone, user_ids=[c['user_id']]), c), who)
        self.assertTrue(app.deck_allowed(everyone, self.person('zl6')), "the zone's own ZL")
        self.assertTrue(app.deck_allowed(everyone, self.person('ap')), 'managers see every deck')

    def test_dls_open_shared_decks_only_and_missionaries_and_office_none(self):
        everyone = self.rule(roles=['DL', 'ZL', 'STL'], everyone=True, owner_zone_id=5)
        dl = self.person('dl')
        self.assertTrue(app.deck_allowed(everyone, dl))
        self.assertTrue(app.deck_allowed(self.rule(user_ids=[dl['user_id']]), dl))
        self.assertFalse(app.deck_editable(everyone, dl), 'a DL never changes a deck')
        self.assertFalse(app.deck_allowed(self.rule(owner_zone_id=5), dl), 'a zone deck not shared with them stays closed')
        for who in ('missionary', 'office'):
            c = self.person(who)
            self.assertFalse(app.deck_allowed(everyone, c), who)
            self.assertFalse(app.deck_editable(everyone, c), who)
            self.assertFalse(app.deck_allowed(self.rule(user_ids=[c['user_id']]), c), who)


if __name__ == '__main__':
    unittest.main()
