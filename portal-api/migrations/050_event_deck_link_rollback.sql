-- Rollback of 050_event_deck_link.sql. Run on Beta only, as supabase_admin.
--
-- What it does: drops portal.events.deck_link (and its check) WITH the links stored in it. Take a backup first if the links
-- should be kept. Do it together with the code rollback (the portal-api image and calendar page before this change): the
-- old code never reads or writes the column, so the order does not matter for events, only the deck links disappear.
--
-- Apply:
--   (Get-Content portal-api/migrations/050_event_deck_link_rollback.sql) -join "`n" |
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

ALTER TABLE portal.events DROP CONSTRAINT IF EXISTS events_deck_link_check;
ALTER TABLE portal.events DROP COLUMN IF EXISTS deck_link;

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'portal' AND table_name = 'events'
             AND column_name = 'deck_link') THEN
    RAISE EXCEPTION 'Check failed: portal.events.deck_link is still there.';
  END IF;
END $$;

COMMIT;
