-- Migration 042 (Oct 2026): a person's weekly answers start from last time. Run on Beta only, as supabase_admin.
--
-- What changes:
-- 1. prefill_weekly_new_members(row ids) and prefill_weekly_friends(row ids): for each weekly row, copy the answers of the
--    same person's latest row of an EARLIER week (any area, so a transfer keeps them) into the answers that are still
--    empty. Nothing already there is overwritten. A New Member gets lessons (actual, goal, the Preach My Gospel
--    percentage), next ordinance, church this Sunday, calling, priesthood, ministering, temple, reading, praying, member
--    involvement, "how are they doing" and the Gemiko support plan. NOT "discussed in Gemiko" (the owner: it is a fact
--    of the week). A friend gets the two baptismal dates, reading, praying, church, keeping the commandments and member
--    involvement.
-- 2. carry_people_into_report() (migration 039) calls them for the rows it makes when a week's plan starts (a missionary
--    opening the portal, or an upload filling the current week). Only for rows made just now, so something a missionary
--    clears on purpose is not refilled the next time the plan opens. The portal's "Add from database" calls the same
--    functions (portal-api/planning.py).
-- 3. get_previous_weekly_new_members(unit) was an old function nothing uses: it is dropped (migration 019 no longer names it).
-- Rollback: 042_prefill_person_answers_rollback.sql.
BEGIN;

CREATE OR REPLACE FUNCTION public.prefill_weekly_new_members(p_row_ids bigint[])
 RETURNS void
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path = public, pg_temp
AS $function$
BEGIN
    -- A signed-in person may do this only for rows of a DRAFT plan of an area they may edit. DA Management and the
    -- carry-over (no signed-in person) are trusted.
    IF auth.uid() IS NOT NULL AND EXISTS (
        SELECT 1 FROM public.weekly_new_members w
        JOIN public.weekly_area_reports r ON r.id = w.weekly_area_report_id
        WHERE w.id = ANY(p_row_ids) AND (r.status <> 'DRAFT' OR NOT public.can_edit_planning_area(r.area_id))) THEN
        RAISE EXCEPTION 'This plan must be an authorized draft before its answers can be filled in.' USING ERRCODE = '42501';
    END IF;
    -- For each row: the same person's latest row of an EARLIER week (any area, so a transfer keeps the answers); only
    -- empty answers are filled, nothing typed is overwritten.
    WITH target AS (
        SELECT w.id, w.new_member_id AS person_id, rw.sunday
        FROM public.weekly_new_members w
        JOIN public.weekly_area_reports r ON r.id = w.weekly_area_report_id
        JOIN public.reporting_weeks rw ON rw.id = r.reporting_week_id
        WHERE w.id = ANY(p_row_ids) AND w.new_member_id IS NOT NULL),
    prev AS (
        SELECT DISTINCT ON (t.id) t.id, p.lessons_actual, p.lessons_goal, p.pmg_lessons_percentage, p.how_are_they_doing, p.gemiko_support_plan, p.next_ordinance, p.at_church_this_sunday, p.has_calling, p.has_aaronic_priesthood, p.has_melchizedek_priesthood, p.ministers_to_someone, p.ministered_to_by_someone, p.has_active_temple_recommend, p.visited_temple_for_baptisms, p.reading, p.praying, p.member_involvement
        FROM target t
        JOIN public.weekly_new_members p ON p.new_member_id = t.person_id AND p.id <> t.id
        JOIN public.weekly_area_reports pr ON pr.id = p.weekly_area_report_id
        JOIN public.reporting_weeks prw ON prw.id = pr.reporting_week_id
        WHERE prw.sunday < t.sunday
        ORDER BY t.id, prw.sunday DESC, p.updated_at DESC NULLS LAST, p.id DESC)
    UPDATE public.weekly_new_members w
    SET lessons_actual = coalesce(w.lessons_actual, prev.lessons_actual),
        lessons_goal = coalesce(w.lessons_goal, prev.lessons_goal),
        pmg_lessons_percentage = coalesce(w.pmg_lessons_percentage, prev.pmg_lessons_percentage),
        how_are_they_doing = coalesce(w.how_are_they_doing, prev.how_are_they_doing),
        gemiko_support_plan = coalesce(w.gemiko_support_plan, prev.gemiko_support_plan),
        next_ordinance = coalesce(w.next_ordinance, prev.next_ordinance),
        at_church_this_sunday = coalesce(w.at_church_this_sunday, prev.at_church_this_sunday),
        has_calling = coalesce(w.has_calling, prev.has_calling),
        has_aaronic_priesthood = coalesce(w.has_aaronic_priesthood, prev.has_aaronic_priesthood),
        has_melchizedek_priesthood = coalesce(w.has_melchizedek_priesthood, prev.has_melchizedek_priesthood),
        ministers_to_someone = coalesce(w.ministers_to_someone, prev.ministers_to_someone),
        ministered_to_by_someone = coalesce(w.ministered_to_by_someone, prev.ministered_to_by_someone),
        has_active_temple_recommend = coalesce(w.has_active_temple_recommend, prev.has_active_temple_recommend),
        visited_temple_for_baptisms = coalesce(w.visited_temple_for_baptisms, prev.visited_temple_for_baptisms),
        reading = coalesce(w.reading, prev.reading),
        praying = coalesce(w.praying, prev.praying),
        member_involvement = coalesce(w.member_involvement, prev.member_involvement)
    FROM prev WHERE w.id = prev.id;
END;
$function$;

CREATE OR REPLACE FUNCTION public.prefill_weekly_friends(p_row_ids bigint[])
 RETURNS void
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path = public, pg_temp
AS $function$
BEGIN
    -- A signed-in person may do this only for rows of a DRAFT plan of an area they may edit. DA Management and the
    -- carry-over (no signed-in person) are trusted.
    IF auth.uid() IS NOT NULL AND EXISTS (
        SELECT 1 FROM public.weekly_baptismal_date_friends w
        JOIN public.weekly_area_reports r ON r.id = w.weekly_area_report_id
        WHERE w.id = ANY(p_row_ids) AND (r.status <> 'DRAFT' OR NOT public.can_edit_planning_area(r.area_id))) THEN
        RAISE EXCEPTION 'This plan must be an authorized draft before its answers can be filled in.' USING ERRCODE = '42501';
    END IF;
    -- For each row: the same person's latest row of an EARLIER week (any area, so a transfer keeps the answers); only
    -- empty answers are filled, nothing typed is overwritten.
    WITH target AS (
        SELECT w.id, w.baptismal_date_person_id AS person_id, rw.sunday
        FROM public.weekly_baptismal_date_friends w
        JOIN public.weekly_area_reports r ON r.id = w.weekly_area_report_id
        JOIN public.reporting_weeks rw ON rw.id = r.reporting_week_id
        WHERE w.id = ANY(p_row_ids) AND w.baptismal_date_person_id IS NOT NULL),
    prev AS (
        SELECT DISTINCT ON (t.id) t.id, p.baptismal_date_set_on, p.current_baptismal_date, p.reading, p.praying, p.at_church_this_sunday, p.keeping_commandments, p.member_involvement
        FROM target t
        JOIN public.weekly_baptismal_date_friends p ON p.baptismal_date_person_id = t.person_id AND p.id <> t.id
        JOIN public.weekly_area_reports pr ON pr.id = p.weekly_area_report_id
        JOIN public.reporting_weeks prw ON prw.id = pr.reporting_week_id
        WHERE prw.sunday < t.sunday
        ORDER BY t.id, prw.sunday DESC, p.updated_at DESC NULLS LAST, p.id DESC)
    UPDATE public.weekly_baptismal_date_friends w
    SET baptismal_date_set_on = coalesce(w.baptismal_date_set_on, prev.baptismal_date_set_on),
        current_baptismal_date = coalesce(w.current_baptismal_date, prev.current_baptismal_date),
        reading = coalesce(w.reading, prev.reading),
        praying = coalesce(w.praying, prev.praying),
        at_church_this_sunday = coalesce(w.at_church_this_sunday, prev.at_church_this_sunday),
        keeping_commandments = coalesce(w.keeping_commandments, prev.keeping_commandments),
        member_involvement = coalesce(w.member_involvement, prev.member_involvement)
    FROM prev WHERE w.id = prev.id;
END;
$function$;

CREATE OR REPLACE FUNCTION public.carry_people_into_report(p_report_id bigint)
 RETURNS void
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public', 'pg_temp'
AS $function$
DECLARE
    v_area bigint; v_unit bigint; v_status text; v_sunday date; v_new_ids bigint[];
BEGIN
    SELECT war.area_id, war.unit_id, war.status, rw.sunday INTO v_area, v_unit, v_status, v_sunday
    FROM public.weekly_area_reports war JOIN public.reporting_weeks rw ON rw.id = war.reporting_week_id
    WHERE war.id = p_report_id;
    IF v_area IS NULL OR v_status <> 'DRAFT' OR v_sunday <> public.current_reporting_sunday() THEN
        RETURN;  -- only a draft of the current week gets its people carried
    END IF;
    WITH made AS (
    INSERT INTO public.weekly_new_members (weekly_area_report_id, new_member_id, display_order)
    SELECT p_report_id, nm.id,
           (SELECT COALESCE(max(display_order), 0) FROM public.weekly_new_members WHERE weekly_area_report_id = p_report_id)
             + row_number() OVER (ORDER BY nm.display_name, nm.id)::integer
    FROM public.current_new_members nm
    WHERE nm.area_id = v_area AND nm.unit_id = v_unit AND nm.follow_up_status = 'current'
    ON CONFLICT (weekly_area_report_id, new_member_id) WHERE new_member_id IS NOT NULL DO NOTHING
    RETURNING id)
    SELECT array_agg(id) INTO v_new_ids FROM made;
    -- Round 12: a New Member starts the week with last time's answers (only on rows made just now).
    IF v_new_ids IS NOT NULL THEN PERFORM public.prefill_weekly_new_members(v_new_ids); END IF;

    WITH made AS (
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
    ON CONFLICT (weekly_area_report_id, baptismal_date_person_id) WHERE baptismal_date_person_id IS NOT NULL DO NOTHING
    RETURNING id)
    SELECT array_agg(id) INTO v_new_ids FROM made;
    IF v_new_ids IS NOT NULL THEN PERFORM public.prefill_weekly_friends(v_new_ids); END IF;

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

ALTER FUNCTION public.prefill_weekly_new_members(bigint[]) OWNER TO postgres;
ALTER FUNCTION public.prefill_weekly_friends(bigint[]) OWNER TO postgres;
ALTER FUNCTION public.carry_people_into_report(bigint) OWNER TO postgres;
REVOKE ALL ON FUNCTION public.prefill_weekly_new_members(bigint[]), public.prefill_weekly_friends(bigint[]) FROM PUBLIC, anon;
GRANT EXECUTE ON FUNCTION public.prefill_weekly_new_members(bigint[]), public.prefill_weekly_friends(bigint[]) TO authenticated, service_role;
REVOKE ALL ON FUNCTION public.carry_people_into_report(bigint) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.carry_people_into_report(bigint) TO service_role;

DROP FUNCTION IF EXISTS public.get_previous_weekly_new_members(bigint);

DO $$
BEGIN
  IF has_function_privilege('anon', 'public.prefill_weekly_new_members(bigint[])', 'EXECUTE')
     OR has_function_privilege('anon', 'public.prefill_weekly_friends(bigint[])', 'EXECUTE')
     OR has_function_privilege('authenticated', 'public.carry_people_into_report(bigint)', 'EXECUTE') THEN
    RAISE EXCEPTION 'Check failed: a prefill or carry function has the wrong rights.';
  END IF;
  IF to_regprocedure('public.get_previous_weekly_new_members(bigint)') IS NOT NULL THEN
    RAISE EXCEPTION 'Check failed: the old function is still there.';
  END IF;
END $$;

COMMIT;
