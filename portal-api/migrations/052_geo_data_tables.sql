-- Migration 052 (Oct 2026): Geo data in the owner's format: zone and district figures, the six urbanisation populations and the area type.
-- Run on Beta only, as supabase_admin. Back up first (CLAUDE.md, "Before any database change").
-- (Numbering: 051 is the Vollzogen list on the round-13 importer2 branch; renumber if another branch took 052 first.)
--
-- Why: the owner's "Areas Geo Data" file has three tables side by side, Zone / District / Area. Each table has Population, Area
-- (km2), Population Density, the population in six degree-of-urbanisation classes (Urban Centre 130, Dense Urban Cluster 223,
-- Semi-dense Urban Cluster 222, Suburban/peri-urban 221, Very low density rural 311, Low density rural 312) and an Area Type.
-- Migration 046 (public.area_geo_data) only knows the area figures. Do NOT edit 046: it may already be applied or tested.
--
-- What changes (all new, nothing existing is changed or removed):
-- 1. public.area_geo_data gets seven new NULLABLE columns: pop_urban_centre, pop_dense_urban_cluster, pop_semi_dense_urban_cluster,
--    pop_suburban, pop_rural_very_low, pop_rural_low (people, >= 0) and area_type (text). Rows already there keep their figures.
-- 2. public.zone_geo_data and public.district_geo_data: the same figures for a whole zone or district (keyed by the stable zone
--    or district id; ON DELETE CASCADE), with source, data_date, extra and who/when. Row level security on, no policy, no rights
--    for PUBLIC, anon, authenticated, service_role or gfm_dashboard_reader: only DA Management (postgres) uses them. An upload
--    records every changed row in roster_import_changes, so Undo works as for the area figures.
-- 3. dashboards.area_geo_data is replaced with the same columns plus the new ones at the end (CREATE OR REPLACE VIEW keeps every
--    existing column in place); new dashboards.zone_geo_data and dashboards.district_geo_data. Read by gfm_dashboard_reader.
-- No personal data is stored: no column has a name of a person.
--
-- Apply (back up Beta first; after 046). Join the lines with plain line feeds:
--   (Get-Content portal-api/migrations/052_geo_data_tables.sql) -join "`n" |
--     docker exec -i gfm-beta-supabase-db-1 psql -U supabase_admin -d postgres -v ON_ERROR_STOP=1
-- (Ubuntu server: psql as supabase_admin in the db container, the same way.) Then run 019_restrict_public_functions.sql
-- again as a check, as after every migration (it must end with COMMIT). Deploy step: that re-run is part of the deploy.
-- Apply this BEFORE the new DA Management image (Geo data uploads and Undo lock and read these tables).
-- Safe to run again: IF NOT EXISTS, CREATE OR REPLACE VIEW, GRANT and REVOKE, then a check that stops on any problem.
-- Rollback: 052_geo_data_tables_rollback.sql (removes the zone and district figures and the new area columns).
BEGIN;
SET LOCAL lock_timeout = '10s';

DO $$
BEGIN
  IF session_user NOT IN ('supabase_admin', 'postgres') THEN
    RAISE EXCEPTION 'Run this file as supabase_admin (see its header), not as %.', session_user;
  END IF;
  IF to_regclass('public.area_geo_data') IS NULL OR to_regclass('dashboards.area_geo_data') IS NULL THEN
    RAISE EXCEPTION 'Apply 046_area_geo_data.sql first.';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'gfm_dashboard_reader') THEN
    RAISE EXCEPTION 'The role gfm_dashboard_reader is missing (migration 018).';
  END IF;
END $$;

-- Everything below belongs to postgres, like the tables and views of 033 and 046 (DA Management connects as postgres).
SET LOCAL ROLE postgres;

-- 1. New columns on the area figures.
ALTER TABLE public.area_geo_data
  ADD COLUMN IF NOT EXISTS pop_urban_centre integer CHECK (pop_urban_centre >= 0),
  ADD COLUMN IF NOT EXISTS pop_dense_urban_cluster integer CHECK (pop_dense_urban_cluster >= 0),
  ADD COLUMN IF NOT EXISTS pop_semi_dense_urban_cluster integer CHECK (pop_semi_dense_urban_cluster >= 0),
  ADD COLUMN IF NOT EXISTS pop_suburban integer CHECK (pop_suburban >= 0),
  ADD COLUMN IF NOT EXISTS pop_rural_very_low integer CHECK (pop_rural_very_low >= 0),
  ADD COLUMN IF NOT EXISTS pop_rural_low integer CHECK (pop_rural_low >= 0),
  ADD COLUMN IF NOT EXISTS area_type text CHECK (length(area_type) <= 60);
COMMENT ON COLUMN public.area_geo_data.pop_urban_centre IS 'People living in urban centre grid cells (degree of urbanisation class 130).';
COMMENT ON COLUMN public.area_geo_data.pop_dense_urban_cluster IS 'People in dense urban cluster grid cells (class 223).';
COMMENT ON COLUMN public.area_geo_data.pop_semi_dense_urban_cluster IS 'People in semi-dense urban cluster grid cells (class 222).';
COMMENT ON COLUMN public.area_geo_data.pop_suburban IS 'People in suburban or peri-urban grid cells (class 221).';
COMMENT ON COLUMN public.area_geo_data.pop_rural_very_low IS 'People in very low density rural grid cells (class 311).';
COMMENT ON COLUMN public.area_geo_data.pop_rural_low IS 'People in low density rural grid cells (class 312).';
COMMENT ON COLUMN public.area_geo_data.area_type IS 'The kind of area as the Geo data file states it (for example City or Town).';

-- 2. The same figures for a whole zone and for a district.
CREATE TABLE IF NOT EXISTS public.zone_geo_data (
  zone_id bigint PRIMARY KEY REFERENCES public.zones(id) ON DELETE CASCADE,
  population integer CHECK (population >= 0),
  size_km2 numeric(12,3) CHECK (size_km2 > 0),
  density_per_km2 numeric(12,2) CHECK (density_per_km2 >= 0),
  pop_urban_centre integer CHECK (pop_urban_centre >= 0),
  pop_dense_urban_cluster integer CHECK (pop_dense_urban_cluster >= 0),
  pop_semi_dense_urban_cluster integer CHECK (pop_semi_dense_urban_cluster >= 0),
  pop_suburban integer CHECK (pop_suburban >= 0),
  pop_rural_very_low integer CHECK (pop_rural_very_low >= 0),
  pop_rural_low integer CHECK (pop_rural_low >= 0),
  area_type text CHECK (length(area_type) <= 60),
  source text CHECK (length(source) <= 200),
  data_date date CHECK (data_date >= DATE '1900-01-01'),
  extra jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(extra) = 'object'),
  updated_at timestamptz NOT NULL DEFAULT now(),
  updated_by text
);
COMMENT ON TABLE public.zone_geo_data IS 'Geo Data per zone (population, size, density, urbanisation classes, area type) with source and date, from DA Management > Data uploads > Geo data.';

CREATE TABLE IF NOT EXISTS public.district_geo_data (
  district_id bigint PRIMARY KEY REFERENCES public.districts(id) ON DELETE CASCADE,
  population integer CHECK (population >= 0),
  size_km2 numeric(12,3) CHECK (size_km2 > 0),
  density_per_km2 numeric(12,2) CHECK (density_per_km2 >= 0),
  pop_urban_centre integer CHECK (pop_urban_centre >= 0),
  pop_dense_urban_cluster integer CHECK (pop_dense_urban_cluster >= 0),
  pop_semi_dense_urban_cluster integer CHECK (pop_semi_dense_urban_cluster >= 0),
  pop_suburban integer CHECK (pop_suburban >= 0),
  pop_rural_very_low integer CHECK (pop_rural_very_low >= 0),
  pop_rural_low integer CHECK (pop_rural_low >= 0),
  area_type text CHECK (length(area_type) <= 60),
  source text CHECK (length(source) <= 200),
  data_date date CHECK (data_date >= DATE '1900-01-01'),
  extra jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(extra) = 'object'),
  updated_at timestamptz NOT NULL DEFAULT now(),
  updated_by text
);
COMMENT ON TABLE public.district_geo_data IS 'Geo Data per district (population, size, density, urbanisation classes, area type) with source and date, from DA Management > Data uploads > Geo data.';

ALTER TABLE public.zone_geo_data ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.district_geo_data ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.zone_geo_data, public.district_geo_data FROM PUBLIC, anon, authenticated, service_role;

-- 3. Views for dashboards.
CREATE OR REPLACE VIEW dashboards.area_geo_data AS
  SELECT z.mission_id, z.id AS zone_id, z.name AS zone, d.id AS district_id, d.name AS district,
         a.id AS area_id, a.name AS area, a.active,
         g.population, g.size_km2,
         coalesce(g.density_per_km2,
                  CASE WHEN g.population IS NOT NULL AND g.size_km2 > 0 THEN round(g.population / g.size_km2, 1) END) AS density_per_km2,
         g.households, g.source, g.data_date, coalesce(g.extra, '{}'::jsonb) AS extra, g.updated_at,
         g.pop_urban_centre, g.pop_dense_urban_cluster, g.pop_semi_dense_urban_cluster, g.pop_suburban,
         g.pop_rural_very_low, g.pop_rural_low, g.area_type
  FROM public.areas a
  JOIN public.districts d ON d.id = a.district_id
  JOIN public.zones z ON z.id = d.zone_id
  LEFT JOIN public.area_geo_data g ON g.area_id = a.id
  WHERE a.active OR g.area_id IS NOT NULL;

CREATE OR REPLACE VIEW dashboards.district_geo_data AS
  SELECT z.mission_id, z.id AS zone_id, z.name AS zone, d.id AS district_id, d.name AS district, d.active,
         g.population, g.size_km2,
         coalesce(g.density_per_km2,
                  CASE WHEN g.population IS NOT NULL AND g.size_km2 > 0 THEN round(g.population / g.size_km2, 1) END) AS density_per_km2,
         g.pop_urban_centre, g.pop_dense_urban_cluster, g.pop_semi_dense_urban_cluster, g.pop_suburban,
         g.pop_rural_very_low, g.pop_rural_low, g.area_type,
         g.source, g.data_date, coalesce(g.extra, '{}'::jsonb) AS extra, g.updated_at
  FROM public.districts d
  JOIN public.zones z ON z.id = d.zone_id
  LEFT JOIN public.district_geo_data g ON g.district_id = d.id
  WHERE d.active OR g.district_id IS NOT NULL;
COMMENT ON VIEW dashboards.district_geo_data IS 'Geo Data per district: every open district (and older ones with figures). density_per_km2 = the source''s figure, else population / size_km2.';

CREATE OR REPLACE VIEW dashboards.zone_geo_data AS
  SELECT z.mission_id, z.id AS zone_id, z.name AS zone, z.active,
         g.population, g.size_km2,
         coalesce(g.density_per_km2,
                  CASE WHEN g.population IS NOT NULL AND g.size_km2 > 0 THEN round(g.population / g.size_km2, 1) END) AS density_per_km2,
         g.pop_urban_centre, g.pop_dense_urban_cluster, g.pop_semi_dense_urban_cluster, g.pop_suburban,
         g.pop_rural_very_low, g.pop_rural_low, g.area_type,
         g.source, g.data_date, coalesce(g.extra, '{}'::jsonb) AS extra, g.updated_at
  FROM public.zones z
  LEFT JOIN public.zone_geo_data g ON g.zone_id = z.id
  WHERE z.active OR g.zone_id IS NOT NULL;
COMMENT ON VIEW dashboards.zone_geo_data IS 'Geo Data per zone: every open zone (and older ones with figures). density_per_km2 = the source''s figure, else population / size_km2.';

-- Rights: the reader gets the new views (and keeps the old ones), nobody else gets anything new.
REVOKE ALL ON dashboards.area_geo_data, dashboards.district_geo_data, dashboards.zone_geo_data FROM PUBLIC, anon, authenticated, service_role;
GRANT SELECT ON dashboards.area_geo_data, dashboards.district_geo_data, dashboards.zone_geo_data TO gfm_dashboard_reader;

-- Check: owners, rights, row level security, and no personal data in what dashboards can read.
DO $$
DECLARE
  readable text[] := ARRAY['dashboards.area_geo_data', 'dashboards.district_geo_data', 'dashboards.zone_geo_data'];
  closed text[] := ARRAY['public.area_geo_data', 'public.district_geo_data', 'public.zone_geo_data'];
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
  IF found IS NOT NULL THEN RAISE EXCEPTION 'Check failed: these may read the Geo data views: %', found; END IF;

  SELECT string_agg(v, ', ') INTO found FROM unnest(closed) v
  WHERE NOT (SELECT relrowsecurity FROM pg_class WHERE oid = to_regclass(v));
  IF found IS NOT NULL THEN RAISE EXCEPTION 'Check failed: row level security is off on %', found; END IF;

  SELECT string_agg(v, ', ') INTO found FROM unnest(closed) v
  WHERE EXISTS (SELECT 1 FROM pg_policy WHERE polrelid = to_regclass(v));
  IF found IS NOT NULL THEN RAISE EXCEPTION 'Check failed: these have a policy (they must have none): %', found; END IF;

  -- Personal data: no column of the views or the tables may look like a name, a person, contact details or a birth date.
  SELECT string_agg(format('%s.%s', c.table_schema || '.' || c.table_name, c.column_name), ', ') INTO found
  FROM information_schema.columns c
  WHERE ((c.table_schema = 'dashboards' AND c.table_name IN ('area_geo_data', 'district_geo_data', 'zone_geo_data'))
      OR (c.table_schema = 'public' AND c.table_name IN ('area_geo_data', 'district_geo_data', 'zone_geo_data')))
    AND c.column_name ~ '(name|person|email|phone|birth|gender|key|referral_number)';
  IF found IS NOT NULL THEN RAISE EXCEPTION 'Check failed: a Geo Data column looks like personal data: %', found; END IF;
END $$;

COMMIT;

-- Verify (read-only, after applying), as postgres:
--   docker exec gfm-beta-supabase-db-1 psql -U postgres -d postgres -c 'BEGIN READ ONLY' -c 'SET LOCAL ROLE gfm_dashboard_reader' -c 'SELECT count(*) FROM dashboards.zone_geo_data' -c 'SELECT count(*) FROM public.zone_geo_data' -c 'ROLLBACK'
-- The first query answers the number of zones; the second must fail with "permission denied".
