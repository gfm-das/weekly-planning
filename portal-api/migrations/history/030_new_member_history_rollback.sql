-- Rollback of 030_new_member_history.sql. Run on Beta only, as supabase_admin.
--
-- What it restores (the state before 030, read from the live database on 27 Sep 2026):
-- - the 84 weekly plan rows without a person, exactly as they were (same ids, values and timestamps), from the copy
--   030 kept in public.cleanup_030_removed_rows;
-- - both foreign keys with ON DELETE SET NULL again;
-- - no public.cleanup_030_removed_rows table (it is dropped once the rows are back).
-- Rows are put back only where their plan still exists. A row whose plan is gone (the test-data tool removed the
-- empty drafts 20, 21, 24 or 25 after 030) is skipped and named in a NOTICE; it stays in the copy table, which is
-- then kept (postgres only). Such a row comes back with its plan from the backup taken before the clean-up; run this
-- file again afterwards, or drop the copy table once those rows are not wanted. Nothing in the code has to be rolled
-- back with it (030 changed no function or view).
--
-- Apply:
--   (Get-Content portal-api/migrations/030_new_member_history_rollback.sql) -join "`n" |
--     docker exec -i gfm-beta-supabase-db-1 psql -U supabase_admin -d postgres -v ON_ERROR_STOP=1
--   (Git Bash: sed 's/\r$//' portal-api/migrations/030_new_member_history_rollback.sql | docker exec -i ...)
-- Then run 019 again as a check. Safe to run again (a second run finds nothing to do). The last block checks the result.
BEGIN;
SET LOCAL lock_timeout = '10s';

DO $$
BEGIN
  IF NOT (SELECT rolsuper FROM pg_roles WHERE rolname = current_user) THEN
    RAISE EXCEPTION 'Run this file as supabase_admin (see its header), not as %.', current_user;
  END IF;
END $$;
SET LOCAL ROLE postgres;

-- 1. The foreign keys first (a row without a person is allowed either way).
DO $$
BEGIN
  IF (SELECT confdeltype FROM pg_constraint WHERE conname = 'weekly_new_members_new_member_id_fkey'
        AND conrelid = 'public.weekly_new_members'::regclass) IS DISTINCT FROM 'n' THEN
    ALTER TABLE public.weekly_new_members DROP CONSTRAINT IF EXISTS weekly_new_members_new_member_id_fkey;
    ALTER TABLE public.weekly_new_members ADD CONSTRAINT weekly_new_members_new_member_id_fkey
      FOREIGN KEY (new_member_id) REFERENCES public.new_members(id) ON DELETE SET NULL;
  END IF;
  IF (SELECT confdeltype FROM pg_constraint WHERE conname = 'weekly_baptismal_date_friends_baptismal_date_person_id_fkey'
        AND conrelid = 'public.weekly_baptismal_date_friends'::regclass) IS DISTINCT FROM 'n' THEN
    ALTER TABLE public.weekly_baptismal_date_friends
      DROP CONSTRAINT IF EXISTS weekly_baptismal_date_friends_baptismal_date_person_id_fkey;
    ALTER TABLE public.weekly_baptismal_date_friends ADD CONSTRAINT weekly_baptismal_date_friends_baptismal_date_person_id_fkey
      FOREIGN KEY (baptismal_date_person_id) REFERENCES public.baptismal_date_people(id) ON DELETE SET NULL;
  END IF;
END $$;

-- 2. The rows, from the copy (only while the copy exists: after the first run it is gone, or holds only rows whose
--    plan is gone).
DO $$
DECLARE
  missing text;
  skipped text;
BEGIN
  IF to_regclass('public.cleanup_030_removed_rows') IS NULL THEN
    RETURN;
  END IF;
  -- Rows whose plan no longer exists cannot come back (their plan was removed after 030, e.g. by the test-data
  -- tool). They are skipped and stay in the copy.
  CREATE TEMP TABLE cleanup_030_back ON COMMIT DROP AS
  SELECT c.* FROM public.cleanup_030_removed_rows c
  WHERE EXISTS (SELECT 1 FROM public.weekly_area_reports r WHERE r.id = (c.row_data->>'weekly_area_report_id')::bigint);
  SELECT string_agg(format('%s %s (plan %s)', c.table_name, c.row_id, c.row_data->>'weekly_area_report_id'), ', '
                    ORDER BY c.table_name, c.row_id) INTO skipped
  FROM public.cleanup_030_removed_rows c
  WHERE NOT EXISTS (SELECT 1 FROM cleanup_030_back b WHERE b.table_name = c.table_name AND b.row_id = c.row_id);

  -- As postgres without a signed-in user: a trusted write for the plan guards, which keep the values as given.
  INSERT INTO public.weekly_new_members OVERRIDING SYSTEM VALUE
  SELECT (jsonb_populate_record(NULL::public.weekly_new_members, c.row_data)).*
  FROM cleanup_030_back c
  WHERE c.table_name = 'weekly_new_members'
    AND NOT EXISTS (SELECT 1 FROM public.weekly_new_members w WHERE w.id = c.row_id);

  INSERT INTO public.weekly_baptismal_date_friends OVERRIDING SYSTEM VALUE
  SELECT (jsonb_populate_record(NULL::public.weekly_baptismal_date_friends, c.row_data)).*
  FROM cleanup_030_back c
  WHERE c.table_name = 'weekly_baptismal_date_friends'
    AND NOT EXISTS (SELECT 1 FROM public.weekly_baptismal_date_friends w WHERE w.id = c.row_id);
  -- fill_weekly_baptismal_date_context sets stake_id from the plan's ward or branch on insert; put back the saved
  -- values (this update does not fire it: it runs only when the person or the plan changes).
  UPDATE public.weekly_baptismal_date_friends w
  SET stake_id = r.stake_id, finding_source = r.finding_source, updated_at = r.updated_at
  FROM cleanup_030_back c
  CROSS JOIN LATERAL jsonb_populate_record(NULL::public.weekly_baptismal_date_friends, c.row_data) r
  WHERE c.table_name = 'weekly_baptismal_date_friends' AND w.id = c.row_id;

  -- Every row put back must be exactly as copied.
  SELECT string_agg(format('%s %s', c.table_name, c.row_id), ', ') INTO missing
  FROM cleanup_030_back c
  WHERE (c.table_name = 'weekly_new_members' AND NOT EXISTS (
           SELECT 1 FROM public.weekly_new_members w WHERE w.id = c.row_id AND to_jsonb(w) = c.row_data))
     OR (c.table_name = 'weekly_baptismal_date_friends' AND NOT EXISTS (
           SELECT 1 FROM public.weekly_baptismal_date_friends w WHERE w.id = c.row_id AND to_jsonb(w) = c.row_data));
  IF missing IS NOT NULL THEN
    RAISE EXCEPTION 'Check failed: these rows did not come back exactly: %', missing;
  END IF;
  RAISE NOTICE 'Put back % weekly_new_members rows and % weekly_baptismal_date_friends row(s).',
    (SELECT count(*) FROM cleanup_030_back WHERE table_name = 'weekly_new_members'),
    (SELECT count(*) FROM cleanup_030_back WHERE table_name = 'weekly_baptismal_date_friends');

  -- The copy is dropped when everything is back; otherwise it keeps only the rows that could not come back.
  DELETE FROM public.cleanup_030_removed_rows c
  USING cleanup_030_back b WHERE b.table_name = c.table_name AND b.row_id = c.row_id;
  IF skipped IS NOT NULL THEN
    RAISE NOTICE 'Not put back, because their plan no longer exists (removed after 030, e.g. by the test-data tool): %. They stay in public.cleanup_030_removed_rows (postgres only). They come back with their plan from the backup taken before the clean-up; run this file again afterwards, or drop that table once they are not wanted.', skipped;
  ELSE
    DROP TABLE public.cleanup_030_removed_rows;
  END IF;
END $$;

DO $$
BEGIN
  IF (SELECT confdeltype FROM pg_constraint WHERE conname = 'weekly_new_members_new_member_id_fkey'
        AND conrelid = 'public.weekly_new_members'::regclass) IS DISTINCT FROM 'n'
     OR (SELECT confdeltype FROM pg_constraint WHERE conname = 'weekly_baptismal_date_friends_baptismal_date_person_id_fkey'
        AND conrelid = 'public.weekly_baptismal_date_friends'::regclass) IS DISTINCT FROM 'n' THEN
    RAISE EXCEPTION 'Check failed: a foreign key is not ON DELETE SET NULL.';
  END IF;
  -- The copy is gone, or holds only rows whose plan no longer exists (named in the NOTICE above).
  IF to_regclass('public.cleanup_030_removed_rows') IS NOT NULL THEN
    IF EXISTS (SELECT 1 FROM public.cleanup_030_removed_rows c
               WHERE EXISTS (SELECT 1 FROM public.weekly_area_reports r
                             WHERE r.id = (c.row_data->>'weekly_area_report_id')::bigint)) THEN
      RAISE EXCEPTION 'Check failed: the copy still holds rows whose plan exists.';
    END IF;
    IF has_table_privilege('anon', 'public.cleanup_030_removed_rows', 'SELECT')
       OR has_table_privilege('authenticated', 'public.cleanup_030_removed_rows', 'SELECT')
       OR has_table_privilege('service_role', 'public.cleanup_030_removed_rows', 'SELECT') THEN
      RAISE EXCEPTION 'Check failed: the copy table can be read through the API.';
    END IF;
  END IF;
END $$;

NOTIFY pgrst, 'reload schema';
COMMIT;
