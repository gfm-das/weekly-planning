"""Uploads that wait between their check and Apply (v1.0.23). v1.0.22: "Nothing was committed. [Errno 2] No such file or
directory: /tmp/roster-importer/<id>.csv". The second of two Apply clicks waited for the first (the mission lock), which
imported the file and removed it; and /tmp inside the container was also lost at every restart or update. Now the files
wait on a Docker volume, old ones are tidied away, and a missing one gets a plain sentence with links. No database."""
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("DATABASE_URL", "postgresql://nobody@127.0.0.1:1/none")

import app  # noqa: E402
import data_uploads  # noqa: E402
import settings  # noqa: E402

HERE = Path(__file__).resolve().parent.parent


class WaitingUploads(unittest.TestCase):
    def client(self, **values):
        client = app.app.test_client()
        with client.session_transaction() as session:
            session["csrf_token"] = "t"
            session.update(values)
        return client

    def test_the_folder_is_a_volume_not_tmp(self):
        compose = (HERE / "docker-compose.yml").read_text(encoding="utf-8")
        self.assertIn("UPLOAD_DIR: /data/uploads", compose)
        self.assertIn("- importer-uploads:/data/uploads", compose)
        self.assertRegex(compose, r"\nvolumes:\n  importer-uploads:\n")
        self.assertIn('os.environ.get("UPLOAD_DIR", "/data/uploads")', (HERE / "settings.py").read_text(encoding="utf-8"))

    def test_historical_apply_of_a_gone_upload_says_so(self):
        client = self.client(historical_file="/nowhere/002ea9c7.csv", historical_filename="h.csv")
        with patch("sign_in.allowed", return_value=True):
            answer = client.post("/historical/apply", data={"csrf_token": "t", "confirmed": "yes", "state_token": "x", "choices": "{}"})
        text = answer.get_data(as_text=True)
        self.assertEqual(answer.status_code, 410)
        self.assertIn(settings.UPLOAD_GONE, text)
        self.assertIn("href='/uploads'", text)
        self.assertNotIn("Errno", text)

    def test_second_apply_that_finds_the_file_removed_says_so(self):
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
            path = f.name
        client = self.client(historical_file=path, historical_filename="h.csv")
        with patch("sign_in.allowed", return_value=True), \
                patch("historical_apply.apply_batch", side_effect=FileNotFoundError(2, "No such file or directory")):
            answer = client.post("/historical/apply", data={"csrf_token": "t", "confirmed": "yes", "state_token": "x", "choices": "{}"})
        os.unlink(path)
        self.assertEqual(answer.status_code, 410)
        self.assertIn(settings.UPLOAD_GONE, answer.get_data(as_text=True))

    def test_roster_apply_of_a_gone_upload_says_so(self):
        client = self.client(pending_file="/nowhere/r.csv", pending_mission_id=2, pending_transfer_date="2026-10-20", pending_filename="r.csv")
        with patch("sign_in.allowed", return_value=True):
            answer = client.post("/apply", data={"csrf_token": "t", "confirmed": "yes"})
        self.assertEqual(answer.status_code, 410)
        self.assertIn(settings.UPLOAD_GONE, answer.get_data(as_text=True))

    def test_old_waiting_files_of_every_kind_are_tidied(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(settings, "UPLOAD_DIR", Path(folder)):
            old, new = Path(folder, "old.csv"), Path(folder, "data-new.json")
            old.write_text("x"), new.write_text("{}")
            os.utime(old, (time.time() - 30 * 3600,) * 2)
            data_uploads.clear_old_pending()
            self.assertEqual((old.exists(), new.exists()), (False, True))

    def test_a_post_form_is_sent_once(self):
        text = (HERE / "page.py").read_text(encoding="utf-8")
        self.assertIn('f.dataset.sent)e.preventDefault()},true)', text)  # capture: a second send is ignored

    def test_a_cancelled_or_script_sent_form_can_still_be_sent(self):
        # v1.0.23 marked a form sent in the capture phase, before its own handlers ran: a confirm() answered Cancel
        # (account page) left the form dead. It is marked only after them, and only when they let it go.
        text = (HERE / "page.py").read_text(encoding="utf-8")
        self.assertIn('window.addEventListener("submit",function(e){var f=e.target;if(f&&!e.defaultPrevented', text)
        self.assertNotIn('f.dataset.sent="1"},true)', text)


if __name__ == "__main__":
    unittest.main()
