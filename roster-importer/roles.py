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
# Who may delete a closed zone, district or area or a retired Weekly Planning question (DA Management > Delete retired,
# retire.py): the managers, signed in through the portal. The same list is in portal-api/roles.py (a test keeps them equal).
RETIRE_ROLES = {"AP", "PRESIDENT", "DATA_ADMIN"}
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

# >>> ROLE ABILITIES: shared block, identical in portal-api/roles.py and roster-importer/roles.py (tests.test_roles_in_step) >>>
# What each role may do for five switchable abilities (round 13, task 21; migration 055; DA Management > Accounts > Role abilities).
# The table public.role_abilities holds one switch per role and ability. The built-in matrix below is TODAY'S behaviour and is the
# fallback: if the table cannot be read, or holds anything that breaks a rule, the code uses the built-in matrix (never a wider one).
# Rules that no table row can change (the same rules are a CHECK in migration 055):
#   - AP, President and Data Analyst (MANAGER_ROLES) always have every ability, so nobody can be locked out;
#   - a Missionary has none;
#   - a cell that is not in SWITCHABLE keeps its built-in value;
#   - there is no ability for DA Management access, giving roles, deleting places or editing abilities: those are code rules for
#     managers only, so Office (or anyone else) can never become a manager through this table.
import threading
import time

ABILITY_ROLES = ('MISSIONARY', 'DL', 'ZL', 'STL', 'AP', 'OFFICE', 'PRESIDENT', 'DATA_ADMIN')
ABILITIES = ('calendar.edit', 'announcements.publish', 'vollzogen.view', 'presentations.use', 'plans.unlock')
# Who has the ability today (13 Oct 2026). A person has it if ANY of their roles (main or additional) has it.
DEFAULT_ROLES = {
    'calendar.edit': ('AP', 'OFFICE', 'PRESIDENT', 'DATA_ADMIN'),
    'announcements.publish': ('DL', 'ZL', 'STL', 'AP', 'OFFICE', 'PRESIDENT', 'DATA_ADMIN'),
    'vollzogen.view': ('AP', 'OFFICE', 'PRESIDENT', 'DATA_ADMIN'),
    'presentations.use': ('DL', 'ZL', 'STL', 'AP', 'PRESIDENT', 'DATA_ADMIN'),
    'plans.unlock': ('DL', 'ZL', 'AP', 'PRESIDENT', 'DATA_ADMIN'),
}
# The only cells a manager may switch. All of them are ON today, so a switch can take a right away and give it back, but it cannot
# give a role a right it does not have today (a DL with calendar editing would also see every event of the mission).
SWITCHABLE = {
    'calendar.edit': ('OFFICE',),
    'announcements.publish': ('DL', 'ZL', 'STL', 'OFFICE'),
    'vollzogen.view': ('OFFICE',),
    'presentations.use': ('DL', 'ZL', 'STL'),
    'plans.unlock': ('DL', 'ZL'),
}
DEFAULT_ABILITIES = {(role, ability): role in DEFAULT_ROLES[ability] for ability in ABILITIES for role in ABILITY_ROLES}
ABILITY_CACHE_SECONDS = 30   # a change reaches every part within this time (the saving part sees it at once)
ABILITY_RETRY_SECONDS = 5    # after a failed read, try again after this time

_abilities = {'fetch': None, 'table': None, 'until': 0.0, 'good': None}
_abilities_lock = threading.Lock()


def cell_is_valid(role, ability, allowed):
    """May this cell hold this value? The same rule as public.role_ability_ok in migration 055."""
    if role not in ABILITY_ROLES or ability not in ABILITIES or not isinstance(allowed, bool):
        return False
    if role in MANAGER_ROLES:
        return allowed
    if role == 'MISSIONARY':
        return not allowed
    if role in SWITCHABLE[ability]:
        return True
    return allowed == DEFAULT_ABILITIES[(role, ability)]


def parse_ability_rows(found):
    """{(role, ability): allowed} from the rows of the table, or None when anything is wrong: a row that is not
    (role, ability, true/false), an unknown role or ability, a value that breaks a rule, a cell twice, or a cell missing."""
    table = {}
    try:
        for row in found:
            role, ability, allowed = (row['role'], row['ability'], row['allowed']) if isinstance(row, dict) else tuple(row)
            cell = (str(role), str(ability))
            if not cell_is_valid(cell[0], cell[1], allowed) or cell in table:
                return None
            table[cell] = allowed
    except Exception:
        return None
    return table if set(table) == set(DEFAULT_ABILITIES) else None


def safe_fallback():
    """What the code uses when the table cannot be read: the built-in matrix, and where a manager had switched a right off
    (the last good read of this program), still off. Never a right the built-in matrix does not give."""
    good = _abilities['good'] or {}
    return {cell: bool(value and good.get(cell, True)) for cell, value in DEFAULT_ABILITIES.items()}


def set_ability_reader(fetch):
    """Tells this program how to read the table: fetch() returns its rows (role, ability, allowed). None: built-in matrix only."""
    with _abilities_lock:
        _abilities.update(fetch=fetch, table=None, until=0.0)


def forget_abilities():
    """Read the table again at the next question (the program that saves a change calls this)."""
    with _abilities_lock:
        _abilities.update(table=None, until=0.0)


def ability_table(read_again=False):
    """The matrix now: {(role, ability): allowed}, read from the table at most every 30 seconds."""
    with _abilities_lock:
        now = time.monotonic()
        if _abilities['table'] is not None and now < _abilities['until'] and not read_again:
            return _abilities['table']
        table = None
        if _abilities['fetch'] is not None:
            try:
                table = parse_ability_rows(_abilities['fetch']())
            except Exception:
                table = None
        if table is not None:
            _abilities.update(table=table, good=table, until=now + ABILITY_CACHE_SECONDS)
        else:
            _abilities.update(table=safe_fallback(), until=now + ABILITY_RETRY_SECONDS)
        return _abilities['table']


def ability_table_is_live():
    """True when the matrix in use was read from the table just now (False: the built-in matrix is in use)."""
    ability_table()
    return _abilities['good'] is not None and _abilities['table'] is _abilities['good']


def held_ability(held, ability):
    """Does a person who holds these roles have the ability? Managers always do; an unknown ability is always no."""
    if ability not in ABILITIES:
        return False
    if any(role in MANAGER_ROLES for role in held):
        return True
    table = ability_table()
    return any(table.get((role, ability), False) for role in held)
# <<< ROLE ABILITIES <<<


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


def may_retire():
    """May the signed-in manager delete a retired place or question? Only a manager signed in through the portal: the old
    shared password has no person behind it, and a delete must name who made it (Import history)."""
    return my_role() in RETIRE_ROLES


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
