-- Call-ins summaries: fast again, with the same results and the same access rules. Run on Beta only, as postgres.
--
-- Why: Call-ins Alpha (portal-api /api/callins) and Appsmith call get_mission/zl/dl_call_in_summary_with_planning
-- as the signed-in user. For every zone, district or area row these called get_call_in_planning_metrics twice
-- and read call_in_planning_details once, and each of those read weekly_area_reports_with_planning_metrics.
-- That view rebuilt every report through jsonb_populate_record, so a filter on the week or the area could not
-- use the table's indexes: every report ever saved (1,279 on 26 Sep 2026) was rebuilt and access-checked with
-- can_access_area (about 2.7 ms per check) on every call, sometimes once per district. The mission summary did
-- not finish in 10 minutes; the portal gives up after 40 seconds.
--
-- What changes (same names, arguments, return types and results; nothing else is touched):
-- 1. weekly_area_reports_with_planning_metrics names its columns directly instead of rebuilding the row through
--    jsonb. Same rows and values, but a filter on the week or area now uses the indexes. Grafana
--    (dashboards.*) and Superset read this view too and get the same data.
-- 2. call_in_planning_details shows a new member's name only when can_access_area allows that member's area.
--    Row-level security on new_members already did this for signed-in users; the check is now written in the
--    view so it also holds inside the summaries below.
-- 3. The three *_with_planning functions keep their access checks and messages unchanged, then read the week in
--    one pass: can_access_area once per area instead of once per report per call, and one query for the totals,
--    last week's goals and the planning details of all rows. They run as their owner (SECURITY DEFINER), so
--    row-level security is not re-evaluated for every report and answer; they only use reports of areas
--    can_access_area allows, which is exactly what row-level security let the caller see before.
--    EXECUTE stays with authenticated, service_role and postgres (never PUBLIC or anon).
-- get_call_in_planning_metrics and get_call_in_planning_previous_goals are not changed; the summaries no longer
-- call them, and change 1 makes them faster for anyone else who does.
--
-- Keep in mind when access rules change later: because the summaries run as owner, row-level security does not
-- filter weekly_area_reports, weekly_planning_answers, weekly_new_members, new_members or the planning question
-- tables inside them. Written checks do that instead: the check at the start of each summary, can_access_area
-- per area ("visible" below) and can_access_area in call_in_planning_details (change 2). Today they match the
-- policies exactly (can_access_area, and only active questions). Any later change to the policies on those
-- tables must be made in these checks too, or the summaries must go back to caller's rights (rollback A at the
-- end of this file does that and keeps change 1).
--
-- Apply (back up Beta first; 018 and 019 must already be applied). The file is plain ASCII (the dash and the dot
-- used in labels are written as U&'' escapes), so Windows PowerShell 5.1 and PowerShell 7 pass it on intact:
--   Get-Content portal-api/migrations/020_callins_performance.sql -Raw |
--     docker exec -i gfm-beta-supabase-db-1 psql -U postgres -d postgres -v ON_ERROR_STOP=1
-- Then run 019 again as a check (it must end with COMMIT):
--   Get-Content portal-api/migrations/019_restrict_public_functions.sql -Raw |
--     docker exec -i gfm-beta-supabase-db-1 psql -U supabase_admin -d postgres -v ON_ERROR_STOP=1
-- Replacing the two views briefly locks them. If an old, slow Call-ins query is still running, the file stops
-- after 10 seconds (lock timeout) instead of making Planning and Grafana wait; then find and cancel it with
--   SELECT pid, now() - query_start, left(query, 60) FROM pg_stat_activity WHERE query LIKE '%call_in_summary_with_planning%' AND state = 'active' AND pid <> pg_backend_pid();
--   SELECT pg_cancel_backend(<pid>);
-- and run the file again.
-- Safe to run again: only CREATE OR REPLACE, REVOKE and GRANT, then a check that stops on any problem.
-- Verify: see the Verify section after COMMIT. Rollback: two levels (A: the three summaries only; B: everything),
-- see the end of this file.
BEGIN;
SET LOCAL lock_timeout = '10s';

DO $$
BEGIN
  IF current_user <> 'postgres' THEN
    RAISE EXCEPTION 'Run this file as postgres (see its header), not as %.', current_user;
  END IF;
END $$;

-- 1. Same 30 columns as before, taken straight from the report; the 12 planning KPIs still prefer the saved
-- planning answer (planning_kpi_value), exactly as in 014.
CREATE OR REPLACE VIEW public.weekly_area_reports_with_planning_metrics
WITH (security_invoker = true) AS
SELECT war.id, war.area_id, war.reporting_week_id, war.status, war.submitted_by, war.submitted_at,
       public.planning_kpi_value((answers.numbers->>'friends_found_actual')::numeric,war.friends_found_actual) AS friends_found_actual,
       public.planning_kpi_value((answers.numbers->>'friends_found_goal')::numeric,war.friends_found_goal) AS friends_found_goal,
       war.lessons_with_friends_actual, war.lessons_with_friends_goal,
       public.planning_kpi_value((answers.numbers->>'members_at_lessons_actual')::numeric,war.lessons_with_members_actual) AS lessons_with_members_actual,
       public.planning_kpi_value((answers.numbers->>'members_at_lessons_goal')::numeric,war.lessons_with_members_goal) AS lessons_with_members_goal,
       public.planning_kpi_value((answers.numbers->>'sacrament_attendance_actual')::numeric,war.sacrament_attendance_actual) AS sacrament_attendance_actual,
       public.planning_kpi_value((answers.numbers->>'sacrament_attendance_goal')::numeric,war.sacrament_attendance_goal) AS sacrament_attendance_goal,
       war.first_time_sacrament_actual,
       public.planning_kpi_value((answers.numbers->>'baptismal_dates_actual')::numeric,war.baptismal_dates_actual) AS baptismal_dates_actual,
       public.planning_kpi_value((answers.numbers->>'baptismal_dates_goal')::numeric,war.baptismal_dates_goal) AS baptismal_dates_goal,
       public.planning_kpi_value((answers.numbers->>'nm_sacrament_attendance')::numeric,war.new_member_sacrament_actual) AS new_member_sacrament_actual,
       public.planning_kpi_value((answers.numbers->>'nm_sacrament_attendance_goal')::numeric,war.new_member_sacrament_goal) AS new_member_sacrament_goal,
       war.follow_up_lessons_actual, war.follow_up_lessons_goal, war.notes, war.created_at, war.updated_at, war.unit_id,
       public.planning_kpi_value((answers.numbers->>'baptisms_confirmations_actual')::numeric,war.baptisms_confirmations_actual) AS baptisms_confirmations_actual,
       public.planning_kpi_value((answers.numbers->>'baptisms_confirmations_goal')::numeric,war.baptisms_confirmations_goal) AS baptisms_confirmations_goal,
       war.historical_source_area, war.historical_source_key, war.import_batch_id
FROM public.weekly_area_reports war
LEFT JOIN LATERAL (
    SELECT jsonb_object_agg(wpa.question_key,wpa.answer_number)
        FILTER (WHERE wpa.answer_number IS NOT NULL) AS numbers
    FROM public.weekly_planning_answers wpa WHERE wpa.weekly_area_report_id = war.id
) answers ON true;

-- 2. As in 014; only the new_members join gained "AND public.can_access_area(nm.area_id)".
-- U&'...!2014...' UESCAPE '!' is the em dash and U&' !00B7 ' UESCAPE '!' the middle dot of 014.
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
        'label',regexp_replace(q.question_label,U&'\s*!2014.*$' UESCAPE '!',''),
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
        'key','new_member_lessons_'||wnm.id,'label','New member lessons'||coalesce(U&' !00B7 ' UESCAPE '!'||nm.display_name,''),
        'section','New member follow-up','actual',wnm.lessons_actual,'goal',wnm.lessons_goal
    ) ORDER BY wnm.display_order,wnm.id) AS items
    FROM public.weekly_new_members wnm
    LEFT JOIN public.new_members nm ON nm.id = wnm.new_member_id AND public.can_access_area(nm.area_id)
    WHERE wnm.weekly_area_report_id = r.id AND wnm.lessons_goal IS NOT NULL
) member_goals ON true
LEFT JOIN LATERAL (
    SELECT jsonb_agg(jsonb_build_object(
        'key',wpa.question_key,
        'label',regexp_replace(regexp_replace(coalesce(q.question_label,initcap(replace(wpa.question_key,'_',' '))),'^Optional: ',''),U&'\s*!2014 Action Plan$' UESCAPE '!',''),
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

-- 3. The summaries. Each one: the unchanged access check; the unchanged base summary (its rows, in the same
-- order); then one query that adds this week's totals, last week's goals and the planning details per row.
-- Totals use the same sums as get_call_in_planning_metrics over the reports of areas can_access_area allows
-- (asked once per area: the CTEs are MATERIALIZED so the check is not pushed down to every report row and
-- the planning details are read once); a row without such reports keeps the base summary's numbers, as before.
CREATE OR REPLACE FUNCTION public.get_dl_call_in_summary_with_planning(target_district_id bigint,target_reporting_week_id bigint)
RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER
SET search_path = public, pg_temp
AS $function$
DECLARE v_rows jsonb; v_previous_week_id bigint; v_result jsonb;
BEGIN
    IF NOT public.can_access_district(target_district_id) OR NOT EXISTS (
        SELECT 1 FROM public.areas a WHERE a.district_id = target_district_id AND public.can_access_area(a.id)
    ) THEN RAISE EXCEPTION 'This district is outside your stewardship.' USING ERRCODE = '42501'; END IF;
    SELECT coalesce(jsonb_agg(to_jsonb(s) ORDER BY s.area_name),'[]'::jsonb) INTO v_rows
    FROM public.get_dl_call_in_summary(target_district_id,target_reporting_week_id) s;
    SELECT rw.id INTO v_previous_week_id FROM public.reporting_weeks rw
    WHERE rw.sunday < (SELECT sunday FROM public.reporting_weeks WHERE id = target_reporting_week_id)
    ORDER BY rw.sunday DESC LIMIT 1;
    WITH reports AS MATERIALIZED (
        SELECT r.*, r.area_id AS scope_id
        FROM public.weekly_area_reports_with_planning_metrics r
        JOIN public.areas a ON a.id = r.area_id
        JOIN public.districts d ON d.id = a.district_id
        JOIN public.zones z ON z.id = d.zone_id
        WHERE r.reporting_week_id IN (target_reporting_week_id,v_previous_week_id) AND d.id = target_district_id
    ), report_areas AS MATERIALIZED (
        SELECT DISTINCT area_id FROM reports
    ), visible AS MATERIALIZED (
        SELECT area_id FROM report_areas WHERE public.can_access_area(area_id)
    ), totals AS (
        SELECT r.reporting_week_id, r.scope_id, jsonb_build_object(
            'friends_found_actual',sum(r.friends_found_actual),'friends_found_goal',sum(r.friends_found_goal),
            'members_at_lessons_actual',sum(r.lessons_with_members_actual),'members_at_lessons_goal',sum(r.lessons_with_members_goal),
            'sacrament_attendance_actual',sum(r.sacrament_attendance_actual),'sacrament_attendance_goal',sum(r.sacrament_attendance_goal),
            'baptismal_dates_actual',sum(coalesce(r.baptismal_dates_actual,0)),'baptismal_dates_goal',sum(coalesce(r.baptismal_dates_goal,0)),
            'baptisms_confirmations_actual',sum(coalesce(r.baptisms_confirmations_actual,0)),'baptisms_confirmations_goal',sum(coalesce(r.baptisms_confirmations_goal,0)),
            'nm_sacrament_actual',sum(r.new_member_sacrament_actual),'nm_sacrament_goal',sum(r.new_member_sacrament_goal)
        ) AS metrics
        FROM reports r JOIN visible v ON v.area_id = r.area_id
        GROUP BY r.reporting_week_id, r.scope_id
    ), details AS MATERIALIZED (
        SELECT p.area_id AS scope_id, jsonb_agg(to_jsonb(p) ORDER BY p.unit_name,p.weekly_area_report_id) AS items
        FROM public.call_in_planning_details p
        WHERE p.reporting_week_id = target_reporting_week_id AND p.district_id = target_district_id
        GROUP BY p.area_id
    )
    SELECT coalesce(jsonb_agg(s.item || coalesce(cur.metrics,'{}'::jsonb) || coalesce(prev.goals,'{}'::jsonb)
        || jsonb_build_object('planning_details',coalesce(det.items,'[]'::jsonb)) ORDER BY s.n),'[]'::jsonb) INTO v_result
    FROM jsonb_array_elements(v_rows) WITH ORDINALITY s(item,n)
    LEFT JOIN totals cur ON cur.reporting_week_id = target_reporting_week_id AND cur.scope_id = (s.item->>'area_id')::bigint
    LEFT JOIN LATERAL (
        SELECT jsonb_object_agg(regexp_replace(m.key,'_goal$','_previous_goal'),m.value) AS goals
        FROM totals t CROSS JOIN LATERAL jsonb_each(t.metrics) m
        WHERE t.reporting_week_id = v_previous_week_id AND t.scope_id = (s.item->>'area_id')::bigint AND right(m.key,5) = '_goal'
    ) prev ON true
    LEFT JOIN details det ON det.scope_id = (s.item->>'area_id')::bigint;
    RETURN v_result;
END;
$function$;

CREATE OR REPLACE FUNCTION public.get_zl_call_in_summary_with_planning(target_zone_id bigint,target_reporting_week_id bigint)
RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER
SET search_path = public, pg_temp
AS $function$
DECLARE v_rows jsonb; v_previous_week_id bigint; v_result jsonb;
BEGIN
    IF NOT public.can_access_zone(target_zone_id) OR NOT EXISTS (
        SELECT 1 FROM public.areas a JOIN public.districts d ON d.id = a.district_id
        WHERE d.zone_id = target_zone_id AND public.can_access_area(a.id)
    ) THEN RAISE EXCEPTION 'This zone is outside your stewardship.' USING ERRCODE = '42501'; END IF;
    SELECT coalesce(jsonb_agg(to_jsonb(s) ORDER BY s.district_name),'[]'::jsonb) INTO v_rows
    FROM public.get_zl_call_in_summary(target_zone_id,target_reporting_week_id) s;
    SELECT rw.id INTO v_previous_week_id FROM public.reporting_weeks rw
    WHERE rw.sunday < (SELECT sunday FROM public.reporting_weeks WHERE id = target_reporting_week_id)
    ORDER BY rw.sunday DESC LIMIT 1;
    WITH reports AS MATERIALIZED (
        SELECT r.*, a.district_id AS scope_id
        FROM public.weekly_area_reports_with_planning_metrics r
        JOIN public.areas a ON a.id = r.area_id
        JOIN public.districts d ON d.id = a.district_id
        JOIN public.zones z ON z.id = d.zone_id
        WHERE r.reporting_week_id IN (target_reporting_week_id,v_previous_week_id) AND z.id = target_zone_id
    ), report_areas AS MATERIALIZED (
        SELECT DISTINCT area_id FROM reports
    ), visible AS MATERIALIZED (
        SELECT area_id FROM report_areas WHERE public.can_access_area(area_id)
    ), totals AS (
        SELECT r.reporting_week_id, r.scope_id, jsonb_build_object(
            'friends_found_actual',sum(r.friends_found_actual),'friends_found_goal',sum(r.friends_found_goal),
            'members_at_lessons_actual',sum(r.lessons_with_members_actual),'members_at_lessons_goal',sum(r.lessons_with_members_goal),
            'sacrament_attendance_actual',sum(r.sacrament_attendance_actual),'sacrament_attendance_goal',sum(r.sacrament_attendance_goal),
            'baptismal_dates_actual',sum(coalesce(r.baptismal_dates_actual,0)),'baptismal_dates_goal',sum(coalesce(r.baptismal_dates_goal,0)),
            'baptisms_confirmations_actual',sum(coalesce(r.baptisms_confirmations_actual,0)),'baptisms_confirmations_goal',sum(coalesce(r.baptisms_confirmations_goal,0)),
            'nm_sacrament_actual',sum(r.new_member_sacrament_actual),'nm_sacrament_goal',sum(r.new_member_sacrament_goal)
        ) AS metrics
        FROM reports r JOIN visible v ON v.area_id = r.area_id
        GROUP BY r.reporting_week_id, r.scope_id
    ), details AS MATERIALIZED (
        SELECT p.district_id AS scope_id, jsonb_agg(to_jsonb(p) ORDER BY p.area_name,p.unit_name,p.weekly_area_report_id) AS items
        FROM public.call_in_planning_details p
        WHERE p.reporting_week_id = target_reporting_week_id AND p.zone_id = target_zone_id
        GROUP BY p.district_id
    )
    SELECT coalesce(jsonb_agg(s.item || coalesce(cur.metrics,'{}'::jsonb) || coalesce(prev.goals,'{}'::jsonb)
        || jsonb_build_object('planning_details',coalesce(det.items,'[]'::jsonb)) ORDER BY s.n),'[]'::jsonb) INTO v_result
    FROM jsonb_array_elements(v_rows) WITH ORDINALITY s(item,n)
    LEFT JOIN totals cur ON cur.reporting_week_id = target_reporting_week_id AND cur.scope_id = (s.item->>'district_id')::bigint
    LEFT JOIN LATERAL (
        SELECT jsonb_object_agg(regexp_replace(m.key,'_goal$','_previous_goal'),m.value) AS goals
        FROM totals t CROSS JOIN LATERAL jsonb_each(t.metrics) m
        WHERE t.reporting_week_id = v_previous_week_id AND t.scope_id = (s.item->>'district_id')::bigint AND right(m.key,5) = '_goal'
    ) prev ON true
    LEFT JOIN details det ON det.scope_id = (s.item->>'district_id')::bigint;
    RETURN v_result;
END;
$function$;

CREATE OR REPLACE FUNCTION public.get_mission_call_in_summary_with_planning(target_mission_id bigint,target_reporting_week_id bigint)
RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER
SET search_path = public, pg_temp
AS $function$
DECLARE v_rows jsonb; v_previous_week_id bigint; v_result jsonb;
BEGIN
    IF NOT public.can_access_mission(target_mission_id) OR NOT EXISTS (
        SELECT 1 FROM public.areas a JOIN public.districts d ON d.id = a.district_id
        JOIN public.zones z ON z.id = d.zone_id
        WHERE z.mission_id = target_mission_id AND public.can_access_area(a.id)
    ) THEN RAISE EXCEPTION 'This mission is outside your assignment.' USING ERRCODE = '42501'; END IF;
    SELECT coalesce(jsonb_agg(to_jsonb(s) ORDER BY s.zone_name),'[]'::jsonb) INTO v_rows
    FROM public.get_mission_call_in_summary(target_mission_id,target_reporting_week_id) s;
    SELECT rw.id INTO v_previous_week_id FROM public.reporting_weeks rw
    WHERE rw.sunday < (SELECT sunday FROM public.reporting_weeks WHERE id = target_reporting_week_id)
    ORDER BY rw.sunday DESC LIMIT 1;
    WITH reports AS MATERIALIZED (
        SELECT r.*, z.id AS scope_id
        FROM public.weekly_area_reports_with_planning_metrics r
        JOIN public.areas a ON a.id = r.area_id
        JOIN public.districts d ON d.id = a.district_id
        JOIN public.zones z ON z.id = d.zone_id
        WHERE r.reporting_week_id IN (target_reporting_week_id,v_previous_week_id) AND z.mission_id = target_mission_id
    ), report_areas AS MATERIALIZED (
        SELECT DISTINCT area_id FROM reports
    ), visible AS MATERIALIZED (
        SELECT area_id FROM report_areas WHERE public.can_access_area(area_id)
    ), totals AS (
        SELECT r.reporting_week_id, r.scope_id, jsonb_build_object(
            'friends_found_actual',sum(r.friends_found_actual),'friends_found_goal',sum(r.friends_found_goal),
            'members_at_lessons_actual',sum(r.lessons_with_members_actual),'members_at_lessons_goal',sum(r.lessons_with_members_goal),
            'sacrament_attendance_actual',sum(r.sacrament_attendance_actual),'sacrament_attendance_goal',sum(r.sacrament_attendance_goal),
            'baptismal_dates_actual',sum(coalesce(r.baptismal_dates_actual,0)),'baptismal_dates_goal',sum(coalesce(r.baptismal_dates_goal,0)),
            'baptisms_confirmations_actual',sum(coalesce(r.baptisms_confirmations_actual,0)),'baptisms_confirmations_goal',sum(coalesce(r.baptisms_confirmations_goal,0)),
            'nm_sacrament_actual',sum(r.new_member_sacrament_actual),'nm_sacrament_goal',sum(r.new_member_sacrament_goal)
        ) AS metrics
        FROM reports r JOIN visible v ON v.area_id = r.area_id
        GROUP BY r.reporting_week_id, r.scope_id
    ), details AS MATERIALIZED (
        SELECT p.zone_id AS scope_id, jsonb_agg(to_jsonb(p) ORDER BY p.district_name,p.area_name,p.unit_name,p.weekly_area_report_id) AS items
        FROM public.call_in_planning_details p
        WHERE p.reporting_week_id = target_reporting_week_id AND p.mission_id = target_mission_id
        GROUP BY p.zone_id
    )
    SELECT coalesce(jsonb_agg(s.item || coalesce(cur.metrics,'{}'::jsonb) || coalesce(prev.goals,'{}'::jsonb)
        || jsonb_build_object('planning_details',coalesce(det.items,'[]'::jsonb)) ORDER BY s.n),'[]'::jsonb) INTO v_result
    FROM jsonb_array_elements(v_rows) WITH ORDINALITY s(item,n)
    LEFT JOIN totals cur ON cur.reporting_week_id = target_reporting_week_id AND cur.scope_id = (s.item->>'zone_id')::bigint
    LEFT JOIN LATERAL (
        SELECT jsonb_object_agg(regexp_replace(m.key,'_goal$','_previous_goal'),m.value) AS goals
        FROM totals t CROSS JOIN LATERAL jsonb_each(t.metrics) m
        WHERE t.reporting_week_id = v_previous_week_id AND t.scope_id = (s.item->>'zone_id')::bigint AND right(m.key,5) = '_goal'
    ) prev ON true
    LEFT JOIN details det ON det.scope_id = (s.item->>'zone_id')::bigint;
    RETURN v_result;
END;
$function$;

-- Same callers as 014: signed-in users, service_role and postgres. Never PUBLIC or anon (these now run as owner).
REVOKE ALL ON FUNCTION public.get_dl_call_in_summary_with_planning(bigint,bigint),
    public.get_zl_call_in_summary_with_planning(bigint,bigint),
    public.get_mission_call_in_summary_with_planning(bigint,bigint) FROM PUBLIC, anon;
GRANT EXECUTE ON FUNCTION public.get_dl_call_in_summary_with_planning(bigint,bigint),
    public.get_zl_call_in_summary_with_planning(bigint,bigint),
    public.get_mission_call_in_summary_with_planning(bigint,bigint) TO authenticated, service_role, postgres;

-- Check: the summaries run as owner with a fixed search_path, only the intended roles may run them, and both
-- views still check as the caller.
DO $$
DECLARE
  found text;
BEGIN
  SELECT string_agg(p.oid::regprocedure::text, ', ') INTO found
  FROM pg_proc p
  WHERE p.oid IN ('public.get_dl_call_in_summary_with_planning(bigint,bigint)'::regprocedure,
                  'public.get_zl_call_in_summary_with_planning(bigint,bigint)'::regprocedure,
                  'public.get_mission_call_in_summary_with_planning(bigint,bigint)'::regprocedure)
    AND (NOT p.prosecdef OR pg_get_userbyid(p.proowner) <> 'postgres'
         OR NOT coalesce(p.proconfig, '{}') @> ARRAY['search_path=public, pg_temp']
         OR has_function_privilege('public', p.oid, 'EXECUTE') OR has_function_privilege('anon', p.oid, 'EXECUTE')
         OR NOT has_function_privilege('authenticated', p.oid, 'EXECUTE')
         OR NOT has_function_privilege('service_role', p.oid, 'EXECUTE'));
  IF found IS NOT NULL THEN
    RAISE EXCEPTION 'Unexpected owner, search_path or EXECUTE rights on: %', found;
  END IF;
  SELECT string_agg(c.oid::regclass::text, ', ') INTO found
  FROM pg_class c
  WHERE c.oid IN ('public.weekly_area_reports_with_planning_metrics'::regclass, 'public.call_in_planning_details'::regclass)
    AND NOT coalesce(c.reloptions, '{}') @> ARRAY['security_invoker=true'];
  IF found IS NOT NULL THEN
    RAISE EXCEPTION 'These views must check row-level security as the caller: %', found;
  END IF;
END $$;

NOTIFY pgrst, 'reload schema';
COMMIT;

-- Verify (read-only, after applying):
-- 1. Run 019 again as supabase_admin (see Apply); it must end with COMMIT.
-- 2. Time the mission summary as an AP (use an AP's id from public.user_profiles) for the week Call-ins opens
--    with: the latest week up to the current reporting Sunday, the same rule as /api/callins. (The current
--    Sunday's own week only exists once a companionship opens Planning, so do not pick it by date.) The command
--    only reads and rolls back:
--   docker exec gfm-beta-supabase-db-1 psql -U postgres -d postgres -c '\timing on' -c 'BEGIN READ ONLY' -c "SELECT set_config('request.jwt.claims', json_build_object('sub','<AP user id>','role','authenticated')::text, true)" -c 'SET LOCAL ROLE authenticated' -c 'SELECT rw.sunday, jsonb_array_length(public.get_mission_call_in_summary_with_planning(2, rw.id)) AS zones FROM (SELECT id, sunday FROM public.reporting_weeks WHERE sunday <= public.current_reporting_sunday() ORDER BY sunday DESC LIMIT 1) rw' -c 'ROLLBACK'
--    Expect the latest reported Sunday and the number of zones (on Beta on 27 Sep 2026: 2026-09-20 and 6) in
--    about a second (before 020 it did not finish). No row, or 0 zones, means no week was found and nothing was
--    timed.
-- 3. Open Call-ins Alpha as an AP, a zone leader and a district leader: each week opens within a few seconds and
--    shows the same numbers and details as before.

-- Rollback, as postgres, in two levels. Both put back exactly what was there before this file: the three
-- functions are pg_get_functiondef output from Beta before 020, the two views are the 014 text (it re-creates
-- Beta's pre-020 views exactly; U&'' escapes as above). Rights are not touched in either direction. Only the
-- lines with the level's marker are run, joined with plain line feeds (so Windows line ends cannot creep into
-- the functions). Each step stops after a 10-second lock timeout instead of making Planning and Grafana wait;
-- then cancel the blocking query (see Apply) and run the same command again. Both levels are safe to repeat.
-- A. First choice: the three summaries only (lines starting "--rbf"). They go back to their pre-020 code, which
--    runs as the caller under row-level security, and keep reading the faster view of change 1, so Call-ins
--    stay usable (a few seconds for the mission instead of minutes). It prints
--    "functions fingerprint 43c3c1586657225983e1de46f48c0234" (these three on Beta before 020); any other value
--    means something differs.
--      ((Get-Content portal-api/migrations/020_callins_performance.sql) -match '^--rbf( |$)' -replace '^--rbf ?','') -join "`n" |
--        docker exec -i gfm-beta-supabase-db-1 psql -U postgres -d postgres -v ON_ERROR_STOP=1
--    (Git Bash: sed -n -E 's/\r$//;s/^--rbf( |$)//p' portal-api/migrations/020_callins_performance.sql | docker exec -i ...)
-- B. Everything (lines starting "--rbf" or "--rb"), only if the views themselves are the suspect: A, then the
--    two views as before 020. Call-ins are then as slow as before 020 (the mission summary does not finish). It
--    prints the functions fingerprint above, then "fingerprint 80c085fd41af406a3daeb65daff6ee1e" (all five
--    definitions on Beta before 020, 26 Sep 2026). If the view step stops on the lock timeout, A is already
--    done; run B again.
--      ((Get-Content portal-api/migrations/020_callins_performance.sql) -match '^--rbf?( |$)' -replace '^--rbf? ?','') -join "`n" |
--        docker exec -i gfm-beta-supabase-db-1 psql -U postgres -d postgres -v ON_ERROR_STOP=1
--    (Git Bash: sed -n -E 's/\r$//;s/^--rbf?( |$)//p' portal-api/migrations/020_callins_performance.sql | docker exec -i ...)
--rbf BEGIN;
--rbf SET LOCAL lock_timeout = '10s';
--rbf CREATE OR REPLACE FUNCTION public.get_dl_call_in_summary_with_planning(target_district_id bigint, target_reporting_week_id bigint)
--rbf  RETURNS jsonb
--rbf  LANGUAGE plpgsql
--rbf  STABLE
--rbf  SET search_path TO 'public', 'pg_temp'
--rbf AS $function$
--rbf DECLARE v_result jsonb;
--rbf BEGIN
--rbf     IF NOT public.can_access_district(target_district_id) OR NOT EXISTS (
--rbf         SELECT 1 FROM public.areas a WHERE a.district_id = target_district_id AND public.can_access_area(a.id)
--rbf     ) THEN RAISE EXCEPTION 'This district is outside your stewardship.' USING ERRCODE = '42501'; END IF;
--rbf     SELECT coalesce(jsonb_agg(to_jsonb(s)
--rbf         || public.get_call_in_planning_metrics(target_reporting_week_id,s.area_id)
--rbf         || public.get_call_in_planning_previous_goals(target_reporting_week_id,s.area_id)
--rbf         || jsonb_build_object('planning_details',coalesce((
--rbf             SELECT jsonb_agg(to_jsonb(p) ORDER BY p.unit_name,p.weekly_area_report_id)
--rbf             FROM public.call_in_planning_details p
--rbf             WHERE p.reporting_week_id = target_reporting_week_id AND p.area_id = s.area_id
--rbf         ),'[]'::jsonb)) ORDER BY s.area_name),'[]'::jsonb) INTO v_result
--rbf     FROM public.get_dl_call_in_summary(target_district_id,target_reporting_week_id) s;
--rbf     RETURN v_result;
--rbf END;
--rbf $function$;
--rbf
--rbf CREATE OR REPLACE FUNCTION public.get_zl_call_in_summary_with_planning(target_zone_id bigint, target_reporting_week_id bigint)
--rbf  RETURNS jsonb
--rbf  LANGUAGE plpgsql
--rbf  STABLE
--rbf  SET search_path TO 'public', 'pg_temp'
--rbf AS $function$
--rbf DECLARE v_result jsonb;
--rbf BEGIN
--rbf     IF NOT public.can_access_zone(target_zone_id) OR NOT EXISTS (
--rbf         SELECT 1 FROM public.areas a JOIN public.districts d ON d.id = a.district_id
--rbf         WHERE d.zone_id = target_zone_id AND public.can_access_area(a.id)
--rbf     ) THEN RAISE EXCEPTION 'This zone is outside your stewardship.' USING ERRCODE = '42501'; END IF;
--rbf     SELECT coalesce(jsonb_agg(to_jsonb(s)
--rbf         || public.get_call_in_planning_metrics(target_reporting_week_id,NULL,s.district_id)
--rbf         || public.get_call_in_planning_previous_goals(target_reporting_week_id,NULL,s.district_id)
--rbf         || jsonb_build_object('planning_details',coalesce((
--rbf             SELECT jsonb_agg(to_jsonb(p) ORDER BY p.area_name,p.unit_name,p.weekly_area_report_id)
--rbf             FROM public.call_in_planning_details p
--rbf             WHERE p.reporting_week_id = target_reporting_week_id AND p.district_id = s.district_id
--rbf         ),'[]'::jsonb)) ORDER BY s.district_name),'[]'::jsonb) INTO v_result
--rbf     FROM public.get_zl_call_in_summary(target_zone_id,target_reporting_week_id) s;
--rbf     RETURN v_result;
--rbf END;
--rbf $function$;
--rbf
--rbf CREATE OR REPLACE FUNCTION public.get_mission_call_in_summary_with_planning(target_mission_id bigint, target_reporting_week_id bigint)
--rbf  RETURNS jsonb
--rbf  LANGUAGE plpgsql
--rbf  STABLE
--rbf  SET search_path TO 'public', 'pg_temp'
--rbf AS $function$
--rbf DECLARE v_result jsonb;
--rbf BEGIN
--rbf     IF NOT public.can_access_mission(target_mission_id) OR NOT EXISTS (
--rbf         SELECT 1 FROM public.areas a JOIN public.districts d ON d.id = a.district_id
--rbf         JOIN public.zones z ON z.id = d.zone_id
--rbf         WHERE z.mission_id = target_mission_id AND public.can_access_area(a.id)
--rbf     ) THEN RAISE EXCEPTION 'This mission is outside your assignment.' USING ERRCODE = '42501'; END IF;
--rbf     SELECT coalesce(jsonb_agg(to_jsonb(s)
--rbf         || public.get_call_in_planning_metrics(target_reporting_week_id,NULL,NULL,s.zone_id)
--rbf         || public.get_call_in_planning_previous_goals(target_reporting_week_id,NULL,NULL,s.zone_id)
--rbf         || jsonb_build_object('planning_details',coalesce((
--rbf             SELECT jsonb_agg(to_jsonb(p) ORDER BY p.district_name,p.area_name,p.unit_name,p.weekly_area_report_id)
--rbf             FROM public.call_in_planning_details p
--rbf             WHERE p.reporting_week_id = target_reporting_week_id AND p.zone_id = s.zone_id
--rbf         ),'[]'::jsonb)) ORDER BY s.zone_name),'[]'::jsonb) INTO v_result
--rbf     FROM public.get_mission_call_in_summary(target_mission_id,target_reporting_week_id) s;
--rbf     RETURN v_result;
--rbf END;
--rbf $function$;
--rbf
--rbf NOTIFY pgrst, 'reload schema';
--rbf COMMIT;
--rbf SELECT 'functions fingerprint ' || md5(string_agg(x, '|' ORDER BY n)) FROM (VALUES
--rbf   (3, pg_get_functiondef('public.get_dl_call_in_summary_with_planning(bigint,bigint)'::regprocedure)),
--rbf   (4, pg_get_functiondef('public.get_zl_call_in_summary_with_planning(bigint,bigint)'::regprocedure)),
--rbf   (5, pg_get_functiondef('public.get_mission_call_in_summary_with_planning(bigint,bigint)'::regprocedure))) v(n, x);
--rb BEGIN;
--rb SET LOCAL lock_timeout = '10s';
--rb CREATE OR REPLACE VIEW public.weekly_area_reports_with_planning_metrics
--rb WITH (security_invoker = true) AS
--rb SELECT mapped.*
--rb FROM public.weekly_area_reports war
--rb LEFT JOIN LATERAL (
--rb     SELECT jsonb_object_agg(wpa.question_key,wpa.answer_number)
--rb         FILTER (WHERE wpa.answer_number IS NOT NULL) AS numbers
--rb     FROM public.weekly_planning_answers wpa WHERE wpa.weekly_area_report_id = war.id
--rb ) answers ON true
--rb CROSS JOIN LATERAL jsonb_populate_record(NULL::public.weekly_area_reports,
--rb     to_jsonb(war) || jsonb_build_object(
--rb         'friends_found_actual',public.planning_kpi_value((answers.numbers->>'friends_found_actual')::numeric,war.friends_found_actual),
--rb         'friends_found_goal',public.planning_kpi_value((answers.numbers->>'friends_found_goal')::numeric,war.friends_found_goal),
--rb         'lessons_with_members_actual',public.planning_kpi_value((answers.numbers->>'members_at_lessons_actual')::numeric,war.lessons_with_members_actual),
--rb         'lessons_with_members_goal',public.planning_kpi_value((answers.numbers->>'members_at_lessons_goal')::numeric,war.lessons_with_members_goal),
--rb         'sacrament_attendance_actual',public.planning_kpi_value((answers.numbers->>'sacrament_attendance_actual')::numeric,war.sacrament_attendance_actual),
--rb         'sacrament_attendance_goal',public.planning_kpi_value((answers.numbers->>'sacrament_attendance_goal')::numeric,war.sacrament_attendance_goal),
--rb         'baptismal_dates_actual',public.planning_kpi_value((answers.numbers->>'baptismal_dates_actual')::numeric,war.baptismal_dates_actual),
--rb         'baptismal_dates_goal',public.planning_kpi_value((answers.numbers->>'baptismal_dates_goal')::numeric,war.baptismal_dates_goal),
--rb         'baptisms_confirmations_actual',public.planning_kpi_value((answers.numbers->>'baptisms_confirmations_actual')::numeric,war.baptisms_confirmations_actual),
--rb         'baptisms_confirmations_goal',public.planning_kpi_value((answers.numbers->>'baptisms_confirmations_goal')::numeric,war.baptisms_confirmations_goal),
--rb         'new_member_sacrament_actual',public.planning_kpi_value((answers.numbers->>'nm_sacrament_attendance')::numeric,war.new_member_sacrament_actual),
--rb         'new_member_sacrament_goal',public.planning_kpi_value((answers.numbers->>'nm_sacrament_attendance_goal')::numeric,war.new_member_sacrament_goal)
--rb     )) mapped;
--rb
--rb CREATE OR REPLACE VIEW public.call_in_planning_details
--rb WITH (security_invoker = true) AS
--rb SELECT r.id AS weekly_area_report_id, r.reporting_week_id, rw.sunday AS reporting_sunday,
--rb        r.area_id, a.name AS area_name, d.id AS district_id, d.name AS district_name,
--rb        z.id AS zone_id, z.name AS zone_name, z.mission_id,
--rb        r.unit_id, u.name AS unit_name, r.status,
--rb        coalesce(goals.items,'[]'::jsonb) || jsonb_build_array(
--rb            jsonb_build_object('key','lessons_with_friends_goal','label','Lessons with friends',
--rb                'section','Teaching and follow-up','actual',r.lessons_with_friends_actual,'goal',r.lessons_with_friends_goal),
--rb            jsonb_build_object('key','follow_up_lessons_goal','label','Follow-up lessons',
--rb                'section','Teaching and follow-up','actual',r.follow_up_lessons_actual,'goal',r.follow_up_lessons_goal)
--rb        ) || coalesce(member_goals.items,'[]'::jsonb) AS other_goals,
--rb        coalesce(plans.items,'[]'::jsonb) AS action_plans,
--rb        nullif(btrim(answers.texts->>'weekly_action_plan'),'') AS weekly_action_plan,
--rb        nullif(btrim(answers.texts->>'information_up_chain'),'') AS information_up_chain
--rb FROM public.weekly_area_reports_with_planning_metrics r
--rb JOIN public.reporting_weeks rw ON rw.id = r.reporting_week_id
--rb JOIN public.areas a ON a.id = r.area_id
--rb JOIN public.districts d ON d.id = a.district_id
--rb JOIN public.zones z ON z.id = d.zone_id
--rb LEFT JOIN public.units u ON u.id = r.unit_id
--rb LEFT JOIN LATERAL (
--rb     SELECT jsonb_object_agg(wpa.question_key,wpa.answer_number)
--rb                FILTER (WHERE wpa.answer_number IS NOT NULL) AS numbers,
--rb            jsonb_object_agg(wpa.question_key,wpa.answer_text)
--rb                FILTER (WHERE wpa.answer_text IS NOT NULL) AS texts
--rb     FROM public.weekly_planning_answers wpa WHERE wpa.weekly_area_report_id = r.id
--rb ) answers ON true
--rb LEFT JOIN LATERAL (
--rb     WITH goal_definitions AS (
--rb         SELECT q.question_key, q.question_label, q.section_title, q.section_order, q.question_order
--rb         FROM public.active_planning_questions q
--rb         WHERE right(q.question_key,5) = '_goal'
--rb           AND q.question_key <> ALL(ARRAY['nm_sacrament_attendance_goal','baptisms_confirmations_goal',
--rb               'baptismal_dates_goal','sacrament_attendance_goal','members_at_lessons_goal','friends_found_goal',
--rb               'lessons_with_friends_goal','follow_up_lessons_goal'])
--rb         UNION ALL
--rb         SELECT wpa.question_key,initcap(replace(wpa.question_key,'_',' ')),
--rb                'Additional goals',999,999
--rb         FROM public.weekly_planning_answers wpa
--rb         WHERE wpa.weekly_area_report_id = r.id AND right(wpa.question_key,5) = '_goal'
--rb           AND NOT EXISTS (SELECT 1 FROM public.active_planning_questions q WHERE q.question_key = wpa.question_key)
--rb     )
--rb     SELECT jsonb_agg(jsonb_build_object(
--rb         'key',q.question_key,
--rb         'label',regexp_replace(q.question_label,U&'\s*!2014.*$' UESCAPE '!',''),
--rb         'section',q.section_title,
--rb         'goal',(answers.numbers->>q.question_key)::numeric,
--rb         'actual',(SELECT sum((answers.numbers->>actual_key)::numeric) FROM unnest(
--rb             CASE q.question_key
--rb                 WHEN 'member_meals_goal' THEN ARRAY['member_meals_active_actual','member_meals_less_active_actual','member_meals_part_member_actual']
--rb                 WHEN 'member_visits_goal' THEN ARRAY['member_visits_active_actual','member_visits_less_active_actual','member_visits_part_member_actual']
--rb                 ELSE ARRAY[regexp_replace(q.question_key,'_goal$','_actual')]
--rb             END) actual_key)
--rb         ) ORDER BY q.section_order,q.question_order,q.question_key) AS items
--rb     FROM goal_definitions q
--rb ) goals ON true
--rb LEFT JOIN LATERAL (
--rb     SELECT jsonb_agg(jsonb_build_object(
--rb         'key','new_member_lessons_'||wnm.id,'label','New member lessons'||coalesce(U&' !00B7 ' UESCAPE '!'||nm.display_name,''),
--rb         'section','New member follow-up','actual',wnm.lessons_actual,'goal',wnm.lessons_goal
--rb     ) ORDER BY wnm.display_order,wnm.id) AS items
--rb     FROM public.weekly_new_members wnm LEFT JOIN public.new_members nm ON nm.id = wnm.new_member_id
--rb     WHERE wnm.weekly_area_report_id = r.id AND wnm.lessons_goal IS NOT NULL
--rb ) member_goals ON true
--rb LEFT JOIN LATERAL (
--rb     SELECT jsonb_agg(jsonb_build_object(
--rb         'key',wpa.question_key,
--rb         'label',regexp_replace(regexp_replace(coalesce(q.question_label,initcap(replace(wpa.question_key,'_',' '))),'^Optional: ',''),U&'\s*!2014 Action Plan$' UESCAPE '!',''),
--rb         'text',btrim(wpa.answer_text),
--rb         'core',wpa.question_key = ANY(ARRAY['nm_sacrament_attendance_plan','baptisms_confirmations_plan',
--rb             'baptismal_dates_plan','sacrament_attendance_plan','members_at_lessons_plan','friends_found_plan'])
--rb     ) ORDER BY q.section_order,q.question_order,wpa.question_key) AS items
--rb     FROM public.weekly_planning_answers wpa
--rb     LEFT JOIN public.active_planning_questions q ON q.question_key = wpa.question_key
--rb     WHERE wpa.weekly_area_report_id = r.id AND right(wpa.question_key,5) = '_plan'
--rb       AND wpa.question_key <> 'weekly_action_plan' AND nullif(btrim(wpa.answer_text),'') IS NOT NULL
--rb ) plans ON true
--rb WHERE public.can_access_area(r.area_id);
--rb
--rb NOTIFY pgrst, 'reload schema';
--rb COMMIT;
--rb SELECT 'fingerprint ' || md5(string_agg(x, '|' ORDER BY n)) FROM (VALUES
--rb   (1, pg_get_viewdef('public.weekly_area_reports_with_planning_metrics'::regclass, true)),
--rb   (2, pg_get_viewdef('public.call_in_planning_details'::regclass, true)),
--rb   (3, pg_get_functiondef('public.get_dl_call_in_summary_with_planning(bigint,bigint)'::regprocedure)),
--rb   (4, pg_get_functiondef('public.get_zl_call_in_summary_with_planning(bigint,bigint)'::regprocedure)),
--rb   (5, pg_get_functiondef('public.get_mission_call_in_summary_with_planning(bigint,bigint)'::regprocedure))) v(n, x);
