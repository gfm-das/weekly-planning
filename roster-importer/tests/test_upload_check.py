"""POST /uploads/check: the one drop zone sends a file to the right check, or asks. No database: the page and the waiting
store are replaced by small stand-ins."""
import io
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))
os.environ.setdefault("DATABASE_URL", "postgresql://nobody@127.0.0.1:1/none")

import app  # noqa: E402
import data_samples as s  # noqa: E402


class Check(unittest.TestCase):
    def send(self, name, data, kind="auto"):
        saved = []
        client = app.app.test_client()
        with client.session_transaction() as session:
            session["csrf_token"] = "t"
        with patch("sign_in.allowed", return_value=True), \
                patch("data_upload_pages.hub_page", side_effect=lambda message="", chosen="auto": f"HUB {chosen} {message}"), \
                patch("data_upload_pages.save_pending", side_effect=lambda *a: saved.append(a[0])):
            answer = client.post("/uploads/check", data={"csrf_token": "t", "kind": kind, "file": (io.BytesIO(data), name)},
                                 content_type="multipart/form-data")
        return answer, saved

    def test_geo_goes_straight_to_its_check(self):
        answer, saved = self.send("g.csv", s.geo_tables_file())
        self.assertEqual((answer.status_code, answer.headers["Location"], saved), (302, "/uploads/geo/review", ["geo"]))

    def test_zone_history_goes_straight_to_its_check(self):
        answer, saved = self.send("z.csv", s.zone_history_file([("9/6/2026", "Frankfurt", 5, 4)]))
        self.assertEqual((answer.headers["Location"], saved), ("/uploads/zone-history/review", ["zone-history"]))

    def test_look_alike_is_asked_and_nothing_is_kept(self):
        answer, saved = self.send("v.xlsx", s.vollzogen_sheet())
        self.assertEqual((answer.status_code, saved), (400, []))
        self.assertIn(b"could be more than one kind", answer.data)

    def test_chosen_kind_is_used(self):
        answer, saved = self.send("v.xlsx", s.vollzogen_sheet(), "vollzogen")
        self.assertEqual((answer.headers["Location"], saved), ("/uploads/vollzogen/review", ["vollzogen"]))

    def test_unknown_file_is_refused(self):
        answer, saved = self.send("x.csv", s.csv_bytes(["Foo"], [["1"]]))
        self.assertEqual((answer.status_code, saved), (400, []))

    def test_old_addresses_lead_to_uploads(self):
        client = app.app.test_client()
        with patch("sign_in.allowed", return_value=True):
            for address in ("/", "/historical", "/people-upload", "/uploads/vollzogen", "/uploads/areas"):
                self.assertEqual(client.get(address).headers["Location"], "/uploads", address)


if __name__ == "__main__":
    unittest.main()
