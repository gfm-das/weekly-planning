"""No DA Management text names the removed tools, without a database.

Appsmith (the old "Beta" pages) was removed on 29 Sep 2026; Grafana and Superset before it. People now plan in the
portal's Weekly Planning, and read the numbers in Call-ins, Dashboards (DataEase), Presentations and Archetypal
Health. So no text that DA Management can show may name Beta, Appsmith, Grafana or Superset.

How it checks: it reads every DA Management program file (roster-importer/*.py) and looks at each piece of text in
it, the way Python itself reads the file. Comments and the explanations at the top of a file or function (docstrings)
are skipped: people never see those. The database's name "gfm-beta-supabase-db-1" is fine: it is written in small
letters and is not a page text.

Run (from roster-importer/, any Python 3.10 or newer; the second test needs Flask and psycopg2, so use DA
Management's image):
  docker run --rm --network none -v <worktree>:/repo -w /repo/roster-importer \
    -e DATABASE_URL=postgresql://nobody@127.0.0.1:1/none roster-importer-roster-importer \
    python -m unittest tests.test_page_words -v
"""
import ast
import os
import re
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]  # roster-importer/
# "Beta" with a capital B as its own word, and the three tool names in any spelling.
OLD_NAMES = re.compile(r"\bBeta\b|(?i:\bappsmith\b|\bgrafana\b|\bsuperset\b)")


def docstrings(tree):
    """The docstring nodes of a file: the first text of the file, of each class and of each function."""
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                found.add(id(first.value))
    return found


def texts_with_old_names(path):
    """(line, text) for every text in the file that names a removed tool (docstrings and comments left out)."""
    tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))  # utf-8-sig: a file may start with a BOM
    skip = docstrings(tree)
    return [(node.lineno, node.value) for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in skip
            and OLD_NAMES.search(node.value)]


class PageWordsTests(unittest.TestCase):
    def test_no_program_text_names_a_removed_tool(self):
        files = sorted(HERE.glob("*.py"))
        self.assertIn("planning_questions.py", [f.name for f in files])
        found = {f.name: texts_with_old_names(f) for f in files}
        self.assertEqual({name: hits for name, hits in found.items() if hits}, {})

    def test_the_check_itself_notices_an_old_name(self):
        # So a broken check cannot pass by finding nothing.
        self.assertTrue(OLD_NAMES.search("in the portal and in Beta"))
        self.assertTrue(OLD_NAMES.search("Appsmith"))
        self.assertFalse(OLD_NAMES.search("gfm-beta-supabase-db-1"))
        self.assertFalse(OLD_NAMES.search("Alphabet, better"))

    def test_every_locked_question_says_who_reads_it(self):
        os.environ.setdefault("DATABASE_URL", "postgresql://nobody@127.0.0.1:1/none")  # never opened here
        import planning_questions as pq
        # The locked keys of migration 024 (the live list on 29 Sep 2026), without the two Facebook keys that
        # migration 038 unlocked and retired (social media archived).
        locked = sorted(pq.KEY_INDICATOR_KEYS | {
            "nm_sacrament_attendance_plan", "baptisms_confirmations_plan", "baptismal_dates_plan",
            "sacrament_attendance_plan", "members_at_lessons_plan", "friends_found_plan", "weekly_action_plan",
            "information_up_chain", "ward_coordination_held", "ward_coordination_attendance", "long_term_service",
            "member_meals_active_actual", "member_meals_less_active_actual",
            "member_meals_part_member_actual", "member_meals_goal", "member_visits_active_actual",
            "member_visits_less_active_actual", "member_visits_part_member_actual", "member_visits_goal"})
        self.assertEqual(len(locked), 31)
        for key in locked:
            reason = pq.protected_reason(key)
            self.assertTrue(reason, key)
            self.assertIsNone(OLD_NAMES.search(reason), key)
        for text in (pq.EXPLAIN, pq.LOCKED_NOTE, pq.KEY_SECTION_STAYS):
            self.assertIsNone(OLD_NAMES.search(text), text)


if __name__ == "__main__":
    unittest.main()
