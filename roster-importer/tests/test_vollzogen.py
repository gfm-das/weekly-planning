"""The Vollzogen upload without a database: the loose reading of a hand-typed sheet, who is matched to whom, what is saved and
what is kept, the pages' HTML from stand-in answers, the migration text and the 14-language texts. Made-up people only (the
owner's real sheet is never in the repository).

The same flow against a real throw-away database (upload, Undo, the dashboards view, rights) is tests/test_vollzogen_db.py,
written but not run in round 13 (no database in the overnight sandbox). Run this one from roster-importer/:
  python -m unittest tests.test_vollzogen
"""
import json
import os
import re
import unittest
from datetime import date, datetime
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "postgresql://nobody@127.0.0.1:1/none")  # never opened by these tests
import app  # noqa: E402
import batches  # noqa: E402
import data_files  # noqa: E402
import data_types  # noqa: E402
import data_upload_pages  # noqa: E402
import data_uploads  # noqa: E402
import page  # noqa: E402
import people_match as match  # noqa: E402
import vollzogen_pages  # noqa: E402
import vollzogen_upload as vz  # noqa: E402
from data_files import FileProblem, read_confirmed, read_loose_date  # noqa: E402
from data_text import TEXT  # noqa: E402
from tests import data_samples as s  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
TODAY = date(2026, 10, 13)


class LooseDateTests(unittest.TestCase):
    def test_every_way_the_office_types_a_date(self):
        cases = {
            "Dec. 15th. 2025": date(2025, 12, 15), "Jan. 4th, 2026": date(2026, 1, 4), "December 1st 2025": date(2025, 12, 1),
            "15 December 2025": date(2025, 12, 15), "2nd Feb 2026": date(2026, 2, 2), "Mar 3rd, 2026": date(2026, 3, 3),
            "15.12.2025": date(2025, 12, 15), "15. 12. 2025": date(2025, 12, 15), "5.1.26": date(2026, 1, 5),
            "15. Dezember 2025": date(2025, 12, 15), "7. März 2026": date(2026, 3, 7), "3 Okt 2025": date(2025, 10, 3),
            "Dez. 24, 2025": date(2025, 12, 24), "2025-12-15": date(2025, 12, 15), "2025/12/15": date(2025, 12, 15),
            "2025-12-15T10:00:00": date(2025, 12, 15), "12/15/2025": date(2025, 12, 15), "9/27/2025 10:06:42 AM": date(2025, 9, 27),
            "27/9/2025": date(2025, 9, 27), "15-12-2025": date(2025, 12, 15),
            datetime(2025, 12, 15, 0, 0): date(2025, 12, 15), date(2025, 12, 15): date(2025, 12, 15),
            45915: date(2025, 9, 15),  # a spreadsheet date number
        }
        for given, expected in cases.items():
            self.assertEqual(read_loose_date(given), expected, given)

    def test_empty_and_placeholders_are_no_date(self):
        for given in (None, "", "   ", "-", "?", "tba", "x", "N/A", True):
            self.assertIsNone(read_loose_date(given), given)

    def test_what_is_not_a_date_is_refused_with_the_text(self):
        for given in ("sometime in spring", "Dec. 2025", "31.02.2025", "13/13/2025", "Foo 15 2025", 12.5, 99):
            with self.assertRaisesRegex(ValueError, "is not a date"):
                read_loose_date(given)

    def test_the_old_reader_is_unchanged(self):
        with self.assertRaises(ValueError):
            data_files.read_date("Dec. 15th. 2025")  # only the Vollzogen reader is this tolerant

    def test_konfirmiert_an_x_a_date_or_nothing(self):
        self.assertEqual(read_confirmed("X"), (True, None))
        self.assertEqual(read_confirmed(" x "), (True, None))
        self.assertEqual(read_confirmed("Ja"), (True, None))
        self.assertEqual(read_confirmed(datetime(2026, 1, 11)), (True, date(2026, 1, 11)))
        self.assertEqual(read_confirmed("Jan. 11th, 2026"), (True, date(2026, 1, 11)))
        for no in (None, "", "nein", "No", "-"):
            self.assertEqual(read_confirmed(no), (False, None), no)
        with self.assertRaises(ValueError):
            read_confirmed("maybe later")


def parsed_sheet(data=None, name="vollzogen.xlsx"):
    return data_types.parse_vollzogen(data_files.read_table(name, data or s.vollzogen_sheet()), today=TODAY)


class SheetTests(unittest.TestCase):
    def test_the_real_shape_title_row_headings_on_row_two(self):
        parsed = parsed_sheet()
        self.assertEqual([r["full_name"] for r in parsed.records], [s.VOLLZOGEN_PEOPLE[i] for i in (0, 1, 2, 3, 4, 5, 8)])
        self.assertEqual((parsed.rows_read, parsed.left_out, parsed.problem_count), (12, 1, 5))
        self.assertEqual(parsed.records[0]["row"], 3)  # the file row (the title row is row 1, the headings row 2)

    def test_a_person_with_every_column(self):
        first = parsed_sheet().records[0]
        self.assertEqual({k: first[k] for k in ("found_how", "baptismal_date_set_on", "baptism_date", "workers", "unit", "stake",
                                                "zone", "confirmed", "confirmed_on", "country", "gender", "preferred_language",
                                                "fc_number", "first", "last")},
                         {"found_how": "Contacting in Public", "baptismal_date_set_on": "2025-12-01", "baptism_date": "2025-12-15",
                          "workers": "Elder Sample, Sister Example", "unit": "Frankfurt 1st", "stake": "Frankfurt", "zone": "Frankfurt",
                          "confirmed": True, "confirmed_on": None, "country": "Testland", "gender": "F",
                          "preferred_language": "German", "fc_number": None, "first": "Testa", "last": "Beispiel"})

    def test_mixed_dates_and_marks_become_one_format(self):
        by_name = {r["full_name"]: r for r in parsed_sheet().records}
        probe = by_name["Probe Person"]
        self.assertEqual((probe["baptismal_date_set_on"], probe["baptism_date"], probe["confirmed"], probe["confirmed_on"]),
                         ("2025-11-15", "2026-01-04", True, "2026-01-11"))  # German set date, English baptism date, a real date
        mira = by_name["Mira Musterfrau"]
        self.assertEqual((mira["baptism_date"], mira["confirmed"]), ("2026-02-01", True))  # spreadsheet dates and a small x
        self.assertEqual(by_name["Alma Erfunden"]["baptism_date"], "2026-03-07")
        nora = by_name["Nora Nirgends"]
        self.assertEqual((nora["baptism_date"], nora["confirmed"]), ("2026-03-07", False))  # "7. März 2026"; "nein" is not confirmed
        ivo = by_name["Ivo Imaginär"]
        self.assertEqual(ivo["baptism_date"], "2026-03-19")  # a spreadsheet date number (46100)
        self.assertEqual((ivo["workers"], ivo["country"]), (None, None))  # empty cells are None

    def test_blank_placeholder_and_unreadable_rows_are_skipped_and_explained(self):
        parsed = parsed_sheet()
        texts = [text for _row, text in parsed.problems]
        self.assertEqual(len(texts), 5)
        self.assertTrue(any("No baptism date" in t for t in texts))
        self.assertTrue(any("'sometime in spring' is not a date" in t for t in texts))
        self.assertTrue(any("2062-01-01" in t and "check the year" in t for t in texts))
        self.assertTrue(any("in the file twice" in t for t in texts))
        self.assertTrue(any("No name" in t for t in texts))
        names = [r["full_name"] for r in parsed.records]
        for left_out in ("TBD", s.VOLLZOGEN_PEOPLE[6], s.VOLLZOGEN_PEOPLE[7], s.VOLLZOGEN_PEOPLE[9]):
            self.assertNotIn(left_out, names)
        self.assertEqual(names.count(s.VOLLZOGEN_PEOPLE[8]), 1)

    def test_a_csv_reads_the_same(self):
        parsed = parsed_sheet(s.vollzogen_csv(), "vollzogen.csv")
        # The same people, except Ivo: a CSV has no spreadsheet date numbers, so "46100" is only text and a problem line.
        self.assertEqual(len(parsed.records), 6)
        self.assertEqual(parsed.problem_count, 6)
        self.assertEqual(parsed.records[1]["baptism_date"], "2026-01-04")
        self.assertEqual(parsed.records[1]["confirmed_on"], "2026-01-11")

    def test_an_fc_number_column_is_read_and_a_bad_cell_is_a_problem(self):
        rows = [["Name", "Taufdatum", "FC number", "Zone"], ["Ana Example", "Dec. 15th. 2025", "FC-123 456", "Alpha"],
                ["Ben Example", "Dec. 16th. 2025", "??", "Alpha"]]
        parsed = data_types.parse_vollzogen(rows, today=TODAY)
        self.assertEqual([r["fc_number"] for r in parsed.records], ["123456", None])
        self.assertEqual(parsed.problem_count, 1)

    def test_other_headings_are_read_as_well(self):
        rows = [["Full name", "Baptism date", "Stake", "Confirmation date"], ["Ana Example", "2025-12-15", "Alpha", "2025-12-21"]]
        record = data_types.parse_vollzogen(rows, today=TODAY).records[0]
        self.assertEqual((record["stake"], record["confirmed_on"], record["confirmed"]), ("Alpha", "2025-12-21", True))

    def test_a_file_without_the_headings_is_refused(self):
        with self.assertRaises(FileProblem):
            data_types.parse_vollzogen([["Foo", "Bar"], ["a", "b"]])

    def test_the_template_reads_back_and_shows_the_example(self):
        headings, rows = data_types.vollzogen_template()
        self.assertEqual(headings[:4], ["Wie gefunden", "Name", "Wann gesetzt", "Taufdatum"])
        self.assertEqual(headings[-1], "FC number")
        parsed = data_types.parse_vollzogen(data_files.read_table("t.csv", data_files.as_csv(headings, rows)), today=TODAY)
        self.assertEqual((len(parsed.records), parsed.problem_count), (1, 0))
        self.assertEqual(parsed.records[0]["fc_number"], "1234567")


def stored(member_id, name, zone="Frankfurt", day=None, fc=None):
    return {"id": member_id, "label": name, "folded": match.fold(name), "baptism_date": day, "fc": fc, "zone": zone,
            "zone_key": vz.data_names.fold_zone(zone)}


def record(name, zone="Frankfurt", day="2025-12-15", fc=None):
    return {"full_name": name, "zone": zone, "baptism_date": day, "fc_number": fc, "record_key": f"{match.fold(name)}|{day}",
            "confirmed": False, "confirmed_on": None, "baptismal_date_set_on": None}


class MatchingTests(unittest.TestCase):
    def result(self, records, members, decisions=None):
        return vz.match_records(records, members, decisions or {})

    def test_the_same_fc_number_is_the_same_person_whatever_the_name(self):
        found = self.result([record("Ana Beispiel", fc="123456")], [stored(7, "Anna B.", "Elsewhere", fc="123456")])
        self.assertEqual(found["links"]["ana beispiel|2025-12-15"], {"member_id": 7, "how": "FC"})
        self.assertEqual(found["questions"], [])

    def test_two_different_fc_numbers_are_never_joined_by_name(self):
        found = self.result([record("Ana Beispiel", fc="111")], [stored(7, "Ana Beispiel", fc="222")])
        self.assertEqual((found["links"], found["questions"]), ({}, []))

    def test_same_name_and_zone_is_the_same_person_without_asking(self):
        found = self.result([record("Ana Beispiel")], [stored(7, "Ana Beispiel")])
        self.assertEqual(list(found["links"].values()), [{"member_id": 7, "how": "NAME"}])

    def test_same_name_and_baptism_date_in_another_zone_is_the_same_person(self):
        found = self.result([record("Ana Beispiel", zone="Alpha")], [stored(7, "Ana Beispiel", "Beta", day=date(2025, 12, 15))])
        self.assertEqual(list(found["links"].values()), [{"member_id": 7, "how": "NAME"}])

    def test_the_same_name_with_nothing_to_back_it_up_is_asked(self):
        found = self.result([record("Ana Beispiel", zone="Alpha")], [stored(7, "Ana Beispiel", "Beta")])
        self.assertEqual(found["links"], {})
        self.assertEqual([(q["member"]["id"], q["reason"]) for q in found["questions"]], [(7, "same_name_unsure")])
        self.assertEqual(found["questions"][0]["keys"], match.pair_key("p:nm:vz:ana beispiel:2025-12-15", "id:nm:7"))

    def test_an_alike_name_in_the_same_zone_is_asked_and_in_another_zone_is_not(self):
        asked = self.result([record("Ana Beispiel")], [stored(7, "Anna Beispiel")])
        self.assertEqual([q["reason"] for q in asked["questions"]], ["alike_name"])
        other = self.result([record("Ana Beispiel")], [stored(7, "Anna Beispiel", "Beta")])
        self.assertEqual((other["links"], other["questions"]), ({}, []))

    def test_a_clashing_baptism_date_means_different_people(self):
        found = self.result([record("Ana Beispiel")], [stored(7, "Ana Beispiel", day=date(2024, 1, 5))])
        self.assertEqual((found["links"], found["questions"]), ({}, []))

    def test_two_sure_matches_are_asked_not_guessed(self):
        found = self.result([record("Ana Beispiel")], [stored(7, "Ana Beispiel"), stored(8, "Ana Beispiel")])
        self.assertEqual((found["links"], sorted(q["member"]["id"] for q in found["questions"])), ({}, [7, 8]))

    def test_a_remembered_answer_decides(self):
        key = match.pair_key("p:nm:vz:ana beispiel:2025-12-15", "id:nm:7")
        asked = [record("Ana Beispiel", zone="Alpha")], [stored(7, "Ana Beispiel", "Beta")]
        same = self.result(*asked, {key: True})
        self.assertEqual(list(same["links"].values()), [{"member_id": 7, "how": "ASKED"}])
        different = self.result(*asked, {key: False})
        self.assertEqual((different["links"], different["questions"]), ({}, []))

    def test_an_fc_number_stored_for_two_people_is_noticed(self):
        found = self.result([], [stored(7, "A One", fc="999"), stored(8, "B Two", fc="999")])
        self.assertEqual(len(found["notices"]), 1)
        self.assertIn("999", found["notices"][0])
        both = self.result([record("C Three", fc="999")], [stored(8, "B Two", fc="999"), stored(7, "A One", fc="999")])
        self.assertEqual(list(both["links"].values()), [{"member_id": 7, "how": "FC"}])  # the older one


class MergeTests(unittest.TestCase):
    OLD = {"id": 4, "found_how": "Street", "baptismal_date_set_on": date(2025, 12, 1), "workers": "Elder Sample", "unit": "A",
           "stake": "S", "zone": "Z", "confirmed": True, "confirmed_on": date(2025, 12, 21), "country": "Testland", "gender": "F",
           "preferred_language": "German", "fc_number": "555", "new_member_id": 9, "matched_how": "ASKED"}

    def test_a_new_person_takes_everything_the_file_has(self):
        rec = {**record("Ana Beispiel", fc="777"), "found_how": "Media", "confirmed": True, "confirmed_on": "2025-12-21",
               "baptismal_date_set_on": "2025-12-01"}
        values = vz.merged_values(None, rec, {"member_id": 3, "how": "FC"})
        self.assertEqual((values["found_how"], values["confirmed"], values["confirmed_on"], values["fc_number"],
                          values["new_member_id"], values["matched_how"], values["baptismal_date_set_on"]),
                         ("Media", True, date(2025, 12, 21), "777", 3, "FC", date(2025, 12, 1)))

    def test_an_empty_cell_keeps_what_is_saved_and_a_filled_one_updates(self):
        values = vz.merged_values(self.OLD, {**record("Ana Beispiel"), "found_how": None, "workers": "Elder Example"}, None)
        self.assertEqual((values["found_how"], values["workers"]), ("Street", "Elder Example"))

    def test_confirmed_never_goes_back_and_an_fc_number_and_a_link_are_never_replaced(self):
        values = vz.merged_values(self.OLD, {**record("Ana Beispiel", fc="999"), "confirmed": False},
                                  {"member_id": 3, "how": "NAME"})
        self.assertEqual((values["confirmed"], values["confirmed_on"], values["fc_number"], values["new_member_id"],
                          values["matched_how"]), (True, date(2025, 12, 21), "555", 9, "ASKED"))

    def test_a_saved_person_without_a_link_gets_one(self):
        values = vz.merged_values({**self.OLD, "new_member_id": None, "matched_how": None}, record("Ana Beispiel"),
                                  {"member_id": 3, "how": "NAME"})
        self.assertEqual((values["new_member_id"], values["matched_how"]), (3, "NAME"))


def render(query):
    """psycopg2.sql objects as text (they need a connection to render themselves): identifiers in double quotes."""
    from psycopg2 import sql
    if isinstance(query, str):
        return query
    if isinstance(query, sql.Composed):
        return "".join(render(part) for part in query.seq)
    if isinstance(query, sql.Identifier):
        return ".".join('"' + s + '"' for s in query.strings)
    if isinstance(query, (sql.SQL, sql.Literal)):
        return query.string if isinstance(query, sql.SQL) else repr(query.wrapped)
    if isinstance(query, sql.Placeholder):
        return "%s"
    return str(query)


class FakeCursor:
    """Stands in for the database cursor: records every statement."""

    def __init__(self, rows=None):
        self.statements, self.rows = [], rows or []

    def execute(self, query, params=None):
        self.statements.append((render(query), params))

    def fetchall(self):
        return self.rows


class SavingTests(unittest.TestCase):
    def planned(self, stored_rows, links=None):
        return {"stored": stored_rows, "found": {"links": links or {}, "questions": []}}

    def test_new_people_are_inserted_changed_ones_updated_and_unchanged_ones_left_alone(self):
        old_same = {**MergeTests.OLD, "record_key": "same one|2025-12-15"}
        old_changed = {**MergeTests.OLD, "id": 5, "record_key": "changed one|2025-12-15", "workers": "Elder Old"}
        records = [{**record("New One"), "workers": "Elder Sample"},
                   {**record("Same One"), "found_how": "Street", "workers": "Elder Sample", "unit": "A", "stake": "S", "zone": "Z",
                    "confirmed": True, "confirmed_on": "2025-12-21", "baptismal_date_set_on": "2025-12-01", "country": "Testland",
                    "gender": "F", "preferred_language": "German"},
                   {**record("Changed One"), "workers": "Elder New"}]
        cur = FakeCursor()
        with patch.object(vz.sign_in, "current_mission_id", return_value=2), patch.object(vz.sign_in, "actor_name", return_value="Test Analyst"):
            vz.save_records(cur, records, self.planned({"same one|2025-12-15": old_same, "changed one|2025-12-15": old_changed}))
        kinds = [text.split()[0].lower() for text, _ in cur.statements]
        self.assertEqual(kinds, ["insert", "update"])
        insert_params = cur.statements[0][1]
        self.assertEqual(insert_params[:4], [2, "new one|2025-12-15", "New One", date(2025, 12, 15)])
        self.assertEqual(cur.statements[1][1][-1], 5)  # the changed person's row id
        self.assertIn("workers", cur.statements[1][0])

    def test_the_insert_names_only_known_columns(self):
        cur = FakeCursor()
        with patch.object(vz.sign_in, "current_mission_id", return_value=2), patch.object(vz.sign_in, "actor_name", return_value="x"):
            vz.save_records(cur, [record("New One")], self.planned({}))
        columns = re.findall(r'"(\w+)"', cur.statements[0][0])
        self.assertEqual(columns[:4], ["mission_id", "record_key", "full_name", "baptism_date"])
        self.assertEqual(columns[-1], "updated_by")
        self.assertEqual(len(columns), len(cur.statements[0][1]))

    def test_apply_refuses_while_a_question_is_open_and_changes_nothing(self):
        class Conn:
            rolled_back = False

            def rollback(self):
                self.rolled_back = True

            def close(self):
                pass

        conn = Conn()
        open_question = {"found": {"links": {}, "questions": [{"keys": ("a", "b")}]}, "stored": {}, "counts": {}}
        with patch.object(vz.database, "connect", return_value=conn), patch.object(vz.database, "cursor", return_value=FakeCtx()), \
                patch.object(vz.batches, "lock_tables"), patch.object(vz, "plan", return_value=open_question), \
                patch.object(vz.sign_in, "current_mission_id", return_value=2), \
                patch.object(vz.batches, "create_batch") as create:
            with self.assertRaisesRegex(ValueError, "Answer the questions"):
                vz.apply({"filename": "x.xlsx", "parsed": {"records": [record("A B")], "rows_read": 1}})
        self.assertTrue(conn.rolled_back)
        create.assert_not_called()


class FakeCtx:
    def __enter__(self):
        return FakeCursor()

    def __exit__(self, *args):
        return False


class PlanTests(unittest.TestCase):
    def test_the_numbers_of_the_check(self):
        records = [record("Ana Beispiel"), record("Ben Neu"), record("Cleo Alt")]
        old = {**MergeTests.OLD, "id": 1, "record_key": "cleo alt|2025-12-15", "new_member_id": None, "matched_how": None,
               "found_how": None, "workers": None, "unit": None, "stake": None, "zone": "Frankfurt", "confirmed": False,
               "confirmed_on": None, "baptismal_date_set_on": None, "country": None, "gender": None, "preferred_language": None,
               "fc_number": None}
        with patch.object(vz, "stored_members", return_value=[stored(7, "Ana Beispiel")]), \
                patch.object(vz.match, "load_decisions", return_value={}), patch.object(vz, "stored_records", return_value={old["record_key"]: old}), \
                patch.object(vz.sign_in, "current_mission_id", return_value=2):
            planned = vz.plan(None, records)
        self.assertEqual(planned["counts"], {"new": 2, "changed": 0, "same": 1, "linked": 1, "by_fc": 0, "by_name": 1,
                                             "asked": 0, "unlinked": 2})


class PageTests(unittest.TestCase):
    def test_a_stranger_is_sent_to_the_sign_in(self):
        client = app.app.test_client()
        for path in ("/uploads/vollzogen", "/uploads/vollzogen/table", "/uploads/vollzogen/template", "/uploads/vollzogen/review"):
            self.assertEqual(client.get(path).status_code, 302, path)

    def test_the_template_is_a_csv_a_manager_can_download(self):
        with patch.object(vollzogen_pages.sign_in, "allowed", return_value=True):
            response = app.app.test_client().get("/uploads/vollzogen/template")
        self.assertEqual((response.status_code, response.mimetype), (200, "text/csv"))
        self.assertIn("template-vollzogen.csv", response.headers["Content-Disposition"])
        self.assertIn("Wie gefunden", response.get_data(as_text=True))

    def test_the_menu_the_kind_and_the_hub_know_the_upload(self):
        self.assertEqual(page.current_page("/uploads/vollzogen"), ("uploads", "/uploads"))
        self.assertEqual(page.current_page("/uploads/vollzogen/review"), ("uploads", "/uploads"))
        self.assertEqual(data_uploads.kind_label("VOLLZOGEN"), "Vollzogen")
        self.assertEqual(batches.TABLES_OF_KIND["VOLLZOGEN"], ["vollzogen_records"])
        self.assertNotIn("VOLLZOGEN", data_uploads.ROW_KINDS)  # its rows are recorded as before/after, like Geo data

    def test_the_exact_routes_win_over_the_generic_upload_routes(self):
        adapter = app.app.url_map.bind("localhost")
        for path in ("/uploads/vollzogen", "/uploads/vollzogen/review", "/uploads/vollzogen/apply"):
            endpoint, _ = adapter.match(path, method="POST" if path.endswith("apply") else "GET")
            self.assertTrue(endpoint.startswith("vollzogen_pages."), (path, endpoint))

    def test_the_check_page_shows_numbers_questions_and_problems(self):
        parsed = parsed_sheet().as_dict()
        pending = {"filename": "vollzogen.xlsx", "parsed": parsed}
        members = [stored(7, "Testa Beispiel"), stored(8, "Mira Musterfrau", "Beta")]
        with patch.object(vollzogen_pages.database, "connect", return_value=FakeCtx()), \
                patch.object(vollzogen_pages.database, "cursor", return_value=FakeCtx()), \
                patch.object(vz, "stored_members", return_value=members), patch.object(vz.match, "load_decisions", return_value={}), \
                patch.object(vz, "stored_records", return_value={}), patch.object(vz.sign_in, "current_mission_id", return_value=2):
            html = vollzogen_pages.review_page(pending)
        for text in ("Vollzogen: vollzogen.xlsx", "People: 7 new", "1 are linked to a person in the portal (0 by FC number, 1 by name",
                     "6 are not in the portal", "1 pair(s) to check", "Mira Musterfrau", "Same person", "Different people",
                     "Rows with a problem", "sometime in spring", "decide::", "value=\"/uploads/vollzogen/review\""):
            self.assertIn(text, html)
        self.assertNotIn("Apply</button>", html)  # closed while a question is open
        self.assertIn("Answer the questions about people who may be the same first", html)

    def test_apply_is_open_when_nothing_is_asked(self):
        pending = {"filename": "v.xlsx", "parsed": parsed_sheet().as_dict()}
        with patch.object(vollzogen_pages.database, "connect", return_value=FakeCtx()), \
                patch.object(vollzogen_pages.database, "cursor", return_value=FakeCtx()), \
                patch.object(vz, "stored_members", return_value=[]), patch.object(vz.match, "load_decisions", return_value={}), \
                patch.object(vz, "stored_records", return_value={}), patch.object(vz.sign_in, "current_mission_id", return_value=2):
            html = vollzogen_pages.review_page(pending)
        self.assertIn('action="/uploads/vollzogen/apply"', html)
        self.assertIn("I checked this upload.", html)

    def test_a_sheet_whose_names_are_all_placeholders_says_so(self):
        # The owner's example export has the word "Name" in every Name cell: nothing can be saved, and the page says why.
        rows = [["Wie gefunden", "Name", "Taufdatum", "Zone"], ["Street", "Name", "Dec. 15th. 2025", "Alpha"], ["Street", "Name", "Dec. 16th. 2025", "Alpha"]]
        parsed = data_types.parse_vollzogen(rows, today=TODAY)
        self.assertEqual((len(parsed.records), parsed.left_out), (0, 2))
        with patch.object(vollzogen_pages.database, "connect", return_value=FakeCtx()), \
                patch.object(vollzogen_pages.database, "cursor", return_value=FakeCtx()), \
                patch.object(vz, "stored_members", return_value=[]), patch.object(vz.match, "load_decisions", return_value={}), \
                patch.object(vz, "stored_records", return_value={}), patch.object(vz.sign_in, "current_mission_id", return_value=2):
            html = vollzogen_pages.review_page({"filename": "v.xlsx", "parsed": parsed.as_dict()})
        self.assertIn("only a placeholder in the Name column", html)
        self.assertNotIn("Apply</button>", html)

    def test_names_are_escaped_on_the_page(self):
        record_ = {**record("<b>Ana</b> Beispiel"), "unit": None}
        html = vollzogen_pages.sample_table([record_], {record_["record_key"]: "<i>X</i>"})
        self.assertNotIn("<b>Ana", html)
        self.assertIn("&lt;b&gt;Ana", html)
        self.assertIn("&lt;i&gt;X", html)


class TextAndMigrationTests(unittest.TestCase):
    def test_every_vollzogen_text_is_in_every_language_catalog(self):
        folder = ROOT / "portal" / "i18n"
        english = json.loads((folder / "en.json").read_text(encoding="utf-8"))
        wanted = {key: value for key, value in TEXT.items() if key.startswith("uploads.vollzogen.") or
                  key in ("uploads.kind.vollzogen", "uploads.problem.noName", "uploads.problem.dateFar", "uploads.col.name",
                          "uploads.col.foundHow", "uploads.col.dateSet", "uploads.col.baptismDate", "uploads.col.workers",
                          "uploads.col.unit", "uploads.col.stake", "uploads.col.confirmed", "uploads.col.country",
                          "uploads.col.gender", "uploads.col.language", "uploads.col.linkedTo")}
        self.assertGreaterEqual(len(wanted), 30)
        texts = {value for value in english.values() if isinstance(value, str)}
        self.assertEqual(sorted(key for key, value in wanted.items() if value not in texts), [])
        for code in json.loads((folder / "catalogs.json").read_text(encoding="utf-8"))["languages"]:
            catalog = json.loads((folder / f"{code}.json").read_text(encoding="utf-8"))
            for key, value in wanted.items():
                owner = next(k for k, v in english.items() if v == value)
                self.assertTrue(str(catalog[owner]).strip(), (code, key))
                self.assertEqual(sorted(re.findall(r"\{(\w+)\}", catalog[owner])), sorted(re.findall(r"\{(\w+)\}", value)), (code, key))

    def test_migration_051_is_one_transaction_with_a_closed_table_and_a_rollback(self):
        folder = ROOT / "portal-api" / "migrations"
        up = (folder / "051_vollzogen_records.sql").read_text(encoding="utf-8")
        down = (folder / "051_vollzogen_records_rollback.sql").read_text(encoding="utf-8")
        for text in (up, down):
            code = "\n".join(line for line in text.splitlines() if not line.startswith("--"))
            self.assertEqual(len(re.findall(r"^BEGIN;", code, re.M)), 1)
            self.assertEqual(len(re.findall(r"^COMMIT;", code, re.M)), 1)
        self.assertIn("ENABLE ROW LEVEL SECURITY", up)
        self.assertNotIn("CREATE POLICY", up)
        self.assertIn("REVOKE ALL ON public.vollzogen_records FROM PUBLIC, anon, authenticated, service_role", up)
        self.assertIn("GRANT SELECT ON dashboards.vollzogen_week TO gfm_dashboard_reader", up)
        self.assertNotIn("GRANT SELECT ON public", up)
        self.assertIn("'VOLLZOGEN'", up.replace("VOLLZOGEN'::text", "'VOLLZOGEN'"))
        self.assertIn("ON DELETE SET NULL", up)
        self.assertIn("DROP TABLE IF EXISTS public.vollzogen_records", down)
        self.assertIn("DROP VIEW IF EXISTS dashboards.vollzogen_week", down)
        self.assertIn("array_remove(kinds, 'VOLLZOGEN')", down)
        # The columns the code writes are the columns of the table.
        for column in vz.FIELDS + ["mission_id", "record_key", "full_name", "baptism_date", "updated_by"]:
            self.assertRegex(up, rf"\n  {column} ", column)

    def test_the_view_has_no_column_that_identifies_a_person(self):
        up = (ROOT / "portal-api" / "migrations" / "051_vollzogen_records.sql").read_text(encoding="utf-8")
        view = up[up.index("CREATE OR REPLACE VIEW dashboards.vollzogen_week"):up.index("COMMENT ON VIEW")]
        self.assertNotRegex(view, r"full_name|fc_number|new_member_id|workers|country|gender")


if __name__ == "__main__":
    unittest.main()
