-- Whiteboards (round 6): the boards of the portal's Whiteboard tab. Run on Beta as postgres (so postgres owns them).
--
-- What: two new tables in the portal schema, nothing else changes.
-- - portal.whiteboards: one row per named board of a mission. scene is the Excalidraw drawing without its pictures
--   ({"type":"gfm-whiteboard","v":1,"style":"hand"|"clean","elements":[...],"appState":{...}}). version goes up by one
--   on every save; portal-api saves only when the browser sends the version it opened (optimistic check), so two
--   people cannot overwrite each other without being told ("someone else saved; reload").
-- - portal.whiteboard_files: the pictures on a board (one row per picture, the bytes and their type), deleted with
--   the board.
-- Who: only portal-api reads and writes them (as postgres), for AP, President and Data Analyst of the board's mission
--   (portal-api/whiteboards.py, roles.is_manager). Like the other portal tables they are API-only: no right for
--   PUBLIC, anon, authenticated or service_role, and row-level security is on with no policy, so a right given by
--   mistake later still shows no row. No function is added, so migration 019's rules hold (run it again as a check).
-- Limits (also checked by portal-api, which gives the readable message): a name of 1 to 80 characters, unique in the
--   mission (letter case and outer spaces ignored); a picture of at most 2 MB; the drawing itself at most 3 MB.
--
-- Apply (back up Beta first):
--   (Get-Content portal-api/migrations/031_whiteboards.sql) -join "`n" |
--     docker exec -i gfm-beta-supabase-db-1 psql -U postgres -d postgres -v ON_ERROR_STOP=1
--   then 019 again as a check (as supabase_admin; it must end with COMMIT):
--   Get-Content portal-api/migrations/019_restrict_public_functions.sql -Raw |
--     docker exec -i gfm-beta-supabase-db-1 psql -U supabase_admin -d postgres -v ON_ERROR_STOP=1
-- Safe to run again (IF NOT EXISTS; the rights and the check are repeated).
-- Rollback (deletes every board and picture; portal-api must no longer offer the Whiteboard first):
--   031_whiteboards_rollback.sql
BEGIN;
SET LOCAL lock_timeout = '10s';

CREATE TABLE IF NOT EXISTS portal.whiteboards (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  mission_id bigint NOT NULL REFERENCES public.missions(id) ON DELETE CASCADE,
  name text NOT NULL,
  scene jsonb NOT NULL DEFAULT '{"type":"gfm-whiteboard","v":1,"style":"hand","elements":[],"appState":{}}'::jsonb,
  version integer NOT NULL DEFAULT 1,
  created_by uuid REFERENCES public.user_profiles(id) ON DELETE SET NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_by uuid REFERENCES public.user_profiles(id) ON DELETE SET NULL,
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT whiteboards_name_length CHECK (char_length(btrim(name)) BETWEEN 1 AND 80 AND name = btrim(name)),
  CONSTRAINT whiteboards_scene_object CHECK (jsonb_typeof(scene) = 'object' AND jsonb_typeof(scene->'elements') = 'array'),
  CONSTRAINT whiteboards_scene_size CHECK (octet_length(scene::text) <= 3 * 1024 * 1024),
  CONSTRAINT whiteboards_version_positive CHECK (version >= 1)
);
CREATE UNIQUE INDEX IF NOT EXISTS whiteboards_mission_name ON portal.whiteboards (mission_id, lower(name));

CREATE TABLE IF NOT EXISTS portal.whiteboard_files (
  board_id uuid NOT NULL REFERENCES portal.whiteboards(id) ON DELETE CASCADE,
  file_id text NOT NULL,
  mime_type text NOT NULL,
  bytes integer NOT NULL,
  data bytea NOT NULL,
  created_by uuid REFERENCES public.user_profiles(id) ON DELETE SET NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (board_id, file_id),
  CONSTRAINT whiteboard_files_id CHECK (file_id ~ '^[A-Za-z0-9_-]{1,100}$'),
  CONSTRAINT whiteboard_files_type CHECK (mime_type IN ('image/png', 'image/jpeg', 'image/gif', 'image/webp', 'image/svg+xml')),
  CONSTRAINT whiteboard_files_size CHECK (bytes = octet_length(data) AND bytes BETWEEN 1 AND 2 * 1024 * 1024)
);

ALTER TABLE portal.whiteboards OWNER TO postgres;
ALTER TABLE portal.whiteboard_files OWNER TO postgres;
ALTER TABLE portal.whiteboards ENABLE ROW LEVEL SECURITY;
ALTER TABLE portal.whiteboard_files ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON portal.whiteboards, portal.whiteboard_files FROM PUBLIC, anon, authenticated, service_role;

-- Check: only postgres (and superusers) can reach the boards.
DO $$
DECLARE
  found text;
BEGIN
  SELECT string_agg(DISTINCT format('%s on %s', r.rolname, c.relname), ', ') INTO found
  FROM pg_class c
  JOIN pg_namespace n ON n.oid = c.relnamespace
  CROSS JOIN pg_roles r
  WHERE n.nspname = 'portal' AND c.relname IN ('whiteboards', 'whiteboard_files')
    AND r.rolname IN ('anon', 'authenticated', 'service_role', 'gfm_dashboard_reader', 'grafana_readonly')
    AND (has_table_privilege(r.oid, c.oid, 'SELECT') OR has_table_privilege(r.oid, c.oid, 'INSERT')
         OR has_table_privilege(r.oid, c.oid, 'UPDATE') OR has_table_privilege(r.oid, c.oid, 'DELETE'));
  IF found IS NOT NULL THEN
    RAISE EXCEPTION 'The whiteboard tables must be reached through portal-api only, but these rights exist: %', found;
  END IF;
  IF NOT (SELECT bool_and(relrowsecurity) FROM pg_class
          WHERE oid IN ('portal.whiteboards'::regclass, 'portal.whiteboard_files'::regclass)) THEN
    RAISE EXCEPTION 'Row-level security must be on for the whiteboard tables.';
  END IF;
END $$;

COMMIT;
