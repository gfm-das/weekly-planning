"""TEST ONLY: tests/portal_stub_api.py plus what the round-3 "small" browser checks need (edge_small_fixes.ps1).

- POST /stub/slow {"ms": n}: portal-enhancements.js is served n ms late, like an 80 KB script on a slow connection
  (the shell start-up race).
- A made-up Weekly Planning form with one friend with a baptismal date on the plan and none to add, and the
  person actions: after any action the friend leaves the plan and the reply lists them under "Add from database",
  as portal-api does for a move to another ward or branch of the same area.
Made-up data only; no database.

  docker run --rm --name gfm-test-small-web --memory 256m -p 127.0.0.1:18072:8080 \
      -v <repo>/portal-api:/app -v <repo>/portal:/portal:ro -w /app gfm-portal-portal-api python tests/small_stub_api.py
"""
import sys
import time
from pathlib import Path

from flask import jsonify, request

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import planning  # noqa: E402  (only its lists of choices, for person_options)
from portal_stub_api import app, log  # noqa: E402

slow = {'ms': 0}
FRIEND = {'id': 501, 'baptismal_date_person_id': 77, 'display_name': 'Zz Sample Friend', 'is_current': True,
          'on_submitted_plan': False, 'baptismal_date_set_on': None, 'current_baptismal_date': None,
          'person': {'first_name': 'Zz Sample', 'last_name': 'Friend', 'finding_source': 'Media/Referral'}}
plan = {'friends': [dict(FRIEND)], 'available': []}


@app.before_request
def slow_enhancements():
    if request.path == '/portal-enhancements.js' and slow['ms']:
        time.sleep(slow['ms'] / 1000)


@app.post('/stub/slow')
def stub_slow():
    slow['ms'] = int((request.json or {}).get('ms', 0))
    return jsonify(ok=True, ms=slow['ms'])


@app.post('/stub/planning-reset')
def stub_planning_reset():
    plan.update(friends=[dict(FRIEND)], available=[])
    return jsonify(ok=True)


def people():
    return {'new_members': [], 'baptismal_friends': plan['friends'], 'high_potential': []}


def available():
    return {'new_members': [], 'baptismal_friends': plan['available']}


@app.get('/api/planning/form')
def planning_form():
    log.append({'method': 'GET', 'path': request.path})
    return jsonify(
        units=[{'unit_id': 5, 'unit': 'Sample Ward', 'unit_type': 'WARD', 'primary_unit': True}],
        report={'report_id': 900, 'unit_id': 5, 'status': 'DRAFT', 'submitted_at': None, 'updated_at': None,
                'sunday': '2026-09-27', 'planning_due_at': None},
        questions=[], answers={}, people=people(), available_people=available(), catalog_version=1,
        person_options={**{key: list(choices) for key, choices in planning.PERSON_CHOICES.items()},
                        'new_member_required': list(planning.NEW_MEMBER_REQUIRED)},
        can_edit=True)


@app.post('/api/planning/reports/<int:report_id>/people/<group>/<int:person_id>/<action>')
def planning_person_action(report_id, group, person_id, action):
    log.append({'method': 'POST', 'path': request.path})
    moved = [f for f in plan['friends'] if f['baptismal_date_person_id'] == person_id]
    plan['friends'] = [f for f in plan['friends'] if f['baptismal_date_person_id'] != person_id]
    plan['available'] = plan['available'] + [{'id': f['baptismal_date_person_id'], 'display_name': f['display_name']}
                                             for f in moved]
    return jsonify(ok=True, action=action, message='Done.', people=people(), available_people=available())


@app.put('/api/planning/reports/<int:report_id>/<part>')
def planning_save(report_id, part):
    return jsonify(ok=True, answers={}, people=people())


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, threaded=True)
