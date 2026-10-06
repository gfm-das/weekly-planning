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
