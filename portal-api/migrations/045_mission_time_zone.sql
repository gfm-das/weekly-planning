-- Migration 045 (Oct 2026): the database counts weeks in the mission's own time zone. Run on Beta only, as supabase_admin.
--
-- Why: the database decided which week a moment belongs to, and put "Sunday noon" on the dashboards, in Europe/Berlin only (written
-- into 10 views and 2 functions). A mission in another time zone would have had some events counted in the wrong week.
-- What changes (nothing for a mission whose time zone is Europe/Berlin: every result stays the same):
-- 1. public.missions.time_zone (an IANA name, default Europe/Berlin): the mission's time zone. The installer sets it.
-- 2. public.gfm_time_zone(): the zone of the first mission in this database (Europe/Berlin when there is none). SECURITY DEFINER, so
--    every caller gets the answer; only the named roles may run it (not PUBLIC: migration 019 would refuse that).
-- 3. These objects use gfm_time_zone() where they had the text 'Europe/Berlin': current_baptismal_date_people, current_new_members, dashboards.baptism_history_week, dashboards.findechristus_referrals_week, dashboards.finding_area_week, dashboards.finding_cohort_week, dashboards.finding_rate_week, dashboards.people_area_week_counts, dashboards.referral_archive_week, dashboards.zone_history_week, dashboards.area_week_rows, reporting_sunday_at.
-- 4. The default of portal.events.timezone follows it too.
-- The new text of each object is the old one with that one change (made from the running definitions, so nothing is retyped).
-- Rollback: 045_mission_time_zone_rollback.sql puts the old definitions back and removes the column and the function.
-- Run 019_restrict_public_functions.sql again afterwards, as after every migration.
BEGIN;

ALTER TABLE public.missions
    ADD COLUMN time_zone text NOT NULL DEFAULT 'Europe/Berlin'
    CONSTRAINT missions_time_zone_check CHECK (time_zone ~ '^[A-Za-z0-9_+-]+(/[A-Za-z0-9_+-]+){0,2}$');
COMMENT ON COLUMN public.missions.time_zone IS
    'The mission''s time zone (IANA name): weeks, "today" and the dashboards'' Sunday noon are counted in it. Programs read GFM_TIME_ZONE.';

CREATE OR REPLACE FUNCTION public.gfm_time_zone()
 RETURNS text
 LANGUAGE sql
 STABLE SECURITY DEFINER
 SET search_path = public, pg_temp
AS $function$
    SELECT coalesce((SELECT m.time_zone FROM public.missions m ORDER BY m.id LIMIT 1), 'Europe/Berlin')
$function$;
REVOKE ALL ON FUNCTION public.gfm_time_zone() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.gfm_time_zone() TO postgres, anon, authenticated, service_role, gfm_dashboard_reader;

CREATE OR REPLACE VIEW current_baptismal_date_people WITH (security_invoker=true) AS
 SELECT f.id,
    f.first_name,
    f.last_name,
    f.display_name,
    f.finding_source,
    faa.area_id,
    faa.start_date AS area_start_date,
    d.current_baptismal_date
   FROM ((baptismal_date_people f
     JOIN baptismal_date_person_area_assignments faa ON ((faa.baptismal_date_person_id = f.id)))
     LEFT JOIN LATERAL ( SELECT w.current_baptismal_date
           FROM ((weekly_baptismal_date_friends w
             JOIN weekly_area_reports r ON ((r.id = w.weekly_area_report_id)))
             JOIN reporting_weeks rw ON ((rw.id = r.reporting_week_id)))
          WHERE ((w.baptismal_date_person_id = f.id) AND (w.current_baptismal_date IS NOT NULL))
          ORDER BY rw.sunday DESC, w.updated_at DESC NULLS LAST, w.id DESC
         LIMIT 1) d ON (true))
  WHERE ((faa.end_date IS NULL) AND (f.tracking_status = 'current'::text) AND ((d.current_baptismal_date IS NULL) OR (d.current_baptismal_date >= ((now() AT TIME ZONE public.gfm_time_zone()))::date)));

CREATE OR REPLACE VIEW current_new_members WITH (security_invoker=true) AS
 SELECT nm.id,
    nm.area_id,
    nm.first_name,
    nm.last_name,
    nm.display_name,
    nm.baptism_date,
    nm.confirmation_date,
    nm.active,
    nm.created_at,
    nm.updated_at,
    nm.stake_id,
    nm.unit_id,
    nm.baptismal_date_extended,
    nm.finding_source,
    nm.conversion_success_notes,
    nm.date_of_birth,
    nm.age_range,
    nm.gender,
    nm.marital_status,
    nm.child_dependents,
    nm.living_situation,
    nm.native_language,
    nm.second_language,
    nm.mission_language_competency,
    nm.country_of_origin,
    nm.created_by,
    nm.inactive_at,
    nm.inactive_reason,
    nm.follow_up_status,
    nm.follow_up_ended_at,
    nm.follow_up_end_reason
   FROM new_members nm
  WHERE ((nm.follow_up_status = 'current'::text) AND (((nm.baptism_date IS NOT NULL) AND (nm.baptism_date > (((now() AT TIME ZONE public.gfm_time_zone()))::date - '1 year'::interval))) OR ((nm.baptism_date IS NULL) AND (EXISTS ( SELECT 1
           FROM ((weekly_new_members w
             JOIN weekly_area_reports r ON ((r.id = w.weekly_area_report_id)))
             JOIN reporting_weeks rw ON ((rw.id = r.reporting_week_id)))
          WHERE ((w.new_member_id = nm.id) AND (rw.sunday >= (current_reporting_sunday() - 7))))))) AND (EXISTS ( SELECT 1
           FROM new_member_area_assignments a
          WHERE ((a.new_member_id = nm.id) AND (a.end_date IS NULL) AND (a.area_id = nm.area_id)))));

CREATE OR REPLACE VIEW dashboards.baptism_history_week AS
 SELECT b.sunday,
    ((b.sunday + '12:00:00'::time without time zone) AT TIME ZONE public.gfm_time_zone()) AS week,
    b.mission_id,
    COALESCE(pz.id, fz.id) AS zone_id,
    COALESCE(pz.name, fz.name, NULLIF(b.zone_name, ''::text)) AS zone,
    pd.id AS district_id,
    pd.name AS district,
    b.area_id,
    COALESCE(pa.name, NULLIF(b.area_name, ''::text)) AS area,
    NULLIF(b.ward, ''::text) AS ward,
    NULLIF(b.finding_source, ''::text) AS finding_source,
    b.baptisms,
    b.confirmations
   FROM (((((baptism_history_weeks b
     JOIN data_upload_week_batches w ON (((w.kind = 'BAPTISMS'::text) AND (w.batch_id = b.batch_id) AND (w.mission_id = b.mission_id) AND (w.sunday = b.sunday))))
     LEFT JOIN areas pa ON ((pa.id = b.area_id)))
     LEFT JOIN districts pd ON ((pd.id = pa.district_id)))
     LEFT JOIN zones pz ON ((pz.id = pd.zone_id)))
     LEFT JOIN zones fz ON ((fz.id = b.zone_id)));

CREATE OR REPLACE VIEW dashboards.findechristus_referrals_week AS
 WITH finding AS (
         SELECT f.sunday,
            f.mission_id,
            f.zone_id,
            f.zone,
            f.district_id,
            f.district,
            f.area_id,
            f.area,
            (sum(f.people_found))::bigint AS referrals
           FROM dashboards.finding_area_week f
          WHERE (f.findechristus AND (f.people_found > 0))
          GROUP BY f.sunday, f.mission_id, f.zone_id, f.zone, f.district_id, f.district, f.area_id, f.area
        ), first_found AS (
         SELECT finding_people_placed.mission_id,
            min(finding_people_placed.found_on) AS day
           FROM finding_people_placed
          GROUP BY finding_people_placed.mission_id
        ), first_whole_week AS (
         SELECT first_found.mission_id,
            ((first_found.day + ((8 - (EXTRACT(isodow FROM first_found.day))::integer) % 7)) + 6) AS sunday
           FROM first_found
        ), archive AS (
         SELECT a.sunday,
            a.mission_id,
            a.zone_id,
            a.zone,
            a.district_id,
            a.district,
            a.area_id,
            a.area,
            sum(a.referrals_received) AS referrals
           FROM (dashboards.referral_archive_week a
             LEFT JOIN first_whole_week s ON ((s.mission_id = a.mission_id)))
          WHERE ((s.sunday IS NULL) OR (a.sunday < s.sunday))
          GROUP BY a.sunday, a.mission_id, a.zone_id, a.zone, a.district_id, a.district, a.area_id, a.area
        ), finding_used AS (
         SELECT f.sunday,
            f.mission_id,
            f.zone_id,
            f.zone,
            f.district_id,
            f.district,
            f.area_id,
            f.area,
            f.referrals
           FROM (finding f
             JOIN first_whole_week s ON ((s.mission_id = f.mission_id)))
          WHERE ((f.sunday >= s.sunday) OR (NOT (EXISTS ( SELECT 1
                   FROM archive a
                  WHERE ((a.mission_id = f.mission_id) AND (a.sunday = f.sunday))))))
        )
 SELECT x.sunday,
    ((x.sunday + '12:00:00'::time without time zone) AT TIME ZONE public.gfm_time_zone()) AS week,
    x.mission_id,
    x.zone_id,
    x.zone,
    x.district_id,
    x.district,
    x.area_id,
    x.area,
    x.referrals,
    x.data_source
   FROM ( SELECT finding_used.sunday,
            finding_used.mission_id,
            finding_used.zone_id,
            finding_used.zone,
            finding_used.district_id,
            finding_used.district,
            finding_used.area_id,
            finding_used.area,
            finding_used.referrals,
            'finding export'::text AS data_source
           FROM finding_used
        UNION ALL
         SELECT archive.sunday,
            archive.mission_id,
            archive.zone_id,
            archive.zone,
            archive.district_id,
            archive.district,
            archive.area_id,
            archive.area,
            archive.referrals,
            'referral archive'::text AS text
           FROM archive) x;

CREATE OR REPLACE VIEW dashboards.finding_area_week AS
 WITH events AS (
         SELECT p.mission_id,
            p.zone_id,
            p.zone,
            p.district_id,
            p.district,
            p.area_id,
            p.area,
            p.finding_category,
            p.finding_source,
            p.findechristus,
            e_1.what,
            (e_1.day + ((7 - (EXTRACT(isodow FROM e_1.day))::integer) % 7)) AS sunday
           FROM (finding_people_placed p
             CROSS JOIN LATERAL ( VALUES ('found'::text,p.found_on), ('referral'::text,p.referral_on), ('contact_attempt'::text,p.contact_attempt_on), ('contacted'::text,p.contacted_on), ('first_lesson'::text,p.first_lesson_on), ('second_lesson'::text,p.second_lesson_on), ('taught'::text,p.taught_on), ('baptismal_date'::text,p.baptismal_date_set_on), ('first_sacrament'::text,p.first_sacrament_on), ('confirmed'::text,p.confirmed_on)) e_1(what, day))
          WHERE (e_1.day IS NOT NULL)
        )
 SELECT e.sunday,
    ((e.sunday + '12:00:00'::time without time zone) AT TIME ZONE public.gfm_time_zone()) AS week,
    e.mission_id,
    e.zone_id,
    e.zone,
    e.district_id,
    e.district,
    e.area_id,
    e.area,
    e.finding_category,
    e.finding_source,
    e.findechristus,
    count(*) FILTER (WHERE (e.what = 'found'::text)) AS people_found,
    count(*) FILTER (WHERE (e.what = 'referral'::text)) AS referrals,
    count(*) FILTER (WHERE (e.what = 'contact_attempt'::text)) AS contact_attempts,
    count(*) FILTER (WHERE (e.what = 'contacted'::text)) AS people_reached,
    count(*) FILTER (WHERE (e.what = 'first_lesson'::text)) AS first_lessons,
    count(*) FILTER (WHERE (e.what = 'second_lesson'::text)) AS second_lessons,
    count(*) FILTER (WHERE (e.what = 'taught'::text)) AS new_people_being_taught,
    count(*) FILTER (WHERE (e.what = 'baptismal_date'::text)) AS baptismal_dates_set,
    count(*) FILTER (WHERE (e.what = 'first_sacrament'::text)) AS first_sacrament_meetings,
    count(*) FILTER (WHERE (e.what = 'confirmed'::text)) AS confirmations
   FROM events e
  GROUP BY e.sunday, e.mission_id, e.zone_id, e.zone, e.district_id, e.district, e.area_id, e.area, e.finding_category, e.finding_source, e.findechristus;

CREATE OR REPLACE VIEW dashboards.finding_cohort_week AS
 SELECT (p.found_on + ((7 - (EXTRACT(isodow FROM p.found_on))::integer) % 7)) AS sunday,
    (((p.found_on + ((7 - (EXTRACT(isodow FROM p.found_on))::integer) % 7)) + '12:00:00'::time without time zone) AT TIME ZONE public.gfm_time_zone()) AS week,
    p.mission_id,
    p.zone_id,
    p.zone,
    p.district_id,
    p.district,
    p.area_id,
    p.area,
    p.finding_category,
    p.finding_source,
    p.findechristus,
    count(*) AS people_found,
    count(p.contact_attempt_on) AS contact_attempted,
    count(p.contacted_on) AS reached,
    count(p.first_lesson_on) AS taught,
    count(p.taught_on) AS new_people_being_taught,
    count(p.baptismal_date_set_on) AS with_baptismal_date,
    count(p.first_sacrament_on) AS at_sacrament_meeting,
    count(p.confirmed_on) AS confirmed
   FROM finding_people_placed p
  WHERE (p.found_on IS NOT NULL)
  GROUP BY (p.found_on + ((7 - (EXTRACT(isodow FROM p.found_on))::integer) % 7)), ((((p.found_on + ((7 - (EXTRACT(isodow FROM p.found_on))::integer) % 7)) + '12:00:00'::time without time zone) AT TIME ZONE public.gfm_time_zone())), p.mission_id, p.zone_id, p.zone, p.district_id, p.district, p.area_id, p.area, p.finding_category, p.finding_source, p.findechristus;

CREATE OR REPLACE VIEW dashboards.finding_rate_week AS
 SELECT r.sunday,
    ((r.sunday + '12:00:00'::time without time zone) AT TIME ZONE public.gfm_time_zone()) AS week,
    r.report_date,
    r.mission_id,
    r.is_mission,
        CASE
            WHEN r.is_mission THEN NULL::bigint
            ELSE COALESCE(z.id, r.zone_id)
        END AS zone_id,
        CASE
            WHEN r.is_mission THEN 'Mission'::text
            ELSE COALESCE(z.name, r.zone_name)
        END AS zone,
    r.teaching_rate,
    r.contact_rate
   FROM ((finding_rate_weeks r
     JOIN data_upload_week_batches w ON (((w.kind = 'RATES'::text) AND (w.batch_id = r.batch_id) AND (w.mission_id = r.mission_id) AND (w.sunday = r.sunday))))
     LEFT JOIN zones z ON ((z.id = r.zone_id)));

CREATE OR REPLACE VIEW dashboards.people_area_week_counts AS
 WITH cells AS (
         SELECT DISTINCT r.reporting_week_id,
            r.area_id
           FROM weekly_area_reports r
        ), nm AS (
         SELECT r.reporting_week_id,
            r.area_id,
            count(*) AS new_members,
            count(*) FILTER (WHERE n.at_church_this_sunday) AS new_members_at_church,
            count(*) FILTER (WHERE (n.has_active_temple_recommend = 'yes'::text)) AS new_members_temple_recommend,
            count(*) FILTER (WHERE (n.has_calling = 'yes'::text)) AS new_members_calling,
            count(*) FILTER (WHERE (n.has_aaronic_priesthood = 'yes'::text)) AS new_members_aaronic_priesthood,
            count(*) FILTER (WHERE (n.has_melchizedek_priesthood = 'yes'::text)) AS new_members_melchizedek_priesthood,
            count(*) FILTER (WHERE (n.ministers_to_someone = 'yes'::text)) AS new_members_ministering,
            count(*) FILTER (WHERE n.ministered_to_by_someone) AS new_members_with_minister,
            count(*) FILTER (WHERE (n.visited_temple_for_baptisms = 'yes'::text)) AS new_members_visited_temple,
            count(*) FILTER (WHERE n.reading) AS new_members_reading,
            count(*) FILTER (WHERE n.praying) AS new_members_praying,
            count(*) FILTER (WHERE n.member_involvement) AS new_members_member_involvement,
            count(*) FILTER (WHERE n.discussed_in_gemiko) AS new_members_discussed_in_gemiko
           FROM (weekly_new_members n
             JOIN weekly_area_reports r ON ((r.id = n.weekly_area_report_id)))
          GROUP BY r.reporting_week_id, r.area_id
        ), bd AS (
         SELECT r.reporting_week_id,
            r.area_id,
            count(*) AS baptismal_date_friends,
            count(*) FILTER (WHERE ((f.current_baptismal_date >= w_1.sunday) AND (f.current_baptismal_date <= (w_1.sunday + 28)))) AS baptismal_date_friends_next_4_weeks,
            count(*) FILTER (WHERE f.at_church_this_sunday) AS baptismal_date_friends_at_church,
            count(*) FILTER (WHERE f.reading) AS baptismal_date_friends_reading,
            count(*) FILTER (WHERE f.praying) AS baptismal_date_friends_praying,
            count(*) FILTER (WHERE f.keeping_commandments) AS baptismal_date_friends_keeping_commandments,
            count(*) FILTER (WHERE f.member_involvement) AS baptismal_date_friends_member_involvement
           FROM ((weekly_baptismal_date_friends f
             JOIN weekly_area_reports r ON ((r.id = f.weekly_area_report_id)))
             JOIN reporting_weeks w_1 ON ((w_1.id = r.reporting_week_id)))
          GROUP BY r.reporting_week_id, r.area_id
        ), hp AS (
         SELECT r.reporting_week_id,
            r.area_id,
            count(*) AS high_potentials,
            count(*) FILTER (WHERE h.at_church_this_sunday) AS high_potentials_at_church
           FROM (weekly_high_potential_friends h
             JOIN weekly_area_reports r ON ((r.id = h.weekly_area_report_id)))
          GROUP BY r.reporting_week_id, r.area_id
        )
 SELECT ((w.sunday + '12:00:00'::time without time zone) AT TIME ZONE public.gfm_time_zone()) AS week,
    w.sunday,
    w.id AS reporting_week_id,
    z.mission_id,
    z.id AS zone_id,
    z.name AS zone,
    d.id AS district_id,
    d.name AS district,
    a.id AS area_id,
    a.name AS area,
    COALESCE(nm.new_members, (0)::bigint) AS new_members,
    COALESCE(nm.new_members_at_church, (0)::bigint) AS new_members_at_church,
    COALESCE(nm.new_members_temple_recommend, (0)::bigint) AS new_members_temple_recommend,
    COALESCE(nm.new_members_calling, (0)::bigint) AS new_members_calling,
    COALESCE(nm.new_members_aaronic_priesthood, (0)::bigint) AS new_members_aaronic_priesthood,
    COALESCE(nm.new_members_melchizedek_priesthood, (0)::bigint) AS new_members_melchizedek_priesthood,
    COALESCE(nm.new_members_ministering, (0)::bigint) AS new_members_ministering,
    COALESCE(nm.new_members_with_minister, (0)::bigint) AS new_members_with_minister,
    COALESCE(nm.new_members_visited_temple, (0)::bigint) AS new_members_visited_temple,
    COALESCE(nm.new_members_reading, (0)::bigint) AS new_members_reading,
    COALESCE(nm.new_members_praying, (0)::bigint) AS new_members_praying,
    COALESCE(nm.new_members_member_involvement, (0)::bigint) AS new_members_member_involvement,
    COALESCE(nm.new_members_discussed_in_gemiko, (0)::bigint) AS new_members_discussed_in_gemiko,
    COALESCE(bd.baptismal_date_friends, (0)::bigint) AS baptismal_date_friends,
    COALESCE(bd.baptismal_date_friends_next_4_weeks, (0)::bigint) AS baptismal_date_friends_next_4_weeks,
    COALESCE(bd.baptismal_date_friends_at_church, (0)::bigint) AS baptismal_date_friends_at_church,
    COALESCE(bd.baptismal_date_friends_reading, (0)::bigint) AS baptismal_date_friends_reading,
    COALESCE(bd.baptismal_date_friends_praying, (0)::bigint) AS baptismal_date_friends_praying,
    COALESCE(bd.baptismal_date_friends_keeping_commandments, (0)::bigint) AS baptismal_date_friends_keeping_commandments,
    COALESCE(bd.baptismal_date_friends_member_involvement, (0)::bigint) AS baptismal_date_friends_member_involvement,
    COALESCE(hp.high_potentials, (0)::bigint) AS high_potentials,
    COALESCE(hp.high_potentials_at_church, (0)::bigint) AS high_potentials_at_church
   FROM (((((((cells c
     JOIN reporting_weeks w ON ((w.id = c.reporting_week_id)))
     JOIN areas a ON ((a.id = c.area_id)))
     JOIN districts d ON ((d.id = a.district_id)))
     JOIN zones z ON ((z.id = d.zone_id)))
     LEFT JOIN nm ON (((nm.reporting_week_id = c.reporting_week_id) AND (nm.area_id = c.area_id))))
     LEFT JOIN bd ON (((bd.reporting_week_id = c.reporting_week_id) AND (bd.area_id = c.area_id))))
     LEFT JOIN hp ON (((hp.reporting_week_id = c.reporting_week_id) AND (hp.area_id = c.area_id))));

CREATE OR REPLACE VIEW dashboards.referral_archive_week AS
 SELECT r.sunday,
    ((r.sunday + '12:00:00'::time without time zone) AT TIME ZONE public.gfm_time_zone()) AS week,
    r.report_date,
    r.mission_id,
    COALESCE(pz.id, fz.id) AS zone_id,
    COALESCE(pz.name, fz.name, NULLIF(r.zone_name, ''::text)) AS zone,
    pd.id AS district_id,
    pd.name AS district,
    r.area_id,
    COALESCE(pa.name, NULLIF(r.area_name, ''::text)) AS area,
    r.source,
    r.referrals_received,
    r.referrals_contacted,
    r.friends_made,
    r.lessons_taught,
    r.church_attendance,
    r.baptismal_dates,
    r.baptisms,
    r.books_of_mormon,
    r.with_member,
    r.follow_up_lessons
   FROM (((((referral_archive_weeks r
     JOIN data_upload_week_batches w ON (((w.kind = 'REFERRAL_ARCHIVE'::text) AND (w.batch_id = r.batch_id) AND (w.mission_id = r.mission_id) AND (w.sunday = r.sunday))))
     LEFT JOIN areas pa ON ((pa.id = r.area_id)))
     LEFT JOIN districts pd ON ((pd.id = pa.district_id)))
     LEFT JOIN zones pz ON ((pz.id = pd.zone_id)))
     LEFT JOIN zones fz ON ((fz.id = r.zone_id)));

CREATE OR REPLACE VIEW dashboards.zone_history_week AS
 WITH portal AS (
         SELECT k.sunday,
            k.mission_id,
            k.zone_id,
            k.zone,
            k.friends_found_actual,
            k.friends_found_goal,
            k.friends_found_previous_goal,
            k.members_at_lessons_actual,
            k.members_at_lessons_goal,
            k.members_at_lessons_previous_goal,
            k.sacrament_attendance_actual,
            k.sacrament_attendance_goal,
            k.sacrament_attendance_previous_goal,
            k.baptismal_dates_actual,
            k.baptismal_dates_goal,
            k.baptismal_dates_previous_goal,
            k.baptisms_confirmations_actual,
            k.baptisms_confirmations_goal,
            k.baptisms_confirmations_previous_goal,
            k.new_member_sacrament_actual,
            k.new_member_sacrament_goal,
            k.new_member_sacrament_previous_goal,
            k.follow_up_lessons_actual,
            k.first_time_sacrament_actual,
            k.areas_reporting AS companionships
           FROM dashboards.kpi_zone_week k
          WHERE (k.reports > 0)
        ), counted AS (
         SELECT u.batch_id,
            u.mission_id,
            u.sunday,
            u.zone_id,
            u.zone_name,
            u.friends_found_goal,
            u.friends_found_actual,
            u.members_at_lessons_goal,
            u.members_at_lessons_actual,
            u.sacrament_attendance_goal,
            u.sacrament_attendance_actual,
            u.baptismal_dates_goal,
            u.baptismal_dates_actual,
            u.baptisms_confirmations_goal,
            u.baptisms_confirmations_actual,
            u.new_member_sacrament_goal,
            u.new_member_sacrament_actual,
            u.follow_up_lessons_actual,
            u.first_time_sacrament_actual,
            u.companionships
           FROM (zone_history_weeks u
             JOIN data_upload_week_batches w ON (((w.kind = 'ZONE_HISTORY'::text) AND (w.batch_id = u.batch_id) AND (w.mission_id = u.mission_id) AND (w.sunday = u.sunday))))
        ), uploaded AS (
         SELECT u.sunday,
            u.mission_id,
            z.id AS zone_id,
            COALESCE(z.name, u.zone_name) AS zone,
            u.friends_found_actual,
            u.friends_found_goal,
            b.friends_found_goal AS friends_found_previous_goal,
            u.members_at_lessons_actual,
            u.members_at_lessons_goal,
            b.members_at_lessons_goal AS members_at_lessons_previous_goal,
            u.sacrament_attendance_actual,
            u.sacrament_attendance_goal,
            b.sacrament_attendance_goal AS sacrament_attendance_previous_goal,
            u.baptismal_dates_actual,
            u.baptismal_dates_goal,
            b.baptismal_dates_goal AS baptismal_dates_previous_goal,
            u.baptisms_confirmations_actual,
            u.baptisms_confirmations_goal,
            b.baptisms_confirmations_goal AS baptisms_confirmations_previous_goal,
            u.new_member_sacrament_actual,
            u.new_member_sacrament_goal,
            b.new_member_sacrament_goal AS new_member_sacrament_previous_goal,
            u.follow_up_lessons_actual,
            u.first_time_sacrament_actual,
            u.companionships
           FROM ((counted u
             LEFT JOIN zones z ON ((z.id = u.zone_id)))
             LEFT JOIN counted b ON (((b.mission_id = u.mission_id) AND (b.sunday = (u.sunday - 7)) AND
                CASE
                    WHEN (u.zone_id IS NULL) THEN ((b.zone_id IS NULL) AND (lower(b.zone_name) = lower(u.zone_name)))
                    ELSE (b.zone_id = u.zone_id)
                END)))
          WHERE (NOT (EXISTS ( SELECT 1
                   FROM portal p
                  WHERE ((p.mission_id = u.mission_id) AND (p.sunday = u.sunday) AND (p.zone_id = u.zone_id)))))
        )
 SELECT x.sunday,
    ((x.sunday + '12:00:00'::time without time zone) AT TIME ZONE public.gfm_time_zone()) AS week,
    x.mission_id,
    x.zone_id,
    x.zone,
    x.data_source,
    x.friends_found_actual,
    x.friends_found_goal,
    x.friends_found_previous_goal,
    x.members_at_lessons_actual,
    x.members_at_lessons_goal,
    x.members_at_lessons_previous_goal,
    x.sacrament_attendance_actual,
    x.sacrament_attendance_goal,
    x.sacrament_attendance_previous_goal,
    x.baptismal_dates_actual,
    x.baptismal_dates_goal,
    x.baptismal_dates_previous_goal,
    x.baptisms_confirmations_actual,
    x.baptisms_confirmations_goal,
    x.baptisms_confirmations_previous_goal,
    x.new_member_sacrament_actual,
    x.new_member_sacrament_goal,
    x.new_member_sacrament_previous_goal,
    x.follow_up_lessons_actual,
    x.first_time_sacrament_actual,
    x.companionships
   FROM ( SELECT portal.sunday,
            portal.mission_id,
            portal.zone_id,
            portal.zone,
            portal.friends_found_actual,
            portal.friends_found_goal,
            portal.friends_found_previous_goal,
            portal.members_at_lessons_actual,
            portal.members_at_lessons_goal,
            portal.members_at_lessons_previous_goal,
            portal.sacrament_attendance_actual,
            portal.sacrament_attendance_goal,
            portal.sacrament_attendance_previous_goal,
            portal.baptismal_dates_actual,
            portal.baptismal_dates_goal,
            portal.baptismal_dates_previous_goal,
            portal.baptisms_confirmations_actual,
            portal.baptisms_confirmations_goal,
            portal.baptisms_confirmations_previous_goal,
            portal.new_member_sacrament_actual,
            portal.new_member_sacrament_goal,
            portal.new_member_sacrament_previous_goal,
            portal.follow_up_lessons_actual,
            portal.first_time_sacrament_actual,
            portal.companionships,
            'portal'::text AS data_source
           FROM portal
        UNION ALL
         SELECT uploaded.sunday,
            uploaded.mission_id,
            uploaded.zone_id,
            uploaded.zone,
            uploaded.friends_found_actual,
            uploaded.friends_found_goal,
            uploaded.friends_found_previous_goal,
            uploaded.members_at_lessons_actual,
            uploaded.members_at_lessons_goal,
            uploaded.members_at_lessons_previous_goal,
            uploaded.sacrament_attendance_actual,
            uploaded.sacrament_attendance_goal,
            uploaded.sacrament_attendance_previous_goal,
            uploaded.baptismal_dates_actual,
            uploaded.baptismal_dates_goal,
            uploaded.baptismal_dates_previous_goal,
            uploaded.baptisms_confirmations_actual,
            uploaded.baptisms_confirmations_goal,
            uploaded.baptisms_confirmations_previous_goal,
            uploaded.new_member_sacrament_actual,
            uploaded.new_member_sacrament_goal,
            uploaded.new_member_sacrament_previous_goal,
            uploaded.follow_up_lessons_actual,
            uploaded.first_time_sacrament_actual,
            uploaded.companionships,
            'upload'::text AS text
           FROM uploaded) x;

CREATE OR REPLACE FUNCTION dashboards.area_week_rows()
 RETURNS TABLE(week timestamp with time zone, sunday date, reporting_week_id bigint, previous_reporting_week_id bigint, mission_id bigint, zone_id bigint, zone text, district_id bigint, district text, area_id bigint, area text, unit_id bigint, unit text, status text, submitted boolean, friends_found_actual integer, friends_found_goal integer, friends_found_previous_goal bigint, baptisms_confirmations_actual integer, baptisms_confirmations_goal integer, baptisms_confirmations_previous_goal bigint, baptismal_dates_actual integer, baptismal_dates_goal integer, baptismal_dates_previous_goal bigint, sacrament_attendance_actual integer, sacrament_attendance_goal integer, sacrament_attendance_previous_goal bigint, members_at_lessons_actual integer, members_at_lessons_goal integer, members_at_lessons_previous_goal bigint, new_member_sacrament_actual integer, new_member_sacrament_goal integer, new_member_sacrament_previous_goal bigint, first_time_sacrament_actual integer, lessons_with_friends_actual integer, lessons_with_friends_goal integer, follow_up_lessons_actual integer, follow_up_lessons_goal integer)
 LANGUAGE sql
 STABLE SECURITY DEFINER
 SET search_path TO 'pg_catalog', 'pg_temp'
AS $function$
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
  SELECT (w.sunday + time '12:00') AT TIME ZONE public.gfm_time_zone(), w.sunday, w.id, w.previous_id,
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
$function$;

CREATE OR REPLACE FUNCTION public.reporting_sunday_at(at_time timestamp with time zone)
 RETURNS date
 LANGUAGE sql
 STABLE
AS $function$
  SELECT (at_time AT TIME ZONE public.gfm_time_zone())::date
         - extract(dow FROM (at_time AT TIME ZONE public.gfm_time_zone()))::integer;
$function$;

ALTER TABLE portal.events ALTER COLUMN timezone SET DEFAULT public.gfm_time_zone();

COMMIT;
