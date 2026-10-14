"""An AP may delete retired places and questions, like the President and a Data Analyst (owner's answer 8, 13 Oct 2026: "APs may
delete places/questions as well; they can do everything, like the others"). No database.

Checked here: both roles.py files (portal-api and roster-importer, kept equal by tests.test_roles_in_step) list AP in RETIRE_ROLES;
the three managers have the same right and nobody else has it; DA Management lets an AP signed in through the portal into
Delete retired and past the permission check of the delete itself, and still refuses Office, a DL, a ZL and the old shared password.
Run from roster-importer/:  python -m unittest tests.test_ap_rights
"""
import importlib.util
import os
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "postgresql://nobody@127.0.0.1:1/none")  # never opened by these tests
import app  # noqa: E402
import retire  # noqa: E402
import retire_pages  # noqa: E402
import roles  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
MANAGERS = {"AP", "PRESIDENT", "DATA_ADMIN"}


def api_roles():
    """portal-api/roles.py loaded by its path (it has no imports, so it loads anywhere)."""
    spec = importlib.util.spec_from_file_location("portal_api_roles", ROOT / "portal-api" / "roles.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ListTests(unittest.TestCase):
    def test_ap_is_in_the_delete_list_of_both_images_and_the_list_is_the_managers(self):
        api = api_roles()
        self.assertIn("AP", roles.RETIRE_ROLES)
        self.assertIn("AP", api.RETIRE_ROLES)
        self.assertEqual(set(roles.RETIRE_ROLES), MANAGERS)
        self.assertEqual(set(api.RETIRE_ROLES), MANAGERS)
        self.assertEqual(set(roles.RETIRE_ROLES), set(roles.MANAGER_ROLES))

    def test_the_portal_api_answer_for_every_kind_of_person(self):
        api = api_roles()
        cases = {
            "an AP by assignment": ({"leadership_role": "AP"}, True),
            "an AP whose saved main role says AP": ({"app_role": "AP", "leadership_role": "AP"}, True),
            "the President": ({"app_role": "PRESIDENT"}, True),
            "a Data Analyst as the main role": ({"app_role": "DATA_ADMIN"}, True),
            "a Data Analyst as an additional role": ({"app_role": "MISSIONARY", "additional_roles": ["DATA_ADMIN"]}, True),
            "an AP who is also Office": ({"leadership_role": "AP", "additional_roles": ["OFFICE"]}, True),
            "Office": ({"app_role": "OFFICE"}, False),
            "a zone leader": ({"leadership_role": "ZL"}, False),
            "a district leader": ({"leadership_role": "DL"}, False),
            "a sister training leader": ({"leadership_role": "STL"}, False),
            "a missionary": ({"app_role": "MISSIONARY"}, False),
            "nobody": ({}, False),
        }
        for who, (context, expected) in cases.items():
            self.assertEqual(api.can_retire_places(context), expected, who)

    def test_an_ap_is_a_manager_with_the_same_right_everywhere_in_the_portal_api(self):
        api = api_roles()
        context = {"leadership_role": "AP"}
        self.assertTrue(api.is_manager(context))
        self.assertTrue(api.can_retire_places(context))


class DaManagementTests(unittest.TestCase):
    def signed_in_as(self, role):
        client = app.app.test_client()
        with client.session_transaction() as data:
            data.update(authenticated=True, csrf_token="t")
            if role:
                data["portal_role"] = role
        return client

    def test_the_management_role_of_an_ap_is_ap_only_while_the_assignment_is_in_force(self):
        self.assertEqual(roles.management_role("MISSIONARY", "AP"), "AP")
        self.assertIsNone(roles.management_role("AP", None))  # a saved role alone gives nothing

    def test_an_ap_signed_in_through_the_portal_may_delete(self):
        with app.app.test_request_context("/"):
            from flask import session
            session["portal_role"] = "AP"
            self.assertTrue(roles.may_retire())

    def test_the_delete_page_opens_for_an_ap_and_the_other_managers_but_not_for_the_rest(self):
        class Ctx:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        for role, status in (("AP", 200), ("PRESIDENT", 200), ("DATA_ADMIN", 200), ("OFFICE", 403), ("DL", 403), ("ZL", 403), (None, 403)):
            client = self.signed_in_as(role)
            with patch.object(retire_pages.sign_in, "allowed", return_value=True), \
                    patch.object(retire_pages.sign_in, "current_mission_id", return_value=2), \
                    patch.object(retire_pages.database, "connect", return_value=Ctx()), \
                    patch.object(retire_pages.database, "cursor", return_value=Ctx()), \
                    patch.object(retire, "closed_places", return_value=[]), patch.object(retire, "retired_questions", return_value=[]):
                self.assertEqual(client.get("/retire").status_code, status, role)

    def test_the_delete_itself_passes_its_permission_check_for_an_ap_and_stops_at_the_database(self):
        """The permission check comes first: for an AP the code goes on and reaches the database (stood in for by an error that
        is only raised there); for everyone else it stops with PermissionError before touching anything."""
        class ReachedTheDatabase(Exception):
            pass

        def database_unreachable():
            raise ReachedTheDatabase()

        for role, reaches in (("AP", True), ("PRESIDENT", True), ("DATA_ADMIN", True), ("OFFICE", False), ("DL", False), (None, False)):
            with app.app.test_request_context("/"):
                from flask import session
                if role:
                    session["portal_role"] = role
                    session["portal_user"], session["portal_user_id"] = "Test Person", "00000000-0000-0000-0000-000000000001"
                with patch.object(retire.database, "connect", side_effect=database_unreachable):
                    for run in (lambda: retire.run_place_delete("area", 1, None, "x"), lambda: retire.run_question_delete("some_key", None, False, "some_key")):
                        if reaches:
                            try:
                                run()
                            except ReachedTheDatabase:
                                pass
                            except retire.Refusal:
                                pass  # a rule of the page said no: it got past the permission check
                        else:
                            with self.assertRaises(PermissionError, msg=role):
                                run()


if __name__ == "__main__":
    unittest.main()
