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
SHARED = ("MANAGER_ROLES", "ADDITIONAL_ROLES", "LEADER_ORDER", "RETIRE_ROLES")


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
        self.assertEqual(set(api["RETIRE_ROLES"]), set(importer["RETIRE_ROLES"]), "who may delete retired places and questions")
        self.assertLessEqual(set(importer["RETIRE_ROLES"]), set(importer["MANAGER_ROLES"]), "only managers may delete")
        # The order of the leadership roles decides which one is the main role: it must be the same.
        self.assertEqual(list(api["LEADER_ORDER"]), list(importer["LEADER_ORDER"]), "the order of the leadership roles")


BEGIN = "# >>> ROLE ABILITIES"
END = "# <<< ROLE ABILITIES <<<"


def abilities_block(path):
    """The shared role-abilities block of a roles.py, as text (line endings made equal)."""
    text = path.read_text(encoding="utf-8-sig")
    return text[text.index(BEGIN):text.index(END) + len(END)]


class SharedAbilityBlock(unittest.TestCase):
    """Round 13, task 21: both images read the role-abilities table with the same code and the same built-in matrix."""

    def test_the_block_is_identical_in_both_files(self):
        api = abilities_block(REPO / "portal-api" / "roles.py")
        importer = abilities_block(REPO / "roster-importer" / "roles.py")
        self.assertEqual(api, importer, "the role-abilities block of portal-api/roles.py and roster-importer/roles.py differ")
        self.assertEqual(api.count(BEGIN), 1)

    def test_both_blocks_give_the_same_built_in_matrix_and_the_same_rules(self):
        answers = []
        for name in ("portal-api", "roster-importer"):
            namespace = {"MANAGER_ROLES": constants(REPO / name / "roles.py")["MANAGER_ROLES"]}
            exec(compile(abilities_block(REPO / name / "roles.py"), name, "exec"), namespace)
            self.assertEqual(len(namespace["DEFAULT_ABILITIES"]), 40)
            answers.append({key: namespace[key] for key in ("ABILITY_ROLES", "ABILITIES", "DEFAULT_ROLES", "SWITCHABLE", "DEFAULT_ABILITIES")})
            every = [(r, a, v) for r in namespace["ABILITY_ROLES"] for a in namespace["ABILITIES"] for v in (True, False)]
            answers[-1]["valid"] = [namespace["cell_is_valid"](r, a, v) for r, a, v in every]
        self.assertEqual(answers[0], answers[1])

    def test_roles_py_of_the_importer_still_has_no_database_code_of_its_own_in_the_block(self):
        block = abilities_block(REPO / "roster-importer" / "roles.py")
        for word in ("psycopg2", "import flask", "database.", "session"):
            self.assertNotIn(word, block)


if __name__ == "__main__":
    unittest.main()
