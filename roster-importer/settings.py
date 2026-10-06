"""The settings of DA Management, read once from the server's environment (the .env file next to docker-compose.yml).

Every other file reads its settings from here, so there is one place to look. Secrets (passwords and keys) are only
ever read, never printed or written anywhere.
"""
import os
from pathlib import Path

# Where the mission database is (a PostgreSQL address). DA Management cannot start without it.
DATABASE_URL = os.environ["DATABASE_URL"]

# The mission whose data DA Management shows when a person's own mission is not known (Frankfurt is mission 2).
DEFAULT_MISSION_ID = int(os.environ.get("MISSION_ID", "2"))

# The old shared password for DA Management. Empty means: no password sign-in at all, only through the portal.
IMPORTER_PASSWORD = os.environ.get("IMPORTER_PASSWORD", "")

# Signs the session cookie, so nobody can make up their own session.
SECRET_KEY = os.environ.get("SECRET_KEY", "change-me")

# A folder for files that wait between "check" and "apply" (a roster or a historical CSV, or the rows of a data upload).
UPLOAD_DIR = Path(os.environ.get("UPLOAD_DIR", "/tmp/roster-importer"))
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

# The mission's time zone (an IANA name such as America/Denver): the times DA Management shows are in it, and the database counts weeks
# in it too (public.gfm_time_zone(), migration 045). Europe/Berlin when nothing is set, as it always was.
TIME_ZONE_NAME = (os.environ.get("GFM_TIME_ZONE") or "Europe/Berlin").strip()

# Supabase Auth, the service that keeps everyone's sign-in (email and password).
SUPABASE_AUTH_INTERNAL_URL = os.environ.get("SUPABASE_AUTH_INTERNAL_URL", "http://supabase-kong:8000").rstrip("/")
SUPABASE_SERVICE_ROLE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
# Where the link in an invitation or password email leads (the portal).
PASSWORD_REDIRECT_URL = os.environ.get("PASSWORD_REDIRECT_URL", "http://localhost/")

# Round 10 (docs/handoff/round10/public-everything.md): DA Management's name on the internet, a Cloudflare tunnel route
# to port 8090, and the portal's public address there. On that name the session cookie is sent over https only, only
# the portal may show the pages in a frame, the translations come from the public portal, and the old shared password
# (/login) is not offered: from the internet only managers signed in through the portal get in. Empty turns it off.
# GFM_PUBLIC_DOMAIN (for example example.org) gives the defaults below: management.<domain> and https://<domain>. Empty:
# the mission has no public address and all three are off. Each can still be set on its own.
PUBLIC_DOMAIN = os.environ.get("GFM_PUBLIC_DOMAIN", "").strip().strip(".").lower()
PUBLIC_NAME = os.environ.get("MANAGEMENT_PUBLIC_NAME", f"management.{PUBLIC_DOMAIN}" if PUBLIC_DOMAIN else "").strip().lower()
PUBLIC_PORTAL = os.environ.get("MANAGEMENT_PUBLIC_PORTAL", f"https://{PUBLIC_DOMAIN}" if PUBLIC_DOMAIN else "").strip().rstrip("/")
PUBLIC_PORTAL_ORIGINS = [origin.strip().rstrip("/") for origin in os.environ.get(
    "MANAGEMENT_PUBLIC_PORTAL_ORIGINS",
    f"https://{PUBLIC_DOMAIN},https://www.{PUBLIC_DOMAIN}" if PUBLIC_DOMAIN else "").split(",") if origin.strip()]

# Where the pages load the portal's translations (i18n.js) from. Empty: the portal on this computer, port 8070 (on the
# public name: PUBLIC_PORTAL).
PORTAL_I18N_SRC = os.environ.get("PORTAL_I18N_SRC", "")

# The two folders shared with the updater on this computer (DA Management > Updates, see updates_page.py).
UPDATES_DIR = Path(os.environ.get("UPDATES_DIR", "/updates"))

# The biggest file anyone may upload: the Church's finding export of one year is about 13 MB.
MAX_UPLOAD_BYTES = 40 * 1024 * 1024

# PERSON_KEY_SECRET (for the finding export) is read by data_uploads.person_secret() each time it is needed.
