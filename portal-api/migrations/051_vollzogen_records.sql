-- Migration 051 (Oct 2026): the Vollzogen list, the people who were baptized and confirmed, from DA Management > Data uploads > Vollzogen.
-- Run on Beta only, as supabase_admin. Back up first (CLAUDE.md, "Before any database change").
--
-- Why: the office keeps a hand-typed list of everyone who was baptized and confirmed (the "Vollzogen" sheet: how they were
-- found, when the baptismal date was set, the baptism date, the missionaries, the unit, stake and zone, whether they are
-- confirmed, and the Mission Office info: country, gender, preferred language). The owner wants it in the portal: Office
-- sees it (in the side menu under Insights) and the dashboards can count it. DA Management reads the sheet loosely (dates in
-- any writing, an X in "Konfirmiert") and links each person to the new member already in the portal when it can.
--
-- What changes:
-- 1. Import history accepts the batch kind VOLLZOGEN (read from the running constraint and added, so kinds added by other
--    migrations are kept).
-- 2. public.vollzogen_records: one row per person of the list (mission_id, record_key = the name in small letters without
--    accents + "|" + the baptism date, so the same person uploaded again is the same row), with the columns of the sheet,
--    new_member_id (the portal person it was matched to, or empty; ON DELETE SET NULL) and matched_how (FC number, NAME or an
--    ASKED answer). The table holds NAMES, so row level security is on with NO policy and no rights for PUBLIC, anon,
--    authenticated, service_role or gfm_dashboard_reader: only the services that connect as postgres (DA Management and the
--    portal API, which checks the viewer's role itself) can read it. An upload records every changed row in
--    roster_import_changes, so Undo works like the other uploads.
-- 3. dashboards.vollzogen_week: COUNTS only (no name, no FC number, no link): baptisms and confirmed per week (named by its
--    Sunday), stake, zone, unit and how they were found. Read by gfm_dashboard_reader like the views of 033 and 046.
-- No row of any existing table is changed.
--
-- Apply (back up Beta first; after 018, 033 and the people tables). Join the lines with plain line feeds:
--   (Get-Content portal-api/migrations/051_vollzogen_records.sql) -join "`n" |
--     docker exec -i gfm-beta-supabase-db-1 psql -U supabase_admin -d postgres -v ON_ERROR_STOP=1
-- (Ubuntu server: psql as supabase_admin in the db container, the same way.) Then run 019_restrict_public_functions.sql
-- again as a check, as after every migration (it must end with COMMIT). Deploy step: that re-run is part of the deploy.
-- Apply this BEFORE the new DA Management image (its Undo knows the kind VOLLZOGEN).
-- Safe to run again: IF NOT EXISTS, CREATE OR REPLACE VIEW, GRANT and REVOKE, then a check that stops on any problem.
-- Rollback: 051_vollzogen_records_rollback.sql (removes the list too; take a backup first if it should be kept).
BEGIN;
SET LOCAL lock_timeout = '10s';

DO $$
BEGIN
  IF session_user NOT IN ('supabase_admin', 'postgres') THEN
    RAISE EXCEPTION 'Run this file as supabase_admin (see its header), not as %.', session_user;
  END IF;
  IF to_regclass('public.new_members') IS NULL OR to_regclass('public.missions') IS NULL
     OR to_regclass('public.roster_import_batches') IS NULL THEN
    RAISE EXCEPTION 'Apply the DA Management and people migrations first (new_members, missions and roster_import_batches are missing).';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'gfm_dashboard_reader') THEN
    RAISE EXCEPTION 'The role gfm_dashboard_reader is missing (migration 018).';
  END IF;
END $$;

-- 1. Import history gets the kind VOLLZOGEN. The constraint belongs to supabase_admin's table, so this runs before the
--    switch to postgres below. The kinds already allowed are read from the constraint itself and kept.
DO $$
DECLARE
  kinds text[];
BEGIN
  SELECT array_agg(DISTINCT m[1] ORDER BY m[1]) INTO kinds
  FROM pg_constraint c
  CROSS JOIN LATERAL regexp_matches(pg_get_constraintdef(c.oid), '''([A-Z_]+)''', 'g') AS m
  WHERE c.conrelid = 'public.roster_import_batches'::regclass AND c.conname = 'roster_import_batches_kind_check';
  IF kinds IS NULL OR NOT ('TRANSFER' = ANY (kinds) AND 'AREA_DATA' = ANY (kinds)) THEN
    RAISE EXCEPTION 'The list of batch kinds could not be read from roster_import_batches_kind_check (found: %).', kinds;
  END IF;
  IF NOT ('VOLLZOGEN' = ANY (kinds)) THEN
    kinds := kinds || 'VOLLZOGEN'::text;
    ALTER TABLE public.roster_import_batches DROP CONSTRAINT roster_import_batches_kind_check;
    EXECUTE format('ALTER TABLE public.roster_import_batches ADD CONSTRAINT roster_import_batches_kind_check CHECK (kind IN (%s))',
      (SELECT string_agg(quote_literal(k), ', ' ORDER BY k) FROM unnest(kinds) k));
  END IF;
END $$;

-- Everything below belongs to postgres, like the tables and views of 033 and 046 (DA Management connects as postgres).
SET LOCAL ROLE postgres;

-- 2. The list. One row per person; an empty column means "not given".
CREATE TABLE IF NOT EXISTS public.vollzogen_records (
  id bigint GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
  mission_id bigint NOT NULL REFERENCES public.missions(id),
  record_key text NOT NULL CHECK (length(record_key) BETWEEN 3 AND 400),
  full_name text NOT NULL CHECK (length(full_name) BETWEEN 1 AND 200),
  found_how text CHECK (length(found_how) <= 200),
  baptismal_date_set_on date CHECK (baptismal_date_set_on >= DATE '1990-01-01'),
  baptism_date date NOT NULL CHECK (baptism_date >= DATE '2000-01-01'),
  workers text CHECK (length(workers) <= 300),
  unit text CHECK (length(unit) <= 200),
  stake text CHECK (length(stake) <= 200),
  zone text CHECK (length(zone) <= 200),
  confirmed boolean NOT NULL DEFAULT false,
  confirmed_on date CHECK (confirmed_on >= DATE '2000-01-01'),
  country text CHECK (length(country) <= 200),
  gender text CHECK (length(gender) <= 60),
  preferred_language text CHECK (length(preferred_language) <= 100),
  fc_number text CHECK (fc_number ~ '^[A-Z0-9-]{3,30}$'),
  new_member_id bigint REFERENCES public.new_members(id) ON DELETE SET NULL,
  matched_how text CHECK (matched_how IN ('FC', 'NAME', 'ASKED')),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  updated_by text,
  CONSTRAINT vollzogen_records_one_per_person UNIQUE (mission_id, record_key),
  CONSTRAINT vollzogen_records_link_how CHECK (new_member_id IS NULL OR matched_how IS NOT NULL)
);
CREATE INDEX IF NOT EXISTS vollzogen_records_week_idx ON public.vollzogen_records (mission_id, baptism_date);
CREATE INDEX IF NOT EXISTS vollzogen_records_person_idx ON public.vollzogen_records (new_member_id) WHERE new_member_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS vollzogen_records_fc_idx ON public.vollzogen_records (fc_number) WHERE fc_number IS NOT NULL;
COMMENT ON TABLE public.vollzogen_records IS 'The office''s Vollzogen list: people who were baptized and confirmed, from DA Management > Data uploads > Vollzogen. Holds NAMES: no policy, no rights except postgres. new_member_id links the portal person it was matched to.';
COMMENT ON COLUMN public.vollzogen_records.record_key IS 'The name in small letters without accents, a bar, and the baptism date: the same person uploaded again is the same row.';
COMMENT ON COLUMN public.vollzogen_records.matched_how IS 'How new_member_id was found: FC (same FC number), NAME (same name and zone or baptism date) or ASKED (a manager said same person).';

ALTER TABLE public.vollzogen_records ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.vollzogen_records FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON SEQUENCE public.vollzogen_records_id_seq FROM PUBLIC, anon, authenticated, service_role;

-- 3. A view of counts for dashboards (no name, no FC number, no link to a person).
CREATE OR REPLACE VIEW dashboards.vollzogen_week AS
  SELECT v.mission_id,
         (v.baptism_date + (7 - extract(isodow FROM v.baptism_date)::int)) AS sunday,
         coalesce(nullif(v.stake, ''), '(not given)') AS stake,
         coalesce(nullif(v.zone, ''), '(not given)') AS zone,
         coalesce(nullif(v.unit, ''), '(not given)') AS unit,
         coalesce(nullif(v.found_how, ''), '(not given)') AS found_how,
         count(*)::int AS baptisms,
         (count(*) FILTER (WHERE v.confirmed))::int AS confirmed
  FROM public.vollzogen_records v
  GROUP BY 1, 2, 3, 4, 5, 6;
COMMENT ON VIEW dashboards.vollzogen_week IS 'Baptisms and how many are confirmed from the office''s Vollzogen list, per week (named by its Sunday), stake, zone, unit and how found. Counts only: no names.';
REVOKE ALL ON dashboards.vollzogen_week FROM PUBLIC, anon, authenticated, service_role;
GRANT SELECT ON dashboards.vollzogen_week TO gfm_dashboard_reader;

-- Check: owners, rights, row level security, the batch kind, and no personal data in what dashboards can read.
DO $$
DECLARE
  found text;
BEGIN
  SELECT string_agg(v, ', ') INTO found
  FROM unnest(ARRAY['public.vollzogen_records', 'dashboards.vollzogen_week']) v
  WHERE to_regclass(v) IS NULL OR (SELECT pg_get_userbyid(relowner) FROM pg_class WHERE oid = to_regclass(v)) <> 'postgres'
     OR coalesce((SELECT reloptions FROM pg_class WHERE oid = to_regclass(v)), '{}') @> ARRAY['security_invoker=true'];
  IF found IS NOT NULL THEN RAISE EXCEPTION 'Check failed: missing, not owned by postgres or security_invoker: %', found; END IF;

  IF NOT has_table_privilege('gfm_dashboard_reader', 'dashboards.vollzogen_week', 'SELECT') THEN
    RAISE EXCEPTION 'Check failed: gfm_dashboard_reader cannot read dashboards.vollzogen_week';
  END IF;

  SELECT string_agg(format('%s (%s)', 'public.vollzogen_records', r), ', ') INTO found
  FROM unnest(ARRAY['public', 'anon', 'authenticated', 'service_role', 'gfm_dashboard_reader']) r
  WHERE has_table_privilege(r, 'public.vollzogen_records', 'SELECT') OR has_table_privilege(r, 'public.vollzogen_records', 'INSERT')
     OR has_table_privilege(r, 'public.vollzogen_records', 'UPDATE') OR has_table_privilege(r, 'public.vollzogen_records', 'DELETE');
  IF found IS NOT NULL THEN RAISE EXCEPTION 'Check failed: these may use the Vollzogen list directly: %', found; END IF;

  SELECT string_agg(r, ', ') INTO found FROM unnest(ARRAY['public', 'anon', 'authenticated', 'service_role']) r
  WHERE has_table_privilege(r, 'dashboards.vollzogen_week', 'SELECT');
  IF found IS NOT NULL THEN RAISE EXCEPTION 'Check failed: these may read the new dashboards view: %', found; END IF;

  IF NOT (SELECT relrowsecurity FROM pg_class WHERE oid = 'public.vollzogen_records'::regclass) THEN
    RAISE EXCEPTION 'Check failed: row level security is off on public.vollzogen_records';
  END IF;
  IF EXISTS (SELECT 1 FROM pg_policy WHERE polrelid = 'public.vollzogen_records'::regclass) THEN
    RAISE EXCEPTION 'Check failed: public.vollzogen_records has a policy (it must have none)';
  END IF;

  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'roster_import_batches_kind_check'
                 AND pg_get_constraintdef(oid) LIKE '%VOLLZOGEN%') THEN
    RAISE EXCEPTION 'Check failed: the batch kind VOLLZOGEN is not allowed.';
  END IF;

  -- Personal data: no column of the dashboards view may look like a name, a person, contact details or a number that
  -- identifies someone.
  SELECT string_agg(c.column_name, ', ') INTO found
  FROM information_schema.columns c
  WHERE c.table_schema = 'dashboards' AND c.table_name = 'vollzogen_week'
    AND c.column_name ~ '(name|person|email|phone|birth|gender|key|fc_number|worker|country|language)';
  IF found IS NOT NULL THEN RAISE EXCEPTION 'Check failed: a column of dashboards.vollzogen_week looks like personal data: %', found; END IF;
END $$;

COMMIT;

-- Verify (read-only, after applying), as postgres:
--   docker exec gfm-beta-supabase-db-1 psql -U postgres -d postgres -c 'BEGIN READ ONLY' -c 'SET LOCAL ROLE gfm_dashboard_reader' -c 'SELECT count(*) FROM dashboards.vollzogen_week' -c 'SELECT count(*) FROM public.vollzogen_records' -c 'ROLLBACK'
-- The first query answers (0 rows until a list is uploaded); the second must fail with "permission denied".
