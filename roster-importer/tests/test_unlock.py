"""Unlocking a locked Weekly Planning question from DA Management > Planning questions, without a database: only an AP, the
President or a Data Analyst signed in through the portal may; a reason and the typed key are needed; the database is told on purpose
(and only for that statement); the change history names who and why; a question reports read can be locked again; the page shows
the right form to the right person; every text is in the 14 catalogs. Made-up questions only.

The same flow against a real throw-away database (the real trigger of migration 024) is tests/test_unlock_db.py (NOT run in round 13:
no database in the overnight sandbox). Run this file from roster-importer/:  python -m unittest tests.test_unlock
"""
import json
import os
import re
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "postgresql://nobody@127.0.0.1:1/none")  # never opened by these tests
import app  # noqa: E402
import planning_questions as pq  # noqa: E402
import planning_questions_pages as pages  # noqa: E402
from unlock_text import TEXT, plain  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
WHO = ("Test Analyst", "00000000-0000-0000-0000-000000000001")
LOCKED = {"id": 7, "question_key": "friends_found_actual", "question_label": "Friends found", "question_type": "NUMBER", "protected": True,
          "active": True, "required": True, "section_id": 1, "updated_at": "2026-10-13T10:00:00", "min_value": 0, "max_value": None,
          "integer_only": True, "help_text": None, "placeholder": None, "value_when_hidden": None, "display_order": 10, "answered": 12}
OPEN = {**LOCKED, "protected": False}
OWN_QUESTION = {**LOCKED, "id": 8, "question_key": "hobby_note", "protected": False, "answered": 0}


class FakeCursor:
    """Records the statements; update_row is replaced by a recorder in the tests that look at it."""

    def __init__(self):
        self.calls = []

    def execute(self, query, params=None):
        self.calls.append((query, params))

    def fetchall(self):
        return []

    def fetchone(self):
        return None


def as_role(role):
    """A request in which a manager of this role is signed in through the portal (or nobody: role None)."""
    ctx = app.app.test_request_context("/")
    ctx.push()
    from flask import session
    session.clear()
    if role:
        session["portal_role"] = role
    return ctx


class RuleTests(unittest.TestCase):
    def tearDown(self):
        while True:
            try:
                app.app.test_request_context("/").pop()
            except Exception:
                break

    def unlock(self, role="DATA_ADMIN", q=LOCKED, reason="The new indicator replaces it", typed="friends_found_actual", who=WHO):
        ctx = as_role(role)
        try:
            cur = FakeCursor()
            with patch.object(pq, "update_row") as update:
                message = pq.unlock_question(cur, who, q, reason, typed)
            return message, cur, update
        finally:
            ctx.pop()

    def test_a_manager_unlocks_with_a_reason_and_the_database_is_told_only_for_that_statement(self):
        message, cur, update = self.unlock()
        self.assertEqual(message, plain("unlock.done"))
        self.assertEqual([params for _q, params in cur.calls], [None, None])
        self.assertIn("planning_catalog.unprotect', 'on', true", cur.calls[0][0])  # on, for this transaction only (is_local)
        self.assertIn("planning_catalog.unprotect', 'off', true", cur.calls[1][0])  # and off again right after
        args = update.call_args.args
        self.assertEqual(args[1:6], (WHO, "planning_questions", 7, {"protected": False}, {"question_key": "friends_found_actual"}))
        self.assertEqual(args[6], "Unlocked: The new indicator replaces it")  # the reason is in the change history note

    def test_the_setting_is_turned_off_again_even_when_the_database_refuses(self):
        ctx = as_role("AP")
        try:
            cur = FakeCursor()
            with patch.object(pq, "update_row", side_effect=ValueError("refused")):
                with self.assertRaises(ValueError):
                    pq.unlock_question(cur, WHO, LOCKED, "a good reason", "friends_found_actual")
            self.assertIn("'off'", cur.calls[-1][0])
        finally:
            ctx.pop()

    def test_the_three_managers_may_and_nobody_else(self):
        for role in ("AP", "PRESIDENT", "DATA_ADMIN"):
            self.assertEqual(self.unlock(role)[0], plain("unlock.done"), role)
        for role in ("OFFICE", "DL", "ZL", "STL", "MISSIONARY", None):
            with self.assertRaisesRegex(ValueError, "Only an AP, the President or a Data Analyst"):
                self.unlock(role)

    def test_nobody_behind_the_old_shared_password(self):
        with self.assertRaisesRegex(ValueError, "Only an AP"):
            self.unlock("DATA_ADMIN", who=None)

    def test_a_reason_and_the_typed_key_are_needed(self):
        for reason in ("", "   ", "no", "four"):
            with self.assertRaisesRegex(ValueError, "at least 5 characters"):
                self.unlock(reason=reason)
        for typed in ("", "friends_found", "Friends_Found_Actual", None):
            with self.assertRaisesRegex(ValueError, "key exactly"):
                self.unlock(typed=typed)
        _message, _cur, update = self.unlock(reason="  Replaced   by   a new one ", typed=" friends_found_actual ")
        self.assertEqual(update.call_args.args[6], "Unlocked: Replaced by a new one")  # extra spaces are removed

    def test_a_long_reason_is_cut_for_the_history(self):
        _message, _cur, update = self.unlock(reason="x" * 500)
        self.assertEqual(len(update.call_args.args[6]), len("Unlocked: ") + pq.UNLOCK_REASON_MAX)

    def test_a_question_that_is_not_locked_cannot_be_unlocked(self):
        with self.assertRaisesRegex(ValueError, "not locked"):
            self.unlock(q=OPEN)

    def lock(self, q, role="AP"):
        ctx = as_role(role)
        try:
            with patch.object(pq, "update_row") as update:
                return pq.lock_question(FakeCursor(), WHO, q), update
        finally:
            ctx.pop()

    def test_a_question_reports_read_can_be_locked_again_and_it_is_logged(self):
        message, update = self.lock(OPEN)
        self.assertEqual(message, plain("unlock.lockedAgain"))
        self.assertEqual(update.call_args.args[1:7], (WHO, "planning_questions", 7, {"protected": True},
                                                      {"question_key": "friends_found_actual"}, "Locked again"))

    def test_only_those_questions_can_be_locked_and_only_by_managers(self):
        with self.assertRaisesRegex(ValueError, "Only a question that reports read"):
            self.lock(OWN_QUESTION)
        with self.assertRaisesRegex(ValueError, "is locked"):
            self.lock(LOCKED)
        with self.assertRaisesRegex(ValueError, "Only an AP"):
            self.lock(OPEN, role="OFFICE")

    def test_the_lockable_questions_are_the_31_of_migration_024(self):
        self.assertEqual(len(pq.LOAD_BEARING_KEYS), 31)
        self.assertTrue(pq.KEY_INDICATOR_KEYS <= pq.LOAD_BEARING_KEYS)
        for key in pq.LOAD_BEARING_KEYS:
            self.assertTrue(pq.protected_reason(key), key)


class Ctx:
    def __init__(self, value=None):
        self.value = value

    def __enter__(self):
        return self.value

    def __exit__(self, *args):
        return False


class PageTests(unittest.TestCase):
    def client(self, role):
        client = app.app.test_client()
        with client.session_transaction() as data:
            data.update(authenticated=True, csrf_token="t")
            if role:
                data.update(portal_role=role, portal_user=WHO[0], portal_user_id=WHO[1], portal_mission_id=2)
        return client

    def question_page(self, role, question):
        sections = [{"id": 1, "section_key": "key_indicators_conversion", "section_title": "Key indicators", "active": True, "display_order": 10}]
        with patch.object(pages.sign_in, "allowed", return_value=True), patch.object(pages.database, "connect", return_value=Ctx()), \
                patch.object(pages.database, "cursor", return_value=Ctx(FakeCursor())), \
                patch.object(pages, "load_catalog", return_value=(sections, [question], [])):
            response = self.client(role).get(f"/planning-questions/questions/{question['id']}")
        self.assertEqual(response.status_code, 200)
        return response.get_data(as_text=True)

    def test_a_manager_sees_the_unlock_form_with_the_warning_a_reason_box_and_the_key_to_type(self):
        for role in ("AP", "PRESIDENT", "DATA_ADMIN"):
            html = self.question_page(role, LOCKED)
            self.assertIn("<summary>Unlock this question</summary>", html, role)
            self.assertIn('action="/planning-questions/questions/7/unlock"', html)
            self.assertIn("Reports read this question.", html)
            self.assertIn("Type the question&#x27;s key to confirm: friends_found_actual", html)
            self.assertIn('name="reason"', html)
            self.assertIn('name="confirm_key"', html)
            self.assertIn("Unlock question</button>", html)

    def test_someone_who_may_not_sees_only_the_note(self):
        html = self.question_page("OFFICE", LOCKED)
        self.assertNotIn("Unlock question</button>", html)
        self.assertIn("Only an AP, the President or a Data Analyst can unlock or lock a question.", html)

    def test_an_unlocked_question_that_reports_read_offers_to_lock_it_again(self):
        html = self.question_page("DATA_ADMIN", OPEN)
        self.assertIn("Unlocked on purpose.", html)
        self.assertIn('action="/planning-questions/questions/7/lock"', html)
        self.assertIn("Lock question again</button>", html)

    def test_an_ordinary_question_has_no_unlock_or_lock_box(self):
        html = self.question_page("DATA_ADMIN", OWN_QUESTION)
        self.assertNotIn("Unlock", html)
        self.assertNotIn("Lock question again", html)

    def test_the_home_page_says_where_to_unlock(self):
        sections = [{"id": 1, "section_key": "k", "section_title": "Key indicators", "active": True, "display_order": 10, "description": None}]
        with patch.object(pages.sign_in, "allowed", return_value=True), patch.object(pages.database, "connect", return_value=Ctx()), \
                patch.object(pages.database, "cursor", return_value=Ctx(FakeCursor())), \
                patch.object(pages, "load_catalog", return_value=(sections, [LOCKED], [])):
            html = self.client("DATA_ADMIN").get("/planning-questions").get_data(as_text=True)
        self.assertIn("A manager can unlock a locked question on its page.", html)

    def post(self, role, path, data, patches=()):
        cur = FakeCursor()
        cur.fetchone = lambda: dict(LOCKED)
        with patch.object(pages.sign_in, "allowed", return_value=True), patch.object(pages.database, "connect", return_value=Ctx()), \
                patch.object(pages.database, "cursor", return_value=Ctx(cur)), patch.object(pages.sign_in, "portal_person", return_value=WHO if role else None), \
                patch.object(pq, "update_row") as update:
            response = self.client(role).post(f"/planning-questions/questions/7/{path}", data={"csrf_token": "t", **data})
        return response, update, cur

    def flashes(self, response):
        with app.app.test_client() as client:
            return ""

    def test_the_unlock_route_unlocks_for_a_manager_and_logs_the_reason(self):
        state = pq.row_state(LOCKED)
        response, update, _cur = self.post("AP", "unlock", {"state": state, "reason": "Replaced by a new question", "confirm_key": "friends_found_actual"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "/planning-questions/questions/7")
        self.assertEqual(update.call_args.args[6], "Unlocked: Replaced by a new question")

    def test_the_unlock_route_refuses_office_a_missing_reason_a_wrong_key_and_a_stale_page(self):
        state = pq.row_state(LOCKED)
        good = {"state": state, "reason": "Replaced by a new question", "confirm_key": "friends_found_actual"}
        for role, data in (("OFFICE", good), ("AP", {**good, "reason": ""}), ("AP", {**good, "confirm_key": "nope"}),
                           ("AP", {**good, "state": "an older page"}), (None, good)):
            response, update, _cur = self.post(role, "unlock", data)
            self.assertEqual(response.status_code, 302, (role, data))
            update.assert_not_called()

    def test_the_lock_route_locks_again_for_a_manager(self):
        cur_row = dict(OPEN)
        cur = FakeCursor()
        cur.fetchone = lambda: cur_row
        with patch.object(pages.sign_in, "allowed", return_value=True), patch.object(pages.database, "connect", return_value=Ctx()), \
                patch.object(pages.database, "cursor", return_value=Ctx(cur)), patch.object(pages.sign_in, "portal_person", return_value=WHO), \
                patch.object(pq, "update_row") as update:
            response = self.client("PRESIDENT").post("/planning-questions/questions/7/lock", data={"csrf_token": "t", "state": pq.row_state(OPEN)})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(update.call_args.args[4], {"protected": True})

    def test_a_stranger_is_sent_to_the_sign_in(self):
        client = app.app.test_client()
        with client.session_transaction() as data:
            data["csrf_token"] = "t"  # a form token, but nobody signed in
        for action in ("unlock", "lock"):
            self.assertEqual(client.post(f"/planning-questions/questions/7/{action}", data={"csrf_token": "t"}).status_code, 302)

    def test_the_change_history_shows_who_and_why(self):
        change = {"table_name": "planning_questions", "row_key": {"question_key": "friends_found_actual"}, "changed_at": __import__("datetime").datetime(2026, 10, 13, 12, 0, tzinfo=__import__("datetime").timezone.utc),
                  "actor": "Test Analyst", "before_row": {"protected": True, "question_label": "Friends found"},
                  "after_row": {"protected": False, "question_label": "Friends found"}, "note": "Unlocked: Replaced by a new question"}
        html = pages.history_item(change)
        self.assertIn("Unlocked: Replaced by a new question", html)
        self.assertIn("Test Analyst", html)
        self.assertIn("protected: True → False", html)


class TextTests(unittest.TestCase):
    def test_every_text_is_in_the_portal_catalog_in_every_language(self):
        folder = ROOT / "portal" / "i18n"
        english = json.loads((folder / "en.json").read_text(encoding="utf-8"))
        texts = {value for value in english.values() if isinstance(value, str)}
        self.assertEqual(sorted(key for key, value in TEXT.items() if value not in texts), [])
        for code in json.loads((folder / "catalogs.json").read_text(encoding="utf-8"))["languages"]:
            catalog = json.loads((folder / f"{code}.json").read_text(encoding="utf-8"))
            for key in TEXT:
                self.assertTrue(str(catalog[key]).strip(), (code, key))
                self.assertEqual(sorted(re.findall(r"\{(\w+)\}", catalog[key])), sorted(re.findall(r"\{(\w+)\}", TEXT[key])), (code, key))
                if code != "en":
                    self.assertNotEqual(catalog[key], TEXT[key], (code, key))  # translated, not left in English

    def test_the_text_helpers_fill_and_escape(self):
        from unlock_text import t
        self.assertEqual(plain("unlock.typeLabel", code="a_b"), "Type the question's key to confirm: a_b")
        self.assertEqual(t("unlock.typeLabel", code="<b>"), "Type the question&#x27;s key to confirm: &lt;b&gt;")

    def test_nothing_in_the_unlock_code_names_a_removed_tool(self):
        from tests.test_page_words import texts_with_old_names
        for name in ("unlock_text.py", "planning_questions.py", "planning_questions_pages.py"):
            self.assertEqual(texts_with_old_names(ROOT / "roster-importer" / name), [], name)


if __name__ == "__main__":
    unittest.main()
