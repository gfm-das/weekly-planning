"""The Wiki button of DA Management (wiki wiki_link.py, links_page.py, /wiki-link), without a database: only managers reach it (DA
Management itself is for managers), the address is a setting or worked out from the one DA Management was reached by, it opens in a
new tab, it is not in the portal's side menu, and every text is in the 14 catalogs. Run from roster-importer/:
  python -m unittest tests.test_wiki_card
"""
import json
import os
import re
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "postgresql://nobody@127.0.0.1:1/none")  # never opened by these tests
import app  # noqa: E402
import links_page  # noqa: E402
import page  # noqa: E402
import settings  # noqa: E402
import wiki_link  # noqa: E402
from links_text import TEXT, plain  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]


class AddressTests(unittest.TestCase):
    def test_worked_out_from_the_name_dam_was_reached_by_and_the_portals_port(self):
        self.assertEqual(wiki_link.wiki_address("office-pc:8090", "http", False, setting="", public_portal="", port="8070"),
                         ("http://office-pc:8070/wiki/", False))
        self.assertEqual(wiki_link.wiki_address("localhost", "http", False, setting="", public_portal="", port="9000"),
                         ("http://localhost:9000/wiki/", False))
        self.assertEqual(wiki_link.wiki_address("[::1]:8090", "http", False, setting="", public_portal="", port="8070"),
                         ("http://[::1]:8070/wiki/", False))

    def test_on_the_internet_name_it_is_the_public_portal(self):
        self.assertEqual(wiki_link.wiki_address("management.example.org", "https", True, setting="", public_portal="https://example.org", port="8070"),
                         ("https://example.org/wiki/", False))

    def test_the_setting_wins_off_hides_and_an_unsafe_address_is_not_shown(self):
        self.assertEqual(wiki_link.wiki_address("x", "http", True, setting="https://wiki.example.org/wiki/", public_portal="https://example.org"),
                         ("https://wiki.example.org/wiki/", False))
        self.assertEqual(wiki_link.wiki_address("x", "http", True, setting="OFF"), (None, True))
        for bad in ("javascript:alert(1)", "ftp://x.example/", "https://user:pw@x.example/", "https://x.example/?token=1",
                    "https://x.example/#a", "wiki.example.org", "https://x.example/ a", "https:///nohost"):
            self.assertEqual(wiki_link.wiki_address("x", "http", False, setting=bad), (None, False), bad)

    def test_no_address_is_written_in_the_program_files(self):
        for name in ("wiki_link.py", "links_page.py", "links_text.py"):
            text = (ROOT / "roster-importer" / name).read_text(encoding="utf-8")
            self.assertNotRegex(text, r"https?://[a-z0-9.-]+\.[a-z]{2,}", name)

    def test_the_settings_have_defaults_that_derive_the_address(self):
        self.assertEqual(settings.WEB_LINK_WIKI, "")
        self.assertEqual(settings.PORTAL_PORT, "8070")


class PageTests(unittest.TestCase):
    def test_a_stranger_is_sent_to_the_sign_in(self):
        self.assertEqual(app.app.test_client().get("/wiki-link").status_code, 302)

    def test_a_manager_sees_one_card_with_a_link_that_opens_in_a_new_tab(self):
        with patch.object(links_page.sign_in, "allowed", return_value=True):
            response = app.app.test_client().get("/wiki-link", base_url="http://office-pc:8090")
        html = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(">Wiki</h3>", html)
        self.assertIn("href='http://office-pc:8070/wiki/'", html)
        self.assertIn("Open the wiki", html)
        self.assertIn("target='_blank' rel='noopener noreferrer'", html)
        self.assertIn("It is not in the portal&#x27;s side menu.", html)
        self.assertNotRegex(html, r"<input[^>]*type=.password")

    def test_the_setting_off_removes_the_button_and_says_so(self):
        with patch.object(links_page.sign_in, "allowed", return_value=True), patch.object(settings, "WEB_LINK_WIKI", "off"):
            html = app.app.test_client().get("/wiki-link").get_data(as_text=True)
        self.assertNotIn("Open the wiki", html)

    def test_it_is_a_tab_entry_of_da_management_and_the_links_page_is_unchanged(self):
        self.assertNotIn(("/wiki-link", "Wiki"), page.MENU)  # round 14: Wiki is in the portal side menu
        self.assertEqual(page.current_page("/wiki-link"), ("history", "/imports"))
        with patch.object(links_page.sign_in, "allowed", return_value=True):
            html = app.app.test_client().get("/links").get_data(as_text=True)
        self.assertNotIn("Open the wiki", html)  # the Links to web services page still has its three cards

    def test_the_portals_side_menu_does_not_get_a_wiki_entry(self):
        """The wiki stays out of the side menu (owner's answer 6): the shell files list no wiki item."""
        for name in ("index.template.html", "portal-enhancements.js"):
            text = (ROOT / "portal" / name).read_text(encoding="utf-8")
            self.assertNotRegex(text, r"""href=["']/wiki""", name)
            self.assertNotRegex(text, r"""['"]/wiki/?['"]""", name)


class TextTests(unittest.TestCase):
    def test_the_wiki_texts_are_in_every_catalog_in_every_language(self):
        folder = ROOT / "portal" / "i18n"
        english = json.loads((folder / "en.json").read_text(encoding="utf-8"))
        keys = [k for k in TEXT if k.startswith("links.wiki.")]
        self.assertEqual(len(keys), 4)
        for code in json.loads((folder / "catalogs.json").read_text(encoding="utf-8"))["languages"]:
            catalog = json.loads((folder / f"{code}.json").read_text(encoding="utf-8"))
            for key in keys:
                self.assertTrue(str(catalog[key]).strip(), (code, key))
        self.assertEqual(english["links.wiki.open"], plain("links.wiki.open"))

    def test_the_wiki_page_of_management_mentions_the_button(self):
        text = (ROOT / "wiki" / "pages" / "management.md").read_text(encoding="utf-8")
        self.assertIn("DA Management", text)
        self.assertRegex(text, r"## Wiki button")
        built = (ROOT / "wiki" / "out-private" / "management.html")
        if built.exists():
            self.assertIn("Wiki button", built.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
