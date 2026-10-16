"""Delete retired (retire.py, backups.py, retire_pages.py) without a database or Docker: the rules, the backup hook with a
stand-in for pg_dump, the roles, the texts and the pages' own refusals. Made-up names only.

The same flow against a real throw-away database (merge, backup named in the batch, Undo) is tests/test_retire_db.py (not run
in round 13: no database in the overnight sandbox). Run this one from roster-importer/:
  python -m unittest tests.test_retire_rules
"""
import json
import os
import re
import subprocess
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import psycopg2.errors

os.environ.setdefault("DATABASE_URL", "postgresql://nobody@127.0.0.1:1/none")  # never opened by these tests
import app  # noqa: E402
import backups  # noqa: E402
import retire  # noqa: E402
import retire_pages  # noqa: E402
import roles  # noqa: E402
from retire_text import TEXT, plain, t  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
URL = "postgresql://postgres:s3cret%21pw@gfm-beta-supabase-db-1:5432/postgres"


class FakeRun:
    """Stands in for subprocess.run: records the calls, writes the file the command is asked to write."""

    def __init__(self, dump=b"PGDMP-made-up", dump_code=0, verify_code=0, stderr="pg_dump: error: boom s3cret!pw"):
        self.calls, self.dump, self.dump_code, self.verify_code, self.stderr = [], dump, dump_code, verify_code, stderr

    def __call__(self, words, env=None, **options):
        self.calls.append((list(words), dict(env or {}), options))
        if words[0] == "pg_dump":
            if self.dump_code == 0 and self.dump is not None:
                Path(words[-1]).write_bytes(self.dump)
            return subprocess.CompletedProcess(words, self.dump_code, "", self.stderr if self.dump_code else "")
        return subprocess.CompletedProcess(words, self.verify_code, "", "pg_restore: error: not a dump" if self.verify_code else "")


class BackupTests(unittest.TestCase):
    def maker(self, directory, run, **options):
        return backups.PgDumpBackup(directory=directory, command="pg_dump --format=custom --file {file}",
                                    verify_command="pg_restore --list {file}", database_url=URL, run=run,
                                    clock=lambda: datetime(2026, 10, 12, 23, 15, 0), **options)

    def test_the_name_says_what_it_is_for_and_when(self):
        self.assertEqual(backups.backup_name("area-Bockenheim / Ost", datetime(2026, 10, 12, 23, 15, 0)),
                         "gfm-before-delete-area-bockenheim-ost-20261012-231500.dump")
        self.assertEqual(backups.backup_name("", datetime(2026, 1, 2, 3, 4, 5)), "gfm-before-delete-item-20260102-030405.dump")

    def test_a_backup_is_made_checked_and_named(self):
        with tempfile.TemporaryDirectory() as folder:
            run = FakeRun()
            backup = self.maker(folder, run).make("area-bockenheim")
            self.assertEqual(backup.name, "gfm-before-delete-area-bockenheim-20261012-231500.dump")
            self.assertTrue((Path(folder) / backup.name).is_file())
            self.assertEqual(backup.as_summary(), {"backup": backup.name, "backup_size_bytes": len(b"PGDMP-made-up"),
                                                   "backup_checked": True})
            self.assertEqual([c[0][0] for c in run.calls], ["pg_dump", "pg_restore"])  # made, then read back

    def test_the_password_never_goes_into_a_command_line(self):
        with tempfile.TemporaryDirectory() as folder:
            run = FakeRun()
            self.maker(folder, run).make("x")
            for words, environment, options in run.calls:
                self.assertNotIn("s3cret", " ".join(words))
                self.assertEqual(environment["PGPASSWORD"], "s3cret!pw")
                self.assertEqual((environment["PGHOST"], environment["PGPORT"], environment["PGUSER"], environment["PGDATABASE"]),
                                 ("gfm-beta-supabase-db-1", "5432", "postgres", "postgres"))
                self.assertFalse(options.get("shell"), "no shell")

    def test_a_failed_dump_stops_everything_and_does_not_repeat_the_password(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(backups.BackupError) as caught:
                self.maker(folder, FakeRun(dump_code=1)).make("x")
            self.assertIn("boom", str(caught.exception))
            self.assertNotIn("s3cret", str(caught.exception))
            self.assertEqual(list(Path(folder).iterdir()), [])

    def test_no_file_an_empty_file_or_an_unreadable_file_is_a_failed_backup(self):
        with tempfile.TemporaryDirectory() as folder:
            for run in (FakeRun(dump=None), FakeRun(dump=b""), FakeRun(verify_code=1)):
                with self.assertRaises(backups.BackupError):
                    self.maker(folder, run).make("x")

    def test_a_missing_program_and_a_timeout_are_plain_failures(self):
        def missing(words, **options):
            raise FileNotFoundError(words[0])

        def slow(words, **options):
            raise subprocess.TimeoutExpired(words, 1)

        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(backups.BackupError, "not installed"):
                self.maker(folder, missing).make("x")
            with self.assertRaisesRegex(backups.BackupError, "too long"):
                self.maker(folder, slow).make("x")

    def test_the_command_needs_the_file_place(self):
        with self.assertRaises(backups.BackupError):
            backups.command_words("pg_dump --format=custom", "/b/x.dump")
        self.assertEqual(backups.command_words("pg_dump -f {file}", "/b/x y.dump"), ["pg_dump", "-f", "/b/x y.dump"])

    def test_the_hook_can_be_replaced_for_a_test(self):
        class Fake:
            def make(self, label):
                return backups.Backup("fake.dump", "/tmp/fake.dump", 1, True)

        backups.set_maker(Fake())
        try:
            self.assertEqual(backups.current().make("x").name, "fake.dump")
            self.assertEqual(retire.make_backup("x").name, "fake.dump")
        finally:
            backups.set_maker(None)

    def test_a_failing_hook_becomes_a_plain_refusal_that_says_nothing_was_deleted(self):
        class Broken:
            def make(self, label):
                raise backups.BackupError("disk full")

        with self.assertRaises(retire.Refusal) as caught:
            retire.make_backup("x", Broken())
        self.assertIn("nothing was deleted", str(caught.exception))
        self.assertIn("disk full", str(caught.exception))


class RuleTests(unittest.TestCase):
    PLACE = {"id": 7, "name": "Altstadt", "active": False, "mission_id": 2, "parent_id": 3, "parent_name": "Frankfurt 1"}

    def check(self, place=None, serving=0, found=(), successor=None, successor_id=None, level="area"):
        rows = {7: place or self.PLACE, 8: successor}
        with patch.object(retire, "place_row", side_effect=lambda cur, lvl, pid, lock=False: rows.get(pid)), \
                patch.object(retire, "serving_now", return_value=serving), \
                patch.object(retire, "attached", return_value=list(found)):
            return retire.check_place(None, level, 7, successor_id, 2)

    def attached(self, table="weekly_area_reports", count=5, removable=False, supported=True, schema="public"):
        return {"schema": schema, "table": table, "column": "area_id", "rule": "r", "width": 1, "count": count,
                "category": retire.CATEGORY.get(table, "other"), "removable": removable, "supported": supported, "pk": ["id"]}

    def test_only_a_closed_place_can_be_deleted(self):
        with self.assertRaisesRegex(retire.Refusal, "still open"):
            self.check(place={**self.PLACE, "active": True})

    def test_an_area_with_missionaries_is_refused(self):
        with self.assertRaisesRegex(retire.Refusal, "3 missionary.ies. serve here now"):
            self.check(serving=3)

    def test_a_place_of_another_mission_or_a_missing_place_is_refused(self):
        with self.assertRaisesRegex(retire.Refusal, "not in your mission"):
            self.check(place={**self.PLACE, "mission_id": 5})
        with patch.object(retire, "place_row", return_value=None):
            with self.assertRaisesRegex(retire.Refusal, "not in your mission"):
                retire.check_place(None, "area", 7, None, 2)

    def test_history_must_move_to_a_successor_but_settings_may_just_go(self):
        with self.assertRaisesRegex(retire.Refusal, "Choose below where it moves to"):
            self.check(found=[self.attached()])
        place, found, successor = self.check(found=[self.attached("area_geo_data", 1, removable=True)])
        self.assertIsNone(successor)
        self.assertEqual(len(found), 1)
        place, found, successor = self.check(found=[self.attached()], successor={**self.PLACE, "id": 8, "active": True}, successor_id=8)
        self.assertEqual(successor["id"], 8)

    def test_the_successor_must_be_open_in_the_same_mission_and_another_place(self):
        for bad in ({**PLACE_OPEN, "active": False}, {**PLACE_OPEN, "mission_id": 9}, None):
            with self.assertRaisesRegex(retire.Refusal, "not a place it can move to"):
                self.check(found=[self.attached()], successor=bad, successor_id=8)
        with patch.object(retire, "place_row", side_effect=[self.PLACE, {**PLACE_OPEN, "id": 7}]), \
                patch.object(retire, "serving_now", return_value=0), patch.object(retire, "attached", return_value=[]):
            with self.assertRaisesRegex(retire.Refusal, "not a place it can move to"):
                retire.check_place(None, "area", 7, 7, 2)  # itself

    def test_what_this_page_cannot_undo_stops_the_delete(self):
        with self.assertRaisesRegex(retire.Refusal, "portal.presentation_access"):
            self.check(found=[self.attached("presentation_access", 2, supported=False, schema="portal")])

    def test_a_unique_clash_in_a_merge_says_so_and_names_what_clashed(self):
        class Cursor:
            rowcount = 0

            def execute(self, query, params=None):
                raise psycopg2.errors.UniqueViolation()

        with self.assertRaisesRegex(retire.Refusal, "Weekly plans.*Nothing was changed"):
            retire.move_what_is_attached(Cursor(), [self.attached()], 7, 8)

    def test_every_table_that_points_at_a_place_has_a_group(self):
        """Read from the baseline and the migrations: a table that gets a key to zones, districts or areas must be put in
        retire.CATEGORY on purpose (this test fails until it is), so the preview never says 'Other data' by accident."""
        text = (ROOT / "portal-api" / "baseline" / "000_baseline.sql").read_text(encoding="utf-8", errors="replace")
        for path in sorted((ROOT / "portal-api" / "migrations").glob("0[4-9]*.sql")):
            if "rollback" not in path.name:
                text += path.read_text(encoding="utf-8", errors="replace")
        pattern = re.compile(r"(?:ALTER TABLE ONLY|ALTER TABLE) (?:public\.)?(\w+)\s+ADD CONSTRAINT \w+ FOREIGN KEY \(\w+\) REFERENCES (?:public\.)?(zones|districts|areas)\(", re.I)
        referencing = {m.group(1) for m in pattern.finditer(text)}
        referencing -= {m.group(1) for m in re.finditer(r"^DROP TABLE IF EXISTS public\.(\w+);", text, re.M | re.I)}  # a migration that drops a table (057 drops the Area data table)
        # Tables made by a migration with an inline REFERENCES (area_geo_data of 046).
        referencing |= {"area_geo_data"} if re.search(r"area_geo_data \($\n  area_id bigint PRIMARY KEY REFERENCES public\.areas", text, re.M) else set()
        # (zone_geo_data and district_geo_data of 052 the same way)
        referencing |= {"zone_geo_data"} if re.search(r"zone_geo_data \($\n  zone_id bigint PRIMARY KEY REFERENCES public\.zones", text, re.M) else set()
        referencing |= {"district_geo_data"} if re.search(r"district_geo_data \($\n  district_id bigint PRIMARY KEY REFERENCES public\.districts", text, re.M) else set()
        self.assertTrue({"weekly_area_reports", "missionary_assignments", "districts"} <= referencing, referencing)
        self.assertEqual(sorted(table for table in referencing if table not in retire.CATEGORY), [])
        self.assertLessEqual(retire.REMOVABLE, set(retire.CATEGORY))

    def test_undo_may_touch_the_place_tables_the_tables_that_point_at_them_and_the_question_tables(self):
        class Cursor:
            def execute(self, query, params=None):
                self.table = params[0].split(".")[1]

            def fetchall(self):
                return {"zones": [{"schema_name": "public", "table_name": "districts", "column_name": "zone_id", "delete_rule": "c", "width": 1},
                                  {"schema_name": "portal", "table_name": "presentation_access", "column_name": "owner_zone_id", "delete_rule": "n", "width": 1}],
                        "areas": [{"schema_name": "public", "table_name": "weekly_area_reports", "column_name": "area_id", "delete_rule": "r", "width": 1}]
                        }.get(self.table, [])

        tables = retire.allowed_tables(Cursor())
        for name in ("zones", "districts", "areas", "weekly_area_reports", "planning_questions", "weekly_planning_answers"):
            self.assertIn(name, tables)
        self.assertNotIn("presentation_access", tables)

    def test_places_come_back_before_what_points_at_them(self):
        rows = {"weekly_area_reports": {}, "districts": {}, "zones": {}, "areas": {}, "area_geo_data": {}}
        self.assertEqual(retire.ordered(rows), ["zones", "districts", "areas", "area_geo_data", "weekly_area_reports"])
        self.assertEqual(retire.QUESTION_TABLES[0], "planning_questions")  # the question before its parts, the answers last
        self.assertEqual(retire.QUESTION_TABLES[-1], "weekly_planning_answers")


PLACE_OPEN = {"id": 8, "name": "Neustadt", "active": True, "mission_id": 2, "parent_id": 3, "parent_name": "Frankfurt 1"}


class RoleAndPageTests(unittest.TestCase):
    def test_only_managers_signed_in_through_the_portal_may_retire(self):
        with app.app.test_request_context("/"):
            from flask import session
            for role, expected in (("DATA_ADMIN", True), ("PRESIDENT", True), ("AP", True), ("OFFICE", False), ("DL", False), (None, False)):
                session.clear()
                if role:
                    session["portal_role"] = role
                self.assertEqual(roles.may_retire(), expected, role)

    def test_the_old_shared_password_may_not_delete(self):
        client = app.app.test_client()
        with client.session_transaction() as data:
            data.update(authenticated=True, csrf_token="t")  # no portal_role: the shared password
        with patch.object(retire_pages.sign_in, "allowed", return_value=True):
            for path in ("/retire", "/retire/place/area/1", "/retire/question/some_question"):
                self.assertEqual(client.get(path).status_code, 403, path)
            for path in ("/retire/place/area/1/delete", "/retire/question/some_question/delete"):
                response = client.post(path, data={"csrf_token": "t", "typed": "x"})
                self.assertEqual(response.status_code, 403, path)

    def test_a_stranger_is_sent_to_the_sign_in(self):
        client = app.app.test_client()
        for path in ("/retire", "/retire/place/zone/1", "/retire/question/some_question"):
            self.assertEqual(client.get(path).status_code, 302, path)

    def test_the_run_functions_refuse_before_touching_anything(self):
        with app.app.test_request_context("/"):
            with self.assertRaises(PermissionError):
                retire.run_place_delete("area", 1, None, "x")
            with self.assertRaises(PermissionError):
                retire.run_question_delete("some_question", None, False, "some_question")


class FakeConnection:
    """A stand-in for database.connect(): a context manager that never opens anything."""

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class PageRenderTests(unittest.TestCase):
    """The pages build their HTML from stand-in answers (no database): the forms, the checks and the refusals show up."""
    CLOSED = {"id": 7, "name": "Alt <Stadt>", "active": False, "mission_id": 2, "parent_id": 3, "parent_name": "Frankfurt 1"}
    FOUND = [{"schema": "public", "table": "weekly_area_reports", "column": "area_id", "rule": "r", "width": 1, "count": 5,
              "category": "plans", "removable": False, "supported": True, "pk": ["id"]},
             {"schema": "public", "table": "area_geo_data", "column": "area_id", "rule": "c", "width": 1, "count": 1,
              "category": "settings", "removable": True, "supported": True, "pk": ["area_id"]}]

    def render_place(self, place=None, into=None, fail=None, serving=0):
        place = place or self.CLOSED
        outcome = {"moved": {"plans": 5}, "removed": 1, "batch": None}
        answer = {"side_effect": fail} if fail else {"return_value": outcome}
        with patch.object(retire_pages.database, "connect", return_value=FakeConnection()), \
                patch.object(retire_pages.database, "cursor", return_value=FakeConnection()), \
                patch.object(retire_pages.sign_in, "current_mission_id", return_value=2), \
                patch.object(retire, "place_row", return_value=place), patch.object(retire, "serving_now", return_value=serving), \
                patch.object(retire, "attached", return_value=self.FOUND), patch.object(retire, "derived_counts", return_value={"answers": 40}), \
                patch.object(retire, "successors", return_value=[(8, "Frankfurt / Frankfurt 1 / Neu")]), \
                patch.object(retire, "check_place_delete", **answer) as check_call:
            return retire_pages.place_page("area", 7, into), check_call

    def test_a_closed_area_shows_what_is_attached_and_asks_where_it_moves(self):
        (html, status), check_call = self.render_place()
        self.assertEqual(status, 200)
        for text in ("Delete area Alt &lt;Stadt&gt;", "Weekly plans", "Its own settings", "Saved answers in those plans: 40",
                     "Choose below where it moves to", "Frankfurt / Frankfurt 1 / Neu", "Do not move anything"):
            self.assertIn(text, html)
        self.assertNotIn("Back up and delete", html)  # nothing may be deleted before a successor is chosen
        check_call.assert_not_called()

    def test_with_a_successor_the_check_runs_and_the_confirmation_form_appears(self):
        (html, status), check_call = self.render_place(into=8)
        check_call.assert_called_once_with("area", 7, 8)
        self.assertIn("Check passed: 5 rows move and 1 settings rows are removed with it", html)
        self.assertIn("Type the name Alt &lt;Stadt&gt; to confirm", html)
        self.assertIn("Delete for good", html)
        self.assertIn("/retire/place/area/7/delete", html)
        self.assertIn('name="into" value="8"', html)

    def test_a_failed_check_shows_why_and_no_delete_button(self):
        (html, status), _ = self.render_place(into=8, fail=retire.Refusal("Both have data for the same week"))
        self.assertIn("Check failed", html)
        self.assertIn("Both have data for the same week", html)
        self.assertNotIn("Back up and delete", html)

    def test_an_open_area_and_an_area_with_missionaries_only_show_the_reason(self):
        (html, _), _ = self.render_place(place={**self.CLOSED, "active": True})
        self.assertIn("still open", html)
        self.assertNotIn("Back up and delete", html)
        (html, _), _ = self.render_place(serving=2)
        self.assertIn("2 missionary(ies) serve here now", html)
        self.assertNotIn("Back up and delete", html)

    def test_the_list_and_the_question_pages(self):
        closed = [{"level": "area", "id": 7, "name": "Alt", "parent": "Frankfurt / F1"}]
        question = {"id": 3, "question_key": "old_question", "question_label": "Old <b>question</b>", "question_type": "NUMBER",
                    "active": False, "protected": False}
        with patch.object(retire_pages.database, "connect", return_value=FakeConnection()), \
                patch.object(retire_pages.database, "cursor", return_value=FakeConnection()), \
                patch.object(retire_pages.sign_in, "current_mission_id", return_value=2), \
                patch.object(retire, "closed_places", return_value=closed), \
                patch.object(retire, "retired_questions", return_value=[{**question, "answers": 4}]), \
                patch.object(retire, "question_row", return_value=question), \
                patch.object(retire, "question_parts", return_value={"answers": 4, "options": 0, "grid_rows": 0, "rules": 1}), \
                patch.object(retire, "answer_targets", return_value=[("new_question", "New question")]), \
                patch.object(retire, "check_question_delete", return_value={"moved": 4, "deleted_answers": 0, "parts": 1}) as check_call:
            listing = retire_pages.list_page()
            self.assertIn("/retire/place/area/7", listing)
            self.assertIn("/retire/question/old_question", listing)
            self.assertIn("Old &lt;b&gt;question&lt;/b&gt;", listing)
            html, status = retire_pages.question_page("old_question")
            self.assertIn("Saved answers: 4. Answer choices: 0. Grid rows: 0. Show/hide rules that name it: 1.", html)
            self.assertNotIn("Back up and delete", html)  # the saved answers need a decision first
            html, status = retire_pages.question_page("old_question", into="new_question")
            check_call.assert_called_with("old_question", "new_question", False)
            self.assertIn("Check passed: 4 saved answers move, 0 are deleted, 1 choices, rows and rules go with it", html)
            self.assertIn("Type the name old_question to confirm", html)
            html, status = retire_pages.question_page("old_question", drop=True)
            check_call.assert_called_with("old_question", None, True)
            self.assertIn("Delete for good", html)

    def test_a_locked_or_active_question_cannot_be_deleted(self):
        for changes, text in (({"protected": True}, "It is locked"), ({"active": True}, "still on the form")):
            question = {"id": 3, "question_key": "q_key", "question_label": "Q", "question_type": "TEXT", "active": False,
                        "protected": False, **changes}
            with patch.object(retire_pages.database, "connect", return_value=FakeConnection()), \
                    patch.object(retire_pages.database, "cursor", return_value=FakeConnection()), \
                    patch.object(retire, "question_row", return_value=question), \
                    patch.object(retire, "question_parts", return_value={"answers": 0, "options": 0, "grid_rows": 0, "rules": 0}), \
                    patch.object(retire, "answer_targets", return_value=[]):
                html, status = retire_pages.question_page("q_key")
            self.assertIn(text, html)
            self.assertNotIn("Back up and delete", html)


class TextTests(unittest.TestCase):
    def test_every_text_is_in_the_portal_catalog_in_every_language(self):
        folder = ROOT / "portal" / "i18n"
        english = json.loads((folder / "en.json").read_text(encoding="utf-8"))
        texts = {value for value in english.values() if isinstance(value, str)}
        self.assertEqual(sorted(key for key, value in TEXT.items() if value not in texts), [])
        for code in json.loads((folder / "catalogs.json").read_text(encoding="utf-8"))["languages"]:
            catalog = json.loads((folder / f"{code}.json").read_text(encoding="utf-8"))
            self.assertEqual(sorted(set(english) - set(catalog)), [], code)
            for key, value in english.items():
                if key.startswith("retire."):
                    self.assertTrue(catalog[key].strip(), (code, key))
                    self.assertEqual(sorted(set(re.findall(r"\{(\w+)\}", catalog[key]))),
                                     sorted(set(re.findall(r"\{(\w+)\}", value))), (code, key))

    def test_the_helpers_fill_and_escape(self):
        self.assertEqual(plain("retire.place.titleArea", name="Alt"), "Delete area Alt")
        self.assertEqual(t("retire.place.titleArea", name="<b>"), "Delete area &lt;b&gt;")

    def test_every_key_used_exists(self):
        source = "".join((Path(__file__).resolve().parents[1] / f).read_text(encoding="utf-8")
                         for f in ("retire.py", "retire_pages.py"))
        used = set(re.findall(r"""["'](retire\.[A-Za-z]+(?:\.[A-Za-z]+)?)["']""", source))
        used |= {f"retire.cat.{c}" for c in set(retire.CATEGORY.values()) | {"other"}}
        used |= {f"retire.kind.{k}" for k in retire.LEVELS} | {f"retire.place.title{k.title()}" for k in retire.LEVELS}
        used.discard("retire.place.title")  # the start of retire.place.titleZone / titleDistrict / titleArea
        self.assertEqual(sorted(used - set(TEXT)), [])


if __name__ == "__main__":
    unittest.main()
