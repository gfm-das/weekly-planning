"""Role abilities against a THROWAWAY copy of the mission database that has migration 055 applied. NOT run in round 13 (no database
in the overnight sandbox): run it on the throw-away copy.

It saves, reverts and tries to break the table, so it refuses to run unless DATABASE_URL names a database whose name contains "test"
(never the live host) and ABIL_TEST_THROWAWAY=yes. It puts every switch back to the built-in value at the end (the log keeps the
rows: use a copy).

Run in a temporary roster-importer container on the test network (like test_unlock_db.py):
  docker run --rm --network gfm-test-r2-net -v <worktree>/roster-importer:/app -w /app \
    -e DATABASE_URL=postgresql://postgres:<password>@gfm-test-r2-db:5432/gfm_test_abil_1 -e ABIL_TEST_THROWAWAY=yes \
    roster-importer-roster-importer python -m unittest tests/test_abilities_db.py -v

Checks: the seed is the built-in matrix (40 rows); a save changes the switch, writes one log row with who, when, before, after and the
note; a revert puts it back and cannot be repeated; a stale base or a stale revert is refused; the database itself refuses a manager
switched off, a missionary switched on, a fixed cell changed, a delete, an update without a change batch, and any change of the log;
the page flow works end to end for a manager and is 403 for Office.
"""
import os
import time
import unittest
import uuid
from unittest.mock import patch
from urllib.parse import urlsplit

import psycopg2

parts = urlsplit(os.environ.get("DATABASE_URL", ""))
if (os.environ.get("ABIL_TEST_THROWAWAY") != "yes" or "test" not in parts.path
        or parts.hostname == "gfm-beta-supabase-db-1"):
    raise RuntimeError("A throwaway *test* database (not the live host) and ABIL_TEST_THROWAWAY=yes are required.")

import abilities  # noqa: E402
import app  # noqa: E402
import database  # noqa: E402
import roles  # noqa: E402

WHO = ("Test Person", str(uuid.uuid4()))
CELL = ("OFFICE", "vollzogen.view")


def raw():
    return psycopg2.connect(os.environ["DATABASE_URL"])


def current():
    with database.connect() as conn:
        with database.cursor(conn) as cur:
            return abilities.read_table(cur)


class Base(unittest.TestCase):
    def setUp(self):
        self.addCleanup(self.restore)
        self.restore()

    def restore(self):
        """Every switch back to the built-in value (through the same path as a save)."""
        table = current()
        wanted = {cell: roles.DEFAULT_ABILITIES[cell] for cell in abilities.SWITCH_CELLS}
        if table is not None and abilities.plan(table, wanted):
            abilities.save_change(wanted, abilities.base_token(table), "test cleanup", WHO)


class Seed(Base):
    def test_the_table_is_the_built_in_matrix(self):
        self.assertEqual(current(), roles.DEFAULT_ABILITIES)

    def test_the_function_and_the_rules_exist(self):
        with raw() as conn, conn.cursor() as cur:
            cur.execute("select count(*) from public.role_abilities")
            self.assertEqual(cur.fetchone()[0], 40)
            cur.execute("select public.role_ability_ok('OFFICE','presentations.use',true), public.role_ability_ok('OFFICE','vollzogen.view',false)")
            self.assertEqual(cur.fetchone(), (False, True))


class SaveAndRevert(Base):
    def test_a_save_writes_the_switch_and_one_log_row(self):
        table = current()
        wanted = {cell: roles.DEFAULT_ABILITIES[cell] for cell in abilities.SWITCH_CELLS}
        wanted[CELL] = False
        status, changes = abilities.save_change(wanted, abilities.base_token(table), "Because of a test", WHO)
        self.assertEqual((status, len(changes)), ("saved", 1))
        self.assertFalse(current()[CELL])
        with database.connect() as conn:
            with database.cursor(conn) as cur:
                log = abilities.read_log(cur)[0]
        self.assertEqual((log["who"], log["note"], log["cells"], log["reverts"], log["reverted"]),
                         (WHO[0], "Because of a test", [(CELL[0], CELL[1], True, False)], None, False))

    def test_a_revert_puts_it_back_once(self):
        table = current()
        wanted = {cell: roles.DEFAULT_ABILITIES[cell] for cell in abilities.SWITCH_CELLS}
        wanted[CELL] = False
        abilities.save_change(wanted, abilities.base_token(table), "", WHO)
        with database.connect() as conn:
            with database.cursor(conn) as cur:
                batch = abilities.read_log(cur)[0]["batch"]
        self.assertEqual(abilities.revert_batch(batch, WHO)[0], "reverted")
        self.assertTrue(current()[CELL])
        self.assertEqual(abilities.revert_batch(batch, WHO)[0], "already")
        with database.connect() as conn:
            with database.cursor(conn) as cur:
                newest = abilities.read_log(cur)
        self.assertEqual(newest[0]["reverts"], batch)
        self.assertTrue(newest[1]["reverted"])

    def test_a_stale_form_and_a_stale_revert_are_refused(self):
        table = current()
        wanted = {cell: roles.DEFAULT_ABILITIES[cell] for cell in abilities.SWITCH_CELLS}
        wanted[CELL] = False
        self.assertEqual(abilities.save_change(wanted, "0" * 11, "", WHO)[0], "stale")
        abilities.save_change(wanted, abilities.base_token(table), "", WHO)
        with database.connect() as conn:
            with database.cursor(conn) as cur:
                batch = abilities.read_log(cur)[0]["batch"]
        again = dict(wanted)
        again[CELL] = True
        abilities.save_change(again, abilities.base_token(current()), "", WHO)  # changed again by hand
        self.assertEqual(abilities.revert_batch(batch, WHO)[0], "stale")

    def test_no_change_and_missing_batch(self):
        table = current()
        wanted = {cell: roles.DEFAULT_ABILITIES[cell] for cell in abilities.SWITCH_CELLS}
        self.assertEqual(abilities.save_change(wanted, abilities.base_token(table), "", WHO)[0], "nochange")
        self.assertEqual(abilities.revert_batch(str(uuid.uuid4()), WHO)[0], "missing")

    def test_roles_py_sees_the_change_at_once_in_the_saving_program(self):
        table = current()
        wanted = {cell: roles.DEFAULT_ABILITIES[cell] for cell in abilities.SWITCH_CELLS}
        wanted[CELL] = False
        abilities.save_change(wanted, abilities.base_token(table), "", WHO)
        self.assertFalse(roles.ability_table()[CELL])
        self.assertTrue(roles.ability_table_is_live())


class TheDatabaseItself(unittest.TestCase):
    """Direct SQL, each in a transaction that is rolled back: the database refuses what the rules forbid."""

    def refused(self, sql, params=(), batch=True):
        conn = raw()
        try:
            with conn.cursor() as cur:
                if batch:
                    cur.execute("select set_config('gfm.change_batch', %s, true)", (str(uuid.uuid4()),))
                with self.assertRaises(psycopg2.Error):
                    cur.execute(sql, params)
        finally:
            conn.rollback()
            conn.close()

    def test_a_manager_cannot_be_switched_off(self):
        for role in ("AP", "PRESIDENT", "DATA_ADMIN"):
            self.refused("update public.role_abilities set allowed=false, changed_by_name='x' where role=%s and ability='calendar.edit'", (role,))

    def test_a_missionary_cannot_be_switched_on(self):
        self.refused("update public.role_abilities set allowed=true, changed_by_name='x' where role='MISSIONARY' and ability='calendar.edit'")

    def test_a_fixed_cell_cannot_change(self):
        for role, ability in (("DL", "calendar.edit"), ("OFFICE", "presentations.use"), ("STL", "plans.unlock"), ("DL", "vollzogen.view")):
            self.refused("update public.role_abilities set allowed=true, changed_by_name='x' where role=%s and ability=%s", (role, ability))

    def test_a_row_cannot_be_deleted_or_renamed(self):
        self.refused("delete from public.role_abilities where role='DL'")
        self.refused("update public.role_abilities set role='KING' where role='DL' and ability='plans.unlock'")
        self.refused("insert into public.role_abilities (role, ability, allowed) values ('OFFICE', 'management', true)")

    def test_a_change_needs_a_batch_and_a_name(self):
        self.refused("update public.role_abilities set allowed=false, changed_by_name='x' where role='OFFICE' and ability='vollzogen.view'", batch=False)
        self.refused("update public.role_abilities set allowed=false where role='OFFICE' and ability='vollzogen.view'")  # still the migration's name

    def test_the_log_is_append_only(self):
        self.refused("update public.role_abilities_log set note='x'")
        self.refused("delete from public.role_abilities_log")

    def test_nobody_but_the_service_connection_can_touch_the_tables(self):
        with raw() as conn, conn.cursor() as cur:
            for role in ("anon", "authenticated", "service_role"):
                for table in ("role_abilities", "role_abilities_log", "ability_catalog"):
                    cur.execute("select has_table_privilege(%s, %s, 'SELECT') or has_table_privilege(%s, %s, 'UPDATE')",
                                (role, f"public.{table}", role, f"public.{table}"))
                    self.assertFalse(cur.fetchone()[0], (role, table))
            cur.execute("select count(*) from pg_policy where polrelid='public.role_abilities'::regclass")
            self.assertEqual(cur.fetchone()[0], 0)


class ThePage(Base):
    def client(self, role):
        client = app.app.test_client()
        with client.session_transaction() as s:
            s.update(authenticated=True, portal_role=role, portal_user=WHO[0], portal_user_id=WHO[1], portal_mission_id=2,
                     portal_expires_at=time.time() + 1800, csrf_token="test-csrf")
        return client

    def test_a_manager_previews_saves_and_reverts(self):
        with patch.object(app.sign_in, "current_management_context", return_value={"user_id": WHO[1], "mission_id": 2, "management_role": "AP"}):
            client = self.client("AP")
            html = client.get("/abilities").get_data(as_text=True)
            self.assertIn("Edit the calendar", html)
            base = abilities.base_token(current())
            ticked = [abilities.cell_key(*c) for c in abilities.SWITCH_CELLS if c != CELL]
            preview = client.post("/abilities/preview", data={"csrf_token": "test-csrf", "on": ticked, "base": base})
            self.assertIn("These people can no longer open the Vollzogen list.", preview.get_data(as_text=True))
            self.assertTrue(current()[CELL])  # a preview changes nothing
            client.post("/abilities/save", data={"csrf_token": "test-csrf", "on": ticked, "base": base, "confirm": "CHANGE", "note": "page test"})
            self.assertFalse(current()[CELL])
            with database.connect() as conn:
                with database.cursor(conn) as cur:
                    batch = abilities.read_log(cur)[0]["batch"]
            client.post(f"/abilities/revert/{batch}", data={"csrf_token": "test-csrf"})
            self.assertTrue(current()[CELL])

    def test_office_is_refused_and_nothing_changes(self):
        with patch.object(app.sign_in, "current_management_context", return_value={"user_id": WHO[1], "mission_id": 2, "management_role": "OFFICE"}):
            client = self.client("OFFICE")
            self.assertEqual(client.get("/abilities").status_code, 403)
            ticked = [abilities.cell_key(*c) for c in abilities.SWITCH_CELLS if c != CELL]
            response = client.post("/abilities/save", data={"csrf_token": "test-csrf", "on": ticked,
                                                            "base": abilities.base_token(current()), "confirm": "CHANGE"})
            self.assertEqual(response.status_code, 403)
            self.assertTrue(current()[CELL])


if __name__ == "__main__":
    unittest.main()
