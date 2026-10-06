-- Call-ins parity with Beta: leaders write their own call-in parts, a completed district call-in is locked,
-- zone notes stay with the zone's leaders, and one function returns the people of any scope. Run on Beta only.
--
-- Why: since 015 only mission managers could save anything in Call-ins, so every DL and ZL save in Beta failed
-- with "You do not have permission". Call-ins Alpha (portal-api callins.py) now offers the same saves as Beta,
-- a drill-down from the mission to one area, and the baptismal-date, new-member and high-potential lists.
--
-- Who may write what (portal-api checks the same rules first; these functions are the final word):
--   - The DL of district D: DL notes and area updates of D, and Complete / Reopen of D's call-in.
--   - The ZL of zone Z: ZL notes of every district in Z, and the zone notes of Z.
--   - Mission managers (is_mission_manager_for_area: AP, President, Data Analyst with an assignment in the
--     mission): everything in their mission.
--   - STLs have no part in Call-ins: nothing in this file lets an STL assignment read or write anything.
--   - A completed district call-in locks its DL notes and area updates until the DL or a manager reopens it.
--     ZL notes and zone notes are never locked.
--   - Zone notes can be read only by the ZL of that zone and mission managers (get_zl_call_in_zone_notes and the
--     call_in_zones read policy); before, every missionary of the zone could read them.
--   - There is no thank-you feature. call_in_districts.thank_you is left exactly as it is: saving DL notes no
--     longer writes it (Beta sent NULL there and wiped it on every save).
--
-- What changes (Beta/Appsmith keeps calling the same functions with the same arguments and gets the same
-- columns; only who may write and the zone-notes readers change):
--   1. New helpers is_call_in_district_leader(district) and is_call_in_zone_leader(zone): a current DL, or ZL,
--      leadership assignment of the signed-in user (never STL). They do not look at user_profiles.app_role, so
--      leaders whose account role drifted (live on 27 Sep 2026) still count. can_view_call_in(level, id): the
--      read rule of the portal's Call-ins (DL of the district, ZL of the zone, or a mission manager).
--   2. can_edit_dl_call_in / can_edit_zl_call_in / can_edit_zl_zone_call_in: the rules above.
--   3. guard_call_in_write (row trigger on the three call-in tables): checks the part of the row that changes,
--      because call_in_districts holds the DL part (notes, completion) and the ZL notes in one row, and enforces
--      the completion lock for every writer except trusted server connections.
--   4. The six write functions check their own rule, write only their own columns, raise SQLSTATE 42501 when the
--      caller may not write and 55000 when the call-in is complete. save_dl_call_in_notes ignores its
--      new_thank_you argument (kept so Beta's calls still match). save_call_in_area_update no longer touches the
--      parent row when it exists.
--   5. get_zl_call_in_zone_notes: only the zone's ZL and mission managers (was: anyone in the zone).
--   6. New get_call_in_people(level, id, week) returns jsonb with the baptismal-date friends, new members and
--      high potentials of a mission, zone, district or area for a week: every card field, Beta's activity rule
--      as "active", totals and active counts. Access is checked once for the scope with can_view_call_in (as in
--      020), and only reports of areas can_access_area allows are used, so nobody outside the caller's
--      stewardship is listed.
--   7. Hardening: anon loses EXECUTE on the 27 legacy call-in functions (Appsmith and the portal sign in, so
--      they use authenticated); anon and authenticated lose TRUNCATE on the three call-in tables (TRUNCATE
--      skips row-level security and triggers); every call-in function gets search_path "public, pg_temp".
-- Not touched: can_access_area/zone/district/mission and is_mission_manager_for_area (migration 021 changes
-- them), the 020 summaries, the call_in_districts and call_in_area_updates read policies, and every row.
--
-- Apply (back up Beta first; after 020, and before or after 021 - they replace different functions). Run as
-- supabase_admin like 019; the file switches to postgres so every function stays owned by postgres:
--   Get-Content portal-api/migrations/022_callins_parity.sql -Raw |
--     docker exec -i gfm-beta-supabase-db-1 psql -U supabase_admin -d postgres -v ON_ERROR_STOP=1
-- Then run 019 again as a check (it must end with COMMIT):
--   Get-Content portal-api/migrations/019_restrict_public_functions.sql -Raw |
--     docker exec -i gfm-beta-supabase-db-1 psql -U supabase_admin -d postgres -v ON_ERROR_STOP=1
-- The file stops after 10 seconds (lock timeout) instead of making Call-ins wait if an old call-in query holds a
-- lock; run it again later. Safe to run again: only CREATE OR REPLACE, ALTER, REVOKE and GRANT, then a check
-- block that stops (and undoes everything) on any problem. The file is plain ASCII.
-- Rollback: 022_callins_parity_rollback.sql (restores the previous definitions, grants and policy).
BEGIN;
SET LOCAL lock_timeout = '10s';

DO $$
BEGIN
  IF current_user NOT IN ('supabase_admin', 'postgres') THEN
    RAISE EXCEPTION 'Run this file as supabase_admin (see its header), not as %.', current_user;
  END IF;
END $$;
-- Everything below is created and granted by postgres, the owner of the call-in functions and tables.
SET LOCAL ROLE postgres;

-- 1. Leader helpers: a current DL or ZL leadership assignment of the signed-in user (not the account role,
-- never STL).
CREATE OR REPLACE FUNCTION public.is_call_in_district_leader(target_district_id bigint)
RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = public, pg_temp
AS $function$
    SELECT EXISTS (
        SELECT 1 FROM public.user_profiles up
        JOIN public.leadership_assignments la ON la.missionary_id = up.missionary_id
        WHERE up.id = auth.uid() AND up.active
          AND la.role = 'DL' AND la.district_id = target_district_id
          AND la.start_date <= CURRENT_DATE AND (la.end_date IS NULL OR la.end_date >= CURRENT_DATE)
    );
$function$;

CREATE OR REPLACE FUNCTION public.is_call_in_zone_leader(target_zone_id bigint)
RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = public, pg_temp
AS $function$
    SELECT EXISTS (
        SELECT 1 FROM public.user_profiles up
        JOIN public.leadership_assignments la ON la.missionary_id = up.missionary_id
        WHERE up.id = auth.uid() AND up.active
          AND la.role = 'ZL' AND la.zone_id = target_zone_id
          AND la.start_date <= CURRENT_DATE AND (la.end_date IS NULL OR la.end_date >= CURRENT_DATE)
    );
$function$;

-- Who may open a call-in scope: the DL of the district, the ZL of the zone, or a mission manager (the rule of
-- 015: is_mission_manager_for_area on some area of the scope). The mission level is for managers only.
CREATE OR REPLACE FUNCTION public.can_view_call_in(target_level text, target_id bigint)
RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = public, pg_temp
AS $function$
    SELECT CASE target_level
        WHEN 'mission' THEN EXISTS (
            SELECT 1 FROM public.areas a JOIN public.districts d ON d.id = a.district_id
            JOIN public.zones z ON z.id = d.zone_id
            WHERE z.mission_id = target_id AND public.is_mission_manager_for_area(a.id))
        WHEN 'zone' THEN public.is_call_in_zone_leader(target_id) OR EXISTS (
            SELECT 1 FROM public.areas a JOIN public.districts d ON d.id = a.district_id
            WHERE d.zone_id = target_id AND public.is_mission_manager_for_area(a.id))
        WHEN 'district' THEN public.is_call_in_district_leader(target_id)
            OR EXISTS (SELECT 1 FROM public.districts d WHERE d.id = target_id AND public.is_call_in_zone_leader(d.zone_id))
            OR EXISTS (SELECT 1 FROM public.areas a WHERE a.district_id = target_id AND public.is_mission_manager_for_area(a.id))
        WHEN 'area' THEN EXISTS (
            SELECT 1 FROM public.areas a JOIN public.districts d ON d.id = a.district_id
            WHERE a.id = target_id
              AND (public.is_call_in_district_leader(d.id) OR public.is_call_in_zone_leader(d.zone_id)
                   OR public.is_mission_manager_for_area(a.id)))
        ELSE false
    END;
$function$;

-- 2. Who may write which part. The leader check comes first because it is cheap; the manager check is the one
-- 015 used (is_mission_manager_for_area on some area of the district or zone).
CREATE OR REPLACE FUNCTION public.can_edit_dl_call_in(target_district_id bigint)
RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = public, pg_temp
AS $function$
    SELECT public.is_call_in_district_leader(target_district_id)
        OR EXISTS (SELECT 1 FROM public.areas a
                   WHERE a.district_id = target_district_id
                     AND public.is_mission_manager_for_area(a.id));
$function$;

CREATE OR REPLACE FUNCTION public.can_edit_zl_call_in(target_district_id bigint)
RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = public, pg_temp
AS $function$
    SELECT EXISTS (SELECT 1 FROM public.districts d
                   WHERE d.id = target_district_id AND public.is_call_in_zone_leader(d.zone_id))
        OR EXISTS (SELECT 1 FROM public.areas a
                   WHERE a.district_id = target_district_id
                     AND public.is_mission_manager_for_area(a.id));
$function$;

-- Also the read rule for zone notes (see 5 and the call_in_zones policy).
CREATE OR REPLACE FUNCTION public.can_edit_zl_zone_call_in(target_zone_id bigint)
RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = public, pg_temp
AS $function$
    SELECT public.is_call_in_zone_leader(target_zone_id)
        OR EXISTS (SELECT 1 FROM public.areas a
                   JOIN public.districts d ON d.id = a.district_id
                   WHERE d.zone_id = target_zone_id
                     AND public.is_mission_manager_for_area(a.id));
$function$;

-- 3. The row trigger. Trusted server connections (no signed-in user) are let through as before.
-- call_in_districts: the DL part is dl_notes, thank_you (unused, but still only the DL's writers may change it)
-- and the completion; the ZL part is zl_notes.
CREATE OR REPLACE FUNCTION public.guard_call_in_write()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER
SET search_path = public, pg_temp
AS $function$
DECLARE
    v_ok boolean := true;
    v_dl boolean := false;
    v_zl boolean := false;
    v_district_id bigint;
    v_completed timestamptz;
BEGIN
    IF public.portal_planning_trusted_write() THEN
        IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
        RETURN NEW;
    END IF;
    IF TG_TABLE_NAME = 'call_in_districts' THEN
        IF TG_OP = 'UPDATE' AND (NEW.district_id, NEW.reporting_week_id) IS DISTINCT FROM (OLD.district_id, OLD.reporting_week_id) THEN
            RAISE EXCEPTION 'A district call-in cannot be moved to another district or week.' USING ERRCODE = '42501';
        END IF;
        IF TG_OP = 'DELETE' THEN
            -- Removes both leaders' parts.
            v_dl := true; v_zl := true;
            v_district_id := OLD.district_id;
        ELSIF TG_OP = 'INSERT' THEN
            v_dl := NEW.dl_notes IS NOT NULL OR NEW.thank_you IS NOT NULL
                    OR NEW.dl_completed_at IS NOT NULL OR NEW.dl_completed_by IS NOT NULL;
            v_zl := NEW.zl_notes IS NOT NULL;
            v_district_id := NEW.district_id;
        ELSE
            v_dl := (NEW.dl_notes, NEW.thank_you, NEW.dl_completed_at, NEW.dl_completed_by)
                    IS DISTINCT FROM (OLD.dl_notes, OLD.thank_you, OLD.dl_completed_at, OLD.dl_completed_by);
            v_zl := NEW.zl_notes IS DISTINCT FROM OLD.zl_notes;
            v_district_id := NEW.district_id;
            IF OLD.dl_completed_at IS NOT NULL AND NEW.dl_completed_at IS NOT NULL
               AND (NEW.dl_notes, NEW.thank_you) IS DISTINCT FROM (OLD.dl_notes, OLD.thank_you) THEN
                RAISE EXCEPTION 'This call-in is marked complete. Reopen it to change the DL notes or area updates.'
                    USING ERRCODE = '55000';
            END IF;
        END IF;
        IF v_dl OR v_zl THEN
            v_ok := (NOT v_dl OR public.can_edit_dl_call_in(v_district_id))
                    AND (NOT v_zl OR public.can_edit_zl_call_in(v_district_id));
        ELSE
            -- An empty row (the parent an area update needs) or an unchanged one: either leader may write it.
            v_ok := public.can_edit_dl_call_in(v_district_id) OR public.can_edit_zl_call_in(v_district_id);
        END IF;
    ELSIF TG_TABLE_NAME = 'call_in_zones' THEN
        IF TG_OP <> 'INSERT' THEN v_ok := public.can_edit_zl_zone_call_in(OLD.zone_id); END IF;
        IF TG_OP <> 'DELETE' THEN v_ok := coalesce(v_ok, false) AND public.can_edit_zl_zone_call_in(NEW.zone_id); END IF;
    ELSIF TG_TABLE_NAME = 'call_in_area_updates' THEN
        IF TG_OP <> 'INSERT' THEN
            SELECT cid.district_id INTO v_district_id FROM public.call_in_districts cid WHERE cid.id = OLD.district_call_in_id;
            IF TG_OP = 'DELETE' AND v_district_id IS NULL THEN
                -- The district call-in row itself is being deleted (cascade); that delete was checked above.
                RETURN OLD;
            END IF;
            v_ok := public.can_edit_dl_call_in(v_district_id)
                    AND EXISTS (SELECT 1 FROM public.areas WHERE id = OLD.area_id AND district_id = v_district_id);
        END IF;
        IF TG_OP <> 'DELETE' THEN
            SELECT cid.district_id, cid.dl_completed_at INTO v_district_id, v_completed
            FROM public.call_in_districts cid WHERE cid.id = NEW.district_call_in_id;
            IF v_completed IS NOT NULL THEN
                RAISE EXCEPTION 'This call-in is marked complete. Reopen it to change the DL notes or area updates.'
                    USING ERRCODE = '55000';
            END IF;
            v_ok := coalesce(v_ok, false) AND public.can_edit_dl_call_in(v_district_id)
                    AND EXISTS (SELECT 1 FROM public.areas WHERE id = NEW.area_id AND district_id = v_district_id);
        END IF;
    ELSE
        RAISE EXCEPTION 'Unsupported Call-ins table.' USING ERRCODE = '42501';
    END IF;
    IF NOT coalesce(v_ok, false) THEN
        RAISE EXCEPTION 'You can change only the call-in notes of your own stewardship.' USING ERRCODE = '42501';
    END IF;
    IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
    RETURN NEW;
END;
$function$;

-- 4. The write functions (same names, arguments and results as before).
-- new_thank_you is accepted and ignored: there is no thank-you feature, and the stored value stays as it is.
CREATE OR REPLACE FUNCTION public.save_dl_call_in_notes(target_district_id bigint, target_reporting_week_id bigint, new_dl_notes text, new_thank_you text)
RETURNS bigint LANGUAGE plpgsql SECURITY DEFINER
SET search_path = public, pg_temp
AS $function$
DECLARE
    v_call_in_id bigint;
    v_completed timestamptz;
BEGIN
    IF NOT public.can_edit_dl_call_in(target_district_id) THEN
        RAISE EXCEPTION 'You do not have permission to edit this district call-in.' USING ERRCODE = '42501';
    END IF;
    SELECT cid.dl_completed_at INTO v_completed FROM public.call_in_districts cid
    WHERE cid.district_id = target_district_id AND cid.reporting_week_id = target_reporting_week_id
    FOR UPDATE;
    IF v_completed IS NOT NULL THEN
        RAISE EXCEPTION 'This call-in is marked complete. Reopen it to change the DL notes or area updates.'
            USING ERRCODE = '55000';
    END IF;
    INSERT INTO public.call_in_districts (district_id, reporting_week_id, dl_notes)
    VALUES (target_district_id, target_reporting_week_id, new_dl_notes)
    ON CONFLICT (district_id, reporting_week_id) DO UPDATE SET
        dl_notes = EXCLUDED.dl_notes,
        updated_at = now()
    RETURNING id INTO v_call_in_id;
    RETURN v_call_in_id;
END;
$function$;

CREATE OR REPLACE FUNCTION public.save_zl_call_in_notes(target_district_id bigint, target_reporting_week_id bigint, new_zl_notes text)
RETURNS bigint LANGUAGE plpgsql SECURITY DEFINER
SET search_path = public, pg_temp
AS $function$
DECLARE
    v_call_in_id bigint;
BEGIN
    IF NOT public.can_edit_zl_call_in(target_district_id) THEN
        RAISE EXCEPTION 'You do not have permission to edit ZL notes for this district.' USING ERRCODE = '42501';
    END IF;
    INSERT INTO public.call_in_districts (district_id, reporting_week_id, zl_notes)
    VALUES (target_district_id, target_reporting_week_id, new_zl_notes)
    ON CONFLICT (district_id, reporting_week_id) DO UPDATE SET
        zl_notes = EXCLUDED.zl_notes,
        updated_at = now()
    RETURNING id INTO v_call_in_id;
    RETURN v_call_in_id;
END;
$function$;

CREATE OR REPLACE FUNCTION public.save_zl_zone_call_in_notes(target_zone_id bigint, target_reporting_week_id bigint, new_zone_notes text)
RETURNS bigint LANGUAGE plpgsql SECURITY DEFINER
SET search_path = public, pg_temp
AS $function$
DECLARE
    result_id bigint;
BEGIN
    IF NOT public.can_edit_zl_zone_call_in(target_zone_id) THEN
        RAISE EXCEPTION 'You do not have permission to edit this zone Call-in.' USING ERRCODE = '42501';
    END IF;
    INSERT INTO public.call_in_zones (zone_id, reporting_week_id, zone_notes, created_at, updated_at)
    VALUES (target_zone_id, target_reporting_week_id, new_zone_notes, now(), now())
    ON CONFLICT (zone_id, reporting_week_id) DO UPDATE SET
        zone_notes = EXCLUDED.zone_notes,
        updated_at = now()
    RETURNING id INTO result_id;
    RETURN result_id;
END;
$function$;

CREATE OR REPLACE FUNCTION public.save_call_in_area_update(target_district_id bigint, target_reporting_week_id bigint, target_area_id bigint, new_update_text text)
RETURNS bigint LANGUAGE plpgsql SECURITY DEFINER
SET search_path = public, pg_temp
AS $function$
DECLARE
    v_call_in_id bigint;
    v_completed timestamptz;
    v_area_update_id bigint;
BEGIN
    IF NOT public.can_edit_dl_call_in(target_district_id) THEN
        RAISE EXCEPTION 'You do not have permission to edit this district call-in.' USING ERRCODE = '42501';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM public.areas a WHERE a.id = target_area_id AND a.district_id = target_district_id) THEN
        RAISE EXCEPTION 'Area does not belong to this district.' USING ERRCODE = '22023';
    END IF;
    -- The district call-in row is the parent; create it empty when missing, never change it otherwise.
    INSERT INTO public.call_in_districts (district_id, reporting_week_id)
    VALUES (target_district_id, target_reporting_week_id)
    ON CONFLICT (district_id, reporting_week_id) DO NOTHING;
    -- Locked so Complete waits for this save (and the other way round).
    SELECT cid.id, cid.dl_completed_at INTO v_call_in_id, v_completed FROM public.call_in_districts cid
    WHERE cid.district_id = target_district_id AND cid.reporting_week_id = target_reporting_week_id
    FOR UPDATE;
    IF v_completed IS NOT NULL THEN
        RAISE EXCEPTION 'This call-in is marked complete. Reopen it to change the DL notes or area updates.'
            USING ERRCODE = '55000';
    END IF;
    INSERT INTO public.call_in_area_updates (district_call_in_id, area_id, update_text)
    VALUES (v_call_in_id, target_area_id, new_update_text)
    ON CONFLICT (district_call_in_id, area_id) DO UPDATE SET
        update_text = EXCLUDED.update_text,
        updated_at = now()
    RETURNING id INTO v_area_update_id;
    RETURN v_area_update_id;
END;
$function$;

CREATE OR REPLACE FUNCTION public.complete_dl_call_in(target_district_id bigint, target_reporting_week_id bigint)
RETURNS bigint LANGUAGE plpgsql SECURITY DEFINER
SET search_path = public, pg_temp
AS $function$
DECLARE
    result_id bigint;
BEGIN
    IF NOT public.can_edit_dl_call_in(target_district_id) THEN
        RAISE EXCEPTION 'You do not have permission to complete this district Call-in.' USING ERRCODE = '42501';
    END IF;
    INSERT INTO public.call_in_districts (district_id, reporting_week_id, dl_completed_at, dl_completed_by, created_at, updated_at)
    VALUES (target_district_id, target_reporting_week_id, now(), auth.uid(), now(), now())
    ON CONFLICT (district_id, reporting_week_id) DO UPDATE SET
        dl_completed_at = now(),
        dl_completed_by = auth.uid(),
        updated_at = now()
    RETURNING id INTO result_id;
    RETURN result_id;
END;
$function$;

CREATE OR REPLACE FUNCTION public.reopen_dl_call_in(target_district_id bigint, target_reporting_week_id bigint)
RETURNS bigint LANGUAGE plpgsql SECURITY DEFINER
SET search_path = public, pg_temp
AS $function$
DECLARE
    result_id bigint;
BEGIN
    IF NOT public.can_edit_dl_call_in(target_district_id) THEN
        RAISE EXCEPTION 'You do not have permission to reopen this district Call-in.' USING ERRCODE = '42501';
    END IF;
    INSERT INTO public.call_in_districts (district_id, reporting_week_id, dl_completed_at, dl_completed_by, created_at, updated_at)
    VALUES (target_district_id, target_reporting_week_id, NULL, NULL, now(), now())
    ON CONFLICT (district_id, reporting_week_id) DO UPDATE SET
        dl_completed_at = NULL,
        dl_completed_by = NULL,
        updated_at = now()
    RETURNING id INTO result_id;
    RETURN result_id;
END;
$function$;

-- 5. Zone notes: the zone's ZL and mission managers only.
CREATE OR REPLACE FUNCTION public.get_zl_call_in_zone_notes(target_zone_id bigint, target_reporting_week_id bigint)
RETURNS TABLE(zone_id bigint, zone_name text, reporting_week_id bigint, reporting_sunday date, zone_notes text)
LANGUAGE plpgsql STABLE SECURITY DEFINER
SET search_path = public, pg_temp
AS $function$
BEGIN
    IF NOT public.can_edit_zl_zone_call_in(target_zone_id) THEN
        RAISE EXCEPTION 'Zone notes are for the zone leaders of this zone and mission leaders.' USING ERRCODE = '42501';
    END IF;
    RETURN QUERY
    SELECT z.id::bigint, z.name::text, rw.id::bigint, rw.sunday::date, ciz.zone_notes::text
    FROM public.zones z
    JOIN public.reporting_weeks rw ON rw.id = target_reporting_week_id
    LEFT JOIN public.call_in_zones ciz ON ciz.zone_id = z.id AND ciz.reporting_week_id = rw.id
    WHERE z.id = target_zone_id;
END;
$function$;

ALTER POLICY call_in_zones_select ON public.call_in_zones USING (public.can_edit_zl_zone_call_in(zone_id));

-- 6. People of a scope for one week. Access: can_view_call_in once for the scope, then only rows from reports
-- of areas can_access_area allows (asked once per area that has people this week), as in the 020 summaries.
-- The rows are the ones Beta's get_dl/zl_call_in_* functions list (weekly rows linked to a person record; a
-- high potential has no person record). "active" follows Beta's activity lists: a baptismal-date friend at
-- church in at least 2 of the 4 Sundays up to this one; a new member baptized in the last 21 days at church
-- this Sunday, otherwise the same 2-of-4 rule; a high potential at church this Sunday.
CREATE OR REPLACE FUNCTION public.get_call_in_people(target_level text, target_id bigint, target_reporting_week_id bigint)
RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER
SET search_path = public, pg_temp
AS $function$
DECLARE
    v_sunday date;
    v_result jsonb;
BEGIN
    IF target_level IS NULL OR target_level NOT IN ('mission', 'zone', 'district', 'area') THEN
        RAISE EXCEPTION 'Choose a mission, zone, district or area.' USING ERRCODE = '22023';
    END IF;
    SELECT rw.sunday INTO v_sunday FROM public.reporting_weeks rw WHERE rw.id = target_reporting_week_id;
    IF v_sunday IS NULL THEN
        RAISE EXCEPTION 'That reporting week is unavailable.' USING ERRCODE = '22023';
    END IF;
    IF NOT public.can_view_call_in(target_level, target_id) THEN
        RAISE EXCEPTION 'This part of the mission is outside your stewardship.' USING ERRCODE = '42501';
    END IF;

    WITH scope AS MATERIALIZED (
        SELECT a.id AS area_id, a.name AS area_name, d.id AS district_id, d.name AS district_name,
               z.id AS zone_id, z.name AS zone_name
        FROM public.areas a
        JOIN public.districts d ON d.id = a.district_id
        JOIN public.zones z ON z.id = d.zone_id
        WHERE (target_level = 'mission' AND z.mission_id = target_id)
           OR (target_level = 'zone' AND z.id = target_id)
           OR (target_level = 'district' AND d.id = target_id)
           OR (target_level = 'area' AND a.id = target_id)
    ), reports AS MATERIALIZED (
        SELECT war.id AS report_id, war.unit_id, u.name AS unit_name, s.*
        FROM public.weekly_area_reports war
        JOIN scope s ON s.area_id = war.area_id
        LEFT JOIN public.units u ON u.id = war.unit_id
        WHERE war.reporting_week_id = target_reporting_week_id
    ), bd_rows AS MATERIALIZED (
        SELECT r.*, w.id AS row_id, w.baptismal_date_person_id AS person_id, w.display_order,
               coalesce(nullif(btrim(p.display_name), ''),
                        nullif(btrim(coalesce(p.first_name, '') || ' ' || coalesce(p.last_name, '')), '')) AS person_name,
               coalesce(w.finding_source, p.finding_source) AS finding_source,
               w.baptismal_date_set_on, w.current_baptismal_date, w.reading, w.praying, w.at_church_this_sunday,
               w.keeping_commandments, w.member_involvement
        FROM public.weekly_baptismal_date_friends w
        JOIN reports r ON r.report_id = w.weekly_area_report_id
        JOIN public.baptismal_date_people p ON p.id = w.baptismal_date_person_id
    ), nm_rows AS MATERIALIZED (
        SELECT r.*, w.id AS row_id, w.new_member_id AS person_id, w.display_order,
               coalesce(nullif(btrim(nm.display_name), ''),
                        nullif(btrim(coalesce(nm.first_name, '') || ' ' || coalesce(nm.last_name, '')), '')) AS person_name,
               nm.baptism_date, nm.confirmation_date, nm.finding_source,
               w.lessons_actual, w.lessons_goal, w.pmg_lessons_percentage, w.how_are_they_doing, w.discussed_in_gemiko,
               w.gemiko_support_plan, w.next_ordinance, w.at_church_this_sunday, w.has_calling, w.has_aaronic_priesthood,
               w.has_melchizedek_priesthood, w.ministers_to_someone, w.ministered_to_by_someone,
               w.has_active_temple_recommend, w.visited_temple_for_baptisms, w.reading, w.praying, w.member_involvement
        FROM public.weekly_new_members w
        JOIN reports r ON r.report_id = w.weekly_area_report_id
        JOIN public.new_members nm ON nm.id = w.new_member_id
    ), hp_rows AS MATERIALIZED (
        SELECT r.*, w.id AS row_id, w.display_order, w.name AS person_name, w.at_church_this_sunday, w.notes
        FROM public.weekly_high_potential_friends w
        JOIN reports r ON r.report_id = w.weekly_area_report_id
    ), people_areas AS MATERIALIZED (
        SELECT area_id FROM bd_rows UNION SELECT area_id FROM nm_rows UNION SELECT area_id FROM hp_rows
    ), visible AS MATERIALIZED (
        SELECT area_id FROM people_areas WHERE public.can_access_area(area_id)
    ), companions AS MATERIALIZED (
        SELECT v.area_id, string_agg(DISTINCT m.display_name, ', ' ORDER BY m.display_name) AS missionaries
        FROM visible v
        JOIN public.missionary_assignments ma ON ma.area_id = v.area_id
         AND ma.start_date <= v_sunday AND (ma.end_date IS NULL OR ma.end_date >= v_sunday)
        JOIN public.missionaries m ON m.id = ma.missionary_id
        GROUP BY v.area_id
    ), bd AS (
        SELECT b.*, c.missionaries, (
            SELECT count(DISTINCT hr.reporting_week_id) >= 2
            FROM public.weekly_baptismal_date_friends h
            JOIN public.weekly_area_reports hr ON hr.id = h.weekly_area_report_id
            JOIN public.reporting_weeks hw ON hw.id = hr.reporting_week_id
            WHERE h.baptismal_date_person_id = b.person_id AND h.at_church_this_sunday IS TRUE
              AND hw.sunday BETWEEN v_sunday - 21 AND v_sunday
        ) AS active
        FROM bd_rows b JOIN visible v ON v.area_id = b.area_id
        LEFT JOIN companions c ON c.area_id = b.area_id
    ), nm AS (
        SELECT n.*, c.missionaries, CASE
            WHEN n.baptism_date IS NOT NULL AND n.baptism_date > v_sunday - 21 THEN coalesce(n.at_church_this_sunday, false)
            ELSE (
                SELECT count(DISTINCT hr.reporting_week_id) >= 2
                FROM public.weekly_new_members h
                JOIN public.weekly_area_reports hr ON hr.id = h.weekly_area_report_id
                JOIN public.reporting_weeks hw ON hw.id = hr.reporting_week_id
                WHERE h.new_member_id = n.person_id AND h.at_church_this_sunday IS TRUE
                  AND hw.sunday BETWEEN v_sunday - 21 AND v_sunday
            ) END AS active
        FROM nm_rows n JOIN visible v ON v.area_id = n.area_id
        LEFT JOIN companions c ON c.area_id = n.area_id
    ), hp AS (
        SELECT h.*, c.missionaries, coalesce(h.at_church_this_sunday, false) AS active
        FROM hp_rows h JOIN visible v ON v.area_id = h.area_id
        LEFT JOIN companions c ON c.area_id = h.area_id
    )
    SELECT jsonb_build_object(
        'level', target_level, 'id', target_id, 'reporting_week_id', target_reporting_week_id, 'sunday', v_sunday,
        'baptismal_dates', coalesce((SELECT jsonb_agg(jsonb_build_object(
            'id', b.row_id, 'person_id', b.person_id, 'name', b.person_name,
            'area_id', b.area_id, 'area_name', b.area_name, 'unit_id', b.unit_id, 'unit_name', b.unit_name,
            'district_id', b.district_id, 'district_name', b.district_name, 'zone_id', b.zone_id, 'zone_name', b.zone_name,
            'missionaries', b.missionaries, 'display_order', b.display_order, 'finding_source', b.finding_source,
            'date_set', b.baptismal_date_set_on, 'baptismal_date', b.current_baptismal_date,
            'days_until', b.current_baptismal_date - v_sunday,
            'weeks_until', round((b.current_baptismal_date - v_sunday)::numeric / 7.0, 1),
            'reading', b.reading, 'praying', b.praying, 'at_church', b.at_church_this_sunday,
            'keeping_commandments', b.keeping_commandments, 'member_involvement', b.member_involvement,
            'active', b.active
        ) ORDER BY b.zone_name, b.district_name, b.area_name, b.display_order, b.person_name, b.row_id) FROM bd b), '[]'::jsonb),
        'new_members', coalesce((SELECT jsonb_agg(jsonb_build_object(
            'id', n.row_id, 'person_id', n.person_id, 'name', n.person_name,
            'area_id', n.area_id, 'area_name', n.area_name, 'unit_id', n.unit_id, 'unit_name', n.unit_name,
            'district_id', n.district_id, 'district_name', n.district_name, 'zone_id', n.zone_id, 'zone_name', n.zone_name,
            'missionaries', n.missionaries, 'display_order', n.display_order,
            'baptism_date', n.baptism_date, 'confirmation_date', n.confirmation_date, 'finding_source', n.finding_source,
            'lessons_actual', n.lessons_actual, 'lessons_goal', n.lessons_goal, 'pmg_lessons_percentage', n.pmg_lessons_percentage,
            'how_are_they_doing', n.how_are_they_doing, 'discussed_in_gemiko', n.discussed_in_gemiko,
            'gemiko_support_plan', n.gemiko_support_plan, 'next_ordinance', n.next_ordinance, 'at_church', n.at_church_this_sunday,
            'has_calling', n.has_calling, 'has_aaronic_priesthood', n.has_aaronic_priesthood,
            'has_melchizedek_priesthood', n.has_melchizedek_priesthood, 'ministers_to_someone', n.ministers_to_someone,
            'ministered_to_by_someone', n.ministered_to_by_someone, 'has_active_temple_recommend', n.has_active_temple_recommend,
            'visited_temple_for_baptisms', n.visited_temple_for_baptisms, 'reading', n.reading, 'praying', n.praying,
            'member_involvement', n.member_involvement, 'active', n.active
        ) ORDER BY n.zone_name, n.district_name, n.area_name, n.display_order, n.person_name, n.row_id) FROM nm n), '[]'::jsonb),
        'high_potentials', coalesce((SELECT jsonb_agg(jsonb_build_object(
            'id', h.row_id, 'name', h.person_name,
            'area_id', h.area_id, 'area_name', h.area_name, 'unit_id', h.unit_id, 'unit_name', h.unit_name,
            'district_id', h.district_id, 'district_name', h.district_name, 'zone_id', h.zone_id, 'zone_name', h.zone_name,
            'missionaries', h.missionaries, 'display_order', h.display_order,
            'at_church', h.at_church_this_sunday, 'notes', h.notes, 'active', h.active
        ) ORDER BY h.zone_name, h.district_name, h.area_name, h.display_order, h.person_name, h.row_id) FROM hp h), '[]'::jsonb),
        'counts', jsonb_build_object(
            'baptismal_dates', (SELECT jsonb_build_object('total', count(*), 'active', count(*) FILTER (WHERE active)) FROM bd),
            'new_members', (SELECT jsonb_build_object('total', count(*), 'active', count(*) FILTER (WHERE active)) FROM nm),
            'high_potentials', (SELECT jsonb_build_object('total', count(*), 'active', count(*) FILTER (WHERE active)) FROM hp))
    ) INTO v_result;
    RETURN v_result;
END;
$function$;

-- Rights of the new and replaced functions: signed-in users and service_role by name, never PUBLIC or anon.
REVOKE ALL ON FUNCTION
    public.is_call_in_district_leader(bigint), public.is_call_in_zone_leader(bigint), public.can_view_call_in(text, bigint),
    public.can_edit_dl_call_in(bigint), public.can_edit_zl_call_in(bigint), public.can_edit_zl_zone_call_in(bigint),
    public.guard_call_in_write(),
    public.save_dl_call_in_notes(bigint, bigint, text, text), public.save_zl_call_in_notes(bigint, bigint, text),
    public.save_zl_zone_call_in_notes(bigint, bigint, text), public.save_call_in_area_update(bigint, bigint, bigint, text),
    public.complete_dl_call_in(bigint, bigint), public.reopen_dl_call_in(bigint, bigint),
    public.get_zl_call_in_zone_notes(bigint, bigint), public.get_call_in_people(text, bigint, bigint)
FROM PUBLIC, anon;
GRANT EXECUTE ON FUNCTION
    public.is_call_in_district_leader(bigint), public.is_call_in_zone_leader(bigint), public.can_view_call_in(text, bigint),
    public.can_edit_dl_call_in(bigint), public.can_edit_zl_call_in(bigint), public.can_edit_zl_zone_call_in(bigint),
    public.guard_call_in_write(),
    public.save_dl_call_in_notes(bigint, bigint, text, text), public.save_zl_call_in_notes(bigint, bigint, text),
    public.save_zl_zone_call_in_notes(bigint, bigint, text), public.save_call_in_area_update(bigint, bigint, bigint, text),
    public.complete_dl_call_in(bigint, bigint), public.reopen_dl_call_in(bigint, bigint),
    public.get_zl_call_in_zone_notes(bigint, bigint), public.get_call_in_people(text, bigint, bigint)
TO authenticated, service_role;

-- 7. Hardening. anon: no legacy call-in function (all need a signed-in user anyway).
REVOKE EXECUTE ON FUNCTION
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
FROM PUBLIC, anon;
-- The 20 getters above keep their code; only the fixed search_path gains pg_temp (the replaced ones have it).
ALTER FUNCTION public.get_dl_call_in_baptismal_dates(bigint, bigint) SET search_path = public, pg_temp;
ALTER FUNCTION public.get_dl_call_in_bd_activity(bigint, bigint) SET search_path = public, pg_temp;
ALTER FUNCTION public.get_dl_call_in_high_potentials(bigint, bigint) SET search_path = public, pg_temp;
ALTER FUNCTION public.get_dl_call_in_hp_activity(bigint, bigint) SET search_path = public, pg_temp;
ALTER FUNCTION public.get_dl_call_in_new_members(bigint, bigint) SET search_path = public, pg_temp;
ALTER FUNCTION public.get_dl_call_in_nm_activity(bigint, bigint) SET search_path = public, pg_temp;
ALTER FUNCTION public.get_dl_call_in_summary(bigint, bigint) SET search_path = public, pg_temp;
ALTER FUNCTION public.get_dl_call_in_ward_coordination(bigint, bigint) SET search_path = public, pg_temp;
ALTER FUNCTION public.get_mission_call_in_bd_activity(bigint, bigint) SET search_path = public, pg_temp;
ALTER FUNCTION public.get_mission_call_in_hp_activity(bigint, bigint) SET search_path = public, pg_temp;
ALTER FUNCTION public.get_mission_call_in_nm_activity(bigint, bigint) SET search_path = public, pg_temp;
ALTER FUNCTION public.get_mission_call_in_summary(bigint, bigint) SET search_path = public, pg_temp;
ALTER FUNCTION public.get_zl_call_in_area_updates(bigint, bigint) SET search_path = public, pg_temp;
ALTER FUNCTION public.get_zl_call_in_baptismal_dates(bigint, bigint) SET search_path = public, pg_temp;
ALTER FUNCTION public.get_zl_call_in_bd_activity(bigint, bigint) SET search_path = public, pg_temp;
ALTER FUNCTION public.get_zl_call_in_high_potentials(bigint, bigint) SET search_path = public, pg_temp;
ALTER FUNCTION public.get_zl_call_in_hp_activity(bigint, bigint) SET search_path = public, pg_temp;
ALTER FUNCTION public.get_zl_call_in_new_members(bigint, bigint) SET search_path = public, pg_temp;
ALTER FUNCTION public.get_zl_call_in_nm_activity(bigint, bigint) SET search_path = public, pg_temp;
ALTER FUNCTION public.get_zl_call_in_summary(bigint, bigint) SET search_path = public, pg_temp;
-- TRUNCATE skips row-level security and the write guard; nobody signed in needs it.
REVOKE TRUNCATE ON public.call_in_districts, public.call_in_zones, public.call_in_area_updates FROM anon, authenticated;

-- Check: stops (and undoes the whole file) on any problem.
DO $$
DECLARE
  found text;
BEGIN
  -- Every call-in function: owned by postgres, fixed search_path with pg_temp, never PUBLIC or anon,
  -- always authenticated and service_role.
  SELECT string_agg(p.oid::regprocedure::text, ', ') INTO found
  FROM pg_proc p
  WHERE p.pronamespace = 'public'::regnamespace
    AND (p.proname LIKE '%call_in%')
    AND p.prosecdef
    AND (pg_get_userbyid(p.proowner) <> 'postgres'
         OR NOT coalesce(p.proconfig, '{}') @> ARRAY['search_path=public, pg_temp']
         OR has_function_privilege('public', p.oid, 'EXECUTE') OR has_function_privilege('anon', p.oid, 'EXECUTE')
         OR NOT has_function_privilege('authenticated', p.oid, 'EXECUTE')
         OR NOT has_function_privilege('service_role', p.oid, 'EXECUTE'));
  IF found IS NOT NULL THEN
    RAISE EXCEPTION 'Unexpected owner, search_path or EXECUTE rights on: %', found;
  END IF;
  IF (SELECT count(*) FROM pg_proc p WHERE p.pronamespace = 'public'::regnamespace AND p.prosecdef
        AND p.proname IN ('get_call_in_people', 'is_call_in_district_leader', 'is_call_in_zone_leader', 'can_view_call_in')) <> 4 THEN
    RAISE EXCEPTION 'The new call-in functions are missing.';
  END IF;
  -- The leader helpers name exactly one leadership role each (STL has no part in Call-ins).
  IF position('''STL''' IN pg_get_functiondef('public.is_call_in_zone_leader(bigint)'::regprocedure)) > 0
     OR position('''STL''' IN pg_get_functiondef('public.is_call_in_district_leader(bigint)'::regprocedure)) > 0 THEN
    RAISE EXCEPTION 'The Call-ins leader helpers must not include STL.';
  END IF;
  SELECT string_agg(format('%s (%s)', c.oid::regclass, r), ', ') INTO found
  FROM pg_class c CROSS JOIN unnest(ARRAY['anon', 'authenticated']) r
  WHERE c.oid IN ('public.call_in_districts'::regclass, 'public.call_in_zones'::regclass, 'public.call_in_area_updates'::regclass)
    AND has_table_privilege(r, c.oid, 'TRUNCATE');
  IF found IS NOT NULL THEN
    RAISE EXCEPTION 'TRUNCATE is still granted on: %', found;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE schemaname = 'public' AND tablename = 'call_in_zones'
                   AND policyname = 'call_in_zones_select' AND qual LIKE '%can_edit_zl_zone_call_in%') THEN
    RAISE EXCEPTION 'The call_in_zones read policy was not narrowed.';
  END IF;
  IF (SELECT count(*) FROM pg_trigger WHERE NOT tgisinternal AND tgfoid = 'public.guard_call_in_write()'::regprocedure) <> 3 THEN
    RAISE EXCEPTION 'The three call-in write guards (015) are missing.';
  END IF;
END $$;

NOTIFY pgrst, 'reload schema';
COMMIT;

-- Verify (read-only, after applying): run 019 again (see Apply). Then, as a DL, ZL and AP (replace the ids; the
-- command only reads and rolls back), each returns true for their own part and false for the others:
--   docker exec gfm-beta-supabase-db-1 psql -U postgres -d postgres -c 'BEGIN READ ONLY' -c "SELECT set_config('request.jwt.claims', json_build_object('sub','<user id>','role','authenticated')::text, true)" -c 'SET LOCAL ROLE authenticated' -c 'SELECT public.can_edit_dl_call_in(<district id>) AS dl, public.can_edit_zl_call_in(<district id>) AS zl, public.can_edit_zl_zone_call_in(<zone id>) AS zone_notes' -c 'ROLLBACK'
-- and the people of the latest week come back (counts only):
--   ... -c "SELECT public.get_call_in_people('district', <district id>, (SELECT id FROM public.reporting_weeks WHERE sunday <= public.current_reporting_sunday() ORDER BY sunday DESC LIMIT 1))->'counts'" ...
