-- Rollback of 027_staff_accounts.sql: staff accounts (no missionary link) lose their home mission again.
-- Run on Beta only, as supabase_admin.
--
-- What it does:
-- 1. is_mission_manager_for_area, can_access_mission and can_access_zone go back to exactly 021's text (the
--    "027" lines are removed): a President or Data Analyst without a missionary link no longer counts as being in a
--    mission.
-- 2. current_user_context and current_user_scope go back to 021's definitions, except that the last column
--    home_mission_id stays and is always NULL, and display_name comes only from the missionary again. The column
--    cannot be dropped without dropping public.current_mission_areas (it depends on current_user_context), so it is
--    kept empty instead: portal-api and DA Management then refuse staff accounts as before 027. Both views stay
--    security_invoker = true.
-- 3. user_profiles.home_mission_id and display_name, their constraints and their data stay (nothing reads them
--    through the views any more); re-applying 027 brings the accounts back as they were.
-- 4. roster_import_batches.kind goes back to TRANSFER and HISTORICAL only if no ACCOUNT batch was recorded; otherwise
--    it keeps ACCOUNT, so those Import history entries stay valid (a NOTICE says so).
-- Also roll back the portal-api and roster-importer images of the same change (see docs/handoff/round2/accounts.md).
-- Roll back 027 before 021 (never 021 alone while 027 is applied), and do not run 021_additional_roles.sql again
-- afterwards: the kept home_mission_id column makes it stop with "cannot drop columns from view" (see 027's header).
--
-- Apply:
--   Get-Content portal-api/migrations/027_staff_accounts_rollback.sql -Raw |
--     docker exec -i gfm-beta-supabase-db-1 psql -U supabase_admin -d postgres -v ON_ERROR_STOP=1
-- Then run 019 again as a check (it must end with COMMIT). Safe to run again.
BEGIN;
SET LOCAL lock_timeout = '10s';

DO $$
BEGIN
  IF NOT (SELECT rolsuper FROM pg_roles WHERE rolname = current_user) THEN
    RAISE EXCEPTION 'Run this file as supabase_admin (see its header); % cannot change roster_import_batches.', current_user;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'current_user_context'
                   AND column_name = 'home_mission_id') THEN
    RAISE EXCEPTION '027 is not applied here (current_user_context has no home_mission_id): nothing to roll back.';
  END IF;
END $$;

-- 2. The views: 021's definitions with an empty home_mission_id as the last column.
CREATE OR REPLACE VIEW public.current_user_context
WITH (security_invoker = true) AS
SELECT up.id AS user_id,
    up.app_role,
    up.active AS user_active,
    m.id AS missionary_id,
    m.missionary_number,
    m.display_name,
    m.missionary_type,
    m.status AS missionary_status,
    ma.id AS missionary_assignment_id,
    ma.start_date AS assignment_start_date,
    ma.roster_position,
    ma.roster_position_abbr,
    ma.special_assignment,
    a.id AS area_id,
    a.area_code,
    a.name AS area,
    a.assignment_type AS area_assignment_type,
    d.id AS district_id,
    d.name AS district,
    z.id AS zone_id,
    z.name AS zone,
    mi.id AS mission_id,
    mi.name AS mission,
    la.role AS leadership_role,
    up.additional_roles,
    NULL::bigint AS home_mission_id  -- 027 rolled back: kept for current_mission_areas, always empty
FROM public.user_profiles up
LEFT JOIN public.missionaries m ON m.id = up.missionary_id
LEFT JOIN public.missionary_assignments ma ON ma.missionary_id = m.id AND ma.start_date <= CURRENT_DATE
      AND (ma.end_date IS NULL OR ma.end_date >= CURRENT_DATE)
LEFT JOIN public.areas a ON a.id = ma.area_id
LEFT JOIN public.districts d ON d.id = a.district_id
LEFT JOIN public.zones z ON z.id = d.zone_id
LEFT JOIN public.missions mi ON mi.id = z.mission_id
LEFT JOIN public.leadership_assignments la ON la.missionary_id = m.id AND la.start_date <= CURRENT_DATE
      AND (la.end_date IS NULL OR la.end_date >= CURRENT_DATE);

CREATE OR REPLACE VIEW public.current_user_scope
WITH (security_invoker = true) AS
SELECT up.id AS user_id,
    up.missionary_id,
    up.app_role,
    cma.area_id,
    cma.area_name,
    cma.district_id,
    cma.district_name,
    cma.zone_id,
    cma.zone_name,
    cma.mission_id,
    cma.mission_name,
    cla.role AS leadership_role,
    cla.district_id AS leadership_district_id,
    cla.district_name AS leadership_district_name,
    cla.zone_id AS leadership_zone_id,
    cla.zone_name AS leadership_zone_name,
    cla.mission_id AS leadership_mission_id,
    cla.mission_name AS leadership_mission_name,
    up.additional_roles,
    NULL::bigint AS home_mission_id  -- 027 rolled back: always empty
FROM public.user_profiles up
LEFT JOIN public.current_missionary_assignments cma ON cma.missionary_id = up.missionary_id
LEFT JOIN public.current_leadership_assignments cla ON cla.missionary_id = up.missionary_id
WHERE up.active = true;

-- 1. The helpers: exactly 021's text.
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
          AND (up.app_role IN ('AP','PRESIDENT','DATA_ADMIN') OR 'DATA_ADMIN' = ANY(up.additional_roles) OR EXISTS (
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
          )
    );
$function$;

CREATE OR REPLACE FUNCTION public.can_access_mission(target_mission_id bigint)
RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = public, pg_temp
AS $function$
    SELECT EXISTS (
        SELECT 1 FROM public.user_profiles up
        WHERE up.id = auth.uid() AND up.active
          AND (
              -- Data Analyst, as the main role or an additional role
              up.app_role = 'DATA_ADMIN' OR 'DATA_ADMIN' = ANY(up.additional_roles)
              -- AP: a current AP assignment in this mission
              OR EXISTS (
                  SELECT 1 FROM public.leadership_assignments la
                  WHERE la.missionary_id = up.missionary_id AND la.role = 'AP'
                    AND la.mission_id = target_mission_id
                    AND la.start_date <= CURRENT_DATE
                    AND (la.end_date IS NULL OR la.end_date >= CURRENT_DATE)
              )
              -- President: a current missionary or leadership assignment in this mission
              OR (up.app_role = 'PRESIDENT' AND (
                  EXISTS (
                      SELECT 1 FROM public.missionary_assignments ma
                      JOIN public.areas a ON a.id = ma.area_id
                      JOIN public.districts d ON d.id = a.district_id
                      JOIN public.zones z ON z.id = d.zone_id
                      WHERE ma.missionary_id = up.missionary_id
                        AND ma.start_date <= CURRENT_DATE
                        AND (ma.end_date IS NULL OR ma.end_date >= CURRENT_DATE)
                        AND z.mission_id = target_mission_id
                  )
                  OR EXISTS (
                      SELECT 1 FROM public.leadership_assignments la
                      LEFT JOIN public.districts ld ON ld.id = la.district_id
                      LEFT JOIN public.zones lz ON lz.id = coalesce(la.zone_id, ld.zone_id)
                      WHERE la.missionary_id = up.missionary_id
                        AND la.start_date <= CURRENT_DATE
                        AND (la.end_date IS NULL OR la.end_date >= CURRENT_DATE)
                        AND coalesce(la.mission_id, lz.mission_id) = target_mission_id
                  )
              ))
          )
    );
$function$;

CREATE OR REPLACE FUNCTION public.can_access_zone(target_zone_id bigint)
RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = public, pg_temp
AS $function$
    SELECT EXISTS (
        SELECT 1 FROM public.user_profiles up
        JOIN public.zones tz ON tz.id = target_zone_id
        WHERE up.id = auth.uid() AND up.active
          AND (
              -- ZL: a current ZL assignment on this zone (STLs have no part in Call-ins)
              EXISTS (
                  SELECT 1 FROM public.leadership_assignments la
                  WHERE la.missionary_id = up.missionary_id AND la.role = 'ZL'
                    AND la.zone_id = target_zone_id
                    AND la.start_date <= CURRENT_DATE
                    AND (la.end_date IS NULL OR la.end_date >= CURRENT_DATE)
              )
              -- AP: a current AP assignment in the zone's mission
              OR EXISTS (
                  SELECT 1 FROM public.leadership_assignments la
                  WHERE la.missionary_id = up.missionary_id AND la.role = 'AP'
                    AND la.mission_id = tz.mission_id
                    AND la.start_date <= CURRENT_DATE
                    AND (la.end_date IS NULL OR la.end_date >= CURRENT_DATE)
              )
              -- President and Data Analyst (main or additional role): a current missionary or leadership assignment
              -- in the zone's mission, as in is_mission_manager_for_area
              OR ((up.app_role IN ('PRESIDENT','DATA_ADMIN') OR 'DATA_ADMIN' = ANY(up.additional_roles)) AND (
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
              ))
          )
    );
$function$;

REVOKE ALL ON FUNCTION public.is_mission_manager_for_area(bigint), public.can_access_mission(bigint),
    public.can_access_zone(bigint)
  FROM PUBLIC, anon;
GRANT EXECUTE ON FUNCTION public.is_mission_manager_for_area(bigint), public.can_access_mission(bigint),
    public.can_access_zone(bigint)
  TO postgres, authenticated, service_role;

-- 4. Import history kinds.
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM public.roster_import_batches WHERE kind = 'ACCOUNT') THEN
    RAISE NOTICE 'roster_import_batches keeps kind ACCOUNT: % account batches are recorded.',
      (SELECT count(*) FROM public.roster_import_batches WHERE kind = 'ACCOUNT');
  ELSE
    ALTER TABLE public.roster_import_batches DROP CONSTRAINT IF EXISTS roster_import_batches_kind_check;
    ALTER TABLE public.roster_import_batches ADD CONSTRAINT roster_import_batches_kind_check
      CHECK (kind IN ('TRANSFER', 'HISTORICAL'));
  END IF;
END $$;

-- Checks: the helpers and views are 021's again (same fingerprints 027 checks for), with the usual rights.
DO $$
DECLARE
  found text;
BEGIN
  SELECT string_agg(p.proname, ', ') INTO found
  FROM pg_proc p
  WHERE p.pronamespace = 'public'::regnamespace
    AND p.proname IN ('is_mission_manager_for_area', 'can_access_mission', 'can_access_zone')
    AND md5(btrim(regexp_replace(p.prosrc, '\s+', ' ', 'g'))) NOT IN (
        '00b7e65493c07021b529d943ad527fc6', '8ca67f04cac806c53c1bb1c35101947a', '83f3e577f11884b09988240fe493408c');
  IF found IS NOT NULL THEN
    RAISE EXCEPTION 'These helpers are not 021''s text after the rollback: %', found;
  END IF;
  SELECT string_agg(c.oid::regclass::text, ', ') INTO found
  FROM pg_class c
  WHERE c.oid IN ('public.current_user_context'::regclass, 'public.current_user_scope'::regclass)
    AND (NOT coalesce(c.reloptions, '{}') @> ARRAY['security_invoker=true'] OR pg_get_userbyid(c.relowner) <> 'postgres');
  IF found IS NOT NULL THEN
    RAISE EXCEPTION 'These views must check row-level security as the caller and belong to postgres: %', found;
  END IF;
  SELECT string_agg(p.oid::regprocedure::text, ', ') INTO found
  FROM pg_proc p
  WHERE p.oid IN ('public.is_mission_manager_for_area(bigint)'::regprocedure, 'public.can_access_mission(bigint)'::regprocedure,
                  'public.can_access_zone(bigint)'::regprocedure)
    AND (NOT p.prosecdef OR NOT coalesce(p.proconfig, '{}') @> ARRAY['search_path=public, pg_temp']
         OR has_function_privilege('public', p.oid, 'EXECUTE') OR has_function_privilege('anon', p.oid, 'EXECUTE')
         OR NOT has_function_privilege('authenticated', p.oid, 'EXECUTE')
         OR NOT has_function_privilege('service_role', p.oid, 'EXECUTE'));
  IF found IS NOT NULL THEN
    RAISE EXCEPTION 'Unexpected search_path or EXECUTE rights on: %', found;
  END IF;
  IF EXISTS (SELECT 1 FROM public.current_user_context WHERE home_mission_id IS NOT NULL) THEN
    RAISE EXCEPTION 'current_user_context still shows a home mission.';
  END IF;
END $$;

NOTIFY pgrst, 'reload schema';
COMMIT;
