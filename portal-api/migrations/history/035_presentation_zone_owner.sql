-- Migration 035 (round 7, zone presentations): every presentation has an owner.
--
-- owner_zone_id NULL: the mission owns the deck (as every deck did before). Only the APs, the President and the
--   Data Analysts change it; ZLs and STLs open it only when its access rule shares it with them.
-- owner_zone_id = a zone: that zone's Zone Leaders and Sister Training Leaders make, edit, publish, present and
--   download it (portal-api app.deck_editable). Other zones never see it unless a manager shares it.
-- A deck without a row here belongs to the mission. Decks a ZL or STL creates get their zone at once
-- (the manager's operation 'create'); a manager can hand a deck to a zone in Manage access.
--
-- Run as supabase_admin or postgres (the table belongs to postgres). Safe to run twice. Nothing else changes:
-- existing rules keep their roles, zones, districts, people and "everyone".
-- Rollback: 035_presentation_zone_owner_rollback.sql (zone decks then belong to the mission again).
BEGIN;

ALTER TABLE portal.presentation_access
  ADD COLUMN IF NOT EXISTS owner_zone_id bigint REFERENCES public.zones(id) ON DELETE SET NULL;

COMMENT ON COLUMN portal.presentation_access.owner_zone_id IS
  'The zone that owns this presentation (its ZLs and STLs edit it), or NULL for a mission presentation (managers only). Round 7, migration 035.';

-- Stop if the column is not there as expected (for example an older column of another type).
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                 WHERE table_schema = 'portal' AND table_name = 'presentation_access'
                   AND column_name = 'owner_zone_id' AND data_type = 'bigint') THEN
    RAISE EXCEPTION 'Migration 035: portal.presentation_access.owner_zone_id is missing or not bigint';
  END IF;
  RAISE NOTICE 'Migration 035: % presentation rule(s), % owned by a zone',
    (SELECT count(*) FROM portal.presentation_access),
    (SELECT count(*) FROM portal.presentation_access WHERE owner_zone_id IS NOT NULL);
END $$;

COMMIT;
