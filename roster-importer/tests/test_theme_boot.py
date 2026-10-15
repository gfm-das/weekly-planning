"""The page's theme is known on the server, so the first byte has the right colour (no light flash in dark mode)."""
import unittest

from flask import Flask

import page


class ThemeBoot(unittest.TestCase):
    def theme(self, query="", cookie=None):
        app = Flask(__name__)
        headers = {"Cookie": f"gfm_theme={cookie}"} if cookie else {}
        with app.test_request_context("/" + query, headers=headers):
            return page.page_theme()

    def test_default_is_mission(self):
        self.assertEqual(self.theme(), "mission")

    def test_cookie_and_address(self):
        self.assertEqual(self.theme(cookie="dark"), "dark")
        self.assertEqual(self.theme("?theme=light", cookie="dark"), "light")

    def test_unknown_value_is_ignored(self):
        self.assertEqual(self.theme("?theme=<x>"), "mission")

    def test_frame_and_style_carry_the_theme(self):
        self.assertIn('data-theme="{{ page_theme }}"', page.FRAME)
        self.assertIn('[data-theme="dark"]{color-scheme:dark;background:#101a21}', page.STYLE)


if __name__ == "__main__":
    unittest.main()
