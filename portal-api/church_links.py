"""Links to churchofjesuschrist.org in the reader's language.

What it is: church_url(), which sets lang= in a link to the Church's site.
Who uses it: app.py (the Overview's scripture thought and the weekly mission focus).
How it fits: the Church's site chooses the language with lang= in the address (lang=deu, lang=pes ...). The portal
sends the chosen interface language in the X-Mission-Language header (portal/portal-client.js); portal/i18n.js
rewrites the links on the page too, so both use the same codes (keep them in step with LANGUAGES in portal/i18n.js).
"""
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from flask import has_request_context, request

# Interface language -> the Church's language code. Each checked on the Church site on 28 Sep 2026.
CHURCH_LANG = {
    'en': 'eng', 'de': 'deu', 'es': 'spa', 'fr': 'fra', 'pt': 'por', 'uk': 'ukr', 'ru': 'rus',
    'it': 'ita', 'tr': 'tur', 'fa': 'pes', 'ro': 'ron', 'sv': 'swe', 'da': 'dan', 'ar': 'ara',
}
# Pages the Church does not offer in a language (28 Sep 2026): those links open in English (eng).
# Persian has only the First Presidency message and chapter 3 of Preach My Gospel; Arabic has no Doctrine and Covenants.
PES_PMG_OFFERED = ('/study/manual/preach-my-gospel-2023/01-first-presidency-message', '/study/manual/preach-my-gospel-2023/04-chapter-3')


def _not_offered(code, path):
    """True for a page the Church does not offer in this language (see PES_PMG_OFFERED)."""
    if code == 'pes' and path.startswith('/study/manual/preach-my-gospel-2023/'):
        return not path.startswith(PES_PMG_OFFERED)
    if code == 'ara' and path.startswith('/study/scriptures/dc-testament/'):
        return True
    return False


def church_code(language):
    """The Church's code for an interface language (de, de-AT -> deu); eng when unknown."""
    base = str(language or 'en').strip().lower().replace('_', '-').split('-')[0]
    return CHURCH_LANG.get(base, 'eng')


def request_language():
    """The interface language the page sent (X-Mission-Language), or None outside a request or when not sent."""
    if not has_request_context():
        return None
    value = (request.headers.get('X-Mission-Language') or '').strip()
    return value[:35] or None


def church_url(url, language=None):
    """url with lang= set to the Church's code for language (default: the request's language). Other sites unchanged."""
    if not url:
        return url
    try:
        parts = urlparse(url)
    except ValueError:
        return url
    host = (parts.hostname or '').lower()
    if host != 'churchofjesuschrist.org' and not host.endswith('.churchofjesuschrist.org'):
        return url
    code = church_code(language or request_language() or 'en')
    if _not_offered(code, parts.path):
        code = 'eng'
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k != 'lang']
    query.insert(0, ('lang', code))
    return urlunparse(parts._replace(query=urlencode(query)))
