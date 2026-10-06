-- Known issues from the 26 Sep 2026 diagnosis (round 2, stream "bugs"). Run on Beta only.
--
-- What changes and why:
-- 1. sync_current_companionships() has no access check, and anon (the public key in every portal page) and
--    authenticated could run it through PostgREST. It writes: on a copy of Beta one anonymous call created 88
--    companionships and 181 memberships. Nothing calls it (checked read-only on 27 Sep 2026): not the portal
--    pages, portal-api, DA Management, Slidev, another database function or trigger, and no Appsmith action,
--    JS object or widget in gfm-test4; pg_cron is not installed. So anon and authenticated lose EXECUTE.
--    postgres (owner) and service_role keep it, so it can still be run by hand on the server.
--    Revoking is not enough on its own: 019, which is run again after every migration as a check, grants EXECUTE
--    to authenticated again, and anyone can sign up and get a signed-in token. So the function itself now refuses
--    every caller except the service role (its verified JWT) and a direct postgres or supabase_admin session.
--    The rest of its body is unchanged (taken read-only from live Beta on 27 Sep 2026).
-- 2. The reporting week rolled over by UTC. current_reporting_sunday() used current_date and the database runs
--    in UTC, so on Sunday from 00:00 to 02:00 in summer (to 01:00 in winter) Berlin still got last week. It
--    now takes today's date in Europe/Berlin, through the new helper reporting_sunday_at(timestamptz) (also
--    used by the check below and by the tests). At every other time the result is the same as before.
--    Its users follow without changes: Planning (form week, closed weeks, the "this plan is for last week"
--    check), Call-ins (latest week, zone notes), the weekly mission focus, the presentation KPIs,
--    start_current_weekly_report, get_previous_planning_answers, get_previous_weekly_new_members and the view
--    current_weekly_reports (the last four are also used by Appsmith Beta). The view current_reporting_week
--    compared with current_date itself; it now uses current_reporting_sunday() (current_area_reporting_status
--    reads that view). Dashboards (dashboards.*) do not use either; the reminders already use Berlin time.
--    Not changed: "today" checks such as assignment start and end dates still use the UTC date.
-- 3. Calendar: one date of a repeating event can now be deleted. portal.events gets skipped_dates (dates in
--    the event's own time zone, normally Europe/Berlin); portal-api leaves those dates out of the calendar,
--    the Overview and the reminders. Deleting a whole event needs no database change.
-- Replaced SECURITY DEFINER function: sync_current_companionships() (search_path now public, pg_temp; EXECUTE for
-- postgres and service_role only, not authenticated, on purpose). reporting_sunday_at is not SECURITY DEFINER: it
-- only does date arithmetic and, like current_reporting_sunday, may be run by everyone.
--
-- Apply (back up Beta first; 019 and 020 must already be applied). The file is plain ASCII:
--   Get-Content portal-api/migrations/026_known_issues.sql -Raw |
--     docker exec -i gfm-beta-supabase-db-1 psql -U postgres -d postgres -v ON_ERROR_STOP=1
-- (supabase_admin works too; the file switches to postgres so everything stays owned by postgres.)
-- Then run 019 again as a check (it must end with COMMIT):
--   Get-Content portal-api/migrations/019_restrict_public_functions.sql -Raw |
--     docker exec -i gfm-beta-supabase-db-1 psql -U supabase_admin -d postgres -v ON_ERROR_STOP=1
-- If it stops on the lock timeout (a long query holds portal.events or the view), run it again a minute later.
-- Safe to run again: CREATE OR REPLACE, REVOKE, ADD COLUMN IF NOT EXISTS, then a check that stops on any problem.
-- After 019, has_function_privilege('authenticated', 'public.sync_current_companionships()', 'EXECUTE') is true
-- again; that is expected and harmless, because the function refuses signed-in callers (see the check below).
-- Rollback: 026_known_issues_rollback.sql (roll back portal-api first; see that file).
BEGIN;
SET LOCAL lock_timeout = '10s';

DO $$
BEGIN
  IF current_user NOT IN ('postgres', 'supabase_admin') THEN
    RAISE EXCEPTION 'Run this file as postgres or supabase_admin (see its header), not as %.', current_user;
  END IF;
END $$;
SET LOCAL ROLE postgres;

-- 1. Companionship sync: only the server (the owner, the service role). The caller check comes first; the rest is
--    the body from before 026, unchanged.
CREATE OR REPLACE FUNCTION public.sync_current_companionships()
 RETURNS void
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path = public, pg_temp
AS $function$
declare
    area_record record;
    current_companionship_id bigint;
    caller_role text;
begin

    -- Migration 026: only the server may run this. Through the API (PostgREST) the caller's role comes from the
    -- verified JWT: anon and authenticated are refused even if they have EXECUTE (019 grants it to authenticated
    -- again), service_role is allowed. Without JWT claims only a direct postgres or supabase_admin session is.
    caller_role := coalesce(
        nullif(current_setting('request.jwt.claims', true), '')::jsonb ->> 'role',
        nullif(current_setting('request.jwt.claim.role', true), ''));
    if not (caller_role = 'service_role'
            or (caller_role is null and session_user in ('postgres', 'supabase_admin'))) then
        raise exception 'sync_current_companionships() can only be run on the server (service role or postgres).'
            using errcode = '42501';
    end if;

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
COMMENT ON FUNCTION public.sync_current_companionships() IS
  'Server only (migration 026): refuses API callers other than service_role, whatever EXECUTE grants say. Nothing calls it; run by hand as postgres.';
REVOKE ALL ON FUNCTION public.sync_current_companionships() FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.sync_current_companionships() TO postgres, service_role;

-- 2. Reporting Sunday in Berlin time. One expression, so the planner can still inline both functions.
CREATE OR REPLACE FUNCTION public.reporting_sunday_at(at_time timestamptz)
RETURNS date
LANGUAGE sql
STABLE
AS $function$
  SELECT (at_time AT TIME ZONE 'Europe/Berlin')::date
         - extract(dow FROM (at_time AT TIME ZONE 'Europe/Berlin'))::integer;
$function$;
COMMENT ON FUNCTION public.reporting_sunday_at(timestamptz) IS
  'The reporting Sunday (Europe/Berlin) of the week containing at_time: that day if it is a Sunday in Berlin, else the Sunday before. Migration 026.';

CREATE OR REPLACE FUNCTION public.current_reporting_sunday()
RETURNS date
LANGUAGE sql
STABLE
AS $function$
  SELECT public.reporting_sunday_at(now());
$function$;
COMMENT ON FUNCTION public.current_reporting_sunday() IS
  'This week''s reporting Sunday in Europe/Berlin (it rolls over at midnight Berlin time, not UTC). Migration 026.';

CREATE OR REPLACE VIEW public.current_reporting_week
WITH (security_invoker = true) AS
SELECT reporting_weeks.id,
       reporting_weeks.sunday,
       reporting_weeks.planning_open_at,
       reporting_weeks.planning_due_at
FROM public.reporting_weeks
WHERE reporting_weeks.sunday <= public.current_reporting_sunday()
ORDER BY reporting_weeks.sunday DESC
LIMIT 1;

-- 3. Deleted dates of repeating events.
ALTER TABLE portal.events ADD COLUMN IF NOT EXISTS skipped_dates date[] NOT NULL DEFAULT '{}';
COMMENT ON COLUMN portal.events.skipped_dates IS
  'Dates (in the event''s time zone) of a repeating event that were deleted one by one. Migration 026.';

NOTIFY pgrst, 'reload schema';

-- Check: stops (and undoes everything above) on any problem.
DO $$
DECLARE
  found text;
  hour timestamptz;
  old_sunday date;
  new_sunday date;
  berlin timestamp;
  api_role text;
BEGIN
  -- 1. Who may run the sync.
  IF has_function_privilege('anon', 'public.sync_current_companionships()', 'EXECUTE')
     OR has_function_privilege('authenticated', 'public.sync_current_companionships()', 'EXECUTE')
     OR has_function_privilege('public', 'public.sync_current_companionships()', 'EXECUTE') THEN
    RAISE EXCEPTION 'anon, authenticated or PUBLIC can still run sync_current_companionships().';
  END IF;
  IF NOT has_function_privilege('service_role', 'public.sync_current_companionships()', 'EXECUTE') THEN
    RAISE EXCEPTION 'service_role lost EXECUTE on sync_current_companionships().';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_proc WHERE oid = 'public.sync_current_companionships()'::regprocedure AND prosecdef
                 AND proconfig = ARRAY['search_path=public, pg_temp']) THEN
    RAISE EXCEPTION 'sync_current_companionships() is not SECURITY DEFINER with search_path public, pg_temp.';
  END IF;
  -- The function itself refuses API callers, so the grant 019 gives authenticated again does no harm. Tried as
  -- PostgREST would call it (the role in request.jwt.claims); each try stops at the check before any write and
  -- is undone with its subtransaction. If the check were missing, the P0001 below would stop this migration.
  FOREACH api_role IN ARRAY ARRAY['anon', 'authenticated', ''] LOOP
    BEGIN
      PERFORM set_config('request.jwt.claims', json_build_object('role', api_role)::text, true);
      PERFORM public.sync_current_companionships();
      RAISE EXCEPTION USING ERRCODE = 'P0001',
        MESSAGE = format('sync_current_companionships() ran for an API caller with role "%s".', api_role);
    EXCEPTION WHEN insufficient_privilege THEN
      IF SQLERRM <> 'sync_current_companionships() can only be run on the server (service role or postgres).' THEN
        RAISE;
      END IF;
    END;
  END LOOP;

  -- 2. The reporting Sunday at the week boundary, summer (CEST, UTC+2) and winter (CET, UTC+1).
  SELECT string_agg(format('%s gave %s, expected %s', t, public.reporting_sunday_at(t), expected), '; ')
    INTO found
  FROM (VALUES
    ('2026-09-26 21:59:59+00'::timestamptz, '2026-09-20'::date),  -- Saturday 23:59:59 in Berlin
    ('2026-09-26 22:00:00+00', '2026-09-27'),                      -- Sunday 00:00 in Berlin (UTC still Saturday)
    ('2026-09-26 23:59:59+00', '2026-09-27'),                      -- Sunday 01:59:59 in Berlin
    ('2026-09-27 12:00:00+00', '2026-09-27'),
    ('2026-10-03 21:59:59+00', '2026-09-27'),                      -- next Saturday 23:59:59 in Berlin
    ('2026-11-28 22:59:59+00', '2026-11-22'),                      -- Saturday 23:59:59 in Berlin (winter)
    ('2026-11-28 23:00:00+00', '2026-11-29'),                      -- Sunday 00:00 in Berlin (winter)
    ('2026-10-25 00:30:00+00', '2026-10-25')                       -- the night summer time ends
  ) v(t, expected)
  WHERE public.reporting_sunday_at(t) IS DISTINCT FROM expected;
  IF found IS NOT NULL THEN
    RAISE EXCEPTION 'reporting_sunday_at is wrong: %', found;
  END IF;

  -- Every hour of 2026 and 2027: the same Sunday as the old UTC rule, except in the hours after midnight Berlin
  -- on a Sunday while it is still Saturday in UTC.
  FOR hour IN SELECT generate_series('2026-01-01 00:00+00'::timestamptz, '2027-12-31 23:00+00', interval '1 hour') LOOP
    old_sunday := (hour AT TIME ZONE 'UTC')::date - extract(dow FROM (hour AT TIME ZONE 'UTC'))::integer;
    new_sunday := public.reporting_sunday_at(hour);
    berlin := hour AT TIME ZONE 'Europe/Berlin';
    IF new_sunday IS DISTINCT FROM old_sunday
       AND NOT (extract(dow FROM berlin) = 0 AND extract(dow FROM (hour AT TIME ZONE 'UTC')) = 6
                AND new_sunday = berlin::date AND old_sunday = berlin::date - 7) THEN
      RAISE EXCEPTION 'reporting_sunday_at differs from the old rule outside the Sunday boundary at %', hour;
    END IF;
  END LOOP;

  IF public.current_reporting_sunday() IS DISTINCT FROM public.reporting_sunday_at(now()) THEN
    RAISE EXCEPTION 'current_reporting_sunday() does not use reporting_sunday_at(now()).';
  END IF;
  IF extract(dow FROM public.current_reporting_sunday()) <> 0 THEN
    RAISE EXCEPTION 'current_reporting_sunday() is not a Sunday.';
  END IF;
  IF (SELECT id FROM public.current_reporting_week) IS DISTINCT FROM
     (SELECT id FROM public.reporting_weeks WHERE sunday <= public.current_reporting_sunday() ORDER BY sunday DESC LIMIT 1) THEN
    RAISE EXCEPTION 'current_reporting_week does not show the latest week up to current_reporting_sunday().';
  END IF;
  IF NOT (SELECT coalesce('security_invoker=true' = ANY(reloptions), false) FROM pg_class
          WHERE oid = 'public.current_reporting_week'::regclass) THEN
    RAISE EXCEPTION 'current_reporting_week lost security_invoker.';
  END IF;
  IF NOT has_table_privilege('authenticated', 'public.current_reporting_week', 'SELECT')
     OR NOT has_function_privilege('authenticated', 'public.current_reporting_sunday()', 'EXECUTE')
     OR NOT has_function_privilege('anon', 'public.current_reporting_sunday()', 'EXECUTE')
     OR NOT has_function_privilege('authenticated', 'public.reporting_sunday_at(timestamptz)', 'EXECUTE') THEN
    RAISE EXCEPTION 'The reporting week function or view lost a grant it had before.';
  END IF;

  -- 3. The new column.
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'portal' AND table_name = 'events'
                 AND column_name = 'skipped_dates' AND data_type = 'ARRAY' AND is_nullable = 'NO') THEN
    RAISE EXCEPTION 'portal.events.skipped_dates is missing.';
  END IF;

  -- Everything touched stays owned by postgres.
  SELECT string_agg(x, ', ') INTO found FROM (
    SELECT 'reporting_sunday_at' x FROM pg_proc WHERE oid = 'public.reporting_sunday_at(timestamptz)'::regprocedure AND pg_get_userbyid(proowner) <> 'postgres'
    UNION ALL SELECT 'sync_current_companionships' FROM pg_proc WHERE oid = 'public.sync_current_companionships()'::regprocedure AND pg_get_userbyid(proowner) <> 'postgres'
    UNION ALL SELECT 'current_reporting_sunday' FROM pg_proc WHERE oid = 'public.current_reporting_sunday()'::regprocedure AND pg_get_userbyid(proowner) <> 'postgres'
    UNION ALL SELECT 'current_reporting_week' FROM pg_class WHERE oid = 'public.current_reporting_week'::regclass AND pg_get_userbyid(relowner) <> 'postgres') o;
  IF found IS NOT NULL THEN
    RAISE EXCEPTION 'Not owned by postgres: %', found;
  END IF;
END $$;

COMMIT;

-- Verify after COMMIT and after 019 (read-only):
--   docker exec gfm-beta-supabase-db-1 psql -U postgres -d postgres -At -c "BEGIN READ ONLY" -c "SELECT public.current_reporting_sunday(), (SELECT sunday FROM public.current_reporting_week), has_function_privilege('anon','public.sync_current_companionships()','EXECUTE'), position('can only be run on the server' in pg_get_functiondef('public.sync_current_companionships()'::regprocedure)) > 0" -c "ROLLBACK"
-- Expected: this week's Sunday (Berlin), the latest existing week up to it, f and t.
-- A signed-in caller is refused (in a read-only transaction, so nothing could be written even if it were not):
--   docker exec gfm-beta-supabase-db-1 psql -U postgres -d postgres -c "BEGIN READ ONLY" -c "SET LOCAL ROLE authenticated" -c "SELECT set_config('request.jwt.claims', json_build_object('role','authenticated')::text, true)" -c "SELECT public.sync_current_companionships()" -c "ROLLBACK"
-- Expected: ERROR: sync_current_companionships() can only be run on the server (service role or postgres).
-- ("permission denied for function" is also a refusal: it means 019 has not been run again yet.)
