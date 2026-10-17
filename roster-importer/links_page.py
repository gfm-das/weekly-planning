"""The Links to web services page (/links): a tidy card per outside service (Gmail, Porkbun, Cloudflare) with what it is for.

For managers only: it is part of DA Management, which only the managers of the mission can open (sign_in.allowed(), checked
on every request). The addresses are settings (web_links.py); no password or key is stored or shown. Every text is links_text.py.
"""
from flask import Blueprint

import page
import sign_in
import web_links
import wiki_link
from links_text import t
from page import h

pages = Blueprint("links_page", __name__)


def wiki_card():
    """The Wiki button as a card: a link to the portal's wiki that opens in a new tab (nothing if the setting hides it)."""
    address, hidden = wiki_link.current_address()
    if hidden:
        return ""
    if not address:
        return f"<div class='card'><h3>{t('links.wiki.title')}</h3><p class='warn'>{t('links.wiki.notSet')}</p></div>"
    return (f"<div class='card'><h3>{t('links.wiki.title')}</h3><p>{t('links.wiki.about')}</p>"
            f"<div class='nav'><a href='{h(address)}' target='_blank' rel='noopener noreferrer'>{t('links.wiki.open')}</a></div></div>")


def links_body():
    cards = []
    for card in web_links.cards():
        if card["url"]:
            action = (f"<div class='nav'><a href='{h(card['url'])}' target='_blank' rel='noopener noreferrer'>"
                      f"{t('links.open', name=card['name'])}</a></div><p class='muted'>{h(card['host'])}</p>")
        else:
            action = f"<p class='warn'>{t('links.notSet')}</p>"
        cards.append(f"<div class='card'><h3>{h(card['name'])}</h3><p>{t(card['about'])}</p>{action}</div>")
    return (f"<div class='card'><h2>{t('links.title')}</h2><p class='muted'>{t('links.intro')}</p>"
            f"<p class='muted'>{t('links.noSecrets')}</p></div><div class='grid'>{''.join(cards)}</div>")


@pages.route("/wiki-link")
def wiki_button():
    """The Wiki tab of DA Management: one card with the button that opens the mission wiki. Managers only, like every page here."""
    if not sign_in.allowed():
        return sign_in.go_to_login()
    return page.render(wiki_card() or f"<div class='card'><p class='muted'>{t('links.wiki.notSet')}</p></div>")


@pages.route("/links")
def links():
    if not sign_in.allowed():
        return sign_in.go_to_login()
    return page.render(links_body())
