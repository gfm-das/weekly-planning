-- Rollback of 021_additional_roles.sql. Run on Beta only, as supabase_admin (it owns
-- public.missionary_language_assignments), and only together with, or after, going back to the portal-api,
-- portal-reminders and DA Management images from before 021 (see docs/handoff/round2/roles.md).
--
-- What it does:
-- 1. Additional roles go back into app_role where the old single-role model can hold them: an additional Data
--    Analyst becomes app_role DATA_ADMIN (unless the account is the President; the old model gives Data Admin the
--    manager rights before any leadership role), and an additional Office becomes app_role OFFICE when the account
--    is Missionary with no current leadership assignment. (A DL, ZL, STL or AP keeps that role; the old model cannot
--    also give them Office.) Then the additional roles are copied into public.user_profiles_additional_roles_021_rollback
--    (with the app_role before and after this file) and cleared, because code from before 021 can neither show nor
--    remove them. Applying 021 again gives them back only to accounts whose app_role is still the value this file
--    wrote: a Data Analyst role taken away while rolled back (another role chosen in the old DA Management) stays
--    away. An account whose app_role changed in the meantime keeps only what it has then; tick its additional roles
--    again on the DA Management account page if they are still wanted.
-- 2. is_mission_manager_for_area, can_access_mission, can_access_zone, can_access_district and is_assignment_admin
--    are put back exactly as they were on Beta before 021 (pg_get_functiondef output of 27 Sep 2026), and so are the
--    two row-level security policies (pg_policies text of the same day).
-- It prints "fingerprint f3ad4471290dd45aef64c9fbf4b2c69b" (those seven definitions on Beta before 021, shown with
-- search_path public, pg_temp); any other value means something differs. Checked on a restored copy: 021, then this
-- file, gives that fingerprint, and 019 passes again.
--
-- What it leaves in place, on purpose:
-- - The additional_roles column (now empty) and the last column of current_user_context and current_user_scope.
--   Removing them needs DROP VIEW of both views and of current_mission_areas and current_user_area_units, which depend
--   on them; the extra column changes nothing for code from before 021.
-- - public.user_profiles_additional_roles_021_rollback, the saved copy (row-level security on, no API grants). 021
--   drops it. If 021 is not going to be applied again, drop it by hand once it is no longer needed.
-- - The tightened EXECUTE rights: anon cannot run the five functions (it only ever got false from them), and anon
--   and authenticated cannot run sync_user_profile_roles(), which rewrites app_role for every linked account. To put
--   those grants back too, run the commented block at the end (not recommended).
--
-- Run (back up first). The file is plain ASCII:
--   Get-Content portal-api/migrations/021_additional_roles_rollback.sql -Raw |
--     docker exec -i gfm-beta-supabase-db-1 psql -U supabase_admin -d postgres -v ON_ERROR_STOP=1
-- Then run 019 again as a check (it must end with COMMIT). If the file stops on the 10-second lock timeout, run it
-- again a little later. Safe to run again (a second run finds no additional roles and keeps the saved copy).
BEGIN;
SET LOCAL lock_timeout = '10s';
SET LOCAL search_path = public, pg_temp;

DO $$
BEGIN
  IF NOT (SELECT rolsuper FROM pg_roles WHERE rolname = current_user) THEN
    RAISE EXCEPTION 'Run this file as supabase_admin (see its header), not as %.', current_user;
  END IF;
END $$;

-- 1. Additional roles back into app_role, where the old model can hold them. First note every account's additional
-- roles and app_role as they are now (for the saved copy below).
CREATE TEMP TABLE rollback_021_before ON COMMIT DROP AS
  SELECT id, additional_roles, app_role FROM public.user_profiles WHERE additional_roles <> '{}';

UPDATE public.user_profiles SET app_role = 'DATA_ADMIN', updated_at = now()
WHERE 'DATA_ADMIN' = ANY(additional_roles) AND app_role NOT IN ('DATA_ADMIN', 'PRESIDENT');
UPDATE public.user_profiles up SET app_role = 'OFFICE', updated_at = now()
WHERE 'OFFICE' = ANY(up.additional_roles) AND up.app_role = 'MISSIONARY'
  AND NOT EXISTS (SELECT 1 FROM public.leadership_assignments la
                  WHERE la.missionary_id = up.missionary_id AND la.start_date <= CURRENT_DATE
                    AND (la.end_date IS NULL OR la.end_date >= CURRENT_DATE));

-- Keep a copy of the additional roles, then clear them: code from before 021 cannot see or remove them, so a role
-- taken away while rolled back (by choosing another role in the old DA Management) must not come back when 021 is
-- applied again. 021 restores a saved row only while app_role is still the value this file wrote (app_role_written).
-- Only supabase_admin and postgres can read the copy (row-level security on; no grants for anon, authenticated or
-- service_role, so PostgREST cannot serve it).
CREATE TABLE IF NOT EXISTS public.user_profiles_additional_roles_021_rollback (
  id uuid PRIMARY KEY,
  additional_roles text[] NOT NULL,
  app_role_before text,
  app_role_written text,
  saved_at timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE public.user_profiles_additional_roles_021_rollback ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.user_profiles_additional_roles_021_rollback FROM PUBLIC, anon, authenticated, service_role;
COMMENT ON TABLE public.user_profiles_additional_roles_021_rollback IS
  'Written by 021_additional_roles_rollback.sql: the additional roles it cleared. Applying 021 again gives them back to accounts whose app_role is still app_role_written, then drops this table.';
INSERT INTO public.user_profiles_additional_roles_021_rollback (id, additional_roles, app_role_before, app_role_written)
SELECT b.id, b.additional_roles, b.app_role, up.app_role
FROM rollback_021_before b JOIN public.user_profiles up ON up.id = b.id
ON CONFLICT (id) DO UPDATE SET additional_roles = EXCLUDED.additional_roles, app_role_before = EXCLUDED.app_role_before,
    app_role_written = EXCLUDED.app_role_written, saved_at = now();
UPDATE public.user_profiles SET additional_roles = '{}', updated_at = now() WHERE additional_roles <> '{}';

DO $$
DECLARE
  saved bigint;
BEGIN
  SELECT count(*) INTO saved FROM rollback_021_before;
  RAISE NOTICE 'Additional roles of % account(s) saved in public.user_profiles_additional_roles_021_rollback and cleared.', saved;
  IF EXISTS (SELECT 1 FROM public.user_profiles WHERE additional_roles <> '{}') THEN
    RAISE EXCEPTION 'Some accounts still have additional roles.';
  END IF;
  IF has_table_privilege('anon', 'public.user_profiles_additional_roles_021_rollback', 'SELECT')
     OR has_table_privilege('authenticated', 'public.user_profiles_additional_roles_021_rollback', 'SELECT')
     OR NOT (SELECT relrowsecurity FROM pg_class WHERE oid = 'public.user_profiles_additional_roles_021_rollback'::regclass) THEN
    RAISE EXCEPTION 'The saved copy of the additional roles must not be readable through the API.';
  END IF;
END $$;

-- 2. The five functions as before 021.
CREATE OR REPLACE FUNCTION public.is_mission_manager_for_area(target_area_id bigint)
 RETURNS boolean
 LANGUAGE sql
 STABLE SECURITY DEFINER
 SET search_path TO 'public', 'pg_temp'
AS $function$
    SELECT EXISTS (
        SELECT 1 FROM public.user_profiles up
        JOIN public.areas target ON target.id = target_area_id
        JOIN public.districts td ON td.id = target.district_id
        JOIN public.zones tz ON tz.id = td.zone_id
        WHERE up.id = auth.uid() AND up.active
          AND (up.app_role IN ('AP','PRESIDENT','DATA_ADMIN') OR EXISTS (
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
 RETURNS boolean
 LANGUAGE sql
 STABLE SECURITY DEFINER
 SET search_path TO 'public'
AS $function$

    SELECT EXISTS (

        SELECT 1

        FROM public.user_profiles up

        LEFT JOIN public.leadership_assignments la
          ON la.missionary_id = up.missionary_id
         AND la.mission_id = target_mission_id
         AND la.start_date <= current_date
         AND (
             la.end_date IS NULL
             OR la.end_date >= current_date
         )

        WHERE up.id = auth.uid()
          AND up.active = true

          AND (
              up.app_role = 'DATA_ADMIN'

              OR (
                  up.app_role IN ('AP', 'PRESIDENT')
                  AND la.id IS NOT NULL
                  AND la.role IN ('AP', 'PRESIDENT')
              )
          )
    );

$function$;

CREATE OR REPLACE FUNCTION public.can_access_zone(target_zone_id bigint)
 RETURNS boolean
 LANGUAGE sql
 STABLE SECURITY DEFINER
 SET search_path TO 'public'
AS $function$

    SELECT EXISTS (

        SELECT 1
        FROM public.user_profiles up

        LEFT JOIN public.missionary_assignments ma
            ON ma.missionary_id = up.missionary_id
           AND ma.start_date <= current_date
           AND (
               ma.end_date IS NULL
               OR ma.end_date >= current_date
           )

        LEFT JOIN public.leadership_assignments la
            ON la.missionary_id = up.missionary_id
           AND la.start_date <= current_date
           AND (
               la.end_date IS NULL
               OR la.end_date >= current_date
           )

        WHERE up.id = auth.uid()
          AND up.active = true

          AND (

              -- Missionary/DL can access zone containing their area
              EXISTS (
                  SELECT 1
                  FROM public.areas a
                  JOIN public.districts d
                    ON d.id = a.district_id
                  WHERE a.id = ma.area_id
                    AND d.zone_id = target_zone_id
              )

              -- ZL/STL can access assigned zone
              OR (
                  up.app_role IN ('ZL', 'STL')
                  AND la.role IN ('ZL', 'STL')
                  AND la.zone_id = target_zone_id
              )

              -- Mission-level leadership / data
              OR up.app_role IN (
                  'AP',
                  'PRESIDENT',
                  'DATA_ADMIN'
              )
          )
    );

$function$;

CREATE OR REPLACE FUNCTION public.can_access_district(target_district_id bigint)
 RETURNS boolean
 LANGUAGE sql
 STABLE SECURITY DEFINER
 SET search_path TO 'public'
AS $function$

    SELECT EXISTS (

        SELECT 1

        FROM public.user_profiles up

        JOIN public.districts d
          ON d.id = target_district_id

        JOIN public.zones z
          ON z.id = d.zone_id

        WHERE up.id = auth.uid()
          AND up.active = true

          AND (

              -- Special system roles
              up.app_role IN (
                  'PRESIDENT',
                  'DATA_ADMIN'
              )

              -- Leadership roles
              OR EXISTS (

                  SELECT 1

                  FROM public.leadership_assignments la

                  WHERE la.missionary_id = up.missionary_id

                    AND la.start_date <= current_date

                    AND (
                        la.end_date IS NULL
                        OR la.end_date >= current_date
                    )

                    AND (

                        -- DL: assigned district only
                        (
                            la.role = 'DL'
                            AND la.district_id = target_district_id
                        )

                        -- ZL / STL: districts in assigned zone
                        OR (
                            la.role IN ('ZL', 'STL')
                            AND la.zone_id = d.zone_id
                        )

                        -- AP: districts in assigned mission
                        OR (
                            la.role = 'AP'
                            AND la.mission_id = z.mission_id
                        )

                    )
              )
          )
    );

$function$;

CREATE OR REPLACE FUNCTION public.is_assignment_admin()
 RETURNS boolean
 LANGUAGE sql
 STABLE SECURITY DEFINER
 SET search_path TO 'public'
AS $function$

    select exists (

        select 1

        from public.user_profiles up

        where up.id = auth.uid()

          and up.active = true

          and up.app_role in (
              'PRESIDENT',
              'DATA_ADMIN'
          )

    );

$function$;

-- 3. The two policies as before 021.
ALTER POLICY "Users can read relevant leadership assignments" ON public.leadership_assignments
USING (
((missionary_id = ( SELECT up.missionary_id
   FROM user_profiles up
  WHERE (up.id = ( SELECT auth.uid() AS uid)))) OR (EXISTS ( SELECT 1
   FROM user_profiles up
  WHERE ((up.id = ( SELECT auth.uid() AS uid)) AND (up.app_role = 'DATA_ADMIN'::text)))))
);

ALTER POLICY assigned_languages_read ON public.missionary_language_assignments
USING (
((missionary_id IN ( SELECT up.missionary_id
   FROM user_profiles up
  WHERE ((up.id = auth.uid()) AND up.active))) OR (EXISTS ( SELECT 1
   FROM (((user_profiles up
     LEFT JOIN LATERAL ( SELECT la.mission_id
           FROM leadership_assignments la
          WHERE ((la.missionary_id = up.missionary_id) AND (la.role = 'AP'::text) AND (la.start_date <= CURRENT_DATE) AND ((la.end_date IS NULL) OR (la.end_date >= CURRENT_DATE)))
          ORDER BY la.start_date DESC, la.id DESC
         LIMIT 1) ap ON (true))
     LEFT JOIN LATERAL ( SELECT own.mission_id
           FROM current_missionary_assignments own
          WHERE (own.missionary_id = up.missionary_id)
          ORDER BY own.start_date DESC, own.assignment_id DESC
         LIMIT 1) own_scope ON (true))
     JOIN LATERAL ( SELECT target.mission_id
           FROM current_missionary_assignments target
          WHERE (target.missionary_id = missionary_language_assignments.missionary_id)
          ORDER BY target.start_date DESC, target.assignment_id DESC
         LIMIT 1) target_scope ON ((target_scope.mission_id = COALESCE(ap.mission_id, own_scope.mission_id))))
  WHERE ((up.id = auth.uid()) AND up.active AND ((up.app_role = ANY (ARRAY['AP'::text, 'PRESIDENT'::text, 'DATA_ADMIN'::text])) OR (ap.mission_id IS NOT NULL))))))
);

NOTIFY pgrst, 'reload schema';
COMMIT;

-- The policy text depends on the search_path it is shown with, so fix it (for this psql session only).
SET search_path = public, pg_temp;
SELECT 'fingerprint ' || md5(string_agg(x, '|' ORDER BY n)) FROM (VALUES
  (1, pg_get_functiondef('public.is_mission_manager_for_area(bigint)'::regprocedure)),
  (2, pg_get_functiondef('public.can_access_mission(bigint)'::regprocedure)),
  (3, pg_get_functiondef('public.can_access_zone(bigint)'::regprocedure)),
  (4, pg_get_functiondef('public.can_access_district(bigint)'::regprocedure)),
  (5, pg_get_functiondef('public.is_assignment_admin()'::regprocedure)),
  (6, (SELECT qual FROM pg_policies WHERE schemaname = 'public' AND tablename = 'leadership_assignments'
         AND policyname = 'Users can read relevant leadership assignments')),
  (7, (SELECT qual FROM pg_policies WHERE schemaname = 'public' AND tablename = 'missionary_language_assignments'
         AND policyname = 'assigned_languages_read'))) v(n, x);

-- Not recommended: the EXECUTE rights exactly as before 021 (anon on four of the functions, and anon and
-- authenticated on sync_user_profile_roles). Remove the leading "-- " and run as supabase_admin.
-- GRANT EXECUTE ON FUNCTION public.can_access_mission(bigint), public.can_access_zone(bigint),
--   public.can_access_district(bigint), public.is_assignment_admin() TO anon;
-- GRANT EXECUTE ON FUNCTION public.sync_user_profile_roles() TO anon, authenticated;
