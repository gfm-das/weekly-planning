-- Mission managers edit Call-ins; district/zone leaders have read-only access.
-- Function signatures and existing Call-ins workflow remain unchanged.
BEGIN;

CREATE OR REPLACE FUNCTION public.can_edit_dl_call_in(target_district_id bigint)
RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = public, pg_temp
AS $function$
    SELECT EXISTS (SELECT 1 FROM public.areas a
                  WHERE a.district_id = target_district_id
                    AND public.is_mission_manager_for_area(a.id));
$function$;

CREATE OR REPLACE FUNCTION public.can_edit_zl_call_in(target_district_id bigint)
RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = public, pg_temp
AS $function$
    SELECT public.can_edit_dl_call_in(target_district_id);
$function$;

CREATE OR REPLACE FUNCTION public.can_edit_zl_zone_call_in(target_zone_id bigint)
RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = public, pg_temp
AS $function$
    SELECT EXISTS (SELECT 1 FROM public.areas a
                  JOIN public.districts d ON d.id = a.district_id
                  WHERE d.zone_id = target_zone_id
                    AND public.is_mission_manager_for_area(a.id));
$function$;

-- Existing tables expose SELECT policies only. These guards also enforce the
-- scope on SECURITY DEFINER RPC writes and any future direct write policy.
CREATE OR REPLACE FUNCTION public.guard_call_in_write()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER
SET search_path = public, pg_temp
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
$function$;

DROP TRIGGER IF EXISTS call_in_districts_write_guard ON public.call_in_districts;
CREATE TRIGGER call_in_districts_write_guard BEFORE INSERT OR UPDATE OR DELETE ON public.call_in_districts
FOR EACH ROW EXECUTE FUNCTION public.guard_call_in_write();
DROP TRIGGER IF EXISTS call_in_zones_write_guard ON public.call_in_zones;
CREATE TRIGGER call_in_zones_write_guard BEFORE INSERT OR UPDATE OR DELETE ON public.call_in_zones
FOR EACH ROW EXECUTE FUNCTION public.guard_call_in_write();
DROP TRIGGER IF EXISTS call_in_area_updates_write_guard ON public.call_in_area_updates;
CREATE TRIGGER call_in_area_updates_write_guard BEFORE INSERT OR UPDATE OR DELETE ON public.call_in_area_updates
FOR EACH ROW EXECUTE FUNCTION public.guard_call_in_write();

REVOKE ALL ON FUNCTION public.can_edit_dl_call_in(bigint),public.can_edit_zl_call_in(bigint),public.can_edit_zl_zone_call_in(bigint),public.guard_call_in_write() FROM PUBLIC,anon;
GRANT EXECUTE ON FUNCTION public.can_edit_dl_call_in(bigint),public.can_edit_zl_call_in(bigint),public.can_edit_zl_zone_call_in(bigint) TO authenticated,service_role,postgres;

NOTIFY pgrst, 'reload schema';
COMMIT;
