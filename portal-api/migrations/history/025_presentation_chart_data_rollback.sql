-- Rollback of 025_presentation_chart_data.sql. Run on Beta only, as supabase_admin.
--
-- What it restores (the state before 025, read from the live database on 27 Sep 2026): the dashboards schema
-- holds only the four views and the function of 018 (kpi_area_week, kpi_area_total_week, kpi_zone_week,
-- kpi_mission_week, area_week_rows), and postgres is not a member of gfm_dashboard_reader. 025 replaced nothing,
-- so nothing has to be put back: the six new views are dropped and the membership is revoked.
-- Do it together with the code rollback, or database charts in slides show "Mission numbers are not available
-- right now." (<MissionKpiChart> and /api/mission-kpis do not use anything from 025 and keep working.)
-- Grafana panels that were built on the new views stop working; the 018 views are untouched.
--
-- Apply:
--   (Get-Content portal-api/migrations/025_presentation_chart_data_rollback.sql) -join "`n" |
--     docker exec -i gfm-beta-supabase-db-1 psql -U supabase_admin -d postgres -v ON_ERROR_STOP=1
--   (Git Bash: sed 's/\r$//' portal-api/migrations/025_presentation_chart_data_rollback.sql | docker exec -i ...)
-- Safe to run again. The last block checks the result and stops on any problem.
BEGIN;
SET LOCAL lock_timeout = '10s';

DO $$
BEGIN
  IF session_user NOT IN ('supabase_admin', 'postgres') THEN
    RAISE EXCEPTION 'Run this file as supabase_admin (see its header), not as %.', session_user;
  END IF;
END $$;

-- The readable views first: they depend on people_area_week_counts and kpi_area_total_week.
DROP VIEW IF EXISTS dashboards.people_area_week, dashboards.people_district_week, dashboards.people_zone_week,
  dashboards.people_mission_week, dashboards.kpi_district_week;
DROP VIEW IF EXISTS dashboards.people_area_week_counts;

REVOKE gfm_dashboard_reader FROM postgres;

DO $$
DECLARE
  found text;
BEGIN
  SELECT string_agg(c.relname, ', ') INTO found
  FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
  WHERE n.nspname = 'dashboards' AND c.relname IN ('kpi_district_week', 'people_area_week_counts', 'people_mission_week',
                                                  'people_zone_week', 'people_district_week', 'people_area_week');
  IF found IS NOT NULL THEN RAISE EXCEPTION 'Check failed: still there: %', found; END IF;
  IF pg_has_role('postgres', 'gfm_dashboard_reader', 'MEMBER') THEN
    RAISE EXCEPTION 'Check failed: postgres is still a member of gfm_dashboard_reader.';
  END IF;
  SELECT string_agg(v, ', ') INTO found
  FROM unnest(ARRAY['dashboards.kpi_area_week', 'dashboards.kpi_area_total_week', 'dashboards.kpi_zone_week',
                    'dashboards.kpi_mission_week']) v
  WHERE to_regclass(v) IS NULL OR NOT has_table_privilege('gfm_dashboard_reader', v, 'SELECT');
  IF found IS NOT NULL THEN RAISE EXCEPTION 'Check failed: the 018 views are missing or unreadable: %', found; END IF;
END $$;

COMMIT;
