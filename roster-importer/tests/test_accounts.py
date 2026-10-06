"""Integration tests for staff accounts, transfers dated ahead, same-date corrections and changed roster emails.

Same rules as test_management.py (whose helpers they reuse): a disposable roster_management_test_* copy of Beta with
migrations 021 and 027, reached under the pinned Beta host name on an internal network. Emails are never sent.
"""
import re
import time
import unittest
import uuid
from datetime import date, timedelta
from unittest.mock import patch

from flask import session

import tests.test_management as tm  # the module, not the class: its own tests must not run twice

import account_changes  # noqa: E402  (after test_management, which checks the database first)
import account_links  # noqa: E402
import account_manager  # noqa: E402
import app  # noqa: E402
import batches  # noqa: E402
import database  # noqa: E402
import sign_in  # noqa: E402
import staff_accounts  # noqa: E402
import supabase_auth  # noqa: E402
import transfer  # noqa: E402
import undo  # noqa: E402

Base = tm.ManagementIntegrationTests


class AccountFlowTests(unittest.TestCase):
    setUpClass = classmethod(Base.setUpClass.__func__)
    tearDownClass = classmethod(Base.tearDownClass.__func__)
    setUp = Base.setUp
    context, scalar = Base.context, Base.scalar
    role_person, remove_person, leaders_of, app_role_of = Base.role_person, Base.remove_person, Base.leaders_of, Base.app_role_of
    admin_client, roster_row = Base.admin_client, Base.roster_row

    # Helpers ------------------------------------------------------------------------------------------------------
    def areas(self, n):
        """n active areas of mission 2 in different districts (the first is the tests' usual area)."""
        with database.connect() as conn:
            with database.cursor(conn) as cur:
                cur.execute("""select distinct on (d.id) a.id,a.name from public.areas a join public.districts d on d.id=a.district_id
                  join public.zones z on z.id=d.zone_id where z.mission_id=2 and a.active and d.active and z.active and d.id<>%s
                  order by d.id,a.id limit %s""", (self.scalar("select district_id from public.areas where id=%s", (self.area["id"],)), n - 1))
                return [self.area] + [dict(r) for r in cur.fetchall()]

    def assignments_of(self, who):
        with database.connect() as conn:
            with conn.cursor() as cur:
                cur.execute("select area_id,start_date,end_date from public.missionary_assignments where missionary_id=%s order by start_date,id", (who["id"],))
                return [tuple(r) for r in cur.fetchall()]

    def moved(self, who, area, roles):
        row = self.roster_row(who, roles)
        with database.connect() as conn:
            with database.cursor(conn) as cur:
                cur.execute("""select a.name area,d.name district,z.name zone from public.areas a join public.districts d on d.id=a.district_id
                  join public.zones z on z.id=d.zone_id where a.id=%s""", (area["id"],))
                row.update(cur.fetchone())
        return row

    def apply(self, rows, day, name="test.csv"):
        with self.context():
            session.update(portal_mission_id=2, portal_user="Integration test")
            return transfer.apply_roster_batch(rows, 2, day, name)

    def undo(self, batch):
        with self.context():
            session.update(portal_mission_id=2, portal_user="Integration test")
            undo.undo_batch(batch)

    def staff_user(self, email):
        """An Auth user (as GoTrue's invite would create it); removed again after the test."""
        user_id = str(uuid.uuid4())
        with database.connect() as conn:
            with conn.cursor() as cur:
                cur.execute("""insert into auth.users(id,instance_id,aud,role,email)
                  values(%s,'00000000-0000-0000-0000-000000000000','authenticated','authenticated',%s)""", (user_id, email))
        self.addCleanup(self.drop_user, user_id)
        return user_id

    def drop_user(self, user_id):
        with database.connect() as conn:
            with conn.cursor() as cur:
                cur.execute("delete from auth.users where id=%s", (user_id,))

    # Bug 2: a transfer dated ahead is not in force before its date -------------------------------------------------
    def test_01_transfer_dated_ahead_keeps_today_until_its_date(self):
        here, there = self.areas(2)
        mover = self.role_person("TEST-ACC-FUTURE-MOVE", leaders=["ZL"])
        leaving = self.role_person("TEST-ACC-FUTURE-LEAVE")
        later = date.today() + timedelta(days=7)
        with database.connect() as conn: before = batches.snapshot(conn, batches.TRANSFER_TABLES)
        batch = self.apply([self.moved(mover, there, [])], later, "ahead.csv")  # everyone else leaves the roster
        try:
            # The portal's current view and DA Management agree: nothing changes before the date.
            self.assertEqual(self.scalar("select area_id from public.current_missionary_assignments where missionary_id=%s", (mover["id"],)), here["id"])
            listed = {r["missionary_id"]: r for r in account_manager.account_rows(2)}
            self.assertEqual(listed[mover["id"]]["area"], here["name"])
            self.assertIn(leaving["id"], listed)  # still serving until the day before
            self.assertEqual(self.scalar("select status from public.missionaries where id=%s", (leaving["id"],)), "Active")
            self.assertTrue(self.scalar("select active from public.areas where id=%s", (here["id"],)))
            self.assertEqual(self.leaders_of(mover), [("ZL", date(2000, 1, 1), later - timedelta(days=1))])
            self.assertEqual(self.assignments_of(mover), [(here["id"], date(2000, 1, 1), later - timedelta(days=1)), (there["id"], later, None)])
            # The account page of someone leaving opens, and a move there would undo the release.
            client = self.admin_client(mover, "DATA_ADMIN")
            with patch.object(sign_in, "allowed", return_value=True):
                self.assertEqual(client.get(f"/accounts/{leaving['id']}").status_code, 200)
            # A roster for an earlier date cannot go underneath the recorded change.
            with self.assertRaisesRegex(ValueError, "already recorded"):
                transfer.preview([self.roster_row(mover, [])], 2, date.today())
            with self.assertRaisesRegex(ValueError, "already recorded"):
                self.apply([self.roster_row(mover, [])], date.today())
            notes = " ".join(transfer.preview([self.moved(mover, there, [])], 2, later)["notes"])
            self.assertIn("already recorded", notes)
            self.assertIn("Assignments and leadership change on", notes)
        finally:
            self.undo(batch)
        with database.connect() as conn: self.assertEqual(batches.snapshot(conn, batches.TRANSFER_TABLES), before)

    # Bug 3: a corrected roster for the same date replaces the earlier one, with undo intact ---------------------------
    def test_02_same_date_correction_replaces_the_earlier_change(self):
        here, there, third = self.areas(3)
        who = self.role_person("TEST-ACC-SAME-DAY", leaders=["DL"])
        day = date.today() + timedelta(days=10)
        with database.connect() as conn: before = batches.snapshot(conn, batches.TRANSFER_TABLES)
        first = self.apply([self.moved(who, there, ["ZL"])], day, "first.csv")
        applied = [first]
        try:
            # The old code failed here: ending the same-day row on the day before its own start broke the date check.
            second = self.apply([self.moved(who, third, ["DL"])], day, "second.csv")
            applied.append(second)
            self.assertEqual(self.assignments_of(who), [(here["id"], date(2000, 1, 1), day - timedelta(days=1)), (third["id"], day, None)])
            self.assertEqual([r[0] for r in self.leaders_of(who)], ["DL", "DL"])  # the ZL added for that date is gone
            self.assertEqual(self.leaders_of(who)[0][2], day - timedelta(days=1))
            third_batch = self.apply([self.moved(who, here, ["DL"])], day, "third.csv")  # back to how it was
            applied.append(third_batch)
            self.assertEqual(self.assignments_of(who), [(here["id"], date(2000, 1, 1), None)])  # re-opened, no second row
            self.assertEqual(self.leaders_of(who), [("DL", date(2000, 1, 1), None)])
            with self.assertRaisesRegex(ValueError, "changed after this import"):
                self.undo(first)  # the later corrections changed its rows
        finally:
            for batch in reversed(applied):
                self.undo(batch)
        with database.connect() as conn: self.assertEqual(batches.snapshot(conn, batches.TRANSFER_TABLES), before)

    # Bug 4: a changed roster email moves the linked sign-in instead of inviting a second one -------------------------
    def test_03_changed_roster_email_moves_the_linked_sign_in(self):
        who = self.role_person("TEST-ACC-NEW-MAIL")
        new = "test-acc-new-mail-2@example.invalid"
        with database.connect() as conn:
            with conn.cursor() as cur:
                cur.execute("update public.missionaries set email=%s where id=%s", (new, who["id"]))
        page = self.client.get("/accounts").get_data(as_text=True)
        row = re.search(r"<tr>(?:(?!</tr>).)*TEST-ACC-NEW-MAIL(?:(?!</tr>).)*</tr>", page, re.S).group(0)
        self.assertIn("Email changed", row)
        users = self.scalar("select count(*) from auth.users")
        form = {"csrf_token": "test-csrf", "mission_id": "2", "missionary_id": str(who["id"])}
        with patch.object(supabase_auth, "auth_request") as sent, patch.object(supabase_auth, "update_sign_in_email") as moved:
            check = self.client.post("/accounts/send", data=form).get_data(as_text=True)
            self.assertIn("Check before sending", check)
            self.assertIn(f"the sign-in changes from {who['email']} to {new}", check)
            self.assertFalse(sent.called or moved.called)
            token = re.search(r'name="plan" value="([0-9a-f]+)"', check).group(1)
            stale = self.client.post("/accounts/send", data=form | {"plan": "0" * 32}).get_data(as_text=True)
            self.assertIn("Something changed", stale)
            done = self.client.post("/accounts/send", data=form | {"plan": token}).get_data(as_text=True)
        self.assertIn("Sign-in moved from", done)
        moved.assert_called_once_with(who["profile_id"], new)
        self.assertEqual([c.args for c in sent.call_args_list], [("/auth/v1/recover", {"email": new})])
        self.assertEqual(self.scalar("select count(*) from auth.users"), users)  # no second sign-in

    def test_04_plans_skip_turned_off_accounts_and_conflicts_and_link_free_sign_ins(self):
        off = self.role_person("TEST-ACC-OFF")
        taken = self.role_person("TEST-ACC-TAKEN")
        other = self.role_person("TEST-ACC-OTHER")
        free = self.role_person("TEST-ACC-FREE")
        with database.connect() as conn:
            with conn.cursor() as cur:
                cur.execute("update public.user_profiles set active=false where id=%s", (off["profile_id"],))
                cur.execute("update public.missionaries set email=%s where id=%s", (other["email"], taken["id"]))
                cur.execute("delete from public.user_profiles where id=%s", (free["profile_id"],))  # a sign-in without a profile
        people = [{"missionary_id": w["id"], "display_name": w["number"], "email": w["email"] if w is not taken else other["email"]}
                  for w in (off, taken, free)]
        with database.connect() as conn:
            with database.cursor(conn) as cur:
                plans = account_links.plan_sign_ins(cur, people)
        self.assertEqual([p["action"] for p in plans], ["SKIP", "SKIP", "LINK"])
        self.assertIn("turned off", plans[0]["reason"])
        self.assertIn("already belongs to another sign-in", plans[1]["reason"])
        # Sending to the turned-off account (the old flow re-activated it) sends nothing and keeps it off.
        with patch.object(supabase_auth, "auth_request") as sent:
            form = {"csrf_token": "test-csrf", "mission_id": "2", "missionary_id": str(off["id"])}
            token = re.search(r'name="plan" value="([0-9a-f]+)"', self.client.post("/accounts/send", data=form).get_data(as_text=True)).group(1)
            self.assertIn("turned off", self.client.post("/accounts/send", data=form | {"plan": token}).get_data(as_text=True))
        self.assertFalse(sent.called)
        self.assertFalse(self.scalar("select active from public.user_profiles where id=%s", (off["profile_id"],)))
        with database.connect() as conn:
            with database.cursor(conn) as cur:
                account_manager.ensure_profile_link(cur, off["profile_id"], off["id"])  # already linked: left as it is
                cur.execute("select active from public.user_profiles where id=%s", (off["profile_id"],))
                self.assertFalse(cur.fetchone()["active"])

    # Bug 1: staff accounts ------------------------------------------------------------------------------------------
    def staff_client(self, role, user_id=None):
        client = app.app.test_client()
        with client.session_transaction() as s:
            s.update(authenticated=True, portal_user_id=user_id or str(uuid.uuid4()), portal_role=role, portal_mission_id=2,
                     portal_user="Integration test", portal_expires_at=time.time() + 1800, csrf_token="test-csrf")
        return client

    def invite(self, client, name, email, role):
        user_id = []

        def fake_auth(path, payload):
            if path == "/auth/v1/invite":
                user_id.append(self.staff_user(payload["email"]))
                return {"id": user_id[-1]}
            return {}
        with patch.object(sign_in, "allowed", return_value=True), patch.object(supabase_auth, "auth_request", side_effect=fake_auth) as sent:
            response = client.post("/staff/new", data={"csrf_token": "test-csrf", "display_name": name, "email": email, "role": role})
        return response, (user_id[0] if user_id else None), sent

    def test_05_staff_president_is_added_signs_in_and_can_be_undone(self):
        client = self.staff_client("DATA_ADMIN")
        response, user_id, sent = self.invite(client, "President Test", "test-acc-president@example.invalid", "PRESIDENT")
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        self.assertIn("an invitation was sent", response.get_data(as_text=True))
        with database.connect() as conn:
            with database.cursor(conn) as cur:
                cur.execute("select missionary_id,app_role,active,home_mission_id,display_name from public.user_profiles where id=%s", (user_id,))
                self.assertEqual(dict(cur.fetchone()), {"missionary_id": None, "app_role": "PRESIDENT", "active": True,
                                                        "home_mission_id": 2, "display_name": "President Test"})
                cur.execute("select home_mission_id,display_name,mission_id from public.current_user_context where user_id=%s", (user_id,))
                self.assertEqual(dict(cur.fetchone()), {"home_mission_id": 2, "display_name": "President Test", "mission_id": None})
        # DA Management: the President has access in the home mission.
        context = sign_in.current_management_context(user_id)
        self.assertEqual((context["management_role"], context["mission_id"], context["display_name"]), ("PRESIDENT", 2, "President Test"))
        with patch.object(sign_in, "allowed", return_value=True):
            staff_page = client.get("/staff").get_data(as_text=True)
            self.assertIn("President Test", staff_page)
            # Round 3 wording: who staff accounts are for, and one line per role.
            self.assertIn("Staff accounts do not have a weekly plan.", staff_page)
            for role in ("PRESIDENT", "DATA_ADMIN", "OFFICE"):
                self.assertIn(staff_accounts.ROLE_HELP[role], staff_page, role)
        batch = self.scalar("select id::text from public.roster_import_batches where kind='ACCOUNT' order by created_at desc limit 1")
        self.undo(batch)
        self.assertEqual(self.scalar("select count(*) from public.user_profiles where id=%s", (user_id,)), 0)
        # Adding the same email again uses the existing sign-in (no second invitation).
        response, again, sent = self.invite(client, "President Test", "test-acc-president@example.invalid", "PRESIDENT")
        self.assertIsNone(again)
        self.assertEqual([c.args[0] for c in sent.call_args_list], ["/auth/v1/recover"])
        self.assertEqual(self.scalar("select app_role from public.user_profiles where id=%s", (user_id,)), "PRESIDENT")

    def test_06_an_ap_gives_every_staff_role_including_president(self):
        # APs have full rights (owner, 28 Sep): the same as the President and a Data Analyst.
        ap = self.staff_client("AP")
        response, president, sent = self.invite(ap, "President Test", "test-acc-president-ap@example.invalid", "PRESIDENT")
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        self.assertEqual(self.profile_of(president), "(PRESIDENT,t,{})")
        self.assertEqual(sign_in.current_management_context(president)["management_role"], "PRESIDENT")
        # An AP may add a Data Analyst, who gets DA Management access.
        response, analyst, _ = self.invite(ap, "Data Test", "test-acc-da@example.invalid", "DATA_ADMIN")
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        self.assertEqual(self.profile_of(analyst), "(DATA_ADMIN,t,{})")
        self.assertEqual(sign_in.current_management_context(analyst)["management_role"], "DATA_ADMIN")
        response, office, _ = self.invite(ap, "Office Test", "test-acc-office@example.invalid", "OFFICE")
        self.assertEqual(response.status_code, 200)
        with patch.object(sign_in, "allowed", return_value=True):
            # The AP's Add form offers every role.
            listing = ap.get("/staff").get_data(as_text=True)
            block = re.search(r'<select name="role">(.*?)</select>', listing, re.S).group(1)
            self.assertEqual(re.findall(r'value="([A-Z_]+)"', block), ["PRESIDENT", "DATA_ADMIN", "OFFICE"])
            self.assertNotIn("can add a President", listing)
            # A President's account is the AP's to change, like any other.
            page = ap.get(f"/staff/{president}").get_data(as_text=True)
            self.assertNotIn(staff_accounts.NOT_ALLOWED, page)
            self.assertIn("Save changes", page)
            # An AP may make the Office account President, then Data Analyst, and Office again.
            form = {"csrf_token": "test-csrf", "display_name": "Office Test", "email": "test-acc-office@example.invalid", "active": "yes"}
            for role in ("PRESIDENT", "DATA_ADMIN", "OFFICE"):
                saved = ap.post(f"/staff/{office}/update", data=form | {"state": self.staff_state(ap, office), "role": role})
                self.assertIn("Saved", saved.get_data(as_text=True), role)
                self.assertEqual(self.profile_of(office), f"({role},t,{{}})")
            # An email that belongs to a missionary is refused.
            missionary = self.role_person("TEST-ACC-MISSIONARY-MAIL")
            refused, _, _ = self.invite(ap, "Someone", missionary["email"], "OFFICE")
            self.assertIn("sign-in of a missionary", refused.get_data(as_text=True))
        # The Office account gets no DA Management access.
        self.assertIsNone(sign_in.current_management_context(office))

    def test_07_edit_turn_off_stale_page_and_own_access(self):
        _, user_id, _ = self.invite(self.staff_client("DATA_ADMIN"), "Analyst Test", "test-acc-analyst@example.invalid", "DATA_ADMIN")
        own = self.staff_client("DATA_ADMIN", user_id)
        with patch.object(sign_in, "allowed", return_value=True):
            state = re.search(r'name="state" value="([0-9a-f]+)"', own.get(f"/staff/{user_id}").get_data(as_text=True)).group(1)
            form = {"csrf_token": "test-csrf", "state": state, "display_name": "Analyst Renamed", "email": "test-acc-analyst@example.invalid",
                    "role": "OFFICE", "active": "yes"}
            refused = own.post(f"/staff/{user_id}/update", data=form).get_data(as_text=True)
            self.assertIn("ends your own DA Management access", refused)
            self.assertIn("or ask an AP, the President or a Data Analyst to make the change.", refused)
            self.assertEqual(self.scalar("select app_role from public.user_profiles where id=%s", (user_id,)), "DATA_ADMIN")
            other = self.staff_client("DATA_ADMIN")
            renamed = other.post(f"/staff/{user_id}/update", data=form | {"role": "DATA_ADMIN"})
            self.assertIn("Saved", renamed.get_data(as_text=True))
            self.assertIn("changed since you opened", other.post(f"/staff/{user_id}/update", data=form).get_data(as_text=True))
            state = re.search(r'name="state" value="([0-9a-f]+)"', own.get(f"/staff/{user_id}").get_data(as_text=True)).group(1)
            done = own.post(f"/staff/{user_id}/update", data=form | {"state": state, "own_access": "yes", "active": ""})
            self.assertIn("signed out of DA Management", done.get_data(as_text=True))
            self.assertIn("Ask an AP, the President or a Data Analyst if you need it again.", done.get_data(as_text=True))
            with own.session_transaction() as s: self.assertNotIn("authenticated", s)
        self.assertEqual(self.scalar("select (app_role,active)::text from public.user_profiles where id=%s", (user_id,)), "(OFFICE,f)")
        self.assertEqual(self.scalar("""select count(*) from public.roster_import_batches b join public.roster_import_changes c on c.batch_id=b.id
          where b.kind='ACCOUNT' and c.row_key->>'id'=%s""", (user_id,)), 3)  # added, renamed, turned off

    # Review fixes ---------------------------------------------------------------------------------------------------
    page_form, plan_of = Base.page_form, Base.plan_of

    def last_account_batch(self):
        return self.scalar("select id::text from public.roster_import_batches where kind='ACCOUNT' order by created_at desc limit 1")

    def staff_state(self, client, user_id):
        return re.search(r'name="state" value="([0-9a-f]+)"', client.get(f"/staff/{user_id}").get_data(as_text=True)).group(1)

    def profile_of(self, user_id):
        return self.scalar("select (app_role,active,coalesce(additional_roles,'{}'))::text from public.user_profiles where id=%s", (user_id,))

    def test_08_an_ap_undoes_staff_account_changes_including_the_presidents(self):
        da, ap = self.staff_client("DATA_ADMIN"), self.staff_client("AP")
        undo = {"csrf_token": "test-csrf", "confirmation": "UNDO"}

        def turn_off(user_id, name, email, role):
            form = {"csrf_token": "test-csrf", "state": self.staff_state(da, user_id), "display_name": name, "email": email,
                    "role": role, "active": ""}
            self.assertIn("Saved", da.post(f"/staff/{user_id}/update", data=form).get_data(as_text=True))
            return self.last_account_batch()
        with patch.object(sign_in, "allowed", return_value=True):
            # A Data Analyst account: the AP may undo the change.
            _, analyst, _ = self.invite(da, "Analyst Undo", "test-acc-undo-da@example.invalid", "DATA_ADMIN")
            turned_off = turn_off(analyst, "Analyst Undo", "test-acc-undo-da@example.invalid", "DATA_ADMIN")
            self.assertEqual(self.profile_of(analyst), "(DATA_ADMIN,f,{})")
            self.assertIn("Undo batch", ap.get(f"/imports/{turned_off}").get_data(as_text=True))
            self.assertEqual(ap.post(f"/imports/{turned_off}/undo", data=undo).status_code, 302)
            self.assertEqual(self.profile_of(analyst), "(DATA_ADMIN,t,{})")
            self.assertEqual(sign_in.current_management_context(analyst)["management_role"], "DATA_ADMIN")
            # A President account: the AP may undo its changes too (APs have full rights, owner 28 Sep).
            _, president, _ = self.invite(da, "President Undo", "test-acc-undo-president@example.invalid", "PRESIDENT")
            added = self.last_account_batch()
            turned_off = turn_off(president, "President Undo", "test-acc-undo-president@example.invalid", "PRESIDENT")
            page = ap.get(f"/imports/{turned_off}").get_data(as_text=True)
            self.assertNotIn(account_changes.NOT_ALLOWED_UNDO, page)
            self.assertIn("Undo batch", page)
            self.assertEqual(ap.post(f"/imports/{turned_off}/undo", data=undo).status_code, 302)
            self.assertEqual(self.profile_of(president), "(PRESIDENT,t,{})")
            self.assertEqual(sign_in.current_management_context(president)["management_role"], "PRESIDENT")
            self.assertEqual(ap.post(f"/imports/{added}/undo", data=undo).status_code, 302)
            self.assertEqual(self.scalar("select count(*) from public.user_profiles where id=%s", (president,)), 0)
            # An Office account, as before.
            _, office, _ = self.invite(ap, "Office Undo", "test-acc-undo-office@example.invalid", "OFFICE")
            self.assertEqual(ap.post(f"/imports/{self.last_account_batch()}/undo", data=undo).status_code, 302)
            self.assertEqual(self.scalar("select count(*) from public.user_profiles where id=%s", (office,)), 0)

    def test_09_undoing_the_batch_that_added_your_own_account_needs_the_tick(self):
        _, analyst, _ = self.invite(self.staff_client("PRESIDENT"), "Analyst Self", "test-acc-undo-self@example.invalid", "DATA_ADMIN")
        batch = self.last_account_batch()
        own = self.staff_client("DATA_ADMIN", analyst)
        undo = {"csrf_token": "test-csrf", "confirmation": "UNDO"}
        with patch.object(sign_in, "allowed", return_value=True):
            page = own.post(f"/imports/{batch}/undo", data=undo)
            self.assertEqual(page.status_code, 409)
            self.assertIn("ends your own DA Management access", page.get_data(as_text=True))
            self.assertIn('name="own_access"', page.get_data(as_text=True))
            self.assertEqual(self.profile_of(analyst), "(DATA_ADMIN,t,{})")  # nothing was undone
            done = own.post(f"/imports/{batch}/undo", data=undo | {"own_access": "yes"})
            self.assertIn("signed out of DA Management", done.get_data(as_text=True))
            self.assertIn("Ask an AP, the President or a Data Analyst if you need it again.", done.get_data(as_text=True))
            with own.session_transaction() as s: self.assertNotIn("authenticated", s)
        self.assertEqual(self.scalar("select count(*) from public.user_profiles where id=%s", (analyst,)), 0)
        self.assertEqual(self.scalar("select status from public.roster_import_batches where id=%s", (batch,)), "UNDONE")

    def test_10_an_ap_president_or_data_analyst_moves_or_links_a_presidents_sign_in(self):
        president = self.role_person("TEST-ACC-PRES-MAIN", "PRESIDENT")
        main = self.role_person("TEST-ACC-DA-MAIN", "DATA_ADMIN")
        extra = self.role_person("TEST-ACC-DA-EXTRA", additional=["DATA_ADMIN"])
        plain = self.role_person("TEST-ACC-PLAIN-MAIL")
        free_president = self.role_person("TEST-ACC-PRES-FREE")
        free_analyst = self.role_person("TEST-ACC-DA-FREE")
        moving = [president, main, extra, plain]
        with database.connect() as conn:
            with conn.cursor() as cur:
                for who in moving:
                    cur.execute("update public.missionaries set email=%s where id=%s", (who["number"].lower() + "-new@example.invalid", who["id"]))
                # Sign-ins with the roster email and a President or Data Analyst profile that is linked to nobody.
                for who, role in ((free_president, "PRESIDENT"), (free_analyst, "DATA_ADMIN")):
                    cur.execute("update public.user_profiles set missionary_id=null,app_role=%s where id=%s", (role, who["profile_id"]))
        people = [{"missionary_id": w["id"], "display_name": w["number"],
                   "email": w["number"].lower() + "-new@example.invalid" if any(w is x for x in moving) else w["email"]}
                  for w in moving + [free_president, free_analyst]]

        def plans(role):
            with self.context():
                session.update(portal_role=role, portal_mission_id=2)
                with database.connect() as conn:
                    with database.cursor(conn) as cur:
                        return account_links.plan_sign_ins(cur, people)
        # APs have full rights (owner, 28 Sep): the same plans as a Data Analyst and the importer password.
        for role in ("AP", "DATA_ADMIN", None):
            self.assertEqual([p["action"] for p in plans(role)], ["EMAIL", "EMAIL", "EMAIL", "EMAIL", "LINK", "LINK"], role)
        # Through the page: the AP's check page offers both emails, and confirming moves both sign-ins.
        client = self.staff_client("AP")
        form = {"csrf_token": "test-csrf", "mission_id": "2", "missionary_id": [str(president["id"]), str(plain["id"])]}
        with patch.object(sign_in, "allowed", return_value=True), patch.object(supabase_auth, "auth_request") as sent, \
                patch.object(supabase_auth, "update_sign_in_email") as moved:
            check = client.post("/accounts/send", data=form).get_data(as_text=True)
            self.assertIn("Send 2 emails", check)
            token = re.search(r'name="plan" value="([0-9a-f]+)"', check).group(1)
            client.post("/accounts/send", data=form | {"plan": token})
        self.assertEqual(sorted(c.args for c in moved.call_args_list),
                         sorted((w["profile_id"], w["number"].lower() + "-new@example.invalid") for w in (president, plain)))
        self.assertEqual(len(sent.call_args_list), 2)

    def test_11_no_email_stays_no_email_for_a_linked_missionary(self):
        who = self.role_person("TEST-ACC-NO-MAIL")
        with database.connect() as conn:
            with conn.cursor() as cur:
                cur.execute("update public.missionaries set email=null where id=%s", (who["id"],))
        rows = account_links.with_linked_sign_ins([r for r in account_manager.account_rows(2) if r["missionary_id"] == who["id"]])
        self.assertEqual(rows[0]["account_status"], "No email")
        page = self.client.get("/accounts?status=Email+changed").get_data(as_text=True)
        self.assertIn('<option value="Email changed" selected', page)
        self.assertIn("email changed</div>", page)

    def test_12_adding_a_staff_account_over_an_existing_sign_in_follows_the_role_rules(self):
        ap, da = self.staff_client("AP"), self.staff_client("DATA_ADMIN")
        cases = {"test-acc-reuse-president@example.invalid": ("PRESIDENT", False, "{}"),
                 "test-acc-reuse-da@example.invalid": ("DATA_ADMIN", False, "{}"),
                 "test-acc-reuse-extra@example.invalid": ("MISSIONARY", False, "{DATA_ADMIN}"),
                 "test-acc-reuse-office@example.invalid": ("MISSIONARY", True, "{OFFICE}")}
        users = {}
        with database.connect() as conn:
            with conn.cursor() as cur:
                for email, (role, active, extras) in cases.items():  # sign-ins without a missionary or a home mission
                    users[email] = self.staff_user(email)
                    cur.execute("insert into public.user_profiles(id,missionary_id,app_role,active,additional_roles) values(%s,null,%s,%s,%s)",
                                (users[email], role, active, extras))
        # The sign-in becomes exactly the staff account shown (its earlier role or additional role goes, and Undo brings it
        # back). APs have full rights (owner, 28 Sep): an AP may take the President role (even turned off) or the Data
        # Analyst role away, as a main or an additional role.
        for email in cases:
            response, _, sent = self.invite(ap, "Reuse Office", email, "OFFICE")
            self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
            self.assertEqual(self.profile_of(users[email]), "(OFFICE,t,{})")
            self.assertEqual([c.args[0] for c in sent.call_args_list], ["/auth/v1/recover"])  # a password email, no new invitation
        self.undo(self.last_account_batch())
        self.assertEqual(self.profile_of(users["test-acc-reuse-office@example.invalid"]), "(MISSIONARY,t,{OFFICE})")
        # A staff account that has Data Analyst as an additional role: an AP may save it, which removes that role.
        office = users["test-acc-reuse-extra@example.invalid"]
        with database.connect() as conn:
            with conn.cursor() as cur:
                cur.execute("update public.user_profiles set additional_roles='{DATA_ADMIN}' where id=%s", (office,))
        form = {"csrf_token": "test-csrf", "display_name": "Reuse Office", "email": "test-acc-reuse-extra@example.invalid",
                "role": "OFFICE", "active": "yes"}
        with patch.object(sign_in, "allowed", return_value=True):
            page = ap.get(f"/staff/{office}").get_data(as_text=True)
            self.assertIn("Office + Data Analyst", page)
            self.assertIn("saving this page removes it", page)
            self.assertIn("Save changes", page)
            saved = ap.post(f"/staff/{office}/update", data=form | {"state": self.staff_state(ap, office)})
            self.assertIn("Saved", saved.get_data(as_text=True))
        self.assertEqual(self.profile_of(office), "(OFFICE,t,{})")
        # A President staff account is open to an AP as well.
        with database.connect() as conn:
            with conn.cursor() as cur:
                cur.execute("update public.user_profiles set app_role='PRESIDENT' where id=%s", (office,))
        with patch.object(sign_in, "allowed", return_value=True):
            self.assertIn("Save changes", ap.get(f"/staff/{office}").get_data(as_text=True))
            self.assertIn("Save changes", da.get(f"/staff/{office}").get_data(as_text=True))
            saved = ap.post(f"/staff/{office}/update", data=form | {"state": self.staff_state(ap, office), "display_name": "Reuse President",
                                                                    "role": "PRESIDENT"})
            self.assertIn("Saved", saved.get_data(as_text=True))
        self.assertEqual(self.profile_of(office), "(PRESIDENT,t,{})")

    def test_13_account_page_shows_today_and_a_move_saved_ahead_can_be_taken_back(self):
        here, there, third = self.areas(3)
        who = self.role_person("TEST-ACC-PAGE-MOVE", leaders=["DL"])
        admin = self.staff_client("DATA_ADMIN")
        later = date.today() + timedelta(days=14)
        tables = ["missionary_assignments", "leadership_assignments"]
        with database.connect() as conn: before = batches.snapshot(conn, tables)
        with patch.object(sign_in, "allowed", return_value=True):
            page, form = self.page_form(admin, who)
            saved = admin.post(f"/accounts/{who['id']}/update", data=form | {"area_id": str(there["id"]), "effective_date": later.isoformat()})
            self.assertEqual(saved.status_code, 302, saved.get_data(as_text=True))
            next_id = self.scalar("select id from public.missionary_assignments where missionary_id=%s and start_date=%s", (who["id"], later))
            # Today's area is shown and selected (as the portal has it), with the move and the way back.
            page, form = self.page_form(admin, who)
            self.assertEqual(form["area_id"], str(here["id"]))
            self.assertEqual(self.scalar("select area_id from public.current_missionary_assignments where missionary_id=%s", (who["id"],)), here["id"])
            self.assertIn(f"moves to", page)
            self.assertIn(f'<option value="-{next_id}"', page)
            # Another move is refused with a message that says how to go on; so is a roster dated before the move.
            refused = admin.post(f"/accounts/{who['id']}/update", data=form | {"area_id": str(third["id"])})
            self.assertEqual(refused.status_code, 400)
            self.assertIn("is already saved. This page keeps one move ahead at a time", refused.get_data(as_text=True))
            self.assertIn("is already saved", self.plan_of(admin, who, form, area_id=str(third["id"]))["errors"][0])
            with self.assertRaisesRegex(ValueError, "saved on the account page.*stay here"):
                transfer.preview([self.roster_row(who, ["DL"])], 2, date.today() + timedelta(days=7))
            plan = self.plan_of(admin, who, form, area_id=f"-{next_id}")
            self.assertEqual((plan["errors"], plan["ends"]), ([], 1))
            self.assertIn("Takes back the move", plan["lines"][0])
            self.assertTrue(any("Removes the DL assignment" in line for line in plan["lines"]))
            stale = admin.post(f"/accounts/{who['id']}/update", data=form | {"area_id": f"-{next_id}", "state": "old"})
            self.assertIn("changed since you opened", stale.get_data(as_text=True))
            taken = admin.post(f"/accounts/{who['id']}/update", data=form | {"area_id": f"-{next_id}"})
            self.assertEqual(taken.status_code, 302, taken.get_data(as_text=True))
        self.assertEqual(self.assignments_of(who), [(here["id"], date(2000, 1, 1), None)])
        self.assertEqual(self.leaders_of(who), [("DL", date(2000, 1, 1), None)])
        with database.connect() as conn: self.assertEqual(batches.snapshot(conn, tables), before)
        self.assertEqual(self.app_role_of(who), "DL")  # as the first save recorded it for the DL assignment in force
        transfer.preview([self.roster_row(who, ["DL"])], 2, date.today() + timedelta(days=7))  # no longer blocked

    def test_14_a_move_recorded_by_a_transfer_is_changed_by_roster_not_on_the_page(self):
        here, there, third = self.areas(3)
        who = self.role_person("TEST-ACC-PAGE-TRANSFER")
        later = date.today() + timedelta(days=7)
        batch = self.apply([self.moved(who, there, [])], later, "ahead-page.csv")
        try:
            admin = self.staff_client("DATA_ADMIN")
            with patch.object(sign_in, "allowed", return_value=True):
                page, form = self.page_form(admin, who)
                self.assertEqual(form["area_id"], str(here["id"]))
                self.assertIn('transfer "ahead-page.csv"', page.replace("&#34;", '"').replace("&quot;", '"'))
                self.assertNotIn("stay here", page)
                refused = admin.post(f"/accounts/{who['id']}/update", data=form | {"area_id": str(third["id"])})
                self.assertIn("already moves them", refused.get_data(as_text=True))
                next_id = self.scalar("select id from public.missionary_assignments where missionary_id=%s and start_date=%s", (who["id"], later))
                self.assertIn("undo that transfer", " ".join(self.plan_of(admin, who, form, area_id=f"-{next_id}")["errors"]))
            with self.assertRaisesRegex(ValueError, 'already recorded by the transfer "ahead-page.csv"'):
                transfer.preview([self.roster_row(who, [])], 2, date.today())
        finally:
            self.undo(batch)


class UndoAfterMigrationTests(unittest.TestCase):
    setUpClass = classmethod(Base.setUpClass.__func__)
    tearDownClass = classmethod(Base.tearDownClass.__func__)
    setUp, context, scalar = Base.setUp, Base.context, Base.scalar
    role_person, remove_person, roster_row = Base.role_person, Base.remove_person, Base.roster_row

    def test_undo_of_a_batch_recorded_before_a_column_was_added(self):
        """Migrations 021 and 027 add user_profiles columns; older audit rows lack them. Undo must still work."""
        ap = self.role_person("TEST-ACC-OLD-AUDIT", "AP", ["AP"])
        with database.connect() as conn: before = batches.snapshot(conn, batches.TRANSFER_TABLES)
        with self.context():
            session.update(portal_mission_id=2, portal_user="Integration test")
            batch = transfer.apply_roster_batch([self.roster_row(ap, [])], 2, date(2099, 1, 2), "old-audit.csv")
            with database.connect() as conn:
                with conn.cursor() as cur:  # as if recorded before 021/027
                    cur.execute("""update public.roster_import_changes set before_row=before_row-'additional_roles'-'home_mission_id'-'display_name',
                      after_row=after_row-'additional_roles'-'home_mission_id'-'display_name' where batch_id=%s and table_name='user_profiles'""", (batch,))
                    self.assertGreater(cur.rowcount, 0)
            undo.undo_batch(batch)
        with database.connect() as conn: self.assertEqual(batches.snapshot(conn, batches.TRANSFER_TABLES), before)


del Base  # only AccountFlowTests belongs to this module (unittest would otherwise run test_management's tests again)

if __name__ == "__main__":
    unittest.main(verbosity=2)
