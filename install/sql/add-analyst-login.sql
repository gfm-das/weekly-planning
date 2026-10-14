-- add-analyst-login.sql: makes (or resets the password of) one Data Analyst's personal database login. Run by tools/add-analyst-login.sh
-- as supabase_admin, in the database container. Do not run it by hand with a password on the command line.
--
-- What it makes: a role that can log in, is a member of the group role gfm_db_analysts (migration 043: full rights on the schemas public,
-- portal and dashboards, including what later migrations add, and the right to create its own tables there), has BYPASSRLS (it sees every
-- row; row-level security is written for the portal's signed-in people), is NOT a superuser and cannot touch Supabase's own schemas
-- (auth, storage, ...), and may have at most 10 connections. The group role is NOT made here: migration 043 makes it.
--
-- It needs three psql variables, which the shell script sends as \set lines on standard input (so a password never appears in a process list):
--   analyst_login      the login name: small letters, digits and _, 3 to 31 characters, starting with a letter
--   analyst_password   the new password (the script makes a long random one and keeps it OUTSIDE Git)
--   analyst_action     create or reset
-- Nothing here prints the password; log_statement is switched off for this transaction. Any problem stops the file with an error
-- (psql exit code 3) and nothing is changed.
\set ON_ERROR_STOP on
BEGIN;
SET LOCAL log_statement = 'none';   -- first, before any statement that holds the password
SELECT :'analyst_action' = 'reset' AS is_reset,
       :'analyst_action' IN ('create', 'reset') AS action_ok,
       :'analyst_login' ~ '^[a-z][a-z0-9_]{2,30}$'
         AND :'analyst_login' !~ '^(pg_|supabase_|pgbouncer|authenticator|dashboard_user)'
         AND :'analyst_login' NOT IN ('postgres', 'anon', 'authenticated', 'service_role', 'gfm_db_analysts', 'gfm_dashboard_reader', 'public') AS name_ok,
       EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'analyst_login') AS login_exists,
       length(:'analyst_password') >= 20 AS password_ok \gset

DO $$
BEGIN
  IF NOT (SELECT rolsuper FROM pg_roles WHERE rolname = current_user) THEN
    RAISE EXCEPTION 'Run this file as supabase_admin (see its header); % cannot do this.', current_user;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'gfm_db_analysts') THEN
    RAISE EXCEPTION 'The group role gfm_db_analysts is missing: apply migration 043_dbeaver_analyst_role.sql first.';
  END IF;
END $$;

\if :action_ok
\else
  DO $$ BEGIN RAISE EXCEPTION 'analyst_action must be create or reset.'; END $$;
\endif
\if :name_ok
\else
  DO $$ BEGIN RAISE EXCEPTION 'The login name must be small letters, digits and _ (3 to 31 characters, starting with a letter) and must not be a system role.'; END $$;
\endif
\if :password_ok
\else
  DO $$ BEGIN RAISE EXCEPTION 'The password is too short (at least 20 characters).'; END $$;
\endif

\if :is_reset
  \if :login_exists
    SELECT format('ALTER ROLE %I PASSWORD %L', :'analyst_login', :'analyst_password') \gexec
  \else
    DO $$ BEGIN RAISE EXCEPTION 'There is no login with that name to reset.'; END $$;
  \endif
\else
  \if :login_exists
    DO $$ BEGIN RAISE EXCEPTION 'A role with that name exists already (use the reset action to give it a new password).'; END $$;
  \else
    SELECT format('CREATE ROLE %I LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION BYPASSRLS CONNECTION LIMIT 10 PASSWORD %L IN ROLE gfm_db_analysts',
                  :'analyst_login', :'analyst_password') \gexec
  \endif
\endif

-- Check what was made; a login that is not as intended makes the whole file fail, so nothing half-made stays.
SELECT (rolcanlogin AND rolbypassrls AND NOT rolsuper AND NOT rolcreaterole AND NOT rolcreatedb AND pg_has_role(rolname, 'gfm_db_analysts', 'member')) AS made_ok
  FROM pg_roles WHERE rolname = :'analyst_login' \gset
\if :made_ok
\else
  DO $$ BEGIN RAISE EXCEPTION 'The login was not made as intended.'; END $$;
\endif

COMMIT;
\echo 'OK'
