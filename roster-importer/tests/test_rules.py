"""Small rules of DA Management, tested without a database (round 9: the functions that had no test of their own).

Each test gives a function a made-up value and checks the answer: reading a roster file, what "Send account setup"
would do, which role an account has, what a save would record, the page language, the language codes, the
Historical CSV choices from the form, and the helpers of batches and Undo. Round 9, stage 2 added: kept database
connections (with a stand-in connection), pages packed with gzip, and the buttons and lists that were made leaner
(Planning questions, Area mappings, Staff accounts, Account Manager).

Run in DA Management's image (it has Flask), from roster-importer/:
  docker run --rm --network none -v <repo>:/repo -w /repo/roster-importer
    -e DATABASE_URL=postgresql://nobody@127.0.0.1:1/none roster-importer-roster-importer
    python -m unittest tests.test_rules
"""
import gzip
import os
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

from werkzeug.datastructures import MultiDict

os.environ.setdefault("DATABASE_URL", "postgresql://nobody@127.0.0.1:1/none")  # never opened by these tests
import account_changes  # noqa: E402
import account_links  # noqa: E402
import account_manager  # noqa: E402
import account_page  # noqa: E402
import account_roles  # noqa: E402
import app  # noqa: E402
import batches  # noqa: E402
import data_upload_pages  # noqa: E402
import database  # noqa: E402
import historical_pages  # noqa: E402
import mappings_page  # noqa: E402
import page  # noqa: E402
import planning_questions as pq  # noqa: E402
import planning_questions_pages  # noqa: E402
import roles  # noqa: E402
import roster_file  # noqa: E402
import settings  # noqa: E402
import staff_accounts  # noqa: E402
import transfer  # noqa: E402
import undo  # noqa: E402

TODAY = date(2026, 9, 29)
HEADINGS = ",".join(roster_file.REQUIRED_COLUMNS)


def leader(role, start=date(2026, 1, 1), end=None, **ids):
    return {"id": hash((role, start)), "role": role, "start_date": start, "end_date": end, "district": "North",
            "zone": "Rhine", "district_id": ids.get("district_id"), "zone_id": ids.get("zone_id"),
            "mission_id": ids.get("mission_id")}


class RosterFileTests(unittest.TestCase):
    def write(self, *lines):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        path = Path(folder.name) / "roster.csv"
        path.write_text("\n".join(lines), encoding="utf-8")
        return path

    def test_dates_in_every_written_form(self):
        for text in ("04 Oct 2026", "2026-10-04", "04.10.2026", "10/04/2026"):
            self.assertEqual(roster_file.parse_date(text), date(2026, 10, 4), text)
        self.assertIsNone(roster_file.parse_date("  "))
        with self.assertRaisesRegex(ValueError, "Unrecognized date"):
            roster_file.parse_date("soon")

    def test_names_and_titles(self):
        self.assertEqual(roster_file.parse_name("Smith, Tom Andrew", "Elder"), ("Tom", "Smith", "Elder Smith"))
        self.assertEqual(roster_file.parse_name("Anna  Maria Muster", "Sister"), ("Anna", "Muster", "Sister Muster"))

    def test_units_keep_their_number_and_come_once(self):
        self.assertEqual(roster_file.parse_units("Frankfurt 1st (66230), Frankfurt 2nd (English) (80144), Frankfurt 1st (66230)"),
                         [{"name": "Frankfurt 1st", "unit_number": "66230"},
                          {"name": "Frankfurt 2nd (English)", "unit_number": "80144"}])
        self.assertEqual(roster_file.parse_units("Bockenheim, bockenheim"), [{"name": "Bockenheim", "unit_number": None}])
        self.assertEqual(roster_file.parse_units(""), [])

    def test_leadership_roles_from_the_position(self):
        self.assertEqual(roster_file.roster_roles({"Position Abbr": "ZLL; DL, zl2, Trainer"}), ["ZL", "DL"])
        self.assertEqual(roster_file.roster_roles({"Position Abbr": None}), [])

    def test_a_roster_file_is_read_and_checked(self):
        good = '"Smith, Tom",900001,Elder,Teaching,Active,Rhine,North,Mitte,Mitte Ward (1),tom@example.invalid,01 Jan 2026,01 Jan 2028,Zone Leader,ZL'
        released = '"Old, Ann",900002,Sister,Teaching,Released,Rhine,North,Mitte,,,01 Jan 2024,01 Jan 2026,,'
        rows = roster_file.read_roster(self.write(HEADINGS, good, released))
        self.assertEqual(len(rows), 1)  # only Active and In-field rows
        self.assertEqual((rows[0]["missionary_number"], rows[0]["display_name"], rows[0]["roles"], rows[0]["special_assignment"]),
                         ("900001", "Elder Smith", ["ZL"], None))
        with self.assertRaisesRegex(ValueError, "Missing required columns: Unit"):
            roster_file.read_roster(self.write(HEADINGS.replace(",Unit,", ",")))
        with self.assertRaisesRegex(ValueError, "Row 3: duplicate ID 900001"):
            roster_file.read_roster(self.write(HEADINGS, good, good))
        with self.assertRaisesRegex(ValueError, "missing Zone, District, or Area"):
            roster_file.read_roster(self.write(HEADINGS, good.replace(",Mitte,Mitte Ward", ",,Mitte Ward")))
        with self.assertRaisesRegex(ValueError, "No active/in-field roster rows found"):
            roster_file.read_roster(self.write(HEADINGS, released))
        # The Church's heading "Ecclesiastical Unit" is read as Unit.
        rows = roster_file.read_roster(self.write(HEADINGS.replace(",Unit,", ",Ecclesiastical Unit,"), good))
        self.assertEqual(rows[0]["units"], [{"name": "Mitte Ward", "unit_number": "1"}])


class TransferRulesTests(unittest.TestCase):
    def test_units_by_area_joins_everyone_serving_there(self):
        rows = [{"zone": "Z", "district": "D", "area": "A", "units": [{"name": "One", "unit_number": "1"}]},
                {"zone": "Z", "district": "D", "area": "A", "units": [{"name": "One", "unit_number": "1"},
                                                                       {"name": "Two", "unit_number": None}]},
                {"zone": "Z", "district": "D", "area": "B", "units": []}]
        found = transfer.units_by_area(rows)
        self.assertEqual([u["name"] for u in found[("Z", "D", "A")]["units"]], ["One", "Two"])
        self.assertFalse(found[("Z", "D", "B")]["has_unit_data"])
        self.assertEqual(transfer.unit_text({"name": "One", "unit_number": "1"}), "One (1)")

    def test_notes_of_the_preview(self):
        changes = {"email_updates": ["x"]}
        notes = transfer.preview_notes(changes, 2, date(2020, 1, 5))
        self.assertTrue(notes[0].startswith("A transfer dated 05 Jan 2020 is already recorded."))
        self.assertIn("send account setup", notes[1])
        self.assertEqual(transfer.preview_notes({"email_updates": []}, 0, date(2020, 1, 5)), [])


class SendAccountSetupTests(unittest.TestCase):
    own = {"id": "u1", "active": True, "email": "old@example.invalid", "app_role": "MISSIONARY", "additional_roles": []}
    free = {"id": "u2", "missionary_id": None, "profile_id": None, "home_mission_id": None, "app_role": None, "additional_roles": None}

    def test_every_action(self):
        choose = account_links.choose_action
        self.assertEqual(choose("", None, None)["action"], "SKIP")
        self.assertEqual(choose("new@example.invalid", dict(self.own, active=False), None)["action"], "SKIP")
        self.assertEqual(choose("OLD@example.invalid", self.own, None)["action"], "RESET")
        self.assertEqual(choose("new@example.invalid", self.own, self.free)["action"], "SKIP")  # the address is taken
        self.assertEqual(choose("new@example.invalid", self.own, None),
                         {"action": "EMAIL", "auth_user_id": "u1", "old_email": "old@example.invalid"})
        self.assertEqual(choose("new@example.invalid", None, dict(self.free, missionary_id=7))["action"], "SKIP")
        self.assertEqual(choose("new@example.invalid", None, dict(self.free, profile_id="u2", home_mission_id="2"))["action"], "SKIP")
        self.assertEqual(choose("new@example.invalid", None, self.free), {"action": "LINK", "auth_user_id": "u2"})
        self.assertEqual(choose("new@example.invalid", None, None), {"action": "INVITE"})

    def test_the_plan_token_changes_with_the_plan(self):
        plan = {"missionary_id": 1, "action": "RESET", "auth_user_id": "u1", "email": "a@example.invalid", "old_email": None,
                "reason": None, "display_name": "Elder A"}
        token = account_links.plan_token([plan])
        self.assertEqual(token, account_links.plan_token([dict(plan, email="A@EXAMPLE.invalid")]))  # capitals do not count
        self.assertNotEqual(token, account_links.plan_token([dict(plan, action="INVITE")]))
        self.assertEqual(account_links.describe(plan), "Password email to a@example.invalid.")


class AccountManagerRulesTests(unittest.TestCase):
    row = {"missionary_id": 1, "email": "a@example.invalid", "auth_user_id": "u1", "linked_missionary_id": 1,
           "profile_active": True, "last_sign_in_at": None, "app_role": "PRESIDENT", "additional_roles": ["DATA_ADMIN", "OFFICE"],
           "leadership_roles": "ZL", "roster_position_abbr": "ZL", "zone": "Rhine", "district": "North", "area": "Mitte",
           "display_name": "Elder A"}

    def test_account_status(self):
        status = account_manager.account_status
        self.assertEqual(status(self.row), "Invited")
        self.assertEqual(status(dict(self.row, last_sign_in_at=TODAY)), "Active")
        self.assertEqual(status(dict(self.row, profile_active=False)), "Disabled")
        self.assertEqual(status(dict(self.row, linked_missionary_id=2)), "Unlinked")
        self.assertEqual(status(dict(self.row, auth_user_id=None)), "Missing")
        self.assertEqual(status(dict(self.row, email=None)), "No email")

    def test_roles_and_filters(self):
        row = dict(self.row, account_roles=account_manager.hand_set_roles(self.row), account_status="Invited")
        self.assertEqual(row["account_roles"], "President, Data Analyst, Office")
        filters = {"zone": "", "district": "", "area": "", "role": "data analyst", "status": "", "q": "elder a"}
        self.assertTrue(account_manager.matches(row, filters))
        self.assertFalse(account_manager.matches(row, dict(filters, zone="Other")))
        self.assertFalse(account_manager.matches(row, dict(filters, role="DL")))


class AccountRoleTests(unittest.TestCase):
    def test_role_today_comes_from_assignments_in_force(self):
        leaders = [leader("ZL"), leader("AP", start=TODAY + timedelta(days=3))]
        self.assertEqual(account_roles.effective_role("AP", leaders, TODAY), "ZL")  # a saved AP counts for nothing
        self.assertEqual(account_roles.effective_role("PRESIDENT", leaders, TODAY), "PRESIDENT")
        self.assertEqual(account_roles.effective_role(None, [], TODAY), "MISSIONARY")

    def test_the_recorded_role_is_never_ahead_of_its_assignment(self):
        self.assertEqual(account_roles.recorded_role("AP", [leader("AP", start=TODAY + timedelta(days=3))], TODAY), "MISSIONARY")
        self.assertEqual(account_roles.recorded_role("AP", [leader("AP", end=TODAY + timedelta(days=3))], TODAY), "MISSIONARY")
        self.assertEqual(account_roles.recorded_role("DL", [leader("ZL")], TODAY), "DL")  # a lower chosen role at once
        self.assertEqual(account_roles.recorded_role("OFFICE", [], TODAY), "OFFICE")

    def test_leader_names(self):
        self.assertEqual(account_roles.leader_label("DL", "North", "Rhine"), "DL assignment for North district")
        self.assertEqual(account_roles.leader_label("AP", form="since", date="01 Jan 2026"),
                         "AP assignment for the whole mission since 01 Jan 2026")
        later = leader("ZL", start=TODAY + timedelta(days=1))
        self.assertEqual(account_roles.leader_name(later, TODAY), "the ZL assignment for Rhine zone (starts 30 Sep 2026)")

    def test_additional_roles(self):
        self.assertEqual(account_roles.clean_additional(["office", " DATA_ADMIN "], "DATA_ADMIN"), ["OFFICE"])
        with self.assertRaisesRegex(ValueError, "Data Analyst or Office"):
            account_roles.clean_additional(["PRESIDENT"], "MISSIONARY")
        self.assertEqual(account_roles.main_role_choices({"app_role": "OFFICE"})[-1], "OFFICE")  # an older main role stays

    def test_roles_label_of_import_history(self):
        self.assertEqual(account_changes.roles_label({"app_role": "DL", "additional_roles": ["data_admin"]}), "DL + Data Analyst")
        self.assertEqual(account_changes.roles_label(None), "No linked account")

    def test_leads_the_same(self):
        self.assertTrue(roles.leads_the_same(leader("ZL", zone_id=5), "ZL", (1, 5, 2)))
        self.assertFalse(roles.leads_the_same(leader("DL", district_id=3), "DL", (1, 5, 2)))


class PageRulesTests(unittest.TestCase):
    def test_page_language(self):
        for address, language in (("/?lang=pes", "fa"), ("/?lang=de-AT", "de"), ("/?lang=xx", "en"), ("/", "en")):
            with app.app.test_request_context(address):
                self.assertEqual(page.page_language(), language, address)

    def test_text_and_dates(self):
        self.assertEqual(page.h("<b>Tom</b>"), "&lt;b&gt;Tom&lt;/b&gt;")
        self.assertEqual(page.h(None), "")
        self.assertEqual(page.day(date(2026, 10, 4)), "04 Oct 2026")

    def test_every_sent_form_gets_the_token(self):
        with app.app.test_request_context("/"):
            html, status = page.render("<form method='post'></form><form METHOD=\"POST\"></form><form method=get></form>")
        self.assertEqual((status, html.count('name="csrf_token"')), (200, 2))

    def test_language_codes(self):
        self.assertEqual(account_page.parse_languages(" DE ", "es; fr, es zh-Hant"), ("de", ["es", "fr", "zh-hant"]))
        with self.assertRaisesRegex(ValueError, "language codes"):
            account_page.parse_languages("german", "")
        with self.assertRaisesRegex(ValueError, "must not also appear"):
            account_page.parse_languages("de", "de")


class HistoricalFormTests(unittest.TestCase):
    def test_choices_from_the_check_page(self):
        form = MultiDict([("collision::k1", "combine"), ("target::5|2026-08-09", "12"),
                          ("unit::Mitte|5", "7"), ("unitauto::Mitte|5", "3"),
                          ("unit::Nord|5", "4"), ("unitauto::Nord|5", "4"), ("unitguess::Nord|5", "1"),
                          ("merge::5|7", "keep:Old A"), ("merge::5|7|2026-08-09", "")])
        self.assertEqual(historical_pages.choices_from_form(form),
                         {"collisions": {"k1": "combine"}, "targets": {"5|2026-08-09": "12"}, "units": {"Mitte|5": "7"},
                          "units_seen": ["Nord|5"], "merges": {"5|7": "keep:Old A"}})


class BatchAndUndoTests(unittest.TestCase):
    def test_row_keys(self):
        self.assertEqual(batches.row_key("areas", {"id": 4, "name": "x"}), {"id": 4})
        self.assertEqual(batches.key_string(batches.row_key("area_profiles", {"area_id": 9})), '{"area_id":9}')
        before = {"areas": {"a": 1, "b": 2}}
        self.assertEqual(batches.count_changes(["areas"], before, {"areas": {"a": 1, "b": 3, "c": 4}}), 2)

    def test_a_row_is_the_same_when_its_recorded_columns_are(self):
        self.assertTrue(undo.same_as_recorded({"id": 1, "app_role": "DL", "added_later": []}, {"id": 1, "app_role": "DL"}))
        self.assertFalse(undo.same_as_recorded({"id": 1, "app_role": "ZL"}, {"id": 1, "app_role": "DL"}))
        self.assertTrue(undo.same_as_recorded(None, None))
        self.assertFalse(undo.same_as_recorded(None, {"id": 1}))


class SmallValueTests(unittest.TestCase):
    def test_area_table_extra_attributes(self):
        self.assertEqual(data_upload_pages.extra_attributes("Chapel: yes; Languages: German, Arabic;"),
                         {"Chapel": "yes", "Languages": "German, Arabic"})
        with self.assertRaises(ValueError):
            data_upload_pages.extra_attributes("Chapel yes")

    def test_planning_question_values(self):
        self.assertEqual((pq.plain(3), pq.plain("0.50"), pq.plain(None)), ("3", "0.5", ""))
        self.assertEqual((pq.yes_no("YES"), pq.yes_no("false"), pq.yes_no("maybe")), ("true", "false", None))
        self.assertEqual(pq.choice_code("Very often", [("often", "Very often")]), "often")
        self.assertEqual(pq.hidden_value("NUMBER", "2", 0, 5), "2")
        with self.assertRaisesRegex(ValueError, "whole number"):
            pq.hidden_value("NUMBER", "2.5", 0, 5, integer_only=True)
        with self.assertRaisesRegex(ValueError, "from 0 to 5"):
            pq.hidden_value("NUMBER", "9", 0, 5)
        self.assertEqual(pq.hidden_value("DATE", "2026-10-04"), "2026-10-04")


class StandInConnection:
    """Behaves like the parts of a psycopg2 connection that database.py uses."""
    made = 0

    def __init__(self):
        StandInConnection.made += 1
        self.closed, self.autocommit, self.broken = 0, False, False
        self.status = database.psycopg2.extensions.STATUS_READY
        self.statements, self.rollbacks = [], 0

    def cursor(self, cursor_factory=None):
        return StandInCursor(self)

    def rollback(self):
        self.rollbacks += 1
        self.status = database.psycopg2.extensions.STATUS_READY

    def close(self):
        self.closed = 1

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.status = database.psycopg2.extensions.STATUS_READY  # committed (or rolled back)


class StandInCursor:
    def __init__(self, connection):
        self.connection = connection

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, statement, params=None):
        if self.connection.broken:
            raise database.psycopg2.OperationalError("server closed the connection")
        self.connection.statements.append(statement)
        if not self.connection.autocommit:
            self.connection.status = database.psycopg2.extensions.STATUS_BEGIN


class KeptConnectionTests(unittest.TestCase):
    def setUp(self):
        database._kept.clear()
        self.addCleanup(database._kept.clear)
        opener = patch.object(database.psycopg2, "connect", side_effect=lambda address: StandInConnection())
        opener.start()
        self.addCleanup(opener.stop)
        StandInConnection.made = 0

    def test_a_given_back_connection_is_reset_and_lent_again(self):
        with database.connect() as conn:
            first = conn._raw
            with database.cursor(conn) as cur:
                cur.execute("select 1")
        self.assertEqual(conn.closed, 1)  # given back ...
        self.assertEqual(first.closed, 0)  # ... but kept open
        with database.connect() as again:
            self.assertIs(again._raw, first)
        self.assertEqual(first.statements[-1], "discard all")
        self.assertEqual(StandInConnection.made, 1)

    def test_two_at_once_get_two_connections_and_a_second_close_does_nothing(self):
        one, two = database.connect(), database.connect()
        self.assertIsNot(one._raw, two._raw)
        one.close()
        one.close()
        self.assertEqual(len(database._kept), 1)
        with self.assertRaises(database.psycopg2.InterfaceError):
            one.cursor()
        two.close()

    def test_an_open_transaction_is_rolled_back_and_a_broken_connection_is_replaced(self):
        conn = database.connect()
        raw = conn._raw
        with database.cursor(conn) as cur:
            cur.execute("update something")
        conn.close()  # never committed: nothing of it is saved
        self.assertEqual(raw.rollbacks, 1)
        raw.broken = True
        with database.connect() as fresh:
            self.assertIsNot(fresh._raw, raw)
        self.assertEqual((raw.closed, StandInConnection.made), (1, 2))

    def test_at_most_keep_connections_and_only_for_the_same_database(self):
        many = [database.connect() for _ in range(database.KEEP + 2)]
        for conn in many:
            conn.close()
        self.assertEqual(len(database._kept), database.KEEP)
        with patch.object(settings, "DATABASE_URL", "postgresql://another/place"):
            with database.connect():
                pass
        self.assertEqual(StandInConnection.made, database.KEEP + 3)


class PackedPageTests(unittest.TestCase):
    def test_pages_are_packed_when_the_browser_accepts_it(self):
        client = app.app.test_client()
        packed = client.get("/login", headers={"Accept-Encoding": "gzip, deflate, br"})
        plain_page = client.get("/login")
        self.assertEqual(packed.headers.get("Content-Encoding"), "gzip")
        self.assertIn("accept-encoding", packed.headers.get("Vary", "").lower())
        self.assertEqual(gzip.decompress(packed.get_data()).decode("utf-8").split("csrf")[0],
                         plain_page.get_data(as_text=True).split("csrf")[0])
        self.assertIsNone(plain_page.headers.get("Content-Encoding"))
        small = client.get("/health", headers={"Accept-Encoding": "gzip"})
        self.assertIsNone(small.headers.get("Content-Encoding"))  # under 1 KB: sent as it is


class LeanerPagesTests(unittest.TestCase):
    def test_question_lines_have_no_edit_button_and_no_arrow_that_does_nothing(self):
        question = {"id": 7, "question_label": "Baptisms", "question_key": "baptisms_actual", "question_type": "NUMBER",
                    "required": True, "answered": 0, "protected": False, "active": True}

        def line(**ends):
            return planning_questions_pages.question_item(question, {"section_key": "kic"}, {}, {}, set(), "", **ends)
        self.assertNotIn(">Edit<", line())
        self.assertIn('href="/planning-questions/questions/7"', line())  # the question's label opens it
        first, last = line(first=True), line(last=True)
        self.assertIn('aria-label="Move up"  hidden>', first)
        self.assertIn('aria-label="Move down"  >', first)
        self.assertIn('aria-label="Move down"  hidden>', last)
        # A locked question is never hidden: no (disabled) box for a value saved while hidden.
        self.assertEqual(planning_questions_pages.hidden_field({**question, "protected": True, "value_when_hidden": None}, ""), "")
        self.assertIn('name="value_when_hidden"', planning_questions_pages.hidden_field({**question, "value_when_hidden": "0"}, ""))

    def test_a_mapping_row_lists_only_its_chosen_area_until_it_is_used(self):
        areas = [{"id": 1, "name": "Mitte", "zone": "Rhine"}, {"id": 2, "name": "Nord", "zone": "Rhine"}]
        row = mappings_page.mapping_row({"source_companionship": "Old Mitte", "target_area_id": 2, "notes": "",
                                         "confirmed_at": None}, areas, {1, 2}, [], [])
        self.assertIn('data-short="1"', row)
        self.assertIn(">Rhine / Nord</option>", row)
        self.assertNotIn("Mitte</option>", row)
        self.assertEqual(mappings_page.area_options(areas, None).count("<option"), 3)

    def test_account_manager_names_each_role_once(self):
        row = {"missionary_id": 5, "display_name": "Elder Test", "missionary_number": "123", "email": "t@example.invalid",
               "area": "Mitte", "district": "North", "zone": "Rhine", "account_status": "Active",
               "roster_position_abbr": "DL", "leadership_roles": "DL, ZL", "account_roles": "Data Analyst"}
        self.assertIn("<td>DL, ZL, Data Analyst</td>", account_manager.table_row(row))

    def test_a_turned_off_staff_account_has_no_empty_card(self):
        account = {"id": "5f4f3146-12bc-4626-8324-03f4d65099cf", "display_name": "Sister Office",
                   "email": "o@example.invalid", "app_role": "OFFICE", "active": True, "additional_roles": [],
                   "last_sign_in_at": None, "home_mission_id": 2, "updated_at": None}
        with app.app.test_request_context("/"):
            on = staff_accounts.account_html(account)[0]
            off = staff_accounts.account_html({**account, "active": False})[0]
        self.assertIn("Send password email", on)
        self.assertNotIn("Send password email", off)
        self.assertNotIn('<div class="card"></div>', off)


if __name__ == "__main__":
    unittest.main()
