-- Migration 044 (Oct 2026): the settings of the read-only Dashboards login on a NEW install. Run on Beta only, as supabase_admin.
--
-- Why: the baseline (portal-api/baseline/000_baseline.sql) creates the role gfm_dashboard_reader (migration 018) but a schema dump
-- does not carry a role's own settings. The running system has them from migration 018; a system built from the baseline did not,
-- so DataEase's login was not read-only by default. This sets the same four settings again (nothing changes on a system that has
-- them): read-only transactions, a 15 second limit per query, 60 seconds idle in a transaction, and the dashboards schema first.
-- Rollback: 044_dashboard_reader_settings_rollback.sql (removes the settings: only for a system built from the baseline, never
-- for the running one, which needs them).
BEGIN;

ALTER ROLE gfm_dashboard_reader SET default_transaction_read_only = on;
ALTER ROLE gfm_dashboard_reader SET statement_timeout = '15s';
ALTER ROLE gfm_dashboard_reader SET idle_in_transaction_session_timeout = '60s';
ALTER ROLE gfm_dashboard_reader SET search_path = dashboards;

COMMIT;
