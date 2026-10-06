-- Rollback of 032_stewardship_rls.sql: is_mission_manager_for_area and the policy assigned_languages_read go back to
-- exactly their text before 032 (027's helper and 021's policy, as live on 28 Sep 2026), so app_role 'AP' alone again
-- makes an account a mission manager. Run on Beta only, as supabase_admin (it owns missionary_language_assignments).
-- Roll back 032 BEFORE 027 or 021 (their rollbacks write older helper text over 032's; see 032's header).
-- Roll back the portal-api and Slidev manager code of round 6 separately (docs/handoff/round6/rls.md); the code does
-- not depend on 032 and 032 does not depend on the code.
--
-- Apply:
--   Get-Content portal-api/migrations/032_stewardship_rls_rollback.sql -Raw |
--     docker exec -i gfm-beta-supabase-db-1 psql -U supabase_admin -d postgres -v ON_ERROR_STOP=1
-- Then run 019 again as a check (it must end with COMMIT). Safe to run again; it prints the two fingerprints, which
-- must be 12cb18294d92f0c78ecc2cfc6bad0bdd (helper) and a3a55e6d62b45b4fd6b0a90c8c0d13c1 (policy), as on live before.
BEGIN;
SET LOCAL lock_timeout = '10s';
SET LOCAL search_path = public, pg_temp;

DO $$
BEGIN
  IF NOT (SELECT rolsuper FROM pg_roles WHERE rolname = current_user) THEN
    RAISE EXCEPTION 'Run this file as supabase_admin (see its header); % cannot change missionary_language_assignments.', current_user;
  END IF;
END $$;

-- 1. 027's helper, unchanged.
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
              -- 027: a President or Data Analyst account without a missionary link, in its home mission
              OR (up.missionary_id IS NULL AND up.home_mission_id = tz.mission_id
                  AND (up.app_role IN ('PRESIDENT','DATA_ADMIN') OR 'DATA_ADMIN' = ANY(up.additional_roles)))
          )
    );
$function$;


REVOKE ALL ON FUNCTION public.is_mission_manager_for_area(bigint) FROM PUBLIC, anon;
GRANT EXECUTE ON FUNCTION public.is_mission_manager_for_area(bigint) TO postgres, authenticated, service_role;

-- 2. 021's policy, unchanged.
ALTER POLICY assigned_languages_read ON public.missionary_language_assignments
USING (
    (missionary_id IN (SELECT up.missionary_id FROM public.user_profiles up WHERE up.id = auth.uid() AND up.active))
    OR EXISTS (
        SELECT 1
        FROM public.user_profiles up
        LEFT JOIN LATERAL (
            SELECT la.mission_id FROM public.leadership_assignments la
            WHERE la.missionary_id = up.missionary_id AND la.role = 'AP' AND la.start_date <= CURRENT_DATE
              AND (la.end_date IS NULL OR la.end_date >= CURRENT_DATE)
            ORDER BY la.start_date DESC, la.id DESC LIMIT 1
        ) ap ON true
        LEFT JOIN LATERAL (
            SELECT own.mission_id FROM public.current_missionary_assignments own
            WHERE own.missionary_id = up.missionary_id
            ORDER BY own.start_date DESC, own.assignment_id DESC LIMIT 1
        ) own_scope ON true
        JOIN LATERAL (
            SELECT target.mission_id FROM public.current_missionary_assignments target
            WHERE target.missionary_id = missionary_language_assignments.missionary_id
            ORDER BY target.start_date DESC, target.assignment_id DESC LIMIT 1
        ) target_scope ON target_scope.mission_id = COALESCE(ap.mission_id, own_scope.mission_id)
        WHERE up.id = auth.uid() AND up.active
          AND (up.app_role = ANY (ARRAY['AP','PRESIDENT','DATA_ADMIN']) OR 'DATA_ADMIN' = ANY(up.additional_roles)
               OR ap.mission_id IS NOT NULL)
    )
);

-- Check: exactly the text before 032.
DO $$
DECLARE
  helper text;
  policy text;
BEGIN
  SELECT md5(btrim(regexp_replace(p.prosrc, '\s+', ' ', 'g'))) INTO helper
  FROM pg_proc p WHERE p.oid = 'public.is_mission_manager_for_area(bigint)'::regprocedure;
  SELECT md5(regexp_replace(pg_get_expr(polqual, polrelid), '\s+', ' ', 'g')) INTO policy
  FROM pg_policy WHERE polrelid = 'public.missionary_language_assignments'::regclass AND polname = 'assigned_languages_read';
  RAISE NOTICE 'fingerprint helper % policy %', helper, policy;
  IF helper IS DISTINCT FROM '12cb18294d92f0c78ecc2cfc6bad0bdd' OR policy IS DISTINCT FROM 'a3a55e6d62b45b4fd6b0a90c8c0d13c1' THEN
    RAISE EXCEPTION 'The restored helper or policy is not the text from before 032.';
  END IF;
  IF has_function_privilege('public', 'public.is_mission_manager_for_area(bigint)'::regprocedure, 'EXECUTE')
     OR has_function_privilege('anon', 'public.is_mission_manager_for_area(bigint)'::regprocedure, 'EXECUTE') THEN
    RAISE EXCEPTION 'PUBLIC or anon can run is_mission_manager_for_area.';
  END IF;
END $$;

COMMIT;
