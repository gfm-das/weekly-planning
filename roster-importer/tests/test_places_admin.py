"""DA Management > Places against a disposable roster_management_test_* copy of Beta with migration 040 (never live).

Same rules as test_management.py (see the Testing part of the README). Made-up places only (zones "Zzz ..."), removed
after every test. Checks: closing a zone or a district needs a destination for everything open inside it and keeps those
places open; the last open zone cannot be closed; nothing moves into a closed place; reopening is possible and respects
the order (zone, district, area); an area with missionaries needs a tick; every change is one entry in Import history and
Undo puts it back; and a roster upload wins (it reopens a place it names).
"""
import os
import unittest
from urllib.parse import urlsplit, urlunsplit

test_db = os.environ.get("MANAGEMENT_TEST_DATABASE", "")
if not test_db.startswith("roster_management_test_"):
    raise RuntimeError("A disposable roster_management_test_* database is required.")
parts = urlsplit(os.environ["DATABASE_URL"])
if parts.hostname != "gfm-beta-supabase-db-1":
    raise RuntimeError("These tests may run only against the pinned Beta database host.")
os.environ["DATABASE_URL"] = urlunsplit(parts._replace(path="/" + test_db))

from flask import session  # noqa: E402

import app  # noqa: E402
import database  # noqa: E402
import places_admin  # noqa: E402
import transfer  # noqa: E402
import undo  # noqa: E402


class PlacesTests(unittest.TestCase):
    def setUp(self):
        app.app.config["TESTING"] = True
        self.cleanup()
        self.addCleanup(self.cleanup)
        with database.connect() as conn:
            with database.cursor(conn) as cur:
                self.z1, self.z2 = (self.add(cur, "zones", "mission_id", 2, f"Zzz Zone {n}") for n in (1, 2))
                self.d1 = self.add(cur, "districts", "zone_id", self.z1, "Zzz District 1")
                self.d2 = self.add(cur, "districts", "zone_id", self.z2, "Zzz District 2")
                self.a1, self.a2 = (self.add(cur, "areas", "district_id", self.d1, f"Zzz Area {n}") for n in (1, 2))
                self.a3 = self.add(cur, "areas", "district_id", self.d2, "Zzz Area 3")

    @staticmethod
    def add(cur, table, column, parent, name):
        cur.execute(f"insert into public.{table}({column},name,active) values(%s,%s,true) returning id", (parent, name))
        return cur.fetchone()["id"]

    def cleanup(self):
        with database.connect() as conn:
            with database.cursor(conn) as cur:
                cur.execute("delete from public.roster_import_changes where batch_id in (select id from public.roster_import_batches where kind='PLACES')")
                cur.execute("delete from public.roster_import_batches where kind='PLACES'")
                cur.execute("delete from public.areas where name like 'Zzz %'")
                cur.execute("delete from public.districts where name like 'Zzz %'")
                cur.execute("delete from public.zones where name like 'Zzz %'")
                cur.execute("update public.zones set active=true where mission_id=2 and name not in ('Kaiserslautern')")

    def change(self, level, place_id, action, moves=None, confirmed=False):
        conn = database.connect()
        try:
            with app.app.test_request_context("/"):
                session.update(portal_mission_id=2, portal_user="Integration test")
                batch = places_admin.change_place(conn, level, place_id, action, moves, confirmed)
            conn.commit()
            return batch
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def undo(self, batch):
        with app.app.test_request_context("/"):
            session.update(portal_mission_id=2, portal_user="Integration test")
            undo.undo_batch(str(batch))

    def row(self, table, place_id):
        with database.connect() as conn:
            with database.cursor(conn) as cur:
                cur.execute(f"select * from public.{table} where id=%s", (place_id,))
                return cur.fetchone()

    # ------------------------------------------------------------------------------------------ tests

    def test_01_closing_a_zone_needs_a_destination_for_each_open_district(self):
        with self.assertRaises(ValueError) as caught:
            self.change("zone", self.z1, "close")
        self.assertIn("Zzz District 1", str(caught.exception))
        self.assertTrue(self.row("zones", self.z1)["active"])
        with self.assertRaises(ValueError):  # a zone cannot send its district to itself
            self.change("zone", self.z1, "close", {str(self.d1): str(self.z1)})
        batch = self.change("zone", self.z1, "close", {str(self.d1): str(self.z2)})
        self.assertFalse(self.row("zones", self.z1)["active"])
        self.assertEqual(self.row("districts", self.d1)["zone_id"], self.z2)
        self.assertTrue(self.row("districts", self.d1)["active"], "the district inside stays open")
        self.assertTrue(self.row("areas", self.a1)["active"])
        self.undo(batch)  # Undo puts the zone and the district back
        self.assertTrue(self.row("zones", self.z1)["active"])
        self.assertEqual(self.row("districts", self.d1)["zone_id"], self.z1)

    def test_02_the_last_open_zone_cannot_be_closed(self):
        with database.connect() as conn:
            with database.cursor(conn) as cur:
                cur.execute("update public.zones set active=false where mission_id=2 and id<>%s", (self.z1,))
        with self.assertRaises(ValueError) as caught:
            self.change("zone", self.z1, "close")
        self.assertIn("last open zone", str(caught.exception))

    def test_03_closing_a_district_moves_its_open_areas(self):
        with self.assertRaises(ValueError):
            self.change("district", self.d1, "close", {str(self.a1): str(self.d2)})  # a2 has no destination
        batch = self.change("district", self.d1, "close", {str(self.a1): str(self.d2), str(self.a2): str(self.d2)})
        self.assertFalse(self.row("districts", self.d1)["active"])
        self.assertEqual({self.row("areas", a)["district_id"] for a in (self.a1, self.a2)}, {self.d2})
        self.assertTrue(self.row("areas", self.a1)["active"], "the areas stay open")
        self.undo(batch)
        self.assertEqual(self.row("areas", self.a1)["district_id"], self.d1)
        self.assertTrue(self.row("districts", self.d1)["active"])

    def test_04_nothing_moves_into_a_closed_place(self):
        self.change("district", self.d2, "close", {str(self.a3): str(self.d1)})
        with self.assertRaises(ValueError):  # d2 is closed now
            self.change("district", self.d1, "close", {str(self.a1): str(self.d2), str(self.a2): str(self.d2)})

    def test_05_reopening_works_and_an_open_place_cannot_be_reopened(self):
        with self.assertRaises(ValueError):
            self.change("area", self.a1, "reopen")  # it is open already
        batch = self.change("area", self.a1, "close")
        self.assertFalse(self.row("areas", self.a1)["active"])
        self.change("area", self.a1, "reopen")
        self.assertTrue(self.row("areas", self.a1)["active"])

    def test_06_a_district_cannot_reopen_inside_a_closed_zone(self):
        self.change("district", self.d1, "close", {str(self.a1): str(self.d2), str(self.a2): str(self.d2)})
        self.change("zone", self.z1, "close")
        with self.assertRaises(ValueError) as caught:
            self.change("district", self.d1, "reopen")
        self.assertIn("Reopen the zone", str(caught.exception))
        self.change("zone", self.z1, "reopen")
        self.change("district", self.d1, "reopen")
        self.assertTrue(self.row("districts", self.d1)["active"])

    def test_07_an_area_with_missionaries_needs_a_tick(self):
        with database.connect() as conn:
            with database.cursor(conn) as cur:
                cur.execute("select place_id from (select a.id place_id from public.areas a join public.missionary_assignments ma on ma.area_id=a.id "
                            "join public.missionaries m on m.id=ma.missionary_id where a.active and (ma.end_date is null or ma.end_date>=current_date) "
                            "and m.status='Active' limit 1) x")
                area = cur.fetchone()["place_id"]
        with self.assertRaises(ValueError) as caught:
            self.change("area", area, "close")
        self.assertIn("serve", str(caught.exception))
        batch = self.change("area", area, "close", confirmed=True)
        self.assertFalse(self.row("areas", area)["active"])
        self.undo(batch)
        self.assertTrue(self.row("areas", area)["active"])

    def test_08_a_name_clash_is_explained_and_nothing_is_saved(self):
        with database.connect() as conn:
            with database.cursor(conn) as cur:
                self.add(cur, "areas", "district_id", self.d2, "Zzz Area 1")  # the same name as a1, in the destination
        with self.assertRaises(ValueError) as caught:
            self.change("district", self.d1, "close", {str(self.a1): str(self.d2), str(self.a2): str(self.d2)})
        self.assertIn("same name", str(caught.exception))
        self.assertTrue(self.row("districts", self.d1)["active"])
        self.assertEqual(self.row("areas", self.a2)["district_id"], self.d1, "all or nothing")

    def test_09_every_change_is_in_import_history(self):
        batch = self.change("area", self.a1, "close")
        with database.connect() as conn:
            with database.cursor(conn) as cur:
                cur.execute("select kind,filename,status,summary from public.roster_import_batches where id=%s", (batch,))
                row = cur.fetchone()
                cur.execute("select count(*) n from public.roster_import_changes where batch_id=%s", (batch,))
                changes = cur.fetchone()["n"]
        self.assertEqual((row["kind"], row["status"], changes), ("PLACES", "APPLIED", 1))
        self.assertIn("Close area Zzz Area 1", row["filename"])

    def test_10_the_page_and_the_form(self):
        client = app.app.test_client()
        with client.session_transaction() as s:
            s.update(authenticated=True, portal_mission_id=2, portal_user="Integration test", csrf_token="test-csrf")
        page = client.get("/places")
        self.assertEqual(page.status_code, 200)
        text = page.get_data(as_text=True)
        self.assertIn("Zzz Zone 1", text)
        self.assertIn("Close zone", text)
        refused = client.post("/places/change", data={"csrf_token": "test-csrf", "level": "zone", "id": self.z1, "action": "close"})
        self.assertEqual(refused.status_code, 400)
        self.assertIn("Choose where", refused.get_data(as_text=True))
        done = client.post("/places/change", data={"csrf_token": "test-csrf", "level": "zone", "id": self.z1, "action": "close",
                                                   f"move::{self.d1}": self.z2})
        self.assertEqual(done.status_code, 302)
        self.assertFalse(self.row("zones", self.z1)["active"])
        self.assertEqual(app.app.test_client().get("/places").status_code, 302)  # signed out: sent to the login

    def test_11_a_roster_upload_wins_it_reopens_a_place_it_names(self):
        self.change("area", self.a1, "close")
        with database.connect() as conn:
            with database.cursor(conn) as cur:
                transfer.find_or_add(cur, "areas", "district_id", self.d1, "Zzz Area 1")
        self.assertTrue(self.row("areas", self.a1)["active"])


if __name__ == "__main__":
    unittest.main()
