-- Migration 055 (Oct 2026): what each role may do, as a table that managers can change (DA Management > Accounts > Role abilities).
-- Run on Beta only, as supabase_admin. Back up first (CLAUDE.md, "Before any database change").
--
-- Why: round 13, task 21 (design note docs/handoff/round13/role-abilities-design.md, approved by the owner on 13 Oct 2026). Until now
-- "may Office see the Vollzogen list?" or "may a ZL publish announcements?" were fixed in portal-api/roles.py. Now five abilities
-- are rows in a table. portal-api/roles.py and roster-importer/roles.py read it (cached for 30 seconds; the built-in matrix is the
-- fallback when the table cannot be read). NOTHING CHANGES FOR ANYONE until a manager edits a switch: the table is seeded with
-- exactly today's matrix, and the check at the end of this file proves it.
--
-- What changes:
-- 1. public.ability_catalog: the five abilities (calendar.edit, announcements.publish, vollzogen.view, presentations.use,
--    plans.unlock). Fixed; the screen cannot add or remove one.
-- 2. public.role_abilities: one row per (role, ability), all 8 roles x 5 abilities = 40 rows, seeded with today's matrix.
--    public.role_ability_ok(role, ability, allowed) says which values a cell may have, and a CHECK uses it:
--      - AP, President and Data Analyst always have every ability (managers can never lose one: no lock-out);
--      - Missionary never has any (an ability cannot be given to a role without stewardship);
--      - cells that are not switchable stay at today's value: Office never gets presentations or plan unlock, DL/ZL/STL never
--        edit the calendar or see the Vollzogen list, an STL never unlocks plans; only the cells listed below can be switched.
--    A trigger also refuses to delete a row, to change a cell's role or ability, and to change a value without a change batch
--    (set by DA Management in the same transaction: gfm.change_batch), so a change cannot go unlogged by accident.
--    There is NO ability for DA Management access, for giving roles, for deleting places or for editing abilities: those stay
--    in code (managers only) and cannot be switched at all. Office can never become a manager through this table.
-- 3. public.role_abilities_log: one row per changed cell (who, when, role, ability, before, after, batch, note). Written by the
--    trigger above; append-only (a trigger refuses UPDATE and DELETE). No foreign keys: the log outlives everything.
-- 4. public.role_has_ability(ability): the question for the database ("may the signed-in person do this?"), SECURITY DEFINER with a
--    fixed search_path, EXECUTE only for authenticated and service_role. No policy or function in the database calls it yet
--    (design phase 4, "RLS follows", is a later migration): the row-level security rules still decide as before. See the
--    hand-over note: until phase 4, a SWITCH-OFF reaches portal-api and DA Management but not the database's own policies.
-- The tables hold no personal data but decide rights: row level security is ON with NO policy and no rights for PUBLIC, anon,
-- authenticated or service_role, so only the services that connect as postgres (DA Management and portal-api) can read or write them.
-- No row of any existing table is changed.
--
-- Switchable cells (everything else is fixed). All of them are ON today, so in this release a manager can switch a right OFF and back ON,
-- but cannot give a role a right it does not have today: calendar editing for a DL/ZL/STL would also show them every event of the mission
-- (portal-api visible()), and the database's own rules (unlock, Vollzogen, presentations) are not switchable yet.
--   calendar.edit          Office                   (today: yes)
--   announcements.publish  DL, ZL, STL, Office      (today: all four)
--   vollzogen.view         Office                   (today: yes)
--   presentations.use      DL, ZL, STL              (today: all three)
--   plans.unlock           DL, ZL                   (today: both)
--
-- Apply (back up Beta first). Join the lines with plain line feeds:
--   (Get-Content portal-api/migrations/055_role_abilities.sql) -join "`n" |
--     docker exec -i gfm-beta-supabase-db-1 psql -U supabase_admin -d postgres -v ON_ERROR_STOP=1
-- (Ubuntu server: psql as supabase_admin in the db container, the same way.) THEN RUN 019_restrict_public_functions.sql AGAIN as a
-- check, as after every migration (it must end with COMMIT): that re-run is part of the deploy, because role_has_ability is a new
-- SECURITY DEFINER function. Apply this BEFORE the new portal-api and DA Management images (they read the table; without it they
-- fall back to the built-in matrix, so the order is safe either way, but the screen needs the table).
-- Safe to run again: IF NOT EXISTS, CREATE OR REPLACE, seed rows only where missing, then a check that stops on any problem.
-- Rollback: 055_role_abilities_rollback.sql (drops the tables WITH the change log and the function; the code then uses the built-in matrix).
BEGIN;
SET LOCAL lock_timeout = '10s';

DO $$
BEGIN
  IF session_user NOT IN ('supabase_admin', 'postgres') THEN
    RAISE EXCEPTION 'Run this file as supabase_admin (see its header), not as %.', session_user;
  END IF;
  IF to_regclass('public.user_profiles') IS NULL OR to_regclass('public.current_user_context') IS NULL THEN
    RAISE EXCEPTION 'The accounts tables are missing (user_profiles, current_user_context).';
  END IF;
END $$;

-- Everything below belongs to postgres, like the tables of 051 (DA Management and portal-api connect as postgres).
SET LOCAL ROLE postgres;

-- 1. The abilities.
CREATE TABLE IF NOT EXISTS public.ability_catalog (
  ability text PRIMARY KEY CHECK (ability IN ('calendar.edit', 'announcements.publish', 'vollzogen.view', 'presentations.use', 'plans.unlock')),
  sort_order int NOT NULL UNIQUE
);
COMMENT ON TABLE public.ability_catalog IS 'The five abilities a manager may switch per role (DA Management > Accounts > Role abilities). Fixed by migration 055.';
INSERT INTO public.ability_catalog (ability, sort_order) VALUES
  ('calendar.edit', 1), ('announcements.publish', 2), ('vollzogen.view', 3), ('presentations.use', 4), ('plans.unlock', 5)
ON CONFLICT (ability) DO NOTHING;

-- 2. Which value a cell may have. IMMUTABLE, used by the CHECK below. The same rules are in roles.py (SWITCHABLE, DEFAULT_ROLES).
CREATE OR REPLACE FUNCTION public.role_ability_ok(p_role text, p_ability text, p_allowed boolean)
RETURNS boolean
LANGUAGE sql IMMUTABLE
SET search_path TO 'pg_catalog', 'pg_temp'
AS $$
  SELECT CASE
    WHEN p_allowed IS NULL THEN false
    WHEN p_role NOT IN ('MISSIONARY', 'DL', 'ZL', 'STL', 'AP', 'OFFICE', 'PRESIDENT', 'DATA_ADMIN') THEN false
    WHEN p_ability NOT IN ('calendar.edit', 'announcements.publish', 'vollzogen.view', 'presentations.use', 'plans.unlock') THEN false
    -- Managers always keep every ability.
    WHEN p_role IN ('AP', 'PRESIDENT', 'DATA_ADMIN') THEN p_allowed
    -- A missionary has none, whatever is written.
    WHEN p_role = 'MISSIONARY' THEN NOT p_allowed
    -- Switchable cells: any value.
    WHEN p_ability = 'calendar.edit' AND p_role = 'OFFICE' THEN true
    WHEN p_ability = 'announcements.publish' AND p_role IN ('DL', 'ZL', 'STL', 'OFFICE') THEN true
    WHEN p_ability = 'vollzogen.view' AND p_role = 'OFFICE' THEN true
    WHEN p_ability = 'presentations.use' AND p_role IN ('DL', 'ZL', 'STL') THEN true
    WHEN p_ability = 'plans.unlock' AND p_role IN ('DL', 'ZL') THEN true
    -- Fixed cells keep today's value (all of them are "no": DL/ZL/STL and calendar editing or the Vollzogen list, Office and
    -- presentations, STL and Office and plan unlock).
    ELSE NOT p_allowed
  END
$$;
REVOKE EXECUTE ON FUNCTION public.role_ability_ok(text, text, boolean) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.role_ability_ok(text, text, boolean) TO postgres, authenticated, service_role;

CREATE TABLE IF NOT EXISTS public.role_abilities (
  role text NOT NULL,
  ability text NOT NULL REFERENCES public.ability_catalog (ability),
  allowed boolean NOT NULL,
  changed_at timestamptz NOT NULL DEFAULT now(),
  changed_by uuid,
  changed_by_name text NOT NULL DEFAULT 'migration 055' CHECK (char_length(changed_by_name) BETWEEN 1 AND 200),
  PRIMARY KEY (role, ability),
  CONSTRAINT role_abilities_cell_ok CHECK (public.role_ability_ok(role, ability, allowed))
);
COMMENT ON TABLE public.role_abilities IS 'What each role may do (migration 055). One row per role and ability, all 40 present. Changed only by DA Management > Accounts > Role abilities; every change is in role_abilities_log.';

-- 3. The log of changes.
CREATE TABLE IF NOT EXISTS public.role_abilities_log (
  id bigint GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
  batch_id uuid NOT NULL,
  role text NOT NULL,
  ability text NOT NULL,
  before_allowed boolean NOT NULL,
  after_allowed boolean NOT NULL,
  changed_by uuid,
  changed_by_name text NOT NULL,
  note text CHECK (note IS NULL OR char_length(note) <= 500),
  reverts_batch uuid,
  changed_at timestamptz NOT NULL DEFAULT now(),
  CHECK (before_allowed <> after_allowed)
);
COMMENT ON TABLE public.role_abilities_log IS 'One row per changed cell of role_abilities: who, when, before, after. A save or a revert is one batch. Append-only. No foreign keys on purpose.';
CREATE INDEX IF NOT EXISTS role_abilities_log_batch_idx ON public.role_abilities_log (batch_id);
CREATE INDEX IF NOT EXISTS role_abilities_log_when_idx ON public.role_abilities_log (changed_at DESC, id DESC);

-- The guards.
CREATE OR REPLACE FUNCTION public.role_abilities_guard()
RETURNS trigger
LANGUAGE plpgsql
SET search_path TO 'public', 'pg_temp'
AS $$
DECLARE
  v_batch text := nullif(current_setting('gfm.change_batch', true), '');
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'A role ability row cannot be deleted.' USING ERRCODE = '42501';
  END IF;
  IF TG_OP = 'UPDATE' THEN
    IF NEW.role IS DISTINCT FROM OLD.role OR NEW.ability IS DISTINCT FROM OLD.ability THEN
      RAISE EXCEPTION 'The role and the ability of a cell cannot be changed.' USING ERRCODE = '42501';
    END IF;
    IF NEW.allowed IS DISTINCT FROM OLD.allowed THEN
      IF v_batch IS NULL THEN
        RAISE EXCEPTION 'A change of a role ability must come from DA Management (gfm.change_batch is not set), so that it is logged.' USING ERRCODE = '42501';
      END IF;
      BEGIN
        PERFORM v_batch::uuid;
      EXCEPTION WHEN invalid_text_representation THEN
        RAISE EXCEPTION 'gfm.change_batch must be a UUID.' USING ERRCODE = '22023';
      END;
      IF nullif(btrim(NEW.changed_by_name), '') IS NULL OR NEW.changed_by_name = 'migration 055' THEN
        RAISE EXCEPTION 'A change of a role ability must say who made it (changed_by_name).' USING ERRCODE = '22023';
      END IF;
      NEW.changed_at := now();
    END IF;
  END IF;
  RETURN NEW;
END;
$$;
DROP TRIGGER IF EXISTS role_abilities_guard ON public.role_abilities;
CREATE TRIGGER role_abilities_guard BEFORE UPDATE OR DELETE ON public.role_abilities
  FOR EACH ROW EXECUTE FUNCTION public.role_abilities_guard();

CREATE OR REPLACE FUNCTION public.role_abilities_write_log()
RETURNS trigger
LANGUAGE plpgsql
SET search_path TO 'public', 'pg_temp'
AS $$
BEGIN
  IF NEW.allowed IS DISTINCT FROM OLD.allowed THEN
    INSERT INTO public.role_abilities_log (batch_id, role, ability, before_allowed, after_allowed, changed_by, changed_by_name, note, reverts_batch)
    VALUES (current_setting('gfm.change_batch')::uuid, NEW.role, NEW.ability, OLD.allowed, NEW.allowed, NEW.changed_by, NEW.changed_by_name,
            left(nullif(btrim(coalesce(current_setting('gfm.change_note', true), '')), ''), 500),
            nullif(current_setting('gfm.reverts_batch', true), '')::uuid);
  END IF;
  RETURN NEW;
END;
$$;
DROP TRIGGER IF EXISTS role_abilities_write_log ON public.role_abilities;
CREATE TRIGGER role_abilities_write_log AFTER UPDATE ON public.role_abilities
  FOR EACH ROW EXECUTE FUNCTION public.role_abilities_write_log();

CREATE OR REPLACE FUNCTION public.role_abilities_log_append_only()
RETURNS trigger
LANGUAGE plpgsql
SET search_path TO 'public', 'pg_temp'
AS $$
BEGIN
  RAISE EXCEPTION 'The role ability log is append-only.' USING ERRCODE = '42501';
END;
$$;
DROP TRIGGER IF EXISTS role_abilities_log_append_only ON public.role_abilities_log;
CREATE TRIGGER role_abilities_log_append_only BEFORE UPDATE OR DELETE ON public.role_abilities_log
  FOR EACH ROW EXECUTE FUNCTION public.role_abilities_log_append_only();

-- Seed: EXACTLY today's matrix (portal-api/roles.py on 13 Oct 2026). Only where a row is missing (safe to run again).
INSERT INTO public.role_abilities (role, ability, allowed)
SELECT r.role, a.ability,
       CASE a.ability
         WHEN 'calendar.edit' THEN r.role IN ('AP', 'PRESIDENT', 'DATA_ADMIN', 'OFFICE')
         WHEN 'announcements.publish' THEN r.role <> 'MISSIONARY'
         WHEN 'vollzogen.view' THEN r.role IN ('AP', 'PRESIDENT', 'DATA_ADMIN', 'OFFICE')
         WHEN 'presentations.use' THEN r.role IN ('DL', 'ZL', 'STL', 'AP', 'PRESIDENT', 'DATA_ADMIN')
         WHEN 'plans.unlock' THEN r.role IN ('DL', 'ZL', 'AP', 'PRESIDENT', 'DATA_ADMIN')
       END
FROM (VALUES ('MISSIONARY'), ('DL'), ('ZL'), ('STL'), ('AP'), ('OFFICE'), ('PRESIDENT'), ('DATA_ADMIN')) AS r(role)
CROSS JOIN public.ability_catalog a
ON CONFLICT (role, ability) DO NOTHING;

-- 4. The database's own question. Roles are worked out as in roles.py: the main role is President/Data Analyst/Office when the
--    account says so, else the highest leadership assignment in force (AP > ZL > STL > DL), else Missionary; the additional roles
--    Data Analyst and Office come on top. The person holds the ability if ANY of their roles has it.
CREATE OR REPLACE FUNCTION public.role_has_ability(p_ability text)
RETURNS boolean
LANGUAGE plpgsql STABLE SECURITY DEFINER
SET search_path TO 'public', 'pg_temp'
AS $$
DECLARE
  v_app text;
  v_lead text;
  v_extra text[];
  v_main text;
  v_roles text[];
BEGIN
  IF auth.uid() IS NULL THEN
    RETURN false;
  END IF;
  SELECT upper(c.app_role), upper(c.leadership_role), coalesce(c.additional_roles, '{}'::text[])
    INTO v_app, v_lead, v_extra
  FROM public.current_user_context c
  WHERE c.user_id = auth.uid() AND c.user_active
  ORDER BY array_position(ARRAY['AP', 'ZL', 'STL', 'DL'], upper(c.leadership_role)) NULLS LAST
  LIMIT 1;
  IF NOT FOUND THEN
    RETURN false;
  END IF;
  v_main := CASE WHEN v_app IN ('PRESIDENT', 'DATA_ADMIN', 'OFFICE') THEN v_app
                 WHEN v_lead IN ('AP', 'ZL', 'STL', 'DL') THEN v_lead
                 ELSE 'MISSIONARY' END;
  v_roles := ARRAY[v_main] || ARRAY(SELECT x FROM unnest(ARRAY['DATA_ADMIN', 'OFFICE']) x
                                     WHERE upper(x) = ANY (SELECT upper(e) FROM unnest(v_extra) e) AND x <> v_main);
  RETURN coalesce((SELECT bool_or(ra.allowed) FROM public.role_abilities ra
                   WHERE ra.ability = p_ability AND ra.role = ANY (v_roles)), false);
END;
$$;
REVOKE EXECUTE ON FUNCTION public.role_has_ability(text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.role_has_ability(text) TO postgres, authenticated, service_role;

-- Rights: only postgres (the services that connect as postgres). Row level security on, with no policy.
ALTER TABLE public.ability_catalog ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.role_abilities ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.role_abilities_log ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.ability_catalog, public.role_abilities, public.role_abilities_log FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON SEQUENCE public.role_abilities_log_id_seq FROM PUBLIC, anon, authenticated, service_role;
REVOKE EXECUTE ON FUNCTION public.role_abilities_guard(), public.role_abilities_write_log(), public.role_abilities_log_append_only() FROM PUBLIC;

-- Check: the seed is today's matrix, the rules hold, the rights are closed.
DO $$
DECLARE
  found text;
  expected CONSTANT text := 'AP/announcements.publish=t AP/calendar.edit=t AP/plans.unlock=t AP/presentations.use=t AP/vollzogen.view=t '
    || 'DATA_ADMIN/announcements.publish=t DATA_ADMIN/calendar.edit=t DATA_ADMIN/plans.unlock=t DATA_ADMIN/presentations.use=t DATA_ADMIN/vollzogen.view=t '
    || 'DL/announcements.publish=t DL/calendar.edit=f DL/plans.unlock=t DL/presentations.use=t DL/vollzogen.view=f '
    || 'MISSIONARY/announcements.publish=f MISSIONARY/calendar.edit=f MISSIONARY/plans.unlock=f MISSIONARY/presentations.use=f MISSIONARY/vollzogen.view=f '
    || 'OFFICE/announcements.publish=t OFFICE/calendar.edit=t OFFICE/plans.unlock=f OFFICE/presentations.use=f OFFICE/vollzogen.view=t '
    || 'PRESIDENT/announcements.publish=t PRESIDENT/calendar.edit=t PRESIDENT/plans.unlock=t PRESIDENT/presentations.use=t PRESIDENT/vollzogen.view=t '
    || 'STL/announcements.publish=t STL/calendar.edit=f STL/plans.unlock=f STL/presentations.use=t STL/vollzogen.view=f '
    || 'ZL/announcements.publish=t ZL/calendar.edit=f ZL/plans.unlock=t ZL/presentations.use=t ZL/vollzogen.view=f';
BEGIN
  IF (SELECT count(*) FROM public.role_abilities) <> 40 THEN
    RAISE EXCEPTION 'Check failed: role_abilities must hold 40 rows (8 roles x 5 abilities), it holds %.', (SELECT count(*) FROM public.role_abilities);
  END IF;
  -- On a first run the table is today's matrix. (After managers changed switches, run this file again only after a rollback.)
  IF NOT EXISTS (SELECT 1 FROM public.role_abilities_log) THEN
    SELECT string_agg(role || '/' || ability || '=' || CASE WHEN allowed THEN 't' ELSE 'f' END, ' ' ORDER BY role COLLATE "C", ability COLLATE "C") INTO found FROM public.role_abilities;
    IF found IS DISTINCT FROM expected THEN
      RAISE EXCEPTION 'Check failed: the seeded matrix is not today''s matrix: %', found;
    END IF;
  END IF;
  -- The rules refuse what they must refuse.
  IF public.role_ability_ok('OFFICE', 'presentations.use', true) OR public.role_ability_ok('AP', 'plans.unlock', false)
     OR public.role_ability_ok('PRESIDENT', 'calendar.edit', false) OR public.role_ability_ok('DATA_ADMIN', 'vollzogen.view', false)
     OR public.role_ability_ok('MISSIONARY', 'calendar.edit', true) OR public.role_ability_ok('STL', 'plans.unlock', true)
     OR public.role_ability_ok('DL', 'vollzogen.view', true) OR public.role_ability_ok('OFFICE', 'plans.unlock', true)
     OR public.role_ability_ok('DL', 'calendar.edit', true) OR public.role_ability_ok('OFFICE', 'management', true) OR public.role_ability_ok('NOBODY', 'calendar.edit', true)
     OR NOT public.role_ability_ok('OFFICE', 'vollzogen.view', false) OR NOT public.role_ability_ok('DL', 'announcements.publish', false) THEN
    RAISE EXCEPTION 'Check failed: role_ability_ok does not follow the rules.';
  END IF;
  -- Rights: nobody but postgres.
  SELECT string_agg(format('%s (%s)', t, r), ', ') INTO found
  FROM unnest(ARRAY['public.ability_catalog', 'public.role_abilities', 'public.role_abilities_log']) t
  CROSS JOIN unnest(ARRAY['public', 'anon', 'authenticated', 'service_role']) r
  WHERE has_table_privilege(r, t, 'SELECT') OR has_table_privilege(r, t, 'INSERT') OR has_table_privilege(r, t, 'UPDATE') OR has_table_privilege(r, t, 'DELETE');
  IF found IS NOT NULL THEN RAISE EXCEPTION 'Check failed: these may use the role ability tables directly: %', found; END IF;
  IF EXISTS (SELECT 1 FROM pg_class c WHERE c.oid IN ('public.ability_catalog'::regclass, 'public.role_abilities'::regclass, 'public.role_abilities_log'::regclass)
             AND (NOT c.relrowsecurity OR pg_get_userbyid(c.relowner) <> 'postgres')) THEN
    RAISE EXCEPTION 'Check failed: row level security is off or an owner is not postgres on a role ability table.';
  END IF;
  IF EXISTS (SELECT 1 FROM pg_policy WHERE polrelid IN ('public.ability_catalog'::regclass, 'public.role_abilities'::regclass, 'public.role_abilities_log'::regclass)) THEN
    RAISE EXCEPTION 'Check failed: a role ability table has a policy (it must have none).';
  END IF;
  IF has_function_privilege('anon', 'public.role_has_ability(text)', 'EXECUTE') OR has_function_privilege('public', 'public.role_has_ability(text)', 'EXECUTE')
     OR NOT has_function_privilege('authenticated', 'public.role_has_ability(text)', 'EXECUTE') THEN
    RAISE EXCEPTION 'Check failed: role_has_ability must run for authenticated and service_role only.';
  END IF;
  IF NOT (SELECT prosecdef FROM pg_proc WHERE oid = 'public.role_has_ability(text)'::regprocedure) THEN
    RAISE EXCEPTION 'Check failed: role_has_ability must be SECURITY DEFINER.';
  END IF;
END $$;

COMMIT;
