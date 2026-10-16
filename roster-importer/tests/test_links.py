"""Links to web services (web_links.py, links_page.py) without a database: only managers see the page, the addresses are
settings, and nothing that looks like a credential is ever shown.

Run from roster-importer/:  python -m unittest tests.test_links
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
import web_links  # noqa: E402
from links_text import TEXT, plain, t  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]


class AddressTests(unittest.TestCase):
    def test_a_plain_https_address_is_fine(self):
        for good in ("https://app.brevo.com/", "https://dash.cloudflare.com/abc/home", "https://porkbun.com/account/login?lang=de"):
            self.assertEqual(web_links.safe_url(good), good)

    def test_anything_that_could_carry_a_credential_or_is_not_a_web_page_is_refused(self):
        for bad in ("", None, "app.brevo.com", "http://app.brevo.com/", "ftp://x.example/", "javascript:alert(1)",
                    "https://admin:pw@app.brevo.com/", "https://admin@app.brevo.com/", "https://app.brevo.com/?token=abc",
                    "https://app.brevo.com/?api_key=abc", "https://app.brevo.com/#access_token=abc",
                    "https://app.brevo.com/?password=x", "https://localhost/", "https://app.brevo.com/ x",
                    "https://" + "a" * 300 + ".com/"):
            self.assertIsNone(web_links.safe_url(bad), bad)

    def test_the_defaults_in_the_settings_are_public_sign_in_pages_without_secrets(self):
        self.assertEqual(sorted(settings.WEB_SERVICE_URLS), ["brevo", "cloudflare", "porkbun"])
        for key, url in settings.WEB_SERVICE_URLS.items():
            self.assertEqual(web_links.safe_url(url), url, key)

    def test_the_cards_follow_the_settings(self):
        shown = web_links.cards({"brevo": "https://mail.example.org/", "porkbun": "off", "cloudflare": "https://admin:pw@x.example/"})
        self.assertEqual([c["key"] for c in shown], ["brevo", "cloudflare"])  # porkbun is off: left out
        self.assertEqual(shown[0]["url"], "https://mail.example.org/")
        self.assertEqual(shown[0]["host"], "mail.example.org")
        self.assertIsNone(shown[1]["url"])  # an address with a password in it is not linked
        self.assertEqual([c["key"] for c in web_links.cards({})], ["brevo", "porkbun", "cloudflare"])

    def test_no_address_is_written_in_the_program_files_only_in_the_settings(self):
        for name in ("web_links.py", "links_page.py", "links_text.py"):
            text = (ROOT / "roster-importer" / name).read_text(encoding="utf-8")
            self.assertNotRegex(text, r"https?://[a-z0-9.-]+\.[a-z]{2,}", name)


class PageTests(unittest.TestCase):
    def test_a_stranger_is_sent_to_the_sign_in(self):
        self.assertEqual(app.app.test_client().get("/links").status_code, 302)

    def test_a_manager_sees_a_card_per_service_with_safe_links(self):
        with patch.object(links_page.sign_in, "allowed", return_value=True):
            response = app.app.test_client().get("/links")
        html = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        for name, host in (("Brevo", "app.brevo.com"), ("Porkbun", "porkbun.com"), ("Cloudflare", "dash.cloudflare.com")):
            self.assertIn(f">{name}</h3>", html)
            self.assertIn(host, html)
            self.assertIn(f"Open {name}", html)
        self.assertEqual(html.count('target="_blank"') + html.count("target='_blank'"), 3)
        self.assertEqual(html.count("noopener noreferrer"), 3)
        self.assertNotRegex(html, r"<input[^>]*type=.password")  # no place to type a password
        self.assertIn("No password or key is kept here", html)

    def test_the_brevo_card_opens_the_smtp_keys_page(self):
        self.assertEqual(settings.WEB_SERVICE_URLS["brevo"], "https://app.brevo.com/settings/keys/smtp")
        self.assertTrue(web_links.safe_url(settings.WEB_SERVICE_URLS["brevo"]))

    def test_a_card_without_a_safe_address_says_so(self):
        with patch.object(links_page.sign_in, "allowed", return_value=True), \
                patch.dict(settings.WEB_SERVICE_URLS, {"brevo": "http://insecure.example/", "porkbun": "off"}):
            html = app.app.test_client().get("/links").get_data(as_text=True)
        self.assertIn("Not shown: the address in the settings", html)
        self.assertNotIn("insecure.example", html)
        self.assertNotIn("Porkbun", html)

    def test_the_menu_has_the_tab(self):
        self.assertIn(("/links", "Links to web services"), page.MENU)


class TextTests(unittest.TestCase):
    def test_every_text_is_in_the_portal_catalog_in_every_language(self):
        folder = ROOT / "portal" / "i18n"
        english = json.loads((folder / "en.json").read_text(encoding="utf-8"))
        texts = {value for value in english.values() if isinstance(value, str)}
        self.assertEqual(sorted(key for key, value in TEXT.items() if value not in texts), [])
        for code in json.loads((folder / "catalogs.json").read_text(encoding="utf-8"))["languages"]:
            catalog = json.loads((folder / f"{code}.json").read_text(encoding="utf-8"))
            for key in TEXT:
                self.assertTrue(str(catalog[key]).strip(), (code, key))
                self.assertEqual(sorted(re.findall(r"\{(\w+)\}", catalog[key])), sorted(re.findall(r"\{(\w+)\}", TEXT[key])), (code, key))

    def test_the_helpers_fill_and_escape(self):
        self.assertEqual(plain("links.open", name="Brevo"), "Open Brevo")
        self.assertEqual(t("links.open", name="<b>"), "Open &lt;b&gt;")


if __name__ == "__main__":
    unittest.main()
