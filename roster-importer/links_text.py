"""The English texts of DA Management > Links to web services (web_links.py and links_page.py).

Every text a person sees on that page comes from here, each under a key (links.*) in the style of the portal's translation
catalog. {name} marks a value filled in on the page. Translation: DA Management loads the portal's i18n.js, which translates
these English texts on the page from portal/i18n/*.json (14 languages); where the portal already had the same English text
the catalog keeps it under its own key. tests/test_links.py checks that every text is in the catalog.
"""
from html import escape

TEXT = {
    "links.title": "Links to web services",
    "links.intro": "The outside web services the mission system relies on. Each link opens the service in a new tab, where you sign in with your own account.",
    "links.noSecrets": "No password or key is kept here. The addresses come from the settings of this system.",
    "links.open": "Open {name}",
    "links.gmail.about": "Sends the system's emails (invitations and password emails) from the mission's Gmail account. The link opens Google's App passwords page, where the mail password is made or replaced.",
    "links.porkbun.about": "Holds the mission's web domain name: renewals and the DNS records that point it to this system.",
    "links.cloudflare.about": "Connects the mission's web address to this system safely (the Cloudflare tunnel) and manages its DNS and protection.",
    "links.wiki.title": "Wiki",
    "links.wiki.about": "The mission wiki: how every part of the portal works, in plain words, with guides for managers. It opens in a new tab. It is not in the portal's side menu.",
    "links.wiki.open": "Open the wiki",
    "links.wiki.notSet": "Not shown: the wiki address in the settings is not a safe web address.",
    "links.notSet": "Not shown: the address in the settings is missing or is not a safe web address.",
}


def plain(key, **values):
    """The English text of a key with its {values} filled in, as plain text."""
    text = TEXT[key]
    for name, value in values.items():
        text = text.replace("{" + name + "}", str(value))
    return text


def t(key, **values):
    """The same text made safe to put into a page (the text and every value are HTML-escaped)."""
    text = escape(TEXT[key])
    for name, value in values.items():
        text = text.replace("{" + name + "}", escape(str(value)))
    return text
