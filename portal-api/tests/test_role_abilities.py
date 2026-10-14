"""Role abilities in portal-api/roles.py (round 13, task 21; migration 055), without a database.

Proves: (1) with no table, or a table that holds the built-in matrix, every kind of person gets exactly the answers the old hard-coded
rules gave, for the five abilities; (2) a table that cannot be read, or holds anything that breaks a rule, never widens anyone's rights;
(3) the rules no switch can change; plus the 30 second cache and one valid switch changing exactly one cell.

Run in the portal-api image (no pytest needed):
  docker run --rm --network none -v <repo>/portal-api:/app -w /app gfm-portal-portal-api python tests/test_role_abilities.py
"""
import itertools
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault('SUPABASE_URL', 'http://supabase.invalid')
os.environ.setdefault('SUPABASE_SERVICE_ROLE_KEY', 'unit-test-only')
import roles  # noqa: E402

MANAGERS = {'AP', 'PRESIDENT', 'DATA_ADMIN'}

# The matrix of docs/handoff/round13/role-abilities-design.md, section 2 (checked 12 Oct 2026), for the five abilities.
GOLDEN = {
    'MISSIONARY': {'calendar.edit': 0, 'announcements.publish': 0, 'vollzogen.view': 0, 'presentations.use': 0, 'plans.unlock': 0},
    'DL': {'calendar.edit': 0, 'announcements.publish': 1, 'vollzogen.view': 0, 'presentations.use': 1, 'plans.unlock': 1},
    'ZL': {'calendar.edit': 0, 'announcements.publish': 1, 'vollzogen.view': 0, 'presentations.use': 1, 'plans.unlock': 1},
    'STL': {'calendar.edit': 0, 'announcements.publish': 1, 'vollzogen.view': 0, 'presentations.use': 1, 'plans.unlock': 0},
    'AP': {'calendar.edit': 1, 'announcements.publish': 1, 'vollzogen.view': 1, 'presentations.use': 1, 'plans.unlock': 1},
    'OFFICE': {'calendar.edit': 1, 'announcements.publish': 1, 'vollzogen.view': 1, 'presentations.use': 0, 'plans.unlock': 0},
    'PRESIDENT': {'calendar.edit': 1, 'announcements.publish': 1, 'vollzogen.view': 1, 'presentations.use': 1, 'plans.unlock': 1},
    'DATA_ADMIN': {'calendar.edit': 1, 'announcements.publish': 1, 'vollzogen.view': 1, 'presentations.use': 1, 'plans.unlock': 1},
}
FUNCTIONS = {'calendar.edit': roles.can_edit_calendar, 'announcements.publish': roles.can_publish,
             'vollzogen.view': roles.can_view_vollzogen, 'presentations.use': roles.can_use_presentations,
             'plans.unlock': roles.can_unlock_plans}


# The old rules, copied from roles.py as it was before migration 055 (they must never be edited to fit the new code).
def old_is_manager(c):
    return any(value in roles.MANAGER_ROLES for value in roles.roles(c))


def old_answers(c):
    return {'calendar.edit': old_is_manager(c) or 'OFFICE' in roles.roles(c),
            'announcements.publish': old_is_manager(c) or 'OFFICE' in roles.roles(c) or roles.main_role(c) in roles.LEADER_ROLES,
            'vollzogen.view': old_is_manager(c) or 'OFFICE' in roles.roles(c),
            'presentations.use': old_is_manager(c) or roles.main_role(c) in roles.LEADER_ROLES,
            'plans.unlock': old_is_manager(c) or roles.main_role(c) in ('DL', 'ZL')}


def everybody():
    """Every kind of person: each saved main role, each leadership assignment and each set of additional roles."""
    for app_role, leader, extra in itertools.product(
            (None, 'MISSIONARY', 'OFFICE', 'PRESIDENT', 'DATA_ADMIN', 'AP'), (None, 'DL', 'ZL', 'STL', 'AP'),
            ([], ['DATA_ADMIN'], ['OFFICE'], ['DATA_ADMIN', 'OFFICE'])):
        yield {'app_role': app_role, 'leadership_role': leader, 'additional_roles': extra}


def rows_of(table):
    return [{'role': role, 'ability': ability, 'allowed': allowed} for (role, ability), allowed in table.items()]


def reset(fetch=None):
    roles.set_ability_reader(fetch)
    roles._abilities['good'] = None


class Defaults(unittest.TestCase):
    def setUp(self):
        reset()

    def test_the_built_in_matrix_is_the_golden_matrix(self):
        for role, abilities in GOLDEN.items():
            for ability, wanted in abilities.items():
                self.assertEqual(roles.DEFAULT_ABILITIES[(role, ability)], bool(wanted), (role, ability))
        self.assertEqual(set(roles.DEFAULT_ABILITIES), {(r, a) for r in GOLDEN for a in roles.ABILITIES})
        self.assertEqual(len(roles.DEFAULT_ABILITIES), 40)

    def test_without_a_table_everybody_gets_the_old_answers(self):
        for c in everybody():
            wanted = old_answers(c)
            for ability, function in FUNCTIONS.items():
                self.assertEqual(function(c), wanted[ability], (c, ability))
                self.assertEqual(roles.has_ability(c, ability), wanted[ability], (c, ability))

    def test_with_a_table_that_holds_the_built_in_matrix_everybody_gets_the_old_answers(self):
        reset(lambda: rows_of(roles.DEFAULT_ABILITIES))
        for c in everybody():
            wanted = old_answers(c)
            for ability, function in FUNCTIONS.items():
                self.assertEqual(function(c), wanted[ability], (c, ability))
        self.assertTrue(roles.ability_table_is_live())

    def test_the_menu_answers_are_unchanged(self):
        for c in everybody():
            caps, wanted = roles.capabilities(c), old_answers(c)
            self.assertEqual((caps['calendar'], caps['publish'], caps['vollzogen_view'], caps['presentations']),
                             (wanted['calendar.edit'], wanted['announcements.publish'], wanted['vollzogen.view'], wanted['presentations.use']), c)

    def test_a_person_keeps_a_right_one_of_their_roles_gives(self):
        reset(lambda: rows_of({**roles.DEFAULT_ABILITIES, ('OFFICE', 'calendar.edit'): False}))
        office_only = {'app_role': 'OFFICE'}
        zl_and_office = {'leadership_role': 'ZL', 'additional_roles': ['OFFICE']}
        self.assertFalse(roles.can_edit_calendar(office_only))
        self.assertFalse(roles.can_edit_calendar(zl_and_office))  # a ZL has no calendar right of their own
        self.assertTrue(roles.can_edit_calendar({'app_role': 'OFFICE', 'additional_roles': ['DATA_ADMIN']}))  # a manager


class OneSwitch(unittest.TestCase):
    def test_switching_office_off_changes_exactly_that_cell(self):
        for ability, role in [(a, r) for a, roles_ in roles.SWITCHABLE.items() for r in roles_]:
            table = {**roles.DEFAULT_ABILITIES, (role, ability): False}
            reset(lambda table=table: rows_of(table))
            live = roles.ability_table()
            self.assertEqual([cell for cell in live if live[cell] != roles.DEFAULT_ABILITIES[cell]], [(role, ability)])
            self.assertTrue(roles.ability_table_is_live())
        reset()

    def test_a_switch_takes_effect_for_that_role_only(self):
        reset(lambda: rows_of({**roles.DEFAULT_ABILITIES, ('DL', 'plans.unlock'): False}))
        self.assertFalse(roles.can_unlock_plans({'leadership_role': 'DL'}))
        self.assertTrue(roles.can_unlock_plans({'leadership_role': 'ZL'}))
        self.assertTrue(roles.can_unlock_plans({'leadership_role': 'DL', 'additional_roles': ['DATA_ADMIN']}))
        reset()

    def test_may_unlock_plan_follows_the_switch_and_keeps_the_stewardship(self):
        where = {'mission_id': 1, 'zone_id': 5, 'district_id': 7}
        dl = {'leadership_role': 'DL', 'leadership_district_id': 7, 'mission_id': 1}
        reset()
        self.assertTrue(roles.may_unlock_plan(dl, where))
        self.assertFalse(roles.may_unlock_plan({**dl, 'leadership_district_id': 8}, where))
        reset(lambda: rows_of({**roles.DEFAULT_ABILITIES, ('DL', 'plans.unlock'): False}))
        self.assertFalse(roles.may_unlock_plan(dl, where))
        reset()

    def test_switching_presentations_off_also_removes_the_zone_of_a_zl(self):
        zl = {'leadership_role': 'ZL', 'leadership_zone_id': 7}
        reset()
        self.assertEqual(roles.presentation_zone(zl), 7)
        reset(lambda: rows_of({**roles.DEFAULT_ABILITIES, ('ZL', 'presentations.use'): False}))
        self.assertFalse(roles.can_use_presentations(zl))
        self.assertIsNone(roles.presentation_zone(zl))
        reset()


class BrokenTable(unittest.TestCase):
    """A table that cannot be read, or breaks a rule, must never give anybody a right the built-in matrix does not give."""

    def never_wider(self):
        table = roles.ability_table()
        for cell, allowed in table.items():
            self.assertLessEqual(allowed, roles.DEFAULT_ABILITIES[cell], cell)
        for c in everybody():
            wanted = old_answers(c)
            for ability, function in FUNCTIONS.items():
                self.assertLessEqual(function(c), wanted[ability], (c, ability))

    def test_a_reader_that_raises(self):
        def broken():
            raise RuntimeError('database is down')
        reset(broken)
        self.never_wider()
        self.assertEqual(roles.ability_table(), roles.DEFAULT_ABILITIES)
        self.assertFalse(roles.ability_table_is_live())

    def test_a_reader_that_answers_with_rubbish(self):
        good = rows_of(roles.DEFAULT_ABILITIES)
        rubbish = {
            'nothing at all': None,
            'not rows': 42,
            'an empty table': [],
            'a missing cell': good[1:],
            'a cell twice': good + [good[0]],
            'an unknown role': good[1:] + [{'role': 'KING', 'ability': 'calendar.edit', 'allowed': True}],
            'an unknown ability': good[1:] + [{'role': 'DL', 'ability': 'management', 'allowed': True}],
            'a value that is not true or false': [dict(r, allowed='yes') if i == 3 else r for i, r in enumerate(good)],
            'a number': [dict(r, allowed=1) if i == 3 else r for i, r in enumerate(good)],
            'a missing value': [dict(r, allowed=None) if i == 3 else r for i, r in enumerate(good)],
            'a short row': [('DL', 'plans.unlock')] + good[1:],
            'a lower-case role': [dict(r, role=r['role'].lower()) for r in good],
        }
        for what, answer in rubbish.items():
            with self.subTest(what):
                reset(lambda answer=answer: answer)
                self.never_wider()
                self.assertEqual(roles.ability_table(), roles.DEFAULT_ABILITIES)
                self.assertFalse(roles.ability_table_is_live())

    def test_every_rule_breaking_cell_makes_the_whole_table_unusable(self):
        """One wrong cell and the table is refused as a whole: the code falls back, it does not use the other 39 cells."""
        for (role, ability), default in roles.DEFAULT_ABILITIES.items():
            table = {**roles.DEFAULT_ABILITIES, (role, ability): not default}
            fixed = role in MANAGERS or role == 'MISSIONARY' or role not in roles.SWITCHABLE[ability]
            parsed = roles.parse_ability_rows(rows_of(table))
            if fixed:
                self.assertIsNone(parsed, (role, ability))
            else:
                self.assertEqual(parsed, table, (role, ability))

    def test_a_valid_narrowing_survives_a_later_failure_but_a_grant_does_not_outlive_it(self):
        answers = [rows_of({**roles.DEFAULT_ABILITIES, ('OFFICE', 'vollzogen.view'): False})]

        def reader():
            if answers:
                return answers.pop(0)
            raise RuntimeError('database is down')
        reset(reader)
        self.assertFalse(roles.can_view_vollzogen({'app_role': 'OFFICE'}))
        roles.forget_abilities()  # the cache runs out; the next read fails
        self.assertFalse(roles.can_view_vollzogen({'app_role': 'OFFICE'}))  # still off: a failure does not give it back
        self.assertFalse(roles.ability_table_is_live())
        self.never_wider()
        # A grant (should one ever exist) is not kept when the table can no longer be read: only the built-in value counts.
        roles._abilities['good'] = {**roles.DEFAULT_ABILITIES, ('DL', 'calendar.edit'): True}
        roles.forget_abilities()
        self.assertFalse(roles.ability_table()[('DL', 'calendar.edit')])
        reset()

    def test_the_table_is_read_again_after_a_failure(self):
        calls = []

        def reader():
            calls.append(1)
            if len(calls) == 1:
                raise RuntimeError('first read fails')
            return rows_of(roles.DEFAULT_ABILITIES)
        reset(reader)
        roles.ability_table()
        with patch.object(roles.time, 'monotonic', return_value=roles._abilities['until'] + 0.1):
            self.assertEqual(roles.ability_table(), roles.DEFAULT_ABILITIES)
        self.assertEqual(len(calls), 2)
        self.assertTrue(roles.ability_table_is_live())
        reset()


class NeverSwitchable(unittest.TestCase):
    def setUp(self):
        reset()

    def test_managers_keep_every_ability_whatever_the_table_says(self):
        for role in MANAGERS:
            for ability in roles.ABILITIES:
                self.assertFalse(roles.cell_is_valid(role, ability, False), (role, ability))
                self.assertTrue(roles.cell_is_valid(role, ability, True), (role, ability))
        # Even a matrix that says "no" everywhere (it cannot be read in, but suppose it were in use) does not touch a manager.
        with patch.object(roles, 'ability_table', return_value={cell: False for cell in roles.DEFAULT_ABILITIES}):
            for c in ({'leadership_role': 'AP'}, {'app_role': 'PRESIDENT'}, {'app_role': 'DATA_ADMIN'},
                      {'app_role': 'MISSIONARY', 'leadership_role': 'DL', 'additional_roles': ['DATA_ADMIN']}):
                for ability in roles.ABILITIES:
                    self.assertTrue(roles.has_ability(c, ability), (c, ability))
            self.assertFalse(roles.has_ability({'app_role': 'OFFICE'}, 'calendar.edit'))  # while Office loses it

    def test_a_missionary_never_has_an_ability(self):
        for ability in roles.ABILITIES:
            self.assertFalse(roles.cell_is_valid('MISSIONARY', ability, True))
            self.assertFalse(roles.has_ability({'app_role': 'MISSIONARY'}, ability))
            self.assertFalse(roles.has_ability({}, ability))

    def test_only_the_listed_cells_are_switchable_and_all_are_on_today(self):
        switchable = {(role, ability) for ability, listed in roles.SWITCHABLE.items() for role in listed}
        self.assertEqual(switchable, {('OFFICE', 'calendar.edit'), ('DL', 'announcements.publish'), ('ZL', 'announcements.publish'),
                                      ('STL', 'announcements.publish'), ('OFFICE', 'announcements.publish'), ('OFFICE', 'vollzogen.view'),
                                      ('DL', 'presentations.use'), ('ZL', 'presentations.use'), ('STL', 'presentations.use'),
                                      ('DL', 'plans.unlock'), ('ZL', 'plans.unlock')})
        for cell in switchable:
            self.assertTrue(roles.DEFAULT_ABILITIES[cell], cell)  # so a switch can only take a right away and give it back
            self.assertTrue(roles.cell_is_valid(*cell, True) and roles.cell_is_valid(*cell, False), cell)
        for (role, ability), default in roles.DEFAULT_ABILITIES.items():
            if (role, ability) not in switchable and role not in MANAGERS and role != 'MISSIONARY':
                self.assertFalse(roles.cell_is_valid(role, ability, not default), (role, ability))

    def test_nothing_in_the_table_widens_stewardship(self):
        """No cell may be given to a role that does not have it today, so no switch can reach a role the stewardship code
        does not already limit (a DL with calendar editing would see every event of the mission)."""
        for (role, ability), default in roles.DEFAULT_ABILITIES.items():
            if not default:
                self.assertFalse(roles.cell_is_valid(role, ability, True), (role, ability))

    def test_there_is_no_ability_for_access_roles_deleting_or_editing_abilities(self):
        for word in ('manage', 'management', 'role', 'account', 'retire', 'delete', 'ability', 'abilities', 'admin'):
            for ability in roles.ABILITIES:
                self.assertNotIn(word, ability)
        self.assertEqual(len(roles.ABILITIES), 5)
        self.assertFalse(roles.has_ability({'app_role': 'DATA_ADMIN'}, 'management'))  # an unknown ability is always "no"
        self.assertFalse(roles.has_ability({'app_role': 'DATA_ADMIN'}, ''))

    def test_office_never_becomes_a_manager_whatever_the_table_says(self):
        reset(lambda: rows_of({**roles.DEFAULT_ABILITIES}))
        for c in ({'app_role': 'OFFICE'}, {'app_role': 'MISSIONARY', 'additional_roles': ['OFFICE']},
                  {'leadership_role': 'DL', 'additional_roles': ['OFFICE']}):
            caps = roles.capabilities(c)
            self.assertFalse(roles.is_manager(c))
            for key in ('manager', 'dashboards', 'management', 'glimpse', 'archetypes', 'wiki_edit', 'all_languages'):
                self.assertFalse(caps[key], (c, key))
            self.assertFalse(roles.can_manage_accounts(c))
            self.assertFalse(roles.can_retire_places(c))
            self.assertFalse(roles.can_use_callins({'app_role': 'OFFICE'}))
        reset()

    def test_the_data_analyst_can_never_lose_management_or_ability_editing(self):
        for c in ({'app_role': 'DATA_ADMIN'}, {'app_role': 'MISSIONARY', 'additional_roles': ['DATA_ADMIN']}):
            self.assertTrue(roles.can_manage_accounts(c))
            self.assertTrue(roles.is_manager(c))
        # Management and ability editing are not read from the table at all.
        source = (Path(__file__).resolve().parents[1] / 'roles.py').read_text(encoding='utf-8')
        body = source[source.index('def can_manage_accounts'):source.index('def can_retire_places')]
        self.assertNotIn('ability_table', body)
        self.assertNotIn('has_ability', body)


class Cache(unittest.TestCase):
    def test_the_table_is_read_at_most_every_30_seconds(self):
        calls = []

        def reader():
            calls.append(1)
            return rows_of(roles.DEFAULT_ABILITIES)
        reset(reader)
        c = {'app_role': 'OFFICE'}
        for _ in range(50):
            roles.can_edit_calendar(c)
        self.assertEqual(len(calls), 1)
        later = roles._abilities['until'] + 0.1
        with patch.object(roles.time, 'monotonic', return_value=later):
            roles.can_edit_calendar(c)
        self.assertEqual(len(calls), 2)
        roles.forget_abilities()
        roles.can_edit_calendar(c)
        self.assertEqual(len(calls), 3)
        self.assertEqual(roles.ABILITY_CACHE_SECONDS, 30)
        reset()

    def test_the_portal_api_registers_its_reader(self):
        source = (Path(__file__).resolve().parents[1] / 'app.py').read_text(encoding='utf-8')
        self.assertIn('roles.set_ability_reader(read_role_abilities)', source)
        self.assertIn('FROM public.role_abilities', source)


if __name__ == '__main__':
    unittest.main()
