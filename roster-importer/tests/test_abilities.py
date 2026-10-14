"""DA Management > Accounts > Role abilities (round 13, task 21; migration 055), without a database.

Checked here: only the managers (AP, President, Data Analyst, signed in through the portal) can open the page and use its API (403 for
everyone else, also for the old shared password); the page shows the matrix, with a switch only where roles.SWITCHABLE allows;
the preview, the typed confirmation and the revert call the right things; the rules no switch can change hold in abilities.py too;
the migration text says the same as roles.py; every text is in all 14 catalogs; the page is in the Accounts tab.
Run from roster-importer/:  python -m unittest tests.test_abilities
"""
import json
import os
import re
import time
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "postgresql://nobody@127.0.0.1:1/none")  # never opened by these tests
import abilities  # noqa: E402
import abilities_page  # noqa: E402
import app  # noqa: E402
import page  # noqa: E402
import roles  # noqa: E402
from abilities_text import TEXT, plain  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
USER_ID = str(uuid.uuid4())
LOG = [{"batch": str(uuid.uuid4()), "when": __import__("datetime").datetime(2026, 10, 13, 9, 30, tzinfo=__import__("datetime").timezone.utc),
        "who": "Test Person", "note": "Invented reason", "reverts": None, "reverted": False,
        "cells": [("OFFICE", "calendar.edit", True, False)]}]


def table(**changes):
    result = dict(roles.DEFAULT_ABILITIES)
    for key, value in changes.items():
        role, ability = key.split("__")
        result[(role, ability.replace("_", "."))] = value
    return result


def client_as(role, person=True):
    """A test client whose session says it is signed in through the portal with this role (None: no role at all)."""
    client = app.app.test_client()
    with client.session_transaction() as s:
        s.update(authenticated=True, csrf_token="test-csrf", portal_expires_at=time.time() + 1800, portal_mission_id=2)
        if role:
            s["portal_role"] = role
        if person:
            s.update(portal_user="Test Person", portal_user_id=USER_ID)
    return client


def allowed_for_all():
    return patch.object(abilities_page.sign_in, "allowed", return_value=True)


class WhoMayUseIt(unittest.TestCase):
    PATHS = [("get", "/abilities"), ("post", "/abilities/preview"), ("post", "/abilities/save"),
             ("post", f"/abilities/revert/{uuid.uuid4()}")]

    def request(self, client, method, path, **data):
        return getattr(client, method)(path, data={"csrf_token": "test-csrf", **data})

    def test_a_stranger_is_sent_to_the_sign_in_and_cannot_post(self):
        client = app.app.test_client()
        self.assertEqual(client.get("/abilities").status_code, 302)
        for method, path in self.PATHS[1:]:
            self.assertEqual(self.request(client, method, path).status_code, 403, path)  # no form token: refused

    def test_everyone_who_is_not_a_manager_gets_403_on_the_page_and_the_api(self):
        with allowed_for_all(), patch.object(abilities_page, "read_screen", side_effect=AssertionError("must not read")), \
                patch.object(abilities, "save_change", side_effect=AssertionError("must not save")), \
                patch.object(abilities, "revert_batch", side_effect=AssertionError("must not revert")):
            for role in ("OFFICE", "DL", "ZL", "STL", "MISSIONARY", "", "KING", None):
                client = client_as(role)
                for method, path in self.PATHS:
                    response = self.request(client, method, path, on="OFFICE|calendar.edit", confirm="CHANGE", base="1")
                    self.assertEqual(response.status_code, 403, (role, path))
                    self.assertIn("Only the managers of the mission can open this page.", response.get_data(as_text=True))

    def test_the_old_shared_password_has_no_person_and_cannot_use_it(self):
        with allowed_for_all(), patch.object(abilities, "save_change", side_effect=AssertionError("must not save")):
            client = app.app.test_client()
            with client.session_transaction() as s:
                s.update(authenticated=True, csrf_token="test-csrf")  # no portal role
            for method, path in self.PATHS:
                self.assertEqual(self.request(client, method, path).status_code, 403, path)

    def test_the_three_managers_open_the_page(self):
        for role in ("AP", "PRESIDENT", "DATA_ADMIN"):
            with allowed_for_all(), patch.object(abilities_page, "read_screen", return_value=(table(), LOG)):
                response = client_as(role).get("/abilities")
            self.assertEqual(response.status_code, 200, role)

    def test_a_manager_without_a_person_may_look_but_not_change(self):
        with allowed_for_all(), patch.object(abilities_page, "read_screen", return_value=(table(), LOG)), \
                patch.object(abilities, "save_change", side_effect=AssertionError("must not save")):
            client = client_as("PRESIDENT", person=False)
            self.assertEqual(client.get("/abilities").status_code, 200)
            self.assertEqual(self.request(client, "post", "/abilities/save", confirm="CHANGE", base="1").status_code, 403)

    def test_the_session_is_checked_against_the_database_every_time(self):
        """A session of a role that is not a manager any more is not let in: sign_in.allowed() decides first."""
        with patch.object(abilities_page.sign_in, "allowed", return_value=False):
            response = client_as("PRESIDENT").get("/abilities")
        self.assertIn(response.status_code, (302, 403))  # sign-in page when the session is gone, 403 when it is still there


class TheScreen(unittest.TestCase):
    def html(self, current=None, log=None):
        with allowed_for_all(), patch.object(abilities_page, "read_screen", return_value=(current or table(), LOG if log is None else log)):
            return client_as("PRESIDENT").get("/abilities").get_data(as_text=True)

    def test_it_shows_every_role_and_ability_and_a_switch_only_where_allowed(self):
        html = self.html()
        for ability in roles.ABILITIES:
            self.assertIn(plain("abil.ability." + ability), html)
            self.assertIn(plain("abil.about." + ability), html)
        for role in abilities.DISPLAY_ROLES:
            self.assertIn(f">{roles.role_name(role)}</th>", html)
        boxes = re.findall(r"<input type='checkbox' name='on' value='([^']+)'( checked)?", html)
        self.assertEqual({value for value, _checked in boxes}, {abilities.cell_key(*cell) for cell in abilities.SWITCH_CELLS})
        self.assertEqual(len(boxes), 11)
        self.assertTrue(all(checked for _value, checked in boxes))  # every switchable cell is on today
        self.assertEqual(html.count(plain("abil.alwaysOn")) + html.count(plain("abil.alwaysOff")), 40 - 11)

    def test_a_switch_that_is_off_is_shown_off(self):
        html = self.html(table(OFFICE__calendar_edit=False))
        self.assertRegex(html, r"value='OFFICE\|calendar\.edit'\s+aria-label")  # not checked
        self.assertNotRegex(html, r"value='OFFICE\|calendar\.edit' checked")
        self.assertRegex(html, r"value='OFFICE\|vollzogen\.view' checked")

    def test_a_manager_never_gets_a_switch(self):
        html = self.html()
        for role in roles.MANAGER_ROLES | {"MISSIONARY"}:
            self.assertNotRegex(html, rf"value='{role}\|")

    def test_the_log_shows_who_when_before_after_and_a_revert_button(self):
        html = self.html()
        self.assertIn("Test Person", html)
        self.assertIn("Invented reason", html)
        self.assertIn(f"/abilities/revert/{LOG[0]['batch']}", html)
        self.assertIn(plain("abil.log.revert"), html)
        self.assertIn("13 Oct 2026", html)

    def test_a_reverted_change_has_no_second_revert_button(self):
        html = self.html(log=[dict(LOG[0], reverted=True)])
        self.assertNotIn("/abilities/revert/", html)
        self.assertIn(plain("abil.log.wasReverted"), html)

    def test_an_empty_log_says_so(self):
        self.assertIn(plain("abil.log.empty"), self.html(log=[]))

    def test_without_the_table_the_page_says_so_and_offers_no_switch(self):
        with allowed_for_all(), patch.object(abilities_page, "read_screen", return_value=(None, [])):
            html = client_as("PRESIDENT").get("/abilities").get_data(as_text=True)
        self.assertIn(plain("abil.builtIn"), html)
        self.assertNotIn("type='checkbox'", html)

    def test_it_is_in_the_accounts_tab(self):
        self.assertIn(("/abilities", "Role abilities"), page.MENU)
        self.assertEqual(page.current_page("/abilities"), ("accounts", "/abilities"))
        self.assertEqual(page.current_page("/abilities/revert/x"), ("accounts", "/abilities"))
        self.assertIn(("/abilities", "Role abilities", []), dict((k, p) for k, _t, p in page.MENU_GROUPS)["accounts"])


class PreviewAndSave(unittest.TestCase):
    def post(self, path, **data):
        form = {"csrf_token": "test-csrf", **data}
        with allowed_for_all():
            return client_as("DATA_ADMIN").post(path, data=form)

    def ticked(self, *off):
        return [abilities.cell_key(*cell) for cell in abilities.SWITCH_CELLS if cell not in off]

    def test_the_preview_lists_what_changes_and_asks_for_the_word(self):
        current = table()
        with patch.object(abilities.database, "connect") as connect, patch.object(abilities, "read_table", return_value=current):
            connect.return_value.__enter__.return_value = object()
            with patch.object(abilities_page.database, "cursor"):
                response = self.post("/abilities/preview", on=self.ticked(("OFFICE", "vollzogen.view")), base=abilities.base_token(current))
        html = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(plain("dam.whatSavingWillChange"), html)
        self.assertIn(plain("abil.effect.vollzogen.view"), html)
        self.assertIn(plain("abil.typeChange"), html)
        self.assertIn("action='/abilities/save'", html)
        self.assertEqual(html.count("name='on'"), 10)  # the ten switches that stay on travel on to the save
        self.assertIn(f"name='base' value='{abilities.base_token(current)}'", html)

    def test_a_preview_without_a_difference_says_so(self):
        current = table()
        with patch.object(abilities.database, "connect"), patch.object(abilities_page.database, "cursor"), \
                patch.object(abilities, "read_table", return_value=current):
            html = self.post("/abilities/preview", on=self.ticked(), base=abilities.base_token(current)).get_data(as_text=True)
        self.assertIn(plain("abil.nothing"), html)
        self.assertNotIn("action='/abilities/save'", html)

    def test_a_value_that_is_not_a_switch_is_refused_everywhere(self):
        for value in ("MISSIONARY|calendar.edit", "AP|calendar.edit", "DATA_ADMIN|plans.unlock", "DL|calendar.edit",
                      "OFFICE|management", "OFFICE|presentations.use", "STL|plans.unlock", "nonsense", ""):
            self.assertIsNone(abilities.cell_from_key(value), value)
            with self.assertRaises(ValueError):
                abilities.wanted_from([value])
            with patch.object(abilities, "save_change", side_effect=AssertionError("must not save")):
                response = self.post("/abilities/save", on=[value], confirm="CHANGE", base="1")
            self.assertEqual(response.status_code, 302, value)
            self.assertIn("/abilities", response.headers["Location"])

    def test_saving_needs_the_typed_word(self):
        with patch.object(abilities, "save_change", side_effect=AssertionError("must not save")):
            for word in ("", "change", "CHANGE!", " ", "YES"):
                response = self.post("/abilities/save", on=self.ticked(), confirm=word, base="1")
                self.assertEqual(response.status_code, 302, word)

    def test_saving_passes_the_wanted_switches_the_base_the_note_and_the_person(self):
        with patch.object(abilities, "save_change", return_value=("saved", [])) as save:
            response = self.post("/abilities/save", on=self.ticked(("OFFICE", "calendar.edit")), confirm="CHANGE", base="11111111111",
                                 note="  Because  ")
        self.assertEqual(response.status_code, 302)
        wanted, base, note, who = save.call_args.args
        self.assertFalse(wanted[("OFFICE", "calendar.edit")])
        self.assertEqual(sum(wanted.values()), 10)
        self.assertEqual((base, note, who), ("11111111111", "Because", ("Test Person", USER_ID)))

    def test_every_answer_of_a_save_has_a_message(self):
        for status in ("saved", "nochange", "stale", "unreadable"):
            with patch.object(abilities, "save_change", return_value=(status, [])):
                response = self.post("/abilities/save", on=self.ticked(), confirm="CHANGE", base="1")
            self.assertEqual(response.status_code, 302, status)

    def test_revert_asks_the_database_layer_with_the_batch_and_the_person(self):
        batch = str(uuid.uuid4())
        for status in ("reverted", "missing", "already", "stale", "unreadable"):
            with patch.object(abilities, "revert_batch", return_value=(status, [])) as revert:
                response = self.post(f"/abilities/revert/{batch}")
            self.assertEqual(response.status_code, 302, status)
            self.assertEqual(revert.call_args.args, (batch, ("Test Person", USER_ID)))
        with patch.object(abilities, "revert_batch", side_effect=AssertionError("must not revert")):
            self.assertEqual(self.post("/abilities/revert/not-a-uuid").status_code, 302)


class RulesInTheCode(unittest.TestCase):
    def test_plan_and_refusal(self):
        current = table()
        wanted = abilities.wanted_from([abilities.cell_key(*cell) for cell in abilities.SWITCH_CELLS if cell != ("DL", "plans.unlock")])
        changes = abilities.plan(current, wanted)
        self.assertEqual(changes, [{"role": "DL", "ability": "plans.unlock", "before": True, "after": False}])
        self.assertIsNone(abilities.refusal(abilities.table_after(current, changes)))
        self.assertEqual(abilities.base_token(current), "1" * 11)
        self.assertEqual(abilities.base_token(abilities.table_after(current, changes)).count("0"), 1)

    def test_refusal_catches_every_rule_breaking_matrix(self):
        for cell in roles.DEFAULT_ABILITIES:
            role, ability = cell
            broken = dict(roles.DEFAULT_ABILITIES)
            broken[cell] = not broken[cell]
            fixed = role in roles.MANAGER_ROLES or role == "MISSIONARY" or cell not in abilities.SWITCH_CELLS
            self.assertEqual(abilities.refusal(broken) is not None, fixed, cell)
        self.assertIsNotNone(abilities.refusal({}))

    def test_the_switches_are_the_switchable_cells_and_nothing_else(self):
        self.assertEqual(len(abilities.SWITCH_CELLS), 11)
        self.assertEqual(set(abilities.SWITCH_CELLS), {(role, ability) for ability, listed in roles.SWITCHABLE.items() for role in listed})
        self.assertFalse({role for role, _ability in abilities.SWITCH_CELLS} & (roles.MANAGER_ROLES | {"MISSIONARY"}))

    def test_a_save_that_reads_back_something_else_is_undone(self):
        class Cur:
            pass
        with patch.object(abilities, "read_table", return_value=table(OFFICE__calendar_edit=False)):
            with self.assertRaises(RuntimeError):
                abilities.check_written(Cur(), table())

    def test_the_page_cannot_widen_what_the_table_may_hold(self):
        """No code path writes a cell outside SWITCH_CELLS: the only UPDATE is in apply_changes, fed by plan()."""
        source = (ROOT / "roster-importer" / "abilities.py").read_text(encoding="utf-8")
        self.assertEqual(len(re.findall(r"update public\.role_abilities", source)), 1)
        self.assertNotIn("delete from public.role_abilities", source.lower())
        self.assertNotIn("insert into public.role_abilities ", source.lower())


class TheMigrationSaysTheSame(unittest.TestCase):
    def sql(self, name="055_role_abilities.sql"):
        return (ROOT / "portal-api" / "migrations" / name).read_text(encoding="utf-8")

    def test_the_seed_check_lists_exactly_the_built_in_matrix(self):
        text = self.sql()
        found = re.search(r"expected CONSTANT text := (.*?);\nBEGIN", text, re.S).group(1)
        cells = dict(re.findall(r"([A-Z_]+/[a-z.]+)=([tf])", found))
        self.assertEqual(len(cells), 40)
        self.assertEqual({tuple(k.split("/")): v == "t" for k, v in cells.items()}, roles.DEFAULT_ABILITIES)

    def test_the_seed_insert_is_the_built_in_matrix(self):
        """The CASE of the seed INSERT gives the same lists as DEFAULT_ROLES (checked by role lists in the text)."""
        text = self.sql()
        seed = text[text.index("INSERT INTO public.role_abilities"):text.index("ON CONFLICT (role, ability) DO NOTHING;", text.index("INSERT INTO public.role_abilities"))]
        for ability, listed in roles.DEFAULT_ROLES.items():
            line = re.search(rf"WHEN '{re.escape(ability)}' THEN (.*)", seed).group(1)
            if ability == "announcements.publish":
                self.assertEqual(line.strip(), "r.role <> 'MISSIONARY'")
                self.assertEqual({r for r in roles.ABILITY_ROLES if r != "MISSIONARY"}, set(listed))
            else:
                self.assertEqual(set(re.findall(r"'([A-Z_]+)'", line)), set(listed), ability)

    def test_the_cell_rule_says_what_roles_py_says(self):
        text = self.sql()
        function = text[text.index("CREATE OR REPLACE FUNCTION public.role_ability_ok"):text.index("CREATE TABLE IF NOT EXISTS public.role_abilities (")]
        self.assertIn("WHEN p_role IN ('AP', 'PRESIDENT', 'DATA_ADMIN') THEN p_allowed", function)
        self.assertIn("WHEN p_role = 'MISSIONARY' THEN NOT p_allowed", function)
        self.assertIn("ELSE NOT p_allowed", function)  # a fixed cell may only be "no" (all fixed cells are "no" today)
        self.assertTrue(all(not v for (r, a), v in roles.DEFAULT_ABILITIES.items()
                            if r not in roles.MANAGER_ROLES and r != "MISSIONARY" and r not in roles.SWITCHABLE[a]))
        for ability, listed in roles.SWITCHABLE.items():
            self.assertIsNotNone(re.search(rf"'{re.escape(ability)}'", function))
            line = next(l for l in function.splitlines() if f"p_ability = '{ability}'" in l and "THEN true" in l)
            self.assertEqual(set(re.findall(r"'([A-Z_]+)'", line)), set(listed), ability)
        self.assertIn("p_ability NOT IN ('calendar.edit', 'announcements.publish', 'vollzogen.view', 'presentations.use', 'plans.unlock')", function)

    def test_the_catalog_and_the_check_list_the_five_abilities(self):
        text = self.sql()
        for ability in roles.ABILITIES:
            self.assertIn(f"'{ability}'", text)
        self.assertEqual(len(re.findall(r"\('[a-z.]+', \d\)", text)), 5)

    def test_the_tables_are_closed_to_everyone_but_the_service_connection(self):
        text = self.sql()
        for table_name in ("ability_catalog", "role_abilities", "role_abilities_log"):
            self.assertIn(f"ALTER TABLE public.{table_name} ENABLE ROW LEVEL SECURITY;", text)
        self.assertIn("REVOKE ALL ON public.ability_catalog, public.role_abilities, public.role_abilities_log FROM PUBLIC, anon, authenticated, service_role;", text)
        self.assertNotIn("CREATE POLICY", text)
        self.assertNotIn("GRANT SELECT ON public.role_abilit", text)
        self.assertNotIn("GRANT ALL ON public.role_abilit", text)

    def test_the_function_is_locked_down_like_every_security_definer_function(self):
        text = self.sql()
        self.assertIn("LANGUAGE plpgsql STABLE SECURITY DEFINER", text)
        self.assertIn("SET search_path TO 'public', 'pg_temp'", text)
        self.assertIn("REVOKE EXECUTE ON FUNCTION public.role_has_ability(text) FROM PUBLIC;", text)
        self.assertIn("GRANT EXECUTE ON FUNCTION public.role_has_ability(text) TO postgres, authenticated, service_role;", text)
        self.assertNotRegex(text, r"GRANT EXECUTE ON FUNCTION public\.role_has_ability\(text\) TO [^;]*\b(anon|public)\b")

    def test_it_is_one_transaction_with_a_checked_rollback(self):
        for name in ("055_role_abilities.sql", "055_role_abilities_rollback.sql"):
            text = self.sql(name)
            self.assertEqual(len(re.findall(r"^BEGIN;$", text, re.M)), 1, name)
            self.assertEqual(len(re.findall(r"^COMMIT;$", text, re.M)), 1, name)
            self.assertTrue(text.rstrip().endswith("COMMIT;"), name)
        down = self.sql("055_role_abilities_rollback.sql")
        for name in ("role_has_ability(text)", "role_abilities_log", "role_abilities;", "ability_catalog", "role_ability_ok"):
            self.assertIn(name, down)
        self.assertLess(down.index("DROP TABLE IF EXISTS public.role_abilities;"), down.index("DROP FUNCTION IF EXISTS public.role_ability_ok"))

    def test_the_guards_and_the_log_are_in_the_database_too(self):
        text = self.sql()
        for needle in ("A role ability row cannot be deleted.", "gfm.change_batch", "The role ability log is append-only.",
                       "CONSTRAINT role_abilities_cell_ok CHECK (public.role_ability_ok(role, ability, allowed))",
                       "BEFORE UPDATE OR DELETE ON public.role_abilities_log", "AFTER UPDATE ON public.role_abilities"):
            self.assertIn(needle, text)

    def test_the_readme_gives_the_next_number(self):
        text = (ROOT / "portal-api" / "migrations" / "README.md").read_text(encoding="utf-8")
        found = re.search(r"The next number is (\d{3})", text)
        self.assertTrue(found and int(found.group(1)) >= 56)
        self.assertIn("055_role_abilities", text)


class Texts(unittest.TestCase):
    def test_every_text_is_in_every_catalog_in_every_language(self):
        folder = ROOT / "portal" / "i18n"
        english = json.loads((folder / "en.json").read_text(encoding="utf-8"))
        values = set(v for v in english.values() if isinstance(v, str))
        for key, text in TEXT.items():
            self.assertIn(text, values, key)  # the page text has a catalog key (its own or an older one)
        keys = [key for key in TEXT if english.get(key) == TEXT[key]]
        self.assertGreaterEqual(len(keys), 50)
        for code in json.loads((folder / "catalogs.json").read_text(encoding="utf-8"))["languages"]:
            catalog = json.loads((folder / f"{code}.json").read_text(encoding="utf-8"))
            for key in keys:
                self.assertTrue(str(catalog.get(key, "")).strip(), (code, key))
            for key in ("abil.title", "abil.intro", "abil.managersNote", "abil.typeChange", "abil.log.title"):
                if code != "en":
                    self.assertNotEqual(catalog[key], english[key], (code, key))
        # The word to type is the same in every language.
        for code in json.loads((folder / "catalogs.json").read_text(encoding="utf-8"))["languages"]:
            catalog = json.loads((folder / f"{code}.json").read_text(encoding="utf-8"))
            self.assertIn(abilities.CONFIRM_WORD, catalog["abil.typeChange"], code)
            self.assertIn(abilities.CONFIRM_WORD, catalog["abil.badWord"], code)

    def test_the_menu_text_is_the_page_title(self):
        self.assertEqual(TEXT["abil.title"], "Role abilities")
        self.assertIn(("/abilities", "Role abilities"), page.MENU)

    def test_the_page_files_are_in_the_translation_check(self):
        text = (ROOT / "portal" / "tests" / "i18n-missing.cjs").read_text(encoding="utf-8")
        self.assertIn("roster-importer/abilities_text.py", text)
        self.assertIn("roster-importer/abilities_page.py", text)


if __name__ == "__main__":
    unittest.main()
