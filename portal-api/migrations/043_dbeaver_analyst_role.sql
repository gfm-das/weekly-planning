-- Migration 043 (Oct 2026): a group role for the data analysts' own database logins (DBeaver). Run on Beta, as supabase_admin.
--
-- What changes: a new role gfm_db_analysts (it cannot log in itself) gets full rights on the portal's data: USAGE and
-- CREATE on the schemas public, portal and dashboards, ALL on every table, view, sequence and function in them, and the
-- same on everything supabase_admin or postgres creates there later (default rights), so new migrations need no extra
-- grants. Supabase's own schemas (auth, storage, realtime, ...) are not included. PUBLIC gets nothing (019 still passes).
--
-- The personal logins are NOT in Git (their passwords must not be): they are made on the server, one per person, as
-- supabase_admin (docs/DBEAVER.md):
--   CREATE ROLE <name> LOGIN BYPASSRLS PASSWORD '<random>' IN ROLE gfm_db_analysts;
-- BYPASSRLS lets a login see every row (row-level security is written for the portal's signed-in users); it cannot be
-- inherited from a group, so each login carries it. A login is removed with DROP ROLE <name> (it owns nothing).
-- Rollback: 043_dbeaver_analyst_role_rollback.sql.
BEGIN;

DO $$
BEGIN
  IF NOT (SELECT rolsuper FROM pg_roles WHERE rolname = current_user) THEN
    RAISE EXCEPTION 'Run this file as supabase_admin (see its header); % cannot do this.', current_user;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'gfm_db_analysts') THEN
    CREATE ROLE gfm_db_analysts NOLOGIN;
  END IF;
END $$;
ALTER ROLE gfm_db_analysts NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;

GRANT USAGE, CREATE ON SCHEMA public, portal, dashboards TO gfm_db_analysts;
GRANT ALL ON ALL TABLES IN SCHEMA public, portal, dashboards TO gfm_db_analysts;
GRANT ALL ON ALL SEQUENCES IN SCHEMA public, portal, dashboards TO gfm_db_analysts;
GRANT ALL ON ALL ROUTINES IN SCHEMA public, portal, dashboards TO gfm_db_analysts;

ALTER DEFAULT PRIVILEGES FOR ROLE supabase_admin IN SCHEMA public, portal, dashboards GRANT ALL ON TABLES TO gfm_db_analysts;
ALTER DEFAULT PRIVILEGES FOR ROLE supabase_admin IN SCHEMA public, portal, dashboards GRANT ALL ON SEQUENCES TO gfm_db_analysts;
ALTER DEFAULT PRIVILEGES FOR ROLE supabase_admin IN SCHEMA public, portal, dashboards GRANT ALL ON ROUTINES TO gfm_db_analysts;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public, portal, dashboards GRANT ALL ON TABLES TO gfm_db_analysts;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public, portal, dashboards GRANT ALL ON SEQUENCES TO gfm_db_analysts;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public, portal, dashboards GRANT ALL ON ROUTINES TO gfm_db_analysts;

COMMIT;