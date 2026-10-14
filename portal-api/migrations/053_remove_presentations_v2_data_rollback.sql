-- Rollback of 053_remove_presentations_v2_data.sql. Run on Beta only, as supabase_admin.
--
-- What it does: puts the 'v2-%' sharing rows back into portal.presentation_access FROM THE BACKUP TABLE
-- portal.presentation_access_v2_removed, which migration 053 filled in the same transaction as the delete. It can restore
-- only what that table holds: if the backup table was emptied or dropped, the rows can only come from a database backup
-- (CLAUDE.md, "Before any database change"). Rows that exist again in the live table are left as they are (no overwrite).
-- Note: the Presentations V2 code and its decks-v2/ files are NOT brought back by this file (code: git; files: the
-- _to-delete-<date>/ folder). Without them the restored rows only point to nothing.
-- The backup table is kept (drop it by hand after a "go" when it is no longer needed).
--
-- Apply:
--   (Get-Content portal-api/migrations/053_remove_presentations_v2_data_rollback.sql) -join "`n" |
--     docker exec -i gfm-beta-supabase-db-1 psql -U supabase_admin -d postgres -v ON_ERROR_STOP=1
-- Then run 019_restrict_public_functions.sql again as a check (it must end with COMMIT).
BEGIN;
SET LOCAL lock_timeout = '10s';

DO $$
BEGIN
  IF session_user NOT IN ('supabase_admin', 'postgres') THEN
    RAISE EXCEPTION 'Run this file as supabase_admin (see its header), not as %.', session_user;
  END IF;
  IF to_regclass('portal.presentation_access_v2_removed') IS NULL THEN
    RAISE EXCEPTION 'The backup table portal.presentation_access_v2_removed is missing: restore the rows from a database backup instead.';
  END IF;
END $$;

INSERT INTO portal.presentation_access
  (deck_slug, mission_id, roles, zone_ids, district_ids, user_ids, everyone, created_at, updated_at, created_by, updated_by)
SELECT b.deck_slug, b.mission_id, b.roles, b.zone_ids, b.district_ids, b.user_ids, b.everyone, b.created_at, b.updated_at,
       CASE WHEN EXISTS (SELECT 1 FROM auth.users u WHERE u.id = b.created_by) THEN b.created_by END,
       CASE WHEN EXISTS (SELECT 1 FROM auth.users u WHERE u.id = b.updated_by) THEN b.updated_by END
FROM portal.presentation_access_v2_removed b
WHERE EXISTS (SELECT 1 FROM public.missions m WHERE m.id = b.mission_id)
ON CONFLICT (mission_id, deck_slug) DO NOTHING;

DO $$
DECLARE missing integer;
BEGIN
  SELECT count(*) INTO missing FROM portal.presentation_access_v2_removed b
   WHERE NOT EXISTS (SELECT 1 FROM portal.presentation_access a WHERE a.mission_id = b.mission_id AND a.deck_slug = b.deck_slug);
  IF missing > 0 THEN
    RAISE EXCEPTION 'Check failed: % backup row(s) could not be restored (their mission no longer exists?).', missing;
  END IF;
END $$;

COMMIT;