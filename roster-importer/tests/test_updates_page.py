"""DA Management > Updates (updates_page.py), without a database and without the updater.

Checks: only managers signed in through the portal (AP, President, Data Analyst) may use the page; "Check for
updates" and "Update now" only write the request file (no shell, no program is started); "Update now" needs the typed
confirmation and the version that was shown; the page shows the status file (commit titles escaped); every text is in
the portal catalog with the same English.

Run in DA Management's image (it has Flask), from roster-importer/:
  docker run --rm --network none -v <repo>:/repo -w /repo/roster-importer
    -e DATABASE_URL=postgresql://nobody@127.0.0.1:1/none roster-importer-roster-importer
    python -m unittest tests.test_updates_page
"""
import json
import os
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "postgresql://nobody@127.0.0.1:1/none")  # never opened by these tests
import app  # noqa: E402
import sign_in  # noqa: E402
import updates_page  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
SHOWN = "a" * 40
USER = "11111111-2222-3333-4444-555555555555"


def portal_catalog():
    """{language: {key: text}}: today one catalogs.json with every language; after the translation round (r6/i18n)
    catalogs.json lists the languages and each has its own <language>.json."""
    folder = REPO / "portal" / "i18n"
    index = json.loads((folder / "catalogs.json").read_text(encoding="utf-8"))
    if "messages" in index:
        return index["messages"]
    return {code: json.loads((folder / f"{code}.json").read_text(encoding="utf-8")) for code in index["languages"]}


def moment(minutes_ago=0):
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).astimezone().isoformat(timespec="seconds")


def status(**changes):
    """A status file like the updater writes it: one new change waiting, the updater seen just now."""
    base = {
        "schema": 1, "state": "idle", "step": "", "updater_seen_at": moment(), "follows": "origin/main",
        "current": {"commit": "b" * 40, "short": "bbbbbbb", "date": "2026-09-28T10:00:00+02:00",
                    "subject": "The version on this computer", "branch": "feat/native-mission-dashboard"},
        "remote": {"commit": SHOWN, "short": "aaaaaaa", "date": "2026-09-29T09:00:00+02:00", "subject": "New"},
        "checked_at": moment(), "checked_head": "b" * 40, "check_result": "updates", "blocked": "",
        "can_update": True, "migrations": ["portal-api/migrations/036_example.sql"], "other_parts": ["nightly-backup"],
        "new_changes": [{"commit": SHOWN, "short": "aaaaaaa", "date": "2026-09-29T09:00:00+02:00",
                         "subject": "Planning: <b>bold</b> & friends"}],
    }
    base.update(changes)
    return base


class UpdatesPageTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.dir = Path(self.folder.name)
        (self.dir / "requests").mkdir()
        (self.dir / "status").mkdir()
        self.signed_in_as_manager = True  # what sign_in.allowed answers (it asks the database in real life)
        self.patches = [patch.object(updates_page, "UPDATES_DIR", self.dir),
                        patch.object(sign_in, "allowed", side_effect=lambda: self.signed_in_as_manager)]
        for p in self.patches:
            p.start()
        self.client = app.app.test_client()
        self.write_status(status())

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.folder.cleanup()

    # Helpers ------------------------------------------------------------------------------------------------------
    def sign_in(self, role="AP"):
        with self.client.session_transaction() as s:
            s["csrf_token"] = "test-token"
            s["authenticated"] = True
            if role:
                s["portal_role"] = role
                s["portal_user_id"] = USER

    def write_status(self, data):
        (self.dir / "status" / "status.json").write_text(json.dumps(data), encoding="utf-8")

    def request_written(self):
        path = self.dir / "requests" / "request.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None

    def post(self, path, **form):
        return self.client.post(path, data={"csrf_token": "test-token", **form}, follow_redirects=True)

    def page(self):
        response = self.client.get("/updates")
        self.assertEqual(response.status_code, 200)
        return response.get_data(as_text=True)

    # Who may use it -----------------------------------------------------------------------------------------------
    def test_someone_not_signed_in_is_sent_to_sign_in_and_nothing_is_written(self):
        self.signed_in_as_manager = False
        self.sign_in("ZL")
        self.assertEqual(self.client.get("/updates").status_code, 302)
        for path in ("/updates/check", "/updates/install"):
            response = self.client.post(path, data={"csrf_token": "test-token", "confirm": "UPDATE", "target": SHOWN})
            self.assertEqual(response.status_code, 302)
            self.assertIn("/login", response.headers["Location"])
        self.assertIsNone(self.request_written())

    def test_a_leader_who_is_not_a_manager_is_refused(self):
        for role in ("ZL", "DL", "STL", "MISSIONARY", "OFFICE"):
            self.sign_in(role)
            self.assertEqual(self.client.get("/updates").status_code, 403)
            response = self.client.post("/updates/check", data={"csrf_token": "test-token"})
            self.assertEqual(response.status_code, 403)
        self.assertIsNone(self.request_written())

    def test_the_old_password_sign_in_cannot_update(self):
        self.sign_in(role=None)
        response = self.client.get("/updates")
        self.assertEqual(response.status_code, 403)
        self.assertIn(updates_page.TEXT["updates.managersOnly"], response.get_data(as_text=True))
        self.client.post("/updates/install", data={"csrf_token": "test-token", "confirm": "UPDATE", "target": SHOWN})
        self.assertIsNone(self.request_written())

    def test_each_manager_role_can_ask_for_a_check(self):
        for role in ("AP", "PRESIDENT", "DATA_ADMIN"):
            self.sign_in(role)
            self.post("/updates/check")
            self.assertEqual(self.request_written(), {"action": "check", "role": role, "user_id": USER})
            (self.dir / "requests" / "request.json").unlink()

    # The page -----------------------------------------------------------------------------------------------------
    def test_the_page_shows_the_version_and_what_is_new_escaped(self):
        self.sign_in()
        html = self.page()
        self.assertIn("bbbbbbb", html)
        self.assertIn("The version on this computer", html)
        self.assertIn("origin/main", html)
        self.assertIn("Planning: &lt;b&gt;bold&lt;/b&gt; &amp; friends", html)
        self.assertNotIn("<b>bold</b>", html)
        self.assertIn("036_example.sql", html)
        self.assertIn("nightly-backup", html)
        self.assertIn('data-i18n="updates.updateNow"', html)
        self.assertIn('<a href="/updates" data-i18n="updates.title">Updates</a>', html)  # the menu link

    def test_the_page_says_when_the_updater_has_not_run_or_is_not_running(self):
        self.sign_in()
        (self.dir / "status" / "status.json").unlink()
        self.assertIn(updates_page.TEXT["updates.neverRan"], self.page())
        self.write_status(status(updater_seen_at=moment(minutes_ago=30)))
        html = self.page()
        self.assertIn(updates_page.TEXT["updates.notRunning"], html)
        self.assertNotIn('data-i18n="updates.updateNow"', html)

    def test_a_waiting_request_does_not_reload_the_page_while_the_updater_is_not_running(self):
        self.sign_in()
        self.write_status(status(updater_seen_at=moment(minutes_ago=30)))
        self.post("/updates/check")
        self.assertEqual(self.request_written()["action"], "check")  # it waits for the updater
        html = self.page()
        self.assertIn(updates_page.TEXT["updates.notRunning"], html)
        self.assertNotIn(updates_page.TEXT["updates.asked"], html)
        self.assertNotIn("location.reload()", html)
        html = self.post("/updates/check").get_data(as_text=True)  # a second press says why nothing happens
        self.assertIn(updates_page.TEXT["updates.notRunning"], html)
        self.assertNotIn(updates_page.TEXT["updates.alreadyAsked"], html)

    def test_settings_that_need_a_look_are_named_and_nothing_is_offered(self):
        self.sign_in()
        self.write_status(status(settings_problem=True))
        html = self.page()
        self.assertIn('data-i18n="updates.settingsProblem"', html)
        self.assertNotIn(updates_page.TEXT["updates.notRunning"], html)
        self.assertNotIn('data-i18n="updates.updateNow"', html)
        self.write_status(status(settings_problem=False))
        self.assertNotIn('data-i18n="updates.settingsProblem"', self.page())

    def test_a_blocked_update_is_explained_and_not_offered(self):
        self.sign_in()
        self.write_status(status(check_result="local_ahead", blocked="local_ahead", can_update=False, new_changes=[]))
        html = self.page()
        self.assertIn(updates_page.TEXT["updates.blocked.local_ahead"], html)
        self.assertNotIn('data-i18n="updates.updateNow"', html)
        self.post("/updates/install", confirm="UPDATE", target=SHOWN)
        self.assertIsNone(self.request_written())

    def test_while_the_updater_works_the_page_refreshes_and_offers_no_update(self):
        self.sign_in()
        self.write_status(status(state="updating", step="services", updater_seen_at=moment(minutes_ago=20)))
        html = self.page()
        self.assertIn(updates_page.TEXT["updates.state.updating"], html)
        self.assertIn("location.reload()", html)  # after asking quietly whether the page answers
        self.assertNotIn(updates_page.TEXT["updates.notRunning"], html)  # a rebuild may take a while
        self.assertNotIn('data-i18n="updates.updateNow"', html)

    def test_the_last_update_is_shown(self):
        self.sign_in()
        last = {"result": "rolled_back", "reason": "", "from": "b" * 40, "to": SHOWN, "finished_at": moment(),
                "rollback_folder": "backups\\updater\\20260929-140500", "log": "updater\\logs\\updater-2026-09.log"}
        self.write_status(status(last_update=last))
        html = self.page()
        self.assertIn(updates_page.TEXT["updates.last.rolled_back"], html)
        self.assertIn("bbbbbbb → aaaaaaa", html)
        self.assertIn("updater-2026-09.log", html)
        self.write_status(status(last_update={"result": "refused", "reason": "changed_by_hand", "finished_at": moment()}))
        html = self.page()
        self.assertIn(updates_page.TEXT["updates.last.refused"], html)
        self.assertIn(updates_page.TEXT["updates.blocked.changed_by_hand"], html)

    # Update now ---------------------------------------------------------------------------------------------------
    def test_update_now_needs_the_typed_confirmation(self):
        self.sign_in()
        for typed in ("", "yes", "UPDATE NOW", "upd"):
            html = self.post("/updates/install", confirm=typed, target=SHOWN).get_data(as_text=True)
            self.assertIsNone(self.request_written())
        self.assertIn(updates_page.TEXT["updates.typeWrong"], html)

    def test_update_now_writes_one_request_for_the_version_shown(self):
        self.sign_in("DATA_ADMIN")
        html = self.post("/updates/install", confirm=" update ", target=SHOWN).get_data(as_text=True)
        self.assertEqual(self.request_written(), {"action": "update", "target": SHOWN, "confirmed": True,
                                                  "role": "DATA_ADMIN", "user_id": USER})
        self.assertIn(updates_page.TEXT["updates.asked"], html)
        # A second request waits for the first.
        self.post("/updates/check")
        self.assertEqual(self.request_written()["action"], "update")

    def test_update_now_refuses_another_version_than_the_one_shown(self):
        self.sign_in()
        for target in ("c" * 40, "HEAD", "a" * 39, SHOWN.upper(), f"{SHOWN}; rm -rf /"):
            self.post("/updates/install", confirm="UPDATE", target=target)
            self.assertIsNone(self.request_written(), target)

    def test_update_now_waits_when_the_updater_is_not_running(self):
        self.sign_in()
        self.write_status(status(updater_seen_at=moment(minutes_ago=30)))
        html = self.post("/updates/install", confirm="UPDATE", target=SHOWN).get_data(as_text=True)
        self.assertIsNone(self.request_written())
        self.assertIn(updates_page.TEXT["updates.notRunning"], html)

    # No shell -----------------------------------------------------------------------------------------------------
    def test_no_program_or_shell_is_ever_started(self):
        def refuse(*args, **kwargs):
            raise AssertionError("the Updates page started a program")
        self.sign_in()
        with patch.object(subprocess, "Popen", side_effect=refuse), patch.object(os, "system", side_effect=refuse), \
                patch.object(os, "popen", side_effect=refuse), patch.object(os, "execv", side_effect=refuse), \
                patch.object(os, "posix_spawn", side_effect=refuse, create=True):
            self.page()
            self.post("/updates/check")
            (self.dir / "requests" / "request.json").unlink()
            self.post("/updates/install", confirm="UPDATE", target=SHOWN)
        self.assertEqual(self.request_written()["action"], "update")
        source = Path(updates_page.__file__).read_text(encoding="utf-8")
        for word in ("subprocess", "os.system", "popen", "os.exec", "spawn", "shell=True"):
            self.assertNotIn(word, source)

    # Texts --------------------------------------------------------------------------------------------------------
    def test_every_text_is_in_the_portal_catalog_with_the_same_english(self):
        catalog = portal_catalog()
        for key, english in updates_page.TEXT.items():
            self.assertEqual(catalog["en"].get(key), english, key)
            for language, messages in catalog.items():
                self.assertTrue(messages.get(key), f"{language} {key}")

    def test_every_marked_text_on_the_page_has_a_text(self):
        self.sign_in()
        self.write_status(status(last_update={"result": "done", "reason": "", "finished_at": moment()}))
        html = self.page()
        import re
        keys = set(re.findall(r'data-i18n="([^"]+)"', html))
        self.assertTrue(keys)
        self.assertEqual(keys - set(updates_page.TEXT), set())


if __name__ == "__main__":
    unittest.main()
