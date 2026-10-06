-- Rollback of 037_faster_access_checks.sql: can_access_area and is_mission_manager_for_area in plain SQL again,
-- exactly as migrations 013 and 032 wrote them. They give the same answers either way; only slower.
--
-- Apply as supabase_admin:
--   Get-Content portal-api/migrations/037_faster_access_checks_rollback.sql -Raw |
--     docker exec -i gfm-beta-supabase-db-1 psql -U supabase_admin -d postgres -v ON_ERROR_STOP=1
-- Then run 019 again (it must end with COMMIT). Safe to run again.
BEGIN;
SET LOCAL lock_timeout = '10s';

DO $$
BEGIN
  IF NOT (SELECT rolsuper FROM pg_roles WHERE rolname = current_user) THEN
    RAISE EXCEPTION 'Run this file as supabase_admin (see its header), not as %.', current_user;
  END IF;
  IF to_regprocedure('public.can_access_area(bigint)') IS NULL
     OR to_regprocedure('public.is_mission_manager_for_area(bigint)') IS NULL THEN
    RAISE EXCEPTION 'Nothing to roll back: an access check is missing (migrations 013 and 032).';
  END IF;
END $$;

CREATE TEMPORARY TABLE access_checks_before ON COMMIT DROP AS
SELECT p.oid, p.proname, pg_get_userbyid(p.proowner) AS owner, p.prosecdef, p.provolatile, p.proconfig,
       p.proacl::text AS rights
FROM pg_proc p
WHERE p.oid IN ('public.can_access_area(bigint)'::regprocedure, 'public.is_mission_manager_for_area(bigint)'::regprocedure);

SET LOCAL ROLE postgres;

-- 1. Exactly as in 032_stewardship_rls.sql.
CREATE OR REPLACE FUNCTION public.is_mission_manager_for_area(target_area_id bigint)
RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = public, pg_temp
AS $function$
    SELECT EXISTS (
        SELECT 1 FROM public.user_profiles up
        JOIN public.areas target ON target.id = target_area_id
        JOIN public.districts td ON td.id = target.district_id
        JOIN public.zones tz ON tz.id = td.zone_id
        WHERE up.id = auth.uid() AND up.active
          -- 032: President and Data Analyst (main or additional role), or an AP through a current AP assignment in
          -- this mission. app_role 'AP' alone no longer counts (it is not updated when an AP is released).
          AND (up.app_role IN ('PRESIDENT','DATA_ADMIN') OR 'DATA_ADMIN' = ANY(up.additional_roles) OR EXISTS (
              SELECT 1 FROM public.leadership_assignments effective_ap
              LEFT JOIN public.districts ap_district ON ap_district.id = effective_ap.district_id
              LEFT JOIN public.zones ap_zone ON ap_zone.id = coalesce(effective_ap.zone_id, ap_district.zone_id)
              WHERE effective_ap.missionary_id = up.missionary_id
                AND effective_ap.role = 'AP'
                AND effective_ap.start_date <= CURRENT_DATE
                AND (effective_ap.end_date IS NULL OR effective_ap.end_date >= CURRENT_DATE)
                AND coalesce(effective_ap.mission_id, ap_zone.mission_id) = tz.mission_id
          ))
          AND (
              EXISTS (
                  SELECT 1 FROM public.missionary_assignments ma
                  JOIN public.areas a ON a.id = ma.area_id
                  JOIN public.districts d ON d.id = a.district_id
                  JOIN public.zones z ON z.id = d.zone_id
                  WHERE ma.missionary_id = up.missionary_id
                    AND ma.start_date <= CURRENT_DATE
                    AND (ma.end_date IS NULL OR ma.end_date >= CURRENT_DATE)
                    AND z.mission_id = tz.mission_id
              )
              OR EXISTS (
                  SELECT 1 FROM public.leadership_assignments la
                  LEFT JOIN public.districts ld ON ld.id = la.district_id
                  LEFT JOIN public.zones lz ON lz.id = coalesce(la.zone_id, ld.zone_id)
                  WHERE la.missionary_id = up.missionary_id
                    AND la.start_date <= CURRENT_DATE
                    AND (la.end_date IS NULL OR la.end_date >= CURRENT_DATE)
                    AND coalesce(la.mission_id, lz.mission_id) = tz.mission_id
              )
              -- 027: a President or Data Analyst account without a missionary link, in its home mission
              OR (up.missionary_id IS NULL AND up.home_mission_id = tz.mission_id
                  AND (up.app_role IN ('PRESIDENT','DATA_ADMIN') OR 'DATA_ADMIN' = ANY(up.additional_roles)))
          )
    );
$function$;

-- 2. Exactly as in 013_planning_permissions.sql.
CREATE OR REPLACE FUNCTION public.can_access_area(target_area_id bigint)
RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = public, pg_temp
AS $function$
    SELECT public.is_mission_manager_for_area(target_area_id) OR EXISTS (
        SELECT 1 FROM public.user_profiles up
        JOIN public.areas a ON a.id = target_area_id
        JOIN public.districts d ON d.id = a.district_id
        JOIN public.zones z ON z.id = d.zone_id
        WHERE up.id = auth.uid() AND up.active
          AND (
              EXISTS (
                  SELECT 1 FROM public.missionary_assignments ma
                  WHERE ma.missionary_id = up.missionary_id AND ma.area_id = target_area_id
                    AND ma.start_date <= CURRENT_DATE
                    AND (ma.end_date IS NULL OR ma.end_date >= CURRENT_DATE)
              )
              OR EXISTS (
                  SELECT 1 FROM public.leadership_assignments la
                  WHERE la.missionary_id = up.missionary_id
                    AND la.start_date <= CURRENT_DATE
                    AND (la.end_date IS NULL OR la.end_date >= CURRENT_DATE)
                    AND ((la.role = 'DL' AND la.district_id = d.id)
                         OR (la.role IN ('ZL','STL') AND la.zone_id = z.id))
              )
          )
    );
$function$;

RESET ROLE;

-- Check: the SQL texts of 013 and 032 are back (md5, line ends ignored), with the same owner, settings and rights.
DO $$
BEGIN
  IF EXISTS (
    SELECT 1
    FROM (VALUES ('public.can_access_area(bigint)', '12d62d4109a13f3c07d1bd4b77cb198a'),
                 ('public.is_mission_manager_for_area(bigint)', 'b3d5c725c02a16125618451f8721754e')) AS want(sig, body)
    JOIN pg_proc p ON p.oid = to_regprocedure(want.sig)
    JOIN pg_language l ON l.oid = p.prolang
    JOIN access_checks_before b ON b.oid = p.oid
    WHERE l.lanname <> 'sql' OR md5(replace(p.prosrc, E'\r', '')) <> want.body
       OR pg_get_userbyid(p.proowner) <> b.owner OR p.prosecdef <> b.prosecdef OR p.provolatile <> b.provolatile
       OR p.proconfig IS DISTINCT FROM b.proconfig OR p.proacl::text IS DISTINCT FROM b.rights
  ) THEN
    RAISE EXCEPTION 'Rollback of 037: an access check is not the 013 / 032 SQL version.';
  END IF;
  RAISE NOTICE 'Rollback of 037: can_access_area and is_mission_manager_for_area run in SQL again.';
END $$;

COMMIT;
