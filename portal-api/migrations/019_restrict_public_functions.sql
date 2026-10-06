-- Closes an older gap in the Beta database before Grafana goes live. Run on Beta only, as supabase_admin.
--
-- Why: every database login is a member of PUBLIC. 15 SECURITY DEFINER functions in public could still
-- be run by PUBLIC (the other 59 already cannot; see 013 and 015), and their access checks trust
-- request.jwt.claims, which any session can set to any user. So any login (gfm_dashboard_reader,
-- whose SQL Grafana editors write, and the older grafana_readonly) could read Call-ins data about
-- people, save Call-ins notes or sync companionships as any portal user. The pg_net schema "net" was
-- also usable by PUBLIC, so any login could make the database send web requests (to other containers
-- or the internet) and read their answers.
--
-- What changes: PUBLIC loses EXECUTE on those 15 functions and USAGE on schema net. The roles that were
-- granted them by name keep them: postgres (owner), anon, authenticated and service_role on the
-- functions (the portal, PostgREST/Appsmith and the Call-ins wrappers work as before), and postgres,
-- anon, authenticated, service_role and supabase_functions_admin on net. Nothing else changes.
-- The last block undoes everything and stops if PUBLIC can still run a SECURITY DEFINER function or
-- touch a table outside the system schemas, so it can also be run again later as a check.
--
-- Apply (back up Beta first; after 018 and BEFORE Grafana is started). supabase_admin is needed
-- because it owns the net schema:
--   Get-Content portal-api/migrations/019_restrict_public_functions.sql -Raw |
--     docker exec -i gfm-beta-supabase-db-1 psql -U supabase_admin -d postgres -v ON_ERROR_STOP=1
-- Safe to run again (also after Supabase image upgrades, which may reinstall pg_net's grants).
-- Rollback: see the commented section at the end of this file.
BEGIN;

DO $$
BEGIN
  IF NOT (SELECT rolsuper FROM pg_roles WHERE rolname = current_user) THEN
    RAISE EXCEPTION 'Run this file as supabase_admin (see its header); % cannot change the net schema.', current_user;
  END IF;
END $$;

REVOKE EXECUTE ON FUNCTION
  public.can_access_district(bigint),
  public.can_access_zone(bigint),
  public.get_dl_call_in_baptismal_dates(bigint, bigint),
  public.get_dl_call_in_high_potentials(bigint, bigint),
  public.get_dl_call_in_new_members(bigint, bigint),
  public.get_dl_call_in_summary(bigint, bigint),
  public.get_dl_call_in_ward_coordination(bigint, bigint),
  public.get_previous_planning_answers(bigint),
  public.get_zl_call_in_zone_notes(bigint, bigint),
  public.save_call_in_area_update(bigint, bigint, bigint, text),
  public.save_dl_call_in_notes(bigint, bigint, text, text),
  public.save_zl_call_in_notes(bigint, bigint, text),
  public.save_zl_zone_call_in_notes(bigint, bigint, text),
  public.sync_current_companionships()
FROM PUBLIC;
-- Already granted by name; repeated so the intended callers are written down here.
GRANT EXECUTE ON FUNCTION
  public.can_access_district(bigint),
  public.can_access_zone(bigint),
  public.get_dl_call_in_baptismal_dates(bigint, bigint),
  public.get_dl_call_in_high_potentials(bigint, bigint),
  public.get_dl_call_in_new_members(bigint, bigint),
  public.get_dl_call_in_summary(bigint, bigint),
  public.get_dl_call_in_ward_coordination(bigint, bigint),
  public.get_previous_planning_answers(bigint),
  public.get_zl_call_in_zone_notes(bigint, bigint),
  public.save_call_in_area_update(bigint, bigint, bigint, text),
  public.save_dl_call_in_notes(bigint, bigint, text, text),
  public.save_zl_call_in_notes(bigint, bigint, text),
  public.save_zl_zone_call_in_notes(bigint, bigint, text),
  public.sync_current_companionships()
TO postgres, authenticated, service_role;

DO $$
BEGIN
  IF to_regnamespace('net') IS NOT NULL THEN
    REVOKE USAGE ON SCHEMA net FROM PUBLIC;
  END IF;
END $$;

-- Check: nothing PUBLIC can reach may act with someone else's rights or change data.
DO $$
DECLARE
  found text;
BEGIN
  SELECT string_agg(format('%s.%s(%s)', n.nspname, p.proname, pg_get_function_identity_arguments(p.oid)), ', ')
    INTO found
  FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
  WHERE p.prosecdef AND n.nspname NOT IN ('pg_catalog', 'information_schema')
    AND has_schema_privilege('public', n.oid, 'USAGE') AND has_function_privilege('public', p.oid, 'EXECUTE');
  IF found IS NOT NULL THEN
    RAISE EXCEPTION 'Every database login can still run these SECURITY DEFINER functions: %', found;
  END IF;
  SELECT string_agg(format('%s.%s', n.nspname, c.relname), ', ')
    INTO found
  FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
  WHERE c.relkind IN ('r', 'p', 'v', 'm', 'f', 'S') AND n.nspname NOT IN ('pg_catalog', 'information_schema')
    AND has_schema_privilege('public', n.oid, 'USAGE')
    AND (has_table_privilege('public', c.oid, 'SELECT') OR has_table_privilege('public', c.oid, 'INSERT')
         OR has_table_privilege('public', c.oid, 'UPDATE') OR has_table_privilege('public', c.oid, 'DELETE')
         OR (c.relkind = 'S' AND has_sequence_privilege('public', c.oid, 'USAGE')));
  IF found IS NOT NULL THEN
    RAISE EXCEPTION 'Every database login can still read or change: %', found;
  END IF;
END $$;

COMMIT;

-- Rollback (restores the old, open grants; stop Grafana first):
-- BEGIN;
-- GRANT EXECUTE ON FUNCTION public.can_access_district(bigint), public.can_access_zone(bigint),
--   public.get_dl_call_in_baptismal_dates(bigint, bigint), public.get_dl_call_in_high_potentials(bigint, bigint),
--   public.get_dl_call_in_new_members(bigint, bigint), public.get_dl_call_in_summary(bigint, bigint),
--   public.get_dl_call_in_ward_coordination(bigint, bigint), public.get_previous_planning_answers(bigint),
--   public.get_zl_call_in_zone_notes(bigint, bigint),
--   public.save_call_in_area_update(bigint, bigint, bigint, text), public.save_dl_call_in_notes(bigint, bigint, text, text),
--   public.save_zl_call_in_notes(bigint, bigint, text), public.save_zl_zone_call_in_notes(bigint, bigint, text),
--   public.sync_current_companionships()
-- TO PUBLIC;
-- GRANT USAGE ON SCHEMA net TO PUBLIC;
-- COMMIT;
