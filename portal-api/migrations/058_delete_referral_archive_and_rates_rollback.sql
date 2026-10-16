-- Rollback of 058_delete_referral_archive_and_rates.sql. Run on Beta only, as supabase_admin.
--
-- What it does: makes the two tables (public.referral_archive_weeks, public.finding_rate_weeks) and the three views
-- (dashboards.referral_archive_week, dashboards.findechristus_referrals_week, dashboards.finding_rate_week) again as 033 and 045 made
-- them, EMPTY; puts the two kinds back into public.data_upload_week_batches; points dashboards.archetype_area_week back at
-- dashboards.findechristus_referrals_week; and allows the batch kinds REFERRAL_ARCHIVE and RATES again.
-- WHAT DOES NOT COME BACK: the uploaded rows of the two tables and the Import history entries (batches) of the two kinds, which
-- 058 deleted. Restore a backup taken before 058 if they should be kept.
-- Do it together with the code rollback (the DA Management image with the two uploads), or the Data uploads pages show an error.
--
-- Apply:
--   (Get-Content portal-api/migrations/058_delete_referral_archive_and_rates_rollback.sql) -join "`n" |
--     docker exec -i gfm-beta-supabase-db-1 psql -U supabase_admin -d postgres -v ON_ERROR_STOP=1
-- Then run 019 again as a check. Safe to run again.
BEGIN;
SET LOCAL lock_timeout = '10s';

DO $$
BEGIN
  IF session_user NOT IN ('supabase_admin', 'postgres') THEN
    RAISE EXCEPTION 'Run this file as supabase_admin (see its header), not as %.', session_user;
  END IF;
END $$;

-- The batch kinds first (the table belongs to supabase_admin).
DO $$
DECLARE
  kinds text[];
BEGIN
  SELECT array_agg(DISTINCT m[1] ORDER BY m[1]) INTO kinds
  FROM pg_constraint c
  CROSS JOIN LATERAL regexp_matches(pg_get_constraintdef(c.oid), '''([A-Z_]+)''', 'g') AS m
  WHERE c.conrelid = 'public.roster_import_batches'::regclass AND c.conname = 'roster_import_batches_kind_check';
  IF kinds IS NULL OR NOT ('TRANSFER' = ANY (kinds)) THEN
    RAISE EXCEPTION 'The list of batch kinds could not be read from roster_import_batches_kind_check (found: %).', kinds;
  END IF;
  IF NOT ('REFERRAL_ARCHIVE' = ANY (kinds) AND 'RATES' = ANY (kinds)) THEN
    kinds := array_remove(array_remove(kinds, 'REFERRAL_ARCHIVE'), 'RATES') || ARRAY['REFERRAL_ARCHIVE', 'RATES']::text[];
    ALTER TABLE public.roster_import_batches DROP CONSTRAINT roster_import_batches_kind_check;
    EXECUTE format('ALTER TABLE public.roster_import_batches ADD CONSTRAINT roster_import_batches_kind_check CHECK (kind IN (%s))',
      (SELECT string_agg(quote_literal(k), ', ' ORDER BY k) FROM unnest(kinds) k));
  END IF;
END $$;

SET LOCAL ROLE postgres;

-- The tables as 033 made them (empty).
CREATE TABLE IF NOT EXISTS public.referral_archive_weeks (
    batch_id uuid NOT NULL REFERENCES public.roster_import_batches(id) ON DELETE CASCADE,
    mission_id bigint NOT NULL REFERENCES public.missions(id),
    sunday date NOT NULL,
    report_date date NOT NULL,
    zone_id bigint REFERENCES public.zones(id),
    area_id bigint REFERENCES public.areas(id),
    zone_name text DEFAULT ''::text NOT NULL,
    area_name text DEFAULT ''::text NOT NULL,
    source text DEFAULT ''::text NOT NULL,
    referrals_received integer,
    referrals_contacted integer,
    friends_made integer,
    lessons_taught integer,
    church_attendance integer,
    baptismal_dates integer,
    baptisms integer,
    books_of_mormon integer,
    with_member integer,
    follow_up_lessons integer,
    CONSTRAINT referral_archive_weeks_sunday_check CHECK ((EXTRACT(isodow FROM sunday) = (7)::numeric)),
    CONSTRAINT referral_archive_weeks_pkey PRIMARY KEY (batch_id, report_date, zone_name, area_name, source)
);
CREATE INDEX IF NOT EXISTS referral_archive_weeks_week_idx ON public.referral_archive_weeks USING btree (mission_id, sunday);
CREATE TABLE IF NOT EXISTS public.finding_rate_weeks (
    batch_id uuid NOT NULL REFERENCES public.roster_import_batches(id) ON DELETE CASCADE,
    mission_id bigint NOT NULL REFERENCES public.missions(id),
    sunday date NOT NULL,
    report_date date NOT NULL,
    zone_id bigint REFERENCES public.zones(id),
    zone_name text NOT NULL,
    is_mission boolean DEFAULT false NOT NULL,
    teaching_rate numeric(8,4),
    contact_rate numeric(8,4),
    CONSTRAINT finding_rate_weeks_contact_rate_check CHECK ((contact_rate >= (0)::numeric)),
    CONSTRAINT finding_rate_weeks_sunday_check CHECK ((EXTRACT(isodow FROM sunday) = (7)::numeric)),
    CONSTRAINT finding_rate_weeks_teaching_rate_check CHECK ((teaching_rate >= (0)::numeric)),
    CONSTRAINT finding_rate_weeks_pkey PRIMARY KEY (batch_id, report_date, zone_name)
);
CREATE INDEX IF NOT EXISTS finding_rate_weeks_week_idx ON public.finding_rate_weeks USING btree (mission_id, sunday);
ALTER TABLE public.referral_archive_weeks ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.finding_rate_weeks ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.referral_archive_weeks, public.finding_rate_weeks FROM PUBLIC, anon, authenticated, service_role;

-- Which upload counts for a week: all four kinds again.
CREATE OR REPLACE VIEW public.data_upload_week_batches AS
 WITH weeks AS (
         SELECT 'ZONE_HISTORY'::text AS kind,
            zone_history_weeks.mission_id,
            zone_history_weeks.sunday,
            zone_history_weeks.batch_id
           FROM zone_history_weeks
        UNION
         SELECT 'REFERRAL_ARCHIVE'::text AS text,
            referral_archive_weeks.mission_id,
            referral_archive_weeks.sunday,
            referral_archive_weeks.batch_id
           FROM referral_archive_weeks
        UNION
         SELECT 'RATES'::text AS text,
            finding_rate_weeks.mission_id,
            finding_rate_weeks.sunday,
            finding_rate_weeks.batch_id
           FROM finding_rate_weeks
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

-- The views as 045 made them.
CREATE VIEW dashboards.referral_archive_week AS
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
   FROM (((((public.referral_archive_weeks r
     JOIN public.data_upload_week_batches w ON (((w.kind = 'REFERRAL_ARCHIVE'::text) AND (w.batch_id = r.batch_id) AND (w.mission_id = r.mission_id) AND (w.sunday = r.sunday))))
     LEFT JOIN public.areas pa ON ((pa.id = r.area_id)))
     LEFT JOIN public.districts pd ON ((pd.id = pa.district_id)))
     LEFT JOIN public.zones pz ON ((pz.id = pd.zone_id)))
     LEFT JOIN public.zones fz ON ((fz.id = r.zone_id)));

CREATE VIEW dashboards.finding_rate_week AS
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
   FROM ((public.finding_rate_weeks r
     JOIN public.data_upload_week_batches w ON (((w.kind = 'RATES'::text) AND (w.batch_id = r.batch_id) AND (w.mission_id = r.mission_id) AND (w.sunday = r.sunday))))
     LEFT JOIN public.zones z ON ((z.id = r.zone_id)));

CREATE VIEW dashboards.findechristus_referrals_week AS
 WITH finding AS (
         SELECT f.sunday,
            f.mission_id,
            f.zone_id,
            f.zone,
            f.district_id,
            f.district,
            f.area_id,
            f.area,
            sum(f.people_found)::bigint AS referrals
           FROM dashboards.finding_area_week f
          WHERE f.findechristus AND f.people_found > 0
          GROUP BY f.sunday, f.mission_id, f.zone_id, f.zone, f.district_id, f.district, f.area_id, f.area
        ), first_found AS (
         SELECT finding_people_placed.mission_id,
            min(finding_people_placed.found_on) AS day
           FROM finding_people_placed
          GROUP BY finding_people_placed.mission_id
        ), first_whole_week AS (
         SELECT first_found.mission_id,
            first_found.day + (8 - EXTRACT(isodow FROM first_found.day)::integer) % 7 + 6 AS sunday
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
           FROM dashboards.referral_archive_week a
             LEFT JOIN first_whole_week s ON s.mission_id = a.mission_id
          WHERE s.sunday IS NULL OR a.sunday < s.sunday
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
           FROM finding f
             JOIN first_whole_week s ON s.mission_id = f.mission_id
          WHERE f.sunday >= s.sunday OR NOT (EXISTS ( SELECT 1
                   FROM archive a
                  WHERE a.mission_id = f.mission_id AND a.sunday = f.sunday))
        )
 SELECT x.sunday,
    ((x.sunday + '12:00:00'::time without time zone) AT TIME ZONE gfm_time_zone()) AS week,
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
;

-- Archetypal Health counts through the mixed view again.
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
           FROM dashboards.archetype_plan_rows() archetype_plan_rows(reporting_week_id, area_id, first_time_first_week_sacrament, member_meals_active, member_meals_less_active, member_meals_part_member, member_visits_active, member_visits_less_active, member_visits_part_member, member_referral_asks, lessons_asked_referral, youth_activities, service_hours, less_active_sacrament, new_members_on_plan, new_member_lessons, new_members_at_church)
        ), fc AS (
         SELECT f.sunday,
            f.area_id,
            sum(f.referrals) AS referrals
           FROM dashboards.findechristus_referrals_week f
          GROUP BY f.sunday, f.area_id
        ), fc_weeks AS (
         SELECT DISTINCT f.sunday
           FROM dashboards.findechristus_referrals_week f
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

REVOKE ALL ON dashboards.referral_archive_week, dashboards.findechristus_referrals_week, dashboards.finding_rate_week,
  dashboards.archetype_area_week FROM PUBLIC, anon, authenticated, service_role;
GRANT SELECT ON dashboards.referral_archive_week, dashboards.findechristus_referrals_week, dashboards.finding_rate_week,
  dashboards.archetype_area_week TO gfm_dashboard_reader;

DO $$
DECLARE
  found text;
BEGIN
  SELECT string_agg(v, ', ') INTO found
  FROM unnest(ARRAY['dashboards.referral_archive_week', 'dashboards.findechristus_referrals_week', 'dashboards.finding_rate_week',
                    'public.referral_archive_weeks', 'public.finding_rate_weeks']) v
  WHERE to_regclass(v) IS NULL;
  IF found IS NOT NULL THEN RAISE EXCEPTION 'Rollback check failed: missing: %', found; END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'roster_import_batches_kind_check'
                 AND pg_get_constraintdef(oid) LIKE '%REFERRAL_ARCHIVE%' AND pg_get_constraintdef(oid) LIKE '%RATES%') THEN
    RAISE EXCEPTION 'Rollback check failed: the batch kinds are not allowed.';
  END IF;
  IF NOT has_table_privilege('gfm_dashboard_reader', 'dashboards.finding_rate_week', 'SELECT')
     OR NOT has_table_privilege('gfm_dashboard_reader', 'dashboards.referral_archive_week', 'SELECT')
     OR NOT has_table_privilege('gfm_dashboard_reader', 'dashboards.findechristus_referrals_week', 'SELECT') THEN
    RAISE EXCEPTION 'Rollback check failed: gfm_dashboard_reader lost a view.';
  END IF;
END $$;

COMMIT;
