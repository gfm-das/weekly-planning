"""People in uploads, against a disposable roster_management_test_* copy of Beta with migration 039 (never live).

Same rules as test_management.py (see the Testing part of the README). Made-up names only. Checks: a Historical CSV
makes real people and puts them on the weekly plans of the weeks they were named on; the same person is one record;
the owner's rules decide who is loaded into the current week (new member: one year after baptism; friend with a
baptismal date: on last week's plan and the date not passed; high potential: on last week's plan); uncertain matches
are asked and block Apply; Undo takes everything back.
"""
import csv
import io
import os
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
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
import data_files  # noqa: E402
import data_names  # noqa: E402
import data_types  # noqa: E402
import database  # noqa: E402
import historical_apply  # noqa: E402
import historical_import as historical  # noqa: E402
import historical_preview  # noqa: E402
import people_match as match  # noqa: E402
import undo  # noqa: E402
from tests import data_samples as samples  # noqa: E402

LABEL = "Test Companionship People"
PEOPLE_TABLES = ["new_members", "new_member_area_assignments", "baptismal_date_people", "baptismal_date_person_area_assignments",
                 "weekly_new_members", "weekly_baptismal_date_friends", "weekly_high_potential_friends"]


class PeopleBase(unittest.TestCase):
    """The set-up and helpers both groups of tests use (it has no tests of its own)."""

    @classmethod
    def setUpClass(cls):
        app.app.config["TESTING"] = True
        with database.connect() as conn:
            with database.cursor(conn) as cur:
                assert cur.execute("select current_database() name") or cur.fetchone()["name"] == test_db
                cur.execute("""select a.id,a.name from public.areas a join public.districts d on d.id=a.district_id
                  join public.zones z on z.id=d.zone_id where z.mission_id=2 and a.active and d.active and z.active
                  and exists (select 1 from public.missionary_assignments ma join public.missionaries mm on mm.id=ma.missionary_id
                              where ma.area_id=a.id and ma.end_date is null and mm.status='Active')
                  order by a.id limit 2""")
                cls.area, cls.other_area = cur.fetchall()
                cur.execute("select public.current_reporting_sunday() s")
                cls.sunday = cur.fetchone()["s"]
                cur.execute("""select count(*) n from public.area_units au where au.area_id=%s and au.active""", (cls.area["id"],))
                assert cur.fetchone()["n"] >= 1, "the test area needs a ward or branch"

    def setUp(self):
        self.wipe()
        self.addCleanup(self.wipe)

    def wipe(self):
        """The test database is a throw-away copy: every test starts and ends without people, plans or imports."""
        with database.connect() as conn:
            with conn.cursor() as cur:
                for table in ["people_match_decisions", "weekly_high_potential_friends", "weekly_baptismal_date_friends",
                              "weekly_new_members", "historical_planning_details", "import_weekly_planning_answers",
                              "import_weekly_new_members", "import_weekly_baptismal_date_friends",
                              "import_weekly_high_potential_friends", "import_weekly_planning_reports"]:
                    cur.execute(f"delete from public.{table}")
                cur.execute("update public.new_members set baptismal_date_person_id=null")
                for table in ["new_member_area_assignments", "baptismal_date_person_area_assignments"]:
                    cur.execute(f"delete from public.{table}")
                cur.execute("delete from public.new_members")
                cur.execute("delete from public.baptismal_date_people")
                cur.execute("delete from public.weekly_planning_answers")
                cur.execute("delete from public.weekly_area_reports")
                cur.execute("delete from public.roster_import_changes where batch_id in (select id from public.roster_import_batches where kind in ('HISTORICAL','PEOPLE'))")
                cur.execute("delete from public.roster_import_batches where kind in ('HISTORICAL','PEOPLE')")

    def context(self):
        ctx = app.app.test_request_context("/")
        return ctx

    def count(self, table, where="true", params=()):
        with database.connect() as conn:
            with conn.cursor() as cur:
                cur.execute(f"select count(*) from public.{table} where {where}", params)
                return cur.fetchone()[0]

    def rows(self, query, params=()):
        with database.connect() as conn:
            with database.cursor(conn) as cur:
                cur.execute(query, params)
                return cur.fetchall()

    # ------------------------------------------------------------------------------------------ fixtures

    def csv_file(self, forms, label=LABEL, area=None):
        """forms: [(sunday, {extra columns})]. Maps the label to the test area and writes the CSV."""
        area = area or self.area
        fields = [historical.TIMESTAMP_COLUMN, historical.EMAIL_COLUMN, historical.COMPANIONSHIP_COLUMN,
                  historical.UNIT_COLUMN, historical.SUNDAY_COLUMN]
        extras = sorted({k for _, e in forms for k in e})
        f = tempfile.NamedTemporaryFile(mode="w", suffix=".csv", encoding="utf-8", newline="", delete=False)
        writer = csv.DictWriter(f, fields + extras)
        writer.writeheader()
        for number, (sunday, extra) in enumerate(forms):
            writer.writerow({historical.TIMESTAMP_COLUMN: f"2026-01-0{number % 9 + 1} 09:00:00",
                             historical.EMAIL_COLUMN: "test@example.invalid", historical.COMPANIONSHIP_COLUMN: label,
                             historical.UNIT_COLUMN: "", historical.SUNDAY_COLUMN: f"{sunday.month}/{sunday.day}/{sunday.year}",
                             **extra})
        f.close()
        self.addCleanup(lambda: Path(f.name).unlink(missing_ok=True))
        with database.connect() as conn:
            with conn.cursor() as cur:
                cur.execute("""insert into public.import_weekly_planning_area_map
                  (source_companionship,target_area_name,target_area_id,mission_id,match_status,confirmed_at)
                  values(%s,%s,%s,2,'CONFIRMED',now()) on conflict(source_companionship) do update
                  set target_area_id=excluded.target_area_id,mission_id=2""", (label, area["name"], area["id"]))
        return f.name

    def apply(self, path):
        with self.context():
            session.update(portal_mission_id=2, portal_user="Integration test")
            return historical_apply.apply_batch(path, "people.csv")

    def check(self, path):
        with self.context():
            session.update(portal_mission_id=2, portal_user="Integration test")
            return historical_preview.preview(path)

    def undo(self, batch):
        with self.context():
            session.update(portal_mission_id=2, portal_user="Integration test")
            undo.undo_batch(batch)

    @staticmethod
    def nm(name, part=1, **answers):
        return {f"First & Last Name pt.{part}": name, f"Gender pt.{part}": "Female", **answers}

    @staticmethod
    def friend(first, last, part=1, current=None, set_on=None):
        return {f"First Name pt.{part}": first, f"Last Name pt.{part}": last,
                f"For which date is their baptismal date currently set? pt.{part}": current or "",
                f"When was the baptismal date set? pt.{part}": set_on or "",
                f"Baptismal Date Friend Commitments pt.{part} [Were they at church this Sunday?]": "Yes"}

    @staticmethod
    def hp(name, part=1):
        return {f"Optional: High potential {part}, first and last name": name}

    @staticmethod
    def us(day):
        return f"{day.month}/{day.day}/{day.year}"

    def week(self, back):
        return self.sunday - timedelta(days=7 * back)

    def current_plan(self, area_id=None):
        """The plan of the current week in the test area, with the names on it."""
        reports = self.rows("""select r.id,r.status from public.weekly_area_reports r join public.reporting_weeks w on w.id=r.reporting_week_id
          where r.area_id=%s and w.sunday=%s""", (area_id or self.area["id"], self.sunday))
        names = {"nm": [], "bd": [], "hp": []}
        for report in reports:
            names["nm"] += [r["display_name"] for r in self.rows("""select n.display_name from public.weekly_new_members w
              join public.new_members n on n.id=w.new_member_id where w.weekly_area_report_id=%s""", (report["id"],))]
            names["bd"] += [r["display_name"] for r in self.rows("""select b.display_name from public.weekly_baptismal_date_friends w
              join public.baptismal_date_people b on b.id=w.baptismal_date_person_id where w.weekly_area_report_id=%s""", (report["id"],))]
            names["hp"] += [r["name"] for r in self.rows("select name from public.weekly_high_potential_friends where weekly_area_report_id=%s", (report["id"],))]
        return reports, {k: sorted(v) for k, v in names.items()}

    def two_weeks(self):
        """Two weeks of forms: last week and the week before, with the same people."""
        future, past = self.us(self.sunday + timedelta(days=21)), self.us(self.sunday - timedelta(days=3))
        before, last = self.week(2), self.week(1)
        return [
            (before, {**self.nm("Anna Testperson"), **self.friend("Bea", "Testfriend", current=future, set_on=self.us(before)),
                      **self.friend("Cora", "Pastdate", part=2, current=past), **self.hp("Hanna Hope"),
                      **self.hp("Gone Hope", part=2)}),
            (last, {**self.nm("Anna Testperson"), **self.friend("Bea", "Testfriend", current=future),
                    **self.friend("Cora", "Pastdate", part=2, current=past), **self.hp("Hanna Hope")}),
        ]



class PeopleUploadTests(PeopleBase):
    """The Historical CSV with people."""

    # ------------------------------------------------------------------------------------------ tests

    def test_01_csv_makes_one_person_per_name_and_loads_the_current_week(self):
        path = self.csv_file(self.two_weeks())
        checked = self.check(path)
        self.assertEqual(checked["errors"], [])
        self.assertEqual(checked["people"]["questions"], [])
        self.assertEqual(checked["people"]["counts"]["people"], 3)  # Anna, Bea, Cora: once each, not once per week
        batch = self.apply(path)
        self.assertEqual(self.count("new_members"), 1)
        self.assertEqual(self.count("baptismal_date_people"), 2)
        self.assertEqual(self.count("weekly_new_members"), 2 + 1)  # two past weeks and the current week
        reports, names = self.current_plan()
        self.assertEqual([r["status"] for r in reports], ["DRAFT"])
        self.assertEqual(names["nm"], ["Anna Testperson"])
        self.assertEqual(names["bd"], ["Bea Testfriend"])  # Cora's date has passed
        self.assertEqual(names["hp"], ["Hanna Hope"])  # "Gone Hope" was not on last week's plan
        # The old high potential is kept as history on the older plan.
        self.assertEqual(self.count("weekly_high_potential_friends", "name='Gone Hope'"), 1)

    def test_02_second_upload_of_the_same_file_adds_nobody(self):
        path = self.csv_file(self.two_weeks())
        first = self.apply(path)
        before = {t: self.count(t) for t in PEOPLE_TABLES}
        second = self.apply(path)
        self.assertEqual({t: self.count(t) for t in PEOPLE_TABLES}, before)

    def test_03_undo_takes_the_people_back(self):
        path = self.csv_file(self.two_weeks())
        batch = self.apply(path)
        self.assertGreater(self.count("new_members"), 0)
        self.undo(batch)
        for table in PEOPLE_TABLES:
            self.assertEqual(self.count(table), 0, table)
        self.assertEqual(self.current_plan()[0], [])

    def test_04_alike_names_are_asked_and_block_apply(self):
        first = self.apply(self.csv_file(self.two_weeks()))
        before = self.week(0)
        path = self.csv_file([(before, self.nm("Anna Testpersson"))], label=LABEL)  # one letter more
        checked = self.check(path)
        self.assertEqual(len(checked["people"]["questions"]), 1)
        self.assertTrue(checked["pending"])
        with self.assertRaises(ValueError):
            self.apply(path)
        question = checked["people"]["questions"][0]
        with database.connect() as conn:
            with database.cursor(conn) as cur:
                match.save_decision(cur, 2, question["keys"][0], question["keys"][1], True, "test")
        checked = self.check(path)
        self.assertEqual(checked["people"]["questions"], [])
        second = self.apply(path)
        self.assertEqual(self.count("new_members"), 1, "answered 'same person': one record")

    def test_05_different_answer_keeps_two_people(self):
        first = self.apply(self.csv_file(self.two_weeks()))
        path = self.csv_file([(self.week(0), self.nm("Anna Testpersson"))])
        question = self.check(path)["people"]["questions"][0]
        with database.connect() as conn:
            with database.cursor(conn) as cur:
                match.save_decision(cur, 2, question["keys"][0], question["keys"][1], False, "test")
        second = self.apply(path)
        self.assertEqual(self.count("new_members"), 2)

    def test_06_same_name_in_another_area_is_asked(self):
        first = self.apply(self.csv_file(self.two_weeks()))
        path = self.csv_file([(self.week(0), self.nm("Anna Testperson"))], label=LABEL + " Other", area=self.other_area)
        questions = self.check(path)["people"]["questions"]
        self.assertEqual([q["reason"] for q in questions], ["same_name_other_area"])

    def test_07_a_typed_answer_is_never_overwritten(self):
        first = self.apply(self.csv_file(self.two_weeks()))
        with database.connect() as conn:
            with conn.cursor() as cur:
                cur.execute("update public.weekly_new_members set how_are_they_doing='typed by hand', reading=false")
        path = self.csv_file([(self.week(1), {**self.nm("Anna Testperson"),
                                             "How are they doing? pt.1": "from the file",
                                             "Grid Multiple Choice NM questions pt.1 [Reading?]": "Yes"})])
        second = self.apply(path)
        rows = self.rows("select how_are_they_doing,reading from public.weekly_new_members where how_are_they_doing is not null")
        self.assertEqual({r["how_are_they_doing"] for r in rows}, {"typed by hand"})  # "from the file" never replaced it
        self.assertEqual({r["reading"] for r in rows}, {False})

    def test_08_a_friend_who_was_baptized_becomes_the_new_member(self):
        future = self.us(self.sunday + timedelta(days=14))
        forms = [(self.week(2), self.friend("Dora", "Convert", current=future)),
                 (self.week(1), self.nm("Dora Convert"))]
        batch = self.apply(self.csv_file(forms))
        link = self.rows("""select b.tracking_status,b.tracking_end_reason from public.new_members n
          join public.baptismal_date_people b on b.id=n.baptismal_date_person_id""")
        self.assertEqual([(r["tracking_status"], r["tracking_end_reason"]) for r in link], [("ended", "baptized")])
        self.assertNotIn("Dora Convert", self.current_plan()[1]["bd"])

    def test_09_a_missionary_opening_the_portal_gets_the_same_people(self):
        """start_current_weekly_report (the portal) uses the same rules as the upload."""
        profile = self.rows("""select up.id,a.id area_id,a.name from public.user_profiles up
          join lateral (select m.area_id from public.missionary_assignments m where m.missionary_id=up.missionary_id
            and m.start_date<=current_date and (m.end_date is null or m.end_date>=current_date) order by m.start_date desc limit 1) ma on true
          join public.areas a on a.id=ma.area_id where up.active and a.active
            and exists (select 1 from public.area_units au where au.area_id=a.id and au.active) limit 1""")
        if not profile:
            self.skipTest("no signed-in missionary with an area in this database")
        area = {"id": profile[0]["area_id"], "name": profile[0]["name"]}
        self.apply(self.csv_file(self.two_weeks(), area=area))
        unit = self.rows("select unit_id from public.weekly_area_reports where area_id=%s limit 1", (area["id"],))[0]["unit_id"]
        with database.connect() as conn:
            with conn.cursor() as cur:
                cur.execute("delete from public.weekly_high_potential_friends where weekly_area_report_id in (select r.id from public.weekly_area_reports r join public.reporting_weeks w on w.id=r.reporting_week_id where w.sunday=%s)", (self.sunday,))
                cur.execute("delete from public.weekly_baptismal_date_friends where weekly_area_report_id in (select r.id from public.weekly_area_reports r join public.reporting_weeks w on w.id=r.reporting_week_id where w.sunday=%s)", (self.sunday,))
                cur.execute("delete from public.weekly_new_members where weekly_area_report_id in (select r.id from public.weekly_area_reports r join public.reporting_weeks w on w.id=r.reporting_week_id where w.sunday=%s)", (self.sunday,))
                cur.execute("delete from public.weekly_area_reports where reporting_week_id in (select id from public.reporting_weeks where sunday=%s)", (self.sunday,))
                cur.execute("set local role authenticated")
                cur.execute("select set_config('request.jwt.claims', %s, true), set_config('request.jwt.claim.sub', %s, true)",
                            ('{"sub":"%s","role":"authenticated"}' % profile[0]["id"], str(profile[0]["id"])))  # both spellings: Supabase versions differ
                cur.execute("select public.start_current_weekly_report(%s)", (unit,))
        self.assertEqual(self.current_plan(area["id"])[1], {"nm": ["Anna Testperson"], "bd": ["Bea Testfriend"], "hp": ["Hanna Hope"]})


class PeopleSheetTests(PeopleBase):
    """The People upload (spreadsheets of new members), through the pages."""

    def setUp(self):
        super().setUp()
        self.client = app.app.test_client()
        with self.client.session_transaction() as session_data:
            session_data.update(authenticated=True, portal_mission_id=2, portal_user="Integration test", csrf_token="test-csrf")

    def post_file(self, data, filename="people.csv"):
        response = self.client.post("/people-upload/preview", content_type="multipart/form-data",
                                    data={"csrf_token": "test-csrf", "file": (io.BytesIO(data), filename)})
        self.assertEqual(response.status_code, 302, response.get_data(as_text=True)[:500])
        review = self.client.get("/people-upload/review")
        self.assertEqual(review.status_code, 200)
        return review.get_data(as_text=True)

    def sheet(self, rows):
        headings = ["First name", "Last name", "Zone", "Area", "Ward or branch", "Baptism date", "Confirmation date", "Gender"]
        return samples.csv_bytes(headings, rows)

    def day_text(self, day):
        return f"{day.month}/{day.day}/{day.year}"

    def apply(self):
        response = self.client.post("/people-upload/apply", data={"csrf_token": "test-csrf", "confirmed": "yes"})
        self.assertEqual(response.status_code, 302, response.get_data(as_text=True)[:800])
        return response.headers["Location"].rsplit("/", 1)[-1]

    def undo_batch(self, batch):
        return self.client.post(f"/imports/{batch}/undo", data={"csrf_token": "test-csrf", "confirmation": "UNDO"})

    def test_01_a_sheet_makes_new_members_and_loads_the_current_week(self):
        recent = self.day_text(date.today() - timedelta(days=30))
        old = self.day_text(date.today() - timedelta(days=800))
        page = self.post_file(self.sheet([["Mia", "Sheetone", "", self.area["name"], "", recent, "", "Female"],
                                          ["Old", "Sheettwo", "", self.area["name"], "", old, "", "Male"]]))
        self.assertIn("people to save", page)
        batch = self.apply()
        self.assertEqual(self.count("new_members"), 2)
        self.assertEqual(self.count("new_members", "follow_up_status='ended'"), 1)  # baptized more than a year ago
        self.assertEqual(self.current_plan()[1]["nm"], ["Mia Sheetone"])
        self.assertEqual(self.client.get(f"/imports/{batch}").status_code, 200)
        # A second upload of the same sheet adds nobody.
        self.post_file(self.sheet([["Mia", "Sheetone", "", self.area["name"], "", recent, "", "Female"]]))
        self.apply()
        self.assertEqual(self.count("new_members"), 2)

    def test_02_undo_removes_the_people(self):
        recent = self.day_text(date.today() - timedelta(days=10))
        self.post_file(self.sheet([["Una", "Sheetundo", "", self.area["name"], "", recent, "", ""]]))
        batch = self.apply()
        self.assertEqual(self.count("new_members"), 1)
        undone = self.undo_batch(batch)
        self.assertEqual(undone.status_code, 302, undone.get_data(as_text=True)[:600])
        for table in PEOPLE_TABLES:
            self.assertEqual(self.count(table), 0, table)

    def test_03_a_row_without_an_area_is_placed_by_its_ward(self):
        found = self.rows("""select u.name ward,min(au.area_id) area_id from public.units u join public.area_units au on au.unit_id=u.id and au.active
          join public.areas a on a.id=au.area_id and a.active group by u.id having count(distinct au.area_id)=1
          and (select count(*) from public.units x where x.name=u.name)=1 order by u.id limit 1""")[0]
        recent = self.day_text(date.today() - timedelta(days=5))
        page = self.post_file(self.sheet([["Wanda", "Sheetward", "", "", found["ward"], recent, "", ""]]))
        self.assertIn("<b>0</b><br>rows left out: no area", page)
        self.apply()
        self.assertEqual(self.rows("select a.area_id from public.new_member_area_assignments a")[0]["area_id"], found["area_id"])

    def test_04_a_row_with_no_area_and_no_ward_is_left_out_and_counted(self):
        recent = self.day_text(date.today() - timedelta(days=5))
        page = self.post_file(self.sheet([["Nora", "Nowhere", "", "", "", recent, "", ""]]))
        self.assertIn("<b>1</b><br>rows left out: no area", page)
        self.assertIn("There is nobody to save", page)

    def test_05_a_closed_area_is_asked_about(self):
        district = self.rows("select district_id from public.areas where id=%s", (self.area["id"],))[0]["district_id"]
        with database.connect() as conn:
            with conn.cursor() as cur:
                cur.execute("insert into public.areas(district_id,name,active) values(%s,'Zzz Closed Test Area',false)", (district,))
        self.addCleanup(self.drop_closed_area)
        recent = self.day_text(date.today() - timedelta(days=5))
        page = self.post_file(self.sheet([["Carl", "Sheetclosed", "", "Zzz Closed Test Area", "", recent, "", ""]]))
        self.assertIn("Which area is this?", page)
        # The manager moves the people to the current area; the answer is remembered and the question is gone.
        with database.connect() as conn:
            with database.cursor(conn) as cur:
                data_names.remember(cur, 2, "area", "Zzz Closed Test Area", f"area:{self.area['id']}", "test")
        page = self.client.get("/people-upload/review").get_data(as_text=True)
        self.assertNotIn("Which area is this?", page)
        self.apply()
        self.assertEqual(self.rows("select a.area_id from public.new_member_area_assignments a")[0]["area_id"], self.area["id"])

    def drop_closed_area(self):
        with database.connect() as conn:
            with conn.cursor() as cur:
                cur.execute("delete from public.data_name_matches where source_name='Zzz Closed Test Area'")
                self.wipe()
                cur.execute("delete from public.areas where name='Zzz Closed Test Area'")

    def test_06_a_name_already_in_area_mappings_is_not_asked_again(self):
        with database.connect() as conn:
            with conn.cursor() as cur:
                cur.execute("""insert into public.import_weekly_planning_area_map
                  (source_companionship,target_area_name,target_area_id,mission_id,match_status,confirmed_at)
                  values('Zzz Mapped Label',%s,%s,2,'CONFIRMED',now()) on conflict(source_companionship) do update
                  set target_area_id=excluded.target_area_id,mission_id=2""", (self.area["name"], self.area["id"]))
        self.addCleanup(self.drop_mapping)
        recent = self.day_text(date.today() - timedelta(days=5))
        page = self.post_file(self.sheet([["Maya", "Sheetmapped", "", "zzz  mapped label", "", recent, "", ""]]))
        self.assertIn("<b>0</b><br>area names to match", page)
        self.apply()
        self.assertEqual(self.rows("select a.area_id from public.new_member_area_assignments a")[0]["area_id"], self.area["id"])

    def drop_mapping(self):
        with database.connect() as conn:
            with conn.cursor() as cur:
                cur.execute("delete from public.import_weekly_planning_area_map where source_companionship='Zzz Mapped Label'")

    def test_07_readers_of_the_two_office_layouts(self):
        vollzogen = [["Taufen", None, None, None, None, None, None, None, None, None, "Mission Office Info", None],
                     ["Wie gefunden", "Name", "Wann gesetzt", "Taufdatum", "Mitarbeiter", "Gemeinde", "Pfahl", "Zone", "Konfirmiert",
                      "Country", "Gender", "Preferred Language"],
                     ["Finde Christus", "Tessa Vollzogen", "2025-01-05", "2025-01-12", "Companionship", "Feucht", "Nürnberg",
                      "Nürnberg", "x", "country", "Female", "Arabic"]]
        parsed = data_types.parse_people(data_files.read_table("v.xlsx", samples.xlsx_bytes(vollzogen)))
        self.assertEqual(parsed.problem_count, 0)
        record = parsed.records[0]
        self.assertEqual((record["first"], record["last"], record["baptism_date"], record["ward"], record["zone"]),
                         ("Tessa", "Vollzogen", "2025-01-12", "Feucht", "Nürnberg"))
        self.assertIsNone(record["confirmation_date"])  # "x" is a mark, not a date
        raw = [["Timestamp", "Stake", "Which companionship is filling out the form?", "Which Ward/Branch Are They in?", "First Name",
                "Last Name", "When was the Baptismal Date Extended", "Date of Baptism", "Date of Confirmation",
                "Finding Source, of friend baptized", "Date of Birth", "Age Range", "Gender"],
               ["2026-06-07 15:30:09", "Stuttgart", "Stuttgart-Tübingen 1", "Stuttgart-Tübingen", "Rita", "Rawform",
                "2026-05-17 00:00:00", "2026-05-31 00:00:00", "2026-06-07 00:00:00", "Missionary/Through Person",
                "1988-08-04 00:00:00", "31-45", "Male"]]
        parsed = data_types.parse_people(data_files.read_table("r.xlsx", samples.xlsx_bytes(raw)))
        record = parsed.records[0]
        self.assertEqual((record["first"], record["last"], record["area"], record["baptism_date"], record["age_range"]),
                         ("Rita", "Rawform", "Stuttgart-Tübingen 1", "2026-05-31", "31-45"))
        self.assertEqual(record["date_of_birth"], "1988-08-04")


class NameRulesTests(unittest.TestCase):
    """Name matching rules without a database."""

    def test_names_fold_and_split(self):
        self.assertEqual(match.fold("Zoë  Müller-Groß"), "zoe muller gross")
        self.assertEqual(match.split_name("Anna Maria Meier"), ("Anna Maria", "Meier"))
        self.assertEqual(match.split_name("Cher"), ("Cher", None))

    def test_alike_names(self):
        self.assertTrue(match.similar_names("maria muller", "maria anna muller"))
        self.assertTrue(match.similar_names("anna testperson", "anna testpersson"))
        self.assertFalse(match.similar_names("anna testperson", "peter schmidt"))

    def test_clashing_baptism_dates_mean_different_people(self):
        a = {"baptism_date": date(2026, 5, 1)}
        self.assertTrue(match.dates_clash(a, {"baptism_date": date(2026, 6, 1)}))
        self.assertFalse(match.dates_clash(a, {"baptism_date": None}))


if __name__ == "__main__":
    unittest.main()
