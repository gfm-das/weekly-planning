-- Migration 016 (history): portal.mission_focus, the mission's focus text for each reporting Sunday (shown on the Overview)
-- with its translations. A new install gets it from portal-api/baseline/000_baseline.sql.

BEGIN;
CREATE TABLE IF NOT EXISTS portal.mission_focus (
 mission_id bigint NOT NULL REFERENCES public.missions(id) ON DELETE CASCADE,
 reporting_sunday date NOT NULL,
 translations jsonb NOT NULL DEFAULT '{}'::jsonb,
 updated_by uuid REFERENCES public.user_profiles(id),
 updated_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY (mission_id, reporting_sunday),
 CHECK (jsonb_typeof(translations) = 'object')
);
REVOKE ALL ON portal.mission_focus FROM PUBLIC, anon, authenticated;
COMMIT;
