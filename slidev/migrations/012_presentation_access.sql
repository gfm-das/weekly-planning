-- Persist deck visibility separately from deck files. No existing decks are modified.
BEGIN;

CREATE SCHEMA IF NOT EXISTS portal;

CREATE TABLE IF NOT EXISTS portal.presentation_access (
  deck_slug text NOT NULL CHECK (deck_slug ~ '^[a-z0-9]+(-[a-z0-9]+)*$'),
  mission_id bigint NOT NULL REFERENCES public.missions(id),
  roles text[] NOT NULL DEFAULT '{}',
  zone_ids bigint[] NOT NULL DEFAULT '{}',
  district_ids bigint[] NOT NULL DEFAULT '{}',
  user_ids uuid[] NOT NULL DEFAULT '{}',
  everyone boolean NOT NULL DEFAULT false,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  created_by uuid REFERENCES auth.users(id) ON DELETE SET NULL,
  updated_by uuid REFERENCES auth.users(id) ON DELETE SET NULL,
  PRIMARY KEY (mission_id, deck_slug),
  CONSTRAINT presentation_access_viewer_roles CHECK (roles <@ ARRAY['DL', 'ZL', 'STL']::text[])
);

COMMENT ON TABLE portal.presentation_access IS
  'Presentation view ACLs. AP/PRESIDENT/DATA_ADMIN manage all decks in their mission. Missing ACLs default to managers only. Eligible viewers are DL/ZL/STL; role and stewardship scope rules combine, and individual assignments can add a deck.';

CREATE OR REPLACE FUNCTION portal.touch_presentation_access()
RETURNS trigger LANGUAGE plpgsql SET search_path = portal, pg_temp AS $$
BEGIN
  NEW.updated_at := now();
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS presentation_access_updated_at ON portal.presentation_access;
CREATE TRIGGER presentation_access_updated_at
BEFORE UPDATE ON portal.presentation_access
FOR EACH ROW EXECUTE FUNCTION portal.touch_presentation_access();

ALTER TABLE portal.presentation_access ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON portal.presentation_access FROM PUBLIC, anon, authenticated;
GRANT USAGE ON SCHEMA portal TO service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON portal.presentation_access TO service_role;
DROP POLICY IF EXISTS presentation_access_service_role ON portal.presentation_access;
CREATE POLICY presentation_access_service_role ON portal.presentation_access
  FOR ALL TO service_role USING (true) WITH CHECK (true);

COMMIT;
