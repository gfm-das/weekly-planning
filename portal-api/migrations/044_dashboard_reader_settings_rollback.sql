-- Rollback of migration 044: takes the four settings of gfm_dashboard_reader away again. Run as supabase_admin with
-- ON_ERROR_STOP=1, then 019_restrict_public_functions.sql again. Only for a system that was built from the baseline: the running
-- system has these settings from migration 018 and must keep them (without them DataEase's login is no longer read-only).
BEGIN;

ALTER ROLE gfm_dashboard_reader RESET default_transaction_read_only;
ALTER ROLE gfm_dashboard_reader RESET statement_timeout;
ALTER ROLE gfm_dashboard_reader RESET idle_in_transaction_session_timeout;
ALTER ROLE gfm_dashboard_reader RESET search_path;

COMMIT;
