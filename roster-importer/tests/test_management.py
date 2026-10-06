"""Integration tests against a disposable copy of Beta, never the live database."""
import csv
import html
import json
import io
import os
import re
import tempfile
import time
import unittest
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from unittest.mock import Mock, patch

test_db = os.environ.get("MANAGEMENT_TEST_DATABASE", "")
if not test_db.startswith("roster_management_test_"):
    raise RuntimeError("A disposable roster_management_test_* database is required.")
parts = urlsplit(os.environ["DATABASE_URL"])
if parts.hostname != "gfm-beta-supabase-db-1":
    raise RuntimeError("These tests may run only against the pinned Beta database host.")
os.environ["DATABASE_URL"] = urlunsplit(parts._replace(path="/" + test_db))

from flask import session

import account_changes
import account_page
import app
import batches
import database
import historical_apply
import historical_import as historical
import historical_preview
import places
import roles
import roster_file
import settings
import sign_in
import supabase_auth
import transfer
import undo
from page import day


class ManagementIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app.app.config["TESTING"] = True
        cls.no_emails = patch.object(supabase_auth, "auth_request", side_effect=AssertionError("Tests must never send email"))
        cls.no_emails.start()
        with database.connect() as conn:
            with database.cursor(conn) as cur:
                cur.execute("select current_database() name")
                assert cur.fetchone()["name"] == test_db
                cur.execute("""select a.id,a.name from public.areas a join public.districts d on d.id=a.district_id
                  join public.zones z on z.id=d.zone_id where z.mission_id=2 and a.active and d.active and z.active
                  and exists (select 1 from public.missionary_assignments ma join public.missionaries mm on mm.id=ma.missionary_id
                              where ma.area_id=a.id and ma.end_date is null and mm.status='Active')
                  order by a.id limit 1""")
                cls.area = cur.fetchone()  # a current area, as the importer only maps to current areas
                cur.execute("""select m.id,up.id profile_id from public.missionaries m
                  join public.missionary_assignments ma on ma.missionary_id=m.id and ma.end_date is null
                  join public.areas a on a.id=ma.area_id join public.districts d on d.id=a.district_id
                  join public.zones z on z.id=d.zone_id left join public.user_profiles up on up.missionary_id=m.id
                  where z.mission_id=2 order by up.id nulls last,m.id limit 1""")
                cls.person = cur.fetchone()

    @classmethod
    def tearDownClass(cls):
        cls.no_emails.stop()

    def setUp(self):
        self.client = app.app.test_client()
        with self.client.session_transaction() as s:
            s.update(authenticated=True, portal_mission_id=2, portal_user="Integration test", csrf_token="test-csrf")

    def context(self):
        return app.app.test_request_context("/")

    def scalar(self, query, params=()):
        with database.connect() as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                return cur.fetchone()[0]

    def fixture_csv(self, source, sunday, value=9, duplicate=True):
        fields = [historical.TIMESTAMP_COLUMN, historical.EMAIL_COLUMN, historical.COMPANIONSHIP_COLUMN,
                  historical.UNIT_COLUMN, historical.SUNDAY_COLUMN, "Friends Found - Actual",
                  "Friends Found - Goal for next week", "Weekly Action Plan", "Test additional goal"]
        f = tempfile.NamedTemporaryFile(mode="w", suffix=".csv", encoding="utf-8", newline="", delete=False)
        writer = csv.DictWriter(f, fields)
        writer.writeheader()
        base = {historical.EMAIL_COLUMN: "test@example.invalid", historical.COMPANIONSHIP_COLUMN: source,
                historical.UNIT_COLUMN: "Historical Ward", historical.SUNDAY_COLUMN: sunday,
                "Friends Found - Goal for next week": "12", "Weekly Action Plan": "Visit assigned families",
                "Test additional goal": "Discuss progress with companion"}
        if duplicate:
            writer.writerow({**base, historical.TIMESTAMP_COLUMN: "2000-01-01 09:00:00", "Friends Found - Actual": "2"})
        writer.writerow({**base, historical.TIMESTAMP_COLUMN: "2000-01-01 10:00:00", "Friends Found - Actual": str(value)})
        f.close()
        self.addCleanup(lambda: Path(f.name).unlink(missing_ok=True))
        with database.connect() as conn:
            with conn.cursor() as cur:
                cur.execute("""insert into public.import_weekly_planning_area_map
                  (source_companionship,target_area_name,target_area_id,mission_id,match_status,confirmed_at)
                  values(%s,%s,%s,2,'CONFIRMED',now()) on conflict(source_companionship) do update
                  set target_area_id=excluded.target_area_id,mission_id=2""", (source, self.area["name"], self.area["id"]))
        return f.name

    def imported_fixture(self, source, sunday):
        path = self.fixture_csv(source, sunday)
        with self.context():
            session.update(portal_mission_id=2, portal_user="Integration test")
            batch = historical_apply.apply_batch(path, "test.csv")
        report = self.scalar("select id from public.weekly_area_reports where historical_source_key=%s",
                             (historical.make_report_key(source, date.fromisoformat(sunday)),))
        return batch, report, path

    def test_01_routes_role_gate_csrf_and_account_loading(self):
        guest = app.app.test_client()
        for path in ["/", "/accounts", "/historical", "/mappings", "/imports", "/docs"]:
            self.assertEqual(guest.get(path).status_code, 302, path)
            self.assertEqual(self.client.get(path).status_code, 200, path)
        self.assertEqual(self.client.get(f"/accounts/{self.person['id']}").status_code, 200)
        self.assertEqual(self.client.get("/accounts?mission_id=999999").status_code, 403)
        self.assertEqual(self.client.post("/mappings/save", data={"source": "Invalid"}).status_code, 403)
        admin_context = {"user_id": str(self.person["profile_id"]), "app_role": "DATA_ADMIN", "leadership_role": "DL",
                         "user_active": True, "mission_id": 2, "management_role": "DATA_ADMIN"}
        with patch.object(sign_in, "portal_context", return_value=admin_context), patch.object(sign_in, "current_management_context", return_value=admin_context):
            self.assertEqual(guest.get("/?portal_token=opaque-test-token").status_code, 302)
            self.assertEqual(guest.get("/").status_code, 200)
        with patch.object(sign_in, "portal_context", return_value={"app_role": "AP", "user_active": False}):
            self.assertEqual(guest.get("/?portal_token=opaque-test-token").status_code, 403)
        with patch.object(sign_in, "portal_context", return_value={"app_role": "OFFICE", "user_active": True}):
            self.assertEqual(guest.get("/?portal_token=opaque-test-token").status_code, 403)

    def test_02_historical_dedup_preservation_and_undo(self):
        source, sunday = "Test former area — preserved", "2000-01-02"
        path = self.fixture_csv(source, sunday)
        with self.context():
            session.update(portal_mission_id=2, portal_user="Integration test")
            preview = historical_preview.preview(path)
            self.assertEqual(preview["duplicates"], 1)
            self.assertFalse(preview["errors"])
            batch = historical_apply.apply_batch(path, "test.csv")
            with database.connect() as conn:
                with database.cursor(conn) as cur:
                    cur.execute("select * from public.weekly_area_reports where import_batch_id=%s", (batch,))
                    r = cur.fetchone()
                    self.assertEqual(r["friends_found_actual"], 9)
                    self.assertEqual(r["friends_found_goal"], 12)
                    self.assertEqual(r["historical_source_area"], source)
                    self.assertEqual(r["area_id"], self.area["id"])
                    self.assertIn("Visit assigned families", r["notes"])
                    cur.execute("select answers from public.historical_planning_details where weekly_area_report_id=%s", (r["id"],))
                    self.assertTrue(any(a["answer_raw"] == "Discuss progress with companion" for a in cur.fetchone()["answers"]))
            self.assertFalse(historical_preview.preview(path)["errors"])
            replacement = historical_apply.apply_batch(path, "duplicate.csv")
            self.assertEqual(self.scalar("select count(*) from public.weekly_area_reports where historical_source_key=%s",
                                         (historical.make_report_key(source, date.fromisoformat(sunday)),)), 1)
            undo.undo_batch(replacement)
            undo.undo_batch(batch)
            self.assertEqual(self.scalar("select count(*) from public.weekly_area_reports where import_batch_id=%s", (batch,)), 0)
            self.assertEqual(self.scalar("select status from public.roster_import_batches where id=%s", (batch,)), "UNDONE")

    def test_03_undo_rejects_later_edits_without_partial_reversal(self):
        batch, report, _ = self.imported_fixture("Edited historical source", "2000-01-09")
        with database.connect() as conn:
            with conn.cursor() as cur:
                cur.execute("update public.weekly_area_reports set friends_found_goal=99 where id=%s", (report,))
        with self.context():
            session.update(portal_mission_id=2)
            with self.assertRaisesRegex(ValueError, "changed after"): undo.undo_batch(batch)
        self.assertEqual(self.scalar("select friends_found_goal from public.weekly_area_reports where id=%s", (report,)), 99)
        self.assertEqual(self.scalar("select status from public.roster_import_batches where id=%s", (batch,)), "APPLIED")
        with database.connect() as conn:
            with conn.cursor() as cur: cur.execute("update public.weekly_area_reports set friends_found_goal=12 where id=%s", (report,))
        with self.context():
            session.update(portal_mission_id=2)
            undo.undo_batch(batch)

    def test_04_undo_rejects_new_dependent_data(self):
        batch, report, _ = self.imported_fixture("Dependent historical source", "2000-01-16")
        with database.connect() as conn:
            with conn.cursor() as cur:
                cur.execute("insert into public.weekly_high_potential_friends(weekly_area_report_id,display_order,name) values(%s,1,'Later test data')", (report,))
        with self.context():
            session.update(portal_mission_id=2)
            with self.assertRaisesRegex(ValueError, "now references"): undo.undo_batch(batch)
        self.assertEqual(self.scalar("select count(*) from public.historical_planning_details where weekly_area_report_id=%s", (report,)), 1)
        self.assertEqual(self.scalar("select status from public.roster_import_batches where id=%s", (batch,)), "APPLIED")
        with database.connect() as conn:
            with conn.cursor() as cur: cur.execute("delete from public.weekly_high_potential_friends where weekly_area_report_id=%s", (report,))
        with self.context():
            session.update(portal_mission_id=2)
            undo.undo_batch(batch)

    def test_05_account_languages_and_invalid_transaction(self):
        page, data = self.page_form(self.client, self.person)  # the page as shown: only the languages are edited
        self.assertIn("Assigned languages", page)
        leaders = self.leaders_of(self.person)
        data.update(primary_language="de", additional_languages="es, fr", effective_date="2099-01-01")
        self.assertEqual(self.client.post(f"/accounts/{self.person['id']}/update", data=data).status_code, 302)
        self.assertEqual(self.leaders_of(self.person), leaders)  # a languages-only save never ends a leadership row
        self.assertEqual(self.scalar("select primary_language from public.missionary_language_assignments where missionary_id=%s", (self.person["id"],)), "de")
        _, data = self.page_form(self.client, self.person)  # the save may have recorded the role: reload, as a browser would
        data.update(primary_language="en", additional_languages="en")
        response = self.client.post(f"/accounts/{self.person['id']}/update", data=data)
        self.assertEqual(response.status_code, 400)
        self.assertIn("must not also appear", response.get_data(as_text=True))
        self.assertEqual(self.scalar("select primary_language from public.missionary_language_assignments where missionary_id=%s", (self.person["id"],)), "de")

    def test_06_transfer_failure_rolls_back_audit_and_roster(self):
        row = {"missionary_number": "TEST-FAIL", "first_name": "Test", "last_name": "Failure", "display_name": "Elder Failure",
               "missionary_type": "Elder", "arrival_date": None, "release_date": None, "email": "failure@example.invalid",
               "zone": "Integration Zone", "district": "Integration District", "area": "Integration Area", "units": [],
               "position": None, "position_abbr": None, "special_assignment": None, "roles": {"INVALID"}}
        count = self.scalar("select count(*) from public.roster_import_batches")
        with self.context():
            session.update(portal_mission_id=2)
            with self.assertRaises(KeyError): transfer.apply_roster_batch([row], 2, date(2099, 1, 2), "failure.csv")
        self.assertEqual(self.scalar("select count(*) from public.roster_import_batches"), count)
        self.assertEqual(self.scalar("select count(*) from public.missionaries where missionary_number='TEST-FAIL'"), 0)
        self.assertEqual(self.scalar("select count(*) from public.zones where name='Integration Zone'"), 0)

    def test_07_transfer_success_and_complete_batch_undo(self):
        row = {"missionary_number": "TEST-SUCCESS", "first_name": "Test", "last_name": "Success", "display_name": "Elder Success",
               "missionary_type": "Elder", "arrival_date": None, "release_date": None, "email": "success@example.invalid",
               "zone": "Integration Zone", "district": "Integration District", "area": "Integration Area", "units": [],
               "position": "District Leader", "position_abbr": "DL", "special_assignment": None, "roles": {"DL"}}
        with database.connect() as conn: before = batches.snapshot(conn, batches.TRANSFER_TABLES)
        with self.context():
            session.update(portal_mission_id=2)
            batch = transfer.apply_roster_batch([row], 2, date(2099, 1, 2), "success.csv")
            self.assertEqual(self.scalar("select count(*) from public.missionaries where missionary_number='TEST-SUCCESS'"), 1)
            self.assertGreater(self.scalar("select count(*) from public.roster_import_changes where batch_id=%s", (batch,)), 0)
            undo.undo_batch(batch)
        with database.connect() as conn: after = batches.snapshot(conn, batches.TRANSFER_TABLES)
        self.assertEqual(before, after)

    def portal_client(self, mission=2):
        client = app.app.test_client()
        with client.session_transaction() as s:
            s.update(authenticated=True, portal_user_id=str(self.person["profile_id"]), portal_role="DATA_ADMIN",
                     portal_mission_id=mission, portal_expires_at=time.time() + 1800, csrf_token="test-csrf")
        return client

    def test_08_live_identity_role_mission_and_logout(self):
        user_id = str(self.person["profile_id"])
        with database.connect() as conn:
            with conn.cursor() as cur:
                cur.execute("select app_role,active from public.user_profiles where id=%s", (user_id,))
                original_profile = cur.fetchone()
                cur.execute("select id,start_date from public.leadership_assignments where missionary_id=%s and role='AP'", (self.person["id"],))
                original_ap_dates = cur.fetchall()
                cur.execute("update public.user_profiles set app_role='DATA_ADMIN',active=true where id=%s", (user_id,))
        inserted_leaders = []
        try:
            client = self.portal_client()
            self.assertEqual(client.get("/accounts").status_code, 200)
            with database.connect() as conn:
                with conn.cursor() as cur:
                    cur.execute("select a.district_id,d.zone_id from public.areas a join public.districts d on d.id=a.district_id where a.id=%s", (self.area["id"],))
                    district, zone = cur.fetchone()
                    for role, district_id, zone_id in [("DL", district, None), ("ZL", None, zone)]:
                        cur.execute("""insert into public.leadership_assignments(missionary_id,role,district_id,zone_id,start_date)
                          values(%s,%s,%s,%s,current_date) returning id""", (self.person["id"], role, district_id, zone_id))
                        inserted_leaders.append(cur.fetchone()[0])
            context = sign_in.current_management_context(user_id)
            self.assertEqual(context["management_role"], "DATA_ADMIN")
            self.assertEqual(context["mission_id"], 2)
            with database.connect() as conn:
                with conn.cursor() as cur:
                    cur.execute("update public.user_profiles set active=false where id=%s", (user_id,))
            self.assertEqual(client.get("/accounts").status_code, 302)
            with client.session_transaction() as s: self.assertNotIn("authenticated", s)
            self.assertEqual(self.portal_client().post(f"/accounts/{self.person['id']}/update", data={"csrf_token": "test-csrf"}).status_code, 302)
            with database.connect() as conn:
                with conn.cursor() as cur:
                    cur.execute("update public.user_profiles set active=true,app_role='MISSIONARY' where id=%s", (user_id,))
                    cur.execute("update public.leadership_assignments set start_date='2099-01-01' where missionary_id=%s and role='AP'", (self.person["id"],))
            self.assertIsNone(sign_in.current_management_context(user_id))
            self.assertEqual(self.portal_client().get("/accounts").status_code, 302)
            self.assertEqual(self.portal_client().post(f"/accounts/{self.person['id']}/update", data={"csrf_token": "test-csrf"}).status_code, 302)
            with database.connect() as conn:
                with conn.cursor() as cur:
                    cur.execute("update public.user_profiles set app_role='DATA_ADMIN' where id=%s", (user_id,))
            self.assertEqual(self.portal_client(mission=999999).get("/accounts").status_code, 302)
            self.assertEqual(self.portal_client(mission=999999).post(f"/accounts/{self.person['id']}/update", data={"csrf_token": "test-csrf"}).status_code, 302)
            client = self.portal_client()
            self.assertEqual(client.get("/accounts").status_code, 200)
            result = client.get("/logout")
            self.assertEqual(result.status_code, 200)
            self.assertIn("Max-Age=0", result.headers["Set-Cookie"])
            self.assertEqual(client.get("/accounts").status_code, 302)
            with patch.object(settings, "IMPORTER_PASSWORD", ""):
                self.assertEqual(self.client.get("/accounts").status_code, 302)
                self.assertEqual(self.client.get("/login").status_code, 403)
                self.assertEqual(self.portal_client().get("/accounts").status_code, 200)
        finally:
            with database.connect() as conn:
                with conn.cursor() as cur:
                    cur.execute("update public.user_profiles set app_role=%s,active=%s where id=%s", (*original_profile, user_id))
                    for leader_id, start_date in original_ap_dates:
                        cur.execute("update public.leadership_assignments set start_date=%s where id=%s", (start_date, leader_id))
                    if inserted_leaders:
                        cur.execute("delete from public.leadership_assignments where id=any(%s)", (inserted_leaders,))

    def test_09_language_rls_same_mission_and_active_only(self):
        conn = database.connect()
        try:
            with conn.cursor() as cur:
                user_id = str(self.person["profile_id"])
                cur.execute("update public.user_profiles set app_role='DATA_ADMIN',active=true where id=%s", (user_id,))
                cur.execute("insert into public.missions(name) values('Test foreign mission') returning id")
                foreign_mission = cur.fetchone()[0]
                cur.execute("insert into public.zones(mission_id,name) values(%s,'Test foreign zone') returning id", (foreign_mission,))
                foreign_zone = cur.fetchone()[0]
                cur.execute("insert into public.districts(zone_id,name) values(%s,'Test foreign district') returning id", (foreign_zone,))
                foreign_district = cur.fetchone()[0]
                cur.execute("insert into public.areas(district_id,name) values(%s,'Test foreign area') returning id", (foreign_district,))
                foreign_area = cur.fetchone()[0]
                people = []
                for area_id, name in [(self.area["id"], "Same mission"), (foreign_area, "Other mission")]:
                    cur.execute("insert into public.missionaries(last_name,display_name) values(%s,%s) returning id", (name, name))
                    person_id = cur.fetchone()[0]
                    people.append(person_id)
                    cur.execute("insert into public.missionary_assignments(missionary_id,area_id,start_date) values(%s,%s,current_date)", (person_id, area_id))
                    cur.execute("insert into public.missionary_language_assignments(missionary_id,primary_language) values(%s,'de')", (person_id,))
                cur.execute("select set_config('request.jwt.claim.sub',%s,true)", (user_id,))
                cur.execute("set local role authenticated")
                cur.execute("select missionary_id from public.missionary_language_assignments where missionary_id=any(%s)", (people,))
                self.assertEqual([r[0] for r in cur.fetchall()], people[:1])
                cur.execute("reset role")
                cur.execute("update public.user_profiles set active=false where id=%s", (user_id,))
                cur.execute("set local role authenticated")
                cur.execute("select missionary_id from public.missionary_language_assignments where missionary_id=any(%s)", (people,))
                self.assertEqual(cur.fetchall(), [])
        finally:
            conn.rollback()
            conn.close()

    def test_10_portal_jwt_identity_filter_and_failure_closed(self):
        user_id = str(self.person["profile_id"])
        identity = Mock(ok=True)
        identity.json.return_value = {"id": user_id}
        rows = Mock(ok=True)
        rows.json.return_value = [{"user_id": user_id, "leadership_role": "DL"}, {"user_id": user_id, "leadership_role": "ZL"}]
        context = {"user_id": user_id, "management_role": "DATA_ADMIN"}
        with patch.object(sign_in.requests, "get", side_effect=[identity, rows]) as get, patch.object(sign_in, "current_management_context", return_value=context) as live:
            self.assertEqual(sign_in.portal_context("test-token"), context)
            self.assertTrue(get.call_args_list[0].args[0].endswith("/auth/v1/user"))
            self.assertEqual(get.call_args_list[1].kwargs["params"], {"user_id": "eq." + user_id})
            live.assert_called_once_with(user_id)
        rows.json.return_value = [{"user_id": "00000000-0000-0000-0000-000000000000"}]
        with patch.object(sign_in.requests, "get", side_effect=[identity, rows]), patch.object(sign_in, "current_management_context") as live:
            self.assertIsNone(sign_in.portal_context("test-token"))
            live.assert_not_called()
        with patch.object(sign_in.requests, "get", side_effect=sign_in.requests.ConnectionError):
            self.assertIsNone(sign_in.portal_context("test-token"))


    def current_areas(self, count=2):
        with self.context():
            session.update(portal_mission_id=2)
            with database.connect() as conn:
                with database.cursor(conn) as cur:
                    return places.current_areas(cur)[:count]

    def labels_fixture(self, labels, sunday, area):
        fields = [historical.TIMESTAMP_COLUMN, historical.EMAIL_COLUMN, historical.COMPANIONSHIP_COLUMN,
                  historical.UNIT_COLUMN, historical.SUNDAY_COLUMN, "Friends Found - Actual", "Test additional goal"]
        f = tempfile.NamedTemporaryFile(mode="w", suffix=".csv", encoding="utf-8", newline="", delete=False)
        writer = csv.DictWriter(f, fields)
        writer.writeheader()
        for index, label in enumerate(labels):
            writer.writerow({historical.TIMESTAMP_COLUMN: "2000-01-01 10:00:00", historical.EMAIL_COLUMN: "test@example.invalid",
                             historical.COMPANIONSHIP_COLUMN: label, historical.UNIT_COLUMN: f"Ward {index}",
                             historical.SUNDAY_COLUMN: sunday, "Friends Found - Actual": str(index + 2),
                             "Test additional goal": f"Answer {label}"})
        f.close()
        self.addCleanup(lambda: Path(f.name).unlink(missing_ok=True))
        with database.connect() as conn:
            with conn.cursor() as cur:
                for label in labels:
                    cur.execute("""insert into public.import_weekly_planning_area_map
                      (source_companionship,target_area_name,target_area_id,mission_id,match_status,confirmed_at)
                      values(%s,%s,%s,2,'CONFIRMED',now()) on conflict(source_companionship) do update
                      set target_area_id=excluded.target_area_id,target_area_name=excluded.target_area_name,mission_id=2,confirmed_at=now()""",
                      (label, area["name"], area["id"]))
        self.addCleanup(self.delete_mappings, labels)
        return f.name

    def delete_mappings(self, labels):
        with database.connect() as conn:
            with conn.cursor() as cur:
                cur.execute("delete from public.import_weekly_planning_area_map where source_companionship=any(%s)", (list(labels),))

    def details(self, report):
        with database.connect() as conn:
            with database.cursor(conn) as cur:
                cur.execute("""select r.area_id,r.historical_source_area,r.historical_source_key,r.friends_found_actual,
                  d.source_companionship,jsonb_array_length(d.answers) answers from public.weekly_area_reports r
                  left join public.historical_planning_details d on d.weekly_area_report_id=r.id where r.id=%s""", (report,))
                return cur.fetchone()

    def test_11_rereplace_is_idempotent_and_combine_keeps_first_key(self):
        area = self.current_areas(1)[0]
        sunday = "2000-01-23"
        path = self.labels_fixture(["Test combine Beta", "Test combine Alpha"], sunday, area)
        alpha_key = historical.make_report_key("Test combine Alpha", date.fromisoformat(sunday))
        with self.context():
            session.update(portal_mission_id=2, portal_user="Integration test")
            first = historical_apply.apply_batch(path, "combine.csv")
            report = self.scalar("select id from public.weekly_area_reports where historical_source_key=%s", (alpha_key,))
            after_first = self.details(report)
            self.assertEqual(after_first["historical_source_area"], "Test combine Alpha")
            self.assertEqual(after_first["source_companionship"], "Test combine Alpha + Test combine Beta")
            self.assertEqual(after_first["friends_found_actual"], 5)
            second = historical_apply.apply_batch(path, "combine-again.csv")
            self.assertEqual(self.details(report), after_first)
            undo.undo_batch(second)
            self.assertEqual(self.details(report), after_first)
            undo.undo_batch(first)
        self.assertEqual(self.scalar("select count(*) from public.weekly_area_reports where id=%s", (report,)), 0)

    def test_12_remapped_label_moves_its_report_and_undo_restores(self):
        old_area, new_area = self.current_areas(2)
        sunday = "2000-01-30"
        path = self.labels_fixture(["Test remap source"], sunday, old_area)
        key = historical.make_report_key("Test remap source", date.fromisoformat(sunday))
        with self.context():
            session.update(portal_mission_id=2, portal_user="Integration test")
            first = historical_apply.apply_batch(path, "remap.csv")
            report = self.scalar("select id from public.weekly_area_reports where historical_source_key=%s", (key,))
            self.labels_fixture(["Test remap source"], sunday, new_area)
            second = historical_apply.apply_batch(path, "remap-again.csv")
            self.assertEqual(self.scalar("select count(*) from public.weekly_area_reports where historical_source_key=%s", (key,)), 1)
            self.assertEqual(self.details(report)["area_id"], new_area["id"])
            undo.undo_batch(second)
            self.assertEqual(self.details(report)["area_id"], old_area["id"])
            undo.undo_batch(first)

    def test_13_punctuation_collision_requires_a_choice_keep_or_combine(self):
        area = self.current_areas(1)[0]
        sunday = "2000-02-06"
        path = self.labels_fixture(["Test Punct Label", "Test Punct-Label"], sunday, area)
        key = historical.make_report_key("Test Punct Label", date.fromisoformat(sunday))
        count = self.scalar("select count(*) from public.roster_import_batches")
        with self.context():
            session.update(portal_mission_id=2, portal_user="Integration test")
            preview = historical_preview.preview(path)
            self.assertTrue(any("share report key" in e for e in preview["pending"]))
            self.assertEqual([r["label"] for r in preview["choices"]["collisions"][0]["rows"]], ["Test Punct Label", "Test Punct-Label"])
            # The choices table names the indicator New People Being Taught; the file is still read by its old column.
            with self.client.session_transaction() as s:
                s.update(historical_file=str(path), historical_filename="collision.csv")
            page = self.client.get("/historical/review").get_data(as_text=True)
            self.assertIn("<th>New people being taught</th>", page)
            self.assertNotIn("<th>Friends Found</th>", page)
            with self.assertRaisesRegex(ValueError, "share report key"):
                historical_apply.apply_batch(path, "collision.csv")
            with self.assertRaisesRegex(ValueError, "not valid"):
                historical_apply.apply_batch(path, "collision.csv", choices={"collisions": {key: "keep:Someone else"}})
            with self.assertRaisesRegex(ValueError, "no longer matches"):
                historical_apply.apply_batch(path, "collision.csv", choices={"collisions": {"other:2000-02-06": "combine"}})
            keep = {"collisions": {key: "keep:Test Punct-Label"}}
            with self.assertRaisesRegex(ValueError, "changed since"):
                historical_apply.apply_batch(path, "collision.csv", choices=keep, state_token="stale")
            self.assertEqual(self.scalar("select count(*) from public.roster_import_batches"), count)
            token = historical_preview.preview(path, choices=keep)["state_token"]
            batch = historical_apply.apply_batch(path, "collision.csv", choices=keep, state_token=token)
            report = self.scalar("select id from public.weekly_area_reports where historical_source_key=%s", (key,))
            kept = self.details(report)
            self.assertEqual((kept["historical_source_area"], kept["friends_found_actual"]), ("Test Punct-Label", 3))
            undo.undo_batch(batch)
            combine = {"collisions": {key: "combine"}}
            batch = historical_apply.apply_batch(path, "collision.csv", choices=combine)
            report = self.scalar("select id from public.weekly_area_reports where historical_source_key=%s", (key,))
            both = self.details(report)
            self.assertEqual(both["friends_found_actual"], 5)
            self.assertEqual(both["source_companionship"], "Test Punct Label + Test Punct-Label")
            undo.undo_batch(batch)
        self.assertEqual(self.scalar("select count(*) from public.weekly_area_reports where historical_source_key like %s", (key + "%",)), 0)

    def rows_fixture(self, rows, area):
        """rows: (label, ward/branch answer, sunday, friends found). All labels are mapped to `area`."""
        fields = [historical.TIMESTAMP_COLUMN, historical.EMAIL_COLUMN, historical.COMPANIONSHIP_COLUMN,
                  historical.UNIT_COLUMN, historical.SUNDAY_COLUMN, "Friends Found - Actual", "Test additional goal"]
        f = tempfile.NamedTemporaryFile(mode="w", suffix=".csv", encoding="utf-8", newline="", delete=False)
        writer = csv.DictWriter(f, fields)
        writer.writeheader()
        for label, ward, sunday, ff in rows:
            writer.writerow({historical.TIMESTAMP_COLUMN: "2000-01-01 10:00:00", historical.EMAIL_COLUMN: "test@example.invalid",
                             historical.COMPANIONSHIP_COLUMN: label, historical.UNIT_COLUMN: ward, historical.SUNDAY_COLUMN: sunday,
                             "Friends Found - Actual": str(ff), "Test additional goal": f"Answer {label} {ward}"})
        f.close()
        self.addCleanup(lambda: Path(f.name).unlink(missing_ok=True))
        labels = sorted({r[0] for r in rows})
        with database.connect() as conn:
            with conn.cursor() as cur:
                for label in labels:
                    cur.execute("""insert into public.import_weekly_planning_area_map
                      (source_companionship,target_area_name,target_area_id,mission_id,match_status,confirmed_at)
                      values(%s,%s,%s,2,'CONFIRMED',now()) on conflict(source_companionship) do update
                      set target_area_id=excluded.target_area_id,target_area_name=excluded.target_area_name,mission_id=2,confirmed_at=now()""",
                      (label, area["name"], area["id"]))
        self.addCleanup(self.delete_mappings, labels)
        return f.name

    def two_unit_area(self):
        """A current area linked to two active units (like APs: Frankfurt 1st + Frankfurt 2nd (English))."""
        with self.context():
            session.update(portal_mission_id=2)
            with database.connect() as conn:
                with database.cursor(conn) as cur:
                    ids = [a["id"] for a in places.current_areas(cur)]
                    cur.execute("""select au.area_id,array_agg(u.id order by au.primary_unit desc,u.name) unit_ids,
                        array_agg(u.name order by au.primary_unit desc,u.name) unit_names
                      from public.area_units au join public.units u on u.id=au.unit_id
                      where au.active and u.active and au.area_id=any(%s) group by au.area_id
                      having count(distinct u.id)=2 and count(*)=2 order by au.area_id limit 1""", (ids,))
                    found = cur.fetchone()
                    area = next(a for a in places.current_areas(cur) if a["id"] == found["area_id"])
                    return area, found["unit_ids"], found["unit_names"]

    def reports_for(self, area_id, sunday):
        with database.connect() as conn:
            with database.cursor(conn) as cur:
                cur.execute("""select r.id,r.unit_id,r.status,r.friends_found_actual,r.historical_source_key,d.source_companionship,d.source_unit
                  from public.weekly_area_reports r join public.reporting_weeks w on w.id=r.reporting_week_id
                  left join public.historical_planning_details d on d.weekly_area_report_id=r.id
                  where r.area_id=%s and w.sunday=%s order by r.id""", (area_id, sunday))
                return cur.fetchall()

    def existing_unit_reports(self, area, unit_ids, sunday):
        conn, reports = database.connect(), []
        with conn.cursor() as cur:
            cur.execute("insert into public.reporting_weeks(sunday) values(%s) on conflict do nothing", (sunday,))
            cur.execute("select id from public.reporting_weeks where sunday=%s", (sunday,))
            week = cur.fetchone()[0]
            for unit in unit_ids:
                cur.execute("insert into public.weekly_area_reports(area_id,reporting_week_id,unit_id,status) values(%s,%s,%s,'DRAFT') returning id",
                            (area["id"], week, unit))
                reports.append(cur.fetchone()[0])
        conn.commit()

        def cleanup():
            with conn.cursor() as cur:
                cur.execute("delete from public.weekly_area_reports where id=any(%s)", (reports,))
                cur.execute("delete from public.reporting_weeks w where sunday=%s and not exists (select 1 from public.weekly_area_reports r where r.reporting_week_id=w.id)", (sunday,))
            conn.commit()
            conn.close()
        self.addCleanup(cleanup)
        return reports

    def test_14_two_units_same_area_and_week_are_both_imported_and_each_replaces_its_own_report(self):
        area, unit_ids, unit_names = self.two_unit_area()
        sunday = "2000-02-13"
        reports = self.existing_unit_reports(area, unit_ids, sunday)
        path = self.rows_fixture([("Test two-unit A", unit_names[0], sunday, 2), ("Test two-unit B", unit_names[1], sunday, 3)], area)
        with self.context():
            session.update(portal_mission_id=2, portal_user="Integration test")
            for combine in (True, False):  # different units never collide, with or without Combine
                preview = historical_preview.preview(path, combine_mapped=combine)
                self.assertEqual((preview["errors"], preview["pending"]), ([], []))
                self.assertEqual(sorted(r["existing_id"] for r in preview["rows"]), sorted(reports))
            batch = historical_apply.apply_batch(path, "two-units.csv", state_token=historical_preview.preview(path)["state_token"])
            rows = self.reports_for(area["id"], sunday)
            self.assertEqual([(r["id"], r["unit_id"], r["status"], r["friends_found_actual"], r["source_companionship"]) for r in rows],
                             [(reports[0], unit_ids[0], "SUBMITTED", 2, "Test two-unit A"), (reports[1], unit_ids[1], "SUBMITTED", 3, "Test two-unit B")])
            undo.undo_batch(batch)
            self.assertEqual([(r["status"], r["friends_found_actual"]) for r in self.reports_for(area["id"], sunday)], [("DRAFT", 0), ("DRAFT", 0)])

    def test_15_same_companionship_two_units_one_week_keeps_both_reports(self):
        area, unit_ids, unit_names = self.two_unit_area()
        sunday = "2000-02-20"
        label = "Test two-unit same companionship"
        path = self.rows_fixture([(label, unit_names[0], sunday, 4), (label, unit_names[1], sunday, 5)], area)
        base = historical.make_report_key(label, date.fromisoformat(sunday))
        with self.context():
            session.update(portal_mission_id=2, portal_user="Integration test")
            preview = historical_preview.preview(path)
            self.assertEqual((preview["errors"], preview["pending"], preview["duplicates"], len(preview["rows"])), ([], [], 0, 2))
            first = historical_apply.apply_batch(path, "same-two-units.csv")
            rows = self.reports_for(area["id"], sunday)
            self.assertEqual(sorted((r["unit_id"], r["friends_found_actual"], r["historical_source_key"]) for r in rows),
                             sorted([(unit_ids[0], 4, f"{base}@u{unit_ids[0]}"), (unit_ids[1], 5, f"{base}@u{unit_ids[1]}")]))
            second = historical_apply.apply_batch(path, "same-two-units-again.csv")  # re-import is idempotent
            self.assertEqual(self.reports_for(area["id"], sunday), rows)
            undo.undo_batch(second)
            undo.undo_batch(first)
        self.assertEqual(self.reports_for(area["id"], sunday), [])

    def test_16_legacy_unitless_import_moves_into_the_unit_report(self):
        area, unit_ids, unit_names = self.two_unit_area()
        sunday = "2000-02-27"
        label = "Test legacy unitless"
        path = self.rows_fixture([(label, unit_names[1], sunday, 6)], area)
        key = historical.make_report_key(label, date.fromisoformat(sunday))
        with self.context():
            session.update(portal_mission_id=2, portal_user="Integration test")
            first = historical_apply.apply_batch(path, "legacy.csv")
            with database.connect() as conn:  # simulate an import made before units were resolved
                with conn.cursor() as cur:
                    cur.execute("update public.weekly_area_reports set unit_id=null where historical_source_key=%s", (key,))
            preview = historical_preview.preview(path)
            self.assertEqual(preview["errors"], [])
            self.assertTrue(preview["rows"][0].get("moved_from", "").endswith("(no unit)"))
            second = historical_apply.apply_batch(path, "legacy-again.csv")
            rows = self.reports_for(area["id"], sunday)
            self.assertEqual([(r["unit_id"], r["friends_found_actual"]) for r in rows], [(unit_ids[1], 6)])
            undo.undo_batch(second)
            self.assertEqual([r["unit_id"] for r in self.reports_for(area["id"], sunday)], [None])
            with database.connect() as conn:  # revert the simulation so the first batch can be undone (undo refuses later edits)
                with conn.cursor() as cur:
                    cur.execute("update public.weekly_area_reports set unit_id=%s where historical_source_key=%s", (unit_ids[1], key))
            undo.undo_batch(first)
        self.assertEqual(self.reports_for(area["id"], sunday), [])

    def test_17_same_unit_rows_need_one_choice_per_area_with_optional_week_override(self):
        area = self.current_areas(1)[0]
        weeks = ["2000-03-05", "2000-03-12"]
        rows = [(label, "Unrecognised Ward", w, ff) for w in weeks for label, ff in (("Test same-unit A", 2), ("Test same-unit B", 3))]
        path = self.rows_fixture(rows, area)
        with self.context():
            session.update(portal_mission_id=2, portal_user="Integration test")
            preview = historical_preview.preview(path, combine_mapped=False)
            self.assertEqual(len(preview["pending"]), 2)
            self.assertEqual(len(preview["choices"]["merges"]), 1)
            scope = preview["choices"]["merges"][0]["key"]
            self.assertEqual([w["sunday"] for w in preview["choices"]["merges"][0]["weeks"]], [date.fromisoformat(w) for w in weeks])
            with self.assertRaisesRegex(ValueError, "not valid"):
                historical_apply.apply_batch(path, "same-unit.csv", combine_mapped=False, choices={"merges": {scope: "keep:Someone else"}})
            with self.assertRaisesRegex(ValueError, "no longer matches"):
                historical_apply.apply_batch(path, "same-unit.csv", combine_mapped=False, choices={"merges": {scope: "combine", "999|1|2000-01-01": "combine"}})
            choice = {"merges": {scope: "keep:Test same-unit B", f"{scope}|{weeks[1]}": "combine"}}
            preview = historical_preview.preview(path, combine_mapped=False, choices=choice)
            self.assertEqual((preview["errors"], preview["pending"]), ([], []))
            self.assertEqual(len(preview["skipped"]), 1)
            with self.assertRaisesRegex(ValueError, "changed since"):
                historical_apply.apply_batch(path, "same-unit.csv", combine_mapped=False, choices=choice, state_token="tampered")
            batch = historical_apply.apply_batch(path, "same-unit.csv", combine_mapped=False, choices=choice, state_token=preview["state_token"],
                                             expected_choices=json.loads(json.dumps(preview["effective_choices"], default=str)))
            got = [[(r["friends_found_actual"], r["source_companionship"]) for r in self.reports_for(area["id"], w)] for w in weeks]
            self.assertEqual(got, [[(3, "Test same-unit B")], [(5, "Test same-unit A + Test same-unit B")]])
            undo.undo_batch(batch)
        self.assertEqual([self.reports_for(area["id"], w) for w in weeks], [[], []])

    def test_18_unit_can_be_corrected_in_the_preview(self):
        area, unit_ids, unit_names = self.two_unit_area()
        sunday = "2000-03-19"
        reports = self.existing_unit_reports(area, unit_ids, sunday)
        path = self.rows_fixture([("Test unit override", "Test Ward Unknown", sunday, 7)], area)
        with self.context():
            session.update(portal_mission_id=2, portal_user="Integration test")
            preview = historical_preview.preview(path)
            unit_ui = preview["choices"]["units"][0]
            self.assertEqual((unit_ui["confident"], unit_ui["selected"]), (False, unit_ids[0]))  # guessed: area's main unit
            self.assertEqual(preview["rows"][0]["existing_id"], reports[0])
            self.assertTrue(any("did not name a known unit" in n for n in preview["notices"]))
            with self.assertRaisesRegex(ValueError, "not a known unit"):
                historical_apply.apply_batch(path, "override.csv", choices={"units": {unit_ui["key"]: "999999999"}})
            with self.assertRaisesRegex(ValueError, "no longer matches"):
                historical_apply.apply_batch(path, "override.csv", choices={"units": {"Other|1": str(unit_ids[1])}})
            choice = {"units": {unit_ui["key"]: str(unit_ids[1])}}
            preview = historical_preview.preview(path, choices=choice)
            self.assertEqual(preview["rows"][0]["existing_id"], reports[1])
            with self.assertRaisesRegex(ValueError, "do not match the reviewed preview"):
                historical_apply.apply_batch(path, "override.csv", choices=choice, state_token=preview["state_token"],
                                         expected_choices={"collisions": {}, "targets": {}, "units": {unit_ui["key"]: unit_ids[0]}, "merges": {}})
            batch = historical_apply.apply_batch(path, "override.csv", choices=choice, state_token=preview["state_token"],
                                             expected_choices={"collisions": {}, "targets": {}, "units": {unit_ui["key"]: unit_ids[1]}, "merges": {}})
            rows = self.reports_for(area["id"], sunday)
            self.assertEqual([(r["id"], r["status"], r["friends_found_actual"]) for r in rows],
                             [(reports[0], "DRAFT", 0), (reports[1], "SUBMITTED", 7)])
            undo.undo_batch(batch)

    # ------------------------------------------------------------ account roles: effective role, transfers, access
    def role_person(self, number, app_role="MISSIONARY", leaders=(), area=None, ended=None, start="2000-01-01", additional=()):
        """A throw-away missionary with a linked account in `area` (default: the test area), holding `leaders`
        roles from `start` (open, or ending on `ended`) and the `additional` roles. Removed again after the test."""
        area = area or self.area
        email = f"{number.lower()}@example.invalid"
        with database.connect() as conn:
            with database.cursor(conn) as cur:
                cur.execute("""select a.id area_id,a.name area,a.district_id,d.name district,d.zone_id,z.name zone from public.areas a
                  join public.districts d on d.id=a.district_id join public.zones z on z.id=d.zone_id where a.id=%s""", (area["id"],))
                who = dict(cur.fetchone(), number=number, email=email)
                cur.execute("""insert into public.missionaries(missionary_number,first_name,last_name,display_name,missionary_type,status,email)
                  values(%s,'Role','Test',%s,'Elder','Active',%s) returning id""", (number, f"Elder {number}", email))
                who["id"] = cur.fetchone()["id"]
                cur.execute("insert into public.missionary_assignments(missionary_id,area_id,start_date) values(%s,%s,'2000-01-01')", (who["id"], who["area_id"]))
                cur.execute("""insert into auth.users(id,instance_id,aud,role,email)
                  values(gen_random_uuid(),'00000000-0000-0000-0000-000000000000','authenticated','authenticated',%s) returning id""", (email,))
                who["profile_id"] = str(cur.fetchone()["id"])
                cur.execute("insert into public.user_profiles(id,missionary_id,app_role,active) values(%s,%s,%s,true)", (who["profile_id"], who["id"], app_role))
                if additional:
                    cur.execute("update public.user_profiles set additional_roles=%s where id=%s", (list(additional), who["profile_id"]))
                for role in leaders:
                    cur.execute("""insert into public.leadership_assignments(missionary_id,role,district_id,zone_id,mission_id,start_date,end_date)
                      values(%s,%s,%s,%s,%s,%s,%s)""", (who["id"], role, who["district_id"] if role == "DL" else None,
                      who["zone_id"] if role in ("ZL", "STL") else None, 2 if role == "AP" else None, start, ended))
        self.addCleanup(self.remove_person, who)
        return who

    def remove_person(self, who):
        with database.connect() as conn:
            with conn.cursor() as cur:
                cur.execute("delete from auth.users where id=%s", (who["profile_id"],))  # cascades to user_profiles
                for table in ("missionary_language_assignments", "leadership_assignments", "missionary_assignments"):
                    cur.execute(f"delete from public.{table} where missionary_id=%s", (who["id"],))
                cur.execute("delete from public.missionaries where id=%s", (who["id"],))

    def leaders_of(self, who):
        with database.connect() as conn:
            with conn.cursor() as cur:
                cur.execute("select role,start_date,end_date from public.leadership_assignments where missionary_id=%s order by id", (who["id"],))
                return [tuple(r) for r in cur.fetchall()]

    def app_role_of(self, who):
        return self.scalar("select app_role from public.user_profiles where missionary_id=%s", (who["id"],))

    def additional_of(self, who):
        return self.scalar("select additional_roles from public.user_profiles where missionary_id=%s", (who["id"],))

    def active_of(self, who):
        return self.scalar("select active from public.user_profiles where missionary_id=%s", (who["id"],))

    def page_form(self, client, who):
        """The account page and its form exactly as shown, i.e. what the browser submits when nothing else is changed."""
        page = client.get(f"/accounts/{who['id']}").get_data(as_text=True)

        def selected(name):
            block = re.search(rf'<select name="{name}"[^>]*>(.*?)</select>', page, re.S).group(1)
            attrs, text = next((a, t) for a, t in re.findall(r"<option([^>]*)>([^<]*)</option>", block) if re.search(r"\bselected\b", a))
            value = re.search(r'value="([^"]*)"', attrs)
            return value.group(1) if value else text
        form = {"csrf_token": "test-csrf", "role": selected("role"), "area_id": selected("area_id"), "effective_date": date.today().isoformat(),
                "primary_language": "de", "additional_languages": "",
                "state": html.unescape(re.search(r'<input type="hidden" name="state" value="([^"]*)">', page).group(1))}
        if re.search(r'name="active" value="yes"[^>]*\bchecked\b', page):
            form["active"] = "yes"
        if 'name="additional_shown" value="yes"' in page:  # the additional-role boxes, as ticked on the page
            form["additional_shown"] = "yes"
            form["additional"] = re.findall(r'name="additional" value="([A-Z_]+)"[^>]*\bchecked\b', page)
        return page, form

    def plan_of(self, client, who, form, **change):
        """The "What saving will change" box for these form values, as the page fetches it."""
        query = {k: form[k] for k in ("role", "area_id", "effective_date")} | {"additional": ",".join(form.get("additional", []))} | change
        return client.get(f"/accounts/{who['id']}/role-plan", query_string=query).get_json()

    def ap_context(self, who):
        return (sign_in.current_management_context(who["profile_id"]) or {}).get("management_role")

    def admin_client(self, who, role):
        client = app.app.test_client()
        with client.session_transaction() as s:
            s.update(authenticated=True, portal_user_id=who["profile_id"], portal_role=role, portal_mission_id=2,
                     portal_expires_at=time.time() + 1800, csrf_token="test-csrf")
        return client

    def test_19_leader_page_save_with_unchanged_role_keeps_the_leadership_row(self):
        zl = self.role_person("TEST-ROLE-ZL", leaders=["ZL"])  # like live: an open ZL row, app_role still MISSIONARY
        page, form = self.page_form(self.client, zl)
        self.assertEqual(self.client.post(f"/accounts/{zl['id']}/update", data=form).status_code, 302)
        self.assertEqual(self.leaders_of(zl), [("ZL", date(2000, 1, 1), None)])
        self.assertEqual(form["role"], "ZL")
        self.assertIn(f"The current ZL assignment for {zl['zone']} zone stays as it is.", page)
        self.assertIn("Recorded account role: Missionary → ZL.", page)
        self.assertEqual(self.app_role_of(zl), "ZL")
        page, form = self.page_form(self.client, zl)  # reopened after the save, which it confirms in a message
        self.assertIn('<div class="flash">Recorded account role: Missionary → ZL.</div>', page)
        self.assertEqual(form["role"], "ZL")
        self.assertEqual((self.plan_of(self.client, zl, form)["lines"]), [f"The current ZL assignment for {zl['zone']} zone stays as it is."])
        self.assertIn("No change to the role or leadership assignments.", self.page_form(self.client, self.role_person("TEST-ROLE-M"))[0])
        form["effective_date"] = "2000-01-01"  # on the ZL start date: nothing to end, so this is fine too
        self.assertEqual(self.client.post(f"/accounts/{zl['id']}/update", data=form).status_code, 302)
        self.assertEqual((self.leaders_of(zl), self.app_role_of(zl)), ([("ZL", date(2000, 1, 1), None)], "ZL"))

    def test_20_role_change_ends_the_leadership_row_and_the_page_says_so(self):
        zl = self.role_person("TEST-ROLE-ZL2", leaders=["ZL"])
        _, form = self.page_form(self.client, zl)
        plan = self.plan_of(self.client, zl, form, role="MISSIONARY", effective_date="2099-01-10")
        self.assertEqual(plan["ends"], 1)
        self.assertIn(f"Changing the role ends the current ZL assignment for {zl['zone']} zone on 09 Jan 2099.", plan["lines"])
        # On the ZL start date the box shows only the error, not also an "ends ... on" line that cannot happen.
        plan = self.plan_of(self.client, zl, form, role="MISSIONARY", effective_date="2000-01-01")
        self.assertEqual((plan["ends"], plan["errors"]), (0, [f"The effective date must be after 01 Jan 2000, when the current ZL assignment for {zl['zone']} zone started."]))
        self.assertFalse([l for l in plan["lines"] if "ends the current ZL" in l])
        form.update(role="MISSIONARY", effective_date="2000-01-01")  # on the ZL start date: refused, nothing saved
        response = self.client.post(f"/accounts/{zl['id']}/update", data=form)
        self.assertEqual(response.status_code, 400)
        self.assertIn("must be after 01 Jan 2000", response.get_data(as_text=True))
        self.assertEqual((self.leaders_of(zl), self.app_role_of(zl)), ([("ZL", date(2000, 1, 1), None)], "MISSIONARY"))
        form["effective_date"] = "2099-01-10"
        self.assertEqual(self.client.post(f"/accounts/{zl['id']}/update", data=form).status_code, 302)
        self.assertEqual((self.leaders_of(zl), self.app_role_of(zl)), ([("ZL", date(2000, 1, 1), date(2099, 1, 9))], "MISSIONARY"))

    def test_21_moving_a_dl_changes_the_row_only_when_the_district_changes(self):
        areas = self.current_areas(1000)
        home = next((a for a in areas if sum(b["district_id"] == a["district_id"] for b in areas) > 1), None)
        if not home:
            self.skipTest("No district with two current areas in this copy.")
        same = next(a for a in areas if a["district_id"] == home["district_id"] and a["id"] != home["id"])
        other = next(a for a in areas if a["district_id"] != home["district_id"])
        dl = self.role_person("TEST-ROLE-DL", leaders=["DL"], area=home)
        _, form = self.page_form(self.client, dl)
        form.update(area_id=str(same["id"]), effective_date="2099-02-01")
        self.assertEqual(self.client.post(f"/accounts/{dl['id']}/update", data=form).status_code, 302)
        self.assertEqual((self.leaders_of(dl), self.app_role_of(dl)), ([("DL", date(2000, 1, 1), None)], "DL"))
        page, form = self.page_form(self.client, dl)  # reopened after the save: today's area, as the portal shows it
        self.assertEqual(form["area_id"], str(home["id"]))
        form.update(area_id=str(other["id"]), effective_date="2099-03-01")
        self.assertIn("is already saved", self.plan_of(self.client, dl, form)["errors"][0])  # one move ahead at a time
        stay = re.search(r'<option value="(-\d+)"', page).group(1)  # "stay here" takes the move back
        self.assertEqual(self.client.post(f"/accounts/{dl['id']}/update", data={**form, "area_id": stay}).status_code, 302)
        _, form = self.page_form(self.client, dl)
        form.update(area_id=str(other["id"]), effective_date="2099-03-01")
        plan = self.plan_of(self.client, dl, form)
        self.assertEqual(plan["lines"][:2], [f"Moving to {other['name']} ends the current DL assignment for {home['district']} district on 28 Feb 2099.",
                                             f"A new DL assignment for {other['district']} district starts on 01 Mar 2099."])
        self.assertEqual(self.client.post(f"/accounts/{dl['id']}/update", data=form).status_code, 302)
        self.assertEqual(self.leaders_of(dl), [("DL", date(2000, 1, 1), date(2099, 2, 28)), ("DL", date(2099, 3, 1), None)])
        self.assertEqual(self.app_role_of(dl), "DL")  # still a DL today, so the recorded role stays

    def test_22_ap_by_assignment_can_save_own_page_but_not_remove_own_access(self):
        ap = self.role_person("TEST-ROLE-AP", leaders=["AP"])  # management access only through the AP row
        client = self.admin_client(ap, "AP")
        _, form = self.page_form(client, ap)
        self.assertEqual(client.post(f"/accounts/{ap['id']}/update", data=form).status_code, 302)
        self.assertEqual((form["role"], self.leaders_of(ap), self.app_role_of(ap)), ("AP", [("AP", date(2000, 1, 1), None)], "AP"))
        _, form = self.page_form(client, ap)  # reopened after the save
        for change in ({"role": "MISSIONARY"}, {"role": "MISSIONARY", "effective_date": "2099-01-01"}, {"active": ""}):
            response = client.post(f"/accounts/{ap['id']}/update", data={**form, **change})
            self.assertEqual(response.status_code, 400)
            self.assertIn("Use another administrator", response.get_data(as_text=True))
            if change.get("effective_date"):  # a later end names its date
                self.assertIn("Saving this ends your own DA Management access from 01 Jan 2099.", response.get_data(as_text=True))
        self.assertEqual((self.leaders_of(ap), self.app_role_of(ap)), ([("AP", date(2000, 1, 1), None)], "AP"))

    def roster_row(self, who, roles):
        return {"missionary_number": who["number"], "first_name": "Role", "last_name": "Test", "display_name": f"Elder {who['number']}",
                "missionary_type": "Elder", "arrival_date": None, "release_date": None, "email": who["email"], "zone": who["zone"],
                "district": who["district"], "area": who["area"], "units": [], "position": None, "position_abbr": None,
                "special_assignment": None, "roles": set(roles)}

    def test_23_transfer_ending_ap_resets_the_saved_role_and_undo_restores_it(self):
        former = self.role_person("TEST-ROLE-FORMER-AP", "AP", ["AP"])
        staying = self.role_person("TEST-ROLE-STAYING-AP", "AP", ["AP"])
        admin = self.role_person("TEST-ROLE-ADMIN-DL", "DATA_ADMIN", ["DL"])
        rows = [self.roster_row(former, []), self.roster_row(staying, ["AP"]), self.roster_row(admin, [])]
        preview = transfer.preview(rows, 2)
        with database.connect() as conn: before = batches.snapshot(conn, batches.TRANSFER_TABLES)
        with self.context():
            session.update(portal_mission_id=2)
            batch = transfer.apply_roster_batch(rows, 2, date(2099, 1, 2), "roles.csv")
            try:
                applied = ([self.app_role_of(w) for w in (former, staying, admin)], [self.leaders_of(w) for w in (former, staying, admin)],
                           self.scalar("""select count(*) from public.roster_import_changes where batch_id=%s and table_name='user_profiles'
                             and row_key->>'id'=%s and after_row->>'app_role'='MISSIONARY'""", (batch, former["profile_id"])))
            finally:
                undo.undo_batch(batch)
        self.assertEqual(applied, (["MISSIONARY", "AP", "DATA_ADMIN"],
                                   [[("AP", date(2000, 1, 1), date(2099, 1, 1))], [("AP", date(2000, 1, 1), None)], [("DL", date(2000, 1, 1), date(2099, 1, 1))]], 1))
        self.assertIn("Elder TEST-ROLE-FORMER-AP: AP → Missionary", preview.get("role_resets", []))
        self.assertFalse([r for r in preview["role_resets"] if "STAYING" in r or "ADMIN-DL" in r])
        self.assertEqual([self.app_role_of(w) for w in (former, staying, admin)], ["AP", "AP", "DATA_ADMIN"])
        self.assertEqual(self.leaders_of(former), [("AP", date(2000, 1, 1), None)])
        with database.connect() as conn: self.assertEqual(batches.snapshot(conn, batches.TRANSFER_TABLES), before)

    def test_24_former_ap_loses_management_access(self):
        former = self.role_person("TEST-ROLE-OLD-AP", "AP", ["AP"], ended=date.today() - timedelta(days=1))  # saved role still AP
        stale = self.role_person("TEST-ROLE-STALE-AP", "AP")  # AP saved by hand, never an AP assignment
        current = self.role_person("TEST-ROLE-NEW-AP", "MISSIONARY", ["AP"])
        admin = self.role_person("TEST-ROLE-DA", "DATA_ADMIN")
        self.assertEqual([(sign_in.current_management_context(w["profile_id"]) or {}).get("management_role") for w in (former, stale, current, admin)],
                         [None, None, "AP", "DATA_ADMIN"])
        identity, rows = Mock(ok=True), Mock(ok=True)
        identity.json.return_value = {"id": former["profile_id"]}
        rows.json.return_value = [{"user_id": former["profile_id"]}]
        with patch.object(sign_in.requests, "get", side_effect=[identity, rows]):
            self.assertEqual(app.app.test_client().get("/?portal_token=opaque-test-token").status_code, 403)
        client = self.admin_client(former, "AP")  # a session opened while they were still AP
        self.assertEqual(client.get("/accounts").status_code, 302)
        with client.session_transaction() as s: self.assertNotIn("authenticated", s)

    def test_25_a_page_opened_before_a_change_is_not_saved(self):
        zl = self.role_person("TEST-ROLE-STALE-PAGE", leaders=["ZL"])
        _, form = self.page_form(self.client, zl)
        languages = "select count(*) from public.missionary_language_assignments where missionary_id=%s"
        later = date.today() + timedelta(days=3)
        with database.connect() as conn:  # meanwhile a transfer dated ahead ends the ZL assignment
            with conn.cursor() as cur:
                cur.execute("update public.leadership_assignments set end_date=%s where missionary_id=%s", (later, zl["id"]))
        response = self.client.post(f"/accounts/{zl['id']}/update", data=form)
        self.assertEqual(response.status_code, 400)
        self.assertIn("changed since you opened the page", response.get_data(as_text=True))
        self.assertEqual((self.leaders_of(zl), self.app_role_of(zl)), ([("ZL", date(2000, 1, 1), later)], "MISSIONARY"))
        self.assertEqual(self.scalar(languages, (zl["id"],)), 0)  # the languages were not saved either
        del form["state"]  # a form without the page's state is refused too
        self.assertEqual(self.client.post(f"/accounts/{zl['id']}/update", data=form).status_code, 400)
        self.assertEqual(self.app_role_of(zl), "MISSIONARY")

    def test_26_assignments_that_start_or_end_later(self):
        soon = date.today() + timedelta(days=5)
        # An incoming AP whose assignment starts later is not an AP yet: no role, no access, nothing recorded early.
        incoming = self.role_person("TEST-ROLE-INCOMING-AP", leaders=["AP"], start="2099-01-01")
        page, form = self.page_form(self.client, incoming)
        self.assertEqual(form["role"], "MISSIONARY")
        self.assertIn("Starting later: AP assignment for the whole mission from 01 Jan 2099", page)
        self.assertIn("The AP assignment for the whole mission (starts 01 Jan 2099) stays as it is.", page)
        self.assertEqual(self.client.post(f"/accounts/{incoming['id']}/update", data=form).status_code, 302)
        plan = self.plan_of(self.client, incoming, form, role="AP")
        self.assertIn("The recorded account role changes to AP only when this page is saved again on or after 01 Jan 2099, "
                      "when the AP assignment starts.", plan["lines"])
        self.assertFalse([l for l in plan["lines"] if l.startswith("Recorded account role") or "DA Management" in l])
        _, form = self.page_form(self.client, incoming)
        self.assertEqual(self.client.post(f"/accounts/{incoming['id']}/update", data={**form, "role": "AP"}).status_code, 302)
        self.assertEqual((self.leaders_of(incoming), self.app_role_of(incoming), self.ap_context(incoming)),
                         ([("AP", date(2099, 1, 1), None)], "MISSIONARY", None))
        # A new AP assignment chosen here with a later date is recorded (and grants access) only from that date.
        newer = self.role_person("TEST-ROLE-LATER-AP")
        _, form = self.page_form(self.client, newer)
        plan = self.plan_of(self.client, newer, form, role="AP", effective_date="2099-02-01")
        self.assertEqual(plan["lines"][:2], ["A new AP assignment for the whole mission starts on 01 Feb 2099.",
                                             "They get DA Management access from 01 Feb 2099."])
        self.assertEqual(self.client.post(f"/accounts/{newer['id']}/update", data={**form, "role": "AP", "effective_date": "2099-02-01"}).status_code, 302)
        self.assertEqual((self.leaders_of(newer), self.app_role_of(newer), self.ap_context(newer)),
                         ([("AP", date(2099, 2, 1), None)], "MISSIONARY", None))
        # An outgoing AP (a transfer dated ahead ended the assignment) is still AP until then; saving keeps the
        # assignment and its end date, and the recorded role becomes Missionary so it cannot outlast the assignment.
        outgoing = self.role_person("TEST-ROLE-OUTGOING-AP", "AP", ["AP"], ended=soon)
        page, form = self.page_form(self.client, outgoing)
        self.assertEqual(form["role"], "AP")
        self.assertIn(f"The current AP assignment for the whole mission stays as it is and ends on {day(soon)}.", page)
        self.assertIn(f"The recorded account role is not AP because the AP assignment ends on {day(soon)}.", page)
        self.assertEqual(self.client.post(f"/accounts/{outgoing['id']}/update", data=form).status_code, 302)
        self.assertEqual((self.leaders_of(outgoing), self.app_role_of(outgoing), self.ap_context(outgoing)),
                         ([("AP", date(2000, 1, 1), soon)], "MISSIONARY", "AP"))
        # A ZL until a later date is ZL today (the zone checks also need the assignment, so ZL may be recorded).
        zl = self.role_person("TEST-ROLE-OUTGOING-ZL", leaders=["ZL"], ended=soon)
        page, form = self.page_form(self.client, zl)
        self.assertEqual(form["role"], "ZL")
        self.assertIn(f"ZL, from the ZL assignment for {zl['zone']} zone since 01 Jan 2000, ending {day(soon)}", page)
        # Ending it later than the roster already does is not an extension: the earlier end date stays.
        plan = self.plan_of(self.client, zl, form, role="MISSIONARY", effective_date=(soon + timedelta(days=30)).isoformat())
        self.assertEqual(plan["ends"], 0)
        self.assertIn(f"The current ZL assignment for {zl['zone']} zone already ends on {day(soon)}.", plan["lines"])
        self.assertEqual(self.client.post(f"/accounts/{zl['id']}/update", data=form).status_code, 302)
        self.assertEqual((self.leaders_of(zl), self.app_role_of(zl)), ([("ZL", date(2000, 1, 1), soon)], "ZL"))
        _, form = self.page_form(self.client, zl)
        self.assertEqual(self.client.post(f"/accounts/{zl['id']}/update", data={**form, "role": "MISSIONARY",
                         "effective_date": (soon + timedelta(days=30)).isoformat()}).status_code, 302)
        self.assertEqual((self.leaders_of(zl), self.app_role_of(zl)), ([("ZL", date(2000, 1, 1), soon)], "MISSIONARY"))

    def test_27_transfer_preview_lists_roles_to_record_by_hand(self):
        new_zl = self.role_person("TEST-ROLE-NEW-ZL")
        known_zl = self.role_person("TEST-ROLE-KNOWN-ZL", "ZL", ["ZL"])
        new_dl = self.role_person("TEST-ROLE-NEW-DL")
        stale_ap = self.role_person("TEST-ROLE-STALE-AP-ZL", "AP")
        rows = [self.roster_row(new_zl, ["ZL"]), self.roster_row(known_zl, ["ZL"]), self.roster_row(new_dl, ["DL"]),
                self.roster_row(stale_ap, ["ZL"])]
        preview = transfer.preview(rows, 2)
        mine = lambda key: sorted(x for x in preview[key] if "TEST-ROLE-" in x)
        self.assertEqual(mine("role_records"), ["Elder TEST-ROLE-NEW-ZL: ZL (account role: Missionary)",
                                                "Elder TEST-ROLE-STALE-AP-ZL: ZL (account role: Missionary)"])
        self.assertEqual(mine("role_resets"), ["Elder TEST-ROLE-STALE-AP-ZL: AP → Missionary"])

    def test_28_a_transfer_that_ends_your_own_ap_access_needs_an_extra_tick(self):
        ap = self.role_person("TEST-ROLE-APPLYING-AP", leaders=["AP"])  # DA Management access only through the AP row
        client = self.admin_client(ap, "AP")
        rows = [self.roster_row(ap, [])]  # the roster no longer lists them as AP
        upload = lambda day: client.post("/preview", data={"csrf_token": "test-csrf", "mission_id": "2", "transfer_date": day.isoformat(),
                                                           "file": (io.BytesIO(b"test roster"), "roster.csv")}, content_type="multipart/form-data")
        batch_count = self.scalar("select count(*) from public.roster_import_batches")
        with patch.object(roster_file, "read_roster", return_value=rows):
            later = date.today() + timedelta(days=7)
            page = upload(later).get_data(as_text=True)
            self.assertIn(f"This transfer ends your own DA Management access on {day(later)}.", page)
            self.assertNotIn('name="own_access"', page.replace("'", '"'))
            page = upload(date.today()).get_data(as_text=True)
            self.assertIn("This transfer ends your own DA Management access as soon as you apply it.", page)
            self.assertIn('name="own_access"', page.replace("'", '"'))
            response = client.post("/apply", data={"csrf_token": "test-csrf", "confirmed": "yes"})
            self.assertIn("tick the box", response.get_data(as_text=True))
            self.assertEqual((self.scalar("select count(*) from public.roster_import_batches"), self.leaders_of(ap), self.ap_context(ap)),
                             (batch_count, [("AP", date(2000, 1, 1), None)], "AP"))
            self.assertIsNone(transfer.own_access_loss(rows, date.today(), None))  # fallback-password sessions have no portal user
            self.assertIsNone(transfer.own_access_loss([self.roster_row(ap, ["AP"])], date.today(), ap["profile_id"]))
            with database.connect() as conn: before = batches.snapshot(conn, batches.TRANSFER_TABLES)
            response = client.post("/apply", data={"csrf_token": "test-csrf", "confirmed": "yes", "own_access": "yes"})
            batch = self.scalar("select id::text from public.roster_import_batches order by created_at desc limit 1")
            try:
                self.assertEqual(response.status_code, 200)
                self.assertIn("Your own DA Management access ended with this transfer", response.get_data(as_text=True))
                self.assertIsNone(self.ap_context(ap))
                self.assertEqual(client.get(f"/imports/{batch}").status_code, 302)
            finally:
                with self.context():
                    session.update(portal_mission_id=2, portal_user="Integration test")
                    undo.undo_batch(batch)
        with database.connect() as conn: self.assertEqual(batches.snapshot(conn, batches.TRANSFER_TABLES), before)
        self.assertEqual(self.ap_context(ap), "AP")

    # ------------------------------------------------------------ additional roles: Data Analyst and Office (migration 021)
    def test_29_dl_who_becomes_data_analyst_keeps_the_dl_assignment(self):
        dl = self.role_person("TEST-ROLE-DL-DA", leaders=["DL"])
        page, form = self.page_form(self.client, dl)
        self.assertEqual((form["role"], form["additional"]), ("DL", []))
        self.assertIn("Data Analyst", page)
        self.assertNotIn("Data Admin", page)
        # Round 3 wording: the main roles spelled out, one line per additional role and for the President.
        self.assertIn('<option value="DL" selected>District leader (DL)</option>', page)
        self.assertIn('<option value="PRESIDENT" >President</option>', page)
        self.assertIn("<legend>Additional roles (optional)</legend>", page)
        self.assertIn(account_page.ADDITIONAL_NOTE, page)
        self.assertIn(html.escape(account_page.ADDITIONAL_HELP["DATA_ADMIN"]), page)
        self.assertIn(account_page.ADDITIONAL_HELP["OFFICE"], page)
        self.assertIn(account_page.PRESIDENT_HELP, page)
        plan = self.plan_of(self.client, dl, form, additional="DATA_ADMIN")
        self.assertEqual((plan["ends"], plan["own"]), (0, 0))
        self.assertIn("Adds the additional role Data Analyst.", plan["lines"])
        self.assertIn("They get DA Management access now.", plan["lines"])
        self.assertIn(f"The current DL assignment for {dl['district']} district stays as it is.", plan["lines"])
        form["additional"] = ["DATA_ADMIN"]
        self.assertEqual(self.client.post(f"/accounts/{dl['id']}/update", data=form).status_code, 302)
        self.assertEqual((self.leaders_of(dl), self.app_role_of(dl), self.additional_of(dl)),
                         ([("DL", date(2000, 1, 1), None)], "DL", ["DATA_ADMIN"]))
        self.assertEqual(self.ap_context(dl), "DATA_ADMIN")
        page, form = self.page_form(self.client, dl)  # reopened after the save
        self.assertEqual((form["role"], form["additional"]), ("DL", ["DATA_ADMIN"]))
        self.assertIn("leadership assignment is unchanged.", page)  # only an additional role changed
        self.assertIn("Additional roles: Data Analyst", page)
        self.assertIn("Adds the additional role Data Analyst.", page)  # the flash after saving
        listing = self.client.get("/accounts", query_string={"q": "TEST-ROLE-DL-DA"}).get_data(as_text=True)
        self.assertIn("DL, Data Analyst", listing)
        # Office as well, then Data Analyst removed again: the DL assignment stays through every save.
        form["additional"] = ["DATA_ADMIN", "OFFICE"]
        self.assertEqual(self.client.post(f"/accounts/{dl['id']}/update", data=form).status_code, 302)
        _, form = self.page_form(self.client, dl)
        form["additional"] = ["OFFICE"]
        plan = self.plan_of(self.client, dl, form)
        self.assertIn("Removes the additional role Data Analyst.", plan["lines"])
        self.assertIn("They lose DA Management access now.", plan["lines"])
        self.assertEqual(self.client.post(f"/accounts/{dl['id']}/update", data=form).status_code, 302)
        self.assertEqual((self.leaders_of(dl), self.app_role_of(dl), self.additional_of(dl), self.ap_context(dl)),
                         ([("DL", date(2000, 1, 1), None)], "DL", ["OFFICE"], None))

    def test_30_office_alone_gives_no_management_access(self):
        office = self.role_person("TEST-ROLE-OFFICE")
        _, form = self.page_form(self.client, office)
        plan = self.plan_of(self.client, office, form, additional="OFFICE")
        self.assertEqual(plan["lines"], ["Adds the additional role Office."])
        form["additional"] = ["OFFICE"]
        self.assertEqual(self.client.post(f"/accounts/{office['id']}/update", data=form).status_code, 302)
        self.assertEqual((self.app_role_of(office), self.additional_of(office), self.ap_context(office)), ("MISSIONARY", ["OFFICE"], None))
        self.assertIsNone(roles.management_role("MISSIONARY", None, ["OFFICE"]))
        self.assertEqual(roles.management_role("MISSIONARY", "DL", ["OFFICE", "DATA_ADMIN"]), "DATA_ADMIN")
        self.assertEqual(roles.management_role("PRESIDENT", None, ["DATA_ADMIN"]), "PRESIDENT")
        self.assertEqual(roles.management_role("MISSIONARY", "AP", ["OFFICE"]), "AP")
        with patch.object(sign_in, "portal_context", return_value={"app_role": "MISSIONARY", "additional_roles": ["OFFICE"], "user_active": True}):
            self.assertEqual(app.app.test_client().get("/?portal_token=opaque-test-token").status_code, 403)
        # Unknown values and an old page without the boxes: refused, or the saved additional roles are kept.
        _, form = self.page_form(self.client, office)
        self.assertEqual(self.client.post(f"/accounts/{office['id']}/update", data={**form, "additional": ["AP"]}).status_code, 400)
        old_page = {k: v for k, v in form.items() if k not in ("additional", "additional_shown")}
        self.assertEqual(self.client.post(f"/accounts/{office['id']}/update", data=old_page).status_code, 302)
        self.assertEqual(self.additional_of(office), ["OFFICE"])

    def test_31_removing_your_own_data_analyst_role_needs_the_tick(self):
        da = self.role_person("TEST-ROLE-OWN-DA", leaders=["DL"], additional=["DATA_ADMIN"])
        client = self.admin_client(da, "DATA_ADMIN")
        page, form = self.page_form(client, da)
        self.assertEqual(form["additional"], ["DATA_ADMIN"])
        self.assertRegex(page, r'<label class="role-choice" id="ownAccess" hidden>')  # nothing to confirm yet
        form["additional"] = []
        plan = self.plan_of(client, da, form)
        self.assertEqual(plan["own"], 1)
        self.assertEqual(plan["lines"][0], "This ends your own DA Management access. Tick the box below to confirm, or ask "
                                           "another administrator to make this change.")
        self.assertEqual(plan["own_text"], "Saving ends my own DA Management access. I cannot give it back to myself.")
        response = client.post(f"/accounts/{da['id']}/update", data=form)
        self.assertEqual(response.status_code, 400)
        self.assertIn("Use another administrator", response.get_data(as_text=True))
        self.assertEqual((self.additional_of(da), self.ap_context(da)), (["DATA_ADMIN"], "DATA_ADMIN"))
        response = client.post(f"/accounts/{da['id']}/update", data={**form, "own_access": "yes"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("Your own DA Management access has ended", response.get_data(as_text=True))
        self.assertEqual((self.additional_of(da), self.leaders_of(da), self.ap_context(da)), ([], [("DL", date(2000, 1, 1), None)], None))
        self.assertEqual(client.get("/accounts").status_code, 302)  # signed out of DA Management
        # Turning your own account off stays refused, tick or not.
        da2 = self.role_person("TEST-ROLE-OWN-DA2", additional=["DATA_ADMIN"])
        client = self.admin_client(da2, "DATA_ADMIN")
        _, form = self.page_form(client, da2)
        del form["active"]
        response = client.post(f"/accounts/{da2['id']}/update", data={**form, "own_access": "yes"})
        self.assertEqual(response.status_code, 400)
        self.assertIn("Use another administrator", response.get_data(as_text=True))
        # Another administrator's page needs no tick to remove someone else's Data Analyst role.
        _, form = self.page_form(self.client, da2)
        self.assertEqual(self.client.post(f"/accounts/{da2['id']}/update", data={**form, "additional": []}).status_code, 302)
        self.assertEqual(self.additional_of(da2), [])

    def test_34_an_ap_gives_or_takes_the_data_analyst_and_president_roles(self):
        # APs have full rights (owner, 28 Sep): the same as the President and a Data Analyst.
        ap = self.role_person("TEST-ROLE-HIGH-AP", leaders=["AP"])
        client = self.admin_client(ap, "AP")
        dl = self.role_person("TEST-ROLE-HIGH-DL", leaders=["DL"])
        # An AP may give the Data Analyst role (and Office).
        _, form = self.page_form(client, dl)
        response = client.post(f"/accounts/{dl['id']}/update", data={**form, "additional": ["DATA_ADMIN"]})
        self.assertEqual(response.status_code, 302, response.get_data(as_text=True))
        self.assertEqual((self.additional_of(dl), self.ap_context(dl)), (["DATA_ADMIN"], "DATA_ADMIN"))
        _, form = self.page_form(client, dl)
        self.assertEqual(client.post(f"/accounts/{dl['id']}/update", data={**form, "additional": ["DATA_ADMIN", "OFFICE"]}).status_code, 302)
        self.assertEqual(self.additional_of(dl), ["DATA_ADMIN", "OFFICE"])
        # An AP may take the Data Analyst role away from someone.
        da = self.role_person("TEST-ROLE-HIGH-DA", leaders=["DL"], additional=["DATA_ADMIN"])
        _, form = self.page_form(client, da)
        self.assertEqual(form["additional"], ["DATA_ADMIN"])
        self.assertEqual(client.post(f"/accounts/{da['id']}/update", data={**form, "additional": []}).status_code, 302)
        self.assertEqual((self.additional_of(da), self.ap_context(da)), ([], None))
        # An AP may give the President role, and take it away again.
        other = self.role_person("TEST-ROLE-HIGH-OTHER")
        _, form = self.page_form(client, other)
        self.assertEqual(self.plan_of(client, other, form, role="PRESIDENT")["errors"], [])
        response = client.post(f"/accounts/{other['id']}/update", data={**form, "role": "PRESIDENT"})
        self.assertEqual(response.status_code, 302, response.get_data(as_text=True))
        self.assertEqual((self.app_role_of(other), self.ap_context(other)), ("PRESIDENT", "PRESIDENT"))
        _, form = self.page_form(client, other)
        self.assertEqual(client.post(f"/accounts/{other['id']}/update", data={**form, "role": "MISSIONARY"}).status_code, 302)
        self.assertEqual((self.app_role_of(other), self.ap_context(other)), ("MISSIONARY", None))
        # The same for the President's own account.
        president = self.role_person("TEST-ROLE-HIGH-PRES", "PRESIDENT")
        _, form = self.page_form(client, president)
        self.assertEqual(form["role"], "PRESIDENT")
        self.assertEqual(client.post(f"/accounts/{president['id']}/update", data={**form, "role": "MISSIONARY"}).status_code, 302)
        self.assertEqual((self.app_role_of(president), self.ap_context(president)), ("MISSIONARY", None))
        # A Data Analyst still may too.
        analyst = self.admin_client(dl, "DATA_ADMIN")
        _, form = self.page_form(analyst, president)
        self.assertEqual(analyst.post(f"/accounts/{president['id']}/update", data={**form, "role": "PRESIDENT"}).status_code, 302)
        self.assertEqual((self.app_role_of(president), self.ap_context(president)), ("PRESIDENT", "PRESIDENT"))

    def test_35_an_ap_changes_their_own_roles_and_the_presidents_account(self):
        ap = self.role_person("TEST-ROLE-SELF-AP", leaders=["AP"])
        client = self.admin_client(ap, "AP")
        # An AP may give themselves the Data Analyst role. Their access stays, so there is nothing to confirm.
        _, form = self.page_form(client, ap)
        self.assertEqual(form["additional"], [])
        plan = self.plan_of(client, ap, form, additional="DATA_ADMIN")
        self.assertEqual((plan["errors"], plan["own"]), ([], 0))
        response = client.post(f"/accounts/{ap['id']}/update", data={**form, "additional": ["OFFICE", "DATA_ADMIN"]})
        self.assertEqual(response.status_code, 302, response.get_data(as_text=True))
        self.assertEqual((self.additional_of(ap), self.ap_context(ap)), (["DATA_ADMIN", "OFFICE"], "DATA_ADMIN"))
        # ...and take it away again: the AP assignment still gives access, so no tick either.
        _, form = self.page_form(client, ap)
        self.assertEqual(client.post(f"/accounts/{ap['id']}/update", data={**form, "additional": ["OFFICE"]}).status_code, 302)
        self.assertEqual((self.additional_of(ap), self.ap_context(ap)), (["OFFICE"], "AP"))
        # An AP may make themselves President ("Yes, everything"). Changing the main role ends the AP assignment.
        second = self.role_person("TEST-ROLE-SELF-AP2", leaders=["AP"])
        own = self.admin_client(second, "AP")
        _, form = self.page_form(own, second)
        self.assertEqual(own.post(f"/accounts/{second['id']}/update", data={**form, "role": "PRESIDENT"}).status_code, 302)
        yesterday = date.today() - timedelta(days=1)
        self.assertEqual((self.app_role_of(second), self.leaders_of(second), self.ap_context(second)),
                         ("PRESIDENT", [("AP", date(2000, 1, 1), yesterday)], "PRESIDENT"))
        # Taking away your own President role ends your own access: that still needs the "I understand" tick.
        _, form = self.page_form(own, second)
        form["role"] = "MISSIONARY"
        self.assertEqual(self.plan_of(own, second, form)["own"], 1)
        response = own.post(f"/accounts/{second['id']}/update", data=form)
        self.assertEqual(response.status_code, 400)
        self.assertIn("Use another administrator", response.get_data(as_text=True))
        self.assertEqual(self.app_role_of(second), "PRESIDENT")
        response = own.post(f"/accounts/{second['id']}/update", data={**form, "own_access": "yes"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("Ask an AP, the President or a Data Analyst if you need it again.", response.get_data(as_text=True))
        self.assertEqual((self.app_role_of(second), self.ap_context(second)), ("MISSIONARY", None))
        # A President's account: the AP may change its roles and turn it off, and on again.
        president = self.role_person("TEST-ROLE-SELF-PRES", "PRESIDENT")
        page, form = self.page_form(client, president)
        self.assertNotIn(roles.NOT_ALLOWED_ACCOUNT, html.unescape(page))
        self.assertEqual(self.plan_of(client, president, form, additional="OFFICE")["errors"], [])
        self.assertEqual(client.post(f"/accounts/{president['id']}/update", data={**form, "additional": ["OFFICE"]}).status_code, 302)
        self.assertEqual((self.additional_of(president), self.ap_context(president)), (["OFFICE"], "PRESIDENT"))
        _, form = self.page_form(client, president)
        self.assertEqual(client.post(f"/accounts/{president['id']}/update", data={**form, "active": ""}).status_code, 302)
        self.assertEqual((self.active_of(president), self.ap_context(president)), (False, None))
        _, form = self.page_form(client, president)
        self.assertNotIn("active", form)
        self.assertEqual(client.post(f"/accounts/{president['id']}/update", data={**form, "active": "yes"}).status_code, 302)
        self.assertEqual((self.active_of(president), self.ap_context(president)), (True, "PRESIDENT"))
        # Staff accounts and Undo follow the same rule. An AP's own sign-in is a missionary's, so this builds the unusual
        # case by hand: a sign-in without a missionary that an AP session claims as its own.
        with database.connect() as conn:
            with conn.cursor() as cur:
                cur.execute("""insert into auth.users(id,instance_id,aud,role,email)
                  values(gen_random_uuid(),'00000000-0000-0000-0000-000000000000','authenticated','authenticated',
                  'test-role-self-staff@example.invalid') returning id""")
                staff_id = str(cur.fetchone()[0])
                cur.execute("""insert into public.user_profiles(id,missionary_id,app_role,active,display_name,home_mission_id)
                  values(%s,null,'OFFICE',true,'Self Staff',2)""", (staff_id,))

        def drop_sign_in():
            with database.connect() as conn:
                with conn.cursor() as cur:
                    cur.execute("delete from auth.users where id=%s", (staff_id,))  # cascades to user_profiles
        self.addCleanup(drop_sign_in)
        with patch.object(sign_in, "allowed", return_value=True):
            own = self.admin_client({"profile_id": staff_id}, "AP")
            state = re.search(r'name="state" value="([0-9a-f]+)"', own.get(f"/staff/{staff_id}").get_data(as_text=True)).group(1)
            response = own.post(f"/staff/{staff_id}/update", data={"csrf_token": "test-csrf", "state": state, "display_name": "Self Staff",
                                                                     "email": "test-role-self-staff@example.invalid", "role": "DATA_ADMIN", "active": "yes"})
            self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
            self.assertIn("Saved", response.get_data(as_text=True))
        self.assertEqual(self.scalar("select app_role from public.user_profiles where id=%s", (staff_id,)), "DATA_ADMIN")
        gave_back = {"table_name": "user_profiles", "before_row": {"id": staff_id, "app_role": "DATA_ADMIN", "additional_roles": []},
                     "after_row": {"id": staff_id, "app_role": "OFFICE", "additional_roles": []}}  # undo would give it back
        with self.context():
            session.update(portal_role="AP", portal_user_id=staff_id)
            account_changes.check_undo([gave_back])  # your own account: allowed too
        # Whom to ask after losing access: the same people for every role.
        self.assertEqual(roles.WHO_GIVES_ACCESS, "an AP, the President or a Data Analyst")

    def test_32_older_accounts_with_data_analyst_or_office_as_main_role_still_display(self):
        legacy = self.role_person("TEST-ROLE-LEGACY-DA", "DATA_ADMIN", ["DL"])
        page, form = self.page_form(self.client, legacy)
        self.assertEqual(form["role"], "DATA_ADMIN")
        self.assertIn('<option value="DATA_ADMIN" selected>Data Analyst</option>', page)
        self.assertIn("Data Analyst, set by hand on this page", page)
        self.assertEqual(self.client.post(f"/accounts/{legacy['id']}/update", data=form).status_code, 302)
        self.assertEqual((self.app_role_of(legacy), self.leaders_of(legacy), self.ap_context(legacy)),
                         ("DATA_ADMIN", [("DL", date(2000, 1, 1), None)], "DATA_ADMIN"))
        listing = self.client.get("/accounts", query_string={"q": "TEST-ROLE-LEGACY-DA"}).get_data(as_text=True)
        self.assertIn("DL, Data Analyst", listing)
        office = self.role_person("TEST-ROLE-LEGACY-OFFICE", "OFFICE")
        page, form = self.page_form(self.client, office)
        self.assertEqual(form["role"], "OFFICE")
        self.assertNotIn('value="DATA_ADMIN" selected', page)
        # Other accounts are not offered the older main roles.
        page, _ = self.page_form(self.client, self.role_person("TEST-ROLE-PLAIN"))
        block = re.search(r'<select name="role"[^>]*>(.*?)</select>', page, re.S).group(1)
        self.assertEqual(re.findall(r'value="([A-Z_]+)"', block), ["MISSIONARY", "DL", "STL", "ZL", "AP", "PRESIDENT"])
        self.assertEqual(self.plan_of(self.client, legacy, form, role="OFFICE")["errors"], ["Choose a role from the list."])

    def test_33_ending_your_own_ap_access_later_keeps_you_signed_in_until_then(self):
        ap = self.role_person("TEST-ROLE-AP-LATER", leaders=["AP"])  # DA Management access only through the AP row
        client = self.admin_client(ap, "AP")
        page, form = self.page_form(client, ap)
        self.assertIn('<span id="ownAccessText">Saving ends my own DA Management access. I cannot give it back to myself.</span>', page)
        later = date.today() + timedelta(days=7)
        form.update(role="MISSIONARY", effective_date=later.isoformat())
        plan = self.plan_of(client, ap, form)
        self.assertEqual(plan["own"], 1)
        self.assertEqual(plan["lines"][0], f"This ends your own DA Management access from {day(later)}. Tick the box below to "
                                           "confirm, or ask another administrator to make this change.")
        self.assertEqual(plan["own_text"], f"Saving ends my own DA Management access from {day(later)}. After that I cannot "
                                           "give it back to myself.")
        response = client.post(f"/accounts/{ap['id']}/update", data=form)  # without the tick: refused, nothing saved
        self.assertEqual(response.status_code, 400)
        self.assertIn(f"Saving this ends your own DA Management access from {day(later)}.", response.get_data(as_text=True))
        self.assertEqual((self.leaders_of(ap), self.ap_context(ap)), ([("AP", date(2000, 1, 1), None)], "AP"))
        response = client.post(f"/accounts/{ap['id']}/update", data={**form, "own_access": "yes"})
        self.assertEqual(response.status_code, 302)  # saved; not signed out, because access lasts until the day before
        self.assertEqual((self.leaders_of(ap), self.ap_context(ap)), ([("AP", date(2000, 1, 1), later - timedelta(days=1))], "AP"))
        page = html.unescape(client.get(f"/accounts/{ap['id']}").get_data(as_text=True))
        self.assertIn(f"You keep your own DA Management access until {day(later - timedelta(days=1))}. "
                      f"From {day(later)} you no longer have it", page)
        self.assertIn(f"Changing the role ends the current AP assignment for the whole mission on {day(later - timedelta(days=1))}.", page)
        self.assertNotIn("Tick the box below", page)  # that line was for before saving
        self.assertNotIn("has ended", page)
        self.assertEqual(client.get("/accounts").status_code, 200)  # still signed in to DA Management

    # ------------------------------------------------------------ Import history: account page saves are ACCOUNT batches
    def history_client(self, who, role):
        """admin_client with the signed-in person's name, as a portal sign-in sets it (Import history's "By")."""
        client = self.admin_client(who, role)
        with client.session_transaction() as s:
            s["portal_user"] = f"Elder {who['number']}"
        return client

    def account_batches(self, who):
        """The ACCOUNT batches that recorded a row of this missionary (area, leadership or account), oldest first."""
        with database.connect() as conn:
            with database.cursor(conn) as cur:
                cur.execute("""select b.id::text id,b.actor,b.filename,b.summary,b.status from public.roster_import_batches b
                  where b.kind='ACCOUNT' and exists (select 1 from public.roster_import_changes c where c.batch_id=b.id
                    and coalesce(c.after_row,c.before_row)->>'missionary_id'=%s) order by b.created_at""", (str(who["id"]),))
                return [dict(r) for r in cur.fetchall()]

    def batch_status(self, batch):
        return self.scalar("select status from public.roster_import_batches where id=%s", (batch["id"],))

    def undo_in_history(self, client, batch, **extra):
        return client.post(f"/imports/{batch['id']}/undo", data={"csrf_token": "test-csrf", "confirmation": "UNDO", **extra})

    def rows_of(self, who):
        with database.connect() as conn:
            with conn.cursor() as cur:
                cur.execute("select area_id,start_date,end_date from public.missionary_assignments where missionary_id=%s order by start_date,id", (who["id"],))
                return [tuple(r) for r in cur.fetchall()], self.leaders_of(who)

    def test_36_an_account_page_role_change_is_one_batch_in_import_history_and_undo_restores_it(self):
        dl = self.role_person("TEST-HIST-DL", "DL", ["DL"])
        client = self.history_client(self.role_person("TEST-HIST-DA", additional=["DATA_ADMIN"]), "DATA_ADMIN")
        # A save of the languages only is not in Import history.
        _, form = self.page_form(client, dl)
        page = client.post(f"/accounts/{dl['id']}/update", data={**form, "primary_language": "es"}, follow_redirects=True)
        self.assertNotIn(account_changes.IN_HISTORY, page.get_data(as_text=True))
        self.assertEqual(self.account_batches(dl), [])
        # A role change (DL to ZL today, and Data Analyst): one batch that names who saved it and whose account it is.
        _, form = self.page_form(client, dl)
        page = client.post(f"/accounts/{dl['id']}/update", data={**form, "role": "ZL", "additional": ["DATA_ADMIN"]}, follow_redirects=True)
        self.assertIn(account_changes.IN_HISTORY, page.get_data(as_text=True))
        yesterday = date.today() - timedelta(days=1)
        self.assertEqual((self.leaders_of(dl), self.app_role_of(dl), self.additional_of(dl), self.ap_context(dl)),
                         ([("DL", date(2000, 1, 1), yesterday), ("ZL", date.today(), None)], "ZL", ["DATA_ADMIN"], "DATA_ADMIN"))
        [batch] = self.account_batches(dl)
        self.assertEqual((batch["actor"], batch["filename"], batch["status"]), ("Elder TEST-HIST-DA", "Account page - Elder TEST-HIST-DL", "APPLIED"))
        self.assertEqual(batch["summary"], {"action": "changed", "role": "DL → ZL + Data Analyst", "changed_rows": 3})
        self.assertEqual(self.scalar("select string_agg(table_name,',' order by sequence) from public.roster_import_changes where batch_id=%s",
                                     (batch["id"],)), "leadership_assignments,leadership_assignments,user_profiles")
        history = html.unescape(client.get("/imports").get_data(as_text=True))
        self.assertIn(f"<a href='/imports/{batch['id']}'>Account page - Elder TEST-HIST-DL</a></td><td>Account</td>", history)
        self.assertIn("<td>Elder TEST-HIST-DA</td>", history)
        detail = html.unescape(client.get(f"/imports/{batch['id']}").get_data(as_text=True))
        self.assertIn("DL → ZL + Data Analyst", detail)
        self.assertIn('name="confirmation"', detail)
        # Undo restores the roles and both leadership rows (the languages saved after it stay as they are).
        self.assertEqual(self.undo_in_history(client, batch).status_code, 302)
        self.assertEqual((self.leaders_of(dl), self.app_role_of(dl), self.additional_of(dl), self.ap_context(dl), self.batch_status(batch)),
                         ([("DL", date(2000, 1, 1), None)], "DL", [], None, "UNDONE"))
        self.assertEqual(self.scalar("select primary_language from public.missionary_language_assignments where missionary_id=%s", (dl["id"],)), "de")

    def test_37_an_ap_giving_another_ap_data_analyst_is_in_import_history_and_undo_keeps_the_rules(self):
        ap1 = self.role_person("TEST-HIST-AP1", "AP", ["AP"])
        ap2 = self.role_person("TEST-HIST-AP2", "AP", ["AP"])
        first, second = self.history_client(ap1, "AP"), self.history_client(ap2, "AP")
        _, form = self.page_form(second, ap1)
        self.assertEqual(second.post(f"/accounts/{ap1['id']}/update", data={**form, "additional": ["DATA_ADMIN"]}).status_code, 302)
        self.assertEqual((self.additional_of(ap1), self.ap_context(ap1)), (["DATA_ADMIN"], "DATA_ADMIN"))
        [grant] = self.account_batches(ap1)
        self.assertEqual((grant["actor"], grant["filename"], grant["summary"]),
                         ("Elder TEST-HIST-AP2", "Account page - Elder TEST-HIST-AP1", {"action": "changed", "role": "AP → AP + Data Analyst", "changed_rows": 1}))
        with database.connect() as conn:
            with database.cursor(conn) as cur:
                cur.execute("""select table_name,before_row->'additional_roles' before,after_row->'additional_roles' after
                  from public.roster_import_changes where batch_id=%s""", (grant["id"],))
                self.assertEqual([dict(r) for r in cur.fetchall()], [{"table_name": "user_profiles", "before": [], "after": ["DATA_ADMIN"]}])
        for client in (first, second):  # both APs see who gave whom the role
            history = client.get("/imports").get_data(as_text=True)
            self.assertIn(f"<a href='/imports/{grant['id']}'>Account page - Elder TEST-HIST-AP1</a>", history)
            self.assertIn("<td>Elder TEST-HIST-AP2</td>", history)
        # AP2 takes it away again. AP1 may undo that, which gives AP1 the role back (APs have full rights, owner 28 Sep).
        _, form = self.page_form(second, ap1)
        self.assertEqual(second.post(f"/accounts/{ap1['id']}/update", data={**form, "additional": []}).status_code, 302)
        took = self.account_batches(ap1)[-1]
        self.assertEqual((took["actor"], took["summary"]["role"]), ("Elder TEST-HIST-AP2", "AP + Data Analyst → AP"))
        page = html.unescape(first.get(f"/imports/{took['id']}").get_data(as_text=True))
        self.assertNotIn(account_changes.NOT_ALLOWED_UNDO, page)
        self.assertIn('name="confirmation"', page)
        self.assertEqual(self.undo_in_history(first, took).status_code, 302)
        self.assertEqual((self.additional_of(ap1), self.batch_status(took)), (["DATA_ADMIN"], "UNDONE"))
        # Then AP1 may undo the grant too (taking the role from themselves).
        self.assertEqual(self.undo_in_history(first, grant).status_code, 302)  # AP1 keeps DA Management as AP: no tick
        self.assertEqual((self.additional_of(ap1), self.ap_context(ap1), self.batch_status(grant)), ([], "AP", "UNDONE"))

    def test_38_undo_of_account_page_changes_to_a_president_or_to_your_own_access(self):
        ap = self.history_client(self.role_person("TEST-HIST-PRES-AP", "AP", ["AP"]), "AP")
        analyst = self.history_client(self.role_person("TEST-HIST-PRES-DA", additional=["DATA_ADMIN"]), "DATA_ADMIN")
        # A Data Analyst's change to the President's account: an AP may undo it (APs have full rights, owner 28 Sep).
        president = self.role_person("TEST-HIST-PRES", "PRESIDENT")
        _, form = self.page_form(analyst, president)
        self.assertEqual(analyst.post(f"/accounts/{president['id']}/update", data={**form, "additional": ["OFFICE"]}).status_code, 302)
        [change] = self.account_batches(president)
        self.assertEqual((change["actor"], change["summary"]["role"]), ("Elder TEST-HIST-PRES-DA", "President → President + Office"))
        self.assertNotIn(account_changes.NOT_ALLOWED_UNDO, html.unescape(ap.get(f"/imports/{change['id']}").get_data(as_text=True)))
        self.assertEqual(self.undo_in_history(ap, change).status_code, 302)
        self.assertEqual(self.additional_of(president), [])
        # Turning an account off is recorded as such; the AP may undo that too.
        _, form = self.page_form(analyst, president)
        self.assertEqual(analyst.post(f"/accounts/{president['id']}/update", data={**form, "active": ""}).status_code, 302)
        off = self.account_batches(president)[-1]
        self.assertEqual((off["summary"]["action"], self.active_of(president)), ("turned off", False))
        self.assertEqual(self.undo_in_history(ap, off).status_code, 302)
        self.assertEqual((self.active_of(president), self.ap_context(president)), (True, "PRESIDENT"))
        # Undoing the grant that gave you your only DA Management access needs the "I understand" tick.
        helper = self.role_person("TEST-HIST-OWN")
        _, form = self.page_form(ap, helper)
        self.assertEqual(ap.post(f"/accounts/{helper['id']}/update", data={**form, "additional": ["DATA_ADMIN"]}).status_code, 302)
        [grant] = self.account_batches(helper)
        own = self.history_client(helper, "DATA_ADMIN")
        response = self.undo_in_history(own, grant)
        self.assertEqual(response.status_code, 409)
        self.assertIn('name="own_access"', response.get_data(as_text=True))
        self.assertEqual((self.additional_of(helper), self.batch_status(grant)), (["DATA_ADMIN"], "APPLIED"))
        response = self.undo_in_history(own, grant, own_access="yes")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Your own DA Management access has ended", response.get_data(as_text=True))
        self.assertEqual((self.additional_of(helper), self.ap_context(helper), self.batch_status(grant)), ([], None, "UNDONE"))

    def test_39_a_move_and_taking_it_back_are_in_import_history_and_undo_reverses_them(self):
        dl = self.role_person("TEST-HIST-MOVE", "DL", ["DL"])
        other = next((a for a in self.current_areas(1000) if a["district_id"] != dl["district_id"]), None)
        if not other:
            self.skipTest("No current area in another district in this copy.")
        client = self.history_client(self.role_person("TEST-HIST-MOVER", additional=["DATA_ADMIN"]), "DATA_ADMIN")
        start, later = self.rows_of(dl), date.today() + timedelta(days=10)
        _, form = self.page_form(client, dl)
        saved = client.post(f"/accounts/{dl['id']}/update", data={**form, "area_id": str(other["id"]), "effective_date": later.isoformat()})
        self.assertEqual(saved.status_code, 302, saved.get_data(as_text=True))
        moved = self.rows_of(dl)
        page, form = self.page_form(client, dl)
        stay = re.search(r'<option value="(-\d+)"', page).group(1)
        page = client.post(f"/accounts/{dl['id']}/update", data={**form, "area_id": stay}, follow_redirects=True).get_data(as_text=True)
        self.assertIn(account_changes.IN_HISTORY, page)
        self.assertEqual(self.rows_of(dl), start)
        move, back = self.account_batches(dl)
        self.assertEqual([(b["actor"], b["summary"]) for b in (move, back)],
                         [("Elder TEST-HIST-MOVER", {"action": "moved", "role": "DL", "changed_rows": 4}),
                          ("Elder TEST-HIST-MOVER", {"action": "move taken back", "role": "DL", "changed_rows": 4})])
        # The move cannot be undone while it is taken back; undoing "stay here" brings the move back, then it can.
        response = self.undo_in_history(client, move)
        self.assertEqual(response.status_code, 409)
        self.assertIn("changed after this import", response.get_data(as_text=True))
        self.assertEqual(self.undo_in_history(client, back).status_code, 302)
        self.assertEqual(self.rows_of(dl), moved)
        self.assertEqual(self.undo_in_history(client, move).status_code, 302)
        self.assertEqual(self.rows_of(dl), start)


if __name__ == "__main__":
    unittest.main(verbosity=2)
