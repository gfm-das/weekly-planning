"""The roles of the mission system, and who may give which role.

A signed-in person has one MAIN role (user_profiles.app_role) and may have ADDITIONAL roles on top
(user_profiles.additional_roles, migration 021):

  Missionary  everyone
  DL, ZL, STL district leader, zone leader, sister training leader: come from a leadership assignment
  AP          assistant to the President: comes from a leadership assignment
  President   the mission president: set by hand
  Data Analyst (DATA_ADMIN)  keeps the data and the portal working: set by hand, usually as an additional role
  Office      edits the calendar: set by hand, usually as an additional role

DA Management (these pages) is for the managers of the mission: the President, the Data Analysts, and the APs while
their AP assignment is in force. Office gives no access here. The same rules are in portal-api/roles.py.
"""
from flask import session

# The managers of the mission: they may use DA Management.
MANAGER_ROLES = {"AP", "PRESIDENT", "DATA_ADMIN"}
# Leadership roles: they come from leadership assignments (a transfer roster or the account page), never set by hand.
LEADER_ROLES = {"DL", "ZL", "STL", "AP"}
# Highest first, as the database function public.sync_user_profile_roles() orders them.
LEADER_ORDER = ["AP", "ZL", "STL", "DL"]
# What a leader leads: a district, a zone or the whole mission.
LEADER_SCOPE = {"DL": "district", "ZL": "zone", "STL": "zone", "AP": "mission"}
# Roles set only by hand on an account page; a transfer roster never changes them.
HAND_SET_ROLES = {"OFFICE", "PRESIDENT", "DATA_ADMIN"}
# The hand-set roles that give DA Management access.
HIGH_ROLES = {"PRESIDENT", "DATA_ADMIN"}
# The main roles an account page offers, and the additional roles it offers on top.
MAIN_ROLES = ["MISSIONARY", "DL", "STL", "ZL", "AP", "PRESIDENT"]
ADDITIONAL_ROLES = ["DATA_ADMIN", "OFFICE"]

# How the pages name the roles (the leadership roles keep their short codes: DL, ZL, STL, AP).
ROLE_NAMES = {"MISSIONARY": "Missionary", "OFFICE": "Office", "PRESIDENT": "President", "DATA_ADMIN": "Data Analyst"}
# The hand-set roles in the order the pages list them.
HAND_SET_ROLE_NAMES = {"PRESIDENT": "President", "DATA_ADMIN": "Data Analyst", "OFFICE": "Office"}

# Whom to ask for a role that gives DA Management access (for someone who just lost their own).
WHO_GIVES_ACCESS = "an AP, the President or a Data Analyst"
# Who may give or take away a role that gives DA Management access. APs have full rights (the owner, 28 Sep).
# Office may be given by anyone who may use DA Management.
GIVEN_BY = {"PRESIDENT": HIGH_ROLES | {"AP"}, "DATA_ADMIN": HIGH_ROLES | {"AP"}}
# Shown on a missionary's account page, and when its save is refused, to someone who may not change that account.
NOT_ALLOWED_ACCOUNT = "Only an AP, the President or a Data Analyst can turn off the President's account or change its roles."


def role_name(role):
    """'Data Analyst' for DATA_ADMIN; the leadership roles stay as they are (ZL)."""
    return ROLE_NAMES.get(role, role)


def management_role(app_role, leadership_role, additional_roles=()):
    """The role that lets someone use DA Management, or None.

    President: from the main role. Data Analyst: from the main role or an additional role. AP: only from an AP
    assignment in force today (leadership_role), never from a saved main role AP alone. Office gives no access."""
    app_role = str(app_role or "").upper()
    if app_role == "PRESIDENT":
        return app_role
    if app_role == "DATA_ADMIN" or "DATA_ADMIN" in {str(r).upper() for r in (additional_roles or [])}:
        return "DATA_ADMIN"
    return "AP" if str(leadership_role or "").upper() == "AP" else None


def my_role():
    """The signed-in manager's role: PRESIDENT, DATA_ADMIN or AP; None for the old shared password."""
    return session.get("portal_role")


def may_give(role):
    """May the signed-in manager give or take away this role? President and Data Analyst: an AP, the President or a
    Data Analyst. Office: anyone here. The old shared password (no portal role) may give every role."""
    return role not in GIVEN_BY or my_role() in GIVEN_BY[role] or not session.get("portal_role")


def additional_roles_of(profile):
    """A user_profiles row's additional roles as a list of capital codes; [] for a row without them."""
    return [str(r).upper() for r in ((profile or {}).get("additional_roles") or [])]


def all_roles_of(profile):
    """Every role of a user_profiles row: the main role and the additional roles."""
    return ({str((profile or {}).get("app_role") or "").upper()} | set(additional_roles_of(profile))) - {""}


def may_change(profile):
    """May the signed-in manager change this user_profiles row? Only if they may give every role it has that gives
    DA Management access (today every AP, President and Data Analyst may)."""
    if not profile:
        return True
    return may_give(profile.get("app_role")) and ("DATA_ADMIN" not in additional_roles_of(profile) or may_give("DATA_ADMIN"))


def leads_the_same(leader, role, place_ids):
    """True when a leadership row (a dict with district_id, zone_id, mission_id) leads the same district, zone or
    mission as `role` would at these places. place_ids: (district id, zone id, mission id)."""
    district_id, zone_id, mission_id = place_ids
    scope = LEADER_SCOPE[role]
    if scope == "district":
        return leader["district_id"] == district_id
    if scope == "zone":
        return leader["zone_id"] == zone_id
    return leader["mission_id"] == mission_id
