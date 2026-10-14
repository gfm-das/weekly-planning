-- seed-test-mission.sql: FAKE seed data for the database tests (portal-api/tests/*_db.py and the database tests of
-- roster-importer). Round 13 (docs/handoff/round13/dbseed.md). Read tools/tests/README-seed.md first.
--
-- Apply it as supabase_admin to a THROW-AWAY copy whose name contains "test" (for example roster_management_test_new),
-- AFTER the baseline and every migration (and 019 again):
--     psql -v ON_ERROR_STOP=1 -U supabase_admin -d roster_management_test_new -f seed-test-mission.sql
-- It refuses to run in any database whose name does not contain "test". It is idempotent: a second run adds nothing
-- that is already there (every insert has ON CONFLICT DO NOTHING or a NOT EXISTS), so it can be run again after a test
-- has wiped plans or people (test_people_uploads does). One transaction: all or nothing.
--
-- Only invented data: names "Test ...", missionaries "Elder SeedNN", e-mail addresses @example.org, ids from 9001 up.
-- No real person, no secret: the accounts get a password hash that matches no password (nobody can sign in with them).
--
-- What it makes (mission 2 is the mission the tests use; the baseline has it, otherwise it is made here):
--   1 stake, 2 zones, 4 districts, 9 areas "Test Area 1".."Test Area 9", 10 wards/branches, 18 missionaries (2 per area)
--   leaders: AP (zone South), ZL (zone North), DL (district North One), a second DL and an STL without accounts
--   9 sign-ins: 3 plain missionaries (two in one area, one far away), DL, ZL, AP, and Office / President / Data Analyst staff
--   15 reporting weeks (this week and 14 finished ones); 14 finished weekly plans for each of the areas 4 to 9, with
--   key-indicator numbers, answers, and small groups of new members, friends with a baptismal date and high-potential friends
-- The areas 1 to 3 (the lowest ids) deliberately have NO plans: overview_weeks_db.py uses the three lowest areas.

BEGIN;

-- 0. Safety -------------------------------------------------------------------------------------------------------
DO $$
BEGIN
    IF current_database() NOT LIKE '%test%' THEN
        RAISE EXCEPTION 'Refusing to run: the database "%" is not a throw-away test copy (its name must contain "test").', current_database();
    END IF;
END $$;

-- 1. Mission, stake, zones, districts, wards, areas ---------------------------------------------------------------
INSERT INTO public.missions (id, name)
SELECT 2, 'Test Mission' WHERE NOT EXISTS (SELECT 1 FROM public.missions WHERE id = 2);

INSERT INTO public.stakes (id, mission_id, name, active) VALUES (9001, 2, 'Test Stake', true)
ON CONFLICT DO NOTHING;

INSERT INTO public.zones (id, mission_id, name, active) VALUES
    (9001, 2, 'Test Zone North', true),
    (9002, 2, 'Test Zone South', true)
ON CONFLICT DO NOTHING;

INSERT INTO public.districts (id, zone_id, name, active) VALUES
    (9001, 9001, 'Test District North One', true),
    (9002, 9001, 'Test District North Two', true),
    (9003, 9002, 'Test District South One', true),
    (9004, 9002, 'Test District South Two', true)
ON CONFLICT DO NOTHING;

-- Wards 9001..9009 (one for each area, same number) and one branch (9010) that area 9004 shares with its own ward.
INSERT INTO public.units (id, stake_id, name, unit_type, active)
SELECT 9000 + n, 9001, 'Test Ward ' || n, 'Ward', true FROM generate_series(1, 9) AS n
UNION ALL
SELECT 9010, 9001, 'Test Branch English', 'Branch', true
ON CONFLICT DO NOTHING;

-- Area n is in these districts: 1 North One, 2 North Two, 3 South One, 4 South Two, 5 North One, 6 North Two,
-- 7 South One, 8 South Two, 9 North One. So every district has areas, and North One has three.
INSERT INTO public.areas (id, district_id, unit_id, name, active)
SELECT 9000 + n, (ARRAY[9001, 9002, 9003, 9004, 9001, 9002, 9003, 9004, 9001])[n], 9000 + n, 'Test Area ' || n, true
FROM generate_series(1, 9) AS n
ON CONFLICT DO NOTHING;

INSERT INTO public.area_units (area_id, unit_id, primary_unit, active)
SELECT 9000 + n, 9000 + n, true, true FROM generate_series(1, 9) AS n
UNION ALL
SELECT 9004, 9010, false, true   -- the one area with two wards or branches
ON CONFLICT DO NOTHING;

-- 2. Missionaries: two in every area (area n has missionaries 2n-1 and 2n) -------------------------------------------
INSERT INTO public.missionaries (id, missionary_number, first_name, last_name, display_name, missionary_type, status,
                                 arrival_date, email)
SELECT 9000 + n, 'SEED-' || lpad(n::text, 2, '0'), 'Seed', 'Elder' || lpad(n::text, 2, '0'),
       'Elder Seed' || lpad(n::text, 2, '0'), 'Elder', 'Active', CURRENT_DATE - 200,
       'seed-elder-' || lpad(n::text, 2, '0') || '@example.org'
FROM generate_series(1, 18) AS n
ON CONFLICT DO NOTHING;

INSERT INTO public.missionary_assignments (id, missionary_id, area_id, start_date)
SELECT 9000 + n, 9000 + n, 9000 + ((n + 1) / 2), DATE '2000-01-01' FROM generate_series(1, 18) AS n
ON CONFLICT DO NOTHING;

-- 3. Leaders -------------------------------------------------------------------------------------------------------
--   AP  Elder Seed05 (area 3, zone South, account 05)      ZL  Elder Seed03 (area 2, zone North, account 04)
--   DL  Elder Seed09 (area 5, North One, account 03)       DL  Elder Seed11 (area 6, North Two, NO account)
--   STL Elder Seed17 (area 9, zone North, NO account)
INSERT INTO public.leadership_assignments (id, missionary_id, role, district_id, zone_id, mission_id, start_date) VALUES
    (9001, 9005, 'AP',  NULL, NULL, 2,    DATE '2000-01-01'),
    (9002, 9003, 'ZL',  NULL, 9001, NULL, DATE '2000-01-01'),
    (9003, 9009, 'DL',  9001, NULL, NULL, DATE '2000-01-01'),
    (9004, 9011, 'DL',  9002, NULL, NULL, DATE '2000-01-01'),
    (9005, 9017, 'STL', NULL, 9001, NULL, DATE '2000-01-01')
ON CONFLICT DO NOTHING;

-- 4. Sign-ins ---------------------------------------------------------------------------------------------------------
-- The ids end in 5eedNN. Account 01 has the lowest id on purpose: test_management takes the lowest profile id as "the
-- person" and a plain missionary is the safest one for it.
--   01 plain Elder Seed01 (area 1)   02 plain Elder Seed02 (area 1, the same area: two companions with sign-ins)
--   03 DL    04 ZL    05 AP    06 Office staff    07 President staff    08 Data Analyst staff
--   09 plain Elder Seed13 (area 7, zone South): the "outsider" of the planning tests (no access to areas 1 to 6)
INSERT INTO auth.users (id, instance_id, aud, role, email, encrypted_password, email_confirmed_at, created_at, updated_at)
SELECT v.id::uuid, '00000000-0000-0000-0000-000000000000'::uuid, 'authenticated', 'authenticated', v.email,
       '$2a$10$' || repeat('x', 53),   -- not a bcrypt hash of any password: nobody can sign in with these accounts
       now(), now(), now()
FROM (VALUES
    ('00000000-0000-4000-8000-0000005eed01', 'seed-elder-01@example.org'),
    ('00000000-0000-4000-8000-0000005eed02', 'seed-elder-02@example.org'),
    ('00000000-0000-4000-8000-0000005eed03', 'seed-elder-09@example.org'),
    ('00000000-0000-4000-8000-0000005eed04', 'seed-elder-03@example.org'),
    ('00000000-0000-4000-8000-0000005eed05', 'seed-elder-05@example.org'),
    ('00000000-0000-4000-8000-0000005eed06', 'seed-office@example.org'),
    ('00000000-0000-4000-8000-0000005eed07', 'seed-president@example.org'),
    ('00000000-0000-4000-8000-0000005eed08', 'seed-analyst@example.org'),
    ('00000000-0000-4000-8000-0000005eed09', 'seed-elder-13@example.org')
) AS v(id, email)
ON CONFLICT DO NOTHING;

INSERT INTO public.user_profiles (id, missionary_id, app_role, active, display_name, home_mission_id) VALUES
    ('00000000-0000-4000-8000-0000005eed01', 9001, 'MISSIONARY', true, NULL, NULL),
    ('00000000-0000-4000-8000-0000005eed02', 9002, 'MISSIONARY', true, NULL, NULL),
    ('00000000-0000-4000-8000-0000005eed03', 9009, 'DL',         true, NULL, NULL),
    ('00000000-0000-4000-8000-0000005eed04', 9003, 'ZL',         true, NULL, NULL),
    ('00000000-0000-4000-8000-0000005eed05', 9005, 'AP',         true, NULL, NULL),
    ('00000000-0000-4000-8000-0000005eed06', NULL, 'OFFICE',     true, 'Seed Office',    2),
    ('00000000-0000-4000-8000-0000005eed07', NULL, 'PRESIDENT',  true, 'Seed President', 2),
    ('00000000-0000-4000-8000-0000005eed08', NULL, 'DATA_ADMIN', true, 'Seed Analyst',   2),
    ('00000000-0000-4000-8000-0000005eed09', 9013, 'MISSIONARY', true, NULL, NULL)
ON CONFLICT DO NOTHING;

-- 5. Reporting weeks: this week and the 14 finished weeks before it -------------------------------------------------
DO $$
BEGIN
    PERFORM public.ensure_reporting_week(public.current_reporting_sunday() - 7 * k) FROM generate_series(0, 14) AS k;
END $$;

-- 6. The finished weekly plans of the areas 4 to 9 (one plan for the ward of the area, submitted) ------------------------
INSERT INTO public.weekly_area_reports (
    area_id, reporting_week_id, unit_id, status, submitted_at,
    friends_found_actual, friends_found_goal, lessons_with_friends_actual, lessons_with_friends_goal,
    lessons_with_members_actual, lessons_with_members_goal, sacrament_attendance_actual, sacrament_attendance_goal,
    first_time_sacrament_actual, baptismal_dates_actual, baptismal_dates_goal, new_member_sacrament_actual,
    new_member_sacrament_goal, follow_up_lessons_actual, follow_up_lessons_goal, baptisms_confirmations_actual,
    baptisms_confirmations_goal)
SELECT a.id, rw.id, a.unit_id, 'SUBMITTED', (rw.sunday + TIME '18:00') AT TIME ZONE 'Europe/Berlin',
       2 + ((a.id * 7 + g.k * 3) % 6),   3 + ((a.id * 7 + g.k * 3) % 6) + (a.id % 2),
       4 + ((a.id + g.k) % 5),           6 + ((a.id + g.k) % 5),
       3 + ((a.id * 3 + g.k) % 4),       4 + ((a.id * 3 + g.k) % 4),
       6 + ((a.id + g.k * 2) % 7),       8 + ((a.id + g.k * 2) % 7),
       (a.id + g.k) % 3,
       (a.id + g.k) % 3,                 1 + ((a.id + g.k) % 3),
       (a.id * 2 + g.k) % 4,             1 + ((a.id * 2 + g.k) % 4),
       2 + ((a.id + g.k * 5) % 4),       3 + ((a.id + g.k * 5) % 4),
       (a.id + g.k) % 2,                 1 + ((a.id + g.k) % 2)
FROM public.areas a
CROSS JOIN generate_series(1, 14) AS g(k)
JOIN public.reporting_weeks rw ON rw.sunday = public.current_reporting_sunday() - 7 * g.k
WHERE a.id BETWEEN 9004 AND 9009
ON CONFLICT DO NOTHING;

-- Planning answers the Archetypal Health and Call-ins views read, and one text answer (the DA Management test of the
-- planning questions needs at least one answered question).
INSERT INTO public.weekly_planning_answers (weekly_area_report_id, question_key, answer_number)
SELECT r.id, q.key, 1 + ((r.id * q.salt) % 5)
FROM public.weekly_area_reports r
CROSS JOIN (VALUES
    ('sacrament_first_time_first_week', 3), ('member_meals_active_actual', 5), ('member_meals_less_active_actual', 7),
    ('member_meals_part_member_actual', 11), ('member_visits_active_actual', 13), ('member_visits_less_active_actual', 17),
    ('member_visits_part_member_actual', 19), ('member_referral_asks_actual', 23), ('youth_activities_actual', 29),
    ('service_hours_actual', 31), ('less_active_sacrament_actual', 37)
) AS q(key, salt)
WHERE r.area_id BETWEEN 9004 AND 9009
ON CONFLICT DO NOTHING;

INSERT INTO public.weekly_planning_answers (weekly_area_report_id, question_key, answer_text)
SELECT r.id, 'weekly_action_plan', 'Visit the test families and invite them to church.'
FROM public.weekly_area_reports r
WHERE r.area_id BETWEEN 9004 AND 9009
ON CONFLICT DO NOTHING;

-- 7. People: 12 new members, 12 friends with a baptismal date, 12 high-potential friends a week ----------------------
-- The same spread for the three groups (person number, area): three in each of the areas 5, 6 and 7, one in area 8 and
-- two in area 4. So every district has three, and the areas 4 and 8 stay under 3 (the dashboards hide small numbers).
CREATE TEMP TABLE seed_spread ON COMMIT DROP AS
SELECT n, area_id FROM (VALUES
    (1, 9005), (2, 9005), (3, 9005), (4, 9006), (5, 9006), (6, 9006),
    (7, 9007), (8, 9007), (9, 9007), (10, 9008), (11, 9004), (12, 9004)
) AS s(n, area_id);

INSERT INTO public.new_members (id, area_id, first_name, last_name, display_name, baptism_date, confirmation_date,
                                baptismal_date_extended, finding_source, active, stake_id, unit_id, follow_up_status)
SELECT 9000 + s.n, s.area_id, 'Nm' || lpad(s.n::text, 2, '0'), 'Seedling', 'Nm' || lpad(s.n::text, 2, '0') || ' Seedling',
       CURRENT_DATE - (40 + 8 * s.n), CURRENT_DATE - (39 + 8 * s.n), CURRENT_DATE - (70 + 8 * s.n), 'Member/Member', true,
       9001, s.area_id, 'current'
FROM seed_spread s
ON CONFLICT DO NOTHING;

INSERT INTO public.new_member_area_assignments (new_member_id, area_id, start_date, unit_id)
SELECT nm.id, nm.area_id, nm.baptism_date, nm.unit_id
FROM public.new_members nm
WHERE nm.id BETWEEN 9001 AND 9012
ON CONFLICT DO NOTHING;

INSERT INTO public.baptismal_date_people (id, first_name, last_name, display_name, finding_source)
SELECT 9000 + s.n, 'Bd' || lpad(s.n::text, 2, '0'), 'Seedfriend', 'Bd' || lpad(s.n::text, 2, '0') || ' Seedfriend', 'Member/Member'
FROM seed_spread s
ON CONFLICT DO NOTHING;

INSERT INTO public.baptismal_date_person_area_assignments (baptismal_date_person_id, area_id, start_date, unit_id)
SELECT 9000 + s.n, s.area_id, CURRENT_DATE - 120, s.area_id
FROM seed_spread s
ON CONFLICT DO NOTHING;

-- On the plans: a new member from the week of the baptism on, the friends and the high-potential friends every week.
INSERT INTO public.weekly_new_members (weekly_area_report_id, new_member_id, display_order, lessons_actual, lessons_goal,
                                       how_are_they_doing, at_church_this_sunday, has_calling, reading, praying,
                                       member_involvement, discussed_in_gemiko)
SELECT r.id, nm.id, s.n, (r.id + nm.id) % 4, 3, 'Doing well.', (r.id + nm.id) % 2 = 0,
       CASE WHEN (r.id + nm.id) % 3 = 0 THEN 'yes' ELSE 'no' END, (r.id + nm.id) % 3 <> 0, (r.id + nm.id) % 4 <> 0,
       (r.id + nm.id) % 2 = 1, (r.id + nm.id) % 5 = 0
FROM seed_spread s
JOIN public.new_members nm ON nm.id = 9000 + s.n
JOIN public.weekly_area_reports r ON r.area_id = s.area_id AND r.unit_id = s.area_id
JOIN public.reporting_weeks rw ON rw.id = r.reporting_week_id
WHERE rw.sunday >= nm.baptism_date
  AND NOT EXISTS (SELECT 1 FROM public.weekly_new_members w WHERE w.weekly_area_report_id = r.id AND w.new_member_id = nm.id);

INSERT INTO public.weekly_baptismal_date_friends (weekly_area_report_id, baptismal_date_person_id, display_order,
                                                  baptismal_date_set_on, current_baptismal_date, reading, praying,
                                                  at_church_this_sunday, keeping_commandments, member_involvement)
SELECT r.id, 9000 + s.n, s.n, rw.sunday - 14, rw.sunday + 21, (r.id + s.n) % 2 = 0, (r.id + s.n) % 3 <> 0,
       (r.id + s.n) % 2 = 1, (r.id + s.n) % 4 <> 0, (r.id + s.n) % 5 = 0
FROM seed_spread s
JOIN public.weekly_area_reports r ON r.area_id = s.area_id AND r.unit_id = s.area_id
JOIN public.reporting_weeks rw ON rw.id = r.reporting_week_id
WHERE NOT EXISTS (SELECT 1 FROM public.weekly_baptismal_date_friends w
                  WHERE w.weekly_area_report_id = r.id AND w.baptismal_date_person_id = 9000 + s.n);

INSERT INTO public.weekly_high_potential_friends (weekly_area_report_id, display_order, name, at_church_this_sunday, notes)
SELECT r.id, s.n, 'Hp' || lpad(s.n::text, 2, '0') || ' Seedperson', (r.id + s.n) % 2 = 0, 'Invented for the tests.'
FROM seed_spread s
JOIN public.weekly_area_reports r ON r.area_id = s.area_id AND r.unit_id = s.area_id
WHERE NOT EXISTS (SELECT 1 FROM public.weekly_high_potential_friends h
                  WHERE h.weekly_area_report_id = r.id AND h.name = 'Hp' || lpad(s.n::text, 2, '0') || ' Seedperson');

-- 8. Counters: new rows made by the tests must not collide with the fixed ids above ---------------------------------
DO $$
DECLARE
    t text;
    seq text;
    top bigint;
BEGIN
    FOREACH t IN ARRAY ARRAY['missions', 'stakes', 'units', 'zones', 'districts', 'areas', 'area_units', 'missionaries',
                             'missionary_assignments', 'leadership_assignments', 'new_members',
                             'new_member_area_assignments', 'baptismal_date_people',
                             'baptismal_date_person_area_assignments'] LOOP
        seq := pg_get_serial_sequence('public.' || t, 'id');
        IF seq IS NULL THEN
            CONTINUE;
        END IF;
        EXECUTE format('SELECT GREATEST(coalesce((SELECT max(id) FROM public.%I), 1), (SELECT last_value FROM %s))', t, seq) INTO top;
        PERFORM setval(seq, top);
    END LOOP;
END $$;

-- 9. The companionships (one for each area with missionaries), as the server's daily job makes them -------------------
DO $$
BEGIN
    PERFORM public.sync_current_companionships();
EXCEPTION WHEN insufficient_privilege THEN
    RAISE NOTICE 'sync_current_companionships() needs supabase_admin or postgres: run SELECT public.sync_current_companionships(); as one of them.';
END $$;

COMMIT;

-- A short count to read (all should be at least these numbers).
SELECT (SELECT count(*) FROM public.areas WHERE id BETWEEN 9001 AND 9009) AS areas,                   -- 9
       (SELECT count(*) FROM public.missionaries WHERE id BETWEEN 9001 AND 9018) AS missionaries,       -- 18
       (SELECT count(*) FROM public.user_profiles WHERE id::text LIKE '00000000-0000-4000-8000-0000005eed%') AS sign_ins,  -- 9
       (SELECT count(*) FROM public.weekly_area_reports WHERE area_id BETWEEN 9004 AND 9009) AS plans,   -- 84
       (SELECT count(*) FROM public.weekly_new_members) AS plan_new_members;
