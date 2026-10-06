-- Rollback of 033_data_uploads.sql. Run on Beta only, as supabase_admin.
--
-- What it does: removes the nine dashboards views and the helper views of 033, the seven tables WITH THEIR DATA
-- (area data, remembered name matches, finding export rows, zone history, referral archive, rates, baptism
-- history), the Import history entries of those uploads (their kinds cannot exist without the tables), and puts
-- the old list of import kinds back (TRANSFER, HISTORICAL, ACCOUNT). Nothing else is touched.
-- Do it together with the code rollback (the DA Management image without data_uploads.py), or the Data uploads
-- pages show an error. Take a backup first if the uploaded data should be kept.
-- Order: if migration 034 (archetypes) is applied, roll back 034 FIRST. Its views read dashboards.area_profile and
-- the finding views, so this file stops with a "depends on" error otherwise (safely: nothing is changed).
--
-- Apply:
--   (Get-Content portal-api/migrations/033_data_uploads_rollback.sql) -join "`n" |
--     docker exec -i gfm-beta-supabase-db-1 psql -U supabase_admin -d postgres -v ON_ERROR_STOP=1
-- Then run 019 again as a check. Safe to run again.
BEGIN;
SET LOCAL lock_timeout = '10s';

DO $$
BEGIN
  IF session_user NOT IN ('supabase_admin', 'postgres') THEN
    RAISE EXCEPTION 'Run this file as supabase_admin (see its header), not as %.', session_user;
  END IF;
END $$;

DROP VIEW IF EXISTS dashboards.mission_history_week, dashboards.zone_history_week, dashboards.findechristus_referrals_week,
  dashboards.finding_cohort_week, dashboards.finding_area_week, dashboards.referral_archive_week,
  dashboards.finding_rate_week, dashboards.baptism_history_week, dashboards.area_profile;
DROP VIEW IF EXISTS public.finding_people_placed, public.finding_people_latest, public.data_upload_week_batches;
DROP TABLE IF EXISTS public.finding_people, public.zone_history_weeks, public.referral_archive_weeks,
  public.finding_rate_weeks, public.baptism_history_weeks, public.area_profiles, public.data_name_matches;

-- The batches of the new kinds (their change rows go with them: ON DELETE CASCADE).
DELETE FROM public.roster_import_batches
WHERE kind IN ('AREA_DATA', 'FINDING', 'ZONE_HISTORY', 'REFERRAL_ARCHIVE', 'RATES', 'BAPTISMS');
ALTER TABLE public.roster_import_batches DROP CONSTRAINT IF EXISTS roster_import_batches_kind_check;
ALTER TABLE public.roster_import_batches ADD CONSTRAINT roster_import_batches_kind_check
  CHECK (kind IN ('TRANSFER', 'HISTORICAL', 'ACCOUNT'));

DO $$
DECLARE
  found text;
BEGIN
  SELECT string_agg(n.nspname || '.' || c.relname, ', ') INTO found
  FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
  WHERE (n.nspname = 'dashboards' AND c.relname IN ('area_profile', 'finding_area_week', 'finding_cohort_week',
           'referral_archive_week', 'findechristus_referrals_week', 'finding_rate_week', 'zone_history_week',
           'mission_history_week', 'baptism_history_week'))
     OR (n.nspname = 'public' AND c.relname IN ('area_profiles', 'data_name_matches', 'finding_people',
           'zone_history_weeks', 'referral_archive_weeks', 'finding_rate_weeks', 'baptism_history_weeks',
           'finding_people_latest', 'finding_people_placed', 'data_upload_week_batches'));
  IF found IS NOT NULL THEN RAISE EXCEPTION 'Rollback check failed: still there: %', found; END IF;
END $$;

COMMIT;
