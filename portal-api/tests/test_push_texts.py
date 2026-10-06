"""Unit checks: push reminders in the person's language (round 6, push_texts.py; no database, no push service).

- push_texts.TEXTS holds the same texts as push.* in portal/i18n/<code>.json, for all 14 languages;
- a stored language (de, de-AT, deu, fa-IR, pes …) finds its texts, anything else English;
- a reminder cycle writes the Weekly Planning and meeting reminders in the language the person chose, English when
  the lookup fails, and looks the language up only for people who get a reminder.

Run in the portal-api image with the portal folder mounted at /portal (the catalog check needs it):
  docker run --rm -v <repo>/portal-api:/app -v <repo>/portal:/portal:ro -w /app gfm-portal-portal-api python tests/test_push_texts.py
"""
import json
import sys
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import push_texts  # noqa: E402
import reminders  # noqa: E402
import test_reminders as tr  # noqa: E402

PORTAL = next((path for path in (Path(__file__).resolve().parents[2] / 'portal', Path('/portal'))
               if (path / 'i18n' / 'catalogs.json').exists()), None)
KEYS = ['push.planningDueTitle', 'push.planningDueBody', 'push.meetingNow', 'push.meetingSoon']


def test_the_texts_are_the_catalogs_texts():
    if PORTAL is None:
        return print('   (skipped: the portal folder is not mounted)')
    languages = json.loads((PORTAL / 'i18n' / 'catalogs.json').read_text(encoding='utf-8'))['languages']
    assert sorted(languages) == sorted(push_texts.TEXTS), sorted(languages)
    for code in languages:
        catalog = json.loads((PORTAL / 'i18n' / f'{code}.json').read_text(encoding='utf-8'))
        assert {key: catalog.get(key) for key in KEYS} == push_texts.TEXTS[code], code


def test_every_language_has_every_text():
    for code, texts in push_texts.TEXTS.items():
        assert sorted(texts) == sorted(KEYS), code
        if code != 'en':
            assert all(texts[key] != push_texts.TEXTS['en'][key] for key in KEYS), code


def test_stored_languages_find_their_texts():
    cases = {'de': 'de', 'de-AT': 'de', 'DE_ch': 'de', 'deu': 'de', 'fa-IR': 'fa', 'pes': 'fa', 'ara': 'ar',
             'ron': 'ro', 'en-GB': 'en', 'zh': 'en', '': 'en', None: 'en'}
    for stored, expected in cases.items():
        assert push_texts.language_code(stored) == expected, (stored, push_texts.language_code(stored))
    assert push_texts.text('pt-BR', 'push.meetingNow') == 'Sua reunião da missão começa agora.'


def test_meeting_messages_in_the_language_and_the_place_as_written():
    at_start = tr.event('a', tr.NOW, 60, reminder=0)
    assert reminders.event_message(at_start) == 'Your mission meeting starts now.'
    assert reminders.event_message(at_start, 'de') == 'Deine Missionsversammlung beginnt jetzt.'
    assert reminders.event_message(tr.event('a', tr.NOW, 60, reminder=15), 'ar') == 'سيبدأ اجتماع البعثة قريبًا.'
    assert reminders.event_message(tr.event('a', tr.NOW, 60, reminder=0, location='Chapel'), 'de') == 'Chapel'


def run_cycle(language_of):
    sent, looked_up = [], []

    def fake_push(conn, user_id, kind, reference, title, body, url):
        sent.append((user_id, kind, title, body))
        return True

    def fake_language(conn, c):
        looked_up.append(c['user_id'])
        value = language_of(c['user_id'])
        if isinstance(value, Exception):
            raise value
        return value

    @contextmanager
    def fake_db():
        yield object()

    due = {'ap': (True, 'plan-ap'), 'zl': (False, None)}
    with patch.object(reminders, 'rows', tr.fake_rows), patch.object(tr.app, 'rows', tr.fake_rows), \
            patch.object(reminders, 'db', fake_db), patch.object(reminders, 'context_for', tr.fake_context), \
            patch.object(reminders, 'push', fake_push), \
            patch.object(reminders, 'planning_due', lambda conn, c, now: due.get(c['user_id'], (False, None))), \
            patch.object(reminders, 'selected_language', fake_language), \
            patch.object(reminders.log, 'exception') as logged, patch.object(reminders.log, 'warning'):
        result = reminders.run_once(tr.NOW)
    return result, sent, looked_up, logged.call_count


def test_a_cycle_writes_each_reminder_in_the_persons_language():
    languages = {'ap': 'deu', 'zl': 'fa', 'office': 'en', 'president': 'ar-EG', 'da': 'xx'}
    result, sent, looked_up, errors = run_cycle(languages.get)
    assert errors == 0 and result['planning_due'] == 1, (result, errors)
    planning = [s for s in sent if s[1] == 'planning']
    assert planning == [('ap', 'planning', 'Die Wochenplanung ist fällig',
                         'Reicht den Plan eurer Mitarbeiterschaft für die kommende Woche ein.')], planning
    by_user = {}
    for user_id, kind, title, body in sent:
        if kind == 'event':
            by_user.setdefault(user_id, set()).add(body)
    assert by_user['zl'] == {'جلسهٔ مأموریت شما هم‌اکنون آغاز می‌شود.', 'جلسهٔ مأموریت شما به‌زودی آغاز می‌شود.'}, by_user
    assert by_user['president'] == {'سيبدأ اجتماع البعثة قريبًا.'}, by_user
    assert by_user['da'] == {'Your mission meeting starts soon.'}, by_user
    # Once per person who gets something, never for someone without a reminder.
    assert sorted(looked_up) == sorted(set(looked_up)) and 'no-mission' not in looked_up, looked_up


def test_a_failed_language_lookup_sends_english():
    result, sent, looked_up, errors = run_cycle(lambda user_id: RuntimeError('no preferences table'))
    assert errors == 0 and result['sent'] == len(sent) > 0, (result, errors)
    assert all(body in ('Your mission meeting starts now.', 'Your mission meeting starts soon.',
                        'Submit your companionship’s plan for the coming week.') for _, _, _, body in sent), sent


if __name__ == '__main__':
    tests = [value for name, value in sorted(globals().items()) if name.startswith('test_') and callable(value)]
    failed = 0
    for test in tests:
        try:
            test()
            print('ok', test.__name__)
        except Exception as error:  # noqa: BLE001
            failed += 1
            print('FAIL', test.__name__, '-', type(error).__name__, error)
    print(f'{len(tests) - failed} of {len(tests)} tests passed')
    sys.exit(1 if failed else 0)
