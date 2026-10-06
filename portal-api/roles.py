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


def can_edit_calendar(c):
    """The calendar: managers and Office."""
    return is_manager(c) or 'OFFICE' in roles(c)


def can_publish(c):
    """Announcements: managers and Office mission-wide; DL/ZL/STL within their own stewardship."""
    return is_manager(c) or 'OFFICE' in roles(c) or main_role(c) in LEADER_ROLES


def can_use_callins(c):
    """Call-ins: managers, DLs and ZLs. STLs have no part in Call-ins."""
    return is_manager(c) or main_role(c) in ('DL', 'ZL')


def can_use_presentations(c):
    """Presentations and their chart data: managers (every deck); ZL/STL (their own zone's decks, plus decks a
    manager shared with them); DLs (only decks a manager shared with them). Missionaries have no Presentations.
    Chart numbers always stay inside the viewer's own stewardship (charts.py)."""
    return is_manager(c) or main_role(c) in LEADER_ROLES


def presentation_zone(c):
    """The zone whose presentations this person makes and edits: a ZL's or STL's own zone. None for everyone else
    (managers edit every deck without owning one; DLs only open shared decks; missionaries have no Presentations)."""
    if is_manager(c) or main_role(c) not in PRESENTATION_LEADERS:
        return None
    return c.get('leadership_zone_id')


def can_unlock_plans(c):
    """Reopening a submitted plan: managers, DLs and ZLs (the database checks the stewardship)."""
    return is_manager(c) or main_role(c) in ('DL', 'ZL')


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


def can_edit_wiki(c):
    """Wiki docs editing: managers (AP, President, Data Analyst — also as an additional role)."""
    return is_manager(c)


def capabilities(c):
    """What the portal may offer this person in its menu (the API still checks every request)."""
    return {'manager': is_manager(c), 'calendar': can_edit_calendar(c), 'publish': can_publish(c),
            'dashboards': is_manager(c), 'management': can_manage_accounts(c),
            'callins': can_use_callins(c), 'presentations': can_use_presentations(c), 'glimpse': shows_glimpse(c),
            'archetypes': archetype_scope(c) is not None, 'wiki_edit': can_edit_wiki(c)}
