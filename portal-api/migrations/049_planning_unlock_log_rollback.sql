-- Rollback of 049_planning_unlock_log.sql. Run on Beta only, as supabase_admin.
--
-- What it does: drops public.reopen_weekly_report_logged and public.planning_unlock_log WITH ITS ROWS (take a backup first
-- if the log should be kept). Do it together with the code rollback (the portal-api image before this change): the old
-- unlock calls public.unsubmit_weekly_report, which this migration never touched, so unlocking keeps working either way.
--
-- Apply:
--   (Get-Content portal-api/migrations/049_planning_unlock_log_rollback.sql) -join "`n" |
--     docker exec -i gfm-beta-supabase-db-1 psql -U supabase_admin -d postgres -v ON_ERROR_STOP=1
-- Then run 019_restrict_public_functions.sql again as a check (it must end with COMMIT).
BEGIN;
SET LOCAL lock_timeout = '10s';

DO $$
BEGIN
  IF session_user NOT IN ('supabase_admin', 'postgres') THEN
    RAISE EXCEPTION 'Run this file as supabase_admin (see its header), not as %.', session_user;
  END IF;
END $$;

DROP FUNCTION IF EXISTS public.reopen_weekly_report_logged(bigint, text);
DROP TABLE IF EXISTS public.planning_unlock_log;

DO $$
BEGIN
  IF to_regclass('public.planning_unlock_log') IS NOT NULL
     OR to_regprocedure('public.reopen_weekly_report_logged(bigint,text)') IS NOT NULL THEN
    RAISE EXCEPTION 'Check failed: the unlock log is still there.';
  END IF;
END $$;

COMMIT;