-- Staff accounts: the President, office staff and Data Analysts who are not missionaries in the roster can sign in.
-- Run on Beta only, as supabase_admin, AFTER 021_additional_roles.sql.
--
-- Why: every account got its mission from a current missionary or leadership assignment. An account without one
-- (the President, an office worker, a Data Analyst who is not on the roster) was refused by portal-api ("A mission
-- assignment is required"), could not open Dashboards, Presentations or Call-ins, and DA Management could not even
-- create it (its account list shows only missionaries with an area).
--
-- What changes:
-- 1. user_profiles gets two columns for accounts WITHOUT a missionary link (missionary_id IS NULL):
--    home_mission_id (the mission the account belongs to) and display_name (the name shown in the portal).
--    An account without a missionary link may have a home mission only as a President, Office or Data Analyst
--    (check constraint). For an account linked to a missionary both are ignored: the roster decides, as before (so
--    linking such an account later, e.g. through link_user_to_missionary, never fails on the constraint).
-- 2. current_user_context and current_user_scope: home_mission_id is appended as their LAST column, after 021's
--    additional_roles (it is NULL for accounts linked to a missionary). current_user_context.display_name falls
--    back to user_profiles.display_name when there is no missionary. mission_id keeps its meaning (the mission of
--    the current assignment); portal-api and DA Management fall back to home_mission_id themselves. Both views stay
--    security_invoker = true, so a signed-in person still sees only their own rows (checked at the end).
-- 3. is_mission_manager_for_area, can_access_mission and can_access_zone: a President or Data Analyst account WITH
--    NO MISSIONARY LINK counts as being in its home mission, where before it needed a current missionary or
--    leadership assignment there. Every other check is exactly 021's (the lines marked "027" are the only
--    additions). can_access_district and is_assignment_admin need no change (they do not check the mission for
--    President and Data Analyst). Office staff get no database access from this: Office is not a manager.
-- 4. roster_import_batches.kind also allows 'ACCOUNT': DA Management records staff account changes (and sign-in
--    links) there, so they appear in Import history with Undo, like transfers.
-- The three replaced functions keep search_path public, pg_temp and EXECUTE only for postgres (owner),
-- authenticated and service_role (never PUBLIC or anon).
--
-- Written against 021 as of 27 Sep 2026: the file stops (and changes nothing) if the three helpers or the two
-- views are not exactly 021's (or this file's own, when it is run again). If 021 changed before deploy, carry its
-- changes into section 2 and 3 below and update the fingerprints in the first check.
--
-- Apply (back up Beta first; 019, 020 and 021 must already be applied). supabase_admin is needed because it owns
-- public.roster_import_batches. The file is plain ASCII:
--   Get-Content portal-api/migrations/027_staff_accounts.sql -Raw |
--     docker exec -i gfm-beta-supabase-db-1 psql -U supabase_admin -d postgres -v ON_ERROR_STOP=1
-- Then run 019 again as a check (it must end with COMMIT):
--   Get-Content portal-api/migrations/019_restrict_public_functions.sql -Raw |
--     docker exec -i gfm-beta-supabase-db-1 psql -U supabase_admin -d postgres -v ON_ERROR_STOP=1
-- Adding the columns and replacing the views briefly lock user_profiles and the views. If a long query holds them,
-- the file stops after 10 seconds (lock timeout) instead of making sign-ins wait; run it again a little later.
-- Safe to run again: ADD COLUMN IF NOT EXISTS, guarded constraints, CREATE OR REPLACE, REVOKE/GRANT, then checks that
-- stop (and undo everything) on any problem.
-- Deploy with the portal-api and DA Management (roster-importer) images of the same change, or apply this file
-- first: code without the change ignores the new columns (staff accounts are then refused, as before).
-- Rollback: portal-api/migrations/027_staff_accounts_rollback.sql (restores 021's three functions and view
-- definitions; the views keep home_mission_id as an always-empty last column, because current_mission_areas depends
-- on current_user_context; the new table columns and their data stay, but nothing uses them any more).
-- Order with 021 (read this before touching 021 again):
--   * Roll back 027 BEFORE 021. 021_additional_roles_rollback.sql restores the pre-021 helpers without the lines
--     marked "027" while the views keep home_mission_id: staff accounts could then still sign in to the portal, but
--     the database refuses their mission (for example, Call-ins of a staff President or Data Analyst fail).
--   * Once 027 has run (even after its rollback), 021_additional_roles.sql cannot be run again: it stops with
--     "cannot drop columns from view" (the views keep home_mission_id) and changes nothing, as it runs in one
--     transaction. Its "Safe to run again" no longer holds.
--   * A later change to 021's three helpers or two views goes into a NEW migration after 027 that keeps the lines
--     marked "027" and the home_mission_id column. Do not edit 021 in place.
BEGIN;
SET LOCAL lock_timeout = '10s';

DO $$
DECLARE
  unexpected text;
BEGIN
  IF NOT (SELECT rolsuper FROM pg_roles WHERE rolname = current_user) THEN
    RAISE EXCEPTION 'Run this file as supabase_admin (see its header); % cannot change roster_import_batches.', current_user;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'user_profiles'
                   AND column_name = 'additional_roles') THEN
    RAISE EXCEPTION 'Apply 021_additional_roles.sql first: this file builds on its views and helpers.';
  END IF;
  -- Fingerprints (whitespace-insensitive) of 021's helpers and of this file's own versions. The views: 021's, this
  -- file's, and 027_staff_accounts_rollback.sql's (021's with an empty home_mission_id column).
  SELECT string_agg(p.proname, ', ') INTO unexpected
  FROM pg_proc p
  WHERE p.pronamespace = 'public'::regnamespace
    AND p.proname IN ('is_mission_manager_for_area', 'can_access_mission', 'can_access_zone')
    AND md5(btrim(regexp_replace(p.prosrc, '\s+', ' ', 'g'))) NOT IN (
        '00b7e65493c07021b529d943ad527fc6', '8ca67f04cac806c53c1bb1c35101947a', '83f3e577f11884b09988240fe493408c',
        '12cb18294d92f0c78ecc2cfc6bad0bdd', 'f4a067b6635704e5bb91f3f24eff1baa', '70b3678044b402ef6fb0b900f63650f7');
  IF unexpected IS NOT NULL THEN
    RAISE EXCEPTION 'These helpers are not the 021 version this file was written against: %. Carry the change into 027 first (see its header).', unexpected;
  END IF;
  SELECT string_agg(c.relname, ', ') INTO unexpected
  FROM pg_class c
  WHERE c.relnamespace = 'public'::regnamespace AND c.relname IN ('current_user_context', 'current_user_scope')
    AND md5(pg_get_viewdef(c.oid)) NOT IN ('2129229434450de5482ca5476e9b3e0f', 'ec896cb2310b0f4999b4ca3f9e7096a9',
                                           'd279cdeb39b39cf58a172deb25423555', '4359f70b59e9b5875c53e3ac7a4e30a8',
                                           '92be850ef64d7489f612c75c6bd1f10c', '29319624ee7aadaea372a707e05edb54');
  IF unexpected IS NOT NULL THEN
    RAISE EXCEPTION 'These views are not the 021 version this file was written against: %. Carry the change into 027 first (see its header).', unexpected;
  END IF;
END $$;

-- 1. The columns. Both are NULL for every existing account, so nothing changes for them.
ALTER TABLE public.user_profiles ADD COLUMN IF NOT EXISTS home_mission_id bigint REFERENCES public.missions(id);
ALTER TABLE public.user_profiles ADD COLUMN IF NOT EXISTS display_name text;
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid = 'public.user_profiles'::regclass
                   AND conname = 'user_profiles_home_mission_staff_check') THEN
    ALTER TABLE public.user_profiles ADD CONSTRAINT user_profiles_home_mission_staff_check
      CHECK (home_mission_id IS NULL OR missionary_id IS NOT NULL OR app_role IN ('PRESIDENT', 'OFFICE', 'DATA_ADMIN'));
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid = 'public.user_profiles'::regclass
                   AND conname = 'user_profiles_display_name_check') THEN
    ALTER TABLE public.user_profiles ADD CONSTRAINT user_profiles_display_name_check
      CHECK (display_name IS NULL OR char_length(btrim(display_name)) BETWEEN 1 AND 120);
  END IF;
END $$;
COMMENT ON COLUMN public.user_profiles.home_mission_id IS
  'Staff accounts (no missionary link): the mission the account belongs to. Only for President, Office or Data Analyst main roles. Ignored while missionary_id is set. Set in DA Management, Staff accounts.';
COMMENT ON COLUMN public.user_profiles.display_name IS
  'Staff accounts (no missionary link): the name shown in the portal. Linked accounts use missionaries.display_name.';

-- 2. The two views: 021's definitions, with display_name falling back to the staff name and home_mission_id appended
-- as the last column (after additional_roles). WITH (security_invoker = true) must be repeated: CREATE OR REPLACE
-- VIEW would otherwise drop it, and every signed-in user could then read everyone's row through PostgREST.
CREATE OR REPLACE VIEW public.current_user_context
WITH (security_invoker = true) AS
SELECT up.id AS user_id,
    up.app_role,
    up.active AS user_active,
    m.id AS missionary_id,
    m.missionary_number,
    COALESCE(m.display_name, up.display_name) AS display_name,  -- 027: staff accounts show their own name
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
    CASE WHEN up.missionary_id IS NULL THEN up.home_mission_id END AS home_mission_id  -- 027
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
    CASE WHEN up.missionary_id IS NULL THEN up.home_mission_id END AS home_mission_id  -- 027
FROM public.user_profiles up
LEFT JOIN public.current_missionary_assignments cma ON cma.missionary_id = up.missionary_id
LEFT JOIN public.current_leadership_assignments cla ON cla.missionary_id = up.missionary_id
WHERE up.active = true;

-- 3. The helpers: 021's text plus the lines marked 027. Same names, arguments and return types.
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
                  -- 027: or, without a missionary link, this is the account's home mission
                  OR (up.missionary_id IS NULL AND up.home_mission_id = target_mission_id)
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
                  -- 027: or, without a missionary link, the zone is in the account's home mission
                  OR (up.missionary_id IS NULL AND up.home_mission_id = tz.mission_id)
              ))
          )
    );
$function$;

-- Signed-in users, service_role and postgres (owner). Never PUBLIC or anon.
REVOKE ALL ON FUNCTION public.is_mission_manager_for_area(bigint), public.can_access_mission(bigint),
    public.can_access_zone(bigint)
  FROM PUBLIC, anon;
GRANT EXECUTE ON FUNCTION public.is_mission_manager_for_area(bigint), public.can_access_mission(bigint),
    public.can_access_zone(bigint)
  TO postgres, authenticated, service_role;

-- 4. Import history also records staff account changes ("ACCOUNT" batches, undone like transfers).
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid = 'public.roster_import_batches'::regclass
                   AND conname = 'roster_import_batches_kind_check'
                   AND pg_get_constraintdef(oid) LIKE '%ACCOUNT%') THEN
    ALTER TABLE public.roster_import_batches DROP CONSTRAINT IF EXISTS roster_import_batches_kind_check;
    ALTER TABLE public.roster_import_batches ADD CONSTRAINT roster_import_batches_kind_check
      CHECK (kind IN ('TRANSFER', 'HISTORICAL', 'ACCOUNT'));
  END IF;
END $$;

-- Checks: stop (and undo everything above) on any problem.
DO $$
DECLARE
  found text;
BEGIN
  IF (SELECT count(*) FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'user_profiles'
        AND column_name IN ('home_mission_id', 'display_name') AND is_nullable = 'YES') <> 2 THEN
    RAISE EXCEPTION 'user_profiles.home_mission_id or display_name is missing.';
  END IF;
  -- Both views: security_invoker, owned by postgres, and ending with additional_roles, home_mission_id.
  SELECT string_agg(c.oid::regclass::text, ', ') INTO found
  FROM pg_class c
  WHERE c.oid IN ('public.current_user_context'::regclass, 'public.current_user_scope'::regclass)
    AND (NOT coalesce(c.reloptions, '{}') @> ARRAY['security_invoker=true']
         OR pg_get_userbyid(c.relowner) <> 'postgres'
         OR ARRAY(SELECT a.attname::text FROM pg_attribute a WHERE a.attrelid = c.oid AND a.attnum > 0 AND NOT a.attisdropped
                  ORDER BY a.attnum DESC LIMIT 2) <> ARRAY['home_mission_id', 'additional_roles']);
  IF found IS NOT NULL THEN
    RAISE EXCEPTION 'These views must check row-level security as the caller, belong to postgres and end with additional_roles, home_mission_id: %', found;
  END IF;
  -- The replaced helpers run as postgres with a fixed search_path; only the intended roles may run them.
  SELECT string_agg(p.oid::regprocedure::text, ', ') INTO found
  FROM pg_proc p
  WHERE p.oid IN ('public.is_mission_manager_for_area(bigint)'::regprocedure, 'public.can_access_mission(bigint)'::regprocedure,
                  'public.can_access_zone(bigint)'::regprocedure)
    AND (NOT p.prosecdef OR pg_get_userbyid(p.proowner) <> 'postgres'
         OR NOT coalesce(p.proconfig, '{}') @> ARRAY['search_path=public, pg_temp']
         OR p.prosrc NOT LIKE '%home_mission_id%'
         OR has_function_privilege('public', p.oid, 'EXECUTE') OR has_function_privilege('anon', p.oid, 'EXECUTE')
         OR NOT has_function_privilege('authenticated', p.oid, 'EXECUTE')
         OR NOT has_function_privilege('service_role', p.oid, 'EXECUTE'));
  IF found IS NOT NULL THEN
    RAISE EXCEPTION 'Unexpected owner, search_path, body or EXECUTE rights on: %', found;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid = 'public.roster_import_batches'::regclass
                   AND conname = 'roster_import_batches_kind_check' AND pg_get_constraintdef(oid) LIKE '%ACCOUNT%') THEN
    RAISE EXCEPTION 'roster_import_batches does not accept ACCOUNT batches.';
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
-- 2. The columns are there and no account has a home mission yet (expect 0 on Beta):
--   docker exec gfm-beta-supabase-db-1 psql -U postgres -d postgres -c "SELECT count(*) FILTER (WHERE home_mission_id IS NOT NULL) AS staff FROM public.user_profiles"
-- 3. In DA Management, Staff accounts: invite the President (main role President). After they set a password, they
--    sign in to the portal and open Dashboards, Presentations and Call-ins (mission level).
