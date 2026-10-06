"""Unit checks for Church links in the reader's language (round 6, church_links.py; no database).

Run in the portal-api image (no pytest needed):
  docker run --rm -v <repo>/portal-api:/app -w /app gfm-portal-portal-api python tests/test_church_links.py
pytest works too: python -m pytest portal-api/tests/test_church_links.py
"""
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from flask import Flask  # noqa: E402

import church_links  # noqa: E402

ALMA = 'https://www.churchofjesuschrist.org/study/scriptures/bofm/alma/37?lang=eng&id=p6'
DC = 'https://www.churchofjesuschrist.org/study/scriptures/dc-testament/dc/64?lang=eng&id=p33'
PMG8 = 'https://www.churchofjesuschrist.org/study/manual/preach-my-gospel-2023/16-chapter-8?lang=eng'
PMG3 = 'https://www.churchofjesuschrist.org/study/manual/preach-my-gospel-2023/04-chapter-3?lang=eng'
# The Church's code for each interface language, each checked on the Church site (28 and 29 Sep 2026).
CODES = {'en': 'eng', 'de': 'deu', 'es': 'spa', 'fr': 'fra', 'pt': 'por', 'uk': 'ukr', 'ru': 'rus', 'it': 'ita',
         'tr': 'tur', 'fa': 'pes', 'ro': 'ron', 'sv': 'swe', 'da': 'dan', 'ar': 'ara'}
failures = []


def check(name, ok, detail=''):
    print(('PASS  ' if ok else 'FAIL  ') + name + ('' if ok else f' -- {detail}'))
    if not ok:
        failures.append(name)


def lang(url):
    return parse_qs(urlparse(url).query).get('lang')


for language, code in CODES.items():
    check(f'{language}: Book of Mormon lang={code}', lang(church_links.church_url(ALMA, language)) == [code])
    check(f'{language}: the verse id stays', parse_qs(urlparse(church_links.church_url(ALMA, language)).query).get('id') == ['p6'])
    # Persian has only the First Presidency message and chapter 3 of Preach My Gospel; Arabic has no D&C.
    check(f'{language}: Preach My Gospel chapter 8', lang(church_links.church_url(PMG8, language)) == ['eng' if code == 'pes' else code])
    check(f'{language}: Preach My Gospel chapter 3', lang(church_links.church_url(PMG3, language)) == [code])
    check(f'{language}: Doctrine and Covenants', lang(church_links.church_url(DC, language)) == ['eng' if code == 'ara' else code])
check('regional tags use the base language', lang(church_links.church_url(ALMA, 'de-CH')) == ['deu'])
check('a language without a catalog opens in English', lang(church_links.church_url(ALMA, 'ja')) == ['eng'])
check('other sites stay as they are', church_links.church_url('https://example.org/a?lang=eng', 'de') == 'https://example.org/a?lang=eng')
check('a look-alike host stays as it is', church_links.church_url('https://churchofjesuschrist.org.evil.example/x?lang=eng', 'de')
      == 'https://churchofjesuschrist.org.evil.example/x?lang=eng')
check('empty stays empty', church_links.church_url('', 'de') == '' and church_links.church_url(None, 'de') is None)
check('outside a request there is no page language', church_links.request_language() is None)

flask_app = Flask(__name__)
with flask_app.test_request_context('/', headers={'X-Mission-Language': 'fa'}):
    check('the page language comes from X-Mission-Language', church_links.request_language() == 'fa')
    check('without a language argument the page language is used', lang(church_links.church_url(ALMA)) == ['pes'])
with flask_app.test_request_context('/'):
    check('without the header: English', lang(church_links.church_url(ALMA)) == ['eng'])
with flask_app.test_request_context('/', headers={'X-Mission-Language': 'x' * 200}):
    check('a long header is cut', len(church_links.request_language()) == 35)

print(f"{len(failures)} failures" if failures else "all passed")
sys.exit(1 if failures else 0)
