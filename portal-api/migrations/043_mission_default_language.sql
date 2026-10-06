-- Migration 043 (Oct 2026): the mission's default language. Run on Beta only, as supabase_admin.
--
-- What changes:
-- 1. public.missions gets default_language: the interface language of everyone who has no language of their own yet
--    (no language assigned in DA Management and none chosen in the portal). It was always English before, so the
--    column starts at 'en' for every mission that exists; only the installer (or a Data Analyst) sets another one.
--    A code of two or three lower-case letters, one of the portal's languages in portal/i18n/ (the programs check
--    that; a new language does not need a new migration).
-- Rollback: 043_mission_default_language_rollback.sql.
BEGIN;

ALTER TABLE public.missions
    ADD COLUMN default_language text NOT NULL DEFAULT 'en'
    CONSTRAINT missions_default_language_check CHECK (default_language ~ '^[a-z]{2,3}$');

COMMENT ON COLUMN public.missions.default_language IS
    'Interface language for people with no assigned or chosen language (code of a catalog in portal/i18n/).';

COMMIT;
