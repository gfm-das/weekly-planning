"""The Vollzogen upload against a disposable roster_management_test_* copy of Beta with migration 051 (never live).

Same rules as test_people_uploads.py, whose set-up it reuses (its import stops everything unless MANAGEMENT_TEST_DATABASE names
a roster_management_test_* database on the pinned test host, and this file refuses on its own unless the database name
contains "test"). Made-up people only. NOT run in round 13 (no database in the overnight sandbox): run it on the throw-away copy
before migration 051 goes live.

Checks: the sheet is saved as one batch with before/after rows and Undo takes everything back; the same sheet again is "nothing
new"; a person is linked by FC number or by name and zone, the portal's person row is not touched; a name with nothing to back it
up is asked, Apply stays closed until it is answered and the answer is remembered; the dashboards view counts without names;
the reader sees the view but not the table; a ZL is refused.
"""
import io
import os
import unittest
from datetime import date

import psycopg2.errors

if "test" not in os.environ.get("MANAGEMENT_TEST_DATABASE", "") and "test" not in os.environ.get("DATABASE_URL", ""):
    raise RuntimeError("These tests need a throw-away database whose name contains 'test'.")

import app  # noqa: E402  (after test_people_uploads' import, which checks the database first)
import database  # noqa: E402
from tests import data_samples as samples  # noqa: E402
from tests.test_people_uploads import PeopleBase  # noqa: E402 (the base class has no tests of its own)


class VollzogenTests(PeopleBase):
    def setUp(self):
        super().setUp()
        self.wipe_vollzogen()
        self.addCleanup(self.wipe_vollzogen)
        self.client = app.app.test_client()
        with self.client.session_transaction() as session_data:
            session_data.update(authenticated=True, portal_mission_id=2, portal_user="Integration test", csrf_token="test-csrf")
        self.zone = self.rows("""select z.name from public.areas a join public.districts d on d.id=a.district_id
          join public.zones z on z.id=d.zone_id where a.id=%s""", (self.area["id"],))[0]["name"]

    def wipe_vollzogen(self):
        with database.connect() as conn:
            with conn.cursor() as cur:
                cur.execute("delete from public.roster_import_batches where kind='VOLLZOGEN'")
                cur.execute("delete from public.vollzogen_records")

    # -- helpers -----------------------------------------------------------------------------------------------
    def sheet(self, rows):
        return samples.csv_bytes(["Wie gefunden", "Name", "Wann gesetzt", "Taufdatum", "Mitarbeiter", "Gemeinde", "Pfahl", "Zone",
                                  "Konfirmiert", "Country", "Gender", "Preferred Language", "FC number"], rows)

    def post_file(self, data, name="vollzogen.csv"):
        response = self.client.post("/uploads/vollzogen/preview", content_type="multipart/form-data",
                                    data={"csrf_token": "test-csrf", "file": (io.BytesIO(data), name)})
        self.assertEqual(response.status_code, 302, response.get_data(as_text=True)[:500])
        review = self.client.get("/uploads/vollzogen/review")
        self.assertEqual(review.status_code, 200)
        return review.get_data(as_text=True)

    def apply(self):
        return self.client.post("/uploads/vollzogen/apply", data={"csrf_token": "test-csrf", "confirmed": "yes"})

    def batch_of(self, response):
        self.assertEqual(response.status_code, 302, response.get_data(as_text=True)[:800])
        return response.headers["Location"].rsplit("/", 1)[-1]

    def undo(self, batch):
        return self.client.post(f"/imports/{batch}/undo", data={"csrf_token": "test-csrf", "confirmation": "UNDO"})

    def stored(self):
        return self.rows("select * from public.vollzogen_records order by full_name")

    def member(self, name, fc=None, day=date(2025, 12, 15)):
        with database.connect() as conn:
            with conn.cursor() as cur:
                cur.execute("""insert into public.new_members(area_id,first_name,last_name,display_name,baptism_date,fc_number)
                  values(%s,%s,%s,%s,%s,%s) returning id""", (self.area["id"], name.split()[0], name.split()[-1], name, day, fc))
                member_id = cur.fetchone()[0]
                cur.execute("insert into public.new_member_area_assignments(new_member_id,area_id,start_date) values(%s,%s,%s)",
                            (member_id, self.area["id"], day))
        return member_id

    # -- tests -------------------------------------------------------------------------------------------------
    def test_01_pages_open_for_managers_only(self):
        guest = app.app.test_client()
        for path in ["/uploads/vollzogen", "/uploads/vollzogen/table", "/uploads/vollzogen/template"]:
            self.assertEqual(guest.get(path).status_code, 302, path)
            self.assertEqual(self.client.get(path).status_code, 200, path)
        self.assertIn("Vollzogen", self.client.get("/uploads").get_data(as_text=True))

    def test_02_the_sheet_is_saved_as_one_batch_and_undo_takes_it_back(self):
        page = self.post_file(samples.vollzogen_csv(self.zone))
        self.assertIn("People: 6 new", page)
        batch = self.batch_of(self.apply())
        found = {r["full_name"]: r for r in self.stored()}
        self.assertEqual(len(found), 6)
        testa = found["Testa Beispiel"]
        self.assertEqual((str(testa["baptism_date"]), str(testa["baptismal_date_set_on"]), testa["confirmed"], testa["unit"], testa["country"]),
                         ("2025-12-15", "2025-12-01", True, "Frankfurt 1st", "Testland"))
        self.assertEqual(str(found["Probe Person"]["confirmed_on"]), "2026-01-11")
        self.assertEqual(self.rows("select kind,status from public.roster_import_batches where id=%s", (batch,))[0]["kind"], "VOLLZOGEN")
        self.assertEqual(self.count("roster_import_changes", "batch_id=%s and table_name='vollzogen_records'", (batch,)), 6)
        # The same sheet again: nothing new.
        self.post_file(samples.vollzogen_csv(self.zone))
        again = self.apply()
        self.assertEqual(again.status_code, 302)
        self.assertEqual(again.headers["Location"], "/uploads/vollzogen")
        self.assertEqual(self.undo(batch).status_code, 302)
        self.assertEqual(self.stored(), [])
        self.assertEqual(self.rows("select status from public.roster_import_batches where id=%s", (batch,))[0]["status"], "UNDONE")

    def test_03_a_person_is_linked_by_fc_number_or_by_name_and_zone_without_touching_the_portal_person(self):
        by_fc = self.member("Fiona Fcperson", fc="1234567")
        by_name = self.member("Nina Namensgleich")
        before = self.rows("select * from public.new_members where id=any(%s) order by id", ([by_fc, by_name],))
        self.post_file(self.sheet([["Street", "Fiona Anders Geschrieben", "", "9/20/2025", "", "", "", "Elsewhere", "X", "", "", "", "FC-1234567"],
                                   ["Street", "Nina Namensgleich", "", "12/15/2025", "", "", "", self.zone, "", "", "", "", ""]]))
        self.batch_of(self.apply())
        links = {r["full_name"]: (r["new_member_id"], r["matched_how"]) for r in self.stored()}
        self.assertEqual(links["Fiona Anders Geschrieben"], (by_fc, "FC"))
        self.assertEqual(links["Nina Namensgleich"], (by_name, "NAME"))
        self.assertEqual(self.rows("select * from public.new_members where id=any(%s) order by id", ([by_fc, by_name],)), before)

    def test_04_a_name_with_nothing_to_back_it_up_is_asked_and_the_answer_is_remembered(self):
        member = self.member("Mira Fragezeichen", day=None)
        page = self.post_file(self.sheet([["Street", "Mira Fragezeichen", "", "12/15/2025", "", "", "", "Faraway Zone", "", "", "", "", ""]]))
        self.assertIn("pair(s) to check", page)
        self.assertNotIn("Apply</button>", page)
        closed = self.apply()
        self.assertEqual(closed.status_code, 409)
        self.assertEqual(self.stored(), [])
        key = f"p:nm:vz:mira fragezeichen:2025-12-15"
        answer = self.client.post("/people/decide", data={"csrf_token": "test-csrf", "back": "/uploads/vollzogen/review",
                                                         f"decide::id:nm:{member}|{key}": "same"})
        self.assertEqual(answer.status_code, 302)
        self.assertNotIn("pair(s) to check", self.client.get("/uploads/vollzogen/review").get_data(as_text=True))
        self.batch_of(self.apply())
        self.assertEqual([(r["new_member_id"], r["matched_how"]) for r in self.stored()], [(member, "ASKED")])

    def test_05_the_dashboards_view_counts_without_names_and_the_reader_cannot_read_the_table(self):
        self.post_file(samples.vollzogen_csv(self.zone))
        self.batch_of(self.apply())
        with database.connect() as conn:
            with database.cursor(conn) as cur:
                cur.execute("set local role gfm_dashboard_reader")
                cur.execute("select sum(baptisms) b, sum(confirmed) c from dashboards.vollzogen_week")
                total = cur.fetchone()
                self.assertEqual((total["b"], total["c"]), (6, 3))
                cur.execute("select column_name from information_schema.columns where table_schema='dashboards' and table_name='vollzogen_week'")
                self.assertNotIn("full_name", {r["column_name"] for r in cur.fetchall()})
                cur.execute("savepoint s")
                with self.assertRaises(psycopg2.errors.InsufficientPrivilege):
                    cur.execute("select count(*) from public.vollzogen_records")
            conn.rollback()

    def test_06_the_database_refuses_a_bad_fc_number_and_a_baptism_date_before_2000(self):
        with database.connect() as conn:
            with conn.cursor() as cur:
                with self.assertRaises(psycopg2.errors.CheckViolation):
                    cur.execute("""insert into public.vollzogen_records(mission_id,record_key,full_name,baptism_date,fc_number)
                      values(2,'x|2025-01-01','X Y','2025-01-01','not a number!')""")
            conn.rollback()
            with conn.cursor() as cur:
                with self.assertRaises(psycopg2.errors.CheckViolation):
                    cur.execute("""insert into public.vollzogen_records(mission_id,record_key,full_name,baptism_date)
                      values(2,'x|1999-01-01','X Y','1999-01-01')""")
            conn.rollback()

    def test_07_a_zl_is_refused(self):
        import tests.test_management as tm
        zl = tm.ManagementIntegrationTests.role_person(self, "TEST-VZ-ZL", leaders=["ZL"])
        try:
            client = tm.ManagementIntegrationTests.admin_client(self, zl, "ZL")
            self.assertEqual(client.get("/uploads/vollzogen").status_code, 302)  # refused: sent to the sign-in
        finally:
            tm.ManagementIntegrationTests.remove_person(self, zl)


if __name__ == "__main__":
    unittest.main()
