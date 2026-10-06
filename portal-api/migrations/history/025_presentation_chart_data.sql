-- Numbers for database charts in Presentations (and Grafana): people counts and district key indicators.
-- Run on Beta only, as supabase_admin.
--
-- Why: slides can now draw charts straight from the database (portal-api charts.py, the Slidev manager's
-- /api/charts/*, the chart builder in /studio). The key indicators were already in the dashboards views of 018,
-- but there was no district view, and nothing about the people on the weekly plans (new members, friends with a
-- baptismal date, high-potential friends). Those numbers live in tables with names and notes, which charts must
-- never see. This file adds count-only views, so a chart (or a Grafana panel) can show "new members at church"
-- without any right on the people tables.
--
-- What changes (nothing existing is altered; everything new lives in the dashboards schema of 018):
-- 1. dashboards.kpi_district_week: the key indicators per reporting week and district, the sum of
--    kpi_area_total_week (so "goal set last week" is paired per area exactly as in Call-ins), with report counts
--    and areas_reporting.
-- 2. dashboards.people_area_week_counts (internal, NOT readable by gfm_dashboard_reader): per reporting week and
--    area, how many people were on the plans and how many of them answered yes to each question. Counts only:
--    no names, no notes, no person ids. Every plan of the week counts (drafts too), like the key indicators.
--      new members: total, at church, active temple recommend, calling, Aaronic Priesthood, Melchizedek
--        Priesthood, ministers to someone, has a minister, visited the temple, reading, praying, member
--        involvement, discussed in GEMIKO (the yes/no questions of the weekly New Member card);
--      friends with a baptismal date: total, date within the next 4 weeks (0 to 28 days after the plan's
--        Sunday), at church, reading, praying, keeping the commandments, member involvement;
--      high-potential friends: total, at church.
-- 3. dashboards.people_mission_week, people_zone_week, people_district_week: those counts added up, with
--    areas_reporting (areas with a plan that week).
-- 4. dashboards.people_area_week: the same per area, with small numbers hidden: a total below 3 is NULL, and a
--    yes-count is NULL unless at least 3 people answered yes AND at least 3 did not (so "all of them" and "all
--    but one" cannot be read off either). Zero counts as small, so it is hidden too.
--    Note: a district total minus the areas that are shown can still reveal the sum of the hidden areas. The
--    rule protects a single area chart, not a reader who compares several levels; district and higher totals
--    are not suppressed (they go to leaders who know these people).
-- 5. gfm_dashboard_reader (018) may read the views of 1, 3 and 4, nothing else new. postgres becomes a member of
--    gfm_dashboard_reader so portal-api (which connects as postgres) can run every chart query with
--    SET LOCAL ROLE gfm_dashboard_reader in a read-only transaction: a chart can only ever read what Grafana
--    may read.
-- No SECURITY DEFINER function is added or changed: the views are ordinary views owned by postgres, so they read
-- the tables with postgres's rights while the reader only has SELECT on the views themselves.
--
-- Apply (back up Beta first; after 018 and 019). Join the lines with plain line feeds:
--   (Get-Content portal-api/migrations/025_presentation_chart_data.sql) -join "`n" |
--     docker exec -i gfm-beta-supabase-db-1 psql -U supabase_admin -d postgres -v ON_ERROR_STOP=1
--   (Git Bash: sed 's/\r$//' portal-api/migrations/025_presentation_chart_data.sql | docker exec -i ...)
-- Then run 019 again as a check (it must end with COMMIT):
--   Get-Content portal-api/migrations/019_restrict_public_functions.sql -Raw |
--     docker exec -i gfm-beta-supabase-db-1 psql -U supabase_admin -d postgres -v ON_ERROR_STOP=1
-- The file waits at most 10 seconds for a lock (lock timeout), then stops; run it again.
-- Safe to run again: CREATE OR REPLACE VIEW, GRANT and REVOKE only, then a check that stops on any problem.
-- Rollback: 025_presentation_chart_data_rollback.sql (same way of running). Chart slides that read these views
-- then show "Mission numbers are not available right now."
BEGIN;
SET LOCAL lock_timeout = '10s';

DO $$
BEGIN
  IF session_user NOT IN ('supabase_admin', 'postgres') THEN
    RAISE EXCEPTION 'Run this file as supabase_admin (see its header), not as %.', session_user;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'gfm_dashboard_reader')
     OR to_regclass('dashboards.kpi_area_total_week') IS NULL THEN
    RAISE EXCEPTION 'Apply 018_dashboard_reporting.sql first.';
  END IF;
END $$;

-- 5a. portal-api (postgres) may switch to the reader for chart queries. The reader's own settings (read only,
-- 15 s statement timeout) apply only when it signs in itself; portal-api sets both for every chart query.
GRANT gfm_dashboard_reader TO postgres;

-- Everything below belongs to postgres, like the views of 018.
SET LOCAL ROLE postgres;

-- 1. Key indicators per district: the areas of kpi_area_total_week added up.
CREATE OR REPLACE VIEW dashboards.kpi_district_week AS
  SELECT k.week, k.sunday, k.reporting_week_id, k.mission_id, k.zone_id, k.zone, k.district_id, k.district,
         sum(k.reports)::bigint AS reports, sum(k.submitted_reports)::bigint AS submitted_reports,
         count(*) FILTER (WHERE k.reports > 0) AS areas_reporting,
         sum(k.friends_found_actual)::bigint AS friends_found_actual,
         sum(k.friends_found_goal)::bigint AS friends_found_goal,
         sum(k.friends_found_previous_goal)::bigint AS friends_found_previous_goal,
         sum(k.baptisms_confirmations_actual)::bigint AS baptisms_confirmations_actual,
         sum(k.baptisms_confirmations_goal)::bigint AS baptisms_confirmations_goal,
         sum(k.baptisms_confirmations_previous_goal)::bigint AS baptisms_confirmations_previous_goal,
         sum(k.baptismal_dates_actual)::bigint AS baptismal_dates_actual,
         sum(k.baptismal_dates_goal)::bigint AS baptismal_dates_goal,
         sum(k.baptismal_dates_previous_goal)::bigint AS baptismal_dates_previous_goal,
         sum(k.sacrament_attendance_actual)::bigint AS sacrament_attendance_actual,
         sum(k.sacrament_attendance_goal)::bigint AS sacrament_attendance_goal,
         sum(k.sacrament_attendance_previous_goal)::bigint AS sacrament_attendance_previous_goal,
         sum(k.members_at_lessons_actual)::bigint AS members_at_lessons_actual,
         sum(k.members_at_lessons_goal)::bigint AS members_at_lessons_goal,
         sum(k.members_at_lessons_previous_goal)::bigint AS members_at_lessons_previous_goal,
         sum(k.new_member_sacrament_actual)::bigint AS new_member_sacrament_actual,
         sum(k.new_member_sacrament_goal)::bigint AS new_member_sacrament_goal,
         sum(k.new_member_sacrament_previous_goal)::bigint AS new_member_sacrament_previous_goal,
         sum(k.first_time_sacrament_actual)::bigint AS first_time_sacrament_actual,
         sum(k.lessons_with_friends_actual)::bigint AS lessons_with_friends_actual,
         sum(k.lessons_with_friends_goal)::bigint AS lessons_with_friends_goal,
         sum(k.follow_up_lessons_actual)::bigint AS follow_up_lessons_actual,
         sum(k.follow_up_lessons_goal)::bigint AS follow_up_lessons_goal
  FROM dashboards.kpi_area_total_week k
  GROUP BY k.week, k.sunday, k.reporting_week_id, k.mission_id, k.zone_id, k.zone, k.district_id, k.district;
COMMENT ON VIEW dashboards.kpi_district_week IS 'Key indicators per reporting week and district: the sum of kpi_area_total_week (so <kpi>_previous_goal is paired per area, as in Call-ins). areas_reporting = areas with at least one plan that week. A district without plans this week has reports = 0 and empty results.';

-- 2. People counts per week and area (internal: never grant this view; people_area_week is the readable one).
CREATE OR REPLACE VIEW dashboards.people_area_week_counts AS
  WITH cells AS (
    SELECT DISTINCT r.reporting_week_id, r.area_id FROM public.weekly_area_reports r
  ), nm AS (
    SELECT r.reporting_week_id, r.area_id,
           count(*) AS new_members,
           count(*) FILTER (WHERE n.at_church_this_sunday) AS new_members_at_church,
           count(*) FILTER (WHERE n.has_active_temple_recommend = 'yes') AS new_members_temple_recommend,
           count(*) FILTER (WHERE n.has_calling = 'yes') AS new_members_calling,
           count(*) FILTER (WHERE n.has_aaronic_priesthood = 'yes') AS new_members_aaronic_priesthood,
           count(*) FILTER (WHERE n.has_melchizedek_priesthood = 'yes') AS new_members_melchizedek_priesthood,
           count(*) FILTER (WHERE n.ministers_to_someone = 'yes') AS new_members_ministering,
           count(*) FILTER (WHERE n.ministered_to_by_someone) AS new_members_with_minister,
           count(*) FILTER (WHERE n.visited_temple_for_baptisms = 'yes') AS new_members_visited_temple,
           count(*) FILTER (WHERE n.reading) AS new_members_reading,
           count(*) FILTER (WHERE n.praying) AS new_members_praying,
           count(*) FILTER (WHERE n.member_involvement) AS new_members_member_involvement,
           count(*) FILTER (WHERE n.discussed_in_gemiko) AS new_members_discussed_in_gemiko
    FROM public.weekly_new_members n
    JOIN public.weekly_area_reports r ON r.id = n.weekly_area_report_id
    GROUP BY r.reporting_week_id, r.area_id
  ), bd AS (
    SELECT r.reporting_week_id, r.area_id,
           count(*) AS baptismal_date_friends,
           count(*) FILTER (WHERE f.current_baptismal_date BETWEEN w.sunday AND w.sunday + 28) AS baptismal_date_friends_next_4_weeks,
           count(*) FILTER (WHERE f.at_church_this_sunday) AS baptismal_date_friends_at_church,
           count(*) FILTER (WHERE f.reading) AS baptismal_date_friends_reading,
           count(*) FILTER (WHERE f.praying) AS baptismal_date_friends_praying,
           count(*) FILTER (WHERE f.keeping_commandments) AS baptismal_date_friends_keeping_commandments,
           count(*) FILTER (WHERE f.member_involvement) AS baptismal_date_friends_member_involvement
    FROM public.weekly_baptismal_date_friends f
    JOIN public.weekly_area_reports r ON r.id = f.weekly_area_report_id
    JOIN public.reporting_weeks w ON w.id = r.reporting_week_id
    GROUP BY r.reporting_week_id, r.area_id
  ), hp AS (
    SELECT r.reporting_week_id, r.area_id,
           count(*) AS high_potentials,
           count(*) FILTER (WHERE h.at_church_this_sunday) AS high_potentials_at_church
    FROM public.weekly_high_potential_friends h
    JOIN public.weekly_area_reports r ON r.id = h.weekly_area_report_id
    GROUP BY r.reporting_week_id, r.area_id
  )
  SELECT (w.sunday + time '12:00') AT TIME ZONE 'Europe/Berlin' AS week, w.sunday, w.id AS reporting_week_id,
         z.mission_id, z.id AS zone_id, z.name AS zone, d.id AS district_id, d.name AS district,
         a.id AS area_id, a.name AS area,
         coalesce(nm.new_members, 0) AS new_members,
         coalesce(nm.new_members_at_church, 0) AS new_members_at_church,
         coalesce(nm.new_members_temple_recommend, 0) AS new_members_temple_recommend,
         coalesce(nm.new_members_calling, 0) AS new_members_calling,
         coalesce(nm.new_members_aaronic_priesthood, 0) AS new_members_aaronic_priesthood,
         coalesce(nm.new_members_melchizedek_priesthood, 0) AS new_members_melchizedek_priesthood,
         coalesce(nm.new_members_ministering, 0) AS new_members_ministering,
         coalesce(nm.new_members_with_minister, 0) AS new_members_with_minister,
         coalesce(nm.new_members_visited_temple, 0) AS new_members_visited_temple,
         coalesce(nm.new_members_reading, 0) AS new_members_reading,
         coalesce(nm.new_members_praying, 0) AS new_members_praying,
         coalesce(nm.new_members_member_involvement, 0) AS new_members_member_involvement,
         coalesce(nm.new_members_discussed_in_gemiko, 0) AS new_members_discussed_in_gemiko,
         coalesce(bd.baptismal_date_friends, 0) AS baptismal_date_friends,
         coalesce(bd.baptismal_date_friends_next_4_weeks, 0) AS baptismal_date_friends_next_4_weeks,
         coalesce(bd.baptismal_date_friends_at_church, 0) AS baptismal_date_friends_at_church,
         coalesce(bd.baptismal_date_friends_reading, 0) AS baptismal_date_friends_reading,
         coalesce(bd.baptismal_date_friends_praying, 0) AS baptismal_date_friends_praying,
         coalesce(bd.baptismal_date_friends_keeping_commandments, 0) AS baptismal_date_friends_keeping_commandments,
         coalesce(bd.baptismal_date_friends_member_involvement, 0) AS baptismal_date_friends_member_involvement,
         coalesce(hp.high_potentials, 0) AS high_potentials,
         coalesce(hp.high_potentials_at_church, 0) AS high_potentials_at_church
  FROM cells c
  JOIN public.reporting_weeks w ON w.id = c.reporting_week_id
  JOIN public.areas a ON a.id = c.area_id
  JOIN public.districts d ON d.id = a.district_id
  JOIN public.zones z ON z.id = d.zone_id
  LEFT JOIN nm ON nm.reporting_week_id = c.reporting_week_id AND nm.area_id = c.area_id
  LEFT JOIN bd ON bd.reporting_week_id = c.reporting_week_id AND bd.area_id = c.area_id
  LEFT JOIN hp ON hp.reporting_week_id = c.reporting_week_id AND hp.area_id = c.area_id;
COMMENT ON VIEW dashboards.people_area_week_counts IS 'INTERNAL, never grant: unsuppressed people counts per reporting week and area (areas with a plan that week), the source of people_*_week. Counts only, no names or notes.';

-- 3. The same counts added up per mission, zone and district.
CREATE OR REPLACE VIEW dashboards.people_mission_week AS
  SELECT c.week, c.sunday, c.reporting_week_id, c.mission_id,
         count(*) AS areas_reporting,
         sum(c.new_members)::bigint AS new_members,
         sum(c.new_members_at_church)::bigint AS new_members_at_church,
         sum(c.new_members_temple_recommend)::bigint AS new_members_temple_recommend,
         sum(c.new_members_calling)::bigint AS new_members_calling,
         sum(c.new_members_aaronic_priesthood)::bigint AS new_members_aaronic_priesthood,
         sum(c.new_members_melchizedek_priesthood)::bigint AS new_members_melchizedek_priesthood,
         sum(c.new_members_ministering)::bigint AS new_members_ministering,
         sum(c.new_members_with_minister)::bigint AS new_members_with_minister,
         sum(c.new_members_visited_temple)::bigint AS new_members_visited_temple,
         sum(c.new_members_reading)::bigint AS new_members_reading,
         sum(c.new_members_praying)::bigint AS new_members_praying,
         sum(c.new_members_member_involvement)::bigint AS new_members_member_involvement,
         sum(c.new_members_discussed_in_gemiko)::bigint AS new_members_discussed_in_gemiko,
         sum(c.baptismal_date_friends)::bigint AS baptismal_date_friends,
         sum(c.baptismal_date_friends_next_4_weeks)::bigint AS baptismal_date_friends_next_4_weeks,
         sum(c.baptismal_date_friends_at_church)::bigint AS baptismal_date_friends_at_church,
         sum(c.baptismal_date_friends_reading)::bigint AS baptismal_date_friends_reading,
         sum(c.baptismal_date_friends_praying)::bigint AS baptismal_date_friends_praying,
         sum(c.baptismal_date_friends_keeping_commandments)::bigint AS baptismal_date_friends_keeping_commandments,
         sum(c.baptismal_date_friends_member_involvement)::bigint AS baptismal_date_friends_member_involvement,
         sum(c.high_potentials)::bigint AS high_potentials,
         sum(c.high_potentials_at_church)::bigint AS high_potentials_at_church
  FROM dashboards.people_area_week_counts c
  GROUP BY c.week, c.sunday, c.reporting_week_id, c.mission_id;
COMMENT ON VIEW dashboards.people_mission_week IS 'People on the weekly plans per reporting week (mission totals): new members, friends with a baptismal date and high-potential friends, with how many answered yes to each question. Counts only. areas_reporting = areas with a plan that week.';

CREATE OR REPLACE VIEW dashboards.people_zone_week AS
  SELECT c.week, c.sunday, c.reporting_week_id, c.mission_id, c.zone_id, c.zone,
         count(*) AS areas_reporting,
         sum(c.new_members)::bigint AS new_members,
         sum(c.new_members_at_church)::bigint AS new_members_at_church,
         sum(c.new_members_temple_recommend)::bigint AS new_members_temple_recommend,
         sum(c.new_members_calling)::bigint AS new_members_calling,
         sum(c.new_members_aaronic_priesthood)::bigint AS new_members_aaronic_priesthood,
         sum(c.new_members_melchizedek_priesthood)::bigint AS new_members_melchizedek_priesthood,
         sum(c.new_members_ministering)::bigint AS new_members_ministering,
         sum(c.new_members_with_minister)::bigint AS new_members_with_minister,
         sum(c.new_members_visited_temple)::bigint AS new_members_visited_temple,
         sum(c.new_members_reading)::bigint AS new_members_reading,
         sum(c.new_members_praying)::bigint AS new_members_praying,
         sum(c.new_members_member_involvement)::bigint AS new_members_member_involvement,
         sum(c.new_members_discussed_in_gemiko)::bigint AS new_members_discussed_in_gemiko,
         sum(c.baptismal_date_friends)::bigint AS baptismal_date_friends,
         sum(c.baptismal_date_friends_next_4_weeks)::bigint AS baptismal_date_friends_next_4_weeks,
         sum(c.baptismal_date_friends_at_church)::bigint AS baptismal_date_friends_at_church,
         sum(c.baptismal_date_friends_reading)::bigint AS baptismal_date_friends_reading,
         sum(c.baptismal_date_friends_praying)::bigint AS baptismal_date_friends_praying,
         sum(c.baptismal_date_friends_keeping_commandments)::bigint AS baptismal_date_friends_keeping_commandments,
         sum(c.baptismal_date_friends_member_involvement)::bigint AS baptismal_date_friends_member_involvement,
         sum(c.high_potentials)::bigint AS high_potentials,
         sum(c.high_potentials_at_church)::bigint AS high_potentials_at_church
  FROM dashboards.people_area_week_counts c
  GROUP BY c.week, c.sunday, c.reporting_week_id, c.mission_id, c.zone_id, c.zone;
COMMENT ON VIEW dashboards.people_zone_week IS 'People on the weekly plans per reporting week and zone (see people_mission_week). Counts only.';

CREATE OR REPLACE VIEW dashboards.people_district_week AS
  SELECT c.week, c.sunday, c.reporting_week_id, c.mission_id, c.zone_id, c.zone, c.district_id, c.district,
         count(*) AS areas_reporting,
         sum(c.new_members)::bigint AS new_members,
         sum(c.new_members_at_church)::bigint AS new_members_at_church,
         sum(c.new_members_temple_recommend)::bigint AS new_members_temple_recommend,
         sum(c.new_members_calling)::bigint AS new_members_calling,
         sum(c.new_members_aaronic_priesthood)::bigint AS new_members_aaronic_priesthood,
         sum(c.new_members_melchizedek_priesthood)::bigint AS new_members_melchizedek_priesthood,
         sum(c.new_members_ministering)::bigint AS new_members_ministering,
         sum(c.new_members_with_minister)::bigint AS new_members_with_minister,
         sum(c.new_members_visited_temple)::bigint AS new_members_visited_temple,
         sum(c.new_members_reading)::bigint AS new_members_reading,
         sum(c.new_members_praying)::bigint AS new_members_praying,
         sum(c.new_members_member_involvement)::bigint AS new_members_member_involvement,
         sum(c.new_members_discussed_in_gemiko)::bigint AS new_members_discussed_in_gemiko,
         sum(c.baptismal_date_friends)::bigint AS baptismal_date_friends,
         sum(c.baptismal_date_friends_next_4_weeks)::bigint AS baptismal_date_friends_next_4_weeks,
         sum(c.baptismal_date_friends_at_church)::bigint AS baptismal_date_friends_at_church,
         sum(c.baptismal_date_friends_reading)::bigint AS baptismal_date_friends_reading,
         sum(c.baptismal_date_friends_praying)::bigint AS baptismal_date_friends_praying,
         sum(c.baptismal_date_friends_keeping_commandments)::bigint AS baptismal_date_friends_keeping_commandments,
         sum(c.baptismal_date_friends_member_involvement)::bigint AS baptismal_date_friends_member_involvement,
         sum(c.high_potentials)::bigint AS high_potentials,
         sum(c.high_potentials_at_church)::bigint AS high_potentials_at_church
  FROM dashboards.people_area_week_counts c
  GROUP BY c.week, c.sunday, c.reporting_week_id, c.mission_id, c.zone_id, c.zone, c.district_id, c.district;
COMMENT ON VIEW dashboards.people_district_week IS 'People on the weekly plans per reporting week and district (see people_mission_week). Counts only.';

-- 4. Per area, with small numbers hidden (see the header). areas_reporting is always 1 (the area had a plan).
CREATE OR REPLACE VIEW dashboards.people_area_week AS
  SELECT c.week, c.sunday, c.reporting_week_id, c.mission_id, c.zone_id, c.zone, c.district_id, c.district,
         c.area_id, c.area, 1::bigint AS areas_reporting,
         CASE WHEN c.new_members >= 3 THEN c.new_members END AS new_members,
         CASE WHEN c.new_members_at_church >= 3 AND c.new_members - c.new_members_at_church >= 3
              THEN c.new_members_at_church END AS new_members_at_church,
         CASE WHEN c.new_members_temple_recommend >= 3 AND c.new_members - c.new_members_temple_recommend >= 3
              THEN c.new_members_temple_recommend END AS new_members_temple_recommend,
         CASE WHEN c.new_members_calling >= 3 AND c.new_members - c.new_members_calling >= 3
              THEN c.new_members_calling END AS new_members_calling,
         CASE WHEN c.new_members_aaronic_priesthood >= 3 AND c.new_members - c.new_members_aaronic_priesthood >= 3
              THEN c.new_members_aaronic_priesthood END AS new_members_aaronic_priesthood,
         CASE WHEN c.new_members_melchizedek_priesthood >= 3 AND c.new_members - c.new_members_melchizedek_priesthood >= 3
              THEN c.new_members_melchizedek_priesthood END AS new_members_melchizedek_priesthood,
         CASE WHEN c.new_members_ministering >= 3 AND c.new_members - c.new_members_ministering >= 3
              THEN c.new_members_ministering END AS new_members_ministering,
         CASE WHEN c.new_members_with_minister >= 3 AND c.new_members - c.new_members_with_minister >= 3
              THEN c.new_members_with_minister END AS new_members_with_minister,
         CASE WHEN c.new_members_visited_temple >= 3 AND c.new_members - c.new_members_visited_temple >= 3
              THEN c.new_members_visited_temple END AS new_members_visited_temple,
         CASE WHEN c.new_members_reading >= 3 AND c.new_members - c.new_members_reading >= 3
              THEN c.new_members_reading END AS new_members_reading,
         CASE WHEN c.new_members_praying >= 3 AND c.new_members - c.new_members_praying >= 3
              THEN c.new_members_praying END AS new_members_praying,
         CASE WHEN c.new_members_member_involvement >= 3 AND c.new_members - c.new_members_member_involvement >= 3
              THEN c.new_members_member_involvement END AS new_members_member_involvement,
         CASE WHEN c.new_members_discussed_in_gemiko >= 3 AND c.new_members - c.new_members_discussed_in_gemiko >= 3
              THEN c.new_members_discussed_in_gemiko END AS new_members_discussed_in_gemiko,
         CASE WHEN c.baptismal_date_friends >= 3 THEN c.baptismal_date_friends END AS baptismal_date_friends,
         CASE WHEN c.baptismal_date_friends_next_4_weeks >= 3 AND c.baptismal_date_friends - c.baptismal_date_friends_next_4_weeks >= 3
              THEN c.baptismal_date_friends_next_4_weeks END AS baptismal_date_friends_next_4_weeks,
         CASE WHEN c.baptismal_date_friends_at_church >= 3 AND c.baptismal_date_friends - c.baptismal_date_friends_at_church >= 3
              THEN c.baptismal_date_friends_at_church END AS baptismal_date_friends_at_church,
         CASE WHEN c.baptismal_date_friends_reading >= 3 AND c.baptismal_date_friends - c.baptismal_date_friends_reading >= 3
              THEN c.baptismal_date_friends_reading END AS baptismal_date_friends_reading,
         CASE WHEN c.baptismal_date_friends_praying >= 3 AND c.baptismal_date_friends - c.baptismal_date_friends_praying >= 3
              THEN c.baptismal_date_friends_praying END AS baptismal_date_friends_praying,
         CASE WHEN c.baptismal_date_friends_keeping_commandments >= 3 AND c.baptismal_date_friends - c.baptismal_date_friends_keeping_commandments >= 3
              THEN c.baptismal_date_friends_keeping_commandments END AS baptismal_date_friends_keeping_commandments,
         CASE WHEN c.baptismal_date_friends_member_involvement >= 3 AND c.baptismal_date_friends - c.baptismal_date_friends_member_involvement >= 3
              THEN c.baptismal_date_friends_member_involvement END AS baptismal_date_friends_member_involvement,
         CASE WHEN c.high_potentials >= 3 THEN c.high_potentials END AS high_potentials,
         CASE WHEN c.high_potentials_at_church >= 3 AND c.high_potentials - c.high_potentials_at_church >= 3
              THEN c.high_potentials_at_church END AS high_potentials_at_church
  FROM dashboards.people_area_week_counts c;
COMMENT ON VIEW dashboards.people_area_week IS 'People on the weekly plans per reporting week and area, with small numbers hidden: a total below 3 is NULL; a yes-count is NULL unless at least 3 answered yes and at least 3 did not. Counts only.';

-- 5b. Rights: the reader gets the readable views; nobody else gets anything (the schema is closed since 018).
REVOKE ALL ON dashboards.kpi_district_week, dashboards.people_area_week_counts, dashboards.people_mission_week,
  dashboards.people_zone_week, dashboards.people_district_week, dashboards.people_area_week
  FROM PUBLIC, anon, authenticated, service_role, gfm_dashboard_reader;
GRANT SELECT ON dashboards.kpi_district_week, dashboards.people_mission_week, dashboards.people_zone_week,
  dashboards.people_district_week, dashboards.people_area_week TO gfm_dashboard_reader;

-- Check: owners, rights, no person columns, suppression, and that the sums add up.
DO $$
DECLARE
  readable text[] := ARRAY['dashboards.kpi_district_week', 'dashboards.people_mission_week', 'dashboards.people_zone_week',
                           'dashboards.people_district_week', 'dashboards.people_area_week'];
  people_tables text[] := ARRAY['public.weekly_new_members', 'public.weekly_baptismal_date_friends',
                                'public.weekly_high_potential_friends', 'public.new_members', 'public.baptismal_date_people',
                                'public.weekly_area_reports', 'public.new_members_clean', 'public.baptismal_dates_clean',
                                'public.high_potentials_clean'];
  found text;
  small bigint;
BEGIN
  IF NOT pg_has_role('postgres', 'gfm_dashboard_reader', 'MEMBER') THEN
    RAISE EXCEPTION 'Check failed: postgres is not a member of gfm_dashboard_reader.';
  END IF;

  SELECT string_agg(v, ', ') INTO found
  FROM unnest(readable || ARRAY['dashboards.people_area_week_counts']) v
  WHERE to_regclass(v) IS NULL OR (SELECT pg_get_userbyid(relowner) FROM pg_class WHERE oid = to_regclass(v)) <> 'postgres'
     OR coalesce((SELECT reloptions FROM pg_class WHERE oid = to_regclass(v)), '{}') @> ARRAY['security_invoker=true'];
  IF found IS NOT NULL THEN RAISE EXCEPTION 'Check failed: missing, not owned by postgres or security_invoker: %', found; END IF;

  SELECT string_agg(v, ', ') INTO found FROM unnest(readable) v
  WHERE NOT has_table_privilege('gfm_dashboard_reader', v, 'SELECT');
  IF found IS NOT NULL THEN RAISE EXCEPTION 'Check failed: gfm_dashboard_reader cannot read %', found; END IF;

  IF has_table_privilege('gfm_dashboard_reader', 'dashboards.people_area_week_counts', 'SELECT') THEN
    RAISE EXCEPTION 'Check failed: gfm_dashboard_reader can read the unsuppressed area counts.';
  END IF;

  SELECT string_agg(format('%s (%s)', v, r), ', ') INTO found
  FROM unnest(readable || ARRAY['dashboards.people_area_week_counts']) v
  CROSS JOIN unnest(ARRAY['public', 'anon', 'authenticated', 'service_role']) r
  WHERE has_table_privilege(r, v, 'SELECT') OR has_table_privilege(r, v, 'INSERT') OR has_table_privilege(r, v, 'UPDATE')
     OR has_table_privilege(r, v, 'DELETE');
  IF found IS NOT NULL THEN RAISE EXCEPTION 'Check failed: these may use the new views: %', found; END IF;

  SELECT string_agg(t, ', ') INTO found FROM unnest(people_tables) t
  WHERE to_regclass(t) IS NOT NULL
    AND (has_table_privilege('gfm_dashboard_reader', t, 'SELECT')
         OR has_any_column_privilege('gfm_dashboard_reader', t, 'SELECT'));
  IF found IS NOT NULL THEN RAISE EXCEPTION 'Check failed: gfm_dashboard_reader can read people tables: %', found; END IF;

  SELECT string_agg(format('%s.%s', c.table_name, c.column_name), ', ') INTO found
  FROM information_schema.columns c
  WHERE c.table_schema = 'dashboards'
    AND c.table_name IN ('kpi_district_week', 'people_area_week_counts', 'people_mission_week', 'people_zone_week',
                         'people_district_week', 'people_area_week')
    AND c.column_name ~ '(name|note|email|phone|how_are|support_plan|person|user|member_id|birth|gender)';
  IF found IS NOT NULL THEN RAISE EXCEPTION 'Check failed: a column looks like personal data: %', found; END IF;

  SELECT string_agg(format('%I < 3', c.column_name), ' OR ') INTO found
  FROM information_schema.columns c
  WHERE c.table_schema = 'dashboards' AND c.table_name = 'people_area_week' AND c.data_type = 'bigint'
    AND c.column_name NOT IN ('reporting_week_id', 'mission_id', 'zone_id', 'district_id', 'area_id', 'areas_reporting');
  EXECUTE 'SELECT count(*) FROM dashboards.people_area_week WHERE ' || found INTO small;
  IF small > 0 THEN RAISE EXCEPTION 'Check failed: % area rows show a number below 3.', small; END IF;

  IF EXISTS (
    SELECT 1 FROM dashboards.people_mission_week m
    JOIN (SELECT reporting_week_id, mission_id, sum(new_members) nm, sum(baptismal_date_friends) bd,
                 sum(high_potentials) hp, sum(areas_reporting) areas
          FROM dashboards.people_zone_week GROUP BY 1, 2) z USING (reporting_week_id, mission_id)
    WHERE (m.new_members, m.baptismal_date_friends, m.high_potentials, m.areas_reporting)
          IS DISTINCT FROM (z.nm::bigint, z.bd::bigint, z.hp::bigint, z.areas::bigint)
  ) THEN
    RAISE EXCEPTION 'Check failed: the zones do not add up to the mission.';
  END IF;

  IF EXISTS (
    SELECT 1 FROM dashboards.kpi_zone_week z
    JOIN (SELECT reporting_week_id, zone_id, sum(friends_found_actual) ff, sum(sacrament_attendance_actual) sa,
                 sum(reports) rp
          FROM dashboards.kpi_district_week GROUP BY 1, 2) d USING (reporting_week_id, zone_id)
    WHERE (z.friends_found_actual, z.sacrament_attendance_actual, z.reports)
          IS DISTINCT FROM (d.ff::bigint, d.sa::bigint, d.rp::bigint)
  ) THEN
    RAISE EXCEPTION 'Check failed: the districts do not add up to their zone.';
  END IF;
END $$;

COMMIT;

-- Verify (read-only, after applying), as postgres:
--   docker exec gfm-beta-supabase-db-1 psql -U postgres -d postgres -c 'BEGIN READ ONLY' -c 'SET LOCAL ROLE gfm_dashboard_reader' -c 'SELECT sunday, new_members, new_members_at_church, baptismal_date_friends, high_potentials FROM dashboards.people_mission_week ORDER BY sunday DESC LIMIT 4' -c 'SELECT count(*) FROM public.weekly_new_members' -c 'ROLLBACK'
-- The first query answers four weeks of counts; the second must fail with "permission denied".
