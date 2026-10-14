-- Migration 053 (Oct 2026): remove the sharing rows of the removed "Presentations V2" app.
-- Run on Beta only, as supabase_admin. Back up first (CLAUDE.md, "Before any database change"). NOT applied anywhere yet.
-- (Numbering: renumber if another branch took 053 first.)
--
-- Why: round 13, task 1. The owner said "just delete it" (OWNER_ANSWERS.md, answer 7: no decks, port nothing, delete the
-- code AND the old v2 sharing rows). The code left in commit "Presentations V2 removed". Presentations V2 had no table of its
-- own (docs/handoff/round13/presentations-v2-audit.md, section 3): its only stored data in the database are the rows of the
-- SHARED table portal.presentation_access whose deck_slug starts with 'v2-'. The classic Slidev decks use the same table, so
-- NOTHING is dropped here: only the rows 'v2-%' are deleted.
--
-- Safety: in the same transaction the rows are first copied into portal.presentation_access_v2_removed (same columns plus
-- removed_at), so they can be put back by 053_remove_presentations_v2_data_rollback.sql. The backup table stays after the
-- migration; the owner may drop it later, by hand, after a "go". The migration stops with a clear message if the backup
-- table already holds rows (a former run) so a backup is never overwritten.
-- Side note: a classic deck whose folder name starts with 'v2-' would lose its sharing rule too (falls back to "managers
-- only"). The code (newDeckSlug in slidev/manager/deck-files.mjs) has prevented such names since V2 was planned, but the
-- migration prints how many rows it removes; look at the list in the NOTICE before COMMIT if running by hand.
--
-- Apply (back up Beta first). Join the lines with plain line feeds:
--   (Get-Content portal-api/migrations/053_remove_presentations_v2_data.sql) -join "`n" |
--     docker exec -i gfm-beta-supabase-db-1 psql -U supabase_admin -d postgres -v ON_ERROR_STOP=1
-- (Ubuntu server: psql as supabase_admin in the db container, the same way.) Then run 019_restrict_public_functions.sql
-- again as a check (it must end with COMMIT).
-- Rollback: 053_remove_presentations_v2_data_rollback.sql (puts the rows back from the backup table).
BEGIN;
SET LOCAL lock_timeout = '10s';

DO $$
BEGIN
  IF session_user NOT IN ('supabase_admin', 'postgres') THEN
    RAISE EXCEPTION 'Run this file as supabase_admin (see its header), not as %.', session_user;
  END IF;
  IF to_regclass('portal.presentation_access') IS NULL THEN
    RAISE EXCEPTION 'portal.presentation_access is missing (slidev/migrations/012).';
  END IF;
END $$;

-- 1. The backup table: same columns as the live table, plus the time of removal. No keys, so a copy can never fail.
CREATE TABLE IF NOT EXISTS portal.presentation_access_v2_removed (
  LIKE portal.presentation_access,
  removed_at timestamptz NOT NULL DEFAULT now()
);
COMMENT ON TABLE portal.presentation_access_v2_removed IS
  'Backup of the portal.presentation_access rows with deck_slug v2-% removed by migration 053 (Presentations V2 was removed). Used only by 053_..._rollback.sql. The owner may drop it after a "go".';
ALTER TABLE portal.presentation_access_v2_removed ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON portal.presentation_access_v2_removed FROM PUBLIC, anon, authenticated;
GRANT SELECT ON portal.presentation_access_v2_removed TO service_role;
DROP POLICY IF EXISTS presentation_access_v2_removed_service_role ON portal.presentation_access_v2_removed;
CREATE POLICY presentation_access_v2_removed_service_role ON portal.presentation_access_v2_removed
  FOR SELECT TO service_role USING (true);

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM portal.presentation_access_v2_removed) THEN
    RAISE EXCEPTION 'portal.presentation_access_v2_removed already holds rows (an earlier run). Look at them, then empty or drop that table by hand after a "go"; the migration will not overwrite a backup.';
  END IF;
END $$;

-- 2. Copy, then delete (one transaction). Column list is explicit so the order of columns cannot matter.
INSERT INTO portal.presentation_access_v2_removed
  (deck_slug, mission_id, roles, zone_ids, district_ids, user_ids, everyone, created_at, updated_at, created_by, updated_by)
SELECT deck_slug, mission_id, roles, zone_ids, district_ids, user_ids, everyone, created_at, updated_at, created_by, updated_by
FROM portal.presentation_access
WHERE deck_slug LIKE 'v2-%';

DELETE FROM portal.presentation_access WHERE deck_slug LIKE 'v2-%';

-- 3. Check: nothing 'v2-%' is left, and every removed row is in the backup.
DO $$
DECLARE saved integer;
BEGIN
  IF EXISTS (SELECT 1 FROM portal.presentation_access WHERE deck_slug LIKE 'v2-%') THEN
    RAISE EXCEPTION 'Check failed: v2-%% rows are still in portal.presentation_access.';
  END IF;
  SELECT count(*) INTO saved FROM portal.presentation_access_v2_removed;
  RAISE NOTICE 'Presentations V2: % sharing row(s) removed and kept in portal.presentation_access_v2_removed.', saved;
END $$;

COMMIT;