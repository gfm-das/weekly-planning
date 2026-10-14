# Seed for the database tests (`seed-test-mission.sql`)

The database tests (`portal-api/tests/*_db.py` and the database tests of `roster-importer/tests`) need a throw-away
database that already holds a small FAKE mission: zones, districts, areas, wards, missionaries, leaders, sign-ins and a few
finished weekly plans. A copy of the live database has none of that (zero areas). This file makes it. Invented data only
(`Test Zone North`, `Elder Seed01`, `@example.org`, ids from 9001); nobody can sign in with the accounts.

## How to use it

On the Ubuntu server, on a throw-away copy whose name contains `test` (for example `roster_management_test_new`, made as
`bash docs/handoff/round13/db-tests-trial.sh` does), after the baseline, all migrations and `019_restrict_public_functions.sql`:

```bash
docker cp tools/tests/seed-test-mission.sql gfm-throwaway-pg:/tmp/seed.sql
docker exec -e PGPASSWORD=... gfm-throwaway-pg psql -h 127.0.0.1 -U supabase_admin -d roster_management_test_new \
    -v ON_ERROR_STOP=1 -f /tmp/seed.sql
```

* It refuses to run if `current_database()` does not contain `test`. It runs in one transaction (all or nothing).
* It is idempotent: run it again and nothing is added twice. Run it again after a test has wiped plans or people.
* Run it as `supabase_admin` (or `postgres`): the plan triggers only let the server write plans, and the last step calls
  `sync_current_companionships()`, which only those two may run.
* It never touches live. Never run it on `postgres` / the live database (the name check is the only guard).

**Tip, one fresh copy per test file.** `test_people_uploads` (and `test_fc_numbers_db`, `test_vollzogen_db`, which reuse its
set-up) deletes every plan and every person at the start and end of each test; `test_data_uploads` deletes the area
profiles. After them the seed is partly gone. Seed once into a copy named `roster_management_test_seeded`, then give every
test file its own database: `CREATE DATABASE roster_management_test_<n> TEMPLATE roster_management_test_seeded OWNER postgres;`
(nobody may be connected to the template while you copy).

## What is in it

| Thing | Contents |
|---|---|
| Mission | mission 2 (the baseline has it; otherwise "Test Mission" is made) |
| Places | stake 9001; zones 9001 North and 9002 South; districts 9001 North One, 9002 North Two (zone North), 9003 South One, 9004 South Two (zone South); areas 9001..9009 "Test Area 1..9" in districts N1, N2, S1, S2, N1, N2, S1, S2, N1 |
| Wards | "Test Ward 1..9" (ids 9001..9009), one for each area; area 4 also has "Test Branch English" (the one area with two units) |
| Missionaries | 18, "Elder Seed01..18", two in each area (area n: missionaries 2n-1 and 2n), all started 2000-01-01 |
| Leaders | AP Seed05 (area 3, South); ZL Seed03 (area 2, North); DL Seed09 (area 5, North One); DL Seed11 (area 6, North Two, no sign-in); STL Seed17 (area 9, North, no sign-in) |
| Sign-ins | `...-0000005eed01` plain Seed01 and `02` plain Seed02 (both area 1); `03` DL; `04` ZL; `05` AP; `06` Office; `07` President; `08` Data Analyst (06 to 08 are staff accounts, no missionary, home mission 2); `09` plain Seed13 (area 7, South) |
| Weeks | this reporting week and the 14 before it |
| Plans | for the areas 4 to 9 only: 14 submitted plans each (84), with key-indicator numbers, 11 numeric answers and an action-plan text |
| People | 12 new members, 12 friends with a baptismal date, 12 high-potential friends a week, spread so each district has three and the areas 4 and 8 stay under three |
| Not made | call-ins, events, announcements, whiteboards, presentation rights (the tests write their own); no plans in the areas 1 to 3 |

The areas 1 to 3 have no plans on purpose: `overview_weeks_db.py` takes the three lowest areas and counts their plans.

## Which tests it is meant to unlock

portal-api (`python tests/<name>.py` in the portal-api container, with its `*_TEST_THROWAWAY=yes` variable):
`roles_db`, `callins_db`, `charts_db`, `dashboard_deck_db` (also needs the deck file at `/deck/slides.md`), `glimpse_db`,
`glimpse_zones_db`, `known_issues_db`, `overview_units_db`, `overview_weeks_db`, `planning_catalog_db`, `planning_people_db`,
`planning_people_actions_db`, `planning_safety_db`, `prefill_answers_db`, `reminders_db`, `role_abilities_db`,
`small_fixes_db`, `staff_accounts_db`, `stewardship_db`, `whiteboards_db`, `zone_decks_db`, `archetypes_db`,
`vollzogen_view_db`.

DA Management (`python -m unittest tests.<name>`, `MANAGEMENT_TEST_DATABASE=roster_management_test_<n>`):
`test_management`, `test_accounts`, `test_data_uploads`, `test_places_admin`, `test_people_uploads`, `test_fc_numbers_db`,
`test_geo_data_db`, `test_retire_db`, `test_vollzogen_db`, `test_unlock_db`, `test_abilities_db`, `test_planning_questions`.

Not helped by it: `access_checks_db.py` (hard-codes five account ids of the old `gfm_test_r3_template` and re-runs migration
037), `new_people_labels_db.py` (re-runs migration 028) and `section_guard_db.py` (re-runs migration 036): they are tests of
old migrations. `test_public_name` needs no database.

## A quick look at the result

```sql
SELECT leadership_role, count(*) FROM public.current_user_context WHERE user_active GROUP BY 1;   -- AP 1, DL 1, ZL 1, null 6 or more
SELECT z.name, count(*) FROM public.areas a JOIN public.districts d ON d.id=a.district_id
  JOIN public.zones z ON z.id=d.zone_id WHERE z.mission_id=2 GROUP BY 1;                          -- North 5, South 4
SELECT count(*) FROM public.weekly_area_reports;                                                    -- 84
```

This file was written without a database (round 13 sandbox) and has not been run. See `docs/handoff/round13/dbseed.md`.
