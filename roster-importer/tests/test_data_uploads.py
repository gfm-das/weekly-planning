"""Data uploads against a disposable roster_management_test_* copy of Beta with migration 033 (never live).

Same rules as test_management.py, whose setup it reuses. Made-up sample files only (tests/data_samples.py).
Checks: every upload reads the real file shapes, a re-upload never counts twice, Undo works, a ZL is refused,
and no name or Church person id reaches the database.
"""
import io
import json
import os
import time
import unittest
from unittest.mock import patch

import tests.test_management as tm  # the module, not the class: its own tests must not run twice

import app  # noqa: E402  (after test_management, which checks the database first)
import data_uploads  # noqa: E402
import database  # noqa: E402
import settings  # noqa: E402
import sign_in  # noqa: E402
from tests import data_samples as s  # noqa: E402

os.environ.setdefault("PERSON_KEY_SECRET", "test-secret-for-person-codes-only")


def management_tests():
    """test_management's test class (not kept in a module name here, or unittest would run its tests again)."""
    return tm.ManagementIntegrationTests


def clear_uploads():
    """Starts from no uploaded data (the copy is thrown away afterwards; a stopped earlier run may have left some)."""
    with database.connect() as conn:
        with conn.cursor() as cur:
            cur.execute("""delete from public.roster_import_batches where kind in
              ('GEO_DATA','FINDING','ZONE_HISTORY','BAPTISMS')""")
            cur.execute("delete from public.area_geo_data")
            cur.execute("delete from public.data_name_matches")


class DataUploadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        management_tests().setUpClass.__func__(cls)
        clear_uploads()

    tearDownClass = classmethod(management_tests().tearDownClass.__func__)
    setUp = management_tests().setUp
    scalar = management_tests().scalar
    role_person, remove_person = management_tests().role_person, management_tests().remove_person

    # Helpers ------------------------------------------------------------------------------------------------------
    def rows(self, query, params=()):
        with database.connect() as conn:
            with database.cursor(conn) as cur:
                cur.execute(query, params)
                return cur.fetchall()

    def portal_areas(self, count=2):
        """(zone, district, area) of current portal areas whose names are unique in the mission."""
        return [(r["zone"], r["district"], r["area"]) for r in self.rows("""
          select z.name zone,d.name district,a.name area from public.areas a join public.districts d on d.id=a.district_id
          join public.zones z on z.id=d.zone_id where z.mission_id=2 and a.active
            and (select count(*) from public.areas x where lower(x.name)=lower(a.name))=1
          order by a.id limit %s""", (count,))]

    def upload(self, slug, data, filename):
        """Upload and check a file; returns the check page."""
        response = self.client.post("/uploads/check", content_type="multipart/form-data",
                                    data={"csrf_token": "test-csrf", "kind": slug, "file": (io.BytesIO(data), filename)})
        self.assertEqual(response.status_code, 302, response.get_data(as_text=True)[:500])
        page = self.client.get(f"/uploads/{slug}/review")
        self.assertEqual(page.status_code, 200)
        return page.get_data(as_text=True)

    def apply(self, slug):
        """Applies the checked upload; returns the new batch id (None when nothing was new)."""
        before = self.scalar("select count(*) from public.roster_import_batches")
        response = self.client.post(f"/uploads/{slug}/apply", data={"csrf_token": "test-csrf", "confirmed": "yes"})
        self.assertEqual(response.status_code, 302, response.get_data(as_text=True)[:800])
        if self.scalar("select count(*) from public.roster_import_batches") == before:
            return None
        return str(self.scalar("select id from public.roster_import_batches order by created_at desc limit 1"))

    def undo(self, batch):
        return self.client.post(f"/imports/{batch}/undo", data={"csrf_token": "test-csrf", "confirmation": "UNDO"})

    def fc_referrals(self):
        return self.scalar("select coalesce(sum(people_found),0) from dashboards.finding_area_week "
                           "where mission_id=2 and findechristus and people_found>0")

    # Tests --------------------------------------------------------------------------------------------------------
    def test_01_managers_only(self):
        guest = app.app.test_client()
        for path in ["/uploads", "/uploads/geo/table", "/uploads/names", "/uploads/zone-history/template"]:
            self.assertEqual(guest.get(path).status_code, 302, path)
            self.assertEqual(self.client.get(path).status_code, 200, path)
        zl = self.role_person("TEST-UPLOAD-ZL", leaders=["ZL"])
        zl_context = {"user_id": zl["profile_id"], "app_role": "ZL", "leadership_role": None, "additional_roles": [],
                      "user_active": True, "mission_id": 2, "display_name": "Elder Test"}
        with patch.object(sign_in, "portal_context", return_value=zl_context):
            self.assertEqual(guest.get("/uploads?portal_token=opaque-test-token").status_code, 403)
        # A session that claims AP for a ZL's account is checked against the database on every request.
        forged = app.app.test_client()
        with forged.session_transaction() as sess:
            sess.update(authenticated=True, portal_user_id=zl["profile_id"], portal_role="AP", portal_mission_id=2,
                        portal_expires_at=time.time() + 1800, csrf_token="test-csrf")
        response = forged.post("/uploads/check", content_type="multipart/form-data",
                               data={"csrf_token": "test-csrf", "kind": "finding", "file": (io.BytesIO(b"x"), "x.csv")})
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login", response.headers["Location"])
        self.assertEqual(forged.get("/uploads").status_code, 302)  # the refused session was cleared
        # An AP has full rights here.
        ap = self.role_person("TEST-UPLOAD-AP", leaders=["AP"])
        self.assertEqual(management_tests().admin_client(self, ap, "AP").get("/uploads").status_code, 200)

    def test_01b_deleted_cards_are_not_offered_and_their_old_addresses_lead_to_the_hub(self):
        # Round 16 (migration 058): Referral archive and Rates are gone for good.
        hub = self.client.get("/uploads").get_data(as_text=True)
        for slug in ("referral-archive", "rates"):
            self.assertNotIn(f'href="/uploads/{slug}"', hub)
            self.assertEqual(self.client.get(f"/uploads/{slug}").status_code, 302)  # old address: leads to /uploads
        self.assertNotIn("Referral archive", hub)
        self.assertNotIn("Teaching and contact rates", hub)
        self.assertIn("Finding export", hub)
        # October 2026: the Baptism history upload is gone too (its stored rows stay, see test_05).
        self.assertNotIn("Baptism history", hub)
        self.assertNotIn('value="baptisms"', hub)
        self.assertEqual(self.client.get("/uploads/baptisms").status_code, 302)  # old address: leads to /uploads
        self.assertEqual(self.client.get("/uploads/baptisms/template").status_code, 404)
        self.assertEqual(self.client.get("/uploads/baptisms/review").status_code, 302)  # nothing can wait there
        refused = self.client.post("/uploads/check", content_type="multipart/form-data",
                                   data={"csrf_token": "test-csrf", "kind": "baptisms",
                                         "file": (io.BytesIO(b"Baptism date,Zone\n9/20/2026,X\n"), "b.csv")})
        self.assertEqual(refused.status_code, 404)

    def test_02_geo_data_flat_file_with_peer_types_table_and_undo(self):
        """Round 16: Area data is part of Geo data. A flat file with Urban type and Assignment type is read, a re-upload
        changes nothing, the Geo data table edits the same figures, and Undo takes them back."""
        (z1, d1, a1), (z2, d2, a2) = self.portal_areas(2)
        page = self.upload("geo", s.geo_flat_file([(z1, d1, a1, "34000", "2,5", "Big city", "Elders", "yes"),
                                                   (z2, d2, a2, "", "12", "", "Sisters", ""),
                                                   (z2, d2, "Not A Portal Area", "5", "", "", "", "")]), "geo-flat.csv")
        self.assertIn("Not A Portal Area", page)  # a name to match
        self.client.post("/uploads/geo/names", data={"csrf_token": "test-csrf", "level": "area",
                                                     "name": "Not A Portal Area", "choice": "historical"})
        self.assertNotIn("names still need a match", self.client.get("/uploads/geo/review").get_data(as_text=True))
        batch = self.apply("geo")
        self.assertIsNotNone(batch)
        row = self.rows("select * from dashboards.area_geo_data where area=%s", (a1,))[0]
        self.assertEqual((row["population"], float(row["size_km2"]), float(row["density_per_km2"]), row["urban_type"],
                          row["extra"]), (34000, 2.5, 13600.0, "Big city", {"Chapel nearby": "yes"}))
        peers = {r["area_id"]: r for r in self.rows("select * from dashboards.archetype_area_profile where mission_id=2")}
        first_id = self.scalar("select id from public.areas where name=%s", (a1,))
        second_id = self.scalar("select id from public.areas where name=%s", (a2,))
        self.assertEqual((peers[first_id]["urban_type"], peers[first_id]["assignment_type"], float(peers[first_id]["density_per_km2"])),
                         ("Big city", "Elders", 13600.0))
        self.assertEqual((peers[second_id]["population"], peers[second_id]["assignment_type"]), (None, "Sisters"))
        # An empty cell keeps the saved value: a file of blanks says nothing.
        self.upload("geo", s.geo_flat_file([(z1, d1, a1, "", "", "", "", "")]), "geo-again.csv")
        self.assertIsNone(self.apply("geo"))
        # The Geo data table: clearing a box clears the value; the save is a batch that Undo reverses.
        table = self.client.get("/uploads/geo/table").get_data(as_text=True)
        self.assertIn(a1, table)
        self.assertIn('name="urban"', table)
        self.assertEqual(self.client.get("/uploads/areas/table").status_code, 404)  # the old Area data table is gone
        ids = [r["area_id"] for r in self.rows("""select a.id area_id from public.areas a join public.districts d on d.id=a.district_id
          join public.zones z on z.id=d.zone_id left join public.area_geo_data g on g.area_id=a.id
          where z.mission_id=2 and (a.active or g.area_id is not null) order by a.active desc,z.name,d.name,a.name""")]
        form = {"csrf_token": "test-csrf", "area_id": [], "population": [], "size": [], "households": [], "urban": [],
                "assignment": [], "extra": []}
        for area_id in ids:
            saved = self.rows("select * from public.area_geo_data where area_id=%s", (area_id,))
            p = saved[0] if saved else {}
            form["area_id"].append(str(area_id))
            cleared = area_id == first_id
            form["population"].append("" if cleared or p.get("population") is None else str(p["population"]))
            form["size"].append("" if p.get("size_km2") is None else str(p["size_km2"]))
            form["households"].append("" if p.get("households") is None else str(p["households"]))
            form["urban"].append("Rural" if area_id == second_id else p.get("urban_type") or "")  # typed by hand
            form["assignment"].append(p.get("assignment_type") or "")
            form["extra"].append("; ".join(f"{k}: {v}" for k, v in (p.get("extra") or {}).items()))
        before = self.rows("select * from public.area_geo_data where area_id in (%s,%s) order by area_id", (first_id, second_id))
        response = self.client.post("/uploads/geo/table", data=form)
        self.assertEqual(response.status_code, 302)
        table_batch = str(self.scalar("select id from public.roster_import_batches order by created_at desc limit 1"))
        self.assertIsNone(self.rows("select population from public.area_geo_data where area_id=%s", (first_id,))[0]["population"])
        self.assertEqual(self.scalar("select urban_type from public.area_geo_data where area_id=%s", (second_id,)), "Rural")
        self.assertEqual(self.scalar("select urban_type from dashboards.archetype_area_profile where area_id=%s", (second_id,)), "Rural")
        self.assertEqual(self.undo(table_batch).status_code, 302)
        self.assertEqual(self.rows("select * from public.area_geo_data where area_id in (%s,%s) order by area_id", (first_id, second_id)), before)
        bad = dict(form, population=["lots"] + form["population"][1:])
        self.assertEqual(self.client.post("/uploads/geo/table", data=bad).status_code, 400)
        self.assertEqual(self.undo(batch).status_code, 302)
        self.assertEqual(self.scalar("select count(*) from public.area_geo_data where area_id in (select id from public.areas where name=any(%s))",
                                     ([a1, a2],)), 0)

    def test_03_finding_upload_reupload_undo_and_no_names(self):
        areas = self.portal_areas(2)
        page = self.upload("finding", s.finding_file(areas), "MissionFindingDetail.csv")
        self.assertIn("5 new", page)
        # FindeChristus is archived (migration 038): the check no longer names it, but still counts it below.
        self.assertNotIn("FindeChristus referrals", page)
        # The waiting rows hold person codes, never names or ids.
        token = self.session_value("data_pending_finding")
        waiting = data_uploads.pending_path(token).read_text(encoding="utf-8")
        for secret in s.MADE_UP_NAMES + s.MADE_UP_IDS:
            self.assertNotIn(secret, waiting)
        first = self.apply("finding")
        self.assertIsNotNone(first)
        self.assertFalse(data_uploads.pending_path(token).exists())  # the waiting rows are gone after Apply
        for kept in settings.UPLOAD_DIR.iterdir():  # no copy of the uploaded file anywhere (other imports keep their own)
            self.assertNotIn(s.MADE_UP_NAMES[0], kept.read_bytes().decode("utf-8", "replace"))
        self.assertEqual(self.scalar("select count(*) from public.finding_people where batch_id=%s", (first,)), 5)
        self.assertEqual(self.fc_referrals(), 2)
        week = self.rows("""select sum(people_found) found,sum(referrals) referrals,sum(people_reached) reached,
            sum(first_lessons) lessons from dashboards.finding_area_week where mission_id=2 and sunday='2026-09-20'""")[0]
        self.assertEqual((week["found"], week["referrals"], week["reached"], week["lessons"]), (2, 2, 1, 1))
        cohort = self.rows("""select sum(people_found) found,sum(taught) taught from dashboards.finding_cohort_week
            where mission_id=2 and sunday='2026-09-20' and findechristus""")[0]
        self.assertEqual((cohort["found"], cohort["taught"]), (2, 1))

        # The same export again: nothing new, nothing counted twice.
        self.assertIn("5 already stored", self.upload("finding", s.finding_file(areas), "MissionFindingDetail.csv"))
        self.assertIsNone(self.apply("finding"))
        # A newer export: person 2 had a lesson, a sixth person was found. Only those two rows are stored.
        newer = s.finding_file(areas, extra_rows=[s.finding_row("900000006", "Newly Found", "Media", "Headquarters Local",
                                                                "9/24/2026", areas[0][2], areas[0][1], areas[0][0])])
        newer = newer.replace(b"9/20/2026,9/20/2026,Media,Facebook - Mission Ad,Facebook - Mission Ad,,,9/20/2026,9/20/2026,,",
                              b"9/20/2026,9/20/2026,Media,Facebook - Mission Ad,Facebook - Mission Ad,,,9/20/2026,9/20/2026,9/25/2026,")
        self.assertIn("1 new, 1 with new dates", self.upload("finding", newer, "MissionFindingDetail (2).csv"))
        second = self.apply("finding")
        self.assertEqual(self.scalar("select count(*) from public.finding_people where batch_id=%s", (second,)), 2)
        self.assertEqual(self.fc_referrals(), 3)
        self.assertEqual(self.scalar("select sum(people_found) from dashboards.finding_area_week where mission_id=2"), 6)
        # Undo: the older upload only after the newer one.
        refused = self.undo(first)
        self.assertEqual(refused.status_code, 409)
        self.assertIn("Undo the newer finding upload first", refused.get_data(as_text=True))
        self.assertEqual(self.undo(second).status_code, 302)
        self.assertEqual((self.fc_referrals(), self.scalar("select sum(people_found) from dashboards.finding_area_week where mission_id=2")), (2, 5))
        # No name, no Church person id anywhere in the stored rows.
        stored = json.dumps([dict(r) for r in self.rows("select * from public.finding_people")], default=str)
        for secret in s.MADE_UP_NAMES + s.MADE_UP_IDS + ["Newly Found", "900000006"]:
            self.assertNotIn(secret, stored)
        self.assertEqual(self.undo(first).status_code, 302)
        self.assertEqual(self.scalar("select count(*) from public.finding_people"), 0)

    def test_04_zone_history_portal_wins_reupload_and_historical_zone(self):
        portal = self.rows("""select sunday,zone from dashboards.kpi_zone_week where mission_id=2 and reports>0
          order by sunday desc limit 1""")[0]
        portal_week = portal["sunday"].strftime("%m/%d/%Y")
        # "<zone> Zone" in the same week means the same portal zone: only the first row counts.
        rows = [("8/4/2024", portal["zone"], 22, 18), ("8/4/2024", "Düsseldorf", 30, 25),
                ("8/4/2024", portal["zone"] + " Zone", 5, 5),
                ("8/11/2024", portal["zone"], 19, 14), (portal_week, portal["zone"], 999, 999)]
        page = self.upload("zone-history", s.zone_history_file(rows), "Data for Data Studio.csv")
        self.assertIn("Düsseldorf", page)
        self.assertIn("The portal already has weekly plans for 1 of these zone weeks", page)
        self.client.post("/uploads/zone-history/names", data={"csrf_token": "test-csrf", "level": "zone",
                                                              "name": "Düsseldorf", "choice": "", "keep_rest": "yes"})
        first = self.apply("zone-history")
        self.assertIsNotNone(first)
        history = {(r["sunday"].isoformat(), r["zone"]): r for r in self.rows(
            "select * from dashboards.zone_history_week where mission_id=2")}
        self.assertEqual(history[("2024-08-04", "Düsseldorf")]["friends_found_actual"], 25)  # a historical zone
        self.assertEqual(history[("2024-08-04", portal["zone"])]["friends_found_goal"], 22)
        # A sheet's Goal is set that Sunday for the next week: week 11 Aug is measured against 4 Aug's goal.
        self.assertEqual(history[("2024-08-11", portal["zone"])]["friends_found_previous_goal"], 22)
        self.assertIsNone(history[("2024-08-04", portal["zone"])]["friends_found_previous_goal"])
        mine = history[(portal["sunday"].isoformat(), portal["zone"])]
        self.assertEqual(mine["data_source"], "portal")  # the portal's own numbers win
        self.assertNotEqual(mine["friends_found_actual"], 999)
        mission = lambda: self.rows("select friends_found_actual from dashboards.mission_history_week where mission_id=2 and sunday='2024-08-04'")[0]["friends_found_actual"]
        self.assertEqual(mission(), 43)
        # The same sheet again (the name is remembered now): replaces those weeks, nothing counted twice.
        self.assertNotIn("Names that are not in the portal", self.upload("zone-history", s.zone_history_file(rows), "again.csv"))
        second = self.apply("zone-history")
        self.assertEqual(mission(), 43)
        # A corrected sheet replaces the week; Undo brings the first upload back.
        page = self.upload("zone-history", s.zone_history_file([("8/4/2024", portal["zone"], 22, 20)]), "corrected.csv")
        # The check says which rows of the older upload stop counting, and that Düsseldorf's row is not in this file.
        self.assertIn("From again.csv (", page)
        self.assertIn("1 weeks, 2 rows stop counting", page)
        self.assertIn("1 of these rows are for a zone or area this file does not have", page)
        third = self.apply("zone-history")
        self.assertEqual(mission(), 20)  # the newest upload of that week counts, with only its rows
        self.assertEqual(self.undo(third).status_code, 302)
        self.assertEqual(mission(), 43)
        for batch in (second, first):
            self.assertEqual(self.undo(batch).status_code, 302)
        self.assertEqual(self.scalar("select count(*) from dashboards.zone_history_week where data_source='upload'"), 0)

    def test_05_old_baptism_history_batches_still_count_show_and_undo(self):
        """The Baptism history upload is gone (October 2026), but a batch uploaded before still counts in the dashboards,
        is listed in Import history and can be undone there."""
        (zone, district, area), = self.portal_areas(1)
        zone_id = self.scalar("select id from public.zones where name=%s and mission_id=2", (zone,))
        area_id = self.scalar("select id from public.areas where name=%s", (area,))
        with database.connect() as conn:
            with conn.cursor() as cur:
                cur.execute("""insert into public.roster_import_batches (id,mission_id,kind,filename,actor,summary)
                  values (gen_random_uuid(),2,'BAPTISMS','Vollzogen 2025.xlsx','Elder Test','{}') returning id""")
                batch = str(cur.fetchone()[0])
                cur.execute("""insert into public.baptism_history_weeks
                  (batch_id,mission_id,sunday,zone_id,area_id,zone_name,area_name,ward,finding_source,baptisms,confirmations)
                  values (%s,2,'2025-09-21',%s,%s,%s,%s,'','',2,0),(%s,2,'2025-09-28',%s,%s,%s,%s,'','',0,1)""",
                            (batch, zone_id, area_id, zone, area) * 2)
        counted = self.rows("select sum(baptisms) b,sum(confirmations) c from dashboards.baptism_history_week where mission_id=2")[0]
        self.assertEqual((counted["b"], counted["c"]), (2, 1))
        history = self.client.get("/imports").get_data(as_text=True)
        self.assertIn("Vollzogen 2025.xlsx", history)
        self.assertIn("Baptism history", history)
        self.assertEqual(self.client.get(f"/imports/{batch}").status_code, 200)
        self.assertEqual(self.undo(batch).status_code, 302)
        self.assertEqual(self.scalar("select count(*) from public.baptism_history_weeks where batch_id=%s", (batch,)), 0)

    def test_06_dashboards_reader_sees_views_not_tables(self):
        with database.connect() as conn:
            with conn.cursor() as cur:
                cur.execute("set local role gfm_dashboard_reader")
                for view in ("area_geo_data", "archetype_area_profile", "finding_area_week", "finding_cohort_week", "zone_history_week",
                             "mission_history_week", "baptism_history_week"):
                    cur.execute(f"select count(*) from dashboards.{view}")
                # Migration 058: the two deleted uploads left no table or view behind, and Archetypal Health no longer reads them.
                cur.execute("reset role")
                cur.execute("""select string_agg(n.nspname||'.'||c.relname, ', ') from pg_class c join pg_namespace n on n.oid=c.relnamespace
                    where c.relname in ('referral_archive_weeks','finding_rate_weeks','referral_archive_week','finding_rate_week',
                                        'findechristus_referrals_week')""")
                self.assertIsNone(cur.fetchone()[0])
                cur.execute("select pg_get_viewdef('dashboards.archetype_area_week'::regclass) like '%findechristus_referrals_week%'")
                self.assertFalse(cur.fetchone()[0])
                cur.execute("set local role gfm_dashboard_reader")
                for table in ("finding_people", "area_geo_data", "data_name_matches", "finding_people_latest"):
                    cur.execute("savepoint s")
                    with self.assertRaises(Exception, msg=table):
                        cur.execute(f"select count(*) from public.{table}")
                    cur.execute("rollback to savepoint s")
            conn.rollback()

    def test_07_file_problems_are_explained(self):
        response = self.client.post("/uploads/check", content_type="multipart/form-data",
                                    data={"csrf_token": "test-csrf", "kind": "zone-history", "file": (io.BytesIO(b"%PDF"), "sheet.pdf")})
        self.assertEqual(response.status_code, 400)
        self.assertIn("Choose a CSV or XLSX file.", response.get_data(as_text=True))
        with patch.dict(os.environ, {"PERSON_KEY_SECRET": ""}):
            answer = self.client.post("/uploads/check", content_type="multipart/form-data",
                                      data={"csrf_token": "test-csrf", "kind": "finding", "file": (io.BytesIO(b"x"), "x.csv")})
            self.assertEqual(answer.status_code, 400)
            self.assertIn("PERSON_KEY_SECRET", answer.get_data(as_text=True))

    def test_09_an_older_finding_export_keeps_the_newer_dates(self):
        areas = self.portal_areas(2)
        newer = s.finding_file(areas, extra_rows=[s.finding_row("900000006", "Newly Found", "Media", "Headquarters Local",
                                                                "9/24/2026", areas[0][2], areas[0][1], areas[0][0])])
        newer = newer.replace(b"9/20/2026,9/20/2026,Media,Facebook - Mission Ad,Facebook - Mission Ad,,,9/20/2026,9/20/2026,,",
                              b"9/20/2026,9/20/2026,Media,Facebook - Mission Ad,Facebook - Mission Ad,,,9/20/2026,9/20/2026,9/25/2026,")
        self.upload("finding", newer, "MissionFindingDetail September.csv")
        first = self.apply("finding")
        lessons = lambda: self.scalar("select count(first_lesson_on) from public.finding_people_latest where mission_id=2")
        self.assertEqual(lessons(), 3)
        # Last month's export after this month's: a warning, a second tick, and no stored date is lost.
        page = self.upload("finding", s.finding_file(areas), "MissionFindingDetail August.csv")
        self.assertIn("This file looks older than what is stored", page)
        self.assertIn('name="older_ok"', page)
        self.assertIn("0 new, 0 with new dates or a new area, 5 already stored", page)  # person 2 keeps the lesson
        refused = self.client.post("/uploads/finding/apply", data={"csrf_token": "test-csrf", "confirmed": "yes"})
        self.assertEqual(refused.status_code, 409)
        self.assertIn("Tick that you still want to apply it", refused.get_data(as_text=True))
        before = self.scalar("select count(*) from public.roster_import_batches")
        response = self.client.post("/uploads/finding/apply",
                                    data={"csrf_token": "test-csrf", "confirmed": "yes", "older_ok": "yes"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.scalar("select count(*) from public.roster_import_batches"), before)  # nothing new
        self.assertEqual(lessons(), 3)
        self.assertEqual(self.undo(first).status_code, 302)

    def test_10_waiting_files_older_than_a_day_are_deleted(self):
        old = settings.UPLOAD_DIR / "data-left-behind-by-a-test-0001.json"
        old.write_text("{}", encoding="utf-8")
        os.utime(old, (time.time() - 25 * 3600, time.time() - 25 * 3600))
        data_uploads.last_tidy = 0.0
        self.client.get("/imports")  # any DA Management page
        self.assertFalse(old.exists())

    def session_value(self, key):
        with self.client.session_transaction() as sess:
            return sess[key]


if __name__ == "__main__":
    unittest.main()
