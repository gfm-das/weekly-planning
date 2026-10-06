-- Rollback of migration 043: the group role gfm_db_analysts and its rights are removed. Run on Beta as supabase_admin.
-- Drop the personal logins first (DROP ROLE <name>; for each member, see docs/DBEAVER.md), or this stops with an error.
BEGIN;

DO $$
DECLARE
  members text;
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'gfm_db_analysts') THEN
    RETURN;
  END IF;
  SELECT string_agg(r.rolname, ', ') INTO members
  FROM pg_auth_members m JOIN pg_roles r ON r.oid = m.member JOIN pg_roles g ON g.oid = m.roleid
  WHERE g.rolname = 'gfm_db_analysts';
  IF members IS NOT NULL THEN
    RAISE EXCEPTION 'Drop these logins first (DROP ROLE ...): %', members;
  END IF;
  ALTER DEFAULT PRIVILEGES FOR ROLE supabase_admin IN SCHEMA public, portal, dashboards REVOKE ALL ON TABLES FROM gfm_db_analysts;
  ALTER DEFAULT PRIVILEGES FOR ROLE supabase_admin IN SCHEMA public, portal, dashboards REVOKE ALL ON SEQUENCES FROM gfm_db_analysts;
  ALTER DEFAULT PRIVILEGES FOR ROLE supabase_admin IN SCHEMA public, portal, dashboards REVOKE ALL ON ROUTINES FROM gfm_db_analysts;
  ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public, portal, dashboards REVOKE ALL ON TABLES FROM gfm_db_analysts;
  ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public, portal, dashboards REVOKE ALL ON SEQUENCES FROM gfm_db_analysts;
  ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public, portal, dashboards REVOKE ALL ON ROUTINES FROM gfm_db_analysts;
  REVOKE ALL ON ALL ROUTINES IN SCHEMA public, portal, dashboards FROM gfm_db_analysts;
  REVOKE ALL ON ALL SEQUENCES IN SCHEMA public, portal, dashboards FROM gfm_db_analysts;
  REVOKE ALL ON ALL TABLES IN SCHEMA public, portal, dashboards FROM gfm_db_analysts;
  REVOKE ALL ON SCHEMA public, portal, dashboards FROM gfm_db_analysts;
  DROP ROLE gfm_db_analysts;
END $$;

COMMIT;