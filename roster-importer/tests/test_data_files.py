"""Reading the upload files, without a database: made-up files with the columns of the owner's real files.

Run: python -m unittest tests.test_data_files (from roster-importer/, with PYTHONPATH=.)"""
import json
import re
import unittest
from datetime import date
from pathlib import Path

import data_files
import data_types
from data_text import TEXT, plain
from tests import data_samples as s

AREAS = [("Frankfurt", "Frankfurt 1", "Bockenheim"), ("Heidelberg", "Mannheim", "Mannheim Innenstadt/Jungbusch")]
ROOT = Path(__file__).resolve().parents[2]


def fake_key(person_id):
    return "k" + person_id  # stands in for data_uploads.person_key (tested in test_data_uploads)


class ReadingTests(unittest.TestCase):
    def test_weeks_run_monday_to_sunday(self):
        self.assertEqual(data_files.week_of(date(2026, 9, 21)), date(2026, 9, 27))  # Monday
        self.assertEqual(data_files.week_of(date(2026, 9, 27)), date(2026, 9, 27))  # Sunday
        self.assertEqual(data_files.week_of(date(2026, 9, 28)), date(2026, 10, 4))
        self.assertEqual(data_files.week_before(date(2026, 9, 28)), date(2026, 9, 27))  # a Monday report
        self.assertEqual(data_files.week_before(date(2026, 9, 27)), date(2026, 9, 27))
        # A FindeChristus report shows the last week that ended at least three days before it (checked on the
        # owner's archives: Monday and Sunday reports are for the Monday meeting, later ones show the week just ended).
        self.assertEqual(data_files.week_reported_on(date(2026, 9, 28)), date(2026, 9, 20))  # Monday
        self.assertEqual(data_files.week_reported_on(date(2026, 9, 27)), date(2026, 9, 20))  # Sunday = next Monday
        self.assertEqual(data_files.week_reported_on(date(2026, 9, 29)), date(2026, 9, 20))  # Tuesday: a day late
        self.assertEqual(data_files.week_reported_on(date(2026, 4, 4)), date(2026, 3, 29))  # Saturday
        self.assertEqual(data_files.week_reported_on(date(2026, 5, 21)), date(2026, 5, 17))  # Thursday
        # Monday 27 Jul and Sunday 2 Aug are two different weeks (they fell into one week before the fix).
        self.assertEqual(data_files.week_reported_on(date(2026, 7, 27)), date(2026, 7, 19))
        self.assertEqual(data_files.week_reported_on(date(2026, 8, 2)), date(2026, 7, 26))

    def test_dates_numbers_rates(self):
        self.assertEqual(data_files.read_date("9/27/2025 10:06:42 AM"), date(2025, 9, 27))
        self.assertEqual(data_files.read_date("27.09.2025"), date(2025, 9, 27))
        self.assertEqual(data_files.read_date("2025-09-27"), date(2025, 9, 27))
        self.assertIsNone(data_files.read_date("  "))
        with self.assertRaises(ValueError):
            data_files.read_date("soon")
        self.assertEqual(data_files.read_count("12"), 12)
        self.assertEqual(data_files.read_big_count("21.000"), 21000)  # German thousands separator
        self.assertEqual(data_files.read_big_count("1,234,567"), 1234567)
        self.assertEqual(data_files.read_big_count("21 000"), 21000)
        self.assertEqual(data_files.read_big_count(21000.0), 21000)
        self.assertEqual(data_files.read_big_count("12"), 12)
        self.assertIsNone(data_files.read_big_count(""))
        with self.assertRaises(ValueError):
            data_files.read_big_count("1,5")
        self.assertEqual(data_files.read_count(3.0), 3)
        self.assertIsNone(data_files.read_count(""))
        with self.assertRaises(ValueError):
            data_files.read_count("-1")
        self.assertEqual(data_files.read_decimal("12,5"), 12.5)
        self.assertEqual(data_files.read_decimal("1.234,5"), 1234.5)
        self.assertEqual(data_files.read_rate("26.00%"), 0.26)
        self.assertEqual(data_files.read_rate("0.135"), 0.135)
        self.assertEqual(data_files.read_rate("41"), 0.41)
        self.assertIsNone(data_files.read_rate("#DIV/0!"))

    def test_wrong_file_type_and_missing_columns(self):
        with self.assertRaises(data_files.FileProblem):
            data_files.read_table("notes.pdf", b"%PDF")
        rows = data_files.read_table("x.csv", b"Zone,Week\nFrankfurt,1\n")
        with self.assertRaises(data_files.FileProblem) as caught:
            data_types.parse_zone_history(rows)
        self.assertIn("Sunday", str(caught.exception))


class FindingTests(unittest.TestCase):
    def parsed(self):
        return data_types.parse_finding(data_files.read_table("MissionFindingDetail.csv", s.finding_file(AREAS)), fake_key)

    def test_real_export_shape(self):
        parsed = self.parsed()
        self.assertEqual(parsed.rows_read, 7)
        self.assertEqual(len(parsed.records), 5)  # person 1 twice (first row used), one row without an id
        self.assertEqual(parsed.problem_count, 2)
        first = parsed.records[0]
        self.assertEqual(first["area"], "Bockenheim")  # the first row of person 1 is kept
        self.assertEqual(first["found_on"], "2026-09-14")
        self.assertEqual(first["referral_on"], "2026-09-14")
        self.assertEqual(first["contacted_on"], "2026-09-15")
        self.assertEqual(first["first_lesson_on"], "2026-09-16")
        self.assertEqual(parsed.records[4]["first_sacrament_on"], "2026-09-27")

    def test_no_names_and_no_ids_in_records(self):
        text = json.dumps(self.parsed().as_dict())
        for secret in s.MADE_UP_NAMES + s.MADE_UP_IDS + ["No Id Person"]:
            self.assertNotIn(secret, text.replace("k" + secret, ""))  # only the stand-in code, never the id itself


class HistoryTests(unittest.TestCase):
    def test_zone_history(self):
        data = s.zone_history_file([("8/4/2024", "Frankfurt", 22, 18), ("8/4/2024", "Mission", 100, 90),
                                    ("8/4/2024", "Frankfurt", 1, 1), ("8/11/2024", "Düsseldorf", 19, "x")])
        parsed = data_types.parse_zone_history(data_files.read_table("history.csv", data))
        self.assertEqual(len(parsed.records), 2)
        self.assertEqual(parsed.left_out, 1)  # the mission row: the mission is added up from the zones
        self.assertEqual(parsed.problem_count, 2)  # Frankfurt twice in a week; 'x' is not a number
        first = parsed.records[0]
        self.assertEqual((first["sunday"], first["zone"], first["friends_found_goal"], first["friends_found_actual"]),
                         ("2024-08-04", "Frankfurt", 22, 18))
        self.assertEqual((first["companionships"], first["first_time_sacrament_actual"]), (12, 2))
        self.assertIsNone(parsed.records[1]["friends_found_actual"])

    def test_archive_adds_up_and_skips_mission_rows(self):
        data = s.archive_file("Düsseldorf", "Wesel", "Bockenheim")
        parsed = data_types.parse_archive(data_files.read_table("archive.csv", data))
        self.assertEqual(parsed.left_out, 1)
        by_source = {(r["area"], r["source"]): r for r in parsed.records}
        lead = by_source[("Wesel", "Lead-Ads")]
        self.assertEqual((lead["referrals_received"], lead["referrals_contacted"], lead["friends_made"]), (2, 1, 1))
        self.assertEqual(lead["sunday"], "2024-02-25")  # a report of Monday 4 Mar 2024 shows 19-25 Feb
        self.assertEqual(by_source[("Bockenheim", "FindeChristus Referrals")]["referrals_received"], 4)
        self.assertNotIn("11033", json.dumps(parsed.as_dict()))  # referral numbers are not read

    def test_rates(self):
        parsed = data_types.parse_rates(data_files.read_table("rates.csv", s.rates_file("Frankfurt")))
        rows = {(r["sunday"], r["zone"]): r for r in parsed.records}
        self.assertEqual(rows[("2026-09-20", "Mission")]["teaching_rate"], 0.26)  # dated Sunday 27 Sep
        self.assertTrue(rows[("2026-09-20", "Mission")]["is_mission"])
        self.assertEqual(rows[("2026-09-20", "Frankfurt")]["teaching_rate"], 0.41)
        self.assertEqual(rows[("2024-06-23", "Mission")]["teaching_rate"], 0.135)
        self.assertEqual(rows[("2026-07-19", "Mission")]["teaching_rate"], 0.27)  # Monday 27 Jul
        self.assertEqual(rows[("2026-07-26", "Mission")]["teaching_rate"], 0.28)  # Sunday 2 Aug: kept, not lost
        self.assertEqual(rows[("2026-03-29", "Mission")]["teaching_rate"], 0.20)  # Saturday 4 Apr
        self.assertEqual(rows[("2026-01-04", "Frankfurt")]["teaching_rate"], 0.22)  # the later of 11 and 12 Jan
        self.assertEqual(len(parsed.records), 7)
        self.assertEqual(parsed.problem_count, 1)  # two dates for one week, said with both dates
        self.assertIn("11 Jan 2026 and 12 Jan 2026 both show the week ending 04 Jan 2026", parsed.problems[0][1])

    def test_archive_keeps_one_report_per_week(self):
        """A Monday report and a Sunday report of the same week are not added up: the later one is used."""
        data = s.csv_bytes(s.ARCHIVE_HEADINGS, [
            ["3/2/2026", "Frankfurt", "", "Bockenheim", "FindeChristus Referrals", "", 5] + [""] * 11,
            ["3/8/2026", "Frankfurt", "", "Bockenheim", "FindeChristus Referrals", "", 6] + [""] * 11,
            ["6/2/2025", "Frankfurt", "", "Bockenheim", "FindeChristus Referrals", "", 3] + [""] * 11,
            ["6/3/2025", "Frankfurt", "", "Bockenheim", "FindeChristus Referrals", "", 4] + [""] * 11,
        ])
        parsed = data_types.parse_archive(data_files.read_table("archive.csv", data))
        weeks = {r["sunday"]: (r["report_date"], r["referrals_received"]) for r in parsed.records}
        # Monday 2 Mar shows 16-22 Feb; Sunday 8 Mar is the report of Monday 9 Mar: 23 Feb - 1 Mar.
        self.assertEqual(weeks["2026-02-22"], ("2026-03-02", 5))
        self.assertEqual(weeks["2026-03-01"], ("2026-03-08", 6))
        # Monday 2 and Tuesday 3 Jun 2025 are the same report: only the later one counts.
        self.assertEqual(weeks["2025-05-25"], ("2025-06-03", 4))
        self.assertEqual(len(parsed.records), 3)
        self.assertEqual([p[0] for p in parsed.problems], [4])  # the row where 2 Jun 2025 starts

    def test_vollzogen_and_new_member_sheets(self):
        parsed = data_types.parse_baptisms(data_files.read_table("Vollzogen 2026.xlsx", s.vollzogen_file("Frankfurt")))
        self.assertEqual(parsed.problem_count, 1)  # the row without a baptism date
        weeks = {(r["sunday"], r["baptisms"], r["confirmations"]) for r in parsed.records}
        self.assertEqual(weeks, {("2026-09-20", 2, 0), ("2026-09-27", 0, 1)})
        other = data_types.parse_baptisms(data_files.read_table("nm.xlsx", s.new_member_file("Bockenheim")))
        self.assertEqual([(r["area"], r["sunday"], r["baptisms"]) for r in other.records if r["baptisms"]],
                         [("Bockenheim", "2026-09-27", 1)])
        text = json.dumps(parsed.as_dict()) + json.dumps(other.as_dict())
        for secret in s.MADE_UP_NAMES + ["made-up@example.invalid", "Testa", "1990"]:
            self.assertNotIn(secret, text)

    def test_area_data_with_extra_attribute(self):
        data = s.area_file([("Frankfurt", "Frankfurt 1", "Bockenheim", "34000", "2,5", "Big city", "Elders", "yes"),
                            ("Frankfurt", "Frankfurt 1", "Bornheim", "", "", "", "", ""),
                            ("Frankfurt", "Frankfurt 1", "Nowhere", "lots", "", "", "", "")])
        parsed = data_types.parse_area_data(data_files.read_table("areas.csv", data))
        first, second = parsed.records
        self.assertEqual((first["population"], first["size_km2"], first["urban_type"]), (34000, 2.5, "Big city"))
        self.assertEqual(first["extra"], {"Chapel nearby": "yes"})
        self.assertIsNone(second["population"])  # blanks are allowed: nothing changes for them
        self.assertEqual(parsed.problem_count, 1)


class GeoDataTests(unittest.TestCase):
    ROWS = [("Frankfurt", "Frankfurt 1", "Bockenheim", "34.000", "2,5", "", "18000", "Stadt Frankfurt, Bürgeramt", "2024-12-31", "yes"),
            ("Frankfurt", "Frankfurt 1", "Bornheim", "21000", "", "", "", "", "", ""),
            ("Frankfurt", "Frankfurt 1", "Nordend", "", "", "", "", "", "", ""),
            ("Frankfurt", "Frankfurt 1", "Sachsenhausen", "lots", "3", "", "", "", "", ""),
            ("Frankfurt", "Frankfurt 1", "Gallus", "9000", "0", "", "", "", "", ""),
            ("Frankfurt", "Frankfurt 1", "Westend", "9000", "1", "", "", "x", "next week", ""),
            ("Frankfurt", "Frankfurt 1", "Bockenheim", "35000", "2,5", "14000", "", "Stadt Frankfurt", "31.12.2025", ""),
            ("Frankfurt", "Frankfurt 1", "Ostend", "12000", "4", "3000", "", "Amt", "12/31/2024", "no")]

    def parsed(self, rows=None, headings=s.GEO_HEADINGS):
        return data_types.parse_geo_data(data_files.read_table("geo.csv", s.geo_file(rows or self.ROWS, headings)))

    def test_figures_source_and_date_are_read(self):
        parsed = self.parsed()
        by_area = {r["area"]: r for r in parsed.records}
        self.assertEqual(sorted(by_area), ["Bockenheim", "Bornheim", "Ostend"])
        ost = by_area["Ostend"]
        self.assertEqual((ost["population"], ost["size_km2"], ost["density_per_km2"], ost["source"], ost["data_date"]),
                         (12000, 4.0, 3000.0, "Amt", "2024-12-31"))
        self.assertEqual(ost["extra"], {"Chapel nearby": "no"})
        bor = by_area["Bornheim"]
        self.assertEqual((bor["population"], bor["size_km2"], bor["source"], bor["data_date"]), (21000, None, None, None))

    def test_the_last_row_of_an_area_wins_and_bad_rows_are_explained(self):
        parsed = self.parsed()
        bockenheim = next(r for r in parsed.records if r["area"] == "Bockenheim")
        self.assertEqual((bockenheim["population"], bockenheim["data_date"], bockenheim["source"]),
                         (35000, "2025-12-31", "Stadt Frankfurt"))
        self.assertEqual(parsed.left_out, 1)  # Nordend has no figure at all
        text = " | ".join(p[1] for p in parsed.problems)
        self.assertIn("Sachsenhausen", text)   # 'lots' is not a number
        self.assertIn("Gallus", text)          # size 0 km2
        self.assertIn("Westend", text)         # 'next week' is not a date
        self.assertIn("Bockenheim is in the file twice", text)
        self.assertEqual(parsed.problem_count, 4)

    def test_german_headings(self):
        headings = ["Zone", "District", "Area", "Einwohner", "Fläche (km2)", "Haushalte", "Quelle", "Stand"]
        parsed = self.parsed([("Frankfurt", "Frankfurt 1", "Bornheim", "21.000", "3,5", "9500", "Statistik", "31.12.2024")], headings)
        record = parsed.records[0]
        self.assertEqual((record["population"], record["size_km2"], record["households"], record["data_date"]),
                         (21000, 3.5, 9500, "2024-12-31"))

    def test_a_file_without_any_figure_column_is_refused(self):
        with self.assertRaises(data_files.FileProblem) as caught:
            data_types.parse_geo_data(data_files.read_table("x.csv", b"Zone,District,Area,Notes\nFrankfurt,F1,Bornheim,hi\n"))
        self.assertIn("Population", str(caught.exception))

    def test_the_template_reads_back_as_it_was_saved(self):
        saved = [{"zone": "Frankfurt", "district": "Frankfurt 1", "area": "Bockenheim", "population": 34000, "size_km2": 2.5,
                  "density_per_km2": 13600.0, "households": 18000, "source": "Amt", "data_date": date(2024, 12, 31),
                  "extra": {"Chapel nearby": "yes"}}]
        headings, rows = data_types.geo_template(saved)
        self.assertEqual(headings[-1], "Chapel nearby")
        parsed = data_types.parse_geo_data(data_files.read_table("t.csv", data_files.as_csv(headings, rows)))
        record = parsed.records[0]
        self.assertEqual((record["population"], record["size_km2"], record["density_per_km2"], record["households"],
                          record["source"], record["data_date"], record["extra"]),
                         (34000, 2.5, 13600.0, 18000, "Amt", "2024-12-31", {"Chapel nearby": "yes"}))
        self.assertEqual(parsed.problem_count, 0)

    def test_no_names_in_geo_records(self):
        text = json.dumps(self.parsed().as_dict())
        for secret in s.MADE_UP_NAMES + s.MADE_UP_IDS:
            self.assertNotIn(secret, text)


class TextTests(unittest.TestCase):
    def test_texts_are_in_the_portal_catalog(self):
        """The upload texts are in the portal's catalogs (round 6 interface translation): each uploads.* text is in
        portal/i18n/en.json, under its own key or, where the portal already had that English text, under the portal's
        key, and every language has the same keys. i18n.js looks a key up by its English text and the first key keeps a
        text, so an upload text never takes over a portal word."""
        self.assertTrue(all(key.startswith("uploads.") for key in TEXT))
        folder = ROOT / "portal" / "i18n"
        if not (folder / "en.json").exists():
            self.skipTest("portal/ is not next to roster-importer/ here")
        english = json.loads((folder / "en.json").read_text(encoding="utf-8"))
        texts = {value for value in english.values() if isinstance(value, str)}
        # (a text that names the mission's time zone is in the catalog with {zone} in its place)
        import settings
        self.assertEqual(sorted(key for key, value in TEXT.items() if value.replace(settings.TIME_ZONE_NAME, '{zone}') not in texts), [])
        for code in json.loads((folder / "catalogs.json").read_text(encoding="utf-8"))["languages"]:
            catalog = json.loads((folder / f"{code}.json").read_text(encoding="utf-8"))
            self.assertEqual(sorted(set(english) - set(catalog)), [], code)

    def test_every_key_used_exists(self):
        source = "".join((Path(__file__).resolve().parents[1] / f).read_text(encoding="utf-8")
                         for f in ("data_uploads.py", "data_upload_pages.py", "data_types.py", "data_files.py", "data_names.py",
                              "vollzogen_pages.py", "vollzogen_upload.py"))
        used = set(re.findall(r"""["'](uploads\.[A-Za-z]+\.[A-Za-z]+)["']""", source))
        self.assertTrue(used)
        self.assertEqual(sorted(used - set(TEXT)), [])
        for part in ("title", "about", "columns", "merge"):
            for name in ("areas", "geo", "finding", "zoneHistory", "referralArchive", "rates", "baptisms"):
                self.assertIn(f"uploads.{name}.{part}", TEXT)
        for key in ("uploads.names.zone", "uploads.names.area"):
            self.assertIn(key, TEXT)
        self.assertEqual(plain("uploads.hub.last", date="1 Jan", file="a.csv"), "Last upload: 1 Jan · a.csv")


if __name__ == "__main__":
    unittest.main()
