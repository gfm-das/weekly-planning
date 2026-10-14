"""Delete retired against a disposable roster_management_test_* copy of Beta with migrations 046 to 048 (never live).

Same rules as test_data_uploads.py, whose set-up it reuses: the import of test_management stops everything unless
MANAGEMENT_TEST_DATABASE names a roster_management_test_* database on the pinned test host. Made-up names only. The backup step
is replaced by a stand-in (backups.set_maker): no pg_dump runs in these tests.
NOT run in round 13 (no database in the overnight sandbox): run it on the throw-away copy before migration 048 goes live
(roster-importer/README.md, Testing). Test 20 is the one to read first: it is the whole flow, merge and Undo included.

Checks: a delete is refused while the place is open, while someone serves there, without the typed name, without a successor
when plans or people are attached, and when the backup fails (nothing changes, no batch); a merge moves the people and the
place's own settings onto the successor; the batch names the backup; Undo puts everything back; a retired question is deleted
with its choices and rules and comes back with Undo; a locked or active question is refused (also by the database); the old
shared password may not delete.
"""
import time
import unittest

import psycopg2.errors

import tests.test_management as tm  # the module, not the class: its own tests must not run twice

import app  # noqa: E402  (after test_management, which checks the database first)
import backups  # noqa: E402
import database  # noqa: E402

PREFIX = "TEST-RETIRE"


def management_tests():
    return tm.ManagementIntegrationTests


class FakeBackup:
    """Stands in for pg_dump: writes nothing, names a file, can be told to fail."""

    def __init__(self, fail=False):
        self.fail, self.labels = fail, []

    def make(self, label):
        self.labels.append(label)
        if self.fail:
            raise backups.BackupError("disk full (test)")
        return backups.Backup("gfm-before-delete-test.dump", "/backups/gfm-before-delete-test.dump", 123, True)


class RetireTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        management_tests().setUpClass.__func__(cls)

    tearDownClass = classmethod(management_tests().tearDownClass.__func__)
    scalar = management_tests().scalar
    role_person, remove_person = management_tests().role_person, management_tests().remove_person

    def setUp(self):
        management_tests().setUp(self)
        self.maker = FakeBackup()
        backups.set_maker(self.maker)
        self.addCleanup(backups.set_maker, None)
        self.addCleanup(self.wipe)
        self.wipe()
        self.ap = self.role_person("TEST-RETIRE-AP", leaders=["AP"])
        self.addCleanup(self.remove_person, self.ap)
        self.admin = management_tests().admin_client(self, self.ap, "AP")
        with database.connect() as conn:
            with database.cursor(conn) as cur:
                cur.execute("insert into public.zones(mission_id,name,active) values(2,%s,true) returning id", (PREFIX + " Zone",))
                self.zone = cur.fetchone()["id"]
                cur.execute("insert into public.districts(zone_id,name,active) values(%s,%s,true) returning id", (self.zone, PREFIX + " District"))
                self.district = cur.fetchone()["id"]
                ids = []
                for name, active in ((PREFIX + " Old", False), (PREFIX + " New", True)):
                    cur.execute("insert into public.areas(district_id,name,active) values(%s,%s,%s) returning id", (self.district, name, active))
                    ids.append(cur.fetchone()["id"])
                self.old, self.new = ids
                cur.execute("""insert into public.new_members(area_id,first_name,display_name,baptism_date)
                  values(%s,'Retire','Retire Person',current_date - 30) returning id""", (self.old,))
                self.person = cur.fetchone()["id"]
                cur.execute("insert into public.area_profiles(area_id,population) values(%s,1234)", (self.old,))

    def wipe(self):
        with database.connect() as conn:
            with conn.cursor() as cur:
                cur.execute("delete from public.roster_import_changes where batch_id in (select id from public.roster_import_batches where kind='RETIRE')")
                cur.execute("delete from public.roster_import_batches where kind='RETIRE'")
                cur.execute("delete from public.new_members where display_name='Retire Person'")
                cur.execute("delete from public.area_profiles where area_id in (select id from public.areas where name like %s)", (PREFIX + "%",))
                cur.execute("delete from public.areas where name like %s", (PREFIX + "%",))
                cur.execute("delete from public.districts where name like %s", (PREFIX + "%",))
                cur.execute("delete from public.zones where name like %s", (PREFIX + "%",))
                cur.execute("delete from public.planning_question_visibility_rules where child_question_key like 'test_retire_%' or parent_question_key like 'test_retire_%'")
                cur.execute("select set_config('planning_catalog.allow_delete','on',true)")
                cur.execute("delete from public.planning_question_options where question_id in (select id from public.planning_questions where question_key like 'test_retire_%')")
                cur.execute("delete from public.planning_questions where question_key like 'test_retire_%'")

    def post_place(self, place, typed=None, into=None, client=None):
        return (client or self.admin).post(f"/retire/place/area/{place}/delete", data={
            "csrf_token": "test-csrf", "typed": PREFIX + " Old" if typed is None else typed, "into": into or ""})

    def old_exists(self):
        return self.scalar("select count(*) from public.areas where id=%s", (self.old,))

    # ------------------------------------------------------------------------------------------ places
    def test_01_the_list_shows_the_closed_area_and_the_review_shows_what_is_attached(self):
        self.assertIn(PREFIX + " Old", self.admin.get("/retire").get_data(as_text=True))
        page = self.admin.get(f"/retire/place/area/{self.old}").get_data(as_text=True)
        self.assertIn("People and assignments", page)
        self.assertIn("Choose below where it moves to", page)

    def test_02_an_open_area_is_refused(self):
        response = self.admin.get(f"/retire/place/area/{self.new}")
        self.assertIn("still open", response.get_data(as_text=True))
        refused = self.post_place(self.new, typed=PREFIX + " New")
        self.assertEqual(refused.status_code, 409)
        self.assertEqual(self.scalar("select count(*) from public.areas where id=%s", (self.new,)), 1)

    def test_03_people_must_move_first_and_nothing_changes_without_the_typed_name(self):
        self.assertEqual(self.post_place(self.old).status_code, 409)  # no successor chosen
        self.assertIn("Choose below where it moves to", self.post_place(self.old).get_data(as_text=True))
        self.assertEqual(self.post_place(self.old, typed="wrong", into=self.new).status_code, 409)
        self.assertEqual(self.old_exists(), 1)
        self.assertEqual(self.maker.labels, [])  # no backup was made for a refused delete

    def test_04_a_failing_backup_stops_everything(self):
        self.maker.fail = True
        response = self.post_place(self.old, into=self.new)
        self.assertEqual(response.status_code, 409)
        self.assertIn("nothing was deleted", response.get_data(as_text=True))
        self.assertEqual(self.old_exists(), 1)
        self.assertEqual(self.scalar("select count(*) from public.roster_import_batches where kind='RETIRE'"), 0)

    def test_05_someone_serving_there_blocks_the_delete(self):
        serving = self.role_person("TEST-RETIRE-SERVING", area={"id": self.old, "name": PREFIX + " Old"})
        self.addCleanup(self.remove_person, serving)
        self.assertIn("serve here now", self.admin.get(f"/retire/place/area/{self.old}").get_data(as_text=True))
        self.assertEqual(self.post_place(self.old, into=self.new).status_code, 409)
        self.assertEqual(self.old_exists(), 1)

    def test_06_the_old_shared_password_may_not_delete(self):
        client = app.app.test_client()
        with client.session_transaction() as data:
            data.update(authenticated=True, csrf_token="test-csrf")
        self.assertIn(client.get("/retire").status_code, (302, 403))
        self.assertIn(self.post_place(self.old, into=self.new, client=client).status_code, (302, 403))
        self.assertEqual(self.old_exists(), 1)

    def test_20_merge_delete_and_undo(self):
        response = self.post_place(self.old, into=self.new)
        self.assertEqual(response.status_code, 302, response.get_data(as_text=True)[:600])
        batch = response.headers["Location"].rsplit("/", 1)[-1]
        self.assertEqual(self.old_exists(), 0)
        self.assertEqual(self.scalar("select area_id from public.new_members where id=%s", (self.person,)), self.new)
        self.assertEqual(self.scalar("select population from public.area_profiles where area_id=%s", (self.new,)), 1234)  # settings moved
        self.assertEqual(self.scalar("select summary->>'backup' from public.roster_import_batches where id=%s", (batch,)),
                         "gfm-before-delete-test.dump")
        self.assertEqual(self.scalar("select kind from public.roster_import_batches where id=%s", (batch,)), "RETIRE")
        self.assertIn("gfm-before-delete-test.dump", self.admin.get(f"/imports/{batch}").get_data(as_text=True))
        undone = self.admin.post(f"/imports/{batch}/undo", data={"csrf_token": "test-csrf", "confirmation": "UNDO"})
        self.assertEqual(undone.status_code, 302, undone.get_data(as_text=True)[:600])
        self.assertEqual(self.old_exists(), 1)
        self.assertEqual(self.scalar("select area_id from public.new_members where id=%s", (self.person,)), self.old)
        self.assertEqual(self.scalar("select population from public.area_profiles where area_id=%s", (self.old,)), 1234)
        self.assertEqual(self.scalar("select count(*) from public.area_profiles where area_id=%s", (self.new,)), 0)

    def test_21_a_row_changed_after_the_delete_blocks_undo_and_changes_nothing(self):
        batch = self.post_place(self.old, into=self.new).headers["Location"].rsplit("/", 1)[-1]
        with database.connect() as conn:
            with conn.cursor() as cur:
                cur.execute("update public.new_members set first_name='Edited' where id=%s", (self.person,))
        undone = self.admin.post(f"/imports/{batch}/undo", data={"csrf_token": "test-csrf", "confirmation": "UNDO"})
        self.assertEqual(undone.status_code, 409)
        self.assertEqual(self.old_exists(), 0)

    def test_22_an_area_with_nothing_attached_but_its_settings_is_deleted_without_a_successor(self):
        with database.connect() as conn:
            with conn.cursor() as cur:
                cur.execute("delete from public.new_members where id=%s", (self.person,))
        response = self.post_place(self.old)
        self.assertEqual(response.status_code, 302, response.get_data(as_text=True)[:600])
        self.assertEqual(self.old_exists(), 0)
        self.assertEqual(self.scalar("select count(*) from public.area_profiles where area_id=%s", (self.old,)), 0)
        batch = response.headers["Location"].rsplit("/", 1)[-1]
        self.admin.post(f"/imports/{batch}/undo", data={"csrf_token": "test-csrf", "confirmation": "UNDO"})
        self.assertEqual(self.scalar("select count(*) from public.area_profiles where area_id=%s", (self.old,)), 1)

    # ------------------------------------------------------------------------------------------ questions
    def make_question(self, key, active=False, protected=False):
        with database.connect() as conn:
            with database.cursor(conn) as cur:
                cur.execute("select id from public.planning_question_sections order by id limit 1")
                section = cur.fetchone()["id"]
                cur.execute("""insert into public.planning_questions(section_id,question_key,question_label,question_type,active,protected)
                  values(%s,%s,'Test retire question','SELECT',%s,%s) returning id""", (section, key, active, protected))
                question = cur.fetchone()["id"]
                cur.execute("insert into public.planning_question_options(question_id,option_value,option_label) values(%s,'yes','Yes'),(%s,'no','No')",
                            (question, question))
        return question

    def post_question(self, key, typed=None, into="", drop=""):
        return self.admin.post(f"/retire/question/{key}/delete", data={
            "csrf_token": "test-csrf", "typed": key if typed is None else typed, "into": into, "drop": drop})

    def test_30_a_retired_question_is_deleted_with_its_choices_and_comes_back_with_undo(self):
        question = self.make_question("test_retire_one")
        response = self.post_question("test_retire_one")
        self.assertEqual(response.status_code, 302, response.get_data(as_text=True)[:600])
        self.assertEqual(self.scalar("select count(*) from public.planning_questions where question_key='test_retire_one'"), 0)
        self.assertEqual(self.scalar("select count(*) from public.planning_question_options where question_id=%s", (question,)), 0)
        batch = response.headers["Location"].rsplit("/", 1)[-1]
        self.assertEqual(self.scalar("select summary->>'backup' from public.roster_import_batches where id=%s", (batch,)),
                         "gfm-before-delete-test.dump")
        self.admin.post(f"/imports/{batch}/undo", data={"csrf_token": "test-csrf", "confirmation": "UNDO"})
        self.assertEqual(self.scalar("select count(*) from public.planning_questions where question_key='test_retire_one'"), 1)
        self.assertEqual(self.scalar("select count(*) from public.planning_question_options where question_id=%s", (question,)), 2)

    def test_31_an_active_or_locked_question_is_refused_here_and_by_the_database(self):
        self.make_question("test_retire_active", active=True)
        self.assertEqual(self.post_question("test_retire_active").status_code, 409)
        locked = self.scalar("select question_key from public.planning_questions where protected limit 1")
        self.assertEqual(self.post_question(locked).status_code, 409)
        # The database itself: without the setting nobody can delete a question; with it, still not an active one.
        with database.connect() as conn:
            with conn.cursor() as cur:
                with self.assertRaises(psycopg2.errors.RaiseException):
                    cur.execute("delete from public.planning_questions where question_key='test_retire_active'")
            conn.rollback()
            with conn.cursor() as cur:
                cur.execute("select set_config('planning_catalog.allow_delete','on',true)")
                with self.assertRaises(psycopg2.errors.RaiseException):
                    cur.execute("delete from public.planning_questions where question_key='test_retire_active'")
            conn.rollback()

    def test_32_the_wrong_typed_key_changes_nothing(self):
        self.make_question("test_retire_typed")
        self.assertEqual(self.post_question("test_retire_typed", typed="nope").status_code, 409)
        self.assertEqual(self.scalar("select count(*) from public.planning_questions where question_key='test_retire_typed'"), 1)


if __name__ == "__main__":
    unittest.main()
