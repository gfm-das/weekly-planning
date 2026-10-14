"""The Wiki button of DA Management: where the mission wiki is (the page is links_page.py, /wiki-link and a card on /links).

The wiki is served by the portal's own web server at /wiki/ (portal/nginx.conf). DA Management is a different program on its own
port, so the button must lead to the portal's address, not to a path of DA Management. The address is not written in code:
  - WEB_LINK_WIKI in roster-importer/.env sets it (a plain http(s) address); "off" hides the button;
  - else, on DA Management's internet name, the portal's public address (MANAGEMENT_PUBLIC_PORTAL) plus /wiki/;
  - else the same computer name the manager reached DA Management by, on the portal's port (PORTAL_PORT, 8070), plus /wiki/.
Only managers see it (DA Management itself is for managers); the wiki is not in the portal's side menu on purpose.
"""
import re
from urllib.parse import urlsplit

import settings

PATH = "/wiki/"
PORT_PATTERN = re.compile(r"^\d{2,5}$")


def safe_address(value):
    """The address as it will be linked, or None: a plain http or https address of a web page with a host, with no user name,
    password, query or fragment, and no spaces."""
    text = str(value or "").strip()
    if not text or len(text) > 300 or any(ch.isspace() or ord(ch) < 32 for ch in text):
        return None
    try:
        parts = urlsplit(text)
        host = parts.hostname
    except ValueError:
        return None
    if parts.scheme not in ("http", "https") or not host or parts.username or parts.password or "@" in parts.netloc \
            or parts.query or parts.fragment:
        return None
    return text


def wiki_address(host, scheme="http", on_public_name=False, setting=None, public_portal=None, port=None):
    """(address or None, hidden). hidden is True when the setting says "off" (the button is left out); address None with hidden
    False means the setting is not a safe address (the page says so).
    host: the name the manager reached DA Management by, with or without a port."""
    setting = settings.WEB_LINK_WIKI if setting is None else setting
    public_portal = settings.PUBLIC_PORTAL if public_portal is None else public_portal
    port = settings.PORTAL_PORT if port is None else port
    setting = str(setting or "").strip()
    if setting.lower() == "off":
        return None, True
    if setting:
        return safe_address(setting), False
    if on_public_name and public_portal:
        return safe_address(public_portal.rstrip("/") + PATH), False
    name = str(host or "").strip().split(":")[0] if not str(host or "").startswith("[") else str(host).split("]")[0] + "]"
    if not name or not PORT_PATTERN.match(str(port)):
        return None, False
    scheme = scheme if scheme in ("http", "https") else "http"
    return safe_address(f"{scheme}://{name}:{port}{PATH}"), False


def current_address():
    """wiki_address for the request being served."""
    from flask import request
    import sign_in
    return wiki_address(request.host, request.scheme, sign_in.on_public_name())
