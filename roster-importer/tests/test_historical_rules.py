"""Database-free unit tests for historical import rules.

Run in DA Management's image (it has Flask), from roster-importer/:
  docker run --rm --network none -v <repo>:/repo -w /repo/roster-importer
    -e DATABASE_URL=postgresql://nobody@127.0.0.1:1/none roster-importer-roster-importer
    python -m unittest tests.test_historical_rules
"""
import os
import unittest
from datetime import date

os.environ.setdefault("DATABASE_URL", "postgresql://nobody@127.0.0.1:1/none")  # never opened by these tests
import historical_import as historical  # noqa: E402
import historical_preview  # noqa: E402
import historical_units  # noqa: E402
import mappings_page  # noqa: E402


def row(label, sunday=date(2026, 8, 9), unit_id=None):
    return {historical.COMPANIONSHIP_COLUMN: label, "_sunday": sunday, "_unit_id": unit_id}


def collisions(rows):
    """{report key: labels} of the labels the check asks about (they would share one report key)."""
    buckets = historical_preview.look_alike_buckets(rows, historical_preview.units_per_report_key(rows))
    return {key: sorted(label for label, _ in bucket) for key, bucket in buckets.items() if len(bucket) > 1}


class ReportKeyCollisionTests(unittest.TestCase):
    def test_punctuation_only_labels_collide(self):
        found = collisions([row("Frankfurt-Darmstadt S"), row("Frankfurt Darmstadt S")])
        self.assertEqual(found, {"frankfurt-darmstadt-s:2026-08-09": ["Frankfurt Darmstadt S", "Frankfurt-Darmstadt S"]})

    def test_same_label_other_week_or_case_does_not_collide(self):
        self.assertEqual(collisions([
            row("Frankfurt-Darmstadt S"), row("frankfurt-darmstadt s", date(2026, 8, 9)),
            row("Frankfurt Darmstadt S", date(2026, 8, 16))]), {})

    def test_a_label_in_two_units_gets_one_key_per_unit(self):
        rows = [row("Frankfurt-Darmstadt S", unit_id=1), row("Frankfurt Darmstadt S", unit_id=2)]
        self.assertEqual(collisions(rows), {})  # different units: two reports, nothing to choose
        self.assertEqual(historical_preview.report_key("Frankfurt-Darmstadt S", date(2026, 8, 9), 1,
                                                       historical_preview.units_per_report_key(rows)),
                         "frankfurt-darmstadt-s:2026-08-09@u1")

    def test_existing_key_format_unchanged(self):
        self.assertEqual(historical.make_report_key("Frankfurt-Langen", date(2026, 8, 23)), "frankfurt-langen:2026-08-23")


class SameReportKeyTests(unittest.TestCase):
    """v1.0.21: 'duplicate key value violates unique constraint "import_weekly_planning_reports_pkey" ... Key
    (source_report_key)=(heidelberg-media-ramstein:2026-06-07)'. A companionship that sent one form per unit, where the
    Ward/Branch answers matched no unit, kept both rows (told apart by the answer) but got one report key."""

    def two_forms(self):
        sunday = date(2026, 6, 7)
        rows = [dict(row("Heidelberg-Media Ramstein", sunday), **{historical.UNIT_COLUMN: "Kaiserslautern-Ramstein 1", "_source_row_number": 4}),
                dict(row("Heidelberg-Media Ramstein", sunday), **{historical.UNIT_COLUMN: "Kaiserslautern-Ramstein 2", "_source_row_number": 9})]
        return rows, sunday

    def test_two_units_without_a_found_unit_get_two_keys(self):
        rows, sunday = self.two_forms()
        units = historical_preview.units_per_report_key(rows)
        keys = {historical_preview.report_key("Heidelberg-Media Ramstein", sunday, historical_preview.unit_identity(r), units) for r in rows}
        self.assertEqual(keys, {"heidelberg-media-ramstein:2026-06-07@tkaiserslautern-ramstein-1",
                                "heidelberg-media-ramstein:2026-06-07@tkaiserslautern-ramstein-2"})
        self.assertEqual(collisions(rows), {})

    def test_found_units_keep_their_old_keys(self):
        rows = [row("Frankfurt-Darmstadt S", unit_id=1), row("Frankfurt-Darmstadt S", unit_id=2)]
        units = historical_preview.units_per_report_key(rows)
        self.assertEqual(historical_preview.report_key("Frankfurt-Darmstadt S", date(2026, 8, 9), 2, units), "frankfurt-darmstadt-s:2026-08-09@u2")
        self.assertEqual(historical_preview.report_key("Frankfurt-Langen", date(2026, 8, 9), None, {}), "frankfurt-langen:2026-08-09")

    def test_two_rows_with_one_key_are_an_error_on_the_check_page(self):
        rows, sunday = self.two_forms()

        class Check:
            errors, closed_only = [], []
        items = [{"key": "heidelberg-media-ramstein:2026-06-07", "source": "Heidelberg-Media Ramstein", "sunday": sunday, "row": r} for r in rows]
        historical_preview.check_same_report_key(Check, items)
        self.assertEqual(Check.errors, ["Rows 4, 9 of the file are both the report of 'Heidelberg-Media Ramstein' for the week of 2026-06-07. "
                                        "Keep only one of them in the file, or give each row its own Ward/Branch."])

    def test_staging_refuses_two_rows_with_one_key_before_writing(self):
        rows, _ = self.two_forms()
        for r in rows:
            r["_report_key"] = "heidelberg-media-ramstein:2026-06-07"

        class Cursor:
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def execute(self, *a): self.ran = True
            def fetchall(self): return [{"source_companionship": "Heidelberg-Media Ramstein", "target_area_name": "Ramstein", "match_status": "MATCHED"}]
        original = historical.database.cursor
        historical.database.cursor = lambda conn: Cursor()
        try:
            with self.assertRaisesRegex(ValueError, "Rows 4, 9 of the file are both the report of 'Heidelberg-Media Ramstein'"):
                historical.stage_rows(None, rows)
        finally:
            historical.database.cursor = original


class OldAreaMatchTests(unittest.TestCase):
    areas = [{"id": 158, "name": "Darmstadt S", "zone": "Frankfurt"},
             {"id": 185, "name": "Wetterau 2", "zone": "Friedrichsdorf"},
             {"id": 204, "name": "Wetterau 1", "zone": "Friedrichsdorf"},
             {"id": 300, "name": "Mitte", "zone": "Frankfurt"},
             {"id": 301, "name": "Mitte", "zone": "Stuttgart"}]
    zones = ["Frankfurt", "Friedrichsdorf", "Stuttgart", "Nürnberg"]

    def match(self, label):
        area, _ = mappings_page.old_area_match(label, self.areas, self.zones)
        return area and area["id"]

    def test_exact_name(self):
        self.assertEqual(self.match("Wetterau 2"), 185)

    def test_zone_prefixed_labels(self):
        self.assertEqual(self.match("Frankfurt-Darmstadt S"), 158)
        self.assertEqual(self.match("Friedrichsdorf-Wetterau 2"), 185)
        self.assertEqual(self.match("friedrichsdorf wetterau 2"), 185)

    def test_ambiguous_prefers_named_zone_else_nothing(self):
        self.assertEqual(self.match("Stuttgart-Mitte"), 301)
        area, reason = mappings_page.old_area_match("Mitte", self.areas, self.zones)
        self.assertIsNone(area)
        self.assertIn("several", reason)

    def test_no_match(self):
        area, reason = mappings_page.old_area_match("Test Old Area Gamma", self.areas, self.zones)
        self.assertIsNone(area)
        self.assertIn("no active area", reason)

    def test_report_labels(self):
        self.assertEqual(historical_preview.report_labels("Frankfurt-Darmstadt Mitte + Frankfurt-Darmstadt S"),
                         ["Frankfurt-Darmstadt Mitte", "Frankfurt-Darmstadt S"])
        self.assertEqual(historical_preview.report_labels(None), [])


class ActionPlanNotesTests(unittest.TestCase):
    def test_notes_come_in_the_same_order_every_time(self):
        written = []

        class Cursor:
            def execute(self, sql, params):
                written.append(params)
        row = {historical.COMPANIONSHIP_COLUMN: "Old Mitte", "_sunday": date(2020, 1, 5), "_source_row_number": 2,
               "_timestamp": None, "Weekly Action Plan": "Visit members",
               "Optional: Baptisms and Confirmations Action Plan": "Teach the Smiths"}
        historical.stage_report(Cursor(), row, {"old mitte": {"target_area_name": "Mitte"}})
        notes = [value for value in written[0] if isinstance(value, str) and "Action Plan" in value]
        self.assertEqual(notes, ["Optional: Baptisms and Confirmations Action Plan: Teach the Smiths\n\n"
                                 "Weekly Action Plan: Visit members"])


def unit(uid, name, number, areas=(), primary=()):
    u = {"id": uid, "name": name, "unit_number": number, "active": True, "area_ids": list(areas), "primary_area_ids": list(primary)}
    u["norm"], u["base"] = historical_units.unit_norm(name), historical_units.unit_norm(name, True)
    return u


class UnitResolutionTests(unittest.TestCase):
    """Real unit names and form answers from the Frankfurt mission (two-unit companionships)."""
    units = [unit(87, "Kaiserslautern", "62537", [195, 176], [195, 176]), unit(122, "Kaiserslautern (English)", "80152", [195]),
             unit(130, "Ramstein 1st (English)", "104337", [165], [165]), unit(131, "Ramstein 2nd (English)", "1992813", [165]),
             unit(91, "Frankfurt 1st", "66230", [198, 180], [198, 180]), unit(92, "Frankfurt 2nd (English)", "80144", [198, 180]),
             unit(111, "Idar-Oberstein", "92177", [212], [212]), unit(114, "Baumholder (English)", "80047", [131], [131]),
             unit(84, "Koblenz", "65315", [173], [173]), unit(81, "Usingen", "442232", [86], [86]),
             unit(97, "Stuttgart 1st", "64106", [190], [190]), unit(126, "Stuttgart 2nd (English)", "65641", [190])]
    zones = {"frankfurt", "friedrichsdorf", "heidelberg", "kaiserslautern", "nürnberg", "stuttgart"}

    def resolve(self, text, label, area):
        found, how, confident = historical_units.resolve_unit(text, label, area, self.units, self.zones)
        return (found and found["id"]), confident

    def test_ward_branch_answers_name_the_unit(self):
        self.assertEqual(self.resolve("Kaiserslautern-Kaiserslautern English", "Heidelberg-Kaiserslautern Military", 195), (122, True))
        self.assertEqual(self.resolve("Kaiserslautern-Ramstein 1", "Heidelberg-Media Ramstein", 195), (130, True))
        self.assertEqual(self.resolve("Kaiserslautern-Ramstein 2", "Heidelberg-Media Ramstein", 195), (131, True))
        self.assertEqual(self.resolve("Frankfurt-Frankfurt 2", "Frankfurt-Office E", 180), (92, True))
        self.assertEqual(self.resolve("Frankfurt-Frankfurt 1", "Frankfurt-Office E", 180), (91, True))
        self.assertEqual(self.resolve("Heidelberg-Idar-Oberstein", "Heidelberg-Idar -Ober - E2", 212), (111, True))
        self.assertEqual(self.resolve("Kaiserslautern-Baumholder", "Heidelberg-Idar/Baumholder", 212), (114, True))
        self.assertEqual(self.resolve("Friedrichsdorf-Usingen", "Friedrichsdorf-Usingen S", 173), (81, True))
        self.assertEqual(self.resolve("Kaiserslautern", "x", 195), (87, True))

    def test_blank_or_unknown_answer_uses_old_area_name_then_area_unit(self):
        self.assertEqual(self.resolve("", "Friedrichsdorf-Koblenz Spanish", 173), (84, False))
        self.assertEqual(self.resolve("Test Ward B1", "Frankfurt-Darmstadt S", 173), (84, False))
        self.assertEqual(self.resolve("Stuttgart-Stuttgart military", "Stuttgart-Stuttgart Military", 190), (97, False))
        found, how, confident = historical_units.resolve_unit("", "Nowhere", 999, self.units, self.zones)
        self.assertIsNone(found)
        self.assertIn("no unit", how)

    def test_dedup_keeps_one_report_per_unit(self):
        rows = [{historical.COMPANIONSHIP_COLUMN: "Heidelberg-Media Ramstein", "_sunday": date(2026, 6, 7), "_timestamp": None, "u": u}
                for u in (130, 131, 131)]
        selected, dups = historical.deduplicate_rows(rows, unit_of=lambda r: r["u"])
        self.assertEqual(([r["u"] for r in selected], len(dups)), ([130, 131], 1))
        selected, dups = historical.deduplicate_rows(rows)
        self.assertEqual((len(selected), len(dups)), (1, 2))


if __name__ == "__main__":
    unittest.main(verbosity=2)


class UnknownUnitsStayApartTests(unittest.TestCase):
    """Real-file test of PR #34: one label sent one form per unit, and neither Ward/Branch answer matched a unit. The
    rows got two report keys (v1.0.22) but still one report group (area, week, no unit), so the check asked to "keep
    only" a label against itself and Apply added the two units' numbers into one report."""

    SUNDAY = date(2026, 6, 7)
    AREA = {"id": 7, "name": "Beta Base"}

    def item(self, answer, number):
        r = dict(row("Zone-Beta Base", self.SUNDAY), **{historical.UNIT_COLUMN: answer, "_source_row_number": number})
        return {"source": "Zone-Beta Base", "area": self.AREA, "sunday": self.SUNDAY, "row": r, "unit_id": None,
                "unit_name": None, "key": f"zone-beta-base:2026-06-07@t{number}", "collision_extra": False, "combined": False,
                "group": historical_preview.report_group(7, self.SUNDAY, r)}

    def test_two_unknown_answers_are_two_report_groups(self):
        a, b, again = self.item("Zone-Beta 1", 4), self.item("Zone-Beta 2", 9), self.item("zone-beta 1", 12)
        self.assertNotEqual(a["group"], b["group"])
        self.assertEqual(a["group"], again["group"])  # the same answer (any case) is the same unit
        found = dict(row("Zone-Beta Base", self.SUNDAY, unit_id=31), **{historical.UNIT_COLUMN: "Zone-Beta 1"})
        self.assertEqual(historical_preview.report_group(7, self.SUNDAY, found), (7, self.SUNDAY, 31))
        self.assertIsNone(historical_preview.group_unit_id(a["group"]))
        self.assertEqual(historical_preview.group_unit_id((7, self.SUNDAY, 31)), 31)

    def test_no_keep_only_question_for_one_label_in_two_unknown_units(self):
        check = historical_preview.Check.__new__(historical_preview.Check)
        check.choices, check.errors, check.pending = {}, [], []
        check.ui, check.effective, check.state = ({"merges": []}, {"merges": {}}, {"merges": {}})
        check.areas, check.units_by_id = {7: self.AREA}, {}
        items, skipped = historical_preview.choose_same_unit_rows(check, [self.item("Zone-Beta 1", 4), self.item("Zone-Beta 2", 9)])
        self.assertEqual((len(items), skipped, check.ui["merges"], check.pending), (2, [], [], []))

    def test_two_labels_in_one_unknown_unit_are_still_asked_about(self):
        check = historical_preview.Check.__new__(historical_preview.Check)
        check.choices, check.errors, check.pending = {}, [], []
        check.ui, check.effective, check.state = ({"merges": []}, {"merges": {}}, {"merges": {}})
        check.areas, check.units_by_id = {7: self.AREA}, {}
        other = self.item("Zone-Beta 1", 5)
        other["source"] = "Zone-Beta Old"
        items, skipped = historical_preview.choose_same_unit_rows(check, [self.item("Zone-Beta 1", 4), other])
        self.assertEqual(len(skipped), 2)
        self.assertEqual(len(check.ui["merges"]), 1)
        self.assertTrue(check.ui["merges"][0]["key"].startswith("7|t"))  # short key: the form keeps 100 characters
        self.assertLessEqual(len(check.ui["merges"][0]["key"]), 12)
        self.assertIn("zone-beta 1", check.ui["merges"][0]["unit"])

    def test_one_earlier_report_is_taken_over_by_one_unit_only(self):
        a, b = self.item("Zone-Beta 1", 4), self.item("Zone-Beta 2", 9)
        check = historical_preview.Check.__new__(historical_preview.Check)
        check.choices, check.errors, check.pending, check.replace_existing = {}, [], [], True
        check.ui, check.effective, check.state = ({"targets": []}, {"targets": {}}, {"targets": {}})
        earlier = {"id": 50, "unit_id": None, "unit_name": None, "status": "SUBMITTED", "historical_source_key": "zone-beta-base:2026-06-07",
                   "friends_found_actual": 1, "lessons_with_friends_actual": 1, "sacrament_attendance_actual": 1, "baptismal_dates_actual": 0}

        class Cursor:
            def execute(self, query, args): self.args = args
            def fetchall(self): return [earlier]
        groups = {a["group"]: [a], b["group"]: [b]}
        targets, taken, _ = historical_preview.choose_target_reports(check, Cursor(), groups)
        self.assertEqual(list(targets.values()), [50])  # never both written into report #50
        self.assertEqual(taken, {50})
        self.assertEqual([a.get("existing_id"), b.get("existing_id")], [50, None])

    def test_apply_writes_one_report_per_group(self):
        import historical_apply
        a, b = self.item("Zone-Beta 1", 4), self.item("Zone-Beta 2", 9)
        made, added = [], []
        originals = (historical_apply.staged_report, historical_apply.write_report, historical_apply.add_to_report, historical_apply.write_details)
        historical_apply.staged_report = lambda cur, key: {"key": key}
        historical_apply.write_report = lambda cur, item, staged, batch, report_id, moved: made.append(item["key"]) or len(made)
        historical_apply.add_to_report = lambda cur, report_id, staged: added.append(report_id)
        historical_apply.write_details = lambda *args: None
        try:
            historical_apply.write_reports(None, {"rows": [a, b], "target_reports": {}, "stale_reports": {}}, "batch")
        finally:
            (historical_apply.staged_report, historical_apply.write_report, historical_apply.add_to_report, historical_apply.write_details) = originals
        self.assertEqual((made, added), ([a["key"], b["key"]], []))
