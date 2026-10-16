"""Geo data uploads against a disposable roster_management_test_* copy of Beta with migration 046 (never live).

Same rules as test_data_uploads.py, whose setup it reuses: the import of test_management stops everything unless
MANAGEMENT_TEST_DATABASE names a roster_management_test_* database on the pinned test host. Made-up figures only.
NOT run in round 13 (no database in the overnight sandbox): run it on the throw-away copy before migration 046 goes live
(roster-importer/README.md, Testing).

Checks: the upload saves figures with source and date, a blank cell keeps what is saved, a new population clears an old
stated density, Undo puts the rows back, the dashboards view and the per-capita view read the figures, the reader sees
the views but not the table, and a ZL is refused.
"""
import io
import os
import unittest

import psycopg2.errors

import tests.test_management as tm  # the module, not the class: its own tests must not run twice

import app  # noqa: E402  (after test_management, which checks the database first)
import database  # noqa: E402
from tests import data_samples as s  # noqa: E402

os.environ.setdefault("PERSON_KEY_SECRET", "test-secret-for-person-codes-only")


def management_tests():
    return tm.ManagementIntegrationTests


def clear_geo():
    with database.connect() as conn:
        with conn.cursor() as cur:
            cur.execute("delete from public.roster_import_batches where kind='GEO_DATA'")
            cur.execute("delete from public.area_geo_data")
            cur.execute("delete from public.zone_geo_data")
            cur.execute("delete from public.district_geo_data")
            cur.execute("delete from public.data_name_matches")


class GeoDataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        management_tests().setUpClass.__func__(cls)
        clear_geo()

    tearDownClass = classmethod(management_tests().tearDownClass.__func__)
    setUp = management_tests().setUp
    scalar = management_tests().scalar
    role_person, remove_person = management_tests().role_person, management_tests().remove_person

    def rows(self, query, params=()):
        with database.connect() as conn:
            with database.cursor(conn) as cur:
                cur.execute(query, params)
                return cur.fetchall()

    def portal_areas(self, count=2):
        return [(r["zone"], r["district"], r["area"]) for r in self.rows("""
          select z.name zone,d.name district,a.name area from public.areas a join public.districts d on d.id=a.district_id
          join public.zones z on z.id=d.zone_id where z.mission_id=2 and a.active
            and (select count(*) from public.areas x where lower(x.name)=lower(a.name))=1
          order by a.id limit %s""", (count,))]

    def upload(self, data, filename="geo.csv"):
        response = self.client.post("/uploads/check", content_type="multipart/form-data",
                                    data={"csrf_token": "test-csrf", "kind": "geo", "file": (io.BytesIO(data), filename)})
        self.assertEqual(response.status_code, 302, response.get_data(as_text=True)[:500])
        page = self.client.get("/uploads/geo/review")
        self.assertEqual(page.status_code, 200)
        return page.get_data(as_text=True)

    def apply(self):
        before = self.scalar("select count(*) from public.roster_import_batches")
        response = self.client.post("/uploads/geo/apply", data={"csrf_token": "test-csrf", "confirmed": "yes"})
        self.assertEqual(response.status_code, 302, response.get_data(as_text=True)[:800])
        if self.scalar("select count(*) from public.roster_import_batches") == before:
            return None
        return str(self.scalar("select id from public.roster_import_batches order by created_at desc limit 1"))

    def undo(self, batch):
        return self.client.post(f"/imports/{batch}/undo", data={"csrf_token": "test-csrf", "confirmation": "UNDO"})

    def test_01_pages_open_for_managers_only(self):
        guest = app.app.test_client()
        for path in ["/uploads", "/uploads/geo/table", "/uploads/geo/template"]:
            self.assertEqual(guest.get(path).status_code, 302, path)
            self.assertEqual(self.client.get(path).status_code, 200, path)
        self.assertIn("Geo data", self.client.get("/uploads").get_data(as_text=True))

    def test_02_upload_blank_keeps_new_population_clears_density_and_undo(self):
        (z1, d1, a1), (z2, d2, a2) = self.portal_areas(2)
        page = self.upload(s.geo_file([(z1, d1, a1, "34.000", "2,5", "13600", "18000", "Test office", "2024-12-31", "yes"),
                                       (z2, d2, a2, "21000", "", "", "", "", "", "")]))
        self.assertIn("1 rows have no source or no data date", page)
        first = self.apply()
        self.assertIsNotNone(first)
        row = self.rows("select * from dashboards.area_geo_data where area=%s", (a1,))[0]
        self.assertEqual((row["population"], float(row["size_km2"]), float(row["density_per_km2"]), row["households"],
                          row["source"], str(row["data_date"]), row["extra"]),
                         (34000, 2.5, 13600.0, 18000, "Test office", "2024-12-31", {"Chapel nearby": "yes"}))
        # A second file: blanks keep, a new population without density clears the stated density (the view works it out).
        self.upload(s.geo_file([(z1, d1, a1, "35000", "", "", "", "", "", "")]))
        second = self.apply()
        row = self.rows("select * from dashboards.area_geo_data where area=%s", (a1,))[0]
        self.assertEqual((row["population"], float(row["size_km2"]), float(row["density_per_km2"]), row["source"]),
                         (35000, 2.5, 14000.0, "Test office"))  # 35000 / 2.5, source kept
        self.assertEqual(self.undo(second).status_code, 302)
        row = self.rows("select * from dashboards.area_geo_data where area=%s", (a1,))[0]
        self.assertEqual((row["population"], float(row["density_per_km2"])), (34000, 13600.0))
        self.assertEqual(self.undo(first).status_code, 302)
        self.assertEqual(self.scalar("select count(*) from public.area_geo_data"), 0)
        self.assertEqual(self.scalar("select status from public.roster_import_batches where id=%s", (first,)), "UNDONE")

    def test_03_per_capita_view_and_reader_rights(self):
        (z1, d1, a1), = self.portal_areas(1)
        self.upload(s.geo_file([(z1, d1, a1, "10000", "5", "", "", "Test office", "2024-12-31", "")]))
        batch = self.apply()
        try:
            with database.connect() as conn:
                with database.cursor(conn) as cur:
                    cur.execute("select count(*) n from dashboards.area_week_per_capita where population=10000")
                    cur.fetchone()  # the view answers (there may be no weekly plans in the copy)
                conn.rollback()
                with database.cursor(conn) as cur:
                    cur.execute("set local role gfm_dashboard_reader")
                    cur.execute("select count(*) n from dashboards.area_geo_data")
                    self.assertGreater(cur.fetchone()["n"], 0)
                    cur.execute("select count(*) n from dashboards.area_week_per_capita")
                    cur.fetchone()
                    cur.execute("savepoint s")
                    with self.assertRaises(psycopg2.errors.InsufficientPrivilege):
                        cur.execute("select count(*) from public.area_geo_data")  # permission denied for the reader
                conn.rollback()
        finally:
            self.undo(batch)

    def test_05_the_owners_three_tables_save_zone_district_and_area_figures_and_undo_takes_them_back(self):
        """NOT run in round 13. Migration 052. Needs a zone, a district and an area of the copy whose names are unique."""
        (z1, d1, a1), = self.portal_areas(1)
        figures = [123456, 10.5, 11757.7, 1, 2, 3, 4, 5, 6, "City"]
        data = s.geo_tables_file(zones=[[z1, *figures], ["Mission", 1, 1, 1, 1, 1, 1, 1, 1, 1, "City"]],
                                 districts=[[d1, *figures], ["Ghost District", 1, 1, 1, 1, 1, 1, 1, 1, 1, "Town"]],
                                 areas=[[a1, *figures], ["Media Elders", *figures], ["Office Sisters", 7, 7, 7, 7, 7, 7, 7, 7, 7, "City"]])
        page = self.upload(data)
        self.assertIn("Three tables found: 1 zones, 2 districts, 1 areas.", page)
        self.assertIn("Rows held back", page)  # Media Elders (a stand-in) and Office Sisters
        self.assertIn("Ghost District", page)  # not a district of the portal: said, not asked
        batch = self.apply()
        self.assertIsNotNone(batch)
        area = self.rows("select * from public.area_geo_data g join public.areas a on a.id=g.area_id where a.name=%s", (a1,))[0]
        self.assertEqual((area["population"], area["pop_urban_centre"], area["pop_rural_low"], area["area_type"]), (123456, 1, 6, "City"))
        self.assertEqual(self.scalar("select count(*) from public.zone_geo_data"), 1)
        self.assertEqual(self.scalar("select count(*) from public.district_geo_data"), 1)  # Ghost District was not saved
        self.assertEqual(self.scalar("select count(*) from public.area_geo_data"), 1)  # the held-back rows were not saved
        self.assertEqual(self.scalar("select pop_suburban from dashboards.zone_geo_data where zone=%s", (z1,)), 4)
        self.assertEqual(self.scalar("select count(*) from public.roster_import_changes where batch_id=%s", (batch,)), 3)
        self.assertEqual(self.undo(batch).status_code, 302)
        for table in ("zone_geo_data", "district_geo_data", "area_geo_data"):
            self.assertEqual(self.scalar(f"select count(*) from public.{table}"), 0, table)

    def test_06_the_reader_sees_the_new_views_but_not_the_new_tables(self):
        with database.connect() as conn:
            with database.cursor(conn) as cur:
                cur.execute("set local role gfm_dashboard_reader")
                for view in ("zone_geo_data", "district_geo_data", "area_geo_data"):
                    cur.execute(f"select count(*) n from dashboards.{view}")
                    cur.fetchone()
                for table in ("zone_geo_data", "district_geo_data"):
                    cur.execute("savepoint s")
                    with self.assertRaises(psycopg2.errors.InsufficientPrivilege):
                        cur.execute(f"select count(*) from public.{table}")
                    cur.execute("rollback to savepoint s")
            conn.rollback()

    def test_04_a_zl_is_refused(self):
        zl = self.role_person("TEST-GEO-ZL", leaders=["ZL"])
        try:
            client = management_tests().admin_client(self, zl, "ZL")
            self.assertIn("/login", client.get("/uploads/geo/table").headers["Location"])  # refused: sent to the sign-in
        finally:
            self.remove_person(zl)


if __name__ == "__main__":
    unittest.main()
