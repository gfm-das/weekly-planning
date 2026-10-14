-- Migration 050 (Oct 2026): an event can link to one of this portal's presentation decks (MMM, ZOKO, ...).
-- Run on Beta only, as supabase_admin. Back up first (CLAUDE.md, "Before any database change").
-- (Numbering: 046 to 048 are on the round-13 importer branch and 049 on branch feat/callins-demo; renumber if another
-- branch took 050 first.)
--
-- Why: round 13, task 20 "Kalender/announcements". Office can attach a presentation deck to a calendar event; the calendar
-- shows an "Open presentation" link in the event. The link is stored as a RELATIVE path of this portal's own presentations,
-- always the form /p/<deck-name>/ (the address Slidev publishes a deck under). Never a web address of someone else: the
-- check below refuses anything else even if the application were bypassed.
-- What changes: one new column portal.events.deck_link (text, may be empty = NULL, no default, so no rewrite of the table
-- and every existing event stays as it is). Row-level security, grants and policies of portal.events are NOT touched; the
-- new column is covered by the table's existing ones. The link gives no access to the deck: whoever opens it is checked by
-- the Presentations manager as always.
--
-- Apply (back up Beta first). Join the lines with plain line feeds:
--   (Get-Content portal-api/migrations/050_event_deck_link.sql) -join "`n" |
--     docker exec -i gfm-beta-supabase-db-1 psql -U supabase_admin -d postgres -v ON_ERROR_STOP=1
-- (Ubuntu server: psql as supabase_admin in the db container, the same way.) Then run 019_restrict_public_functions.sql
-- again as a check (it must end with COMMIT). Apply this BEFORE the new portal-api image: its event save writes the column.
-- Not run in the night session (no database there): test it on a throw-away copy first.
-- Rollback: 050_event_deck_link_rollback.sql (drops the column WITH the links stored in it).
BEGIN;
SET LOCAL lock_timeout = '10s';

DO $$
BEGIN
  IF session_user NOT IN ('supabase_admin', 'postgres') THEN
    RAISE EXCEPTION 'Run this file as supabase_admin (see its header), not as %.', session_user;
  END IF;
  IF to_regclass('portal.events') IS NULL THEN
    RAISE EXCEPTION 'portal.events is missing (migration 010).';
  END IF;
END $$;

ALTER TABLE portal.events ADD COLUMN IF NOT EXISTS deck_link text;
ALTER TABLE portal.events DROP CONSTRAINT IF EXISTS events_deck_link_check;
ALTER TABLE portal.events ADD CONSTRAINT events_deck_link_check
  CHECK (deck_link IS NULL OR (char_length(deck_link) <= 90 AND deck_link ~ '^/p/[a-z0-9]+(-[a-z0-9]+)*/$'));
COMMENT ON COLUMN portal.events.deck_link IS
  'Optional link to one of this portal''s presentation decks, always the relative path /p/<deck-name>/ (checked here and in portal-api). NULL = no deck.';

-- Check: the column exists, may be empty, and the other rules of the table are unchanged.
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'portal' AND table_name = 'events'
                 AND column_name = 'deck_link' AND data_type = 'text' AND is_nullable = 'YES') THEN
    RAISE EXCEPTION 'Check failed: portal.events.deck_link is missing or not nullable.';
  END IF;
  IF NOT (SELECT relrowsecurity FROM pg_class WHERE oid = 'portal.events'::regclass) THEN
    RAISE EXCEPTION 'Check failed: row-level security on portal.events is off.';
  END IF;
END $$;

COMMIT;
