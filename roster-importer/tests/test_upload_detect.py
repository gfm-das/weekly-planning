"""The Uploads page tells which kind of file was dropped from its heading row: one kind goes straight on, several are asked."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))
os.environ.setdefault("DATABASE_URL", "postgresql://nobody@127.0.0.1:1/none")

import data_samples as s  # noqa: E402
import historical_import  # noqa: E402
import roster_file  # noqa: E402
import upload_detect  # noqa: E402
from data_files import FileProblem  # noqa: E402


class Detect(unittest.TestCase):
    def kinds(self, name, data):
        return upload_detect.detect(name, data)

    def test_one_kind_goes_straight_on(self):
        self.assertEqual(self.kinds("a.csv", s.finding_file([("Frankfurt", "D1", "Bockenheim")])), ["finding"])
        self.assertEqual(self.kinds("a.csv", s.zone_history_file([("9/6/2026", "Frankfurt", 5, 4)])), ["zone-history"])
        # The Rates upload is gone (round 16): its sheet is no longer recognised.
        self.assertEqual(self.kinds("a.csv", s.csv_bytes(["Date", "Zone", "Teaching Rate", "Contact Rate"],
                                                         [["9/27/2026", "Frankfurt", "41.00%", "98.30%"]])), [])
        self.assertEqual(self.kinds("a.csv", s.geo_tables_file()), ["geo"])
        roster = s.csv_bytes(roster_file.REQUIRED_COLUMNS, [])
        self.assertEqual(self.kinds("r.csv", roster), ["roster"])
        old = s.csv_bytes(upload_headings(), [])
        self.assertEqual(self.kinds("h.csv", old), ["historical"])

    def test_look_alikes_are_asked(self):
        self.assertEqual(self.kinds("v.xlsx", s.vollzogen_sheet()), ["people", "vollzogen", "baptisms"])
        self.assertEqual(self.kinds("n.xlsx", s.new_member_file("Bockenheim")), ["people", "baptisms"])


    def test_a_flat_area_file_is_geo_data_without_a_question(self):
        flat = s.geo_flat_file([("Frankfurt", "D1", "Bockenheim", 1000, 2.5, "Urban", "Normal", "x")])
        self.assertEqual(self.kinds("a.csv", flat), ["geo"])
        only_types = s.csv_bytes(["Zone", "District", "Area", "Urban type"], [["Frankfurt", "D1", "Bockenheim", "Urban"]])
        self.assertEqual(self.kinds("t.csv", only_types), ["geo"])

    def test_unknown_and_unreadable(self):
        self.assertEqual(self.kinds("x.csv", s.csv_bytes(["Foo", "Bar"], [["1", "2"]])), [])
        with self.assertRaises(FileProblem):
            self.kinds("x.pdf", b"%PDF")


def upload_headings():
    return [historical_import.TIMESTAMP_COLUMN, historical_import.EMAIL_COLUMN, historical_import.COMPANIONSHIP_COLUMN,
            historical_import.UNIT_COLUMN, historical_import.SUNDAY_COLUMN]


if __name__ == "__main__":
    unittest.main()
