"""Geo data in the owner's format without a database: three tables side by side (Zone / District / Area), six urbanisation
columns and an Area Type, German and English number formats, placeholder and duplicate rows held back for the manager, the
template, how rows are saved, the pages' HTML and the migration text. The sample (tests/data_samples.py) has the real file's
headings and invented places and numbers.

The same upload against a real throw-away database is tests/test_geo_data_db.py (test_05 onwards; NOT run in round 13: no database
in the overnight sandbox). Run this file from roster-importer/:  python -m unittest tests.test_geo_csv
"""
import json
import os
import re
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "postgresql://nobody@127.0.0.1:1/none")  # never opened by these tests
import batches  # noqa: E402
import data_files  # noqa: E402
import data_names  # noqa: E402
import data_types  # noqa: E402
import data_upload_pages as pages  # noqa: E402
import data_uploads  # noqa: E402
from data_files import FileProblem  # noqa: E402
from data_text import TEXT  # noqa: E402
from tests import data_samples as s  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]


def data_upload_pages_app():
    import app
    return app.app


def parsed(data=None, name="geo.csv"):
    return data_types.parse_geo_data(data_files.read_table(name, data or s.geo_tables_file()))


def by_level(result):
    out = {"zone": {}, "district": {}, "area": {}}
    for record in result.records:
        out[record["level"]][record[record["level"]]] = record
    return out


class ThreeTableTests(unittest.TestCase):
    def test_the_layout_is_found_and_each_table_becomes_records_of_its_level(self):
        found = by_level(parsed())
        self.assertEqual(sorted(found["zone"]), ["Alpha Zone", "Beta Zone"])
        self.assertEqual(sorted(found["district"]), ["District One", "District Two", "Ghost District"])
        self.assertEqual(sorted(found["area"]), ["Beispielstadt", "Nord Dorf", "Testville"])

    def test_the_mission_total_is_left_out_and_an_empty_row_says_nothing(self):
        result = parsed()
        self.assertEqual(result.left_out, 2)  # the Mission row of the Zone table and Emptyville (no figure)
        self.assertEqual(result.problem_count, 0)
        self.assertEqual(result.rows_read, 3 + 4 + 8)  # every named row of the three tables

    def test_the_figures_the_six_urbanisation_columns_and_the_area_type(self):
        zone = by_level(parsed())["zone"]["Alpha Zone"]
        self.assertEqual((zone["population"], zone["size_km2"], zone["density_per_km2"], zone["area_type"]), (4414139, 9036.03, 488.5, "City"))
        self.assertEqual((zone["pop_urban_centre"], zone["pop_dense_urban_cluster"], zone["pop_semi_dense_urban_cluster"],
                          zone["pop_suburban"], zone["pop_rural_very_low"], zone["pop_rural_low"]),
                         (1486250, 1285607, 201129, 833013, 26588, 221659))
        self.assertEqual((zone["zone"], zone["district"], zone["area"], zone["households"], zone["source"], zone["data_date"]),
                         ("Alpha Zone", "", "", None, None, None))

    def test_german_and_english_number_formats(self):
        found = by_level(parsed())
        beta = found["zone"]["Beta Zone"]
        self.assertEqual((beta["population"], beta["size_km2"], beta["density_per_km2"]), (6859500, 24298.15, 282.31))
        self.assertEqual(found["district"]["District Two"]["population"], 850000)
        nord = found["area"]["Nord Dorf"]
        self.assertEqual((nord["population"], nord["size_km2"], nord["density_per_km2"]), (15000, 12.5, 1200.0))
        english = by_level(parsed(s.geo_tables_file(areas=[["Eng Town", "21,000", "1,234.5", "17.0", "1", "2", "3", "4", "5", "6", "City"]])))
        record = english["area"]["Eng Town"]
        self.assertEqual((record["population"], record["size_km2"]), (21000, 1234.5))

    def test_placeholders_and_copies_are_held_back_and_listed_not_saved(self):
        result = parsed()
        held = {name: (level, why) for _row, name, level, why in result.flagged}
        self.assertEqual(sorted(held), ["APs", "Copy Town", "Media Elders", "Office Sisters", "Offstrict"])
        self.assertEqual(held["Media Elders"], ("area", "Media Elders looks like a placeholder, not a place."))
        self.assertEqual(held["Offstrict"][0], "district")
        self.assertEqual(held["Copy Town"], ("area", "Copy Town has exactly the same figures as Beispielstadt: a copy?"))
        saved = {r["area"] or r["district"] or r["zone"] for r in result.records}
        self.assertFalse(saved & set(held))
        self.assertTrue(all(isinstance(row, int) and row > 1 for row, *_ in result.as_dict()["flagged"]))  # numbered for the manager

    def test_the_first_of_two_copies_is_kept(self):
        found = by_level(parsed())["area"]
        self.assertIn("Beispielstadt", found)
        self.assertNotIn("Copy Town", found)

    def test_a_name_twice_in_one_table_uses_the_last_row(self):
        result = parsed(s.geo_tables_file(zones=[["Alpha Zone", 1, 1, 1, 1, 1, 1, 1, 1, 1, "City"], ["Alpha Zone", 2, 2, 2, 2, 2, 2, 2, 2, 2, "City"]],
                                          districts=[], areas=[]))
        self.assertEqual([r["population"] for r in result.records], [2])
        self.assertEqual(result.problem_count, 1)

    def test_a_bad_number_is_a_problem_of_its_row_only(self):
        result = parsed(s.geo_tables_file(zones=[], districts=[["District One", "lots", 1, 1, 1, 1, 1, 1, 1, 1, "City"],
                                                              ["District Two", 5, 1, 1, 1, 1, 1, 1, 1, 1, "City"]], areas=[]))
        self.assertEqual([r["district"] for r in result.records], ["District Two"])
        self.assertEqual(result.problem_count, 1)
        self.assertIn("District One", result.problems[0][1])

    def test_an_xlsx_reads_the_same(self):
        self.assertEqual(len(parsed(s.geo_tables_file(as_xlsx=True), "geo.xlsx").records), len(parsed().records))

    def test_the_columns_are_found_by_their_code_not_by_their_order(self):
        data = s.csv_bytes(["Zone", "Population", "Area", "Population Density", "Low density rural grid cell(312)", "Urban Centre(130)", "Area Type", "",
                            "Area", "Population", "Area", "Population Density"],
                           [["Z One", "100", "5", "20", "7", "9", "Town", "", "A One", "50", "2.5", "20"]])
        found = by_level(parsed(data))
        self.assertEqual((found["zone"]["Z One"]["pop_rural_low"], found["zone"]["Z One"]["pop_urban_centre"],
                          found["zone"]["Z One"]["pop_suburban"], found["zone"]["Z One"]["area_type"]), (7, 9, None, "Town"))
        self.assertEqual(found["area"]["A One"]["size_km2"], 2.5)

    def test_a_table_without_size_or_density_columns_still_reads(self):
        data = s.csv_bytes(["Zone", "Population", "", "District", "Population"], [["Z One", "100", "", "D One", "40"]])
        found = by_level(parsed(data))
        self.assertEqual((found["zone"]["Z One"]["population"], found["zone"]["Z One"]["size_km2"], found["district"]["D One"]["population"]),
                         (100, None, 40))


class FlatFormatTests(unittest.TestCase):
    """The older single-table format (one row per area) still works, now with the new columns."""

    def test_the_flat_file_is_read_as_before(self):
        result = data_types.parse_geo_data(data_files.read_table("g.csv", s.geo_file([("Alpha Zone", "District One", "Testville", "34.000", "2,5", "13600", "18000", "Amt", "2024-12-31", "yes")])))
        record = result.records[0]
        self.assertEqual((record["level"], record["population"], record["size_km2"], record["households"], record["extra"]),
                         ("area", 34000, 2.5, 18000, {"Chapel nearby": "yes"}))
        self.assertIsNone(record["pop_urban_centre"])

    def test_the_flat_file_can_carry_the_new_columns(self):
        headings = s.GEO_HEADINGS[:-1] + ["Urban Centre (130)", "Low density rural grid cell (312)", "Area Type"]
        data = s.geo_file([("Alpha Zone", "District One", "Testville", "34000", "2", "", "", "", "", "9.000", "1.000", "City")], headings)
        record = data_types.parse_geo_data(data_files.read_table("g.csv", data)).records[0]
        self.assertEqual((record["pop_urban_centre"], record["pop_rural_low"], record["area_type"], record["extra"]), (9000, 1000, "City", {}))

    def test_a_flat_file_is_not_mistaken_for_three_tables(self):
        self.assertIsNone(data_types.geo_table_starts(data_files.read_table("g.csv", s.geo_file([("Z", "D", "A", "1", "1", "", "", "", "", "")]))))
        self.assertIsNotNone(data_types.geo_table_starts(data_files.read_table("g.csv", s.geo_tables_file())))


class TemplateTests(unittest.TestCase):
    ZONES = [{"zone": "Alpha Zone", "population": 1000, "size_km2": 10.0, "density_per_km2": 100.0, "pop_urban_centre": 500,
              "area_type": "City"}, {"zone": "Beta Zone"}]
    DISTRICTS = [{"district": "District One", "population": 400}]
    AREAS = [{"area": "Testville", "population": 250, "size_km2": 2.5, "density_per_km2": 100.0, "pop_rural_low": 7},
             {"area": "Nord Dorf"}, {"area": "Third"}]

    def test_the_template_has_the_three_tables_with_the_saved_figures(self):
        headings, rows = data_types.geo_template_tables(self.ZONES, self.DISTRICTS, self.AREAS)
        self.assertEqual(len(headings), 11 * 3 + 2)
        self.assertEqual([headings[0], headings[12], headings[24]], ["Zone", "District", "Area"])
        self.assertEqual((headings[11], headings[23]), ("", ""))  # the blank columns between the tables
        self.assertIn("Dense Urban Cluster (223)", headings)
        self.assertEqual(len(rows), 3)  # as many rows as the longest table
        self.assertEqual(rows[0][:5], ["Alpha Zone", 1000, "10", "100", 500])
        self.assertEqual(rows[2][:12], [""] * 12)

    def test_the_template_reads_back_as_the_same_figures(self):
        headings, rows = data_types.geo_template_tables(self.ZONES, self.DISTRICTS, self.AREAS)
        result = data_types.parse_geo_data(data_files.read_table("t.csv", data_files.as_csv(headings, rows)))
        found = by_level(result)
        self.assertEqual((found["zone"]["Alpha Zone"]["population"], found["zone"]["Alpha Zone"]["pop_urban_centre"]), (1000, 500))
        self.assertEqual(found["area"]["Testville"]["pop_rural_low"], 7)
        self.assertEqual(found["district"]["District One"]["population"], 400)
        self.assertEqual(result.left_out, 3)  # Beta Zone, Nord Dorf and Third have no figure yet
        self.assertEqual(result.problem_count, 0)
        self.assertEqual(result.flagged, [])

    def test_the_download_is_the_three_table_template(self):
        class Cursor:
            pass

        with patch.object(data_uploads, "geo_zone_rows", return_value=self.ZONES), \
                patch.object(data_uploads, "geo_district_rows", return_value=self.DISTRICTS), \
                patch.object(data_uploads, "geo_rows", return_value=self.AREAS):
            name, headings, rows = data_uploads.template_file("geo", Cursor())
        self.assertEqual(name, "template-geo.csv")
        self.assertEqual(headings.count("Population"), 3)
        self.assertEqual(len(rows), 3)


class FakeCursor:
    def __init__(self):
        self.calls = []

    def execute(self, query, params=None):
        self.calls.append((query, params))


class FakeCtx:
    def __init__(self, cursor):
        self.cursor = cursor

    def __enter__(self):
        return self.cursor

    def __exit__(self, *args):
        return False


class SavingTests(unittest.TestCase):
    def test_every_table_has_its_upsert_with_the_columns_it_has(self):
        for level, (table, key, columns) in data_uploads.GEO_TABLES.items():
            sql_text = data_uploads.geo_upsert(table, key, columns)
            self.assertTrue(sql_text.startswith(f"insert into public.{table} as g ("))
            self.assertIn(f"on conflict ({key}) do update", sql_text)
            self.assertEqual("households" in sql_text, level == "area", level)
            self.assertIn("is distinct from", sql_text)  # nothing is written when nothing would change
            self.assertIn("coalesce(excluded.pop_urban_centre,g.pop_urban_centre)", sql_text)  # an empty cell keeps what is saved
            self.assertIn("when excluded.population is not null or excluded.size_km2 is not null then null", sql_text)  # old density cleared

    def test_the_batch_covers_the_three_tables_and_their_keys(self):
        self.assertEqual(batches.GEO_DATA_TABLES, ["area_geo_data", "zone_geo_data", "district_geo_data"])
        self.assertEqual(batches.TABLES_OF_KIND["GEO_DATA"], batches.GEO_DATA_TABLES)
        self.assertEqual(batches.row_key("zone_geo_data", {"zone_id": 4}), {"zone_id": 4})
        self.assertEqual(batches.row_key("district_geo_data", {"district_id": 5}), {"district_id": 5})

    def test_each_record_goes_to_the_table_of_its_level_and_a_name_without_a_place_is_skipped(self):
        cursor = FakeCursor()
        records = [{"level": "zone", "zone": "Alpha Zone", "zone_id": 1, "population": 10, "extra": {}},
                   {"level": "district", "district": "District One", "district_id": 2, "population": 5, "extra": {}},
                   {"level": "district", "district": "Ghost District", "district_id": None, "population": 5, "extra": {}},
                   {"level": "area", "area": "Testville", "area_id": 3, "population": 2, "households": 1, "extra": {}},
                   {"area": "Old flat row", "area_id": 4, "population": 1, "extra": {}},  # the flat format has no level
                   {"level": "zone", "zone": "Left out", "zone_id": None, "population": 1, "extra": {}}]
        with patch.object(data_uploads.batches, "lock_tables"), patch.object(data_uploads.batches, "snapshot", return_value={}), \
                patch.object(data_uploads.batches, "count_changes", return_value=0), \
                patch.object(data_uploads.database, "cursor", return_value=FakeCtx(cursor)), \
                patch.object(data_uploads.sign_in, "actor_name", return_value="Test Analyst"):
            self.assertIsNone(data_uploads.save_geo_records(object(), records, "geo.csv"))  # nothing changed: no batch
        tables = [re.match(r"insert into public\.(\w+)", query).group(1) for query, _ in cursor.calls]
        self.assertEqual(tables, ["zone_geo_data", "district_geo_data", "area_geo_data", "area_geo_data"])
        self.assertEqual(cursor.calls[0][1]["zone_id"], 1)
        self.assertEqual(cursor.calls[0][1]["actor"], "Test Analyst")
        self.assertNotIn("households", cursor.calls[0][1])

    def test_a_changed_upload_is_one_batch_with_the_counts_per_level(self):
        cursor = FakeCursor()
        records = [{"level": "zone", "zone_id": 1, "population": 10, "extra": {}}, {"level": "area", "area_id": 3, "population": 2, "extra": {}},
                   {"level": "area", "area_id": 4, "population": 2, "extra": {}}]
        with patch.object(data_uploads.batches, "lock_tables"), patch.object(data_uploads.batches, "snapshot", return_value={}), \
                patch.object(data_uploads.batches, "count_changes", return_value=3), \
                patch.object(data_uploads.batches, "create_batch", return_value="batch-1") as create, \
                patch.object(data_uploads.batches, "record_changes") as record, \
                patch.object(data_uploads.database, "cursor", return_value=FakeCtx(cursor)), \
                patch.object(data_uploads.sign_in, "actor_name", return_value="x"):
            self.assertEqual(data_uploads.save_geo_records(object(), records, "geo.csv"), "batch-1")
        self.assertEqual(create.call_args.args[1:3], ("GEO_DATA", "geo.csv"))
        self.assertEqual(create.call_args.args[4], {"areas_in_file": 2, "districts_in_file": 0, "zones_in_file": 1, "rows_changed": 3})
        self.assertEqual(record.call_args.args[2], batches.GEO_DATA_TABLES)


class MatchingTests(unittest.TestCase):
    ZONES = [{"id": 1, "name": "Alpha Zone", "active": True}, {"id": 2, "name": "Beta Zone", "active": True}]
    AREAS = [{"id": 10, "name": "Testville", "active": True, "district": "District One", "zone_id": 1, "zone": "Alpha Zone"},
             {"id": 11, "name": "Nord Dorf", "active": True, "district": "District Two", "zone_id": 2, "zone": "Beta Zone"}]
    DISTRICTS = [{"id": 20, "name": "District One", "active": True, "zone_id": 1, "zone": "Alpha Zone"},
                 {"id": 21, "name": "District Two", "active": True, "zone_id": 2, "zone": "Beta Zone"}]

    def matcher(self):
        matcher = data_names.Matcher.__new__(data_names.Matcher)
        matcher.mission_id, matcher.answers, matcher.remembered = 2, {}, {}
        matcher.zones = [dict(z, key=data_names.fold_zone(z["name"])) for z in self.ZONES]
        matcher.areas = [dict(a, key=data_names.fold(a["name"]), zone_key=data_names.fold_zone(a["zone"])) for a in self.AREAS]
        matcher.area_by_id = {a["id"]: a for a in matcher.areas}
        matcher.districts = [dict(d, key=data_names.fold(d["name"])) for d in self.DISTRICTS]
        return matcher

    def test_zones_districts_and_areas_are_placed_each_at_its_level(self):
        records = parsed().records
        questions = data_uploads.place_records(self.matcher(), "geo", records)
        found = by_level(type("Result", (), {"records": records}))
        self.assertEqual(found["zone"]["Alpha Zone"]["zone_id"], 1)
        self.assertEqual(found["district"]["District One"]["district_id"], 20)
        self.assertIsNone(found["district"]["Ghost District"]["district_id"])  # quietly: a district is never asked about
        self.assertEqual(found["area"]["Testville"]["area_id"], 10)
        # Beispielstadt is no portal area: it is asked (as areas always are), and so is nothing else.
        self.assertEqual(sorted(name for _level, name in questions), ["Beispielstadt"])

    def test_the_check_page_counts_the_tables_and_names_the_districts_that_are_not_in_the_portal(self):
        pending = {"parsed": {"records": parsed().records}}
        matcher = self.matcher()
        with patch.object(data_uploads.data_names, "Matcher", lambda cur, mission, with_districts=False: matcher), \
                patch.object(data_uploads.sign_in, "current_mission_id", return_value=2):
            check = data_uploads.check_upload(object(), "geo", pending)
        lines = " | ".join(check["lines"])
        self.assertIn("Three tables found: 2 zones, 3 districts, 3 areas.", lines)
        self.assertIn("1 district(s) of the file are not districts of the portal, so their figures are not saved: Ghost District.", lines)
        self.assertIn("rows have no source or no data date", lines)  # the owner's file has neither: said, not blocked


class PageTests(unittest.TestCase):
    def test_the_check_page_lists_the_rows_held_back(self):
        result = parsed().as_dict()
        pending = {"filename": "geo.csv", "parsed": result}
        check = {"questions": {}, "lines": ["x"], "older": None, "matcher": None}
        with patch.object(pages.database, "connect", return_value=FakeCtx(None)), patch.object(pages.database, "cursor", return_value=FakeCtx(None)), \
                patch.object(pages, "check_upload", return_value=check):
            html = pages.review_page("geo", pending)
        for text in ("Rows held back", "Media Elders", "Media Elders looks like a placeholder, not a place.", "Copy Town has exactly the same figures as Beispielstadt",
                     "rows held back", "Offstrict", "<td>District</td>", "<td>Area</td>"):
            self.assertIn(text, html)
        self.assertIn('action="/uploads/geo/apply"', html)  # what is not held back can be applied

    def test_the_upload_page_tells_about_the_owners_format(self):
        class Cursor:
            pass

        with patch.object(pages.database, "connect", return_value=FakeCtx(None)), patch.object(pages.database, "cursor", return_value=FakeCtx(None)), \
                patch.object(pages, "recent_uploads", return_value=[]), data_upload_pages_app().test_request_context("/"):
            html = pages.upload_page("geo")
        self.assertIn("three tables side by side", html)

    def test_the_sample_shows_a_zone_or_district_name_in_the_area_column(self):
        records = parsed().records
        table = pages.sample_table("geo", records)
        self.assertIn("Alpha Zone", table)
        self.assertIn("4414139", table)

    def test_the_table_page_has_zones_districts_and_areas_with_the_new_columns(self):
        zones = [{"zone_id": 1, "zone": "Alpha Zone", "active": True, "population": 5, "size_km2": 2.0, "density_per_km2": 2.5,
                  "pop_urban_centre": 7, "area_type": "City"}]
        districts = [{"district_id": 2, "district": "District One", "zone": "Alpha Zone", "active": False, "population": 4}]
        areas = [{"area_id": 3, "area": "Testville", "district": "District One", "zone": "Alpha Zone", "active": True, "population": 3,
                  "pop_rural_low": 9, "households": 2, "source": "Amt", "data_date": None}]
        with patch.object(pages.database, "connect", return_value=FakeCtx(None)), patch.object(pages.database, "cursor", return_value=FakeCtx(None)), \
                patch.object(pages, "geo_zone_rows", return_value=zones), patch.object(pages, "geo_district_rows", return_value=districts), \
                patch.object(pages, "geo_rows", return_value=areas):
            html = pages.geo_table_page()
        for text in ("<h3>Zones</h3>", "<h3>Districts</h3>", "<h3>Areas</h3>", "Urban centre (130)", "Low density rural (312)", "Area type", "Alpha Zone",
                     "old</span>"):
            self.assertIn(text, html)


class TextAndMigrationTests(unittest.TestCase):
    NEW = ["uploads.geo.tablesAbout", "uploads.geo.tables", "uploads.geo.flaggedTitle", "uploads.geo.flaggedHelp", "uploads.geo.flaggedCount",
           "uploads.geo.flagPlaceholder", "uploads.geo.flagCopy", "uploads.geo.districtsNotInPortal", "uploads.geo.zonesTitle",
           "uploads.geo.districtsTitle", "uploads.geo.areasTitle", "uploads.col.areaType", "uploads.col.urban130", "uploads.col.urban223",
           "uploads.col.urban222", "uploads.col.urban221", "uploads.col.urban311", "uploads.col.urban312"]

    def test_every_new_text_is_in_every_language_catalog(self):
        folder = ROOT / "portal" / "i18n"
        english = json.loads((folder / "en.json").read_text(encoding="utf-8"))
        owners = {}
        for key in self.NEW:
            owners[key] = next(k for k, v in english.items() if v == TEXT[key])
        for code in json.loads((folder / "catalogs.json").read_text(encoding="utf-8"))["languages"]:
            catalog = json.loads((folder / f"{code}.json").read_text(encoding="utf-8"))
            for key, owner in owners.items():
                self.assertTrue(str(catalog[owner]).strip(), (code, key))
                self.assertEqual(sorted(re.findall(r"\{(\w+)\}", catalog[owner])), sorted(re.findall(r"\{(\w+)\}", TEXT[key])), (code, key))

    def test_migration_052_adds_columns_and_two_closed_tables_and_does_not_touch_046(self):
        folder = ROOT / "portal-api" / "migrations"
        up = (folder / "052_geo_data_tables.sql").read_text(encoding="utf-8")
        down = (folder / "052_geo_data_tables_rollback.sql").read_text(encoding="utf-8")
        for text in (up, down):
            code = "\n".join(line for line in text.splitlines() if not line.startswith("--"))
            self.assertEqual(len(re.findall(r"^BEGIN;", code, re.M)), 1)
            self.assertEqual(len(re.findall(r"^COMMIT;", code, re.M)), 1)
        for field in data_types.URBAN_FIELDS:
            self.assertIn(f"ADD COLUMN IF NOT EXISTS {field} integer CHECK ({field} >= 0)", up)
            self.assertRegex(up, rf"CREATE TABLE IF NOT EXISTS public\.zone_geo_data \([\s\S]*?\n  {field} integer")
        self.assertIn("ADD COLUMN IF NOT EXISTS area_type text", up)
        self.assertNotRegex(up, r"ADD COLUMN IF NOT EXISTS \w+ [^,;]*NOT NULL")  # new columns are nullable
        for table in ("zone_geo_data", "district_geo_data"):
            self.assertIn(f"CREATE TABLE IF NOT EXISTS public.{table}", up)
        self.assertEqual(up.count("ENABLE ROW LEVEL SECURITY"), 2)
        self.assertNotIn("CREATE POLICY", up)
        self.assertNotIn("GRANT SELECT ON public", up)
        self.assertIn("REVOKE ALL ON public.zone_geo_data, public.district_geo_data FROM PUBLIC, anon, authenticated, service_role", up)
        self.assertIn("DROP TABLE IF EXISTS public.zone_geo_data, public.district_geo_data", down)
        self.assertIn("DELETE FROM public.roster_import_changes WHERE table_name IN ('zone_geo_data', 'district_geo_data')", down)
        # 046 is not edited: it still creates only the area table.
        old = (folder / "046_area_geo_data.sql").read_text(encoding="utf-8")
        self.assertNotIn("pop_urban_centre", old)
        self.assertNotIn("zone_geo_data", old)
        # The columns the code writes are the columns of the tables.
        for level, (table, key, columns) in data_uploads.GEO_TABLES.items():
            if level != "area":
                block = up[up.index(f"CREATE TABLE IF NOT EXISTS public.{table}"):]
                block = block[:block.index(");")]
                for column in [key, *columns, "source", "data_date", "extra", "updated_by"]:
                    self.assertRegex(block, rf"\n  {column} ", (table, column))

    def test_the_next_migration_number_is_past_052(self):
        text = (ROOT / "portal-api" / "migrations" / "README.md").read_text(encoding="utf-8")
        found = re.search(r"The next number is (\d{3})", text)
        self.assertTrue(found and int(found.group(1)) >= 53)


if __name__ == "__main__":
    unittest.main()
