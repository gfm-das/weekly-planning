-- Removes old database parts that nothing uses, and rights nobody uses. Run on Beta only, as supabase_admin.
--
-- Why: Beta was built in Supabase Studio before the portal, and several of its early parts were never used or were
-- replaced. Some of them were a risk: the public key that every portal page carries (role anon), and any signed-in
-- account (sign-up is open), could read the names and notes of people on submitted plans through views that skip
-- row-level security (*_clean), read and even change the historical spreadsheets' people (import_weekly_*, 2766
-- New Members with names), the old roster staging table (missionary names and phone numbers) and the area-to-ward
-- table. The hotfix of 27 Sep 2026, 22:50 (docs/handoff/11_KNOWN_ISSUES.md) already took those rights away from
-- anon, authenticated and grafana_readonly. This file removes the parts themselves and the other rights nobody uses,
-- so that a new table or view is not open to the public key again before anyone decides it should be.
-- The proof that each part is unused is in docs/handoff/round3/cleanup-unused.md: this repository (all code,
-- migrations, tests, Grafana dashboards), the live Grafana dashboard, every Appsmith Beta action, JS object and page
-- (published and unpublished; Beta keeps everything it calls), Superset's datasets, charts and SQL Lab history
-- (everything Superset reads stays), the Supabase Edge Functions, function bodies, views, policies, triggers,
-- defaults and checks in the database, migrations that name them (019 is run again after every migration; the
-- rollbacks of 021-028 keep working while 029 is applied, tested), PostgREST (only public is exposed; every Appsmith
-- call and every portal service sends the signed-in person's token or connects as postgres) and pg_stat_statements
-- since 25 Sep.
--
-- What changes:
-- 1. Nine functions are dropped: clear_missionary_special_assignment, set_missionary_special_assignment,
--    set_area_assignment_type, link_user_to_missionary and unlink_user_from_missionary (early admin helpers; DA
--    Management does this work itself), and four overloads marked DEPRECATED in their own comments that nothing calls
--    any more: save_current_planning_answer(text,text,numeric,boolean), save_current_planning_answer(bigint,text,
--    text,numeric,boolean), submit_current_weekly_report() and update_current_weekly_report(17 integers, text).
--    Beta calls save_current_planning_answer with answer_json and submit_current_weekly_report(target_unit_id); those
--    stay. update_current_weekly_report(target_unit_id, ...) stays too: nothing calls it, but its comment calls it the
--    canonical API.
-- 2. Twelve views are dropped: area_history, current_assignment_details, district_/zone_/mission_reporting_status,
--    area_/district_/zone_/mission_weekly_metrics_clean, new_members_clean, baptismal_dates_clean and
--    high_potentials_clean. area_reporting_status stays (current_area_reporting_status, which 026 checks, reads it).
-- 3. Two tables are dropped: missionary_import_stage (168 rows) and organization_import_stage (24 rows), the staging
--    tables of a roster import done by hand before DA Management existed. Their rows come back only from the backup
--    taken before this file (see the rollback).
-- 4. Rights nobody uses are taken away (each one is first written to public.cleanup_029_revoked_grants, which only
--    postgres can read, so the rollback gives back exactly these):
--    - anon: every right on every table, view and sequence in public, and EXECUTE on every SECURITY DEFINER function
--      in public. Nothing reads or writes data as anon: Appsmith sends the signed-in person's token on every data
--      call (the key alone only for sign-in), and so do the portal page, DA Management, Presentations and the Edge
--      Functions; portal-api, reminders and DA Management connect as postgres, Grafana as gfm_dashboard_reader.
--      Functions that are not SECURITY DEFINER keep PUBLIC's EXECUTE (they run with the caller's rights anyway).
--      One exception: anon keeps SELECT on the five planning catalogue tables (planning_question_sections,
--      _questions, _options, _grid_rows and _visibility_rules). Row-level security gives anon no rows there (their
--      policies are for authenticated only), and 024's rollback checks that anon still has SELECT, so that rollback
--      keeps working on its own while 029 is applied.
--    - grafana_readonly (a login from before gfm_dashboard_reader; no data source, session or statement uses it):
--      every right on tables, views, sequences and functions in public, dashboards and portal. The login itself is
--      not changed.
--    - authenticated: every right on import_weekly_planning_reports, _answers, _new_members,
--      _baptismal_date_friends, _high_potential_friends, _area_map and gfm_schema_migrations (tables without
--      row-level security that only DA Management uses, as postgres); on area_units every right except SELECT
--      (Beta reads it; only DA Management writes it) and every right on its sequence; and EXECUTE on
--      ensure_reporting_week(date) (only start_current_weekly_report calls it, with the owner's rights).
--      On live Beta the hotfix of 27 Sep 22:50 already took the import tables and the area_units writes away; the
--      file takes whatever is still there (on live: gfm_schema_migrations and ensure_reporting_week).
--    - The default rights of postgres and supabase_admin in public no longer give new tables, views, sequences and
--      functions to anon, nor new tables to grafana_readonly (so a new table is not open to the public key before
--      someone thinks about it). authenticated and service_role keep their default rights.
-- Nothing else changes: every part that Beta, the portal, Call-ins, Dashboards (Grafana), Presentations, DA
-- Management, the reminders or Superset use stays, with the same rights for authenticated and service_role.
--
-- Apply (back up Beta first, e.g. backups/beta-pre-029-<date>.dump: the staging tables' rows come back only from it).
-- Join the lines with plain line feeds:
--   (Get-Content portal-api/migrations/029_remove_unused.sql) -join "`n" |
--     docker exec -i gfm-beta-supabase-db-1 psql -U supabase_admin -d postgres -v ON_ERROR_STOP=1
--   (Git Bash: sed 's/\r$//' portal-api/migrations/029_remove_unused.sql | docker exec -i ...)
-- Then run 019 again as a check (it must end with COMMIT):
--   Get-Content portal-api/migrations/019_restrict_public_functions.sql -Raw |
--     docker exec -i gfm-beta-supabase-db-1 psql -U supabase_admin -d postgres -v ON_ERROR_STOP=1
-- The file stops, and changes nothing, if a part to be dropped changed since 27 Sep 2026, 22:50 (its definition,
-- rights or comment differ from what the rollback would put back; the fingerprints below were read from live Beta
-- after the hotfix), or after 10 seconds waiting for a lock; look, then run it again. On a throwaway copy made from
-- a template older than the hotfix, replay the hotfix first (portal-api/tests/hotfix_20260927_replay.sql).
-- Safe to run again: parts already dropped are skipped, rights already taken away stay recorded once.
-- Rollback: 029_remove_unused_rollback.sql (recreates the 23 parts with their rights and comments from live Beta,
-- gives back every recorded right and the default rights), then the staging tables' rows from the backup.
BEGIN;
SET LOCAL lock_timeout = '10s';

DO $$
BEGIN
  IF NOT (SELECT rolsuper FROM pg_roles WHERE rolname = current_user) THEN
    RAISE EXCEPTION 'Run this file as supabase_admin (see its header), not as %.', current_user;
  END IF;
END $$;

-- 0. What is dropped, with the fingerprint of each part on live Beta (27 Sep 2026, after the 22:50 hotfix, which
--    changed the rights of the seven *_clean views and the two staging tables): definition, owner, rights and
--    comment. The rollback recreates exactly these, so a part that changed since then is not dropped.
CREATE TEMP TABLE cleanup_029_drop (kind text, name text, fingerprint text, drop_order int) ON COMMIT DROP;
INSERT INTO cleanup_029_drop VALUES
  ('view', 'public.district_reporting_status', '3a7c314a7b7db36e728cdcdb2de5a535', 1),
  ('view', 'public.zone_reporting_status', '93b4901c60f5e3a4932b7bc94d226ded', 1),
  ('view', 'public.mission_reporting_status', '3a56117686bf95199bfa8601923bce04', 1),
  ('view', 'public.district_weekly_metrics_clean', 'bc63b0712de48c8e9c8e59dd65cefd42', 1),
  ('view', 'public.zone_weekly_metrics_clean', '2be268ebb2a0d4863f9b450076b9a470', 1),
  ('view', 'public.mission_weekly_metrics_clean', '4b71647f30626308c4fa65cadfaf1fcc', 1),
  ('view', 'public.area_weekly_metrics_clean', '9dd2869fa05b3847d0a2a1589d7bae50', 2),
  ('view', 'public.area_history', '48f6ad5d2c7f013612b0c2363dd84692', 1),
  ('view', 'public.current_assignment_details', '2d080552244df42ff75ce859fc16c6a6', 1),
  ('view', 'public.new_members_clean', 'd4e7a781d556d1339884494ad6eedab1', 1),
  ('view', 'public.baptismal_dates_clean', '317dc5b5727f10d3e183c3381ed224c5', 1),
  ('view', 'public.high_potentials_clean', 'e8cbcd0d09950c38884d9cc86d35530e', 1),
  ('table', 'public.missionary_import_stage', '7741eeed525bf4e65189ca58f2b01da4', 3),
  ('table', 'public.organization_import_stage', '232e1122a959f521c23220f19ae2c62c', 3),
  ('function', 'public.clear_missionary_special_assignment(text)', '2e444ba80de93f0bb2eee26cb4773cf1', 4),
  ('function', 'public.set_missionary_special_assignment(text,text,text)', '43c285f3664d25bd1e4267e89dce3738', 4),
  ('function', 'public.set_area_assignment_type(text,text,text)', '54f25895d5c6a6e0af255848fe4d8e3e', 4),
  ('function', 'public.link_user_to_missionary(uuid,text)', 'bc39c324e852b396fd7c4679a2cb7478', 4),
  ('function', 'public.unlink_user_from_missionary(uuid)', 'af6e07a328dee91dc3a456132d31127b', 4),
  ('function', 'public.save_current_planning_answer(text,text,numeric,boolean)', '7f2c508c64a2223cb6eaa9f442512135', 4),
  ('function', 'public.save_current_planning_answer(bigint,text,text,numeric,boolean)', '8f4729ec544f778d6fe58fc768505e10', 4),
  ('function', 'public.submit_current_weekly_report()', '7c59fc705bf007d0089a1ac3ef5c5b9e', 4),
  ('function', 'public.update_current_weekly_report(integer,integer,integer,integer,integer,integer,integer,integer,integer,integer,integer,integer,integer,integer,integer,integer,integer,text)', '536be00b2b173984dded72695ceda165', 4);

DO $$
DECLARE
  d record;
  actual text;
  changed text := '';
BEGIN
  FOR d IN SELECT * FROM cleanup_029_drop ORDER BY name LOOP
    IF d.kind = 'function' THEN
      SELECT md5(replace(pg_get_functiondef(p.oid), chr(13), '') || '|' || pg_get_userbyid(p.proowner) || '|'
                 || coalesce((SELECT string_agg(x::text, ',' ORDER BY x::text) FROM unnest(p.proacl) x), '') || '|'
                 || coalesce(obj_description(p.oid, 'pg_proc'), ''))
        INTO actual FROM pg_proc p WHERE p.oid = to_regprocedure(d.name);
    ELSE
      SELECT md5(coalesce(pg_get_viewdef(c.oid), '') || '|'
                 || (SELECT string_agg(a.attname || ' ' || format_type(a.atttypid, a.atttypmod), ',' ORDER BY a.attnum)
                     FROM pg_attribute a WHERE a.attrelid = c.oid AND a.attnum > 0 AND NOT a.attisdropped) || '|'
                 || coalesce(array_to_string(c.reloptions, ','), '') || '|' || c.relrowsecurity || '|'
                 || pg_get_userbyid(c.relowner) || '|'
                 || coalesce((SELECT string_agg(x::text, ',' ORDER BY x::text) FROM unnest(c.relacl) x), '') || '|'
                 || coalesce(obj_description(c.oid, 'pg_class'), ''))
        INTO actual FROM pg_class c WHERE c.oid = to_regclass(d.name);
    END IF;
    -- Already dropped (a second run): nothing to compare.
    IF actual IS NOT NULL AND actual <> d.fingerprint THEN
      changed := changed || format(E'\n  %s (now %s)', d.name, actual);
    END IF;
  END LOOP;
  IF changed <> '' THEN
    RAISE EXCEPTION 'Stopped, nothing changed: these parts differ from 27 Sep 2026, so the rollback would not restore them exactly:%', changed;
  END IF;
  -- Something new may have started to use a view or table: DROP without CASCADE below stops then, but say it here.
  SELECT string_agg(DISTINCT dep.relname || ' uses ' || x.name, ', ') INTO changed
  FROM cleanup_029_drop x
  JOIN pg_depend pd ON x.kind <> 'function' AND pd.refobjid = to_regclass(x.name)
  JOIN pg_rewrite rw ON rw.oid = pd.objid
  JOIN pg_class dep ON dep.oid = rw.ev_class
  WHERE dep.oid <> to_regclass(x.name)
    AND NOT EXISTS (SELECT 1 FROM cleanup_029_drop o WHERE to_regclass(o.name) = dep.oid);
  IF changed IS NOT NULL THEN
    RAISE EXCEPTION 'Stopped, nothing changed: other views use parts on the list: %', changed;
  END IF;
  IF to_regclass('public.missionary_import_stage') IS NOT NULL THEN
    RAISE NOTICE 'Dropping missionary_import_stage (% rows) and organization_import_stage (% rows); they come back only from the backup.',
      (SELECT count(*) FROM public.missionary_import_stage), (SELECT count(*) FROM public.organization_import_stage);
  END IF;
END $$;

-- 1-3. Drop (dependent views first). No CASCADE: if anything new depends on one of them, the file stops here.
DO $$
DECLARE
  d record;
BEGIN
  FOR d IN SELECT * FROM cleanup_029_drop ORDER BY drop_order, name LOOP
    IF d.kind = 'view' AND to_regclass(d.name) IS NOT NULL THEN
      EXECUTE format('DROP VIEW %s', d.name);
    ELSIF d.kind = 'table' AND to_regclass(d.name) IS NOT NULL THEN
      EXECUTE format('DROP TABLE %s', d.name);
    ELSIF d.kind = 'function' AND to_regprocedure(d.name) IS NOT NULL THEN
      EXECUTE format('DROP FUNCTION %s', d.name);
    END IF;
  END LOOP;
END $$;

-- 4. Rights nobody uses. First written down (only on the first run: a second run finds them gone), then taken away.
SET LOCAL ROLE postgres;
CREATE TABLE IF NOT EXISTS public.cleanup_029_revoked_grants (
  object_kind text NOT NULL CHECK (object_kind IN ('TABLE', 'SEQUENCE', 'FUNCTION', 'DEFAULT')),
  object_name text NOT NULL,
  grantee text NOT NULL,
  privilege_type text NOT NULL,
  grantor text NOT NULL,
  is_grantable boolean NOT NULL,
  revoked_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (object_kind, object_name, grantee, privilege_type)
);
COMMENT ON TABLE public.cleanup_029_revoked_grants IS 'Migration 029: every right it took away (anon, grafana_readonly and a few of authenticated). Read by 029_remove_unused_rollback.sql to give exactly these back. Drop it once the cleanup is accepted.';
ALTER TABLE public.cleanup_029_revoked_grants ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.cleanup_029_revoked_grants FROM PUBLIC, anon, authenticated, service_role;
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'grafana_readonly') THEN
    EXECUTE 'REVOKE ALL ON public.cleanup_029_revoked_grants FROM grafana_readonly';
  END IF;
END $$;
RESET ROLE;

-- The five planning catalogue tables where anon keeps SELECT (row-level security gives it no rows; 024's rollback
-- checks for it).
CREATE TEMP TABLE cleanup_029_anon_keeps_select ON COMMIT DROP AS
SELECT to_regclass(n) AS oid FROM unnest(ARRAY[
  'public.planning_question_sections', 'public.planning_questions', 'public.planning_question_options',
  'public.planning_question_grid_rows', 'public.planning_question_visibility_rules']) n
WHERE to_regclass(n) IS NOT NULL;

CREATE TEMP TABLE cleanup_029_targets ON COMMIT DROP AS
-- anon: tables, views and sequences in public.
SELECT CASE WHEN c.relkind = 'S' THEN 'SEQUENCE' ELSE 'TABLE' END AS object_kind, format('%I.%I', c.relnamespace::regnamespace, c.relname) AS object_name,
       a.grantee::regrole::text AS grantee, a.privilege_type, a.grantor::regrole::text AS grantor, a.is_grantable
FROM pg_class c CROSS JOIN LATERAL aclexplode(c.relacl) a
WHERE c.relnamespace = 'public'::regnamespace AND c.relkind IN ('r', 'p', 'v', 'm', 'f', 'S')
  AND a.grantee = 'anon'::regrole
  AND c.oid <> 'public.cleanup_029_revoked_grants'::regclass
  AND NOT (a.privilege_type = 'SELECT' AND c.oid IN (SELECT oid FROM cleanup_029_anon_keeps_select))
UNION ALL
-- anon: SECURITY DEFINER functions in public.
SELECT 'FUNCTION', format('%I.%I(%s)', p.pronamespace::regnamespace, p.proname, pg_get_function_identity_arguments(p.oid)), a.grantee::regrole::text, a.privilege_type, a.grantor::regrole::text, a.is_grantable
FROM pg_proc p CROSS JOIN LATERAL aclexplode(p.proacl) a
WHERE p.pronamespace = 'public'::regnamespace AND p.prosecdef AND a.grantee = 'anon'::regrole
UNION ALL
-- grafana_readonly: everything in public, dashboards and portal.
SELECT CASE WHEN c.relkind = 'S' THEN 'SEQUENCE' ELSE 'TABLE' END, format('%I.%I', c.relnamespace::regnamespace, c.relname), a.grantee::regrole::text,
       a.privilege_type, a.grantor::regrole::text, a.is_grantable
FROM pg_class c CROSS JOIN LATERAL aclexplode(c.relacl) a
WHERE c.relnamespace IN ('public'::regnamespace, 'dashboards'::regnamespace, 'portal'::regnamespace)
  AND c.relkind IN ('r', 'p', 'v', 'm', 'f', 'S')
  AND a.grantee = (SELECT oid FROM pg_roles WHERE rolname = 'grafana_readonly')
UNION ALL
SELECT 'FUNCTION', format('%I.%I(%s)', p.pronamespace::regnamespace, p.proname, pg_get_function_identity_arguments(p.oid)), a.grantee::regrole::text, a.privilege_type, a.grantor::regrole::text, a.is_grantable
FROM pg_proc p CROSS JOIN LATERAL aclexplode(p.proacl) a
WHERE p.pronamespace IN ('public'::regnamespace, 'dashboards'::regnamespace, 'portal'::regnamespace)
  AND a.grantee = (SELECT oid FROM pg_roles WHERE rolname = 'grafana_readonly')
UNION ALL
-- authenticated: the import tables and the migrations list (no row-level security, only DA Management uses them).
SELECT CASE WHEN c.relkind = 'S' THEN 'SEQUENCE' ELSE 'TABLE' END, format('%I.%I', c.relnamespace::regnamespace, c.relname), a.grantee::regrole::text,
       a.privilege_type, a.grantor::regrole::text, a.is_grantable
FROM pg_class c CROSS JOIN LATERAL aclexplode(c.relacl) a
WHERE c.oid IN (SELECT to_regclass(n) FROM unnest(ARRAY[
        'public.import_weekly_planning_reports', 'public.import_weekly_planning_answers', 'public.import_weekly_new_members',
        'public.import_weekly_baptismal_date_friends', 'public.import_weekly_high_potential_friends',
        'public.import_weekly_planning_area_map', 'public.gfm_schema_migrations', 'public.gfm_schema_migrations_id_seq',
        'public.area_units_id_seq']) n)
  AND a.grantee = 'authenticated'::regrole
UNION ALL
-- authenticated: area_units, all but reading.
SELECT 'TABLE', format('%I.%I', c.relnamespace::regnamespace, c.relname), a.grantee::regrole::text, a.privilege_type, a.grantor::regrole::text, a.is_grantable
FROM pg_class c CROSS JOIN LATERAL aclexplode(c.relacl) a
WHERE c.oid = 'public.area_units'::regclass AND a.grantee = 'authenticated'::regrole AND a.privilege_type <> 'SELECT'
UNION ALL
-- authenticated: ensure_reporting_week (only called inside start_current_weekly_report).
SELECT 'FUNCTION', format('%I.%I(%s)', p.pronamespace::regnamespace, p.proname, pg_get_function_identity_arguments(p.oid)), a.grantee::regrole::text, a.privilege_type, a.grantor::regrole::text, a.is_grantable
FROM pg_proc p CROSS JOIN LATERAL aclexplode(p.proacl) a
WHERE p.oid = 'public.ensure_reporting_week(date)'::regprocedure AND a.grantee = 'authenticated'::regrole
UNION ALL
-- Default rights of postgres and supabase_admin in public: anon (all kinds) and grafana_readonly (tables).
SELECT 'DEFAULT', format('%s:%s', pg_get_userbyid(d.defaclrole), d.defaclobjtype), a.grantee::regrole::text,
       a.privilege_type, a.grantor::regrole::text, a.is_grantable
FROM pg_default_acl d CROSS JOIN LATERAL aclexplode(d.defaclacl) a
WHERE d.defaclnamespace = 'public'::regnamespace
  AND pg_get_userbyid(d.defaclrole) IN ('postgres', 'supabase_admin')
  AND (a.grantee = 'anon'::regrole OR a.grantee = (SELECT oid FROM pg_roles WHERE rolname = 'grafana_readonly'));

INSERT INTO public.cleanup_029_revoked_grants (object_kind, object_name, grantee, privilege_type, grantor, is_grantable)
SELECT object_kind, object_name, grantee, privilege_type, grantor, is_grantable FROM cleanup_029_targets
ON CONFLICT DO NOTHING;

DO $$
DECLARE
  t record;
  owner_kind text;
BEGIN
  FOR t IN SELECT object_kind, object_name, grantee, string_agg(privilege_type, ', ' ORDER BY privilege_type) AS privileges
           FROM cleanup_029_targets GROUP BY 1, 2, 3 LOOP
    IF t.object_kind = 'DEFAULT' THEN
      owner_kind := split_part(t.object_name, ':', 2);
      EXECUTE format('ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA public REVOKE %s ON %s FROM %I',
                     split_part(t.object_name, ':', 1), t.privileges,
                     CASE owner_kind WHEN 'r' THEN 'TABLES' WHEN 'S' THEN 'SEQUENCES' WHEN 'f' THEN 'FUNCTIONS'
                                     WHEN 'T' THEN 'TYPES' WHEN 'n' THEN 'SCHEMAS' END, t.grantee);
    ELSE
      EXECUTE format('REVOKE %s ON %s %s FROM %I', t.privileges, t.object_kind, t.object_name, t.grantee);
    END IF;
  END LOOP;
END $$;

-- Check: the parts are gone, the rights are gone, the copy of the rights is private, and everything that Beta, the
-- portal and the Edge Functions use through PostgREST (as authenticated) still works.
DO $$
DECLARE
  found text;
BEGIN
  SELECT string_agg(name, ', ') INTO found FROM cleanup_029_drop
  WHERE (kind = 'function' AND to_regprocedure(name) IS NOT NULL) OR (kind <> 'function' AND to_regclass(name) IS NOT NULL);
  IF found IS NOT NULL THEN RAISE EXCEPTION 'Check failed: still there: %', found; END IF;

  SELECT string_agg(DISTINCT c.oid::regclass::text, ', ') INTO found
  FROM pg_class c CROSS JOIN LATERAL aclexplode(c.relacl) a
  WHERE c.relnamespace = 'public'::regnamespace AND a.grantee = 'anon'::regrole
    AND NOT (a.privilege_type = 'SELECT' AND c.oid IN (SELECT oid FROM cleanup_029_anon_keeps_select));
  IF found IS NOT NULL THEN RAISE EXCEPTION 'Check failed: anon still has rights on %', found; END IF;
  -- The one exception must be harmless: row-level security on, and no policy that lets anon (or PUBLIC) read.
  SELECT string_agg(c.relname, ', ') INTO found
  FROM pg_class c WHERE c.oid IN (SELECT oid FROM cleanup_029_anon_keeps_select)
    AND has_table_privilege('anon', c.oid, 'SELECT')
    AND (NOT c.relrowsecurity OR EXISTS (SELECT 1 FROM pg_policy pol WHERE pol.polrelid = c.oid
                                          AND (pol.polroles && ARRAY[0::oid, 'anon'::regrole::oid])));
  IF found IS NOT NULL THEN RAISE EXCEPTION 'Check failed: anon could read rows of %', found; END IF;
  SELECT string_agg(p.oid::regprocedure::text, ', ') INTO found FROM pg_proc p
  WHERE p.pronamespace = 'public'::regnamespace AND p.prosecdef AND has_function_privilege('anon', p.oid, 'EXECUTE');
  IF found IS NOT NULL THEN RAISE EXCEPTION 'Check failed: anon can still run %', found; END IF;
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'grafana_readonly') THEN
    SELECT string_agg(DISTINCT c.oid::regclass::text, ', ') INTO found
    FROM pg_class c CROSS JOIN LATERAL aclexplode(c.relacl) a
    WHERE c.relnamespace IN ('public'::regnamespace, 'dashboards'::regnamespace, 'portal'::regnamespace)
      AND a.grantee = 'grafana_readonly'::regrole;
    IF found IS NOT NULL THEN RAISE EXCEPTION 'Check failed: grafana_readonly still has rights on %', found; END IF;
  END IF;
  SELECT string_agg(n, ', ') INTO found FROM unnest(ARRAY[
    'public.import_weekly_planning_reports', 'public.import_weekly_planning_answers', 'public.import_weekly_new_members',
    'public.import_weekly_baptismal_date_friends', 'public.import_weekly_high_potential_friends',
    'public.import_weekly_planning_area_map', 'public.gfm_schema_migrations']) n
  WHERE has_table_privilege('authenticated', n, 'SELECT') OR has_table_privilege('authenticated', n, 'INSERT')
     OR has_table_privilege('authenticated', n, 'UPDATE') OR has_table_privilege('authenticated', n, 'DELETE');
  IF found IS NOT NULL THEN RAISE EXCEPTION 'Check failed: signed-in users can still use %', found; END IF;
  IF has_table_privilege('authenticated', 'public.area_units', 'INSERT') OR has_table_privilege('authenticated', 'public.area_units', 'UPDATE')
     OR has_table_privilege('authenticated', 'public.area_units', 'DELETE')
     OR has_function_privilege('authenticated', 'public.ensure_reporting_week(date)', 'EXECUTE') THEN
    RAISE EXCEPTION 'Check failed: signed-in users can still change area_units or run ensure_reporting_week.';
  END IF;
  IF EXISTS (SELECT 1 FROM pg_default_acl d CROSS JOIN LATERAL aclexplode(d.defaclacl) a
             WHERE d.defaclnamespace = 'public'::regnamespace AND pg_get_userbyid(d.defaclrole) IN ('postgres', 'supabase_admin')
               AND pg_get_userbyid(a.grantee) IN ('anon', 'grafana_readonly')) THEN
    RAISE EXCEPTION 'Check failed: new objects in public would still be given to anon or grafana_readonly.';
  END IF;

  -- What Beta (Appsmith), the portal page, DA Management, Presentations and the Edge Function read through PostgREST.
  SELECT string_agg(n, ', ') INTO found FROM unnest(ARRAY[
    'public.active_planning_questions', 'public.area_units', 'public.call_in_districts', 'public.current_baptismal_date_people',
    'public.current_mission_areas', 'public.current_new_members', 'public.current_user_area_units', 'public.current_user_context',
    'public.current_user_scope', 'public.current_weekly_reports', 'public.planning_question_grid_rows',
    'public.planning_question_options', 'public.planning_question_visibility_rules', 'public.reporting_weeks',
    'public.weekly_baptismal_date_friends', 'public.weekly_high_potential_friends', 'public.weekly_new_members',
    'public.weekly_planning_answers']) n
  WHERE to_regclass(n) IS NULL OR NOT has_table_privilege('authenticated', n, 'SELECT');
  IF found IS NOT NULL THEN RAISE EXCEPTION 'Check failed: signed-in users can no longer read %', found; END IF;
  SELECT string_agg(n, ', ') INTO found FROM unnest(ARRAY[
    'public.weekly_baptismal_date_friends', 'public.weekly_high_potential_friends', 'public.weekly_new_members']) n
  WHERE NOT (has_table_privilege('authenticated', n, 'INSERT') AND has_table_privilege('authenticated', n, 'UPDATE'));
  IF found IS NOT NULL THEN RAISE EXCEPTION 'Check failed: signed-in users can no longer write %', found; END IF;
  SELECT string_agg(n, ', ') INTO found FROM unnest(ARRAY[
    'public.archive_baptismal_date_person(bigint,text)', 'public.archive_new_member(bigint,text)',
    'public.complete_dl_call_in(bigint,bigint)', 'public.convert_baptismal_date_person_to_new_member(bigint,date,date,date,date,text,text,text,integer,text,text,text,text,text,text)',
    'public.create_baptismal_date_person(text,text,text,bigint)',
    'public.create_new_member(text,text,bigint,bigint,date,date,date,text,date,text,text,text,integer,text,text,text,text,text,text)',
    'public.get_dl_call_in_summary(bigint,bigint)', 'public.get_mission_call_in_summary(bigint,bigint)',
    'public.get_zl_call_in_summary(bigint,bigint)', 'public.get_previous_planning_answers(bigint)',
    'public.get_previous_weekly_new_members(bigint)', 'public.reopen_dl_call_in(bigint,bigint)',
    'public.save_current_planning_answer(bigint,text,text,numeric,boolean,jsonb)',
    'public.start_current_weekly_report(bigint)', 'public.submit_current_weekly_report(bigint)',
    'public.transfer_baptismal_date_person(bigint,bigint,bigint)', 'public.transfer_new_member(bigint,bigint)',
    'public.unsubmit_weekly_report(bigint)']) n
  WHERE to_regprocedure(n) IS NULL OR NOT has_function_privilege('authenticated', n, 'EXECUTE');
  IF found IS NOT NULL THEN RAISE EXCEPTION 'Check failed: signed-in users can no longer run %', found; END IF;

  IF has_table_privilege('anon', 'public.cleanup_029_revoked_grants', 'SELECT')
     OR has_table_privilege('authenticated', 'public.cleanup_029_revoked_grants', 'SELECT')
     OR has_table_privilege('service_role', 'public.cleanup_029_revoked_grants', 'SELECT') THEN
    RAISE EXCEPTION 'Check failed: the copy of the rights can be read through the API.';
  END IF;
END $$;

NOTIFY pgrst, 'reload schema';
COMMIT;

-- Verify (read-only, after applying):
-- 1. Run 019 again as supabase_admin (see Apply); it must end with COMMIT.
-- 2. What was taken away (counts per role and kind):
--      docker exec gfm-beta-supabase-db-1 psql -U postgres -d postgres -c "BEGIN READ ONLY" -c "SELECT grantee, object_kind, count(DISTINCT object_name) AS objects, count(*) AS rights FROM public.cleanup_029_revoked_grants GROUP BY 1, 2 ORDER BY 1, 2" -c "ROLLBACK"
-- 3. The public key reads nothing any more (must print 401 or 42501-style errors, never rows):
--      docker exec gfm-beta-supabase-db-1 psql -U postgres -d postgres -c "BEGIN READ ONLY" -c "SET LOCAL ROLE anon" -c "SELECT count(*) FROM public.import_weekly_new_members" -c "ROLLBACK"
--    (expected: ERROR: permission denied for table import_weekly_new_members)
