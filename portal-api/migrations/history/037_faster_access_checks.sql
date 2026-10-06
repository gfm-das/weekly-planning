-- Migration 037 (round 9): the two database checks behind "may this person see this area?" answer much faster.
--
-- Why: row-level security asks public.can_access_area(area_id) for every weekly plan, planning answer, person,
-- companionship and missionary row a signed-in person reads, and can_access_area asks
-- public.is_mission_manager_for_area first. Both were written in plain SQL. Postgres keeps no plan for a SQL function
-- that is called from inside another function, so every single check was planned again from scratch: about 3 ms per
-- row. The managers' mission glimpse reads about 1,000 plans (and their answers), so its first read took 2.5 to 5 s;
-- Weekly Planning, the Overview and the Call-ins summaries paid the same price on a smaller scale.
--
-- What changes: only the language of the two functions, from sql to plpgsql. plpgsql keeps each function's plan for
-- the whole connection, so a check costs well under 1 ms. The question each function asks is word for word the
-- one migrations 013 (can_access_area) and 032 (is_mission_manager_for_area, with 027's lines) wrote. Names,
-- arguments, STABLE, SECURITY DEFINER, search_path, owner (postgres) and rights (postgres, authenticated,
-- service_role; never PUBLIC or anon) stay the same, so every policy and function that uses them stays the same too.
-- Measured on a live-like copy (docs/handoff/round9/api.md): the glimpse query went from about 2.9 s to 0.4 s.
--
-- Apply as supabase_admin (the functions belong to postgres). The file is plain ASCII:
--   Get-Content portal-api/migrations/037_faster_access_checks.sql -Raw |
--     docker exec -i gfm-beta-supabase-db-1 psql -U supabase_admin -d postgres -v ON_ERROR_STOP=1
-- Then run 019 again (it must end with COMMIT):
--   Get-Content portal-api/migrations/019_restrict_public_functions.sql -Raw |
--     docker exec -i gfm-beta-supabase-db-1 psql -U supabase_admin -d postgres -v ON_ERROR_STOP=1
-- Safe to run again. No code needs it first: portal-api and DA Management get the same answers either way.
-- It stops (and changes nothing) when the functions are not the 013 / 032 versions it was written against.
-- Rollback: 037_faster_access_checks_rollback.sql (the same two functions in SQL again).
BEGIN;
SET LOCAL lock_timeout = '10s';

-- Before: the database is the one this file was written for, and what the checks at the end compare against.
-- The SQL texts are recognised by their md5 (line ends ignored); a database that already has 037 passes too.
DO $$
BEGIN
  IF NOT (SELECT rolsuper FROM pg_roles WHERE rolname = current_user) THEN
    RAISE EXCEPTION 'Run this file as supabase_admin (see its header), not as %.', current_user;
  END IF;
  IF to_regprocedure('public.can_access_area(bigint)') IS NULL
     OR to_regprocedure('public.is_mission_manager_for_area(bigint)') IS NULL THEN
    RAISE EXCEPTION 'Migration 037 needs migrations 013 and 032 (an access check is missing).';
  END IF;
  IF EXISTS (
    SELECT 1
    FROM (VALUES ('public.can_access_area(bigint)', '12d62d4109a13f3c07d1bd4b77cb198a'),
                 ('public.is_mission_manager_for_area(bigint)', 'b3d5c725c02a16125618451f8721754e')) AS want(sig, body)
    JOIN pg_proc p ON p.oid = to_regprocedure(want.sig)
    JOIN pg_language l ON l.oid = p.prolang
    WHERE NOT (l.lanname = 'sql' AND md5(replace(p.prosrc, E'\r', '')) = want.body)
      AND NOT (l.lanname = 'plpgsql' AND position('Migration 037' IN p.prosrc) > 0)
  ) THEN
    RAISE EXCEPTION 'An access check is not the 013 / 032 version this file was written against. Carry the change into 037 first.';
  END IF;
END $$;

CREATE TEMPORARY TABLE access_checks_before ON COMMIT DROP AS
SELECT p.oid, p.proname, pg_get_userbyid(p.proowner) AS owner, p.prosecdef, p.provolatile, p.proconfig,
       p.proacl::text AS rights
FROM pg_proc p
WHERE p.oid IN ('public.can_access_area(bigint)'::regprocedure, 'public.is_mission_manager_for_area(bigint)'::regprocedure);

SET LOCAL ROLE postgres;

-- 1. The manager check: 032's question (with 027's lines), word for word.
CREATE OR REPLACE FUNCTION public.is_mission_manager_for_area(target_area_id bigint)
RETURNS boolean LANGUAGE plpgsql STABLE SECURITY DEFINER
SET search_path = public, pg_temp
AS $function$
BEGIN
  -- Migration 037: the same question as migration 032, in plpgsql so its plan is kept for the whole connection.
  RETURN (
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
    )
  );
END
$function$;

-- 2. The area check: 013's question, word for word.
CREATE OR REPLACE FUNCTION public.can_access_area(target_area_id bigint)
RETURNS boolean LANGUAGE plpgsql STABLE SECURITY DEFINER
SET search_path = public, pg_temp
AS $function$
BEGIN
  -- Migration 037: the same question as migration 013, in plpgsql so its plan is kept for the whole connection.
  RETURN (
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
    )
  );
END
$function$;

RESET ROLE;

-- Check: both are plpgsql now and kept their owner, SECURITY DEFINER, STABLE, search_path and rights; nobody
-- signed in gets true.
DO $$
DECLARE
  changed text;
BEGIN
  SELECT string_agg(b.proname, ', ') INTO changed
  FROM access_checks_before b
  JOIN pg_proc p ON p.oid = b.oid
  JOIN pg_language l ON l.oid = p.prolang
  WHERE l.lanname <> 'plpgsql' OR pg_get_userbyid(p.proowner) <> b.owner OR p.prosecdef <> b.prosecdef
     OR p.provolatile <> b.provolatile OR p.proconfig IS DISTINCT FROM b.proconfig
     OR p.proacl::text IS DISTINCT FROM b.rights;
  IF changed IS NOT NULL THEN
    RAISE EXCEPTION 'Migration 037: % changed more than its language.', changed;
  END IF;
  IF (SELECT count(*) FROM access_checks_before WHERE owner = 'postgres' AND prosecdef AND provolatile = 's'
        AND proconfig = ARRAY['search_path=public, pg_temp']) <> 2 THEN
    RAISE EXCEPTION 'Migration 037: the access checks are not owned by postgres with SECURITY DEFINER and search_path.';
  END IF;
  PERFORM set_config('request.jwt.claims', '', true);
  PERFORM set_config('request.jwt.claim.sub', '', true);
  IF EXISTS (SELECT 1 FROM public.areas a WHERE public.can_access_area(a.id) OR public.is_mission_manager_for_area(a.id)) THEN
    RAISE EXCEPTION 'Migration 037: an access check says yes to nobody.';
  END IF;
  RAISE NOTICE 'Migration 037: can_access_area and is_mission_manager_for_area run in plpgsql.';
END $$;

COMMIT;
