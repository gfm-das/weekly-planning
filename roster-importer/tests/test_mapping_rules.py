"""Round 19, without a database: what an Area mapping means (one to one, Closed, Combined companionship), why an
area that is already closed can be mapped as Closed, and that two old areas are never added up unless asked.

Run in DA Management's image, from roster-importer/:
  docker run --rm --network none -v <repo>:/repo -w /repo/roster-importer
    -e DATABASE_URL=postgresql://nobody@127.0.0.1:1/none roster-importer-roster-importer
    python -m unittest tests.test_mapping_rules
"""
import os
import unittest
from datetime import date
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "postgresql://nobody@127.0.0.1:1/none")  # never opened by these tests
import historical_import as historical  # noqa: E402
import historical_pages  # noqa: E402
import historical_preview  # noqa: E402
import historical_separate  # noqa: E402
import mappings_page  # noqa: E402

ZONES = ["Heidelberg", "Frankfurt"]
AREAS = [{"id": 1, "name": "Idar/Baumholder", "zone": "Heidelberg", "active": False},
         {"id": 2, "name": "Mitte", "zone": "Frankfurt", "active": True},
         {"id": 3, "name": "Mitte", "zone": "Frankfurt", "active": False},
         {"id": 4, "name": "Darmstadt S", "zone": "Frankfurt", "active": True}]


class Cursor:
    """Records what is written; answers 'select' with the given rows."""
    def __init__(self, rows=()):
        self.rows, self.done, self.rowcount = list(rows), [], 1

    def execute(self, query, params=()):
        self.done.append((" ".join(query.split()), params))

    def fetchone(self):
        return self.rows.pop(0) if self.rows else None

    def fetchall(self):
        return self.rows


class ClosedAreaTests(unittest.TestCase):
    def test_an_area_that_is_already_closed_is_found_and_offered_as_closed(self):
        area, reason = mappings_page.old_area_match("Heidelberg-Idar/Baumholder", AREAS, ZONES)
        self.assertEqual((area["id"], reason), (1, None))  # the old rule looked at active areas only: "Nothing to close"
        cell = mappings_page.close_cell({"source_companionship": "Heidelberg-Idar/Baumholder"}, AREAS, ZONES)
        self.assertIn("Already closed:", cell)
        self.assertNotIn("Nothing to close", cell)

    def test_an_active_area_comes_before_a_closed_one_of_the_same_name(self):
        self.assertEqual(mappings_page.old_area_match("Mitte", AREAS, ZONES)[0]["id"], 2)
        self.assertIn('name="deactivate"', mappings_page.close_cell({"source_companionship": "Frankfurt-Darmstadt S"}, AREAS, ZONES))

    def test_no_area_at_all_points_to_the_closed_choice(self):
        cell = mappings_page.close_cell({"source_companionship": "Nowhere"}, AREAS, ZONES)
        self.assertIn("choose Closed area in the list", cell)

    def test_every_row_offers_closed_area_and_combined_companionship(self):
        current = [{"id": 2, "name": "Mitte", "zone": "Frankfurt"}]
        closed = mappings_page.mapping_row({"source_companionship": "Idar/Baumholder", "match_status": "CLOSED", "target_area_id": 1,
                                            "confirmed_at": 1}, current, {2}, AREAS, ZONES)
        self.assertIn('<option value="closed" selected>Closed area', closed)
        self.assertIn(">Closed<", closed)
        combined = mappings_page.mapping_row({"source_companionship": "Baumholder", "match_status": "COMBINED", "target_area_id": 2,
                                              "confirmed_at": 1}, current, {2}, AREAS, ZONES, {"baumholder": 3})
        self.assertIn('name="combined" value="Baumholder" checked', combined)
        self.assertIn('<option value="closed">Closed area', combined)
        self.assertIn("Added together with another area in 3 report(s)", combined)
        self.assertIn('formaction="/mappings/separate"', combined)
        self.assertIn('value="closed"', mappings_page.closed_option(False))
        plain = mappings_page.mapping_row({"source_companionship": "Mitte", "target_area_id": 2, "confirmed_at": 1}, current, {2}, AREAS, ZONES)
        self.assertNotIn("Separate", plain)
        self.assertNotIn(" checked", plain)

    @patch("sign_in.current_mission_id", return_value=2)
    @patch("sign_in.actor_name", return_value="Test")
    def test_saving_closed_keeps_the_closed_area_and_closes_an_open_one(self, *_):
        cur = Cursor()
        self.assertEqual(mappings_page.save_mapping(cur, "Heidelberg-Idar/Baumholder", None, "", set(), AREAS, ZONES, "CLOSED"), (1, 0))
        insert = cur.done[-1][1]
        self.assertEqual((insert[1], insert[2], insert[4]), ("Idar/Baumholder", 1, "CLOSED"))
        self.assertFalse(any("update public.areas" in q for q, _ in cur.done))  # already closed: nothing to turn off
        cur = Cursor()
        self.assertEqual(mappings_page.save_mapping(cur, "Frankfurt-Darmstadt S", None, "", set(), AREAS, ZONES, "CLOSED"), (1, 1))
        self.assertTrue(any("update public.areas set active=false" in q and p == (4,) for q, p in cur.done))
        cur = Cursor()  # a Closed label without any area is still saved (its rows stay in the import tables)
        self.assertEqual(mappings_page.save_mapping(cur, "Nowhere", None, "", set(), AREAS, ZONES, "CLOSED"), (1, 0))
        self.assertEqual(cur.done[-1][1][1:5], (None, None, 2, "CLOSED"))
        with self.assertRaises(ValueError):  # one to one and combined still need a current area
            mappings_page.save_mapping(Cursor(), "Nowhere", None, "", set(), AREAS, ZONES, "COMBINED")

    def test_a_closed_label_without_an_area_is_staged_without_one(self):
        cur = Cursor()
        row = {historical.COMPANIONSHIP_COLUMN: "Nowhere", "_sunday": date(2020, 1, 5), "_source_row_number": 2, "_timestamp": None}
        historical.stage_report(cur, row, {"nowhere": {"target_area_name": None, "match_status": "CLOSED"}})
        self.assertIn(None, cur.done[0][1])
        historical.check_mappings([row], {"nowhere": {"target_area_name": None, "match_status": "CLOSED"}})
        with self.assertRaisesRegex(ValueError, "Unresolved"):
            historical.check_mappings([row], {"nowhere": {"target_area_name": None, "match_status": "CONFIRMED"}})


class NoSummingTests(unittest.TestCase):
    def check(self):
        check = historical_preview.Check.__new__(historical_preview.Check)
        check.areas = {2: {"id": 2, "name": "Mitte"}}
        check.all_areas = {**check.areas, 1: {"id": 1, "name": "Idar/Baumholder"}}
        check.mappings = {"old idar": {"match_status": "CLOSED", "target_area_id": 1}, "mitte": {"target_area_id": 2}}
        check.units_by_id, check.choices = {}, {}
        check.errors, check.pending, check.notices = [], [], []
        check.ui = {"merges": []}
        check.effective = {"merges": {}}
        check.state = {"merges": {}}
        return check

    def item(self, label, combined=False):
        return {"source": label, "area": {"id": 2, "name": "Mitte"}, "unit_id": None, "sunday": date(2020, 1, 5),
                "collision_extra": False, "combined": combined, "key": label}

    def test_two_old_areas_of_one_area_and_week_need_a_choice_and_cannot_be_added_up(self):
        check = self.check()
        rows, skipped = historical_preview.choose_same_unit_rows(check, [self.item("A"), self.item("B")])
        self.assertEqual((rows, len(skipped), len(check.pending)), ([], 2, 1))
        self.assertNotIn("combine", check.pending[0])
        check = self.check()
        check.choices = {"merges": {"2|none": "combine"}}
        historical_preview.choose_same_unit_rows(check, [self.item("A"), self.item("B")])
        self.assertTrue(any("not valid" in e for e in check.errors))
        check = self.check()
        check.choices = {"merges": {"2|none": "keep:B"}}
        rows, skipped = historical_preview.choose_same_unit_rows(check, [self.item("A"), self.item("B")])
        self.assertEqual(([r["source"] for r in rows], [s["source"] for s in skipped]), (["B"], ["A"]))

    def test_only_a_combined_companionship_is_added_without_asking(self):
        check = self.check()
        rows, skipped = historical_preview.choose_same_unit_rows(check, [self.item("A"), self.item("B", combined=True)])
        self.assertEqual((len(rows), skipped, check.pending), (2, [], []))

    def test_a_closed_label_finds_its_closed_area(self):
        check = self.check()
        self.assertEqual(check.area_of_label("Old Idar")["id"], 1)
        self.assertEqual(check.area_of_label("Mitte")["id"], 2)

    def test_the_choice_page_offers_no_adding_up(self):
        html = historical_pages.merges_part({"merges": [{"key": "2|none", "area": "Mitte", "unit": "no unit", "labels": ["A", "B"],
                                                         "selected": None, "weeks": [{"key": "2|none|2020-01-05", "sunday": "2020-01-05",
                                                                                      "labels": ["A", "B"], "override": None, "missing": False}]}]})
        self.assertNotIn('value="combine"', html)
        self.assertIn("never added together", html)
        self.assertIn("Keep only <b>A</b>", html)


class SeparateTests(unittest.TestCase):
    def test_the_label_s_own_staged_report_is_found_by_key_then_unit(self):
        report = {"sunday": date(2020, 1, 5), "historical_source_key": "a:2020-01-05", "unit_id": 7}
        rows = [{"source_report_key": "b:2020-01-05@u6"}, {"source_report_key": "b:2020-01-05@u7"}]
        self.assertEqual(historical_separate.staged(Cursor(rows), "B", report)["source_report_key"], "b:2020-01-05@u7")
        self.assertIsNone(historical_separate.staged(Cursor([{"source_report_key": "b:x@u1"}, {"source_report_key": "b:x@u2"}]), "B", report))
        self.assertEqual(historical_separate.staged(Cursor([{"source_report_key": "b:2020-01-05"}]), "B", report)["source_report_key"], "b:2020-01-05")

    def test_nothing_to_separate_changes_nothing(self):
        cur = Cursor([])
        with self.assertRaisesRegex(ValueError, "not added together"):
            historical_separate.separate(cur, "B", {"id": 4, "name": "Darmstadt S"})
        self.assertEqual(len(cur.done), 1)  # only the look-up, no write



class SuggestionTests(unittest.TestCase):
    """Round 21: a new label gets the best guess preselected (never saved by itself)."""
    CURRENT = [{"id": 2, "name": "Mitte", "zone": "Frankfurt"}, {"id": 4, "name": "Darmstadt S", "zone": "Frankfurt"},
               {"id": 5, "name": "Bad Kreuznach", "zone": "Heidelberg"}]
    ALL = AREAS + [{"id": 5, "name": "Bad Kreuznach", "zone": "Heidelberg", "active": True}]

    def guess(self, label, remembered=None, areas=None):
        return mappings_page.suggestion(label, self.CURRENT, areas or self.ALL, ZONES, remembered)

    def test_the_reasons_in_order(self):
        self.assertEqual(self.guess("Mitte"), (2, "Same name."))
        self.assertEqual(self.guess("Frankfurt-Darmstadt S"), (4, "Same name without the zone prefix."))
        self.assertEqual(self.guess("Heidelberg-Idar/Baumholder"), ("closed", "Matches an area that is already closed."))
        self.assertEqual(self.guess("Bad Kreuznch"), (5, "Similar spelling."))
        self.assertEqual(self.guess("Heidelberg - Bad-Kreuznach"), (5, "Similar spelling."))
        self.assertEqual(self.guess("Nowhere"), (None, None))

    def test_a_remembered_match_wins_and_can_mean_closed(self):
        self.assertEqual(self.guess("Mitte", {"mitte": {"area_id": 4, "historical": False}}), (4, "Remembered from an earlier upload."))
        self.assertEqual(self.guess("Old North", {"old north": {"area_id": None, "historical": True}}), ("closed", "Remembered from an earlier upload."))
        self.assertEqual(self.guess("Mitte", {"mitte": {"area_id": 99, "historical": False}}), (2, "Same name."))  # not a current area

    def test_no_guess_when_two_areas_are_equally_alike_or_the_match_is_not_current(self):
        twins = [{"id": 7, "name": "Alpha 1", "zone": "Frankfurt", "active": True}, {"id": 8, "name": "Alpha 2", "zone": "Frankfurt", "active": True}]
        self.assertEqual(mappings_page.suggestion("Alpha 3", self.CURRENT, twins, ZONES), (None, None))
        numbered = [{"id": 10, "name": "Beta 1", "zone": "Frankfurt", "active": True}]
        self.assertIsNone(mappings_page.look_alike("Beta 12", numbered, ZONES))  # another number is another area
        self.assertEqual(mappings_page.look_alike("Betta 1", numbered, ZONES)["id"], 10)
        # A one-letter mark is another companionship: Elders (E) are never suggested for a Sisters (S) area.
        marked = [{"id": 11, "name": "Gamma S", "zone": "Frankfurt", "active": True}, {"id": 12, "name": "Delta", "zone": "Frankfurt", "active": True}]
        self.assertIsNone(mappings_page.look_alike("Frankfurt-Gamma E", marked, ZONES))
        self.assertIsNone(mappings_page.look_alike("Delta S", marked, ZONES))
        self.assertEqual(mappings_page.look_alike("Gama S", marked, ZONES)["id"], 11)
        idle = [{"id": 9, "name": "Quiet Town", "zone": "Frankfurt", "active": True}]  # active, but nobody serves there
        self.assertEqual(mappings_page.suggestion("Quiet Town", self.CURRENT, idle, ZONES), (None, None))

    def test_the_row_preselects_the_guess_marks_it_and_ticks_nothing(self):
        row = mappings_page.mapping_row({"source_companionship": "Frankfurt-Darmstadt S", "target_area_id": None, "notes": "", "confirmed_at": None},
                                        self.CURRENT, {2, 4, 5}, self.ALL, ZONES)
        self.assertIn('<option value="4" selected>Frankfurt / Darmstadt S</option>', row)
        self.assertIn("<b class='warn'>Suggested</b>", row)
        self.assertIn("Same name without the zone prefix.", row)
        self.assertNotIn(" checked", row)  # neither Combined companionship nor Close old area
        same = mappings_page.mapping_row({"source_companionship": "Mitte", "target_area_id": None}, self.CURRENT, {2, 4, 5}, self.ALL, ZONES)
        self.assertIn("currently the target", same)  # closing the suggested area itself is pointed out, not offered blindly
        closed = mappings_page.mapping_row({"source_companionship": "Idar/Baumholder", "target_area_id": None}, self.CURRENT, {2, 4, 5}, self.ALL, ZONES)
        self.assertIn('<option value="closed" selected>', closed)
        self.assertIn("Suggested", closed)
        none = mappings_page.mapping_row({"source_companionship": "Nowhere", "target_area_id": None}, self.CURRENT, {2, 4, 5}, self.ALL, ZONES)
        self.assertIn('<option value="">Choose current area</option>', none)
        self.assertNotIn(" selected", none)
        self.assertNotIn("Suggested", none)

    def test_a_saved_mapping_is_never_replaced_by_a_guess(self):
        saved = mappings_page.mapping_row({"source_companionship": "Mitte", "target_area_id": 4, "match_status": "CONFIRMED", "confirmed_at": 1},
                                          self.CURRENT, {2, 4, 5}, self.ALL, ZONES)
        self.assertIn('<option value="4" selected>', saved)
        self.assertNotIn("Suggested", saved)
        closed = mappings_page.mapping_row({"source_companionship": "Mitte", "target_area_id": None, "match_status": "CLOSED", "confirmed_at": 1},
                                           self.CURRENT, {2, 4, 5}, self.ALL, ZONES)
        self.assertNotIn("Suggested", closed)
        self.assertNotIn('value="2" selected', closed)

if __name__ == "__main__":
    unittest.main()
