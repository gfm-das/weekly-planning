"""Round 16: the styled file picker shows the chosen file's name (no database)."""
import inspect
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("DATABASE_URL", "postgresql://nobody@127.0.0.1:1/none")

import app  # noqa: E402
import data_upload_pages  # noqa: E402
import data_text  # noqa: E402
import page  # noqa: E402


class FilePick(unittest.TestCase):
    def test_the_picker_has_a_name_element_with_the_empty_text(self):
        source = inspect.getsource(data_upload_pages)
        self.assertIn('class="name" data-empty=', source)
        self.assertIn("uploads.page.noneChosen", source)
        self.assertEqual(data_text.TEXT["uploads.page.noneChosen"], "No file chosen")

    def test_every_page_carries_the_script_and_the_styles(self):
        with app.app.test_request_context("/"):
            html, _ = page.render('<label class="file-pick"><span class="name" data-empty="No file chosen">No file chosen</span><input type="file"></label>')
        for needle in ('.file-pick', 'querySelectorAll(".file-pick")', "dragover", "drop", "input.files=files", "has-file", "f.name"):
            self.assertIn(needle, html)

    def test_the_hidden_native_input_is_still_clickable(self):
        self.assertIn(".file-pick input[type=file]{position:absolute;inset:0;opacity:0", page.STYLE)


if __name__ == "__main__":
    unittest.main()
