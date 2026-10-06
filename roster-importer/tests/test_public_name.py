"""Round 10 (docs/handoff/round10/public-everything.md): DA Management on its public name
https://management.example.org (a Cloudflare tunnel route to port 8090), without a database.

Checks: on the public name the session cookie is Secure, only the portal may frame the pages, the translations come
from the public portal, and the old shared password is refused (page and session); the office address answers as
before (no Secure, no frame rule, the shared password still works there).

Run in DA Management's image (it has Flask), from roster-importer/:
  docker run --rm --network none -v <repo>:/repo -w /repo/roster-importer
    -e DATABASE_URL=postgresql://nobody@127.0.0.1:1/none roster-importer-roster-importer
    python -m unittest tests.test_public_name
"""
import os
import re
import unittest
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "postgresql://nobody@127.0.0.1:1/none")  # never opened by these tests
import app  # noqa: E402
import settings  # noqa: E402
import sign_in  # noqa: E402

PUBLIC = "management.example.org"
OFFICE = "192.168.1.20:8090"


class PublicNameTests(unittest.TestCase):
    def setUp(self):
        app.app.config["TESTING"] = True
        self.password = patch.object(settings, "IMPORTER_PASSWORD", "office-test-password")
        self.password.start()
        self.addCleanup(self.password.stop)
        # The public names come from the setting GFM_PUBLIC_DOMAIN, read when the program starts. These checks use one domain whatever
        # was imported first (another test module may have loaded settings already).
        domain = "example.org"
        for name, value in (("PUBLIC_DOMAIN", domain), ("PUBLIC_NAME", "management." + domain), ("PUBLIC_PORTAL", "https://" + domain),
                            ("PUBLIC_PORTAL_ORIGINS", ["https://" + domain, "https://www." + domain])):
            patcher = patch.object(settings, name, value, create=True)
            patcher.start()
            self.addCleanup(patcher.stop)

    def client(self):
        return app.app.test_client()

    def login(self, host):
        """The password form as a person sends it: the page first (its form token), then the password."""
        client = self.client()
        form = client.get("/login", headers={"Host": host}).get_data(as_text=True)
        token = re.search(r'name="csrf_token" value="([^"]+)"', form)
        answer = client.post("/login", data={"password": "office-test-password", "csrf_token": token.group(1) if token else ""},
                             headers={"Host": host})
        return client, answer

    def test_the_names(self):
        self.assertEqual(settings.PUBLIC_NAME, PUBLIC)
        self.assertEqual(settings.PUBLIC_PORTAL, "https://example.org")
        self.assertEqual(settings.PUBLIC_PORTAL_ORIGINS, ["https://example.org", "https://www.example.org"])

    def test_public_name_refuses_the_shared_password(self):
        page = self.client().get("/login", headers={"Host": PUBLIC})
        self.assertEqual(page.status_code, 403)
        self.assertIn(b"Sign in through Mission System", page.data)
        self.assertNotIn(b'type="password"', page.data)
        client, answer = self.login(PUBLIC)
        self.assertEqual(answer.status_code, 403)
        with client.session_transaction(base_url="https://" + PUBLIC) as saved:
            self.assertFalse(saved.get("authenticated"))
        # A look-alike name is not the public name (it is not routed here anyway).
        for host in ("management.example.org.evil.example", "xmanagement.example.org"):
            with app.app.test_request_context("/", headers={"Host": host}):
                self.assertFalse(sign_in.on_public_name(), host)

    def test_office_address_keeps_the_shared_password(self):
        client, answer = self.login(OFFICE)
        self.assertEqual(answer.status_code, 302)
        cookie = answer.headers.get("Set-Cookie", "")
        self.assertTrue(cookie.startswith("gfm_roster_session="))
        self.assertNotIn("Secure", cookie)
        self.assertNotIn("Domain", cookie)
        self.assertIsNone(answer.headers.get("Content-Security-Policy"))
        with client.session_transaction(base_url="http://" + OFFICE) as saved:
            self.assertTrue(saved.get("authenticated"))
        # That office session is not accepted on the public name (the cookie would not be sent there; even if it were).
        with app.app.test_request_context("/", headers={"Host": PUBLIC}):
            from flask import session
            session["authenticated"] = True
            self.assertFalse(sign_in.allowed())
        with app.app.test_request_context("/", headers={"Host": OFFICE}):
            from flask import session
            session["authenticated"] = True
            self.assertTrue(sign_in.allowed())

    def test_public_name_cookie_is_secure_and_pages_are_framed_by_the_portal_only(self):
        client = self.client()
        with patch.object(sign_in, "portal_context", return_value={
                "app_role": "MISSIONARY", "leadership_role": "AP", "additional_roles": [], "user_active": True,
                "display_name": "Test AP", "user_id": "11111111-2222-3333-4444-555555555555", "mission_id": 2}):
            answer = client.get("/health?portal_token=made-up", headers={"Host": PUBLIC})
        self.assertEqual(answer.status_code, 302)
        self.assertEqual(answer.headers["Location"], "/health", "the token leaves the address at once (a relative address)")
        cookie = answer.headers.get("Set-Cookie", "")
        self.assertTrue(cookie.startswith("gfm_roster_session="))
        self.assertIn("Secure", cookie)
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=Lax", cookie)
        self.assertNotIn("Domain", cookie)
        csp = answer.headers.get("Content-Security-Policy")
        self.assertEqual(csp, "frame-ancestors 'self' https://example.org https://www.example.org")
        self.assertEqual(answer.headers.get("Cache-Control"), "no-store")
        office = client.get("/health", headers={"Host": OFFICE})
        self.assertEqual(office.headers.get("Content-Security-Policy"), None)
        self.assertEqual(office.headers.get("Cache-Control"), None)

    def test_translations_come_from_the_public_portal(self):
        with patch.object(settings, "PORTAL_I18N_SRC", ""):
            public = self.client().get("/login", headers={"Host": PUBLIC}).get_data(as_text=True)
            office = self.client().get("/login", headers={"Host": OFFICE}).get_data(as_text=True)
        self.assertIn('s.src="https://example.org/i18n.js?v=6"||', public)
        self.assertIn('s.src=""||location.protocol+"//"+location.hostname+":8070/i18n.js"', office)


if __name__ == "__main__":
    unittest.main()
