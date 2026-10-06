-- Rollback of 022_callins_parity.sql. Run on Beta only, as supabase_admin (the file switches to postgres).
--
-- What it restores (exactly as on Beta before 022, taken read-only with pg_get_functiondef on 27 Sep 2026):
--   - the 11 functions 022 replaced: can_edit_dl_call_in, can_edit_zl_call_in, can_edit_zl_zone_call_in,
--     guard_call_in_write, save_dl_call_in_notes, save_zl_call_in_notes, save_zl_zone_call_in_notes,
--     save_call_in_area_update, complete_dl_call_in, reopen_dl_call_in, get_zl_call_in_zone_notes
--     (so only mission managers can write Call-ins again, as after 015);
--   - the call_in_zones read policy (can_access_zone), anon EXECUTE on the 27 legacy call-in functions,
--     TRUNCATE for anon and authenticated on the three call-in tables, and search_path "public" on the 20
--     getters whose code 022 did not change;
-- and removes get_call_in_people, can_view_call_in, is_call_in_district_leader and is_call_in_zone_leader.
-- Notes, area updates and completions saved while 022 was in place stay in the tables.
--
-- Roll back portal-api first (or at the same time): the new Call-ins page needs get_call_in_people, and DL and
-- ZL saves are refused again after this file.
--
-- Run (strip Windows line ends so the function bodies match the originals byte for byte):
--   ((Get-Content portal-api/migrations/022_callins_parity_rollback.sql -Raw) -replace "`r", "") |
--     docker exec -i gfm-beta-supabase-db-1 psql -U supabase_admin -d postgres -v ON_ERROR_STOP=1
--   Git Bash: sed 's/\r$//' portal-api/migrations/022_callins_parity_rollback.sql |
--     docker exec -i gfm-beta-supabase-db-1 psql -U supabase_admin -d postgres -v ON_ERROR_STOP=1
-- It prints two lines; both must match Beta before 022 (27 Sep 2026):
--   functions fingerprint 7171e4f004e22bc5cd3302399b616846   (the 11 function definitions)
--   rights fingerprint aa94040479959d4af482466cc8a26c89      (settings and rights of every call-in function,
--                                                             the grants on the three tables, their policies)
-- Any other value means something differs. Then run 019 again as a check. Safe to run again. It stops after
-- 10 seconds (lock timeout) instead of making Call-ins wait; run it again later.
BEGIN;
SET LOCAL lock_timeout = '10s';

DO $$
BEGIN
  IF current_user NOT IN ('supabase_admin', 'postgres') THEN
    RAISE EXCEPTION 'Run this file as supabase_admin (see its header), not as %.', current_user;
  END IF;
END $$;
SET LOCAL ROLE postgres;

-- The 11 functions as they were (pg_get_functiondef output).
CREATE OR REPLACE FUNCTION public.can_edit_dl_call_in(target_district_id bigint)
 RETURNS boolean
 LANGUAGE sql
 STABLE SECURITY DEFINER
 SET search_path TO 'public', 'pg_temp'
AS $function$
    SELECT EXISTS (SELECT 1 FROM public.areas a
                  WHERE a.district_id = target_district_id
                    AND public.is_mission_manager_for_area(a.id));
$function$
;

CREATE OR REPLACE FUNCTION public.can_edit_zl_call_in(target_district_id bigint)
 RETURNS boolean
 LANGUAGE sql
 STABLE SECURITY DEFINER
 SET search_path TO 'public', 'pg_temp'
AS $function$
    SELECT public.can_edit_dl_call_in(target_district_id);
$function$
;

CREATE OR REPLACE FUNCTION public.can_edit_zl_zone_call_in(target_zone_id bigint)
 RETURNS boolean
 LANGUAGE sql
 STABLE SECURITY DEFINER
 SET search_path TO 'public', 'pg_temp'
AS $function$
    SELECT EXISTS (SELECT 1 FROM public.areas a
                  JOIN public.districts d ON d.id = a.district_id
                  WHERE d.zone_id = target_zone_id
                    AND public.is_mission_manager_for_area(a.id));
$function$
;

CREATE OR REPLACE FUNCTION public.guard_call_in_write()
 RETURNS trigger
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public', 'pg_temp'
AS $function$
DECLARE
    v_old_ok boolean := true;
    v_new_ok boolean := true;
    v_district_id bigint;
BEGIN
    IF public.portal_planning_trusted_write() THEN
        IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
        RETURN NEW;
    END IF;
    IF TG_TABLE_NAME = 'call_in_districts' THEN
        IF TG_OP <> 'INSERT' THEN v_old_ok := public.can_edit_dl_call_in(OLD.district_id); END IF;
        IF TG_OP <> 'DELETE' THEN v_new_ok := public.can_edit_dl_call_in(NEW.district_id); END IF;
    ELSIF TG_TABLE_NAME = 'call_in_zones' THEN
        IF TG_OP <> 'INSERT' THEN v_old_ok := public.can_edit_zl_zone_call_in(OLD.zone_id); END IF;
        IF TG_OP <> 'DELETE' THEN v_new_ok := public.can_edit_zl_zone_call_in(NEW.zone_id); END IF;
    ELSIF TG_TABLE_NAME = 'call_in_area_updates' THEN
        IF TG_OP <> 'INSERT' THEN
            SELECT district_id INTO v_district_id FROM public.call_in_districts WHERE id = OLD.district_call_in_id;
            v_old_ok := public.can_edit_dl_call_in(v_district_id) AND public.is_mission_manager_for_area(OLD.area_id)
                        AND EXISTS (SELECT 1 FROM public.areas WHERE id = OLD.area_id AND district_id = v_district_id);
        END IF;
        IF TG_OP <> 'DELETE' THEN
            SELECT district_id INTO v_district_id FROM public.call_in_districts WHERE id = NEW.district_call_in_id;
            v_new_ok := public.can_edit_dl_call_in(v_district_id) AND public.is_mission_manager_for_area(NEW.area_id)
                        AND EXISTS (SELECT 1 FROM public.areas WHERE id = NEW.area_id AND district_id = v_district_id);
        END IF;
    ELSE
        RAISE EXCEPTION 'Unsupported Call-ins table.' USING ERRCODE = '42501';
    END IF;
    IF NOT coalesce(v_old_ok,false) OR NOT coalesce(v_new_ok,false) THEN
        RAISE EXCEPTION 'Call-ins are editable only by mission managers in their assigned mission.' USING ERRCODE = '42501';
    END IF;
    IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
    RETURN NEW;
END;
$function$
;

CREATE OR REPLACE FUNCTION public.save_dl_call_in_notes(target_district_id bigint, target_reporting_week_id bigint, new_dl_notes text, new_thank_you text)
 RETURNS bigint
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public'
AS $function$

DECLARE
    v_call_in_id bigint;
BEGIN

    IF NOT public.can_edit_dl_call_in(target_district_id) THEN
        RAISE EXCEPTION
            'You do not have permission to edit this district call-in.';
    END IF;


    INSERT INTO public.call_in_districts (
        district_id,
        reporting_week_id,
        dl_notes,
        thank_you
    )
    VALUES (
        target_district_id,
        target_reporting_week_id,
        new_dl_notes,
        new_thank_you
    )

    ON CONFLICT (
        district_id,
        reporting_week_id
    )
    DO UPDATE SET
        dl_notes = EXCLUDED.dl_notes,
        thank_you = EXCLUDED.thank_you,
        updated_at = now()

    RETURNING id
    INTO v_call_in_id;


    RETURN v_call_in_id;

END;
$function$
;

CREATE OR REPLACE FUNCTION public.save_zl_call_in_notes(target_district_id bigint, target_reporting_week_id bigint, new_zl_notes text)
 RETURNS bigint
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public'
AS $function$

DECLARE
    v_call_in_id bigint;
BEGIN

    IF NOT public.can_edit_zl_call_in(target_district_id) THEN
        RAISE EXCEPTION
            'You do not have permission to edit ZL notes for this district.';
    END IF;


    INSERT INTO public.call_in_districts (
        district_id,
        reporting_week_id,
        zl_notes
    )
    VALUES (
        target_district_id,
        target_reporting_week_id,
        new_zl_notes
    )

    ON CONFLICT (
        district_id,
        reporting_week_id
    )
    DO UPDATE SET
        zl_notes = EXCLUDED.zl_notes,
        updated_at = now()

    RETURNING id
    INTO v_call_in_id;


    RETURN v_call_in_id;

END;
$function$
;

CREATE OR REPLACE FUNCTION public.save_zl_zone_call_in_notes(target_zone_id bigint, target_reporting_week_id bigint, new_zone_notes text)
 RETURNS bigint
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public'
AS $function$

DECLARE
    result_id bigint;
BEGIN

    IF NOT public.can_edit_zl_zone_call_in(target_zone_id) THEN
        RAISE EXCEPTION
            'You do not have permission to edit this zone Call-in.';
    END IF;


    INSERT INTO public.call_in_zones (
        zone_id,
        reporting_week_id,
        zone_notes,
        created_at,
        updated_at
    )
    VALUES (
        target_zone_id,
        target_reporting_week_id,
        new_zone_notes,
        now(),
        now()
    )

    ON CONFLICT (zone_id, reporting_week_id)
    DO UPDATE SET
        zone_notes = EXCLUDED.zone_notes,
        updated_at = now()

    RETURNING id
    INTO result_id;


    RETURN result_id;

END;
$function$
;

CREATE OR REPLACE FUNCTION public.save_call_in_area_update(target_district_id bigint, target_reporting_week_id bigint, target_area_id bigint, new_update_text text)
 RETURNS bigint
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public'
AS $function$

DECLARE
    v_call_in_id bigint;
    v_area_update_id bigint;
BEGIN

    IF NOT public.can_edit_dl_call_in(target_district_id) THEN
        RAISE EXCEPTION
            'You do not have permission to edit this district call-in.';
    END IF;


    -- Make sure the selected area actually belongs to the district.
    IF NOT EXISTS (
        SELECT 1
        FROM public.areas a
        WHERE a.id = target_area_id
          AND a.district_id = target_district_id
    ) THEN
        RAISE EXCEPTION
            'Area does not belong to this district.';
    END IF;


    -- Make sure district call-in parent exists.
    INSERT INTO public.call_in_districts (
        district_id,
        reporting_week_id
    )
    VALUES (
        target_district_id,
        target_reporting_week_id
    )

    ON CONFLICT (
        district_id,
        reporting_week_id
    )
    DO UPDATE SET
        updated_at = public.call_in_districts.updated_at

    RETURNING id
    INTO v_call_in_id;


    -- Save the area update.
    INSERT INTO public.call_in_area_updates (
        district_call_in_id,
        area_id,
        update_text
    )
    VALUES (
        v_call_in_id,
        target_area_id,
        new_update_text
    )

    ON CONFLICT (
        district_call_in_id,
        area_id
    )
    DO UPDATE SET
        update_text = EXCLUDED.update_text,
        updated_at = now()

    RETURNING id
    INTO v_area_update_id;


    RETURN v_area_update_id;

END;
$function$
;

CREATE OR REPLACE FUNCTION public.complete_dl_call_in(target_district_id bigint, target_reporting_week_id bigint)
 RETURNS bigint
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public'
AS $function$

DECLARE
    result_id bigint;
BEGIN

    IF NOT public.can_edit_dl_call_in(target_district_id) THEN
        RAISE EXCEPTION
            'You do not have permission to complete this district Call-in.';
    END IF;


    INSERT INTO public.call_in_districts (
        district_id,
        reporting_week_id,
        dl_completed_at,
        dl_completed_by,
        created_at,
        updated_at
    )
    VALUES (
        target_district_id,
        target_reporting_week_id,
        now(),
        auth.uid(),
        now(),
        now()
    )

    ON CONFLICT (district_id, reporting_week_id)
    DO UPDATE SET
        dl_completed_at = now(),
        dl_completed_by = auth.uid(),
        updated_at = now()

    RETURNING id
    INTO result_id;


    RETURN result_id;

END;
$function$
;

CREATE OR REPLACE FUNCTION public.reopen_dl_call_in(target_district_id bigint, target_reporting_week_id bigint)
 RETURNS bigint
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public'
AS $function$

DECLARE
    result_id bigint;
BEGIN

    IF NOT public.can_edit_dl_call_in(target_district_id) THEN
        RAISE EXCEPTION
            'You do not have permission to reopen this district Call-in.';
    END IF;


    INSERT INTO public.call_in_districts (
        district_id,
        reporting_week_id,
        dl_completed_at,
        dl_completed_by,
        created_at,
        updated_at
    )
    VALUES (
        target_district_id,
        target_reporting_week_id,
        NULL,
        NULL,
        now(),
        now()
    )

    ON CONFLICT (district_id, reporting_week_id)
    DO UPDATE SET
        dl_completed_at = NULL,
        dl_completed_by = NULL,
        updated_at = now()

    RETURNING id
    INTO result_id;


    RETURN result_id;

END;
$function$
;

CREATE OR REPLACE FUNCTION public.get_zl_call_in_zone_notes(target_zone_id bigint, target_reporting_week_id bigint)
 RETURNS TABLE(zone_id bigint, zone_name text, reporting_week_id bigint, reporting_sunday date, zone_notes text)
 LANGUAGE plpgsql
 STABLE SECURITY DEFINER
 SET search_path TO 'public'
AS $function$

BEGIN

    IF NOT public.can_access_zone(target_zone_id) THEN
        RAISE EXCEPTION
            'You do not have permission to view this zone.';
    END IF;


    RETURN QUERY

    SELECT

        z.id::bigint,
        z.name::text,

        rw.id::bigint,
        rw.sunday::date,

        ciz.zone_notes::text

    FROM public.zones z

    JOIN public.reporting_weeks rw
      ON rw.id = target_reporting_week_id

    LEFT JOIN public.call_in_zones ciz
      ON ciz.zone_id = z.id
     AND ciz.reporting_week_id = rw.id

    WHERE z.id = target_zone_id;

END;
$function$
;

-- The functions 022 added (nothing uses them once the definitions above are back).
DROP FUNCTION IF EXISTS public.get_call_in_people(text, bigint, bigint);
DROP FUNCTION IF EXISTS public.can_view_call_in(text, bigint);
DROP FUNCTION IF EXISTS public.is_call_in_district_leader(bigint);
DROP FUNCTION IF EXISTS public.is_call_in_zone_leader(bigint);

ALTER POLICY call_in_zones_select ON public.call_in_zones USING (public.can_access_zone(zone_id));

GRANT EXECUTE ON FUNCTION
    public.complete_dl_call_in(bigint, bigint), public.reopen_dl_call_in(bigint, bigint),
    public.save_call_in_area_update(bigint, bigint, bigint, text), public.save_dl_call_in_notes(bigint, bigint, text, text),
    public.save_zl_call_in_notes(bigint, bigint, text), public.save_zl_zone_call_in_notes(bigint, bigint, text),
    public.get_zl_call_in_zone_notes(bigint, bigint),
    public.get_dl_call_in_baptismal_dates(bigint, bigint), public.get_dl_call_in_bd_activity(bigint, bigint),
    public.get_dl_call_in_high_potentials(bigint, bigint), public.get_dl_call_in_hp_activity(bigint, bigint),
    public.get_dl_call_in_new_members(bigint, bigint), public.get_dl_call_in_nm_activity(bigint, bigint),
    public.get_dl_call_in_summary(bigint, bigint), public.get_dl_call_in_ward_coordination(bigint, bigint),
    public.get_mission_call_in_bd_activity(bigint, bigint), public.get_mission_call_in_hp_activity(bigint, bigint),
    public.get_mission_call_in_nm_activity(bigint, bigint), public.get_mission_call_in_summary(bigint, bigint),
    public.get_zl_call_in_area_updates(bigint, bigint), public.get_zl_call_in_baptismal_dates(bigint, bigint),
    public.get_zl_call_in_bd_activity(bigint, bigint), public.get_zl_call_in_high_potentials(bigint, bigint),
    public.get_zl_call_in_hp_activity(bigint, bigint), public.get_zl_call_in_new_members(bigint, bigint),
    public.get_zl_call_in_nm_activity(bigint, bigint), public.get_zl_call_in_summary(bigint, bigint)
TO anon;

ALTER FUNCTION public.get_dl_call_in_baptismal_dates(bigint, bigint) SET search_path = public;
ALTER FUNCTION public.get_dl_call_in_bd_activity(bigint, bigint) SET search_path = public;
ALTER FUNCTION public.get_dl_call_in_high_potentials(bigint, bigint) SET search_path = public;
ALTER FUNCTION public.get_dl_call_in_hp_activity(bigint, bigint) SET search_path = public;
ALTER FUNCTION public.get_dl_call_in_new_members(bigint, bigint) SET search_path = public;
ALTER FUNCTION public.get_dl_call_in_nm_activity(bigint, bigint) SET search_path = public;
ALTER FUNCTION public.get_dl_call_in_summary(bigint, bigint) SET search_path = public;
ALTER FUNCTION public.get_dl_call_in_ward_coordination(bigint, bigint) SET search_path = public;
ALTER FUNCTION public.get_mission_call_in_bd_activity(bigint, bigint) SET search_path = public;
ALTER FUNCTION public.get_mission_call_in_hp_activity(bigint, bigint) SET search_path = public;
ALTER FUNCTION public.get_mission_call_in_nm_activity(bigint, bigint) SET search_path = public;
ALTER FUNCTION public.get_mission_call_in_summary(bigint, bigint) SET search_path = public;
ALTER FUNCTION public.get_zl_call_in_area_updates(bigint, bigint) SET search_path = public;
ALTER FUNCTION public.get_zl_call_in_baptismal_dates(bigint, bigint) SET search_path = public;
ALTER FUNCTION public.get_zl_call_in_bd_activity(bigint, bigint) SET search_path = public;
ALTER FUNCTION public.get_zl_call_in_high_potentials(bigint, bigint) SET search_path = public;
ALTER FUNCTION public.get_zl_call_in_hp_activity(bigint, bigint) SET search_path = public;
ALTER FUNCTION public.get_zl_call_in_new_members(bigint, bigint) SET search_path = public;
ALTER FUNCTION public.get_zl_call_in_nm_activity(bigint, bigint) SET search_path = public;
ALTER FUNCTION public.get_zl_call_in_summary(bigint, bigint) SET search_path = public;

GRANT TRUNCATE ON public.call_in_districts, public.call_in_zones, public.call_in_area_updates TO anon, authenticated;

-- Check: PUBLIC still cannot run any call-in function (019), and the policy is back.
DO $$
DECLARE
  found text;
BEGIN
  SELECT string_agg(p.oid::regprocedure::text, ', ') INTO found
  FROM pg_proc p
  WHERE p.pronamespace = 'public'::regnamespace AND p.proname LIKE '%call_in%' AND p.prosecdef
    AND has_function_privilege('public', p.oid, 'EXECUTE');
  IF found IS NOT NULL THEN
    RAISE EXCEPTION 'PUBLIC can run: %', found;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE schemaname = 'public' AND tablename = 'call_in_zones'
                   AND policyname = 'call_in_zones_select' AND qual LIKE '%can_access_zone%') THEN
    RAISE EXCEPTION 'The call_in_zones read policy was not restored.';
  END IF;
END $$;

NOTIFY pgrst, 'reload schema';
COMMIT;
SELECT 'functions fingerprint ' || md5(string_agg(x, '|' ORDER BY n)) FROM (VALUES
  (1, pg_get_functiondef('public.can_edit_dl_call_in(bigint)'::regprocedure)),
  (2, pg_get_functiondef('public.can_edit_zl_call_in(bigint)'::regprocedure)),
  (3, pg_get_functiondef('public.can_edit_zl_zone_call_in(bigint)'::regprocedure)),
  (4, pg_get_functiondef('public.guard_call_in_write()'::regprocedure)),
  (5, pg_get_functiondef('public.save_dl_call_in_notes(bigint,bigint,text,text)'::regprocedure)),
  (6, pg_get_functiondef('public.save_zl_call_in_notes(bigint,bigint,text)'::regprocedure)),
  (7, pg_get_functiondef('public.save_zl_zone_call_in_notes(bigint,bigint,text)'::regprocedure)),
  (8, pg_get_functiondef('public.save_call_in_area_update(bigint,bigint,bigint,text)'::regprocedure)),
  (9, pg_get_functiondef('public.complete_dl_call_in(bigint,bigint)'::regprocedure)),
  (10, pg_get_functiondef('public.reopen_dl_call_in(bigint,bigint)'::regprocedure)),
  (11, pg_get_functiondef('public.get_zl_call_in_zone_notes(bigint,bigint)'::regprocedure))) v(n, x);
SELECT 'rights fingerprint ' || md5(string_agg(x, '|' ORDER BY x)) FROM (
  SELECT p.oid::regprocedure::text || ' ' || coalesce(array_to_string(p.proconfig, ','), '') || ' ' || coalesce((
      SELECT string_agg(g, ',' ORDER BY g) FROM (
        SELECT CASE a.grantee WHEN 0 THEN 'PUBLIC' ELSE a.grantee::regrole::text END || ':' || a.privilege_type AS g
        FROM aclexplode(p.proacl) a) e), '') AS x
  FROM pg_proc p WHERE p.pronamespace = 'public'::regnamespace AND p.proname LIKE '%call_in%'
  UNION ALL
  SELECT c.relname || ' ' || coalesce((
      SELECT string_agg(g, ',' ORDER BY g) FROM (
        SELECT CASE a.grantee WHEN 0 THEN 'PUBLIC' ELSE a.grantee::regrole::text END || ':' || a.privilege_type AS g
        FROM aclexplode(c.relacl) a) e), '')
  FROM pg_class c
  WHERE c.oid IN ('public.call_in_districts'::regclass, 'public.call_in_zones'::regclass, 'public.call_in_area_updates'::regclass)
  UNION ALL
  SELECT policyname || ' ' || qual FROM pg_policies WHERE schemaname = 'public' AND tablename LIKE 'call_in%') s;
