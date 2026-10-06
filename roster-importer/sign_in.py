"""Who may use DA Management, checked on every page.

There are two ways in:
  1. Through the portal (the normal way). The portal opens DA Management with ?portal_token=... in the address.
     sign_in_from_portal() asks Supabase Auth whose token it is, then reads that person's roles from the database.
     Only the managers of the mission get in (an AP with an AP assignment in force, the President, a Data Analyst).
     The session lasts 30 minutes, and every page checks the person again against the database (allowed()), so
     someone who is turned off or loses the role is out at their next click.
  2. The old shared password (/login), only when IMPORTER_PASSWORD is set. It has no person behind it, so some
     pages (Planning questions changes, Updates) need the portal way.

Every sent form also needs the session's secret form token (check_form_token), which page.render() puts into every
form.
"""
import secrets
import time
import uuid

import requests
from flask import Blueprint, flash, redirect, request, session

import database
import page
import roles
import settings

pages = Blueprint("sign_in", __name__)

SESSION_SECONDS = 30 * 60


# ------------------------------------------------------------------------------------------ the public name

def on_public_name():
    """True when this request came in on DA Management's internet name (settings.PUBLIC_NAME, round 10)."""
    return bool(settings.PUBLIC_NAME) and request.host.lower() == settings.PUBLIC_NAME


# ------------------------------------------------------------------------------------------ who is signed in

def allowed():
    """True when the person on this page may use DA Management (checked again on every page)."""
    if session.get("portal_role"):
        return portal_session_still_good()
    # An empty password must never let anyone in without signing in.
    # The shared password's session is never accepted on the public name (it could only come from there by mistake).
    return bool(settings.IMPORTER_PASSWORD) and session.get("authenticated") is True and not on_public_name()


def portal_session_still_good():
    """Checks a portal session against the database: still active, still a manager, still the same mission, and the
    30 minutes not over. Clears the session when anything changed."""
    context = live_context_of_session()
    if not context:
        session.clear()
        return False
    session["portal_role"] = context["management_role"]
    return session.get("authenticated") is True


def live_context_of_session():
    """The session person's management context as the database says it is now, or None."""
    if session.get("portal_role") not in roles.MANAGER_ROLES or session.get("portal_expires_at", 0) < time.time():
        return None
    user_id = session.get("portal_user_id")
    context = current_management_context(user_id) if user_id else None
    if not context or int(context["mission_id"]) != int(session.get("portal_mission_id") or 0):
        return None
    return context


def current_mission_id():
    """The mission of the signed-in manager."""
    return int(session.get("portal_mission_id") or settings.DEFAULT_MISSION_ID)


def actor_name():
    """The name Import history and the change histories write for whoever makes a change."""
    return session.get("portal_user") or "Importer administrator"


def portal_person():
    """(name, user id) of the person signed in through the portal, or None for the old shared password."""
    user_id = session.get("portal_user_id")
    if not user_id:
        return None
    return session.get("portal_user") or "Portal user", str(user_id)


def is_me(profile_id):
    """True when this user_profiles id is the signed-in person's own account."""
    return bool(profile_id) and str(profile_id) == str(session.get("portal_user_id") or "")


# ------------------------------------------------------------------------------------------ roles from the database

def current_management_context(user_id):
    """The person's live management context (see management_context), or None."""
    try:
        user_id = str(uuid.UUID(str(user_id)))
    except (ValueError, TypeError, AttributeError):
        return None
    with database.connect() as conn:
        with database.cursor(conn) as cur:
            return management_context(cur, user_id)


def management_context(cur, user_id):
    """What the database says about this person today: name, main and additional roles, their AP assignment, their
    mission and management_role. None when they may not use DA Management.

    Takes an open cursor, so a page can also ask about its own save before it is committed ("would this save end my
    own access?")."""
    # to_jsonb(up): additional_roles once migration 021 is applied, an empty list before.
    cur.execute("""select up.id user_id,up.app_role,up.active user_active,m.display_name,
      coalesce(to_jsonb(up)->'additional_roles','[]'::jsonb) additional_roles,
      coalesce(ap.mission_id,assignment.mission_id) mission_id,
      case when ap.mission_id is not null then 'AP' end leadership_role
      from public.user_profiles up left join public.missionaries m on m.id=up.missionary_id
      left join lateral (
        select la.mission_id from public.leadership_assignments la
        where la.missionary_id=up.missionary_id and la.role='AP' and la.start_date<=current_date
          and (la.end_date is null or la.end_date>=current_date)
        order by la.start_date desc,la.id desc limit 1
      ) ap on true
      left join lateral (
        select z.mission_id from public.missionary_assignments ma
        join public.areas a on a.id=ma.area_id join public.districts d on d.id=a.district_id
        join public.zones z on z.id=d.zone_id
        where ma.missionary_id=up.missionary_id and ma.start_date<=current_date
          and (ma.end_date is null or ma.end_date>=current_date)
        order by ma.start_date desc,ma.id desc limit 1
      ) assignment on true where up.id=%s""", (user_id,))
    context = with_home_mission(cur, cur.fetchone())
    if not context or not context["user_active"] or not context["mission_id"]:
        return None
    role = roles.management_role(context["app_role"], context["leadership_role"], context["additional_roles"])
    if role not in roles.MANAGER_ROLES:
        return None
    context["management_role"] = role
    return dict(context)


def with_home_mission(cur, context):
    """Staff accounts (a President or Data Analyst who is not a missionary, migration 027) have no area, so their
    mission is the home mission saved under Staff accounts, and their name is the one saved there."""
    if context and not context["mission_id"]:
        cur.execute("""select (to_jsonb(up)->>'home_mission_id')::bigint home_mission_id,to_jsonb(up)->>'display_name' display_name
          from public.user_profiles up where up.id=%s and up.missionary_id is null""", (context["user_id"],))
        staff = cur.fetchone()
        if staff and staff["home_mission_id"]:
            context["mission_id"] = staff["home_mission_id"]
            context["display_name"] = context["display_name"] or staff["display_name"]
    return context


def portal_context(access_token):
    """Whose portal token this is: Supabase Auth checks the token, the portal's own view must name the same person,
    then the database gives their live management context. None when anything does not fit."""
    if not access_token or not settings.SUPABASE_SERVICE_ROLE_KEY:
        return None
    headers = {"apikey": settings.SUPABASE_SERVICE_ROLE_KEY, "Authorization": f"Bearer {access_token}"}
    base = settings.SUPABASE_AUTH_INTERNAL_URL
    try:
        identity = requests.get(f"{base}/auth/v1/user", headers=headers, timeout=10)
        if not identity.ok:
            return None
        user_id = str(uuid.UUID(identity.json()["id"]))
        response = requests.get(f"{base}/rest/v1/current_user_context?select=*", params={"user_id": f"eq.{user_id}"},
                                headers=headers, timeout=10)
        if not response.ok:
            return None
        rows = response.json()
        if not isinstance(rows, list) or not rows or any(not isinstance(row, dict) or str(row.get("user_id")) != user_id for row in rows):
            return None
    except (requests.RequestException, ValueError, KeyError, TypeError):
        return None
    return current_management_context(user_id)


# ------------------------------------------------------------------------------------------ checks before every page

def sign_in_from_portal():
    """Runs before every page. When the portal sends ?portal_token=..., it starts a new session for that person (or
    refuses them), then opens the same page without the token in the address."""
    token = request.args.get("portal_token", "").strip()
    if not token:
        return None
    # A new portal person must never keep the session of the person before.
    session.clear()
    context = portal_context(token) or {}
    role = roles.management_role(context.get("app_role"), context.get("leadership_role"), context.get("additional_roles"))
    if role not in roles.MANAGER_ROLES or not context.get("user_active"):
        return page.render("<div class='error'><b>Management access denied.</b></div>", 403)
    session["authenticated"] = True
    session["portal_role"] = role
    session["portal_user"] = context.get("display_name") or "Portal administrator"
    session["portal_user_id"] = context.get("user_id")
    session["portal_mission_id"] = context.get("mission_id") or settings.DEFAULT_MISSION_ID
    session["portal_expires_at"] = time.time() + SESSION_SECONDS
    return redirect(request.path)


def check_form_token():
    """Runs before every page. A sent form (POST) must carry this session's secret form token (see page.render)."""
    if request.method != "POST":
        return None
    supplied = request.form.get("csrf_token", "")
    expected = session.get("csrf_token", "")
    if not expected or not secrets.compare_digest(supplied, expected):
        return page.render("<div class='error'>This form expired. Reload the page and try again.</div>", 403)
    return None


# ------------------------------------------------------------------------------------------ pages

@pages.route("/login", methods=["GET", "POST"])
def login():
    """The old shared password. Without IMPORTER_PASSWORD it only says to come through the portal. On the public name
    (round 10) neither: a shared password must not be guessable from the internet."""
    if not settings.IMPORTER_PASSWORD or on_public_name():
        return page.render("<div class='card'><h2>Sign in through Mission System</h2><p>Open management from your signed-in portal account.</p></div>", 403)
    if request.method == "POST":
        if secrets.compare_digest(request.form.get("password", ""), settings.IMPORTER_PASSWORD):
            session.clear()
            session["authenticated"] = True
            return redirect("/")
        flash("Incorrect password.")
    return page.render("""<div class="card"><h2>Admin login</h2><form method="post"><input type="password" name="password" required><button>Login</button></form></div>""")


@pages.route("/logout")
def logout():
    """The portal calls this when someone signs out of the portal."""
    session.clear()
    return "Management session signed out.", 200


def go_to_login():
    """Where a page sends someone who may not use it."""
    return redirect("/login")
