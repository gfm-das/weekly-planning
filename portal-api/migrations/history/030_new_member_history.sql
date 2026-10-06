-- Tidies the New Member history: weekly plan rows whose person record was deleted. Run on Beta only, as supabase_admin.
--
-- Why: 83 weekly_new_members rows have no new_member_id, and 1 weekly_baptismal_date_friends row has no
-- baptismal_date_person_id. They looked like imported history. They are not. What the database, its backups and
-- Appsmith show (read-only, 27 Sep 2026; details in docs/handoff/round3/cleanup.md):
-- - The historical importer never writes these tables: it keeps the spreadsheets' people in
--   historical_planning_details. These rows were made in Beta between 12 and 21 Sep, on 9 plans of the weeks of
--   6, 13 and 20 Sep (areas 112, 122, 147 and 198), by the test accounts, each time a New Member was added to a plan.
-- - Their New Member records (ids 1 to 23) were deleted before 16 Sep: the oldest backup (gfm-beta-seed.dump,
--   16 Sep) already has the rows without a person. The foreign key is ON DELETE SET NULL, so the rows stayed.
-- - 81 of the 83 hold no answer at all. The other 2 (ids 1113 and 1114, plan 29) hold only test values, such as
--   -1111 as the lesson percentage. The baptismal-date row (id 129, plan 23) holds nothing. No name or any other
--   detail exists anywhere, so none of them can be linked to a real person. Showing them as "name not recorded"
--   entries would invent people: up to 22 in one area and week, where the spreadsheet for that week lists none, and
--   several are the same click saved again (the positions repeat).
-- - Call-ins never listed or counted them (it lists only rows with a person). Weekly Planning shows them as people
--   without a name on those old plans, Beta as empty rows, and the Presentations people counts (dashboards.people_*,
--   migration 025) count them: 26, 45 and 13 new members for the weeks of 6, 13 and 20 Sep, where Call-ins has
--   0, 1 and 0.
--
-- What changes:
-- 1. Exactly these 84 rows are removed (listed below by id; the user confirms the list before the deploy). An exact
--    copy of each row (as JSON) is kept in public.cleanup_030_removed_rows, which only postgres can read (no API role
--    has any right on it, row-level security is on), so the rollback can put every row back as it was.
--    The file stops, and changes nothing, if a listed row has a person again, or if any other row without a person
--    exists (someone deleted a person in the meantime): look at those first. A listed row that is already gone is
--    skipped and counted in the closing NOTICE: the test-data tool (portal-api/tools/remove_test_data.py) removes
--    the empty drafts 20, 21, 24 and 25 with their 8 listed rows, and may run before or after this file.
--    47 of the rows are on the submitted plans 19 (22 rows), 22 (14) and 30 (11). The historical import took these
--    plans over later (they are now its plans for those area-weeks) and the rows stayed inside them. The import
--    never writes weekly_new_members, so the rows are not part of what it imported. Removing them changes these
--    three submitted plans (their nameless rows go); the user confirms that with the list.
-- 2. The two foreign keys change from ON DELETE SET NULL to ON DELETE NO ACTION. A New Member or a friend with a
--    baptismal date who is still on a weekly plan can then no longer be deleted directly (for example in Supabase
--    Studio): the database refuses instead of leaving rows without a person. The app's "Delete (added by mistake)"
--    (migration 023) removes the person's weekly rows first, so it keeps working. Nothing else deletes people.
-- Not changed: Call-ins (get_call_in_people already lists only rows with a person), the Dashboards and Presentations
-- views (with the empty rows gone they count the same people as Call-ins), and every other row. The real history of
-- those weeks (the spreadsheets' people in historical_planning_details) is not touched.
--
-- Apply (back up Beta first; after 028 and 029 if they go out together). Join the lines with plain line feeds:
--   (Get-Content portal-api/migrations/030_new_member_history.sql) -join "`n" |
--     docker exec -i gfm-beta-supabase-db-1 psql -U supabase_admin -d postgres -v ON_ERROR_STOP=1
--   (Git Bash: sed 's/\r$//' portal-api/migrations/030_new_member_history.sql | docker exec -i ...)
-- Then run 019 again as a check (it must end with COMMIT):
--   Get-Content portal-api/migrations/019_restrict_public_functions.sql -Raw |
--     docker exec -i gfm-beta-supabase-db-1 psql -U supabase_admin -d postgres -v ON_ERROR_STOP=1
-- The file waits at most 10 seconds for a lock (lock timeout), then stops and changes nothing; run it again.
-- Safe to run again: rows already removed are skipped, the constraints are only replaced while they still say
-- SET NULL, and the last block checks the result.
-- Rollback: 030_new_member_history_rollback.sql (puts the 84 rows back exactly and restores ON DELETE SET NULL).
BEGIN;
SET LOCAL lock_timeout = '10s';

DO $$
BEGIN
  IF NOT (SELECT rolsuper FROM pg_roles WHERE rolname = current_user) THEN
    RAISE EXCEPTION 'Run this file as supabase_admin (see its header), not as %.', current_user;
  END IF;
END $$;
-- Everything below belongs to postgres, like the tables it touches.
SET LOCAL ROLE postgres;

-- The copy kept for the rollback. Only postgres (its owner) can read it.
CREATE TABLE IF NOT EXISTS public.cleanup_030_removed_rows (
  table_name text NOT NULL CHECK (table_name IN ('weekly_new_members', 'weekly_baptismal_date_friends')),
  row_id bigint NOT NULL,
  row_data jsonb NOT NULL,
  removed_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (table_name, row_id)
);
COMMENT ON TABLE public.cleanup_030_removed_rows IS 'Migration 030: exact copies of the weekly plan rows without a person that 030 removed (no names, no answers). Read by 030_new_member_history_rollback.sql. Drop it once the cleanup is accepted.';
ALTER TABLE public.cleanup_030_removed_rows ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.cleanup_030_removed_rows FROM PUBLIC, anon, authenticated, service_role;
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'grafana_readonly') THEN
    EXECUTE 'REVOKE ALL ON public.cleanup_030_removed_rows FROM grafana_readonly';
  END IF;
END $$;

-- 1. The 84 rows (27 Sep 2026). The same ids are listed in docs/handoff/round3/cleanup-test-data.md.
CREATE TEMP TABLE cleanup_030_targets (table_name text, row_id bigint) ON COMMIT DROP;
INSERT INTO cleanup_030_targets
SELECT 'weekly_new_members', unnest(ARRAY[
  921, 922, 924, 925, 927, 928, 929, 930, 933, 934, 935, 936, 938, 940, 941, 943, 944, 945, 946, 952, 953, 955,
  962, 963, 966, 967, 971, 982, 983, 985, 986, 987, 988, 989, 990, 995, 996, 997, 998, 999, 1004, 1006, 1011,
  1012, 1013, 1014, 1015, 1019, 1020, 1021, 1045, 1048, 1051, 1052, 1056, 1057, 1059, 1065, 1066, 1068, 1070,
  1071, 1075, 1077, 1080, 1085, 1086, 1101, 1102, 1103, 1113, 1114, 1115, 1116, 1118, 1119, 1122, 1123, 1124,
  1126, 1127, 1128, 1129]::bigint[])
UNION ALL SELECT 'weekly_baptismal_date_friends', 129;

DO $$
DECLARE
  found text;
BEGIN
  IF (SELECT count(*) FROM cleanup_030_targets) <> 84 THEN
    RAISE EXCEPTION 'The list must hold 84 rows.';
  END IF;
  -- A listed row that is still there must still be without a person.
  SELECT string_agg(format('%s %s', t.table_name, t.row_id), ', ') INTO found
  FROM cleanup_030_targets t
  WHERE (t.table_name = 'weekly_new_members' AND EXISTS (
           SELECT 1 FROM public.weekly_new_members w WHERE w.id = t.row_id AND w.new_member_id IS NOT NULL))
     OR (t.table_name = 'weekly_baptismal_date_friends' AND EXISTS (
           SELECT 1 FROM public.weekly_baptismal_date_friends w WHERE w.id = t.row_id AND w.baptismal_date_person_id IS NOT NULL));
  IF found IS NOT NULL THEN
    RAISE EXCEPTION 'Stopped, nothing changed: these listed rows have a person now: %', found;
  END IF;
  -- Any other row without a person appeared after the list was made: look at it before removing anything.
  SELECT string_agg(x, ', ') INTO found FROM (
    SELECT 'weekly_new_members ' || w.id AS x FROM public.weekly_new_members w
    WHERE w.new_member_id IS NULL
      AND NOT EXISTS (SELECT 1 FROM cleanup_030_targets t WHERE t.table_name = 'weekly_new_members' AND t.row_id = w.id)
    UNION ALL
    SELECT 'weekly_baptismal_date_friends ' || w.id FROM public.weekly_baptismal_date_friends w
    WHERE w.baptismal_date_person_id IS NULL
      AND NOT EXISTS (SELECT 1 FROM cleanup_030_targets t WHERE t.table_name = 'weekly_baptismal_date_friends' AND t.row_id = w.id)
  ) extra;
  IF found IS NOT NULL THEN
    RAISE EXCEPTION 'Stopped, nothing changed: rows without a person that are not on the list: %. Check them first.', found;
  END IF;
END $$;

-- The listed rows that are still there. A listed row can already be gone: removed by an earlier run of this file,
-- or together with its plan (the test-data tool removes the empty drafts 20, 21, 24 and 25, which hold 8 of these
-- rows; the tool may run before or after this file).
CREATE TEMP TABLE cleanup_030_present ON COMMIT DROP AS
SELECT t.table_name, t.row_id FROM cleanup_030_targets t
WHERE (t.table_name = 'weekly_new_members' AND EXISTS (SELECT 1 FROM public.weekly_new_members w WHERE w.id = t.row_id))
   OR (t.table_name = 'weekly_baptismal_date_friends'
       AND EXISTS (SELECT 1 FROM public.weekly_baptismal_date_friends w WHERE w.id = t.row_id));

-- Keep the copies (a re-run finds the rows gone), then remove the rows. As postgres without a signed-in user this is
-- a trusted write for the plan guards, so rows on submitted plans can be removed too (47 of them are on the
-- submitted, imported plans 19, 22 and 30; the import never wrote them).
INSERT INTO public.cleanup_030_removed_rows (table_name, row_id, row_data)
SELECT 'weekly_new_members', w.id, to_jsonb(w)
FROM public.weekly_new_members w JOIN cleanup_030_targets t ON t.table_name = 'weekly_new_members' AND t.row_id = w.id
ON CONFLICT (table_name, row_id) DO NOTHING;
INSERT INTO public.cleanup_030_removed_rows (table_name, row_id, row_data)
SELECT 'weekly_baptismal_date_friends', w.id, to_jsonb(w)
FROM public.weekly_baptismal_date_friends w
JOIN cleanup_030_targets t ON t.table_name = 'weekly_baptismal_date_friends' AND t.row_id = w.id
ON CONFLICT (table_name, row_id) DO NOTHING;

DELETE FROM public.weekly_new_members w
USING cleanup_030_targets t WHERE t.table_name = 'weekly_new_members' AND t.row_id = w.id AND w.new_member_id IS NULL;
DELETE FROM public.weekly_baptismal_date_friends w
USING cleanup_030_targets t
WHERE t.table_name = 'weekly_baptismal_date_friends' AND t.row_id = w.id AND w.baptismal_date_person_id IS NULL;

-- 2. No more rows without a person: refuse to delete someone who is still on a weekly plan.
DO $$
BEGIN
  IF (SELECT confdeltype FROM pg_constraint WHERE conname = 'weekly_new_members_new_member_id_fkey'
        AND conrelid = 'public.weekly_new_members'::regclass) = 'n' THEN
    ALTER TABLE public.weekly_new_members DROP CONSTRAINT weekly_new_members_new_member_id_fkey;
    ALTER TABLE public.weekly_new_members ADD CONSTRAINT weekly_new_members_new_member_id_fkey
      FOREIGN KEY (new_member_id) REFERENCES public.new_members(id) ON DELETE NO ACTION;
  END IF;
  IF (SELECT confdeltype FROM pg_constraint WHERE conname = 'weekly_baptismal_date_friends_baptismal_date_person_id_fkey'
        AND conrelid = 'public.weekly_baptismal_date_friends'::regclass) = 'n' THEN
    ALTER TABLE public.weekly_baptismal_date_friends DROP CONSTRAINT weekly_baptismal_date_friends_baptismal_date_person_id_fkey;
    ALTER TABLE public.weekly_baptismal_date_friends ADD CONSTRAINT weekly_baptismal_date_friends_baptismal_date_person_id_fkey
      FOREIGN KEY (baptismal_date_person_id) REFERENCES public.baptismal_date_people(id) ON DELETE NO ACTION;
  END IF;
END $$;

-- Check: the rows are gone and copied, nothing without a person is left, the keys refuse, the copy is private.
DO $$
DECLARE
  found text;
BEGIN
  IF EXISTS (SELECT 1 FROM public.weekly_new_members WHERE new_member_id IS NULL)
     OR EXISTS (SELECT 1 FROM public.weekly_baptismal_date_friends WHERE baptismal_date_person_id IS NULL) THEN
    RAISE EXCEPTION 'Check failed: weekly rows without a person are still there.';
  END IF;
  -- Every listed row that was there at the start is in the copy; the others were gone before this run.
  SELECT string_agg(format('%s %s', p.table_name, p.row_id), ', ') INTO found
  FROM cleanup_030_present p
  WHERE NOT EXISTS (SELECT 1 FROM public.cleanup_030_removed_rows r WHERE r.table_name = p.table_name AND r.row_id = p.row_id);
  IF found IS NOT NULL THEN
    RAISE EXCEPTION 'Check failed: these removed rows are not in the copy: %', found;
  END IF;
  RAISE NOTICE 'Migration 030: removed % listed row(s) now; the copy holds % of the 84; % listed row(s) were already gone without a copy (removed with their plan, e.g. by the test-data tool).',
    (SELECT count(*) FROM cleanup_030_present),
    (SELECT count(*) FROM public.cleanup_030_removed_rows r JOIN cleanup_030_targets t USING (table_name, row_id)),
    (SELECT count(*) FROM cleanup_030_targets t
     WHERE NOT EXISTS (SELECT 1 FROM public.cleanup_030_removed_rows r WHERE r.table_name = t.table_name AND r.row_id = t.row_id));
  IF (SELECT confdeltype FROM pg_constraint WHERE conname = 'weekly_new_members_new_member_id_fkey'
        AND conrelid = 'public.weekly_new_members'::regclass) IS DISTINCT FROM 'a'
     OR (SELECT confdeltype FROM pg_constraint WHERE conname = 'weekly_baptismal_date_friends_baptismal_date_person_id_fkey'
        AND conrelid = 'public.weekly_baptismal_date_friends'::regclass) IS DISTINCT FROM 'a' THEN
    RAISE EXCEPTION 'Check failed: a foreign key still sets the person to empty on delete.';
  END IF;
  SELECT string_agg(r, ', ') INTO found
  FROM unnest(ARRAY['public', 'anon', 'authenticated', 'service_role']) r
  WHERE has_table_privilege(r, 'public.cleanup_030_removed_rows', 'SELECT')
     OR has_table_privilege(r, 'public.cleanup_030_removed_rows', 'INSERT')
     OR has_table_privilege(r, 'public.cleanup_030_removed_rows', 'UPDATE')
     OR has_table_privilege(r, 'public.cleanup_030_removed_rows', 'DELETE');
  IF found IS NOT NULL THEN
    RAISE EXCEPTION 'Check failed: these may use the copy table: %', found;
  END IF;
  IF (SELECT pg_get_userbyid(relowner) FROM pg_class WHERE oid = 'public.cleanup_030_removed_rows'::regclass) <> 'postgres' THEN
    RAISE EXCEPTION 'Check failed: the copy table is not owned by postgres.';
  END IF;
END $$;

NOTIFY pgrst, 'reload schema';
COMMIT;

-- Verify (read-only, after applying):
-- 1. Run 019 again as supabase_admin (see Apply); it must end with COMMIT.
-- 2. Both counts must be 0, and the copy must hold 83 and 1 rows (75 and 1 if the test-data tool removed the plans
--    20, 21, 24 and 25 first):
--      docker exec gfm-beta-supabase-db-1 psql -U postgres -d postgres -c "BEGIN READ ONLY" -c "SELECT (SELECT count(*) FROM public.weekly_new_members WHERE new_member_id IS NULL) AS nm_without_person, (SELECT count(*) FROM public.weekly_baptismal_date_friends WHERE baptismal_date_person_id IS NULL) AS bd_without_person, (SELECT string_agg(table_name || ' ' || n, ', ') FROM (SELECT table_name, count(*) n FROM public.cleanup_030_removed_rows GROUP BY 1) c) AS kept" -c "ROLLBACK"
