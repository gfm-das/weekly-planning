"""DA Management: the program behind the "DA Management" pages of the portal.

What it is: a small web server (Flask) that the portal shows inside a frame. The managers of the mission (the
President, the Data Analysts, and the APs) use it to import transfer rosters, manage accounts and roles, change the
Weekly Planning questions, upload data, look at Import history (and undo things), and update the mission system.

How it starts: gunicorn runs `app:app` (see Dockerfile), which is the `app` made below.

This file only puts the pieces together:
  1. the settings (settings.py),
  2. the checks that run before every page, in this order:
       - a portal sign-in in the address (?portal_token=...) starts a new session (sign_in.py),
       - a sent form must carry the session's secret form token (sign_in.py),
       - now and then, uploads left waiting for more than a day are deleted (data_uploads.py),
  3. every group of pages. Each page file has one Flask "Blueprint" called `pages` (a group of pages),
  4. after every page: the page is packed with gzip on its way to the browser (see pack()).

README.md says which file makes which page.
"""
import gzip

from flask import Flask, request
from flask.sessions import SecureCookieSessionInterface

import account_manager
import account_page
import data_upload_pages
import data_uploads
import docs_page
import historical_pages
import import_history
import mappings_page
import people_pages
import places_admin
import people_upload_pages
import planning_questions_pages
import settings
import sign_in
import staff_accounts
import transfer_pages
import updates_page

app = Flask(__name__)
app.secret_key = settings.SECRET_KEY
app.config["MAX_CONTENT_LENGTH"] = settings.MAX_UPLOAD_BYTES
# The session cookie has its own name (the portal has its own cookies), and page scripts cannot read it.
app.config.update(SESSION_COOKIE_NAME="gfm_roster_session", SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax")


class SessionCookie(SecureCookieSessionInterface):
    """Round 10: on the public name (https through the Cloudflare tunnel) the session cookie is sent over https only.
    It stays a cookie of DA Management's own name (no Domain), as on the office address."""

    def get_cookie_secure(self, app):
        return super().get_cookie_secure(app) or sign_in.on_public_name()


app.session_interface = SessionCookie()

app.before_request(sign_in.sign_in_from_portal)
app.before_request(sign_in.check_form_token)
app.before_request(data_uploads.tidy_now_and_then)

PAGE_GROUPS = [
    sign_in,             # /login, /logout
    transfer_pages,      # Roster Import: /, /preview, /apply
    account_manager,     # Account Manager: /accounts, /accounts/send
    account_page,        # one missionary's account: /accounts/<id>
    planning_questions_pages,  # Planning questions: /planning-questions/...
    historical_pages,    # Historical CSV: /historical/...
    mappings_page,       # Area mappings: /mappings
    places_admin,        # Places (close and reopen zones, districts, areas): /places/...
    people_pages,        # "Same person?" answers of upload checks: /people/decide
    people_upload_pages,  # People upload: /people-upload/...
    staff_accounts,      # Staff accounts: /staff/...
    data_upload_pages,   # Data uploads: /uploads/...
    import_history,      # Import history: /imports/...
    docs_page,           # DA Docs: /docs
    updates_page,        # Updates: /updates/...
]
for group in PAGE_GROUPS:
    app.register_blueprint(group.pages)

# Pages and the answers for page scripts are text that gzip packs to about a tenth (Account Manager: 107 KB -> 12 KB).
PACKED_KINDS = {"text/html", "application/json"}
SMALLEST_TO_PACK = 1024  # bytes; smaller answers are sent as they are


@app.after_request
def pack(response):
    """Runs after every page: packs it with gzip when the browser accepts that (every browser does). Downloads (the
    CSV templates) and short answers are sent as they are."""
    if (response.mimetype in PACKED_KINDS and not response.direct_passthrough and not response.is_streamed
            and not response.content_encoding and "gzip" in request.accept_encodings):
        data = response.get_data()
        if len(data) >= SMALLEST_TO_PACK:
            response.set_data(gzip.compress(data, compresslevel=6))
            response.content_encoding = "gzip"
            response.vary.add("accept-encoding")  # a cache must keep the packed and the plain page apart
    return response


@app.after_request
def public_name_headers(response):
    """Round 10: on the public name only the portal (and DA Management itself) may show these pages in a frame, so no
    other website can lay them under its own buttons, and no answer is kept by Cloudflare or the browser. The office
    address keeps its answers as they were."""
    if sign_in.on_public_name():
        response.headers["Content-Security-Policy"] = "frame-ancestors " + " ".join(["'self'", *settings.PUBLIC_PORTAL_ORIGINS])
        # Every answer here is for one signed-in manager: Cloudflare and the browser must never keep a copy for others.
        response.headers.setdefault("Cache-Control", "no-store")
    return response


@app.route("/health")
def health():
    """For health checks (health.ps1): answers as long as the program runs. It does not look at the database."""
    return {"status": "ok", "version": "2.0"}


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
