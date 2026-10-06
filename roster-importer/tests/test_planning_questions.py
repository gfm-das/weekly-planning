"""DA Management "Planning questions" page against a THROWAWAY copy of the mission database with migration 024 applied.

Covers the routes and who may use them (view only with the shared password, changes only with a signed-in portal
identity, CSRF), every kind of change the page offers (sections, questions, answer choices, grid rows, show/hide
rules, order), the change history row each change writes in the same transaction, and the database protections
the page relies on (renaming, retiring locked questions, re-typing answered ones, codes used in saved plans,
circular rules). Third version: a retired parent question or section makes Weekly Planning ignore its rules (read
as the signed-in person, as the portal reads them), a choice a rule looks for stays, whole-number questions need whole limits, a locked question keeps its
Required setting both ways, Delete buttons are readable and answers are counted once. Round 3 (test_18): the Preach
My Gospel wording of the page and, when migration 028 is applied, New People Being Taught in labels and history.
Round 8 (test_19): the old "Beta" pages (Appsmith) are gone since 29 Sep, so no page here names Beta or Appsmith
(only the change history may, where it quotes what was written at the time).

It commits rows (new test sections and questions, a few answers on one plan), so it refuses to run unless
DATABASE_URL names a database whose name contains "test" (never the live host) and PLANQ_TEST_THROWAWAY=yes.

Run in a temporary roster-importer container on the test network:
  docker run --rm --network gfm-test-r2-net -v <worktree>/roster-importer:/app -w /app \
    -e DATABASE_URL=postgresql://postgres:<password>@gfm-test-r2-db:5432/gfm_test_planq_2 -e PLANQ_TEST_THROWAWAY=yes \
    roster-importer-roster-importer python -m unittest tests/test_planning_questions.py -v
"""
import os
import re
import time
import unittest
import uuid
from urllib.parse import urlsplit
from unittest.mock import patch

import psycopg2

parts = urlsplit(os.environ.get("DATABASE_URL", ""))
if (os.environ.get("PLANQ_TEST_THROWAWAY") != "yes" or "test" not in parts.path
        or parts.hostname == "gfm-beta-supabase-db-1"):
    raise RuntimeError("A throwaway *test* database (not the live host) and PLANQ_TEST_THROWAWAY=yes are required.")

import app  # noqa: E402
import database  # noqa: E402
import planning_questions as pq  # noqa: E402
import settings  # noqa: E402
import sign_in  # noqa: E402

EDITOR_ID = str(uuid.uuid4())
RUN = uuid.uuid4().hex[:6]


class PlanningQuestionsPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app.app.config["TESTING"] = True
        cls.context = patch.object(sign_in, "current_management_context",
                                   return_value={"user_id": EDITOR_ID, "mission_id": 2, "management_role": "DATA_ADMIN"})
        cls.context.start()
        cls.report_id = cls.scalar("select id from public.weekly_area_reports order by id limit 1")

    @classmethod
    def tearDownClass(cls):
        cls.context.stop()

    def setUp(self):
        self.client = app.app.test_client()
        with self.client.session_transaction() as s:
            s.update(authenticated=True, portal_role="DATA_ADMIN", portal_user="Test Analyst", portal_user_id=EDITOR_ID,
                     portal_mission_id=2, portal_expires_at=time.time() + 1800, csrf_token="test-csrf")

    # -- helpers ---------------------------------------------------------------------------------------------
    @staticmethod
    def scalar(query, params=()):
        with database.connect() as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                row = cur.fetchone()
                return row[0] if row else None

    @staticmethod
    def execute(query, params=()):
        with database.connect() as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)

    def post(self, path, data, client=None):
        return (client or self.client).post(path, data={"csrf_token": "test-csrf", **data})

    def flashes(self, client=None):
        """The messages flashed since the last call (and forgets them)."""
        with (client or self.client).session_transaction() as s:
            return " ".join(message for _, message in s.pop("_flashes", []))

    def history_count(self):
        return self.scalar("select count(*) from public.planning_catalog_changes")

    def question(self, key):
        with database.connect() as conn:
            with database.cursor(conn) as cur:
                cur.execute("select * from public.planning_questions where question_key=%s", (key,))
                return cur.fetchone()

    def add_section(self, title):
        response = self.post(f"{pq.BASE}/sections/new", {"section_title": title, "description": "Test section"})
        self.assertEqual(response.status_code, 302, self.flashes())
        return self.scalar("select id from public.planning_question_sections where section_title=%s", (title,))

    def add_question(self, section_id, label, kind="NUMBER", key="", required=False):
        response = self.post(f"{pq.BASE}/questions/new", {"section_id": section_id, "question_label": label, "question_type": kind,
                                                          "question_key": key, **({"required": "yes"} if required else {})})
        self.assertEqual(response.status_code, 302)
        return self.question(key) if key else None

    def save_question(self, question, **fields):
        form = {"action": "save", "state": pq.row_state(question), "question_label": question["question_label"],
                "help_text": question["help_text"] or "", "question_type": question["question_type"],
                "section_id": question["section_id"], "placeholder": question["placeholder"] or "",
                "value_when_hidden": question["value_when_hidden"] or "",
                **({"required": "yes"} if question["required"] else {}),
                **({"integer_only": "yes"} if question["integer_only"] else {})}
        form.update(fields)
        form = {k: v for k, v in form.items() if v is not None}
        return self.post(f"{pq.BASE}/questions/{question['id']}", form)

    # -- tests -----------------------------------------------------------------------------------------------
    def test_01_access_view_only_and_csrf(self):
        guest = app.app.test_client()
        for path in [pq.BASE, f"{pq.BASE}/preview", f"{pq.BASE}/history"]:
            self.assertEqual(guest.get(path).status_code, 302, path)
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200, path)
            self.assertIn('href="/planning-questions">Planning questions</a>', response.get_data(as_text=True))
        # The other DA Management pages still work and show the new link next to Account Manager.
        for path in ["/imports", "/docs", "/mappings"]:
            page = self.client.get(path).get_data(as_text=True)
            self.assertIn('<a href="/accounts">Account Manager</a><a href="/planning-questions">Planning questions</a>', page, path)
            self.assertEqual(page.count('href="/planning-questions"'), 1, path)
        # The shared importer password may look, but not change anything (the history needs a name).
        shared = app.app.test_client()
        with shared.session_transaction() as s:
            s.update(authenticated=True, csrf_token="test-csrf")
        with patch.object(settings, "IMPORTER_PASSWORD", "x"):
            page = shared.get(pq.BASE).get_data(as_text=True)
            self.assertIn("View only", page)
            before = self.history_count()
            response = self.post(f"{pq.BASE}/sections/new", {"section_title": f"Shared password {RUN}"}, client=shared)
            self.assertEqual(response.status_code, 302)
            self.assertIn("open DA Management from your signed-in portal account", self.flashes(shared))
            self.assertEqual(self.history_count(), before)
            self.assertIsNone(self.scalar("select id from public.planning_question_sections where section_title=%s", (f"Shared password {RUN}",)))
        # Every form needs the session's CSRF token.
        response = self.client.post(f"{pq.BASE}/sections/new", data={"section_title": "No token"})
        self.assertEqual(response.status_code, 403)

    def test_02_sections_add_rename_order_retire_with_history(self):
        before = self.history_count()
        section_id = self.add_section(f"Test Section {RUN}")
        key = self.scalar("select section_key from public.planning_question_sections where id=%s", (section_id,))
        self.assertEqual(key, f"test_section_{RUN}")
        self.assertEqual(self.history_count(), before + 1)
        self.assertEqual(self.scalar("select actor from public.planning_catalog_changes order by id desc limit 1"), "Test Analyst")
        self.assertEqual(self.scalar("select actor_user_id::text from public.planning_catalog_changes order by id desc limit 1"), EDITOR_ID)
        with database.connect() as conn:
            with database.cursor(conn) as cur:
                cur.execute("select * from public.planning_question_sections where id=%s", (section_id,))
                section = cur.fetchone()
        # A page opened before someone else's change is refused.
        self.post(f"{pq.BASE}/sections/{section_id}", {"action": "save", "state": "old", "section_title": "Renamed"})
        self.assertIn("Someone changed this section", self.flashes())
        self.post(f"{pq.BASE}/sections/{section_id}", {"action": "save", "state": pq.row_state(section),
                                                      "section_title": f"Renamed {RUN}", "description": "New words"})
        self.assertEqual(self.scalar("select section_title from public.planning_question_sections where id=%s", (section_id,)), f"Renamed {RUN}")
        self.assertEqual(self.scalar("select section_key from public.planning_question_sections where id=%s", (section_id,)), key)
        order = self.scalar("select display_order from public.planning_question_sections where id=%s", (section_id,))
        self.post(f"{pq.BASE}/sections/{section_id}", {"action": "up"})
        self.assertLess(self.scalar("select display_order from public.planning_question_sections where id=%s", (section_id,)), order)
        with database.connect() as conn:
            with database.cursor(conn) as cur:
                cur.execute("select * from public.planning_question_sections where id=%s", (section_id,))
                state = pq.row_state(cur.fetchone())
        self.post(f"{pq.BASE}/sections/{section_id}", {"action": "retire", "state": state})
        self.assertFalse(self.scalar("select active from public.planning_question_sections where id=%s", (section_id,)))
        self.assertIn("Section retired", self.flashes())

    def test_03_locked_sections_and_questions_stay(self):
        with database.connect() as conn:
            with database.cursor(conn) as cur:
                cur.execute("select * from public.planning_question_sections where section_key='key_indicators_conversion'")
                kic = cur.fetchone()
        self.post(f"{pq.BASE}/sections/{kic['id']}", {"action": "retire", "state": pq.row_state(kic)})
        message = self.flashes()
        self.assertIn("Nothing was changed", message)
        # Refused by the page in plain words, before the database (whose own message still names Beta).
        self.assertIn(f"“{kic['section_title']}” stays on the form. It holds the key indicators", message)
        self.assertNotIn("Beta", message)
        self.assertTrue(self.scalar("select active from public.planning_question_sections where id=%s", (kic["id"],)))
        locked = self.question("friends_found_actual")
        page = self.client.get(f"{pq.BASE}/questions/{locked['id']}").get_data(as_text=True)
        self.assertIn("Locked.", page)
        self.assertIn("A key indicator: Dashboards, Call-ins and Presentations read it.", page)
        self.post(f"{pq.BASE}/questions/{locked['id']}", {"action": "retire", "state": pq.row_state(locked)})
        self.assertIn("protected because reports read it", self.flashes())
        self.assertTrue(self.question("friends_found_actual")["active"])
        response = self.save_question(locked, question_type="TEXT")
        self.assertIn("Nothing was changed", self.flashes())
        self.assertEqual(self.question("friends_found_actual")["question_type"], "NUMBER")
        self.save_question(self.question("friends_found_actual"), required=None)
        self.assertTrue(self.question("friends_found_actual")["required"])  # the page keeps it required
        # Its wording can change (and is put back).
        label = locked["question_label"]
        self.save_question(self.question("friends_found_actual"), question_label=f"{label} (test)")
        self.assertEqual(self.question("friends_found_actual")["question_label"], f"{label} (test)")
        self.save_question(self.question("friends_found_actual"), question_label=label)
        self.assertEqual(response.status_code, 302)

    def test_04_questions_add_edit_type_limits_and_history(self):
        section_id = self.add_section(f"Questions {RUN}")
        self.post(f"{pq.BASE}/questions/new", {"section_id": section_id, "question_label": "Bad key", "question_type": "NUMBER",
                                              "question_key": "Bad-Key"})
        self.assertIn("A key starts with a small letter", self.flashes())
        self.post(f"{pq.BASE}/questions/new", {"section_id": section_id, "question_label": "Taken", "question_type": "NUMBER",
                                              "question_key": "friends_found_goal"})
        self.assertIn("already used", self.flashes())
        self.add_question(section_id, f"Service Projects {RUN} — Goal", "NUMBER")
        q = self.question(f"service_projects_{RUN}_goal")
        self.assertIsNotNone(q)
        self.assertIn("appear in Call-ins automatically", self.flashes())
        before = self.history_count()
        self.save_question(q, question_label="Service projects next week", help_text="Count each project once.",
                           min_value="1", max_value="0")
        self.assertIn("lowest number must not be above", self.flashes())
        self.save_question(self.question(q["question_key"]), question_label="Service projects next week",
                           help_text="Count each project once.", min_value="1", max_value="20", integer_only=None,
                           placeholder="e.g. 2", value_when_hidden="1,5")
        saved = self.question(q["question_key"])
        self.assertEqual((saved["question_label"], float(saved["min_value"]), float(saved["max_value"]), saved["integer_only"],
                          saved["placeholder"], saved["value_when_hidden"]),
                         ("Service projects next week", 1.0, 20.0, False, "e.g. 2", "1.5"))
        self.assertEqual(self.history_count(), before + 1)
        # Type changes while nobody answered it, not after.
        self.save_question(self.question(q["question_key"]), question_type="TEXT")
        self.assertEqual(self.question(q["question_key"])["question_type"], "TEXT")
        self.execute("""insert into public.weekly_planning_answers(weekly_area_report_id,question_key,answer_text)
                        values(%s,%s,'test') on conflict do nothing""", (self.report_id, q["question_key"]))
        try:
            page = self.client.get(f"{pq.BASE}/questions/{q['id']}").get_data(as_text=True)
            self.assertIn("Saved plans already answered it", page)
            self.save_question(self.question(q["question_key"]), question_type="NUMBER")
            self.assertIn("so its type stays", self.flashes())
            self.assertEqual(self.question(q["question_key"])["question_type"], "TEXT")
        finally:
            self.execute("delete from public.weekly_planning_answers where weekly_area_report_id=%s and question_key=%s",
                         (self.report_id, q["question_key"]))
        # Stale page.
        self.post(f"{pq.BASE}/questions/{q['id']}", {"action": "save", "state": "old", "question_label": "x", "question_type": "TEXT"})
        self.assertIn("Someone changed this question", self.flashes())
        # Retire and restore; the key never changes.
        self.post(f"{pq.BASE}/questions/{q['id']}", {"action": "retire", "state": pq.row_state(self.question(q["question_key"]))})
        self.assertFalse(self.question(q["question_key"])["active"])
        self.post(f"{pq.BASE}/questions/{q['id']}", {"action": "restore", "state": pq.row_state(self.question(q["question_key"]))})
        self.assertTrue(self.question(q["question_key"])["active"])

    def test_05_choices_and_grid_rows(self):
        section_id = self.add_section(f"Choices {RUN}")
        self.add_question(section_id, "Who taught?", "SELECT", key=f"who_taught_{RUN}")
        q = self.question(f"who_taught_{RUN}")
        base = f"{pq.BASE}/questions/{q['id']}/choices"
        self.post(base, {"kind": "option", "action": "add", "label": "Both of us"})
        self.post(base, {"kind": "option", "action": "add", "label": "A member", "value": "member"})
        self.post(base, {"kind": "option", "action": "add", "label": "Duplicate", "value": "member"})
        self.assertIn("already has a choice with the code member", self.flashes())
        with database.connect() as conn:
            with database.cursor(conn) as cur:
                cur.execute("select * from public.planning_question_options where question_id=%s order by display_order", (q["id"],))
                options = cur.fetchall()
        self.assertEqual([o["option_value"] for o in options], ["both_of_us", "member"])
        both, member = options
        # Unused: the code can change; used in a saved plan: it cannot, and the choice cannot be deleted.
        self.post(base, {"kind": "option", "action": "save", "item_id": both["id"], "state": pq.row_state(both), "label": "Both", "value": "both"})
        self.assertEqual(self.scalar("select option_value from public.planning_question_options where id=%s", (both["id"],)), "both")
        self.execute("insert into public.weekly_planning_answers(weekly_area_report_id,question_key,answer_text) values(%s,%s,'member')",
                     (self.report_id, q["question_key"]))
        try:
            member_state = pq.row_state(member)
            self.post(base, {"kind": "option", "action": "save", "item_id": member["id"], "state": member_state, "label": "A member", "value": "friend"})
            self.assertIn("its value stays", self.flashes())
            self.post(base, {"kind": "option", "action": "delete", "item_id": member["id"], "state": member_state})
            self.assertIn("cannot be deleted", self.flashes())
            self.post(base, {"kind": "option", "action": "retire", "item_id": member["id"], "state": member_state})
            self.assertFalse(self.scalar("select active from public.planning_question_options where id=%s", (member["id"],)))
        finally:
            self.execute("delete from public.weekly_planning_answers where weekly_area_report_id=%s and question_key=%s",
                         (self.report_id, q["question_key"]))
        with database.connect() as conn:
            with database.cursor(conn) as cur:
                cur.execute("select * from public.planning_question_options where id=%s", (both["id"],))
                both_state = pq.row_state(cur.fetchone())
        self.post(base, {"kind": "option", "action": "delete", "item_id": both["id"], "state": both_state})
        self.assertIsNone(self.scalar("select id from public.planning_question_options where id=%s", (both["id"],)))
        self.assertEqual(self.scalar("""select note from public.planning_catalog_changes where table_name='planning_question_options'
                                        order by id desc limit 1"""), "Choice deleted")
        # A grid: rows and choices.
        self.add_question(section_id, "Who came?", "GRID", key=f"who_came_{RUN}")
        grid = self.question(f"who_came_{RUN}")
        base = f"{pq.BASE}/questions/{grid['id']}/choices"
        for label in ("Yes", "No"):
            self.post(base, {"kind": "option", "action": "add", "label": label})
        for label in ("Bishop", "Ward mission leader"):
            self.post(base, {"kind": "row", "action": "add", "label": label})
        self.assertEqual(self.scalar("select string_agg(row_key, ',' order by display_order) from public.planning_question_grid_rows where question_id=%s",
                                     (grid["id"],)), "bishop,ward_mission_leader")
        row_id = self.scalar("select id from public.planning_question_grid_rows where question_id=%s and row_key='ward_mission_leader'", (grid["id"],))
        self.post(base, {"kind": "row", "action": "up", "item_id": row_id})
        self.assertEqual(self.scalar("select string_agg(row_key, ',' order by display_order) from public.planning_question_grid_rows where question_id=%s",
                                     (grid["id"],)), "ward_mission_leader,bishop")
        page = self.client.get(f"{pq.BASE}/preview").get_data(as_text=True)
        self.assertIn("Ward mission leader", page)
        # The locked ward coordination grid keeps its codes and rows.
        locked = self.question("ward_coordination_attendance")
        with database.connect() as conn:
            with database.cursor(conn) as cur:
                cur.execute("select * from public.planning_question_grid_rows where question_id=%s order by id limit 1", (locked["id"],))
                row = cur.fetchone()
        self.post(f"{pq.BASE}/questions/{locked['id']}/choices", {"kind": "row", "action": "retire", "item_id": row["id"], "state": pq.row_state(row)})
        self.assertIn("fixed because reports read them", self.flashes())
        self.assertTrue(self.scalar("select active from public.planning_question_grid_rows where id=%s", (row["id"],)))

    def test_06_show_hide_rules(self):
        section_id = self.add_section(f"Rules {RUN}")
        for label, kind in (("Rule parent", "NUMBER"), ("Rule child", "NUMBER"), ("Rule yes no", "BOOLEAN")):
            self.add_question(section_id, label, kind, key=f"{label.lower().replace(' ', '_')}_{RUN}")
        parent, child, yes_no = (self.question(f"{name}_{RUN}") for name in ("rule_parent", "rule_child", "rule_yes_no"))
        rules = lambda q: f"{pq.BASE}/questions/{q['id']}/rules"
        self.post(rules(child), {"action": "add", "parent": parent["question_key"], "operator": "greater_than", "value": "0"})
        self.assertIn("Rule added", self.flashes())
        self.post(rules(child), {"action": "add", "parent": child["question_key"], "operator": "greater_than", "value": "0"})
        self.assertIn("cannot depend on itself", self.flashes())
        self.post(rules(parent), {"action": "add", "parent": child["question_key"], "operator": "greater_than", "value": "1"})
        self.assertIn("depend on itself", self.flashes())  # a circle: child -> parent -> child
        self.post(rules(child), {"action": "add", "parent": parent["question_key"], "operator": "less_than", "value": "9"})
        self.assertIn("already has a rule for that question", self.flashes())
        self.post(rules(child), {"action": "add", "parent": yes_no["question_key"], "operator": "greater_than", "value": "Yes"})
        self.assertIn("only use", self.flashes())
        self.post(rules(child), {"action": "add", "parent": yes_no["question_key"], "operator": "equals", "value": "Yes"})
        self.assertEqual(self.scalar("select comparison_value from public.planning_question_visibility_rules where child_question_key=%s and parent_question_key=%s",
                                     (child["question_key"], yes_no["question_key"])), "true")
        page = self.client.get(f"{pq.BASE}/questions/{child['id']}").get_data(as_text=True)
        self.assertIn("Shown only when", page)
        rule_id = self.scalar("select id from public.planning_question_visibility_rules where child_question_key=%s and parent_question_key=%s",
                              (child["question_key"], yes_no["question_key"]))
        self.post(rules(child), {"action": "off", "rule_id": rule_id})
        self.assertFalse(self.scalar("select active from public.planning_question_visibility_rules where id=%s", (rule_id,)))
        self.post(rules(child), {"action": "delete", "rule_id": rule_id})
        self.assertIsNone(self.scalar("select id from public.planning_question_visibility_rules where id=%s", (rule_id,)))
        # Retiring a parent is allowed; the page says which rule is then ignored.
        self.post(f"{pq.BASE}/questions/{parent['id']}", {"action": "retire", "state": pq.row_state(self.question(parent["question_key"]))})
        self.assertIn("depends on it", self.flashes())

    def test_07_history_and_version(self):
        version = self.scalar("select version from public.planning_catalog_version")
        self.add_section(f"History {RUN}")
        self.assertGreater(self.scalar("select version from public.planning_catalog_version"), version)
        page = self.client.get(f"{pq.BASE}/history").get_data(as_text=True)
        self.assertIn("Test Analyst", page)
        self.assertIn(f"History {RUN}", page)
        self.assertIn("Migration 024", page)
        # Nothing on the page was written without its history row: every audited table row names a person.
        self.assertEqual(self.scalar("select count(*) from public.planning_catalog_changes where actor=''"), 0)

    def test_09_value_saved_while_hidden_must_fit_the_question(self):
        section_id = self.add_section(f"Hidden values {RUN}")
        key = f"hidden_count_{RUN}"
        self.add_question(section_id, "Hidden count", "NUMBER", key=key)
        # Refused like a missionary's answer would be (review: -1, 1.5, NaN and Infinity were stored).
        for value, message in (("-1", "must be 0 or more"), ("1.5", "whole number"), ("NaN", "must be a number"),
                               ("Infinity", "must be a number"), ("abc", "must be a number")):
            self.save_question(self.question(key), value_when_hidden=value)
            self.assertIn(message, self.flashes(), value)
            self.assertIsNone(self.question(key)["value_when_hidden"], value)
        self.save_question(self.question(key), min_value="1", value_when_hidden="0")
        self.assertIn("must be 1 or more", self.flashes())
        self.save_question(self.question(key), value_when_hidden="0,0")
        self.assertEqual(self.question(key)["value_when_hidden"], "0")
        # Limits changed later must still fit it (the same form saves both).
        self.save_question(self.question(key), min_value="2")
        self.assertIn("must be 2 or more", self.flashes())
        self.assertIsNone(self.question(key)["min_value"])
        self.save_question(self.question(key), integer_only=None, max_value="10", value_when_hidden="0.5")
        self.assertEqual(self.question(key)["value_when_hidden"], "0.5")
        self.save_question(self.question(key), integer_only="yes")
        self.assertIn("whole number", self.flashes())
        self.assertFalse(self.question(key)["integer_only"])
        # A drop-down: one of its choices (label or code), stored as the code. That choice then stays until the
        # value saved while hidden changes.
        choice_key = f"hidden_choice_{RUN}"
        self.add_question(section_id, "Hidden choice", "SELECT", key=choice_key)
        q = self.question(choice_key)
        self.save_question(q, value_when_hidden="None")
        self.assertIn("Add the answer choices first", self.flashes())
        base = f"{pq.BASE}/questions/{q['id']}/choices"
        self.post(base, {"kind": "option", "action": "add", "label": "None", "value": "none"})
        self.post(base, {"kind": "option", "action": "add", "label": "Some"})
        self.save_question(self.question(choice_key), value_when_hidden="Nothing")
        self.assertIn("must be one of the answer choices: None, Some", self.flashes())
        self.save_question(self.question(choice_key), value_when_hidden="None")
        self.assertEqual(self.question(choice_key)["value_when_hidden"], "none")
        with database.connect() as conn:
            with database.cursor(conn) as cur:
                cur.execute("select * from public.planning_question_options where question_id=%s and option_value='none'", (q["id"],))
                none = cur.fetchone()
        for action, extra in (("retire", {}), ("delete", {}), ("save", {"label": "None", "value": "nothing"})):
            self.post(base, {"kind": "option", "action": action, "item_id": none["id"], "state": pq.row_state(none), **extra})
            self.assertIn("is the value saved while", self.flashes(), action)
        self.assertTrue(self.scalar("select active from public.planning_question_options where id=%s and option_value='none'", (none["id"],)))
        self.post(base, {"kind": "option", "action": "save", "item_id": none["id"], "state": pq.row_state(none), "label": "No one", "value": "none"})
        self.assertEqual(self.scalar("select option_label from public.planning_question_options where id=%s", (none["id"],)), "No one")
        # A date: written as YYYY-MM-DD. Yes/No: stored as true/false. Grids and tick boxes: none.
        date_key = f"hidden_date_{RUN}"
        self.add_question(section_id, "Hidden date", "DATE", key=date_key)
        self.save_question(self.question(date_key), value_when_hidden="none")
        self.assertIn("a date written like 2026-10-04", self.flashes())
        self.save_question(self.question(date_key), value_when_hidden="2026-10-04")
        self.assertEqual(self.question(date_key)["value_when_hidden"], "2026-10-04")
        self.save_question(self.question(date_key), question_type="BOOLEAN", value_when_hidden="No")
        self.assertEqual((self.question(date_key)["question_type"], self.question(date_key)["value_when_hidden"]), ("BOOLEAN", "false"))
        self.save_question(self.question(date_key), question_type="CHECKBOX")
        self.assertIn("cannot have a value saved while hidden", self.flashes())

    def test_10_locked_questions_keep_their_choices_rows_and_rules(self):
        locked = self.question("ward_coordination_attendance")
        kpi = self.question("friends_found_goal")
        page = self.client.get(f"{pq.BASE}/questions/{locked['id']}").get_data(as_text=True)
        for gone in ("Add row</button>", "Add choice</button>", "Add rule</button>", 'name="value_when_hidden"', 'value="off"'):
            self.assertNotIn(gone, page)
        self.assertIn("no row can be added", page)
        self.assertIn("its show/hide rules are fixed", page)
        counts = lambda: (self.scalar("select count(*) from public.planning_question_grid_rows where question_id=%s", (locked["id"],)),
                          self.scalar("select count(*) from public.planning_question_options where question_id=%s", (locked["id"],)),
                          self.scalar("select count(*) from public.planning_question_visibility_rules"),
                          self.history_count())
        before = counts()
        self.post(f"{pq.BASE}/questions/{locked['id']}/choices", {"kind": "row", "action": "add", "label": "Bishop"})
        self.assertIn("is locked: no row can be added", self.flashes())
        self.post(f"{pq.BASE}/questions/{locked['id']}/choices", {"kind": "option", "action": "add", "label": "Maybe"})
        self.assertIn("is locked: no choice can be added", self.flashes())
        # No rule can hide a locked question (a Key Indicator goal would then be neither asked nor required) ...
        self.post(f"{pq.BASE}/questions/{kpi['id']}/rules", {"action": "add", "parent": "ward_coordination_held", "operator": "equals", "value": "Yes"})
        self.assertIn("its show/hide rules are fixed", self.flashes())
        # ... and the ward coordination grid keeps its rule "shown when the meeting was held".
        rule_id = self.scalar("select id from public.planning_question_visibility_rules where child_question_key='ward_coordination_attendance'")
        for action in ("off", "delete"):
            self.post(f"{pq.BASE}/questions/{locked['id']}/rules", {"action": action, "rule_id": rule_id})
            self.assertIn("its show/hide rules are fixed", self.flashes(), action)
        self.assertTrue(self.scalar("select active from public.planning_question_visibility_rules where id=%s", (rule_id,)))
        self.save_question(kpi, value_when_hidden="0")
        self.assertIn("Locked questions are never hidden", self.flashes())
        self.assertIsNone(self.question("friends_found_goal")["value_when_hidden"])
        self.assertEqual(counts(), before)
        # The database refuses the same without the page (e.g. Supabase Studio).
        with self.assertRaisesRegex(Exception, "no row can be added"):
            self.execute("insert into public.planning_question_grid_rows(question_id,row_key,row_label) values(%s,'bishop','Bishop')", (locked["id"],))

    def test_11_rule_values_must_be_real_numbers(self):
        section_id = self.add_section(f"Rule numbers {RUN}")
        for label in ("Number parent", "Number child"):
            self.add_question(section_id, label, "NUMBER", key=f"{label.lower().replace(' ', '_')}_{RUN}")
        parent, child = self.question(f"number_parent_{RUN}"), self.question(f"number_child_{RUN}")
        for value in ("Infinity", "-Infinity", "NaN", "1e400", "abc"):
            response = self.post(f"{pq.BASE}/questions/{child['id']}/rules",
                                 {"action": "add", "parent": parent["question_key"], "operator": "greater_than", "value": value})
            self.assertEqual(response.status_code, 302, value)  # review: Infinity gave an HTTP 500
            self.assertIn("is a number question: type a number", self.flashes(), value)
        self.assertEqual(self.scalar("select count(*) from public.planning_question_visibility_rules where child_question_key=%s",
                                     (child["question_key"],)), 0)
        self.post(f"{pq.BASE}/questions/{child['id']}/rules", {"action": "add", "parent": parent["question_key"], "operator": "greater_than", "value": "2,0"})
        self.assertEqual(self.scalar("select comparison_value from public.planning_question_visibility_rules where child_question_key=%s",
                                     (child["question_key"],)), "2")

    def test_12_a_question_that_becomes_a_number_keeps_whole_numbers(self):
        section_id = self.add_section(f"Retype {RUN}")
        key = f"retyped_{RUN}"
        self.add_question(section_id, "Retyped", "TEXT", key=key)
        self.assertTrue(self.question(key)["integer_only"])
        page = self.client.get(f"{pq.BASE}/questions/{self.question(key)['id']}").get_data(as_text=True)
        self.assertNotIn('name="integer_only"', page)  # the text form has no such box ...
        self.save_question(self.question(key), question_type="NUMBER", integer_only=None)  # ... so none is posted
        saved = self.question(key)
        self.assertEqual((saved["question_type"], saved["integer_only"]), ("NUMBER", True))
        # Once it is a number question, the box is on the form and decides.
        page = self.client.get(f"{pq.BASE}/questions/{saved['id']}").get_data(as_text=True)
        self.assertIn('name="integer_only"', page)
        self.save_question(saved, integer_only=None)
        self.assertFalse(self.question(key)["integer_only"])

    @staticmethod
    def as_authenticated(query, params=()):
        """One count as a signed-in user, the way the portal's Weekly Planning reads the catalogue (portal-api's
        user_db(): role authenticated, so row-level security applies)."""
        conn = psycopg2.connect(os.environ["DATABASE_URL"])
        try:
            with conn.cursor() as cur:
                cur.execute("set local role authenticated")
                cur.execute(query, params)
                return cur.fetchone()[0]
        finally:
            conn.rollback()
            conn.close()

    def test_13_retiring_a_parent_question_or_its_section(self):
        # Review (round 2): the page said a retired parent's rule was ignored, but a signed-in reader (then the old
        # Beta pages) still read it and kept the child hidden (and required nothing), while the portal showed and
        # required it. The portal reads as the signed-in person too, so this still matters.
        parents, children = self.add_section(f"Parents {RUN}"), self.add_section(f"Children {RUN}")
        self.add_question(parents, "Parent count", "NUMBER", key=f"parent_count_{RUN}")
        self.add_question(children, "Child count", "NUMBER", key=f"child_count_{RUN}")
        parent, child = self.question(f"parent_count_{RUN}"), self.question(f"child_count_{RUN}")
        rules = f"{pq.BASE}/questions/{child['id']}/rules"
        self.post(rules, {"action": "add", "parent": parent["question_key"], "operator": "greater_than", "value": "0"})
        self.flashes()
        portal_reads = lambda: self.as_authenticated("select count(*) from public.planning_question_visibility_rules where child_question_key=%s",
                                                  (child["question_key"],))
        rule_on = lambda: self.scalar("select active from public.planning_question_visibility_rules where child_question_key=%s", (child["question_key"],))
        self.assertEqual(portal_reads(), 1)
        self.post(f"{pq.BASE}/questions/{parent['id']}", {"action": "retire", "state": pq.row_state(self.question(parent["question_key"]))})
        message = self.flashes()
        self.assertIn("“Child count” depends on it", message)
        self.assertIn("Weekly Planning ignores that show/hide rule", message)
        self.assertEqual((portal_reads(), rule_on()), (0, True))  # ignored by Weekly Planning, but kept for when it comes back
        page = self.client.get(f"{pq.BASE}/questions/{child['id']}").get_data(as_text=True)
        self.assertIn("ignored while “Parent count” is not on the form", page)
        self.assertNotIn(f"<option value='{parent['question_key']}'>", page)  # not offered for a new rule
        self.post(f"{pq.BASE}/questions/{parent['id']}", {"action": "restore", "state": pq.row_state(self.question(parent["question_key"]))})
        self.assertIn("The show/hide rule of “Child count” applies again", self.flashes())
        self.assertEqual(portal_reads(), 1)
        # A retired section: its questions are not on the form either.
        with database.connect() as conn:
            with database.cursor(conn) as cur:
                cur.execute("select * from public.planning_question_sections where id=%s", (parents,))
                section = cur.fetchone()
        self.post(f"{pq.BASE}/sections/{parents}", {"action": "retire", "state": pq.row_state(section)})
        message = self.flashes()
        self.assertIn("“Child count” in another section depends on its questions", message)
        self.assertIn("while it is retired, Weekly Planning ignores those show/hide rules", message)
        self.assertEqual((portal_reads(), rule_on()), (0, True))
        page = self.client.get(f"{pq.BASE}/questions/{child['id']}").get_data(as_text=True)
        self.assertIn("ignored while “Parent count” is not on the form", page)
        self.assertNotIn(f"<option value='{parent['question_key']}'>", page)
        other =self.add_question(children, "Second child", "NUMBER", key=f"second_child_{RUN}")
        self.post(f"{pq.BASE}/questions/{other['id']}/rules", {"action": "add", "parent": parent["question_key"], "operator": "greater_than", "value": "0"})
        self.assertIn("that is on the form", self.flashes())
        with database.connect() as conn:
            with database.cursor(conn) as cur:
                cur.execute("select * from public.planning_question_sections where id=%s", (parents,))
                section = cur.fetchone()
        self.post(f"{pq.BASE}/sections/{parents}", {"action": "restore", "state": pq.row_state(section)})
        self.assertIn("The show/hide rules of “Child count” apply again", self.flashes())
        self.assertEqual(portal_reads(), 1)

    def test_14_a_choice_a_rule_looks_for_stays(self):
        # Review: retiring or deleting a choice named by a rule left its question impossible to show.
        section_id = self.add_section(f"Named choices {RUN}")
        self.add_question(section_id, "How did you meet?", "SELECT", key=f"how_met_{RUN}")
        self.add_question(section_id, "Who referred them?", "TEXT", key=f"referred_by_{RUN}")
        how, detail = self.question(f"how_met_{RUN}"), self.question(f"referred_by_{RUN}")
        base, rules = f"{pq.BASE}/questions/{how['id']}/choices", f"{pq.BASE}/questions/{detail['id']}/rules"
        self.post(base, {"kind": "option", "action": "add", "label": "Referral", "value": "referral"})
        self.post(base, {"kind": "option", "action": "add", "label": "Street", "value": "street"})
        self.post(rules, {"action": "add", "parent": how["question_key"], "operator": "equals", "value": "Referral"})
        self.assertIn("Rule added", self.flashes())
        option = lambda: self.one("select * from public.planning_question_options where question_id=%s and option_label like '%%Referral'", (how["id"],))
        page = self.client.get(f"{pq.BASE}/questions/{how['id']}").get_data(as_text=True)
        self.assertIn("The show/hide rule of “Who referred them?” looks for it", page)
        before = self.history_count()
        for action, extra in (("retire", {}), ("delete", {}), ("save", {"label": "Referral", "value": "referred"})):
            self.post(base, {"kind": "option", "action": action, "item_id": option()["id"], "state": pq.row_state(option()), **extra})
            self.assertIn("looks for “Referral”", self.flashes(), action)
        self.assertEqual((option()["active"], option()["option_value"], self.history_count()), (True, "referral", before))
        self.post(base, {"kind": "option", "action": "save", "item_id": option()["id"], "state": pq.row_state(option()), "label": "A Referral"})
        self.assertEqual(option()["option_label"], "A Referral")  # the label can still change
        # Once the rule is off the choice can go, and the rule cannot be turned on again while its choice is gone.
        rule_id = self.scalar("select id from public.planning_question_visibility_rules where child_question_key=%s", (detail["question_key"],))
        self.post(rules, {"action": "off", "rule_id": rule_id})
        self.post(base, {"kind": "option", "action": "retire", "item_id": option()["id"], "state": pq.row_state(option())})
        self.assertFalse(option()["active"])
        self.flashes()
        self.post(rules, {"action": "on", "rule_id": rule_id})
        self.assertIn("no longer offers the choice this rule looks for", self.flashes())
        self.assertFalse(self.scalar("select active from public.planning_question_visibility_rules where id=%s", (rule_id,)))

    def test_15_whole_number_questions_need_whole_limits(self):
        # Review: a lowest number of 0.5 with "Whole numbers only" made every whole number wrong in the portal's box.
        section_id = self.add_section(f"Whole limits {RUN}")
        key = f"whole_limits_{RUN}"
        self.add_question(section_id, "Whole limits", "NUMBER", key=key)
        before = self.history_count()
        for fields in ({"min_value": "0.5"}, {"max_value": "9,5"}, {"min_value": "1", "max_value": "2.25"}):
            self.save_question(self.question(key), **fields)
            self.assertIn("must be whole numbers too", self.flashes(), fields)
        self.assertEqual((self.question(key)["min_value"], self.question(key)["max_value"], self.history_count()), (None, None, before))
        self.save_question(self.question(key), min_value="0.5", max_value="9.5", integer_only=None)  # decimals allowed: fine
        self.assertEqual((float(self.question(key)["min_value"]), self.question(key)["integer_only"]), (0.5, False))
        self.save_question(self.question(key), min_value="0.5", max_value="9.5", integer_only="yes")
        self.assertIn("must be whole numbers too", self.flashes())
        self.assertFalse(self.question(key)["integer_only"])
        # The database refuses the same without the page (Supabase Studio), with the page's words when it shows it.
        with self.assertRaisesRegex(Exception, "planning_questions_whole_limits"):
            self.execute("update public.planning_questions set integer_only=true where question_key=%s", (key,))

    def test_16_a_locked_optional_question_stays_optional(self):
        # Review: ticking Required on a locked optional question could only be undone with SQL.
        q = self.question("information_up_chain")
        self.assertEqual((q["protected"], q["required"]), (True, False))
        page = self.client.get(f"{pq.BASE}/questions/{q['id']}").get_data(as_text=True)
        details = page[page.index("Question (what missionaries read)"):page.index("Save question")]
        self.assertNotIn("name='required'", details)  # shown, but disabled and not posted
        self.assertIn("stays optional", details)
        before = self.history_count()
        self.save_question(q, required="yes")
        self.assertIn("is locked, so it stays optional", self.flashes())
        self.assertEqual((self.question("information_up_chain")["required"], self.history_count()), (False, before))

    def test_17_readable_delete_buttons_and_answer_counts(self):
        section_id = self.add_section(f"Buttons {RUN}")
        self.add_question(section_id, "Button check", "RADIO", key=f"button_check_{RUN}")
        q = self.question(f"button_check_{RUN}")
        self.post(f"{pq.BASE}/questions/{q['id']}/choices", {"kind": "option", "action": "add", "label": "Unused"})
        page = self.client.get(f"{pq.BASE}/questions/{q['id']}").get_data(as_text=True)
        self.assertIn('<button class="danger" name="action" value="delete"', page)  # white on red, like the rest of DA Management
        self.assertNotIn("secondary danger", page)
        # The saved answers are counted once for all questions (review: one full scan per question); same numbers.
        with database.connect() as conn:
            with database.cursor(conn) as cur:
                _, questions, _ = pq.load_catalog(cur)
                cur.execute("select question_key,count(*) n from public.weekly_planning_answers group by question_key")
                direct = {row["question_key"]: row["n"] for row in cur.fetchall()}
        self.assertEqual({q["question_key"]: q["answered"] for q in questions}, {q["question_key"]: direct.get(q["question_key"], 0) for q in questions})
        self.assertTrue(any(q["answered"] for q in questions))

    def one(self, query, params=()):
        with database.connect() as conn:
            with database.cursor(conn) as cur:
                cur.execute(query, params)
                return cur.fetchone()

    def test_18_preach_my_gospel_wording_and_new_people_being_taught(self):
        home = self.client.get(pq.BASE).get_data(as_text=True)
        for text in (pq.EXPLAIN, pq.TIMING, pq.PEOPLE_CARDS, pq.LOCKED_NOTE):
            self.assertIn(text, home)
        self.assertIn("Every question adds time to someone's Sunday.", home)
        # Review: the home page's note is not next to one question, so it speaks of locked questions in general.
        self.assertIn("Locked questions are read by Dashboards, Call-ins, Presentations or Archetypal Health. You can "
                      "change their wording", home)
        self.assertIn("Missionaries answer these questions every week in Weekly Planning. Ask only", home)
        self.assertNotIn("You can change its wording", home)
        self.assertIn('placeholder="for example service_projects_goal"', home)
        locked = self.question("friends_found_actual")
        page = self.client.get(f"{pq.BASE}/questions/{locked['id']}").get_data(as_text=True)
        self.assertIn(pq.LOCK_RULES, page)
        self.assertIn("A key indicator: Dashboards, Call-ins and Presentations read it.", page)
        # After migration 028 the key indicator is New People Being Taught everywhere the page shows it; the key stays.
        if self.scalar("select count(*) from public.planning_catalog_changes where actor='Migration 028'"):
            self.assertIn("New People Being Taught — Actual", page)
            self.assertIn("<code>friends_found_actual</code>", page)
            self.assertNotIn("Friends Found —", home)
            history = self.client.get(f"{pq.BASE}/history").get_data(as_text=True)
            self.assertIn("Migration 028", history)
            self.assertIn("Friends Found — Actual → New People Being Taught — Actual", history)
            preview = self.client.get(f"{pq.BASE}/preview").get_data(as_text=True)
            self.assertIn("New People Being Taught — Goal", preview)
            self.assertIn("What will you do, with whom, and when? Include how members can help.", preview)
            self.assertIn("Your GEMIKO (ward mission coordination) meeting: was it held, and who came?", preview)

    def test_19_no_page_names_the_old_beta_pages(self):
        # Round 8: Appsmith (the old "Beta" pages) was removed on 29 Sep. The change history is left out on purpose:
        # it quotes what was written at the time (Migration 024's note still says Beta).
        old_names = re.compile(r"\bBeta\b|(?i:appsmith)")
        pages = {path: self.client.get(path).get_data(as_text=True) for path in (pq.BASE, f"{pq.BASE}/preview")}
        with database.connect() as conn:
            with database.cursor(conn) as cur:
                cur.execute("select id,question_key from public.planning_questions where protected order by id")
                locked = cur.fetchall()
        for row in locked:  # every locked question page, so every "who reads it" sentence is seen
            pages[row["question_key"]] = self.client.get(f"{pq.BASE}/questions/{row['id']}").get_data(as_text=True)
        self.assertGreater(len(locked), 0)
        for name, page in pages.items():
            self.assertIsNone(old_names.search(page), name)
        expected = {  # the new words, where the old ones named Beta
            "friends_found_plan": "The action plan of a key indicator: leaders read it in Call-ins.",
            "ward_coordination_held": "Call-ins shows it under GEMIKO (ward mission coordination), with its rows and choices.",
            "long_term_service": "Saved plans keep their answers under this key, so it stays the same.",
        }
        for key, text in expected.items():
            if key in pages:
                self.assertIn(text, pages[key], key)

    def test_08_make_key(self):
        self.assertEqual(pq.make_key("Friends Found — Goal", set()), "friends_found_goal")
        self.assertEqual(pq.make_key("Übung für Jugendliche", set()), "uebung_fuer_jugendliche")
        self.assertEqual(pq.make_key("2 Wochen", set()), "q_2_wochen")
        self.assertEqual(pq.make_key("ab", {"ab_1"}), "ab_1_2")
        self.assertEqual(pq.make_key("Friends found goal", {"friends_found_goal"}), "friends_found_2_goal")
        self.assertEqual(pq.make_key("No", set(), pattern=pq.VALUE_PATTERN), "no")
        self.assertTrue(re.match(pq.KEY_PATTERN, pq.make_key("x" * 200, set())))


if __name__ == "__main__":
    unittest.main()
