-- Archetypal Health (round 7). Run on Beta only, as supabase_admin, AFTER 033 (it reads 033's upload views).
--
-- Why: the owner's "Mission Benchmarks & Archetype Engine" sheet compares every area with similar areas and shows six
-- archetypes (Finding, Teaching, Bringing, Baptizing, Fellowshipping, Reactivating) as an index where 100 is what
-- similar areas usually do. The portal page "Archetypal Health" (portal/archetypes.html, portal-api/archetypes.py)
-- does the same with the portal's own numbers, and managers can change every setting.
--
-- What this adds:
--   1. public.archetype_settings: one row per mission with the settings as JSON (weights, peer groups, bands and
--      colours, balance threshold, weeks to average, diagnosis texts). No row = the sheet's defaults (written in
--      portal-api/archetype_model.py, DEFAULT_SETTINGS).
--   2. public.archetype_settings_history: every save and every "Restore the sheet's defaults": who, when, what changed,
--      and the full settings as they were after the change.
--   3. public.archetype_notes: leader notes per area and week (managers, and the area's ZL, STL and DL). One note per
--      person, area and week.
--   4. dashboards.archetype_area_week: one row per week and area that has a weekly plan, with every number the
--      archetypes can use (counts only, no names). It adds up:
--        - the key indicators of dashboards.kpi_area_total_week (018; the same numbers as Call-ins),
--        - the other numeric planning answers (member meals and visits, first time at church, ...): the portal's own
--          answer (weekly_planning_answers) or, for imported weeks, the answer in the imported sheet
--          (historical_planning_details.answers, matched by the sheet's column name),
--        - the new members on the plans (how many, their lessons, how many were at church),
--        - the uploads of 033: FindeChristus referrals, the Church finding export and the baptism history. For a week
--          that an upload covers, an area with no row has 0; for a week it does not cover, the number is empty.
--      The planning answers and new members are read by dashboards.archetype_plan_rows(), which runs as its owner
--      (postgres, SECURITY DEFINER) and returns counts only, like dashboards.area_week_rows() in 018.
--   5. dashboards.archetype_area_profile: the area attributes for peer groups (033's area data; the assignment type
--      falls back to the portal's own areas.assignment_type).
--
-- Who can read it: the three tables are for portal-api only (row level security on, no policy, no rights for PUBLIC,
-- anon, authenticated, service_role or gfm_dashboard_reader). portal-api connects as postgres and checks the
-- stewardship itself on every request (roles.archetype_scope). The two dashboards views are for
-- gfm_dashboard_reader, like the other dashboards views: org units and counts only. They are mission-wide: a page that
-- shows them to a ZL or DL must filter by zone or district, as portal-api does.
--
-- Apply (back up Beta first; after 033). Join the lines with plain line feeds:
--   (Get-Content portal-api/migrations/034_archetypes.sql) -join "`n" |
--     docker exec -i gfm-beta-supabase-db-1 psql -U supabase_admin -d postgres -v ON_ERROR_STOP=1
-- Then run 019 again as a check (it must end with COMMIT).
-- Safe to run again: IF NOT EXISTS, CREATE OR REPLACE, GRANT and REVOKE, then a check that stops on any problem.
-- The file waits at most 10 seconds for a lock, then stops and changes nothing; run it again.
-- Rollback: 034_archetypes_rollback.sql (removes the settings, their history and the notes: back up first).
BEGIN;
SET LOCAL lock_timeout = '10s';

DO $$
BEGIN
  IF NOT (SELECT rolsuper FROM pg_roles WHERE rolname = current_user) THEN
    RAISE EXCEPTION 'Run this file as supabase_admin (see its header), not as %.', current_user;
  END IF;
  IF to_regclass('dashboards.findechristus_referrals_week') IS NULL THEN
    RAISE EXCEPTION 'Apply 033_data_uploads.sql first: 034 reads its views.';
  END IF;
END $$;

-- Everything below belongs to postgres, like the views of 018, 025 and 033 (portal-api connects as postgres).
SET LOCAL ROLE postgres;

-- 1. Settings: one row per mission. settings is checked by portal-api (archetype_model.validate_settings) before it is
-- saved; version goes up by one with every save, so two managers saving at once cannot overwrite each other.
CREATE TABLE IF NOT EXISTS public.archetype_settings (
  mission_id bigint PRIMARY KEY REFERENCES public.missions(id) ON DELETE CASCADE,
  settings jsonb NOT NULL CHECK (jsonb_typeof(settings) = 'object'),
  version integer NOT NULL DEFAULT 1 CHECK (version >= 1),
  updated_at timestamptz NOT NULL DEFAULT now(),
  updated_by uuid,
  updated_by_name text CHECK (length(updated_by_name) <= 200)
);
COMMENT ON TABLE public.archetype_settings IS 'Archetypal Health settings per mission (portal-api archetypes.py). No row = the defaults of the owner''s sheet.';

-- 2. Change history: one row per save or restore, with the full settings after the change.
CREATE TABLE IF NOT EXISTS public.archetype_settings_history (
  id bigint GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
  mission_id bigint NOT NULL REFERENCES public.missions(id) ON DELETE CASCADE,
  version integer NOT NULL,
  action text NOT NULL CHECK (action IN ('save', 'restore_defaults')),
  summary text NOT NULL DEFAULT '' CHECK (length(summary) <= 4000),
  settings jsonb NOT NULL CHECK (jsonb_typeof(settings) = 'object'),
  changed_at timestamptz NOT NULL DEFAULT now(),
  changed_by uuid,
  changed_by_name text CHECK (length(changed_by_name) <= 200)
);
CREATE INDEX IF NOT EXISTS archetype_settings_history_mission_idx
  ON public.archetype_settings_history (mission_id, changed_at DESC);
COMMENT ON TABLE public.archetype_settings_history IS 'Every change of the Archetypal Health settings: who, when, a short summary and the settings after the change.';

-- 3. Leader notes: one note per person, area and week (the Sunday that ends the week).
CREATE TABLE IF NOT EXISTS public.archetype_notes (
  id bigint GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
  area_id bigint NOT NULL REFERENCES public.areas(id) ON DELETE CASCADE,
  sunday date NOT NULL CHECK (extract(isodow FROM sunday) = 7),
  author_id uuid NOT NULL,
  author_name text CHECK (length(author_name) <= 200),
  author_role text CHECK (length(author_role) <= 60),
  body text NOT NULL CHECK (length(btrim(body)) BETWEEN 1 AND 4000),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (area_id, sunday, author_id)
);
CREATE INDEX IF NOT EXISTS archetype_notes_week_idx ON public.archetype_notes (sunday, area_id);
COMMENT ON TABLE public.archetype_notes IS 'Archetypal Health leader notes per area and week. Written and read through portal-api only (managers, and the area''s ZL, STL and DL).';

ALTER TABLE public.archetype_settings ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.archetype_settings_history ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.archetype_notes ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.archetype_settings, public.archetype_settings_history, public.archetype_notes
  FROM PUBLIC, anon, authenticated, service_role, gfm_dashboard_reader;
REVOKE ALL ON SEQUENCE public.archetype_settings_history_id_seq, public.archetype_notes_id_seq
  FROM PUBLIC, anon, authenticated, service_role, gfm_dashboard_reader;

-- 4a. The planning numbers that are not in kpi_area_total_week, per week and area. Runs as postgres so the reader needs
-- no right on public.* (the imported sheet rows also hold names; only numbers leave this function).
-- Which answer counts: the portal's own answer of a plan; for a plan without one, the imported sheet's answer. The
-- sheet's column names are compared "folded" (lower case, letters and digits only), so spaces, dashes and quotes in
-- the sheet do not matter.
CREATE OR REPLACE FUNCTION dashboards.archetype_plan_rows()
RETURNS TABLE (
  reporting_week_id bigint, area_id bigint,
  first_time_first_week_sacrament numeric,
  member_meals_active numeric, member_meals_less_active numeric, member_meals_part_member numeric,
  member_visits_active numeric, member_visits_less_active numeric, member_visits_part_member numeric,
  member_referral_asks numeric, lessons_asked_referral numeric,
  facebook_finding_days numeric, facebook_friends_found numeric,
  youth_activities numeric, service_hours numeric, less_active_sacrament numeric,
  new_members_on_plan bigint, new_member_lessons numeric, new_members_at_church bigint
)
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $$
  WITH numbers(kpi, question_key, sheet_column) AS (
    VALUES
      ('first_time_first_week_sacrament', 'sacrament_first_time_first_week',
       'numberofpeoplewhoattendedsacramentforthefirsttimethatwerefoundthisweek'),
      ('member_meals_active', 'member_meals_active_actual', 'membermealswithactivememberactual'),
      ('member_meals_less_active', 'member_meals_less_active_actual', 'membermealswithlessactivememberactual'),
      ('member_meals_part_member', 'member_meals_part_member_actual', 'membermealswithpartmemberfamilyactual'),
      ('member_visits_active', 'member_visits_active_actual', 'membervisitswithactivememberactual'),
      ('member_visits_less_active', 'member_visits_less_active_actual', 'membervisitswithlessactivememberactual'),
      ('member_visits_part_member', 'member_visits_part_member_actual', 'membervisitswithpartmemberfamilyactual'),
      ('member_referral_asks', 'member_referral_asks_actual',
       'outofallofyourmembermealsandvisitshowmanytimesdidyouaskforafriendreferralactual'),
      ('lessons_asked_referral', NULL,
       'lessonsintheweekwhereyouaskeddoyouknowsomeonewhowouldbeinterestedinactual'),
      ('facebook_finding_days', 'facebook_finding_days', 'daysoffacebookfinding'),
      ('facebook_friends_found', 'facebook_friends_found', 'friendsfoundthroughfacebook'),
      ('youth_activities', 'youth_activities_actual', 'youthactivitiesactual'),
      ('service_hours', 'service_hours_actual', 'servicehoursactual'),
      ('less_active_sacrament', 'less_active_sacrament_actual',
       'numberoflessactivemembersthatyouvebeenworkingwithwhoattendedsacrament')
  ), portal_answers AS (
    SELECT a.weekly_area_report_id AS report_id, n.kpi, sum(a.answer_number) AS value
    FROM public.weekly_planning_answers a
    JOIN numbers n ON n.question_key = a.question_key
    WHERE a.answer_number IS NOT NULL
    GROUP BY 1, 2
  ), sheet_rows AS MATERIALIZED (
    SELECT h.weekly_area_report_id AS report_id, x->>'source_question_label' AS label,
           (x->>'answer_number')::numeric AS value
    FROM public.historical_planning_details h
    CROSS JOIN LATERAL jsonb_array_elements(h.answers) x
    WHERE jsonb_typeof(x->'answer_number') = 'number'
  ), sheet_labels AS (  -- folding each distinct column name once is much faster than folding every answer
    SELECT l.label, n.kpi
    FROM (SELECT DISTINCT label FROM sheet_rows) l
    JOIN numbers n ON n.sheet_column = regexp_replace(lower(l.label), '[^a-z0-9]', '', 'g')
  ), sheet_answers AS (
    SELECT r.report_id, l.kpi, sum(r.value) AS value
    FROM sheet_rows r JOIN sheet_labels l ON l.label = r.label
    GROUP BY 1, 2
  ), answers AS (  -- one value per plan and number: the portal's answer wins over the imported one
    SELECT coalesce(p.report_id, s.report_id) AS report_id, coalesce(p.kpi, s.kpi) AS kpi,
           coalesce(p.value, s.value) AS value
    FROM portal_answers p
    FULL JOIN sheet_answers s ON s.report_id = p.report_id AND s.kpi = p.kpi
  ), portal_new_members AS (
    SELECT m.weekly_area_report_id AS report_id, count(*) AS people, sum(m.lessons_actual) AS lessons,
           count(*) FILTER (WHERE m.at_church_this_sunday) AS at_church
    FROM public.weekly_new_members m
    GROUP BY 1
  ), sheet_new_members AS (
    SELECT h.weekly_area_report_id AS report_id, count(*) AS people,
           sum(CASE WHEN jsonb_typeof(x->'lessons_actual') = 'number' THEN (x->>'lessons_actual')::numeric END) AS lessons,
           count(*) FILTER (WHERE x->>'at_church_this_sunday' = 'true') AS at_church
    FROM public.historical_planning_details h
    CROSS JOIN LATERAL jsonb_array_elements(h.new_members) x
    GROUP BY 1
  ), new_members AS (  -- the portal's new member cards of a plan win over the imported ones
    SELECT coalesce(p.report_id, s.report_id) AS report_id,
           CASE WHEN p.report_id IS NOT NULL THEN p.people ELSE s.people END AS people,
           CASE WHEN p.report_id IS NOT NULL THEN p.lessons ELSE s.lessons END AS lessons,
           CASE WHEN p.report_id IS NOT NULL THEN p.at_church ELSE s.at_church END AS at_church
    FROM portal_new_members p
    FULL JOIN sheet_new_members s ON s.report_id = p.report_id
  ), plans AS (  -- an area may have several plans in a week (one per ward or branch): they are added up
    SELECT r.id, r.reporting_week_id, r.area_id FROM public.weekly_area_reports r
  ), answer_totals AS (
    SELECT r.reporting_week_id, r.area_id, a.kpi, sum(a.value) AS value
    FROM plans r JOIN answers a ON a.report_id = r.id
    GROUP BY 1, 2, 3
  ), new_member_totals AS (
    SELECT r.reporting_week_id, r.area_id, sum(m.people)::bigint AS people, sum(m.lessons) AS lessons,
           sum(m.at_church)::bigint AS at_church
    FROM plans r JOIN new_members m ON m.report_id = r.id
    GROUP BY 1, 2
  ), area_weeks AS (
    SELECT DISTINCT reporting_week_id, area_id FROM plans
  )
  SELECT w.reporting_week_id, w.area_id,
         max(t.value) FILTER (WHERE t.kpi = 'first_time_first_week_sacrament'),
         max(t.value) FILTER (WHERE t.kpi = 'member_meals_active'),
         max(t.value) FILTER (WHERE t.kpi = 'member_meals_less_active'),
         max(t.value) FILTER (WHERE t.kpi = 'member_meals_part_member'),
         max(t.value) FILTER (WHERE t.kpi = 'member_visits_active'),
         max(t.value) FILTER (WHERE t.kpi = 'member_visits_less_active'),
         max(t.value) FILTER (WHERE t.kpi = 'member_visits_part_member'),
         max(t.value) FILTER (WHERE t.kpi = 'member_referral_asks'),
         max(t.value) FILTER (WHERE t.kpi = 'lessons_asked_referral'),
         max(t.value) FILTER (WHERE t.kpi = 'facebook_finding_days'),
         max(t.value) FILTER (WHERE t.kpi = 'facebook_friends_found'),
         max(t.value) FILTER (WHERE t.kpi = 'youth_activities'),
         max(t.value) FILTER (WHERE t.kpi = 'service_hours'),
         max(t.value) FILTER (WHERE t.kpi = 'less_active_sacrament'),
         n.people, n.lessons, n.at_church
  FROM area_weeks w
  LEFT JOIN answer_totals t ON t.reporting_week_id = w.reporting_week_id AND t.area_id = w.area_id
  LEFT JOIN new_member_totals n ON n.reporting_week_id = w.reporting_week_id AND n.area_id = w.area_id
  GROUP BY w.reporting_week_id, w.area_id, n.people, n.lessons, n.at_church
$$;
REVOKE ALL ON FUNCTION dashboards.archetype_plan_rows() FROM PUBLIC, anon, authenticated, service_role;
GRANT EXECUTE ON FUNCTION dashboards.archetype_plan_rows() TO gfm_dashboard_reader;
COMMENT ON FUNCTION dashboards.archetype_plan_rows() IS 'Numbers of dashboards.archetype_area_week that come from planning answers and new member cards (counts only). Runs as postgres so the reader needs no rights on public.*.';

-- 4b. One row per week and area with a weekly plan: every number the archetypes can use.
-- Upload numbers: a week the upload covers (any area has a row that week) gives 0 to an area without a row; a week it
-- does not cover stays empty, so the page can say "no numbers yet" instead of counting a zero.
CREATE OR REPLACE VIEW dashboards.archetype_area_week AS
  WITH plans AS MATERIALIZED (
    SELECT k.* FROM dashboards.kpi_area_total_week k WHERE k.reports > 0
  ), extra AS MATERIALIZED (
    SELECT * FROM dashboards.archetype_plan_rows()
  ), fc AS (
    SELECT f.sunday, f.area_id, sum(f.referrals) AS referrals
    FROM dashboards.findechristus_referrals_week f GROUP BY 1, 2
  ), fc_weeks AS (
    SELECT DISTINCT f.sunday FROM dashboards.findechristus_referrals_week f
  ), finding AS (
    SELECT f.sunday, f.area_id, sum(f.people_found) AS people_found, sum(f.people_reached) AS people_reached,
           sum(f.first_lessons) AS first_lessons
    FROM dashboards.finding_area_week f GROUP BY 1, 2
  ), finding_weeks AS (
    SELECT DISTINCT f.sunday FROM dashboards.finding_area_week f
  ), baptisms AS (
    SELECT b.sunday, b.area_id, sum(b.baptisms) AS baptisms FROM dashboards.baptism_history_week b GROUP BY 1, 2
  ), baptism_weeks AS (
    SELECT DISTINCT b.sunday FROM dashboards.baptism_history_week b
  )
  SELECT k.sunday, k.week, k.reporting_week_id, k.mission_id, k.zone_id, k.zone, k.district_id, k.district,
         k.area_id, k.area, k.reports,
         -- the key indicators, as in Call-ins
         k.friends_found_actual AS friends_found,
         k.lessons_with_friends_actual AS lessons_with_friends,
         k.follow_up_lessons_actual AS follow_up_lessons,
         k.members_at_lessons_actual AS members_at_lessons,
         k.baptismal_dates_actual AS baptismal_dates,
         k.baptisms_confirmations_actual AS baptisms_confirmations,
         k.sacrament_attendance_actual AS sacrament_attendance,
         k.first_time_sacrament_actual AS first_time_sacrament,
         k.new_member_sacrament_actual AS new_member_sacrament,
         -- other planning answers
         e.first_time_first_week_sacrament,
         e.member_meals_active, e.member_meals_less_active, e.member_meals_part_member,
         e.member_visits_active, e.member_visits_less_active, e.member_visits_part_member,
         e.member_referral_asks, e.lessons_asked_referral, e.facebook_finding_days, e.facebook_friends_found,
         e.youth_activities, e.service_hours, e.less_active_sacrament,
         -- new members on the plans; the two shares are empty for a plan without new members
         coalesce(e.new_members_on_plan, 0) AS new_members_on_plan,
         e.new_member_lessons, e.new_members_at_church,
         CASE WHEN e.new_members_on_plan > 0
              THEN round(coalesce(e.new_member_lessons, 0) / e.new_members_on_plan, 4) END AS new_member_lessons_per_member,
         CASE WHEN e.new_members_on_plan > 0
              THEN round(coalesce(e.new_members_at_church, 0)::numeric / e.new_members_on_plan, 4) END AS new_member_sacrament_share,
         -- uploads (033)
         CASE WHEN fw.sunday IS NOT NULL THEN coalesce(fc.referrals, 0) END AS findechristus_referrals,
         CASE WHEN nw.sunday IS NOT NULL THEN coalesce(fi.people_found, 0) END AS finding_people_found,
         CASE WHEN nw.sunday IS NOT NULL THEN coalesce(fi.people_reached, 0) END AS finding_people_reached,
         CASE WHEN nw.sunday IS NOT NULL THEN coalesce(fi.first_lessons, 0) END AS finding_first_lessons,
         CASE WHEN bw.sunday IS NOT NULL THEN coalesce(b.baptisms, 0) END AS baptism_records
  FROM plans k
  LEFT JOIN extra e ON e.reporting_week_id = k.reporting_week_id AND e.area_id = k.area_id
  LEFT JOIN fc_weeks fw ON fw.sunday = k.sunday
  LEFT JOIN fc ON fc.sunday = k.sunday AND fc.area_id = k.area_id
  LEFT JOIN finding_weeks nw ON nw.sunday = k.sunday
  LEFT JOIN finding fi ON fi.sunday = k.sunday AND fi.area_id = k.area_id
  LEFT JOIN baptism_weeks bw ON bw.sunday = k.sunday
  LEFT JOIN baptisms b ON b.sunday = k.sunday AND b.area_id = k.area_id;
COMMENT ON VIEW dashboards.archetype_area_week IS 'Archetypal Health numbers: one row per week (sunday) and area with a weekly plan. Key indicators as in Call-ins, other planning answers (portal answer, else the imported sheet), new members on the plans, and the 033 uploads (0 in a week an upload covers, empty in a week it does not). Counts only.';

-- 5. Area attributes for peer groups (033's area data; assignment type falls back to the portal's own).
CREATE OR REPLACE VIEW dashboards.archetype_area_profile AS
  SELECT z.mission_id, z.id AS zone_id, d.id AS district_id, a.id AS area_id, a.active,
         p.population, p.size_km2,
         CASE WHEN p.population IS NOT NULL AND p.size_km2 > 0 THEN round(p.population / p.size_km2, 1) END AS density_per_km2,
         nullif(btrim(p.urban_type), '') AS urban_type,
         coalesce(nullif(btrim(p.assignment_type), ''), a.assignment_type) AS assignment_type,
         coalesce(p.extra, '{}'::jsonb) AS extra
  FROM public.areas a
  JOIN public.districts d ON d.id = a.district_id
  JOIN public.zones z ON z.id = d.zone_id
  LEFT JOIN public.area_profiles p ON p.area_id = a.id;
COMMENT ON VIEW dashboards.archetype_area_profile IS 'Area attributes for Archetypal Health peer groups: urban type, assignment type (uploaded, else the portal''s), density per km2 and the free extra attributes.';

REVOKE ALL ON dashboards.archetype_area_week, dashboards.archetype_area_profile
  FROM PUBLIC, anon, authenticated, service_role;
GRANT SELECT ON dashboards.archetype_area_week, dashboards.archetype_area_profile TO gfm_dashboard_reader;

-- Check: owners, rights, and no personal data in what dashboards can read.
DO $$
DECLARE
  readable text[] := ARRAY['dashboards.archetype_area_week', 'dashboards.archetype_area_profile'];
  closed text[] := ARRAY['public.archetype_settings', 'public.archetype_settings_history', 'public.archetype_notes'];
  found text;
BEGIN
  SELECT string_agg(v, ', ') INTO found
  FROM unnest(readable || closed) v
  WHERE to_regclass(v) IS NULL OR (SELECT pg_get_userbyid(relowner) FROM pg_class WHERE oid = to_regclass(v)) <> 'postgres'
     OR coalesce((SELECT reloptions FROM pg_class WHERE oid = to_regclass(v)), '{}') @> ARRAY['security_invoker=true'];
  IF found IS NOT NULL THEN RAISE EXCEPTION 'Check failed: missing, not owned by postgres or security_invoker: %', found; END IF;

  IF (SELECT pg_get_userbyid(proowner) FROM pg_proc WHERE oid = 'dashboards.archetype_plan_rows()'::regprocedure) <> 'postgres'
     OR has_function_privilege('public', 'dashboards.archetype_plan_rows()', 'EXECUTE')
     OR has_function_privilege('anon', 'dashboards.archetype_plan_rows()', 'EXECUTE')
     OR has_function_privilege('authenticated', 'dashboards.archetype_plan_rows()', 'EXECUTE') THEN
    RAISE EXCEPTION 'Check failed: dashboards.archetype_plan_rows() must belong to postgres and not be open to API roles.';
  END IF;

  SELECT string_agg(v, ', ') INTO found FROM unnest(readable) v
  WHERE NOT has_table_privilege('gfm_dashboard_reader', v, 'SELECT');
  IF found IS NOT NULL THEN RAISE EXCEPTION 'Check failed: gfm_dashboard_reader cannot read %', found; END IF;

  SELECT string_agg(format('%s (%s)', v, r), ', ') INTO found
  FROM unnest(closed) v CROSS JOIN unnest(ARRAY['public', 'anon', 'authenticated', 'service_role', 'gfm_dashboard_reader']) r
  WHERE has_table_privilege(r, v, 'SELECT') OR has_table_privilege(r, v, 'INSERT')
     OR has_table_privilege(r, v, 'UPDATE') OR has_table_privilege(r, v, 'DELETE');
  IF found IS NOT NULL THEN RAISE EXCEPTION 'Check failed: these may use the archetype tables directly: %', found; END IF;

  SELECT string_agg(format('%s (%s)', v, r), ', ') INTO found
  FROM unnest(readable) v CROSS JOIN unnest(ARRAY['public', 'anon', 'authenticated', 'service_role']) r
  WHERE has_table_privilege(r, v, 'SELECT');
  IF found IS NOT NULL THEN RAISE EXCEPTION 'Check failed: these may read the archetype views: %', found; END IF;

  SELECT string_agg(format('%s.%s', c.table_name, c.column_name), ', ') INTO found
  FROM information_schema.columns c
  WHERE c.table_schema = 'dashboards' AND c.table_name IN ('archetype_area_week', 'archetype_area_profile')
    AND c.column_name ~ '(name|person|email|phone|birth|gender|key|note)';
  IF found IS NOT NULL THEN RAISE EXCEPTION 'Check failed: a dashboards column looks like personal data: %', found; END IF;

  IF NOT (SELECT relrowsecurity FROM pg_class WHERE oid = 'public.archetype_notes'::regclass)
     OR NOT (SELECT relrowsecurity FROM pg_class WHERE oid = 'public.archetype_settings'::regclass)
     OR NOT (SELECT relrowsecurity FROM pg_class WHERE oid = 'public.archetype_settings_history'::regclass) THEN
    RAISE EXCEPTION 'Check failed: row level security must be on for the archetype tables.';
  END IF;
END $$;

COMMIT;

-- Verify (read-only, after applying), as postgres:
--   docker exec gfm-beta-supabase-db-1 psql -U postgres -d postgres -c 'BEGIN READ ONLY' -c 'SET LOCAL ROLE gfm_dashboard_reader' -c 'SELECT count(*) FROM dashboards.archetype_area_week' -c 'SELECT count(*) FROM public.archetype_notes' -c 'ROLLBACK'
-- The first query answers the number of area weeks with a plan; the second must fail with "permission denied".
