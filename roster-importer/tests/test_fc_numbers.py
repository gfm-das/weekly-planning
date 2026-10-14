"""FC numbers (FindeChristus numbers) as the first, exact match key of the People upload, without a database.

Made-up names and numbers only. Run from roster-importer/ (see the README, Testing):
  python -m unittest tests.test_fc_numbers
"""
import inspect
import os
import unittest
from datetime import date
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "postgresql://nobody@127.0.0.1:1/none")  # never opened by these tests
import data_files  # noqa: E402
import data_types  # noqa: E402
import people_match as match  # noqa: E402
import people_upload  # noqa: E402
import people_write  # noqa: E402
from data_text import TEXT  # noqa: E402

SUNDAY = date(2026, 10, 4)


def appearance(name, area=1, fc=None, kind=match.NEW_MEMBER, bapt=None, order=1):
    first, last = match.split_name(name)
    return {"kind": kind, "name": name, "first": first, "last": last, "area_id": area, "unit_id": None, "sunday": None,
            "order": order, "target": None, "baptism_date": bapt, "profile": {}, "weekly": None, "fc": fc}


def stored(person_id, name, area=1, fc=None, kind=match.NEW_MEMBER, bapt=None):
    first, last = match.split_name(name)
    row = {"id": person_id, "first_name": first, "last_name": last, "display_name": name, "area_id": area,
           "unit_id": None, "fc_number": fc}
    return match.stored_person(kind, row, bapt)


def resolve(upload, stored_people=(), decisions=None):
    return match.resolve(match.group_people(upload), list(stored_people), decisions or {})


class ReadingFcNumbers(unittest.TestCase):
    def test_one_way_of_writing_a_number(self):
        read = data_files.read_fc_number
        self.assertEqual(read("1234567"), "1234567")
        self.assertEqual(read(" fc-123 456 "), "123456")
        self.assertEqual(read("FC#00123"), "00123")  # leading zeros stay
        self.assertEqual(read(1234567.0), "1234567")  # a number cell of a spreadsheet
        self.assertEqual(read(1234567), "1234567")
        self.assertIsNone(read(None))
        self.assertIsNone(read("   "))

    def test_something_that_cannot_be_a_number_is_refused(self):
        for bad in ("12", "n/a?", "a" * 31, "FC", "12.34.56", "12 34/56"):
            with self.assertRaises(ValueError, msg=bad):
                data_files.read_fc_number(bad)

    def test_the_sheet_reads_the_column_and_leaves_a_bad_cell_empty(self):
        data = ("First name,Last name,Baptism date,Area,FC number\n"
                "Ana,Beispiel,2026-09-20,Bockenheim,1234567\n"
                "Ben,Probe,2026-09-21,Bockenheim,x\n"
                "Cem,Muster,2026-09-22,Bockenheim,\n").encode()
        parsed = data_types.parse_people(data_files.read_table("people.csv", data))
        self.assertEqual([r["fc_number"] for r in parsed.records], ["1234567", None, None])
        self.assertEqual(parsed.problem_count, 1)
        self.assertEqual(parsed.problems[0][0], 3)
        self.assertIn("not an FC number", parsed.problems[0][1])

    def test_other_headings_and_the_template(self):
        data = ("Name,Date of Baptism,FC-Nummer\nAna Beispiel,2026-09-20,FC 7654321\n").encode()
        parsed = data_types.parse_people(data_files.read_table("people.csv", data))
        self.assertEqual(parsed.records[0]["fc_number"], "7654321")
        headings, rows = data_types.people_template()
        self.assertIn("FC number", headings)
        self.assertEqual(len(headings), len(rows[0]))

    def test_every_new_text_exists(self):
        for key in ("uploads.people.fcAbout", "uploads.people.withFc", "uploads.people.joinedByFc",
                    "uploads.people.fcTwiceStored", "uploads.people.fcSeveralNames", "uploads.people.fcKept",
                    "uploads.problem.notFcNumber"):
            self.assertIn(key, TEXT)


class MatchingByFcNumber(unittest.TestCase):
    def test_the_same_number_is_the_same_person_whatever_the_name_or_area(self):
        found = resolve([appearance("Ana Beispiel", area=1, fc="1234567")],
                        [stored(9, "Anna Beispielova", area=2, fc="1234567")])
        self.assertEqual(found["questions"], [])
        self.assertEqual([g["stored_id"] for g in found["groups"]], [9])
        self.assertEqual(found["groups"][0]["fc"], "1234567")

    def test_the_same_name_with_two_numbers_is_two_people(self):
        found = resolve([appearance("Ana Beispiel", fc="1111111"), appearance("Ana Beispiel", fc="2222222")])
        self.assertEqual(len(found["groups"]), 2)
        self.assertEqual(found["questions"], [])

    def test_a_stored_person_with_another_number_is_not_joined_by_name(self):
        found = resolve([appearance("Ana Beispiel", fc="1111111")], [stored(9, "Ana Beispiel", fc="2222222")])
        self.assertEqual([g["stored_id"] for g in found["groups"]], [None])  # a new person
        self.assertEqual(found["questions"], [])

    def test_a_row_without_a_number_is_still_matched_by_name(self):
        found = resolve([appearance("Ana Beispiel")], [stored(9, "Ana Beispiel", fc="2222222")])
        self.assertEqual([g["stored_id"] for g in found["groups"]], [9])
        found = resolve([appearance("Ana Beispiel", area=3)], [stored(9, "Ana Beispiel", area=1, fc="2222222")])
        self.assertEqual(len(found["questions"]), 1)  # other area: asked, as before

    def test_a_number_and_the_same_person_without_a_number_become_one(self):
        found = resolve([appearance("Ana Beispiel", fc="1234567", order=1), appearance("Ana Beispiel", order=2)])
        self.assertEqual(len(found["groups"]), 1)
        self.assertEqual(found["groups"][0]["fc"], "1234567")
        self.assertEqual(len(found["groups"][0]["appearances"]), 2)

    def test_rows_with_one_number_are_one_person_and_different_names_are_flagged(self):
        found = resolve([appearance("Ana Beispiel", fc="1234567", order=1), appearance("Anna Beispiel", fc="1234567", order=2)])
        self.assertEqual(len(found["groups"]), 1)
        self.assertEqual(len(found["notices"]), 1)
        self.assertIn("FC number 1234567 has different names", found["notices"][0])
        self.assertIn("Ana Beispiel, Anna Beispiel", found["notices"][0])

    def test_one_number_stored_for_two_people_is_flagged_and_they_are_not_joined(self):
        found = resolve([appearance("Cem Probe", fc="9999999")],
                        [stored(1, "Dora Muster", fc="1234567"), stored(2, "Dora Mustar", area=2, fc="1234567")])
        text = " ".join(found["notices"])
        self.assertIn("FC number 1234567 is saved for 2 people", text)
        self.assertIn("Dora Mustar, Dora Muster", text)
        self.assertEqual([g["stored_id"] for g in found["groups"]], [None])

    def test_a_stored_number_is_kept_when_a_manager_says_same_person(self):
        upload = appearance("Ana Beispiel", fc="1111111")
        person = match.group_people([upload])[0]
        owner = stored(9, "Ana Beispiel", fc="2222222")
        decisions = {match.pair_key(person["key"], owner["key"]): True}
        found = resolve([upload], [owner], decisions)
        self.assertEqual([g["stored_id"] for g in found["groups"]], [9])
        self.assertTrue(any("already has the FC number 2222222" in n and "1111111" in n for n in found["notices"]))

    def test_the_same_number_wins_over_an_old_different_people_answer(self):
        upload = appearance("Ana Beispiel", fc="1234567")
        person = match.group_people([upload])[0]
        owner = stored(9, "Ana Beispiel", fc="1234567")
        found = resolve([upload], [owner], {match.pair_key(person["key"], owner["key"]): False})
        self.assertEqual([g["stored_id"] for g in found["groups"]], [9])

    def test_a_new_member_with_the_number_of_a_friend_was_that_friend(self):
        friend = stored(4, "Ana B.", area=7, fc="1234567", kind=match.FRIEND)
        found = resolve([appearance("Ana Beispiel", area=1, fc="1234567")], [friend])
        self.assertEqual(found["groups"][0]["bapt_from"], 4)

    def test_person_keys(self):
        self.assertEqual(match.person_key(match.NEW_MEMBER, 1, "ana", None, "1234567"), "p:nm:fc:1234567")
        self.assertEqual(match.person_key(match.FRIEND, 1, "ana", None, "1234567"), "p:bd:fc:1234567")
        self.assertEqual(match.person_key(match.NEW_MEMBER, 1, "ana"), "p:nm:1:ana")
        self.assertTrue(match.valid_key("p:nm:fc:1234567"))


class RecordsFromTheUpload(unittest.TestCase):
    def test_the_number_travels_from_the_sheet_to_the_appearance(self):
        record = {"first": "Ana", "last": "Beispiel", "area_id": 1, "unit_id": None, "baptism_date": "2026-09-20",
                  "confirmation_date": None, "baptismal_date_extended": None, "date_of_birth": None, "fc_number": "1234567"}
        self.assertEqual(people_upload.appearances_of([record])[0]["fc"], "1234567")
        del record["fc_number"]
        self.assertIsNone(people_upload.appearances_of([record])[0]["fc"])


class FakeCursor:
    def __init__(self):
        self.calls = []

    def execute(self, query, params=None):
        self.calls.append((str(query), params))

    def fetchone(self):
        return {"id": 5, "baptismal_date_person_id": None}


class SavingTheNumber(unittest.TestCase):
    def group(self, stored_id=None, fc="1234567"):
        return {"kind": match.NEW_MEMBER, "stored_id": stored_id, "area_id": 1, "unit_id": None, "first": "Ana",
                "last": "Beispiel", "baptism_date": date(2026, 9, 20), "appearances": [], "bapt_from": None, "fc": fc}

    def test_a_new_member_is_saved_with_the_number(self):
        counts = {"new_members_added": 0, "new_members_joined": 0, "weekly_rows": 0}
        with patch.object(people_write, "insert_row_ended", return_value=5) as insert, \
                patch.object(people_write, "stake_of", return_value=None):
            people_write.write_new_member(FakeCursor(), self.group(), {}, counts, SUNDAY, [], {})
        self.assertEqual(insert.call_args[0][1]["fc_number"], "1234567")

    def test_a_stored_person_only_gets_a_number_where_there_was_none(self):
        counts = {"new_members_added": 0, "new_members_joined": 0, "weekly_rows": 0}
        with patch.object(people_write, "fill_blanks") as fill:
            people_write.write_new_member(FakeCursor(), self.group(stored_id=9), {}, counts, SUNDAY, [], {})
        table, person_id, values = fill.call_args[0][1:]
        self.assertEqual((table, person_id, values["fc_number"]), ("new_members", 9, "1234567"))

    def test_fill_blanks_never_overwrites_and_skips_an_empty_number(self):
        cursor = FakeCursor()
        people_write.fill_blanks(cursor, "new_members", 9, {"fc_number": None})
        self.assertEqual(cursor.calls, [])  # nothing to fill
        # The stored value wins: the update is set number = coalesce(stored number, new number) (run for real in
        # test_fc_numbers_db).
        self.assertIn("coalesce({t}.{c},%s)", inspect.getsource(people_write.fill_blanks))


if __name__ == "__main__":
    unittest.main()
