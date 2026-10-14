"""The Geo data pages build their HTML from stand-in answers (no database): the table of figures with source and date, the check
page lines, and the sample table. Made-up areas only. Run from roster-importer/:  python -m unittest tests.test_geo_pages
"""
import os
import unittest
from datetime import date
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "postgresql://nobody@127.0.0.1:1/none")  # never opened by these tests
import data_upload_pages as pages  # noqa: E402
import data_uploads  # noqa: E402


class FakeConnection:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class GeoPageTests(unittest.TestCase):
    AREAS = [{"area_id": 1, "area": "Bockenheim", "district": "Frankfurt 1", "zone": "Frankfurt", "active": True,
              "population": 34000, "size_km2": 2.5, "density_per_km2": 13600.0, "households": 18000, "source": "Stadt <Test>",
              "data_date": date(2024, 12, 31), "extra": {}},
             {"area_id": 2, "area": "Altstadt", "district": "Frankfurt 1", "zone": "Frankfurt", "active": False,
              "population": None, "size_km2": None, "density_per_km2": None, "households": None, "source": None,
              "data_date": None, "extra": {}}]

    def test_the_table_shows_figures_source_and_date_and_marks_old_areas(self):
        with patch.object(pages.database, "connect", return_value=FakeConnection()), \
                patch.object(pages.database, "cursor", return_value=FakeConnection()), \
                patch.object(pages, "geo_rows", return_value=self.AREAS), \
                patch.object(pages, "geo_zone_rows", return_value=[]), patch.object(pages, "geo_district_rows", return_value=[]):
            html = pages.geo_table_page()
        for text in ("Geo data per area", "Bockenheim", "34000", "13600", "18000", "Stadt &lt;Test&gt;", "31 Dec 2024", "Data date",
                     "Households", "Source"):
            self.assertIn(text, html)
        self.assertIn("old</span>", html)  # the closed area with no figures is marked old

    def test_the_geo_upload_is_listed_with_its_kind_and_columns(self):
        self.assertIn("geo", data_uploads.UPLOADS)
        self.assertEqual(data_uploads.UPLOADS["geo"]["kind"], "GEO_DATA")
        self.assertEqual(data_uploads.kind_label("GEO_DATA"), "Geo data")
        self.assertEqual(data_uploads.kind_label("RETIRE"), "Deleted place or question")
        self.assertEqual([field for _, field in pages.SAMPLE_COLUMNS["geo"]],
                         ["zone", "area", "population", "size_km2", "density_per_km2", "households", "source", "data_date"])
        table = pages.sample_table("geo", [{"zone": "Frankfurt", "area": "Bockenheim", "population": 34000, "size_km2": 2.5,
                                            "density_per_km2": None, "households": 18000, "source": "Amt",
                                            "data_date": "2024-12-31"}])
        self.assertIn("31 Dec 2024", table)
        self.assertIn("2.5", table)

    def test_the_check_page_counts_rows_without_source_or_date(self):
        class Cursor:
            pass

        pending = {"parsed": {"records": [
            {"zone": "Frankfurt", "area": "Bockenheim", "source": "Amt", "data_date": "2024-12-31", "area_id": 1},
            {"zone": "Frankfurt", "area": "Bornheim", "source": None, "data_date": None, "area_id": 2}]}}

        class Matcher:
            def __init__(self, cur, mission, with_districts=False):
                pass

        with patch.object(data_uploads.data_names, "Matcher", Matcher), \
                patch.object(data_uploads.data_names, "place_all", return_value={}), \
                patch.object(data_uploads.sign_in, "current_mission_id", return_value=2):
            check = data_uploads.check_upload(Cursor(), "geo", pending)
        self.assertEqual(check["questions"], {})
        self.assertTrue(any("1 rows have no source or no data date" in line for line in check["lines"]), check["lines"])


if __name__ == "__main__":
    unittest.main()
