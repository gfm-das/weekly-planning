"""Unit checks for roles.py (main role plus additional Data Analyst / Office roles).

Run in the portal-api image (no pytest needed):
  docker run --rm -v <repo>/portal-api:/app -w /app gfm-portal-portal-api python tests/test_roles.py
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import roles  # noqa: E402


class MainRole(unittest.TestCase):
    def test_leadership_decides_for_missionaries(self):
        self.assertEqual(roles.main_role({'app_role': 'MISSIONARY', 'leadership_role': 'ZL'}), 'ZL')
        self.assertEqual(roles.main_role({'app_role': 'MISSIONARY', 'leadership_role': None}), 'MISSIONARY')

    def test_app_role_ap_without_assignment_is_not_ap(self):
        self.assertEqual(roles.main_role({'app_role': 'AP', 'leadership_role': None}), 'MISSIONARY')
        self.assertEqual(roles.main_role({'app_role': 'AP', 'leadership_role': 'AP'}), 'AP')

    def test_stale_app_role_dl_without_assignment(self):
        self.assertEqual(roles.main_role({'app_role': 'DL', 'leadership_role': None}), 'MISSIONARY')

    def test_manual_main_roles_win(self):
        for value in ('PRESIDENT', 'DATA_ADMIN', 'OFFICE'):
            self.assertEqual(roles.main_role({'app_role': value, 'leadership_role': 'DL'}), value)


class AdditionalRoles(unittest.TestCase):
    def test_dl_who_is_also_data_analyst(self):
        c = {'app_role': 'MISSIONARY', 'leadership_role': 'DL', 'additional_roles': ['DATA_ADMIN']}
        self.assertEqual(roles.roles(c), ['DL', 'DATA_ADMIN'])
        self.assertTrue(roles.is_manager(c))
        self.assertTrue(roles.is_data_analyst(c))
        self.assertEqual(roles.main_role(c), 'DL')
        self.assertEqual(roles.describe(c), 'DL · Data Analyst')

    def test_office_is_not_a_manager(self):
        c = {'app_role': 'MISSIONARY', 'leadership_role': 'ZL', 'additional_roles': ['office']}
        self.assertFalse(roles.is_manager(c))
        self.assertTrue(roles.can_edit_calendar(c))
        self.assertTrue(roles.can_publish(c))
        self.assertEqual(roles.roles(c), ['ZL', 'OFFICE'])

    def test_unknown_and_duplicate_values_are_ignored(self):
        c = {'app_role': 'OFFICE', 'additional_roles': ['OFFICE', 'AP', 'DATA_ADMIN', 'DATA_ADMIN']}
        self.assertEqual(roles.roles(c), ['OFFICE', 'DATA_ADMIN'])

    def test_missing_column_means_no_additional_roles(self):
        c = {'app_role': 'MISSIONARY', 'leadership_role': None}
        self.assertEqual(roles.roles(c), ['MISSIONARY'])
        self.assertFalse(roles.is_manager(c))
        self.assertFalse(roles.can_edit_calendar(c))
        self.assertFalse(roles.can_publish(c))


class Capabilities(unittest.TestCase):
    def person(self, app_role='MISSIONARY', leader=None, *additional):
        return {'app_role': app_role, 'leadership_role': leader, 'additional_roles': list(additional)}

    def test_dl_who_is_also_data_analyst_has_manager_rights_but_keeps_the_dl_label(self):
        c = self.person('MISSIONARY', 'DL', 'DATA_ADMIN')
        self.assertEqual(roles.capabilities(c), {'manager': True, 'calendar': True, 'publish': True, 'dashboards': True,
                                                 'management': True, 'callins': True, 'presentations': True,
                                                 'glimpse': True, 'archetypes': True, 'wiki_edit': True})
        self.assertTrue(roles.shows_glimpse(c))
        self.assertEqual(roles.planning_scope(c), 'mission')
        self.assertEqual(roles.target_scope(c), 'mission')

    def test_office_gives_calendar_editing_and_mission_announcement_publishing(self):
        c = self.person('MISSIONARY', None, 'OFFICE')
        self.assertEqual(roles.capabilities(c), {'manager': False, 'calendar': True, 'publish': True, 'dashboards': False,
                                                 'management': False, 'callins': False, 'presentations': False,
                                                 'glimpse': False, 'archetypes': False, 'wiki_edit': False})
        self.assertEqual(roles.target_scope(c, 'calendar'), 'mission')
        self.assertEqual(roles.target_scope(c, 'announcements'), 'mission')
        self.assertEqual(roles.target_scope(c, 'presentations'), 'area')
        self.assertIsNone(roles.planning_scope(c))
        self.assertFalse(roles.shows_glimpse(c))

    def test_office_widens_announcements_but_not_other_stewardship(self):
        c = self.person('MISSIONARY', 'DL', 'OFFICE')
        self.assertEqual(roles.target_scope(c, 'calendar'), 'mission')
        self.assertEqual(roles.target_scope(c, 'announcements'), 'mission')
        self.assertEqual(roles.target_scope(self.person('MISSIONARY', 'ZL', 'OFFICE')), 'mission')
        self.assertEqual(roles.target_scope(c, 'presentations'), 'district')
        self.assertEqual(roles.planning_scope(c), 'district')

    def test_stl_has_no_part_in_callins_or_plan_unlocking(self):
        c = self.person('STL', 'STL')
        self.assertFalse(roles.can_use_callins(c))
        self.assertFalse(roles.can_unlock_plans(c))
        self.assertTrue(roles.can_use_presentations(c))
        self.assertTrue(roles.can_publish(c))
        self.assertEqual(roles.target_scope(c), 'zone')
        self.assertIsNone(roles.planning_scope(c))

    def test_presentations_for_managers_zls_and_stls_only(self):
        # Round 7 (zone presentations): ZLs and STLs make their own zone's decks; DLs only open shared decks;
        # missionaries have none.
        zl = {'app_role': 'MISSIONARY', 'leadership_role': 'ZL', 'leadership_zone_id': 7}
        stl = {'app_role': 'MISSIONARY', 'leadership_role': 'STL', 'leadership_zone_id': 7}
        for c in (zl, stl):
            self.assertTrue(roles.can_use_presentations(c))
            self.assertTrue(roles.capabilities(c)['presentations'])
            self.assertEqual(roles.presentation_zone(c), 7)
        # A DL opens the decks shared with them (since round 2) but makes none.
        dl = self.person('MISSIONARY', 'DL')
        self.assertTrue(roles.can_use_presentations(dl))
        self.assertTrue(roles.capabilities(dl)['presentations'])
        self.assertIsNone(roles.presentation_zone(dl))
        for c in (self.person(), self.person('OFFICE'), self.person('AP')):
            self.assertFalse(roles.can_use_presentations(c))
            self.assertFalse(roles.capabilities(c)['presentations'])
            self.assertIsNone(roles.presentation_zone(c))
        # Managers use every deck and own none; a ZL who is also a Data Analyst is a manager here.
        for c in (self.person('MISSIONARY', 'AP'), self.person('PRESIDENT'), self.person('DATA_ADMIN'),
                  dict(zl, additional_roles=['DATA_ADMIN'])):
            self.assertTrue(roles.capabilities(c)['presentations'])
            self.assertIsNone(roles.presentation_zone(c))

    def test_leaders_and_managers(self):
        self.assertTrue(roles.can_use_callins(self.person('MISSIONARY', 'DL')))
        self.assertTrue(roles.can_use_callins(self.person('MISSIONARY', 'ZL')))
        self.assertFalse(roles.can_use_callins(self.person()))
        self.assertTrue(roles.capabilities(self.person('MISSIONARY', 'AP'))['dashboards'])
        self.assertTrue(roles.capabilities(self.person('PRESIDENT'))['dashboards'])
        self.assertTrue(roles.capabilities(self.person('DATA_ADMIN'))['dashboards'])
        self.assertFalse(roles.capabilities(self.person('MISSIONARY', 'ZL'))['dashboards'])
        self.assertTrue(roles.can_manage_accounts(self.person('PRESIDENT')))
        self.assertTrue(roles.can_manage_accounts(self.person('MISSIONARY', 'AP')))
        self.assertFalse(roles.can_manage_accounts(self.person('AP')))  # app_role AP without an AP assignment
        self.assertFalse(roles.can_manage_accounts(self.person('OFFICE')))
        self.assertEqual(roles.describe(self.person('PRESIDENT', None, 'DATA_ADMIN', 'OFFICE')), 'President · Data Analyst · Office')


class Glimpse(unittest.TestCase):
    """Round 6: the managers' Overview starts with the mission glimpse (GET /api/dashboard); nobody else's does."""

    def person(self, app_role='MISSIONARY', leader=None, *additional):
        return {'app_role': app_role, 'leadership_role': leader, 'additional_roles': list(additional)}

    def test_every_manager_gets_the_glimpse(self):
        for c in (self.person('MISSIONARY', 'AP'), self.person('PRESIDENT'), self.person('president'),
                  self.person('PRESIDENT', 'AP'), self.person('DATA_ADMIN'), self.person('MISSIONARY', None, 'DATA_ADMIN'),
                  self.person('MISSIONARY', 'DL', 'DATA_ADMIN'), self.person('MISSIONARY', 'ZL', 'data_admin'),
                  self.person('MISSIONARY', 'STL', 'DATA_ADMIN'), self.person('OFFICE', None, 'DATA_ADMIN'),
                  self.person('PRESIDENT', None, 'DATA_ADMIN', 'OFFICE')):
            self.assertTrue(roles.shows_glimpse(c), c)
            self.assertTrue(roles.capabilities(c)['glimpse'], c)
            self.assertEqual(roles.capabilities(c)['glimpse'], roles.capabilities(c)['dashboards'], c)

    def test_nobody_else_does(self):
        for c in (self.person(), self.person('MISSIONARY', 'DL'), self.person('MISSIONARY', 'ZL'),
                  self.person('MISSIONARY', 'STL'), self.person('OFFICE'), self.person('MISSIONARY', 'DL', 'OFFICE'),
                  self.person('AP'), self.person('DL'), {'app_role': None, 'leadership_role': None}):
            self.assertFalse(roles.shows_glimpse(c), c)
            self.assertFalse(roles.capabilities(c)['glimpse'], c)

    def test_president_or_ap_cannot_be_an_additional_role(self):
        # additional_roles only knows Data Analyst and Office: a stray PRESIDENT or AP there gives nothing.
        for extra in ('PRESIDENT', 'AP'):
            self.assertFalse(roles.shows_glimpse(self.person('MISSIONARY', 'DL', extra)), extra)

    def test_grafana_role_mapping_is_gone(self):
        self.assertFalse(hasattr(roles, 'dashboard_role'))


if __name__ == '__main__':
    unittest.main()
