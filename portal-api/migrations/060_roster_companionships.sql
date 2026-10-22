-- Migration 060 (Oct 2026, round 28): distinct companionships per week, and church unit names, for roster slides.
-- Run on Beta only, as supabase_admin. Back up first (CLAUDE.md, "Before any database change").
--
-- Why: 059 counted one companionship per area with missionaries. An area can hold more than one companionship, so
-- "per companionship" numbers were divided by too few. Slides also need missionaries per church unit by name.
--
-- What changes: dashboards.roster_area_week gets two more columns (at the end; the others stay as they are):
--   unit           the area's church unit name (public.units.name), empty when the area has no unit.
--   companionships the distinct companionships active in the area that Sunday: rows of public.companionships for
--                  the area with start_date <= Sunday <= end_date (or no end_date) that have at least one member
--                  (public.companionship_members, joined <= Sunday <= left or not left) assigned to the area that
--                  Sunday. An area with missionaries but no such row (the companionships table is filled only by
--                  the importer) counts as one companionship: the missionaries assigned there together.
-- Still counts only; no person is stored or shown.
--
-- Apply (back up Beta first). Join the lines with plain line feeds:
--   (Get-Content portal-api/migrations/060_roster_companionships.sql) -join "`n" |
--     docker exec -i gfm-beta-supabase-db-1 psql -U supabase_admin -d postgres -v ON_ERROR_STOP=1
-- Then run 019_restrict_public_functions.sql again as a check. Apply it BEFORE the new portal-api image (its roster
-- charts read the new columns). Safe to run again (CREATE OR REPLACE VIEW).
-- Rollback: 060_roster_companionships_rollback.sql (the 059 view again).
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
  IF to_regclass('dashboards.roster_area_week') IS NULL THEN
    RAISE EXCEPTION 'Apply migration 059 (dashboards.roster_area_week) first.';
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
                                               AND lower(coalesce(m.missionary_type, '')) LIKE '%elder%')::bigint AS elders,
       coalesce(u.name, '') AS unit,
       greatest(1, (SELECT count(DISTINCT c.id)
                    FROM public.companionships c
                    JOIN public.companionship_members cm ON cm.companionship_id = c.id
                         AND (cm.joined_date IS NULL OR cm.joined_date <= w.sunday)
                         AND (cm.left_date IS NULL OR cm.left_date >= w.sunday)
                    JOIN public.missionary_assignments cma ON cma.missionary_id = cm.missionary_id AND cma.area_id = a.id
                         AND cma.start_date <= w.sunday AND (cma.end_date IS NULL OR cma.end_date >= w.sunday)
                    WHERE c.area_id = a.id AND c.start_date <= w.sunday
                      AND (c.end_date IS NULL OR c.end_date >= w.sunday)))::bigint AS companionships
FROM dashboards.people_mission_week w
JOIN public.zones z ON z.mission_id = w.mission_id
JOIN public.districts d ON d.zone_id = z.id
JOIN public.areas a ON a.district_id = d.id
JOIN public.missionary_assignments ma ON ma.area_id = a.id AND ma.start_date <= w.sunday
     AND (ma.end_date IS NULL OR ma.end_date >= w.sunday)
JOIN public.missionaries m ON m.id = ma.missionary_id
LEFT JOIN public.units u ON u.id = a.unit_id
GROUP BY w.sunday, z.mission_id, z.id, z.name, d.id, d.name, a.id, a.name, a.unit_id, u.name;

COMMENT ON VIEW dashboards.roster_area_week IS
  'Migrations 059/060: missionaries, elders, sisters and distinct companionships per area and reporting Sunday (areas with at least one missionary), with the church unit name. Counts only.';

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
