"""TEST ONLY: the real Call-ins API (callins.py) over an in-memory, made-up mission - for browser checks of
portal/callins.html without a database and without personal data.

Everything a database would answer comes from the sample mission below (three zones, a few districts and areas,
made-up people). Saves change the in-memory copy, and a completed district call-in refuses DL notes and area
updates like migration 022. The bearer token is "stub.<viewer>.x" with viewer ap, zl, dl, dl_da, office_da or missionary.
It never talks to Supabase or a database.

  docker run --rm --network <net> --name <name> -v <repo>/portal-api:/app -w /app gfm-portal-portal-api \
      python tests/callins_stub_api.py          (listens on 8091, like portal-api)
Serve portal/ with nginx and proxy /api/ to it; open callins.html?portal_token=stub.dl.x (or zl, ap, ...).
"""
import os
import random
import sys
from contextlib import contextmanager
from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

import psycopg2

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('SUPABASE_URL', 'http://stub.invalid')
os.environ.setdefault('SUPABASE_SERVICE_ROLE_KEY', 'stub-only')
import app  # noqa: E402
import callins  # noqa: E402

MISSION = {1: 'Sample Mission'}
ZONES = {5: ('North Zone', 1), 6: ('South Zone', 1), 7: ('East Zone', 1)}
DISTRICTS = {51: ('Riverside', 5), 52: ('Hillview', 5), 53: ('Old Town', 5), 61: ('Lakeside', 6), 62: ('Meadow', 6),
             71: ('Harbour', 7)}
AREAS = {}
for district_id, (district_name, _) in DISTRICTS.items():
    for n, suffix in enumerate(('North', 'South', 'Centre', 'West')[:3 if district_id % 2 else 4]):
        AREAS[district_id * 10 + n + 1] = (f'{district_name} {suffix}', district_id)
WEEKS = [(12, date(2026, 9, 20)), (11, date(2026, 9, 13)), (10, date(2026, 9, 6))]
CONTEXTS = {
    'ap': {'app_role': 'AP', 'leadership_role': 'AP', 'mission_id': 1, 'zone_id': 6, 'district_id': 61, 'area_id': 611},
    'zl': {'app_role': 'MISSIONARY', 'leadership_role': 'ZL', 'leadership_zone_id': 5, 'mission_id': 1, 'zone_id': 5,
           'district_id': 51, 'area_id': 511},
    'dl': {'app_role': 'MISSIONARY', 'leadership_role': 'DL', 'leadership_district_id': 51, 'mission_id': 1, 'zone_id': 5,
           'district_id': 51, 'area_id': 512},
    'dl_da': {'app_role': 'MISSIONARY', 'leadership_role': 'DL', 'leadership_district_id': 51, 'mission_id': 1, 'zone_id': 5,
              'district_id': 51, 'area_id': 512, 'additional_roles': ['DATA_ADMIN']},
    'missionary': {'app_role': 'MISSIONARY', 'leadership_role': None, 'mission_id': 1, 'zone_id': 5, 'district_id': 51, 'area_id': 511},
    # Office by main role, Data Analyst as an additional role: opens on the mission, computer-first.
    'office_da': {'app_role': 'OFFICE', 'leadership_role': None, 'mission_id': 1, 'zone_id': 6, 'area_id': 611,
                  'additional_roles': ['DATA_ADMIN']},
}
LONG = ('We will ask the ward mission leader for two members to join our lessons this week, and invite the '
        'friends we found on Saturday to the ward activity.')
DISTRICT_ROWS = {}   # (district_id, week_id) -> {'dl_notes', 'zl_notes', 'dl_completed_at', 'updated_at'}
ZONE_NOTES = {(5, 12): 'Great week of finding. Keep inviting friends to sacrament meeting.'}
AREA_UPDATES = {(511, 12): 'Two new friends found through the ward. Lessons with members went well.'}


def area_numbers(area_id, week_id):
    r = random.Random(area_id * 100 + week_id)
    row = {}
    for key, _ in callins.METRICS:
        row[key + '_actual'] = r.randint(0, 6)
        row[key + '_goal'] = r.randint(1, 7)
        if key != 'follow_up_lessons':
            row[key + '_previous_goal'] = r.randint(1, 7)
    return row


def add(rows):
    total = {}
    for row in rows:
        for k, v in row.items():
            if k.endswith(('_actual', '_goal')) and isinstance(v, int):
                total[k] = total.get(k, 0) + v
    return total


def missionaries(area_id):
    return [{'display_name': f'Elder Sample {area_id}a', 'roster_position_abbr': 'DL' if area_id % 10 == 2 else 'SR'},
            {'display_name': f'Elder Sample {area_id}b', 'roster_position_abbr': 'JR'}]


def completed(district_id, week_id):
    return (DISTRICT_ROWS.get((district_id, week_id)) or {}).get('dl_completed_at')


def planning_details(area_id, week_id):
    name, district_id = AREAS[area_id]
    return [{'area_name': name, 'unit_name': f'{name.split()[0]} Ward', 'status': 'SUBMITTED' if area_id % 3 else 'DRAFT',
             'other_goals': [{'key': 'member_meals_goal', 'label': 'Member meals', 'actual': 2, 'goal': 3},
                             {'key': 'follow_up_lessons_goal', 'label': 'Follow-up lessons', 'actual': 1, 'goal': 2}],
             'weekly_action_plan': LONG if area_id % 2 else None,
             'information_up_chain': 'Could the zone leaders help with a Spanish-speaking friend?' if area_id % 5 == 1 else None}]


def area_row(area_id, week_id):
    name, district_id = AREAS[area_id]
    return dict(area_numbers(area_id, week_id), area_id=area_id, area_name=name, district_id=district_id,
                report_count=1 if area_id % 4 else 0, all_reports_submitted=bool(area_id % 3),
                dl_update=AREA_UPDATES.get((area_id, week_id)), missionaries=missionaries(area_id),
                friends_found_plan=LONG, sacrament_attendance_plan='Remind friends on Saturday evening.' if area_id % 2 else None,
                planning_details=planning_details(area_id, week_id))


def district_row(district_id, week_id):
    name, zone_id = DISTRICTS[district_id]
    areas = [a for a, (_, d) in AREAS.items() if d == district_id]
    record = DISTRICT_ROWS.get((district_id, week_id)) or {}
    return dict(add(area_numbers(a, week_id) for a in areas), district_id=district_id, district_name=name, zone_id=zone_id,
                dl_notes=record.get('dl_notes'), zl_notes=record.get('zl_notes'), thank_you='NEVER SHOWN',
                dl_call_in_complete=bool(record.get('dl_completed_at')), dl_completed_at=record.get('dl_completed_at'),
                area_count=len(areas), all_weekly_reports_submitted=district_id % 2 == 1,
                planning_details=[p for a in areas for p in planning_details(a, week_id)])


def zone_row(zone_id, week_id):
    name, mission_id = ZONES[zone_id]
    districts = [d for d, (_, z) in DISTRICTS.items() if z == zone_id]
    return dict(add(area_numbers(a, week_id) for a, (_, d) in AREAS.items() if d in districts), zone_id=zone_id, zone_name=name,
                mission_id=mission_id, district_count=len(districts),
                completed_district_count=sum(1 for d in districts if completed(d, week_id)),
                all_dl_call_ins_complete=all(completed(d, week_id) for d in districts),
                all_weekly_reports_submitted=zone_id != 6, area_count=sum(1 for _, d in AREAS.values() if d in districts),
                zone_notes=ZONE_NOTES.get((zone_id, week_id)), planning_details=[])


def people(level, scope_id, week_id):
    def inside(area_id):
        _, district_id = AREAS[area_id]
        zone_id = DISTRICTS[district_id][1]
        return {'mission': True, 'zone': zone_id == scope_id, 'district': district_id == scope_id, 'area': area_id == scope_id}[level]

    def where(area_id):
        name, district_id = AREAS[area_id]
        zone_id = DISTRICTS[district_id][1]
        return {'area_id': area_id, 'area_name': name, 'unit_name': f'{name.split()[0]} Ward', 'district_id': district_id,
                'district_name': DISTRICTS[district_id][0], 'zone_id': zone_id, 'zone_name': ZONES[zone_id][0],
                'missionaries': ', '.join(m['display_name'] for m in missionaries(area_id))}
    bd, nm, hp = [], [], []
    for n, area_id in enumerate(sorted(AREAS)):
        if not inside(area_id):
            continue
        if n % 2 == 0:
            bd.append(dict(where(area_id), id=1000 + n, person_id=2000 + n, name=f'Friend {chr(65 + n % 26)}. Sample',
                           finding_source='Member/Member', date_set='2026-09-06', baptismal_date=f'2026-10-{(n % 20) + 4:02d}',
                           days_until=14 + n, weeks_until=round((14 + n) / 7, 1), reading=True, praying=n % 3 != 0,
                           at_church=n % 4 != 0, keeping_commandments=True, member_involvement=n % 5 != 0, active=n % 4 != 0))
        if n % 3 == 0:
            nm.append(dict(where(area_id), id=3000 + n, person_id=4000 + n, name=f'Member {chr(66 + n % 24)}. Example',
                           baptism_date='2026-08-23', confirmation_date='2026-08-30', finding_source='Street contacting',
                           lessons_actual=2, lessons_goal=3, pmg_lessons_percentage=60,
                           how_are_they_doing='Coming every week and reading the Book of Mormon with the family.',
                           discussed_in_gemiko=True, gemiko_support_plan='Relief Society sister will visit on Tuesday.',
                           next_ordinance=['TB', 'AP', 'MP', 'TE'][n % 4], at_church=n % 2 == 0, has_calling='no',
                           has_aaronic_priesthood='yes', has_melchizedek_priesthood='not_applicable', ministers_to_someone='no',
                           ministered_to_by_someone=True, has_active_temple_recommend='yes', visited_temple_for_baptisms='no',
                           reading=True, praying=True, member_involvement=True, active=n % 2 == 0))
        if n % 4 == 1:
            hp.append(dict(where(area_id), id=5000 + n, name=f'Potential {n}', at_church=n % 8 == 1,
                           notes='Met at the ward activity; wants to learn more.', active=n % 8 == 1))
    count = lambda rows: {'total': len(rows), 'active': sum(1 for r in rows if r['active'])}
    return {'level': level, 'id': scope_id, 'reporting_week_id': week_id, 'baptismal_dates': bd, 'new_members': nm,
            'high_potentials': hp, 'counts': {'baptismal_dates': count(bd), 'new_members': count(nm), 'high_potentials': count(hp)}}


class StubError(psycopg2.Error):
    def __init__(self, code, message):
        super().__init__(message)
        self._code, self._message = code, message

    @property
    def pgcode(self):
        return self._code

    @property
    def diag(self):
        return SimpleNamespace(message_primary=self._message)


LOCK = StubError('55000', 'This call-in is marked complete.')


class Cursor:
    def __init__(self, conn):
        self.conn, self.description, self.result = conn, None, []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def answer(self, rows, columns=None):
        columns = columns or (list(rows[0]) if rows else ['value'])
        self.description = [(c,) for c in columns]
        self.result = [tuple(r.get(c) for c in columns) for r in rows]

    def execute(self, sql, args=()):
        flat = ' '.join(sql.split())
        now = datetime.now(timezone.utc).isoformat()
        self.description, self.result = None, []
        for level, text in callins.CHAIN_SQL.items():
            if flat == ' '.join(text.split()):
                return self.answer(chain(level, args[0]), ['mission_id', 'mission_name', 'zone_id', 'zone_name',
                                                           'district_id', 'district_name', 'area_id', 'area_name'])
        if 'get_mission_call_in_summary_with_planning' in flat:
            return self.answer([{'data': [zone_row(z, args[1]) for z in ZONES]}])
        if 'get_zl_call_in_summary_with_planning' in flat:
            return self.answer([{'data': [district_row(d, args[1]) for d, (_, z) in DISTRICTS.items() if z == args[0]]}])
        if 'get_zl_call_in_area_updates' in flat:
            return self.answer([{'district_id': d, 'area_id': a, 'area_name': n, 'missionaries': missionaries(a),
                                 'dl_update': AREA_UPDATES.get((a, args[1]))}
                                for a, (n, d) in AREAS.items() if DISTRICTS[d][1] == args[0]],
                               ['district_id', 'area_id', 'area_name', 'missionaries', 'dl_update'])
        if 'get_zl_call_in_zone_notes' in flat:
            return self.answer([{'zone_notes': ZONE_NOTES.get((args[0], args[1])), 'updated_at': now}])
        if 'get_dl_call_in_summary_with_planning' in flat:
            return self.answer([{'data': [area_row(a, args[1]) for a, (_, d) in AREAS.items() if d == args[0]]}])
        if 'FROM public.call_in_districts WHERE district_id' in flat:
            record = DISTRICT_ROWS.get((args[0], args[1]))
            return self.answer([record] if record else [], ['dl_notes', 'zl_notes', 'dl_completed_at', 'updated_at'])
        if 'get_call_in_people' in flat:
            return self.answer([{'data': people(args[0], args[1], args[2])}])
        if 'get_dl_call_in_ward_coordination' in flat:
            rows = []
            for a, (n, d) in AREAS.items():
                if d != args[0]:
                    continue
                attendance = ['Missionaries', 'Bishopric'] if a % 4 == 3 else {
                    key: ['yes', 'no', 'dont_have_one'][(a + i) % 3] for i, (key, _) in enumerate(GEMIKO)}
                rows.append({'area_id': a, 'area_name': n, 'unit_id': a, 'unit_name': f'{n.split()[0]} Ward',
                             'ward_coordination_held': a % 5 != 0, 'ward_coordination_attendance': attendance})
            return self.answer(rows, ['area_id', 'area_name', 'unit_id', 'unit_name', 'ward_coordination_held',
                                      'ward_coordination_attendance'])
        if 'FROM public.reporting_weeks' in flat:
            if 'sunday=%s' in flat:
                return self.answer([{'id': i, 'sunday': s} for i, s in WEEKS if s == args[0]], ['id', 'sunday'])
            return self.answer([{'id': i, 'sunday': s} for i, s in WEEKS], ['id', 'sunday'])
        if 'current_reporting_sunday() AS sunday' in flat:
            return self.answer([{'sunday': date(2026, 9, 27)}])
        record = lambda: DISTRICT_ROWS.setdefault((args[0], args[1]), {'dl_notes': None, 'zl_notes': None,
                                                                        'dl_completed_at': None, 'updated_at': now})
        if 'save_dl_call_in_notes' in flat:
            if completed(args[0], args[1]):
                raise LOCK
            record().update(dl_notes=args[2], updated_at=now)
        elif 'save_zl_call_in_notes' in flat:
            record().update(zl_notes=args[2], updated_at=now)
        elif 'save_zl_zone_call_in_notes' in flat:
            ZONE_NOTES[(args[0], args[1])] = args[2]
        elif 'save_call_in_area_update' in flat:
            if completed(args[0], args[1]):
                raise LOCK
            AREA_UPDATES[(args[2], args[1])] = args[3]
        elif 'complete_dl_call_in' in flat:
            record().update(dl_completed_at=now, updated_at=now)
        elif 'reopen_dl_call_in' in flat:
            record().update(dl_completed_at=None, updated_at=now)
        elif 'FROM public.call_in_area_updates' in flat:
            return self.answer([{'update_text': AREA_UPDATES.get((args[2], args[1])), 'updated_at': now}])
        if flat.startswith('SELECT'):
            self.answer([{'value': 'ok'}])

    def fetchall(self):
        if self.conn.cursor_factory:
            return [dict(zip([d[0] for d in self.description], row)) for row in self.result]
        return self.result


GEMIKO = [('elders_quorum_representative', ''), ('relief_society_representative', ''), ('primary_presidency_representative', ''),
          ('ward_missionaries', ''), ('priests_quorum_assistant', ''), ('oldest_young_women_presidency', ''),
          ('senior_service_missionaries', ''), ('gemiko_leader', '')]


def chain(level, scope_id):
    if level == 'mission':
        return [{'mission_id': scope_id, 'mission_name': MISSION[scope_id]}] if scope_id in MISSION else []
    if level == 'zone':
        if scope_id not in ZONES:
            return []
        return [{'zone_id': scope_id, 'zone_name': ZONES[scope_id][0], 'mission_id': 1, 'mission_name': MISSION[1]}]
    if level == 'district':
        if scope_id not in DISTRICTS:
            return []
        name, zone_id = DISTRICTS[scope_id]
        return [{'district_id': scope_id, 'district_name': name, 'zone_id': zone_id, 'zone_name': ZONES[zone_id][0],
                 'mission_id': 1, 'mission_name': MISSION[1]}]
    if scope_id not in AREAS:
        return []
    name, district_id = AREAS[scope_id]
    zone_id = DISTRICTS[district_id][1]
    return [{'area_id': scope_id, 'area_name': name, 'district_id': district_id, 'district_name': DISTRICTS[district_id][0],
             'zone_id': zone_id, 'zone_name': ZONES[zone_id][0], 'mission_id': 1, 'mission_name': MISSION[1]}]


class Conn:
    cursor_factory = 'RealDictCursor'

    def cursor(self):
        return Cursor(self)


@contextmanager
def stub_db():
    yield Conn()


def stub_identity(url, headers, timeout):
    return SimpleNamespace(status_code=200, json=lambda: {'id': '00000000-0000-0000-0000-000000000001'})


def stub_context(conn, user_id):
    from flask import request
    token = request.headers.get('Authorization', '').split(' ', 1)[-1]  # "stub.<viewer>.x"
    viewer = (token.split('.') + ['', ''])[1]
    if viewer not in CONTEXTS:
        from flask import abort
        abort(401, 'Stub: use the token stub.<viewer>.x with viewer ap, zl, dl, dl_da, office_da or missionary.')
    return dict(CONTEXTS[viewer], user_id=viewer, user_active=True)


if __name__ == '__main__':
    with patch.object(app.requests, 'get', stub_identity), patch.object(app, 'db', stub_db), \
            patch.object(app, 'context_for', stub_context), patch.object(app.base64, 'urlsafe_b64decode', lambda s: b'{}'):
        app.app.run(host='0.0.0.0', port=8091, threaded=False)
