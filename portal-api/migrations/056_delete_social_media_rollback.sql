-- Rollback of 056: none by design (owner, 14 Oct 2026: social-media rows are deleted for real, no copies kept).
-- The only way back is the nightly database backup taken before the update.
BEGIN;
DO $$ BEGIN RAISE NOTICE 'Migration 056 has no rollback: restore the nightly backup if the social-media rows are needed.'; END $$;
COMMIT;
