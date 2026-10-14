"""The grouped menu of DA Management (round 13): five tabs, every page in exactly one of them, every address as before.

No database. Run from roster-importer/:  python -m unittest tests.test_menu
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

ROOT = Path(__file__).resolve().parents[2]
# Not pages of the menu: the sign-in, the health check of the container, and Flask's own static files.
NOT_MENU = {"/login", "/logout", "/health"}
# The addresses that were in the menu before the grouping (round 13 start) and the ones added in round 13: all stay.
BEFORE = ["/", "/accounts", "/planning-questions", "/historical", "/mappings", "/places", "/staff", "/uploads",
          "/people-upload", "/imports", "/docs", "/links", "/updates"]
ROUND_13 = ["/uploads/geo", "/retire"]


def sample(rule):
    """A real-looking address for a Flask rule: <int:x> becomes 1, other parts get a word."""
    return re.sub(r"<(?:int:|uuid:)?[^>]+>", "1", rule)


class GroupTests(unittest.TestCase):
    def test_five_tabs_in_this_order(self):
        self.assertEqual([key for key, _tab, _pages in page.MENU_GROUPS], ["data", "people", "places", "accounts", "history"])
        self.assertEqual([tab for _key, tab, _pages in page.MENU_GROUPS], ["Data", "People", "Places", "Accounts", "History"])

    def test_every_old_page_and_the_round_13_pages_are_still_in_the_menu(self):
        addresses = [address for address, _text in page.MENU]
        for address in BEFORE + ROUND_13:
            self.assertIn(address, addresses)
        self.assertEqual(len(addresses), len(set(addresses)))  # each page once

    def test_the_flat_list_still_works_for_old_callers(self):
        self.assertIn(("/links", "Links to web services"), page.MENU)
        self.assertIn(("/retire", "Delete retired"), page.MENU)
        self.assertIn(("/uploads/geo", "Geo data"), page.MENU)

    def test_every_page_of_the_program_belongs_to_a_tab(self):
        """No route is left out: each page (GET) and each form target (POST) is found under some tab."""
        lost = []
        for rule in app.app.url_map.iter_rules():
            address = sample(rule.rule)
            if rule.endpoint == "static" or address in NOT_MENU:
                continue
            if page.current_page(address) == (None, None):
                lost.append(address)
        self.assertEqual(lost, [])

    def test_every_menu_address_is_a_real_page(self):
        client = app.app.test_client()
        for address, _text in page.MENU:
            self.assertNotEqual(client.get(address).status_code, 404, address)  # signed out: sent to the sign-in (302)

    def test_sub_pages_keep_their_own_tab_lit(self):
        expected = {
            "/": ("data", "/"), "/preview": ("data", "/"), "/apply": ("data", "/"),
            "/uploads/geo/table": ("data", "/uploads/geo"), "/uploads/geo/review": ("data", "/uploads/geo"),
            "/uploads/areas/table": ("data", "/uploads"), "/uploads/names": ("data", "/uploads"),
            "/planning-questions/questions/4": ("data", "/planning-questions"),
            "/people/decide": ("people", "/people-upload"), "/people-upload/review": ("people", "/people-upload"),
            "/accounts/12": ("people", "/accounts"),
            "/places/change": ("places", "/places"), "/mappings/save": ("places", "/mappings"),
            "/retire/place/area/3": ("places", "/retire"),
            "/staff/new": ("accounts", "/staff"), "/links": ("accounts", "/links"),
            "/imports/abc": ("history", "/imports"), "/updates/check": ("history", "/updates"), "/docs": ("history", "/docs"),
            "/login": (None, None),
        }
        for path, found in expected.items():
            self.assertEqual(page.current_page(path), found, path)


class HtmlTests(unittest.TestCase):
    def test_tabs_open_the_first_page_of_their_group(self):
        html = page.menu_html("/places")
        for _key, tab, pages in page.MENU_GROUPS:
            self.assertIn(f'<a href="{pages[0][0]}"', html)
            self.assertIn(f">{tab}</a>", html)

    def test_only_the_open_group_shows_its_pages_and_one_of_them_is_lit(self):
        html = page.menu_html("/retire/question/x")
        for text in ("Places", "Area mappings", "Delete retired"):
            self.assertIn(f">{text}</a>", html)
        for text in ("Roster Import", "Staff accounts", "Import history", "Links to web services"):
            self.assertNotIn(f">{text}</a>", html)
        self.assertEqual(html.count('aria-current="page"'), 2)  # the tab and the page
        self.assertIn('<a href="/retire" class="on" aria-current="page">Delete retired</a>', html)
        self.assertIn('<a href="/places" class="on" aria-current="page">Places</a>', html)  # the Places tab

    def test_a_page_outside_the_groups_shows_the_tabs_only(self):
        html = page.menu_html("/login")
        self.assertEqual(html.count("<nav"), 1)
        self.assertNotIn("aria-current", html)

    def test_a_rendered_page_carries_the_menu(self):
        with patch.object(links_page.sign_in, "allowed", return_value=True):
            html = app.app.test_client().get("/links").get_data(as_text=True)
        self.assertIn('<nav class="nav tabs"', html)
        self.assertIn('<nav class="nav sub"', html)
        self.assertIn('<a href="/links" class="on" aria-current="page">Links to web services</a>', html)
        self.assertIn(">Staff accounts</a>", html)
        self.assertNotIn(">Roster Import</a>", html)  # another group's pages are one tab away


class WordListTests(unittest.TestCase):
    def test_every_tab_and_page_text_is_in_every_language_catalog(self):
        folder = ROOT / "portal" / "i18n"
        english = json.loads((folder / "en.json").read_text(encoding="utf-8"))
        texts = [tab for _key, tab, _pages in page.MENU_GROUPS] + [text for _address, text in page.MENU]
        texts += ["Sections", "Pages in this section"]
        keys = [key for key, value in english.items() if isinstance(value, str) and value in texts]
        self.assertEqual(sorted(set(texts) - {english[key] for key in keys}), [])  # each text has a key
        for code in json.loads((folder / "catalogs.json").read_text(encoding="utf-8"))["languages"]:
            catalog = json.loads((folder / f"{code}.json").read_text(encoding="utf-8"))
            for key in keys:
                self.assertTrue(str(catalog.get(key, "")).strip(), (code, key))
        for key in ("dam.tab.accounts", "dam.tab.history", "dam.tab.deleteRetired", "dam.tab.sections", "dam.tab.pages"):
            self.assertIn(key, english)
            for code in json.loads((folder / "catalogs.json").read_text(encoding="utf-8"))["languages"]:
                if code != "en":
                    catalog = json.loads((folder / f"{code}.json").read_text(encoding="utf-8"))
                    if (code, key) != ("fr", "dam.tab.sections"):  # French uses the same word
                        self.assertNotEqual(catalog[key], english[key], (code, key))  # translated, not left in English


if __name__ == "__main__":
    unittest.main()
