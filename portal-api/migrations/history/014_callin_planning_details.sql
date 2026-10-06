-- Read-only planning projections shared by Call-ins and Superset. Beta only.
-- Original reports, summary RPCs, and saved answers are not rewritten.
BEGIN;

CREATE OR REPLACE FUNCTION public.planning_kpi_value(answer_value numeric, fallback_value integer)
RETURNS integer LANGUAGE sql IMMUTABLE
SET search_path = public, pg_temp
AS $function$
    SELECT CASE WHEN answer_value BETWEEN 0 AND 2147483647
                     AND answer_value = trunc(answer_value)
                THEN answer_value::integer ELSE fallback_value END;
$function$;

CREATE OR REPLACE VIEW public.weekly_area_reports_with_planning_metrics
WITH (security_invoker = true) AS
SELECT mapped.*
FROM public.weekly_area_reports war
LEFT JOIN LATERAL (
    SELECT jsonb_object_agg(wpa.question_key,wpa.answer_number)
        FILTER (WHERE wpa.answer_number IS NOT NULL) AS numbers
    FROM public.weekly_planning_answers wpa WHERE wpa.weekly_area_report_id = war.id
) answers ON true
CROSS JOIN LATERAL jsonb_populate_record(NULL::public.weekly_area_reports,
    to_jsonb(war) || jsonb_build_object(
        'friends_found_actual',public.planning_kpi_value((answers.numbers->>'friends_found_actual')::numeric,war.friends_found_actual),
        'friends_found_goal',public.planning_kpi_value((answers.numbers->>'friends_found_goal')::numeric,war.friends_found_goal),
        'lessons_with_members_actual',public.planning_kpi_value((answers.numbers->>'members_at_lessons_actual')::numeric,war.lessons_with_members_actual),
        'lessons_with_members_goal',public.planning_kpi_value((answers.numbers->>'members_at_lessons_goal')::numeric,war.lessons_with_members_goal),
        'sacrament_attendance_actual',public.planning_kpi_value((answers.numbers->>'sacrament_attendance_actual')::numeric,war.sacrament_attendance_actual),
        'sacrament_attendance_goal',public.planning_kpi_value((answers.numbers->>'sacrament_attendance_goal')::numeric,war.sacrament_attendance_goal),
        'baptismal_dates_actual',public.planning_kpi_value((answers.numbers->>'baptismal_dates_actual')::numeric,war.baptismal_dates_actual),
        'baptismal_dates_goal',public.planning_kpi_value((answers.numbers->>'baptismal_dates_goal')::numeric,war.baptismal_dates_goal),
        'baptisms_confirmations_actual',public.planning_kpi_value((answers.numbers->>'baptisms_confirmations_actual')::numeric,war.baptisms_confirmations_actual),
        'baptisms_confirmations_goal',public.planning_kpi_value((answers.numbers->>'baptisms_confirmations_goal')::numeric,war.baptisms_confirmations_goal),
        'new_member_sacrament_actual',public.planning_kpi_value((answers.numbers->>'nm_sacrament_attendance')::numeric,war.new_member_sacrament_actual),
        'new_member_sacrament_goal',public.planning_kpi_value((answers.numbers->>'nm_sacrament_attendance_goal')::numeric,war.new_member_sacrament_goal)
    )) mapped;

CREATE OR REPLACE VIEW public.call_in_planning_details
WITH (security_invoker = true) AS
SELECT r.id AS weekly_area_report_id, r.reporting_week_id, rw.sunday AS reporting_sunday,
       r.area_id, a.name AS area_name, d.id AS district_id, d.name AS district_name,
       z.id AS zone_id, z.name AS zone_name, z.mission_id,
       r.unit_id, u.name AS unit_name, r.status,
       coalesce(goals.items,'[]'::jsonb) || jsonb_build_array(
           jsonb_build_object('key','lessons_with_friends_goal','label','Lessons with friends',
               'section','Teaching and follow-up','actual',r.lessons_with_friends_actual,'goal',r.lessons_with_friends_goal),
           jsonb_build_object('key','follow_up_lessons_goal','label','Follow-up lessons',
               'section','Teaching and follow-up','actual',r.follow_up_lessons_actual,'goal',r.follow_up_lessons_goal)
       ) || coalesce(member_goals.items,'[]'::jsonb) AS other_goals,
       coalesce(plans.items,'[]'::jsonb) AS action_plans,
       nullif(btrim(answers.texts->>'weekly_action_plan'),'') AS weekly_action_plan,
       nullif(btrim(answers.texts->>'information_up_chain'),'') AS information_up_chain
FROM public.weekly_area_reports_with_planning_metrics r
JOIN public.reporting_weeks rw ON rw.id = r.reporting_week_id
JOIN public.areas a ON a.id = r.area_id
JOIN public.districts d ON d.id = a.district_id
JOIN public.zones z ON z.id = d.zone_id
LEFT JOIN public.units u ON u.id = r.unit_id
LEFT JOIN LATERAL (
    SELECT jsonb_object_agg(wpa.question_key,wpa.answer_number)
               FILTER (WHERE wpa.answer_number IS NOT NULL) AS numbers,
           jsonb_object_agg(wpa.question_key,wpa.answer_text)
               FILTER (WHERE wpa.answer_text IS NOT NULL) AS texts
    FROM public.weekly_planning_answers wpa WHERE wpa.weekly_area_report_id = r.id
) answers ON true
LEFT JOIN LATERAL (
    WITH goal_definitions AS (
        SELECT q.question_key, q.question_label, q.section_title, q.section_order, q.question_order
        FROM public.active_planning_questions q
        WHERE right(q.question_key,5) = '_goal'
          AND q.question_key <> ALL(ARRAY['nm_sacrament_attendance_goal','baptisms_confirmations_goal',
              'baptismal_dates_goal','sacrament_attendance_goal','members_at_lessons_goal','friends_found_goal',
              'lessons_with_friends_goal','follow_up_lessons_goal'])
        UNION ALL
        SELECT wpa.question_key,initcap(replace(wpa.question_key,'_',' ')),
               'Additional goals',999,999
        FROM public.weekly_planning_answers wpa
        WHERE wpa.weekly_area_report_id = r.id AND right(wpa.question_key,5) = '_goal'
          AND NOT EXISTS (SELECT 1 FROM public.active_planning_questions q WHERE q.question_key = wpa.question_key)
    )
    SELECT jsonb_agg(jsonb_build_object(
        'key',q.question_key,
        'label',regexp_replace(q.question_label,'\s*—.*$',''),
        'section',q.section_title,
        'goal',(answers.numbers->>q.question_key)::numeric,
        'actual',(SELECT sum((answers.numbers->>actual_key)::numeric) FROM unnest(
            CASE q.question_key
                WHEN 'member_meals_goal' THEN ARRAY['member_meals_active_actual','member_meals_less_active_actual','member_meals_part_member_actual']
                WHEN 'member_visits_goal' THEN ARRAY['member_visits_active_actual','member_visits_less_active_actual','member_visits_part_member_actual']
                ELSE ARRAY[regexp_replace(q.question_key,'_goal$','_actual')]
            END) actual_key)
        ) ORDER BY q.section_order,q.question_order,q.question_key) AS items
    FROM goal_definitions q
) goals ON true
LEFT JOIN LATERAL (
    SELECT jsonb_agg(jsonb_build_object(
        'key','new_member_lessons_'||wnm.id,'label','New member lessons'||coalesce(' · '||nm.display_name,''),
        'section','New member follow-up','actual',wnm.lessons_actual,'goal',wnm.lessons_goal
    ) ORDER BY wnm.display_order,wnm.id) AS items
    FROM public.weekly_new_members wnm LEFT JOIN public.new_members nm ON nm.id = wnm.new_member_id
    WHERE wnm.weekly_area_report_id = r.id AND wnm.lessons_goal IS NOT NULL
) member_goals ON true
LEFT JOIN LATERAL (
    SELECT jsonb_agg(jsonb_build_object(
        'key',wpa.question_key,
        'label',regexp_replace(regexp_replace(coalesce(q.question_label,initcap(replace(wpa.question_key,'_',' '))),'^Optional: ',''),'\s*— Action Plan$',''),
        'text',btrim(wpa.answer_text),
        'core',wpa.question_key = ANY(ARRAY['nm_sacrament_attendance_plan','baptisms_confirmations_plan',
            'baptismal_dates_plan','sacrament_attendance_plan','members_at_lessons_plan','friends_found_plan'])
    ) ORDER BY q.section_order,q.question_order,wpa.question_key) AS items
    FROM public.weekly_planning_answers wpa
    LEFT JOIN public.active_planning_questions q ON q.question_key = wpa.question_key
    WHERE wpa.weekly_area_report_id = r.id AND right(wpa.question_key,5) = '_plan'
      AND wpa.question_key <> 'weekly_action_plan' AND nullif(btrim(wpa.answer_text),'') IS NOT NULL
) plans ON true
WHERE public.can_access_area(r.area_id);

CREATE OR REPLACE FUNCTION public.get_call_in_planning_metrics(
    target_reporting_week_id bigint, target_area_id bigint DEFAULT NULL,
    target_district_id bigint DEFAULT NULL, target_zone_id bigint DEFAULT NULL,
    target_mission_id bigint DEFAULT NULL)
RETURNS jsonb LANGUAGE sql STABLE SECURITY INVOKER
SET search_path = public, pg_temp
AS $function$
    SELECT coalesce((SELECT jsonb_build_object(
        'friends_found_actual',sum(r.friends_found_actual),'friends_found_goal',sum(r.friends_found_goal),
        'members_at_lessons_actual',sum(r.lessons_with_members_actual),'members_at_lessons_goal',sum(r.lessons_with_members_goal),
        'sacrament_attendance_actual',sum(r.sacrament_attendance_actual),'sacrament_attendance_goal',sum(r.sacrament_attendance_goal),
        'baptismal_dates_actual',sum(coalesce(r.baptismal_dates_actual,0)),'baptismal_dates_goal',sum(coalesce(r.baptismal_dates_goal,0)),
        'baptisms_confirmations_actual',sum(coalesce(r.baptisms_confirmations_actual,0)),'baptisms_confirmations_goal',sum(coalesce(r.baptisms_confirmations_goal,0)),
        'nm_sacrament_actual',sum(r.new_member_sacrament_actual),'nm_sacrament_goal',sum(r.new_member_sacrament_goal)
    ) FROM public.weekly_area_reports_with_planning_metrics r
      JOIN public.areas a ON a.id = r.area_id
      JOIN public.districts d ON d.id = a.district_id
      JOIN public.zones z ON z.id = d.zone_id
      WHERE r.reporting_week_id = target_reporting_week_id
        AND (target_area_id IS NULL OR r.area_id = target_area_id)
        AND (target_district_id IS NULL OR d.id = target_district_id)
        AND (target_zone_id IS NULL OR z.id = target_zone_id)
        AND (target_mission_id IS NULL OR z.mission_id = target_mission_id)
        AND public.can_access_area(r.area_id)
      HAVING count(*) > 0),'{}'::jsonb);
$function$;

CREATE OR REPLACE FUNCTION public.get_call_in_planning_previous_goals(
    target_reporting_week_id bigint, target_area_id bigint DEFAULT NULL,
    target_district_id bigint DEFAULT NULL, target_zone_id bigint DEFAULT NULL,
    target_mission_id bigint DEFAULT NULL)
RETURNS jsonb LANGUAGE sql STABLE SECURITY INVOKER
SET search_path = public, pg_temp
AS $function$
    SELECT coalesce(jsonb_object_agg(regexp_replace(metric.key,'_goal$','_previous_goal'),metric.value),'{}'::jsonb)
    FROM jsonb_each(public.get_call_in_planning_metrics(
        (SELECT rw.id FROM public.reporting_weeks rw
         WHERE rw.sunday < (SELECT sunday FROM public.reporting_weeks WHERE id = target_reporting_week_id)
         ORDER BY rw.sunday DESC LIMIT 1),target_area_id,target_district_id,target_zone_id,target_mission_id
    )) metric WHERE right(metric.key,5) = '_goal';
$function$;

CREATE OR REPLACE FUNCTION public.get_dl_call_in_summary_with_planning(target_district_id bigint,target_reporting_week_id bigint)
RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY INVOKER
SET search_path = public, pg_temp
AS $function$
DECLARE v_result jsonb;
BEGIN
    IF NOT public.can_access_district(target_district_id) OR NOT EXISTS (
        SELECT 1 FROM public.areas a WHERE a.district_id = target_district_id AND public.can_access_area(a.id)
    ) THEN RAISE EXCEPTION 'This district is outside your stewardship.' USING ERRCODE = '42501'; END IF;
    SELECT coalesce(jsonb_agg(to_jsonb(s)
        || public.get_call_in_planning_metrics(target_reporting_week_id,s.area_id)
        || public.get_call_in_planning_previous_goals(target_reporting_week_id,s.area_id)
        || jsonb_build_object('planning_details',coalesce((
            SELECT jsonb_agg(to_jsonb(p) ORDER BY p.unit_name,p.weekly_area_report_id)
            FROM public.call_in_planning_details p
            WHERE p.reporting_week_id = target_reporting_week_id AND p.area_id = s.area_id
        ),'[]'::jsonb)) ORDER BY s.area_name),'[]'::jsonb) INTO v_result
    FROM public.get_dl_call_in_summary(target_district_id,target_reporting_week_id) s;
    RETURN v_result;
END;
$function$;

CREATE OR REPLACE FUNCTION public.get_zl_call_in_summary_with_planning(target_zone_id bigint,target_reporting_week_id bigint)
RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY INVOKER
SET search_path = public, pg_temp
AS $function$
DECLARE v_result jsonb;
BEGIN
    IF NOT public.can_access_zone(target_zone_id) OR NOT EXISTS (
        SELECT 1 FROM public.areas a JOIN public.districts d ON d.id = a.district_id
        WHERE d.zone_id = target_zone_id AND public.can_access_area(a.id)
    ) THEN RAISE EXCEPTION 'This zone is outside your stewardship.' USING ERRCODE = '42501'; END IF;
    SELECT coalesce(jsonb_agg(to_jsonb(s)
        || public.get_call_in_planning_metrics(target_reporting_week_id,NULL,s.district_id)
        || public.get_call_in_planning_previous_goals(target_reporting_week_id,NULL,s.district_id)
        || jsonb_build_object('planning_details',coalesce((
            SELECT jsonb_agg(to_jsonb(p) ORDER BY p.area_name,p.unit_name,p.weekly_area_report_id)
            FROM public.call_in_planning_details p
            WHERE p.reporting_week_id = target_reporting_week_id AND p.district_id = s.district_id
        ),'[]'::jsonb)) ORDER BY s.district_name),'[]'::jsonb) INTO v_result
    FROM public.get_zl_call_in_summary(target_zone_id,target_reporting_week_id) s;
    RETURN v_result;
END;
$function$;

CREATE OR REPLACE FUNCTION public.get_mission_call_in_summary_with_planning(target_mission_id bigint,target_reporting_week_id bigint)
RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY INVOKER
SET search_path = public, pg_temp
AS $function$
DECLARE v_result jsonb;
BEGIN
    IF NOT public.can_access_mission(target_mission_id) OR NOT EXISTS (
        SELECT 1 FROM public.areas a JOIN public.districts d ON d.id = a.district_id
        JOIN public.zones z ON z.id = d.zone_id
        WHERE z.mission_id = target_mission_id AND public.can_access_area(a.id)
    ) THEN RAISE EXCEPTION 'This mission is outside your assignment.' USING ERRCODE = '42501'; END IF;
    SELECT coalesce(jsonb_agg(to_jsonb(s)
        || public.get_call_in_planning_metrics(target_reporting_week_id,NULL,NULL,s.zone_id)
        || public.get_call_in_planning_previous_goals(target_reporting_week_id,NULL,NULL,s.zone_id)
        || jsonb_build_object('planning_details',coalesce((
            SELECT jsonb_agg(to_jsonb(p) ORDER BY p.district_name,p.area_name,p.unit_name,p.weekly_area_report_id)
            FROM public.call_in_planning_details p
            WHERE p.reporting_week_id = target_reporting_week_id AND p.zone_id = s.zone_id
        ),'[]'::jsonb)) ORDER BY s.zone_name),'[]'::jsonb) INTO v_result
    FROM public.get_mission_call_in_summary(target_mission_id,target_reporting_week_id) s;
    RETURN v_result;
END;
$function$;

REVOKE ALL ON public.weekly_area_reports_with_planning_metrics,public.call_in_planning_details FROM PUBLIC,anon,authenticated,service_role;
GRANT SELECT ON public.weekly_area_reports_with_planning_metrics,public.call_in_planning_details TO authenticated,service_role,postgres;
REVOKE EXECUTE ON FUNCTION public.planning_kpi_value(numeric,integer),
    public.get_call_in_planning_metrics(bigint,bigint,bigint,bigint,bigint),
    public.get_call_in_planning_previous_goals(bigint,bigint,bigint,bigint,bigint),
    public.get_dl_call_in_summary_with_planning(bigint,bigint),
    public.get_zl_call_in_summary_with_planning(bigint,bigint),
    public.get_mission_call_in_summary_with_planning(bigint,bigint) FROM PUBLIC,anon;
GRANT EXECUTE ON FUNCTION public.planning_kpi_value(numeric,integer),
    public.get_call_in_planning_metrics(bigint,bigint,bigint,bigint,bigint),
    public.get_call_in_planning_previous_goals(bigint,bigint,bigint,bigint,bigint),
    public.get_dl_call_in_summary_with_planning(bigint,bigint),
    public.get_zl_call_in_summary_with_planning(bigint,bigint),
    public.get_mission_call_in_summary_with_planning(bigint,bigint) TO authenticated,service_role,postgres;

NOTIFY pgrst,'reload schema';
COMMIT;
