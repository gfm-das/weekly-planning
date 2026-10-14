-- Migration 049 (Oct 2026): a log of every unlock of a Weekly Planning plan, and one function that unlocks and logs.
-- Run on Beta only, as supabase_admin. Back up first (CLAUDE.md, "Before any database change").
-- (Numbering: 046 Geo data, 047 FC numbers and 048 Delete retired are on the round-13 importer branch; renumber if another
-- branch took 049 first.)
--
-- Why: round 13, task 23 "WP Questions: be able to unlock stuff". A leader reopens a submitted plan through the portal
-- (POST /api/planning/reports/<id>/unlock). Until now nothing recorded who did it, and a plan a manager had LOCKED could not be
-- reopened through the portal at all (public.unsubmit_weekly_report refuses everything but SUBMITTED). Now:
-- 1. public.planning_unlock_log: one row per unlock (the plan, its area and week, the status before, who, an optional note,
--    when). Managers of the area's mission can read it (row-level security); nobody can write to it except through the
--    function below (no INSERT/UPDATE/DELETE right for authenticated or anon).
-- 2. public.reopen_weekly_report_logged(report_id, note): calls the existing public.reopen_weekly_report (which checks the
--    stewardship with can_unlock_planning_area and lets only mission managers reopen a LOCKED plan, and writes the plan as a
--    DRAFT again) and then writes the log row, in the same transaction. If the unlock is refused, nothing is logged.
--    SECURITY DEFINER, so the revoke/grant lines below matter (migration 019 re-checks them).
-- Nothing else changes: plan contents, the guard triggers and public.unsubmit_weekly_report stay as they are.
--
-- Apply (back up Beta first). Join the lines with plain line feeds:
--   (Get-Content portal-api/migrations/049_planning_unlock_log.sql) -join "`n" |
--     docker exec -i gfm-beta-supabase-db-1 psql -U supabase_admin -d postgres -v ON_ERROR_STOP=1
-- (Ubuntu server: psql as supabase_admin in the db container, the same way.) Then run 019_restrict_public_functions.sql
-- again as a check (it must end with COMMIT). Apply this BEFORE the new portal-api image: its unlock calls the function.
-- Not run in the night session (no database there): test it on a throw-away copy first.
-- Rollback: 049_planning_unlock_log_rollback.sql (drops the function and the log table WITH its rows).
BEGIN;
SET LOCAL lock_timeout = '10s';

DO $$
BEGIN
  IF session_user NOT IN ('supabase_admin', 'postgres') THEN
    RAISE EXCEPTION 'Run this file as supabase_admin (see its header), not as %.', session_user;
  END IF;
  IF to_regclass('public.weekly_area_reports') IS NULL
     OR to_regprocedure('public.reopen_weekly_report(bigint)') IS NULL
     OR to_regprocedure('public.is_mission_manager_for_area(bigint)') IS NULL THEN
    RAISE EXCEPTION 'Weekly Planning tables or functions are missing (baseline).';
  END IF;
END $$;

CREATE TABLE IF NOT EXISTS public.planning_unlock_log (
  id bigserial PRIMARY KEY,
  weekly_area_report_id bigint NOT NULL,
  area_id bigint NOT NULL,
  reporting_week_id bigint,
  previous_status text NOT NULL CHECK (previous_status IN ('SUBMITTED', 'LOCKED')),
  unlocked_by uuid NOT NULL,
  note text CHECK (note IS NULL OR char_length(note) <= 500),
  unlocked_at timestamptz NOT NULL DEFAULT now()
);
COMMENT ON TABLE public.planning_unlock_log IS 'One row per unlock of a Weekly Planning plan (public.reopen_weekly_report_logged). No foreign keys on purpose: the log outlives a deleted plan.';
CREATE INDEX IF NOT EXISTS planning_unlock_log_report_idx ON public.planning_unlock_log (weekly_area_report_id);
CREATE INDEX IF NOT EXISTS planning_unlock_log_area_idx ON public.planning_unlock_log (area_id, unlocked_at DESC);

ALTER TABLE public.planning_unlock_log ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.planning_unlock_log FROM PUBLIC, anon, authenticated;
GRANT SELECT ON public.planning_unlock_log TO authenticated;
GRANT ALL ON public.planning_unlock_log TO service_role;
GRANT USAGE, SELECT ON SEQUENCE public.planning_unlock_log_id_seq TO service_role;
DROP POLICY IF EXISTS planning_unlock_log_managers_read ON public.planning_unlock_log;
CREATE POLICY planning_unlock_log_managers_read ON public.planning_unlock_log
  FOR SELECT TO authenticated USING (public.is_mission_manager_for_area(area_id));

CREATE OR REPLACE FUNCTION public.reopen_weekly_report_logged(target_report_id bigint, unlock_note text DEFAULT NULL)
RETURNS TABLE(weekly_report_id bigint, status text, previous_status text)
LANGUAGE plpgsql SECURITY DEFINER
SET search_path TO 'public', 'pg_temp'
AS $$
DECLARE
  v_area_id bigint;
  v_week_id bigint;
  v_status text;
  v_note text := NULLIF(btrim(unlock_note), '');
BEGIN
  IF auth.uid() IS NULL THEN
    RAISE EXCEPTION 'Sign in to unlock a plan.' USING ERRCODE = '42501';
  END IF;
  IF v_note IS NOT NULL AND char_length(v_note) > 500 THEN
    RAISE EXCEPTION 'The note must be 500 characters or fewer.' USING ERRCODE = '22023';
  END IF;
  SELECT war.area_id, war.reporting_week_id, war.status INTO v_area_id, v_week_id, v_status
  FROM public.weekly_area_reports war WHERE war.id = target_report_id;
  -- The stewardship, the LOCKED-needs-a-manager rule and the status check are the existing function's.
  PERFORM public.reopen_weekly_report(target_report_id);
  INSERT INTO public.planning_unlock_log (weekly_area_report_id, area_id, reporting_week_id, previous_status, unlocked_by, note)
  VALUES (target_report_id, v_area_id, v_week_id, v_status, auth.uid(), v_note);
  RETURN QUERY SELECT target_report_id, 'DRAFT'::text, v_status;
END;
$$;

REVOKE EXECUTE ON FUNCTION public.reopen_weekly_report_logged(bigint, text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.reopen_weekly_report_logged(bigint, text) TO authenticated, service_role;

-- Check: table, policy, function and the grants are as intended.
DO $$
BEGIN
  IF to_regclass('public.planning_unlock_log') IS NULL
     OR to_regprocedure('public.reopen_weekly_report_logged(bigint,text)') IS NULL
     OR NOT EXISTS (SELECT 1 FROM pg_policies WHERE schemaname = 'public' AND tablename = 'planning_unlock_log'
                    AND policyname = 'planning_unlock_log_managers_read') THEN
    RAISE EXCEPTION 'Check failed: the unlock log is not set up.';
  END IF;
  IF has_function_privilege('anon', 'public.reopen_weekly_report_logged(bigint,text)', 'EXECUTE')
     OR has_table_privilege('authenticated', 'public.planning_unlock_log', 'INSERT')
     OR has_table_privilege('anon', 'public.planning_unlock_log', 'SELECT') THEN
    RAISE EXCEPTION 'Check failed: anon may run the function, or authenticated may write the log.';
  END IF;
END $$;

COMMIT;