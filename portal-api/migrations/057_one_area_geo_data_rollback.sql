-- Rollback of 057_one_area_geo_data.sql. Run on Beta only, as supabase_admin.
--
-- What it does: makes public.area_profiles (and dashboards.area_profile) again as 033 made them and fills it from Geo data (population,
-- size, urban type, assignment type and the free attributes of every area that has any of them), points dashboards.archetype_area_profile
-- back at it, takes urban_type and assignment_type off public.area_geo_data and allows the batch kind AREA_DATA again. The Area data
-- batches that 057 deleted from Import history do NOT come back.
-- Do it together with the code rollback (the DA Management image with the Area data upload), or the Data uploads pages show an error.
-- Take a backup first if the figures should be kept.
--
-- Apply:
--   (Get-Content portal-api/migrations/057_one_area_geo_data_rollback.sql) -join "`n" |
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

-- The batch kind first (the table belongs to supabase_admin).
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
  IF NOT ('AREA_DATA' = ANY (kinds)) THEN
    kinds := kinds || 'AREA_DATA'::text;
    ALTER TABLE public.roster_import_batches DROP CONSTRAINT roster_import_batches_kind_check;
    EXECUTE format('ALTER TABLE public.roster_import_batches ADD CONSTRAINT roster_import_batches_kind_check CHECK (kind IN (%s))',
      (SELECT string_agg(quote_literal(k), ', ' ORDER BY k) FROM unnest(kinds) k));
  END IF;
END $$;

SET LOCAL ROLE postgres;

-- Area data as 033 made it, filled from Geo data.
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
ALTER TABLE public.area_profiles ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.area_profiles FROM PUBLIC, anon, authenticated, service_role;

INSERT INTO public.area_profiles (area_id, population, size_km2, urban_type, assignment_type, extra, updated_at, updated_by)
SELECT g.area_id, g.population, g.size_km2, g.urban_type, g.assignment_type, g.extra, g.updated_at, g.updated_by
FROM public.area_geo_data g
WHERE g.population IS NOT NULL OR g.size_km2 IS NOT NULL OR g.urban_type IS NOT NULL OR g.assignment_type IS NOT NULL
   OR g.extra <> '{}'::jsonb
ON CONFLICT (area_id) DO NOTHING;

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

-- The area Geo data view as 052 made it (columns cannot be dropped from a view with CREATE OR REPLACE), then the columns go.
DROP VIEW IF EXISTS dashboards.area_geo_data;
ALTER TABLE public.area_geo_data DROP COLUMN IF EXISTS urban_type, DROP COLUMN IF EXISTS assignment_type;
COMMENT ON TABLE public.area_geo_data IS 'Geo Data per area (population, size, density, households) with the source and the date of the figures, from DA Management > Data uploads > Geo data. extra = free attributes {"label": "value"}.';
CREATE VIEW dashboards.area_geo_data AS
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
COMMENT ON VIEW dashboards.area_geo_data IS 'Geo Data per area: every open area (and older areas with figures). density_per_km2 = the source''s figure, else population / size_km2. source and data_date say where and when the figures are from.';

REVOKE ALL ON dashboards.area_profile, dashboards.area_geo_data, dashboards.archetype_area_profile FROM PUBLIC, anon, authenticated, service_role;
GRANT SELECT ON dashboards.area_profile, dashboards.area_geo_data, dashboards.archetype_area_profile TO gfm_dashboard_reader;

DO $$
BEGIN
  IF to_regclass('public.area_profiles') IS NULL OR to_regclass('dashboards.area_profile') IS NULL THEN
    RAISE EXCEPTION 'Rollback check failed: Area data is not back.';
  END IF;
  IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'area_geo_data'
             AND column_name IN ('urban_type', 'assignment_type')) THEN
    RAISE EXCEPTION 'Rollback check failed: the new columns are still on public.area_geo_data.';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'roster_import_batches_kind_check'
                 AND pg_get_constraintdef(oid) LIKE '%AREA_DATA%') THEN
    RAISE EXCEPTION 'Rollback check failed: AREA_DATA is not an allowed batch kind.';
  END IF;
  IF NOT has_table_privilege('gfm_dashboard_reader', 'dashboards.archetype_area_profile', 'SELECT')
     OR NOT has_table_privilege('gfm_dashboard_reader', 'dashboards.area_geo_data', 'SELECT')
     OR NOT has_table_privilege('gfm_dashboard_reader', 'dashboards.area_profile', 'SELECT') THEN
    RAISE EXCEPTION 'Rollback check failed: gfm_dashboard_reader lost a view.';
  END IF;
END $$;

COMMIT;
