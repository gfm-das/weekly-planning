-- Migration 059 (Oct 2026, round 27): roster counts for slides ("State of the mission").
-- Run on Beta only, as supabase_admin. Back up first (CLAUDE.md, "Before any database change").
--
-- Why: a deck should show, live from the database, how many companionships served each week (to show the key
-- indicators per companionship), how many church units have missionaries, and how many elders and sisters serve.
-- The deck charts read only the dashboards views as gfm_dashboard_reader (charts.py), so the counts come as a view.
--
-- What changes: one new view, dashboards.roster_area_week: one row per area and reporting Sunday (the Sundays that
-- have weekly plans, from dashboards.people_mission_week) on which at least one missionary was assigned to the area
-- (public.missionary_assignments: start_date <= Sunday and end_date empty or >= Sunday). Columns: mission, zone,
-- district and area (ids and names), the area's church unit id, and three counts: missionaries, elders, sisters
-- (public.missionaries.missionary_type: a type that contains "sister" is a sister, one that contains "elder" an
-- elder; any other type is counted only in missionaries). One area with missionaries = one companionship.
-- No person is stored or shown: only counts per area and week. Nothing else changes.
--
-- Apply (back up Beta first). Join the lines with plain line feeds:
--   (Get-Content portal-api/migrations/059_roster_counts.sql) -join "`n" |
--     docker exec -i gfm-beta-supabase-db-1 psql -U supabase_admin -d postgres -v ON_ERROR_STOP=1
-- Then run 019_restrict_public_functions.sql again as a check, as after every migration. Apply it BEFORE the new
-- portal-api image (its roster charts read this view). Safe to run again (CREATE OR REPLACE VIEW).
-- Rollback: 059_roster_counts_rollback.sql (drops the view).
BEGIN;
SET LOCAL lock_timeout = '10s';

DO $$
BEGIN
  IF session_user NOT IN ('supabase_admin', 'postgres') THEN
    RAISE EXCEPTION 'Run this file as supabase_admin (see its header), not as %.', session_user;
  END IF;
  IF to_regclass('dashboards.people_mission_week') IS NULL OR to_regclass('public.missionary_assignments') IS NULL THEN
    RAISE EXCEPTION 'Apply migration 025 (dashboards.people_mission_week) first.';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'gfm_dashboard_reader') THEN
    RAISE EXCEPTION 'The role gfm_dashboard_reader is missing (migration 018).';
  END IF;
END $$;

SET LOCAL ROLE postgres;

CREATE OR REPLACE VIEW dashboards.roster_area_week AS
SELECT w.sunday,
       z.mission_id,
       z.id AS zone_id, z.name AS zone,
       d.id AS district_id, d.name AS district,
       a.id AS area_id, a.name AS area,
       a.unit_id,
       count(DISTINCT ma.missionary_id)::bigint AS missionaries,
       count(DISTINCT ma.missionary_id) FILTER (WHERE lower(coalesce(m.missionary_type, '')) LIKE '%sister%')::bigint AS sisters,
       count(DISTINCT ma.missionary_id) FILTER (WHERE lower(coalesce(m.missionary_type, '')) NOT LIKE '%sister%'
                                               AND lower(coalesce(m.missionary_type, '')) LIKE '%elder%')::bigint AS elders
FROM dashboards.people_mission_week w
JOIN public.zones z ON z.mission_id = w.mission_id
JOIN public.districts d ON d.zone_id = z.id
JOIN public.areas a ON a.district_id = d.id
JOIN public.missionary_assignments ma ON ma.area_id = a.id AND ma.start_date <= w.sunday
     AND (ma.end_date IS NULL OR ma.end_date >= w.sunday)
JOIN public.missionaries m ON m.id = ma.missionary_id
GROUP BY w.sunday, z.mission_id, z.id, z.name, d.id, d.name, a.id, a.name, a.unit_id;

COMMENT ON VIEW dashboards.roster_area_week IS
  'Migration 059: missionaries, elders and sisters per area and reporting Sunday (areas with at least one missionary). Counts only.';

REVOKE ALL ON dashboards.roster_area_week FROM PUBLIC;
GRANT SELECT ON dashboards.roster_area_week TO gfm_dashboard_reader;

RESET ROLE;

DO $$
BEGIN
  IF NOT has_table_privilege('gfm_dashboard_reader', 'dashboards.roster_area_week', 'SELECT') THEN
    RAISE EXCEPTION 'gfm_dashboard_reader cannot read dashboards.roster_area_week.';
  END IF;
  IF has_table_privilege('gfm_dashboard_reader', 'public.missionaries', 'SELECT') THEN
    RAISE EXCEPTION 'gfm_dashboard_reader must not read public.missionaries.';
  END IF;
END $$;

COMMIT;
