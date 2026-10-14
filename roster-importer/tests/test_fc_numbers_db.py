"""FC numbers in the People upload, against a disposable roster_management_test_* copy of Beta with migration 047 (never live).

Same rules as test_people_uploads.py, whose set-up it reuses (its import stops everything unless MANAGEMENT_TEST_DATABASE names
a roster_management_test_* database on the pinned test host). Made-up names and numbers only.
NOT run in round 13 (no database in the overnight sandbox): run it on the throw-away copy before migration 047 goes live.

Checks: a sheet with an FC column stores the number; the same number in a later sheet is the same person even with another
spelling of the name or another area (nothing is asked, nobody is added twice); a stored number is never overwritten; the same
number for two stored people is flagged and they are not joined; Undo takes the number back with the person; the database
refuses a number that does not look like one.
"""
import io
import unittest
from datetime import date, timedelta

import psycopg2.errors

import app  # noqa: E402  (after test_people_uploads' import, which checks the database first)
import database  # noqa: E402
from tests import data_samples as samples  # noqa: E402
from tests.test_people_uploads import PeopleBase  # noqa: E402 (the base class has no tests of its own)


class FcNumberTests(PeopleBase):
    def setUp(self):
        super().setUp()
        self.client = app.app.test_client()
        with self.client.session_transaction() as session_data:
            session_data.update(authenticated=True, portal_mission_id=2, portal_user="Integration test", csrf_token="test-csrf")

    def sheet(self, rows):
        headings = ["First name", "Last name", "Zone", "Area", "Ward or branch", "Baptism date", "Confirmation date", "FC number"]
        return samples.csv_bytes(headings, rows)

    def day_text(self, day):
        return f"{day.month}/{day.day}/{day.year}"

    def post_file(self, data):
        response = self.client.post("/people-upload/preview", content_type="multipart/form-data",
                                    data={"csrf_token": "test-csrf", "file": (io.BytesIO(data), "people.csv")})
        self.assertEqual(response.status_code, 302, response.get_data(as_text=True)[:500])
        review = self.client.get("/people-upload/review")
        self.assertEqual(review.status_code, 200)
        return review.get_data(as_text=True)

    def apply(self):
        response = self.client.post("/people-upload/apply", data={"csrf_token": "test-csrf", "confirmed": "yes"})
        self.assertEqual(response.status_code, 302, response.get_data(as_text=True)[:800])
        return response.headers["Location"].rsplit("/", 1)[-1]

    def numbers(self):
        return [(r["display_name"], r["fc_number"]) for r in self.rows(
            "select display_name,fc_number from public.new_members order by display_name")]

    def test_01_the_number_is_stored_and_undo_takes_it_back_with_the_person(self):
        recent = self.day_text(date.today() - timedelta(days=20))
        self.post_file(self.sheet([["Fiona", "Fcone", "", self.area["name"], "", recent, "", "FC-1234567"]]))
        batch = self.apply()
        self.assertEqual(self.numbers(), [("Fiona Fcone", "1234567")])
        undone = self.client.post(f"/imports/{batch}/undo", data={"csrf_token": "test-csrf", "confirmation": "UNDO"})
        self.assertEqual(undone.status_code, 302, undone.get_data(as_text=True)[:600])
        self.assertEqual(self.numbers(), [])

    def test_02_the_same_number_is_the_same_person_even_with_another_name_and_area(self):
        recent = self.day_text(date.today() - timedelta(days=20))
        self.post_file(self.sheet([["Fiona", "Fcone", "", self.area["name"], "", recent, "", "1234567"]]))
        self.apply()
        page = self.post_file(self.sheet([["Fionna", "Fc-One", "", self.other_area["name"], "", recent, "", "1234567"]]))
        self.assertNotIn("pair(s) to check", page)  # nothing to ask: the number decides
        self.apply()
        self.assertEqual(self.numbers(), [("Fiona Fcone", "1234567")])  # one person, the stored name and number kept

    def test_03_a_stored_number_is_never_overwritten_and_a_blank_is_filled(self):
        recent = self.day_text(date.today() - timedelta(days=20))
        self.post_file(self.sheet([["Gina", "Fctwo", "", self.area["name"], "", recent, "", ""],
                                   ["Hans", "Fcthree", "", self.area["name"], "", recent, "", "7777777"]]))
        self.apply()
        self.post_file(self.sheet([["Gina", "Fctwo", "", self.area["name"], "", recent, "", "2222222"],
                                   ["Hans", "Fcthree", "", self.area["name"], "", recent, "", "8888888"]]))
        self.apply()
        found = self.numbers()
        self.assertIn(("Gina Fctwo", "2222222"), found)  # was blank: filled
        self.assertIn(("Hans Fcthree", "7777777"), found)  # had one: kept, never overwritten
        self.assertIn(("Hans Fcthree", "8888888"), found)  # the same name with another number is another person
        self.assertEqual(len(found), 3)

    def test_04_one_number_for_two_stored_people_is_flagged_and_they_are_not_joined(self):
        recent = self.day_text(date.today() - timedelta(days=20))
        with database.connect() as conn:
            with conn.cursor() as cur:
                for name in ("Ivo Dup", "Ida Dup"):
                    cur.execute("""insert into public.new_members(area_id,first_name,display_name,baptism_date,fc_number)
                      values(%s,%s,%s,%s,'5555555') returning id""",
                                (self.area["id"], name.split()[0], name, date.today() - timedelta(days=20)))
                    cur.execute("""insert into public.new_member_area_assignments(new_member_id,area_id,start_date)
                      values(%s,%s,%s)""", (cur.fetchone()[0], self.area["id"], date.today() - timedelta(days=20)))
        page = self.post_file(self.sheet([["Jan", "Other", "", self.area["name"], "", recent, "", "6666666"]]))
        self.assertIn("FC number 5555555 is saved for 2 people", page)

    def test_05_the_database_refuses_a_number_that_does_not_look_like_one(self):
        with database.connect() as conn:
            with conn.cursor() as cur:
                with self.assertRaises(psycopg2.errors.CheckViolation):
                    cur.execute("""insert into public.new_members(area_id,first_name,display_name,fc_number)
                      values(%s,'Bad','Bad Number','not a number!')""", (self.area["id"],))
            conn.rollback()


if __name__ == "__main__":
    unittest.main()
