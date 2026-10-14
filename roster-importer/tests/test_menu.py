"""The grouped menu of DA Management (round 14): four tabs. Uploads is one hub; DA Docs and Wiki tabs are gone
(the portal side menu opens the wiki). Old addresses still light the right tab.

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
NOT_MENU = {"/login", "/logout", "/health"}


def sample(rule):
    """A real-looking address for a Flask rule: <int:x> becomes 1, other parts get a word."""
    return re.sub(r"<(?:int:|uuid:)?[^>]+>", "1", rule)


class GroupTests(unittest.TestCase):
    def test_four_tabs_in_this_order(self):
        self.assertEqual([key for key, _tab, _pages in page.MENU_GROUPS],
                         ["uploads", "people", "places", "history"])
        self.assertEqual([tab for _key, tab, _pages in page.MENU_GROUPS],
                         ["Uploads", "People", "Places", "History"])

    def test_the_flat_list_has_the_visible_pages(self):
        addresses = [address for address, _text in page.MENU]
        for address in ["/uploads", "/accounts", "/staff", "/abilities", "/links", "/places", "/mappings",
                        "/planning-questions", "/retire", "/imports", "/updates"]:
            self.assertIn(address, addresses)
        self.assertNotIn("/docs", addresses)
        self.assertNotIn("/wiki-link", addresses)
        self.assertEqual(len(addresses), len(set(addresses)))

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
            self.assertNotEqual(client.get(address).status_code, 404, address)

    def test_sub_pages_keep_their_own_tab_lit(self):
        expected = {
            "/": ("uploads", "/uploads"), "/preview": ("uploads", "/uploads"), "/apply": ("uploads", "/uploads"),
            "/uploads/geo/table": ("uploads", "/uploads"), "/uploads/geo/review": ("uploads", "/uploads"),
            "/uploads/areas/table": ("uploads", "/uploads"), "/uploads/names": ("uploads", "/uploads"),
            "/historical": ("uploads", "/uploads"), "/people-upload": ("uploads", "/uploads"),
            "/people/decide": ("uploads", "/uploads"), "/uploads/vollzogen": ("uploads", "/uploads"),
            "/planning-questions/questions/4": ("places", "/planning-questions"),
            "/accounts/12": ("people", "/accounts"),
            "/places/change": ("places", "/places"), "/mappings/save": ("places", "/mappings"),
            "/retire/place/area/3": ("places", "/retire"),
            "/staff/new": ("people", "/staff"), "/links": ("people", "/links"), "/abilities": ("people", "/abilities"),
            "/imports/abc": ("history", "/imports"), "/updates/check": ("history", "/updates"),
            "/docs": ("history", "/imports"), "/wiki-link": ("history", "/imports"),
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
        for text in ("Places", "Area mappings", "Delete retired", "Planning questions"):
            self.assertIn(f">{text}</a>", html)
        for text in ("Uploads", "Account Manager", "Import history"):
            # tab names still appear in the top tabs row
            pass
        self.assertEqual(html.count('aria-current="page"'), 2)
        self.assertIn('<a href="/retire" class="on" aria-current="page">Delete retired</a>', html)
        self.assertIn('<a href="/places" class="on" aria-current="page">Places</a>', html)

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
        self.assertNotIn(">Delete retired</a>", html)


class WordListTests(unittest.TestCase):
    def test_every_tab_and_page_text_is_in_every_language_catalog(self):
        folder = ROOT / "portal" / "i18n"
        english = json.loads((folder / "en.json").read_text(encoding="utf-8"))
        texts = [tab for _key, tab, _pages in page.MENU_GROUPS] + [text for _address, text in page.MENU]
        texts += ["Sections", "Pages in this section"]
        keys = [key for key, value in english.items() if isinstance(value, str) and value in texts]
        self.assertEqual(sorted(set(texts) - {english[key] for key in keys}), [])
        for code in json.loads((folder / "catalogs.json").read_text(encoding="utf-8"))["languages"]:
            catalog = json.loads((folder / f"{code}.json").read_text(encoding="utf-8"))
            for key in keys:
                self.assertTrue(str(catalog.get(key, "")).strip(), (code, key))
        for key in ("dam.tab.uploads", "dam.tab.history", "dam.tab.deleteRetired", "dam.tab.sections", "dam.tab.pages"):
            self.assertIn(key, english)
