"""Links to web services: which cards DA Management > Links to web services shows (the page is links_page.py).

The addresses are settings (settings.WEB_SERVICE_URLS, from WEB_LINK_GMAIL, WEB_LINK_PORKBUN and WEB_LINK_CLOUDFLARE), never
code. Nothing secret is stored or shown: an address is shown only when it is a plain https address of a web page, without a
user name or password in it and without a query that looks like it carries a key (a link must be safe to print on a screen
that someone else may look at). "off" in a setting hides the card.
"""
import re
from urllib.parse import urlsplit

import settings

# The cards, in the order shown: (setting key, the service's name, the key of its short text "what it is for").
SERVICES = [("gmail", "Gmail", "links.gmail.about"),
            ("porkbun", "Porkbun", "links.porkbun.about"),
            ("cloudflare", "Cloudflare", "links.cloudflare.about")]
SECRET_WORDS = re.compile(r"pass|pwd|secret|token|key|auth|session|credential", re.IGNORECASE)
MAX_LENGTH = 300


def safe_url(value):
    """The address as it will be linked, or None when it is not a safe plain https web address."""
    text = str(value or "").strip()
    if not text or len(text) > MAX_LENGTH or any(ch.isspace() or ord(ch) < 32 for ch in text):
        return None
    try:
        parts = urlsplit(text)
        host = parts.hostname
    except ValueError:
        return None
    if parts.scheme != "https" or not host or "." not in host or parts.username or parts.password or "@" in parts.netloc:
        return None
    if SECRET_WORDS.search(parts.query) or SECRET_WORDS.search(parts.fragment):
        return None
    return text


def cards(urls=None):
    """[{key, name, about, url, host}] for the cards to show, in order. url is None for a card whose setting is not a safe
    address (the page says so); a card set to "off" is left out."""
    urls = settings.WEB_SERVICE_URLS if urls is None else urls
    shown = []
    for key, name, about in SERVICES:
        raw = str(urls.get(key) or "").strip()
        if raw.lower() == "off":
            continue
        url = safe_url(raw)
        shown.append({"key": key, "name": name, "about": about, "url": url, "host": urlsplit(url).hostname if url else None})
    return shown
