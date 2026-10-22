-- Rollback of migration 060: dashboards.roster_area_week as migration 059 made it (no unit, no companionships).
-- Run as supabase_admin, after going back to the portal-api image before round 28.
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

DROP VIEW IF EXISTS dashboards.roster_area_week;
CREATE VIEW dashboards.roster_area_week AS
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
