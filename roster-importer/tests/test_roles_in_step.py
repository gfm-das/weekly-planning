"""The two roles.py files (portal-api and roster-importer) must agree on the shared lists, without a database.

They are different programs in different Docker images (portal-api decides what a signed-in person may see; DA Management
decides who may use it and who may give which role), so they cannot be one file. They do share a few lists. If one list
is changed in only one of the two files, this test fails.

Run from roster-importer/ (any Python 3.10+, no packages needed):  python -m unittest tests.test_roles_in_step
"""
import ast
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SHARED = ("MANAGER_ROLES", "ADDITIONAL_ROLES", "LEADER_ORDER")


def constants(path):
    """{name: value} of the module-level lists and sets in a roles.py (read, never run)."""
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    found = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
            if name in SHARED:
                code = compile(ast.Expression(node.value), str(path), "eval")
                found[name] = eval(code, {"__builtins__": {}}, {"frozenset": frozenset})
    return found


class SharedRoleLists(unittest.TestCase):
    def test_the_shared_lists_agree(self):
        api = constants(REPO / "portal-api" / "roles.py")
        importer = constants(REPO / "roster-importer" / "roles.py")
        for name in SHARED:
            self.assertIn(name, api, f"portal-api/roles.py has no {name}")
            self.assertIn(name, importer, f"roster-importer/roles.py has no {name}")
        self.assertEqual(set(api["MANAGER_ROLES"]), set(importer["MANAGER_ROLES"]), "who counts as a manager")
        self.assertEqual(set(api["ADDITIONAL_ROLES"]), set(importer["ADDITIONAL_ROLES"]), "the additional roles")
        # The order of the leadership roles decides which one is the main role: it must be the same.
        self.assertEqual(list(api["LEADER_ORDER"]), list(importer["LEADER_ORDER"]), "the order of the leadership roles")


if __name__ == "__main__":
    unittest.main()
