"""A guard at the API's front door: only the portal's own pages may call /api/.

What it is: one question, refusal(), asked by app.py before anything else runs on every request.
Who uses it: app.authenticate (and tests/test_origin_guard.py).
How it fits: presentations run on their own address since round 8, port 8089 of the same computer ("the deck
address", see slidev/manager/deck-origin.mjs), because a deck is page code that Zone Leaders may write. Browsers treat
two ports of one computer as "same-site", so a deck page could send requests here. They would carry no sign-in
(portal-api only accepts a Bearer token, which lives in the portal page; a page on another address can neither read
nor send it without the browser first asking this API, which never says yes: there are no CORS headers here). This
guard refuses such requests anyway:

- a request the browser marks as coming from another address (Sec-Fetch-Site: same-site or cross-site);
- a request whose Origin is the deck address (any computer name, the deck port) or "null" (a page without an address).

The portal's own pages send Sec-Fetch-Site: same-origin (or no such header in older browsers), so nothing changes for
them. Programs on the server (the presentation manager, the reminders) call /internal/ and /health, not /api/.
"""
from urllib.parse import urlparse

DEFAULT_DECK_PORT = 8089
REFUSED = 'This request came from another page, so it was refused.'
OTHER_ADDRESS = {'same-site', 'cross-site'}


def deck_port(environ):
    """The deck address's port (PRESENTATIONS_DECK_PORT, like the presentation manager), 8089 when not set."""
    try:
        return int(environ.get('PRESENTATIONS_DECK_PORT') or DEFAULT_DECK_PORT)
    except ValueError:
        return DEFAULT_DECK_PORT


def refusal(path, headers, port=DEFAULT_DECK_PORT):
    """None when this request may reach the API, else the sentence to refuse it with (403).
    headers: anything with .get() (Flask's request.headers)."""
    if not path.startswith('/api/') or path == '/api/health':
        return None
    if (headers.get('Sec-Fetch-Site') or '').strip().lower() in OTHER_ADDRESS:
        return REFUSED
    origin = (headers.get('Origin') or '').strip()
    if origin == 'null':
        return REFUSED
    if origin:
        try:
            if urlparse(origin).port == port:
                return REFUSED
        except ValueError:
            return REFUSED
    return None
