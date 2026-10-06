-- Stewardship in the database: DLs, ZLs and STLs reach only their own district or zone, never the whole mission.
-- Run on Beta only, as supabase_admin, AFTER 027_staff_accounts.sql (and 028-030). Round 6, 28 Sep 2026.
--
-- The rule (the owner, 28 Sep: "ZL can't do other zones and mission"): a ZL or STL sees and changes only their own
-- zone (its districts and areas), a DL only their own district, a missionary only their own area; the AP, the
-- President and the Data Analysts (also as an additional role) the whole mission. Office never widens stewardship.
--
-- Why: a read-only audit of live Beta on 28 Sep, as the real ZL and DL accounts, found no row outside their
-- stewardship in any table, view or function (docs/handoff/round6/rls.md). Two database checks still trusted the
-- account's app_role 'AP' on its own, without a current AP assignment:
-- 1. is_mission_manager_for_area: app_role 'AP' made anyone a mission manager. This helper is behind
--    can_access_area (every plan, answer, person, companionship and missionary row), can_edit_planning_area, the
--    Call-ins write and read checks and the planning lock. app_role is only copied from the leadership rows when an
--    account is linked (sync_user_profile_roles), and live already has an account whose app_role says DL with no
--    current DL assignment. So an AP released to be a ZL, DL or missionary whose app_role still says AP would read
--    and change the whole mission, while portal-api (roles.main_role, which ignores app_role 'AP') treats them as a
--    ZL, DL or missionary. No such account exists on live today.
-- 2. The read policy assigned_languages_read on missionary_language_assignments: the same app_role 'AP' path.
--
-- What changes: the AP is a mission manager only through a current AP assignment in that mission, exactly as 021
-- already decided for can_access_mission and can_access_zone. The President and the Data Analysts are unchanged
-- (app_role PRESIDENT/DATA_ADMIN are set by hand; additional DATA_ADMIN), and so is every other line (027's lines
-- included). The helper keeps its name, arguments, owner, search_path and rights (postgres, authenticated,
-- service_role; never PUBLIC or anon). The live AP accounts keep their access: both have a current AP assignment.
-- Nothing else in the database changes; the other paths the audit found are in portal-api and the presentation
-- manager (see rls.md).
--
-- The last blocks stop (and undo everything) on any problem, and prove the rule with every real leader account in
-- the database: each current DL, ZL and STL without manager rights must reach no area outside their own district,
-- zone or area, and no mission-level check may pass for them (nothing is printed about people).
--
-- Written against 027's helper and 021's policy as live on 28 Sep 2026: the file stops (changing nothing) if either
-- is different (or this file's own version, when it is run again).
--
-- Apply (back up Beta first). supabase_admin is needed because it owns missionary_language_assignments:
--   Get-Content portal-api/migrations/032_stewardship_rls.sql -Raw |
--     docker exec -i gfm-beta-supabase-db-1 psql -U supabase_admin -d postgres -v ON_ERROR_STOP=1
-- Then run 019 again as a check (it must end with COMMIT):
--   Get-Content portal-api/migrations/019_restrict_public_functions.sql -Raw |
--     docker exec -i gfm-beta-supabase-db-1 psql -U supabase_admin -d postgres -v ON_ERROR_STOP=1
-- Safe to run again. The file waits at most 10 seconds for its locks, then stops; run it again a little later.
-- Rollback: portal-api/migrations/032_stewardship_rls_rollback.sql (restores both exactly as live on 28 Sep).
-- Order: roll back 032 BEFORE 027 or 021. Their rollbacks write their own older helper text (with app_role 'AP')
-- over 032's, so rolling one of them back while 032 stays would quietly undo 032's helper change (the policy change
-- would stay). 027 cannot be run again after 032 (its first check stops on the changed helper and changes nothing);
-- a later change to this helper goes into a new migration that keeps the lines marked 027 and 032.
BEGIN;
SET LOCAL lock_timeout = '10s';
-- A fixed search_path, so the policy's fingerprint below does not depend on who runs the file (supabase_admin's own
-- search_path includes auth, which changes how the policy expression is printed).
SET LOCAL search_path = public, pg_temp;

DO $$
DECLARE
  unexpected text;
BEGIN
  IF NOT (SELECT rolsuper FROM pg_roles WHERE rolname = current_user) THEN
    RAISE EXCEPTION 'Run this file as supabase_admin (see its header); % cannot change missionary_language_assignments.', current_user;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'user_profiles'
                   AND column_name = 'home_mission_id') THEN
    RAISE EXCEPTION 'Apply 027_staff_accounts.sql first: this file builds on its helper.';
  END IF;
  -- Whitespace-insensitive fingerprints: 027's helper (live on 28 Sep) and this file's own.
  SELECT string_agg(p.proname, ', ') INTO unexpected
  FROM pg_proc p
  WHERE p.oid = 'public.is_mission_manager_for_area(bigint)'::regprocedure
    AND md5(btrim(regexp_replace(p.prosrc, '\s+', ' ', 'g'))) NOT IN (
        '12cb18294d92f0c78ecc2cfc6bad0bdd', '60ea45ffaa3c8e4029f236e4733f0188');
  IF unexpected IS NOT NULL THEN
    RAISE EXCEPTION 'is_mission_manager_for_area is not the 027 version this file was written against. Carry the change into 032 first (see its header).';
  END IF;
  -- 021's policy (live on 28 Sep) or this file's own.
  IF NOT EXISTS (SELECT 1 FROM pg_policy
                 WHERE polrelid = 'public.missionary_language_assignments'::regclass AND polname = 'assigned_languages_read'
                   AND md5(regexp_replace(pg_get_expr(polqual, polrelid), '\s+', ' ', 'g')) IN (
                       'a3a55e6d62b45b4fd6b0a90c8c0d13c1', 'e93746ac7a040aee00807960edb65be6')) THEN
    RAISE EXCEPTION 'The policy assigned_languages_read is not the 021 version this file was written against. Carry the change into 032 first.';
  END IF;
END $$;

-- 1. The helper: 027's text; only the first condition changed (the lines marked 032).
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

-- Signed-in users, service_role and postgres (owner). Never PUBLIC or anon.
REVOKE ALL ON FUNCTION public.is_mission_manager_for_area(bigint) FROM PUBLIC, anon;
GRANT EXECUTE ON FUNCTION public.is_mission_manager_for_area(bigint) TO postgres, authenticated, service_role;

-- 2. Language assignments: 021's policy without app_role 'AP' (the AP reads through the current AP assignment).
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
          AND (up.app_role = ANY (ARRAY['PRESIDENT','DATA_ADMIN']) OR 'DATA_ADMIN' = ANY(up.additional_roles)
               OR ap.mission_id IS NOT NULL)
    )
);

-- Checks: stop (and undo everything above) on any problem.
DO $$
DECLARE
  found text;
BEGIN
  SELECT string_agg(p.oid::regprocedure::text, ', ') INTO found
  FROM pg_proc p
  WHERE p.oid = 'public.is_mission_manager_for_area(bigint)'::regprocedure
    AND (NOT p.prosecdef OR pg_get_userbyid(p.proowner) <> 'postgres'
         OR NOT coalesce(p.proconfig, '{}') @> ARRAY['search_path=public, pg_temp']
         OR p.prosrc LIKE '%''AP'',''PRESIDENT''%' OR p.prosrc NOT LIKE '%home_mission_id%'
         OR has_function_privilege('public', p.oid, 'EXECUTE') OR has_function_privilege('anon', p.oid, 'EXECUTE')
         OR NOT has_function_privilege('authenticated', p.oid, 'EXECUTE')
         OR NOT has_function_privilege('service_role', p.oid, 'EXECUTE'));
  IF found IS NOT NULL THEN
    RAISE EXCEPTION 'Unexpected owner, search_path, body or EXECUTE rights on: %', found;
  END IF;
  -- No access check left that trusts app_role 'AP': the is_*/can_* helpers and every policy in public and portal.
  SELECT string_agg(p.proname, ', ') INTO found
  FROM pg_proc p
  WHERE p.pronamespace = 'public'::regnamespace AND p.prosecdef AND p.proname ~ '^(is_|can_)'
    AND p.prosrc ~ 'app_role\s*(=|IN|=\s*ANY)\s*\(?[^)]*''AP''';
  IF found IS NOT NULL THEN
    RAISE EXCEPTION 'These functions still trust app_role ''AP'': %', found;
  END IF;
  SELECT string_agg(tablename || '.' || policyname, ', ') INTO found
  FROM pg_policies WHERE schemaname IN ('public', 'portal') AND coalesce(qual, '') || coalesce(with_check, '') ~ 'app_role[^)]*''AP''';
  IF found IS NOT NULL THEN
    RAISE EXCEPTION 'These policies still trust app_role ''AP'': %', found;
  END IF;
END $$;

-- Proof with the real accounts: every current DL, ZL or STL without manager rights (no current AP assignment, not
-- President or Data Analyst) reaches only their own district or zone (and their own area). Only counts are used.
DO $$
DECLARE
  leader record;
  outside bigint;
  checked integer := 0;
BEGIN
  FOR leader IN
    SELECT up.id, up.missionary_id
    FROM public.user_profiles up
    WHERE up.active AND up.missionary_id IS NOT NULL
      AND up.app_role NOT IN ('PRESIDENT', 'DATA_ADMIN') AND NOT ('DATA_ADMIN' = ANY(up.additional_roles))
      AND EXISTS (SELECT 1 FROM public.leadership_assignments la WHERE la.missionary_id = up.missionary_id
                    AND la.role IN ('DL', 'ZL', 'STL') AND la.start_date <= CURRENT_DATE
                    AND (la.end_date IS NULL OR la.end_date >= CURRENT_DATE))
      AND NOT EXISTS (SELECT 1 FROM public.leadership_assignments la WHERE la.missionary_id = up.missionary_id
                        AND la.role = 'AP' AND la.start_date <= CURRENT_DATE
                        AND (la.end_date IS NULL OR la.end_date >= CURRENT_DATE))
  LOOP
    PERFORM set_config('request.jwt.claims', json_build_object('sub', leader.id, 'role', 'authenticated')::text, true);
    SELECT count(*) INTO outside
    FROM public.areas a JOIN public.districts d ON d.id = a.district_id
    WHERE (public.can_access_area(a.id) OR public.is_mission_manager_for_area(a.id)
           OR public.can_edit_planning_area(a.id) OR public.can_unlock_planning_area(a.id))
      AND NOT EXISTS (SELECT 1 FROM public.leadership_assignments la WHERE la.missionary_id = leader.missionary_id
                        AND la.start_date <= CURRENT_DATE AND (la.end_date IS NULL OR la.end_date >= CURRENT_DATE)
                        AND ((la.role = 'DL' AND la.district_id = d.id) OR (la.role IN ('ZL', 'STL') AND la.zone_id = d.zone_id)))
      AND NOT EXISTS (SELECT 1 FROM public.missionary_assignments ma WHERE ma.missionary_id = leader.missionary_id
                        AND ma.area_id = a.id AND ma.start_date <= CURRENT_DATE
                        AND (ma.end_date IS NULL OR ma.end_date >= CURRENT_DATE));
    IF outside > 0 THEN
      RAISE EXCEPTION 'A leader account reaches % area(s) outside their stewardship.', outside;
    END IF;
    IF EXISTS (SELECT 1 FROM public.missions m WHERE public.can_access_mission(m.id) OR public.can_view_call_in('mission', m.id))
       OR EXISTS (SELECT 1 FROM public.areas a WHERE public.is_mission_manager_for_area(a.id)) THEN
      RAISE EXCEPTION 'A leader account passes a mission-level check.';
    END IF;
    checked := checked + 1;
  END LOOP;
  PERFORM set_config('request.jwt.claims', '', true);
  RAISE NOTICE 'Migration 032: stewardship proven for % leader account(s) (DL, ZL, STL without manager rights).', checked;
END $$;

COMMIT;
