-- Rollback of 026_known_issues.sql: puts back the state of Beta before 026 (definitions and grants taken
-- read-only from live Beta on 27 Sep 2026). Run on Beta only, as postgres or supabase_admin.
--
-- Order: roll back portal-api and portal-reminders to the image from before this round FIRST (the new code can
-- delete one date of a repeating event, which needs portal.events.skipped_dates). Then run this file:
--   Get-Content portal-api/migrations/026_known_issues_rollback.sql -Raw |
--     docker exec -i gfm-beta-supabase-db-1 psql -U postgres -d postgres -v ON_ERROR_STOP=1
-- What users notice: dates deleted one by one from repeating events come back (the column is dropped); the
-- reporting week again rolls over at midnight UTC; anon and signed-in users can again run
-- sync_current_companionships() through the public API (its caller check is removed too).
-- Safe to run twice. Afterwards run 019 as a check (it must end with COMMIT).
BEGIN;
SET LOCAL lock_timeout = '10s';

DO $$
BEGIN
  IF current_user NOT IN ('postgres', 'supabase_admin') THEN
    RAISE EXCEPTION 'Run this file as postgres or supabase_admin, not as %.', current_user;
  END IF;
END $$;
SET LOCAL ROLE postgres;

-- 1. Before 026: no caller check, search_path public only, no comment; postgres, anon, authenticated and
--    service_role could run it (PUBLIC could not, since 019). The definition is exactly the one from live Beta.
CREATE OR REPLACE FUNCTION public.sync_current_companionships()
 RETURNS void
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public'
AS $function$
declare
    area_record record;
    current_companionship_id bigint;
begin

    -- Close companionships for areas that no longer have active missionaries
    update public.companionships c
    set end_date = current_date - 1
    where c.end_date is null
      and not exists (
          select 1
          from public.missionary_assignments ma
          where ma.area_id = c.area_id
            and ma.start_date <= current_date
            and (
                ma.end_date is null
                or ma.end_date >= current_date
            )
      );


    -- Process every area that currently has missionaries
    for area_record in

        select distinct ma.area_id

        from public.missionary_assignments ma

        where ma.start_date <= current_date
          and (
              ma.end_date is null
              or ma.end_date >= current_date
          )

    loop

        -- Find current companionship
        select c.id
        into current_companionship_id

        from public.companionships c

        where c.area_id = area_record.area_id
          and c.end_date is null

        order by c.start_date desc
        limit 1;


        -- Create one if it doesn't exist
        if current_companionship_id is null then

            insert into public.companionships (
                area_id,
                start_date
            )

            values (
                area_record.area_id,
                current_date
            )

            returning id
            into current_companionship_id;

        end if;


        -- Add currently assigned missionaries
        insert into public.companionship_members (
            companionship_id,
            missionary_id,
            joined_date
        )

        select
            current_companionship_id,
            ma.missionary_id,
            ma.start_date

        from public.missionary_assignments ma

        where ma.area_id = area_record.area_id

          and ma.start_date <= current_date

          and (
              ma.end_date is null
              or ma.end_date >= current_date
          )

        on conflict (
            companionship_id,
            missionary_id
        )
        do update set
            left_date = null;


        -- Close membership for missionaries no longer assigned there
        update public.companionship_members cm

        set left_date = current_date - 1

        where cm.companionship_id = current_companionship_id

          and cm.left_date is null

          and not exists (
              select 1

              from public.missionary_assignments ma

              where ma.missionary_id = cm.missionary_id
                and ma.area_id = area_record.area_id
                and ma.start_date <= current_date
                and (
                    ma.end_date is null
                    or ma.end_date >= current_date
                )
          );

    end loop;

end;
$function$;
COMMENT ON FUNCTION public.sync_current_companionships() IS NULL;
GRANT EXECUTE ON FUNCTION public.sync_current_companionships() TO postgres, anon, authenticated, service_role;

-- 2. The UTC reporting week, exactly as before (no comment was set on these before 026).
CREATE OR REPLACE FUNCTION public.current_reporting_sunday()
 RETURNS date
 LANGUAGE sql
 STABLE
AS $function$
  SELECT
    current_date
    - extract(dow from current_date)::integer;
$function$;
COMMENT ON FUNCTION public.current_reporting_sunday() IS NULL;

CREATE OR REPLACE VIEW public.current_reporting_week
WITH (security_invoker = true) AS
SELECT reporting_weeks.id,
       reporting_weeks.sunday,
       reporting_weeks.planning_open_at,
       reporting_weeks.planning_due_at
FROM public.reporting_weeks
WHERE reporting_weeks.sunday <= CURRENT_DATE
ORDER BY reporting_weeks.sunday DESC
LIMIT 1;

DROP FUNCTION IF EXISTS public.reporting_sunday_at(timestamptz);

-- 3. Deleted dates of repeating events.
ALTER TABLE portal.events DROP COLUMN IF EXISTS skipped_dates;

NOTIFY pgrst, 'reload schema';

DO $$
BEGIN
  IF NOT has_function_privilege('anon', 'public.sync_current_companionships()', 'EXECUTE')
     OR NOT has_function_privilege('authenticated', 'public.sync_current_companionships()', 'EXECUTE') THEN
    RAISE EXCEPTION 'The old grants on sync_current_companionships() were not restored.';
  END IF;
  IF has_function_privilege('public', 'public.sync_current_companionships()', 'EXECUTE') THEN
    RAISE EXCEPTION 'PUBLIC can run sync_current_companionships(); 019 does not allow that.';
  END IF;
  IF position('can only be run on the server' in pg_get_functiondef('public.sync_current_companionships()'::regprocedure)) > 0
     OR NOT EXISTS (SELECT 1 FROM pg_proc WHERE oid = 'public.sync_current_companionships()'::regprocedure
                    AND prosecdef AND proconfig = ARRAY['search_path=public']) THEN
    RAISE EXCEPTION 'The old sync_current_companionships() was not restored.';
  END IF;
  IF public.current_reporting_sunday() IS DISTINCT FROM current_date - extract(dow FROM current_date)::integer THEN
    RAISE EXCEPTION 'current_reporting_sunday() was not restored.';
  END IF;
  IF to_regprocedure('public.reporting_sunday_at(timestamptz)') IS NOT NULL
     OR EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'portal' AND table_name = 'events'
                AND column_name = 'skipped_dates') THEN
    RAISE EXCEPTION '026 objects are still there.';
  END IF;
END $$;

COMMIT;

-- Check afterwards (read-only). Before 026 and after this rollback, live Beta gives
-- fingerprint e1505221bfc05ab76f3c6c92af2cc535 (live Beta read-only with 021-024 applied, and copies of Beta,
-- 27 Sep 2026). Function bodies are compared without carriage returns: files checked out on Windows have CRLF.
--   BEGIN READ ONLY;
--   SELECT 'fingerprint ' || md5(string_agg(x, '|' ORDER BY n)) FROM (VALUES
--     (1, replace(pg_get_functiondef('public.current_reporting_sunday()'::regprocedure), chr(13), '')),
--     (2, pg_get_viewdef('public.current_reporting_week'::regclass, true)),
--     (3, (SELECT array_to_string(reloptions, ',') FROM pg_class WHERE oid = 'public.current_reporting_week'::regclass)),
--     (4, (SELECT string_agg(a::text, ',' ORDER BY a::text) FROM pg_class, unnest(relacl) a WHERE oid = 'public.current_reporting_week'::regclass)),
--     (5, (SELECT string_agg(a::text, ',' ORDER BY a::text) FROM pg_proc, unnest(proacl) a WHERE oid = 'public.sync_current_companionships()'::regprocedure)),
--     (6, (SELECT string_agg(a::text, ',' ORDER BY a::text) FROM pg_proc, unnest(proacl) a WHERE oid = 'public.current_reporting_sunday()'::regprocedure)),
--     (7, (SELECT string_agg(column_name || ':' || data_type, ',' ORDER BY ordinal_position) FROM information_schema.columns WHERE table_schema = 'portal' AND table_name = 'events')),
--     (8, coalesce(to_regprocedure('public.reporting_sunday_at(timestamptz)')::text, 'none')),
--     (9, pg_get_viewdef('public.current_area_reporting_status'::regclass, true)),
--     (10, replace(pg_get_functiondef('public.sync_current_companionships()'::regprocedure), chr(13), '')),
--     (11, coalesce(obj_description('public.sync_current_companionships()'::regprocedure, 'pg_proc'), 'none'))) v(n, x);
--   ROLLBACK;
-- (Another migration that changes portal.events or these grants changes the value too.)
