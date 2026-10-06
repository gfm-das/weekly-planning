-- Rollback of 029_remove_unused.sql. Run on Beta only, as supabase_admin.
--
-- What it restores (the state before 029, read from the live database on 27 Sep 2026 after the 22:50 hotfix):
-- - the 9 functions, 12 views and 2 tables that 029 dropped, with the same definitions, owner (postgres), rights and
--   comments (029 refuses to drop a part that differs from these, so this is exact). The seven *_clean views and
--   the two staging tables get only the rights they had after the hotfix (postgres and service_role): never anon,
--   authenticated or grafana_readonly again;
-- - every right 029 took away, from its record public.cleanup_029_revoked_grants (anon, grafana_readonly, the few of
--   authenticated, and the default rights for new objects), each given by the same grantor; then the record is
--   dropped;
-- - NOT the rows of missionary_import_stage and organization_import_stage: they come back from the backup taken
--   before 029 (step 2 below). This file recreates the two tables empty.
-- Nothing in the code has to be rolled back with it (no code used these parts).
-- This file was generated from live Beta's definitions (read-only); do not edit the definitions by hand.
--
-- Apply:
-- 1. (Get-Content portal-api/migrations/029_remove_unused_rollback.sql) -join "`n" |
--      docker exec -i gfm-beta-supabase-db-1 psql -U supabase_admin -d postgres -v ON_ERROR_STOP=1
--    (Git Bash: sed 's/\r$//' portal-api/migrations/029_remove_unused_rollback.sql | docker exec -i ...)
--    It prints "029 rollback: 23 parts back, N rights given back" and must end with COMMIT.
-- 2. The staging tables' rows, from the backup taken before 029 (only the data of these two tables):
--      docker cp backups/beta-pre-029-<date>.dump gfm-beta-supabase-db-1:/tmp/beta-pre-029.dump
--      docker exec gfm-beta-supabase-db-1 pg_restore -U postgres -d postgres --data-only -t missionary_import_stage -t organization_import_stage /tmp/beta-pre-029.dump
--      docker exec gfm-beta-supabase-db-1 rm /tmp/beta-pre-029.dump
--    Then (read-only) the counts must be 168 and 24:
--      docker exec gfm-beta-supabase-db-1 psql -U postgres -d postgres -At -c "SELECT (SELECT count(*) FROM public.missionary_import_stage), (SELECT count(*) FROM public.organization_import_stage)"
-- 3. Run 019 again as a check (it must end with COMMIT).
-- Safe to run again: CREATE ... IF NOT EXISTS / OR REPLACE, GRANT and REVOKE; the record of rights is used only
-- while it exists. The last block checks every recreated part against its fingerprint from before 029.
BEGIN;
SET LOCAL lock_timeout = '10s';
-- The same search path as the fingerprints in 029 (postgres's): view definitions print names relative to it.
SET LOCAL search_path TO "$user", public, extensions;

DO $$
BEGIN
  IF NOT (SELECT rolsuper FROM pg_roles WHERE rolname = current_user) THEN
    RAISE EXCEPTION 'Run this file as supabase_admin (see its header), not as %.', current_user;
  END IF;
END $$;

-- 1. The default rights, as recorded (new objects in public go to anon and grafana_readonly again).
DO $$
DECLARE
  t record;
BEGIN
  IF to_regclass('public.cleanup_029_revoked_grants') IS NULL THEN
    RETURN;
  END IF;
  FOR t IN SELECT object_name, grantee, grantor, is_grantable, string_agg(privilege_type, ', ' ORDER BY privilege_type) AS privileges
           FROM public.cleanup_029_revoked_grants WHERE object_kind = 'DEFAULT' GROUP BY 1, 2, 3, 4 LOOP
    EXECUTE format('ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA public GRANT %s ON %s TO %I%s',
                   split_part(t.object_name, ':', 1), t.privileges,
                   CASE split_part(t.object_name, ':', 2) WHEN 'r' THEN 'TABLES' WHEN 'S' THEN 'SEQUENCES'
                        WHEN 'f' THEN 'FUNCTIONS' WHEN 'T' THEN 'TYPES' WHEN 'n' THEN 'SCHEMAS' END,
                   t.grantee, CASE WHEN t.is_grantable THEN ' WITH GRANT OPTION' ELSE '' END);
  END LOOP;
END $$;

-- 2. The dropped parts, as postgres (their owner). Each gets exactly its old rights: whatever the default rights
--    give on creation is taken back first.
SET LOCAL ROLE postgres;

CREATE TABLE IF NOT EXISTS public.missionary_import_stage (
  missionary text,
  missionary_number text,
  missionary_type text,
  assignment text,
  status text,
  zone text,
  district text,
  area text,
  phone text,
  mtc_date text,
  arrival_date text,
  release_date text,
  languages text,
  "position" text,
  position_abbr text,
  social_media_leader text,
  content_creator text
);

CREATE TABLE IF NOT EXISTS public.organization_import_stage (
  mission text,
  zone text,
  district text,
  area_code text,
  area text,
  stake text,
  unit text,
  unit_type text,
  assignment_type text,
  language text
);

CREATE OR REPLACE VIEW public.area_weekly_metrics_clean AS
 WITH finalized_reports AS (
         SELECT war.id AS weekly_area_report_id,
            war.area_id,
            war.reporting_week_id,
            war.unit_id,
            war.status,
            war.submitted_at,
            war.friends_found_actual,
            war.friends_found_goal,
            war.lessons_with_friends_actual,
            war.lessons_with_friends_goal,
            war.lessons_with_members_actual,
            war.lessons_with_members_goal,
            war.sacrament_attendance_actual,
            war.sacrament_attendance_goal,
            war.first_time_sacrament_actual,
            war.baptismal_dates_actual,
            war.baptismal_dates_goal,
            war.baptisms_confirmations_actual,
            war.baptisms_confirmations_goal,
            war.new_member_sacrament_actual,
            war.new_member_sacrament_goal,
            war.follow_up_lessons_actual,
            war.follow_up_lessons_goal
           FROM weekly_area_reports war
          WHERE (war.status = ANY (ARRAY['SUBMITTED'::text, 'LOCKED'::text]))
        ), area_week_rollup AS (
         SELECT fr.area_id,
            fr.reporting_week_id,
            count(*) AS report_count,
            (count(DISTINCT fr.unit_id) FILTER (WHERE (fr.unit_id IS NOT NULL)))::integer AS unit_count,
            array_agg(DISTINCT fr.unit_id ORDER BY fr.unit_id) FILTER (WHERE (fr.unit_id IS NOT NULL)) AS unit_ids,
            max(fr.submitted_at) AS latest_submitted_at,
            sum(fr.friends_found_actual) AS friends_found_actual,
            sum(fr.friends_found_goal) AS friends_found_goal,
            sum(fr.lessons_with_friends_actual) AS lessons_with_friends_actual,
            sum(fr.lessons_with_friends_goal) AS lessons_with_friends_goal,
            sum(fr.lessons_with_members_actual) AS lessons_with_members_actual,
            sum(fr.lessons_with_members_goal) AS lessons_with_members_goal,
            sum(fr.sacrament_attendance_actual) AS sacrament_attendance_actual,
            sum(fr.sacrament_attendance_goal) AS sacrament_attendance_goal,
            sum(fr.first_time_sacrament_actual) AS first_time_sacrament_actual,
            sum(fr.baptismal_dates_actual) AS baptismal_dates_actual,
            sum(fr.baptismal_dates_goal) AS baptismal_dates_goal,
            sum(fr.baptisms_confirmations_actual) AS baptisms_confirmations_actual,
            sum(fr.baptisms_confirmations_goal) AS baptisms_confirmations_goal,
            sum(fr.new_member_sacrament_actual) AS new_member_sacrament_actual,
            sum(fr.new_member_sacrament_goal) AS new_member_sacrament_goal,
            sum(fr.follow_up_lessons_actual) AS follow_up_lessons_actual,
            sum(fr.follow_up_lessons_goal) AS follow_up_lessons_goal
           FROM finalized_reports fr
          GROUP BY fr.area_id, fr.reporting_week_id
        ), unit_names AS (
         SELECT fr.area_id,
            fr.reporting_week_id,
            array_agg(DISTINCT u.name ORDER BY u.name) FILTER (WHERE (u.id IS NOT NULL)) AS unit_names
           FROM (finalized_reports fr
             LEFT JOIN units u ON ((u.id = fr.unit_id)))
          GROUP BY fr.area_id, fr.reporting_week_id
        )
 SELECT awr.reporting_week_id,
    rw.sunday AS reporting_sunday,
    m.id AS mission_id,
    m.name AS mission_name,
    z.id AS zone_id,
    z.name AS zone_name,
    d.id AS district_id,
    d.name AS district_name,
    a.id AS area_id,
    a.area_code,
    a.name AS area_name,
    a.assignment_type,
    a.language AS area_language,
    awr.report_count,
    awr.unit_count,
    awr.unit_ids,
    un.unit_names,
    awr.latest_submitted_at,
    awr.friends_found_actual,
    awr.friends_found_goal,
    awr.lessons_with_friends_actual,
    awr.lessons_with_friends_goal,
    awr.lessons_with_members_actual,
    awr.lessons_with_members_goal,
    awr.sacrament_attendance_actual,
    awr.sacrament_attendance_goal,
    awr.first_time_sacrament_actual,
    awr.baptismal_dates_actual,
    awr.baptismal_dates_goal,
    awr.baptisms_confirmations_actual,
    awr.baptisms_confirmations_goal,
    awr.new_member_sacrament_actual,
    awr.new_member_sacrament_goal,
    awr.follow_up_lessons_actual,
    awr.follow_up_lessons_goal
   FROM ((((((area_week_rollup awr
     JOIN reporting_weeks rw ON ((rw.id = awr.reporting_week_id)))
     JOIN areas a ON ((a.id = awr.area_id)))
     JOIN districts d ON ((d.id = a.district_id)))
     JOIN zones z ON ((z.id = d.zone_id)))
     JOIN missions m ON ((m.id = z.mission_id)))
     LEFT JOIN unit_names un ON (((un.area_id = awr.area_id) AND (un.reporting_week_id = awr.reporting_week_id))));

CREATE OR REPLACE VIEW public.district_weekly_metrics_clean AS
 SELECT awm.reporting_week_id,
    awm.reporting_sunday,
    awm.mission_id,
    awm.mission_name,
    awm.zone_id,
    awm.zone_name,
    awm.district_id,
    awm.district_name,
    (count(DISTINCT awm.area_id))::integer AS area_count,
    (sum(awm.friends_found_actual))::bigint AS friends_found_actual,
    (sum(awm.friends_found_goal))::bigint AS friends_found_goal,
    (sum(awm.lessons_with_friends_actual))::bigint AS lessons_with_friends_actual,
    (sum(awm.lessons_with_friends_goal))::bigint AS lessons_with_friends_goal,
    (sum(awm.lessons_with_members_actual))::bigint AS lessons_with_members_actual,
    (sum(awm.lessons_with_members_goal))::bigint AS lessons_with_members_goal,
    (sum(awm.sacrament_attendance_actual))::bigint AS sacrament_attendance_actual,
    (sum(awm.sacrament_attendance_goal))::bigint AS sacrament_attendance_goal,
    (sum(awm.first_time_sacrament_actual))::bigint AS first_time_sacrament_actual,
    (sum(awm.baptismal_dates_actual))::bigint AS baptismal_dates_actual,
    (sum(awm.baptismal_dates_goal))::bigint AS baptismal_dates_goal,
    (sum(awm.baptisms_confirmations_actual))::bigint AS baptisms_confirmations_actual,
    (sum(awm.baptisms_confirmations_goal))::bigint AS baptisms_confirmations_goal,
    (sum(awm.new_member_sacrament_actual))::bigint AS new_member_sacrament_actual,
    (sum(awm.new_member_sacrament_goal))::bigint AS new_member_sacrament_goal,
    (sum(awm.follow_up_lessons_actual))::bigint AS follow_up_lessons_actual,
    (sum(awm.follow_up_lessons_goal))::bigint AS follow_up_lessons_goal
   FROM area_weekly_metrics_clean awm
  GROUP BY awm.reporting_week_id, awm.reporting_sunday, awm.mission_id, awm.mission_name, awm.zone_id, awm.zone_name, awm.district_id, awm.district_name;

CREATE OR REPLACE VIEW public.zone_weekly_metrics_clean AS
 SELECT awm.reporting_week_id,
    awm.reporting_sunday,
    awm.mission_id,
    awm.mission_name,
    awm.zone_id,
    awm.zone_name,
    (count(DISTINCT awm.district_id))::integer AS district_count,
    (count(DISTINCT awm.area_id))::integer AS area_count,
    (sum(awm.friends_found_actual))::bigint AS friends_found_actual,
    (sum(awm.friends_found_goal))::bigint AS friends_found_goal,
    (sum(awm.lessons_with_friends_actual))::bigint AS lessons_with_friends_actual,
    (sum(awm.lessons_with_friends_goal))::bigint AS lessons_with_friends_goal,
    (sum(awm.lessons_with_members_actual))::bigint AS lessons_with_members_actual,
    (sum(awm.lessons_with_members_goal))::bigint AS lessons_with_members_goal,
    (sum(awm.sacrament_attendance_actual))::bigint AS sacrament_attendance_actual,
    (sum(awm.sacrament_attendance_goal))::bigint AS sacrament_attendance_goal,
    (sum(awm.first_time_sacrament_actual))::bigint AS first_time_sacrament_actual,
    (sum(awm.baptismal_dates_actual))::bigint AS baptismal_dates_actual,
    (sum(awm.baptismal_dates_goal))::bigint AS baptismal_dates_goal,
    (sum(awm.baptisms_confirmations_actual))::bigint AS baptisms_confirmations_actual,
    (sum(awm.baptisms_confirmations_goal))::bigint AS baptisms_confirmations_goal,
    (sum(awm.new_member_sacrament_actual))::bigint AS new_member_sacrament_actual,
    (sum(awm.new_member_sacrament_goal))::bigint AS new_member_sacrament_goal,
    (sum(awm.follow_up_lessons_actual))::bigint AS follow_up_lessons_actual,
    (sum(awm.follow_up_lessons_goal))::bigint AS follow_up_lessons_goal
   FROM area_weekly_metrics_clean awm
  GROUP BY awm.reporting_week_id, awm.reporting_sunday, awm.mission_id, awm.mission_name, awm.zone_id, awm.zone_name;

CREATE OR REPLACE VIEW public.mission_weekly_metrics_clean AS
 SELECT awm.reporting_week_id,
    awm.reporting_sunday,
    awm.mission_id,
    awm.mission_name,
    (count(DISTINCT awm.zone_id))::integer AS zone_count,
    (count(DISTINCT awm.district_id))::integer AS district_count,
    (count(DISTINCT awm.area_id))::integer AS area_count,
    (sum(awm.friends_found_actual))::bigint AS friends_found_actual,
    (sum(awm.friends_found_goal))::bigint AS friends_found_goal,
    (sum(awm.lessons_with_friends_actual))::bigint AS lessons_with_friends_actual,
    (sum(awm.lessons_with_friends_goal))::bigint AS lessons_with_friends_goal,
    (sum(awm.lessons_with_members_actual))::bigint AS lessons_with_members_actual,
    (sum(awm.lessons_with_members_goal))::bigint AS lessons_with_members_goal,
    (sum(awm.sacrament_attendance_actual))::bigint AS sacrament_attendance_actual,
    (sum(awm.sacrament_attendance_goal))::bigint AS sacrament_attendance_goal,
    (sum(awm.first_time_sacrament_actual))::bigint AS first_time_sacrament_actual,
    (sum(awm.baptismal_dates_actual))::bigint AS baptismal_dates_actual,
    (sum(awm.baptismal_dates_goal))::bigint AS baptismal_dates_goal,
    (sum(awm.baptisms_confirmations_actual))::bigint AS baptisms_confirmations_actual,
    (sum(awm.baptisms_confirmations_goal))::bigint AS baptisms_confirmations_goal,
    (sum(awm.new_member_sacrament_actual))::bigint AS new_member_sacrament_actual,
    (sum(awm.new_member_sacrament_goal))::bigint AS new_member_sacrament_goal,
    (sum(awm.follow_up_lessons_actual))::bigint AS follow_up_lessons_actual,
    (sum(awm.follow_up_lessons_goal))::bigint AS follow_up_lessons_goal
   FROM area_weekly_metrics_clean awm
  GROUP BY awm.reporting_week_id, awm.reporting_sunday, awm.mission_id, awm.mission_name;

CREATE OR REPLACE VIEW public.district_reporting_status WITH (security_invoker=true) AS
 SELECT area_reporting_status.reporting_week_id,
    area_reporting_status.sunday,
    area_reporting_status.district_id,
    area_reporting_status.district_name,
    area_reporting_status.zone_id,
    area_reporting_status.zone_name,
    area_reporting_status.mission_id,
    area_reporting_status.mission_name,
    count(*) AS total_areas,
    count(*) FILTER (WHERE (area_reporting_status.submitted = true)) AS submitted_areas,
    count(*) FILTER (WHERE (area_reporting_status.submitted = false)) AS missing_areas,
    round(((100.0 * (count(*) FILTER (WHERE (area_reporting_status.submitted = true)))::numeric) / (NULLIF(count(*), 0))::numeric), 1) AS completion_percent
   FROM area_reporting_status
  GROUP BY area_reporting_status.reporting_week_id, area_reporting_status.sunday, area_reporting_status.district_id, area_reporting_status.district_name, area_reporting_status.zone_id, area_reporting_status.zone_name, area_reporting_status.mission_id, area_reporting_status.mission_name;

CREATE OR REPLACE VIEW public.zone_reporting_status WITH (security_invoker=true) AS
 SELECT area_reporting_status.reporting_week_id,
    area_reporting_status.sunday,
    area_reporting_status.zone_id,
    area_reporting_status.zone_name,
    area_reporting_status.mission_id,
    area_reporting_status.mission_name,
    count(*) AS total_areas,
    count(*) FILTER (WHERE (area_reporting_status.submitted = true)) AS submitted_areas,
    count(*) FILTER (WHERE (area_reporting_status.submitted = false)) AS missing_areas,
    round(((100.0 * (count(*) FILTER (WHERE (area_reporting_status.submitted = true)))::numeric) / (NULLIF(count(*), 0))::numeric), 1) AS completion_percent
   FROM area_reporting_status
  GROUP BY area_reporting_status.reporting_week_id, area_reporting_status.sunday, area_reporting_status.zone_id, area_reporting_status.zone_name, area_reporting_status.mission_id, area_reporting_status.mission_name;

CREATE OR REPLACE VIEW public.mission_reporting_status WITH (security_invoker=true) AS
 SELECT area_reporting_status.reporting_week_id,
    area_reporting_status.sunday,
    area_reporting_status.mission_id,
    area_reporting_status.mission_name,
    count(*) AS total_areas,
    count(*) FILTER (WHERE (area_reporting_status.submitted = true)) AS submitted_areas,
    count(*) FILTER (WHERE (area_reporting_status.submitted = false)) AS missing_areas,
    round(((100.0 * (count(*) FILTER (WHERE (area_reporting_status.submitted = true)))::numeric) / (NULLIF(count(*), 0))::numeric), 1) AS completion_percent
   FROM area_reporting_status
  GROUP BY area_reporting_status.reporting_week_id, area_reporting_status.sunday, area_reporting_status.mission_id, area_reporting_status.mission_name;

CREATE OR REPLACE VIEW public.area_history WITH (security_invoker=true) AS
 SELECT a.id AS area_id,
    a.name AS area_name,
    d.id AS district_id,
    d.name AS district_name,
    z.id AS zone_id,
    z.name AS zone_name,
    m.id AS mission_id,
    m.name AS mission_name,
    rw.id AS reporting_week_id,
    rw.sunday,
    war.status,
    war.submitted_at,
    war.friends_found_actual,
    war.friends_found_goal,
    war.lessons_with_friends_actual,
    war.lessons_with_friends_goal,
    war.lessons_with_members_actual,
    war.lessons_with_members_goal,
    war.sacrament_attendance_actual,
    war.sacrament_attendance_goal,
    war.first_time_sacrament_actual,
    war.baptismal_dates_actual,
    war.baptismal_dates_goal,
    war.new_member_sacrament_actual,
    war.new_member_sacrament_goal,
    war.follow_up_lessons_actual,
    war.follow_up_lessons_goal
   FROM (((((weekly_area_reports war
     JOIN areas a ON ((a.id = war.area_id)))
     JOIN districts d ON ((d.id = a.district_id)))
     JOIN zones z ON ((z.id = d.zone_id)))
     JOIN missions m ON ((m.id = z.mission_id)))
     JOIN reporting_weeks rw ON ((rw.id = war.reporting_week_id)))
  WHERE (war.status = ANY (ARRAY['SUBMITTED'::text, 'LOCKED'::text]));

CREATE OR REPLACE VIEW public.current_assignment_details WITH (security_invoker=true) AS
 SELECT m.id AS missionary_id,
    m.missionary_number,
    m.display_name,
    m.missionary_type,
    m.status AS missionary_status,
    mi.id AS mission_id,
    mi.name AS mission,
    z.id AS zone_id,
    z.name AS zone,
    d.id AS district_id,
    d.name AS district,
    a.id AS area_id,
    a.area_code,
    a.name AS area,
    a.assignment_type AS area_assignment_type,
    a.assignment_type_notes,
    ma.id AS missionary_assignment_id,
    ma.start_date AS assignment_start_date,
    ma.end_date AS assignment_end_date,
    ma.roster_position,
    ma.roster_position_abbr,
    ma.special_assignment,
    ma.special_assignment_notes,
    la.role AS leadership_role
   FROM ((((((missionaries m
     JOIN missionary_assignments ma ON (((ma.missionary_id = m.id) AND (ma.start_date <= CURRENT_DATE) AND ((ma.end_date IS NULL) OR (ma.end_date >= CURRENT_DATE)))))
     JOIN areas a ON ((a.id = ma.area_id)))
     JOIN districts d ON ((d.id = a.district_id)))
     JOIN zones z ON ((z.id = d.zone_id)))
     JOIN missions mi ON ((mi.id = z.mission_id)))
     LEFT JOIN leadership_assignments la ON (((la.missionary_id = m.id) AND (la.start_date <= CURRENT_DATE) AND ((la.end_date IS NULL) OR (la.end_date >= CURRENT_DATE)))));

CREATE OR REPLACE VIEW public.new_members_clean AS
 SELECT rw.id AS reporting_week_id,
    rw.sunday AS reporting_sunday,
    m.id AS mission_id,
    m.name AS mission_name,
    z.id AS zone_id,
    z.name AS zone_name,
    d.id AS district_id,
    d.name AS district_name,
    a.id AS area_id,
    a.area_code,
    a.name AS area_name,
    u.id AS unit_id,
    u.name AS unit_name,
    u.unit_type,
    s.id AS stake_id,
    s.name AS stake_name,
    war.id AS weekly_area_report_id,
    wnm.id AS weekly_new_member_id,
    wnm.new_member_id,
    wnm.display_order,
    nm.display_name AS person_name,
    nm.first_name,
    nm.last_name,
    nm.baptism_date,
    nm.confirmation_date,
    nm.finding_source,
    wnm.lessons_actual,
    wnm.lessons_goal,
    wnm.pmg_lessons_percentage,
    wnm.how_are_they_doing,
    wnm.discussed_in_gemiko,
    wnm.gemiko_support_plan,
    wnm.next_ordinance,
    wnm.at_church_this_sunday,
    wnm.has_calling,
    wnm.has_aaronic_priesthood,
    wnm.has_melchizedek_priesthood,
    wnm.ministers_to_someone,
    wnm.ministered_to_by_someone,
    wnm.has_active_temple_recommend,
    wnm.visited_temple_for_baptisms,
    wnm.reading,
    wnm.praying,
    wnm.member_involvement
   FROM (((((((((weekly_new_members wnm
     JOIN weekly_area_reports war ON ((war.id = wnm.weekly_area_report_id)))
     JOIN reporting_weeks rw ON ((rw.id = war.reporting_week_id)))
     JOIN areas a ON ((a.id = war.area_id)))
     JOIN districts d ON ((d.id = a.district_id)))
     JOIN zones z ON ((z.id = d.zone_id)))
     JOIN missions m ON ((m.id = z.mission_id)))
     LEFT JOIN units u ON ((u.id = war.unit_id)))
     JOIN new_members nm ON ((nm.id = wnm.new_member_id)))
     LEFT JOIN stakes s ON ((s.id = COALESCE(nm.stake_id, u.stake_id))))
  WHERE ((war.status = ANY (ARRAY['SUBMITTED'::text, 'LOCKED'::text])) AND (wnm.new_member_id IS NOT NULL));

CREATE OR REPLACE VIEW public.baptismal_dates_clean AS
 SELECT rw.id AS reporting_week_id,
    rw.sunday AS reporting_sunday,
    m.id AS mission_id,
    m.name AS mission_name,
    z.id AS zone_id,
    z.name AS zone_name,
    d.id AS district_id,
    d.name AS district_name,
    a.id AS area_id,
    a.area_code,
    a.name AS area_name,
    u.id AS unit_id,
    u.name AS unit_name,
    u.unit_type,
    s.id AS stake_id,
    s.name AS stake_name,
    war.id AS weekly_area_report_id,
    wbdf.id AS weekly_baptismal_date_friend_id,
    wbdf.baptismal_date_person_id,
    bdp.display_name AS person_name,
    bdp.first_name,
    bdp.last_name,
    COALESCE(wbdf.finding_source, bdp.finding_source) AS finding_source,
    wbdf.display_order,
    wbdf.baptismal_date_set_on,
    wbdf.current_baptismal_date,
        CASE
            WHEN (wbdf.current_baptismal_date IS NULL) THEN NULL::integer
            ELSE (wbdf.current_baptismal_date - rw.sunday)
        END AS days_until_baptism,
        CASE
            WHEN (wbdf.current_baptismal_date IS NULL) THEN NULL::numeric
            ELSE round((((wbdf.current_baptismal_date - rw.sunday))::numeric / 7.0), 1)
        END AS weeks_until_baptism,
    wbdf.reading,
    wbdf.praying,
    wbdf.at_church_this_sunday,
    wbdf.keeping_commandments,
    wbdf.member_involvement
   FROM (((((((((weekly_baptismal_date_friends wbdf
     JOIN weekly_area_reports war ON ((war.id = wbdf.weekly_area_report_id)))
     JOIN reporting_weeks rw ON ((rw.id = war.reporting_week_id)))
     JOIN areas a ON ((a.id = war.area_id)))
     JOIN districts d ON ((d.id = a.district_id)))
     JOIN zones z ON ((z.id = d.zone_id)))
     JOIN missions m ON ((m.id = z.mission_id)))
     LEFT JOIN units u ON ((u.id = war.unit_id)))
     LEFT JOIN stakes s ON ((s.id = COALESCE(wbdf.stake_id, u.stake_id))))
     JOIN baptismal_date_people bdp ON ((bdp.id = wbdf.baptismal_date_person_id)))
  WHERE ((war.status = ANY (ARRAY['SUBMITTED'::text, 'LOCKED'::text])) AND (wbdf.baptismal_date_person_id IS NOT NULL));

CREATE OR REPLACE VIEW public.high_potentials_clean AS
 SELECT rw.id AS reporting_week_id,
    rw.sunday AS reporting_sunday,
    m.id AS mission_id,
    m.name AS mission_name,
    z.id AS zone_id,
    z.name AS zone_name,
    d.id AS district_id,
    d.name AS district_name,
    a.id AS area_id,
    a.area_code,
    a.name AS area_name,
    u.id AS unit_id,
    u.name AS unit_name,
    u.unit_type,
    s.id AS stake_id,
    s.name AS stake_name,
    war.id AS weekly_area_report_id,
    whpf.id AS weekly_high_potential_id,
    whpf.display_order,
    whpf.name AS person_name,
    whpf.at_church_this_sunday,
    whpf.notes
   FROM ((((((((weekly_high_potential_friends whpf
     JOIN weekly_area_reports war ON ((war.id = whpf.weekly_area_report_id)))
     JOIN reporting_weeks rw ON ((rw.id = war.reporting_week_id)))
     JOIN areas a ON ((a.id = war.area_id)))
     JOIN districts d ON ((d.id = a.district_id)))
     JOIN zones z ON ((z.id = d.zone_id)))
     JOIN missions m ON ((m.id = z.mission_id)))
     LEFT JOIN units u ON ((u.id = war.unit_id)))
     LEFT JOIN stakes s ON ((s.id = u.stake_id)))
  WHERE (war.status = ANY (ARRAY['SUBMITTED'::text, 'LOCKED'::text]));

CREATE OR REPLACE FUNCTION public.clear_missionary_special_assignment(target_missionary_number text)
 RETURNS void
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public'
AS $function$

declare

    target_assignment_id bigint;

begin


    if not public.is_assignment_admin() then

        raise exception
        'You do not have permission to clear special assignments.';

    end if;


    select ma.id

    into target_assignment_id

    from public.missionaries m

    join public.missionary_assignments ma

        on ma.missionary_id = m.id

       and ma.start_date <= current_date

       and (
            ma.end_date is null
            or ma.end_date >= current_date
       )

    where m.missionary_number =
          trim(target_missionary_number)

    order by ma.start_date desc

    limit 1;


    if target_assignment_id is null then

        raise exception
        'No current assignment found for missionary "%".',
        target_missionary_number;

    end if;


    update public.missionary_assignments

    set
        special_assignment = null,
        special_assignment_notes = null

    where id =
          target_assignment_id;


end;

$function$;

CREATE OR REPLACE FUNCTION public.link_user_to_missionary(target_user_id uuid, target_missionary_number text)
 RETURNS void
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public'
AS $function$

declare

    target_missionary_id bigint;

begin


    if not public.is_assignment_admin() then

        raise exception
        'You do not have permission to link user accounts.';

    end if;


    if not exists (

        select 1

        from auth.users

        where id = target_user_id

    ) then

        raise exception
        'Supabase user "%" does not exist.',
        target_user_id;

    end if;


    select id

    into target_missionary_id

    from public.missionaries

    where missionary_number =
          trim(target_missionary_number);


    if target_missionary_id is null then

        raise exception
        'Missionary number "%" was not found.',
        target_missionary_number;

    end if;


    insert into public.user_profiles (

        id,

        missionary_id,

        app_role,

        active

    )

    values (

        target_user_id,

        target_missionary_id,

        'MISSIONARY',

        true

    )


    on conflict (id)

    do update set

        missionary_id =
            excluded.missionary_id,

        active =
            true,

        updated_at =
            now();


    perform public.sync_user_profile_roles();


end;

$function$;

CREATE OR REPLACE FUNCTION public.save_current_planning_answer(target_unit_id bigint, question_key text, answer_text text DEFAULT NULL::text, answer_number numeric DEFAULT NULL::numeric, answer_boolean boolean DEFAULT NULL::boolean)
 RETURNS void
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public'
AS $function$
declare
    v_report_id bigint;
    v_status text;
begin
    if question_key is null or btrim(question_key) = '' then
        raise exception 'question_key is required.';
    end if;

    v_report_id := public.start_current_weekly_report(target_unit_id);

    select status
    into v_status
    from public.weekly_area_reports
    where id = v_report_id;

    if v_status <> 'DRAFT' then
        raise exception
            'This weekly report is %, not DRAFT, and cannot be edited.',
            v_status;
    end if;

    insert into public.weekly_planning_answers (
        weekly_area_report_id,
        question_key,
        answer_text,
        answer_number,
        answer_boolean
    )
    values (
        v_report_id,
        question_key,
        answer_text,
        answer_number,
        answer_boolean
    )
    on conflict (weekly_area_report_id, question_key)
    do update set
        answer_text = excluded.answer_text,
        answer_number = excluded.answer_number,
        answer_boolean = excluded.answer_boolean;
end;
$function$;

CREATE OR REPLACE FUNCTION public.save_current_planning_answer(target_question_key text, new_answer_text text DEFAULT NULL::text, new_answer_number numeric DEFAULT NULL::numeric, new_answer_boolean boolean DEFAULT NULL::boolean)
 RETURNS void
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public'
AS $function$

declare

    report_id bigint;

    report_status text;

begin


    if nullif(
        trim(target_question_key),
        ''
    ) is null then

        raise exception
        'question_key cannot be blank.';

    end if;


    report_id :=
        public.start_current_weekly_report();


    select status

    into report_status

    from public.weekly_area_reports

    where id = report_id;


    if report_status <> 'DRAFT' then

        raise exception
        'This weekly report is %, not DRAFT, and cannot be edited.',
        report_status;

    end if;


    insert into public.weekly_planning_answers (

        weekly_area_report_id,

        question_key,

        answer_text,

        answer_number,

        answer_boolean

    )

    values (

        report_id,

        trim(target_question_key),

        new_answer_text,

        new_answer_number,

        new_answer_boolean

    )


    on conflict (
        weekly_area_report_id,
        question_key
    )

    do update set

        answer_text =
            excluded.answer_text,

        answer_number =
            excluded.answer_number,

        answer_boolean =
            excluded.answer_boolean;

end;

$function$;

CREATE OR REPLACE FUNCTION public.set_area_assignment_type(target_area_code text, new_assignment_type text, new_notes text DEFAULT NULL::text)
 RETURNS void
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public'
AS $function$

begin


    if not public.is_assignment_admin() then

        raise exception
        'You do not have permission to change area assignment types.';

    end if;


    if new_assignment_type not in (
        'Standard',
        'Military',
        'Special'
    ) then

        raise exception
        'Invalid area assignment type: %. Expected Standard, Military, or Special.',
        new_assignment_type;

    end if;


    update public.areas

    set
        assignment_type =
            new_assignment_type,

        assignment_type_notes =
            nullif(trim(new_notes), '')

    where area_code =
          trim(target_area_code);


    if not found then

        raise exception
        'Area code "%" was not found.',
        target_area_code;

    end if;


end;

$function$;

CREATE OR REPLACE FUNCTION public.set_missionary_special_assignment(target_missionary_number text, new_special_assignment text, new_notes text DEFAULT NULL::text)
 RETURNS void
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public'
AS $function$

declare

    target_assignment_id bigint;

begin


    if not public.is_assignment_admin() then

        raise exception
        'You do not have permission to change special assignments.';

    end if;


    select ma.id

    into target_assignment_id

    from public.missionaries m

    join public.missionary_assignments ma

        on ma.missionary_id = m.id

       and ma.start_date <= current_date

       and (
            ma.end_date is null
            or ma.end_date >= current_date
       )

    where m.missionary_number =
          trim(target_missionary_number)

    order by ma.start_date desc

    limit 1;


    if target_assignment_id is null then

        raise exception
        'No current assignment found for missionary "%".',
        target_missionary_number;

    end if;


    update public.missionary_assignments

    set
        special_assignment =
            nullif(trim(new_special_assignment), ''),

        special_assignment_notes =
            nullif(trim(new_notes), '')

    where id =
          target_assignment_id;


end;

$function$;

CREATE OR REPLACE FUNCTION public.submit_current_weekly_report()
 RETURNS bigint
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public'
AS $function$

declare

    report_id bigint;

    current_status text;

begin


    report_id :=
        public.start_current_weekly_report();


    select status

    into current_status

    from public.weekly_area_reports

    where id = report_id;


    if current_status = 'LOCKED' then

        raise exception
        'This report is locked.';

    end if;


    if current_status = 'SUBMITTED' then

        return report_id;

    end if;


    update public.weekly_area_reports

    set

        status =
            'SUBMITTED',

        submitted_by =
            auth.uid(),

        submitted_at =
            now(),

        updated_at =
            now()

    where id =
          report_id;


    return report_id;

end;

$function$;

CREATE OR REPLACE FUNCTION public.unlink_user_from_missionary(target_user_id uuid)
 RETURNS void
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public'
AS $function$

begin


    if not public.is_assignment_admin() then

        raise exception
        'You do not have permission to unlink user accounts.';

    end if;


    update public.user_profiles

    set
        missionary_id = null,
        active = false,
        updated_at = now()

    where id = target_user_id;


end;

$function$;

CREATE OR REPLACE FUNCTION public.update_current_weekly_report(new_friends_found_actual integer DEFAULT NULL::integer, new_friends_found_goal integer DEFAULT NULL::integer, new_lessons_with_friends_actual integer DEFAULT NULL::integer, new_lessons_with_friends_goal integer DEFAULT NULL::integer, new_lessons_with_members_actual integer DEFAULT NULL::integer, new_lessons_with_members_goal integer DEFAULT NULL::integer, new_sacrament_attendance_actual integer DEFAULT NULL::integer, new_sacrament_attendance_goal integer DEFAULT NULL::integer, new_first_time_sacrament_actual integer DEFAULT NULL::integer, new_baptismal_dates_actual integer DEFAULT NULL::integer, new_baptismal_dates_goal integer DEFAULT NULL::integer, new_baptisms_confirmations_actual integer DEFAULT NULL::integer, new_baptisms_confirmations_goal integer DEFAULT NULL::integer, new_new_member_sacrament_actual integer DEFAULT NULL::integer, new_new_member_sacrament_goal integer DEFAULT NULL::integer, new_follow_up_lessons_actual integer DEFAULT NULL::integer, new_follow_up_lessons_goal integer DEFAULT NULL::integer, new_notes text DEFAULT NULL::text)
 RETURNS bigint
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public'
AS $function$
DECLARE
    report_id bigint;
    report_status text;
BEGIN
    report_id :=
        public.start_current_weekly_report();

    SELECT status
    INTO report_status
    FROM public.weekly_area_reports
    WHERE id = report_id;

    IF report_status <> 'DRAFT' THEN
        RAISE EXCEPTION
            'This weekly report is %, not DRAFT, and cannot be edited.',
            report_status;
    END IF;

    -- Reject negative KPI values.
    IF COALESCE(new_friends_found_actual, 0) < 0
       OR COALESCE(new_friends_found_goal, 0) < 0
       OR COALESCE(new_lessons_with_friends_actual, 0) < 0
       OR COALESCE(new_lessons_with_friends_goal, 0) < 0
       OR COALESCE(new_lessons_with_members_actual, 0) < 0
       OR COALESCE(new_lessons_with_members_goal, 0) < 0
       OR COALESCE(new_sacrament_attendance_actual, 0) < 0
       OR COALESCE(new_sacrament_attendance_goal, 0) < 0
       OR COALESCE(new_first_time_sacrament_actual, 0) < 0
       OR COALESCE(new_baptismal_dates_actual, 0) < 0
       OR COALESCE(new_baptismal_dates_goal, 0) < 0
       OR COALESCE(new_baptisms_confirmations_actual, 0) < 0
       OR COALESCE(new_baptisms_confirmations_goal, 0) < 0
       OR COALESCE(new_new_member_sacrament_actual, 0) < 0
       OR COALESCE(new_new_member_sacrament_goal, 0) < 0
       OR COALESCE(new_follow_up_lessons_actual, 0) < 0
       OR COALESCE(new_follow_up_lessons_goal, 0) < 0
    THEN
        RAISE EXCEPTION
            'Weekly KPI values cannot be negative.';
    END IF;

    UPDATE public.weekly_area_reports
    SET
        friends_found_actual =
            COALESCE(new_friends_found_actual, friends_found_actual),

        friends_found_goal =
            COALESCE(new_friends_found_goal, friends_found_goal),

        lessons_with_friends_actual =
            COALESCE(new_lessons_with_friends_actual, lessons_with_friends_actual),

        lessons_with_friends_goal =
            COALESCE(new_lessons_with_friends_goal, lessons_with_friends_goal),

        lessons_with_members_actual =
            COALESCE(new_lessons_with_members_actual, lessons_with_members_actual),

        lessons_with_members_goal =
            COALESCE(new_lessons_with_members_goal, lessons_with_members_goal),

        sacrament_attendance_actual =
            COALESCE(new_sacrament_attendance_actual, sacrament_attendance_actual),

        sacrament_attendance_goal =
            COALESCE(new_sacrament_attendance_goal, sacrament_attendance_goal),

        first_time_sacrament_actual =
            COALESCE(new_first_time_sacrament_actual, first_time_sacrament_actual),

        baptismal_dates_actual =
            COALESCE(new_baptismal_dates_actual, baptismal_dates_actual),

        baptismal_dates_goal =
            COALESCE(new_baptismal_dates_goal, baptismal_dates_goal),

        baptisms_confirmations_actual =
            COALESCE(
                new_baptisms_confirmations_actual,
                baptisms_confirmations_actual
            ),

        baptisms_confirmations_goal =
            COALESCE(
                new_baptisms_confirmations_goal,
                baptisms_confirmations_goal
            ),

        new_member_sacrament_actual =
            COALESCE(
                new_new_member_sacrament_actual,
                new_member_sacrament_actual
            ),

        new_member_sacrament_goal =
            COALESCE(
                new_new_member_sacrament_goal,
                new_member_sacrament_goal
            ),

        follow_up_lessons_actual =
            COALESCE(new_follow_up_lessons_actual, follow_up_lessons_actual),

        follow_up_lessons_goal =
            COALESCE(new_follow_up_lessons_goal, follow_up_lessons_goal),

        notes =
            COALESCE(new_notes, notes),

        updated_at = NOW()

    WHERE id = report_id;

    RETURN report_id;
END;
$function$;

-- Rights and comments of the recreated parts (from live Beta, 27 Sep 2026, after the 22:50 hotfix).
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'grafana_readonly') THEN
    EXECUTE 'REVOKE ALL ON public.missionary_import_stage, public.organization_import_stage, public.area_weekly_metrics_clean, public.district_weekly_metrics_clean, public.zone_weekly_metrics_clean, public.mission_weekly_metrics_clean, public.district_reporting_status, public.zone_reporting_status, public.mission_reporting_status, public.area_history, public.current_assignment_details, public.new_members_clean, public.baptismal_dates_clean, public.high_potentials_clean FROM grafana_readonly';
  END IF;
END $$;
REVOKE ALL ON public.missionary_import_stage, public.organization_import_stage, public.area_weekly_metrics_clean, public.district_weekly_metrics_clean, public.zone_weekly_metrics_clean, public.mission_weekly_metrics_clean, public.district_reporting_status, public.zone_reporting_status, public.mission_reporting_status, public.area_history, public.current_assignment_details, public.new_members_clean, public.baptismal_dates_clean, public.high_potentials_clean FROM PUBLIC, anon, authenticated, service_role;
GRANT INSERT, SELECT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER ON TABLE public.missionary_import_stage TO service_role;
GRANT INSERT, SELECT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER ON TABLE public.organization_import_stage TO service_role;
GRANT INSERT, SELECT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER ON TABLE public.area_weekly_metrics_clean TO service_role;
COMMENT ON VIEW public.area_weekly_metrics_clean IS 'Dashboard-friendly area weekly metrics. Grain: one row per area + reporting week. Numeric metrics sum finalized (SUBMITTED/LOCKED) unit-specific weekly reports. Unit identities are retained as arrays. Metric values are historical snapshots, but organization hierarchy/names reflect the current organization tables at query time.';
GRANT INSERT, SELECT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER ON TABLE public.district_weekly_metrics_clean TO service_role;
COMMENT ON VIEW public.district_weekly_metrics_clean IS 'Dashboard-friendly district weekly metrics. Grain: one row per district + reporting week. Derived exclusively from area_weekly_metrics_clean by summing area-level metrics.';
GRANT INSERT, SELECT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER ON TABLE public.zone_weekly_metrics_clean TO service_role;
COMMENT ON VIEW public.zone_weekly_metrics_clean IS 'Dashboard-friendly zone weekly metrics. Grain: one row per zone + reporting week. Derived exclusively from area_weekly_metrics_clean by summing area-level metrics.';
GRANT INSERT, SELECT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER ON TABLE public.mission_weekly_metrics_clean TO service_role;
COMMENT ON VIEW public.mission_weekly_metrics_clean IS 'Dashboard-friendly mission weekly metrics. Grain: one row per mission + reporting week. Derived exclusively from area_weekly_metrics_clean by summing area-level metrics.';
GRANT INSERT, SELECT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER ON TABLE public.district_reporting_status TO anon;
GRANT INSERT, SELECT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER ON TABLE public.district_reporting_status TO authenticated;
GRANT SELECT ON TABLE public.district_reporting_status TO grafana_readonly;
GRANT INSERT, SELECT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER ON TABLE public.district_reporting_status TO service_role;
GRANT INSERT, SELECT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER ON TABLE public.zone_reporting_status TO anon;
GRANT INSERT, SELECT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER ON TABLE public.zone_reporting_status TO authenticated;
GRANT SELECT ON TABLE public.zone_reporting_status TO grafana_readonly;
GRANT INSERT, SELECT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER ON TABLE public.zone_reporting_status TO service_role;
GRANT INSERT, SELECT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER ON TABLE public.mission_reporting_status TO anon;
GRANT INSERT, SELECT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER ON TABLE public.mission_reporting_status TO authenticated;
GRANT SELECT ON TABLE public.mission_reporting_status TO grafana_readonly;
GRANT INSERT, SELECT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER ON TABLE public.mission_reporting_status TO service_role;
GRANT INSERT, SELECT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER ON TABLE public.area_history TO anon;
GRANT INSERT, SELECT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER ON TABLE public.area_history TO authenticated;
GRANT SELECT ON TABLE public.area_history TO grafana_readonly;
GRANT INSERT, SELECT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER ON TABLE public.area_history TO service_role;
GRANT INSERT, SELECT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER ON TABLE public.current_assignment_details TO anon;
GRANT INSERT, SELECT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER ON TABLE public.current_assignment_details TO authenticated;
GRANT SELECT ON TABLE public.current_assignment_details TO grafana_readonly;
GRANT INSERT, SELECT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER ON TABLE public.current_assignment_details TO service_role;
GRANT INSERT, SELECT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER ON TABLE public.new_members_clean TO service_role;
COMMENT ON VIEW public.new_members_clean IS 'Dashboard-friendly new-member weekly follow-up snapshots. Grain: one new member + reporting week + unit report. Person rows remain individual; no cross-unit summing. Finalized weekly reports only.';
GRANT INSERT, SELECT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER ON TABLE public.baptismal_dates_clean TO service_role;
COMMENT ON VIEW public.baptismal_dates_clean IS 'Dashboard-friendly baptismal-date weekly snapshots. Grain: one baptismal-date person + reporting week + unit report. Person rows remain individual; no cross-unit summing. Finalized weekly reports only.';
GRANT INSERT, SELECT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER ON TABLE public.high_potentials_clean TO service_role;
COMMENT ON VIEW public.high_potentials_clean IS 'Dashboard-friendly weekly high-potential snapshots. Grain: one weekly high-potential entry + reporting week + unit report. High potentials currently have weekly identity only, not a permanent person identity. Finalized weekly reports only.';
REVOKE ALL ON FUNCTION public.clear_missionary_special_assignment(text) FROM PUBLIC, anon, authenticated, service_role;
GRANT EXECUTE ON FUNCTION public.clear_missionary_special_assignment(text) TO anon;
GRANT EXECUTE ON FUNCTION public.clear_missionary_special_assignment(text) TO authenticated;
GRANT EXECUTE ON FUNCTION public.clear_missionary_special_assignment(text) TO service_role;
REVOKE ALL ON FUNCTION public.link_user_to_missionary(uuid,text) FROM PUBLIC, anon, authenticated, service_role;
GRANT EXECUTE ON FUNCTION public.link_user_to_missionary(uuid,text) TO anon;
GRANT EXECUTE ON FUNCTION public.link_user_to_missionary(uuid,text) TO authenticated;
GRANT EXECUTE ON FUNCTION public.link_user_to_missionary(uuid,text) TO service_role;
REVOKE ALL ON FUNCTION public.save_current_planning_answer(bigint,text,text,numeric,boolean) FROM PUBLIC, anon, authenticated, service_role;
GRANT EXECUTE ON FUNCTION public.save_current_planning_answer(bigint,text,text,numeric,boolean) TO anon;
GRANT EXECUTE ON FUNCTION public.save_current_planning_answer(bigint,text,text,numeric,boolean) TO authenticated;
GRANT EXECUTE ON FUNCTION public.save_current_planning_answer(bigint,text,text,numeric,boolean) TO service_role;
COMMENT ON FUNCTION public.save_current_planning_answer(bigint,text,text,numeric,boolean) IS 'DEPRECATED compatibility API. Intermediate multi-unit planning-answer writer without structured JSON support. New application code must use the target_unit_id + answer_json overload. Retained until external/Appsmith consumers are verified migrated.';
REVOKE ALL ON FUNCTION public.save_current_planning_answer(text,text,numeric,boolean) FROM PUBLIC, anon, authenticated, service_role;
GRANT EXECUTE ON FUNCTION public.save_current_planning_answer(text,text,numeric,boolean) TO anon;
GRANT EXECUTE ON FUNCTION public.save_current_planning_answer(text,text,numeric,boolean) TO authenticated;
GRANT EXECUTE ON FUNCTION public.save_current_planning_answer(text,text,numeric,boolean) TO service_role;
COMMENT ON FUNCTION public.save_current_planning_answer(text,text,numeric,boolean) IS 'DEPRECATED compatibility API. Legacy single-unit planning-answer writer. New application code must use the target_unit_id + answer_json overload. Retained until external/Appsmith consumers are verified migrated.';
REVOKE ALL ON FUNCTION public.set_area_assignment_type(text,text,text) FROM PUBLIC, anon, authenticated, service_role;
GRANT EXECUTE ON FUNCTION public.set_area_assignment_type(text,text,text) TO anon;
GRANT EXECUTE ON FUNCTION public.set_area_assignment_type(text,text,text) TO authenticated;
GRANT EXECUTE ON FUNCTION public.set_area_assignment_type(text,text,text) TO service_role;
REVOKE ALL ON FUNCTION public.set_missionary_special_assignment(text,text,text) FROM PUBLIC, anon, authenticated, service_role;
GRANT EXECUTE ON FUNCTION public.set_missionary_special_assignment(text,text,text) TO anon;
GRANT EXECUTE ON FUNCTION public.set_missionary_special_assignment(text,text,text) TO authenticated;
GRANT EXECUTE ON FUNCTION public.set_missionary_special_assignment(text,text,text) TO service_role;
REVOKE ALL ON FUNCTION public.submit_current_weekly_report() FROM PUBLIC, anon, authenticated, service_role;
GRANT EXECUTE ON FUNCTION public.submit_current_weekly_report() TO anon;
GRANT EXECUTE ON FUNCTION public.submit_current_weekly_report() TO authenticated;
GRANT EXECUTE ON FUNCTION public.submit_current_weekly_report() TO service_role;
COMMENT ON FUNCTION public.submit_current_weekly_report() IS 'DEPRECATED compatibility API. Legacy single-unit submit path. New application code must use submit_current_weekly_report(target_unit_id bigint). Retained temporarily until all external/Appsmith consumers are verified migrated.';
REVOKE ALL ON FUNCTION public.unlink_user_from_missionary(uuid) FROM PUBLIC, anon, authenticated, service_role;
GRANT EXECUTE ON FUNCTION public.unlink_user_from_missionary(uuid) TO anon;
GRANT EXECUTE ON FUNCTION public.unlink_user_from_missionary(uuid) TO authenticated;
GRANT EXECUTE ON FUNCTION public.unlink_user_from_missionary(uuid) TO service_role;
REVOKE ALL ON FUNCTION public.update_current_weekly_report(integer,integer,integer,integer,integer,integer,integer,integer,integer,integer,integer,integer,integer,integer,integer,integer,integer,text) FROM PUBLIC, anon, authenticated, service_role;
GRANT EXECUTE ON FUNCTION public.update_current_weekly_report(integer,integer,integer,integer,integer,integer,integer,integer,integer,integer,integer,integer,integer,integer,integer,integer,integer,text) TO anon;
GRANT EXECUTE ON FUNCTION public.update_current_weekly_report(integer,integer,integer,integer,integer,integer,integer,integer,integer,integer,integer,integer,integer,integer,integer,integer,integer,text) TO authenticated;
GRANT EXECUTE ON FUNCTION public.update_current_weekly_report(integer,integer,integer,integer,integer,integer,integer,integer,integer,integer,integer,integer,integer,integer,integer,integer,integer,text) TO service_role;
COMMENT ON FUNCTION public.update_current_weekly_report(integer,integer,integer,integer,integer,integer,integer,integer,integer,integer,integer,integer,integer,integer,integer,integer,integer,text) IS 'DEPRECATED compatibility API. Legacy single-unit weekly-report update path. New application code must use the target_unit_id bigint overload. Retained temporarily until all external/Appsmith consumers are verified migrated.';
RESET ROLE;

-- 3. Every other right 029 took away, given back by the same grantor; then the record is dropped.
DO $$
DECLARE
  t record;
  given int := 0;
BEGIN
  IF to_regclass('public.cleanup_029_revoked_grants') IS NULL THEN
    RAISE NOTICE '029 rollback: 23 parts back; no record of rights left (rolled back before), nothing else given back';
    RETURN;
  END IF;
  FOR t IN SELECT object_kind, object_name, grantee, grantor, is_grantable,
                  string_agg(privilege_type, ', ' ORDER BY privilege_type) AS privileges, count(*) AS n
           FROM public.cleanup_029_revoked_grants WHERE object_kind <> 'DEFAULT' GROUP BY 1, 2, 3, 4, 5 LOOP
    IF (t.object_kind = 'FUNCTION' AND NOT EXISTS (
          SELECT 1 FROM pg_proc p WHERE format('%I.%I(%s)', p.pronamespace::regnamespace, p.proname,
                                               pg_get_function_identity_arguments(p.oid)) = t.object_name))
       OR (t.object_kind <> 'FUNCTION' AND to_regclass(t.object_name) IS NULL) THEN
      RAISE EXCEPTION 'Stopped: % no longer exists, so its rights cannot be given back.', t.object_name;
    END IF;
    EXECUTE format('SET LOCAL ROLE %I', t.grantor);
    EXECUTE format('GRANT %s ON %s %s TO %I%s', t.privileges, t.object_kind, t.object_name, t.grantee,
                   CASE WHEN t.is_grantable THEN ' WITH GRANT OPTION' ELSE '' END);
    RESET ROLE;
    given := given + t.n;
  END LOOP;
  given := given + (SELECT count(*) FROM public.cleanup_029_revoked_grants WHERE object_kind = 'DEFAULT');
  RAISE NOTICE '029 rollback: 23 parts back, % rights given back', given;
END $$;
DROP TABLE IF EXISTS public.cleanup_029_revoked_grants;

-- Check: every recreated part is exactly as on live Beta before 029, after the hotfix (the fingerprints 029 checks for).
DO $$
DECLARE
  d record;
  actual text;
  changed text := '';
BEGIN
  FOR d IN SELECT * FROM (VALUES
    ('function', 'public.clear_missionary_special_assignment(text)', '2e444ba80de93f0bb2eee26cb4773cf1'),
    ('function', 'public.link_user_to_missionary(uuid,text)', 'bc39c324e852b396fd7c4679a2cb7478'),
    ('function', 'public.save_current_planning_answer(bigint,text,text,numeric,boolean)', '8f4729ec544f778d6fe58fc768505e10'),
    ('function', 'public.save_current_planning_answer(text,text,numeric,boolean)', '7f2c508c64a2223cb6eaa9f442512135'),
    ('function', 'public.set_area_assignment_type(text,text,text)', '54f25895d5c6a6e0af255848fe4d8e3e'),
    ('function', 'public.set_missionary_special_assignment(text,text,text)', '43c285f3664d25bd1e4267e89dce3738'),
    ('function', 'public.submit_current_weekly_report()', '7c59fc705bf007d0089a1ac3ef5c5b9e'),
    ('function', 'public.unlink_user_from_missionary(uuid)', 'af6e07a328dee91dc3a456132d31127b'),
    ('function', 'public.update_current_weekly_report(integer,integer,integer,integer,integer,integer,integer,integer,integer,integer,integer,integer,integer,integer,integer,integer,integer,text)', '536be00b2b173984dded72695ceda165'),
    ('table', 'public.missionary_import_stage', '7741eeed525bf4e65189ca58f2b01da4'),
    ('table', 'public.organization_import_stage', '232e1122a959f521c23220f19ae2c62c'),
    ('view', 'public.area_weekly_metrics_clean', '9dd2869fa05b3847d0a2a1589d7bae50'),
    ('view', 'public.district_weekly_metrics_clean', 'bc63b0712de48c8e9c8e59dd65cefd42'),
    ('view', 'public.zone_weekly_metrics_clean', '2be268ebb2a0d4863f9b450076b9a470'),
    ('view', 'public.mission_weekly_metrics_clean', '4b71647f30626308c4fa65cadfaf1fcc'),
    ('view', 'public.district_reporting_status', '3a7c314a7b7db36e728cdcdb2de5a535'),
    ('view', 'public.zone_reporting_status', '93b4901c60f5e3a4932b7bc94d226ded'),
    ('view', 'public.mission_reporting_status', '3a56117686bf95199bfa8601923bce04'),
    ('view', 'public.area_history', '48f6ad5d2c7f013612b0c2363dd84692'),
    ('view', 'public.current_assignment_details', '2d080552244df42ff75ce859fc16c6a6'),
    ('view', 'public.new_members_clean', 'd4e7a781d556d1339884494ad6eedab1'),
    ('view', 'public.baptismal_dates_clean', '317dc5b5727f10d3e183c3381ed224c5'),
    ('view', 'public.high_potentials_clean', 'e8cbcd0d09950c38884d9cc86d35530e')) v(kind, name, fingerprint) LOOP
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
    IF actual IS DISTINCT FROM d.fingerprint THEN
      changed := changed || format(E'\n  %s (%s)', d.name, coalesce(actual, 'missing'));
    END IF;
  END LOOP;
  IF changed <> '' THEN
    RAISE EXCEPTION 'Check failed: these parts are not as before 029:%', changed;
  END IF;
END $$;

NOTIFY pgrst, 'reload schema';
COMMIT;
