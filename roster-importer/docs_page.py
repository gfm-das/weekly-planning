"""DA Docs is retired (round 14). /docs leads to the portal wiki, which holds the same guide for data analysts."""
from flask import Blueprint, redirect

import sign_in

pages = Blueprint("docs_page", __name__)


@pages.route("/docs")
def management_docs():
    """The old DA Docs address: the portal wiki is the guide now."""
    if not sign_in.allowed():
        return sign_in.go_to_login()
    # Same-origin portal wiki (wiki_link derives the public / office address).
    import wiki_link
    address, _hidden = wiki_link.current_address()
    return redirect(address or "/wiki/")
