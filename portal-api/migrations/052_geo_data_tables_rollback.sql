-- Rollback of 052_geo_data_tables.sql. Run on Beta only, as supabase_admin.
--
-- What it does: removes the zone and district figures (public.zone_geo_data, public.district_geo_data and their dashboards views)
-- WITH THEIR FIGURES, takes the seven new columns off public.area_geo_data (the figures in them go; population, size,
-- density, households, source and date stay) and puts dashboards.area_geo_data back as 046 made it. In Import history it
-- scrubs what refers to the removed parts: the recorded rows of the two removed tables are deleted, and the new columns are taken
-- out of the recorded before/after rows of public.area_geo_data, so an older Geo data upload can still be undone. (An upload that
-- changed ONLY zone or district rows stays in the list with no rows to undo: Undo it BEFORE this rollback if it matters.)
-- Do it together with the code rollback (the DA Management image without the three-table Geo data upload), or Geo data uploads show
-- an error. Take a backup first if the figures should be kept.
-- Order: roll back anything that reads the new dashboards views first; this file stops with a "depends on" error otherwise (safely).
--
-- Apply:
--   (Get-Content portal-api/migrations/052_geo_data_tables_rollback.sql) -join "`n" |
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

SET LOCAL ROLE postgres;

-- Import history: scrub first (the rows may refer to the parts removed below).
DELETE FROM public.roster_import_changes WHERE table_name IN ('zone_geo_data', 'district_geo_data');
UPDATE public.roster_import_changes
   SET before_row = before_row - ARRAY['pop_urban_centre', 'pop_dense_urban_cluster', 'pop_semi_dense_urban_cluster', 'pop_suburban',
                                       'pop_rural_very_low', 'pop_rural_low', 'area_type'],
       after_row = after_row - ARRAY['pop_urban_centre', 'pop_dense_urban_cluster', 'pop_semi_dense_urban_cluster', 'pop_suburban',
                                     'pop_rural_very_low', 'pop_rural_low', 'area_type']
 WHERE table_name = 'area_geo_data';

DROP VIEW IF EXISTS dashboards.zone_geo_data, dashboards.district_geo_data;

-- The area view as 046 made it (the columns cannot be dropped from a view with CREATE OR REPLACE, so it is dropped and made again).
DROP VIEW IF EXISTS dashboards.area_geo_data;

ALTER TABLE public.area_geo_data
  DROP COLUMN IF EXISTS pop_urban_centre, DROP COLUMN IF EXISTS pop_dense_urban_cluster,
  DROP COLUMN IF EXISTS pop_semi_dense_urban_cluster, DROP COLUMN IF EXISTS pop_suburban,
  DROP COLUMN IF EXISTS pop_rural_very_low, DROP COLUMN IF EXISTS pop_rural_low, DROP COLUMN IF EXISTS area_type;
DROP TABLE IF EXISTS public.zone_geo_data, public.district_geo_data;

CREATE VIEW dashboards.area_geo_data AS
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
REVOKE ALL ON dashboards.area_geo_data FROM PUBLIC, anon, authenticated, service_role;
GRANT SELECT ON dashboards.area_geo_data TO gfm_dashboard_reader;

DO $$
DECLARE
  found text;
BEGIN
  SELECT string_agg(n.nspname || '.' || c.relname, ', ') INTO found
  FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
  WHERE (n.nspname = 'dashboards' AND c.relname IN ('zone_geo_data', 'district_geo_data'))
     OR (n.nspname = 'public' AND c.relname IN ('zone_geo_data', 'district_geo_data'));
  IF found IS NOT NULL THEN RAISE EXCEPTION 'Rollback check failed: still there: %', found; END IF;
  IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'area_geo_data'
             AND column_name IN ('pop_urban_centre', 'area_type')) THEN
    RAISE EXCEPTION 'Rollback check failed: the new columns are still on public.area_geo_data.';
  END IF;
  IF NOT has_table_privilege('gfm_dashboard_reader', 'dashboards.area_geo_data', 'SELECT') THEN
    RAISE EXCEPTION 'Rollback check failed: gfm_dashboard_reader cannot read dashboards.area_geo_data.';
  END IF;
END $$;

COMMIT;
