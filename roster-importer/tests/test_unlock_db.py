"""Unlocking a locked Weekly Planning question against a THROWAWAY copy of the mission database with migration 024 applied (the real
trigger planning_questions_guard). NOT run in round 13 (no database in the overnight sandbox): run it on the throw-away copy.

It changes the locked question friends_found_actual (and locks it again at the end), so it refuses to run unless DATABASE_URL
names a database whose name contains "test" (never the live host) and PLANQ_TEST_THROWAWAY=yes, like test_planning_questions.py.

Run in a temporary roster-importer container on the test network:
  docker run --rm --network gfm-test-r2-net -v <worktree>/roster-importer:/app -w /app \
    -e DATABASE_URL=postgresql://postgres:<password>@gfm-test-r2-db:5432/gfm_test_planq_2 -e PLANQ_TEST_THROWAWAY=yes \
    roster-importer-roster-importer python -m unittest tests/test_unlock_db.py -v

Checks: a manager unlocks with a reason and the change history says who and why; an Office person and the shared password cannot;
the database stays protective for everyone else (the setting is only on for the unlock statement); an unlocked question can be
retired and restored and locked again; a retired one cannot be locked again (the database says why).
"""
import os
import time
import unittest
import uuid
from unittest.mock import patch
from urllib.parse import urlsplit

import psycopg2

parts = urlsplit(os.environ.get("DATABASE_URL", ""))
if (os.environ.get("PLANQ_TEST_THROWAWAY") != "yes" or "test" not in parts.path
        or parts.hostname == "gfm-beta-supabase-db-1"):
    raise RuntimeError("A throwaway *test* database (not the live host) and PLANQ_TEST_THROWAWAY=yes are required.")

import app  # noqa: E402
import database  # noqa: E402
import planning_questions as pq  # noqa: E402
import sign_in  # noqa: E402

EDITOR_ID = str(uuid.uuid4())
KEY = "friends_found_actual"


class UnlockTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app.app.config["TESTING"] = True
        cls.context = patch.object(sign_in, "current_management_context",
                                   return_value={"user_id": EDITOR_ID, "mission_id": 2, "management_role": "DATA_ADMIN"})
        cls.context.start()

    @classmethod
    def tearDownClass(cls):
        cls.context.stop()

    def setUp(self):
        self.addCleanup(self.lock_for_good)
        self.lock_for_good()

    def lock_for_good(self):
        """Every test starts and ends with the question active and locked (a direct UPDATE: locking needs no setting)."""
        self.execute("update public.planning_questions set active=true where question_key=%s", (KEY,))
        self.execute("update public.planning_questions set protected=true where question_key=%s", (KEY,))

    def as_role(self, role):
        client = app.app.test_client()
        with client.session_transaction() as s:
            s.update(authenticated=True, portal_role=role, portal_user="Test Person", portal_user_id=EDITOR_ID,
                     portal_mission_id=2, portal_expires_at=time.time() + 1800, csrf_token="test-csrf")
        return client

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

    def question(self):
        with database.connect() as conn:
            with database.cursor(conn) as cur:
                cur.execute("select * from public.planning_questions where question_key=%s", (KEY,))
                return cur.fetchone()

    def post(self, client, action, **data):
        q = self.question()
        return client.post(f"/planning-questions/questions/{q['id']}/{action}",
                           data={"csrf_token": "test-csrf", "state": pq.row_state(q), **data})

    def flashes(self, client):
        with client.session_transaction() as s:
            return " ".join(message for _, message in s.pop("_flashes", []))

    def test_01_a_manager_unlocks_with_a_reason_and_the_history_says_who_and_why(self):
        for role in ("DATA_ADMIN", "AP", "PRESIDENT"):
            client = self.as_role(role)
            response = self.post(client, "unlock", reason=f"{role} replaces the indicator", confirm_key=KEY)
            self.assertEqual(response.status_code, 302, role)
            self.assertFalse(self.question()["protected"], role)
            note, actor = self.scalar("select note from public.planning_catalog_changes order by id desc limit 1"), \
                self.scalar("select actor from public.planning_catalog_changes order by id desc limit 1")
            self.assertEqual(note, f"Unlocked: {role} replaces the indicator")
            self.assertEqual(actor, "Test Person")
            self.lock_for_good()

    def test_02_office_and_a_wrong_key_and_no_reason_change_nothing(self):
        before = self.scalar("select count(*) from public.planning_catalog_changes")
        for client, data in ((self.as_role("OFFICE"), {"reason": "a fine reason", "confirm_key": KEY}),
                             (self.as_role("DATA_ADMIN"), {"reason": "a fine reason", "confirm_key": "wrong_key"}),
                             (self.as_role("DATA_ADMIN"), {"reason": "", "confirm_key": KEY})):
            self.assertEqual(self.post(client, "unlock", **data).status_code, 302)
            self.assertTrue(self.question()["protected"])
        self.assertEqual(self.scalar("select count(*) from public.planning_catalog_changes"), before)

    def test_03_the_database_stays_protective_for_everyone_else(self):
        client = self.as_role("DATA_ADMIN")
        self.post(client, "unlock", reason="a fine reason", confirm_key=KEY)
        self.lock_for_good()
        # The setting was on only for the unlock statement: a plain UPDATE that removes the protection is refused again.
        with database.connect() as conn:
            with conn.cursor() as cur:
                with self.assertRaises(psycopg2.Error) as caught:
                    cur.execute("update public.planning_questions set protected=false where question_key=%s", (KEY,))
                self.assertIn("is protected because reports read it", str(caught.exception))
            conn.rollback()

    def test_04_an_unlocked_question_can_be_retired_restored_and_locked_again(self):
        client = self.as_role("AP")
        self.post(client, "unlock", reason="testing the unlock", confirm_key=KEY)
        q = self.question()
        self.assertEqual(client.post(f"/planning-questions/questions/{q['id']}",
                                     data={"csrf_token": "test-csrf", "state": pq.row_state(q), "action": "retire"}).status_code, 302)
        self.assertFalse(self.question()["active"])  # a locked question could not be retired; this one can
        self.assertEqual(self.post(client, "lock").status_code, 302)  # retired: the database says why, nothing changes
        self.assertFalse(self.question()["protected"])
        self.assertIn("stays on the form", self.flashes(client))
        q = self.question()
        client.post(f"/planning-questions/questions/{q['id']}", data={"csrf_token": "test-csrf", "state": pq.row_state(q), "action": "restore"})
        self.assertTrue(self.question()["active"])
        self.post(client, "lock")
        self.assertTrue(self.question()["protected"])
        self.assertEqual(self.scalar("select note from public.planning_catalog_changes order by id desc limit 1"), "Locked again")

    def test_05_a_question_that_is_not_locked_cannot_be_unlocked_twice(self):
        client = self.as_role("DATA_ADMIN")
        self.post(client, "unlock", reason="the first time", confirm_key=KEY)
        count = self.scalar("select count(*) from public.planning_catalog_changes")
        self.post(client, "unlock", reason="the second time", confirm_key=KEY)
        self.assertEqual(self.scalar("select count(*) from public.planning_catalog_changes"), count)


if __name__ == "__main__":
    unittest.main()
