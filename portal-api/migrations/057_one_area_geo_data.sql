-- Migration 057 (Oct 2026, round 16): "Area data" and "Geo data" become ONE upload, Geo data.
-- Run on Beta only, as supabase_admin. Back up first (CLAUDE.md, "Before any database change").
--
-- Why: two cards stored the same thing. Area data (033, public.area_profiles) held population, size, urban type, assignment type and
-- free attributes per area; Geo data (046 and 052, public.area_geo_data) holds population, size, density, households, source and date.
-- The owner wants one upload. Geo data stays; it learns the two peer-group columns Area data had.
--
-- What changes:
-- 1. public.area_geo_data gets urban_type and assignment_type (text, at most 60 characters, empty = not known).
-- 2. Every row of public.area_profiles is copied into public.area_geo_data (one row per area): where both have a value Geo data
--    wins; an empty Geo data cell is filled from Area data; the free attributes (extra) are merged, Geo data wins on a clash.
--    Rows that say nothing are not copied.
-- 3. dashboards.archetype_area_profile (Archetypal Health peer groups) reads public.area_geo_data: density = the stored density,
--    else population / size. Same columns as before. dashboards.area_geo_data gets urban_type and assignment_type at the end.
-- 4. dashboards.area_profile (033, read by nothing any more) and public.area_profiles are dropped.
-- 5. Import history: the batches of kind AREA_DATA are DELETED (their recorded rows go with them: ON DELETE CASCADE) and AREA_DATA is
--    taken out of the allowed batch kinds. Their rows could not be undone any more (the table is gone), and the figures live on as
--    Geo data. The Geo data batches stay as they are.
-- No person is stored: only counts, sizes and labels of places.
--
-- Apply (back up Beta first; after 046 and 052). Join the lines with plain line feeds:
--   (Get-Content portal-api/migrations/057_one_area_geo_data.sql) -join "`n" |
--     docker exec -i gfm-beta-supabase-db-1 psql -U supabase_admin -d postgres -v ON_ERROR_STOP=1
-- (Ubuntu server: psql as supabase_admin in the db container, the same way.) Then run 019_restrict_public_functions.sql
-- again as a check, as after every migration (it must end with COMMIT). Deploy step: that re-run is part of the deploy.
-- Apply this BEFORE the new DA Management image (it no longer knows Area data) and, on an update, together with it.
-- Safe to run again: IF NOT EXISTS, CREATE OR REPLACE VIEW, DROP ... IF EXISTS, then a check that stops on any problem.
-- Rollback: 057_one_area_geo_data_rollback.sql (makes public.area_profiles again from the Geo data columns; the deleted Area data
-- batches in Import history do not come back).
BEGIN;
SET LOCAL lock_timeout = '10s';

DO $$
BEGIN
  IF session_user NOT IN ('supabase_admin', 'postgres') THEN
    RAISE EXCEPTION 'Run this file as supabase_admin (see its header), not as %.', session_user;
  END IF;
  IF to_regclass('public.area_geo_data') IS NULL OR to_regclass('dashboards.area_geo_data') IS NULL
     OR to_regclass('dashboards.archetype_area_profile') IS NULL OR to_regclass('public.roster_import_batches') IS NULL THEN
    RAISE EXCEPTION 'Apply 046 and 052 (Geo data) and the archetypes migration first.';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'area_geo_data'
                 AND column_name = 'area_type') THEN
    RAISE EXCEPTION 'Apply 052_geo_data_tables.sql first.';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'gfm_dashboard_reader') THEN
    RAISE EXCEPTION 'The role gfm_dashboard_reader is missing (migration 018).';
  END IF;
END $$;

-- 1. Import history: the Area data batches go (rows recorded for Undo go with them) and AREA_DATA stops being a kind. The constraint
--    belongs to supabase_admin's table, so this runs before the switch to postgres below. The other kinds are read from the
--    constraint itself and kept.
DELETE FROM public.roster_import_batches WHERE kind = 'AREA_DATA';
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
  IF 'AREA_DATA' = ANY (kinds) THEN
    kinds := array_remove(kinds, 'AREA_DATA');
    ALTER TABLE public.roster_import_batches DROP CONSTRAINT roster_import_batches_kind_check;
    EXECUTE format('ALTER TABLE public.roster_import_batches ADD CONSTRAINT roster_import_batches_kind_check CHECK (kind IN (%s))',
      (SELECT string_agg(quote_literal(k), ', ' ORDER BY k) FROM unnest(kinds) k));
  END IF;
END $$;

-- Everything below belongs to postgres, like the tables and views of 033, 046 and 052 (DA Management connects as postgres).
SET LOCAL ROLE postgres;

-- 2. The two peer-group columns on the Geo data table.
ALTER TABLE public.area_geo_data
  ADD COLUMN IF NOT EXISTS urban_type text CHECK (length(urban_type) <= 60),
  ADD COLUMN IF NOT EXISTS assignment_type text CHECK (length(assignment_type) <= 60);
COMMENT ON COLUMN public.area_geo_data.urban_type IS 'Peer-group attribute for Archetypal Health (for example Urban or Rural), typed by hand or uploaded.';
COMMENT ON COLUMN public.area_geo_data.assignment_type IS 'Peer-group attribute for Archetypal Health: the kind of assignment; empty = the portal''s own value of the area.';
COMMENT ON TABLE public.area_geo_data IS 'Geo Data per area (population, size, density, households, urban type, assignment type) with the source and the date of the figures, from DA Management > Data uploads > Geo data. extra = free attributes {"label": "value"}.';

-- 3. Copy what Area data had (Geo data wins where both have a value). Skipped when public.area_profiles is already gone.
DO $$
BEGIN
  IF to_regclass('public.area_profiles') IS NOT NULL THEN
    INSERT INTO public.area_geo_data AS g (area_id, population, size_km2, urban_type, assignment_type, extra, updated_at, updated_by)
    SELECT p.area_id, p.population, p.size_km2, p.urban_type, p.assignment_type, p.extra, p.updated_at, p.updated_by
    FROM public.area_profiles p
    WHERE p.population IS NOT NULL OR p.size_km2 IS NOT NULL OR p.urban_type IS NOT NULL OR p.assignment_type IS NOT NULL
       OR p.extra <> '{}'::jsonb
    ON CONFLICT (area_id) DO UPDATE SET
      population = coalesce(g.population, excluded.population),
      size_km2 = coalesce(g.size_km2, excluded.size_km2),
      urban_type = coalesce(g.urban_type, excluded.urban_type),
      assignment_type = coalesce(g.assignment_type, excluded.assignment_type),
      extra = excluded.extra || g.extra;
  END IF;
END $$;

-- 4. The views. Archetypal Health reads the Geo data table now (the same columns as before). The area view gets the two new columns
--    at the end (CREATE OR REPLACE VIEW keeps every existing column in place).
CREATE OR REPLACE VIEW dashboards.archetype_area_profile AS
  SELECT z.mission_id, z.id AS zone_id, d.id AS district_id, a.id AS area_id, a.active,
         g.population, g.size_km2,
         coalesce(g.density_per_km2,
                  CASE WHEN g.population IS NOT NULL AND g.size_km2 > 0 THEN round(g.population / g.size_km2, 1) END) AS density_per_km2,
         nullif(btrim(g.urban_type), '') AS urban_type,
         coalesce(nullif(btrim(g.assignment_type), ''), a.assignment_type) AS assignment_type,
         coalesce(g.extra, '{}'::jsonb) AS extra
  FROM public.areas a
  JOIN public.districts d ON d.id = a.district_id
  JOIN public.zones z ON z.id = d.zone_id
  LEFT JOIN public.area_geo_data g ON g.area_id = a.id;
COMMENT ON VIEW dashboards.archetype_area_profile IS 'Area attributes for Archetypal Health peer groups, from Geo data: urban type, assignment type (uploaded or typed, else the portal''s), density per km2 (the stored one, else population / size) and the free extra attributes.';

CREATE OR REPLACE VIEW dashboards.area_geo_data AS
  SELECT z.mission_id, z.id AS zone_id, z.name AS zone, d.id AS district_id, d.name AS district,
         a.id AS area_id, a.name AS area, a.active,
         g.population, g.size_km2,
         coalesce(g.density_per_km2,
                  CASE WHEN g.population IS NOT NULL AND g.size_km2 > 0 THEN round(g.population / g.size_km2, 1) END) AS density_per_km2,
         g.households, g.source, g.data_date, coalesce(g.extra, '{}'::jsonb) AS extra, g.updated_at,
         g.pop_urban_centre, g.pop_dense_urban_cluster, g.pop_semi_dense_urban_cluster, g.pop_suburban,
         g.pop_rural_very_low, g.pop_rural_low, g.area_type, g.urban_type, g.assignment_type
  FROM public.areas a
  JOIN public.districts d ON d.id = a.district_id
  JOIN public.zones z ON z.id = d.zone_id
  LEFT JOIN public.area_geo_data g ON g.area_id = a.id
  WHERE a.active OR g.area_id IS NOT NULL;
COMMENT ON VIEW dashboards.area_geo_data IS 'Geo Data per area: every open area (and older areas with figures). density_per_km2 = the source''s figure, else population / size_km2. source and data_date say where and when the figures are from.';

-- 5. Area data is gone.
DROP VIEW IF EXISTS dashboards.area_profile;
DROP TABLE IF EXISTS public.area_profiles;

-- Rights: the reader keeps the views it had (CREATE OR REPLACE keeps them); stated again to be sure.
REVOKE ALL ON dashboards.area_geo_data, dashboards.archetype_area_profile FROM PUBLIC, anon, authenticated, service_role;
GRANT SELECT ON dashboards.area_geo_data, dashboards.archetype_area_profile TO gfm_dashboard_reader;

-- Check.
DO $$
DECLARE
  found text;
BEGIN
  IF to_regclass('public.area_profiles') IS NOT NULL OR to_regclass('dashboards.area_profile') IS NOT NULL THEN
    RAISE EXCEPTION 'Check failed: Area data is still there.';
  END IF;
  IF EXISTS (SELECT 1 FROM public.roster_import_batches WHERE kind = 'AREA_DATA')
     OR EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'roster_import_batches_kind_check'
                AND pg_get_constraintdef(oid) LIKE '%AREA_DATA%') THEN
    RAISE EXCEPTION 'Check failed: the batch kind AREA_DATA is still there.';
  END IF;
  IF EXISTS (SELECT 1 FROM public.roster_import_changes WHERE table_name = 'area_profiles') THEN
    RAISE EXCEPTION 'Check failed: recorded rows of area_profiles are still in Import history.';
  END IF;

  SELECT string_agg(v, ', ') INTO found
  FROM unnest(ARRAY['dashboards.area_geo_data', 'dashboards.archetype_area_profile']) v
  WHERE NOT has_table_privilege('gfm_dashboard_reader', v, 'SELECT');
  IF found IS NOT NULL THEN RAISE EXCEPTION 'Check failed: gfm_dashboard_reader cannot read %', found; END IF;

  SELECT string_agg(format('%s (%s)', v, r), ', ') INTO found
  FROM unnest(ARRAY['dashboards.area_geo_data', 'dashboards.archetype_area_profile']) v
  CROSS JOIN unnest(ARRAY['public', 'anon', 'authenticated', 'service_role']) r
  WHERE has_table_privilege(r, v, 'SELECT');
  IF found IS NOT NULL THEN RAISE EXCEPTION 'Check failed: these may read the views: %', found; END IF;

  SELECT string_agg(r, ', ') INTO found
  FROM unnest(ARRAY['public', 'anon', 'authenticated', 'service_role', 'gfm_dashboard_reader']) r
  WHERE has_table_privilege(r, 'public.area_geo_data', 'SELECT') OR has_table_privilege(r, 'public.area_geo_data', 'INSERT')
     OR has_table_privilege(r, 'public.area_geo_data', 'UPDATE') OR has_table_privilege(r, 'public.area_geo_data', 'DELETE');
  IF found IS NOT NULL THEN RAISE EXCEPTION 'Check failed: these may use public.area_geo_data directly: %', found; END IF;

  SELECT string_agg(v, ', ') INTO found
  FROM unnest(ARRAY['dashboards.area_geo_data', 'dashboards.archetype_area_profile']) v
  WHERE (SELECT pg_get_userbyid(relowner) FROM pg_class WHERE oid = to_regclass(v)) <> 'postgres'
     OR coalesce((SELECT reloptions FROM pg_class WHERE oid = to_regclass(v)), '{}') @> ARRAY['security_invoker=true'];
  IF found IS NOT NULL THEN RAISE EXCEPTION 'Check failed: not owned by postgres or security_invoker: %', found; END IF;
END $$;

COMMIT;

-- Verify (read-only, after applying), as postgres:
--   docker exec gfm-beta-supabase-db-1 psql -U postgres -d postgres -c 'BEGIN READ ONLY' -c 'SET LOCAL ROLE gfm_dashboard_reader' -c 'SELECT count(*), count(urban_type) FROM dashboards.archetype_area_profile' -c 'ROLLBACK'
