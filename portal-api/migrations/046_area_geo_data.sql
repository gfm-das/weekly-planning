-- Migration 046 (Oct 2026): Geo Data, population, size and density per area, with the source and the date of the figures.
-- Run on Beta only, as supabase_admin. Back up first (CLAUDE.md, "Before any database change").
--
-- Why: the owner wants numbers about the places the missionaries serve in (how many people live in an area, how big it
-- is, how dense) next to the weekly numbers, so dashboards and planning can compare areas fairly ("baptisms per 10,000
-- residents"). Area data (migration 033, public.area_profiles) holds peer-group attributes by hand and has no source or
-- date. Geo Data is the official figures with the source (for example "Statistisches Amt Frankfurt") and the date they
-- are from (for example 2024-12-31), imported from a CSV in DA Management > Data uploads > Geo data.
--
-- What changes:
-- 1. Import history accepts the batch kind GEO_DATA. The list of kinds is read from the running constraint and GEO_DATA
--    is added to it, so kinds added by other migrations are kept.
-- 2. public.area_geo_data: one row per area (the stable area id, so a renamed or moved area keeps its figures):
--    population, size_km2, density_per_km2 (as the file states it; the view works it out when the file leaves it out),
--    households, source, data_date, extra (free attributes, text) and who/when. Row level security on, no policy, no
--    rights for PUBLIC, anon, authenticated, service_role or gfm_dashboard_reader: only DA Management (postgres) uses
--    the table. An upload records every changed row in roster_import_changes, so Undo works like Area data (033).
-- 3. dashboards.area_geo_data: the figures per area for dashboards (counts and org units only, no people).
--    dashboards.area_week_per_capita: the six key indicators per area and week (dashboards.kpi_area_week) with the
--    area's population and the same numbers per 10,000 residents. Read by gfm_dashboard_reader like the views of 033.
-- Nothing else is touched. No personal data is stored: the table has no name or person column.
--
-- Apply (back up Beta first; after 018 and 033). Join the lines with plain line feeds:
--   (Get-Content portal-api/migrations/046_area_geo_data.sql) -join "`n" |
--     docker exec -i gfm-beta-supabase-db-1 psql -U supabase_admin -d postgres -v ON_ERROR_STOP=1
-- (Ubuntu server: psql as supabase_admin in the db container, the same way.) Then run 019_restrict_public_functions.sql
-- again as a check, as after every migration (it must end with COMMIT). Deploy step: that re-run is part of the deploy.
-- Safe to run again: IF NOT EXISTS, CREATE OR REPLACE VIEW, GRANT and REVOKE, then a check that stops on any problem.
-- Rollback: 046_area_geo_data_rollback.sql (removes the figures too; take a backup first if they should be kept).
BEGIN;
SET LOCAL lock_timeout = '10s';

DO $$
BEGIN
  IF session_user NOT IN ('supabase_admin', 'postgres') THEN
    RAISE EXCEPTION 'Run this file as supabase_admin (see its header), not as %.', session_user;
  END IF;
  IF to_regclass('dashboards.kpi_area_week') IS NULL OR to_regclass('public.area_profiles') IS NULL THEN
    RAISE EXCEPTION 'Apply 018_dashboard_reporting.sql and 033_data_uploads.sql first.';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'gfm_dashboard_reader') THEN
    RAISE EXCEPTION 'The role gfm_dashboard_reader is missing (migration 018).';
  END IF;
END $$;

-- 1. Import history gets the kind GEO_DATA. The constraint belongs to supabase_admin's table, so this runs before the
--    switch to postgres below. The kinds already allowed are read from the constraint itself and kept.
DO $$
DECLARE
  kinds text[];
BEGIN
  SELECT array_agg(DISTINCT m[1] ORDER BY m[1]) INTO kinds
  FROM pg_constraint c
  CROSS JOIN LATERAL regexp_matches(pg_get_constraintdef(c.oid), '''([A-Z_]+)''', 'g') AS m
  WHERE c.conrelid = 'public.roster_import_batches'::regclass AND c.conname = 'roster_import_batches_kind_check';
  IF kinds IS NULL OR NOT ('TRANSFER' = ANY (kinds) AND 'AREA_DATA' = ANY (kinds)) THEN
    RAISE EXCEPTION 'The list of batch kinds could not be read from roster_import_batches_kind_check (found: %).', kinds;
  END IF;
  IF NOT ('GEO_DATA' = ANY (kinds)) THEN
    kinds := kinds || 'GEO_DATA'::text;
    ALTER TABLE public.roster_import_batches DROP CONSTRAINT roster_import_batches_kind_check;
    EXECUTE format('ALTER TABLE public.roster_import_batches ADD CONSTRAINT roster_import_batches_kind_check CHECK (kind IN (%s))',
      (SELECT string_agg(quote_literal(k), ', ' ORDER BY k) FROM unnest(kinds) k));
  END IF;
END $$;

-- Everything below belongs to postgres, like the tables and views of 033 (DA Management connects as postgres).
SET LOCAL ROLE postgres;

-- 2. The figures. One row per area; an empty column means "not known yet".
CREATE TABLE IF NOT EXISTS public.area_geo_data (
  area_id bigint PRIMARY KEY REFERENCES public.areas(id) ON DELETE CASCADE,
  population integer CHECK (population >= 0),
  size_km2 numeric(12,3) CHECK (size_km2 > 0),
  density_per_km2 numeric(12,2) CHECK (density_per_km2 >= 0),
  households integer CHECK (households >= 0),
  source text CHECK (length(source) <= 200),
  data_date date CHECK (data_date >= DATE '1900-01-01'),
  extra jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(extra) = 'object'),
  updated_at timestamptz NOT NULL DEFAULT now(),
  updated_by text
);
COMMENT ON TABLE public.area_geo_data IS 'Geo Data per area (population, size, density, households) with the source and the date of the figures, from DA Management > Data uploads > Geo data. extra = free attributes {"label": "value"}.';
COMMENT ON COLUMN public.area_geo_data.density_per_km2 IS 'People per km2 as the source states it. Empty: dashboards.area_geo_data works it out from population / size_km2.';
COMMENT ON COLUMN public.area_geo_data.data_date IS 'The date the figures are from ("as of"), not the day they were uploaded.';

ALTER TABLE public.area_geo_data ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.area_geo_data FROM PUBLIC, anon, authenticated, service_role;

-- 3. Views for dashboards.
CREATE OR REPLACE VIEW dashboards.area_geo_data AS
  SELECT z.mission_id, z.id AS zone_id, z.name AS zone, d.id AS district_id, d.name AS district,
         a.id AS area_id, a.name AS area, a.active,
         g.population, g.size_km2,
         coalesce(g.density_per_km2,
                  CASE WHEN g.population IS NOT NULL AND g.size_km2 > 0 THEN round(g.population / g.size_km2, 1) END) AS density_per_km2,
         g.households, g.source, g.data_date, coalesce(g.extra, '{}'::jsonb) AS extra, g.updated_at
  FROM public.areas a
  JOIN public.districts d ON d.id = a.district_id
  JOIN public.zones z ON z.id = d.zone_id
  LEFT JOIN public.area_geo_data g ON g.area_id = a.id
  WHERE a.active OR g.area_id IS NOT NULL;
COMMENT ON VIEW dashboards.area_geo_data IS 'Geo Data per area: every open area (and older areas with figures). density_per_km2 = the source''s figure, else population / size_km2. source and data_date say where and when the figures are from.';

CREATE OR REPLACE VIEW dashboards.area_week_per_capita AS
  SELECT k.sunday, k.week, k.mission_id, k.zone_id, k.zone, k.district_id, k.district, k.area_id, k.area,
         g.population, g.size_km2, g.data_date AS geo_data_date,
         k.friends_found_actual, k.baptisms_confirmations_actual, k.baptismal_dates_actual,
         k.sacrament_attendance_actual, k.members_at_lessons_actual, k.new_member_sacrament_actual,
         CASE WHEN g.population > 0 THEN round(k.friends_found_actual * 10000.0 / g.population, 2) END AS friends_found_per_10k,
         CASE WHEN g.population > 0 THEN round(k.baptisms_confirmations_actual * 10000.0 / g.population, 2) END AS baptisms_confirmations_per_10k,
         CASE WHEN g.population > 0 THEN round(k.baptismal_dates_actual * 10000.0 / g.population, 2) END AS baptismal_dates_per_10k,
         CASE WHEN g.population > 0 THEN round(k.sacrament_attendance_actual * 10000.0 / g.population, 2) END AS sacrament_attendance_per_10k,
         CASE WHEN g.population > 0 THEN round(k.members_at_lessons_actual * 10000.0 / g.population, 2) END AS members_at_lessons_per_10k,
         CASE WHEN g.population > 0 THEN round(k.new_member_sacrament_actual * 10000.0 / g.population, 2) END AS new_member_sacrament_per_10k
  FROM dashboards.kpi_area_week k
  LEFT JOIN public.area_geo_data g ON g.area_id = k.area_id;
COMMENT ON VIEW dashboards.area_week_per_capita IS 'The six key indicators per area and week (dashboards.kpi_area_week) with the area''s population from Geo Data and each indicator per 10,000 residents. Empty per-10k columns: the area has no population yet.';

-- Rights: the reader gets the two views, nobody else gets anything new.
REVOKE ALL ON dashboards.area_geo_data, dashboards.area_week_per_capita FROM PUBLIC, anon, authenticated, service_role;
GRANT SELECT ON dashboards.area_geo_data, dashboards.area_week_per_capita TO gfm_dashboard_reader;

-- Check: owners, rights, the batch kind, and no personal data in what dashboards can read.
DO $$
DECLARE
  readable text[] := ARRAY['dashboards.area_geo_data', 'dashboards.area_week_per_capita'];
  closed text[] := ARRAY['public.area_geo_data'];
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
  IF found IS NOT NULL THEN RAISE EXCEPTION 'Check failed: these may use Geo Data directly: %', found; END IF;

  SELECT string_agg(format('%s (%s)', v, r), ', ') INTO found
  FROM unnest(readable) v CROSS JOIN unnest(ARRAY['public', 'anon', 'authenticated', 'service_role']) r
  WHERE has_table_privilege(r, v, 'SELECT');
  IF found IS NOT NULL THEN RAISE EXCEPTION 'Check failed: these may read the new dashboards views: %', found; END IF;

  IF NOT (SELECT relrowsecurity FROM pg_class WHERE oid = 'public.area_geo_data'::regclass) THEN
    RAISE EXCEPTION 'Check failed: row level security is off on public.area_geo_data';
  END IF;

  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'roster_import_batches_kind_check'
                 AND pg_get_constraintdef(oid) LIKE '%GEO_DATA%') THEN
    RAISE EXCEPTION 'Check failed: the batch kind GEO_DATA is not allowed.';
  END IF;

  -- Personal data: no column of the views or the table may look like a name, a person, contact details or a birth date.
  SELECT string_agg(format('%s.%s', c.table_schema || '.' || c.table_name, c.column_name), ', ') INTO found
  FROM information_schema.columns c
  WHERE ((c.table_schema = 'dashboards' AND c.table_name IN ('area_geo_data', 'area_week_per_capita'))
      OR (c.table_schema = 'public' AND c.table_name = 'area_geo_data'))
    AND c.column_name ~ '(name|person|email|phone|birth|gender|key|referral_number)';
  IF found IS NOT NULL THEN RAISE EXCEPTION 'Check failed: a Geo Data column looks like personal data: %', found; END IF;
END $$;

COMMIT;

-- Verify (read-only, after applying), as postgres:
--   docker exec gfm-beta-supabase-db-1 psql -U postgres -d postgres -c 'BEGIN READ ONLY' -c 'SET LOCAL ROLE gfm_dashboard_reader' -c 'SELECT count(*) FROM dashboards.area_geo_data' -c 'SELECT count(*) FROM public.area_geo_data' -c 'ROLLBACK'
-- The first query answers the number of areas; the second must fail with "permission denied".
