-- Data uploads in DA Management (round 7). Run on Beta only, as supabase_admin.
--
-- Why: the owner wants to put in the numbers the portal does not collect itself:
--   1. Area data for peer groups (archetypes): population, size in km2, urban type, assignment type and free
--      extra attributes per area. Density is worked out (population / km2), never typed.
--   2. The Church's finding export (MissionFindingDetail): per person found, the finding category and source, the
--      area, and the dates of the first finding, referral, contact attempt, successful contact, lessons, new person
--      being taught, baptismal date set, first sacrament meeting and confirmation. NO names and NO Church person id:
--      a re-upload recognises a person by person_key, an HMAC-SHA256 code of the person id made with a secret that
--      only DA Management knows (PERSON_KEY_SECRET). The uploaded file itself is never kept.
--   3. Zone history going back years (the "Data for Data Studio" sheet: goal and result per zone, week and key
--      indicator), the FindeChristus referral archive (the "FC Data Archives" sheet, since 2022) and the teaching and
--      contact rates per zone and week.
--   4. Baptism history as counts per week, zone or area, ward and finding source (the "Vollzogen" and "New Member
--      Database Raw" sheets); no names.
--
-- How an upload is stored: every upload is one batch in public.roster_import_batches (the DA Management Import
-- history), so it is listed there and can be undone there.
--   * Area data: one row per area in area_profiles. Uploads and saves of the area table record their changed rows in
--     roster_import_changes like every other import, so Undo checks for later edits and restores the rows.
--   * Weekly data (zone history, referral archive, rates, baptism history): every upload keeps its own rows. For each
--     week, the newest applied upload that has that week counts; older uploads of the same week are kept but not
--     counted. So uploading the same sheet again never counts anything twice, and Undo simply removes the batch's
--     rows (the older upload of those weeks counts again).
--   * Finding export: a re-upload stores only the people who are new or whose dates, area or source changed; the
--     newest stored version of each person counts. Undo removes the batch's rows; only the newest finding upload can
--     be undone (DA Management says so), because a newer upload skipped the people that had not changed.
--   * Names in a file that are not portal names (old zones and areas, other spellings) are matched once by a manager
--     and remembered in data_name_matches. A name can also be kept as a historical name (no portal zone or area).
--
-- Who can read it: the tables are for DA Management only (row level security on, no policy; no rights for PUBLIC,
-- anon, authenticated or service_role). Dashboards read the new views in the dashboards schema through
-- gfm_dashboard_reader (as in 018 and 025): counts and org units only, no person code, no names.
--   dashboards.area_profile                 per area: population, km2, density, urban type, assignment type, extra
--   dashboards.finding_area_week            per week, area, finding category and source: how many people were found,
--                                            referred, tried to contact, reached, taught ... that week
--   dashboards.finding_cohort_week          per week found, area, category and source: of the people found that week,
--                                            how many were reached, taught, got a baptismal date, came to church ...
--   dashboards.findechristus_referrals_week FindeChristus referrals per area and week: category Media without
--                                            "Facebook - Personal Profile" from the finding export, and the referral
--                                            archive for the weeks before the export's first whole week
--   dashboards.referral_archive_week        the FindeChristus referral archive per week, area and source
--   dashboards.finding_rate_week            teaching and contact rates per week and zone (zone 'Mission' = mission)
--   dashboards.zone_history_week            goal and result per week, zone and key indicator: the portal's own
--                                            numbers where the portal has weekly plans for that zone and week,
--                                            otherwise the uploaded history (never both)
--   dashboards.mission_history_week         zone_history_week added up per week
--   dashboards.baptism_history_week         baptisms and confirmations per week, zone, area, ward and finding source
-- Weeks run Monday to Sunday and are named by their Sunday (column sunday), like the portal's reporting weeks.
-- The history views use the goal columns of dashboards.kpi_zone_week: <kpi>_goal is set that week for the next week
-- (the owner's sheet has the same), <kpi>_previous_goal is the goal the week is measured against.
-- A FindeChristus report (referral archive, rates) counts for the week it shows, one report per week: the last week
-- that ended at least three days before the report. Sunday 27 and Monday 28 Sep 2026 show Monday 14 to Sunday 20
-- Sep (the owner's FC Data Studio rule); a Saturday report shows the week just ended. DA Management works the week
-- out (data_files.week_reported_on); report_date keeps the date as written.
--
-- Apply (back up Beta first; after 018, 025 and 032). Join the lines with plain line feeds:
--   (Get-Content portal-api/migrations/033_data_uploads.sql) -join "`n" |
--     docker exec -i gfm-beta-supabase-db-1 psql -U supabase_admin -d postgres -v ON_ERROR_STOP=1
-- Then run 019 again as a check (it must end with COMMIT).
-- Safe to run again: IF NOT EXISTS, CREATE OR REPLACE VIEW, GRANT and REVOKE, then a check that stops on any problem.
-- Rollback: 033_data_uploads_rollback.sql (it removes the uploaded data too; roll back 034 first if it is applied).
BEGIN;
SET LOCAL lock_timeout = '10s';

DO $$
BEGIN
  IF session_user NOT IN ('supabase_admin', 'postgres') THEN
    RAISE EXCEPTION 'Run this file as supabase_admin (see its header), not as %.', session_user;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'gfm_dashboard_reader')
     OR to_regclass('dashboards.kpi_zone_week') IS NULL THEN
    RAISE EXCEPTION 'Apply 018_dashboard_reporting.sql first.';
  END IF;
  IF to_regclass('public.roster_import_batches') IS NULL THEN
    RAISE EXCEPTION 'Apply the DA Management migrations (roster-importer/migrations) first.';
  END IF;
END $$;

-- Import history gets the new kinds of upload. The constraint belongs to supabase_admin's table, so this runs
-- before the switch to postgres below.
ALTER TABLE public.roster_import_batches DROP CONSTRAINT IF EXISTS roster_import_batches_kind_check;
ALTER TABLE public.roster_import_batches ADD CONSTRAINT roster_import_batches_kind_check CHECK (kind IN (
  'TRANSFER', 'HISTORICAL', 'ACCOUNT',
  'AREA_DATA', 'FINDING', 'ZONE_HISTORY', 'REFERRAL_ARCHIVE', 'RATES', 'BAPTISMS'));

-- Everything below belongs to postgres, like the views of 018 and 025 (DA Management connects as postgres).
SET LOCAL ROLE postgres;

-- 1. Area data (peer groups). One row per area; empty = not known yet.
CREATE TABLE IF NOT EXISTS public.area_profiles (
  area_id bigint PRIMARY KEY REFERENCES public.areas(id) ON DELETE CASCADE,
  population integer CHECK (population >= 0),
  size_km2 numeric(12,3) CHECK (size_km2 > 0),
  urban_type text CHECK (length(urban_type) <= 60),
  assignment_type text CHECK (length(assignment_type) <= 60),
  extra jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(extra) = 'object'),
  updated_at timestamptz NOT NULL DEFAULT now(),
  updated_by text
);
COMMENT ON TABLE public.area_profiles IS 'Area data for peer groups, from DA Management > Data uploads > Area data. extra = free attributes {"name": "value"}.';

-- Remembered name matches: a zone or area name from an uploaded file -> a portal zone or area, or "historical"
-- (an old zone or area that is not in the portal; the name is kept as written).
CREATE TABLE IF NOT EXISTS public.data_name_matches (
  id bigint GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
  mission_id bigint NOT NULL REFERENCES public.missions(id),
  level text NOT NULL CHECK (level IN ('zone', 'area')),
  source_key text NOT NULL,
  source_name text NOT NULL,
  zone_id bigint REFERENCES public.zones(id),
  area_id bigint REFERENCES public.areas(id),
  historical boolean NOT NULL DEFAULT false,
  confirmed_by text,
  confirmed_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (mission_id, level, source_key),
  CHECK (CASE WHEN historical THEN zone_id IS NULL AND area_id IS NULL
              WHEN level = 'zone' THEN zone_id IS NOT NULL AND area_id IS NULL
              ELSE area_id IS NOT NULL AND zone_id IS NULL END)
);
COMMENT ON TABLE public.data_name_matches IS 'Zone and area names from uploaded files matched to the portal by a manager. source_key = the name folded (lower case, no accents or punctuation).';

-- 2. The finding export: one row per person and upload, only for people new or changed in that upload.
CREATE TABLE IF NOT EXISTS public.finding_people (
  batch_id uuid NOT NULL REFERENCES public.roster_import_batches(id) ON DELETE CASCADE,
  mission_id bigint NOT NULL REFERENCES public.missions(id),
  person_key text NOT NULL CHECK (person_key ~ '^[0-9a-f]{32}$'),
  zone_id bigint REFERENCES public.zones(id),
  area_id bigint REFERENCES public.areas(id),
  zone_name text NOT NULL DEFAULT '',
  district_name text NOT NULL DEFAULT '',
  area_name text NOT NULL DEFAULT '',
  finding_category text NOT NULL,
  finding_source text NOT NULL,
  found_on date,
  referral_on date,
  contact_attempt_on date,
  contacted_on date,
  first_lesson_on date,
  second_lesson_on date,
  taught_on date,
  baptismal_date_set_on date,
  first_sacrament_on date,
  confirmed_on date,
  PRIMARY KEY (batch_id, person_key)
);
CREATE INDEX IF NOT EXISTS finding_people_person_idx ON public.finding_people (mission_id, person_key);
COMMENT ON TABLE public.finding_people IS 'Finding export rows without names. person_key = HMAC-SHA256 of the Church person id with a secret kept outside the database (32 hex characters). Names in the file: org units only.';

-- 3. Zone history: goal and result per week, zone and key indicator. <kpi>_goal = the goal set that Sunday for the
--    NEXT week, as in the owner's sheet and in the portal's own kpi views (their <kpi>_goal).
CREATE TABLE IF NOT EXISTS public.zone_history_weeks (
  batch_id uuid NOT NULL REFERENCES public.roster_import_batches(id) ON DELETE CASCADE,
  mission_id bigint NOT NULL REFERENCES public.missions(id),
  sunday date NOT NULL CHECK (extract(isodow FROM sunday) = 7),
  zone_id bigint REFERENCES public.zones(id),
  zone_name text NOT NULL,
  friends_found_goal integer, friends_found_actual integer,
  members_at_lessons_goal integer, members_at_lessons_actual integer,
  sacrament_attendance_goal integer, sacrament_attendance_actual integer,
  baptismal_dates_goal integer, baptismal_dates_actual integer,
  baptisms_confirmations_goal integer, baptisms_confirmations_actual integer,
  new_member_sacrament_goal integer, new_member_sacrament_actual integer,
  follow_up_lessons_actual integer,
  first_time_sacrament_actual integer,
  companionships integer,
  PRIMARY KEY (batch_id, sunday, zone_name)
);
CREATE INDEX IF NOT EXISTS zone_history_weeks_week_idx ON public.zone_history_weeks (mission_id, sunday);

-- The FindeChristus referral archive, added up per report date, zone, area and source (no referral numbers).
CREATE TABLE IF NOT EXISTS public.referral_archive_weeks (
  batch_id uuid NOT NULL REFERENCES public.roster_import_batches(id) ON DELETE CASCADE,
  mission_id bigint NOT NULL REFERENCES public.missions(id),
  sunday date NOT NULL CHECK (extract(isodow FROM sunday) = 7),
  report_date date NOT NULL,
  zone_id bigint REFERENCES public.zones(id),
  area_id bigint REFERENCES public.areas(id),
  zone_name text NOT NULL DEFAULT '',
  area_name text NOT NULL DEFAULT '',
  source text NOT NULL DEFAULT '',
  referrals_received integer, referrals_contacted integer, friends_made integer, lessons_taught integer,
  church_attendance integer, baptismal_dates integer, baptisms integer, books_of_mormon integer,
  with_member integer, follow_up_lessons integer,
  PRIMARY KEY (batch_id, report_date, zone_name, area_name, source)
);
CREATE INDEX IF NOT EXISTS referral_archive_weeks_week_idx ON public.referral_archive_weeks (mission_id, sunday);

-- Teaching and contact rates per week and zone, as fractions (0.25 = 25 %). zone_name 'Mission' = the mission.
CREATE TABLE IF NOT EXISTS public.finding_rate_weeks (
  batch_id uuid NOT NULL REFERENCES public.roster_import_batches(id) ON DELETE CASCADE,
  mission_id bigint NOT NULL REFERENCES public.missions(id),
  sunday date NOT NULL CHECK (extract(isodow FROM sunday) = 7),
  report_date date NOT NULL,
  zone_id bigint REFERENCES public.zones(id),
  zone_name text NOT NULL,
  is_mission boolean NOT NULL DEFAULT false,
  teaching_rate numeric(8,4) CHECK (teaching_rate >= 0),
  contact_rate numeric(8,4) CHECK (contact_rate >= 0),
  PRIMARY KEY (batch_id, report_date, zone_name)
);
CREATE INDEX IF NOT EXISTS finding_rate_weeks_week_idx ON public.finding_rate_weeks (mission_id, sunday);

-- 4. Baptism history: counts only.
CREATE TABLE IF NOT EXISTS public.baptism_history_weeks (
  batch_id uuid NOT NULL REFERENCES public.roster_import_batches(id) ON DELETE CASCADE,
  mission_id bigint NOT NULL REFERENCES public.missions(id),
  sunday date NOT NULL CHECK (extract(isodow FROM sunday) = 7),
  zone_id bigint REFERENCES public.zones(id),
  area_id bigint REFERENCES public.areas(id),
  zone_name text NOT NULL DEFAULT '',
  area_name text NOT NULL DEFAULT '',
  ward text NOT NULL DEFAULT '',
  finding_source text NOT NULL DEFAULT '',
  baptisms integer NOT NULL DEFAULT 0 CHECK (baptisms >= 0),
  confirmations integer NOT NULL DEFAULT 0 CHECK (confirmations >= 0),
  PRIMARY KEY (batch_id, sunday, zone_name, area_name, ward, finding_source)
);
CREATE INDEX IF NOT EXISTS baptism_history_weeks_week_idx ON public.baptism_history_weeks (mission_id, sunday);

-- The tables are for DA Management only.
ALTER TABLE public.area_profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.data_name_matches ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.finding_people ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.zone_history_weeks ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.referral_archive_weeks ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.finding_rate_weeks ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.baptism_history_weeks ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.area_profiles, public.data_name_matches, public.finding_people, public.zone_history_weeks,
  public.referral_archive_weeks, public.finding_rate_weeks, public.baptism_history_weeks
  FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON SEQUENCE public.data_name_matches_id_seq FROM PUBLIC, anon, authenticated, service_role;

-- Helper views (not for dashboards): which stored rows count. They are in public, closed like the tables.
-- Finding: the newest stored version of each person.
CREATE OR REPLACE VIEW public.finding_people_latest AS
  SELECT DISTINCT ON (p.mission_id, p.person_key) p.*
  FROM public.finding_people p
  JOIN public.roster_import_batches b ON b.id = p.batch_id AND b.status = 'APPLIED'
  ORDER BY p.mission_id, p.person_key, b.created_at DESC, b.id DESC;

-- Weekly uploads: for each kind, mission and week, the newest applied batch that has rows for that week.
CREATE OR REPLACE VIEW public.data_upload_week_batches AS
  WITH weeks AS (
    SELECT 'ZONE_HISTORY' AS kind, mission_id, sunday, batch_id FROM public.zone_history_weeks
    UNION SELECT 'REFERRAL_ARCHIVE', mission_id, sunday, batch_id FROM public.referral_archive_weeks
    UNION SELECT 'RATES', mission_id, sunday, batch_id FROM public.finding_rate_weeks
    UNION SELECT 'BAPTISMS', mission_id, sunday, batch_id FROM public.baptism_history_weeks
  )
  SELECT DISTINCT ON (w.kind, w.mission_id, w.sunday) w.kind, w.mission_id, w.sunday, w.batch_id
  FROM weeks w
  JOIN public.roster_import_batches b ON b.id = w.batch_id AND b.status = 'APPLIED'
  ORDER BY w.kind, w.mission_id, w.sunday, b.created_at DESC, b.id DESC;

REVOKE ALL ON public.finding_people_latest, public.data_upload_week_batches
  FROM PUBLIC, anon, authenticated, service_role;

-- Dashboards views. Portal names win: a matched row shows today's portal zone, district and area; a historical
-- row shows the name from the file.

CREATE OR REPLACE VIEW dashboards.area_profile AS
  SELECT z.mission_id, z.id AS zone_id, z.name AS zone, d.id AS district_id, d.name AS district,
         a.id AS area_id, a.name AS area, a.active,
         p.population, p.size_km2,
         CASE WHEN p.population IS NOT NULL AND p.size_km2 > 0 THEN round(p.population / p.size_km2, 1) END AS density_per_km2,
         p.urban_type, p.assignment_type, coalesce(p.extra, '{}'::jsonb) AS extra, p.updated_at
  FROM public.areas a
  JOIN public.districts d ON d.id = a.district_id
  JOIN public.zones z ON z.id = d.zone_id
  LEFT JOIN public.area_profiles p ON p.area_id = a.id
  WHERE a.active OR p.area_id IS NOT NULL;
COMMENT ON VIEW dashboards.area_profile IS 'Area data for peer groups: every active area (and older areas with data). density_per_km2 = population / size_km2. extra = free attributes typed in DA Management.';

-- The finding export, one row per person (newest version), with portal names. Not readable by dashboards.
CREATE OR REPLACE VIEW public.finding_people_placed AS
  SELECT p.mission_id,
         coalesce(pz.id, p.zone_id) AS zone_id, coalesce(pz.name, fz.name, p.zone_name) AS zone,
         pd.id AS district_id, coalesce(pd.name, p.district_name) AS district,
         p.area_id, coalesce(pa.name, p.area_name) AS area,
         p.finding_category, p.finding_source,
         (p.finding_category = 'Media' AND p.finding_source <> 'Facebook - Personal Profile') AS findechristus,
         p.found_on, p.referral_on, p.contact_attempt_on, p.contacted_on, p.first_lesson_on, p.second_lesson_on,
         p.taught_on, p.baptismal_date_set_on, p.first_sacrament_on, p.confirmed_on
  FROM public.finding_people_latest p
  LEFT JOIN public.areas pa ON pa.id = p.area_id
  LEFT JOIN public.districts pd ON pd.id = pa.district_id
  LEFT JOIN public.zones pz ON pz.id = pd.zone_id
  LEFT JOIN public.zones fz ON fz.id = p.zone_id;
REVOKE ALL ON public.finding_people_placed FROM PUBLIC, anon, authenticated, service_role;

-- How many things happened in each Monday-Sunday week (a person counts in the week of each of their dates).
CREATE OR REPLACE VIEW dashboards.finding_area_week AS
  WITH events AS (
    SELECT p.mission_id, p.zone_id, p.zone, p.district_id, p.district, p.area_id, p.area,
           p.finding_category, p.finding_source, p.findechristus, e.what,
           e.day + ((7 - extract(isodow FROM e.day)::integer) % 7) AS sunday
    FROM public.finding_people_placed p
    CROSS JOIN LATERAL (VALUES ('found', p.found_on), ('referral', p.referral_on),
                               ('contact_attempt', p.contact_attempt_on), ('contacted', p.contacted_on),
                               ('first_lesson', p.first_lesson_on), ('second_lesson', p.second_lesson_on),
                               ('taught', p.taught_on), ('baptismal_date', p.baptismal_date_set_on),
                               ('first_sacrament', p.first_sacrament_on), ('confirmed', p.confirmed_on)) e(what, day)
    WHERE e.day IS NOT NULL
  )
  SELECT e.sunday, (e.sunday + time '12:00') AT TIME ZONE 'Europe/Berlin' AS week,
         e.mission_id, e.zone_id, e.zone, e.district_id, e.district, e.area_id, e.area,
         e.finding_category, e.finding_source, e.findechristus,
         count(*) FILTER (WHERE e.what = 'found') AS people_found,
         count(*) FILTER (WHERE e.what = 'referral') AS referrals,
         count(*) FILTER (WHERE e.what = 'contact_attempt') AS contact_attempts,
         count(*) FILTER (WHERE e.what = 'contacted') AS people_reached,
         count(*) FILTER (WHERE e.what = 'first_lesson') AS first_lessons,
         count(*) FILTER (WHERE e.what = 'second_lesson') AS second_lessons,
         count(*) FILTER (WHERE e.what = 'taught') AS new_people_being_taught,
         count(*) FILTER (WHERE e.what = 'baptismal_date') AS baptismal_dates_set,
         count(*) FILTER (WHERE e.what = 'first_sacrament') AS first_sacrament_meetings,
         count(*) FILTER (WHERE e.what = 'confirmed') AS confirmations
  FROM events e
  GROUP BY e.sunday, e.mission_id, e.zone_id, e.zone, e.district_id, e.district, e.area_id, e.area,
           e.finding_category, e.finding_source, e.findechristus;
COMMENT ON VIEW dashboards.finding_area_week IS 'Finding export per Monday-Sunday week (sunday = its Sunday), area, finding category and source: how many people had each first event that week. findechristus = category Media without Facebook - Personal Profile. Counts only.';

-- Of the people found in each week, how many have come how far (by today).
CREATE OR REPLACE VIEW dashboards.finding_cohort_week AS
  SELECT p.found_on + ((7 - extract(isodow FROM p.found_on)::integer) % 7) AS sunday,
         (p.found_on + ((7 - extract(isodow FROM p.found_on)::integer) % 7) + time '12:00') AT TIME ZONE 'Europe/Berlin' AS week,
         p.mission_id, p.zone_id, p.zone, p.district_id, p.district, p.area_id, p.area,
         p.finding_category, p.finding_source, p.findechristus,
         count(*) AS people_found,
         count(p.contact_attempt_on) AS contact_attempted,
         count(p.contacted_on) AS reached,
         count(p.first_lesson_on) AS taught,
         count(p.taught_on) AS new_people_being_taught,
         count(p.baptismal_date_set_on) AS with_baptismal_date,
         count(p.first_sacrament_on) AS at_sacrament_meeting,
         count(p.confirmed_on) AS confirmed
  FROM public.finding_people_placed p
  WHERE p.found_on IS NOT NULL
  GROUP BY 1, 2, p.mission_id, p.zone_id, p.zone, p.district_id, p.district, p.area_id, p.area,
           p.finding_category, p.finding_source, p.findechristus;
COMMENT ON VIEW dashboards.finding_cohort_week IS 'People found per Monday-Sunday week, area, category and source, and how many of them were reached, taught (a first lesson), became new people being taught, got a baptismal date, came to sacrament meeting and were confirmed. contact rate = reached / people_found; teaching rate = taught / people_found. Counts only.';

CREATE OR REPLACE VIEW dashboards.referral_archive_week AS
  SELECT r.sunday, (r.sunday + time '12:00') AT TIME ZONE 'Europe/Berlin' AS week, r.report_date, r.mission_id,
         coalesce(pz.id, fz.id) AS zone_id, coalesce(pz.name, fz.name, nullif(r.zone_name, '')) AS zone,
         pd.id AS district_id, pd.name AS district,
         r.area_id, coalesce(pa.name, nullif(r.area_name, '')) AS area, r.source,
         r.referrals_received, r.referrals_contacted, r.friends_made, r.lessons_taught, r.church_attendance,
         r.baptismal_dates, r.baptisms, r.books_of_mormon, r.with_member, r.follow_up_lessons
  FROM public.referral_archive_weeks r
  JOIN public.data_upload_week_batches w ON w.kind = 'REFERRAL_ARCHIVE' AND w.batch_id = r.batch_id
   AND w.mission_id = r.mission_id AND w.sunday = r.sunday
  LEFT JOIN public.areas pa ON pa.id = r.area_id
  LEFT JOIN public.districts pd ON pd.id = pa.district_id
  LEFT JOIN public.zones pz ON pz.id = pd.zone_id
  LEFT JOIN public.zones fz ON fz.id = r.zone_id;
COMMENT ON VIEW dashboards.referral_archive_week IS 'The FindeChristus referral archive (FC Data Archives) per week, area and source; the newest upload of each week counts, one report per week. sunday = the week the report shows: the last week that ended at least three days before the report (Sunday 27 and Monday 28 Sep show 14-20 Sep, the FC Data Studio rule; a Saturday report shows the week just ended); report_date = the date in the sheet.';

-- The finding export takes over from its first WHOLE week: the owner's export starts on Wednesday 24 Sep 2025, so
-- the week of 22-28 Sep 2025 misses its Monday and Tuesday. That week and every week before it come from the
-- referral archive. The export's first part-week is used only when the archive does not have that week.
CREATE OR REPLACE VIEW dashboards.findechristus_referrals_week AS
  WITH finding AS (
    SELECT f.sunday, f.mission_id, f.zone_id, f.zone, f.district_id, f.district, f.area_id, f.area,
           sum(f.people_found)::bigint AS referrals
    FROM dashboards.finding_area_week f
    WHERE f.findechristus AND f.people_found > 0
    GROUP BY f.sunday, f.mission_id, f.zone_id, f.zone, f.district_id, f.district, f.area_id, f.area
  ), first_found AS (
    SELECT mission_id, min(found_on) AS day FROM public.finding_people_placed GROUP BY mission_id
  ), first_whole_week AS (  -- the Sunday of the first week whose Monday is on or after the first finding date
    SELECT mission_id, day + ((8 - extract(isodow FROM day)::integer) % 7) + 6 AS sunday FROM first_found
  ), archive AS (
    SELECT a.sunday, a.mission_id, a.zone_id, a.zone, a.district_id, a.district, a.area_id, a.area,
           sum(a.referrals_received)::bigint AS referrals
    FROM dashboards.referral_archive_week a
    LEFT JOIN first_whole_week s ON s.mission_id = a.mission_id
    WHERE s.sunday IS NULL OR a.sunday < s.sunday
    GROUP BY a.sunday, a.mission_id, a.zone_id, a.zone, a.district_id, a.district, a.area_id, a.area
  ), finding_used AS (
    SELECT f.*
    FROM finding f
    JOIN first_whole_week s ON s.mission_id = f.mission_id
    WHERE f.sunday >= s.sunday
       OR NOT EXISTS (SELECT 1 FROM archive a WHERE a.mission_id = f.mission_id AND a.sunday = f.sunday)
  )
  SELECT x.sunday, (x.sunday + time '12:00') AT TIME ZONE 'Europe/Berlin' AS week, x.mission_id, x.zone_id, x.zone,
         x.district_id, x.district, x.area_id, x.area, x.referrals, x.data_source
  FROM (SELECT finding_used.*, 'finding export' AS data_source FROM finding_used
        UNION ALL SELECT archive.*, 'referral archive' FROM archive) x;
COMMENT ON VIEW dashboards.findechristus_referrals_week IS 'FindeChristus referrals per Monday-Sunday week and area: from the finding export (category Media without Facebook - Personal Profile, by first finding date) from its first whole week on, and from the referral archive for the weeks before (the export''s first part-week only when the archive lacks that week). data_source says which.';

CREATE OR REPLACE VIEW dashboards.finding_rate_week AS
  SELECT r.sunday, (r.sunday + time '12:00') AT TIME ZONE 'Europe/Berlin' AS week, r.report_date, r.mission_id,
         r.is_mission, CASE WHEN r.is_mission THEN NULL ELSE coalesce(z.id, r.zone_id) END AS zone_id,
         CASE WHEN r.is_mission THEN 'Mission' ELSE coalesce(z.name, r.zone_name) END AS zone,
         r.teaching_rate, r.contact_rate
  FROM public.finding_rate_weeks r
  JOIN public.data_upload_week_batches w ON w.kind = 'RATES' AND w.batch_id = r.batch_id
   AND w.mission_id = r.mission_id AND w.sunday = r.sunday
  LEFT JOIN public.zones z ON z.id = r.zone_id;
COMMENT ON VIEW dashboards.finding_rate_week IS 'Uploaded teaching and contact rates (fractions: 0.25 = 25 %) per week and zone; is_mission = the mission row. sunday = the week the report shows (as in referral_archive_week); report_date = the date in the sheet. For weeks of the finding export, finding_cohort_week gives the counts behind such rates.';

-- The same columns as dashboards.kpi_zone_week: <kpi>_actual, <kpi>_goal (set that week for the next week) and
-- <kpi>_previous_goal (the goal this week is measured against). For uploaded weeks the previous goal is the goal of
-- the same zone's uploaded row one week earlier.
CREATE OR REPLACE VIEW dashboards.zone_history_week AS
  WITH portal AS (
    SELECT k.sunday, k.mission_id, k.zone_id, k.zone,
           k.friends_found_actual, k.friends_found_goal, k.friends_found_previous_goal,
           k.members_at_lessons_actual, k.members_at_lessons_goal, k.members_at_lessons_previous_goal,
           k.sacrament_attendance_actual, k.sacrament_attendance_goal, k.sacrament_attendance_previous_goal,
           k.baptismal_dates_actual, k.baptismal_dates_goal, k.baptismal_dates_previous_goal,
           k.baptisms_confirmations_actual, k.baptisms_confirmations_goal, k.baptisms_confirmations_previous_goal,
           k.new_member_sacrament_actual, k.new_member_sacrament_goal, k.new_member_sacrament_previous_goal,
           k.follow_up_lessons_actual, k.first_time_sacrament_actual,
           k.areas_reporting AS companionships
    FROM dashboards.kpi_zone_week k
    WHERE k.reports > 0
  ), counted AS (  -- the uploaded rows that count: the newest upload of each week
    SELECT u.*
    FROM public.zone_history_weeks u
    JOIN public.data_upload_week_batches w ON w.kind = 'ZONE_HISTORY' AND w.batch_id = u.batch_id
     AND w.mission_id = u.mission_id AND w.sunday = u.sunday
  ), uploaded AS (
    SELECT u.sunday, u.mission_id, z.id AS zone_id, coalesce(z.name, u.zone_name) AS zone,
           u.friends_found_actual, u.friends_found_goal, b.friends_found_goal AS friends_found_previous_goal,
           u.members_at_lessons_actual, u.members_at_lessons_goal, b.members_at_lessons_goal AS members_at_lessons_previous_goal,
           u.sacrament_attendance_actual, u.sacrament_attendance_goal, b.sacrament_attendance_goal AS sacrament_attendance_previous_goal,
           u.baptismal_dates_actual, u.baptismal_dates_goal, b.baptismal_dates_goal AS baptismal_dates_previous_goal,
           u.baptisms_confirmations_actual, u.baptisms_confirmations_goal,
           b.baptisms_confirmations_goal AS baptisms_confirmations_previous_goal,
           u.new_member_sacrament_actual, u.new_member_sacrament_goal,
           b.new_member_sacrament_goal AS new_member_sacrament_previous_goal,
           u.follow_up_lessons_actual, u.first_time_sacrament_actual, u.companionships
    FROM counted u
    LEFT JOIN public.zones z ON z.id = u.zone_id
    -- The week before, same zone: the portal zone when there is one, else the historical name as written.
    LEFT JOIN counted b ON b.mission_id = u.mission_id AND b.sunday = u.sunday - 7
     AND CASE WHEN u.zone_id IS NULL THEN b.zone_id IS NULL AND lower(b.zone_name) = lower(u.zone_name)
              ELSE b.zone_id = u.zone_id END
    WHERE NOT EXISTS (SELECT 1 FROM portal p
                      WHERE p.mission_id = u.mission_id AND p.sunday = u.sunday AND p.zone_id = u.zone_id)
  )
  SELECT x.sunday, (x.sunday + time '12:00') AT TIME ZONE 'Europe/Berlin' AS week, x.mission_id, x.zone_id, x.zone,
         x.data_source,
         x.friends_found_actual, x.friends_found_goal, x.friends_found_previous_goal,
         x.members_at_lessons_actual, x.members_at_lessons_goal, x.members_at_lessons_previous_goal,
         x.sacrament_attendance_actual, x.sacrament_attendance_goal, x.sacrament_attendance_previous_goal,
         x.baptismal_dates_actual, x.baptismal_dates_goal, x.baptismal_dates_previous_goal,
         x.baptisms_confirmations_actual, x.baptisms_confirmations_goal, x.baptisms_confirmations_previous_goal,
         x.new_member_sacrament_actual, x.new_member_sacrament_goal, x.new_member_sacrament_previous_goal,
         x.follow_up_lessons_actual, x.first_time_sacrament_actual, x.companionships
  FROM (SELECT portal.*, 'portal' AS data_source FROM portal
        UNION ALL SELECT uploaded.*, 'upload' FROM uploaded) x;
COMMENT ON VIEW dashboards.zone_history_week IS 'Goal and result per Monday-Sunday week (sunday), zone and key indicator, with the columns of kpi_zone_week: <kpi>_goal = set that week for the next week, <kpi>_previous_goal = the goal the week is measured against. data_source = portal where the portal has weekly plans for that zone and week (its numbers win), otherwise upload (newest upload of that week). companionships: uploaded count, or areas reporting in the portal.';

CREATE OR REPLACE VIEW dashboards.mission_history_week AS
  SELECT h.sunday, min(h.week) AS week, h.mission_id,
         string_agg(DISTINCT h.data_source, ', ' ORDER BY h.data_source) AS data_sources,
         count(*) AS zones,
         sum(h.friends_found_actual)::bigint AS friends_found_actual,
         sum(h.friends_found_goal)::bigint AS friends_found_goal,
         sum(h.friends_found_previous_goal)::bigint AS friends_found_previous_goal,
         sum(h.members_at_lessons_actual)::bigint AS members_at_lessons_actual,
         sum(h.members_at_lessons_goal)::bigint AS members_at_lessons_goal,
         sum(h.members_at_lessons_previous_goal)::bigint AS members_at_lessons_previous_goal,
         sum(h.sacrament_attendance_actual)::bigint AS sacrament_attendance_actual,
         sum(h.sacrament_attendance_goal)::bigint AS sacrament_attendance_goal,
         sum(h.sacrament_attendance_previous_goal)::bigint AS sacrament_attendance_previous_goal,
         sum(h.baptismal_dates_actual)::bigint AS baptismal_dates_actual,
         sum(h.baptismal_dates_goal)::bigint AS baptismal_dates_goal,
         sum(h.baptismal_dates_previous_goal)::bigint AS baptismal_dates_previous_goal,
         sum(h.baptisms_confirmations_actual)::bigint AS baptisms_confirmations_actual,
         sum(h.baptisms_confirmations_goal)::bigint AS baptisms_confirmations_goal,
         sum(h.baptisms_confirmations_previous_goal)::bigint AS baptisms_confirmations_previous_goal,
         sum(h.new_member_sacrament_actual)::bigint AS new_member_sacrament_actual,
         sum(h.new_member_sacrament_goal)::bigint AS new_member_sacrament_goal,
         sum(h.new_member_sacrament_previous_goal)::bigint AS new_member_sacrament_previous_goal,
         sum(h.follow_up_lessons_actual)::bigint AS follow_up_lessons_actual,
         sum(h.first_time_sacrament_actual)::bigint AS first_time_sacrament_actual,
         sum(h.companionships)::bigint AS companionships
  FROM dashboards.zone_history_week h
  GROUP BY h.sunday, h.mission_id;
COMMENT ON VIEW dashboards.mission_history_week IS 'zone_history_week added up per week: the mission''s goals and results going back as far as the uploads go (same goal columns as zone_history_week).';

CREATE OR REPLACE VIEW dashboards.baptism_history_week AS
  SELECT b.sunday, (b.sunday + time '12:00') AT TIME ZONE 'Europe/Berlin' AS week, b.mission_id,
         coalesce(pz.id, fz.id) AS zone_id, coalesce(pz.name, fz.name, nullif(b.zone_name, '')) AS zone,
         pd.id AS district_id, pd.name AS district,
         b.area_id, coalesce(pa.name, nullif(b.area_name, '')) AS area,
         nullif(b.ward, '') AS ward, nullif(b.finding_source, '') AS finding_source, b.baptisms, b.confirmations
  FROM public.baptism_history_weeks b
  JOIN public.data_upload_week_batches w ON w.kind = 'BAPTISMS' AND w.batch_id = b.batch_id
   AND w.mission_id = b.mission_id AND w.sunday = b.sunday
  LEFT JOIN public.areas pa ON pa.id = b.area_id
  LEFT JOIN public.districts pd ON pd.id = pa.district_id
  LEFT JOIN public.zones pz ON pz.id = pd.zone_id
  LEFT JOIN public.zones fz ON fz.id = b.zone_id;
COMMENT ON VIEW dashboards.baptism_history_week IS 'Baptisms (week of the baptism) and confirmations (week of the confirmation) per Monday-Sunday week, zone, area, ward and finding source; the newest upload of each week counts. Counts only.';

-- Rights: the reader gets the dashboards views, nobody else gets anything new.
REVOKE ALL ON dashboards.area_profile, dashboards.finding_area_week, dashboards.finding_cohort_week,
  dashboards.referral_archive_week, dashboards.findechristus_referrals_week, dashboards.finding_rate_week,
  dashboards.zone_history_week, dashboards.mission_history_week, dashboards.baptism_history_week
  FROM PUBLIC, anon, authenticated, service_role;
GRANT SELECT ON dashboards.area_profile, dashboards.finding_area_week, dashboards.finding_cohort_week,
  dashboards.referral_archive_week, dashboards.findechristus_referrals_week, dashboards.finding_rate_week,
  dashboards.zone_history_week, dashboards.mission_history_week, dashboards.baptism_history_week
  TO gfm_dashboard_reader;

-- Check: owners, rights, and no personal data in what dashboards can read.
DO $$
DECLARE
  readable text[] := ARRAY['dashboards.area_profile', 'dashboards.finding_area_week', 'dashboards.finding_cohort_week',
                           'dashboards.referral_archive_week', 'dashboards.findechristus_referrals_week',
                           'dashboards.finding_rate_week', 'dashboards.zone_history_week',
                           'dashboards.mission_history_week', 'dashboards.baptism_history_week'];
  closed text[] := ARRAY['public.area_profiles', 'public.data_name_matches', 'public.finding_people',
                         'public.zone_history_weeks', 'public.referral_archive_weeks', 'public.finding_rate_weeks',
                         'public.baptism_history_weeks', 'public.finding_people_latest', 'public.finding_people_placed',
                         'public.data_upload_week_batches'];
  found text;
BEGIN
  SELECT string_agg(v, ', ') INTO found
  FROM unnest(readable || closed) v
  WHERE to_regclass(v) IS NULL OR (SELECT pg_get_userbyid(relowner) FROM pg_class WHERE oid = to_regclass(v)) <> 'postgres'
     OR coalesce((SELECT reloptions FROM pg_class WHERE oid = to_regclass(v)), '{}') @> ARRAY['security_invoker=true'];
  IF found IS NOT NULL THEN RAISE EXCEPTION 'Check failed: missing, not owned by postgres or security_invoker: %', found; END IF;

  SELECT string_agg(v, ', ') INTO found FROM unnest(readable) v
  WHERE NOT has_table_privilege('gfm_dashboard_reader', v, 'SELECT');
  IF found IS NOT NULL THEN RAISE EXCEPTION 'Check failed: gfm_dashboard_reader cannot read %', found; END IF;

  SELECT string_agg(format('%s (%s)', v, r), ', ') INTO found
  FROM unnest(closed) v CROSS JOIN unnest(ARRAY['public', 'anon', 'authenticated', 'service_role', 'gfm_dashboard_reader']) r
  WHERE has_table_privilege(r, v, 'SELECT') OR has_table_privilege(r, v, 'INSERT')
     OR has_table_privilege(r, v, 'UPDATE') OR has_table_privilege(r, v, 'DELETE');
  IF found IS NOT NULL THEN RAISE EXCEPTION 'Check failed: these may use DA Management data directly: %', found; END IF;

  SELECT string_agg(format('%s (%s)', v, r), ', ') INTO found
  FROM unnest(readable) v CROSS JOIN unnest(ARRAY['public', 'anon', 'authenticated', 'service_role']) r
  WHERE has_table_privilege(r, v, 'SELECT');
  IF found IS NOT NULL THEN RAISE EXCEPTION 'Check failed: these may read the new dashboards views: %', found; END IF;

  -- Personal data: no dashboards column may look like a name, a person, contact details or a birth date.
  SELECT string_agg(format('%s.%s', c.table_name, c.column_name), ', ') INTO found
  FROM information_schema.columns c
  WHERE c.table_schema = 'dashboards'
    AND c.table_name IN ('area_profile', 'finding_area_week', 'finding_cohort_week', 'referral_archive_week',
                         'findechristus_referrals_week', 'finding_rate_week', 'zone_history_week',
                         'mission_history_week', 'baptism_history_week')
    AND c.column_name ~ '(name|person|email|phone|birth|gender|key|referral_number)';
  IF found IS NOT NULL THEN RAISE EXCEPTION 'Check failed: a dashboards column looks like personal data: %', found; END IF;

  -- No table holds a name or a Church person id: only org-unit names (zone_name, district_name, area_name).
  SELECT string_agg(format('%s.%s', c.table_name, c.column_name), ', ') INTO found
  FROM information_schema.columns c
  WHERE c.table_schema = 'public'
    AND c.table_name IN ('area_profiles', 'finding_people', 'zone_history_weeks', 'referral_archive_weeks',
                         'finding_rate_weeks', 'baptism_history_weeks')
    AND c.column_name ~ '(name|person|email|phone|birth|gender)'
    AND c.column_name NOT IN ('zone_name', 'district_name', 'area_name', 'person_key');
  IF found IS NOT NULL THEN RAISE EXCEPTION 'Check failed: a data table has a personal column: %', found; END IF;
END $$;

COMMIT;

-- Verify (read-only, after applying), as postgres:
--   docker exec gfm-beta-supabase-db-1 psql -U postgres -d postgres -c 'BEGIN READ ONLY' -c 'SET LOCAL ROLE gfm_dashboard_reader' -c 'SELECT count(*) FROM dashboards.area_profile' -c 'SELECT count(*) FROM public.finding_people' -c 'ROLLBACK'
-- The first query answers the number of areas; the second must fail with "permission denied".
