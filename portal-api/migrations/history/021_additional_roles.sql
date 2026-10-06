-- Additional roles: a person keeps one main role and may also be "Data Analyst" and/or "Office". Run on Beta only,
-- as supabase_admin.
--
-- Why: user_profiles.app_role holds a single role, so a DL, ZL, STL or AP could not also be the Data Analyst or work in
-- the office: choosing Data Admin or Office on the DA Management account page ended their leadership assignment.
--
-- What changes:
-- 1. user_profiles.additional_roles text[] NOT NULL DEFAULT '{}', only DATA_ADMIN ("Data Analyst") and OFFICE allowed.
--    Linked accounts whose app_role is DATA_ADMIN or OFFICE (none on Beta on 27 Sep 2026) get that role as an
--    additional role and their main role from their current leadership assignment (AP > ZL > STL > DL, else
--    MISSIONARY), as sync_user_profile_roles() would record it. Accounts without a missionary keep their app_role.
--    After a rollback, the additional roles it saved come back first, but only for accounts whose app_role is still
--    the value the rollback wrote (a role taken away while rolled back stays away); the saved copy is then dropped.
-- 2. current_user_context and current_user_scope get additional_roles as their LAST column (the portal, Slidev,
--    DA Management and Appsmith read them; readers that ignore the column work as before). Both stay
--    security_invoker = true, so a signed-in person still sees only their own rows (the check at the end proves it).
-- 3. An additional Data Analyst counts like app_role DATA_ADMIN in is_mission_manager_for_area, can_access_mission,
--    can_access_zone, can_access_district and is_assignment_admin, and in the two row-level security policies that
--    name DATA_ADMIN (leadership_assignments, missionary_language_assignments). OFFICE gives no database access.
-- 4. can_access_mission: a President passes with a current missionary or leadership assignment in that mission (as in
--    is_mission_manager_for_area; before, a President could never pass because no leadership row is ever PRESIDENT).
--    An AP passes with a current AP assignment in that mission; app_role no longer has to say AP as well.
-- 5. can_access_zone is tightened: it no longer lets every missionary into the zone of their own area (that let anyone
--    read their zone's Call-ins zone notes) and no longer lets app_role AP/PRESIDENT/DATA_ADMIN into every zone.
--    ZL: a current ZL assignment on that zone (app_role is no longer checked; the drifted Beta ZL whose app_role is
--    MISSIONARY keeps access). AP: a current AP assignment in the zone's mission. President and Data Analyst (main or
--    additional): a current missionary or leadership assignment in the zone's mission, the rule of
--    is_mission_manager_for_area.
-- 6. STLs have no part in Call-ins: can_access_zone and can_access_district no longer let an STL in. On Beta on
--    27 Sep 2026 every user of these two helpers is a Call-ins object (the get_zl_call_in_* and get_dl_call_in_*
--    functions, including the 020 summaries, and the policies on call_in_zones, call_in_districts and
--    call_in_area_updates); no view uses them. The check at the end stops if anything else starts using them.
-- 7. The five replaced functions get search_path public, pg_temp, and EXECUTE only for postgres (owner),
--    authenticated and service_role (anon lost it; it could only ever get false). sync_user_profile_roles() can no
--    longer be run by anon or authenticated: it rewrites app_role for every linked account (only
--    link_user_to_missionary, which runs as postgres, calls it).
-- Summaries (020), Call-ins write checks (015), planning checks (013) and the dashboards schema (018) are unchanged;
-- they use these helpers and follow automatically. The three 020 summaries return the same data for the AP, ZL and DL
-- of Beta for their own scopes (checked on a restored copy; see docs/handoff/round2/roles.md).
--
-- Apply (back up Beta first; 018, 019 and 020 must already be applied). supabase_admin is needed because it owns
-- public.missionary_language_assignments (item 3 above). The file is plain ASCII:
--   Get-Content portal-api/migrations/021_additional_roles.sql -Raw |
--     docker exec -i gfm-beta-supabase-db-1 psql -U supabase_admin -d postgres -v ON_ERROR_STOP=1
-- Then run 019 again as a check (it must end with COMMIT):
--   Get-Content portal-api/migrations/019_restrict_public_functions.sql -Raw |
--     docker exec -i gfm-beta-supabase-db-1 psql -U supabase_admin -d postgres -v ON_ERROR_STOP=1
-- Adding the column and replacing the views briefly lock user_profiles and the views. If a long query holds them, the
-- file stops after 10 seconds (lock timeout) instead of making sign-ins wait; run it again a little later.
-- Safe to run again: ADD COLUMN IF NOT EXISTS, a guarded constraint, a restore step that runs only after a rollback,
-- CREATE OR REPLACE, ALTER POLICY, REVOKE/GRANT, then checks that stop (and undo everything) on any problem.
-- Deploy with the portal-api, portal-reminders and DA Management (roster-importer) images of the same change, or
-- apply this file first: code without the change ignores additional_roles (it grants less, never more).
-- Rollback: portal-api/migrations/021_additional_roles_rollback.sql (restores the five functions and the two policies
-- exactly as before, folds additional roles into app_role where it can, saves and clears them; the column and view
-- columns stay, see that file).
BEGIN;
SET LOCAL lock_timeout = '10s';

DO $$
BEGIN
  IF NOT (SELECT rolsuper FROM pg_roles WHERE rolname = current_user) THEN
    RAISE EXCEPTION 'Run this file as supabase_admin (see its header); % cannot change the language policy.', current_user;
  END IF;
END $$;

-- 1. The column. The default is a constant, so adding it does not rewrite the table.
ALTER TABLE public.user_profiles ADD COLUMN IF NOT EXISTS additional_roles text[] NOT NULL DEFAULT '{}';
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid = 'public.user_profiles'::regclass
                   AND conname = 'user_profiles_additional_roles_check') THEN
    ALTER TABLE public.user_profiles ADD CONSTRAINT user_profiles_additional_roles_check
      CHECK (additional_roles <@ ARRAY['DATA_ADMIN','OFFICE']::text[]);
  END IF;
END $$;
COMMENT ON COLUMN public.user_profiles.additional_roles IS
  'Roles held on top of the main role (app_role): DATA_ADMIN ("Data Analyst", manager rights) and OFFICE (calendar editing). Set on the DA Management account page.';

-- After a rollback (021_additional_roles_rollback.sql): give back the additional roles it saved and cleared, but only
-- to accounts whose app_role is still the value the rollback wrote. Another app_role means someone changed the role
-- while rolled back (for example took away Data Admin in the old DA Management), and that change stands. Accounts
-- without a missionary also get their main role back; linked ones get it from the next step. Then drop the copy.
DO $$
DECLARE
  restored bigint;
  saved bigint;
BEGIN
  IF to_regclass('public.user_profiles_additional_roles_021_rollback') IS NULL THEN
    RETURN;  -- no rollback before this run (the usual case)
  END IF;
  EXECUTE 'SELECT count(*) FROM public.user_profiles_additional_roles_021_rollback' INTO saved;
  EXECUTE $sql$
    WITH done AS (
      UPDATE public.user_profiles up
      SET additional_roles = ARRAY(SELECT DISTINCT r FROM unnest(up.additional_roles || saved.additional_roles) r ORDER BY r),
          app_role = CASE WHEN up.missionary_id IS NULL THEN coalesce(saved.app_role_before, up.app_role) ELSE up.app_role END,
          updated_at = now()
      FROM public.user_profiles_additional_roles_021_rollback saved
      WHERE saved.id = up.id AND up.app_role IS NOT DISTINCT FROM saved.app_role_written
      RETURNING 1)
    SELECT count(*) FROM done $sql$ INTO restored;
  RAISE NOTICE 'Additional roles given back to % of % account(s) saved by the rollback; the others changed role since.',
    restored, saved;
  EXECUTE 'DROP TABLE public.user_profiles_additional_roles_021_rollback';
END $$;

-- Linked accounts that have Data Admin or Office as their only role: keep it as an additional role, and record their
-- main role from their current leadership assignments like sync_user_profile_roles(). None on Beta on 27 Sep 2026.
UPDATE public.user_profiles up
SET additional_roles = ARRAY(SELECT DISTINCT r FROM unnest(up.additional_roles || up.app_role) r ORDER BY r),
    app_role = coalesce((
        SELECT la.role FROM public.leadership_assignments la
        WHERE la.missionary_id = up.missionary_id AND la.role IN ('AP','ZL','STL','DL')
          AND la.start_date <= CURRENT_DATE AND (la.end_date IS NULL OR la.end_date >= CURRENT_DATE)
        ORDER BY array_position(ARRAY['AP','ZL','STL','DL'], la.role) LIMIT 1), 'MISSIONARY'),
    updated_at = now()
WHERE up.missionary_id IS NOT NULL AND up.app_role IN ('DATA_ADMIN','OFFICE');

-- 2. The two views: the definitions on Beta before this file, with additional_roles appended as the last column.
-- WITH (security_invoker = true) must be repeated: CREATE OR REPLACE VIEW would otherwise drop it, and every
-- signed-in user could then read everyone's row through PostgREST.
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
    up.additional_roles
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
    up.additional_roles
FROM public.user_profiles up
LEFT JOIN public.current_missionary_assignments cma ON cma.missionary_id = up.missionary_id
LEFT JOIN public.current_leadership_assignments cla ON cla.missionary_id = up.missionary_id
WHERE up.active = true;

-- 3. The helpers. Same names, arguments and return types (grants on them are kept, then set below).
-- As in 013, only the role test gained the additional Data Analyst.
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

-- The mission level (Call-ins mission summary). Data Analyst: any mission, as app_role DATA_ADMIN before.
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

-- The zone level (Call-ins zone summary, zone notes and the other get_zl_* functions).
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

-- The district level. As before, plus the additional Data Analyst, and without STL (Call-ins only).
CREATE OR REPLACE FUNCTION public.can_access_district(target_district_id bigint)
RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = public, pg_temp
AS $function$
    SELECT EXISTS (
        SELECT 1 FROM public.user_profiles up
        JOIN public.districts d ON d.id = target_district_id
        JOIN public.zones z ON z.id = d.zone_id
        WHERE up.id = auth.uid() AND up.active = true
          AND (
              -- President and Data Analyst (main or additional role)
              up.app_role IN ('PRESIDENT','DATA_ADMIN') OR 'DATA_ADMIN' = ANY(up.additional_roles)
              -- Leadership: DL of this district, ZL of its zone, AP of its mission
              OR EXISTS (
                  SELECT 1 FROM public.leadership_assignments la
                  WHERE la.missionary_id = up.missionary_id
                    AND la.start_date <= CURRENT_DATE
                    AND (la.end_date IS NULL OR la.end_date >= CURRENT_DATE)
                    AND ((la.role = 'DL' AND la.district_id = target_district_id)
                         OR (la.role = 'ZL' AND la.zone_id = d.zone_id)
                         OR (la.role = 'AP' AND la.mission_id = z.mission_id))
              )
          )
    );
$function$;

-- Linking accounts and setting special or area assignments (link_user_to_missionary and friends).
CREATE OR REPLACE FUNCTION public.is_assignment_admin()
RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = public, pg_temp
AS $function$
    SELECT EXISTS (
        SELECT 1 FROM public.user_profiles up
        WHERE up.id = auth.uid() AND up.active = true
          AND (up.app_role IN ('PRESIDENT','DATA_ADMIN') OR 'DATA_ADMIN' = ANY(up.additional_roles))
    );
$function$;

-- Signed-in users, service_role and postgres (owner). Never PUBLIC or anon.
REVOKE ALL ON FUNCTION public.is_mission_manager_for_area(bigint), public.can_access_mission(bigint),
    public.can_access_zone(bigint), public.can_access_district(bigint), public.is_assignment_admin()
  FROM PUBLIC, anon;
GRANT EXECUTE ON FUNCTION public.is_mission_manager_for_area(bigint), public.can_access_mission(bigint),
    public.can_access_zone(bigint), public.can_access_district(bigint), public.is_assignment_admin()
  TO postgres, authenticated, service_role;
-- Rewrites app_role for every linked account; only link_user_to_missionary (runs as postgres) calls it.
REVOKE EXECUTE ON FUNCTION public.sync_user_profile_roles() FROM PUBLIC, anon, authenticated;

-- 4. The two policies that name DATA_ADMIN: the expressions on Beta before this file plus the additional role.
ALTER POLICY "Users can read relevant leadership assignments" ON public.leadership_assignments
USING (
    (missionary_id = (SELECT up.missionary_id FROM public.user_profiles up WHERE up.id = (SELECT auth.uid() AS uid)))
    OR EXISTS (
        SELECT 1 FROM public.user_profiles up
        WHERE up.id = (SELECT auth.uid() AS uid)
          AND (up.app_role = 'DATA_ADMIN' OR 'DATA_ADMIN' = ANY(up.additional_roles))
    )
);

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

-- Checks: stop (and undo everything above) on any problem.
DO $$
DECLARE
  found text;
BEGIN
  -- The column and its rule.
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'user_profiles'
                   AND column_name = 'additional_roles' AND is_nullable = 'NO') THEN
    RAISE EXCEPTION 'user_profiles.additional_roles is missing or allows NULL.';
  END IF;
  SELECT string_agg(up.id::text, ', ') INTO found FROM public.user_profiles up
  WHERE NOT up.additional_roles <@ ARRAY['DATA_ADMIN','OFFICE']::text[]
     OR (up.missionary_id IS NOT NULL AND up.app_role IN ('DATA_ADMIN','OFFICE'));
  IF found IS NOT NULL THEN
    RAISE EXCEPTION 'These accounts still have Data Admin or Office as a linked main role, or an unknown additional role: %', found;
  END IF;
  IF to_regclass('public.user_profiles_additional_roles_021_rollback') IS NOT NULL THEN
    RAISE EXCEPTION 'The copy saved by the rollback (public.user_profiles_additional_roles_021_rollback) is still there.';
  END IF;
  -- additional_roles is the last column of both views, and both still check row-level security as the caller.
  SELECT string_agg(c.oid::regclass::text, ', ') INTO found
  FROM pg_class c
  WHERE c.oid IN ('public.current_user_context'::regclass, 'public.current_user_scope'::regclass)
    AND (NOT coalesce(c.reloptions, '{}') @> ARRAY['security_invoker=true']
         OR pg_get_userbyid(c.relowner) <> 'postgres'
         OR (SELECT a.attname FROM pg_attribute a WHERE a.attrelid = c.oid AND a.attnum > 0 AND NOT a.attisdropped
             ORDER BY a.attnum DESC LIMIT 1) <> 'additional_roles');
  IF found IS NOT NULL THEN
    RAISE EXCEPTION 'These views must check row-level security as the caller, belong to postgres and end with additional_roles: %', found;
  END IF;
  -- The replaced helpers run as postgres with a fixed search_path; only the intended roles may run them.
  SELECT string_agg(p.oid::regprocedure::text, ', ') INTO found
  FROM pg_proc p
  WHERE p.oid IN ('public.is_mission_manager_for_area(bigint)'::regprocedure, 'public.can_access_mission(bigint)'::regprocedure,
                  'public.can_access_zone(bigint)'::regprocedure, 'public.can_access_district(bigint)'::regprocedure,
                  'public.is_assignment_admin()'::regprocedure)
    AND (NOT p.prosecdef OR pg_get_userbyid(p.proowner) <> 'postgres'
         OR NOT coalesce(p.proconfig, '{}') @> ARRAY['search_path=public, pg_temp']
         OR has_function_privilege('public', p.oid, 'EXECUTE') OR has_function_privilege('anon', p.oid, 'EXECUTE')
         OR NOT has_function_privilege('authenticated', p.oid, 'EXECUTE')
         OR NOT has_function_privilege('service_role', p.oid, 'EXECUTE'));
  IF found IS NOT NULL THEN
    RAISE EXCEPTION 'Unexpected owner, search_path or EXECUTE rights on: %', found;
  END IF;
  IF has_function_privilege('anon', 'public.sync_user_profile_roles()'::regprocedure, 'EXECUTE')
     OR has_function_privilege('authenticated', 'public.sync_user_profile_roles()'::regprocedure, 'EXECUTE') THEN
    RAISE EXCEPTION 'anon or authenticated can still run sync_user_profile_roles().';
  END IF;
  -- can_access_zone and can_access_district left STL out because only Call-ins uses them. Stop if anything else does.
  SELECT string_agg(x, ', ') INTO found FROM (
    SELECT p.oid::regprocedure::text AS x FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
    WHERE n.nspname NOT IN ('pg_catalog', 'information_schema')
      AND p.prosrc ~ 'can_access_(zone|district)\s*\('
      AND p.proname NOT LIKE '%call\_in\_%' AND p.proname NOT IN ('can_access_zone', 'can_access_district')
    UNION ALL
    SELECT format('policy %s on %s.%s', policyname, schemaname, tablename) FROM pg_policies
    WHERE coalesce(qual, '') || coalesce(with_check, '') ~ 'can_access_(zone|district)'
      AND tablename NOT LIKE 'call\_in\_%'
    UNION ALL
    SELECT format('view %s.%s', schemaname, viewname) FROM pg_views
    WHERE schemaname NOT IN ('pg_catalog', 'information_schema') AND definition ~ 'can_access_(zone|district)') used;
  IF found IS NOT NULL THEN
    RAISE EXCEPTION 'can_access_zone/can_access_district no longer let STLs in, but these non-Call-ins objects use them: %', found;
  END IF;
  -- Both policies know the additional role.
  SELECT string_agg(policyname, ', ') INTO found FROM pg_policies
  WHERE schemaname = 'public'
    AND ((tablename = 'leadership_assignments' AND policyname = 'Users can read relevant leadership assignments')
      OR (tablename = 'missionary_language_assignments' AND policyname = 'assigned_languages_read'))
    AND qual NOT LIKE '%additional_roles%';
  IF found IS NOT NULL THEN
    RAISE EXCEPTION 'These policies do not include the additional Data Analyst: %', found;
  END IF;
END $$;

-- Check: a signed-in person still sees only their own rows in both views (as the first active account; no names are
-- read or shown, only counts).
DO $$
BEGIN
  PERFORM set_config('request.jwt.claims',
                     json_build_object('sub', (SELECT id FROM public.user_profiles WHERE active ORDER BY id LIMIT 1),
                                       'role', 'authenticated')::text, true);
END $$;
SET LOCAL ROLE authenticated;
DO $$
DECLARE
  own_rows bigint; other_rows bigint;
BEGIN
  IF auth.uid() IS NULL THEN
    RETURN;  -- no active account in this database: nothing to check
  END IF;
  SELECT count(*) FILTER (WHERE user_id = auth.uid()), count(*) FILTER (WHERE user_id IS DISTINCT FROM auth.uid())
    INTO own_rows, other_rows FROM public.current_user_context;
  IF own_rows = 0 OR other_rows > 0 THEN
    RAISE EXCEPTION 'current_user_context must show a signed-in person only their own rows (own %, others %).', own_rows, other_rows;
  END IF;
  SELECT count(*) FILTER (WHERE user_id = auth.uid()), count(*) FILTER (WHERE user_id IS DISTINCT FROM auth.uid())
    INTO own_rows, other_rows FROM public.current_user_scope;
  IF own_rows = 0 OR other_rows > 0 THEN
    RAISE EXCEPTION 'current_user_scope must show a signed-in person only their own rows (own %, others %).', own_rows, other_rows;
  END IF;
END $$;
RESET ROLE;
DO $$ BEGIN PERFORM set_config('request.jwt.claims', '', true); END $$;

NOTIFY pgrst, 'reload schema';
COMMIT;

-- Verify (read-only, after applying):
-- 1. Run 019 again as supabase_admin (see Apply); it must end with COMMIT.
-- 2. The column is there and nobody has an additional role yet (expect 0 and 0 on Beta):
--   docker exec gfm-beta-supabase-db-1 psql -U postgres -d postgres -c "SELECT count(*) FILTER (WHERE additional_roles <> '{}') AS with_additional, count(*) FILTER (WHERE app_role IN ('DATA_ADMIN','OFFICE') AND missionary_id IS NOT NULL) AS linked_legacy FROM public.user_profiles"
-- 3. Open Call-ins Alpha as the AP, the zone leader and the district leader: the same numbers as before. Open the
--    DA Management account page, tick "Data Analyst" for a test account, save, and sign in to the portal as it.
