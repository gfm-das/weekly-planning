-- Rollback of migration 042: a person's weekly answers no longer start from last time, and the old unused function is back.
-- Run on Beta as supabase_admin. Revert the portal-api code of this change too, and use the OLD migration 019 afterwards
-- (the new one no longer names get_previous_weekly_new_members).
BEGIN;
CREATE OR REPLACE FUNCTION public.carry_people_into_report(p_report_id bigint)
 RETURNS void
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public', 'pg_temp'
AS $function$
DECLARE
    v_area bigint; v_unit bigint; v_status text; v_sunday date;
BEGIN
    SELECT war.area_id, war.unit_id, war.status, rw.sunday INTO v_area, v_unit, v_status, v_sunday
    FROM public.weekly_area_reports war JOIN public.reporting_weeks rw ON rw.id = war.reporting_week_id
    WHERE war.id = p_report_id;
    IF v_area IS NULL OR v_status <> 'DRAFT' OR v_sunday <> public.current_reporting_sunday() THEN
        RETURN;  -- only a draft of the current week gets its people carried
    END IF;
    INSERT INTO public.weekly_new_members (weekly_area_report_id, new_member_id, display_order)
    SELECT p_report_id, nm.id,
           (SELECT COALESCE(max(display_order), 0) FROM public.weekly_new_members WHERE weekly_area_report_id = p_report_id)
             + row_number() OVER (ORDER BY nm.display_name, nm.id)::integer
    FROM public.current_new_members nm
    WHERE nm.area_id = v_area AND nm.unit_id = v_unit AND nm.follow_up_status = 'current'
    ON CONFLICT (weekly_area_report_id, new_member_id) WHERE new_member_id IS NOT NULL DO NOTHING;

    INSERT INTO public.weekly_baptismal_date_friends (weekly_area_report_id, baptismal_date_person_id, display_order)
    SELECT p_report_id, bdp.id,
           (SELECT COALESCE(max(display_order), 0) FROM public.weekly_baptismal_date_friends WHERE weekly_area_report_id = p_report_id)
             + row_number() OVER (ORDER BY bdp.display_name, bdp.id)::integer
    FROM public.current_baptismal_date_people bdp
    JOIN public.baptismal_date_person_area_assignments bdpa
      ON bdpa.baptismal_date_person_id = bdp.id AND bdpa.end_date IS NULL
    WHERE bdp.area_id = v_area AND bdpa.unit_id = v_unit
      AND EXISTS (SELECT 1 FROM public.weekly_baptismal_date_friends w
                  JOIN public.weekly_area_reports r ON r.id = w.weekly_area_report_id
                  JOIN public.reporting_weeks rw ON rw.id = r.reporting_week_id
                  WHERE w.baptismal_date_person_id = bdp.id AND rw.sunday = v_sunday - 7)
    ON CONFLICT (weekly_area_report_id, baptismal_date_person_id) WHERE baptismal_date_person_id IS NOT NULL DO NOTHING;

    -- A friend's "date set" and "current baptismal date" do not change every week: fill this week's empty ones from
    -- the friend's latest earlier weekly row (any area, so a transfer keeps them). Rows that already have them are not touched.
    WITH previous AS (
        SELECT DISTINCT ON (w.id) w.id, p.baptismal_date_set_on, p.current_baptismal_date
        FROM public.weekly_baptismal_date_friends w
        JOIN public.weekly_baptismal_date_friends p
          ON p.baptismal_date_person_id = w.baptismal_date_person_id AND p.id <> w.id
        JOIN public.weekly_area_reports pr ON pr.id = p.weekly_area_report_id
        JOIN public.reporting_weeks prw ON prw.id = pr.reporting_week_id
        WHERE w.weekly_area_report_id = p_report_id
          AND prw.sunday < v_sunday
          AND ((w.baptismal_date_set_on IS NULL AND p.baptismal_date_set_on IS NOT NULL)
               OR (w.current_baptismal_date IS NULL AND p.current_baptismal_date IS NOT NULL))
        ORDER BY w.id, prw.sunday DESC, p.updated_at DESC NULLS LAST, p.id DESC
    )
    UPDATE public.weekly_baptismal_date_friends w
    SET baptismal_date_set_on = coalesce(w.baptismal_date_set_on, previous.baptismal_date_set_on),
        current_baptismal_date = coalesce(w.current_baptismal_date, previous.current_baptismal_date)
    FROM previous WHERE w.id = previous.id;

    INSERT INTO public.weekly_high_potential_friends (weekly_area_report_id, display_order, name)
    SELECT p_report_id,
           (SELECT COALESCE(max(display_order), 0) FROM public.weekly_high_potential_friends WHERE weekly_area_report_id = p_report_id)
             + row_number() OVER (ORDER BY h.display_order, h.id)::integer,
           h.name
    FROM public.weekly_high_potential_friends h
    JOIN public.weekly_area_reports pr ON pr.id = h.weekly_area_report_id
    JOIN public.reporting_weeks prw ON prw.id = pr.reporting_week_id
    WHERE pr.area_id = v_area AND pr.unit_id IS NOT DISTINCT FROM v_unit AND prw.sunday = v_sunday - 7
      AND btrim(h.name) <> '' AND h.name <> 'New High Potential'
      AND NOT EXISTS (SELECT 1 FROM public.weekly_high_potential_friends c
                      WHERE c.weekly_area_report_id = p_report_id AND lower(btrim(c.name)) = lower(btrim(h.name)));
END;
$function$;
ALTER FUNCTION public.carry_people_into_report(bigint) OWNER TO postgres;
REVOKE ALL ON FUNCTION public.carry_people_into_report(bigint) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.carry_people_into_report(bigint) TO service_role;
DROP FUNCTION IF EXISTS public.prefill_weekly_new_members(bigint[]);
DROP FUNCTION IF EXISTS public.prefill_weekly_friends(bigint[]);
CREATE OR REPLACE FUNCTION public.get_previous_weekly_new_members(target_unit_id bigint)
 RETURNS SETOF weekly_new_members
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public', 'pg_temp'
AS $function$
DECLARE
    v_area_id bigint;
    v_previous_sunday date;
    v_previous_report_id bigint;
BEGIN

    IF target_unit_id IS NULL THEN
        RAISE EXCEPTION 'A unit must be selected.';
    END IF;

    IF NOT public.can_current_user_report_for_unit(target_unit_id) THEN
        RAISE EXCEPTION 'You do not have access to this unit.';
    END IF;

    v_area_id := public.current_user_area_id();

    IF v_area_id IS NULL THEN
        RETURN;
    END IF;

    v_previous_sunday :=
        public.current_reporting_sunday() - 7;

    SELECT war.id
    INTO v_previous_report_id
    FROM public.weekly_area_reports war
    JOIN public.reporting_weeks rw
      ON rw.id = war.reporting_week_id
    WHERE
        war.area_id = v_area_id
        AND war.unit_id = target_unit_id
        AND rw.sunday = v_previous_sunday
    LIMIT 1;

    IF v_previous_report_id IS NULL THEN
        RETURN;
    END IF;

    RETURN QUERY
    SELECT wnm.*
    FROM public.weekly_new_members wnm
    WHERE
        wnm.weekly_area_report_id =
        v_previous_report_id;
END;
$function$;
ALTER FUNCTION public.get_previous_weekly_new_members(bigint) OWNER TO postgres;
REVOKE ALL ON FUNCTION public.get_previous_weekly_new_members(bigint) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.get_previous_weekly_new_members(bigint) TO authenticated, service_role;
COMMIT;
