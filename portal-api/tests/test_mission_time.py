"""Unit checks for the mission's time zone (GFM_TIME_ZONE): the default stays Europe/Berlin, and another zone moves "today",
the Sunday reminder and the new-event default with it. No database, no network.

Run in the portal-api image (no pytest needed):
  docker run --rm -v <repo>/portal-api:/app -w /app gfm-portal-portal-api python tests/test_mission_time.py
pytest works too: python -m pytest portal-api/tests/test_mission_time.py
Each check runs the program code in a fresh Python with its own GFM_TIME_ZONE (the zone is read when the program starts).
"""
import json
import os
import subprocess
import sys
from pathlib import Path

API = Path(__file__).resolve().parents[1]

# What runs in the fresh Python: prints one JSON line.
PROBE = r'''
import json, sys
from datetime import datetime, timezone
from unittest.mock import patch
sys.path.insert(0, %(api)r)
import mission_time, planning, archetypes, reminders, app
out = {'name': mission_time.NAME, 'zone': str(mission_time.ZONE)}
out['planning_today'] = planning._mission_today().isoformat()
out['archetypes_today'] = archetypes.today().isoformat()
out['expected_today'] = datetime.now(mission_time.ZONE).date().isoformat()
# A Sunday: 2026-09-27 16:30 UTC is 18:30 in Berlin (summer time), 10:30 in Denver, 05:30 on Monday 28th in Kiritimati.
instant = datetime(2026, 9, 27, 16, 30, tzinfo=timezone.utc)
with patch.object(reminders, 'rows', return_value=[]), patch.object(reminders, 'worked_on_lately', return_value=False):
    out['planning_due_sunday_1630_utc'] = reminders.planning_due(None, {'area_id': 1}, instant)[0]

print(json.dumps(out))
'''


def probe(zone=None):
    env = {k: v for k, v in os.environ.items() if k != 'GFM_TIME_ZONE'}
    env.update({'DATABASE_URL': 'postgresql://x@127.0.0.1:1/x', 'SUPABASE_URL': 'http://x', 'SUPABASE_SERVICE_ROLE_KEY': 'x',
                'PORTAL_SERVICE_KEY': 'x' * 32, 'VAPID_PRIVATE_KEY': 'x', 'VAPID_PUBLIC_KEY': 'x', 'VAPID_SUBJECT': 'mailto:x@example.org'})
    if zone is not None:
        env['GFM_TIME_ZONE'] = zone
    done = subprocess.run([sys.executable, '-c', PROBE % {'api': str(API)}], env=env, capture_output=True, text=True, cwd=str(API))
    assert done.returncode == 0, done.stderr[-800:]
    return json.loads(done.stdout.strip().splitlines()[-1])


def test_nothing_set_means_europe_berlin_as_before():
    out = probe()
    assert out['name'] == 'Europe/Berlin' and out['zone'] == 'Europe/Berlin'
    assert out['planning_today'] == out['archetypes_today'] == out['expected_today']
    assert out['planning_due_sunday_1630_utc'] is True, 'Sunday 18:30 in Berlin: the planning reminder is due'


def test_an_empty_setting_also_means_europe_berlin():
    assert probe('')['name'] == 'Europe/Berlin'


def test_another_zone_moves_today_and_the_sunday_reminder():
    denver = probe('America/Denver')
    assert denver['name'] == denver['zone'] == 'America/Denver'
    assert denver['planning_today'] == denver['archetypes_today'] == denver['expected_today']
    assert denver['planning_due_sunday_1630_utc'] is False, 'it is only 10:30 on Sunday morning in Denver'


def test_the_far_ends_of_the_world_count_their_own_day():
    ahead, behind = probe('Pacific/Kiritimati'), probe('Pacific/Pago_Pago')  # UTC+14 and UTC-11
    for out in (ahead, behind):
        assert out['planning_today'] == out['archetypes_today'] == out['expected_today']
    assert ahead['planning_today'] > behind['planning_today'], 'the same moment is a different day in the two zones'
    assert ahead['planning_due_sunday_1630_utc'] is False and behind['planning_due_sunday_1630_utc'] is False


def test_a_wrong_name_stops_the_program_at_start():
    env = {k: v for k, v in os.environ.items() if k != 'GFM_TIME_ZONE'}
    env['GFM_TIME_ZONE'] = 'Mars/Olympus'
    done = subprocess.run([sys.executable, '-c', 'import mission_time'], env=env, capture_output=True, text=True, cwd=str(API))
    assert done.returncode != 0 and 'Mars/Olympus' in done.stderr


if __name__ == '__main__':
    tests = [value for name, value in sorted(globals().items()) if name.startswith('test_') and callable(value)]
    for test in tests:
        test()
        print('ok', test.__name__)
    print(f'{len(tests)} passed')
