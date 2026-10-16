-- Migration 058 (Oct 2026, round 16): two duplicate Data uploads are deleted for real: "Referral archive" and "Rates".
-- Run on Beta only, as supabase_admin. Back up first (CLAUDE.md, "Before any database change"). This is the SECOND database change
-- of release 1.0.9 (057 was the first: Area data and Geo data became one upload).
--
-- Why: the owner asked to check whether upload cards duplicate each other (docs/handoff/round16/uploads-duplicates.md).
--  * Referral archive (batch kind REFERRAL_ARCHIVE, public.referral_archive_weeks): the FindeChristus referral archive since 2022.
--    FindeChristus is archived (038) and the Finding export has the same referrals for its weeks. The card was already hidden.
--  * Rates (batch kind RATES, public.finding_rate_weeks): teaching and contact rates per zone and week. Nothing in the repository read
--    dashboards.finding_rate_week.
--
-- What changes:
-- 1. Import history: the batches of kind REFERRAL_ARCHIVE and RATES are DELETED (the rows they recorded, and the uploaded rows, go with
--    them: ON DELETE CASCADE) and both kinds are taken out of the allowed batch kinds. Their rows could not be undone any more (the
--    tables are gone). The Finding export, Zone history, Baptism history and the other batches are untouched.
-- 2. dashboards.archetype_area_week (Archetypal Health) counted FindeChristus referrals through dashboards.findechristus_referrals_week,
--    which mixed the Finding export with the referral archive. It now counts them from the Finding export only
--    (dashboards.finding_area_week: category FindeChristus, people found). Weeks before the first Finding export lose the archived
--    referral counts (the owner accepted this); the columns of the view are unchanged.
-- 3. public.data_upload_week_batches (which upload counts for a week) no longer knows the two kinds.
-- 4. Dropped: dashboards.findechristus_referrals_week, dashboards.referral_archive_week, dashboards.finding_rate_week and the tables
--    public.referral_archive_weeks and public.finding_rate_weeks (with their data). A hand-made DataEase dashboard that reads one of
--    these three views stops working.
-- No person is stored in any of these tables: only counts, rates and labels of places.
-- Not changed: Baptism history (public.baptism_history_weeks and dashboards.baptism_history_week stay; see docs/handoff/round16/item8-dupes.md).
--
-- Apply (back up Beta first; after 057). Join the lines with plain line feeds:
--   (Get-Content portal-api/migrations/058_delete_referral_archive_and_rates.sql) -join "`n" |
--     docker exec -i gfm-beta-supabase-db-1 psql -U supabase_admin -d postgres -v ON_ERROR_STOP=1
-- (Ubuntu server: psql as supabase_admin in the db container, the same way.) Then run 019_restrict_public_functions.sql
-- again as a check, as after every migration (it must end with COMMIT). Deploy step: that re-run is part of the deploy.
-- Apply this BEFORE the new DA Management image (it no longer knows the two uploads) and, on an update, together with it.
-- Safe to run again: DROP ... IF EXISTS, CREATE OR REPLACE VIEW, then a check that stops on any problem.
-- Rollback: 058_delete_referral_archive_and_rates_rollback.sql (makes the empty tables and views again; the deleted batches and
-- all uploaded rows do NOT come back: restore a backup for that).
BEGIN;
SET LOCAL lock_timeout = '10s';

DO $$
BEGIN
  IF session_user NOT IN ('supabase_admin', 'postgres') THEN
    RAISE EXCEPTION 'Run this file as supabase_admin (see its header), not as %.', session_user;
  END IF;
  IF to_regclass('dashboards.archetype_area_week') IS NULL OR to_regclass('dashboards.finding_area_week') IS NULL
     OR to_regclass('public.data_upload_week_batches') IS NULL OR to_regclass('public.roster_import_batches') IS NULL THEN
    RAISE EXCEPTION 'Apply the data uploads (033) and archetypes (034) migrations first.';
  END IF;
  IF to_regclass('public.baptism_history_weeks') IS NULL OR to_regclass('public.zone_history_weeks') IS NULL THEN
    RAISE EXCEPTION 'Apply 033_data_uploads.sql first.';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'gfm_dashboard_reader') THEN
    RAISE EXCEPTION 'The role gfm_dashboard_reader is missing (migration 018).';
  END IF;
END $$;

-- 1. Import history: the two kinds go (uploaded rows and recorded rows go with the batches). The constraint belongs to
--    supabase_admin's table, so this runs before the switch to postgres below. The other kinds are read from the constraint and kept.
DELETE FROM public.roster_import_batches WHERE kind IN ('REFERRAL_ARCHIVE', 'RATES');
DO $$
DECLARE
  kinds text[];
  cname name;
BEGIN
  -- The kind constraint is found by what it says (a list that holds 'TRANSFER'), not by its name: an older database may have named it differently.
  SELECT c.conname INTO cname
  FROM pg_constraint c
  WHERE c.conrelid = 'public.roster_import_batches'::regclass AND c.contype = 'c' AND pg_get_constraintdef(c.oid) LIKE '%''TRANSFER''%'
  ORDER BY c.conname LIMIT 1;
  SELECT array_agg(DISTINCT m[1] ORDER BY m[1]) INTO kinds
  FROM pg_constraint c
  CROSS JOIN LATERAL regexp_matches(pg_get_constraintdef(c.oid), '''([A-Z_]+)''', 'g') AS m
  WHERE c.conrelid = 'public.roster_import_batches'::regclass AND c.conname = cname;
  IF kinds IS NULL OR NOT ('TRANSFER' = ANY (kinds)) THEN
    RAISE EXCEPTION 'The list of batch kinds could not be read from the kind constraint of roster_import_batches (found: %).', kinds;
  END IF;
  IF 'REFERRAL_ARCHIVE' = ANY (kinds) OR 'RATES' = ANY (kinds) THEN
    kinds := array_remove(array_remove(kinds, 'REFERRAL_ARCHIVE'), 'RATES');
    EXECUTE format('ALTER TABLE public.roster_import_batches DROP CONSTRAINT %I', cname);
    EXECUTE format('ALTER TABLE public.roster_import_batches ADD CONSTRAINT %I CHECK (kind IN (%s))',
      cname, (SELECT string_agg(quote_literal(k), ', ' ORDER BY k) FROM unnest(kinds) k));
  END IF;
END $$;

-- Everything below belongs to postgres, like the tables and views of 033 (DA Management connects as postgres).
SET LOCAL ROLE postgres;

-- 2a. A view that has MORE or other columns than the new definition cannot be replaced by CREATE OR REPLACE VIEW ("cannot drop columns
--     from view"). The real server's dashboards.archetype_area_week still has two old social-media columns (the first two after lessons_asked_referral)
--     (they came from migration 034; the social-media section was deleted in 056, so they are meant to go).
--     So: when the columns of a view are not the start of the new column list, its rights are remembered, the view is dropped
--     (WITHOUT CASCADE: if another object reads it, this file stops with a clear message and nothing is changed) and made again below.
DO $$
DECLARE
  v record;
  have text[];
  acl text;
BEGIN
  FOR v IN SELECT * FROM (VALUES
      ('dashboards.archetype_area_week', ARRAY['sunday', 'week', 'reporting_week_id', 'mission_id', 'zone_id', 'zone', 'district_id', 'district', 'area_id', 'area', 'reports', 'friends_found', 'lessons_with_friends', 'follow_up_lessons', 'members_at_lessons', 'baptismal_dates', 'baptisms_confirmations', 'sacrament_attendance', 'first_time_sacrament', 'new_member_sacrament', 'first_time_first_week_sacrament', 'member_meals_active', 'member_meals_less_active', 'member_meals_part_member', 'member_visits_active', 'member_visits_less_active', 'member_visits_part_member', 'member_referral_asks', 'lessons_asked_referral', 'youth_activities', 'service_hours', 'less_active_sacrament', 'new_members_on_plan', 'new_member_lessons', 'new_members_at_church', 'new_member_lessons_per_member', 'new_member_sacrament_share', 'findechristus_referrals', 'finding_people_found', 'finding_people_reached', 'finding_first_lessons', 'baptism_records']),
      ('public.data_upload_week_batches', ARRAY['kind', 'mission_id', 'sunday', 'batch_id'])
    ) AS t(name, want) LOOP
    IF to_regclass(v.name) IS NULL THEN CONTINUE; END IF;
    SELECT array_agg(attname::text ORDER BY attnum) INTO have FROM pg_attribute
    WHERE attrelid = v.name::regclass AND attnum > 0 AND NOT attisdropped;
    IF cardinality(have) <= cardinality(v.want) AND have = v.want[1:cardinality(have)] THEN CONTINUE; END IF;
    SELECT coalesce(string_agg(CASE WHEN a.grantee = 0 THEN 'PUBLIC' ELSE pg_get_userbyid(a.grantee) END || '|' || a.privilege_type || '|' || a.is_grantable, ';'), '')
      INTO acl FROM pg_class c, aclexplode(c.relacl) a WHERE c.oid = v.name::regclass;
    PERFORM set_config('gfm.view_acl_' || replace(v.name, '.', '_'), acl, true);
    RAISE NOTICE 'Dropping % (columns: %) to make it again with the new column list.', v.name, have;
    BEGIN
      EXECUTE format('DROP VIEW %s', v.name);
    EXCEPTION WHEN dependent_objects_still_exist THEN
      RAISE EXCEPTION 'Stopped, nothing was changed: another object reads %. Drop or change that object first (%).', v.name, SQLERRM;
    END;
  END LOOP;
END $$;

-- 2. Archetypal Health counts FindeChristus referrals from the Finding export only. Same columns as before.
CREATE OR REPLACE VIEW dashboards.archetype_area_week AS
 WITH plans AS MATERIALIZED (
         SELECT k_1.week,
            k_1.sunday,
            k_1.reporting_week_id,
            k_1.mission_id,
            k_1.zone_id,
            k_1.zone,
            k_1.district_id,
            k_1.district,
            k_1.area_id,
            k_1.area,
            k_1.reports,
            k_1.submitted_reports,
            k_1.units_reporting,
            k_1.friends_found_actual,
            k_1.friends_found_goal,
            k_1.friends_found_previous_goal,
            k_1.baptisms_confirmations_actual,
            k_1.baptisms_confirmations_goal,
            k_1.baptisms_confirmations_previous_goal,
            k_1.baptismal_dates_actual,
            k_1.baptismal_dates_goal,
            k_1.baptismal_dates_previous_goal,
            k_1.sacrament_attendance_actual,
            k_1.sacrament_attendance_goal,
            k_1.sacrament_attendance_previous_goal,
            k_1.members_at_lessons_actual,
            k_1.members_at_lessons_goal,
            k_1.members_at_lessons_previous_goal,
            k_1.new_member_sacrament_actual,
            k_1.new_member_sacrament_goal,
            k_1.new_member_sacrament_previous_goal,
            k_1.first_time_sacrament_actual,
            k_1.lessons_with_friends_actual,
            k_1.lessons_with_friends_goal,
            k_1.follow_up_lessons_actual,
            k_1.follow_up_lessons_goal
           FROM dashboards.kpi_area_total_week k_1
          WHERE k_1.reports > 0
        ), extra AS MATERIALIZED (
         SELECT archetype_plan_rows.reporting_week_id,
            archetype_plan_rows.area_id,
            archetype_plan_rows.first_time_first_week_sacrament,
            archetype_plan_rows.member_meals_active,
            archetype_plan_rows.member_meals_less_active,
            archetype_plan_rows.member_meals_part_member,
            archetype_plan_rows.member_visits_active,
            archetype_plan_rows.member_visits_less_active,
            archetype_plan_rows.member_visits_part_member,
            archetype_plan_rows.member_referral_asks,
            archetype_plan_rows.lessons_asked_referral,
            archetype_plan_rows.youth_activities,
            archetype_plan_rows.service_hours,
            archetype_plan_rows.less_active_sacrament,
            archetype_plan_rows.new_members_on_plan,
            archetype_plan_rows.new_member_lessons,
            archetype_plan_rows.new_members_at_church
           FROM dashboards.archetype_plan_rows() archetype_plan_rows
        ), fc AS (
         SELECT f.sunday,
            f.area_id,
            sum(f.people_found) AS referrals
           FROM dashboards.finding_area_week f
          WHERE f.findechristus AND f.people_found > 0
          GROUP BY f.sunday, f.area_id
        ), fc_weeks AS (
         SELECT DISTINCT f.sunday
           FROM dashboards.finding_area_week f
          WHERE f.findechristus AND f.people_found > 0
        ), finding AS (
         SELECT f.sunday,
            f.area_id,
            sum(f.people_found) AS people_found,
            sum(f.people_reached) AS people_reached,
            sum(f.first_lessons) AS first_lessons
           FROM dashboards.finding_area_week f
          GROUP BY f.sunday, f.area_id
        ), finding_weeks AS (
         SELECT DISTINCT f.sunday
           FROM dashboards.finding_area_week f
        ), baptisms AS (
         SELECT b_1.sunday,
            b_1.area_id,
            sum(b_1.baptisms) AS baptisms
           FROM dashboards.baptism_history_week b_1
          GROUP BY b_1.sunday, b_1.area_id
        ), baptism_weeks AS (
         SELECT DISTINCT b_1.sunday
           FROM dashboards.baptism_history_week b_1
        )
 SELECT k.sunday,
    k.week,
    k.reporting_week_id,
    k.mission_id,
    k.zone_id,
    k.zone,
    k.district_id,
    k.district,
    k.area_id,
    k.area,
    k.reports,
    k.friends_found_actual AS friends_found,
    k.lessons_with_friends_actual AS lessons_with_friends,
    k.follow_up_lessons_actual AS follow_up_lessons,
    k.members_at_lessons_actual AS members_at_lessons,
    k.baptismal_dates_actual AS baptismal_dates,
    k.baptisms_confirmations_actual AS baptisms_confirmations,
    k.sacrament_attendance_actual AS sacrament_attendance,
    k.first_time_sacrament_actual AS first_time_sacrament,
    k.new_member_sacrament_actual AS new_member_sacrament,
    e.first_time_first_week_sacrament,
    e.member_meals_active,
    e.member_meals_less_active,
    e.member_meals_part_member,
    e.member_visits_active,
    e.member_visits_less_active,
    e.member_visits_part_member,
    e.member_referral_asks,
    e.lessons_asked_referral,
    e.youth_activities,
    e.service_hours,
    e.less_active_sacrament,
    COALESCE(e.new_members_on_plan, 0::bigint) AS new_members_on_plan,
    e.new_member_lessons,
    e.new_members_at_church,
        CASE
            WHEN e.new_members_on_plan > 0 THEN round(COALESCE(e.new_member_lessons, 0::numeric) / e.new_members_on_plan::numeric, 4)
            ELSE NULL::numeric
        END AS new_member_lessons_per_member,
        CASE
            WHEN e.new_members_on_plan > 0 THEN round(COALESCE(e.new_members_at_church, 0::bigint)::numeric / e.new_members_on_plan::numeric, 4)
            ELSE NULL::numeric
        END AS new_member_sacrament_share,
        CASE
            WHEN fw.sunday IS NOT NULL THEN COALESCE(fc.referrals, 0::numeric)
            ELSE NULL::numeric
        END AS findechristus_referrals,
        CASE
            WHEN nw.sunday IS NOT NULL THEN COALESCE(fi.people_found, 0::numeric)
            ELSE NULL::numeric
        END AS finding_people_found,
        CASE
            WHEN nw.sunday IS NOT NULL THEN COALESCE(fi.people_reached, 0::numeric)
            ELSE NULL::numeric
        END AS finding_people_reached,
        CASE
            WHEN nw.sunday IS NOT NULL THEN COALESCE(fi.first_lessons, 0::numeric)
            ELSE NULL::numeric
        END AS finding_first_lessons,
        CASE
            WHEN bw.sunday IS NOT NULL THEN COALESCE(b.baptisms, 0::bigint)
            ELSE NULL::bigint
        END AS baptism_records
   FROM plans k
     LEFT JOIN extra e ON e.reporting_week_id = k.reporting_week_id AND e.area_id = k.area_id
     LEFT JOIN fc_weeks fw ON fw.sunday = k.sunday
     LEFT JOIN fc ON fc.sunday = k.sunday AND fc.area_id = k.area_id
     LEFT JOIN finding_weeks nw ON nw.sunday = k.sunday
     LEFT JOIN finding fi ON fi.sunday = k.sunday AND fi.area_id = k.area_id
     LEFT JOIN baptism_weeks bw ON bw.sunday = k.sunday
     LEFT JOIN baptisms b ON b.sunday = k.sunday AND b.area_id = k.area_id;;

-- 3. Which upload counts for a week: the kinds that are left.
CREATE OR REPLACE VIEW public.data_upload_week_batches AS
 WITH weeks AS (
         SELECT 'ZONE_HISTORY'::text AS kind,
            zone_history_weeks.mission_id,
            zone_history_weeks.sunday,
            zone_history_weeks.batch_id
           FROM zone_history_weeks
        UNION
         SELECT 'BAPTISMS'::text AS text,
            baptism_history_weeks.mission_id,
            baptism_history_weeks.sunday,
            baptism_history_weeks.batch_id
           FROM baptism_history_weeks
        )
 SELECT DISTINCT ON (w.kind, w.mission_id, w.sunday) w.kind,
    w.mission_id,
    w.sunday,
    w.batch_id
   FROM weeks w
     JOIN roster_import_batches b ON b.id = w.batch_id AND b.status = 'APPLIED'::text
  ORDER BY w.kind, w.mission_id, w.sunday, b.created_at DESC, b.id DESC;

-- 3a. Rights of a view that was dropped and made again above: the remembered rights come back (the owner is postgres, as before).
DO $$
DECLARE
  v text;
  r text[];
  acl text;
  one text;
BEGIN
  FOREACH v IN ARRAY ARRAY['dashboards.archetype_area_week', 'public.data_upload_week_batches'] LOOP
    acl := current_setting('gfm.view_acl_' || replace(v, '.', '_'), true);
    IF acl IS NULL OR acl = '' THEN CONTINUE; END IF;
    FOREACH one IN ARRAY string_to_array(acl, ';') LOOP
      r := string_to_array(one, '|');
      IF r[1] = 'postgres' THEN CONTINUE; END IF;
      EXECUTE format('GRANT %s ON %s TO %s%s', r[2], v, CASE WHEN r[1] = 'PUBLIC' THEN 'PUBLIC' ELSE quote_ident(r[1]) END,
                     CASE WHEN r[3] = 'true' THEN ' WITH GRANT OPTION' ELSE '' END);
    END LOOP;
  END LOOP;
END $$;

-- 4. The views and tables of the two uploads are gone.
DROP VIEW IF EXISTS dashboards.findechristus_referrals_week;
DROP VIEW IF EXISTS dashboards.referral_archive_week;
DROP VIEW IF EXISTS dashboards.finding_rate_week;
DROP TABLE IF EXISTS public.referral_archive_weeks;
DROP TABLE IF EXISTS public.finding_rate_weeks;

-- Rights: the reader keeps the view (CREATE OR REPLACE keeps them); stated again to be sure.
REVOKE ALL ON dashboards.archetype_area_week FROM PUBLIC, anon, authenticated, service_role;
GRANT SELECT ON dashboards.archetype_area_week TO gfm_dashboard_reader;

-- Check.
DO $$
DECLARE
  found text;
BEGIN
  SELECT string_agg(n.nspname || '.' || c.relname, ', ') INTO found
  FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
  WHERE (n.nspname = 'dashboards' AND c.relname IN ('findechristus_referrals_week', 'referral_archive_week', 'finding_rate_week'))
     OR (n.nspname = 'public' AND c.relname IN ('referral_archive_weeks', 'finding_rate_weeks'));
  IF found IS NOT NULL THEN RAISE EXCEPTION 'Check failed: still there: %', found; END IF;
  IF EXISTS (SELECT 1 FROM public.roster_import_batches WHERE kind IN ('REFERRAL_ARCHIVE', 'RATES'))
     OR EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid = 'public.roster_import_batches'::regclass AND contype = 'c'
                AND (pg_get_constraintdef(oid) LIKE '%REFERRAL_ARCHIVE%' OR pg_get_constraintdef(oid) LIKE '%RATES%')) THEN
    RAISE EXCEPTION 'Check failed: the batch kinds REFERRAL_ARCHIVE or RATES are still there.';
  END IF;
  IF EXISTS (SELECT 1 FROM public.roster_import_changes WHERE table_name IN ('referral_archive_weeks', 'finding_rate_weeks')) THEN
    RAISE EXCEPTION 'Check failed: recorded rows of the two tables are still in Import history.';
  END IF;
  IF NOT has_table_privilege('gfm_dashboard_reader', 'dashboards.archetype_area_week', 'SELECT') THEN
    RAISE EXCEPTION 'Check failed: gfm_dashboard_reader cannot read dashboards.archetype_area_week';
  END IF;
  SELECT string_agg(r, ', ') INTO found FROM unnest(ARRAY['public', 'anon', 'authenticated', 'service_role']) r
  WHERE has_table_privilege(r, 'dashboards.archetype_area_week', 'SELECT');
  IF found IS NOT NULL THEN RAISE EXCEPTION 'Check failed: these may read dashboards.archetype_area_week: %', found; END IF;
  IF (SELECT pg_get_userbyid(relowner) FROM pg_class WHERE oid = to_regclass('dashboards.archetype_area_week')) <> 'postgres'
     OR coalesce((SELECT reloptions FROM pg_class WHERE oid = to_regclass('dashboards.archetype_area_week')), '{}') @> ARRAY['security_invoker=true'] THEN
    RAISE EXCEPTION 'Check failed: dashboards.archetype_area_week is not owned by postgres or is security_invoker.';
  END IF;
  IF pg_get_viewdef('dashboards.archetype_area_week'::regclass) LIKE '%findechristus_referrals_week%' THEN
    RAISE EXCEPTION 'Check failed: dashboards.archetype_area_week still reads the dropped view.';
  END IF;
END $$;

COMMIT;

-- Verify (read-only, after applying), as postgres:
--   docker exec gfm-beta-supabase-db-1 psql -U postgres -d postgres -c 'BEGIN READ ONLY' -c 'SET LOCAL ROLE gfm_dashboard_reader' -c 'SELECT count(*), count(findechristus_referrals) FROM dashboards.archetype_area_week' -c 'ROLLBACK'
