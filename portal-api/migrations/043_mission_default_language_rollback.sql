-- Rollback of migration 043: takes the mission's default language away again (everyone without a language of their own
-- gets English, as before). Run as supabase_admin with ON_ERROR_STOP=1, then 019_restrict_public_functions.sql again.
-- The programs of this version read the column: roll them back first (or at the same time).
BEGIN;

ALTER TABLE public.missions DROP COLUMN IF EXISTS default_language;

COMMIT;
