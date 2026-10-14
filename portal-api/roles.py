"""Who a signed-in person is and what they may do.

What it is: a small set of yes/no questions ("may this person edit the calendar?", "is this person a manager?").
Who uses it: every other file in portal-api. No other file decides a role on its own, so the rules live in one place.
How it fits: app.py reads the person's row from public.current_user_context (the "context", a plain dict) and every
question here looks only at that dict. Nothing here talks to the database.

A person has one MAIN role and may hold ADDITIONAL roles on top of it (migration 021):
- Main role: PRESIDENT, DATA_ADMIN or OFFICE when user_profiles.app_role says so (these are set by hand in
  DA Management). Otherwise the highest current leadership assignment (AP > ZL > STL > DL). Otherwise MISSIONARY.
  Stewardship (which zone, district or area someone sees) always follows the main role.
- Additional roles: user_profiles.additional_roles, a subset of {DATA_ADMIN, OFFICE}. "Data Analyst" (DATA_ADMIN)
  gives the manager rights; "Office" gives calendar editing and mission-wide announcement publishing. Other
  stewardship still follows the main role.

Missing columns count as empty, so a database without migration 021 simply has no additional roles.
The portal page keeps the same rules for its menu (portal/portal-enhancements.js); keep the two in step.
"""

# The managers: they read the whole mission.
MANAGER_ROLES = frozenset({'AP', 'PRESIDENT', 'DATA_ADMIN'})
ADDITIONAL_ROLES = ('DATA_ADMIN', 'OFFICE')
# Who may delete a closed zone, district or area or a retired Weekly Planning question (DA Management > Delete retired,
# roster-importer/roles.py may_retire). The portal itself offers no delete; the list is here so both images agree.
RETIRE_ROLES = frozenset({'AP', 'PRESIDENT', 'DATA_ADMIN'})
# Main roles that are set by hand on the account (not taken from leadership assignments).
MANUAL_MAIN_ROLES = frozenset({'PRESIDENT', 'DATA_ADMIN', 'OFFICE'})
# Leadership assignments, highest first.
LEADER_ORDER = ('AP', 'ZL', 'STL', 'DL')
LEADER_ROLES = frozenset({'DL', 'ZL', 'STL'})
# Zone Leaders and Sister Training Leaders make presentations for their own zone (round 7). DLs only open the decks a
# manager shared with them and make none. Missionaries have no Presentations.
PRESENTATION_LEADERS = frozenset({'ZL', 'STL'})
ROLE_LABELS = {
    'MISSIONARY': 'Missionary', 'DL': 'DL', 'ZL': 'ZL', 'STL': 'STL', 'AP': 'AP',
    'OFFICE': 'Office', 'PRESIDENT': 'President', 'DATA_ADMIN': 'Data Analyst',
}


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


def _upper(value):
    return str(value or '').strip().upper()


# ---------------------------------------------------------------------------------------------- which roles
def main_role(c):
    """The one role that decides stewardship: a hand-set role, else the leadership assignment, else MISSIONARY."""
    app_role = _upper(c.get('app_role'))
    if app_role in MANUAL_MAIN_ROLES:
        return app_role
    leadership = _upper(c.get('leadership_role'))
    if leadership in LEADER_ORDER:
        return leadership
    return 'MISSIONARY'


def additional_roles(c):
    """The extra roles on the account, in a fixed order, without the main role repeated."""
    values = {_upper(value) for value in (c.get('additional_roles') or [])}
    main = main_role(c)
    return [value for value in ADDITIONAL_ROLES if value in values and value != main]


def roles(c):
    """Every role the person holds: the main role first, then the additional roles."""
    return [main_role(c), *additional_roles(c)]


def describe(c):
    """A short label for the person's roles, e.g. "DL · Data Analyst"."""
    return ' · '.join(ROLE_LABELS.get(value, value.title()) for value in roles(c))


# ---------------------------------------------------------------------------------------------- what they may do
def is_manager(c):
    """AP, President or Data Analyst (also as an additional role): the whole mission, Call-ins notes,
    presentations, the mission focus, Dashboards, the Whiteboard."""
    return any(value in MANAGER_ROLES for value in roles(c))


def is_data_analyst(c):
    return 'DATA_ADMIN' in roles(c)


def has_ability(c, ability):
    """Does this person have one of the five switchable abilities (ABILITIES)? Any of their roles may give it: the managers
    always have it, the others as DA Management > Role abilities says (the built-in matrix when the table cannot be read)."""
    return held_ability(roles(c), ability)


def can_edit_calendar(c):
    """The calendar: managers and Office (Office can be switched off in DA Management > Role abilities)."""
    return has_ability(c, 'calendar.edit')


def can_publish(c):
    """Announcements: managers and Office mission-wide; DL/ZL/STL within their own stewardship (each can be switched off)."""
    return has_ability(c, 'announcements.publish')


def can_use_callins(c):
    """Call-ins: managers, DLs and ZLs. STLs have no part in Call-ins."""
    return is_manager(c) or main_role(c) in ('DL', 'ZL')


def can_view_vollzogen(c):
    """The read-only Vollzogen list (the people who were baptized and confirmed), GET /api/vollzogen (vollzogen.py): the
    managers (AP, President, Data Analyst) and Office, for the whole mission. It is a viewing right only: Office stays
    a non-manager (is_manager is False for Office) and gets no other right from it. DLs, ZLs, STLs and missionaries
    never see the list, because it holds names."""
    return has_ability(c, 'vollzogen.view')


def can_use_presentations(c):
    """Presentations and their chart data: managers (every deck); ZL/STL (their own zone's decks, plus decks a
    manager shared with them); DLs (only decks a manager shared with them). Missionaries have no Presentations.
    Chart numbers always stay inside the viewer's own stewardship (charts.py)."""
    return has_ability(c, 'presentations.use')


def presentation_zone(c):
    """The zone whose presentations this person makes and edits: a ZL's or STL's own zone. None for everyone else
    (managers edit every deck without owning one; DLs only open shared decks; missionaries have no Presentations)."""
    if is_manager(c) or main_role(c) not in PRESENTATION_LEADERS or not can_use_presentations(c):
        return None
    return c.get('leadership_zone_id')


def can_unlock_plans(c):
    """Reopening a submitted plan: managers, DLs and ZLs (the database checks the stewardship)."""
    return has_ability(c, 'plans.unlock')


def may_unlock_plan(c, where):
    """May this person reopen the plan of the area described by `where` (mission_id, zone_id, district_id)?
    Stewardship follows the main role: managers the whole mission, a ZL their zone, a DL their district. Nobody else.
    This is the first gate in planning.unlock_planning_report; the database checks it again (can_unlock_planning_area)."""
    if not can_unlock_plans(c):
        return False
    if is_manager(c):
        return where.get('mission_id') is not None and where.get('mission_id') == c.get('mission_id')
    main = main_role(c)
    if main == 'ZL':
        zone_id = c.get('leadership_zone_id') or c.get('zone_id')
        return zone_id is not None and where.get('zone_id') == zone_id
    if main == 'DL':
        district_id = c.get('leadership_district_id') or c.get('district_id')
        return district_id is not None and where.get('district_id') == district_id
    return False


def planning_scope(c):
    """The areas whose plans someone may view: 'mission' (managers), 'zone' (ZL), 'district' (DL), else None."""
    if is_manager(c):
        return 'mission'
    return {'ZL': 'zone', 'DL': 'district'}.get(main_role(c))


def archetype_scope(c):
    """Archetypal Health (archetypes.py): the whole mission for APs, the President and Data Analysts; nobody else."""
    return 'mission' if is_manager(c) else None


def target_scope(c, purpose='announcements'):
    """How far someone may aim a calendar event ('calendar') or an announcement or deck rule (anything else):
    'mission', 'zone', 'district' or 'area'. Managers reach the whole mission for every purpose. Office reaches the
    whole mission for calendar events and announcements, but does not widen presentation access. Everyone else uses
    their main role's stewardship."""
    if is_manager(c) or ('OFFICE' in roles(c) and purpose in {'calendar', 'announcements'}):
        return 'mission'
    return {'DL': 'district', 'ZL': 'zone', 'STL': 'zone'}.get(main_role(c), 'area')


def shows_glimpse(c):
    """The mission glimpse at the top of the Overview (portal/glimpse.js) and its numbers (GET /api/dashboard): the
    managers, the same people as Dashboards. The portal shell makes the same choice (portal-enhancements.js)."""
    return is_manager(c)


def can_manage_accounts(c):
    """DA Management: the President, a Data Analyst, or an AP (an AP main role needs a current AP assignment).
    DA Management checks this itself (roster-importer management_role); this is only what the portal shows."""
    return main_role(c) in ('AP', 'PRESIDENT') or is_data_analyst(c)


def can_retire_places(c):
    """Delete retired (DA Management): the managers. DA Management checks this itself (roster-importer roles.may_retire)."""
    return any(value in RETIRE_ROLES for value in roles(c))


def can_edit_wiki(c):
    """Wiki docs editing: managers (AP, President, Data Analyst — also as an additional role)."""
    return is_manager(c)


# The portal's interface languages (portal/i18n/catalogs.json; tests/test_roles.py checks the two stay the same).
INTERFACE_LANGUAGES = ('en', 'de', 'es', 'fr', 'pt', 'uk', 'ru', 'it', 'tr', 'fa', 'ro', 'sv', 'da', 'ar')


def can_choose_all_languages(c):
    """Every interface language, not only the ones DA Management assigned: managers (AP, President, Data Analyst,
    also as an additional role), the same people as can_edit_wiki. app.py language_choices uses it."""
    return is_manager(c)


def capabilities(c):
    """What the portal may offer this person in its menu (the API still checks every request)."""
    return {'manager': is_manager(c), 'calendar': can_edit_calendar(c), 'publish': can_publish(c),
            'dashboards': is_manager(c), 'management': can_manage_accounts(c),
            'callins': can_use_callins(c), 'vollzogen_view': can_view_vollzogen(c),
            'presentations': can_use_presentations(c), 'glimpse': shows_glimpse(c),
            'archetypes': archetype_scope(c) is not None, 'wiki_edit': can_edit_wiki(c),
            'all_languages': can_choose_all_languages(c)}
