-- Reporting views for the Dashboards tab (Grafana) and the Presentations KPI feed. Run on Beta only.
-- The views hold only mission, zone, district, area and ward/branch names and numbers: no people,
-- no notes, no user ids. Nothing existing is changed; one schema, one function, four views and one
-- read-only login role are added.
--
-- Values come from public.weekly_area_reports_with_planning_metrics, so they match Planning and
-- Call-ins exactly: every report in a week counts (drafts too), and "previous goal" is the goal set
-- in the previous reporting week, which is what that week's result is measured against. Call-ins
-- pair the weeks per area (all its wards/branches together); kpi_area_total_week, kpi_zone_week and
-- kpi_mission_week do the same. Only kpi_area_week pairs per ward/branch (see its comment).
--
-- Why a SECURITY DEFINER function: the base view is security_invoker, so it checks the tables as
-- whoever queries it, even through another view. dashboards.area_week_rows() runs as its owner
-- (postgres), so gfm_dashboard_reader can read the dashboards views without any right on public.*.
--
-- Apply (back up Beta first; run as postgres so postgres owns the objects):
--   Get-Content portal-api/migrations/018_dashboard_reporting.sql -Raw |
--     docker exec -i gfm-beta-supabase-db-1 psql -U postgres -d postgres -v ON_ERROR_STOP=1
-- Then apply 019_restrict_public_functions.sql (as supabase_admin) BEFORE Grafana is started: until
-- then every database login, this one included, can run 15 SECURITY DEFINER functions in public.
-- Then give gfm_dashboard_reader its password from grafana/.env (the password never reaches the
-- command line or the server log; only its SCRAM hash is sent):
--   powershell -NoProfile -ExecutionPolicy Bypass -File grafana/set-reader-password.ps1
-- Safe to run again: every statement is idempotent.
-- Rollback: see the commented section at the end of this file.
BEGIN;

CREATE SCHEMA IF NOT EXISTS dashboards;
REVOKE ALL ON SCHEMA dashboards FROM PUBLIC, anon, authenticated;
COMMENT ON SCHEMA dashboards IS 'Read-only reporting views for Grafana and slides. Org units and numbers only, no personal data.';

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'gfm_dashboard_reader') THEN
    CREATE ROLE gfm_dashboard_reader LOGIN NOINHERIT;
  END IF;
END $$;
-- New roles are never superuser, replication or bypassrls (and postgres may not change those flags).
ALTER ROLE gfm_dashboard_reader LOGIN NOINHERIT NOCREATEDB NOCREATEROLE CONNECTION LIMIT 10;
ALTER ROLE gfm_dashboard_reader SET default_transaction_read_only = on;
ALTER ROLE gfm_dashboard_reader SET statement_timeout = '15s';
ALTER ROLE gfm_dashboard_reader SET idle_in_transaction_session_timeout = '60s';
ALTER ROLE gfm_dashboard_reader SET search_path = dashboards;
COMMENT ON ROLE gfm_dashboard_reader IS 'Grafana data source. May read the dashboards views only.';

-- One row per weekly report (area + ward/branch). previous_goal pairs the report with the report of
-- the same area AND ward/branch in the previous reporting week. Call-ins pair per area only, so when
-- an area reports for a different ward/branch than the week before, this previous_goal is empty or
-- partial and does not match Call-ins: use kpi_area_total_week for area and district figures.
CREATE OR REPLACE FUNCTION dashboards.area_week_rows()
RETURNS TABLE (
  week timestamptz, sunday date, reporting_week_id bigint, previous_reporting_week_id bigint,
  mission_id bigint, zone_id bigint, zone text, district_id bigint, district text,
  area_id bigint, area text, unit_id bigint, unit text, status text, submitted boolean,
  friends_found_actual integer, friends_found_goal integer, friends_found_previous_goal bigint,
  baptisms_confirmations_actual integer, baptisms_confirmations_goal integer, baptisms_confirmations_previous_goal bigint,
  baptismal_dates_actual integer, baptismal_dates_goal integer, baptismal_dates_previous_goal bigint,
  sacrament_attendance_actual integer, sacrament_attendance_goal integer, sacrament_attendance_previous_goal bigint,
  members_at_lessons_actual integer, members_at_lessons_goal integer, members_at_lessons_previous_goal bigint,
  new_member_sacrament_actual integer, new_member_sacrament_goal integer, new_member_sacrament_previous_goal bigint,
  first_time_sacrament_actual integer,
  lessons_with_friends_actual integer, lessons_with_friends_goal integer,
  follow_up_lessons_actual integer, follow_up_lessons_goal integer
)
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $$
  WITH weeks AS (
    SELECT rw.id, rw.sunday, lag(rw.id) OVER (ORDER BY rw.sunday) AS previous_id
    FROM public.reporting_weeks rw
  ), reports AS MATERIALIZED (
    SELECT v.* FROM public.weekly_area_reports_with_planning_metrics v
  ), goals AS (
    SELECT r.reporting_week_id, r.area_id, r.unit_id,
           sum(r.friends_found_goal) AS friends_found,
           sum(r.baptisms_confirmations_goal) AS baptisms_confirmations,
           sum(r.baptismal_dates_goal) AS baptismal_dates,
           sum(r.sacrament_attendance_goal) AS sacrament_attendance,
           sum(r.lessons_with_members_goal) AS members_at_lessons,
           sum(r.new_member_sacrament_goal) AS new_member_sacrament
    FROM reports r
    GROUP BY r.reporting_week_id, r.area_id, r.unit_id
  )
  SELECT (w.sunday + time '12:00') AT TIME ZONE 'Europe/Berlin', w.sunday, w.id, w.previous_id,
         z.mission_id, z.id, z.name, d.id, d.name, a.id, a.name, u.id, u.name,
         r.status, r.status IN ('SUBMITTED', 'LOCKED'),
         r.friends_found_actual, r.friends_found_goal, p.friends_found,
         r.baptisms_confirmations_actual, r.baptisms_confirmations_goal, p.baptisms_confirmations,
         r.baptismal_dates_actual, r.baptismal_dates_goal, p.baptismal_dates,
         r.sacrament_attendance_actual, r.sacrament_attendance_goal, p.sacrament_attendance,
         r.lessons_with_members_actual, r.lessons_with_members_goal, p.members_at_lessons,
         r.new_member_sacrament_actual, r.new_member_sacrament_goal, p.new_member_sacrament,
         r.first_time_sacrament_actual,
         r.lessons_with_friends_actual, r.lessons_with_friends_goal,
         r.follow_up_lessons_actual, r.follow_up_lessons_goal
  FROM reports r
  JOIN weeks w ON w.id = r.reporting_week_id
  JOIN public.areas a ON a.id = r.area_id
  JOIN public.districts d ON d.id = a.district_id
  JOIN public.zones z ON z.id = d.zone_id
  LEFT JOIN public.units u ON u.id = r.unit_id
  LEFT JOIN goals p ON p.reporting_week_id = w.previous_id AND p.area_id = r.area_id
                   AND p.unit_id IS NOT DISTINCT FROM r.unit_id
$$;
REVOKE ALL ON FUNCTION dashboards.area_week_rows() FROM PUBLIC, anon, authenticated;
COMMENT ON FUNCTION dashboards.area_week_rows() IS 'Rows of dashboards.kpi_area_week. Runs as postgres so the reader needs no rights on public.*.';

CREATE OR REPLACE VIEW dashboards.kpi_area_week AS
  SELECT * FROM dashboards.area_week_rows();
COMMENT ON VIEW dashboards.kpi_area_week IS 'One row per weekly report (area and ward/branch). week = reporting Sunday 12:00 Europe/Berlin (Grafana time column). <kpi>_goal is the goal set this week for next week; <kpi>_previous_goal is the goal the same area set for the same ward/branch last reporting week. For area and district totals that match Call-ins use kpi_area_total_week.';

-- Totals per week and area (all its wards/branches together): the rows of the district Call-ins.
-- previous_goal is the sum of all the area's reports in the previous reporting week, paired exactly
-- as Call-ins do (get_call_in_planning_previous_goals), so it stays right when an area reports for a
-- different ward/branch than the week before. An area that set goals last week but has no report
-- yet this week still gets a row (reports = 0), so areas add up to their district, zone and mission.
CREATE OR REPLACE VIEW dashboards.kpi_area_total_week AS
  WITH base AS MATERIALIZED (
    SELECT * FROM dashboards.kpi_area_week
  ), totals AS (
    SELECT k.reporting_week_id, k.area_id,
           count(*) AS reports, count(*) FILTER (WHERE k.submitted) AS submitted_reports,
           count(DISTINCT k.unit_id) AS units_reporting,
           sum(coalesce(k.friends_found_actual, 0)) AS friends_found_actual,
           sum(coalesce(k.friends_found_goal, 0)) AS friends_found_goal,
           sum(coalesce(k.baptisms_confirmations_actual, 0)) AS baptisms_confirmations_actual,
           sum(coalesce(k.baptisms_confirmations_goal, 0)) AS baptisms_confirmations_goal,
           sum(coalesce(k.baptismal_dates_actual, 0)) AS baptismal_dates_actual,
           sum(coalesce(k.baptismal_dates_goal, 0)) AS baptismal_dates_goal,
           sum(coalesce(k.sacrament_attendance_actual, 0)) AS sacrament_attendance_actual,
           sum(coalesce(k.sacrament_attendance_goal, 0)) AS sacrament_attendance_goal,
           sum(coalesce(k.members_at_lessons_actual, 0)) AS members_at_lessons_actual,
           sum(coalesce(k.members_at_lessons_goal, 0)) AS members_at_lessons_goal,
           sum(coalesce(k.new_member_sacrament_actual, 0)) AS new_member_sacrament_actual,
           sum(coalesce(k.new_member_sacrament_goal, 0)) AS new_member_sacrament_goal,
           sum(coalesce(k.first_time_sacrament_actual, 0)) AS first_time_sacrament_actual,
           sum(coalesce(k.lessons_with_friends_actual, 0)) AS lessons_with_friends_actual,
           sum(coalesce(k.lessons_with_friends_goal, 0)) AS lessons_with_friends_goal,
           sum(coalesce(k.follow_up_lessons_actual, 0)) AS follow_up_lessons_actual,
           sum(coalesce(k.follow_up_lessons_goal, 0)) AS follow_up_lessons_goal
    FROM base k
    GROUP BY k.reporting_week_id, k.area_id
  ), areas AS (
    SELECT DISTINCT k.mission_id, k.zone_id, k.zone, k.district_id, k.district, k.area_id, k.area FROM base k
  ), weeks AS (
    SELECT DISTINCT k.reporting_week_id, k.previous_reporting_week_id, k.week, k.sunday FROM base k
  ), cells AS (
    SELECT DISTINCT w.reporting_week_id, x.area_id
    FROM weeks w
    JOIN totals x ON x.reporting_week_id IN (w.reporting_week_id, w.previous_reporting_week_id)
  )
  SELECT w.week, w.sunday, w.reporting_week_id, a.mission_id, a.zone_id, a.zone, a.district_id, a.district,
         a.area_id, a.area,
         coalesce(t.reports, 0) AS reports, coalesce(t.submitted_reports, 0) AS submitted_reports,
         coalesce(t.units_reporting, 0) AS units_reporting,
         t.friends_found_actual, t.friends_found_goal, p.friends_found_goal AS friends_found_previous_goal,
         t.baptisms_confirmations_actual, t.baptisms_confirmations_goal,
         p.baptisms_confirmations_goal AS baptisms_confirmations_previous_goal,
         t.baptismal_dates_actual, t.baptismal_dates_goal, p.baptismal_dates_goal AS baptismal_dates_previous_goal,
         t.sacrament_attendance_actual, t.sacrament_attendance_goal,
         p.sacrament_attendance_goal AS sacrament_attendance_previous_goal,
         t.members_at_lessons_actual, t.members_at_lessons_goal,
         p.members_at_lessons_goal AS members_at_lessons_previous_goal,
         t.new_member_sacrament_actual, t.new_member_sacrament_goal,
         p.new_member_sacrament_goal AS new_member_sacrament_previous_goal,
         t.first_time_sacrament_actual, t.lessons_with_friends_actual, t.lessons_with_friends_goal,
         t.follow_up_lessons_actual, t.follow_up_lessons_goal
  FROM cells c
  JOIN weeks w ON w.reporting_week_id = c.reporting_week_id
  JOIN areas a ON a.area_id = c.area_id
  LEFT JOIN totals t ON t.reporting_week_id = c.reporting_week_id AND t.area_id = c.area_id
  LEFT JOIN totals p ON p.reporting_week_id = w.previous_reporting_week_id AND p.area_id = c.area_id;
COMMENT ON VIEW dashboards.kpi_area_total_week IS 'Totals per reporting week and area (all its wards/branches), as in the district Call-ins. <kpi>_previous_goal = all goals the area set in the previous reporting week (as in Call-ins). An area without reports this week has reports = 0 and empty results.';

-- Totals per week and zone. previous_goal is the zone total of the previous reporting week's goals,
-- the same figure the mission Call-ins show as "last week goal". A zone that set goals last week
-- but has no report yet this week still gets a row (reports = 0), so adding up the zones always
-- gives the mission total.
CREATE OR REPLACE VIEW dashboards.kpi_zone_week AS
  WITH base AS MATERIALIZED (
    SELECT * FROM dashboards.kpi_area_week
  ), totals AS (
    SELECT k.reporting_week_id, k.mission_id, k.zone_id, min(k.zone) AS zone,
           count(*) AS reports, count(*) FILTER (WHERE k.submitted) AS submitted_reports,
           count(DISTINCT k.area_id) AS areas_reporting,
           sum(coalesce(k.friends_found_actual, 0)) AS friends_found_actual,
           sum(coalesce(k.friends_found_goal, 0)) AS friends_found_goal,
           sum(coalesce(k.baptisms_confirmations_actual, 0)) AS baptisms_confirmations_actual,
           sum(coalesce(k.baptisms_confirmations_goal, 0)) AS baptisms_confirmations_goal,
           sum(coalesce(k.baptismal_dates_actual, 0)) AS baptismal_dates_actual,
           sum(coalesce(k.baptismal_dates_goal, 0)) AS baptismal_dates_goal,
           sum(coalesce(k.sacrament_attendance_actual, 0)) AS sacrament_attendance_actual,
           sum(coalesce(k.sacrament_attendance_goal, 0)) AS sacrament_attendance_goal,
           sum(coalesce(k.members_at_lessons_actual, 0)) AS members_at_lessons_actual,
           sum(coalesce(k.members_at_lessons_goal, 0)) AS members_at_lessons_goal,
           sum(coalesce(k.new_member_sacrament_actual, 0)) AS new_member_sacrament_actual,
           sum(coalesce(k.new_member_sacrament_goal, 0)) AS new_member_sacrament_goal,
           sum(coalesce(k.first_time_sacrament_actual, 0)) AS first_time_sacrament_actual,
           sum(coalesce(k.lessons_with_friends_actual, 0)) AS lessons_with_friends_actual,
           sum(coalesce(k.lessons_with_friends_goal, 0)) AS lessons_with_friends_goal,
           sum(coalesce(k.follow_up_lessons_actual, 0)) AS follow_up_lessons_actual,
           sum(coalesce(k.follow_up_lessons_goal, 0)) AS follow_up_lessons_goal
    FROM base k
    GROUP BY k.reporting_week_id, k.mission_id, k.zone_id
  ), weeks AS (
    SELECT DISTINCT k.reporting_week_id, k.previous_reporting_week_id, k.week, k.sunday FROM base k
  ), cells AS (
    SELECT DISTINCT w.reporting_week_id, x.mission_id, x.zone_id, x.zone
    FROM weeks w
    JOIN totals x ON x.reporting_week_id IN (w.reporting_week_id, w.previous_reporting_week_id)
  )
  SELECT w.week, w.sunday, w.reporting_week_id, c.mission_id, c.zone_id, c.zone,
         coalesce(t.reports, 0) AS reports, coalesce(t.submitted_reports, 0) AS submitted_reports,
         coalesce(t.areas_reporting, 0) AS areas_reporting,
         t.friends_found_actual, t.friends_found_goal, p.friends_found_goal AS friends_found_previous_goal,
         t.baptisms_confirmations_actual, t.baptisms_confirmations_goal,
         p.baptisms_confirmations_goal AS baptisms_confirmations_previous_goal,
         t.baptismal_dates_actual, t.baptismal_dates_goal, p.baptismal_dates_goal AS baptismal_dates_previous_goal,
         t.sacrament_attendance_actual, t.sacrament_attendance_goal,
         p.sacrament_attendance_goal AS sacrament_attendance_previous_goal,
         t.members_at_lessons_actual, t.members_at_lessons_goal,
         p.members_at_lessons_goal AS members_at_lessons_previous_goal,
         t.new_member_sacrament_actual, t.new_member_sacrament_goal,
         p.new_member_sacrament_goal AS new_member_sacrament_previous_goal,
         t.first_time_sacrament_actual, t.lessons_with_friends_actual, t.lessons_with_friends_goal,
         t.follow_up_lessons_actual, t.follow_up_lessons_goal
  FROM cells c
  JOIN weeks w ON w.reporting_week_id = c.reporting_week_id
  LEFT JOIN totals t ON t.reporting_week_id = c.reporting_week_id AND t.zone_id = c.zone_id
  LEFT JOIN totals p ON p.reporting_week_id = w.previous_reporting_week_id AND p.zone_id = c.zone_id;
COMMENT ON VIEW dashboards.kpi_zone_week IS 'Totals per reporting week and zone, with report counts. <kpi>_previous_goal = the zone''s goals set in the previous reporting week (as in Call-ins). A zone without reports this week has reports = 0 and empty results.';

CREATE OR REPLACE VIEW dashboards.kpi_mission_week AS
  WITH totals AS (
    SELECT min(k.week) AS week, min(k.sunday) AS sunday, k.reporting_week_id,
           min(k.previous_reporting_week_id) AS previous_reporting_week_id, k.mission_id,
           count(*) AS reports, count(*) FILTER (WHERE k.submitted) AS submitted_reports,
           count(DISTINCT k.area_id) AS areas_reporting, count(DISTINCT k.zone_id) AS zones_reporting,
           sum(coalesce(k.friends_found_actual, 0)) AS friends_found_actual,
           sum(coalesce(k.friends_found_goal, 0)) AS friends_found_goal,
           sum(coalesce(k.baptisms_confirmations_actual, 0)) AS baptisms_confirmations_actual,
           sum(coalesce(k.baptisms_confirmations_goal, 0)) AS baptisms_confirmations_goal,
           sum(coalesce(k.baptismal_dates_actual, 0)) AS baptismal_dates_actual,
           sum(coalesce(k.baptismal_dates_goal, 0)) AS baptismal_dates_goal,
           sum(coalesce(k.sacrament_attendance_actual, 0)) AS sacrament_attendance_actual,
           sum(coalesce(k.sacrament_attendance_goal, 0)) AS sacrament_attendance_goal,
           sum(coalesce(k.members_at_lessons_actual, 0)) AS members_at_lessons_actual,
           sum(coalesce(k.members_at_lessons_goal, 0)) AS members_at_lessons_goal,
           sum(coalesce(k.new_member_sacrament_actual, 0)) AS new_member_sacrament_actual,
           sum(coalesce(k.new_member_sacrament_goal, 0)) AS new_member_sacrament_goal,
           sum(coalesce(k.first_time_sacrament_actual, 0)) AS first_time_sacrament_actual,
           sum(coalesce(k.lessons_with_friends_actual, 0)) AS lessons_with_friends_actual,
           sum(coalesce(k.lessons_with_friends_goal, 0)) AS lessons_with_friends_goal,
           sum(coalesce(k.follow_up_lessons_actual, 0)) AS follow_up_lessons_actual,
           sum(coalesce(k.follow_up_lessons_goal, 0)) AS follow_up_lessons_goal
    FROM dashboards.kpi_area_week k
    GROUP BY k.reporting_week_id, k.mission_id
  )
  SELECT t.week, t.sunday, t.reporting_week_id, t.mission_id,
         t.reports, t.submitted_reports, t.areas_reporting, t.zones_reporting,
         t.friends_found_actual, t.friends_found_goal, p.friends_found_goal AS friends_found_previous_goal,
         t.baptisms_confirmations_actual, t.baptisms_confirmations_goal,
         p.baptisms_confirmations_goal AS baptisms_confirmations_previous_goal,
         t.baptismal_dates_actual, t.baptismal_dates_goal, p.baptismal_dates_goal AS baptismal_dates_previous_goal,
         t.sacrament_attendance_actual, t.sacrament_attendance_goal,
         p.sacrament_attendance_goal AS sacrament_attendance_previous_goal,
         t.members_at_lessons_actual, t.members_at_lessons_goal,
         p.members_at_lessons_goal AS members_at_lessons_previous_goal,
         t.new_member_sacrament_actual, t.new_member_sacrament_goal,
         p.new_member_sacrament_goal AS new_member_sacrament_previous_goal,
         t.first_time_sacrament_actual, t.lessons_with_friends_actual, t.lessons_with_friends_goal,
         t.follow_up_lessons_actual, t.follow_up_lessons_goal
  FROM totals t
  LEFT JOIN totals p ON p.reporting_week_id = t.previous_reporting_week_id AND p.mission_id = t.mission_id;
COMMENT ON VIEW dashboards.kpi_mission_week IS 'Mission totals per reporting week, with report counts. <kpi>_previous_goal = the goals set in the previous reporting week (as in Call-ins).';

REVOKE ALL ON dashboards.kpi_area_week, dashboards.kpi_area_total_week, dashboards.kpi_zone_week,
  dashboards.kpi_mission_week FROM PUBLIC, anon, authenticated;
GRANT USAGE ON SCHEMA dashboards TO gfm_dashboard_reader;
GRANT EXECUTE ON FUNCTION dashboards.area_week_rows() TO gfm_dashboard_reader;
GRANT SELECT ON dashboards.kpi_area_week, dashboards.kpi_area_total_week, dashboards.kpi_zone_week,
  dashboards.kpi_mission_week TO gfm_dashboard_reader;

COMMIT;

-- Rollback (stop Grafana first, or its data source reports errors until it is removed):
-- BEGIN;
-- DROP VIEW IF EXISTS dashboards.kpi_mission_week, dashboards.kpi_zone_week, dashboards.kpi_area_total_week,
--   dashboards.kpi_area_week;
-- DROP FUNCTION IF EXISTS dashboards.area_week_rows();
-- DROP SCHEMA IF EXISTS dashboards;
-- DROP ROLE IF EXISTS gfm_dashboard_reader;
-- COMMIT;
