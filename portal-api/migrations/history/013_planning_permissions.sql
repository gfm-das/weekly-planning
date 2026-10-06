-- Beta planning permissions. Shared reports remain keyed by area/unit/week.
-- Importer writes made as postgres/service_role without a user identity retain
-- their historical-import behavior. Authenticated portal/Appsmith writes do not.
BEGIN;

CREATE OR REPLACE FUNCTION public.is_mission_manager_for_area(target_area_id bigint)
RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = public, pg_temp
AS $function$
    SELECT EXISTS (
        SELECT 1 FROM public.user_profiles up
        JOIN public.areas target ON target.id = target_area_id
        JOIN public.districts td ON td.id = target.district_id
        JOIN public.zones tz ON tz.id = td.zone_id
        WHERE up.id = auth.uid() AND up.active
          AND (up.app_role IN ('AP','PRESIDENT','DATA_ADMIN') OR EXISTS (
              SELECT 1 FROM public.leadership_assignments effective_ap
              LEFT JOIN public.districts ap_district ON ap_district.id = effective_ap.district_id
              LEFT JOIN public.zones ap_zone ON ap_zone.id = coalesce(effective_ap.zone_id, ap_district.zone_id)
              WHERE effective_ap.missionary_id = up.missionary_id
                AND effective_ap.role = 'AP'
                AND effective_ap.start_date <= CURRENT_DATE
                AND (effective_ap.end_date IS NULL OR effective_ap.end_date >= CURRENT_DATE)
                AND coalesce(effective_ap.mission_id, ap_zone.mission_id) = tz.mission_id
          ))
          AND (
              EXISTS (
                  SELECT 1 FROM public.missionary_assignments ma
                  JOIN public.areas a ON a.id = ma.area_id
                  JOIN public.districts d ON d.id = a.district_id
                  JOIN public.zones z ON z.id = d.zone_id
                  WHERE ma.missionary_id = up.missionary_id
                    AND ma.start_date <= CURRENT_DATE
                    AND (ma.end_date IS NULL OR ma.end_date >= CURRENT_DATE)
                    AND z.mission_id = tz.mission_id
              )
              OR EXISTS (
                  SELECT 1 FROM public.leadership_assignments la
                  LEFT JOIN public.districts ld ON ld.id = la.district_id
                  LEFT JOIN public.zones lz ON lz.id = coalesce(la.zone_id, ld.zone_id)
                  WHERE la.missionary_id = up.missionary_id
                    AND la.start_date <= CURRENT_DATE
                    AND (la.end_date IS NULL OR la.end_date >= CURRENT_DATE)
                    AND coalesce(la.mission_id, lz.mission_id) = tz.mission_id
              )
          )
    );
$function$;

CREATE OR REPLACE FUNCTION public.can_access_area(target_area_id bigint)
RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = public, pg_temp
AS $function$
    SELECT public.is_mission_manager_for_area(target_area_id) OR EXISTS (
        SELECT 1 FROM public.user_profiles up
        JOIN public.areas a ON a.id = target_area_id
        JOIN public.districts d ON d.id = a.district_id
        JOIN public.zones z ON z.id = d.zone_id
        WHERE up.id = auth.uid() AND up.active
          AND (
              EXISTS (
                  SELECT 1 FROM public.missionary_assignments ma
                  WHERE ma.missionary_id = up.missionary_id AND ma.area_id = target_area_id
                    AND ma.start_date <= CURRENT_DATE
                    AND (ma.end_date IS NULL OR ma.end_date >= CURRENT_DATE)
              )
              OR EXISTS (
                  SELECT 1 FROM public.leadership_assignments la
                  WHERE la.missionary_id = up.missionary_id
                    AND la.start_date <= CURRENT_DATE
                    AND (la.end_date IS NULL OR la.end_date >= CURRENT_DATE)
                    AND ((la.role = 'DL' AND la.district_id = d.id)
                         OR (la.role IN ('ZL','STL') AND la.zone_id = z.id))
              )
          )
    );
$function$;

CREATE OR REPLACE FUNCTION public.can_edit_planning_area(target_area_id bigint)
RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = public, pg_temp
AS $function$
    SELECT public.is_mission_manager_for_area(target_area_id)
        OR public.is_current_user_area(target_area_id);
$function$;

CREATE OR REPLACE FUNCTION public.can_unlock_planning_area(target_area_id bigint)
RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = public, pg_temp
AS $function$
    SELECT public.is_mission_manager_for_area(target_area_id) OR EXISTS (
        SELECT 1 FROM public.user_profiles up
        JOIN public.areas a ON a.id = target_area_id
        JOIN public.districts d ON d.id = a.district_id
        JOIN public.zones z ON z.id = d.zone_id
        JOIN public.leadership_assignments la ON la.missionary_id = up.missionary_id
        WHERE up.id = auth.uid() AND up.active
          AND la.start_date <= CURRENT_DATE
          AND (la.end_date IS NULL OR la.end_date >= CURRENT_DATE)
          AND ((la.role = 'DL' AND la.district_id = d.id)
               OR (la.role = 'ZL' AND la.zone_id = z.id))
    );
$function$;

CREATE OR REPLACE FUNCTION public.can_edit_planning_report(target_report_id bigint)
RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = public, pg_temp
AS $function$
    SELECT EXISTS (
        SELECT 1 FROM public.weekly_area_reports war
        WHERE war.id = target_report_id AND war.status = 'DRAFT'
          AND public.can_edit_planning_area(war.area_id)
    );
$function$;

CREATE OR REPLACE FUNCTION public.portal_planning_trusted_write()
RETURNS boolean LANGUAGE sql STABLE
SET search_path = public, pg_temp
AS $function$
    SELECT auth.uid() IS NULL
       AND coalesce(current_setting('role', true),'none') NOT IN ('authenticated','anon')
       AND (session_user IN ('postgres','supabase_admin','service_role')
            OR coalesce(nullif(current_setting('request.jwt.claims', true),'')::jsonb ->> 'role','') = 'service_role');
$function$;

CREATE OR REPLACE FUNCTION public.guard_shared_planning_report()
RETURNS trigger LANGUAGE plpgsql
SET search_path = public, pg_temp
AS $function$
DECLARE
    v_content_changed boolean;
BEGIN
    IF public.portal_planning_trusted_write() THEN
        IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
        RETURN NEW;
    END IF;
    IF auth.uid() IS NULL THEN
        RAISE EXCEPTION 'Sign in to edit Weekly Planning.' USING ERRCODE = '42501';
    END IF;
    IF TG_OP = 'INSERT' THEN
        IF NOT public.can_edit_planning_area(NEW.area_id) OR NEW.status <> 'DRAFT'
           OR NEW.submitted_by IS DISTINCT FROM auth.uid() OR NEW.submitted_at IS NOT NULL THEN
            RAISE EXCEPTION 'A new plan must be an authorized companionship draft.' USING ERRCODE = '42501';
        END IF;
        RETURN NEW;
    END IF;
    IF TG_OP = 'DELETE' THEN
        IF OLD.status <> 'DRAFT' OR NOT public.can_edit_planning_area(OLD.area_id) THEN
            RAISE EXCEPTION 'A submitted plan must be unlocked before it can be changed.' USING ERRCODE = '42501';
        END IF;
        RETURN OLD;
    END IF;
    IF NEW.id IS DISTINCT FROM OLD.id OR NEW.area_id IS DISTINCT FROM OLD.area_id
       OR NEW.unit_id IS DISTINCT FROM OLD.unit_id
       OR NEW.reporting_week_id IS DISTINCT FROM OLD.reporting_week_id THEN
        RAISE EXCEPTION 'A plan cannot be moved to another area, unit, or week.' USING ERRCODE = '42501';
    END IF;
    v_content_changed := (to_jsonb(NEW) - ARRAY['status','submitted_by','submitted_at','updated_at'])
        IS DISTINCT FROM (to_jsonb(OLD) - ARRAY['status','submitted_by','submitted_at','updated_at']);
    IF OLD.status = 'DRAFT' THEN
        IF NOT public.can_edit_planning_area(OLD.area_id) THEN
            RAISE EXCEPTION 'You may read this area''s plan but cannot edit it.' USING ERRCODE = '42501';
        END IF;
        IF NEW.status = 'SUBMITTED' THEN
            IF NEW.submitted_by IS DISTINCT FROM auth.uid() OR NEW.submitted_at IS NULL THEN
                RAISE EXCEPTION 'Submission must record the submitting missionary and time.' USING ERRCODE = '42501';
            END IF;
        ELSIF NEW.status <> 'DRAFT' THEN
            RAISE EXCEPTION 'Submit the plan before it can be locked.' USING ERRCODE = '42501';
        END IF;
    ELSIF NEW.status = 'DRAFT' THEN
        IF NOT public.can_unlock_planning_area(OLD.area_id)
           OR (OLD.status = 'LOCKED' AND NOT public.is_mission_manager_for_area(OLD.area_id))
           OR v_content_changed OR NEW.submitted_by IS NOT NULL OR NEW.submitted_at IS NOT NULL THEN
            RAISE EXCEPTION 'A leader must unlock this plan before it can be edited.' USING ERRCODE = '42501';
        END IF;
    ELSIF OLD.status = 'SUBMITTED' AND NEW.status = 'LOCKED' THEN
        IF NOT public.is_mission_manager_for_area(OLD.area_id) OR v_content_changed
           OR NEW.submitted_by IS DISTINCT FROM OLD.submitted_by
           OR NEW.submitted_at IS DISTINCT FROM OLD.submitted_at THEN
            RAISE EXCEPTION 'Only mission leadership may lock an unchanged submitted plan.' USING ERRCODE = '42501';
        END IF;
    ELSIF NEW.status IS DISTINCT FROM OLD.status OR v_content_changed
       OR NEW.submitted_by IS DISTINCT FROM OLD.submitted_by
       OR NEW.submitted_at IS DISTINCT FROM OLD.submitted_at THEN
        RAISE EXCEPTION 'A submitted plan must be unlocked before it can be edited.' USING ERRCODE = '42501';
    END IF;
    NEW.updated_at := now();
    RETURN NEW;
END;
$function$;

CREATE OR REPLACE FUNCTION public.guard_shared_planning_child()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER
SET search_path = public, pg_temp
AS $function$
DECLARE
    v_report_id bigint;
    v_area_id bigint;
    v_status text;
BEGIN
    IF public.portal_planning_trusted_write() THEN
        IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
        RETURN NEW;
    END IF;
    IF TG_OP = 'UPDATE' AND NEW.weekly_area_report_id IS DISTINCT FROM OLD.weekly_area_report_id THEN
        RAISE EXCEPTION 'An answer cannot be moved to another plan.' USING ERRCODE = '42501';
    END IF;
    v_report_id := CASE WHEN TG_OP = 'DELETE' THEN OLD.weekly_area_report_id ELSE NEW.weekly_area_report_id END;
    -- Serializes answer edits with submission and leader unlock.
    SELECT war.area_id, war.status INTO v_area_id, v_status
    FROM public.weekly_area_reports war WHERE war.id = v_report_id FOR UPDATE;
    IF v_area_id IS NULL OR v_status <> 'DRAFT' OR NOT public.can_edit_planning_area(v_area_id) THEN
        RAISE EXCEPTION 'This plan must be an authorized draft before its answers can be edited.' USING ERRCODE = '42501';
    END IF;
    IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
    NEW.updated_at := now();
    RETURN NEW;
END;
$function$;

DROP TRIGGER IF EXISTS portal_guard_shared_report ON public.weekly_area_reports;
CREATE TRIGGER portal_guard_shared_report BEFORE INSERT OR UPDATE OR DELETE
ON public.weekly_area_reports FOR EACH ROW EXECUTE FUNCTION public.guard_shared_planning_report();

DO $block$
DECLARE
    v_table text;
    v_policy record;
BEGIN
    FOR v_table IN SELECT unnest(ARRAY['weekly_area_reports','weekly_planning_answers',
        'weekly_baptismal_date_friends','weekly_new_members','weekly_high_potential_friends']) LOOP
        FOR v_policy IN SELECT policyname FROM pg_policies
            WHERE schemaname = 'public' AND tablename = v_table AND cmd IN ('INSERT','UPDATE','DELETE') LOOP
            EXECUTE format('DROP POLICY %I ON public.%I', v_policy.policyname, v_table);
        END LOOP;
        IF v_table = 'weekly_area_reports' THEN
            EXECUTE format('CREATE POLICY portal_planning_insert ON public.%I FOR INSERT TO authenticated WITH CHECK (public.can_edit_planning_area(area_id) AND status = ''DRAFT'' AND submitted_by = auth.uid())', v_table);
            EXECUTE format('CREATE POLICY portal_planning_update ON public.%I FOR UPDATE TO authenticated USING (public.can_edit_planning_area(area_id) OR public.can_unlock_planning_area(area_id)) WITH CHECK (public.can_edit_planning_area(area_id) OR public.can_unlock_planning_area(area_id))', v_table);
        ELSE
            EXECUTE format('DROP TRIGGER IF EXISTS portal_guard_shared_child ON public.%I', v_table);
            EXECUTE format('CREATE TRIGGER portal_guard_shared_child BEFORE INSERT OR UPDATE OR DELETE ON public.%I FOR EACH ROW EXECUTE FUNCTION public.guard_shared_planning_child()', v_table);
            EXECUTE format('CREATE POLICY portal_planning_insert ON public.%I FOR INSERT TO authenticated WITH CHECK (public.can_edit_planning_report(weekly_area_report_id))', v_table);
            EXECUTE format('CREATE POLICY portal_planning_update ON public.%I FOR UPDATE TO authenticated USING (public.can_edit_planning_report(weekly_area_report_id)) WITH CHECK (public.can_edit_planning_report(weekly_area_report_id))', v_table);
            EXECUTE format('CREATE POLICY portal_planning_delete ON public.%I FOR DELETE TO authenticated USING (public.can_edit_planning_report(weekly_area_report_id))', v_table);
        END IF;
    END LOOP;
END;
$block$;

CREATE OR REPLACE FUNCTION public.unsubmit_weekly_report(target_report_id bigint)
RETURNS TABLE(weekly_report_id bigint, status text, submitted_by uuid, submitted_at timestamptz)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp
AS $function$
DECLARE v_area_id bigint; v_status text;
BEGIN
    SELECT war.area_id, war.status INTO v_area_id, v_status
    FROM public.weekly_area_reports war WHERE war.id = target_report_id FOR UPDATE;
    IF v_area_id IS NULL OR NOT public.can_unlock_planning_area(v_area_id) THEN
        RAISE EXCEPTION 'A leader within this stewardship must unlock this plan.' USING ERRCODE = '42501';
    END IF;
    IF v_status <> 'SUBMITTED' THEN
        RAISE EXCEPTION 'Only a submitted plan can be reopened.' USING ERRCODE = '22023';
    END IF;
    RETURN QUERY UPDATE public.weekly_area_reports war
    SET status = 'DRAFT', submitted_by = NULL, submitted_at = NULL, updated_at = now()
    WHERE war.id = target_report_id
    RETURNING war.id, war.status, war.submitted_by, war.submitted_at;
END;
$function$;

CREATE OR REPLACE FUNCTION public.reopen_weekly_report(target_report_id bigint)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp
AS $function$
DECLARE v_area_id bigint; v_status text;
BEGIN
    SELECT war.area_id, war.status INTO v_area_id, v_status
    FROM public.weekly_area_reports war WHERE war.id = target_report_id FOR UPDATE;
    IF v_area_id IS NULL OR NOT public.can_unlock_planning_area(v_area_id)
       OR (v_status = 'LOCKED' AND NOT public.is_mission_manager_for_area(v_area_id)) THEN
        RAISE EXCEPTION 'A leader within this stewardship must unlock this plan.' USING ERRCODE = '42501';
    END IF;
    IF v_status NOT IN ('SUBMITTED','LOCKED') THEN
        RAISE EXCEPTION 'Only a submitted or locked plan can be reopened.' USING ERRCODE = '22023';
    END IF;
    UPDATE public.weekly_area_reports war
    SET status = 'DRAFT', submitted_by = NULL, submitted_at = NULL, updated_at = now()
    WHERE war.id = target_report_id;
END;
$function$;

-- Opening an existing submitted report must not insert carried-forward people.
CREATE OR REPLACE FUNCTION public.start_current_weekly_report(target_unit_id bigint)
RETURNS bigint LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp
AS $function$
DECLARE
    v_area_id bigint; v_week_id bigint; v_report_id bigint; v_status text;
BEGIN
    IF target_unit_id IS NULL THEN RAISE EXCEPTION 'A unit must be selected.'; END IF;
    IF NOT public.can_current_user_report_for_unit(target_unit_id) THEN
        RAISE EXCEPTION 'You do not have access to this unit.' USING ERRCODE = '42501';
    END IF;
    v_area_id := public.current_user_area_id();
    IF v_area_id IS NULL THEN RAISE EXCEPTION 'No current area assignment found for this user.'; END IF;
    v_week_id := public.ensure_reporting_week(public.current_reporting_sunday());
    SELECT war.id, war.status INTO v_report_id, v_status
    FROM public.weekly_area_reports war
    WHERE war.area_id = v_area_id AND war.unit_id = target_unit_id AND war.reporting_week_id = v_week_id;
    IF v_report_id IS NULL THEN
        INSERT INTO public.weekly_area_reports (area_id, unit_id, reporting_week_id, status, submitted_by)
        VALUES (v_area_id, target_unit_id, v_week_id, 'DRAFT', auth.uid())
        RETURNING id, status INTO v_report_id, v_status;
    END IF;
    IF v_status = 'DRAFT' THEN
        INSERT INTO public.weekly_new_members (weekly_area_report_id, new_member_id, display_order)
        SELECT v_report_id, nm.id, row_number() OVER (ORDER BY nm.display_name,nm.id)::integer
        FROM public.current_new_members nm
        WHERE nm.area_id = v_area_id AND nm.unit_id = target_unit_id AND nm.follow_up_status = 'current'
        ON CONFLICT (weekly_area_report_id,new_member_id) WHERE new_member_id IS NOT NULL DO NOTHING;
        INSERT INTO public.weekly_baptismal_date_friends (weekly_area_report_id,baptismal_date_person_id,display_order)
        SELECT v_report_id, bdp.id, row_number() OVER (ORDER BY bdp.display_name,bdp.id)::integer
        FROM public.current_baptismal_date_people bdp
        JOIN public.baptismal_date_person_area_assignments bdpa
          ON bdpa.baptismal_date_person_id = bdp.id AND bdpa.end_date IS NULL
        WHERE bdp.area_id = v_area_id AND bdpa.unit_id = target_unit_id
        ON CONFLICT (weekly_area_report_id,baptismal_date_person_id) WHERE baptismal_date_person_id IS NOT NULL DO NOTHING;
    END IF;
    RETURN v_report_id;
END;
$function$;

REVOKE EXECUTE ON FUNCTION public.is_mission_manager_for_area(bigint),
    public.can_access_area(bigint), public.can_edit_planning_area(bigint),
    public.can_unlock_planning_area(bigint), public.can_edit_planning_report(bigint),
    public.portal_planning_trusted_write(), public.guard_shared_planning_report(),
    public.guard_shared_planning_child(), public.unsubmit_weekly_report(bigint),
    public.reopen_weekly_report(bigint), public.start_current_weekly_report(bigint)
FROM PUBLIC, anon;
GRANT EXECUTE ON FUNCTION public.is_mission_manager_for_area(bigint),
    public.can_access_area(bigint), public.can_edit_planning_area(bigint),
    public.can_unlock_planning_area(bigint), public.can_edit_planning_report(bigint),
    public.portal_planning_trusted_write(), public.guard_shared_planning_report(),
    public.guard_shared_planning_child(), public.unsubmit_weekly_report(bigint),
    public.reopen_weekly_report(bigint), public.start_current_weekly_report(bigint)
TO authenticated, service_role;

COMMIT;
