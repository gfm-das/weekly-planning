-- GFM baseline schema: a FRESH install starts here (installer prep, round 12, step 6).
--
-- What it is: the whole database of the mission system as it was after migration 040 (4 Oct 2026): every table, view,
-- function, trigger, policy and right of the schemas public, dashboards and portal, plus the few rows a new system needs
-- (the mission, the planning questions with their sections, choices and rules, the Archetypal Health settings).
-- The numbered files in migrations/ are the story of how it got here; they cannot be replayed on an empty database,
-- because the first tables came from an older system. A new change is a new numbered migration (041 and up) applied
-- after this file. A running system never applies this file.
--
-- How to apply (empty Supabase database, as supabase_admin; the Supabase stack must be up so the roles and the auth
-- schema exist):
--   Get-Content portal-api/baseline/000_baseline.sql -Raw | docker exec -i gfm-beta-supabase-db-1 psql -U supabase_admin -d postgres -v ON_ERROR_STOP=1 --single-transaction
-- then migration 019 (the rights check), as every migration is followed by it:
--   Get-Content portal-api/migrations/019_restrict_public_functions.sql -Raw | docker exec -i gfm-beta-supabase-db-1 psql -U supabase_admin -d postgres -v ON_ERROR_STOP=1
-- Checked by building an empty database from it and comparing it with the live one: portal-api/baseline/check-baseline.ps1.
-- Made with pg_dump --schema-only (grants kept, comments left out) from the live database; the retired grafana_readonly
-- role is left out. Rollback: this file only ever runs on an empty database; there is nothing to roll back but dropping it.

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'gfm_dashboard_reader') THEN
    CREATE ROLE gfm_dashboard_reader LOGIN NOINHERIT;
  END IF;
  ALTER ROLE gfm_dashboard_reader LOGIN NOINHERIT NOCREATEDB NOCREATEROLE CONNECTION LIMIT 10;
  -- The password is set once afterwards: dataease/set-reader-password.ps1.
END $$;
GRANT gfm_dashboard_reader TO postgres;

--
-- PostgreSQL database dump
--

-- Dumped from database version 15.8
-- Dumped by pg_dump version 15.8

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: dashboards; Type: SCHEMA; Schema: -; Owner: postgres
--

CREATE SCHEMA dashboards;


ALTER SCHEMA dashboards OWNER TO postgres;

--
-- Name: portal; Type: SCHEMA; Schema: -; Owner: postgres
--

CREATE SCHEMA portal;


ALTER SCHEMA portal OWNER TO postgres;

--
-- Name: public; Type: SCHEMA; Schema: -; Owner: pg_database_owner
--

CREATE SCHEMA IF NOT EXISTS public;


ALTER SCHEMA public OWNER TO pg_database_owner;

--
-- Name: archetype_plan_rows(); Type: FUNCTION; Schema: dashboards; Owner: postgres
--

CREATE FUNCTION dashboards.archetype_plan_rows() RETURNS TABLE(reporting_week_id bigint, area_id bigint, first_time_first_week_sacrament numeric, member_meals_active numeric, member_meals_less_active numeric, member_meals_part_member numeric, member_visits_active numeric, member_visits_less_active numeric, member_visits_part_member numeric, member_referral_asks numeric, lessons_asked_referral numeric, facebook_finding_days numeric, facebook_friends_found numeric, youth_activities numeric, service_hours numeric, less_active_sacrament numeric, new_members_on_plan bigint, new_member_lessons numeric, new_members_at_church bigint)
    LANGUAGE sql STABLE SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'pg_temp'
    AS $$
  WITH numbers(kpi, question_key, sheet_column) AS (
    VALUES
      ('first_time_first_week_sacrament', 'sacrament_first_time_first_week',
       'numberofpeoplewhoattendedsacramentforthefirsttimethatwerefoundthisweek'),
      ('member_meals_active', 'member_meals_active_actual', 'membermealswithactivememberactual'),
      ('member_meals_less_active', 'member_meals_less_active_actual', 'membermealswithlessactivememberactual'),
      ('member_meals_part_member', 'member_meals_part_member_actual', 'membermealswithpartmemberfamilyactual'),
      ('member_visits_active', 'member_visits_active_actual', 'membervisitswithactivememberactual'),
      ('member_visits_less_active', 'member_visits_less_active_actual', 'membervisitswithlessactivememberactual'),
      ('member_visits_part_member', 'member_visits_part_member_actual', 'membervisitswithpartmemberfamilyactual'),
      ('member_referral_asks', 'member_referral_asks_actual',
       'outofallofyourmembermealsandvisitshowmanytimesdidyouaskforafriendreferralactual'),
      ('lessons_asked_referral', NULL,
       'lessonsintheweekwhereyouaskeddoyouknowsomeonewhowouldbeinterestedinactual'),
      ('facebook_finding_days', 'facebook_finding_days', 'daysoffacebookfinding'),
      ('facebook_friends_found', 'facebook_friends_found', 'friendsfoundthroughfacebook'),
      ('youth_activities', 'youth_activities_actual', 'youthactivitiesactual'),
      ('service_hours', 'service_hours_actual', 'servicehoursactual'),
      ('less_active_sacrament', 'less_active_sacrament_actual',
       'numberoflessactivemembersthatyouvebeenworkingwithwhoattendedsacrament')
  ), portal_answers AS (
    SELECT a.weekly_area_report_id AS report_id, n.kpi, sum(a.answer_number) AS value
    FROM public.weekly_planning_answers a
    JOIN numbers n ON n.question_key = a.question_key
    WHERE a.answer_number IS NOT NULL
    GROUP BY 1, 2
  ), sheet_rows AS MATERIALIZED (
    SELECT h.weekly_area_report_id AS report_id, x->>'source_question_label' AS label,
           (x->>'answer_number')::numeric AS value
    FROM public.historical_planning_details h
    CROSS JOIN LATERAL jsonb_array_elements(h.answers) x
    WHERE jsonb_typeof(x->'answer_number') = 'number'
  ), sheet_labels AS (  -- folding each distinct column name once is much faster than folding every answer
    SELECT l.label, n.kpi
    FROM (SELECT DISTINCT label FROM sheet_rows) l
    JOIN numbers n ON n.sheet_column = regexp_replace(lower(l.label), '[^a-z0-9]', '', 'g')
  ), sheet_answers AS (
    SELECT r.report_id, l.kpi, sum(r.value) AS value
    FROM sheet_rows r JOIN sheet_labels l ON l.label = r.label
    GROUP BY 1, 2
  ), answers AS (  -- one value per plan and number: the portal's answer wins over the imported one
    SELECT coalesce(p.report_id, s.report_id) AS report_id, coalesce(p.kpi, s.kpi) AS kpi,
           coalesce(p.value, s.value) AS value
    FROM portal_answers p
    FULL JOIN sheet_answers s ON s.report_id = p.report_id AND s.kpi = p.kpi
  ), portal_new_members AS (
    SELECT m.weekly_area_report_id AS report_id, count(*) AS people, sum(m.lessons_actual) AS lessons,
           count(*) FILTER (WHERE m.at_church_this_sunday) AS at_church
    FROM public.weekly_new_members m
    GROUP BY 1
  ), sheet_new_members AS (
    SELECT h.weekly_area_report_id AS report_id, count(*) AS people,
           sum(CASE WHEN jsonb_typeof(x->'lessons_actual') = 'number' THEN (x->>'lessons_actual')::numeric END) AS lessons,
           count(*) FILTER (WHERE x->>'at_church_this_sunday' = 'true') AS at_church
    FROM public.historical_planning_details h
    CROSS JOIN LATERAL jsonb_array_elements(h.new_members) x
    GROUP BY 1
  ), new_members AS (  -- the portal's new member cards of a plan win over the imported ones
    SELECT coalesce(p.report_id, s.report_id) AS report_id,
           CASE WHEN p.report_id IS NOT NULL THEN p.people ELSE s.people END AS people,
           CASE WHEN p.report_id IS NOT NULL THEN p.lessons ELSE s.lessons END AS lessons,
           CASE WHEN p.report_id IS NOT NULL THEN p.at_church ELSE s.at_church END AS at_church
    FROM portal_new_members p
    FULL JOIN sheet_new_members s ON s.report_id = p.report_id
  ), plans AS (  -- an area may have several plans in a week (one per ward or branch): they are added up
    SELECT r.id, r.reporting_week_id, r.area_id FROM public.weekly_area_reports r
  ), answer_totals AS (
    SELECT r.reporting_week_id, r.area_id, a.kpi, sum(a.value) AS value
    FROM plans r JOIN answers a ON a.report_id = r.id
    GROUP BY 1, 2, 3
  ), new_member_totals AS (
    SELECT r.reporting_week_id, r.area_id, sum(m.people)::bigint AS people, sum(m.lessons) AS lessons,
           sum(m.at_church)::bigint AS at_church
    FROM plans r JOIN new_members m ON m.report_id = r.id
    GROUP BY 1, 2
  ), area_weeks AS (
    SELECT DISTINCT reporting_week_id, area_id FROM plans
  )
  SELECT w.reporting_week_id, w.area_id,
         max(t.value) FILTER (WHERE t.kpi = 'first_time_first_week_sacrament'),
         max(t.value) FILTER (WHERE t.kpi = 'member_meals_active'),
         max(t.value) FILTER (WHERE t.kpi = 'member_meals_less_active'),
         max(t.value) FILTER (WHERE t.kpi = 'member_meals_part_member'),
         max(t.value) FILTER (WHERE t.kpi = 'member_visits_active'),
         max(t.value) FILTER (WHERE t.kpi = 'member_visits_less_active'),
         max(t.value) FILTER (WHERE t.kpi = 'member_visits_part_member'),
         max(t.value) FILTER (WHERE t.kpi = 'member_referral_asks'),
         max(t.value) FILTER (WHERE t.kpi = 'lessons_asked_referral'),
         max(t.value) FILTER (WHERE t.kpi = 'facebook_finding_days'),
         max(t.value) FILTER (WHERE t.kpi = 'facebook_friends_found'),
         max(t.value) FILTER (WHERE t.kpi = 'youth_activities'),
         max(t.value) FILTER (WHERE t.kpi = 'service_hours'),
         max(t.value) FILTER (WHERE t.kpi = 'less_active_sacrament'),
         n.people, n.lessons, n.at_church
  FROM area_weeks w
  LEFT JOIN answer_totals t ON t.reporting_week_id = w.reporting_week_id AND t.area_id = w.area_id
  LEFT JOIN new_member_totals n ON n.reporting_week_id = w.reporting_week_id AND n.area_id = w.area_id
  GROUP BY w.reporting_week_id, w.area_id, n.people, n.lessons, n.at_church
$$;


ALTER FUNCTION dashboards.archetype_plan_rows() OWNER TO postgres;

--
-- Name: area_week_rows(); Type: FUNCTION; Schema: dashboards; Owner: postgres
--

CREATE FUNCTION dashboards.area_week_rows() RETURNS TABLE(week timestamp with time zone, sunday date, reporting_week_id bigint, previous_reporting_week_id bigint, mission_id bigint, zone_id bigint, zone text, district_id bigint, district text, area_id bigint, area text, unit_id bigint, unit text, status text, submitted boolean, friends_found_actual integer, friends_found_goal integer, friends_found_previous_goal bigint, baptisms_confirmations_actual integer, baptisms_confirmations_goal integer, baptisms_confirmations_previous_goal bigint, baptismal_dates_actual integer, baptismal_dates_goal integer, baptismal_dates_previous_goal bigint, sacrament_attendance_actual integer, sacrament_attendance_goal integer, sacrament_attendance_previous_goal bigint, members_at_lessons_actual integer, members_at_lessons_goal integer, members_at_lessons_previous_goal bigint, new_member_sacrament_actual integer, new_member_sacrament_goal integer, new_member_sacrament_previous_goal bigint, first_time_sacrament_actual integer, lessons_with_friends_actual integer, lessons_with_friends_goal integer, follow_up_lessons_actual integer, follow_up_lessons_goal integer)
    LANGUAGE sql STABLE SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'pg_temp'
    AS $$
  WITH weeks AS (
    SELECT rw.id, rw.sunday, lag(rw.id) OVER (ORDER BY rw.sunday) AS previous_id
    FROM public.reporting_weeks rw
  ), reports AS MATERIALIZED (
    SELECT v.* FROM public.weekly_area_reports_with_planning_metrics v
  ), goals AS (
    SELECT r.reporting_week_id, r.area_id, r.unit_id,
           sum(r.friends_found_goal) AS friends_found,
           sum(r.baptisms_confirmations_goal) AS baptisms_confirmations,
           sum(r.baptismal_dates_goal) AS baptismal_dates,
           sum(r.sacrament_attendance_goal) AS sacrament_attendance,
           sum(r.lessons_with_members_goal) AS members_at_lessons,
           sum(r.new_member_sacrament_goal) AS new_member_sacrament
    FROM reports r
    GROUP BY r.reporting_week_id, r.area_id, r.unit_id
  )
  SELECT (w.sunday + time '12:00') AT TIME ZONE 'Europe/Berlin', w.sunday, w.id, w.previous_id,
         z.mission_id, z.id, z.name, d.id, d.name, a.id, a.name, u.id, u.name,
         r.status, r.status IN ('SUBMITTED', 'LOCKED'),
         r.friends_found_actual, r.friends_found_goal, p.friends_found,
         r.baptisms_confirmations_actual, r.baptisms_confirmations_goal, p.baptisms_confirmations,
         r.baptismal_dates_actual, r.baptismal_dates_goal, p.baptismal_dates,
         r.sacrament_attendance_actual, r.sacrament_attendance_goal, p.sacrament_attendance,
         r.lessons_with_members_actual, r.lessons_with_members_goal, p.members_at_lessons,
         r.new_member_sacrament_actual, r.new_member_sacrament_goal, p.new_member_sacrament,
         r.first_time_sacrament_actual,
         r.lessons_with_friends_actual, r.lessons_with_friends_goal,
         r.follow_up_lessons_actual, r.follow_up_lessons_goal
  FROM reports r
  JOIN weeks w ON w.id = r.reporting_week_id
  JOIN public.areas a ON a.id = r.area_id
  JOIN public.districts d ON d.id = a.district_id
  JOIN public.zones z ON z.id = d.zone_id
  LEFT JOIN public.units u ON u.id = r.unit_id
  LEFT JOIN goals p ON p.reporting_week_id = w.previous_id AND p.area_id = r.area_id
                   AND p.unit_id IS NOT DISTINCT FROM r.unit_id
$$;


ALTER FUNCTION dashboards.area_week_rows() OWNER TO postgres;

--
-- Name: touch_presentation_access(); Type: FUNCTION; Schema: portal; Owner: postgres
--

CREATE FUNCTION portal.touch_presentation_access() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'portal', 'pg_temp'
    AS $$
BEGIN
  NEW.updated_at := now();
  RETURN NEW;
END;
$$;


ALTER FUNCTION portal.touch_presentation_access() OWNER TO postgres;

--
-- Name: archive_baptismal_date_person(bigint, text); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.archive_baptismal_date_person(target_baptismal_date_person_id bigint, archive_reason text) RETURNS void
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'public', 'pg_temp'
    AS $$
declare
    v_area_id bigint;
begin

    if archive_reason not in (
        'no_longer_on_date',
        'moved_out_of_mission',
        'duplicate',
        'other'
    ) then
        raise exception 'Invalid archive reason.';
    end if;


    select bdpa.area_id
    into v_area_id
    from public.baptismal_date_person_area_assignments bdpa
    where bdpa.baptismal_date_person_id =
              target_baptismal_date_person_id
      and bdpa.end_date is null;


    if v_area_id is null then
        raise exception
            'Person does not have a current area assignment.';
    end if;


    if not public.can_access_area(v_area_id) then
        raise exception
            'You do not have permission to end tracking for this person.';
    end if;


    update public.baptismal_date_person_area_assignments
    set
        end_date = current_date,
        transfer_reason = archive_reason
    where baptismal_date_person_id =
              target_baptismal_date_person_id
      and end_date is null;


    update public.baptismal_date_people
    set
        tracking_status = 'ended',
        tracking_ended_at = now(),
        tracking_end_reason = archive_reason,
        updated_at = now()
    where id = target_baptismal_date_person_id;

end;
$$;


ALTER FUNCTION public.archive_baptismal_date_person(target_baptismal_date_person_id bigint, archive_reason text) OWNER TO postgres;

--
-- Name: archive_expired_new_members(); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.archive_expired_new_members() RETURNS integer
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'public', 'pg_temp'
    AS $$
declare
    v_count integer;
begin

    -- Close current area assignments first.
    update public.new_member_area_assignments nmaa
    set
        end_date = current_date,
        transfer_reason = 'one_year'
    where nmaa.end_date is null
      and exists (
          select 1
          from public.new_members nm
          where nm.id = nmaa.new_member_id
            and nm.follow_up_status = 'current'
            and nm.baptism_date is not null
            and nm.baptism_date <= current_date - interval '1 year'
      );


    update public.new_members nm
    set
        follow_up_status = 'ended',
        follow_up_ended_at = now(),
        follow_up_end_reason = 'one_year',

        -- Legacy compatibility.
        active = false,
        inactive_at = now(),
        inactive_reason = 'one_year',

        updated_at = now()
    where nm.follow_up_status = 'current'
      and nm.baptism_date is not null
      and nm.baptism_date <= current_date - interval '1 year';


    get diagnostics v_count = row_count;

    return v_count;

end;
$$;


ALTER FUNCTION public.archive_expired_new_members() OWNER TO postgres;

--
-- Name: archive_new_member(bigint, text); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.archive_new_member(target_new_member_id bigint, archive_reason text) RETURNS void
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'public', 'pg_temp'
    AS $$
declare
    v_area_id bigint;
begin

    if archive_reason is null
       or archive_reason not in (
            'moved_out_of_mission',
            'record_removed',
            'deceased',
            'duplicate',
            'other'
       ) then
        raise exception
            'Invalid follow-up end reason.';
    end if;


    select nmaa.area_id
    into v_area_id
    from public.new_member_area_assignments nmaa
    where nmaa.new_member_id = target_new_member_id
      and nmaa.end_date is null;


    if v_area_id is null then
        raise exception
            'New Member does not have a current area assignment.';
    end if;


    if not public.can_access_area(v_area_id) then
        raise exception
            'You do not have permission to end follow-up for this New Member.';
    end if;


    -- End current area assignment.
    update public.new_member_area_assignments
    set
        end_date = current_date,
        transfer_reason = archive_reason
    where new_member_id = target_new_member_id
      and end_date is null;


    -- New terminology.
    update public.new_members
    set
        follow_up_status = 'ended',
        follow_up_ended_at = now(),
        follow_up_end_reason = archive_reason,

        -- Legacy compatibility fields.
        active = false,
        inactive_at = now(),
        inactive_reason =
            case
                when archive_reason = 'one_year'
                    then 'one_year'
                else 'other'
            end,

        updated_at = now()
    where id = target_new_member_id;

end;
$$;


ALTER FUNCTION public.archive_new_member(target_new_member_id bigint, archive_reason text) OWNER TO postgres;

--
-- Name: can_access_area(bigint); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.can_access_area(target_area_id bigint) RETURNS boolean
    LANGUAGE plpgsql STABLE SECURITY DEFINER
    SET search_path TO 'public', 'pg_temp'
    AS $$
BEGIN
  -- Migration 037: the same question as migration 013, in plpgsql so its plan is kept for the whole connection.
  RETURN (
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
    )
  );
END
$$;


ALTER FUNCTION public.can_access_area(target_area_id bigint) OWNER TO postgres;

--
-- Name: can_access_district(bigint); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.can_access_district(target_district_id bigint) RETURNS boolean
    LANGUAGE sql STABLE SECURITY DEFINER
    SET search_path TO 'public', 'pg_temp'
    AS $$
    SELECT EXISTS (
        SELECT 1 FROM public.user_profiles up
        JOIN public.districts d ON d.id = target_district_id
        JOIN public.zones z ON z.id = d.zone_id
        WHERE up.id = auth.uid() AND up.active = true
          AND (
              -- President and Data Analyst (main or additional role)
              up.app_role IN ('PRESIDENT','DATA_ADMIN') OR 'DATA_ADMIN' = ANY(up.additional_roles)
              -- Leadership: DL of this district, ZL of its zone, AP of its mission
              OR EXISTS (
                  SELECT 1 FROM public.leadership_assignments la
                  WHERE la.missionary_id = up.missionary_id
                    AND la.start_date <= CURRENT_DATE
                    AND (la.end_date IS NULL OR la.end_date >= CURRENT_DATE)
                    AND ((la.role = 'DL' AND la.district_id = target_district_id)
                         OR (la.role = 'ZL' AND la.zone_id = d.zone_id)
                         OR (la.role = 'AP' AND la.mission_id = z.mission_id))
              )
          )
    );
$$;


ALTER FUNCTION public.can_access_district(target_district_id bigint) OWNER TO postgres;

--
-- Name: can_access_mission(bigint); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.can_access_mission(target_mission_id bigint) RETURNS boolean
    LANGUAGE sql STABLE SECURITY DEFINER
    SET search_path TO 'public', 'pg_temp'
    AS $$
    SELECT EXISTS (
        SELECT 1 FROM public.user_profiles up
        WHERE up.id = auth.uid() AND up.active
          AND (
              -- Data Analyst, as the main role or an additional role
              up.app_role = 'DATA_ADMIN' OR 'DATA_ADMIN' = ANY(up.additional_roles)
              -- AP: a current AP assignment in this mission
              OR EXISTS (
                  SELECT 1 FROM public.leadership_assignments la
                  WHERE la.missionary_id = up.missionary_id AND la.role = 'AP'
                    AND la.mission_id = target_mission_id
                    AND la.start_date <= CURRENT_DATE
                    AND (la.end_date IS NULL OR la.end_date >= CURRENT_DATE)
              )
              -- President: a current missionary or leadership assignment in this mission
              OR (up.app_role = 'PRESIDENT' AND (
                  EXISTS (
                      SELECT 1 FROM public.missionary_assignments ma
                      JOIN public.areas a ON a.id = ma.area_id
                      JOIN public.districts d ON d.id = a.district_id
                      JOIN public.zones z ON z.id = d.zone_id
                      WHERE ma.missionary_id = up.missionary_id
                        AND ma.start_date <= CURRENT_DATE
                        AND (ma.end_date IS NULL OR ma.end_date >= CURRENT_DATE)
                        AND z.mission_id = target_mission_id
                  )
                  OR EXISTS (
                      SELECT 1 FROM public.leadership_assignments la
                      LEFT JOIN public.districts ld ON ld.id = la.district_id
                      LEFT JOIN public.zones lz ON lz.id = coalesce(la.zone_id, ld.zone_id)
                      WHERE la.missionary_id = up.missionary_id
                        AND la.start_date <= CURRENT_DATE
                        AND (la.end_date IS NULL OR la.end_date >= CURRENT_DATE)
                        AND coalesce(la.mission_id, lz.mission_id) = target_mission_id
                  )
                  -- 027: or, without a missionary link, this is the account's home mission
                  OR (up.missionary_id IS NULL AND up.home_mission_id = target_mission_id)
              ))
          )
    );
$$;


ALTER FUNCTION public.can_access_mission(target_mission_id bigint) OWNER TO postgres;

--
-- Name: can_access_zone(bigint); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.can_access_zone(target_zone_id bigint) RETURNS boolean
    LANGUAGE sql STABLE SECURITY DEFINER
    SET search_path TO 'public', 'pg_temp'
    AS $$
    SELECT EXISTS (
        SELECT 1 FROM public.user_profiles up
        JOIN public.zones tz ON tz.id = target_zone_id
        WHERE up.id = auth.uid() AND up.active
          AND (
              -- ZL: a current ZL assignment on this zone (STLs have no part in Call-ins)
              EXISTS (
                  SELECT 1 FROM public.leadership_assignments la
                  WHERE la.missionary_id = up.missionary_id AND la.role = 'ZL'
                    AND la.zone_id = target_zone_id
                    AND la.start_date <= CURRENT_DATE
                    AND (la.end_date IS NULL OR la.end_date >= CURRENT_DATE)
              )
              -- AP: a current AP assignment in the zone's mission
              OR EXISTS (
                  SELECT 1 FROM public.leadership_assignments la
                  WHERE la.missionary_id = up.missionary_id AND la.role = 'AP'
                    AND la.mission_id = tz.mission_id
                    AND la.start_date <= CURRENT_DATE
                    AND (la.end_date IS NULL OR la.end_date >= CURRENT_DATE)
              )
              -- President and Data Analyst (main or additional role): a current missionary or leadership assignment
              -- in the zone's mission, as in is_mission_manager_for_area
              OR ((up.app_role IN ('PRESIDENT','DATA_ADMIN') OR 'DATA_ADMIN' = ANY(up.additional_roles)) AND (
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
                  -- 027: or, without a missionary link, the zone is in the account's home mission
                  OR (up.missionary_id IS NULL AND up.home_mission_id = tz.mission_id)
              ))
          )
    );
$$;


ALTER FUNCTION public.can_access_zone(target_zone_id bigint) OWNER TO postgres;

--
-- Name: can_current_user_report_for_unit(bigint); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.can_current_user_report_for_unit(target_unit_id bigint) RETURNS boolean
    LANGUAGE sql STABLE SECURITY DEFINER
    SET search_path TO 'public'
    AS $$
    select exists (
        select 1
        from public.current_user_area_units cuau
        where cuau.unit_id = target_unit_id
    );
$$;


ALTER FUNCTION public.can_current_user_report_for_unit(target_unit_id bigint) OWNER TO postgres;

--
-- Name: can_edit_dl_call_in(bigint); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.can_edit_dl_call_in(target_district_id bigint) RETURNS boolean
    LANGUAGE sql STABLE SECURITY DEFINER
    SET search_path TO 'public', 'pg_temp'
    AS $$
    SELECT public.is_call_in_district_leader(target_district_id)
        OR EXISTS (SELECT 1 FROM public.areas a
                   WHERE a.district_id = target_district_id
                     AND public.is_mission_manager_for_area(a.id));
$$;


ALTER FUNCTION public.can_edit_dl_call_in(target_district_id bigint) OWNER TO postgres;

--
-- Name: can_edit_planning_area(bigint); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.can_edit_planning_area(target_area_id bigint) RETURNS boolean
    LANGUAGE sql STABLE SECURITY DEFINER
    SET search_path TO 'public', 'pg_temp'
    AS $$
    SELECT public.is_mission_manager_for_area(target_area_id)
        OR public.is_current_user_area(target_area_id);
$$;


ALTER FUNCTION public.can_edit_planning_area(target_area_id bigint) OWNER TO postgres;

--
-- Name: can_edit_planning_report(bigint); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.can_edit_planning_report(target_report_id bigint) RETURNS boolean
    LANGUAGE sql STABLE SECURITY DEFINER
    SET search_path TO 'public', 'pg_temp'
    AS $$
    SELECT EXISTS (
        SELECT 1 FROM public.weekly_area_reports war
        WHERE war.id = target_report_id AND war.status = 'DRAFT'
          AND public.can_edit_planning_area(war.area_id)
    );
$$;


ALTER FUNCTION public.can_edit_planning_report(target_report_id bigint) OWNER TO postgres;

--
-- Name: can_edit_zl_call_in(bigint); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.can_edit_zl_call_in(target_district_id bigint) RETURNS boolean
    LANGUAGE sql STABLE SECURITY DEFINER
    SET search_path TO 'public', 'pg_temp'
    AS $$
    SELECT EXISTS (SELECT 1 FROM public.districts d
                   WHERE d.id = target_district_id AND public.is_call_in_zone_leader(d.zone_id))
        OR EXISTS (SELECT 1 FROM public.areas a
                   WHERE a.district_id = target_district_id
                     AND public.is_mission_manager_for_area(a.id));
$$;


ALTER FUNCTION public.can_edit_zl_call_in(target_district_id bigint) OWNER TO postgres;

--
-- Name: can_edit_zl_zone_call_in(bigint); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.can_edit_zl_zone_call_in(target_zone_id bigint) RETURNS boolean
    LANGUAGE sql STABLE SECURITY DEFINER
    SET search_path TO 'public', 'pg_temp'
    AS $$
    SELECT public.is_call_in_zone_leader(target_zone_id)
        OR EXISTS (SELECT 1 FROM public.areas a
                   JOIN public.districts d ON d.id = a.district_id
                   WHERE d.zone_id = target_zone_id
                     AND public.is_mission_manager_for_area(a.id));
$$;


ALTER FUNCTION public.can_edit_zl_zone_call_in(target_zone_id bigint) OWNER TO postgres;

--
-- Name: can_unlock_planning_area(bigint); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.can_unlock_planning_area(target_area_id bigint) RETURNS boolean
    LANGUAGE sql STABLE SECURITY DEFINER
    SET search_path TO 'public', 'pg_temp'
    AS $$
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
$$;


ALTER FUNCTION public.can_unlock_planning_area(target_area_id bigint) OWNER TO postgres;

--
-- Name: can_view_call_in(text, bigint); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.can_view_call_in(target_level text, target_id bigint) RETURNS boolean
    LANGUAGE sql STABLE SECURITY DEFINER
    SET search_path TO 'public', 'pg_temp'
    AS $$
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
$$;


ALTER FUNCTION public.can_view_call_in(target_level text, target_id bigint) OWNER TO postgres;

--
-- Name: carry_people_into_report(bigint); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.carry_people_into_report(p_report_id bigint) RETURNS void
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'public', 'pg_temp'
    AS $$
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
$$;


ALTER FUNCTION public.carry_people_into_report(p_report_id bigint) OWNER TO postgres;

--
-- Name: complete_dl_call_in(bigint, bigint); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.complete_dl_call_in(target_district_id bigint, target_reporting_week_id bigint) RETURNS bigint
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'public', 'pg_temp'
    AS $$
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
$$;


ALTER FUNCTION public.complete_dl_call_in(target_district_id bigint, target_reporting_week_id bigint) OWNER TO postgres;

SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: new_members; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.new_members (
    id bigint NOT NULL,
    area_id bigint NOT NULL,
    first_name text NOT NULL,
    last_name text,
    display_name text NOT NULL,
    baptism_date date,
    confirmation_date date,
    active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    stake_id bigint,
    unit_id bigint,
    baptismal_date_extended date,
    finding_source text,
    conversion_success_notes text,
    date_of_birth date,
    age_range text,
    gender text,
    marital_status text,
    child_dependents integer,
    living_situation text,
    native_language text,
    second_language text,
    mission_language_competency text,
    country_of_origin text,
    created_by uuid,
    inactive_at timestamp with time zone,
    inactive_reason text,
    follow_up_status text DEFAULT 'current'::text NOT NULL,
    follow_up_ended_at timestamp with time zone,
    follow_up_end_reason text,
    baptismal_date_person_id bigint,
    CONSTRAINT new_members_child_dependents_nonnegative CHECK (((child_dependents IS NULL) OR (child_dependents >= 0))),
    CONSTRAINT new_members_follow_up_end_reason_check CHECK (((follow_up_end_reason IS NULL) OR (follow_up_end_reason = ANY (ARRAY['one_year'::text, 'moved_out_of_mission'::text, 'record_removed'::text, 'deceased'::text, 'duplicate'::text, 'other'::text])))),
    CONSTRAINT new_members_follow_up_state_check CHECK ((((follow_up_status = 'current'::text) AND (follow_up_ended_at IS NULL) AND (follow_up_end_reason IS NULL)) OR ((follow_up_status = 'ended'::text) AND (follow_up_ended_at IS NOT NULL) AND (follow_up_end_reason IS NOT NULL)))),
    CONSTRAINT new_members_follow_up_status_check CHECK ((follow_up_status = ANY (ARRAY['current'::text, 'ended'::text]))),
    CONSTRAINT new_members_inactive_reason_check CHECK (((inactive_reason IS NULL) OR (inactive_reason = ANY (ARRAY['one_year'::text, 'moved'::text, 'other'::text])))),
    CONSTRAINT new_members_inactive_state_check CHECK ((((active = true) AND (inactive_at IS NULL) AND (inactive_reason IS NULL)) OR ((active = false) AND (inactive_at IS NOT NULL) AND (inactive_reason IS NOT NULL))))
);


ALTER TABLE public.new_members OWNER TO postgres;

--
-- Name: convert_baptismal_date_person_to_new_member(bigint, date, date, date, date, text, text, text, integer, text, text, text, text, text, text); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.convert_baptismal_date_person_to_new_member(target_baptismal_date_person_id bigint, new_baptismal_date_extended date DEFAULT NULL::date, new_baptism_date date DEFAULT NULL::date, new_confirmation_date date DEFAULT NULL::date, new_date_of_birth date DEFAULT NULL::date, new_age_range text DEFAULT NULL::text, new_gender text DEFAULT NULL::text, new_marital_status text DEFAULT NULL::text, new_child_dependents integer DEFAULT NULL::integer, new_living_situation text DEFAULT NULL::text, new_native_language text DEFAULT NULL::text, new_second_language text DEFAULT NULL::text, new_mission_language_competency text DEFAULT NULL::text, new_country_of_origin text DEFAULT NULL::text, new_conversion_success_notes text DEFAULT NULL::text) RETURNS public.new_members
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'public', 'pg_temp'
    AS $$
declare
    v_person public.baptismal_date_people;
    v_area_id bigint;
    v_unit_id bigint;
    v_new_member public.new_members;
begin

    -- ========================================================
    -- VALIDATION
    -- ========================================================

    if new_baptism_date is null then
        raise exception 'Baptism date is required.';
    end if;


    select *
    into v_person
    from public.baptismal_date_people
    where id = target_baptismal_date_person_id;


    if not found then
        raise exception
            'Baptismal Date person was not found.';
    end if;


    if v_person.tracking_status <> 'current' then
        raise exception
            'This person is no longer currently being tracked.';
    end if;


    if exists (
        select 1
        from public.new_members nm
        where nm.baptismal_date_person_id =
              target_baptismal_date_person_id
    ) then
        raise exception
            'This person has already been converted to a New Member.';
    end if;


    -- ========================================================
    -- CURRENT AREA + UNIT
    -- ========================================================

    select
        bdpa.area_id,
        bdpa.unit_id
    into
        v_area_id,
        v_unit_id
    from public.baptismal_date_person_area_assignments bdpa
    where bdpa.baptismal_date_person_id =
              target_baptismal_date_person_id
      and bdpa.end_date is null;


    if v_area_id is null then
        raise exception
            'Person does not have a current area assignment.';
    end if;


    if v_unit_id is null then
        raise exception
            'Person does not have a current unit assignment.';
    end if;


    if not public.can_access_area(v_area_id) then
        raise exception
            'You do not have permission to convert this person.';
    end if;


    -- ========================================================
    -- CREATE NEW MEMBER
    -- ========================================================

    select *
    into v_new_member
    from public.create_new_member(
        new_first_name =>
            v_person.first_name,

        new_last_name =>
            v_person.last_name,

        new_stake_id =>
            null,

        new_unit_id =>
            v_unit_id,

        new_baptismal_date_extended =>
            new_baptismal_date_extended,

        new_baptism_date =>
            new_baptism_date,

        new_confirmation_date =>
            new_confirmation_date,

        new_finding_source =>
            v_person.finding_source,

        new_date_of_birth =>
            new_date_of_birth,

        new_age_range =>
            new_age_range,

        new_gender =>
            new_gender,

        new_marital_status =>
            new_marital_status,

        new_child_dependents =>
            new_child_dependents,

        new_living_situation =>
            new_living_situation,

        new_native_language =>
            new_native_language,

        new_second_language =>
            new_second_language,

        new_mission_language_competency =>
            new_mission_language_competency,

        new_country_of_origin =>
            new_country_of_origin,

        new_conversion_success_notes =>
            new_conversion_success_notes
    );


    -- ========================================================
    -- LINK RECORDS
    -- ========================================================

    update public.new_members
    set baptismal_date_person_id =
            target_baptismal_date_person_id
    where id = v_new_member.id
    returning *
    into v_new_member;


    -- ========================================================
    -- CLOSE BAPTISMAL DATE TRACKING ASSIGNMENT
    --
    -- IMPORTANT:
    -- This is the tracking/area assignment end date, NOT the
    -- person's baptism date.
    --
    -- The baptism itself may have happened before this record
    -- was entered into the system, so use CURRENT_DATE here.
    -- ========================================================

    update public.baptismal_date_person_area_assignments
    set
        end_date = current_date,
        transfer_reason = 'baptized'
    where baptismal_date_person_id =
              target_baptismal_date_person_id
      and end_date is null;


    -- ========================================================
    -- END BAPTISMAL DATE TRACKING
    -- ========================================================

    update public.baptismal_date_people
    set
        tracking_status = 'ended',
        tracking_ended_at = now(),
        tracking_end_reason = 'baptized',
        updated_at = now()
    where id = target_baptismal_date_person_id;


    return v_new_member;

end;
$$;


ALTER FUNCTION public.convert_baptismal_date_person_to_new_member(target_baptismal_date_person_id bigint, new_baptismal_date_extended date, new_baptism_date date, new_confirmation_date date, new_date_of_birth date, new_age_range text, new_gender text, new_marital_status text, new_child_dependents integer, new_living_situation text, new_native_language text, new_second_language text, new_mission_language_competency text, new_country_of_origin text, new_conversion_success_notes text) OWNER TO postgres;

--
-- Name: baptismal_date_people; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.baptismal_date_people (
    id bigint NOT NULL,
    first_name text NOT NULL,
    last_name text,
    display_name text NOT NULL,
    finding_source text,
    created_by uuid,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    tracking_status text DEFAULT 'current'::text NOT NULL,
    tracking_ended_at timestamp with time zone,
    tracking_end_reason text,
    CONSTRAINT baptismal_date_people_tracking_end_reason_check CHECK (((tracking_end_reason IS NULL) OR (tracking_end_reason = ANY (ARRAY['baptized'::text, 'no_longer_on_date'::text, 'moved_out_of_mission'::text, 'duplicate'::text, 'other'::text])))),
    CONSTRAINT baptismal_date_people_tracking_state_check CHECK ((((tracking_status = 'current'::text) AND (tracking_ended_at IS NULL) AND (tracking_end_reason IS NULL)) OR ((tracking_status = 'ended'::text) AND (tracking_ended_at IS NOT NULL) AND (tracking_end_reason IS NOT NULL)))),
    CONSTRAINT baptismal_date_people_tracking_status_check CHECK ((tracking_status = ANY (ARRAY['current'::text, 'ended'::text])))
);


ALTER TABLE public.baptismal_date_people OWNER TO postgres;

--
-- Name: create_baptismal_date_person(text, text, text, bigint); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.create_baptismal_date_person(new_first_name text, new_last_name text DEFAULT NULL::text, new_finding_source text DEFAULT NULL::text, selected_unit_id bigint DEFAULT NULL::bigint) RETURNS public.baptismal_date_people
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'public', 'pg_temp'
    AS $$
declare
    v_area_id bigint;
    v_user_id uuid;
    v_person public.baptismal_date_people;
begin

    v_user_id := auth.uid();
    v_area_id := public.current_user_area_id();


    if v_user_id is null then
        raise exception 'Authenticated user is required.';
    end if;


    if v_area_id is null then
        raise exception
            'Current user does not have a current area assignment.';
    end if;


    if new_first_name is null
       or btrim(new_first_name) = '' then
        raise exception 'First name is required.';
    end if;


    if selected_unit_id is null then
        raise exception
            'A unit must be selected before creating a person on baptismal date.';
    end if;


    if not exists (
        select 1
        from public.area_units au
        where au.area_id = v_area_id
          and au.unit_id = selected_unit_id
    ) then
        raise exception
            'Selected unit does not belong to the current area.';
    end if;


    insert into public.baptismal_date_people (
        first_name,
        last_name,
        display_name,
        finding_source,
        created_by
    )
    values (
        btrim(new_first_name),
        nullif(btrim(new_last_name), ''),
        btrim(
            concat_ws(
                ' ',
                btrim(new_first_name),
                nullif(btrim(new_last_name), '')
            )
        ),
        new_finding_source,
        v_user_id
    )
    returning *
    into v_person;


    insert into public.baptismal_date_person_area_assignments (
        baptismal_date_person_id,
        area_id,
        unit_id,
        start_date
    )
    values (
        v_person.id,
        v_area_id,
        selected_unit_id,
        current_date
    );


    return v_person;

end;
$$;


ALTER FUNCTION public.create_baptismal_date_person(new_first_name text, new_last_name text, new_finding_source text, selected_unit_id bigint) OWNER TO postgres;

--
-- Name: create_new_member(text, text, bigint, bigint, date, date, date, text, date, text, text, text, integer, text, text, text, text, text, text); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.create_new_member(new_first_name text, new_last_name text DEFAULT NULL::text, new_stake_id bigint DEFAULT NULL::bigint, new_unit_id bigint DEFAULT NULL::bigint, new_baptismal_date_extended date DEFAULT NULL::date, new_baptism_date date DEFAULT NULL::date, new_confirmation_date date DEFAULT NULL::date, new_finding_source text DEFAULT NULL::text, new_date_of_birth date DEFAULT NULL::date, new_age_range text DEFAULT NULL::text, new_gender text DEFAULT NULL::text, new_marital_status text DEFAULT NULL::text, new_child_dependents integer DEFAULT NULL::integer, new_living_situation text DEFAULT NULL::text, new_native_language text DEFAULT NULL::text, new_second_language text DEFAULT NULL::text, new_mission_language_competency text DEFAULT NULL::text, new_country_of_origin text DEFAULT NULL::text, new_conversion_success_notes text DEFAULT NULL::text) RETURNS public.new_members
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'public', 'pg_temp'
    AS $$
declare
    v_area_id bigint;
    v_user_id uuid;
    v_record public.new_members;
    v_unit_id bigint;
    v_stake_id bigint;
begin

    v_user_id := auth.uid();
    v_area_id := public.current_user_area_id();
    v_unit_id := new_unit_id;


    if v_user_id is null then
        raise exception 'Authenticated user is required.';
    end if;


    if v_area_id is null then
        raise exception
            'Current user does not have an active area assignment.';
    end if;


    if new_first_name is null
       or btrim(new_first_name) = '' then
        raise exception 'First name is required.';
    end if;


    if v_unit_id is null then
        raise exception
            'A unit must be selected before creating a New Member.';
    end if;


    -- The selected unit must actually belong to this area.
    if not exists (
        select 1
        from public.area_units au
        where au.area_id = v_area_id
          and au.unit_id = v_unit_id
    ) then
        raise exception
            'Selected unit does not belong to the current area.';
    end if;


    -- Stake comes from the selected unit.
    select u.stake_id
    into v_stake_id
    from public.units u
    where u.id = v_unit_id;


    insert into public.new_members (
        area_id,
        stake_id,
        unit_id,

        first_name,
        last_name,
        display_name,

        baptismal_date_extended,
        baptism_date,
        confirmation_date,
        finding_source,

        date_of_birth,
        age_range,
        gender,
        marital_status,
        child_dependents,
        living_situation,

        native_language,
        second_language,
        mission_language_competency,
        country_of_origin,
        conversion_success_notes,

        follow_up_status,

        active,

        created_by
    )
    values (
        v_area_id,
        v_stake_id,
        v_unit_id,

        btrim(new_first_name),
        nullif(btrim(new_last_name), ''),
        btrim(
            concat_ws(
                ' ',
                btrim(new_first_name),
                nullif(btrim(new_last_name), '')
            )
        ),

        new_baptismal_date_extended,
        new_baptism_date,
        new_confirmation_date,
        new_finding_source,

        new_date_of_birth,
        new_age_range,
        new_gender,
        new_marital_status,
        new_child_dependents,
        new_living_situation,

        new_native_language,
        new_second_language,
        new_mission_language_competency,
        new_country_of_origin,
        new_conversion_success_notes,

        'current',

        true,

        v_user_id
    )
    returning *
    into v_record;


    insert into public.new_member_area_assignments (
        new_member_id,
        area_id,
        unit_id,
        start_date
    )
    values (
        v_record.id,
        v_area_id,
        v_unit_id,
        coalesce(new_baptism_date, current_date)
    );


    return v_record;

end;
$$;


ALTER FUNCTION public.create_new_member(new_first_name text, new_last_name text, new_stake_id bigint, new_unit_id bigint, new_baptismal_date_extended date, new_baptism_date date, new_confirmation_date date, new_finding_source text, new_date_of_birth date, new_age_range text, new_gender text, new_marital_status text, new_child_dependents integer, new_living_situation text, new_native_language text, new_second_language text, new_mission_language_competency text, new_country_of_origin text, new_conversion_success_notes text) OWNER TO postgres;

--
-- Name: current_reporting_sunday(); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.current_reporting_sunday() RETURNS date
    LANGUAGE sql STABLE
    AS $$
  SELECT public.reporting_sunday_at(now());
$$;


ALTER FUNCTION public.current_reporting_sunday() OWNER TO postgres;

--
-- Name: current_user_area_id(); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.current_user_area_id() RETURNS bigint
    LANGUAGE sql STABLE SECURITY DEFINER
    SET search_path TO 'public'
    AS $$

    select ma.area_id

    from public.user_profiles up

    join public.missionary_assignments ma
        on ma.missionary_id = up.missionary_id

       and ma.start_date <= current_date

       and (
            ma.end_date is null
            or ma.end_date >= current_date
       )

    where up.id = auth.uid()

      and up.active = true

    order by ma.start_date desc

    limit 1;

$$;


ALTER FUNCTION public.current_user_area_id() OWNER TO postgres;

--
-- Name: delete_baptismal_date_person_added_by_mistake(bigint); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.delete_baptismal_date_person_added_by_mistake(target_baptismal_date_person_id bigint) RETURNS void
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'public', 'pg_temp'
    AS $$
DECLARE
    v_area_id bigint;
BEGIN
    PERFORM 1 FROM public.baptismal_date_people WHERE id = target_baptismal_date_person_id FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'This friend was not found.';
    END IF;
    SELECT area_id INTO v_area_id FROM public.baptismal_date_person_area_assignments
    WHERE baptismal_date_person_id = target_baptismal_date_person_id AND end_date IS NULL;
    IF v_area_id IS NULL THEN
        RAISE EXCEPTION 'This friend is no longer on the baptismal date list, so the record is kept.';
    END IF;
    IF NOT public.can_access_area(v_area_id) THEN
        RAISE EXCEPTION 'You do not have permission to delete this friend.';
    END IF;
    IF EXISTS (SELECT 1 FROM public.new_members WHERE baptismal_date_person_id = target_baptismal_date_person_id) THEN
        RAISE EXCEPTION 'This friend is already a New Member, so the record is kept.';
    END IF;
    IF EXISTS (SELECT 1 FROM public.weekly_baptismal_date_friends w
               JOIN public.weekly_area_reports war ON war.id = w.weekly_area_report_id
               JOIN public.reporting_weeks rw ON rw.id = war.reporting_week_id
               WHERE w.baptismal_date_person_id = target_baptismal_date_person_id
                 AND (war.status <> 'DRAFT' OR rw.sunday < public.current_reporting_sunday())) THEN
        RAISE EXCEPTION 'This friend is already on an earlier or submitted weekly plan, so the record is kept for the mission''s reports. Use Drop instead.'
            USING ERRCODE = 'GF409';
    END IF;
    IF EXISTS (SELECT 1 FROM public.weekly_baptismal_date_friends w
               JOIN public.weekly_area_reports war ON war.id = w.weekly_area_report_id
               WHERE w.baptismal_date_person_id = target_baptismal_date_person_id
                 AND NOT public.can_edit_planning_area(war.area_id)) THEN
        RAISE EXCEPTION 'This friend is also on another area''s plan, so the record is kept. Use Drop instead.'
            USING ERRCODE = 'GF409';
    END IF;

    DELETE FROM public.weekly_baptismal_date_friends WHERE baptismal_date_person_id = target_baptismal_date_person_id;
    DELETE FROM public.baptismal_date_people WHERE id = target_baptismal_date_person_id;
END;
$$;


ALTER FUNCTION public.delete_baptismal_date_person_added_by_mistake(target_baptismal_date_person_id bigint) OWNER TO postgres;

--
-- Name: delete_new_member_added_by_mistake(bigint); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.delete_new_member_added_by_mistake(target_new_member_id bigint) RETURNS bigint
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'public', 'pg_temp'
    AS $$
DECLARE
    v_member public.new_members;
    v_area_id bigint;
    v_friend_assignment public.baptismal_date_person_area_assignments;
    v_restored_friend_id bigint;
BEGIN
    SELECT * INTO v_member FROM public.new_members WHERE id = target_new_member_id FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'This New Member was not found.';
    END IF;
    SELECT area_id INTO v_area_id FROM public.new_member_area_assignments
    WHERE new_member_id = target_new_member_id AND end_date IS NULL;
    IF v_area_id IS NULL THEN
        RAISE EXCEPTION 'This New Member is no longer followed up, so the record is kept.';
    END IF;
    IF NOT public.can_access_area(v_area_id) THEN
        RAISE EXCEPTION 'You do not have permission to delete this New Member.';
    END IF;
    IF EXISTS (SELECT 1 FROM public.weekly_new_members w
               JOIN public.weekly_area_reports war ON war.id = w.weekly_area_report_id
               JOIN public.reporting_weeks rw ON rw.id = war.reporting_week_id
               WHERE w.new_member_id = target_new_member_id
                 AND (war.status <> 'DRAFT' OR rw.sunday < public.current_reporting_sunday())) THEN
        RAISE EXCEPTION 'This New Member is already on an earlier or submitted weekly plan, so the record is kept for the mission''s reports. Use End follow-up instead.'
            USING ERRCODE = 'GF409';
    END IF;
    IF EXISTS (SELECT 1 FROM public.weekly_new_members w
               JOIN public.weekly_area_reports war ON war.id = w.weekly_area_report_id
               WHERE w.new_member_id = target_new_member_id AND NOT public.can_edit_planning_area(war.area_id)) THEN
        RAISE EXCEPTION 'This New Member is also on another area''s plan, so the record is kept. Use End follow-up instead.'
            USING ERRCODE = 'GF409';
    END IF;

    DELETE FROM public.weekly_new_members WHERE new_member_id = target_new_member_id;

    -- Came from "Baptized": put the friend back on the baptismal date list where they were.
    IF v_member.baptismal_date_person_id IS NOT NULL
       AND NOT EXISTS (SELECT 1 FROM public.baptismal_date_person_area_assignments
                       WHERE baptismal_date_person_id = v_member.baptismal_date_person_id AND end_date IS NULL) THEN
        SELECT * INTO v_friend_assignment FROM public.baptismal_date_person_area_assignments
        WHERE baptismal_date_person_id = v_member.baptismal_date_person_id AND transfer_reason = 'baptized'
        ORDER BY end_date DESC, id DESC
        LIMIT 1;
        IF v_friend_assignment.id IS NOT NULL THEN
            UPDATE public.baptismal_date_people
            SET tracking_status = 'current', tracking_ended_at = NULL, tracking_end_reason = NULL, updated_at = now()
            WHERE id = v_member.baptismal_date_person_id AND tracking_status = 'ended' AND tracking_end_reason = 'baptized';
            IF FOUND THEN
                INSERT INTO public.baptismal_date_person_area_assignments
                    (baptismal_date_person_id, area_id, unit_id, start_date, transfer_reason)
                VALUES (v_member.baptismal_date_person_id, v_friend_assignment.area_id, v_friend_assignment.unit_id,
                        current_date, 'baptism_undone');
                v_restored_friend_id := v_member.baptismal_date_person_id;
            END IF;
        END IF;
    END IF;

    DELETE FROM public.new_members WHERE id = target_new_member_id;
    RETURN v_restored_friend_id;
END;
$$;


ALTER FUNCTION public.delete_new_member_added_by_mistake(target_new_member_id bigint) OWNER TO postgres;

--
-- Name: ensure_reporting_week(date); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.ensure_reporting_week(target_sunday date) RETURNS bigint
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'public'
    AS $$

declare
    result_id bigint;

begin


    if extract(dow from target_sunday) <> 0 then

        raise exception
        'Reporting week date % is not a Sunday.',
        target_sunday;

    end if;


    insert into public.reporting_weeks (
        sunday
    )

    values (
        target_sunday
    )

    on conflict (sunday)
    do nothing;


    select id
    into result_id

    from public.reporting_weeks

    where sunday =
          target_sunday;


    return result_id;

end;

$$;


ALTER FUNCTION public.ensure_reporting_week(target_sunday date) OWNER TO postgres;

--
-- Name: fill_current_week_plans(); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.fill_current_week_plans() RETURNS integer
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'public', 'pg_temp'
    AS $$
DECLARE
    v_sunday date := public.current_reporting_sunday();
    v_week_id bigint; v_report_id bigint; v_status text; r record; v_count integer := 0;
BEGIN
    v_week_id := public.ensure_reporting_week(v_sunday);
    FOR r IN
        SELECT DISTINCT p.area_id, p.unit_id FROM (
            SELECT nm.area_id, nm.unit_id FROM public.current_new_members nm
            UNION
            SELECT bdp.area_id, bdpa.unit_id FROM public.current_baptismal_date_people bdp
              JOIN public.baptismal_date_person_area_assignments bdpa
                ON bdpa.baptismal_date_person_id = bdp.id AND bdpa.end_date IS NULL
              WHERE EXISTS (SELECT 1 FROM public.weekly_baptismal_date_friends w
                            JOIN public.weekly_area_reports wr ON wr.id = w.weekly_area_report_id
                            JOIN public.reporting_weeks rw ON rw.id = wr.reporting_week_id
                            WHERE w.baptismal_date_person_id = bdp.id AND rw.sunday = v_sunday - 7)
            UNION
            SELECT pr.area_id, pr.unit_id FROM public.weekly_high_potential_friends h
              JOIN public.weekly_area_reports pr ON pr.id = h.weekly_area_report_id
              JOIN public.reporting_weeks prw ON prw.id = pr.reporting_week_id
              WHERE prw.sunday = v_sunday - 7 AND btrim(h.name) <> '' AND h.name <> 'New High Potential'
        ) p JOIN public.areas a ON a.id = p.area_id AND a.active
        WHERE p.unit_id IS NOT NULL
    LOOP
        SELECT war.id, war.status INTO v_report_id, v_status FROM public.weekly_area_reports war
        WHERE war.area_id = r.area_id AND war.unit_id = r.unit_id AND war.reporting_week_id = v_week_id;
        IF v_report_id IS NULL THEN
            INSERT INTO public.weekly_area_reports (area_id, unit_id, reporting_week_id, status)
            VALUES (r.area_id, r.unit_id, v_week_id, 'DRAFT') RETURNING id, status INTO v_report_id, v_status;
        END IF;
        IF v_status = 'DRAFT' THEN
            PERFORM public.carry_people_into_report(v_report_id);
            v_count := v_count + 1;
        END IF;
    END LOOP;
    RETURN v_count;
END;
$$;


ALTER FUNCTION public.fill_current_week_plans() OWNER TO postgres;

--
-- Name: fill_weekly_baptismal_date_context(); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.fill_weekly_baptismal_date_context() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'public'
    AS $$
declare
    v_finding_source text;
    v_stake_id bigint;
begin

    -- --------------------------------------------------------
    -- Finding Source
    -- --------------------------------------------------------

    if NEW.baptismal_date_person_id is not null then

        select bdp.finding_source
        into v_finding_source
        from public.baptismal_date_people bdp
        where bdp.id = NEW.baptismal_date_person_id;

        NEW.finding_source := v_finding_source;

    end if;


    -- --------------------------------------------------------
    -- Stake
    --
    -- weekly_area_report
    --      -> unit_id
    --      -> units.stake_id
    -- --------------------------------------------------------

    select u.stake_id
    into v_stake_id
    from public.weekly_area_reports war
    join public.units u
      on u.id = war.unit_id
    where war.id = NEW.weekly_area_report_id;

    NEW.stake_id := v_stake_id;


    return NEW;

end;
$$;


ALTER FUNCTION public.fill_weekly_baptismal_date_context() OWNER TO postgres;

--
-- Name: get_call_in_people(text, bigint, bigint); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.get_call_in_people(target_level text, target_id bigint, target_reporting_week_id bigint) RETURNS jsonb
    LANGUAGE plpgsql STABLE SECURITY DEFINER
    SET search_path TO 'public', 'pg_temp'
    AS $$
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
$$;


ALTER FUNCTION public.get_call_in_people(target_level text, target_id bigint, target_reporting_week_id bigint) OWNER TO postgres;

--
-- Name: get_call_in_planning_metrics(bigint, bigint, bigint, bigint, bigint); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.get_call_in_planning_metrics(target_reporting_week_id bigint, target_area_id bigint DEFAULT NULL::bigint, target_district_id bigint DEFAULT NULL::bigint, target_zone_id bigint DEFAULT NULL::bigint, target_mission_id bigint DEFAULT NULL::bigint) RETURNS jsonb
    LANGUAGE sql STABLE
    SET search_path TO 'public', 'pg_temp'
    AS $$
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
$$;


ALTER FUNCTION public.get_call_in_planning_metrics(target_reporting_week_id bigint, target_area_id bigint, target_district_id bigint, target_zone_id bigint, target_mission_id bigint) OWNER TO postgres;

--
-- Name: get_call_in_planning_previous_goals(bigint, bigint, bigint, bigint, bigint); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.get_call_in_planning_previous_goals(target_reporting_week_id bigint, target_area_id bigint DEFAULT NULL::bigint, target_district_id bigint DEFAULT NULL::bigint, target_zone_id bigint DEFAULT NULL::bigint, target_mission_id bigint DEFAULT NULL::bigint) RETURNS jsonb
    LANGUAGE sql STABLE
    SET search_path TO 'public', 'pg_temp'
    AS $_$
    SELECT coalesce(jsonb_object_agg(regexp_replace(metric.key,'_goal$','_previous_goal'),metric.value),'{}'::jsonb)
    FROM jsonb_each(public.get_call_in_planning_metrics(
        (SELECT rw.id FROM public.reporting_weeks rw
         WHERE rw.sunday < (SELECT sunday FROM public.reporting_weeks WHERE id = target_reporting_week_id)
         ORDER BY rw.sunday DESC LIMIT 1),target_area_id,target_district_id,target_zone_id,target_mission_id
    )) metric WHERE right(metric.key,5) = '_goal';
$_$;


ALTER FUNCTION public.get_call_in_planning_previous_goals(target_reporting_week_id bigint, target_area_id bigint, target_district_id bigint, target_zone_id bigint, target_mission_id bigint) OWNER TO postgres;

--
-- Name: get_dl_call_in_baptismal_dates(bigint, bigint); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.get_dl_call_in_baptismal_dates(target_district_id bigint, target_reporting_week_id bigint) RETURNS TABLE(district_id bigint, district_name text, reporting_week_id bigint, reporting_sunday date, area_id bigint, area_name text, unit_id bigint, unit_name text, missionaries text, weekly_baptismal_date_friend_id bigint, baptismal_date_person_id bigint, display_order integer, person_name text, finding_source text, baptismal_date_set_on date, current_baptismal_date date, days_until_baptism integer, weeks_until_baptism numeric, reading boolean, praying boolean, at_church_this_sunday boolean, keeping_commandments boolean, member_involvement boolean, stake_id bigint)
    LANGUAGE plpgsql STABLE SECURITY DEFINER
    SET search_path TO 'public', 'pg_temp'
    AS $$

BEGIN

    IF NOT public.can_access_district(target_district_id) THEN
        RAISE EXCEPTION
            'You do not have permission to view this district.';
    END IF;


    RETURN QUERY

    WITH area_missionaries AS (

        SELECT
            a.id AS area_id,

            STRING_AGG(
                DISTINCT m.display_name,
                ', '
                ORDER BY m.display_name
            ) AS missionaries

        FROM public.areas a

        LEFT JOIN public.reporting_weeks rw
          ON rw.id = target_reporting_week_id

        LEFT JOIN public.missionary_assignments ma
          ON ma.area_id = a.id
         AND ma.start_date <= rw.sunday
         AND (
             ma.end_date IS NULL
             OR ma.end_date >= rw.sunday
         )

        LEFT JOIN public.missionaries m
          ON m.id = ma.missionary_id

        WHERE a.district_id = target_district_id

        GROUP BY a.id
    )

    SELECT

        d.id::bigint,
        d.name::text,

        rw.id::bigint,
        rw.sunday::date,

        a.id::bigint,
        a.name::text,

        u.id::bigint,
        u.name::text,

        am.missionaries::text,

        wbdf.id::bigint,
        wbdf.baptismal_date_person_id::bigint,
        wbdf.display_order::integer,

        COALESCE(
            NULLIF(BTRIM(bdp.display_name), ''),
            NULLIF(
                BTRIM(
                    COALESCE(bdp.first_name, '') ||
                    ' ' ||
                    COALESCE(bdp.last_name, '')
                ),
                ''
            )
        )::text AS person_name,

        COALESCE(
            wbdf.finding_source,
            bdp.finding_source
        )::text,

        wbdf.baptismal_date_set_on::date,
        wbdf.current_baptismal_date::date,

        CASE
            WHEN wbdf.current_baptismal_date IS NULL
                THEN NULL
            ELSE
                (
                    wbdf.current_baptismal_date
                    - rw.sunday
                )::integer
        END,

        CASE
            WHEN wbdf.current_baptismal_date IS NULL
                THEN NULL
            ELSE
                ROUND(
                    (
                        wbdf.current_baptismal_date
                        - rw.sunday
                    )::numeric / 7.0,
                    1
                )
        END,

        wbdf.reading::boolean,
        wbdf.praying::boolean,
        wbdf.at_church_this_sunday::boolean,
        wbdf.keeping_commandments::boolean,
        wbdf.member_involvement::boolean,

        wbdf.stake_id::bigint


    FROM public.weekly_baptismal_date_friends wbdf

    JOIN public.weekly_area_reports war
      ON war.id = wbdf.weekly_area_report_id

    JOIN public.reporting_weeks rw
      ON rw.id = war.reporting_week_id

    JOIN public.areas a
      ON a.id = war.area_id

    JOIN public.districts d
      ON d.id = a.district_id

    LEFT JOIN public.units u
      ON u.id = war.unit_id

    -- A Call-in BD must correspond to a real tracked person.
    JOIN public.baptismal_date_people bdp
      ON bdp.id = wbdf.baptismal_date_person_id

    LEFT JOIN area_missionaries am
      ON am.area_id = a.id

    WHERE war.reporting_week_id = target_reporting_week_id
      AND a.district_id = target_district_id
      AND wbdf.baptismal_date_person_id IS NOT NULL

    ORDER BY
        a.name,
        wbdf.display_order,
        person_name;

END;
$$;


ALTER FUNCTION public.get_dl_call_in_baptismal_dates(target_district_id bigint, target_reporting_week_id bigint) OWNER TO postgres;

--
-- Name: get_dl_call_in_bd_activity(bigint, bigint); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.get_dl_call_in_bd_activity(target_district_id bigint, target_reporting_week_id bigint) RETURNS TABLE(name text, companionship text, area text, active boolean)
    LANGUAGE plpgsql STABLE SECURITY DEFINER
    SET search_path TO 'public', 'pg_temp'
    AS $$
BEGIN

    IF NOT public.can_access_district(target_district_id) THEN
        RAISE EXCEPTION
            'You do not have permission to view this district.';
    END IF;


    RETURN QUERY

    WITH selected_week AS (
        SELECT rw.sunday
        FROM public.reporting_weeks rw
        WHERE rw.id = target_reporting_week_id
    )

    SELECT

        p.person_name::text AS name,
        COALESCE(p.missionaries, '—')::text AS companionship,
        p.area_name::text AS area,

        (
            SELECT COUNT(DISTINCT rw_hist.id) >= 2

            FROM public.weekly_baptismal_date_friends wbdf_hist

            JOIN public.weekly_area_reports war_hist
              ON war_hist.id = wbdf_hist.weekly_area_report_id

            JOIN public.reporting_weeks rw_hist
              ON rw_hist.id = war_hist.reporting_week_id

            CROSS JOIN selected_week sw

            WHERE wbdf_hist.baptismal_date_person_id =
                  p.baptismal_date_person_id

              AND rw_hist.sunday BETWEEN
                  sw.sunday - 21
                  AND sw.sunday

              AND wbdf_hist.at_church_this_sunday IS TRUE
        )::boolean AS active


    FROM public.get_dl_call_in_baptismal_dates(
        target_district_id,
        target_reporting_week_id
    ) p

    ORDER BY
        p.area_name,
        p.person_name;

END;
$$;


ALTER FUNCTION public.get_dl_call_in_bd_activity(target_district_id bigint, target_reporting_week_id bigint) OWNER TO postgres;

--
-- Name: get_dl_call_in_high_potentials(bigint, bigint); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.get_dl_call_in_high_potentials(target_district_id bigint, target_reporting_week_id bigint) RETURNS TABLE(district_id bigint, district_name text, reporting_week_id bigint, reporting_sunday date, area_id bigint, area_name text, unit_id bigint, unit_name text, missionaries text, weekly_high_potential_id bigint, display_order integer, person_name text, at_church_this_sunday boolean, notes text)
    LANGUAGE plpgsql STABLE SECURITY DEFINER
    SET search_path TO 'public', 'pg_temp'
    AS $$

BEGIN

    IF NOT public.can_access_district(target_district_id) THEN
        RAISE EXCEPTION
            'You do not have permission to view this district.';
    END IF;


    RETURN QUERY

    WITH area_missionaries AS (

        SELECT
            a.id AS area_id,

            STRING_AGG(
                DISTINCT m.display_name,
                ', '
                ORDER BY m.display_name
            ) AS missionaries

        FROM public.areas a

        LEFT JOIN public.reporting_weeks rw
          ON rw.id = target_reporting_week_id

        LEFT JOIN public.missionary_assignments ma
          ON ma.area_id = a.id
         AND ma.start_date <= rw.sunday
         AND (
             ma.end_date IS NULL
             OR ma.end_date >= rw.sunday
         )

        LEFT JOIN public.missionaries m
          ON m.id = ma.missionary_id

        WHERE a.district_id = target_district_id

        GROUP BY a.id
    )

    SELECT

        d.id::bigint,
        d.name::text,

        rw.id::bigint,
        rw.sunday::date,

        a.id::bigint,
        a.name::text,

        u.id::bigint,
        u.name::text,

        am.missionaries::text,

        whpf.id::bigint,
        whpf.display_order::integer,

        whpf.name::text AS person_name,
        whpf.at_church_this_sunday::boolean,
        whpf.notes::text


    FROM public.weekly_high_potential_friends whpf

    JOIN public.weekly_area_reports war
      ON war.id = whpf.weekly_area_report_id

    JOIN public.reporting_weeks rw
      ON rw.id = war.reporting_week_id

    JOIN public.areas a
      ON a.id = war.area_id

    JOIN public.districts d
      ON d.id = a.district_id

    LEFT JOIN public.units u
      ON u.id = war.unit_id

    LEFT JOIN area_missionaries am
      ON am.area_id = a.id

    WHERE war.reporting_week_id = target_reporting_week_id
      AND a.district_id = target_district_id

    ORDER BY
        a.name,
        whpf.display_order,
        person_name;

END;
$$;


ALTER FUNCTION public.get_dl_call_in_high_potentials(target_district_id bigint, target_reporting_week_id bigint) OWNER TO postgres;

--
-- Name: get_dl_call_in_hp_activity(bigint, bigint); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.get_dl_call_in_hp_activity(target_district_id bigint, target_reporting_week_id bigint) RETURNS TABLE(name text, companionship text, area text, active boolean)
    LANGUAGE plpgsql STABLE SECURITY DEFINER
    SET search_path TO 'public', 'pg_temp'
    AS $$
BEGIN

    IF NOT public.can_access_district(target_district_id) THEN
        RAISE EXCEPTION
            'You do not have permission to view this district.';
    END IF;


    RETURN QUERY

    SELECT

        p.person_name::text AS name,
        COALESCE(p.missionaries, '—')::text AS companionship,
        p.area_name::text AS area,

        COALESCE(
            p.at_church_this_sunday,
            false
        )::boolean AS active


    FROM public.get_dl_call_in_high_potentials(
        target_district_id,
        target_reporting_week_id
    ) p

    ORDER BY
        p.area_name,
        p.person_name;

END;
$$;


ALTER FUNCTION public.get_dl_call_in_hp_activity(target_district_id bigint, target_reporting_week_id bigint) OWNER TO postgres;

--
-- Name: get_dl_call_in_new_members(bigint, bigint); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.get_dl_call_in_new_members(target_district_id bigint, target_reporting_week_id bigint) RETURNS TABLE(district_id bigint, district_name text, reporting_week_id bigint, reporting_sunday date, area_id bigint, area_name text, unit_id bigint, unit_name text, missionaries text, weekly_new_member_id bigint, new_member_id bigint, display_order integer, person_name text, baptism_date date, confirmation_date date, finding_source text, lessons_actual integer, lessons_goal integer, pmg_lessons_percentage numeric, how_are_they_doing text, discussed_in_gemiko boolean, gemiko_support_plan text, next_ordinance text, at_church_this_sunday boolean, has_calling text, has_aaronic_priesthood text, has_melchizedek_priesthood text, ministers_to_someone text, ministered_to_by_someone boolean, has_active_temple_recommend text, visited_temple_for_baptisms text, reading boolean, praying boolean, member_involvement boolean)
    LANGUAGE plpgsql STABLE SECURITY DEFINER
    SET search_path TO 'public', 'pg_temp'
    AS $$

BEGIN

    IF NOT public.can_access_district(target_district_id) THEN
        RAISE EXCEPTION
            'You do not have permission to view this district.';
    END IF;


    RETURN QUERY

    WITH area_missionaries AS (

        SELECT
            a.id AS area_id,

            STRING_AGG(
                DISTINCT m.display_name,
                ', '
                ORDER BY m.display_name
            ) AS missionaries

        FROM public.areas a

        LEFT JOIN public.reporting_weeks rw
          ON rw.id = target_reporting_week_id

        LEFT JOIN public.missionary_assignments ma
          ON ma.area_id = a.id
         AND ma.start_date <= rw.sunday
         AND (
             ma.end_date IS NULL
             OR ma.end_date >= rw.sunday
         )

        LEFT JOIN public.missionaries m
          ON m.id = ma.missionary_id

        WHERE a.district_id = target_district_id

        GROUP BY a.id
    )

    SELECT

        d.id::bigint,
        d.name::text,

        rw.id::bigint,
        rw.sunday::date,

        a.id::bigint,
        a.name::text,

        u.id::bigint,
        u.name::text,

        am.missionaries::text,

        wnm.id::bigint,
        wnm.new_member_id::bigint,
        wnm.display_order::integer,

        COALESCE(
            NULLIF(BTRIM(nm.display_name), ''),
            NULLIF(
                BTRIM(
                    COALESCE(nm.first_name, '') ||
                    ' ' ||
                    COALESCE(nm.last_name, '')
                ),
                ''
            )
        )::text AS person_name,

        nm.baptism_date::date,
        nm.confirmation_date::date,
        nm.finding_source::text,

        wnm.lessons_actual::integer,
        wnm.lessons_goal::integer,
        wnm.pmg_lessons_percentage::numeric,

        wnm.how_are_they_doing::text,

        wnm.discussed_in_gemiko::boolean,
        wnm.gemiko_support_plan::text,

        wnm.next_ordinance::text,
        wnm.at_church_this_sunday::boolean,

        wnm.has_calling::text,
        wnm.has_aaronic_priesthood::text,
        wnm.has_melchizedek_priesthood::text,
        wnm.ministers_to_someone::text,
        wnm.ministered_to_by_someone::boolean,

        wnm.has_active_temple_recommend::text,
        wnm.visited_temple_for_baptisms::text,

        wnm.reading::boolean,
        wnm.praying::boolean,
        wnm.member_involvement::boolean


    FROM public.weekly_new_members wnm

    JOIN public.weekly_area_reports war
      ON war.id = wnm.weekly_area_report_id

    JOIN public.reporting_weeks rw
      ON rw.id = war.reporting_week_id

    JOIN public.areas a
      ON a.id = war.area_id

    JOIN public.districts d
      ON d.id = a.district_id

    LEFT JOIN public.units u
      ON u.id = war.unit_id

    -- A Call-in New Member must correspond to a real
    -- permanent new_members record.
    JOIN public.new_members nm
      ON nm.id = wnm.new_member_id

    LEFT JOIN area_missionaries am
      ON am.area_id = a.id

    WHERE war.reporting_week_id = target_reporting_week_id
      AND a.district_id = target_district_id
      AND wnm.new_member_id IS NOT NULL

    ORDER BY
        a.name,
        wnm.display_order,
        person_name;

END;
$$;


ALTER FUNCTION public.get_dl_call_in_new_members(target_district_id bigint, target_reporting_week_id bigint) OWNER TO postgres;

--
-- Name: get_dl_call_in_nm_activity(bigint, bigint); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.get_dl_call_in_nm_activity(target_district_id bigint, target_reporting_week_id bigint) RETURNS TABLE(name text, companionship text, area text, active boolean)
    LANGUAGE plpgsql STABLE SECURITY DEFINER
    SET search_path TO 'public', 'pg_temp'
    AS $$
BEGIN

    IF NOT public.can_access_district(target_district_id) THEN
        RAISE EXCEPTION
            'You do not have permission to view this district.';
    END IF;


    RETURN QUERY

    WITH selected_week AS (
        SELECT rw.sunday
        FROM public.reporting_weeks rw
        WHERE rw.id = target_reporting_week_id
    )

    SELECT

        p.person_name::text AS name,
        COALESCE(p.missionaries, '—')::text AS companionship,
        p.area_name::text AS area,

        CASE

            -- ------------------------------------------------
            -- Newly baptized:
            -- Until they have roughly 3 weeks of history,
            -- judge activity based on this selected Sunday.
            -- ------------------------------------------------
            WHEN p.baptism_date IS NOT NULL
             AND p.baptism_date > sw.sunday - 21
            THEN
                COALESCE(
                    p.at_church_this_sunday,
                    false
                )


            -- ------------------------------------------------
            -- Established New Member:
            -- 2+ church attendances in selected week +
            -- previous three reporting weeks.
            -- ------------------------------------------------
            ELSE (
                SELECT COUNT(DISTINCT rw_hist.id) >= 2

                FROM public.weekly_new_members wnm_hist

                JOIN public.weekly_area_reports war_hist
                  ON war_hist.id =
                     wnm_hist.weekly_area_report_id

                JOIN public.reporting_weeks rw_hist
                  ON rw_hist.id =
                     war_hist.reporting_week_id

                WHERE wnm_hist.new_member_id =
                      p.new_member_id

                  AND rw_hist.sunday BETWEEN
                      sw.sunday - 21
                      AND sw.sunday

                  AND wnm_hist.at_church_this_sunday IS TRUE
            )

        END::boolean AS active


    FROM public.get_dl_call_in_new_members(
        target_district_id,
        target_reporting_week_id
    ) p

    CROSS JOIN selected_week sw

    ORDER BY
        p.area_name,
        p.person_name;

END;
$$;


ALTER FUNCTION public.get_dl_call_in_nm_activity(target_district_id bigint, target_reporting_week_id bigint) OWNER TO postgres;

--
-- Name: get_dl_call_in_summary(bigint, bigint); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.get_dl_call_in_summary(target_district_id bigint, target_reporting_week_id bigint) RETURNS TABLE(district_id bigint, district_name text, reporting_week_id bigint, reporting_sunday date, area_id bigint, area_name text, missionaries jsonb, dl_update text, report_count bigint, all_reports_submitted boolean, facebook_finding_days numeric, facebook_friends_found numeric, long_term_service boolean, friends_found_previous_goal numeric, friends_found_actual numeric, friends_found_goal numeric, friends_found_plan text, friends_found_plans jsonb, members_at_lessons_previous_goal numeric, members_at_lessons_actual numeric, members_at_lessons_goal numeric, members_at_lessons_plan text, members_at_lessons_plans jsonb, sacrament_attendance_previous_goal numeric, sacrament_attendance_actual numeric, sacrament_attendance_goal numeric, sacrament_attendance_plan text, sacrament_attendance_plans jsonb, baptismal_dates_previous_goal numeric, baptismal_dates_actual numeric, baptismal_dates_goal numeric, baptismal_dates_plan text, baptismal_dates_plans jsonb, baptisms_confirmations_previous_goal numeric, baptisms_confirmations_actual numeric, baptisms_confirmations_goal numeric, baptisms_confirmations_plan text, baptisms_confirmations_plans jsonb, nm_sacrament_previous_goal numeric, nm_sacrament_actual numeric, nm_sacrament_goal numeric, nm_sacrament_plan text, nm_sacrament_plans jsonb, follow_up_lessons_actual bigint, follow_up_lessons_goal bigint)
    LANGUAGE plpgsql STABLE SECURITY DEFINER
    SET search_path TO 'public', 'pg_temp'
    AS $$

DECLARE
    v_reporting_sunday date;
    v_previous_week_id bigint;

BEGIN

    -- --------------------------------------------------------
    -- Security
    -- --------------------------------------------------------

    IF NOT public.can_access_district(target_district_id) THEN
        RAISE EXCEPTION
            'You do not have permission to view this district.';
    END IF;


    -- --------------------------------------------------------
    -- Find selected reporting Sunday
    -- --------------------------------------------------------

    SELECT rw.sunday
    INTO v_reporting_sunday
    FROM public.reporting_weeks rw
    WHERE rw.id = target_reporting_week_id;


    IF v_reporting_sunday IS NULL THEN
        RAISE EXCEPTION
            'Reporting week % does not exist.',
            target_reporting_week_id;
    END IF;


    -- --------------------------------------------------------
    -- Find immediately previous reporting week
    -- --------------------------------------------------------

    SELECT rw.id
    INTO v_previous_week_id
    FROM public.reporting_weeks rw
    WHERE rw.sunday < v_reporting_sunday
    ORDER BY rw.sunday DESC
    LIMIT 1;


    RETURN QUERY

    WITH


    -- ========================================================
    -- AREAS IN DISTRICT
    -- ========================================================

    district_areas AS (

        SELECT
            a.id,
            a.name

        FROM public.areas a

        WHERE a.district_id = target_district_id
          AND a.active = true
    ),


    -- ========================================================
    -- CURRENT WEEK REPORTS
    --
    -- There can be multiple rows for the same area because
    -- an area may report for multiple units.
    -- ========================================================

    current_reports AS (

        SELECT
            war.id AS weekly_area_report_id,
            war.area_id,
            war.unit_id,
            war.status,

            -- Canonical stable KPI values
            war.friends_found_actual,
            war.friends_found_goal,
            war.lessons_with_members_actual,
            war.lessons_with_members_goal,
            war.sacrament_attendance_actual,
            war.sacrament_attendance_goal,
            war.baptismal_dates_actual,
            war.baptismal_dates_goal,
            war.baptisms_confirmations_actual,
            war.baptisms_confirmations_goal,
            war.new_member_sacrament_actual,
            war.new_member_sacrament_goal,

            war.follow_up_lessons_actual,
            war.follow_up_lessons_goal

        FROM public.weekly_area_reports war

        WHERE war.reporting_week_id = target_reporting_week_id
    ),


    -- ========================================================
    -- PREVIOUS WEEK REPORTS
    -- ========================================================

    previous_reports AS (

        SELECT
            war.id AS weekly_area_report_id,
            war.area_id,
            war.unit_id,

            -- Previous-week canonical goals
            war.friends_found_goal,
            war.lessons_with_members_goal,
            war.sacrament_attendance_goal,
            war.baptismal_dates_goal,
            war.baptisms_confirmations_goal,
            war.new_member_sacrament_goal

        FROM public.weekly_area_reports war

        WHERE war.reporting_week_id = v_previous_week_id
    ),


    -- ========================================================
    -- CURRENT WEEK ANSWERS
    -- ========================================================

    current_answers AS (

        SELECT
            cr.area_id,
            cr.unit_id,
            wpa.question_key,
            wpa.answer_number,
            wpa.answer_text,
            wpa.answer_boolean

        FROM current_reports cr

        JOIN public.weekly_planning_answers wpa
          ON wpa.weekly_area_report_id = cr.weekly_area_report_id
    ),


    -- ========================================================
    -- PREVIOUS WEEK ANSWERS
    -- ========================================================

    previous_answers AS (

        SELECT
            pr.area_id,
            pr.unit_id,
            wpa.question_key,
            wpa.answer_number,
            wpa.answer_text,
            wpa.answer_boolean

        FROM previous_reports pr

        JOIN public.weekly_planning_answers wpa
          ON wpa.weekly_area_report_id = pr.weekly_area_report_id
    ),


    -- ========================================================
    -- CURRENT NUMERIC ANSWERS
    --
    -- SUM across units so each area becomes one DL row.
    -- ========================================================

    current_numbers AS (

        SELECT
            cr.area_id,

            -- Flexible/non-core values remain in weekly_planning_answers
            fa.facebook_finding_days,
            fa.facebook_friends_found,

            -- Stable KPIs come from weekly_area_reports and are summed
            -- across unit reports to produce one district-call-in row per area.
            SUM(COALESCE(cr.friends_found_actual, 0))::numeric
                AS friends_found_actual,

            SUM(COALESCE(cr.friends_found_goal, 0))::numeric
                AS friends_found_goal,

            SUM(COALESCE(cr.lessons_with_members_actual, 0))::numeric
                AS members_at_lessons_actual,

            SUM(COALESCE(cr.lessons_with_members_goal, 0))::numeric
                AS members_at_lessons_goal,

            SUM(COALESCE(cr.sacrament_attendance_actual, 0))::numeric
                AS sacrament_attendance_actual,

            SUM(COALESCE(cr.sacrament_attendance_goal, 0))::numeric
                AS sacrament_attendance_goal,

            SUM(COALESCE(cr.baptismal_dates_actual, 0))::numeric
                AS baptismal_dates_actual,

            SUM(COALESCE(cr.baptismal_dates_goal, 0))::numeric
                AS baptismal_dates_goal,

            SUM(COALESCE(cr.baptisms_confirmations_actual, 0))::numeric
                AS baptisms_confirmations_actual,

            SUM(COALESCE(cr.baptisms_confirmations_goal, 0))::numeric
                AS baptisms_confirmations_goal,

            SUM(COALESCE(cr.new_member_sacrament_actual, 0))::numeric
                AS nm_sacrament_actual,

            SUM(COALESCE(cr.new_member_sacrament_goal, 0))::numeric
                AS nm_sacrament_goal

        FROM current_reports cr

        LEFT JOIN (
            SELECT
                ca.area_id,

                SUM(ca.answer_number)
                    FILTER (
                        WHERE ca.question_key = 'facebook_finding_days'
                    )
                    AS facebook_finding_days,

                SUM(ca.answer_number)
                    FILTER (
                        WHERE ca.question_key = 'facebook_friends_found'
                    )
                    AS facebook_friends_found

            FROM current_answers ca
            GROUP BY ca.area_id
        ) fa
          ON fa.area_id = cr.area_id

        GROUP BY
            cr.area_id,
            fa.facebook_finding_days,
            fa.facebook_friends_found
    ),


    -- ========================================================
    -- PREVIOUS WEEK GOALS
    --
    -- These become "Last Week Goal" in the call-in sheet.
    -- ========================================================

    previous_goals AS (

        SELECT
            pr.area_id,

            SUM(COALESCE(pr.friends_found_goal, 0))::numeric
                AS friends_found_previous_goal,

            SUM(COALESCE(pr.lessons_with_members_goal, 0))::numeric
                AS members_at_lessons_previous_goal,

            SUM(COALESCE(pr.sacrament_attendance_goal, 0))::numeric
                AS sacrament_attendance_previous_goal,

            SUM(COALESCE(pr.baptismal_dates_goal, 0))::numeric
                AS baptismal_dates_previous_goal,

            SUM(COALESCE(pr.baptisms_confirmations_goal, 0))::numeric
                AS baptisms_confirmations_previous_goal,

            SUM(COALESCE(pr.new_member_sacrament_goal, 0))::numeric
                AS nm_sacrament_previous_goal

        FROM previous_reports pr

        GROUP BY pr.area_id
    ),


    -- ========================================================
    -- LONG TERM SERVICE
    --
    -- TRUE if any unit report for the area says true.
    -- ========================================================

    boolean_answers AS (

        SELECT

            ca.area_id,

            BOOL_OR(
                COALESCE(ca.answer_boolean, false)
            )
            FILTER (
                WHERE ca.question_key = 'long_term_service'
            )
            AS long_term_service

        FROM current_answers ca

        GROUP BY ca.area_id
    ),


    -- ========================================================
    -- ACTION PLANS
    --
    -- Two representations are returned:
    --
    -- 1. *_plan
    --    simple combined text for easy Appsmith display
    --
    -- 2. *_plans
    --    JSON preserving each unit/report separately
    -- ========================================================

    action_plans AS (

        SELECT

            ca.area_id,


            STRING_AGG(
                DISTINCT NULLIF(BTRIM(ca.answer_text), ''),
                E'\n\n'
            )
            FILTER (
                WHERE ca.question_key = 'friends_found_plan'
                  AND NULLIF(BTRIM(ca.answer_text), '') IS NOT NULL
            )
            AS friends_found_plan,

            COALESCE(
                JSONB_AGG(
                    JSONB_BUILD_OBJECT(
                        'unit_id', ca.unit_id,
                        'plan', ca.answer_text
                    )
                    ORDER BY ca.unit_id
                )
                FILTER (
                    WHERE ca.question_key = 'friends_found_plan'
                      AND NULLIF(BTRIM(ca.answer_text), '') IS NOT NULL
                ),
                '[]'::jsonb
            )
            AS friends_found_plans,


            STRING_AGG(
                DISTINCT NULLIF(BTRIM(ca.answer_text), ''),
                E'\n\n'
            )
            FILTER (
                WHERE ca.question_key = 'members_at_lessons_plan'
                  AND NULLIF(BTRIM(ca.answer_text), '') IS NOT NULL
            )
            AS members_at_lessons_plan,

            COALESCE(
                JSONB_AGG(
                    JSONB_BUILD_OBJECT(
                        'unit_id', ca.unit_id,
                        'plan', ca.answer_text
                    )
                    ORDER BY ca.unit_id
                )
                FILTER (
                    WHERE ca.question_key = 'members_at_lessons_plan'
                      AND NULLIF(BTRIM(ca.answer_text), '') IS NOT NULL
                ),
                '[]'::jsonb
            )
            AS members_at_lessons_plans,


            STRING_AGG(
                DISTINCT NULLIF(BTRIM(ca.answer_text), ''),
                E'\n\n'
            )
            FILTER (
                WHERE ca.question_key = 'sacrament_attendance_plan'
                  AND NULLIF(BTRIM(ca.answer_text), '') IS NOT NULL
            )
            AS sacrament_attendance_plan,

            COALESCE(
                JSONB_AGG(
                    JSONB_BUILD_OBJECT(
                        'unit_id', ca.unit_id,
                        'plan', ca.answer_text
                    )
                    ORDER BY ca.unit_id
                )
                FILTER (
                    WHERE ca.question_key = 'sacrament_attendance_plan'
                      AND NULLIF(BTRIM(ca.answer_text), '') IS NOT NULL
                ),
                '[]'::jsonb
            )
            AS sacrament_attendance_plans,


            STRING_AGG(
                DISTINCT NULLIF(BTRIM(ca.answer_text), ''),
                E'\n\n'
            )
            FILTER (
                WHERE ca.question_key = 'baptismal_dates_plan'
                  AND NULLIF(BTRIM(ca.answer_text), '') IS NOT NULL
            )
            AS baptismal_dates_plan,

            COALESCE(
                JSONB_AGG(
                    JSONB_BUILD_OBJECT(
                        'unit_id', ca.unit_id,
                        'plan', ca.answer_text
                    )
                    ORDER BY ca.unit_id
                )
                FILTER (
                    WHERE ca.question_key = 'baptismal_dates_plan'
                      AND NULLIF(BTRIM(ca.answer_text), '') IS NOT NULL
                ),
                '[]'::jsonb
            )
            AS baptismal_dates_plans,


            STRING_AGG(
                DISTINCT NULLIF(BTRIM(ca.answer_text), ''),
                E'\n\n'
            )
            FILTER (
                WHERE ca.question_key = 'baptisms_confirmations_plan'
                  AND NULLIF(BTRIM(ca.answer_text), '') IS NOT NULL
            )
            AS baptisms_confirmations_plan,

            COALESCE(
                JSONB_AGG(
                    JSONB_BUILD_OBJECT(
                        'unit_id', ca.unit_id,
                        'plan', ca.answer_text
                    )
                    ORDER BY ca.unit_id
                )
                FILTER (
                    WHERE ca.question_key = 'baptisms_confirmations_plan'
                      AND NULLIF(BTRIM(ca.answer_text), '') IS NOT NULL
                ),
                '[]'::jsonb
            )
            AS baptisms_confirmations_plans,


            STRING_AGG(
                DISTINCT NULLIF(BTRIM(ca.answer_text), ''),
                E'\n\n'
            )
            FILTER (
                WHERE ca.question_key = 'nm_sacrament_attendance_plan'
                  AND NULLIF(BTRIM(ca.answer_text), '') IS NOT NULL
            )
            AS nm_sacrament_plan,

            COALESCE(
                JSONB_AGG(
                    JSONB_BUILD_OBJECT(
                        'unit_id', ca.unit_id,
                        'plan', ca.answer_text
                    )
                    ORDER BY ca.unit_id
                )
                FILTER (
                    WHERE ca.question_key = 'nm_sacrament_attendance_plan'
                      AND NULLIF(BTRIM(ca.answer_text), '') IS NOT NULL
                ),
                '[]'::jsonb
            )
            AS nm_sacrament_plans

        FROM current_answers ca

        GROUP BY ca.area_id
    ),


    -- ========================================================
    -- REPORT STATUS / FOLLOW-UP LESSONS
    -- ========================================================

    report_rollup AS (

        SELECT

            cr.area_id,

            COUNT(*) AS report_count,

            BOOL_AND(
                cr.status IN ('SUBMITTED', 'LOCKED')
            ) AS all_reports_submitted,

            SUM(
                COALESCE(cr.follow_up_lessons_actual, 0)
            )::bigint
                AS follow_up_lessons_actual,

            SUM(
                COALESCE(cr.follow_up_lessons_goal, 0)
            )::bigint
                AS follow_up_lessons_goal

        FROM current_reports cr

        GROUP BY cr.area_id
    ),


    -- ========================================================
    -- MISSIONARIES ASSIGNED TO AREA DURING REPORTING WEEK
    --
    -- This is week-aware, not merely "who is assigned today."
    -- ========================================================

    area_missionaries AS (

        SELECT

            da.id AS area_id,

            COALESCE(
                JSONB_AGG(
                    DISTINCT JSONB_BUILD_OBJECT(
                        'missionary_id', m.id,
                        'display_name', m.display_name,
                        'first_name', m.first_name,
                        'last_name', m.last_name,
                        'missionary_type', m.missionary_type,
                        'roster_position', ma.roster_position,
                        'roster_position_abbr', ma.roster_position_abbr
                    )
                )
                FILTER (
                    WHERE m.id IS NOT NULL
                ),
                '[]'::jsonb
            ) AS missionaries

        FROM district_areas da

        LEFT JOIN public.missionary_assignments ma
          ON ma.area_id = da.id
         AND ma.start_date <= v_reporting_sunday
         AND (
              ma.end_date IS NULL
              OR ma.end_date >= v_reporting_sunday
         )

        LEFT JOIN public.missionaries m
          ON m.id = ma.missionary_id

        GROUP BY da.id
    ),


    -- ========================================================
    -- MANUAL DL AREA UPDATE
    -- ========================================================

    manual_updates AS (

        SELECT
            ciau.area_id,
            ciau.update_text

        FROM public.call_in_area_updates ciau

        JOIN public.call_in_districts cid
          ON cid.id = ciau.district_call_in_id

        WHERE cid.district_id = target_district_id
          AND cid.reporting_week_id = target_reporting_week_id
    )


    -- ========================================================
    -- FINAL AREA-LEVEL RESULT
    -- ========================================================

    SELECT

        d.id::bigint AS district_id,
        d.name::text AS district_name,

        rw.id::bigint AS reporting_week_id,
        rw.sunday::date AS reporting_sunday,

        da.id::bigint AS area_id,
        da.name::text AS area_name,

        COALESCE(
            am.missionaries,
            '[]'::jsonb
        ) AS missionaries,

        mu.update_text::text AS dl_update,

        COALESCE(
            rr.report_count,
            0
        )::bigint AS report_count,

        COALESCE(
            rr.all_reports_submitted,
            false
        )::boolean AS all_reports_submitted,


        cn.facebook_finding_days,
        cn.facebook_friends_found,

        COALESCE(
            ba.long_term_service,
            false
        ) AS long_term_service,


        pg.friends_found_previous_goal,
        cn.friends_found_actual,
        cn.friends_found_goal,
        ap.friends_found_plan,
        COALESCE(
            ap.friends_found_plans,
            '[]'::jsonb
        ),


        pg.members_at_lessons_previous_goal,
        cn.members_at_lessons_actual,
        cn.members_at_lessons_goal,
        ap.members_at_lessons_plan,
        COALESCE(
            ap.members_at_lessons_plans,
            '[]'::jsonb
        ),


        pg.sacrament_attendance_previous_goal,
        cn.sacrament_attendance_actual,
        cn.sacrament_attendance_goal,
        ap.sacrament_attendance_plan,
        COALESCE(
            ap.sacrament_attendance_plans,
            '[]'::jsonb
        ),


        pg.baptismal_dates_previous_goal,
        cn.baptismal_dates_actual,
        cn.baptismal_dates_goal,
        ap.baptismal_dates_plan,
        COALESCE(
            ap.baptismal_dates_plans,
            '[]'::jsonb
        ),


        pg.baptisms_confirmations_previous_goal,
        cn.baptisms_confirmations_actual,
        cn.baptisms_confirmations_goal,
        ap.baptisms_confirmations_plan,
        COALESCE(
            ap.baptisms_confirmations_plans,
            '[]'::jsonb
        ),


        pg.nm_sacrament_previous_goal,
        cn.nm_sacrament_actual,
        cn.nm_sacrament_goal,
        ap.nm_sacrament_plan,
        COALESCE(
            ap.nm_sacrament_plans,
            '[]'::jsonb
        ),


        COALESCE(
            rr.follow_up_lessons_actual,
            0
        )::bigint,

        COALESCE(
            rr.follow_up_lessons_goal,
            0
        )::bigint


    FROM district_areas da

    JOIN public.districts d
      ON d.id = target_district_id

    JOIN public.reporting_weeks rw
      ON rw.id = target_reporting_week_id

    LEFT JOIN area_missionaries am
      ON am.area_id = da.id

    LEFT JOIN manual_updates mu
      ON mu.area_id = da.id

    LEFT JOIN report_rollup rr
      ON rr.area_id = da.id

    LEFT JOIN current_numbers cn
      ON cn.area_id = da.id

    LEFT JOIN previous_goals pg
      ON pg.area_id = da.id

    LEFT JOIN boolean_answers ba
      ON ba.area_id = da.id

    LEFT JOIN action_plans ap
      ON ap.area_id = da.id

    ORDER BY da.name;

END;
$$;


ALTER FUNCTION public.get_dl_call_in_summary(target_district_id bigint, target_reporting_week_id bigint) OWNER TO postgres;

--
-- Name: get_dl_call_in_summary_with_planning(bigint, bigint); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.get_dl_call_in_summary_with_planning(target_district_id bigint, target_reporting_week_id bigint) RETURNS jsonb
    LANGUAGE plpgsql STABLE SECURITY DEFINER
    SET search_path TO 'public', 'pg_temp'
    AS $_$
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
$_$;


ALTER FUNCTION public.get_dl_call_in_summary_with_planning(target_district_id bigint, target_reporting_week_id bigint) OWNER TO postgres;

--
-- Name: get_dl_call_in_ward_coordination(bigint, bigint); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.get_dl_call_in_ward_coordination(target_district_id bigint, target_reporting_week_id bigint) RETURNS TABLE(district_id bigint, district_name text, reporting_week_id bigint, reporting_sunday date, area_id bigint, area_name text, unit_id bigint, unit_name text, weekly_area_report_id bigint, ward_coordination_held boolean, ward_coordination_attendance jsonb)
    LANGUAGE plpgsql STABLE SECURITY DEFINER
    SET search_path TO 'public', 'pg_temp'
    AS $$

BEGIN

    -- --------------------------------------------------------
    -- Security
    -- --------------------------------------------------------

    IF NOT public.can_access_district(target_district_id) THEN
        RAISE EXCEPTION
            'You do not have permission to view this district.';
    END IF;


    RETURN QUERY

    SELECT

        d.id::bigint AS district_id,
        d.name::text AS district_name,

        rw.id::bigint AS reporting_week_id,
        rw.sunday::date AS reporting_sunday,

        a.id::bigint AS area_id,
        a.name::text AS area_name,

        u.id::bigint AS unit_id,
        u.name::text AS unit_name,

        war.id::bigint AS weekly_area_report_id,


        -- Was ward coordination / Gemiko held?
        held.answer_boolean::boolean
            AS ward_coordination_held,


        -- Attendance grid exactly as entered in Weekly Planning.
        COALESCE(
            attendance.answer_json,
            '{}'::jsonb
        )::jsonb
            AS ward_coordination_attendance


    FROM public.weekly_area_reports war

    JOIN public.reporting_weeks rw
      ON rw.id = war.reporting_week_id

    JOIN public.areas a
      ON a.id = war.area_id

    JOIN public.districts d
      ON d.id = a.district_id

    LEFT JOIN public.units u
      ON u.id = war.unit_id


    LEFT JOIN public.weekly_planning_answers held
      ON held.weekly_area_report_id = war.id
     AND held.question_key = 'ward_coordination_held'


    LEFT JOIN public.weekly_planning_answers attendance
      ON attendance.weekly_area_report_id = war.id
     AND attendance.question_key = 'ward_coordination_attendance'


    WHERE war.reporting_week_id = target_reporting_week_id
      AND a.district_id = target_district_id


    ORDER BY
        a.name,
        u.name;

END;
$$;


ALTER FUNCTION public.get_dl_call_in_ward_coordination(target_district_id bigint, target_reporting_week_id bigint) OWNER TO postgres;

--
-- Name: get_mission_call_in_bd_activity(bigint, bigint); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.get_mission_call_in_bd_activity(target_mission_id bigint, target_reporting_week_id bigint) RETURNS TABLE(name text, companionship text, area text, active boolean)
    LANGUAGE plpgsql STABLE SECURITY DEFINER
    SET search_path TO 'public', 'pg_temp'
    AS $$
BEGIN

    IF NOT public.can_access_mission(target_mission_id) THEN
        RAISE EXCEPTION
            'You do not have permission to view this mission.';
    END IF;

    RETURN QUERY

    SELECT
        x.name,
        x.companionship,
        x.area,
        x.active

    FROM public.zones z

    JOIN LATERAL
        public.get_zl_call_in_bd_activity(
            z.id,
            target_reporting_week_id
        ) x
      ON true

    WHERE z.mission_id = target_mission_id

    ORDER BY
        z.name,
        x.area,
        x.name;

END;
$$;


ALTER FUNCTION public.get_mission_call_in_bd_activity(target_mission_id bigint, target_reporting_week_id bigint) OWNER TO postgres;

--
-- Name: get_mission_call_in_hp_activity(bigint, bigint); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.get_mission_call_in_hp_activity(target_mission_id bigint, target_reporting_week_id bigint) RETURNS TABLE(name text, companionship text, area text, active boolean)
    LANGUAGE plpgsql STABLE SECURITY DEFINER
    SET search_path TO 'public', 'pg_temp'
    AS $$
BEGIN

    IF NOT public.can_access_mission(target_mission_id) THEN
        RAISE EXCEPTION
            'You do not have permission to view this mission.';
    END IF;

    RETURN QUERY

    SELECT
        x.name,
        x.companionship,
        x.area,
        x.active

    FROM public.zones z

    JOIN LATERAL
        public.get_zl_call_in_hp_activity(
            z.id,
            target_reporting_week_id
        ) x
      ON true

    WHERE z.mission_id = target_mission_id

    ORDER BY
        z.name,
        x.area,
        x.name;

END;
$$;


ALTER FUNCTION public.get_mission_call_in_hp_activity(target_mission_id bigint, target_reporting_week_id bigint) OWNER TO postgres;

--
-- Name: get_mission_call_in_nm_activity(bigint, bigint); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.get_mission_call_in_nm_activity(target_mission_id bigint, target_reporting_week_id bigint) RETURNS TABLE(name text, companionship text, area text, active boolean)
    LANGUAGE plpgsql STABLE SECURITY DEFINER
    SET search_path TO 'public', 'pg_temp'
    AS $$
BEGIN

    IF NOT public.can_access_mission(target_mission_id) THEN
        RAISE EXCEPTION
            'You do not have permission to view this mission.';
    END IF;

    RETURN QUERY

    SELECT
        x.name,
        x.companionship,
        x.area,
        x.active

    FROM public.zones z

    JOIN LATERAL
        public.get_zl_call_in_nm_activity(
            z.id,
            target_reporting_week_id
        ) x
      ON true

    WHERE z.mission_id = target_mission_id

    ORDER BY
        z.name,
        x.area,
        x.name;

END;
$$;


ALTER FUNCTION public.get_mission_call_in_nm_activity(target_mission_id bigint, target_reporting_week_id bigint) OWNER TO postgres;

--
-- Name: get_mission_call_in_summary(bigint, bigint); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.get_mission_call_in_summary(target_mission_id bigint, target_reporting_week_id bigint) RETURNS TABLE(mission_id bigint, mission_name text, reporting_week_id bigint, reporting_sunday date, zone_id bigint, zone_name text, zone_notes text, district_count integer, completed_district_count integer, all_dl_call_ins_complete boolean, all_weekly_reports_submitted boolean, area_count integer, friends_found_previous_goal numeric, friends_found_actual numeric, friends_found_goal numeric, members_at_lessons_previous_goal numeric, members_at_lessons_actual numeric, members_at_lessons_goal numeric, sacrament_attendance_previous_goal numeric, sacrament_attendance_actual numeric, sacrament_attendance_goal numeric, baptismal_dates_previous_goal numeric, baptismal_dates_actual numeric, baptismal_dates_goal numeric, baptisms_confirmations_previous_goal numeric, baptisms_confirmations_actual numeric, baptisms_confirmations_goal numeric, nm_sacrament_previous_goal numeric, nm_sacrament_actual numeric, nm_sacrament_goal numeric, follow_up_lessons_actual numeric, follow_up_lessons_goal numeric)
    LANGUAGE plpgsql STABLE SECURITY DEFINER
    SET search_path TO 'public', 'pg_temp'
    AS $$

BEGIN

    IF NOT public.can_access_mission(target_mission_id) THEN
        RAISE EXCEPTION
            'You do not have permission to view this mission.';
    END IF;


    RETURN QUERY

    SELECT

        m.id::bigint AS mission_id,
        m.name::text AS mission_name,

        rw.id::bigint AS reporting_week_id,
        rw.sunday::date AS reporting_sunday,

        z.id::bigint AS zone_id,
        z.name::text AS zone_name,

        ciz.zone_notes::text,

        COUNT(s.district_id)::integer
            AS district_count,

        COUNT(*) FILTER (
            WHERE s.dl_call_in_complete IS TRUE
        )::integer
            AS completed_district_count,

        CASE
            WHEN COUNT(s.district_id) = 0 THEN false
            ELSE BOOL_AND(
                COALESCE(s.dl_call_in_complete, false)
            )
        END::boolean
            AS all_dl_call_ins_complete,

        CASE
            WHEN COUNT(s.district_id) = 0 THEN false
            ELSE BOOL_AND(
                COALESCE(s.all_weekly_reports_submitted, false)
            )
        END::boolean
            AS all_weekly_reports_submitted,

        COALESCE(SUM(s.area_count), 0)::integer
            AS area_count,


        SUM(s.friends_found_previous_goal)::numeric,
        SUM(s.friends_found_actual)::numeric,
        SUM(s.friends_found_goal)::numeric,


        SUM(s.members_at_lessons_previous_goal)::numeric,
        SUM(s.members_at_lessons_actual)::numeric,
        SUM(s.members_at_lessons_goal)::numeric,


        SUM(s.sacrament_attendance_previous_goal)::numeric,
        SUM(s.sacrament_attendance_actual)::numeric,
        SUM(s.sacrament_attendance_goal)::numeric,


        SUM(s.baptismal_dates_previous_goal)::numeric,
        SUM(s.baptismal_dates_actual)::numeric,
        SUM(s.baptismal_dates_goal)::numeric,


        SUM(s.baptisms_confirmations_previous_goal)::numeric,
        SUM(s.baptisms_confirmations_actual)::numeric,
        SUM(s.baptisms_confirmations_goal)::numeric,


        SUM(s.nm_sacrament_previous_goal)::numeric,
        SUM(s.nm_sacrament_actual)::numeric,
        SUM(s.nm_sacrament_goal)::numeric,


        SUM(s.follow_up_lessons_actual)::numeric,
        SUM(s.follow_up_lessons_goal)::numeric


    FROM public.missions m

    JOIN public.zones z
      ON z.mission_id = m.id

    JOIN public.reporting_weeks rw
      ON rw.id = target_reporting_week_id


    LEFT JOIN LATERAL
        public.get_zl_call_in_summary(
            z.id,
            target_reporting_week_id
        ) s
      ON true


    LEFT JOIN public.call_in_zones ciz
      ON ciz.zone_id = z.id
     AND ciz.reporting_week_id = target_reporting_week_id


    WHERE m.id = target_mission_id


    GROUP BY

        m.id,
        m.name,

        rw.id,
        rw.sunday,

        z.id,
        z.name,

        ciz.zone_notes


    ORDER BY z.name;

END;
$$;


ALTER FUNCTION public.get_mission_call_in_summary(target_mission_id bigint, target_reporting_week_id bigint) OWNER TO postgres;

--
-- Name: get_mission_call_in_summary_with_planning(bigint, bigint); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.get_mission_call_in_summary_with_planning(target_mission_id bigint, target_reporting_week_id bigint) RETURNS jsonb
    LANGUAGE plpgsql STABLE SECURITY DEFINER
    SET search_path TO 'public', 'pg_temp'
    AS $_$
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
$_$;


ALTER FUNCTION public.get_mission_call_in_summary_with_planning(target_mission_id bigint, target_reporting_week_id bigint) OWNER TO postgres;

--
-- Name: get_previous_planning_answers(bigint); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.get_previous_planning_answers(target_unit_id bigint) RETURNS TABLE(question_key text, answer_text text, answer_number numeric, answer_boolean boolean, answer_json jsonb)
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'public'
    AS $$
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
    SELECT
        wpa.question_key,
        wpa.answer_text,
        wpa.answer_number,
        wpa.answer_boolean,
        wpa.answer_json
    FROM public.weekly_planning_answers wpa
    WHERE
        wpa.weekly_area_report_id =
        v_previous_report_id;
END;
$$;


ALTER FUNCTION public.get_previous_planning_answers(target_unit_id bigint) OWNER TO postgres;

--
-- Name: weekly_new_members; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.weekly_new_members (
    id bigint NOT NULL,
    weekly_area_report_id bigint NOT NULL,
    display_order integer DEFAULT 0 NOT NULL,
    lessons_actual integer,
    lessons_goal integer,
    pmg_lessons_percentage numeric,
    how_are_they_doing text,
    discussed_in_gemiko boolean,
    gemiko_support_plan text,
    next_ordinance text,
    at_church_this_sunday boolean,
    has_calling text,
    has_aaronic_priesthood text,
    has_melchizedek_priesthood text,
    ministers_to_someone text,
    ministered_to_by_someone boolean,
    has_active_temple_recommend text,
    visited_temple_for_baptisms text,
    reading boolean,
    praying boolean,
    member_involvement boolean,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    new_member_id bigint,
    CONSTRAINT weekly_new_members_has_aaronic_priesthood_check CHECK (((has_aaronic_priesthood IS NULL) OR (has_aaronic_priesthood = ANY (ARRAY['yes'::text, 'no'::text, 'not_applicable'::text])))),
    CONSTRAINT weekly_new_members_has_active_temple_recommend_check CHECK (((has_active_temple_recommend IS NULL) OR (has_active_temple_recommend = ANY (ARRAY['yes'::text, 'no'::text, 'not_applicable'::text])))),
    CONSTRAINT weekly_new_members_has_calling_check CHECK (((has_calling IS NULL) OR (has_calling = ANY (ARRAY['yes'::text, 'no'::text, 'not_applicable'::text])))),
    CONSTRAINT weekly_new_members_has_melchizedek_priesthood_check CHECK (((has_melchizedek_priesthood IS NULL) OR (has_melchizedek_priesthood = ANY (ARRAY['yes'::text, 'no'::text, 'not_applicable'::text])))),
    CONSTRAINT weekly_new_members_ministers_to_someone_check CHECK (((ministers_to_someone IS NULL) OR (ministers_to_someone = ANY (ARRAY['yes'::text, 'no'::text, 'not_applicable'::text])))),
    CONSTRAINT weekly_new_members_visited_temple_for_baptisms_check CHECK (((visited_temple_for_baptisms IS NULL) OR (visited_temple_for_baptisms = ANY (ARRAY['yes'::text, 'no'::text, 'not_applicable'::text]))))
);


ALTER TABLE public.weekly_new_members OWNER TO postgres;

--
-- Name: get_previous_weekly_new_members(bigint); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.get_previous_weekly_new_members(target_unit_id bigint) RETURNS SETOF public.weekly_new_members
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'public', 'pg_temp'
    AS $$
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
$$;


ALTER FUNCTION public.get_previous_weekly_new_members(target_unit_id bigint) OWNER TO postgres;

--
-- Name: get_zl_call_in_area_updates(bigint, bigint); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.get_zl_call_in_area_updates(target_zone_id bigint, target_reporting_week_id bigint) RETURNS TABLE(zone_id bigint, zone_name text, reporting_week_id bigint, reporting_sunday date, district_id bigint, district_name text, area_id bigint, area_name text, missionaries jsonb, dl_update text, report_count bigint, all_reports_submitted boolean)
    LANGUAGE plpgsql STABLE SECURITY DEFINER
    SET search_path TO 'public', 'pg_temp'
    AS $$

BEGIN

    IF NOT public.can_access_zone(target_zone_id) THEN
        RAISE EXCEPTION
            'You do not have permission to view this zone.';
    END IF;


    RETURN QUERY

    SELECT

        z.id::bigint,
        z.name::text,

        s.reporting_week_id::bigint,
        s.reporting_sunday::date,

        d.id::bigint,
        d.name::text,

        s.area_id::bigint,
        s.area_name::text,

        s.missionaries::jsonb,

        s.dl_update::text,

        s.report_count::bigint,
        s.all_reports_submitted::boolean


    FROM public.zones z

    JOIN public.districts d
      ON d.zone_id = z.id

    JOIN LATERAL
        public.get_dl_call_in_summary(
            d.id,
            target_reporting_week_id
        ) s
      ON true

    WHERE z.id = target_zone_id

    ORDER BY
        d.name,
        s.area_name;

END;
$$;


ALTER FUNCTION public.get_zl_call_in_area_updates(target_zone_id bigint, target_reporting_week_id bigint) OWNER TO postgres;

--
-- Name: get_zl_call_in_baptismal_dates(bigint, bigint); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.get_zl_call_in_baptismal_dates(target_zone_id bigint, target_reporting_week_id bigint) RETURNS TABLE(zone_id bigint, zone_name text, district_id bigint, district_name text, reporting_week_id bigint, reporting_sunday date, area_id bigint, area_name text, unit_id bigint, unit_name text, missionaries text, weekly_baptismal_date_friend_id bigint, baptismal_date_person_id bigint, display_order integer, person_name text, finding_source text, baptismal_date_set_on date, current_baptismal_date date, days_until_baptism integer, weeks_until_baptism numeric, reading boolean, praying boolean, at_church_this_sunday boolean, keeping_commandments boolean, member_involvement boolean, stake_id bigint)
    LANGUAGE plpgsql STABLE SECURITY DEFINER
    SET search_path TO 'public', 'pg_temp'
    AS $$
BEGIN

    IF NOT public.can_access_zone(target_zone_id) THEN
        RAISE EXCEPTION
            'You do not have permission to view this zone.';
    END IF;

    RETURN QUERY

    SELECT
        z.id::bigint,
        z.name::text,

        d.id::bigint,
        d.name::text,

        p.reporting_week_id,
        p.reporting_sunday,

        p.area_id,
        p.area_name,

        p.unit_id,
        p.unit_name,

        p.missionaries,

        p.weekly_baptismal_date_friend_id,
        p.baptismal_date_person_id,
        p.display_order,

        p.person_name,
        p.finding_source,

        p.baptismal_date_set_on,
        p.current_baptismal_date,

        p.days_until_baptism,
        p.weeks_until_baptism,

        p.reading,
        p.praying,
        p.at_church_this_sunday,
        p.keeping_commandments,
        p.member_involvement,

        p.stake_id

    FROM public.zones z

    JOIN public.districts d
      ON d.zone_id = z.id

    JOIN LATERAL
        public.get_dl_call_in_baptismal_dates(
            d.id,
            target_reporting_week_id
        ) p
      ON true

    WHERE z.id = target_zone_id

    ORDER BY
        d.name,
        p.area_name,
        p.display_order,
        p.person_name;

END;
$$;


ALTER FUNCTION public.get_zl_call_in_baptismal_dates(target_zone_id bigint, target_reporting_week_id bigint) OWNER TO postgres;

--
-- Name: get_zl_call_in_bd_activity(bigint, bigint); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.get_zl_call_in_bd_activity(target_zone_id bigint, target_reporting_week_id bigint) RETURNS TABLE(name text, companionship text, area text, active boolean)
    LANGUAGE plpgsql STABLE SECURITY DEFINER
    SET search_path TO 'public', 'pg_temp'
    AS $$
BEGIN

    IF NOT public.can_access_zone(target_zone_id) THEN
        RAISE EXCEPTION
            'You do not have permission to view this zone.';
    END IF;


    RETURN QUERY

    SELECT
        x.name,
        x.companionship,
        x.area,
        x.active

    FROM public.districts d

    JOIN LATERAL
        public.get_dl_call_in_bd_activity(
            d.id,
            target_reporting_week_id
        ) x
      ON true

    WHERE d.zone_id = target_zone_id

    ORDER BY
        d.name,
        x.area,
        x.name;

END;
$$;


ALTER FUNCTION public.get_zl_call_in_bd_activity(target_zone_id bigint, target_reporting_week_id bigint) OWNER TO postgres;

--
-- Name: get_zl_call_in_high_potentials(bigint, bigint); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.get_zl_call_in_high_potentials(target_zone_id bigint, target_reporting_week_id bigint) RETURNS TABLE(zone_id bigint, zone_name text, district_id bigint, district_name text, reporting_week_id bigint, reporting_sunday date, area_id bigint, area_name text, unit_id bigint, unit_name text, missionaries text, weekly_high_potential_id bigint, display_order integer, person_name text, at_church_this_sunday boolean, notes text)
    LANGUAGE plpgsql STABLE SECURITY DEFINER
    SET search_path TO 'public', 'pg_temp'
    AS $$
BEGIN

    IF NOT public.can_access_zone(target_zone_id) THEN
        RAISE EXCEPTION
            'You do not have permission to view this zone.';
    END IF;

    RETURN QUERY

    SELECT
        z.id::bigint,
        z.name::text,

        d.id::bigint,
        d.name::text,

        p.reporting_week_id,
        p.reporting_sunday,

        p.area_id,
        p.area_name,

        p.unit_id,
        p.unit_name,

        p.missionaries,

        p.weekly_high_potential_id,
        p.display_order,

        p.person_name,
        p.at_church_this_sunday,
        p.notes

    FROM public.zones z

    JOIN public.districts d
      ON d.zone_id = z.id

    JOIN LATERAL
        public.get_dl_call_in_high_potentials(
            d.id,
            target_reporting_week_id
        ) p
      ON true

    WHERE z.id = target_zone_id

    ORDER BY
        d.name,
        p.area_name,
        p.display_order,
        p.person_name;

END;
$$;


ALTER FUNCTION public.get_zl_call_in_high_potentials(target_zone_id bigint, target_reporting_week_id bigint) OWNER TO postgres;

--
-- Name: get_zl_call_in_hp_activity(bigint, bigint); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.get_zl_call_in_hp_activity(target_zone_id bigint, target_reporting_week_id bigint) RETURNS TABLE(name text, companionship text, area text, active boolean)
    LANGUAGE plpgsql STABLE SECURITY DEFINER
    SET search_path TO 'public', 'pg_temp'
    AS $$
BEGIN

    IF NOT public.can_access_zone(target_zone_id) THEN
        RAISE EXCEPTION
            'You do not have permission to view this zone.';
    END IF;


    RETURN QUERY

    SELECT
        x.name,
        x.companionship,
        x.area,
        x.active

    FROM public.districts d

    JOIN LATERAL
        public.get_dl_call_in_hp_activity(
            d.id,
            target_reporting_week_id
        ) x
      ON true

    WHERE d.zone_id = target_zone_id

    ORDER BY
        d.name,
        x.area,
        x.name;

END;
$$;


ALTER FUNCTION public.get_zl_call_in_hp_activity(target_zone_id bigint, target_reporting_week_id bigint) OWNER TO postgres;

--
-- Name: get_zl_call_in_new_members(bigint, bigint); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.get_zl_call_in_new_members(target_zone_id bigint, target_reporting_week_id bigint) RETURNS TABLE(zone_id bigint, zone_name text, district_id bigint, district_name text, reporting_week_id bigint, reporting_sunday date, area_id bigint, area_name text, unit_id bigint, unit_name text, missionaries text, weekly_new_member_id bigint, new_member_id bigint, display_order integer, person_name text, baptism_date date, confirmation_date date, finding_source text, lessons_actual integer, lessons_goal integer, pmg_lessons_percentage numeric, how_are_they_doing text, discussed_in_gemiko boolean, gemiko_support_plan text, next_ordinance text, at_church_this_sunday boolean, has_calling text, has_aaronic_priesthood text, has_melchizedek_priesthood text, ministers_to_someone text, ministered_to_by_someone boolean, has_active_temple_recommend text, visited_temple_for_baptisms text, reading boolean, praying boolean, member_involvement boolean)
    LANGUAGE plpgsql STABLE SECURITY DEFINER
    SET search_path TO 'public', 'pg_temp'
    AS $$
BEGIN

    IF NOT public.can_access_zone(target_zone_id) THEN
        RAISE EXCEPTION
            'You do not have permission to view this zone.';
    END IF;

    RETURN QUERY

    SELECT
        z.id::bigint,
        z.name::text,

        d.id::bigint,
        d.name::text,

        p.reporting_week_id,
        p.reporting_sunday,

        p.area_id,
        p.area_name,

        p.unit_id,
        p.unit_name,

        p.missionaries,

        p.weekly_new_member_id,
        p.new_member_id,
        p.display_order,

        p.person_name,
        p.baptism_date,
        p.confirmation_date,
        p.finding_source,

        p.lessons_actual,
        p.lessons_goal,
        p.pmg_lessons_percentage,

        p.how_are_they_doing,

        p.discussed_in_gemiko,
        p.gemiko_support_plan,

        p.next_ordinance,
        p.at_church_this_sunday,

        p.has_calling,
        p.has_aaronic_priesthood,
        p.has_melchizedek_priesthood,
        p.ministers_to_someone,
        p.ministered_to_by_someone,

        p.has_active_temple_recommend,
        p.visited_temple_for_baptisms,

        p.reading,
        p.praying,
        p.member_involvement

    FROM public.zones z

    JOIN public.districts d
      ON d.zone_id = z.id

    JOIN LATERAL
        public.get_dl_call_in_new_members(
            d.id,
            target_reporting_week_id
        ) p
      ON true

    WHERE z.id = target_zone_id

    ORDER BY
        d.name,
        p.area_name,
        p.display_order,
        p.person_name;

END;
$$;


ALTER FUNCTION public.get_zl_call_in_new_members(target_zone_id bigint, target_reporting_week_id bigint) OWNER TO postgres;

--
-- Name: get_zl_call_in_nm_activity(bigint, bigint); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.get_zl_call_in_nm_activity(target_zone_id bigint, target_reporting_week_id bigint) RETURNS TABLE(name text, companionship text, area text, active boolean)
    LANGUAGE plpgsql STABLE SECURITY DEFINER
    SET search_path TO 'public', 'pg_temp'
    AS $$
BEGIN

    IF NOT public.can_access_zone(target_zone_id) THEN
        RAISE EXCEPTION
            'You do not have permission to view this zone.';
    END IF;


    RETURN QUERY

    SELECT
        x.name,
        x.companionship,
        x.area,
        x.active

    FROM public.districts d

    JOIN LATERAL
        public.get_dl_call_in_nm_activity(
            d.id,
            target_reporting_week_id
        ) x
      ON true

    WHERE d.zone_id = target_zone_id

    ORDER BY
        d.name,
        x.area,
        x.name;

END;
$$;


ALTER FUNCTION public.get_zl_call_in_nm_activity(target_zone_id bigint, target_reporting_week_id bigint) OWNER TO postgres;

--
-- Name: get_zl_call_in_summary(bigint, bigint); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.get_zl_call_in_summary(target_zone_id bigint, target_reporting_week_id bigint) RETURNS TABLE(zone_id bigint, zone_name text, reporting_week_id bigint, reporting_sunday date, district_id bigint, district_name text, dl_notes text, thank_you text, zl_notes text, dl_call_in_complete boolean, dl_completed_at timestamp with time zone, dl_completed_by uuid, area_count integer, all_weekly_reports_submitted boolean, friends_found_previous_goal numeric, friends_found_actual numeric, friends_found_goal numeric, members_at_lessons_previous_goal numeric, members_at_lessons_actual numeric, members_at_lessons_goal numeric, sacrament_attendance_previous_goal numeric, sacrament_attendance_actual numeric, sacrament_attendance_goal numeric, baptismal_dates_previous_goal numeric, baptismal_dates_actual numeric, baptismal_dates_goal numeric, baptisms_confirmations_previous_goal numeric, baptisms_confirmations_actual numeric, baptisms_confirmations_goal numeric, nm_sacrament_previous_goal numeric, nm_sacrament_actual numeric, nm_sacrament_goal numeric, follow_up_lessons_actual numeric, follow_up_lessons_goal numeric)
    LANGUAGE plpgsql STABLE SECURITY DEFINER
    SET search_path TO 'public', 'pg_temp'
    AS $$

BEGIN

    IF NOT public.can_access_zone(target_zone_id) THEN
        RAISE EXCEPTION
            'You do not have permission to view this zone.';
    END IF;


    RETURN QUERY

    SELECT

        z.id::bigint AS zone_id,
        z.name::text AS zone_name,

        rw.id::bigint AS reporting_week_id,
        rw.sunday::date AS reporting_sunday,

        d.id::bigint AS district_id,
        d.name::text AS district_name,

        cid.dl_notes::text,
        cid.thank_you::text,
        cid.zl_notes::text,

        (cid.dl_completed_at IS NOT NULL)::boolean
            AS dl_call_in_complete,

        cid.dl_completed_at,
        cid.dl_completed_by,

        COUNT(s.area_id)::integer AS area_count,

        CASE
            WHEN COUNT(s.area_id) = 0 THEN false
            ELSE BOOL_AND(
                COALESCE(s.all_reports_submitted, false)
            )
        END::boolean
            AS all_weekly_reports_submitted,


        SUM(s.friends_found_previous_goal)::numeric,
        SUM(s.friends_found_actual)::numeric,
        SUM(s.friends_found_goal)::numeric,


        SUM(s.members_at_lessons_previous_goal)::numeric,
        SUM(s.members_at_lessons_actual)::numeric,
        SUM(s.members_at_lessons_goal)::numeric,


        SUM(s.sacrament_attendance_previous_goal)::numeric,
        SUM(s.sacrament_attendance_actual)::numeric,
        SUM(s.sacrament_attendance_goal)::numeric,


        SUM(s.baptismal_dates_previous_goal)::numeric,
        SUM(s.baptismal_dates_actual)::numeric,
        SUM(s.baptismal_dates_goal)::numeric,


        SUM(s.baptisms_confirmations_previous_goal)::numeric,
        SUM(s.baptisms_confirmations_actual)::numeric,
        SUM(s.baptisms_confirmations_goal)::numeric,


        SUM(s.nm_sacrament_previous_goal)::numeric,
        SUM(s.nm_sacrament_actual)::numeric,
        SUM(s.nm_sacrament_goal)::numeric,


        SUM(s.follow_up_lessons_actual)::numeric,
        SUM(s.follow_up_lessons_goal)::numeric


    FROM public.zones z

    JOIN public.districts d
      ON d.zone_id = z.id

    JOIN public.reporting_weeks rw
      ON rw.id = target_reporting_week_id


    -- Reuse the already-working DL summary for each district.
    LEFT JOIN LATERAL
        public.get_dl_call_in_summary(
            d.id,
            target_reporting_week_id
        ) s
      ON true


    LEFT JOIN public.call_in_districts cid
      ON cid.district_id = d.id
     AND cid.reporting_week_id = target_reporting_week_id


    WHERE z.id = target_zone_id


    GROUP BY

        z.id,
        z.name,

        rw.id,
        rw.sunday,

        d.id,
        d.name,

        cid.dl_notes,
        cid.thank_you,
        cid.zl_notes,

        cid.dl_completed_at,
        cid.dl_completed_by


    ORDER BY d.name;

END;
$$;


ALTER FUNCTION public.get_zl_call_in_summary(target_zone_id bigint, target_reporting_week_id bigint) OWNER TO postgres;

--
-- Name: get_zl_call_in_summary_with_planning(bigint, bigint); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.get_zl_call_in_summary_with_planning(target_zone_id bigint, target_reporting_week_id bigint) RETURNS jsonb
    LANGUAGE plpgsql STABLE SECURITY DEFINER
    SET search_path TO 'public', 'pg_temp'
    AS $_$
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
$_$;


ALTER FUNCTION public.get_zl_call_in_summary_with_planning(target_zone_id bigint, target_reporting_week_id bigint) OWNER TO postgres;

--
-- Name: get_zl_call_in_zone_notes(bigint, bigint); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.get_zl_call_in_zone_notes(target_zone_id bigint, target_reporting_week_id bigint) RETURNS TABLE(zone_id bigint, zone_name text, reporting_week_id bigint, reporting_sunday date, zone_notes text)
    LANGUAGE plpgsql STABLE SECURITY DEFINER
    SET search_path TO 'public', 'pg_temp'
    AS $$
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
$$;


ALTER FUNCTION public.get_zl_call_in_zone_notes(target_zone_id bigint, target_reporting_week_id bigint) OWNER TO postgres;

--
-- Name: guard_call_in_write(); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.guard_call_in_write() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'public', 'pg_temp'
    AS $$
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
$$;


ALTER FUNCTION public.guard_call_in_write() OWNER TO postgres;

--
-- Name: guard_shared_planning_child(); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.guard_shared_planning_child() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'public', 'pg_temp'
    AS $$
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
$$;


ALTER FUNCTION public.guard_shared_planning_child() OWNER TO postgres;

--
-- Name: guard_shared_planning_report(); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.guard_shared_planning_report() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'public', 'pg_temp'
    AS $$
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
$$;


ALTER FUNCTION public.guard_shared_planning_report() OWNER TO postgres;

--
-- Name: is_assignment_admin(); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.is_assignment_admin() RETURNS boolean
    LANGUAGE sql STABLE SECURITY DEFINER
    SET search_path TO 'public', 'pg_temp'
    AS $$
    SELECT EXISTS (
        SELECT 1 FROM public.user_profiles up
        WHERE up.id = auth.uid() AND up.active = true
          AND (up.app_role IN ('PRESIDENT','DATA_ADMIN') OR 'DATA_ADMIN' = ANY(up.additional_roles))
    );
$$;


ALTER FUNCTION public.is_assignment_admin() OWNER TO postgres;

--
-- Name: is_call_in_district_leader(bigint); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.is_call_in_district_leader(target_district_id bigint) RETURNS boolean
    LANGUAGE sql STABLE SECURITY DEFINER
    SET search_path TO 'public', 'pg_temp'
    AS $$
    SELECT EXISTS (
        SELECT 1 FROM public.user_profiles up
        JOIN public.leadership_assignments la ON la.missionary_id = up.missionary_id
        WHERE up.id = auth.uid() AND up.active
          AND la.role = 'DL' AND la.district_id = target_district_id
          AND la.start_date <= CURRENT_DATE AND (la.end_date IS NULL OR la.end_date >= CURRENT_DATE)
    );
$$;


ALTER FUNCTION public.is_call_in_district_leader(target_district_id bigint) OWNER TO postgres;

--
-- Name: is_call_in_zone_leader(bigint); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.is_call_in_zone_leader(target_zone_id bigint) RETURNS boolean
    LANGUAGE sql STABLE SECURITY DEFINER
    SET search_path TO 'public', 'pg_temp'
    AS $$
    SELECT EXISTS (
        SELECT 1 FROM public.user_profiles up
        JOIN public.leadership_assignments la ON la.missionary_id = up.missionary_id
        WHERE up.id = auth.uid() AND up.active
          AND la.role = 'ZL' AND la.zone_id = target_zone_id
          AND la.start_date <= CURRENT_DATE AND (la.end_date IS NULL OR la.end_date >= CURRENT_DATE)
    );
$$;


ALTER FUNCTION public.is_call_in_zone_leader(target_zone_id bigint) OWNER TO postgres;

--
-- Name: is_current_user_area(bigint); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.is_current_user_area(target_area_id bigint) RETURNS boolean
    LANGUAGE sql STABLE SECURITY DEFINER
    SET search_path TO 'public'
    AS $$
    select exists (
        select 1
        from public.user_profiles up
        join public.missionary_assignments ma
            on ma.missionary_id = up.missionary_id
        where up.id = auth.uid()
          and up.active = true
          and ma.area_id = target_area_id
          and ma.start_date <= current_date
          and (
              ma.end_date is null
              or ma.end_date >= current_date
          )
    );
$$;


ALTER FUNCTION public.is_current_user_area(target_area_id bigint) OWNER TO postgres;

--
-- Name: is_mission_manager_for_area(bigint); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.is_mission_manager_for_area(target_area_id bigint) RETURNS boolean
    LANGUAGE plpgsql STABLE SECURITY DEFINER
    SET search_path TO 'public', 'pg_temp'
    AS $$
BEGIN
  -- Migration 037: the same question as migration 032, in plpgsql so its plan is kept for the whole connection.
  RETURN (
    SELECT EXISTS (
        SELECT 1 FROM public.user_profiles up
        JOIN public.areas target ON target.id = target_area_id
        JOIN public.districts td ON td.id = target.district_id
        JOIN public.zones tz ON tz.id = td.zone_id
        WHERE up.id = auth.uid() AND up.active
          -- 032: President and Data Analyst (main or additional role), or an AP through a current AP assignment in
          -- this mission. app_role 'AP' alone no longer counts (it is not updated when an AP is released).
          AND (up.app_role IN ('PRESIDENT','DATA_ADMIN') OR 'DATA_ADMIN' = ANY(up.additional_roles) OR EXISTS (
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
              -- 027: a President or Data Analyst account without a missionary link, in its home mission
              OR (up.missionary_id IS NULL AND up.home_mission_id = tz.mission_id
                  AND (up.app_role IN ('PRESIDENT','DATA_ADMIN') OR 'DATA_ADMIN' = ANY(up.additional_roles)))
          )
    )
  );
END
$$;


ALTER FUNCTION public.is_mission_manager_for_area(target_area_id bigint) OWNER TO postgres;

--
-- Name: planning_catalog_bump_version(); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.planning_catalog_bump_version() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'public', 'pg_temp'
    AS $$
BEGIN
  UPDATE public.planning_catalog_version SET version = version + 1, changed_at = now();
  RETURN NULL;
END $$;


ALTER FUNCTION public.planning_catalog_bump_version() OWNER TO postgres;

--
-- Name: planning_catalog_no_truncate(); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.planning_catalog_no_truncate() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'public', 'pg_temp'
    AS $$
BEGIN
  RAISE EXCEPTION 'The planning questions cannot be emptied (%): saved plans and reports depend on them. Retire items instead (active = false).', TG_TABLE_NAME;
END $$;


ALTER FUNCTION public.planning_catalog_no_truncate() OWNER TO postgres;

--
-- Name: planning_catalog_touch(); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.planning_catalog_touch() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'public', 'pg_temp'
    AS $$
BEGIN
  IF NEW IS DISTINCT FROM OLD THEN
    NEW.updated_at := now();
  END IF;
  RETURN NEW;
END $$;


ALTER FUNCTION public.planning_catalog_touch() OWNER TO postgres;

--
-- Name: planning_kpi_value(numeric, integer); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.planning_kpi_value(answer_value numeric, fallback_value integer) RETURNS integer
    LANGUAGE sql IMMUTABLE
    SET search_path TO 'public', 'pg_temp'
    AS $$
    SELECT CASE WHEN answer_value BETWEEN 0 AND 2147483647
                     AND answer_value = trunc(answer_value)
                THEN answer_value::integer ELSE fallback_value END;
$$;


ALTER FUNCTION public.planning_kpi_value(answer_value numeric, fallback_value integer) OWNER TO postgres;

--
-- Name: planning_option_used(text, text); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.planning_option_used(target_question_key text, target_value text) RETURNS boolean
    LANGUAGE sql STABLE
    SET search_path TO 'public', 'pg_temp'
    AS $$
  SELECT EXISTS (
    SELECT 1 FROM public.weekly_planning_answers a
    WHERE a.question_key = target_question_key
      AND (a.answer_text = target_value
           OR CASE jsonb_typeof(a.answer_json)
                WHEN 'array' THEN a.answer_json ? target_value
                WHEN 'object' THEN EXISTS (SELECT 1 FROM jsonb_each_text(a.answer_json) e WHERE e.value = target_value)
                ELSE false
              END));
$$;


ALTER FUNCTION public.planning_option_used(target_question_key text, target_value text) OWNER TO postgres;

--
-- Name: planning_question_grid_rows_guard(); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.planning_question_grid_rows_guard() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'public', 'pg_temp'
    AS $$
DECLARE
  v_key text;
  v_protected boolean;
BEGIN
  IF TG_OP = 'INSERT' THEN
    SELECT q.question_key, q.protected INTO v_key, v_protected FROM public.planning_questions q WHERE q.id = NEW.question_id;
    IF v_protected THEN
      RAISE EXCEPTION 'The rows of "%" are fixed because reports read them, so no row can be added.', v_key;
    END IF;
    RETURN NEW;
  END IF;
  SELECT q.question_key, q.protected INTO v_key, v_protected FROM public.planning_questions q WHERE q.id = OLD.question_id;
  IF TG_OP = 'UPDATE' AND NEW.question_id IS DISTINCT FROM OLD.question_id THEN
    RAISE EXCEPTION 'A grid row cannot move to another question. Add it there instead.';
  END IF;
  IF v_protected AND (TG_OP = 'DELETE' OR NEW.row_key IS DISTINCT FROM OLD.row_key OR (OLD.active AND NOT NEW.active)) THEN
    RAISE EXCEPTION 'The rows of "%" are fixed because reports read them. You can change their labels.', v_key;
  END IF;
  IF (TG_OP = 'DELETE' OR NEW.row_key IS DISTINCT FROM OLD.row_key)
     AND EXISTS (SELECT 1 FROM public.weekly_planning_answers a
                 WHERE a.question_key = v_key
                   AND CASE WHEN jsonb_typeof(a.answer_json) = 'object' THEN a.answer_json ? OLD.row_key ELSE false END) THEN
    IF TG_OP = 'DELETE' THEN
      RAISE EXCEPTION 'Saved plans already answered the row "%" of "%", so it cannot be deleted. Retire it instead.', OLD.row_label, v_key;
    END IF;
    RAISE EXCEPTION 'Saved plans already answered the row "%" of "%", so its key stays. You can change its label.', OLD.row_label, v_key;
  END IF;
  IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
  RETURN NEW;
END $$;


ALTER FUNCTION public.planning_question_grid_rows_guard() OWNER TO postgres;

--
-- Name: planning_question_options_guard(); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.planning_question_options_guard() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'public', 'pg_temp'
    AS $$
DECLARE
  v_key text;
  v_protected boolean;
BEGIN
  IF TG_OP = 'INSERT' THEN
    SELECT q.question_key, q.protected INTO v_key, v_protected FROM public.planning_questions q WHERE q.id = NEW.question_id;
    IF v_protected THEN
      RAISE EXCEPTION 'The answer choices of "%" are fixed because reports read them, so no choice can be added.', v_key;
    END IF;
    RETURN NEW;
  END IF;
  SELECT q.question_key, q.protected INTO v_key, v_protected FROM public.planning_questions q WHERE q.id = OLD.question_id;
  IF TG_OP = 'UPDATE' AND NEW.question_id IS DISTINCT FROM OLD.question_id THEN
    RAISE EXCEPTION 'An answer choice cannot move to another question. Add it there instead.';
  END IF;
  IF v_protected AND (TG_OP = 'DELETE' OR NEW.option_value IS DISTINCT FROM OLD.option_value OR (OLD.active AND NOT NEW.active)) THEN
    RAISE EXCEPTION 'The answer choices of "%" are fixed because reports read them. You can change their labels.', v_key;
  END IF;
  IF (TG_OP = 'DELETE' OR NEW.option_value IS DISTINCT FROM OLD.option_value)
     AND public.planning_option_used(v_key, OLD.option_value) THEN
    IF TG_OP = 'DELETE' THEN
      RAISE EXCEPTION 'Saved plans already chose "%" for "%", so it cannot be deleted. Retire it instead.', OLD.option_label, v_key;
    END IF;
    RAISE EXCEPTION 'Saved plans already chose "%" for "%", so its value stays. You can change its label.', OLD.option_label, v_key;
  END IF;
  IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
  RETURN NEW;
END $$;


ALTER FUNCTION public.planning_question_options_guard() OWNER TO postgres;

--
-- Name: planning_question_sections_guard(); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.planning_question_sections_guard() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'public', 'pg_temp'
    AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'Sections are never deleted ("%"). Retire it instead: it then disappears from the form.', OLD.section_title;
  END IF;
  IF NEW.section_key IS DISTINCT FROM OLD.section_key THEN
    RAISE EXCEPTION 'The key of a section never changes ("%"). Change its title instead.', OLD.section_key;
  END IF;
  IF OLD.active AND NOT NEW.active THEN
    IF OLD.section_key = 'key_indicators_conversion' THEN
      RAISE EXCEPTION 'The section "%" stays active: it holds the key indicators that Dashboards, Call-ins and Presentations read every week.', OLD.section_title;
    END IF;
    IF EXISTS (SELECT 1 FROM public.planning_questions q WHERE q.section_id = OLD.id AND q.active AND q.protected) THEN
      RAISE EXCEPTION 'The section "%" holds protected questions, so it stays active. Move them to another section first.', OLD.section_title;
    END IF;
  END IF;
  RETURN NEW;
END $$;


ALTER FUNCTION public.planning_question_sections_guard() OWNER TO postgres;

--
-- Name: planning_questions_guard(); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.planning_questions_guard() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'public', 'pg_temp'
    AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'Planning questions are never deleted ("%"): saved plans keep their answers. Retire it instead.', OLD.question_key;
  END IF;
  IF TG_OP = 'UPDATE' THEN
    IF NEW.question_key IS DISTINCT FROM OLD.question_key THEN
      RAISE EXCEPTION 'The key of a question never changes ("%"): saved answers are linked by it. Change its label, or add a new question.', OLD.question_key;
    END IF;
    IF OLD.protected AND NOT NEW.protected
       AND coalesce(current_setting('planning_catalog.unprotect', true), '') <> 'on' THEN
      RAISE EXCEPTION '"%" is protected because reports read it. See migration 024 to remove the protection on purpose.', OLD.question_key;
    END IF;
    IF NEW.question_type IS DISTINCT FROM OLD.question_type THEN
      IF NEW.protected THEN
        RAISE EXCEPTION '"%" is protected because reports read it, so its type stays %.', OLD.question_key, OLD.question_type;
      END IF;
      IF EXISTS (SELECT 1 FROM public.weekly_planning_answers a WHERE a.question_key = OLD.question_key) THEN
        RAISE EXCEPTION 'Saved plans already answered "%", so its type stays %. Add a new question instead.', OLD.question_key, OLD.question_type;
      END IF;
    END IF;
    IF NEW.protected AND OLD.required AND NOT NEW.required THEN
      RAISE EXCEPTION '"%" is protected because reports read it, so it stays required.', OLD.question_key;
    END IF;
  END IF;
  IF NEW.protected THEN
    IF NOT NEW.active THEN
      RAISE EXCEPTION '"%" is protected because reports read it, so it stays on the form.', NEW.question_key;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM public.planning_question_sections s WHERE s.id = NEW.section_id AND s.active) THEN
      RAISE EXCEPTION '"%" is protected because reports read it, so it must be in an active section.', NEW.question_key;
    END IF;
    -- A value saved while hidden would put an answer into reports that nobody gave. It can always be cleared.
    IF NEW.value_when_hidden IS NOT NULL THEN
      IF TG_OP = 'INSERT' THEN
        RAISE EXCEPTION '"%" is protected because reports read it, so nothing is saved for it while hidden.', NEW.question_key;
      ELSIF NOT OLD.protected OR NEW.value_when_hidden IS DISTINCT FROM OLD.value_when_hidden THEN
        RAISE EXCEPTION '"%" is protected because reports read it, so nothing is saved for it while hidden. Clear "value saved while hidden" first.', NEW.question_key;
      END IF;
    END IF;
  END IF;
  RETURN NEW;
END $$;


ALTER FUNCTION public.planning_questions_guard() OWNER TO postgres;

--
-- Name: planning_visibility_rules_guard(); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.planning_visibility_rules_guard() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'public', 'pg_temp'
    AS $$
BEGIN
  -- The rules of a protected question are fixed: a rule could hide it, and a hidden question is neither asked nor
  -- required. (The ward coordination grid keeps its rule "shown when the meeting was held".)
  IF TG_OP <> 'INSERT' THEN
    IF EXISTS (SELECT 1 FROM public.planning_questions q WHERE q.question_key = OLD.child_question_key AND q.protected) THEN
      IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'The show/hide rules of "%" are fixed because reports read it, so this rule cannot be deleted.', OLD.child_question_key;
      END IF;
      IF (NEW.child_question_key, NEW.parent_question_key, NEW.operator, NEW.comparison_value, NEW.active)
         IS DISTINCT FROM (OLD.child_question_key, OLD.parent_question_key, OLD.operator, OLD.comparison_value, OLD.active) THEN
        RAISE EXCEPTION 'The show/hide rules of "%" are fixed because reports read it, so this rule cannot be changed or turned off.', OLD.child_question_key;
      END IF;
    END IF;
    IF TG_OP = 'DELETE' THEN
      RETURN OLD;
    END IF;
  END IF;
  IF EXISTS (SELECT 1 FROM public.planning_questions q WHERE q.question_key = NEW.child_question_key AND q.protected) THEN
    IF TG_OP = 'INSERT' THEN
      RAISE EXCEPTION 'The show/hide rules of "%" are fixed because reports read it, so no rule can be added. It is always shown.', NEW.child_question_key;
    ELSIF NEW.child_question_key IS DISTINCT FROM OLD.child_question_key THEN
      RAISE EXCEPTION 'The show/hide rules of "%" are fixed because reports read it, so no rule can be moved to it.', NEW.child_question_key;
    END IF;
  END IF;
  IF NEW.active AND EXISTS (
    WITH RECURSIVE parents(question_key) AS (
      SELECT NEW.parent_question_key
      UNION
      SELECT r.parent_question_key
      FROM public.planning_question_visibility_rules r JOIN parents p ON r.child_question_key = p.question_key
      WHERE r.active AND r.id IS DISTINCT FROM NEW.id
    )
    SELECT 1 FROM parents WHERE question_key = NEW.child_question_key
  ) THEN
    RAISE EXCEPTION 'This rule would make "%" depend on itself (through "%"). Choose another question.', NEW.child_question_key, NEW.parent_question_key;
  END IF;
  RETURN NEW;
END $$;


ALTER FUNCTION public.planning_visibility_rules_guard() OWNER TO postgres;

--
-- Name: portal_planning_trusted_write(); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.portal_planning_trusted_write() RETURNS boolean
    LANGUAGE sql STABLE
    SET search_path TO 'public', 'pg_temp'
    AS $$
    SELECT auth.uid() IS NULL
       AND coalesce(current_setting('role', true),'none') NOT IN ('authenticated','anon')
       AND (session_user IN ('postgres','supabase_admin','service_role')
            OR coalesce(nullif(current_setting('request.jwt.claims', true),'')::jsonb ->> 'role','') = 'service_role');
$$;


ALTER FUNCTION public.portal_planning_trusted_write() OWNER TO postgres;

--
-- Name: reactivate_new_member(bigint); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.reactivate_new_member(target_new_member_id bigint) RETURNS void
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'public', 'pg_temp'
    AS $$
DECLARE
    v_unit_id bigint;
BEGIN
    SELECT au.unit_id INTO v_unit_id
    FROM public.new_members nm
    JOIN public.area_units au ON au.area_id = nm.area_id AND au.active
    JOIN public.units u ON u.id = au.unit_id AND u.active
    WHERE nm.id = target_new_member_id
    ORDER BY (au.unit_id IS NOT DISTINCT FROM nm.unit_id) DESC, au.primary_unit DESC, u.name, u.id
    LIMIT 1;
    IF v_unit_id IS NULL THEN
        IF NOT EXISTS (SELECT 1 FROM public.new_members WHERE id = target_new_member_id) THEN
            RAISE EXCEPTION 'New Member record not found.';
        END IF;
        RAISE EXCEPTION 'The New Member''s area has no active ward or branch.';
    END IF;
    PERFORM public.reactivate_new_member(target_new_member_id, v_unit_id);
END;
$$;


ALTER FUNCTION public.reactivate_new_member(target_new_member_id bigint) OWNER TO postgres;

--
-- Name: reactivate_new_member(bigint, bigint); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.reactivate_new_member(target_new_member_id bigint, target_unit_id bigint) RETURNS void
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'public', 'pg_temp'
    AS $$
DECLARE
    v_member public.new_members;
    v_stake_id bigint;
BEGIN
    SELECT * INTO v_member FROM public.new_members WHERE id = target_new_member_id FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'New Member record not found.';
    END IF;
    IF NOT public.can_access_area(v_member.area_id) THEN
        RAISE EXCEPTION 'You do not have permission to restore follow-up for this New Member.';
    END IF;
    IF v_member.baptism_date IS NOT NULL AND v_member.baptism_date <= current_date - interval '1 year' THEN
        RAISE EXCEPTION 'This person has been a member for one year or longer.';
    END IF;
    SELECT u.stake_id INTO v_stake_id
    FROM public.area_units au JOIN public.units u ON u.id = au.unit_id
    WHERE au.area_id = v_member.area_id AND au.unit_id = target_unit_id AND au.active AND u.active;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Selected unit does not belong to the New Member''s area.';
    END IF;

    UPDATE public.new_members
    SET follow_up_status = 'current', follow_up_ended_at = NULL, follow_up_end_reason = NULL,
        -- Legacy compatibility.
        active = true, inactive_at = NULL, inactive_reason = NULL,
        unit_id = target_unit_id, stake_id = v_stake_id, updated_at = now()
    WHERE id = target_new_member_id;

    IF EXISTS (SELECT 1 FROM public.new_member_area_assignments
               WHERE new_member_id = target_new_member_id AND end_date IS NULL) THEN
        UPDATE public.new_member_area_assignments SET unit_id = target_unit_id
        WHERE new_member_id = target_new_member_id AND end_date IS NULL AND area_id = v_member.area_id;
    ELSE
        INSERT INTO public.new_member_area_assignments (new_member_id, area_id, unit_id, start_date, transfer_reason)
        VALUES (target_new_member_id, v_member.area_id, target_unit_id, current_date, 'follow_up_restored');
    END IF;
END;
$$;


ALTER FUNCTION public.reactivate_new_member(target_new_member_id bigint, target_unit_id bigint) OWNER TO postgres;

--
-- Name: reopen_dl_call_in(bigint, bigint); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.reopen_dl_call_in(target_district_id bigint, target_reporting_week_id bigint) RETURNS bigint
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'public', 'pg_temp'
    AS $$
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
$$;


ALTER FUNCTION public.reopen_dl_call_in(target_district_id bigint, target_reporting_week_id bigint) OWNER TO postgres;

--
-- Name: reopen_weekly_report(bigint); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.reopen_weekly_report(target_report_id bigint) RETURNS void
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'public', 'pg_temp'
    AS $$
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
$$;


ALTER FUNCTION public.reopen_weekly_report(target_report_id bigint) OWNER TO postgres;

--
-- Name: reporting_sunday_at(timestamp with time zone); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.reporting_sunday_at(at_time timestamp with time zone) RETURNS date
    LANGUAGE sql STABLE
    AS $$
  SELECT (at_time AT TIME ZONE 'Europe/Berlin')::date
         - extract(dow FROM (at_time AT TIME ZONE 'Europe/Berlin'))::integer;
$$;


ALTER FUNCTION public.reporting_sunday_at(at_time timestamp with time zone) OWNER TO postgres;

--
-- Name: save_call_in_area_update(bigint, bigint, bigint, text); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.save_call_in_area_update(target_district_id bigint, target_reporting_week_id bigint, target_area_id bigint, new_update_text text) RETURNS bigint
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'public', 'pg_temp'
    AS $$
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
$$;


ALTER FUNCTION public.save_call_in_area_update(target_district_id bigint, target_reporting_week_id bigint, target_area_id bigint, new_update_text text) OWNER TO postgres;

--
-- Name: save_current_planning_answer(bigint, text, text, numeric, boolean, jsonb); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.save_current_planning_answer(target_unit_id bigint, question_key text, answer_text text DEFAULT NULL::text, answer_number numeric DEFAULT NULL::numeric, answer_boolean boolean DEFAULT NULL::boolean, answer_json jsonb DEFAULT NULL::jsonb) RETURNS void
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'public'
    AS $$
#variable_conflict use_column

declare
    v_report_id bigint;
    v_status text;
    v_question_key text;
begin

    -- Copy the RPC parameter into a clearly named local variable.
    v_question_key := save_current_planning_answer.question_key;

    if v_question_key is null or btrim(v_question_key) = '' then
        raise exception 'question_key is required.';
    end if;


    -- Get or create the current report for the selected unit.
    v_report_id :=
        public.start_current_weekly_report(target_unit_id);


    -- Make sure the report is still editable.
    select war.status
    into v_status
    from public.weekly_area_reports war
    where war.id = v_report_id;


    if v_status <> 'DRAFT' then
        raise exception
            'This weekly report is %, not DRAFT, and cannot be edited.',
            v_status;
    end if;


    -- Insert the answer, or update it if this question
    -- already has an answer for this report.
    insert into public.weekly_planning_answers (
        weekly_area_report_id,
        question_key,
        answer_text,
        answer_number,
        answer_boolean,
        answer_json
    )
    values (
        v_report_id,
        v_question_key,
        answer_text,
        answer_number,
        answer_boolean,
        answer_json
    )
    on conflict (
        weekly_area_report_id,
        question_key
    )
    do update set
        answer_text = excluded.answer_text,
        answer_number = excluded.answer_number,
        answer_boolean = excluded.answer_boolean,
        answer_json = excluded.answer_json;

end;
$$;


ALTER FUNCTION public.save_current_planning_answer(target_unit_id bigint, question_key text, answer_text text, answer_number numeric, answer_boolean boolean, answer_json jsonb) OWNER TO postgres;

--
-- Name: save_dl_call_in_notes(bigint, bigint, text, text); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.save_dl_call_in_notes(target_district_id bigint, target_reporting_week_id bigint, new_dl_notes text, new_thank_you text) RETURNS bigint
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'public', 'pg_temp'
    AS $$
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
$$;


ALTER FUNCTION public.save_dl_call_in_notes(target_district_id bigint, target_reporting_week_id bigint, new_dl_notes text, new_thank_you text) OWNER TO postgres;

--
-- Name: save_zl_call_in_notes(bigint, bigint, text); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.save_zl_call_in_notes(target_district_id bigint, target_reporting_week_id bigint, new_zl_notes text) RETURNS bigint
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'public', 'pg_temp'
    AS $$
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
$$;


ALTER FUNCTION public.save_zl_call_in_notes(target_district_id bigint, target_reporting_week_id bigint, new_zl_notes text) OWNER TO postgres;

--
-- Name: save_zl_zone_call_in_notes(bigint, bigint, text); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.save_zl_zone_call_in_notes(target_zone_id bigint, target_reporting_week_id bigint, new_zone_notes text) RETURNS bigint
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'public', 'pg_temp'
    AS $$
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
$$;


ALTER FUNCTION public.save_zl_zone_call_in_notes(target_zone_id bigint, target_reporting_week_id bigint, new_zone_notes text) OWNER TO postgres;

--
-- Name: start_current_weekly_report(); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.start_current_weekly_report() RETURNS bigint
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'public'
    AS $$

declare

    target_area_id bigint;

    target_week_id bigint;

    report_id bigint;

begin


    target_area_id :=
        public.current_user_area_id();


    if target_area_id is null then

        raise exception
        'No current area assignment was found for this user.';

    end if;


    target_week_id :=
        public.ensure_reporting_week(
            public.current_reporting_sunday()
        );


    select war.id

    into report_id

    from public.weekly_area_reports war

    where war.area_id =
          target_area_id

      and war.reporting_week_id =
          target_week_id;


    if report_id is not null then

        return report_id;

    end if;


    insert into public.weekly_area_reports (

        area_id,

        reporting_week_id,

        status,

        submitted_by

    )

    values (

        target_area_id,

        target_week_id,

        'DRAFT',

        auth.uid()

    )

    returning id
    into report_id;


    return report_id;

end;

$$;


ALTER FUNCTION public.start_current_weekly_report() OWNER TO postgres;

--
-- Name: start_current_weekly_report(bigint); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.start_current_weekly_report(target_unit_id bigint) RETURNS bigint
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'public', 'pg_temp'
    AS $$
DECLARE
    v_area_id bigint; v_week_id bigint; v_report_id bigint;
BEGIN
    IF target_unit_id IS NULL THEN RAISE EXCEPTION 'A unit must be selected.'; END IF;
    IF NOT public.can_current_user_report_for_unit(target_unit_id) THEN
        RAISE EXCEPTION 'You do not have access to this unit.' USING ERRCODE = '42501';
    END IF;
    v_area_id := public.current_user_area_id();
    IF v_area_id IS NULL THEN RAISE EXCEPTION 'No current area assignment found for this user.'; END IF;
    v_week_id := public.ensure_reporting_week(public.current_reporting_sunday());
    SELECT war.id INTO v_report_id
    FROM public.weekly_area_reports war
    WHERE war.area_id = v_area_id AND war.unit_id = target_unit_id AND war.reporting_week_id = v_week_id;
    IF v_report_id IS NULL THEN
        INSERT INTO public.weekly_area_reports (area_id, unit_id, reporting_week_id, status, submitted_by)
        VALUES (v_area_id, target_unit_id, v_week_id, 'DRAFT', auth.uid())
        RETURNING id INTO v_report_id;
    END IF;
    PERFORM public.carry_people_into_report(v_report_id);
    RETURN v_report_id;
END;
$$;


ALTER FUNCTION public.start_current_weekly_report(target_unit_id bigint) OWNER TO postgres;

--
-- Name: submit_current_weekly_report(bigint); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.submit_current_weekly_report(target_unit_id bigint) RETURNS bigint
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'public'
    AS $$
declare
    v_report_id bigint;
    v_status text;
begin
    v_report_id := public.start_current_weekly_report(target_unit_id);

    select status
    into v_status
    from public.weekly_area_reports
    where id = v_report_id;

    if v_status = 'LOCKED' then
        raise exception 'This weekly report is LOCKED.';
    end if;

    if v_status = 'SUBMITTED' then
        return v_report_id;
    end if;

    update public.weekly_area_reports
    set
        status = 'SUBMITTED',
        submitted_by = auth.uid(),
        submitted_at = now(),
        updated_at = now()
    where id = v_report_id;

    return v_report_id;
end;
$$;


ALTER FUNCTION public.submit_current_weekly_report(target_unit_id bigint) OWNER TO postgres;

--
-- Name: sync_baptismal_date_person_display_name(); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.sync_baptismal_date_person_display_name() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
begin

    new.display_name :=
        btrim(
            concat_ws(
                ' ',
                nullif(btrim(new.first_name), ''),
                nullif(btrim(new.last_name), '')
            )
        );

    if new.display_name = '' then
        raise exception 'Friend name is required.';
    end if;

    new.updated_at := now();

    return new;

end;
$$;


ALTER FUNCTION public.sync_baptismal_date_person_display_name() OWNER TO postgres;

--
-- Name: sync_current_companionships(); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.sync_current_companionships() RETURNS void
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'public', 'pg_temp'
    AS $$
declare
    area_record record;
    current_companionship_id bigint;
    caller_role text;
begin

    -- Migration 026: only the server may run this. Through the API (PostgREST) the caller's role comes from the
    -- verified JWT: anon and authenticated are refused even if they have EXECUTE (019 grants it to authenticated
    -- again), service_role is allowed. Without JWT claims only a direct postgres or supabase_admin session is.
    caller_role := coalesce(
        nullif(current_setting('request.jwt.claims', true), '')::jsonb ->> 'role',
        nullif(current_setting('request.jwt.claim.role', true), ''));
    if not (caller_role = 'service_role'
            or (caller_role is null and session_user in ('postgres', 'supabase_admin'))) then
        raise exception 'sync_current_companionships() can only be run on the server (service role or postgres).'
            using errcode = '42501';
    end if;

    -- Close companionships for areas that no longer have active missionaries
    update public.companionships c
    set end_date = current_date - 1
    where c.end_date is null
      and not exists (
          select 1
          from public.missionary_assignments ma
          where ma.area_id = c.area_id
            and ma.start_date <= current_date
            and (
                ma.end_date is null
                or ma.end_date >= current_date
            )
      );


    -- Process every area that currently has missionaries
    for area_record in

        select distinct ma.area_id

        from public.missionary_assignments ma

        where ma.start_date <= current_date
          and (
              ma.end_date is null
              or ma.end_date >= current_date
          )

    loop

        -- Find current companionship
        select c.id
        into current_companionship_id

        from public.companionships c

        where c.area_id = area_record.area_id
          and c.end_date is null

        order by c.start_date desc
        limit 1;


        -- Create one if it doesn't exist
        if current_companionship_id is null then

            insert into public.companionships (
                area_id,
                start_date
            )

            values (
                area_record.area_id,
                current_date
            )

            returning id
            into current_companionship_id;

        end if;


        -- Add currently assigned missionaries
        insert into public.companionship_members (
            companionship_id,
            missionary_id,
            joined_date
        )

        select
            current_companionship_id,
            ma.missionary_id,
            ma.start_date

        from public.missionary_assignments ma

        where ma.area_id = area_record.area_id

          and ma.start_date <= current_date

          and (
              ma.end_date is null
              or ma.end_date >= current_date
          )

        on conflict (
            companionship_id,
            missionary_id
        )
        do update set
            left_date = null;


        -- Close membership for missionaries no longer assigned there
        update public.companionship_members cm

        set left_date = current_date - 1

        where cm.companionship_id = current_companionship_id

          and cm.left_date is null

          and not exists (
              select 1

              from public.missionary_assignments ma

              where ma.missionary_id = cm.missionary_id
                and ma.area_id = area_record.area_id
                and ma.start_date <= current_date
                and (
                    ma.end_date is null
                    or ma.end_date >= current_date
                )
          );

    end loop;

end;
$$;


ALTER FUNCTION public.sync_current_companionships() OWNER TO postgres;

--
-- Name: sync_new_member_display_name(); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.sync_new_member_display_name() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
begin
    new.display_name :=
        btrim(
            concat_ws(
                ' ',
                nullif(btrim(new.first_name), ''),
                nullif(btrim(new.last_name), '')
            )
        );

    if new.display_name = '' then
        raise exception 'New Member name is required.';
    end if;

    new.updated_at := now();

    return new;
end;
$$;


ALTER FUNCTION public.sync_new_member_display_name() OWNER TO postgres;

--
-- Name: sync_user_profile_roles(); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.sync_user_profile_roles() RETURNS void
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'public'
    AS $$

begin


    update public.user_profiles up

    set

        app_role =

            case

                when exists (

                    select 1

                    from public.leadership_assignments la

                    where la.missionary_id =
                          up.missionary_id

                      and la.role = 'AP'

                      and la.start_date <= current_date

                      and (
                            la.end_date is null
                            or la.end_date >= current_date
                      )

                )
                then 'AP'


                when exists (

                    select 1

                    from public.leadership_assignments la

                    where la.missionary_id =
                          up.missionary_id

                      and la.role = 'ZL'

                      and la.start_date <= current_date

                      and (
                            la.end_date is null
                            or la.end_date >= current_date
                      )

                )
                then 'ZL'


                when exists (

                    select 1

                    from public.leadership_assignments la

                    where la.missionary_id =
                          up.missionary_id

                      and la.role = 'STL'

                      and la.start_date <= current_date

                      and (
                            la.end_date is null
                            or la.end_date >= current_date
                      )

                )
                then 'STL'


                when exists (

                    select 1

                    from public.leadership_assignments la

                    where la.missionary_id =
                          up.missionary_id

                      and la.role = 'DL'

                      and la.start_date <= current_date

                      and (
                            la.end_date is null
                            or la.end_date >= current_date
                      )

                )
                then 'DL'


                else 'MISSIONARY'

            end,

        updated_at = now()


    where up.active = true

      and up.missionary_id is not null

      and up.app_role not in (
          'PRESIDENT',
          'DATA_ADMIN'
      );


end;

$$;


ALTER FUNCTION public.sync_user_profile_roles() OWNER TO postgres;

--
-- Name: transfer_baptismal_date_person(bigint, bigint, bigint); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.transfer_baptismal_date_person(target_baptismal_date_person_id bigint, target_area_id bigint, target_unit_id bigint) RETURNS void
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'public', 'pg_temp'
    AS $$
declare
    v_source_area_id bigint;
    v_source_mission_id bigint;
    v_target_mission_id bigint;
begin

    select bdpa.area_id
    into v_source_area_id
    from public.baptismal_date_person_area_assignments bdpa
    where bdpa.baptismal_date_person_id =
              target_baptismal_date_person_id
      and bdpa.end_date is null;


    if v_source_area_id is null then
        raise exception
            'Person does not have a current area assignment.';
    end if;


    if not public.can_access_area(v_source_area_id) then
        raise exception
            'You do not have permission to transfer this person.';
    end if;


    if target_unit_id is null then
        raise exception
            'A destination unit is required.';
    end if;


    if not exists (
        select 1
        from public.area_units au
        where au.area_id = target_area_id
          and au.unit_id = target_unit_id
    ) then
        raise exception
            'Selected unit does not belong to the destination area.';
    end if;


    select z.mission_id
    into v_source_mission_id
    from public.areas a
    join public.districts d
        on d.id = a.district_id
    join public.zones z
        on z.id = d.zone_id
    where a.id = v_source_area_id;


    select z.mission_id
    into v_target_mission_id
    from public.areas a
    join public.districts d
        on d.id = a.district_id
    join public.zones z
        on z.id = d.zone_id
    where a.id = target_area_id;


    if v_target_mission_id is null then
        raise exception 'Destination area was not found.';
    end if;


    if v_source_mission_id <> v_target_mission_id then
        raise exception
            'Destination area must be in the same mission.';
    end if;


    update public.baptismal_date_person_area_assignments
    set
        end_date = current_date,
        transfer_reason = 'transferred_within_mission'
    where baptismal_date_person_id =
              target_baptismal_date_person_id
      and end_date is null;


    insert into public.baptismal_date_person_area_assignments (
        baptismal_date_person_id,
        area_id,
        unit_id,
        start_date,
        transfer_reason
    )
    values (
        target_baptismal_date_person_id,
        target_area_id,
        target_unit_id,
        current_date,
        'transferred_within_mission'
    );

end;
$$;


ALTER FUNCTION public.transfer_baptismal_date_person(target_baptismal_date_person_id bigint, target_area_id bigint, target_unit_id bigint) OWNER TO postgres;

--
-- Name: transfer_new_member(bigint, bigint); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.transfer_new_member(target_new_member_id bigint, target_area_id bigint) RETURNS void
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'public', 'pg_temp'
    AS $$
DECLARE
    v_unit_id bigint;
BEGIN
    SELECT au.unit_id INTO v_unit_id
    FROM public.area_units au
    JOIN public.units u ON u.id = au.unit_id
    LEFT JOIN public.new_members nm ON nm.id = target_new_member_id AND nm.unit_id = au.unit_id
    WHERE au.area_id = target_area_id AND au.active AND u.active
    ORDER BY (nm.id IS NOT NULL) DESC, au.primary_unit DESC, u.name, u.id
    LIMIT 1;
    IF v_unit_id IS NULL THEN
        RAISE EXCEPTION 'The destination area has no active ward or branch.';
    END IF;
    PERFORM public.transfer_new_member(target_new_member_id, target_area_id, v_unit_id);
END;
$$;


ALTER FUNCTION public.transfer_new_member(target_new_member_id bigint, target_area_id bigint) OWNER TO postgres;

--
-- Name: transfer_new_member(bigint, bigint, bigint); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.transfer_new_member(target_new_member_id bigint, target_area_id bigint, target_unit_id bigint) RETURNS void
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'public', 'pg_temp'
    AS $$
DECLARE
    v_assignment public.new_member_area_assignments;
    v_current_unit_id bigint;
    v_source_mission_id bigint;
    v_target_mission_id bigint;
    v_stake_id bigint;
BEGIN
    SELECT nm.unit_id INTO v_current_unit_id
    FROM public.new_members nm WHERE nm.id = target_new_member_id FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'This New Member was not found.';
    END IF;

    SELECT * INTO v_assignment
    FROM public.new_member_area_assignments nmaa
    WHERE nmaa.new_member_id = target_new_member_id AND nmaa.end_date IS NULL;
    IF v_assignment.id IS NULL THEN
        RAISE EXCEPTION 'New Member does not have a current area assignment.';
    END IF;
    IF NOT public.can_access_area(v_assignment.area_id) THEN
        RAISE EXCEPTION 'You do not have permission to transfer this New Member.';
    END IF;
    IF target_area_id IS NULL OR target_unit_id IS NULL THEN
        RAISE EXCEPTION 'Choose the new area and ward or branch.';
    END IF;

    SELECT z.mission_id INTO v_target_mission_id
    FROM public.areas a JOIN public.districts d ON d.id = a.district_id JOIN public.zones z ON z.id = d.zone_id
    WHERE a.id = target_area_id AND a.active;
    IF v_target_mission_id IS NULL THEN
        RAISE EXCEPTION 'Destination area was not found.';
    END IF;
    SELECT z.mission_id INTO v_source_mission_id
    FROM public.areas a JOIN public.districts d ON d.id = a.district_id JOIN public.zones z ON z.id = d.zone_id
    WHERE a.id = v_assignment.area_id;
    IF v_source_mission_id IS DISTINCT FROM v_target_mission_id THEN
        RAISE EXCEPTION 'Use the end-follow-up workflow when someone moves outside the mission.';
    END IF;

    SELECT u.stake_id INTO v_stake_id
    FROM public.area_units au JOIN public.units u ON u.id = au.unit_id
    WHERE au.area_id = target_area_id AND au.unit_id = target_unit_id AND au.active AND u.active;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Selected unit does not belong to the destination area.';
    END IF;
    IF v_assignment.area_id = target_area_id AND v_current_unit_id IS NOT DISTINCT FROM target_unit_id THEN
        RAISE EXCEPTION 'New Member is already assigned to this area and ward or branch.';
    END IF;

    -- greatest(): an old assignment may start in the future (it starts on the baptism date).
    UPDATE public.new_member_area_assignments
    SET end_date = greatest(start_date, current_date), transfer_reason = 'transferred_within_mission'
    WHERE id = v_assignment.id;

    INSERT INTO public.new_member_area_assignments (new_member_id, area_id, unit_id, start_date, transfer_reason)
    VALUES (target_new_member_id, target_area_id, target_unit_id, current_date, 'transferred_within_mission');

    UPDATE public.new_members
    SET area_id = target_area_id, unit_id = target_unit_id, stake_id = v_stake_id, updated_at = now()
    WHERE id = target_new_member_id;
END;
$$;


ALTER FUNCTION public.transfer_new_member(target_new_member_id bigint, target_area_id bigint, target_unit_id bigint) OWNER TO postgres;

--
-- Name: unsubmit_weekly_report(bigint); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.unsubmit_weekly_report(target_report_id bigint) RETURNS TABLE(weekly_report_id bigint, status text, submitted_by uuid, submitted_at timestamp with time zone)
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'public', 'pg_temp'
    AS $$
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
$$;


ALTER FUNCTION public.unsubmit_weekly_report(target_report_id bigint) OWNER TO postgres;

--
-- Name: update_baptismal_date_person(bigint, text, text, text); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.update_baptismal_date_person(target_baptismal_date_person_id bigint, new_first_name text, new_last_name text, new_finding_source text) RETURNS public.baptismal_date_people
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'public', 'pg_temp'
    AS $$
DECLARE
    v_area_id bigint;
    v_person public.baptismal_date_people;
BEGIN
    PERFORM 1 FROM public.baptismal_date_people WHERE id = target_baptismal_date_person_id FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'This friend was not found.';
    END IF;
    SELECT area_id INTO v_area_id FROM public.baptismal_date_person_area_assignments
    WHERE baptismal_date_person_id = target_baptismal_date_person_id AND end_date IS NULL;
    IF v_area_id IS NULL THEN
        RAISE EXCEPTION 'This friend is no longer on the baptismal date list, so their details cannot be changed here.';
    END IF;
    IF NOT public.can_access_area(v_area_id) THEN
        RAISE EXCEPTION 'You do not have permission to edit this friend.';
    END IF;
    IF nullif(btrim(new_first_name), '') IS NULL THEN
        RAISE EXCEPTION 'First name is required.';
    END IF;
    IF length(btrim(new_first_name)) > 100 OR length(btrim(coalesce(new_last_name, ''))) > 100
       OR length(coalesce(new_finding_source, '')) > 200 THEN
        RAISE EXCEPTION 'Names must be 100 characters or fewer.';
    END IF;

    UPDATE public.baptismal_date_people
    SET first_name = btrim(new_first_name),
        last_name = nullif(btrim(new_last_name), ''),
        finding_source = nullif(btrim(new_finding_source), ''),
        updated_at = now()
    WHERE id = target_baptismal_date_person_id
    RETURNING * INTO v_person;

    -- The friend's weekly rows keep a copy of the finding source (Call-ins read it); keep draft plans in step.
    -- Submitted plans keep what was reported.
    UPDATE public.weekly_baptismal_date_friends w
    SET finding_source = v_person.finding_source
    FROM public.weekly_area_reports war
    WHERE war.id = w.weekly_area_report_id AND w.baptismal_date_person_id = target_baptismal_date_person_id
      AND war.status = 'DRAFT' AND public.can_edit_planning_area(war.area_id)
      AND w.finding_source IS DISTINCT FROM v_person.finding_source;
    RETURN v_person;
END;
$$;


ALTER FUNCTION public.update_baptismal_date_person(target_baptismal_date_person_id bigint, new_first_name text, new_last_name text, new_finding_source text) OWNER TO postgres;

--
-- Name: update_current_weekly_report(bigint, integer, integer, integer, integer, integer, integer, integer, integer, integer, integer, integer, integer, integer, integer, integer, integer, integer, text); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.update_current_weekly_report(target_unit_id bigint, new_friends_found_actual integer DEFAULT NULL::integer, new_friends_found_goal integer DEFAULT NULL::integer, new_lessons_with_friends_actual integer DEFAULT NULL::integer, new_lessons_with_friends_goal integer DEFAULT NULL::integer, new_lessons_with_members_actual integer DEFAULT NULL::integer, new_lessons_with_members_goal integer DEFAULT NULL::integer, new_sacrament_attendance_actual integer DEFAULT NULL::integer, new_sacrament_attendance_goal integer DEFAULT NULL::integer, new_first_time_sacrament_actual integer DEFAULT NULL::integer, new_baptismal_dates_actual integer DEFAULT NULL::integer, new_baptismal_dates_goal integer DEFAULT NULL::integer, new_baptisms_confirmations_actual integer DEFAULT NULL::integer, new_baptisms_confirmations_goal integer DEFAULT NULL::integer, new_new_member_sacrament_actual integer DEFAULT NULL::integer, new_new_member_sacrament_goal integer DEFAULT NULL::integer, new_follow_up_lessons_actual integer DEFAULT NULL::integer, new_follow_up_lessons_goal integer DEFAULT NULL::integer, new_notes text DEFAULT NULL::text) RETURNS bigint
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'public'
    AS $$
DECLARE
    v_report_id bigint;
    v_status text;
BEGIN
    v_report_id :=
        public.start_current_weekly_report(target_unit_id);

    SELECT status
    INTO v_status
    FROM public.weekly_area_reports
    WHERE id = v_report_id;

    IF v_status <> 'DRAFT' THEN
        RAISE EXCEPTION
            'This weekly report is %, not DRAFT, and cannot be edited.',
            v_status;
    END IF;

    IF COALESCE(new_friends_found_actual, 0) < 0
       OR COALESCE(new_friends_found_goal, 0) < 0
       OR COALESCE(new_lessons_with_friends_actual, 0) < 0
       OR COALESCE(new_lessons_with_friends_goal, 0) < 0
       OR COALESCE(new_lessons_with_members_actual, 0) < 0
       OR COALESCE(new_lessons_with_members_goal, 0) < 0
       OR COALESCE(new_sacrament_attendance_actual, 0) < 0
       OR COALESCE(new_sacrament_attendance_goal, 0) < 0
       OR COALESCE(new_first_time_sacrament_actual, 0) < 0
       OR COALESCE(new_baptismal_dates_actual, 0) < 0
       OR COALESCE(new_baptismal_dates_goal, 0) < 0
       OR COALESCE(new_baptisms_confirmations_actual, 0) < 0
       OR COALESCE(new_baptisms_confirmations_goal, 0) < 0
       OR COALESCE(new_new_member_sacrament_actual, 0) < 0
       OR COALESCE(new_new_member_sacrament_goal, 0) < 0
       OR COALESCE(new_follow_up_lessons_actual, 0) < 0
       OR COALESCE(new_follow_up_lessons_goal, 0) < 0
    THEN
        RAISE EXCEPTION
            'Weekly report values cannot be negative.';
    END IF;

    UPDATE public.weekly_area_reports
    SET
        friends_found_actual =
            COALESCE(new_friends_found_actual, friends_found_actual),

        friends_found_goal =
            COALESCE(new_friends_found_goal, friends_found_goal),

        lessons_with_friends_actual =
            COALESCE(new_lessons_with_friends_actual, lessons_with_friends_actual),

        lessons_with_friends_goal =
            COALESCE(new_lessons_with_friends_goal, lessons_with_friends_goal),

        lessons_with_members_actual =
            COALESCE(new_lessons_with_members_actual, lessons_with_members_actual),

        lessons_with_members_goal =
            COALESCE(new_lessons_with_members_goal, lessons_with_members_goal),

        sacrament_attendance_actual =
            COALESCE(new_sacrament_attendance_actual, sacrament_attendance_actual),

        sacrament_attendance_goal =
            COALESCE(new_sacrament_attendance_goal, sacrament_attendance_goal),

        first_time_sacrament_actual =
            COALESCE(new_first_time_sacrament_actual, first_time_sacrament_actual),

        baptismal_dates_actual =
            COALESCE(new_baptismal_dates_actual, baptismal_dates_actual),

        baptismal_dates_goal =
            COALESCE(new_baptismal_dates_goal, baptismal_dates_goal),

        baptisms_confirmations_actual =
            COALESCE(
                new_baptisms_confirmations_actual,
                baptisms_confirmations_actual
            ),

        baptisms_confirmations_goal =
            COALESCE(
                new_baptisms_confirmations_goal,
                baptisms_confirmations_goal
            ),

        new_member_sacrament_actual =
            COALESCE(
                new_new_member_sacrament_actual,
                new_member_sacrament_actual
            ),

        new_member_sacrament_goal =
            COALESCE(
                new_new_member_sacrament_goal,
                new_member_sacrament_goal
            ),

        follow_up_lessons_actual =
            COALESCE(new_follow_up_lessons_actual, follow_up_lessons_actual),

        follow_up_lessons_goal =
            COALESCE(new_follow_up_lessons_goal, follow_up_lessons_goal),

        notes =
            COALESCE(new_notes, notes),

        updated_at = NOW()

    WHERE id = v_report_id;

    RETURN v_report_id;
END;
$$;


ALTER FUNCTION public.update_current_weekly_report(target_unit_id bigint, new_friends_found_actual integer, new_friends_found_goal integer, new_lessons_with_friends_actual integer, new_lessons_with_friends_goal integer, new_lessons_with_members_actual integer, new_lessons_with_members_goal integer, new_sacrament_attendance_actual integer, new_sacrament_attendance_goal integer, new_first_time_sacrament_actual integer, new_baptismal_dates_actual integer, new_baptismal_dates_goal integer, new_baptisms_confirmations_actual integer, new_baptisms_confirmations_goal integer, new_new_member_sacrament_actual integer, new_new_member_sacrament_goal integer, new_follow_up_lessons_actual integer, new_follow_up_lessons_goal integer, new_notes text) OWNER TO postgres;

--
-- Name: update_new_member_profile(bigint, text, text, date, date, date, text, date, text, text, text, integer, text, text, text, text, text, text); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.update_new_member_profile(target_new_member_id bigint, new_first_name text, new_last_name text, new_baptismal_date_extended date, new_baptism_date date, new_confirmation_date date, new_finding_source text, new_date_of_birth date, new_age_range text, new_gender text, new_marital_status text, new_child_dependents integer, new_living_situation text, new_native_language text, new_second_language text, new_mission_language_competency text, new_country_of_origin text, new_conversion_success_notes text) RETURNS public.new_members
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'public', 'pg_temp'
    AS $$
DECLARE
    v_area_id bigint;
    v_record public.new_members;
BEGIN
    PERFORM 1 FROM public.new_members WHERE id = target_new_member_id FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'This New Member was not found.';
    END IF;
    SELECT area_id INTO v_area_id FROM public.new_member_area_assignments
    WHERE new_member_id = target_new_member_id AND end_date IS NULL;
    IF v_area_id IS NULL THEN
        RAISE EXCEPTION 'This New Member is no longer followed up, so their details cannot be changed here.';
    END IF;
    IF NOT public.can_access_area(v_area_id) THEN
        RAISE EXCEPTION 'You do not have permission to edit this New Member.';
    END IF;

    IF nullif(btrim(new_first_name), '') IS NULL THEN
        RAISE EXCEPTION 'First name is required.';
    END IF;
    IF length(btrim(new_first_name)) > 100 OR length(btrim(coalesce(new_last_name, ''))) > 100
       OR length(coalesce(new_native_language, '')) > 100 OR length(coalesce(new_second_language, '')) > 100
       OR length(coalesce(new_country_of_origin, '')) > 100 OR length(coalesce(new_finding_source, '')) > 200
       OR length(coalesce(new_age_range, '')) > 200 OR length(coalesce(new_gender, '')) > 200
       OR length(coalesce(new_marital_status, '')) > 200 OR length(coalesce(new_living_situation, '')) > 200
       OR length(coalesce(new_mission_language_competency, '')) > 200 THEN
        RAISE EXCEPTION 'Names, languages and country must be 100 characters or fewer.';
    END IF;
    IF length(coalesce(new_conversion_success_notes, '')) > 5000 THEN
        RAISE EXCEPTION 'The conversion notes must be 5000 characters or fewer.';
    END IF;
    IF new_child_dependents IS NOT NULL AND new_child_dependents NOT BETWEEN 0 AND 30 THEN
        RAISE EXCEPTION 'Child dependants must be a whole number from 0 to 30.';
    END IF;
    -- One day of grace for "the future": the database's day is UTC, the mission's is Berlin.
    IF least(new_baptismal_date_extended, new_baptism_date, new_confirmation_date, new_date_of_birth) < date '1900-01-01'
       OR greatest(new_baptismal_date_extended, new_baptism_date, new_confirmation_date, new_date_of_birth) > current_date + 1 THEN
        RAISE EXCEPTION 'Dates must be real dates and not in the future.';
    END IF;
    IF new_baptism_date < new_baptismal_date_extended THEN
        RAISE EXCEPTION 'Baptism cannot be before the date it was extended.';
    END IF;
    IF new_confirmation_date < new_baptism_date THEN
        RAISE EXCEPTION 'Confirmation cannot be before the baptism date.';
    END IF;

    UPDATE public.new_members
    SET first_name = btrim(new_first_name),
        last_name = nullif(btrim(new_last_name), ''),
        baptismal_date_extended = new_baptismal_date_extended,
        baptism_date = new_baptism_date,
        confirmation_date = new_confirmation_date,
        finding_source = nullif(btrim(new_finding_source), ''),
        date_of_birth = new_date_of_birth,
        age_range = nullif(btrim(new_age_range), ''),
        gender = nullif(btrim(new_gender), ''),
        marital_status = nullif(btrim(new_marital_status), ''),
        child_dependents = new_child_dependents,
        living_situation = nullif(btrim(new_living_situation), ''),
        native_language = nullif(btrim(new_native_language), ''),
        second_language = nullif(btrim(new_second_language), ''),
        mission_language_competency = nullif(btrim(new_mission_language_competency), ''),
        country_of_origin = nullif(btrim(new_country_of_origin), ''),
        conversion_success_notes = nullif(btrim(new_conversion_success_notes), ''),
        updated_at = now()
    WHERE id = target_new_member_id
    RETURNING * INTO v_record;
    RETURN v_record;
END;
$$;


ALTER FUNCTION public.update_new_member_profile(target_new_member_id bigint, new_first_name text, new_last_name text, new_baptismal_date_extended date, new_baptism_date date, new_confirmation_date date, new_finding_source text, new_date_of_birth date, new_age_range text, new_gender text, new_marital_status text, new_child_dependents integer, new_living_situation text, new_native_language text, new_second_language text, new_mission_language_competency text, new_country_of_origin text, new_conversion_success_notes text) OWNER TO postgres;

--
-- Name: area_profiles; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.area_profiles (
    area_id bigint NOT NULL,
    population integer,
    size_km2 numeric(12,3),
    urban_type text,
    assignment_type text,
    extra jsonb DEFAULT '{}'::jsonb NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_by text,
    CONSTRAINT area_profiles_assignment_type_check CHECK ((length(assignment_type) <= 60)),
    CONSTRAINT area_profiles_extra_check CHECK ((jsonb_typeof(extra) = 'object'::text)),
    CONSTRAINT area_profiles_population_check CHECK ((population >= 0)),
    CONSTRAINT area_profiles_size_km2_check CHECK ((size_km2 > (0)::numeric)),
    CONSTRAINT area_profiles_urban_type_check CHECK ((length(urban_type) <= 60))
);


ALTER TABLE public.area_profiles OWNER TO postgres;

--
-- Name: areas; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.areas (
    id bigint NOT NULL,
    district_id bigint NOT NULL,
    unit_id bigint,
    name text NOT NULL,
    assignment_type text DEFAULT 'Standard'::text NOT NULL,
    language text,
    active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    area_code text,
    assignment_type_notes text,
    CONSTRAINT areas_assignment_type_check CHECK ((assignment_type = ANY (ARRAY['Standard'::text, 'Military'::text, 'Special'::text])))
);


ALTER TABLE public.areas OWNER TO postgres;

--
-- Name: districts; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.districts (
    id bigint NOT NULL,
    zone_id bigint NOT NULL,
    name text NOT NULL,
    active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.districts OWNER TO postgres;

--
-- Name: zones; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.zones (
    id bigint NOT NULL,
    mission_id bigint NOT NULL,
    name text NOT NULL,
    active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.zones OWNER TO postgres;

--
-- Name: archetype_area_profile; Type: VIEW; Schema: dashboards; Owner: postgres
--

CREATE VIEW dashboards.archetype_area_profile AS
 SELECT z.mission_id,
    z.id AS zone_id,
    d.id AS district_id,
    a.id AS area_id,
    a.active,
    p.population,
    p.size_km2,
        CASE
            WHEN ((p.population IS NOT NULL) AND (p.size_km2 > (0)::numeric)) THEN round(((p.population)::numeric / p.size_km2), 1)
            ELSE NULL::numeric
        END AS density_per_km2,
    NULLIF(btrim(p.urban_type), ''::text) AS urban_type,
    COALESCE(NULLIF(btrim(p.assignment_type), ''::text), a.assignment_type) AS assignment_type,
    COALESCE(p.extra, '{}'::jsonb) AS extra
   FROM (((public.areas a
     JOIN public.districts d ON ((d.id = a.district_id)))
     JOIN public.zones z ON ((z.id = d.zone_id)))
     LEFT JOIN public.area_profiles p ON ((p.area_id = a.id)));


ALTER TABLE dashboards.archetype_area_profile OWNER TO postgres;

--
-- Name: baptism_history_weeks; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.baptism_history_weeks (
    batch_id uuid NOT NULL,
    mission_id bigint NOT NULL,
    sunday date NOT NULL,
    zone_id bigint,
    area_id bigint,
    zone_name text DEFAULT ''::text NOT NULL,
    area_name text DEFAULT ''::text NOT NULL,
    ward text DEFAULT ''::text NOT NULL,
    finding_source text DEFAULT ''::text NOT NULL,
    baptisms integer DEFAULT 0 NOT NULL,
    confirmations integer DEFAULT 0 NOT NULL,
    CONSTRAINT baptism_history_weeks_baptisms_check CHECK ((baptisms >= 0)),
    CONSTRAINT baptism_history_weeks_confirmations_check CHECK ((confirmations >= 0)),
    CONSTRAINT baptism_history_weeks_sunday_check CHECK ((EXTRACT(isodow FROM sunday) = (7)::numeric))
);


ALTER TABLE public.baptism_history_weeks OWNER TO postgres;

--
-- Name: finding_rate_weeks; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.finding_rate_weeks (
    batch_id uuid NOT NULL,
    mission_id bigint NOT NULL,
    sunday date NOT NULL,
    report_date date NOT NULL,
    zone_id bigint,
    zone_name text NOT NULL,
    is_mission boolean DEFAULT false NOT NULL,
    teaching_rate numeric(8,4),
    contact_rate numeric(8,4),
    CONSTRAINT finding_rate_weeks_contact_rate_check CHECK ((contact_rate >= (0)::numeric)),
    CONSTRAINT finding_rate_weeks_sunday_check CHECK ((EXTRACT(isodow FROM sunday) = (7)::numeric)),
    CONSTRAINT finding_rate_weeks_teaching_rate_check CHECK ((teaching_rate >= (0)::numeric))
);


ALTER TABLE public.finding_rate_weeks OWNER TO postgres;

--
-- Name: referral_archive_weeks; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.referral_archive_weeks (
    batch_id uuid NOT NULL,
    mission_id bigint NOT NULL,
    sunday date NOT NULL,
    report_date date NOT NULL,
    zone_id bigint,
    area_id bigint,
    zone_name text DEFAULT ''::text NOT NULL,
    area_name text DEFAULT ''::text NOT NULL,
    source text DEFAULT ''::text NOT NULL,
    referrals_received integer,
    referrals_contacted integer,
    friends_made integer,
    lessons_taught integer,
    church_attendance integer,
    baptismal_dates integer,
    baptisms integer,
    books_of_mormon integer,
    with_member integer,
    follow_up_lessons integer,
    CONSTRAINT referral_archive_weeks_sunday_check CHECK ((EXTRACT(isodow FROM sunday) = (7)::numeric))
);


ALTER TABLE public.referral_archive_weeks OWNER TO postgres;

--
-- Name: roster_import_batches; Type: TABLE; Schema: public; Owner: supabase_admin
--

CREATE TABLE public.roster_import_batches (
    id uuid NOT NULL,
    mission_id bigint NOT NULL,
    kind text NOT NULL,
    filename text NOT NULL,
    effective_date date,
    actor text NOT NULL,
    status text DEFAULT 'APPLIED'::text NOT NULL,
    summary jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    undone_at timestamp with time zone,
    undone_by text,
    CONSTRAINT roster_import_batches_kind_check CHECK ((kind = ANY (ARRAY['TRANSFER'::text, 'HISTORICAL'::text, 'ACCOUNT'::text, 'AREA_DATA'::text, 'FINDING'::text, 'ZONE_HISTORY'::text, 'REFERRAL_ARCHIVE'::text, 'RATES'::text, 'BAPTISMS'::text, 'PEOPLE'::text, 'PLACES'::text]))),
    CONSTRAINT roster_import_batches_status_check CHECK ((status = ANY (ARRAY['APPLIED'::text, 'UNDONE'::text])))
);


ALTER TABLE public.roster_import_batches OWNER TO supabase_admin;

--
-- Name: zone_history_weeks; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.zone_history_weeks (
    batch_id uuid NOT NULL,
    mission_id bigint NOT NULL,
    sunday date NOT NULL,
    zone_id bigint,
    zone_name text NOT NULL,
    friends_found_goal integer,
    friends_found_actual integer,
    members_at_lessons_goal integer,
    members_at_lessons_actual integer,
    sacrament_attendance_goal integer,
    sacrament_attendance_actual integer,
    baptismal_dates_goal integer,
    baptismal_dates_actual integer,
    baptisms_confirmations_goal integer,
    baptisms_confirmations_actual integer,
    new_member_sacrament_goal integer,
    new_member_sacrament_actual integer,
    follow_up_lessons_actual integer,
    first_time_sacrament_actual integer,
    companionships integer,
    CONSTRAINT zone_history_weeks_sunday_check CHECK ((EXTRACT(isodow FROM sunday) = (7)::numeric))
);


ALTER TABLE public.zone_history_weeks OWNER TO postgres;

--
-- Name: data_upload_week_batches; Type: VIEW; Schema: public; Owner: postgres
--

CREATE VIEW public.data_upload_week_batches AS
 WITH weeks AS (
         SELECT 'ZONE_HISTORY'::text AS kind,
            zone_history_weeks.mission_id,
            zone_history_weeks.sunday,
            zone_history_weeks.batch_id
           FROM public.zone_history_weeks
        UNION
         SELECT 'REFERRAL_ARCHIVE'::text,
            referral_archive_weeks.mission_id,
            referral_archive_weeks.sunday,
            referral_archive_weeks.batch_id
           FROM public.referral_archive_weeks
        UNION
         SELECT 'RATES'::text,
            finding_rate_weeks.mission_id,
            finding_rate_weeks.sunday,
            finding_rate_weeks.batch_id
           FROM public.finding_rate_weeks
        UNION
         SELECT 'BAPTISMS'::text,
            baptism_history_weeks.mission_id,
            baptism_history_weeks.sunday,
            baptism_history_weeks.batch_id
           FROM public.baptism_history_weeks
        )
 SELECT DISTINCT ON (w.kind, w.mission_id, w.sunday) w.kind,
    w.mission_id,
    w.sunday,
    w.batch_id
   FROM (weeks w
     JOIN public.roster_import_batches b ON (((b.id = w.batch_id) AND (b.status = 'APPLIED'::text))))
  ORDER BY w.kind, w.mission_id, w.sunday, b.created_at DESC, b.id DESC;


ALTER TABLE public.data_upload_week_batches OWNER TO postgres;

--
-- Name: baptism_history_week; Type: VIEW; Schema: dashboards; Owner: postgres
--

CREATE VIEW dashboards.baptism_history_week AS
 SELECT b.sunday,
    ((b.sunday + '12:00:00'::time without time zone) AT TIME ZONE 'Europe/Berlin'::text) AS week,
    b.mission_id,
    COALESCE(pz.id, fz.id) AS zone_id,
    COALESCE(pz.name, fz.name, NULLIF(b.zone_name, ''::text)) AS zone,
    pd.id AS district_id,
    pd.name AS district,
    b.area_id,
    COALESCE(pa.name, NULLIF(b.area_name, ''::text)) AS area,
    NULLIF(b.ward, ''::text) AS ward,
    NULLIF(b.finding_source, ''::text) AS finding_source,
    b.baptisms,
    b.confirmations
   FROM (((((public.baptism_history_weeks b
     JOIN public.data_upload_week_batches w ON (((w.kind = 'BAPTISMS'::text) AND (w.batch_id = b.batch_id) AND (w.mission_id = b.mission_id) AND (w.sunday = b.sunday))))
     LEFT JOIN public.areas pa ON ((pa.id = b.area_id)))
     LEFT JOIN public.districts pd ON ((pd.id = pa.district_id)))
     LEFT JOIN public.zones pz ON ((pz.id = pd.zone_id)))
     LEFT JOIN public.zones fz ON ((fz.id = b.zone_id)));


ALTER TABLE dashboards.baptism_history_week OWNER TO postgres;

--
-- Name: finding_people; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.finding_people (
    batch_id uuid NOT NULL,
    mission_id bigint NOT NULL,
    person_key text NOT NULL,
    zone_id bigint,
    area_id bigint,
    zone_name text DEFAULT ''::text NOT NULL,
    district_name text DEFAULT ''::text NOT NULL,
    area_name text DEFAULT ''::text NOT NULL,
    finding_category text NOT NULL,
    finding_source text NOT NULL,
    found_on date,
    referral_on date,
    contact_attempt_on date,
    contacted_on date,
    first_lesson_on date,
    second_lesson_on date,
    taught_on date,
    baptismal_date_set_on date,
    first_sacrament_on date,
    confirmed_on date,
    CONSTRAINT finding_people_person_key_check CHECK ((person_key ~ '^[0-9a-f]{32}$'::text))
);


ALTER TABLE public.finding_people OWNER TO postgres;

--
-- Name: finding_people_latest; Type: VIEW; Schema: public; Owner: postgres
--

CREATE VIEW public.finding_people_latest AS
 SELECT DISTINCT ON (p.mission_id, p.person_key) p.batch_id,
    p.mission_id,
    p.person_key,
    p.zone_id,
    p.area_id,
    p.zone_name,
    p.district_name,
    p.area_name,
    p.finding_category,
    p.finding_source,
    p.found_on,
    p.referral_on,
    p.contact_attempt_on,
    p.contacted_on,
    p.first_lesson_on,
    p.second_lesson_on,
    p.taught_on,
    p.baptismal_date_set_on,
    p.first_sacrament_on,
    p.confirmed_on
   FROM (public.finding_people p
     JOIN public.roster_import_batches b ON (((b.id = p.batch_id) AND (b.status = 'APPLIED'::text))))
  ORDER BY p.mission_id, p.person_key, b.created_at DESC, b.id DESC;


ALTER TABLE public.finding_people_latest OWNER TO postgres;

--
-- Name: finding_people_placed; Type: VIEW; Schema: public; Owner: postgres
--

CREATE VIEW public.finding_people_placed AS
 SELECT p.mission_id,
    COALESCE(pz.id, p.zone_id) AS zone_id,
    COALESCE(pz.name, fz.name, p.zone_name) AS zone,
    pd.id AS district_id,
    COALESCE(pd.name, p.district_name) AS district,
    p.area_id,
    COALESCE(pa.name, p.area_name) AS area,
    p.finding_category,
    p.finding_source,
    ((p.finding_category = 'Media'::text) AND (p.finding_source <> 'Facebook - Personal Profile'::text)) AS findechristus,
    p.found_on,
    p.referral_on,
    p.contact_attempt_on,
    p.contacted_on,
    p.first_lesson_on,
    p.second_lesson_on,
    p.taught_on,
    p.baptismal_date_set_on,
    p.first_sacrament_on,
    p.confirmed_on
   FROM ((((public.finding_people_latest p
     LEFT JOIN public.areas pa ON ((pa.id = p.area_id)))
     LEFT JOIN public.districts pd ON ((pd.id = pa.district_id)))
     LEFT JOIN public.zones pz ON ((pz.id = pd.zone_id)))
     LEFT JOIN public.zones fz ON ((fz.id = p.zone_id)));


ALTER TABLE public.finding_people_placed OWNER TO postgres;

--
-- Name: finding_area_week; Type: VIEW; Schema: dashboards; Owner: postgres
--

CREATE VIEW dashboards.finding_area_week AS
 WITH events AS (
         SELECT p.mission_id,
            p.zone_id,
            p.zone,
            p.district_id,
            p.district,
            p.area_id,
            p.area,
            p.finding_category,
            p.finding_source,
            p.findechristus,
            e_1.what,
            (e_1.day + ((7 - (EXTRACT(isodow FROM e_1.day))::integer) % 7)) AS sunday
           FROM (public.finding_people_placed p
             CROSS JOIN LATERAL ( VALUES ('found'::text,p.found_on), ('referral'::text,p.referral_on), ('contact_attempt'::text,p.contact_attempt_on), ('contacted'::text,p.contacted_on), ('first_lesson'::text,p.first_lesson_on), ('second_lesson'::text,p.second_lesson_on), ('taught'::text,p.taught_on), ('baptismal_date'::text,p.baptismal_date_set_on), ('first_sacrament'::text,p.first_sacrament_on), ('confirmed'::text,p.confirmed_on)) e_1(what, day))
          WHERE (e_1.day IS NOT NULL)
        )
 SELECT e.sunday,
    ((e.sunday + '12:00:00'::time without time zone) AT TIME ZONE 'Europe/Berlin'::text) AS week,
    e.mission_id,
    e.zone_id,
    e.zone,
    e.district_id,
    e.district,
    e.area_id,
    e.area,
    e.finding_category,
    e.finding_source,
    e.findechristus,
    count(*) FILTER (WHERE (e.what = 'found'::text)) AS people_found,
    count(*) FILTER (WHERE (e.what = 'referral'::text)) AS referrals,
    count(*) FILTER (WHERE (e.what = 'contact_attempt'::text)) AS contact_attempts,
    count(*) FILTER (WHERE (e.what = 'contacted'::text)) AS people_reached,
    count(*) FILTER (WHERE (e.what = 'first_lesson'::text)) AS first_lessons,
    count(*) FILTER (WHERE (e.what = 'second_lesson'::text)) AS second_lessons,
    count(*) FILTER (WHERE (e.what = 'taught'::text)) AS new_people_being_taught,
    count(*) FILTER (WHERE (e.what = 'baptismal_date'::text)) AS baptismal_dates_set,
    count(*) FILTER (WHERE (e.what = 'first_sacrament'::text)) AS first_sacrament_meetings,
    count(*) FILTER (WHERE (e.what = 'confirmed'::text)) AS confirmations
   FROM events e
  GROUP BY e.sunday, e.mission_id, e.zone_id, e.zone, e.district_id, e.district, e.area_id, e.area, e.finding_category, e.finding_source, e.findechristus;


ALTER TABLE dashboards.finding_area_week OWNER TO postgres;

--
-- Name: referral_archive_week; Type: VIEW; Schema: dashboards; Owner: postgres
--

CREATE VIEW dashboards.referral_archive_week AS
 SELECT r.sunday,
    ((r.sunday + '12:00:00'::time without time zone) AT TIME ZONE 'Europe/Berlin'::text) AS week,
    r.report_date,
    r.mission_id,
    COALESCE(pz.id, fz.id) AS zone_id,
    COALESCE(pz.name, fz.name, NULLIF(r.zone_name, ''::text)) AS zone,
    pd.id AS district_id,
    pd.name AS district,
    r.area_id,
    COALESCE(pa.name, NULLIF(r.area_name, ''::text)) AS area,
    r.source,
    r.referrals_received,
    r.referrals_contacted,
    r.friends_made,
    r.lessons_taught,
    r.church_attendance,
    r.baptismal_dates,
    r.baptisms,
    r.books_of_mormon,
    r.with_member,
    r.follow_up_lessons
   FROM (((((public.referral_archive_weeks r
     JOIN public.data_upload_week_batches w ON (((w.kind = 'REFERRAL_ARCHIVE'::text) AND (w.batch_id = r.batch_id) AND (w.mission_id = r.mission_id) AND (w.sunday = r.sunday))))
     LEFT JOIN public.areas pa ON ((pa.id = r.area_id)))
     LEFT JOIN public.districts pd ON ((pd.id = pa.district_id)))
     LEFT JOIN public.zones pz ON ((pz.id = pd.zone_id)))
     LEFT JOIN public.zones fz ON ((fz.id = r.zone_id)));


ALTER TABLE dashboards.referral_archive_week OWNER TO postgres;

--
-- Name: findechristus_referrals_week; Type: VIEW; Schema: dashboards; Owner: postgres
--

CREATE VIEW dashboards.findechristus_referrals_week AS
 WITH finding AS (
         SELECT f.sunday,
            f.mission_id,
            f.zone_id,
            f.zone,
            f.district_id,
            f.district,
            f.area_id,
            f.area,
            (sum(f.people_found))::bigint AS referrals
           FROM dashboards.finding_area_week f
          WHERE (f.findechristus AND (f.people_found > 0))
          GROUP BY f.sunday, f.mission_id, f.zone_id, f.zone, f.district_id, f.district, f.area_id, f.area
        ), first_found AS (
         SELECT finding_people_placed.mission_id,
            min(finding_people_placed.found_on) AS day
           FROM public.finding_people_placed
          GROUP BY finding_people_placed.mission_id
        ), first_whole_week AS (
         SELECT first_found.mission_id,
            ((first_found.day + ((8 - (EXTRACT(isodow FROM first_found.day))::integer) % 7)) + 6) AS sunday
           FROM first_found
        ), archive AS (
         SELECT a.sunday,
            a.mission_id,
            a.zone_id,
            a.zone,
            a.district_id,
            a.district,
            a.area_id,
            a.area,
            sum(a.referrals_received) AS referrals
           FROM (dashboards.referral_archive_week a
             LEFT JOIN first_whole_week s ON ((s.mission_id = a.mission_id)))
          WHERE ((s.sunday IS NULL) OR (a.sunday < s.sunday))
          GROUP BY a.sunday, a.mission_id, a.zone_id, a.zone, a.district_id, a.district, a.area_id, a.area
        ), finding_used AS (
         SELECT f.sunday,
            f.mission_id,
            f.zone_id,
            f.zone,
            f.district_id,
            f.district,
            f.area_id,
            f.area,
            f.referrals
           FROM (finding f
             JOIN first_whole_week s ON ((s.mission_id = f.mission_id)))
          WHERE ((f.sunday >= s.sunday) OR (NOT (EXISTS ( SELECT 1
                   FROM archive a
                  WHERE ((a.mission_id = f.mission_id) AND (a.sunday = f.sunday))))))
        )
 SELECT x.sunday,
    ((x.sunday + '12:00:00'::time without time zone) AT TIME ZONE 'Europe/Berlin'::text) AS week,
    x.mission_id,
    x.zone_id,
    x.zone,
    x.district_id,
    x.district,
    x.area_id,
    x.area,
    x.referrals,
    x.data_source
   FROM ( SELECT finding_used.sunday,
            finding_used.mission_id,
            finding_used.zone_id,
            finding_used.zone,
            finding_used.district_id,
            finding_used.district,
            finding_used.area_id,
            finding_used.area,
            finding_used.referrals,
            'finding export'::text AS data_source
           FROM finding_used
        UNION ALL
         SELECT archive.sunday,
            archive.mission_id,
            archive.zone_id,
            archive.zone,
            archive.district_id,
            archive.district,
            archive.area_id,
            archive.area,
            archive.referrals,
            'referral archive'::text
           FROM archive) x;


ALTER TABLE dashboards.findechristus_referrals_week OWNER TO postgres;

--
-- Name: kpi_area_week; Type: VIEW; Schema: dashboards; Owner: postgres
--

CREATE VIEW dashboards.kpi_area_week AS
 SELECT area_week_rows.week,
    area_week_rows.sunday,
    area_week_rows.reporting_week_id,
    area_week_rows.previous_reporting_week_id,
    area_week_rows.mission_id,
    area_week_rows.zone_id,
    area_week_rows.zone,
    area_week_rows.district_id,
    area_week_rows.district,
    area_week_rows.area_id,
    area_week_rows.area,
    area_week_rows.unit_id,
    area_week_rows.unit,
    area_week_rows.status,
    area_week_rows.submitted,
    area_week_rows.friends_found_actual,
    area_week_rows.friends_found_goal,
    area_week_rows.friends_found_previous_goal,
    area_week_rows.baptisms_confirmations_actual,
    area_week_rows.baptisms_confirmations_goal,
    area_week_rows.baptisms_confirmations_previous_goal,
    area_week_rows.baptismal_dates_actual,
    area_week_rows.baptismal_dates_goal,
    area_week_rows.baptismal_dates_previous_goal,
    area_week_rows.sacrament_attendance_actual,
    area_week_rows.sacrament_attendance_goal,
    area_week_rows.sacrament_attendance_previous_goal,
    area_week_rows.members_at_lessons_actual,
    area_week_rows.members_at_lessons_goal,
    area_week_rows.members_at_lessons_previous_goal,
    area_week_rows.new_member_sacrament_actual,
    area_week_rows.new_member_sacrament_goal,
    area_week_rows.new_member_sacrament_previous_goal,
    area_week_rows.first_time_sacrament_actual,
    area_week_rows.lessons_with_friends_actual,
    area_week_rows.lessons_with_friends_goal,
    area_week_rows.follow_up_lessons_actual,
    area_week_rows.follow_up_lessons_goal
   FROM dashboards.area_week_rows() area_week_rows(week, sunday, reporting_week_id, previous_reporting_week_id, mission_id, zone_id, zone, district_id, district, area_id, area, unit_id, unit, status, submitted, friends_found_actual, friends_found_goal, friends_found_previous_goal, baptisms_confirmations_actual, baptisms_confirmations_goal, baptisms_confirmations_previous_goal, baptismal_dates_actual, baptismal_dates_goal, baptismal_dates_previous_goal, sacrament_attendance_actual, sacrament_attendance_goal, sacrament_attendance_previous_goal, members_at_lessons_actual, members_at_lessons_goal, members_at_lessons_previous_goal, new_member_sacrament_actual, new_member_sacrament_goal, new_member_sacrament_previous_goal, first_time_sacrament_actual, lessons_with_friends_actual, lessons_with_friends_goal, follow_up_lessons_actual, follow_up_lessons_goal);


ALTER TABLE dashboards.kpi_area_week OWNER TO postgres;

--
-- Name: kpi_area_total_week; Type: VIEW; Schema: dashboards; Owner: postgres
--

CREATE VIEW dashboards.kpi_area_total_week AS
 WITH base AS MATERIALIZED (
         SELECT kpi_area_week.week,
            kpi_area_week.sunday,
            kpi_area_week.reporting_week_id,
            kpi_area_week.previous_reporting_week_id,
            kpi_area_week.mission_id,
            kpi_area_week.zone_id,
            kpi_area_week.zone,
            kpi_area_week.district_id,
            kpi_area_week.district,
            kpi_area_week.area_id,
            kpi_area_week.area,
            kpi_area_week.unit_id,
            kpi_area_week.unit,
            kpi_area_week.status,
            kpi_area_week.submitted,
            kpi_area_week.friends_found_actual,
            kpi_area_week.friends_found_goal,
            kpi_area_week.friends_found_previous_goal,
            kpi_area_week.baptisms_confirmations_actual,
            kpi_area_week.baptisms_confirmations_goal,
            kpi_area_week.baptisms_confirmations_previous_goal,
            kpi_area_week.baptismal_dates_actual,
            kpi_area_week.baptismal_dates_goal,
            kpi_area_week.baptismal_dates_previous_goal,
            kpi_area_week.sacrament_attendance_actual,
            kpi_area_week.sacrament_attendance_goal,
            kpi_area_week.sacrament_attendance_previous_goal,
            kpi_area_week.members_at_lessons_actual,
            kpi_area_week.members_at_lessons_goal,
            kpi_area_week.members_at_lessons_previous_goal,
            kpi_area_week.new_member_sacrament_actual,
            kpi_area_week.new_member_sacrament_goal,
            kpi_area_week.new_member_sacrament_previous_goal,
            kpi_area_week.first_time_sacrament_actual,
            kpi_area_week.lessons_with_friends_actual,
            kpi_area_week.lessons_with_friends_goal,
            kpi_area_week.follow_up_lessons_actual,
            kpi_area_week.follow_up_lessons_goal
           FROM dashboards.kpi_area_week
        ), totals AS (
         SELECT k.reporting_week_id,
            k.area_id,
            count(*) AS reports,
            count(*) FILTER (WHERE k.submitted) AS submitted_reports,
            count(DISTINCT k.unit_id) AS units_reporting,
            sum(COALESCE(k.friends_found_actual, 0)) AS friends_found_actual,
            sum(COALESCE(k.friends_found_goal, 0)) AS friends_found_goal,
            sum(COALESCE(k.baptisms_confirmations_actual, 0)) AS baptisms_confirmations_actual,
            sum(COALESCE(k.baptisms_confirmations_goal, 0)) AS baptisms_confirmations_goal,
            sum(COALESCE(k.baptismal_dates_actual, 0)) AS baptismal_dates_actual,
            sum(COALESCE(k.baptismal_dates_goal, 0)) AS baptismal_dates_goal,
            sum(COALESCE(k.sacrament_attendance_actual, 0)) AS sacrament_attendance_actual,
            sum(COALESCE(k.sacrament_attendance_goal, 0)) AS sacrament_attendance_goal,
            sum(COALESCE(k.members_at_lessons_actual, 0)) AS members_at_lessons_actual,
            sum(COALESCE(k.members_at_lessons_goal, 0)) AS members_at_lessons_goal,
            sum(COALESCE(k.new_member_sacrament_actual, 0)) AS new_member_sacrament_actual,
            sum(COALESCE(k.new_member_sacrament_goal, 0)) AS new_member_sacrament_goal,
            sum(COALESCE(k.first_time_sacrament_actual, 0)) AS first_time_sacrament_actual,
            sum(COALESCE(k.lessons_with_friends_actual, 0)) AS lessons_with_friends_actual,
            sum(COALESCE(k.lessons_with_friends_goal, 0)) AS lessons_with_friends_goal,
            sum(COALESCE(k.follow_up_lessons_actual, 0)) AS follow_up_lessons_actual,
            sum(COALESCE(k.follow_up_lessons_goal, 0)) AS follow_up_lessons_goal
           FROM base k
          GROUP BY k.reporting_week_id, k.area_id
        ), areas AS (
         SELECT DISTINCT k.mission_id,
            k.zone_id,
            k.zone,
            k.district_id,
            k.district,
            k.area_id,
            k.area
           FROM base k
        ), weeks AS (
         SELECT DISTINCT k.reporting_week_id,
            k.previous_reporting_week_id,
            k.week,
            k.sunday
           FROM base k
        ), cells AS (
         SELECT DISTINCT w_1.reporting_week_id,
            x.area_id
           FROM (weeks w_1
             JOIN totals x ON (((x.reporting_week_id = w_1.reporting_week_id) OR (x.reporting_week_id = w_1.previous_reporting_week_id))))
        )
 SELECT w.week,
    w.sunday,
    w.reporting_week_id,
    a.mission_id,
    a.zone_id,
    a.zone,
    a.district_id,
    a.district,
    a.area_id,
    a.area,
    COALESCE(t.reports, (0)::bigint) AS reports,
    COALESCE(t.submitted_reports, (0)::bigint) AS submitted_reports,
    COALESCE(t.units_reporting, (0)::bigint) AS units_reporting,
    t.friends_found_actual,
    t.friends_found_goal,
    p.friends_found_goal AS friends_found_previous_goal,
    t.baptisms_confirmations_actual,
    t.baptisms_confirmations_goal,
    p.baptisms_confirmations_goal AS baptisms_confirmations_previous_goal,
    t.baptismal_dates_actual,
    t.baptismal_dates_goal,
    p.baptismal_dates_goal AS baptismal_dates_previous_goal,
    t.sacrament_attendance_actual,
    t.sacrament_attendance_goal,
    p.sacrament_attendance_goal AS sacrament_attendance_previous_goal,
    t.members_at_lessons_actual,
    t.members_at_lessons_goal,
    p.members_at_lessons_goal AS members_at_lessons_previous_goal,
    t.new_member_sacrament_actual,
    t.new_member_sacrament_goal,
    p.new_member_sacrament_goal AS new_member_sacrament_previous_goal,
    t.first_time_sacrament_actual,
    t.lessons_with_friends_actual,
    t.lessons_with_friends_goal,
    t.follow_up_lessons_actual,
    t.follow_up_lessons_goal
   FROM ((((cells c
     JOIN weeks w ON ((w.reporting_week_id = c.reporting_week_id)))
     JOIN areas a ON ((a.area_id = c.area_id)))
     LEFT JOIN totals t ON (((t.reporting_week_id = c.reporting_week_id) AND (t.area_id = c.area_id))))
     LEFT JOIN totals p ON (((p.reporting_week_id = w.previous_reporting_week_id) AND (p.area_id = c.area_id))));


ALTER TABLE dashboards.kpi_area_total_week OWNER TO postgres;

--
-- Name: archetype_area_week; Type: VIEW; Schema: dashboards; Owner: postgres
--

CREATE VIEW dashboards.archetype_area_week AS
 WITH plans AS MATERIALIZED (
         SELECT k_1.week,
            k_1.sunday,
            k_1.reporting_week_id,
            k_1.mission_id,
            k_1.zone_id,
            k_1.zone,
            k_1.district_id,
            k_1.district,
            k_1.area_id,
            k_1.area,
            k_1.reports,
            k_1.submitted_reports,
            k_1.units_reporting,
            k_1.friends_found_actual,
            k_1.friends_found_goal,
            k_1.friends_found_previous_goal,
            k_1.baptisms_confirmations_actual,
            k_1.baptisms_confirmations_goal,
            k_1.baptisms_confirmations_previous_goal,
            k_1.baptismal_dates_actual,
            k_1.baptismal_dates_goal,
            k_1.baptismal_dates_previous_goal,
            k_1.sacrament_attendance_actual,
            k_1.sacrament_attendance_goal,
            k_1.sacrament_attendance_previous_goal,
            k_1.members_at_lessons_actual,
            k_1.members_at_lessons_goal,
            k_1.members_at_lessons_previous_goal,
            k_1.new_member_sacrament_actual,
            k_1.new_member_sacrament_goal,
            k_1.new_member_sacrament_previous_goal,
            k_1.first_time_sacrament_actual,
            k_1.lessons_with_friends_actual,
            k_1.lessons_with_friends_goal,
            k_1.follow_up_lessons_actual,
            k_1.follow_up_lessons_goal
           FROM dashboards.kpi_area_total_week k_1
          WHERE (k_1.reports > 0)
        ), extra AS MATERIALIZED (
         SELECT archetype_plan_rows.reporting_week_id,
            archetype_plan_rows.area_id,
            archetype_plan_rows.first_time_first_week_sacrament,
            archetype_plan_rows.member_meals_active,
            archetype_plan_rows.member_meals_less_active,
            archetype_plan_rows.member_meals_part_member,
            archetype_plan_rows.member_visits_active,
            archetype_plan_rows.member_visits_less_active,
            archetype_plan_rows.member_visits_part_member,
            archetype_plan_rows.member_referral_asks,
            archetype_plan_rows.lessons_asked_referral,
            archetype_plan_rows.facebook_finding_days,
            archetype_plan_rows.facebook_friends_found,
            archetype_plan_rows.youth_activities,
            archetype_plan_rows.service_hours,
            archetype_plan_rows.less_active_sacrament,
            archetype_plan_rows.new_members_on_plan,
            archetype_plan_rows.new_member_lessons,
            archetype_plan_rows.new_members_at_church
           FROM dashboards.archetype_plan_rows() archetype_plan_rows(reporting_week_id, area_id, first_time_first_week_sacrament, member_meals_active, member_meals_less_active, member_meals_part_member, member_visits_active, member_visits_less_active, member_visits_part_member, member_referral_asks, lessons_asked_referral, facebook_finding_days, facebook_friends_found, youth_activities, service_hours, less_active_sacrament, new_members_on_plan, new_member_lessons, new_members_at_church)
        ), fc AS (
         SELECT f.sunday,
            f.area_id,
            sum(f.referrals) AS referrals
           FROM dashboards.findechristus_referrals_week f
          GROUP BY f.sunday, f.area_id
        ), fc_weeks AS (
         SELECT DISTINCT f.sunday
           FROM dashboards.findechristus_referrals_week f
        ), finding AS (
         SELECT f.sunday,
            f.area_id,
            sum(f.people_found) AS people_found,
            sum(f.people_reached) AS people_reached,
            sum(f.first_lessons) AS first_lessons
           FROM dashboards.finding_area_week f
          GROUP BY f.sunday, f.area_id
        ), finding_weeks AS (
         SELECT DISTINCT f.sunday
           FROM dashboards.finding_area_week f
        ), baptisms AS (
         SELECT b_1.sunday,
            b_1.area_id,
            sum(b_1.baptisms) AS baptisms
           FROM dashboards.baptism_history_week b_1
          GROUP BY b_1.sunday, b_1.area_id
        ), baptism_weeks AS (
         SELECT DISTINCT b_1.sunday
           FROM dashboards.baptism_history_week b_1
        )
 SELECT k.sunday,
    k.week,
    k.reporting_week_id,
    k.mission_id,
    k.zone_id,
    k.zone,
    k.district_id,
    k.district,
    k.area_id,
    k.area,
    k.reports,
    k.friends_found_actual AS friends_found,
    k.lessons_with_friends_actual AS lessons_with_friends,
    k.follow_up_lessons_actual AS follow_up_lessons,
    k.members_at_lessons_actual AS members_at_lessons,
    k.baptismal_dates_actual AS baptismal_dates,
    k.baptisms_confirmations_actual AS baptisms_confirmations,
    k.sacrament_attendance_actual AS sacrament_attendance,
    k.first_time_sacrament_actual AS first_time_sacrament,
    k.new_member_sacrament_actual AS new_member_sacrament,
    e.first_time_first_week_sacrament,
    e.member_meals_active,
    e.member_meals_less_active,
    e.member_meals_part_member,
    e.member_visits_active,
    e.member_visits_less_active,
    e.member_visits_part_member,
    e.member_referral_asks,
    e.lessons_asked_referral,
    e.facebook_finding_days,
    e.facebook_friends_found,
    e.youth_activities,
    e.service_hours,
    e.less_active_sacrament,
    COALESCE(e.new_members_on_plan, (0)::bigint) AS new_members_on_plan,
    e.new_member_lessons,
    e.new_members_at_church,
        CASE
            WHEN (e.new_members_on_plan > 0) THEN round((COALESCE(e.new_member_lessons, (0)::numeric) / (e.new_members_on_plan)::numeric), 4)
            ELSE NULL::numeric
        END AS new_member_lessons_per_member,
        CASE
            WHEN (e.new_members_on_plan > 0) THEN round(((COALESCE(e.new_members_at_church, (0)::bigint))::numeric / (e.new_members_on_plan)::numeric), 4)
            ELSE NULL::numeric
        END AS new_member_sacrament_share,
        CASE
            WHEN (fw.sunday IS NOT NULL) THEN COALESCE(fc.referrals, (0)::numeric)
            ELSE NULL::numeric
        END AS findechristus_referrals,
        CASE
            WHEN (nw.sunday IS NOT NULL) THEN COALESCE(fi.people_found, (0)::numeric)
            ELSE NULL::numeric
        END AS finding_people_found,
        CASE
            WHEN (nw.sunday IS NOT NULL) THEN COALESCE(fi.people_reached, (0)::numeric)
            ELSE NULL::numeric
        END AS finding_people_reached,
        CASE
            WHEN (nw.sunday IS NOT NULL) THEN COALESCE(fi.first_lessons, (0)::numeric)
            ELSE NULL::numeric
        END AS finding_first_lessons,
        CASE
            WHEN (bw.sunday IS NOT NULL) THEN COALESCE(b.baptisms, (0)::bigint)
            ELSE NULL::bigint
        END AS baptism_records
   FROM (((((((plans k
     LEFT JOIN extra e ON (((e.reporting_week_id = k.reporting_week_id) AND (e.area_id = k.area_id))))
     LEFT JOIN fc_weeks fw ON ((fw.sunday = k.sunday)))
     LEFT JOIN fc ON (((fc.sunday = k.sunday) AND (fc.area_id = k.area_id))))
     LEFT JOIN finding_weeks nw ON ((nw.sunday = k.sunday)))
     LEFT JOIN finding fi ON (((fi.sunday = k.sunday) AND (fi.area_id = k.area_id))))
     LEFT JOIN baptism_weeks bw ON ((bw.sunday = k.sunday)))
     LEFT JOIN baptisms b ON (((b.sunday = k.sunday) AND (b.area_id = k.area_id))));


ALTER TABLE dashboards.archetype_area_week OWNER TO postgres;

--
-- Name: area_profile; Type: VIEW; Schema: dashboards; Owner: postgres
--

CREATE VIEW dashboards.area_profile AS
 SELECT z.mission_id,
    z.id AS zone_id,
    z.name AS zone,
    d.id AS district_id,
    d.name AS district,
    a.id AS area_id,
    a.name AS area,
    a.active,
    p.population,
    p.size_km2,
        CASE
            WHEN ((p.population IS NOT NULL) AND (p.size_km2 > (0)::numeric)) THEN round(((p.population)::numeric / p.size_km2), 1)
            ELSE NULL::numeric
        END AS density_per_km2,
    p.urban_type,
    p.assignment_type,
    COALESCE(p.extra, '{}'::jsonb) AS extra,
    p.updated_at
   FROM (((public.areas a
     JOIN public.districts d ON ((d.id = a.district_id)))
     JOIN public.zones z ON ((z.id = d.zone_id)))
     LEFT JOIN public.area_profiles p ON ((p.area_id = a.id)))
  WHERE (a.active OR (p.area_id IS NOT NULL));


ALTER TABLE dashboards.area_profile OWNER TO postgres;

--
-- Name: finding_cohort_week; Type: VIEW; Schema: dashboards; Owner: postgres
--

CREATE VIEW dashboards.finding_cohort_week AS
 SELECT (p.found_on + ((7 - (EXTRACT(isodow FROM p.found_on))::integer) % 7)) AS sunday,
    (((p.found_on + ((7 - (EXTRACT(isodow FROM p.found_on))::integer) % 7)) + '12:00:00'::time without time zone) AT TIME ZONE 'Europe/Berlin'::text) AS week,
    p.mission_id,
    p.zone_id,
    p.zone,
    p.district_id,
    p.district,
    p.area_id,
    p.area,
    p.finding_category,
    p.finding_source,
    p.findechristus,
    count(*) AS people_found,
    count(p.contact_attempt_on) AS contact_attempted,
    count(p.contacted_on) AS reached,
    count(p.first_lesson_on) AS taught,
    count(p.taught_on) AS new_people_being_taught,
    count(p.baptismal_date_set_on) AS with_baptismal_date,
    count(p.first_sacrament_on) AS at_sacrament_meeting,
    count(p.confirmed_on) AS confirmed
   FROM public.finding_people_placed p
  WHERE (p.found_on IS NOT NULL)
  GROUP BY (p.found_on + ((7 - (EXTRACT(isodow FROM p.found_on))::integer) % 7)), ((((p.found_on + ((7 - (EXTRACT(isodow FROM p.found_on))::integer) % 7)) + '12:00:00'::time without time zone) AT TIME ZONE 'Europe/Berlin'::text)), p.mission_id, p.zone_id, p.zone, p.district_id, p.district, p.area_id, p.area, p.finding_category, p.finding_source, p.findechristus;


ALTER TABLE dashboards.finding_cohort_week OWNER TO postgres;

--
-- Name: finding_rate_week; Type: VIEW; Schema: dashboards; Owner: postgres
--

CREATE VIEW dashboards.finding_rate_week AS
 SELECT r.sunday,
    ((r.sunday + '12:00:00'::time without time zone) AT TIME ZONE 'Europe/Berlin'::text) AS week,
    r.report_date,
    r.mission_id,
    r.is_mission,
        CASE
            WHEN r.is_mission THEN NULL::bigint
            ELSE COALESCE(z.id, r.zone_id)
        END AS zone_id,
        CASE
            WHEN r.is_mission THEN 'Mission'::text
            ELSE COALESCE(z.name, r.zone_name)
        END AS zone,
    r.teaching_rate,
    r.contact_rate
   FROM ((public.finding_rate_weeks r
     JOIN public.data_upload_week_batches w ON (((w.kind = 'RATES'::text) AND (w.batch_id = r.batch_id) AND (w.mission_id = r.mission_id) AND (w.sunday = r.sunday))))
     LEFT JOIN public.zones z ON ((z.id = r.zone_id)));


ALTER TABLE dashboards.finding_rate_week OWNER TO postgres;

--
-- Name: kpi_district_week; Type: VIEW; Schema: dashboards; Owner: postgres
--

CREATE VIEW dashboards.kpi_district_week AS
 SELECT k.week,
    k.sunday,
    k.reporting_week_id,
    k.mission_id,
    k.zone_id,
    k.zone,
    k.district_id,
    k.district,
    (sum(k.reports))::bigint AS reports,
    (sum(k.submitted_reports))::bigint AS submitted_reports,
    count(*) FILTER (WHERE (k.reports > 0)) AS areas_reporting,
    (sum(k.friends_found_actual))::bigint AS friends_found_actual,
    (sum(k.friends_found_goal))::bigint AS friends_found_goal,
    (sum(k.friends_found_previous_goal))::bigint AS friends_found_previous_goal,
    (sum(k.baptisms_confirmations_actual))::bigint AS baptisms_confirmations_actual,
    (sum(k.baptisms_confirmations_goal))::bigint AS baptisms_confirmations_goal,
    (sum(k.baptisms_confirmations_previous_goal))::bigint AS baptisms_confirmations_previous_goal,
    (sum(k.baptismal_dates_actual))::bigint AS baptismal_dates_actual,
    (sum(k.baptismal_dates_goal))::bigint AS baptismal_dates_goal,
    (sum(k.baptismal_dates_previous_goal))::bigint AS baptismal_dates_previous_goal,
    (sum(k.sacrament_attendance_actual))::bigint AS sacrament_attendance_actual,
    (sum(k.sacrament_attendance_goal))::bigint AS sacrament_attendance_goal,
    (sum(k.sacrament_attendance_previous_goal))::bigint AS sacrament_attendance_previous_goal,
    (sum(k.members_at_lessons_actual))::bigint AS members_at_lessons_actual,
    (sum(k.members_at_lessons_goal))::bigint AS members_at_lessons_goal,
    (sum(k.members_at_lessons_previous_goal))::bigint AS members_at_lessons_previous_goal,
    (sum(k.new_member_sacrament_actual))::bigint AS new_member_sacrament_actual,
    (sum(k.new_member_sacrament_goal))::bigint AS new_member_sacrament_goal,
    (sum(k.new_member_sacrament_previous_goal))::bigint AS new_member_sacrament_previous_goal,
    (sum(k.first_time_sacrament_actual))::bigint AS first_time_sacrament_actual,
    (sum(k.lessons_with_friends_actual))::bigint AS lessons_with_friends_actual,
    (sum(k.lessons_with_friends_goal))::bigint AS lessons_with_friends_goal,
    (sum(k.follow_up_lessons_actual))::bigint AS follow_up_lessons_actual,
    (sum(k.follow_up_lessons_goal))::bigint AS follow_up_lessons_goal
   FROM dashboards.kpi_area_total_week k
  GROUP BY k.week, k.sunday, k.reporting_week_id, k.mission_id, k.zone_id, k.zone, k.district_id, k.district;


ALTER TABLE dashboards.kpi_district_week OWNER TO postgres;

--
-- Name: kpi_mission_week; Type: VIEW; Schema: dashboards; Owner: postgres
--

CREATE VIEW dashboards.kpi_mission_week AS
 WITH totals AS (
         SELECT min(k.week) AS week,
            min(k.sunday) AS sunday,
            k.reporting_week_id,
            min(k.previous_reporting_week_id) AS previous_reporting_week_id,
            k.mission_id,
            count(*) AS reports,
            count(*) FILTER (WHERE k.submitted) AS submitted_reports,
            count(DISTINCT k.area_id) AS areas_reporting,
            count(DISTINCT k.zone_id) AS zones_reporting,
            sum(COALESCE(k.friends_found_actual, 0)) AS friends_found_actual,
            sum(COALESCE(k.friends_found_goal, 0)) AS friends_found_goal,
            sum(COALESCE(k.baptisms_confirmations_actual, 0)) AS baptisms_confirmations_actual,
            sum(COALESCE(k.baptisms_confirmations_goal, 0)) AS baptisms_confirmations_goal,
            sum(COALESCE(k.baptismal_dates_actual, 0)) AS baptismal_dates_actual,
            sum(COALESCE(k.baptismal_dates_goal, 0)) AS baptismal_dates_goal,
            sum(COALESCE(k.sacrament_attendance_actual, 0)) AS sacrament_attendance_actual,
            sum(COALESCE(k.sacrament_attendance_goal, 0)) AS sacrament_attendance_goal,
            sum(COALESCE(k.members_at_lessons_actual, 0)) AS members_at_lessons_actual,
            sum(COALESCE(k.members_at_lessons_goal, 0)) AS members_at_lessons_goal,
            sum(COALESCE(k.new_member_sacrament_actual, 0)) AS new_member_sacrament_actual,
            sum(COALESCE(k.new_member_sacrament_goal, 0)) AS new_member_sacrament_goal,
            sum(COALESCE(k.first_time_sacrament_actual, 0)) AS first_time_sacrament_actual,
            sum(COALESCE(k.lessons_with_friends_actual, 0)) AS lessons_with_friends_actual,
            sum(COALESCE(k.lessons_with_friends_goal, 0)) AS lessons_with_friends_goal,
            sum(COALESCE(k.follow_up_lessons_actual, 0)) AS follow_up_lessons_actual,
            sum(COALESCE(k.follow_up_lessons_goal, 0)) AS follow_up_lessons_goal
           FROM dashboards.kpi_area_week k
          GROUP BY k.reporting_week_id, k.mission_id
        )
 SELECT t.week,
    t.sunday,
    t.reporting_week_id,
    t.mission_id,
    t.reports,
    t.submitted_reports,
    t.areas_reporting,
    t.zones_reporting,
    t.friends_found_actual,
    t.friends_found_goal,
    p.friends_found_goal AS friends_found_previous_goal,
    t.baptisms_confirmations_actual,
    t.baptisms_confirmations_goal,
    p.baptisms_confirmations_goal AS baptisms_confirmations_previous_goal,
    t.baptismal_dates_actual,
    t.baptismal_dates_goal,
    p.baptismal_dates_goal AS baptismal_dates_previous_goal,
    t.sacrament_attendance_actual,
    t.sacrament_attendance_goal,
    p.sacrament_attendance_goal AS sacrament_attendance_previous_goal,
    t.members_at_lessons_actual,
    t.members_at_lessons_goal,
    p.members_at_lessons_goal AS members_at_lessons_previous_goal,
    t.new_member_sacrament_actual,
    t.new_member_sacrament_goal,
    p.new_member_sacrament_goal AS new_member_sacrament_previous_goal,
    t.first_time_sacrament_actual,
    t.lessons_with_friends_actual,
    t.lessons_with_friends_goal,
    t.follow_up_lessons_actual,
    t.follow_up_lessons_goal
   FROM (totals t
     LEFT JOIN totals p ON (((p.reporting_week_id = t.previous_reporting_week_id) AND (p.mission_id = t.mission_id))));


ALTER TABLE dashboards.kpi_mission_week OWNER TO postgres;

--
-- Name: kpi_zone_week; Type: VIEW; Schema: dashboards; Owner: postgres
--

CREATE VIEW dashboards.kpi_zone_week AS
 WITH base AS MATERIALIZED (
         SELECT kpi_area_week.week,
            kpi_area_week.sunday,
            kpi_area_week.reporting_week_id,
            kpi_area_week.previous_reporting_week_id,
            kpi_area_week.mission_id,
            kpi_area_week.zone_id,
            kpi_area_week.zone,
            kpi_area_week.district_id,
            kpi_area_week.district,
            kpi_area_week.area_id,
            kpi_area_week.area,
            kpi_area_week.unit_id,
            kpi_area_week.unit,
            kpi_area_week.status,
            kpi_area_week.submitted,
            kpi_area_week.friends_found_actual,
            kpi_area_week.friends_found_goal,
            kpi_area_week.friends_found_previous_goal,
            kpi_area_week.baptisms_confirmations_actual,
            kpi_area_week.baptisms_confirmations_goal,
            kpi_area_week.baptisms_confirmations_previous_goal,
            kpi_area_week.baptismal_dates_actual,
            kpi_area_week.baptismal_dates_goal,
            kpi_area_week.baptismal_dates_previous_goal,
            kpi_area_week.sacrament_attendance_actual,
            kpi_area_week.sacrament_attendance_goal,
            kpi_area_week.sacrament_attendance_previous_goal,
            kpi_area_week.members_at_lessons_actual,
            kpi_area_week.members_at_lessons_goal,
            kpi_area_week.members_at_lessons_previous_goal,
            kpi_area_week.new_member_sacrament_actual,
            kpi_area_week.new_member_sacrament_goal,
            kpi_area_week.new_member_sacrament_previous_goal,
            kpi_area_week.first_time_sacrament_actual,
            kpi_area_week.lessons_with_friends_actual,
            kpi_area_week.lessons_with_friends_goal,
            kpi_area_week.follow_up_lessons_actual,
            kpi_area_week.follow_up_lessons_goal
           FROM dashboards.kpi_area_week
        ), totals AS (
         SELECT k.reporting_week_id,
            k.mission_id,
            k.zone_id,
            min(k.zone) AS zone,
            count(*) AS reports,
            count(*) FILTER (WHERE k.submitted) AS submitted_reports,
            count(DISTINCT k.area_id) AS areas_reporting,
            sum(COALESCE(k.friends_found_actual, 0)) AS friends_found_actual,
            sum(COALESCE(k.friends_found_goal, 0)) AS friends_found_goal,
            sum(COALESCE(k.baptisms_confirmations_actual, 0)) AS baptisms_confirmations_actual,
            sum(COALESCE(k.baptisms_confirmations_goal, 0)) AS baptisms_confirmations_goal,
            sum(COALESCE(k.baptismal_dates_actual, 0)) AS baptismal_dates_actual,
            sum(COALESCE(k.baptismal_dates_goal, 0)) AS baptismal_dates_goal,
            sum(COALESCE(k.sacrament_attendance_actual, 0)) AS sacrament_attendance_actual,
            sum(COALESCE(k.sacrament_attendance_goal, 0)) AS sacrament_attendance_goal,
            sum(COALESCE(k.members_at_lessons_actual, 0)) AS members_at_lessons_actual,
            sum(COALESCE(k.members_at_lessons_goal, 0)) AS members_at_lessons_goal,
            sum(COALESCE(k.new_member_sacrament_actual, 0)) AS new_member_sacrament_actual,
            sum(COALESCE(k.new_member_sacrament_goal, 0)) AS new_member_sacrament_goal,
            sum(COALESCE(k.first_time_sacrament_actual, 0)) AS first_time_sacrament_actual,
            sum(COALESCE(k.lessons_with_friends_actual, 0)) AS lessons_with_friends_actual,
            sum(COALESCE(k.lessons_with_friends_goal, 0)) AS lessons_with_friends_goal,
            sum(COALESCE(k.follow_up_lessons_actual, 0)) AS follow_up_lessons_actual,
            sum(COALESCE(k.follow_up_lessons_goal, 0)) AS follow_up_lessons_goal
           FROM base k
          GROUP BY k.reporting_week_id, k.mission_id, k.zone_id
        ), weeks AS (
         SELECT DISTINCT k.reporting_week_id,
            k.previous_reporting_week_id,
            k.week,
            k.sunday
           FROM base k
        ), cells AS (
         SELECT DISTINCT w_1.reporting_week_id,
            x.mission_id,
            x.zone_id,
            x.zone
           FROM (weeks w_1
             JOIN totals x ON (((x.reporting_week_id = w_1.reporting_week_id) OR (x.reporting_week_id = w_1.previous_reporting_week_id))))
        )
 SELECT w.week,
    w.sunday,
    w.reporting_week_id,
    c.mission_id,
    c.zone_id,
    c.zone,
    COALESCE(t.reports, (0)::bigint) AS reports,
    COALESCE(t.submitted_reports, (0)::bigint) AS submitted_reports,
    COALESCE(t.areas_reporting, (0)::bigint) AS areas_reporting,
    t.friends_found_actual,
    t.friends_found_goal,
    p.friends_found_goal AS friends_found_previous_goal,
    t.baptisms_confirmations_actual,
    t.baptisms_confirmations_goal,
    p.baptisms_confirmations_goal AS baptisms_confirmations_previous_goal,
    t.baptismal_dates_actual,
    t.baptismal_dates_goal,
    p.baptismal_dates_goal AS baptismal_dates_previous_goal,
    t.sacrament_attendance_actual,
    t.sacrament_attendance_goal,
    p.sacrament_attendance_goal AS sacrament_attendance_previous_goal,
    t.members_at_lessons_actual,
    t.members_at_lessons_goal,
    p.members_at_lessons_goal AS members_at_lessons_previous_goal,
    t.new_member_sacrament_actual,
    t.new_member_sacrament_goal,
    p.new_member_sacrament_goal AS new_member_sacrament_previous_goal,
    t.first_time_sacrament_actual,
    t.lessons_with_friends_actual,
    t.lessons_with_friends_goal,
    t.follow_up_lessons_actual,
    t.follow_up_lessons_goal
   FROM (((cells c
     JOIN weeks w ON ((w.reporting_week_id = c.reporting_week_id)))
     LEFT JOIN totals t ON (((t.reporting_week_id = c.reporting_week_id) AND (t.zone_id = c.zone_id))))
     LEFT JOIN totals p ON (((p.reporting_week_id = w.previous_reporting_week_id) AND (p.zone_id = c.zone_id))));


ALTER TABLE dashboards.kpi_zone_week OWNER TO postgres;

--
-- Name: zone_history_week; Type: VIEW; Schema: dashboards; Owner: postgres
--

CREATE VIEW dashboards.zone_history_week AS
 WITH portal AS (
         SELECT k.sunday,
            k.mission_id,
            k.zone_id,
            k.zone,
            k.friends_found_actual,
            k.friends_found_goal,
            k.friends_found_previous_goal,
            k.members_at_lessons_actual,
            k.members_at_lessons_goal,
            k.members_at_lessons_previous_goal,
            k.sacrament_attendance_actual,
            k.sacrament_attendance_goal,
            k.sacrament_attendance_previous_goal,
            k.baptismal_dates_actual,
            k.baptismal_dates_goal,
            k.baptismal_dates_previous_goal,
            k.baptisms_confirmations_actual,
            k.baptisms_confirmations_goal,
            k.baptisms_confirmations_previous_goal,
            k.new_member_sacrament_actual,
            k.new_member_sacrament_goal,
            k.new_member_sacrament_previous_goal,
            k.follow_up_lessons_actual,
            k.first_time_sacrament_actual,
            k.areas_reporting AS companionships
           FROM dashboards.kpi_zone_week k
          WHERE (k.reports > 0)
        ), counted AS (
         SELECT u.batch_id,
            u.mission_id,
            u.sunday,
            u.zone_id,
            u.zone_name,
            u.friends_found_goal,
            u.friends_found_actual,
            u.members_at_lessons_goal,
            u.members_at_lessons_actual,
            u.sacrament_attendance_goal,
            u.sacrament_attendance_actual,
            u.baptismal_dates_goal,
            u.baptismal_dates_actual,
            u.baptisms_confirmations_goal,
            u.baptisms_confirmations_actual,
            u.new_member_sacrament_goal,
            u.new_member_sacrament_actual,
            u.follow_up_lessons_actual,
            u.first_time_sacrament_actual,
            u.companionships
           FROM (public.zone_history_weeks u
             JOIN public.data_upload_week_batches w ON (((w.kind = 'ZONE_HISTORY'::text) AND (w.batch_id = u.batch_id) AND (w.mission_id = u.mission_id) AND (w.sunday = u.sunday))))
        ), uploaded AS (
         SELECT u.sunday,
            u.mission_id,
            z.id AS zone_id,
            COALESCE(z.name, u.zone_name) AS zone,
            u.friends_found_actual,
            u.friends_found_goal,
            b.friends_found_goal AS friends_found_previous_goal,
            u.members_at_lessons_actual,
            u.members_at_lessons_goal,
            b.members_at_lessons_goal AS members_at_lessons_previous_goal,
            u.sacrament_attendance_actual,
            u.sacrament_attendance_goal,
            b.sacrament_attendance_goal AS sacrament_attendance_previous_goal,
            u.baptismal_dates_actual,
            u.baptismal_dates_goal,
            b.baptismal_dates_goal AS baptismal_dates_previous_goal,
            u.baptisms_confirmations_actual,
            u.baptisms_confirmations_goal,
            b.baptisms_confirmations_goal AS baptisms_confirmations_previous_goal,
            u.new_member_sacrament_actual,
            u.new_member_sacrament_goal,
            b.new_member_sacrament_goal AS new_member_sacrament_previous_goal,
            u.follow_up_lessons_actual,
            u.first_time_sacrament_actual,
            u.companionships
           FROM ((counted u
             LEFT JOIN public.zones z ON ((z.id = u.zone_id)))
             LEFT JOIN counted b ON (((b.mission_id = u.mission_id) AND (b.sunday = (u.sunday - 7)) AND
                CASE
                    WHEN (u.zone_id IS NULL) THEN ((b.zone_id IS NULL) AND (lower(b.zone_name) = lower(u.zone_name)))
                    ELSE (b.zone_id = u.zone_id)
                END)))
          WHERE (NOT (EXISTS ( SELECT 1
                   FROM portal p
                  WHERE ((p.mission_id = u.mission_id) AND (p.sunday = u.sunday) AND (p.zone_id = u.zone_id)))))
        )
 SELECT x.sunday,
    ((x.sunday + '12:00:00'::time without time zone) AT TIME ZONE 'Europe/Berlin'::text) AS week,
    x.mission_id,
    x.zone_id,
    x.zone,
    x.data_source,
    x.friends_found_actual,
    x.friends_found_goal,
    x.friends_found_previous_goal,
    x.members_at_lessons_actual,
    x.members_at_lessons_goal,
    x.members_at_lessons_previous_goal,
    x.sacrament_attendance_actual,
    x.sacrament_attendance_goal,
    x.sacrament_attendance_previous_goal,
    x.baptismal_dates_actual,
    x.baptismal_dates_goal,
    x.baptismal_dates_previous_goal,
    x.baptisms_confirmations_actual,
    x.baptisms_confirmations_goal,
    x.baptisms_confirmations_previous_goal,
    x.new_member_sacrament_actual,
    x.new_member_sacrament_goal,
    x.new_member_sacrament_previous_goal,
    x.follow_up_lessons_actual,
    x.first_time_sacrament_actual,
    x.companionships
   FROM ( SELECT portal.sunday,
            portal.mission_id,
            portal.zone_id,
            portal.zone,
            portal.friends_found_actual,
            portal.friends_found_goal,
            portal.friends_found_previous_goal,
            portal.members_at_lessons_actual,
            portal.members_at_lessons_goal,
            portal.members_at_lessons_previous_goal,
            portal.sacrament_attendance_actual,
            portal.sacrament_attendance_goal,
            portal.sacrament_attendance_previous_goal,
            portal.baptismal_dates_actual,
            portal.baptismal_dates_goal,
            portal.baptismal_dates_previous_goal,
            portal.baptisms_confirmations_actual,
            portal.baptisms_confirmations_goal,
            portal.baptisms_confirmations_previous_goal,
            portal.new_member_sacrament_actual,
            portal.new_member_sacrament_goal,
            portal.new_member_sacrament_previous_goal,
            portal.follow_up_lessons_actual,
            portal.first_time_sacrament_actual,
            portal.companionships,
            'portal'::text AS data_source
           FROM portal
        UNION ALL
         SELECT uploaded.sunday,
            uploaded.mission_id,
            uploaded.zone_id,
            uploaded.zone,
            uploaded.friends_found_actual,
            uploaded.friends_found_goal,
            uploaded.friends_found_previous_goal,
            uploaded.members_at_lessons_actual,
            uploaded.members_at_lessons_goal,
            uploaded.members_at_lessons_previous_goal,
            uploaded.sacrament_attendance_actual,
            uploaded.sacrament_attendance_goal,
            uploaded.sacrament_attendance_previous_goal,
            uploaded.baptismal_dates_actual,
            uploaded.baptismal_dates_goal,
            uploaded.baptismal_dates_previous_goal,
            uploaded.baptisms_confirmations_actual,
            uploaded.baptisms_confirmations_goal,
            uploaded.baptisms_confirmations_previous_goal,
            uploaded.new_member_sacrament_actual,
            uploaded.new_member_sacrament_goal,
            uploaded.new_member_sacrament_previous_goal,
            uploaded.follow_up_lessons_actual,
            uploaded.first_time_sacrament_actual,
            uploaded.companionships,
            'upload'::text
           FROM uploaded) x;


ALTER TABLE dashboards.zone_history_week OWNER TO postgres;

--
-- Name: mission_history_week; Type: VIEW; Schema: dashboards; Owner: postgres
--

CREATE VIEW dashboards.mission_history_week AS
 SELECT h.sunday,
    min(h.week) AS week,
    h.mission_id,
    string_agg(DISTINCT h.data_source, ', '::text ORDER BY h.data_source) AS data_sources,
    count(*) AS zones,
    (sum(h.friends_found_actual))::bigint AS friends_found_actual,
    (sum(h.friends_found_goal))::bigint AS friends_found_goal,
    (sum(h.friends_found_previous_goal))::bigint AS friends_found_previous_goal,
    (sum(h.members_at_lessons_actual))::bigint AS members_at_lessons_actual,
    (sum(h.members_at_lessons_goal))::bigint AS members_at_lessons_goal,
    (sum(h.members_at_lessons_previous_goal))::bigint AS members_at_lessons_previous_goal,
    (sum(h.sacrament_attendance_actual))::bigint AS sacrament_attendance_actual,
    (sum(h.sacrament_attendance_goal))::bigint AS sacrament_attendance_goal,
    (sum(h.sacrament_attendance_previous_goal))::bigint AS sacrament_attendance_previous_goal,
    (sum(h.baptismal_dates_actual))::bigint AS baptismal_dates_actual,
    (sum(h.baptismal_dates_goal))::bigint AS baptismal_dates_goal,
    (sum(h.baptismal_dates_previous_goal))::bigint AS baptismal_dates_previous_goal,
    (sum(h.baptisms_confirmations_actual))::bigint AS baptisms_confirmations_actual,
    (sum(h.baptisms_confirmations_goal))::bigint AS baptisms_confirmations_goal,
    (sum(h.baptisms_confirmations_previous_goal))::bigint AS baptisms_confirmations_previous_goal,
    (sum(h.new_member_sacrament_actual))::bigint AS new_member_sacrament_actual,
    (sum(h.new_member_sacrament_goal))::bigint AS new_member_sacrament_goal,
    (sum(h.new_member_sacrament_previous_goal))::bigint AS new_member_sacrament_previous_goal,
    (sum(h.follow_up_lessons_actual))::bigint AS follow_up_lessons_actual,
    (sum(h.first_time_sacrament_actual))::bigint AS first_time_sacrament_actual,
    (sum(h.companionships))::bigint AS companionships
   FROM dashboards.zone_history_week h
  GROUP BY h.sunday, h.mission_id;


ALTER TABLE dashboards.mission_history_week OWNER TO postgres;

--
-- Name: reporting_weeks; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.reporting_weeks (
    id bigint NOT NULL,
    sunday date NOT NULL,
    planning_open_at timestamp with time zone,
    planning_due_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.reporting_weeks OWNER TO postgres;

--
-- Name: weekly_area_reports; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.weekly_area_reports (
    id bigint NOT NULL,
    area_id bigint NOT NULL,
    reporting_week_id bigint NOT NULL,
    status text DEFAULT 'DRAFT'::text NOT NULL,
    submitted_by uuid,
    submitted_at timestamp with time zone,
    friends_found_actual integer DEFAULT 0 NOT NULL,
    friends_found_goal integer DEFAULT 0 NOT NULL,
    lessons_with_friends_actual integer DEFAULT 0 NOT NULL,
    lessons_with_friends_goal integer DEFAULT 0 NOT NULL,
    lessons_with_members_actual integer DEFAULT 0 NOT NULL,
    lessons_with_members_goal integer DEFAULT 0 NOT NULL,
    sacrament_attendance_actual integer DEFAULT 0 NOT NULL,
    sacrament_attendance_goal integer DEFAULT 0 NOT NULL,
    first_time_sacrament_actual integer DEFAULT 0 NOT NULL,
    baptismal_dates_actual integer DEFAULT 0 NOT NULL,
    baptismal_dates_goal integer DEFAULT 0 NOT NULL,
    new_member_sacrament_actual integer DEFAULT 0 NOT NULL,
    new_member_sacrament_goal integer DEFAULT 0 NOT NULL,
    follow_up_lessons_actual integer DEFAULT 0 NOT NULL,
    follow_up_lessons_goal integer DEFAULT 0 NOT NULL,
    notes text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    unit_id bigint,
    baptisms_confirmations_actual integer,
    baptisms_confirmations_goal integer,
    historical_source_area text,
    historical_source_key text,
    import_batch_id uuid,
    CONSTRAINT weekly_area_reports_baptismal_dates_actual_check CHECK ((baptismal_dates_actual >= 0)),
    CONSTRAINT weekly_area_reports_baptismal_dates_goal_check CHECK ((baptismal_dates_goal >= 0)),
    CONSTRAINT weekly_area_reports_first_time_sacrament_actual_check CHECK ((first_time_sacrament_actual >= 0)),
    CONSTRAINT weekly_area_reports_follow_up_lessons_actual_check CHECK ((follow_up_lessons_actual >= 0)),
    CONSTRAINT weekly_area_reports_follow_up_lessons_goal_check CHECK ((follow_up_lessons_goal >= 0)),
    CONSTRAINT weekly_area_reports_friends_found_actual_check CHECK ((friends_found_actual >= 0)),
    CONSTRAINT weekly_area_reports_friends_found_goal_check CHECK ((friends_found_goal >= 0)),
    CONSTRAINT weekly_area_reports_lessons_with_friends_actual_check CHECK ((lessons_with_friends_actual >= 0)),
    CONSTRAINT weekly_area_reports_lessons_with_friends_goal_check CHECK ((lessons_with_friends_goal >= 0)),
    CONSTRAINT weekly_area_reports_lessons_with_members_actual_check CHECK ((lessons_with_members_actual >= 0)),
    CONSTRAINT weekly_area_reports_lessons_with_members_goal_check CHECK ((lessons_with_members_goal >= 0)),
    CONSTRAINT weekly_area_reports_new_member_sacrament_actual_check CHECK ((new_member_sacrament_actual >= 0)),
    CONSTRAINT weekly_area_reports_new_member_sacrament_goal_check CHECK ((new_member_sacrament_goal >= 0)),
    CONSTRAINT weekly_area_reports_sacrament_attendance_actual_check CHECK ((sacrament_attendance_actual >= 0)),
    CONSTRAINT weekly_area_reports_sacrament_attendance_goal_check CHECK ((sacrament_attendance_goal >= 0)),
    CONSTRAINT weekly_area_reports_status_check CHECK ((status = ANY (ARRAY['DRAFT'::text, 'SUBMITTED'::text, 'LOCKED'::text])))
);


ALTER TABLE public.weekly_area_reports OWNER TO postgres;

--
-- Name: weekly_baptismal_date_friends; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.weekly_baptismal_date_friends (
    id bigint NOT NULL,
    weekly_area_report_id bigint NOT NULL,
    baptismal_date_person_id bigint,
    display_order integer DEFAULT 0 NOT NULL,
    baptismal_date_set_on date,
    current_baptismal_date date,
    finding_source text,
    reading boolean,
    praying boolean,
    at_church_this_sunday boolean,
    keeping_commandments boolean,
    member_involvement boolean,
    stake_id bigint,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.weekly_baptismal_date_friends OWNER TO postgres;

--
-- Name: weekly_high_potential_friends; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.weekly_high_potential_friends (
    id bigint NOT NULL,
    weekly_area_report_id bigint NOT NULL,
    display_order integer DEFAULT 0 NOT NULL,
    name text NOT NULL,
    at_church_this_sunday boolean,
    notes text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.weekly_high_potential_friends OWNER TO postgres;

--
-- Name: people_area_week_counts; Type: VIEW; Schema: dashboards; Owner: postgres
--

CREATE VIEW dashboards.people_area_week_counts AS
 WITH cells AS (
         SELECT DISTINCT r.reporting_week_id,
            r.area_id
           FROM public.weekly_area_reports r
        ), nm AS (
         SELECT r.reporting_week_id,
            r.area_id,
            count(*) AS new_members,
            count(*) FILTER (WHERE n.at_church_this_sunday) AS new_members_at_church,
            count(*) FILTER (WHERE (n.has_active_temple_recommend = 'yes'::text)) AS new_members_temple_recommend,
            count(*) FILTER (WHERE (n.has_calling = 'yes'::text)) AS new_members_calling,
            count(*) FILTER (WHERE (n.has_aaronic_priesthood = 'yes'::text)) AS new_members_aaronic_priesthood,
            count(*) FILTER (WHERE (n.has_melchizedek_priesthood = 'yes'::text)) AS new_members_melchizedek_priesthood,
            count(*) FILTER (WHERE (n.ministers_to_someone = 'yes'::text)) AS new_members_ministering,
            count(*) FILTER (WHERE n.ministered_to_by_someone) AS new_members_with_minister,
            count(*) FILTER (WHERE (n.visited_temple_for_baptisms = 'yes'::text)) AS new_members_visited_temple,
            count(*) FILTER (WHERE n.reading) AS new_members_reading,
            count(*) FILTER (WHERE n.praying) AS new_members_praying,
            count(*) FILTER (WHERE n.member_involvement) AS new_members_member_involvement,
            count(*) FILTER (WHERE n.discussed_in_gemiko) AS new_members_discussed_in_gemiko
           FROM (public.weekly_new_members n
             JOIN public.weekly_area_reports r ON ((r.id = n.weekly_area_report_id)))
          GROUP BY r.reporting_week_id, r.area_id
        ), bd AS (
         SELECT r.reporting_week_id,
            r.area_id,
            count(*) AS baptismal_date_friends,
            count(*) FILTER (WHERE ((f.current_baptismal_date >= w_1.sunday) AND (f.current_baptismal_date <= (w_1.sunday + 28)))) AS baptismal_date_friends_next_4_weeks,
            count(*) FILTER (WHERE f.at_church_this_sunday) AS baptismal_date_friends_at_church,
            count(*) FILTER (WHERE f.reading) AS baptismal_date_friends_reading,
            count(*) FILTER (WHERE f.praying) AS baptismal_date_friends_praying,
            count(*) FILTER (WHERE f.keeping_commandments) AS baptismal_date_friends_keeping_commandments,
            count(*) FILTER (WHERE f.member_involvement) AS baptismal_date_friends_member_involvement
           FROM ((public.weekly_baptismal_date_friends f
             JOIN public.weekly_area_reports r ON ((r.id = f.weekly_area_report_id)))
             JOIN public.reporting_weeks w_1 ON ((w_1.id = r.reporting_week_id)))
          GROUP BY r.reporting_week_id, r.area_id
        ), hp AS (
         SELECT r.reporting_week_id,
            r.area_id,
            count(*) AS high_potentials,
            count(*) FILTER (WHERE h.at_church_this_sunday) AS high_potentials_at_church
           FROM (public.weekly_high_potential_friends h
             JOIN public.weekly_area_reports r ON ((r.id = h.weekly_area_report_id)))
          GROUP BY r.reporting_week_id, r.area_id
        )
 SELECT ((w.sunday + '12:00:00'::time without time zone) AT TIME ZONE 'Europe/Berlin'::text) AS week,
    w.sunday,
    w.id AS reporting_week_id,
    z.mission_id,
    z.id AS zone_id,
    z.name AS zone,
    d.id AS district_id,
    d.name AS district,
    a.id AS area_id,
    a.name AS area,
    COALESCE(nm.new_members, (0)::bigint) AS new_members,
    COALESCE(nm.new_members_at_church, (0)::bigint) AS new_members_at_church,
    COALESCE(nm.new_members_temple_recommend, (0)::bigint) AS new_members_temple_recommend,
    COALESCE(nm.new_members_calling, (0)::bigint) AS new_members_calling,
    COALESCE(nm.new_members_aaronic_priesthood, (0)::bigint) AS new_members_aaronic_priesthood,
    COALESCE(nm.new_members_melchizedek_priesthood, (0)::bigint) AS new_members_melchizedek_priesthood,
    COALESCE(nm.new_members_ministering, (0)::bigint) AS new_members_ministering,
    COALESCE(nm.new_members_with_minister, (0)::bigint) AS new_members_with_minister,
    COALESCE(nm.new_members_visited_temple, (0)::bigint) AS new_members_visited_temple,
    COALESCE(nm.new_members_reading, (0)::bigint) AS new_members_reading,
    COALESCE(nm.new_members_praying, (0)::bigint) AS new_members_praying,
    COALESCE(nm.new_members_member_involvement, (0)::bigint) AS new_members_member_involvement,
    COALESCE(nm.new_members_discussed_in_gemiko, (0)::bigint) AS new_members_discussed_in_gemiko,
    COALESCE(bd.baptismal_date_friends, (0)::bigint) AS baptismal_date_friends,
    COALESCE(bd.baptismal_date_friends_next_4_weeks, (0)::bigint) AS baptismal_date_friends_next_4_weeks,
    COALESCE(bd.baptismal_date_friends_at_church, (0)::bigint) AS baptismal_date_friends_at_church,
    COALESCE(bd.baptismal_date_friends_reading, (0)::bigint) AS baptismal_date_friends_reading,
    COALESCE(bd.baptismal_date_friends_praying, (0)::bigint) AS baptismal_date_friends_praying,
    COALESCE(bd.baptismal_date_friends_keeping_commandments, (0)::bigint) AS baptismal_date_friends_keeping_commandments,
    COALESCE(bd.baptismal_date_friends_member_involvement, (0)::bigint) AS baptismal_date_friends_member_involvement,
    COALESCE(hp.high_potentials, (0)::bigint) AS high_potentials,
    COALESCE(hp.high_potentials_at_church, (0)::bigint) AS high_potentials_at_church
   FROM (((((((cells c
     JOIN public.reporting_weeks w ON ((w.id = c.reporting_week_id)))
     JOIN public.areas a ON ((a.id = c.area_id)))
     JOIN public.districts d ON ((d.id = a.district_id)))
     JOIN public.zones z ON ((z.id = d.zone_id)))
     LEFT JOIN nm ON (((nm.reporting_week_id = c.reporting_week_id) AND (nm.area_id = c.area_id))))
     LEFT JOIN bd ON (((bd.reporting_week_id = c.reporting_week_id) AND (bd.area_id = c.area_id))))
     LEFT JOIN hp ON (((hp.reporting_week_id = c.reporting_week_id) AND (hp.area_id = c.area_id))));


ALTER TABLE dashboards.people_area_week_counts OWNER TO postgres;

--
-- Name: people_area_week; Type: VIEW; Schema: dashboards; Owner: postgres
--

CREATE VIEW dashboards.people_area_week AS
 SELECT c.week,
    c.sunday,
    c.reporting_week_id,
    c.mission_id,
    c.zone_id,
    c.zone,
    c.district_id,
    c.district,
    c.area_id,
    c.area,
    (1)::bigint AS areas_reporting,
        CASE
            WHEN (c.new_members >= 3) THEN c.new_members
            ELSE NULL::bigint
        END AS new_members,
        CASE
            WHEN ((c.new_members_at_church >= 3) AND ((c.new_members - c.new_members_at_church) >= 3)) THEN c.new_members_at_church
            ELSE NULL::bigint
        END AS new_members_at_church,
        CASE
            WHEN ((c.new_members_temple_recommend >= 3) AND ((c.new_members - c.new_members_temple_recommend) >= 3)) THEN c.new_members_temple_recommend
            ELSE NULL::bigint
        END AS new_members_temple_recommend,
        CASE
            WHEN ((c.new_members_calling >= 3) AND ((c.new_members - c.new_members_calling) >= 3)) THEN c.new_members_calling
            ELSE NULL::bigint
        END AS new_members_calling,
        CASE
            WHEN ((c.new_members_aaronic_priesthood >= 3) AND ((c.new_members - c.new_members_aaronic_priesthood) >= 3)) THEN c.new_members_aaronic_priesthood
            ELSE NULL::bigint
        END AS new_members_aaronic_priesthood,
        CASE
            WHEN ((c.new_members_melchizedek_priesthood >= 3) AND ((c.new_members - c.new_members_melchizedek_priesthood) >= 3)) THEN c.new_members_melchizedek_priesthood
            ELSE NULL::bigint
        END AS new_members_melchizedek_priesthood,
        CASE
            WHEN ((c.new_members_ministering >= 3) AND ((c.new_members - c.new_members_ministering) >= 3)) THEN c.new_members_ministering
            ELSE NULL::bigint
        END AS new_members_ministering,
        CASE
            WHEN ((c.new_members_with_minister >= 3) AND ((c.new_members - c.new_members_with_minister) >= 3)) THEN c.new_members_with_minister
            ELSE NULL::bigint
        END AS new_members_with_minister,
        CASE
            WHEN ((c.new_members_visited_temple >= 3) AND ((c.new_members - c.new_members_visited_temple) >= 3)) THEN c.new_members_visited_temple
            ELSE NULL::bigint
        END AS new_members_visited_temple,
        CASE
            WHEN ((c.new_members_reading >= 3) AND ((c.new_members - c.new_members_reading) >= 3)) THEN c.new_members_reading
            ELSE NULL::bigint
        END AS new_members_reading,
        CASE
            WHEN ((c.new_members_praying >= 3) AND ((c.new_members - c.new_members_praying) >= 3)) THEN c.new_members_praying
            ELSE NULL::bigint
        END AS new_members_praying,
        CASE
            WHEN ((c.new_members_member_involvement >= 3) AND ((c.new_members - c.new_members_member_involvement) >= 3)) THEN c.new_members_member_involvement
            ELSE NULL::bigint
        END AS new_members_member_involvement,
        CASE
            WHEN ((c.new_members_discussed_in_gemiko >= 3) AND ((c.new_members - c.new_members_discussed_in_gemiko) >= 3)) THEN c.new_members_discussed_in_gemiko
            ELSE NULL::bigint
        END AS new_members_discussed_in_gemiko,
        CASE
            WHEN (c.baptismal_date_friends >= 3) THEN c.baptismal_date_friends
            ELSE NULL::bigint
        END AS baptismal_date_friends,
        CASE
            WHEN ((c.baptismal_date_friends_next_4_weeks >= 3) AND ((c.baptismal_date_friends - c.baptismal_date_friends_next_4_weeks) >= 3)) THEN c.baptismal_date_friends_next_4_weeks
            ELSE NULL::bigint
        END AS baptismal_date_friends_next_4_weeks,
        CASE
            WHEN ((c.baptismal_date_friends_at_church >= 3) AND ((c.baptismal_date_friends - c.baptismal_date_friends_at_church) >= 3)) THEN c.baptismal_date_friends_at_church
            ELSE NULL::bigint
        END AS baptismal_date_friends_at_church,
        CASE
            WHEN ((c.baptismal_date_friends_reading >= 3) AND ((c.baptismal_date_friends - c.baptismal_date_friends_reading) >= 3)) THEN c.baptismal_date_friends_reading
            ELSE NULL::bigint
        END AS baptismal_date_friends_reading,
        CASE
            WHEN ((c.baptismal_date_friends_praying >= 3) AND ((c.baptismal_date_friends - c.baptismal_date_friends_praying) >= 3)) THEN c.baptismal_date_friends_praying
            ELSE NULL::bigint
        END AS baptismal_date_friends_praying,
        CASE
            WHEN ((c.baptismal_date_friends_keeping_commandments >= 3) AND ((c.baptismal_date_friends - c.baptismal_date_friends_keeping_commandments) >= 3)) THEN c.baptismal_date_friends_keeping_commandments
            ELSE NULL::bigint
        END AS baptismal_date_friends_keeping_commandments,
        CASE
            WHEN ((c.baptismal_date_friends_member_involvement >= 3) AND ((c.baptismal_date_friends - c.baptismal_date_friends_member_involvement) >= 3)) THEN c.baptismal_date_friends_member_involvement
            ELSE NULL::bigint
        END AS baptismal_date_friends_member_involvement,
        CASE
            WHEN (c.high_potentials >= 3) THEN c.high_potentials
            ELSE NULL::bigint
        END AS high_potentials,
        CASE
            WHEN ((c.high_potentials_at_church >= 3) AND ((c.high_potentials - c.high_potentials_at_church) >= 3)) THEN c.high_potentials_at_church
            ELSE NULL::bigint
        END AS high_potentials_at_church
   FROM dashboards.people_area_week_counts c;


ALTER TABLE dashboards.people_area_week OWNER TO postgres;

--
-- Name: people_district_week; Type: VIEW; Schema: dashboards; Owner: postgres
--

CREATE VIEW dashboards.people_district_week AS
 SELECT c.week,
    c.sunday,
    c.reporting_week_id,
    c.mission_id,
    c.zone_id,
    c.zone,
    c.district_id,
    c.district,
    count(*) AS areas_reporting,
    (sum(c.new_members))::bigint AS new_members,
    (sum(c.new_members_at_church))::bigint AS new_members_at_church,
    (sum(c.new_members_temple_recommend))::bigint AS new_members_temple_recommend,
    (sum(c.new_members_calling))::bigint AS new_members_calling,
    (sum(c.new_members_aaronic_priesthood))::bigint AS new_members_aaronic_priesthood,
    (sum(c.new_members_melchizedek_priesthood))::bigint AS new_members_melchizedek_priesthood,
    (sum(c.new_members_ministering))::bigint AS new_members_ministering,
    (sum(c.new_members_with_minister))::bigint AS new_members_with_minister,
    (sum(c.new_members_visited_temple))::bigint AS new_members_visited_temple,
    (sum(c.new_members_reading))::bigint AS new_members_reading,
    (sum(c.new_members_praying))::bigint AS new_members_praying,
    (sum(c.new_members_member_involvement))::bigint AS new_members_member_involvement,
    (sum(c.new_members_discussed_in_gemiko))::bigint AS new_members_discussed_in_gemiko,
    (sum(c.baptismal_date_friends))::bigint AS baptismal_date_friends,
    (sum(c.baptismal_date_friends_next_4_weeks))::bigint AS baptismal_date_friends_next_4_weeks,
    (sum(c.baptismal_date_friends_at_church))::bigint AS baptismal_date_friends_at_church,
    (sum(c.baptismal_date_friends_reading))::bigint AS baptismal_date_friends_reading,
    (sum(c.baptismal_date_friends_praying))::bigint AS baptismal_date_friends_praying,
    (sum(c.baptismal_date_friends_keeping_commandments))::bigint AS baptismal_date_friends_keeping_commandments,
    (sum(c.baptismal_date_friends_member_involvement))::bigint AS baptismal_date_friends_member_involvement,
    (sum(c.high_potentials))::bigint AS high_potentials,
    (sum(c.high_potentials_at_church))::bigint AS high_potentials_at_church
   FROM dashboards.people_area_week_counts c
  GROUP BY c.week, c.sunday, c.reporting_week_id, c.mission_id, c.zone_id, c.zone, c.district_id, c.district;


ALTER TABLE dashboards.people_district_week OWNER TO postgres;

--
-- Name: people_mission_week; Type: VIEW; Schema: dashboards; Owner: postgres
--

CREATE VIEW dashboards.people_mission_week AS
 SELECT c.week,
    c.sunday,
    c.reporting_week_id,
    c.mission_id,
    count(*) AS areas_reporting,
    (sum(c.new_members))::bigint AS new_members,
    (sum(c.new_members_at_church))::bigint AS new_members_at_church,
    (sum(c.new_members_temple_recommend))::bigint AS new_members_temple_recommend,
    (sum(c.new_members_calling))::bigint AS new_members_calling,
    (sum(c.new_members_aaronic_priesthood))::bigint AS new_members_aaronic_priesthood,
    (sum(c.new_members_melchizedek_priesthood))::bigint AS new_members_melchizedek_priesthood,
    (sum(c.new_members_ministering))::bigint AS new_members_ministering,
    (sum(c.new_members_with_minister))::bigint AS new_members_with_minister,
    (sum(c.new_members_visited_temple))::bigint AS new_members_visited_temple,
    (sum(c.new_members_reading))::bigint AS new_members_reading,
    (sum(c.new_members_praying))::bigint AS new_members_praying,
    (sum(c.new_members_member_involvement))::bigint AS new_members_member_involvement,
    (sum(c.new_members_discussed_in_gemiko))::bigint AS new_members_discussed_in_gemiko,
    (sum(c.baptismal_date_friends))::bigint AS baptismal_date_friends,
    (sum(c.baptismal_date_friends_next_4_weeks))::bigint AS baptismal_date_friends_next_4_weeks,
    (sum(c.baptismal_date_friends_at_church))::bigint AS baptismal_date_friends_at_church,
    (sum(c.baptismal_date_friends_reading))::bigint AS baptismal_date_friends_reading,
    (sum(c.baptismal_date_friends_praying))::bigint AS baptismal_date_friends_praying,
    (sum(c.baptismal_date_friends_keeping_commandments))::bigint AS baptismal_date_friends_keeping_commandments,
    (sum(c.baptismal_date_friends_member_involvement))::bigint AS baptismal_date_friends_member_involvement,
    (sum(c.high_potentials))::bigint AS high_potentials,
    (sum(c.high_potentials_at_church))::bigint AS high_potentials_at_church
   FROM dashboards.people_area_week_counts c
  GROUP BY c.week, c.sunday, c.reporting_week_id, c.mission_id;


ALTER TABLE dashboards.people_mission_week OWNER TO postgres;

--
-- Name: people_zone_week; Type: VIEW; Schema: dashboards; Owner: postgres
--

CREATE VIEW dashboards.people_zone_week AS
 SELECT c.week,
    c.sunday,
    c.reporting_week_id,
    c.mission_id,
    c.zone_id,
    c.zone,
    count(*) AS areas_reporting,
    (sum(c.new_members))::bigint AS new_members,
    (sum(c.new_members_at_church))::bigint AS new_members_at_church,
    (sum(c.new_members_temple_recommend))::bigint AS new_members_temple_recommend,
    (sum(c.new_members_calling))::bigint AS new_members_calling,
    (sum(c.new_members_aaronic_priesthood))::bigint AS new_members_aaronic_priesthood,
    (sum(c.new_members_melchizedek_priesthood))::bigint AS new_members_melchizedek_priesthood,
    (sum(c.new_members_ministering))::bigint AS new_members_ministering,
    (sum(c.new_members_with_minister))::bigint AS new_members_with_minister,
    (sum(c.new_members_visited_temple))::bigint AS new_members_visited_temple,
    (sum(c.new_members_reading))::bigint AS new_members_reading,
    (sum(c.new_members_praying))::bigint AS new_members_praying,
    (sum(c.new_members_member_involvement))::bigint AS new_members_member_involvement,
    (sum(c.new_members_discussed_in_gemiko))::bigint AS new_members_discussed_in_gemiko,
    (sum(c.baptismal_date_friends))::bigint AS baptismal_date_friends,
    (sum(c.baptismal_date_friends_next_4_weeks))::bigint AS baptismal_date_friends_next_4_weeks,
    (sum(c.baptismal_date_friends_at_church))::bigint AS baptismal_date_friends_at_church,
    (sum(c.baptismal_date_friends_reading))::bigint AS baptismal_date_friends_reading,
    (sum(c.baptismal_date_friends_praying))::bigint AS baptismal_date_friends_praying,
    (sum(c.baptismal_date_friends_keeping_commandments))::bigint AS baptismal_date_friends_keeping_commandments,
    (sum(c.baptismal_date_friends_member_involvement))::bigint AS baptismal_date_friends_member_involvement,
    (sum(c.high_potentials))::bigint AS high_potentials,
    (sum(c.high_potentials_at_church))::bigint AS high_potentials_at_church
   FROM dashboards.people_area_week_counts c
  GROUP BY c.week, c.sunday, c.reporting_week_id, c.mission_id, c.zone_id, c.zone;


ALTER TABLE dashboards.people_zone_week OWNER TO postgres;

--
-- Name: activity; Type: TABLE; Schema: portal; Owner: postgres
--

CREATE TABLE portal.activity (
    user_id uuid NOT NULL,
    area_id bigint,
    last_activity timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE portal.activity OWNER TO postgres;

--
-- Name: announcement_reads; Type: TABLE; Schema: portal; Owner: postgres
--

CREATE TABLE portal.announcement_reads (
    announcement_id uuid NOT NULL,
    user_id uuid NOT NULL,
    read_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE portal.announcement_reads OWNER TO postgres;

--
-- Name: announcements; Type: TABLE; Schema: portal; Owner: postgres
--

CREATE TABLE portal.announcements (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    mission_id bigint NOT NULL,
    author_id uuid NOT NULL,
    title text NOT NULL,
    body text NOT NULL,
    roles text[] DEFAULT '{}'::text[] NOT NULL,
    zone_ids bigint[] DEFAULT '{}'::bigint[] NOT NULL,
    district_ids bigint[] DEFAULT '{}'::bigint[] NOT NULL,
    area_ids bigint[] DEFAULT '{}'::bigint[] NOT NULL,
    user_ids uuid[] DEFAULT '{}'::uuid[] NOT NULL,
    pinned boolean DEFAULT false NOT NULL,
    urgent boolean DEFAULT false NOT NULL,
    expires_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT announcements_title_check CHECK (((length(title) >= 1) AND (length(title) <= 180)))
);


ALTER TABLE portal.announcements OWNER TO postgres;

--
-- Name: attachments; Type: TABLE; Schema: portal; Owner: postgres
--

CREATE TABLE portal.attachments (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    mission_id bigint NOT NULL,
    uploader_id uuid NOT NULL,
    event_id uuid,
    announcement_id uuid,
    filename text NOT NULL,
    storage_name text NOT NULL,
    mime_type text NOT NULL,
    bytes bigint NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT attachments_check CHECK (((event_id IS NULL) <> (announcement_id IS NULL)))
);


ALTER TABLE portal.attachments OWNER TO postgres;

--
-- Name: attendance; Type: TABLE; Schema: portal; Owner: postgres
--

CREATE TABLE portal.attendance (
    event_id uuid NOT NULL,
    occurrence timestamp with time zone NOT NULL,
    user_id uuid NOT NULL,
    attended boolean NOT NULL,
    recorded_by uuid,
    recorded_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE portal.attendance OWNER TO postgres;

--
-- Name: events; Type: TABLE; Schema: portal; Owner: postgres
--

CREATE TABLE portal.events (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    mission_id bigint NOT NULL,
    author_id uuid NOT NULL,
    title text NOT NULL,
    description text DEFAULT ''::text NOT NULL,
    starts_at timestamp with time zone NOT NULL,
    ends_at timestamp with time zone NOT NULL,
    timezone text DEFAULT 'Europe/Berlin'::text NOT NULL,
    recurrence jsonb,
    roles text[] DEFAULT '{}'::text[] NOT NULL,
    zone_ids bigint[] DEFAULT '{}'::bigint[] NOT NULL,
    location text DEFAULT ''::text NOT NULL,
    meeting_url text DEFAULT ''::text NOT NULL,
    reminder_minutes integer DEFAULT 30 NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    skipped_dates date[] DEFAULT '{}'::date[] NOT NULL,
    CONSTRAINT events_check CHECK ((ends_at > starts_at)),
    CONSTRAINT events_reminder_minutes_check CHECK (((reminder_minutes >= 0) AND (reminder_minutes <= 10080))),
    CONSTRAINT events_title_check CHECK (((length(title) >= 1) AND (length(title) <= 180)))
);


ALTER TABLE portal.events OWNER TO postgres;

--
-- Name: mission_focus; Type: TABLE; Schema: portal; Owner: postgres
--

CREATE TABLE portal.mission_focus (
    mission_id bigint NOT NULL,
    reporting_sunday date NOT NULL,
    translations jsonb DEFAULT '{}'::jsonb NOT NULL,
    updated_by uuid,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT mission_focus_translations_check CHECK ((jsonb_typeof(translations) = 'object'::text))
);


ALTER TABLE portal.mission_focus OWNER TO postgres;

--
-- Name: presentation_access; Type: TABLE; Schema: portal; Owner: postgres
--

CREATE TABLE portal.presentation_access (
    deck_slug text NOT NULL,
    mission_id bigint NOT NULL,
    roles text[] DEFAULT '{}'::text[] NOT NULL,
    zone_ids bigint[] DEFAULT '{}'::bigint[] NOT NULL,
    district_ids bigint[] DEFAULT '{}'::bigint[] NOT NULL,
    user_ids uuid[] DEFAULT '{}'::uuid[] NOT NULL,
    everyone boolean DEFAULT false NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    created_by uuid,
    updated_by uuid,
    owner_zone_id bigint,
    CONSTRAINT presentation_access_deck_slug_check CHECK ((deck_slug ~ '^[a-z0-9]+(-[a-z0-9]+)*$'::text)),
    CONSTRAINT presentation_access_viewer_roles CHECK ((roles <@ ARRAY['DL'::text, 'ZL'::text, 'STL'::text]))
);


ALTER TABLE portal.presentation_access OWNER TO postgres;

--
-- Name: push_subscriptions; Type: TABLE; Schema: portal; Owner: postgres
--

CREATE TABLE portal.push_subscriptions (
    id bigint NOT NULL,
    user_id uuid NOT NULL,
    endpoint text NOT NULL,
    keys jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE portal.push_subscriptions OWNER TO postgres;

--
-- Name: push_subscriptions_id_seq; Type: SEQUENCE; Schema: portal; Owner: postgres
--

CREATE SEQUENCE portal.push_subscriptions_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER TABLE portal.push_subscriptions_id_seq OWNER TO postgres;

--
-- Name: push_subscriptions_id_seq; Type: SEQUENCE OWNED BY; Schema: portal; Owner: postgres
--

ALTER SEQUENCE portal.push_subscriptions_id_seq OWNED BY portal.push_subscriptions.id;


--
-- Name: reminder_deliveries; Type: TABLE; Schema: portal; Owner: postgres
--

CREATE TABLE portal.reminder_deliveries (
    user_id uuid NOT NULL,
    kind text NOT NULL,
    reference text NOT NULL,
    sent_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE portal.reminder_deliveries OWNER TO postgres;

--
-- Name: user_preferences; Type: TABLE; Schema: portal; Owner: postgres
--

CREATE TABLE portal.user_preferences (
    user_id uuid NOT NULL,
    language text NOT NULL
);


ALTER TABLE portal.user_preferences OWNER TO postgres;

--
-- Name: whiteboard_files; Type: TABLE; Schema: portal; Owner: postgres
--

CREATE TABLE portal.whiteboard_files (
    board_id uuid NOT NULL,
    file_id text NOT NULL,
    mime_type text NOT NULL,
    bytes integer NOT NULL,
    data bytea NOT NULL,
    created_by uuid,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT whiteboard_files_id CHECK ((file_id ~ '^[A-Za-z0-9_-]{1,100}$'::text)),
    CONSTRAINT whiteboard_files_size CHECK (((bytes = octet_length(data)) AND ((bytes >= 1) AND (bytes <= ((2 * 1024) * 1024))))),
    CONSTRAINT whiteboard_files_type CHECK ((mime_type = ANY (ARRAY['image/png'::text, 'image/jpeg'::text, 'image/gif'::text, 'image/webp'::text, 'image/svg+xml'::text])))
);


ALTER TABLE portal.whiteboard_files OWNER TO postgres;

--
-- Name: whiteboards; Type: TABLE; Schema: portal; Owner: postgres
--

CREATE TABLE portal.whiteboards (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    mission_id bigint NOT NULL,
    name text NOT NULL,
    scene jsonb DEFAULT '{"v": 1, "type": "gfm-whiteboard", "style": "hand", "appState": {}, "elements": []}'::jsonb NOT NULL,
    version integer DEFAULT 1 NOT NULL,
    created_by uuid,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_by uuid,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT whiteboards_name_length CHECK ((((char_length(btrim(name)) >= 1) AND (char_length(btrim(name)) <= 80)) AND (name = btrim(name)))),
    CONSTRAINT whiteboards_scene_object CHECK (((jsonb_typeof(scene) = 'object'::text) AND (jsonb_typeof((scene -> 'elements'::text)) = 'array'::text))),
    CONSTRAINT whiteboards_scene_size CHECK ((octet_length((scene)::text) <= ((3 * 1024) * 1024))),
    CONSTRAINT whiteboards_version_positive CHECK ((version >= 1))
);


ALTER TABLE portal.whiteboards OWNER TO postgres;

--
-- Name: planning_question_sections; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.planning_question_sections (
    id bigint NOT NULL,
    section_key text NOT NULL,
    section_title text NOT NULL,
    description text,
    display_order integer DEFAULT 0 NOT NULL,
    active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT planning_question_sections_key_format CHECK ((section_key ~ '^[a-z][a-z0-9_]{2,62}$'::text))
);


ALTER TABLE public.planning_question_sections OWNER TO postgres;

--
-- Name: planning_questions; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.planning_questions (
    id bigint NOT NULL,
    section_id bigint NOT NULL,
    question_key text NOT NULL,
    question_label text NOT NULL,
    help_text text,
    question_type text NOT NULL,
    required boolean DEFAULT false NOT NULL,
    display_order integer DEFAULT 0 NOT NULL,
    active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    min_value numeric,
    max_value numeric,
    integer_only boolean DEFAULT true NOT NULL,
    placeholder text,
    value_when_hidden text,
    protected boolean DEFAULT false NOT NULL,
    CONSTRAINT planning_questions_key_format CHECK ((question_key ~ '^[a-z][a-z0-9_]{2,62}$'::text)),
    CONSTRAINT planning_questions_limits_order CHECK (((min_value IS NULL) OR (max_value IS NULL) OR (min_value <= max_value))),
    CONSTRAINT planning_questions_question_type_check CHECK ((question_type = ANY (ARRAY['TEXT'::text, 'LONG_TEXT'::text, 'NUMBER'::text, 'BOOLEAN'::text, 'DATE'::text, 'SELECT'::text, 'RADIO'::text, 'CHECKBOX'::text, 'GRID'::text]))),
    CONSTRAINT planning_questions_whole_limits CHECK (((NOT integer_only) OR (((min_value IS NULL) OR (min_value = trunc(min_value))) AND ((max_value IS NULL) OR (max_value = trunc(max_value))))))
);


ALTER TABLE public.planning_questions OWNER TO postgres;

--
-- Name: active_planning_questions; Type: VIEW; Schema: public; Owner: postgres
--

CREATE VIEW public.active_planning_questions WITH (security_invoker='true') AS
 SELECT s.id AS section_id,
    s.section_key,
    s.section_title,
    s.description AS section_description,
    s.display_order AS section_order,
    q.id AS question_id,
    q.question_key,
    q.question_label,
    q.help_text,
    q.question_type,
    q.required,
    q.display_order AS question_order
   FROM (public.planning_question_sections s
     JOIN public.planning_questions q ON ((q.section_id = s.id)))
  WHERE ((s.active = true) AND (q.active = true))
  ORDER BY s.display_order, q.display_order, q.id;


ALTER TABLE public.active_planning_questions OWNER TO postgres;

--
-- Name: archetype_notes; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.archetype_notes (
    id bigint NOT NULL,
    area_id bigint NOT NULL,
    sunday date NOT NULL,
    author_id uuid NOT NULL,
    author_name text,
    author_role text,
    body text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT archetype_notes_author_name_check CHECK ((length(author_name) <= 200)),
    CONSTRAINT archetype_notes_author_role_check CHECK ((length(author_role) <= 60)),
    CONSTRAINT archetype_notes_body_check CHECK (((length(btrim(body)) >= 1) AND (length(btrim(body)) <= 4000))),
    CONSTRAINT archetype_notes_sunday_check CHECK ((EXTRACT(isodow FROM sunday) = (7)::numeric))
);


ALTER TABLE public.archetype_notes OWNER TO postgres;

--
-- Name: archetype_notes_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

ALTER TABLE public.archetype_notes ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.archetype_notes_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: archetype_settings; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.archetype_settings (
    mission_id bigint NOT NULL,
    settings jsonb NOT NULL,
    version integer DEFAULT 1 NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_by uuid,
    updated_by_name text,
    CONSTRAINT archetype_settings_settings_check CHECK ((jsonb_typeof(settings) = 'object'::text)),
    CONSTRAINT archetype_settings_updated_by_name_check CHECK ((length(updated_by_name) <= 200)),
    CONSTRAINT archetype_settings_version_check CHECK ((version >= 1))
);


ALTER TABLE public.archetype_settings OWNER TO postgres;

--
-- Name: archetype_settings_history; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.archetype_settings_history (
    id bigint NOT NULL,
    mission_id bigint NOT NULL,
    version integer NOT NULL,
    action text NOT NULL,
    summary text DEFAULT ''::text NOT NULL,
    settings jsonb NOT NULL,
    changed_at timestamp with time zone DEFAULT now() NOT NULL,
    changed_by uuid,
    changed_by_name text,
    CONSTRAINT archetype_settings_history_action_check CHECK ((action = ANY (ARRAY['save'::text, 'restore_defaults'::text]))),
    CONSTRAINT archetype_settings_history_changed_by_name_check CHECK ((length(changed_by_name) <= 200)),
    CONSTRAINT archetype_settings_history_settings_check CHECK ((jsonb_typeof(settings) = 'object'::text)),
    CONSTRAINT archetype_settings_history_summary_check CHECK ((length(summary) <= 4000))
);


ALTER TABLE public.archetype_settings_history OWNER TO postgres;

--
-- Name: archetype_settings_history_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

ALTER TABLE public.archetype_settings_history ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.archetype_settings_history_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: missions; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.missions (
    id bigint NOT NULL,
    name text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.missions OWNER TO postgres;

--
-- Name: area_reporting_status; Type: VIEW; Schema: public; Owner: postgres
--

CREATE VIEW public.area_reporting_status WITH (security_invoker='true') AS
 SELECT a.id AS area_id,
    a.name AS area_name,
    d.id AS district_id,
    d.name AS district_name,
    z.id AS zone_id,
    z.name AS zone_name,
    m.id AS mission_id,
    m.name AS mission_name,
    rw.id AS reporting_week_id,
    rw.sunday,
    war.id AS weekly_area_report_id,
        CASE
            WHEN (war.status = ANY (ARRAY['SUBMITTED'::text, 'LOCKED'::text])) THEN true
            ELSE false
        END AS submitted,
    war.status,
    war.submitted_at,
    war.submitted_by
   FROM (((((public.areas a
     JOIN public.districts d ON ((d.id = a.district_id)))
     JOIN public.zones z ON ((z.id = d.zone_id)))
     JOIN public.missions m ON ((m.id = z.mission_id)))
     CROSS JOIN public.reporting_weeks rw)
     LEFT JOIN public.weekly_area_reports war ON (((war.area_id = a.id) AND (war.reporting_week_id = rw.id))))
  WHERE ((a.active = true) AND (d.active = true) AND (z.active = true) AND public.can_access_area(a.id));


ALTER TABLE public.area_reporting_status OWNER TO postgres;

--
-- Name: area_units; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.area_units (
    id bigint NOT NULL,
    area_id bigint NOT NULL,
    unit_id bigint NOT NULL,
    primary_unit boolean DEFAULT false NOT NULL,
    active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.area_units OWNER TO postgres;

--
-- Name: area_units_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

ALTER TABLE public.area_units ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.area_units_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: areas_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

ALTER TABLE public.areas ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.areas_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: baptismal_date_people_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.baptismal_date_people_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER TABLE public.baptismal_date_people_id_seq OWNER TO postgres;

--
-- Name: baptismal_date_people_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.baptismal_date_people_id_seq OWNED BY public.baptismal_date_people.id;


--
-- Name: baptismal_date_person_area_assignments; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.baptismal_date_person_area_assignments (
    id bigint NOT NULL,
    baptismal_date_person_id bigint NOT NULL,
    area_id bigint NOT NULL,
    start_date date DEFAULT CURRENT_DATE NOT NULL,
    end_date date,
    transfer_reason text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    unit_id bigint,
    CONSTRAINT friend_area_assignment_dates_check CHECK (((end_date IS NULL) OR (end_date >= start_date)))
);


ALTER TABLE public.baptismal_date_person_area_assignments OWNER TO postgres;

--
-- Name: baptismal_date_person_area_assignments_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.baptismal_date_person_area_assignments_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER TABLE public.baptismal_date_person_area_assignments_id_seq OWNER TO postgres;

--
-- Name: baptismal_date_person_area_assignments_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.baptismal_date_person_area_assignments_id_seq OWNED BY public.baptismal_date_person_area_assignments.id;


--
-- Name: call_in_area_updates; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.call_in_area_updates (
    id bigint NOT NULL,
    district_call_in_id bigint NOT NULL,
    area_id bigint NOT NULL,
    update_text text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.call_in_area_updates OWNER TO postgres;

--
-- Name: call_in_area_updates_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

ALTER TABLE public.call_in_area_updates ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.call_in_area_updates_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: call_in_districts; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.call_in_districts (
    id bigint NOT NULL,
    district_id bigint NOT NULL,
    reporting_week_id bigint NOT NULL,
    dl_notes text,
    thank_you text,
    zl_notes text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    dl_completed_at timestamp with time zone,
    dl_completed_by uuid
);


ALTER TABLE public.call_in_districts OWNER TO postgres;

--
-- Name: call_in_districts_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

ALTER TABLE public.call_in_districts ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.call_in_districts_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: units; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.units (
    id bigint NOT NULL,
    stake_id bigint,
    name text NOT NULL,
    unit_type text,
    active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    unit_number text
);


ALTER TABLE public.units OWNER TO postgres;

--
-- Name: weekly_planning_answers; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.weekly_planning_answers (
    id bigint NOT NULL,
    weekly_area_report_id bigint NOT NULL,
    question_key text NOT NULL,
    answer_text text,
    answer_number numeric,
    answer_boolean boolean,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    answer_json jsonb
);


ALTER TABLE public.weekly_planning_answers OWNER TO postgres;

--
-- Name: weekly_area_reports_with_planning_metrics; Type: VIEW; Schema: public; Owner: postgres
--

CREATE VIEW public.weekly_area_reports_with_planning_metrics WITH (security_invoker='true') AS
 SELECT war.id,
    war.area_id,
    war.reporting_week_id,
    war.status,
    war.submitted_by,
    war.submitted_at,
    public.planning_kpi_value(((answers.numbers ->> 'friends_found_actual'::text))::numeric, war.friends_found_actual) AS friends_found_actual,
    public.planning_kpi_value(((answers.numbers ->> 'friends_found_goal'::text))::numeric, war.friends_found_goal) AS friends_found_goal,
    war.lessons_with_friends_actual,
    war.lessons_with_friends_goal,
    public.planning_kpi_value(((answers.numbers ->> 'members_at_lessons_actual'::text))::numeric, war.lessons_with_members_actual) AS lessons_with_members_actual,
    public.planning_kpi_value(((answers.numbers ->> 'members_at_lessons_goal'::text))::numeric, war.lessons_with_members_goal) AS lessons_with_members_goal,
    public.planning_kpi_value(((answers.numbers ->> 'sacrament_attendance_actual'::text))::numeric, war.sacrament_attendance_actual) AS sacrament_attendance_actual,
    public.planning_kpi_value(((answers.numbers ->> 'sacrament_attendance_goal'::text))::numeric, war.sacrament_attendance_goal) AS sacrament_attendance_goal,
    war.first_time_sacrament_actual,
    public.planning_kpi_value(((answers.numbers ->> 'baptismal_dates_actual'::text))::numeric, war.baptismal_dates_actual) AS baptismal_dates_actual,
    public.planning_kpi_value(((answers.numbers ->> 'baptismal_dates_goal'::text))::numeric, war.baptismal_dates_goal) AS baptismal_dates_goal,
    public.planning_kpi_value(((answers.numbers ->> 'nm_sacrament_attendance'::text))::numeric, war.new_member_sacrament_actual) AS new_member_sacrament_actual,
    public.planning_kpi_value(((answers.numbers ->> 'nm_sacrament_attendance_goal'::text))::numeric, war.new_member_sacrament_goal) AS new_member_sacrament_goal,
    war.follow_up_lessons_actual,
    war.follow_up_lessons_goal,
    war.notes,
    war.created_at,
    war.updated_at,
    war.unit_id,
    public.planning_kpi_value(((answers.numbers ->> 'baptisms_confirmations_actual'::text))::numeric, war.baptisms_confirmations_actual) AS baptisms_confirmations_actual,
    public.planning_kpi_value(((answers.numbers ->> 'baptisms_confirmations_goal'::text))::numeric, war.baptisms_confirmations_goal) AS baptisms_confirmations_goal,
    war.historical_source_area,
    war.historical_source_key,
    war.import_batch_id
   FROM (public.weekly_area_reports war
     LEFT JOIN LATERAL ( SELECT jsonb_object_agg(wpa.question_key, wpa.answer_number) FILTER (WHERE (wpa.answer_number IS NOT NULL)) AS numbers
           FROM public.weekly_planning_answers wpa
          WHERE (wpa.weekly_area_report_id = war.id)) answers ON (true));


ALTER TABLE public.weekly_area_reports_with_planning_metrics OWNER TO postgres;

--
-- Name: call_in_planning_details; Type: VIEW; Schema: public; Owner: postgres
--

CREATE VIEW public.call_in_planning_details WITH (security_invoker='true') AS
 SELECT r.id AS weekly_area_report_id,
    r.reporting_week_id,
    rw.sunday AS reporting_sunday,
    r.area_id,
    a.name AS area_name,
    d.id AS district_id,
    d.name AS district_name,
    z.id AS zone_id,
    z.name AS zone_name,
    z.mission_id,
    r.unit_id,
    u.name AS unit_name,
    r.status,
    ((COALESCE(goals.items, '[]'::jsonb) || jsonb_build_array(jsonb_build_object('key', 'lessons_with_friends_goal', 'label', 'Lessons with friends', 'section', 'Teaching and follow-up', 'actual', r.lessons_with_friends_actual, 'goal', r.lessons_with_friends_goal), jsonb_build_object('key', 'follow_up_lessons_goal', 'label', 'Follow-up lessons', 'section', 'Teaching and follow-up', 'actual', r.follow_up_lessons_actual, 'goal', r.follow_up_lessons_goal))) || COALESCE(member_goals.items, '[]'::jsonb)) AS other_goals,
    COALESCE(plans.items, '[]'::jsonb) AS action_plans,
    NULLIF(btrim((answers.texts ->> 'weekly_action_plan'::text)), ''::text) AS weekly_action_plan,
    NULLIF(btrim((answers.texts ->> 'information_up_chain'::text)), ''::text) AS information_up_chain
   FROM (((((((((public.weekly_area_reports_with_planning_metrics r
     JOIN public.reporting_weeks rw ON ((rw.id = r.reporting_week_id)))
     JOIN public.areas a ON ((a.id = r.area_id)))
     JOIN public.districts d ON ((d.id = a.district_id)))
     JOIN public.zones z ON ((z.id = d.zone_id)))
     LEFT JOIN public.units u ON ((u.id = r.unit_id)))
     LEFT JOIN LATERAL ( SELECT jsonb_object_agg(wpa.question_key, wpa.answer_number) FILTER (WHERE (wpa.answer_number IS NOT NULL)) AS numbers,
            jsonb_object_agg(wpa.question_key, wpa.answer_text) FILTER (WHERE (wpa.answer_text IS NOT NULL)) AS texts
           FROM public.weekly_planning_answers wpa
          WHERE (wpa.weekly_area_report_id = r.id)) answers ON (true))
     LEFT JOIN LATERAL ( WITH goal_definitions AS (
                 SELECT q_1.question_key,
                    q_1.question_label,
                    q_1.section_title,
                    q_1.section_order,
                    q_1.question_order
                   FROM public.active_planning_questions q_1
                  WHERE (("right"(q_1.question_key, 5) = '_goal'::text) AND (q_1.question_key <> ALL (ARRAY['nm_sacrament_attendance_goal'::text, 'baptisms_confirmations_goal'::text, 'baptismal_dates_goal'::text, 'sacrament_attendance_goal'::text, 'members_at_lessons_goal'::text, 'friends_found_goal'::text, 'lessons_with_friends_goal'::text, 'follow_up_lessons_goal'::text])))
                UNION ALL
                 SELECT wpa.question_key,
                    initcap(replace(wpa.question_key, '_'::text, ' '::text)) AS initcap,
                    'Additional goals'::text AS text,
                    999,
                    999
                   FROM public.weekly_planning_answers wpa
                  WHERE ((wpa.weekly_area_report_id = r.id) AND ("right"(wpa.question_key, 5) = '_goal'::text) AND (NOT (EXISTS ( SELECT 1
                           FROM public.active_planning_questions q_1
                          WHERE (q_1.question_key = wpa.question_key)))))
                )
         SELECT jsonb_agg(jsonb_build_object('key', q.question_key, 'label', regexp_replace(q.question_label, '\s*—.*$'::text, ''::text), 'section', q.section_title, 'goal', ((answers.numbers ->> q.question_key))::numeric, 'actual', ( SELECT sum(((answers.numbers ->> actual_key.actual_key))::numeric) AS sum
                   FROM unnest(
                        CASE q.question_key
                            WHEN 'member_meals_goal'::text THEN ARRAY['member_meals_active_actual'::text, 'member_meals_less_active_actual'::text, 'member_meals_part_member_actual'::text]
                            WHEN 'member_visits_goal'::text THEN ARRAY['member_visits_active_actual'::text, 'member_visits_less_active_actual'::text, 'member_visits_part_member_actual'::text]
                            ELSE ARRAY[regexp_replace(q.question_key, '_goal$'::text, '_actual'::text)]
                        END) actual_key(actual_key))) ORDER BY q.section_order, q.question_order, q.question_key) AS items
           FROM goal_definitions q) goals ON (true))
     LEFT JOIN LATERAL ( SELECT jsonb_agg(jsonb_build_object('key', ('new_member_lessons_'::text || wnm.id), 'label', ('New member lessons'::text || COALESCE((' · '::text || nm.display_name), ''::text)), 'section', 'New member follow-up', 'actual', wnm.lessons_actual, 'goal', wnm.lessons_goal) ORDER BY wnm.display_order, wnm.id) AS items
           FROM (public.weekly_new_members wnm
             LEFT JOIN public.new_members nm ON (((nm.id = wnm.new_member_id) AND public.can_access_area(nm.area_id))))
          WHERE ((wnm.weekly_area_report_id = r.id) AND (wnm.lessons_goal IS NOT NULL))) member_goals ON (true))
     LEFT JOIN LATERAL ( SELECT jsonb_agg(jsonb_build_object('key', wpa.question_key, 'label', regexp_replace(regexp_replace(COALESCE(q.question_label, initcap(replace(wpa.question_key, '_'::text, ' '::text))), '^Optional: '::text, ''::text), '\s*— Action Plan$'::text, ''::text), 'text', btrim(wpa.answer_text), 'core', (wpa.question_key = ANY (ARRAY['nm_sacrament_attendance_plan'::text, 'baptisms_confirmations_plan'::text, 'baptismal_dates_plan'::text, 'sacrament_attendance_plan'::text, 'members_at_lessons_plan'::text, 'friends_found_plan'::text]))) ORDER BY q.section_order, q.question_order, wpa.question_key) AS items
           FROM (public.weekly_planning_answers wpa
             LEFT JOIN public.active_planning_questions q ON ((q.question_key = wpa.question_key)))
          WHERE ((wpa.weekly_area_report_id = r.id) AND ("right"(wpa.question_key, 5) = '_plan'::text) AND (wpa.question_key <> ALL (ARRAY['weekly_action_plan'::text, 'social_media_plan'::text])) AND (NULLIF(btrim(wpa.answer_text), ''::text) IS NOT NULL))) plans ON (true))
  WHERE public.can_access_area(r.area_id);


ALTER TABLE public.call_in_planning_details OWNER TO postgres;

--
-- Name: call_in_zones; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.call_in_zones (
    id bigint NOT NULL,
    zone_id bigint NOT NULL,
    reporting_week_id bigint NOT NULL,
    zone_notes text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.call_in_zones OWNER TO postgres;

--
-- Name: call_in_zones_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

ALTER TABLE public.call_in_zones ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.call_in_zones_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: cleanup_029_revoked_grants; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.cleanup_029_revoked_grants (
    object_kind text NOT NULL,
    object_name text NOT NULL,
    grantee text NOT NULL,
    privilege_type text NOT NULL,
    grantor text NOT NULL,
    is_grantable boolean NOT NULL,
    revoked_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT cleanup_029_revoked_grants_object_kind_check CHECK ((object_kind = ANY (ARRAY['TABLE'::text, 'SEQUENCE'::text, 'FUNCTION'::text, 'DEFAULT'::text])))
);


ALTER TABLE public.cleanup_029_revoked_grants OWNER TO postgres;

--
-- Name: cleanup_030_removed_rows; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.cleanup_030_removed_rows (
    table_name text NOT NULL,
    row_id bigint NOT NULL,
    row_data jsonb NOT NULL,
    removed_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT cleanup_030_removed_rows_table_name_check CHECK ((table_name = ANY (ARRAY['weekly_new_members'::text, 'weekly_baptismal_date_friends'::text])))
);


ALTER TABLE public.cleanup_030_removed_rows OWNER TO postgres;

--
-- Name: companionship_members; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.companionship_members (
    companionship_id bigint NOT NULL,
    missionary_id bigint NOT NULL,
    joined_date date,
    left_date date,
    CONSTRAINT companionship_members_check CHECK (((left_date IS NULL) OR (joined_date IS NULL) OR (left_date >= joined_date)))
);


ALTER TABLE public.companionship_members OWNER TO postgres;

--
-- Name: companionships; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.companionships (
    id bigint NOT NULL,
    area_id bigint NOT NULL,
    start_date date NOT NULL,
    end_date date,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT companionships_check CHECK (((end_date IS NULL) OR (end_date >= start_date)))
);


ALTER TABLE public.companionships OWNER TO postgres;

--
-- Name: companionships_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

ALTER TABLE public.companionships ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.companionships_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: current_reporting_week; Type: VIEW; Schema: public; Owner: postgres
--

CREATE VIEW public.current_reporting_week WITH (security_invoker='true') AS
 SELECT reporting_weeks.id,
    reporting_weeks.sunday,
    reporting_weeks.planning_open_at,
    reporting_weeks.planning_due_at
   FROM public.reporting_weeks
  WHERE (reporting_weeks.sunday <= public.current_reporting_sunday())
  ORDER BY reporting_weeks.sunday DESC
 LIMIT 1;


ALTER TABLE public.current_reporting_week OWNER TO postgres;

--
-- Name: current_area_reporting_status; Type: VIEW; Schema: public; Owner: postgres
--

CREATE VIEW public.current_area_reporting_status WITH (security_invoker='true') AS
 SELECT ars.area_id,
    ars.area_name,
    ars.district_id,
    ars.district_name,
    ars.zone_id,
    ars.zone_name,
    ars.mission_id,
    ars.mission_name,
    ars.reporting_week_id,
    ars.sunday,
    ars.weekly_area_report_id,
    ars.submitted,
    ars.status,
    ars.submitted_at,
    ars.submitted_by
   FROM (public.area_reporting_status ars
     JOIN public.current_reporting_week crw ON ((crw.id = ars.reporting_week_id)));


ALTER TABLE public.current_area_reporting_status OWNER TO postgres;

--
-- Name: current_baptismal_date_people; Type: VIEW; Schema: public; Owner: postgres
--

CREATE VIEW public.current_baptismal_date_people WITH (security_invoker='true') AS
 SELECT f.id,
    f.first_name,
    f.last_name,
    f.display_name,
    f.finding_source,
    faa.area_id,
    faa.start_date AS area_start_date,
    d.current_baptismal_date
   FROM ((public.baptismal_date_people f
     JOIN public.baptismal_date_person_area_assignments faa ON ((faa.baptismal_date_person_id = f.id)))
     LEFT JOIN LATERAL ( SELECT w.current_baptismal_date
           FROM ((public.weekly_baptismal_date_friends w
             JOIN public.weekly_area_reports r ON ((r.id = w.weekly_area_report_id)))
             JOIN public.reporting_weeks rw ON ((rw.id = r.reporting_week_id)))
          WHERE ((w.baptismal_date_person_id = f.id) AND (w.current_baptismal_date IS NOT NULL))
          ORDER BY rw.sunday DESC, w.updated_at DESC NULLS LAST, w.id DESC
         LIMIT 1) d ON (true))
  WHERE ((faa.end_date IS NULL) AND (f.tracking_status = 'current'::text) AND ((d.current_baptismal_date IS NULL) OR (d.current_baptismal_date >= ((now() AT TIME ZONE 'Europe/Berlin'::text))::date)));


ALTER TABLE public.current_baptismal_date_people OWNER TO postgres;

--
-- Name: leadership_assignments; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.leadership_assignments (
    id bigint NOT NULL,
    missionary_id bigint NOT NULL,
    role text NOT NULL,
    district_id bigint,
    zone_id bigint,
    mission_id bigint,
    start_date date NOT NULL,
    end_date date,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT leadership_assignments_check CHECK (((end_date IS NULL) OR (end_date >= start_date))),
    CONSTRAINT leadership_assignments_check1 CHECK ((((role = 'DL'::text) AND (district_id IS NOT NULL)) OR ((role = ANY (ARRAY['STL'::text, 'ZL'::text])) AND (zone_id IS NOT NULL)) OR ((role = 'AP'::text) AND (mission_id IS NOT NULL)))),
    CONSTRAINT leadership_assignments_role_check CHECK ((role = ANY (ARRAY['DL'::text, 'STL'::text, 'ZL'::text, 'AP'::text])))
);


ALTER TABLE public.leadership_assignments OWNER TO postgres;

--
-- Name: current_leadership_assignments; Type: VIEW; Schema: public; Owner: postgres
--

CREATE VIEW public.current_leadership_assignments WITH (security_invoker='true') AS
 SELECT la.id AS leadership_assignment_id,
    la.missionary_id,
    la.role,
    la.district_id,
    d.name AS district_name,
    la.zone_id,
    z.name AS zone_name,
    la.mission_id,
    m.name AS mission_name,
    la.start_date,
    la.end_date
   FROM (((public.leadership_assignments la
     LEFT JOIN public.districts d ON ((d.id = la.district_id)))
     LEFT JOIN public.zones z ON ((z.id = la.zone_id)))
     LEFT JOIN public.missions m ON ((m.id = la.mission_id)))
  WHERE ((la.start_date <= CURRENT_DATE) AND ((la.end_date IS NULL) OR (la.end_date >= CURRENT_DATE)));


ALTER TABLE public.current_leadership_assignments OWNER TO postgres;

--
-- Name: missionaries; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.missionaries (
    id bigint NOT NULL,
    missionary_number text,
    first_name text,
    last_name text NOT NULL,
    display_name text NOT NULL,
    missionary_type text,
    status text DEFAULT 'Active'::text NOT NULL,
    arrival_date date,
    release_date date,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    phone text,
    mtc_date date,
    languages text,
    email text,
    CONSTRAINT missionaries_status_check CHECK ((status = ANY (ARRAY['Active'::text, 'Released'::text, 'Incoming'::text, 'Other'::text])))
);


ALTER TABLE public.missionaries OWNER TO postgres;

--
-- Name: missionary_assignments; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.missionary_assignments (
    id bigint NOT NULL,
    missionary_id bigint NOT NULL,
    area_id bigint NOT NULL,
    start_date date NOT NULL,
    end_date date,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    roster_position text,
    roster_position_abbr text,
    special_assignment text,
    special_assignment_notes text,
    CONSTRAINT missionary_assignments_check CHECK (((end_date IS NULL) OR (end_date >= start_date)))
);


ALTER TABLE public.missionary_assignments OWNER TO postgres;

--
-- Name: user_profiles; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.user_profiles (
    id uuid NOT NULL,
    missionary_id bigint,
    app_role text DEFAULT 'MISSIONARY'::text NOT NULL,
    active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    additional_roles text[] DEFAULT '{}'::text[] NOT NULL,
    home_mission_id bigint,
    display_name text,
    CONSTRAINT user_profiles_additional_roles_check CHECK ((additional_roles <@ ARRAY['DATA_ADMIN'::text, 'OFFICE'::text])),
    CONSTRAINT user_profiles_app_role_management_check CHECK ((app_role = ANY (ARRAY['MISSIONARY'::text, 'DL'::text, 'STL'::text, 'ZL'::text, 'AP'::text, 'OFFICE'::text, 'PRESIDENT'::text, 'DATA_ADMIN'::text]))),
    CONSTRAINT user_profiles_display_name_check CHECK (((display_name IS NULL) OR ((char_length(btrim(display_name)) >= 1) AND (char_length(btrim(display_name)) <= 120)))),
    CONSTRAINT user_profiles_home_mission_staff_check CHECK (((home_mission_id IS NULL) OR (missionary_id IS NOT NULL) OR (app_role = ANY (ARRAY['PRESIDENT'::text, 'OFFICE'::text, 'DATA_ADMIN'::text]))))
);


ALTER TABLE public.user_profiles OWNER TO postgres;

--
-- Name: current_user_context; Type: VIEW; Schema: public; Owner: postgres
--

CREATE VIEW public.current_user_context WITH (security_invoker='true') AS
 SELECT up.id AS user_id,
    up.app_role,
    up.active AS user_active,
    m.id AS missionary_id,
    m.missionary_number,
    COALESCE(m.display_name, up.display_name) AS display_name,
    m.missionary_type,
    m.status AS missionary_status,
    ma.id AS missionary_assignment_id,
    ma.start_date AS assignment_start_date,
    ma.roster_position,
    ma.roster_position_abbr,
    ma.special_assignment,
    a.id AS area_id,
    a.area_code,
    a.name AS area,
    a.assignment_type AS area_assignment_type,
    d.id AS district_id,
    d.name AS district,
    z.id AS zone_id,
    z.name AS zone,
    mi.id AS mission_id,
    mi.name AS mission,
    la.role AS leadership_role,
    up.additional_roles,
        CASE
            WHEN (up.missionary_id IS NULL) THEN up.home_mission_id
            ELSE NULL::bigint
        END AS home_mission_id
   FROM (((((((public.user_profiles up
     LEFT JOIN public.missionaries m ON ((m.id = up.missionary_id)))
     LEFT JOIN public.missionary_assignments ma ON (((ma.missionary_id = m.id) AND (ma.start_date <= CURRENT_DATE) AND ((ma.end_date IS NULL) OR (ma.end_date >= CURRENT_DATE)))))
     LEFT JOIN public.areas a ON ((a.id = ma.area_id)))
     LEFT JOIN public.districts d ON ((d.id = a.district_id)))
     LEFT JOIN public.zones z ON ((z.id = d.zone_id)))
     LEFT JOIN public.missions mi ON ((mi.id = z.mission_id)))
     LEFT JOIN public.leadership_assignments la ON (((la.missionary_id = m.id) AND (la.start_date <= CURRENT_DATE) AND ((la.end_date IS NULL) OR (la.end_date >= CURRENT_DATE)))));


ALTER TABLE public.current_user_context OWNER TO postgres;

--
-- Name: current_mission_areas; Type: VIEW; Schema: public; Owner: postgres
--

CREATE VIEW public.current_mission_areas WITH (security_invoker='true') AS
 SELECT a.id AS area_id,
    a.area_code,
    a.name AS area,
    d.id AS district_id,
    d.name AS district,
    z.id AS zone_id,
    z.name AS zone,
    z.mission_id
   FROM ((public.areas a
     JOIN public.districts d ON ((d.id = a.district_id)))
     JOIN public.zones z ON ((z.id = d.zone_id)))
  WHERE ((z.mission_id = ( SELECT cuc.mission_id
           FROM public.current_user_context cuc
         LIMIT 1)) AND (a.active = true));


ALTER TABLE public.current_mission_areas OWNER TO postgres;

--
-- Name: current_missionary_assignments; Type: VIEW; Schema: public; Owner: postgres
--

CREATE VIEW public.current_missionary_assignments WITH (security_invoker='true') AS
 SELECT ma.id AS assignment_id,
    ma.missionary_id,
    ma.area_id,
    a.name AS area_name,
    d.id AS district_id,
    d.name AS district_name,
    z.id AS zone_id,
    z.name AS zone_name,
    m.id AS mission_id,
    m.name AS mission_name,
    ma.start_date,
    ma.end_date
   FROM ((((public.missionary_assignments ma
     JOIN public.areas a ON ((a.id = ma.area_id)))
     JOIN public.districts d ON ((d.id = a.district_id)))
     JOIN public.zones z ON ((z.id = d.zone_id)))
     JOIN public.missions m ON ((m.id = z.mission_id)))
  WHERE ((ma.start_date <= CURRENT_DATE) AND ((ma.end_date IS NULL) OR (ma.end_date >= CURRENT_DATE)));


ALTER TABLE public.current_missionary_assignments OWNER TO postgres;

--
-- Name: new_member_area_assignments; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.new_member_area_assignments (
    id bigint NOT NULL,
    new_member_id bigint NOT NULL,
    area_id bigint NOT NULL,
    start_date date DEFAULT CURRENT_DATE NOT NULL,
    end_date date,
    transfer_reason text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    unit_id bigint,
    CONSTRAINT new_member_area_assignment_dates_check CHECK (((end_date IS NULL) OR (end_date >= start_date)))
);


ALTER TABLE public.new_member_area_assignments OWNER TO postgres;

--
-- Name: current_new_members; Type: VIEW; Schema: public; Owner: postgres
--

CREATE VIEW public.current_new_members WITH (security_invoker='true') AS
 SELECT nm.id,
    nm.area_id,
    nm.first_name,
    nm.last_name,
    nm.display_name,
    nm.baptism_date,
    nm.confirmation_date,
    nm.active,
    nm.created_at,
    nm.updated_at,
    nm.stake_id,
    nm.unit_id,
    nm.baptismal_date_extended,
    nm.finding_source,
    nm.conversion_success_notes,
    nm.date_of_birth,
    nm.age_range,
    nm.gender,
    nm.marital_status,
    nm.child_dependents,
    nm.living_situation,
    nm.native_language,
    nm.second_language,
    nm.mission_language_competency,
    nm.country_of_origin,
    nm.created_by,
    nm.inactive_at,
    nm.inactive_reason,
    nm.follow_up_status,
    nm.follow_up_ended_at,
    nm.follow_up_end_reason
   FROM public.new_members nm
  WHERE ((nm.follow_up_status = 'current'::text) AND (((nm.baptism_date IS NOT NULL) AND (nm.baptism_date > (((now() AT TIME ZONE 'Europe/Berlin'::text))::date - '1 year'::interval))) OR ((nm.baptism_date IS NULL) AND (EXISTS ( SELECT 1
           FROM ((public.weekly_new_members w
             JOIN public.weekly_area_reports r ON ((r.id = w.weekly_area_report_id)))
             JOIN public.reporting_weeks rw ON ((rw.id = r.reporting_week_id)))
          WHERE ((w.new_member_id = nm.id) AND (rw.sunday >= (public.current_reporting_sunday() - 7))))))) AND (EXISTS ( SELECT 1
           FROM public.new_member_area_assignments a
          WHERE ((a.new_member_id = nm.id) AND (a.end_date IS NULL) AND (a.area_id = nm.area_id)))));


ALTER TABLE public.current_new_members OWNER TO postgres;

--
-- Name: current_user_area_units; Type: VIEW; Schema: public; Owner: postgres
--

CREATE VIEW public.current_user_area_units WITH (security_invoker='true') AS
 SELECT a.id AS area_id,
    a.area_code,
    a.name AS area,
    u.id AS unit_id,
    u.name AS unit,
    u.unit_type,
    au.primary_unit
   FROM ((((public.current_missionary_assignments cma
     JOIN public.areas a ON ((a.id = cma.area_id)))
     JOIN public.area_units au ON (((au.area_id = a.id) AND (au.active = true))))
     JOIN public.units u ON (((u.id = au.unit_id) AND (u.active = true))))
     JOIN public.user_profiles up ON (((up.missionary_id = cma.missionary_id) AND (up.id = auth.uid()) AND (up.active = true))))
  ORDER BY au.primary_unit DESC, u.name;


ALTER TABLE public.current_user_area_units OWNER TO postgres;

--
-- Name: current_user_scope; Type: VIEW; Schema: public; Owner: postgres
--

CREATE VIEW public.current_user_scope WITH (security_invoker='true') AS
 SELECT up.id AS user_id,
    up.missionary_id,
    up.app_role,
    cma.area_id,
    cma.area_name,
    cma.district_id,
    cma.district_name,
    cma.zone_id,
    cma.zone_name,
    cma.mission_id,
    cma.mission_name,
    cla.role AS leadership_role,
    cla.district_id AS leadership_district_id,
    cla.district_name AS leadership_district_name,
    cla.zone_id AS leadership_zone_id,
    cla.zone_name AS leadership_zone_name,
    cla.mission_id AS leadership_mission_id,
    cla.mission_name AS leadership_mission_name,
    up.additional_roles,
        CASE
            WHEN (up.missionary_id IS NULL) THEN up.home_mission_id
            ELSE NULL::bigint
        END AS home_mission_id
   FROM ((public.user_profiles up
     LEFT JOIN public.current_missionary_assignments cma ON ((cma.missionary_id = up.missionary_id)))
     LEFT JOIN public.current_leadership_assignments cla ON ((cla.missionary_id = up.missionary_id)))
  WHERE (up.active = true);


ALTER TABLE public.current_user_scope OWNER TO postgres;

--
-- Name: current_weekly_reports; Type: VIEW; Schema: public; Owner: postgres
--

CREATE VIEW public.current_weekly_reports WITH (security_invoker='true') AS
 SELECT war.id AS weekly_report_id,
    rw.sunday,
    war.status,
    war.submitted_at,
    m.id AS mission_id,
    m.name AS mission,
    z.id AS zone_id,
    z.name AS zone,
    d.id AS district_id,
    d.name AS district,
    a.id AS area_id,
    a.area_code,
    a.name AS area,
    war.friends_found_actual,
    war.friends_found_goal,
    war.lessons_with_friends_actual,
    war.lessons_with_friends_goal,
    war.lessons_with_members_actual,
    war.lessons_with_members_goal,
    war.sacrament_attendance_actual,
    war.sacrament_attendance_goal,
    war.first_time_sacrament_actual,
    war.baptismal_dates_actual,
    war.baptismal_dates_goal,
    war.new_member_sacrament_actual,
    war.new_member_sacrament_goal,
    war.follow_up_lessons_actual,
    war.follow_up_lessons_goal,
    war.notes,
    u.id AS unit_id,
    u.name AS unit,
    u.unit_type
   FROM ((((((public.weekly_area_reports war
     JOIN public.reporting_weeks rw ON ((rw.id = war.reporting_week_id)))
     JOIN public.areas a ON ((a.id = war.area_id)))
     JOIN public.districts d ON ((d.id = a.district_id)))
     JOIN public.zones z ON ((z.id = d.zone_id)))
     JOIN public.missions m ON ((m.id = z.mission_id)))
     LEFT JOIN public.units u ON ((u.id = war.unit_id)))
  WHERE ((rw.sunday = public.current_reporting_sunday()) AND public.can_access_area(a.id));


ALTER TABLE public.current_weekly_reports OWNER TO postgres;

--
-- Name: data_name_matches; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.data_name_matches (
    id bigint NOT NULL,
    mission_id bigint NOT NULL,
    level text NOT NULL,
    source_key text NOT NULL,
    source_name text NOT NULL,
    zone_id bigint,
    area_id bigint,
    historical boolean DEFAULT false NOT NULL,
    confirmed_by text,
    confirmed_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT data_name_matches_check CHECK (
CASE
    WHEN historical THEN ((zone_id IS NULL) AND (area_id IS NULL))
    WHEN (level = 'zone'::text) THEN ((zone_id IS NOT NULL) AND (area_id IS NULL))
    ELSE ((area_id IS NOT NULL) AND (zone_id IS NULL))
END),
    CONSTRAINT data_name_matches_level_check CHECK ((level = ANY (ARRAY['zone'::text, 'area'::text])))
);


ALTER TABLE public.data_name_matches OWNER TO postgres;

--
-- Name: data_name_matches_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

ALTER TABLE public.data_name_matches ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.data_name_matches_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: districts_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

ALTER TABLE public.districts ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.districts_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: gfm_schema_migrations; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.gfm_schema_migrations (
    id bigint NOT NULL,
    migration_name text NOT NULL,
    applied_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.gfm_schema_migrations OWNER TO postgres;

--
-- Name: gfm_schema_migrations_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

ALTER TABLE public.gfm_schema_migrations ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.gfm_schema_migrations_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: historical_planning_details; Type: TABLE; Schema: public; Owner: supabase_admin
--

CREATE TABLE public.historical_planning_details (
    weekly_area_report_id bigint NOT NULL,
    source_companionship text NOT NULL,
    source_unit text,
    answers jsonb DEFAULT '[]'::jsonb NOT NULL,
    new_members jsonb DEFAULT '[]'::jsonb NOT NULL,
    baptismal_date_friends jsonb DEFAULT '[]'::jsonb NOT NULL,
    high_potential_friends jsonb DEFAULT '[]'::jsonb NOT NULL
);


ALTER TABLE public.historical_planning_details OWNER TO supabase_admin;

--
-- Name: import_weekly_baptismal_date_friends; Type: TABLE; Schema: public; Owner: supabase_admin
--

CREATE TABLE public.import_weekly_baptismal_date_friends (
    source_report_key text,
    display_order integer,
    source_first_name text,
    source_last_name text,
    baptismal_date_set_on date,
    finding_source text,
    reading boolean,
    praying boolean,
    at_church_this_sunday boolean,
    keeping_commandments boolean,
    member_involvement boolean,
    current_baptismal_date date,
    source_stake_name text
);


ALTER TABLE public.import_weekly_baptismal_date_friends OWNER TO supabase_admin;

--
-- Name: import_weekly_high_potential_friends; Type: TABLE; Schema: public; Owner: supabase_admin
--

CREATE TABLE public.import_weekly_high_potential_friends (
    source_report_key text,
    display_order integer,
    name text,
    at_church_this_sunday boolean,
    notes text
);


ALTER TABLE public.import_weekly_high_potential_friends OWNER TO supabase_admin;

--
-- Name: import_weekly_new_members; Type: TABLE; Schema: public; Owner: supabase_admin
--

CREATE TABLE public.import_weekly_new_members (
    source_report_key text,
    display_order integer,
    source_name text,
    source_gender text,
    source_age_range text,
    lessons_actual integer,
    lessons_goal integer,
    pmg_lessons_percentage numeric,
    next_ordinance text,
    at_church_this_sunday boolean,
    has_calling text,
    has_aaronic_priesthood text,
    has_melchizedek_priesthood text,
    ministers_to_someone text,
    ministered_to_by_someone boolean,
    has_active_temple_recommend text,
    visited_temple_for_baptisms text,
    reading boolean,
    praying boolean,
    member_involvement boolean,
    how_are_they_doing text,
    discussed_in_gemiko boolean,
    gemiko_support_plan text
);


ALTER TABLE public.import_weekly_new_members OWNER TO supabase_admin;

--
-- Name: import_weekly_planning_answers; Type: TABLE; Schema: public; Owner: supabase_admin
--

CREATE TABLE public.import_weekly_planning_answers (
    source_report_key text,
    source_column text,
    source_question_label text,
    answer_raw text,
    answer_boolean boolean,
    answer_number numeric,
    answer_text text
);


ALTER TABLE public.import_weekly_planning_answers OWNER TO supabase_admin;

--
-- Name: import_weekly_planning_area_map; Type: TABLE; Schema: public; Owner: supabase_admin
--

CREATE TABLE public.import_weekly_planning_area_map (
    source_companionship text NOT NULL,
    target_area_name text,
    match_status text,
    source_units text,
    submission_rows integer,
    distinct_weeks integer,
    first_sunday date,
    last_sunday date,
    notes text,
    mission_id bigint,
    target_area_id bigint,
    confirmed_at timestamp with time zone,
    confirmed_by text
);


ALTER TABLE public.import_weekly_planning_area_map OWNER TO supabase_admin;

--
-- Name: import_weekly_planning_reports; Type: TABLE; Schema: public; Owner: supabase_admin
--

CREATE TABLE public.import_weekly_planning_reports (
    source_report_key text NOT NULL,
    source_row_number integer,
    source_timestamp timestamp with time zone,
    source_email text,
    source_companionship text,
    target_area_name text,
    source_unit text,
    reporting_sunday date,
    status text,
    baptisms_confirmations_actual integer,
    baptisms_confirmations_goal integer,
    new_member_sacrament_actual integer,
    new_member_sacrament_goal integer,
    baptismal_dates_actual integer,
    baptismal_dates_goal integer,
    friends_found_actual integer,
    friends_found_goal integer,
    lessons_with_friends_actual integer,
    lessons_with_friends_goal integer,
    follow_up_lessons_actual integer,
    follow_up_lessons_goal integer,
    lessons_with_members_actual integer,
    lessons_with_members_goal integer,
    sacrament_attendance_actual integer,
    sacrament_attendance_goal integer,
    first_time_sacrament_actual integer,
    notes text
);


ALTER TABLE public.import_weekly_planning_reports OWNER TO supabase_admin;

--
-- Name: leadership_assignments_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

ALTER TABLE public.leadership_assignments ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.leadership_assignments_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: missionaries_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

ALTER TABLE public.missionaries ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.missionaries_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: missionary_assignments_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

ALTER TABLE public.missionary_assignments ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.missionary_assignments_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: missionary_language_assignments; Type: TABLE; Schema: public; Owner: supabase_admin
--

CREATE TABLE public.missionary_language_assignments (
    missionary_id bigint NOT NULL,
    primary_language text DEFAULT 'en'::text NOT NULL,
    additional_languages text[] DEFAULT '{}'::text[] NOT NULL,
    assigned_by text,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT language_primary_code CHECK ((primary_language ~ '^[a-zA-Z]{2,3}(-[a-zA-Z0-9]{2,8})*$'::text)),
    CONSTRAINT language_primary_not_additional CHECK ((NOT (primary_language = ANY (additional_languages))))
);


ALTER TABLE public.missionary_language_assignments OWNER TO supabase_admin;

--
-- Name: missions_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

ALTER TABLE public.missions ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.missions_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: new_member_area_assignments_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.new_member_area_assignments_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER TABLE public.new_member_area_assignments_id_seq OWNER TO postgres;

--
-- Name: new_member_area_assignments_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.new_member_area_assignments_id_seq OWNED BY public.new_member_area_assignments.id;


--
-- Name: new_members_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.new_members_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER TABLE public.new_members_id_seq OWNER TO postgres;

--
-- Name: new_members_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.new_members_id_seq OWNED BY public.new_members.id;


--
-- Name: people_match_decisions; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.people_match_decisions (
    id bigint NOT NULL,
    mission_id bigint NOT NULL,
    key_a text NOT NULL,
    key_b text NOT NULL,
    same boolean NOT NULL,
    decided_by text,
    decided_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT people_match_decisions_check CHECK ((key_a <> key_b))
);


ALTER TABLE public.people_match_decisions OWNER TO postgres;

--
-- Name: people_match_decisions_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

ALTER TABLE public.people_match_decisions ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.people_match_decisions_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: planning_catalog_changes; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.planning_catalog_changes (
    id bigint NOT NULL,
    changed_at timestamp with time zone DEFAULT now() NOT NULL,
    actor text NOT NULL,
    actor_user_id uuid,
    table_name text NOT NULL,
    row_key jsonb NOT NULL,
    before_row jsonb,
    after_row jsonb,
    note text,
    CONSTRAINT planning_catalog_changes_table_check CHECK ((table_name = ANY (ARRAY['planning_question_sections'::text, 'planning_questions'::text, 'planning_question_options'::text, 'planning_question_grid_rows'::text, 'planning_question_visibility_rules'::text, 'weekly_planning_answers'::text])))
);


ALTER TABLE public.planning_catalog_changes OWNER TO postgres;

--
-- Name: planning_catalog_changes_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

ALTER TABLE public.planning_catalog_changes ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.planning_catalog_changes_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: planning_catalog_version; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.planning_catalog_version (
    id boolean DEFAULT true NOT NULL,
    version bigint DEFAULT 1 NOT NULL,
    changed_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT planning_catalog_version_one_row CHECK (id)
);


ALTER TABLE public.planning_catalog_version OWNER TO postgres;

--
-- Name: planning_question_grid_rows; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.planning_question_grid_rows (
    id bigint NOT NULL,
    question_id bigint NOT NULL,
    row_key text NOT NULL,
    row_label text NOT NULL,
    display_order integer DEFAULT 0 NOT NULL,
    active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.planning_question_grid_rows OWNER TO postgres;

--
-- Name: planning_question_grid_rows_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

ALTER TABLE public.planning_question_grid_rows ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.planning_question_grid_rows_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: planning_question_options; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.planning_question_options (
    id bigint NOT NULL,
    question_id bigint NOT NULL,
    option_value text NOT NULL,
    option_label text NOT NULL,
    display_order integer DEFAULT 0 NOT NULL,
    active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.planning_question_options OWNER TO postgres;

--
-- Name: planning_question_options_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

ALTER TABLE public.planning_question_options ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.planning_question_options_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: planning_question_sections_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

ALTER TABLE public.planning_question_sections ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.planning_question_sections_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: planning_question_visibility_rules; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.planning_question_visibility_rules (
    id bigint NOT NULL,
    child_question_key text NOT NULL,
    parent_question_key text NOT NULL,
    operator text NOT NULL,
    comparison_value text NOT NULL,
    active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT planning_visibility_not_self CHECK ((child_question_key <> parent_question_key)),
    CONSTRAINT planning_visibility_operator_check CHECK ((operator = ANY (ARRAY['equals'::text, 'not_equals'::text, 'greater_than'::text, 'greater_than_or_equal'::text, 'less_than'::text, 'less_than_or_equal'::text])))
);


ALTER TABLE public.planning_question_visibility_rules OWNER TO postgres;

--
-- Name: planning_question_visibility_rules_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

ALTER TABLE public.planning_question_visibility_rules ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.planning_question_visibility_rules_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: planning_questions_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

ALTER TABLE public.planning_questions ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.planning_questions_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: reporting_weeks_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

ALTER TABLE public.reporting_weeks ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.reporting_weeks_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: roster_import_changes; Type: TABLE; Schema: public; Owner: supabase_admin
--

CREATE TABLE public.roster_import_changes (
    batch_id uuid NOT NULL,
    sequence integer NOT NULL,
    table_name text NOT NULL,
    row_key jsonb NOT NULL,
    before_row jsonb,
    after_row jsonb
);


ALTER TABLE public.roster_import_changes OWNER TO supabase_admin;

--
-- Name: stakes; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.stakes (
    id bigint NOT NULL,
    mission_id bigint NOT NULL,
    name text NOT NULL,
    active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.stakes OWNER TO postgres;

--
-- Name: stakes_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

ALTER TABLE public.stakes ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.stakes_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: units_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

ALTER TABLE public.units ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.units_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: weekly_area_reports_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

ALTER TABLE public.weekly_area_reports ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.weekly_area_reports_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: weekly_baptismal_date_friends_id_seq1; Type: SEQUENCE; Schema: public; Owner: postgres
--

ALTER TABLE public.weekly_baptismal_date_friends ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.weekly_baptismal_date_friends_id_seq1
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: weekly_high_potential_friends_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

ALTER TABLE public.weekly_high_potential_friends ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.weekly_high_potential_friends_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: weekly_new_members_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

ALTER TABLE public.weekly_new_members ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.weekly_new_members_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: weekly_planning_answers_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

ALTER TABLE public.weekly_planning_answers ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.weekly_planning_answers_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: zones_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

ALTER TABLE public.zones ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.zones_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: push_subscriptions id; Type: DEFAULT; Schema: portal; Owner: postgres
--

ALTER TABLE ONLY portal.push_subscriptions ALTER COLUMN id SET DEFAULT nextval('portal.push_subscriptions_id_seq'::regclass);


--
-- Name: baptismal_date_people id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.baptismal_date_people ALTER COLUMN id SET DEFAULT nextval('public.baptismal_date_people_id_seq'::regclass);


--
-- Name: baptismal_date_person_area_assignments id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.baptismal_date_person_area_assignments ALTER COLUMN id SET DEFAULT nextval('public.baptismal_date_person_area_assignments_id_seq'::regclass);


--
-- Name: new_member_area_assignments id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.new_member_area_assignments ALTER COLUMN id SET DEFAULT nextval('public.new_member_area_assignments_id_seq'::regclass);


--
-- Name: new_members id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.new_members ALTER COLUMN id SET DEFAULT nextval('public.new_members_id_seq'::regclass);


--
-- Name: activity activity_pkey; Type: CONSTRAINT; Schema: portal; Owner: postgres
--

ALTER TABLE ONLY portal.activity
    ADD CONSTRAINT activity_pkey PRIMARY KEY (user_id);


--
-- Name: announcement_reads announcement_reads_pkey; Type: CONSTRAINT; Schema: portal; Owner: postgres
--

ALTER TABLE ONLY portal.announcement_reads
    ADD CONSTRAINT announcement_reads_pkey PRIMARY KEY (announcement_id, user_id);


--
-- Name: announcements announcements_pkey; Type: CONSTRAINT; Schema: portal; Owner: postgres
--

ALTER TABLE ONLY portal.announcements
    ADD CONSTRAINT announcements_pkey PRIMARY KEY (id);


--
-- Name: attachments attachments_pkey; Type: CONSTRAINT; Schema: portal; Owner: postgres
--

ALTER TABLE ONLY portal.attachments
    ADD CONSTRAINT attachments_pkey PRIMARY KEY (id);


--
-- Name: attachments attachments_storage_name_key; Type: CONSTRAINT; Schema: portal; Owner: postgres
--

ALTER TABLE ONLY portal.attachments
    ADD CONSTRAINT attachments_storage_name_key UNIQUE (storage_name);


--
-- Name: attendance attendance_pkey; Type: CONSTRAINT; Schema: portal; Owner: postgres
--

ALTER TABLE ONLY portal.attendance
    ADD CONSTRAINT attendance_pkey PRIMARY KEY (event_id, occurrence, user_id);


--
-- Name: events events_pkey; Type: CONSTRAINT; Schema: portal; Owner: postgres
--

ALTER TABLE ONLY portal.events
    ADD CONSTRAINT events_pkey PRIMARY KEY (id);


--
-- Name: mission_focus mission_focus_pkey; Type: CONSTRAINT; Schema: portal; Owner: postgres
--

ALTER TABLE ONLY portal.mission_focus
    ADD CONSTRAINT mission_focus_pkey PRIMARY KEY (mission_id, reporting_sunday);


--
-- Name: presentation_access presentation_access_pkey; Type: CONSTRAINT; Schema: portal; Owner: postgres
--

ALTER TABLE ONLY portal.presentation_access
    ADD CONSTRAINT presentation_access_pkey PRIMARY KEY (mission_id, deck_slug);


--
-- Name: push_subscriptions push_subscriptions_endpoint_key; Type: CONSTRAINT; Schema: portal; Owner: postgres
--

ALTER TABLE ONLY portal.push_subscriptions
    ADD CONSTRAINT push_subscriptions_endpoint_key UNIQUE (endpoint);


--
-- Name: push_subscriptions push_subscriptions_pkey; Type: CONSTRAINT; Schema: portal; Owner: postgres
--

ALTER TABLE ONLY portal.push_subscriptions
    ADD CONSTRAINT push_subscriptions_pkey PRIMARY KEY (id);


--
-- Name: reminder_deliveries reminder_deliveries_pkey; Type: CONSTRAINT; Schema: portal; Owner: postgres
--

ALTER TABLE ONLY portal.reminder_deliveries
    ADD CONSTRAINT reminder_deliveries_pkey PRIMARY KEY (user_id, kind, reference);


--
-- Name: user_preferences user_preferences_pkey; Type: CONSTRAINT; Schema: portal; Owner: postgres
--

ALTER TABLE ONLY portal.user_preferences
    ADD CONSTRAINT user_preferences_pkey PRIMARY KEY (user_id);


--
-- Name: whiteboard_files whiteboard_files_pkey; Type: CONSTRAINT; Schema: portal; Owner: postgres
--

ALTER TABLE ONLY portal.whiteboard_files
    ADD CONSTRAINT whiteboard_files_pkey PRIMARY KEY (board_id, file_id);


--
-- Name: whiteboards whiteboards_pkey; Type: CONSTRAINT; Schema: portal; Owner: postgres
--

ALTER TABLE ONLY portal.whiteboards
    ADD CONSTRAINT whiteboards_pkey PRIMARY KEY (id);


--
-- Name: archetype_notes archetype_notes_area_id_sunday_author_id_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.archetype_notes
    ADD CONSTRAINT archetype_notes_area_id_sunday_author_id_key UNIQUE (area_id, sunday, author_id);


--
-- Name: archetype_notes archetype_notes_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.archetype_notes
    ADD CONSTRAINT archetype_notes_pkey PRIMARY KEY (id);


--
-- Name: archetype_settings_history archetype_settings_history_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.archetype_settings_history
    ADD CONSTRAINT archetype_settings_history_pkey PRIMARY KEY (id);


--
-- Name: archetype_settings archetype_settings_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.archetype_settings
    ADD CONSTRAINT archetype_settings_pkey PRIMARY KEY (mission_id);


--
-- Name: area_profiles area_profiles_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.area_profiles
    ADD CONSTRAINT area_profiles_pkey PRIMARY KEY (area_id);


--
-- Name: area_units area_units_area_id_unit_id_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.area_units
    ADD CONSTRAINT area_units_area_id_unit_id_key UNIQUE (area_id, unit_id);


--
-- Name: area_units area_units_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.area_units
    ADD CONSTRAINT area_units_pkey PRIMARY KEY (id);


--
-- Name: areas areas_district_id_name_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.areas
    ADD CONSTRAINT areas_district_id_name_key UNIQUE (district_id, name);


--
-- Name: areas areas_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.areas
    ADD CONSTRAINT areas_pkey PRIMARY KEY (id);


--
-- Name: baptism_history_weeks baptism_history_weeks_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.baptism_history_weeks
    ADD CONSTRAINT baptism_history_weeks_pkey PRIMARY KEY (batch_id, sunday, zone_name, area_name, ward, finding_source);


--
-- Name: call_in_area_updates call_in_area_updates_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.call_in_area_updates
    ADD CONSTRAINT call_in_area_updates_pkey PRIMARY KEY (id);


--
-- Name: call_in_area_updates call_in_area_updates_unique; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.call_in_area_updates
    ADD CONSTRAINT call_in_area_updates_unique UNIQUE (district_call_in_id, area_id);


--
-- Name: call_in_districts call_in_districts_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.call_in_districts
    ADD CONSTRAINT call_in_districts_pkey PRIMARY KEY (id);


--
-- Name: call_in_districts call_in_districts_unique; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.call_in_districts
    ADD CONSTRAINT call_in_districts_unique UNIQUE (district_id, reporting_week_id);


--
-- Name: call_in_zones call_in_zones_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.call_in_zones
    ADD CONSTRAINT call_in_zones_pkey PRIMARY KEY (id);


--
-- Name: call_in_zones call_in_zones_zone_id_reporting_week_id_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.call_in_zones
    ADD CONSTRAINT call_in_zones_zone_id_reporting_week_id_key UNIQUE (zone_id, reporting_week_id);


--
-- Name: cleanup_029_revoked_grants cleanup_029_revoked_grants_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.cleanup_029_revoked_grants
    ADD CONSTRAINT cleanup_029_revoked_grants_pkey PRIMARY KEY (object_kind, object_name, grantee, privilege_type);


--
-- Name: cleanup_030_removed_rows cleanup_030_removed_rows_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.cleanup_030_removed_rows
    ADD CONSTRAINT cleanup_030_removed_rows_pkey PRIMARY KEY (table_name, row_id);


--
-- Name: companionship_members companionship_members_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.companionship_members
    ADD CONSTRAINT companionship_members_pkey PRIMARY KEY (companionship_id, missionary_id);


--
-- Name: companionships companionships_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.companionships
    ADD CONSTRAINT companionships_pkey PRIMARY KEY (id);


--
-- Name: data_name_matches data_name_matches_mission_id_level_source_key_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.data_name_matches
    ADD CONSTRAINT data_name_matches_mission_id_level_source_key_key UNIQUE (mission_id, level, source_key);


--
-- Name: data_name_matches data_name_matches_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.data_name_matches
    ADD CONSTRAINT data_name_matches_pkey PRIMARY KEY (id);


--
-- Name: districts districts_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.districts
    ADD CONSTRAINT districts_pkey PRIMARY KEY (id);


--
-- Name: districts districts_zone_id_name_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.districts
    ADD CONSTRAINT districts_zone_id_name_key UNIQUE (zone_id, name);


--
-- Name: finding_people finding_people_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.finding_people
    ADD CONSTRAINT finding_people_pkey PRIMARY KEY (batch_id, person_key);


--
-- Name: finding_rate_weeks finding_rate_weeks_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.finding_rate_weeks
    ADD CONSTRAINT finding_rate_weeks_pkey PRIMARY KEY (batch_id, report_date, zone_name);


--
-- Name: baptismal_date_person_area_assignments friend_area_assignments_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.baptismal_date_person_area_assignments
    ADD CONSTRAINT friend_area_assignments_pkey PRIMARY KEY (id);


--
-- Name: baptismal_date_people friends_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.baptismal_date_people
    ADD CONSTRAINT friends_pkey PRIMARY KEY (id);


--
-- Name: gfm_schema_migrations gfm_schema_migrations_migration_name_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.gfm_schema_migrations
    ADD CONSTRAINT gfm_schema_migrations_migration_name_key UNIQUE (migration_name);


--
-- Name: gfm_schema_migrations gfm_schema_migrations_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.gfm_schema_migrations
    ADD CONSTRAINT gfm_schema_migrations_pkey PRIMARY KEY (id);


--
-- Name: historical_planning_details historical_planning_details_pkey; Type: CONSTRAINT; Schema: public; Owner: supabase_admin
--

ALTER TABLE ONLY public.historical_planning_details
    ADD CONSTRAINT historical_planning_details_pkey PRIMARY KEY (weekly_area_report_id);


--
-- Name: import_weekly_planning_area_map import_weekly_planning_area_map_pkey; Type: CONSTRAINT; Schema: public; Owner: supabase_admin
--

ALTER TABLE ONLY public.import_weekly_planning_area_map
    ADD CONSTRAINT import_weekly_planning_area_map_pkey PRIMARY KEY (source_companionship);


--
-- Name: import_weekly_planning_reports import_weekly_planning_reports_pkey; Type: CONSTRAINT; Schema: public; Owner: supabase_admin
--

ALTER TABLE ONLY public.import_weekly_planning_reports
    ADD CONSTRAINT import_weekly_planning_reports_pkey PRIMARY KEY (source_report_key);


--
-- Name: leadership_assignments leadership_assignments_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.leadership_assignments
    ADD CONSTRAINT leadership_assignments_pkey PRIMARY KEY (id);


--
-- Name: missionaries missionaries_missionary_number_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.missionaries
    ADD CONSTRAINT missionaries_missionary_number_key UNIQUE (missionary_number);


--
-- Name: missionaries missionaries_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.missionaries
    ADD CONSTRAINT missionaries_pkey PRIMARY KEY (id);


--
-- Name: missionary_assignments missionary_assignments_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.missionary_assignments
    ADD CONSTRAINT missionary_assignments_pkey PRIMARY KEY (id);


--
-- Name: missionary_language_assignments missionary_language_assignments_pkey; Type: CONSTRAINT; Schema: public; Owner: supabase_admin
--

ALTER TABLE ONLY public.missionary_language_assignments
    ADD CONSTRAINT missionary_language_assignments_pkey PRIMARY KEY (missionary_id);


--
-- Name: missions missions_name_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.missions
    ADD CONSTRAINT missions_name_key UNIQUE (name);


--
-- Name: missions missions_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.missions
    ADD CONSTRAINT missions_pkey PRIMARY KEY (id);


--
-- Name: new_member_area_assignments new_member_area_assignments_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.new_member_area_assignments
    ADD CONSTRAINT new_member_area_assignments_pkey PRIMARY KEY (id);


--
-- Name: new_members new_members_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.new_members
    ADD CONSTRAINT new_members_pkey PRIMARY KEY (id);


--
-- Name: people_match_decisions people_match_decisions_mission_id_key_a_key_b_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.people_match_decisions
    ADD CONSTRAINT people_match_decisions_mission_id_key_a_key_b_key UNIQUE (mission_id, key_a, key_b);


--
-- Name: people_match_decisions people_match_decisions_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.people_match_decisions
    ADD CONSTRAINT people_match_decisions_pkey PRIMARY KEY (id);


--
-- Name: planning_catalog_changes planning_catalog_changes_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.planning_catalog_changes
    ADD CONSTRAINT planning_catalog_changes_pkey PRIMARY KEY (id);


--
-- Name: planning_catalog_version planning_catalog_version_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.planning_catalog_version
    ADD CONSTRAINT planning_catalog_version_pkey PRIMARY KEY (id);


--
-- Name: planning_question_grid_rows planning_question_grid_rows_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.planning_question_grid_rows
    ADD CONSTRAINT planning_question_grid_rows_pkey PRIMARY KEY (id);


--
-- Name: planning_question_grid_rows planning_question_grid_rows_question_id_row_key_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.planning_question_grid_rows
    ADD CONSTRAINT planning_question_grid_rows_question_id_row_key_key UNIQUE (question_id, row_key);


--
-- Name: planning_question_options planning_question_options_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.planning_question_options
    ADD CONSTRAINT planning_question_options_pkey PRIMARY KEY (id);


--
-- Name: planning_question_options planning_question_options_question_id_option_value_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.planning_question_options
    ADD CONSTRAINT planning_question_options_question_id_option_value_key UNIQUE (question_id, option_value);


--
-- Name: planning_question_sections planning_question_sections_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.planning_question_sections
    ADD CONSTRAINT planning_question_sections_pkey PRIMARY KEY (id);


--
-- Name: planning_question_sections planning_question_sections_section_key_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.planning_question_sections
    ADD CONSTRAINT planning_question_sections_section_key_key UNIQUE (section_key);


--
-- Name: planning_question_visibility_rules planning_question_visibility_rules_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.planning_question_visibility_rules
    ADD CONSTRAINT planning_question_visibility_rules_pkey PRIMARY KEY (id);


--
-- Name: planning_questions planning_questions_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.planning_questions
    ADD CONSTRAINT planning_questions_pkey PRIMARY KEY (id);


--
-- Name: planning_questions planning_questions_question_key_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.planning_questions
    ADD CONSTRAINT planning_questions_question_key_key UNIQUE (question_key);


--
-- Name: planning_question_visibility_rules planning_visibility_unique; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.planning_question_visibility_rules
    ADD CONSTRAINT planning_visibility_unique UNIQUE (child_question_key, parent_question_key);


--
-- Name: referral_archive_weeks referral_archive_weeks_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.referral_archive_weeks
    ADD CONSTRAINT referral_archive_weeks_pkey PRIMARY KEY (batch_id, report_date, zone_name, area_name, source);


--
-- Name: reporting_weeks reporting_weeks_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.reporting_weeks
    ADD CONSTRAINT reporting_weeks_pkey PRIMARY KEY (id);


--
-- Name: reporting_weeks reporting_weeks_sunday_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.reporting_weeks
    ADD CONSTRAINT reporting_weeks_sunday_key UNIQUE (sunday);


--
-- Name: roster_import_batches roster_import_batches_pkey; Type: CONSTRAINT; Schema: public; Owner: supabase_admin
--

ALTER TABLE ONLY public.roster_import_batches
    ADD CONSTRAINT roster_import_batches_pkey PRIMARY KEY (id);


--
-- Name: roster_import_changes roster_import_changes_pkey; Type: CONSTRAINT; Schema: public; Owner: supabase_admin
--

ALTER TABLE ONLY public.roster_import_changes
    ADD CONSTRAINT roster_import_changes_pkey PRIMARY KEY (batch_id, sequence);


--
-- Name: stakes stakes_mission_id_name_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.stakes
    ADD CONSTRAINT stakes_mission_id_name_key UNIQUE (mission_id, name);


--
-- Name: stakes stakes_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.stakes
    ADD CONSTRAINT stakes_pkey PRIMARY KEY (id);


--
-- Name: units units_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.units
    ADD CONSTRAINT units_pkey PRIMARY KEY (id);


--
-- Name: units units_stake_id_name_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.units
    ADD CONSTRAINT units_stake_id_name_key UNIQUE (stake_id, name);


--
-- Name: user_profiles user_profiles_missionary_id_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.user_profiles
    ADD CONSTRAINT user_profiles_missionary_id_key UNIQUE (missionary_id);


--
-- Name: user_profiles user_profiles_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.user_profiles
    ADD CONSTRAINT user_profiles_pkey PRIMARY KEY (id);


--
-- Name: weekly_area_reports weekly_area_reports_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.weekly_area_reports
    ADD CONSTRAINT weekly_area_reports_pkey PRIMARY KEY (id);


--
-- Name: weekly_baptismal_date_friends weekly_baptismal_date_friends_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.weekly_baptismal_date_friends
    ADD CONSTRAINT weekly_baptismal_date_friends_pkey PRIMARY KEY (id);


--
-- Name: weekly_high_potential_friends weekly_high_potential_friends_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.weekly_high_potential_friends
    ADD CONSTRAINT weekly_high_potential_friends_pkey PRIMARY KEY (id);


--
-- Name: weekly_new_members weekly_new_members_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.weekly_new_members
    ADD CONSTRAINT weekly_new_members_pkey PRIMARY KEY (id);


--
-- Name: weekly_planning_answers weekly_planning_answers_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.weekly_planning_answers
    ADD CONSTRAINT weekly_planning_answers_pkey PRIMARY KEY (id);


--
-- Name: weekly_planning_answers weekly_planning_answers_weekly_area_report_id_question_key_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.weekly_planning_answers
    ADD CONSTRAINT weekly_planning_answers_weekly_area_report_id_question_key_key UNIQUE (weekly_area_report_id, question_key);


--
-- Name: zone_history_weeks zone_history_weeks_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.zone_history_weeks
    ADD CONSTRAINT zone_history_weeks_pkey PRIMARY KEY (batch_id, sunday, zone_name);


--
-- Name: zones zones_mission_id_name_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.zones
    ADD CONSTRAINT zones_mission_id_name_key UNIQUE (mission_id, name);


--
-- Name: zones zones_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.zones
    ADD CONSTRAINT zones_pkey PRIMARY KEY (id);


--
-- Name: portal_announcements_mission; Type: INDEX; Schema: portal; Owner: postgres
--

CREATE INDEX portal_announcements_mission ON portal.announcements USING btree (mission_id, created_at DESC);


--
-- Name: portal_events_mission_start; Type: INDEX; Schema: portal; Owner: postgres
--

CREATE INDEX portal_events_mission_start ON portal.events USING btree (mission_id, starts_at);


--
-- Name: whiteboards_mission_name; Type: INDEX; Schema: portal; Owner: postgres
--

CREATE UNIQUE INDEX whiteboards_mission_name ON portal.whiteboards USING btree (mission_id, lower(name));


--
-- Name: archetype_notes_week_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX archetype_notes_week_idx ON public.archetype_notes USING btree (sunday, area_id);


--
-- Name: archetype_settings_history_mission_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX archetype_settings_history_mission_idx ON public.archetype_settings_history USING btree (mission_id, changed_at DESC);


--
-- Name: area_units_area_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX area_units_area_idx ON public.area_units USING btree (area_id);


--
-- Name: area_units_unit_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX area_units_unit_idx ON public.area_units USING btree (unit_id);


--
-- Name: baptism_history_weeks_week_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX baptism_history_weeks_week_idx ON public.baptism_history_weeks USING btree (mission_id, sunday);


--
-- Name: baptismal_date_person_one_current_area_unique; Type: INDEX; Schema: public; Owner: postgres
--

CREATE UNIQUE INDEX baptismal_date_person_one_current_area_unique ON public.baptismal_date_person_area_assignments USING btree (baptismal_date_person_id) WHERE (end_date IS NULL);


--
-- Name: call_in_area_updates_area_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX call_in_area_updates_area_idx ON public.call_in_area_updates USING btree (area_id);


--
-- Name: call_in_area_updates_call_in_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX call_in_area_updates_call_in_idx ON public.call_in_area_updates USING btree (district_call_in_id);


--
-- Name: call_in_districts_district_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX call_in_districts_district_idx ON public.call_in_districts USING btree (district_id);


--
-- Name: call_in_districts_week_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX call_in_districts_week_idx ON public.call_in_districts USING btree (reporting_week_id);


--
-- Name: finding_people_person_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX finding_people_person_idx ON public.finding_people USING btree (mission_id, person_key);


--
-- Name: finding_rate_weeks_week_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX finding_rate_weeks_week_idx ON public.finding_rate_weeks USING btree (mission_id, sunday);


--
-- Name: idx_areas_area_code; Type: INDEX; Schema: public; Owner: postgres
--

CREATE UNIQUE INDEX idx_areas_area_code ON public.areas USING btree (area_code) WHERE (area_code IS NOT NULL);


--
-- Name: idx_baptismal_date_people_display_name; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_baptismal_date_people_display_name ON public.baptismal_date_people USING btree (display_name);


--
-- Name: idx_baptismal_date_person_assignments_area; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_baptismal_date_person_assignments_area ON public.baptismal_date_person_area_assignments USING btree (area_id);


--
-- Name: idx_baptismal_date_person_assignments_person; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_baptismal_date_person_assignments_person ON public.baptismal_date_person_area_assignments USING btree (baptismal_date_person_id);


--
-- Name: idx_baptismal_date_person_assignments_unit; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_baptismal_date_person_assignments_unit ON public.baptismal_date_person_area_assignments USING btree (unit_id);


--
-- Name: idx_companionship_members_missionary; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_companionship_members_missionary ON public.companionship_members USING btree (missionary_id);


--
-- Name: idx_companionships_area; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_companionships_area ON public.companionships USING btree (area_id);


--
-- Name: idx_companionships_dates; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_companionships_dates ON public.companionships USING btree (start_date, end_date);


--
-- Name: idx_leadership_assignments_district; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_leadership_assignments_district ON public.leadership_assignments USING btree (district_id);


--
-- Name: idx_leadership_assignments_mission; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_leadership_assignments_mission ON public.leadership_assignments USING btree (mission_id);


--
-- Name: idx_leadership_assignments_missionary; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_leadership_assignments_missionary ON public.leadership_assignments USING btree (missionary_id);


--
-- Name: idx_leadership_assignments_zone; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_leadership_assignments_zone ON public.leadership_assignments USING btree (zone_id);


--
-- Name: idx_missionaries_status; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_missionaries_status ON public.missionaries USING btree (status);


--
-- Name: idx_missionary_assignments_area; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_missionary_assignments_area ON public.missionary_assignments USING btree (area_id);


--
-- Name: idx_missionary_assignments_dates; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_missionary_assignments_dates ON public.missionary_assignments USING btree (start_date, end_date);


--
-- Name: idx_missionary_assignments_missionary; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_missionary_assignments_missionary ON public.missionary_assignments USING btree (missionary_id);


--
-- Name: idx_new_member_area_assignments_area; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_new_member_area_assignments_area ON public.new_member_area_assignments USING btree (area_id);


--
-- Name: idx_new_member_area_assignments_member; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_new_member_area_assignments_member ON public.new_member_area_assignments USING btree (new_member_id);


--
-- Name: idx_new_member_area_assignments_unit; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_new_member_area_assignments_unit ON public.new_member_area_assignments USING btree (unit_id);


--
-- Name: idx_new_members_active; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_new_members_active ON public.new_members USING btree (active);


--
-- Name: idx_new_members_area_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_new_members_area_id ON public.new_members USING btree (area_id);


--
-- Name: idx_new_members_created_by; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_new_members_created_by ON public.new_members USING btree (created_by);


--
-- Name: idx_new_members_stake_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_new_members_stake_id ON public.new_members USING btree (stake_id);


--
-- Name: idx_new_members_unit_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_new_members_unit_id ON public.new_members USING btree (unit_id);


--
-- Name: idx_user_profiles_missionary_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_user_profiles_missionary_id ON public.user_profiles USING btree (missionary_id);


--
-- Name: idx_weekly_area_reports_area; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_weekly_area_reports_area ON public.weekly_area_reports USING btree (area_id);


--
-- Name: idx_weekly_area_reports_status; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_weekly_area_reports_status ON public.weekly_area_reports USING btree (status);


--
-- Name: idx_weekly_area_reports_week; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_weekly_area_reports_week ON public.weekly_area_reports USING btree (reporting_week_id);


--
-- Name: idx_weekly_baptismal_date_friends_person; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_weekly_baptismal_date_friends_person ON public.weekly_baptismal_date_friends USING btree (baptismal_date_person_id);


--
-- Name: idx_weekly_new_members_new_member_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_weekly_new_members_new_member_id ON public.weekly_new_members USING btree (new_member_id);


--
-- Name: missionaries_email_lower_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX missionaries_email_lower_idx ON public.missionaries USING btree (lower(email)) WHERE ((email IS NOT NULL) AND (email <> ''::text));


--
-- Name: new_member_one_current_area_unique; Type: INDEX; Schema: public; Owner: postgres
--

CREATE UNIQUE INDEX new_member_one_current_area_unique ON public.new_member_area_assignments USING btree (new_member_id) WHERE (end_date IS NULL);


--
-- Name: new_members_baptismal_date_person_unique; Type: INDEX; Schema: public; Owner: postgres
--

CREATE UNIQUE INDEX new_members_baptismal_date_person_unique ON public.new_members USING btree (baptismal_date_person_id) WHERE (baptismal_date_person_id IS NOT NULL);


--
-- Name: planning_catalog_changes_changed_at_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX planning_catalog_changes_changed_at_idx ON public.planning_catalog_changes USING btree (changed_at DESC, id DESC);


--
-- Name: planning_question_grid_rows_question_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX planning_question_grid_rows_question_idx ON public.planning_question_grid_rows USING btree (question_id, display_order);


--
-- Name: planning_question_options_question_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX planning_question_options_question_idx ON public.planning_question_options USING btree (question_id, display_order);


--
-- Name: planning_questions_section_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX planning_questions_section_idx ON public.planning_questions USING btree (section_id, display_order);


--
-- Name: planning_visibility_child_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX planning_visibility_child_idx ON public.planning_question_visibility_rules USING btree (child_question_key);


--
-- Name: planning_visibility_parent_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX planning_visibility_parent_idx ON public.planning_question_visibility_rules USING btree (parent_question_key);


--
-- Name: referral_archive_weeks_week_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX referral_archive_weeks_week_idx ON public.referral_archive_weeks USING btree (mission_id, sunday);


--
-- Name: units_unit_number_unique_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE UNIQUE INDEX units_unit_number_unique_idx ON public.units USING btree (unit_number) WHERE ((unit_number IS NOT NULL) AND (unit_number <> ''::text));


--
-- Name: weekly_area_reports_area_unit_week_uidx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE UNIQUE INDEX weekly_area_reports_area_unit_week_uidx ON public.weekly_area_reports USING btree (area_id, unit_id, reporting_week_id);


--
-- Name: weekly_area_reports_historical_source_key_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE UNIQUE INDEX weekly_area_reports_historical_source_key_idx ON public.weekly_area_reports USING btree (historical_source_key) WHERE (historical_source_key IS NOT NULL);


--
-- Name: weekly_baptismal_date_person_unique; Type: INDEX; Schema: public; Owner: postgres
--

CREATE UNIQUE INDEX weekly_baptismal_date_person_unique ON public.weekly_baptismal_date_friends USING btree (weekly_area_report_id, baptismal_date_person_id) WHERE (baptismal_date_person_id IS NOT NULL);


--
-- Name: weekly_bd_friends_report_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX weekly_bd_friends_report_idx ON public.weekly_baptismal_date_friends USING btree (weekly_area_report_id);


--
-- Name: weekly_high_potential_report_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX weekly_high_potential_report_idx ON public.weekly_high_potential_friends USING btree (weekly_area_report_id);


--
-- Name: weekly_new_members_report_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX weekly_new_members_report_idx ON public.weekly_new_members USING btree (weekly_area_report_id);


--
-- Name: weekly_new_members_report_member_unique; Type: INDEX; Schema: public; Owner: postgres
--

CREATE UNIQUE INDEX weekly_new_members_report_member_unique ON public.weekly_new_members USING btree (weekly_area_report_id, new_member_id) WHERE (new_member_id IS NOT NULL);


--
-- Name: weekly_planning_answers_question_key_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX weekly_planning_answers_question_key_idx ON public.weekly_planning_answers USING btree (question_key);


--
-- Name: zone_history_weeks_week_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX zone_history_weeks_week_idx ON public.zone_history_weeks USING btree (mission_id, sunday);


--
-- Name: presentation_access presentation_access_updated_at; Type: TRIGGER; Schema: portal; Owner: postgres
--

CREATE TRIGGER presentation_access_updated_at BEFORE UPDATE ON portal.presentation_access FOR EACH ROW EXECUTE FUNCTION portal.touch_presentation_access();


--
-- Name: call_in_area_updates call_in_area_updates_write_guard; Type: TRIGGER; Schema: public; Owner: postgres
--

CREATE TRIGGER call_in_area_updates_write_guard BEFORE INSERT OR DELETE OR UPDATE ON public.call_in_area_updates FOR EACH ROW EXECUTE FUNCTION public.guard_call_in_write();


--
-- Name: call_in_districts call_in_districts_write_guard; Type: TRIGGER; Schema: public; Owner: postgres
--

CREATE TRIGGER call_in_districts_write_guard BEFORE INSERT OR DELETE OR UPDATE ON public.call_in_districts FOR EACH ROW EXECUTE FUNCTION public.guard_call_in_write();


--
-- Name: call_in_zones call_in_zones_write_guard; Type: TRIGGER; Schema: public; Owner: postgres
--

CREATE TRIGGER call_in_zones_write_guard BEFORE INSERT OR DELETE OR UPDATE ON public.call_in_zones FOR EACH ROW EXECUTE FUNCTION public.guard_call_in_write();


--
-- Name: planning_question_grid_rows planning_catalog_guard; Type: TRIGGER; Schema: public; Owner: postgres
--

CREATE TRIGGER planning_catalog_guard BEFORE INSERT OR DELETE OR UPDATE ON public.planning_question_grid_rows FOR EACH ROW EXECUTE FUNCTION public.planning_question_grid_rows_guard();


--
-- Name: planning_question_options planning_catalog_guard; Type: TRIGGER; Schema: public; Owner: postgres
--

CREATE TRIGGER planning_catalog_guard BEFORE INSERT OR DELETE OR UPDATE ON public.planning_question_options FOR EACH ROW EXECUTE FUNCTION public.planning_question_options_guard();


--
-- Name: planning_question_sections planning_catalog_guard; Type: TRIGGER; Schema: public; Owner: postgres
--

CREATE TRIGGER planning_catalog_guard BEFORE DELETE OR UPDATE ON public.planning_question_sections FOR EACH ROW EXECUTE FUNCTION public.planning_question_sections_guard();


--
-- Name: planning_question_visibility_rules planning_catalog_guard; Type: TRIGGER; Schema: public; Owner: postgres
--

CREATE TRIGGER planning_catalog_guard BEFORE INSERT OR DELETE OR UPDATE ON public.planning_question_visibility_rules FOR EACH ROW EXECUTE FUNCTION public.planning_visibility_rules_guard();


--
-- Name: planning_questions planning_catalog_guard; Type: TRIGGER; Schema: public; Owner: postgres
--

CREATE TRIGGER planning_catalog_guard BEFORE INSERT OR DELETE OR UPDATE ON public.planning_questions FOR EACH ROW EXECUTE FUNCTION public.planning_questions_guard();


--
-- Name: planning_question_grid_rows planning_catalog_no_truncate; Type: TRIGGER; Schema: public; Owner: postgres
--

CREATE TRIGGER planning_catalog_no_truncate BEFORE TRUNCATE ON public.planning_question_grid_rows FOR EACH STATEMENT EXECUTE FUNCTION public.planning_catalog_no_truncate();


--
-- Name: planning_question_options planning_catalog_no_truncate; Type: TRIGGER; Schema: public; Owner: postgres
--

CREATE TRIGGER planning_catalog_no_truncate BEFORE TRUNCATE ON public.planning_question_options FOR EACH STATEMENT EXECUTE FUNCTION public.planning_catalog_no_truncate();


--
-- Name: planning_question_sections planning_catalog_no_truncate; Type: TRIGGER; Schema: public; Owner: postgres
--

CREATE TRIGGER planning_catalog_no_truncate BEFORE TRUNCATE ON public.planning_question_sections FOR EACH STATEMENT EXECUTE FUNCTION public.planning_catalog_no_truncate();


--
-- Name: planning_question_visibility_rules planning_catalog_no_truncate; Type: TRIGGER; Schema: public; Owner: postgres
--

CREATE TRIGGER planning_catalog_no_truncate BEFORE TRUNCATE ON public.planning_question_visibility_rules FOR EACH STATEMENT EXECUTE FUNCTION public.planning_catalog_no_truncate();


--
-- Name: planning_questions planning_catalog_no_truncate; Type: TRIGGER; Schema: public; Owner: postgres
--

CREATE TRIGGER planning_catalog_no_truncate BEFORE TRUNCATE ON public.planning_questions FOR EACH STATEMENT EXECUTE FUNCTION public.planning_catalog_no_truncate();


--
-- Name: planning_question_grid_rows planning_catalog_touch; Type: TRIGGER; Schema: public; Owner: postgres
--

CREATE TRIGGER planning_catalog_touch BEFORE UPDATE ON public.planning_question_grid_rows FOR EACH ROW EXECUTE FUNCTION public.planning_catalog_touch();


--
-- Name: planning_question_options planning_catalog_touch; Type: TRIGGER; Schema: public; Owner: postgres
--

CREATE TRIGGER planning_catalog_touch BEFORE UPDATE ON public.planning_question_options FOR EACH ROW EXECUTE FUNCTION public.planning_catalog_touch();


--
-- Name: planning_question_sections planning_catalog_touch; Type: TRIGGER; Schema: public; Owner: postgres
--

CREATE TRIGGER planning_catalog_touch BEFORE UPDATE ON public.planning_question_sections FOR EACH ROW EXECUTE FUNCTION public.planning_catalog_touch();


--
-- Name: planning_question_visibility_rules planning_catalog_touch; Type: TRIGGER; Schema: public; Owner: postgres
--

CREATE TRIGGER planning_catalog_touch BEFORE UPDATE ON public.planning_question_visibility_rules FOR EACH ROW EXECUTE FUNCTION public.planning_catalog_touch();


--
-- Name: planning_questions planning_catalog_touch; Type: TRIGGER; Schema: public; Owner: postgres
--

CREATE TRIGGER planning_catalog_touch BEFORE UPDATE ON public.planning_questions FOR EACH ROW EXECUTE FUNCTION public.planning_catalog_touch();


--
-- Name: planning_question_grid_rows planning_catalog_version; Type: TRIGGER; Schema: public; Owner: postgres
--

CREATE TRIGGER planning_catalog_version AFTER INSERT OR DELETE OR UPDATE OR TRUNCATE ON public.planning_question_grid_rows FOR EACH STATEMENT EXECUTE FUNCTION public.planning_catalog_bump_version();


--
-- Name: planning_question_options planning_catalog_version; Type: TRIGGER; Schema: public; Owner: postgres
--

CREATE TRIGGER planning_catalog_version AFTER INSERT OR DELETE OR UPDATE OR TRUNCATE ON public.planning_question_options FOR EACH STATEMENT EXECUTE FUNCTION public.planning_catalog_bump_version();


--
-- Name: planning_question_sections planning_catalog_version; Type: TRIGGER; Schema: public; Owner: postgres
--

CREATE TRIGGER planning_catalog_version AFTER INSERT OR DELETE OR UPDATE OR TRUNCATE ON public.planning_question_sections FOR EACH STATEMENT EXECUTE FUNCTION public.planning_catalog_bump_version();


--
-- Name: planning_question_visibility_rules planning_catalog_version; Type: TRIGGER; Schema: public; Owner: postgres
--

CREATE TRIGGER planning_catalog_version AFTER INSERT OR DELETE OR UPDATE OR TRUNCATE ON public.planning_question_visibility_rules FOR EACH STATEMENT EXECUTE FUNCTION public.planning_catalog_bump_version();


--
-- Name: planning_questions planning_catalog_version; Type: TRIGGER; Schema: public; Owner: postgres
--

CREATE TRIGGER planning_catalog_version AFTER INSERT OR DELETE OR UPDATE OR TRUNCATE ON public.planning_questions FOR EACH STATEMENT EXECUTE FUNCTION public.planning_catalog_bump_version();


--
-- Name: weekly_baptismal_date_friends portal_guard_shared_child; Type: TRIGGER; Schema: public; Owner: postgres
--

CREATE TRIGGER portal_guard_shared_child BEFORE INSERT OR DELETE OR UPDATE ON public.weekly_baptismal_date_friends FOR EACH ROW EXECUTE FUNCTION public.guard_shared_planning_child();


--
-- Name: weekly_high_potential_friends portal_guard_shared_child; Type: TRIGGER; Schema: public; Owner: postgres
--

CREATE TRIGGER portal_guard_shared_child BEFORE INSERT OR DELETE OR UPDATE ON public.weekly_high_potential_friends FOR EACH ROW EXECUTE FUNCTION public.guard_shared_planning_child();


--
-- Name: weekly_new_members portal_guard_shared_child; Type: TRIGGER; Schema: public; Owner: postgres
--

CREATE TRIGGER portal_guard_shared_child BEFORE INSERT OR DELETE OR UPDATE ON public.weekly_new_members FOR EACH ROW EXECUTE FUNCTION public.guard_shared_planning_child();


--
-- Name: weekly_planning_answers portal_guard_shared_child; Type: TRIGGER; Schema: public; Owner: postgres
--

CREATE TRIGGER portal_guard_shared_child BEFORE INSERT OR DELETE OR UPDATE ON public.weekly_planning_answers FOR EACH ROW EXECUTE FUNCTION public.guard_shared_planning_child();


--
-- Name: weekly_area_reports portal_guard_shared_report; Type: TRIGGER; Schema: public; Owner: postgres
--

CREATE TRIGGER portal_guard_shared_report BEFORE INSERT OR DELETE OR UPDATE ON public.weekly_area_reports FOR EACH ROW EXECUTE FUNCTION public.guard_shared_planning_report();


--
-- Name: weekly_baptismal_date_friends trg_fill_weekly_baptismal_date_context; Type: TRIGGER; Schema: public; Owner: postgres
--

CREATE TRIGGER trg_fill_weekly_baptismal_date_context BEFORE INSERT OR UPDATE OF baptismal_date_person_id, weekly_area_report_id ON public.weekly_baptismal_date_friends FOR EACH ROW EXECUTE FUNCTION public.fill_weekly_baptismal_date_context();


--
-- Name: baptismal_date_people trg_sync_baptismal_date_person_display_name; Type: TRIGGER; Schema: public; Owner: postgres
--

CREATE TRIGGER trg_sync_baptismal_date_person_display_name BEFORE INSERT OR UPDATE ON public.baptismal_date_people FOR EACH ROW EXECUTE FUNCTION public.sync_baptismal_date_person_display_name();


--
-- Name: new_members trg_sync_new_member_display_name; Type: TRIGGER; Schema: public; Owner: postgres
--

CREATE TRIGGER trg_sync_new_member_display_name BEFORE INSERT OR UPDATE ON public.new_members FOR EACH ROW EXECUTE FUNCTION public.sync_new_member_display_name();


--
-- Name: activity activity_user_id_fkey; Type: FK CONSTRAINT; Schema: portal; Owner: postgres
--

ALTER TABLE ONLY portal.activity
    ADD CONSTRAINT activity_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.user_profiles(id) ON DELETE CASCADE;


--
-- Name: announcement_reads announcement_reads_announcement_id_fkey; Type: FK CONSTRAINT; Schema: portal; Owner: postgres
--

ALTER TABLE ONLY portal.announcement_reads
    ADD CONSTRAINT announcement_reads_announcement_id_fkey FOREIGN KEY (announcement_id) REFERENCES portal.announcements(id) ON DELETE CASCADE;


--
-- Name: announcement_reads announcement_reads_user_id_fkey; Type: FK CONSTRAINT; Schema: portal; Owner: postgres
--

ALTER TABLE ONLY portal.announcement_reads
    ADD CONSTRAINT announcement_reads_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.user_profiles(id) ON DELETE CASCADE;


--
-- Name: announcements announcements_author_id_fkey; Type: FK CONSTRAINT; Schema: portal; Owner: postgres
--

ALTER TABLE ONLY portal.announcements
    ADD CONSTRAINT announcements_author_id_fkey FOREIGN KEY (author_id) REFERENCES public.user_profiles(id);


--
-- Name: announcements announcements_mission_id_fkey; Type: FK CONSTRAINT; Schema: portal; Owner: postgres
--

ALTER TABLE ONLY portal.announcements
    ADD CONSTRAINT announcements_mission_id_fkey FOREIGN KEY (mission_id) REFERENCES public.missions(id);


--
-- Name: attachments attachments_announcement_id_fkey; Type: FK CONSTRAINT; Schema: portal; Owner: postgres
--

ALTER TABLE ONLY portal.attachments
    ADD CONSTRAINT attachments_announcement_id_fkey FOREIGN KEY (announcement_id) REFERENCES portal.announcements(id) ON DELETE CASCADE;


--
-- Name: attachments attachments_event_id_fkey; Type: FK CONSTRAINT; Schema: portal; Owner: postgres
--

ALTER TABLE ONLY portal.attachments
    ADD CONSTRAINT attachments_event_id_fkey FOREIGN KEY (event_id) REFERENCES portal.events(id) ON DELETE CASCADE;


--
-- Name: attendance attendance_event_id_fkey; Type: FK CONSTRAINT; Schema: portal; Owner: postgres
--

ALTER TABLE ONLY portal.attendance
    ADD CONSTRAINT attendance_event_id_fkey FOREIGN KEY (event_id) REFERENCES portal.events(id) ON DELETE CASCADE;


--
-- Name: attendance attendance_recorded_by_fkey; Type: FK CONSTRAINT; Schema: portal; Owner: postgres
--

ALTER TABLE ONLY portal.attendance
    ADD CONSTRAINT attendance_recorded_by_fkey FOREIGN KEY (recorded_by) REFERENCES public.user_profiles(id);


--
-- Name: attendance attendance_user_id_fkey; Type: FK CONSTRAINT; Schema: portal; Owner: postgres
--

ALTER TABLE ONLY portal.attendance
    ADD CONSTRAINT attendance_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.user_profiles(id);


--
-- Name: events events_author_id_fkey; Type: FK CONSTRAINT; Schema: portal; Owner: postgres
--

ALTER TABLE ONLY portal.events
    ADD CONSTRAINT events_author_id_fkey FOREIGN KEY (author_id) REFERENCES public.user_profiles(id);


--
-- Name: events events_mission_id_fkey; Type: FK CONSTRAINT; Schema: portal; Owner: postgres
--

ALTER TABLE ONLY portal.events
    ADD CONSTRAINT events_mission_id_fkey FOREIGN KEY (mission_id) REFERENCES public.missions(id);


--
-- Name: mission_focus mission_focus_mission_id_fkey; Type: FK CONSTRAINT; Schema: portal; Owner: postgres
--

ALTER TABLE ONLY portal.mission_focus
    ADD CONSTRAINT mission_focus_mission_id_fkey FOREIGN KEY (mission_id) REFERENCES public.missions(id) ON DELETE CASCADE;


--
-- Name: mission_focus mission_focus_updated_by_fkey; Type: FK CONSTRAINT; Schema: portal; Owner: postgres
--

ALTER TABLE ONLY portal.mission_focus
    ADD CONSTRAINT mission_focus_updated_by_fkey FOREIGN KEY (updated_by) REFERENCES public.user_profiles(id);


--
-- Name: presentation_access presentation_access_created_by_fkey; Type: FK CONSTRAINT; Schema: portal; Owner: postgres
--

ALTER TABLE ONLY portal.presentation_access
    ADD CONSTRAINT presentation_access_created_by_fkey FOREIGN KEY (created_by) REFERENCES auth.users(id) ON DELETE SET NULL;


--
-- Name: presentation_access presentation_access_mission_id_fkey; Type: FK CONSTRAINT; Schema: portal; Owner: postgres
--

ALTER TABLE ONLY portal.presentation_access
    ADD CONSTRAINT presentation_access_mission_id_fkey FOREIGN KEY (mission_id) REFERENCES public.missions(id);


--
-- Name: presentation_access presentation_access_owner_zone_id_fkey; Type: FK CONSTRAINT; Schema: portal; Owner: postgres
--

ALTER TABLE ONLY portal.presentation_access
    ADD CONSTRAINT presentation_access_owner_zone_id_fkey FOREIGN KEY (owner_zone_id) REFERENCES public.zones(id) ON DELETE SET NULL;


--
-- Name: presentation_access presentation_access_updated_by_fkey; Type: FK CONSTRAINT; Schema: portal; Owner: postgres
--

ALTER TABLE ONLY portal.presentation_access
    ADD CONSTRAINT presentation_access_updated_by_fkey FOREIGN KEY (updated_by) REFERENCES auth.users(id) ON DELETE SET NULL;


--
-- Name: push_subscriptions push_subscriptions_user_id_fkey; Type: FK CONSTRAINT; Schema: portal; Owner: postgres
--

ALTER TABLE ONLY portal.push_subscriptions
    ADD CONSTRAINT push_subscriptions_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.user_profiles(id) ON DELETE CASCADE;


--
-- Name: user_preferences user_preferences_user_id_fkey; Type: FK CONSTRAINT; Schema: portal; Owner: postgres
--

ALTER TABLE ONLY portal.user_preferences
    ADD CONSTRAINT user_preferences_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.user_profiles(id) ON DELETE CASCADE;


--
-- Name: whiteboard_files whiteboard_files_board_id_fkey; Type: FK CONSTRAINT; Schema: portal; Owner: postgres
--

ALTER TABLE ONLY portal.whiteboard_files
    ADD CONSTRAINT whiteboard_files_board_id_fkey FOREIGN KEY (board_id) REFERENCES portal.whiteboards(id) ON DELETE CASCADE;


--
-- Name: whiteboard_files whiteboard_files_created_by_fkey; Type: FK CONSTRAINT; Schema: portal; Owner: postgres
--

ALTER TABLE ONLY portal.whiteboard_files
    ADD CONSTRAINT whiteboard_files_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.user_profiles(id) ON DELETE SET NULL;


--
-- Name: whiteboards whiteboards_created_by_fkey; Type: FK CONSTRAINT; Schema: portal; Owner: postgres
--

ALTER TABLE ONLY portal.whiteboards
    ADD CONSTRAINT whiteboards_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.user_profiles(id) ON DELETE SET NULL;


--
-- Name: whiteboards whiteboards_mission_id_fkey; Type: FK CONSTRAINT; Schema: portal; Owner: postgres
--

ALTER TABLE ONLY portal.whiteboards
    ADD CONSTRAINT whiteboards_mission_id_fkey FOREIGN KEY (mission_id) REFERENCES public.missions(id) ON DELETE CASCADE;


--
-- Name: whiteboards whiteboards_updated_by_fkey; Type: FK CONSTRAINT; Schema: portal; Owner: postgres
--

ALTER TABLE ONLY portal.whiteboards
    ADD CONSTRAINT whiteboards_updated_by_fkey FOREIGN KEY (updated_by) REFERENCES public.user_profiles(id) ON DELETE SET NULL;


--
-- Name: archetype_notes archetype_notes_area_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.archetype_notes
    ADD CONSTRAINT archetype_notes_area_id_fkey FOREIGN KEY (area_id) REFERENCES public.areas(id) ON DELETE CASCADE;


--
-- Name: archetype_settings_history archetype_settings_history_mission_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.archetype_settings_history
    ADD CONSTRAINT archetype_settings_history_mission_id_fkey FOREIGN KEY (mission_id) REFERENCES public.missions(id) ON DELETE CASCADE;


--
-- Name: archetype_settings archetype_settings_mission_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.archetype_settings
    ADD CONSTRAINT archetype_settings_mission_id_fkey FOREIGN KEY (mission_id) REFERENCES public.missions(id) ON DELETE CASCADE;


--
-- Name: area_profiles area_profiles_area_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.area_profiles
    ADD CONSTRAINT area_profiles_area_id_fkey FOREIGN KEY (area_id) REFERENCES public.areas(id) ON DELETE CASCADE;


--
-- Name: area_units area_units_area_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.area_units
    ADD CONSTRAINT area_units_area_id_fkey FOREIGN KEY (area_id) REFERENCES public.areas(id) ON DELETE CASCADE;


--
-- Name: area_units area_units_unit_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.area_units
    ADD CONSTRAINT area_units_unit_id_fkey FOREIGN KEY (unit_id) REFERENCES public.units(id) ON DELETE CASCADE;


--
-- Name: areas areas_district_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.areas
    ADD CONSTRAINT areas_district_id_fkey FOREIGN KEY (district_id) REFERENCES public.districts(id) ON DELETE RESTRICT;


--
-- Name: areas areas_unit_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.areas
    ADD CONSTRAINT areas_unit_id_fkey FOREIGN KEY (unit_id) REFERENCES public.units(id) ON DELETE SET NULL;


--
-- Name: baptism_history_weeks baptism_history_weeks_area_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.baptism_history_weeks
    ADD CONSTRAINT baptism_history_weeks_area_id_fkey FOREIGN KEY (area_id) REFERENCES public.areas(id);


--
-- Name: baptism_history_weeks baptism_history_weeks_batch_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.baptism_history_weeks
    ADD CONSTRAINT baptism_history_weeks_batch_id_fkey FOREIGN KEY (batch_id) REFERENCES public.roster_import_batches(id) ON DELETE CASCADE;


--
-- Name: baptism_history_weeks baptism_history_weeks_mission_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.baptism_history_weeks
    ADD CONSTRAINT baptism_history_weeks_mission_id_fkey FOREIGN KEY (mission_id) REFERENCES public.missions(id);


--
-- Name: baptism_history_weeks baptism_history_weeks_zone_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.baptism_history_weeks
    ADD CONSTRAINT baptism_history_weeks_zone_id_fkey FOREIGN KEY (zone_id) REFERENCES public.zones(id);


--
-- Name: baptismal_date_person_area_assignments baptismal_date_person_area_assignments_unit_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.baptismal_date_person_area_assignments
    ADD CONSTRAINT baptismal_date_person_area_assignments_unit_id_fkey FOREIGN KEY (unit_id) REFERENCES public.units(id) ON DELETE RESTRICT;


--
-- Name: call_in_area_updates call_in_area_updates_area_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.call_in_area_updates
    ADD CONSTRAINT call_in_area_updates_area_fkey FOREIGN KEY (area_id) REFERENCES public.areas(id) ON DELETE CASCADE;


--
-- Name: call_in_area_updates call_in_area_updates_call_in_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.call_in_area_updates
    ADD CONSTRAINT call_in_area_updates_call_in_fkey FOREIGN KEY (district_call_in_id) REFERENCES public.call_in_districts(id) ON DELETE CASCADE;


--
-- Name: call_in_districts call_in_districts_district_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.call_in_districts
    ADD CONSTRAINT call_in_districts_district_fkey FOREIGN KEY (district_id) REFERENCES public.districts(id) ON DELETE CASCADE;


--
-- Name: call_in_districts call_in_districts_reporting_week_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.call_in_districts
    ADD CONSTRAINT call_in_districts_reporting_week_fkey FOREIGN KEY (reporting_week_id) REFERENCES public.reporting_weeks(id) ON DELETE CASCADE;


--
-- Name: call_in_zones call_in_zones_reporting_week_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.call_in_zones
    ADD CONSTRAINT call_in_zones_reporting_week_id_fkey FOREIGN KEY (reporting_week_id) REFERENCES public.reporting_weeks(id) ON DELETE CASCADE;


--
-- Name: call_in_zones call_in_zones_zone_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.call_in_zones
    ADD CONSTRAINT call_in_zones_zone_id_fkey FOREIGN KEY (zone_id) REFERENCES public.zones(id) ON DELETE CASCADE;


--
-- Name: companionship_members companionship_members_companionship_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.companionship_members
    ADD CONSTRAINT companionship_members_companionship_id_fkey FOREIGN KEY (companionship_id) REFERENCES public.companionships(id) ON DELETE CASCADE;


--
-- Name: companionship_members companionship_members_missionary_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.companionship_members
    ADD CONSTRAINT companionship_members_missionary_id_fkey FOREIGN KEY (missionary_id) REFERENCES public.missionaries(id) ON DELETE CASCADE;


--
-- Name: companionships companionships_area_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.companionships
    ADD CONSTRAINT companionships_area_id_fkey FOREIGN KEY (area_id) REFERENCES public.areas(id) ON DELETE RESTRICT;


--
-- Name: data_name_matches data_name_matches_area_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.data_name_matches
    ADD CONSTRAINT data_name_matches_area_id_fkey FOREIGN KEY (area_id) REFERENCES public.areas(id);


--
-- Name: data_name_matches data_name_matches_mission_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.data_name_matches
    ADD CONSTRAINT data_name_matches_mission_id_fkey FOREIGN KEY (mission_id) REFERENCES public.missions(id);


--
-- Name: data_name_matches data_name_matches_zone_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.data_name_matches
    ADD CONSTRAINT data_name_matches_zone_id_fkey FOREIGN KEY (zone_id) REFERENCES public.zones(id);


--
-- Name: districts districts_zone_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.districts
    ADD CONSTRAINT districts_zone_id_fkey FOREIGN KEY (zone_id) REFERENCES public.zones(id) ON DELETE CASCADE;


--
-- Name: finding_people finding_people_area_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.finding_people
    ADD CONSTRAINT finding_people_area_id_fkey FOREIGN KEY (area_id) REFERENCES public.areas(id);


--
-- Name: finding_people finding_people_batch_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.finding_people
    ADD CONSTRAINT finding_people_batch_id_fkey FOREIGN KEY (batch_id) REFERENCES public.roster_import_batches(id) ON DELETE CASCADE;


--
-- Name: finding_people finding_people_mission_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.finding_people
    ADD CONSTRAINT finding_people_mission_id_fkey FOREIGN KEY (mission_id) REFERENCES public.missions(id);


--
-- Name: finding_people finding_people_zone_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.finding_people
    ADD CONSTRAINT finding_people_zone_id_fkey FOREIGN KEY (zone_id) REFERENCES public.zones(id);


--
-- Name: finding_rate_weeks finding_rate_weeks_batch_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.finding_rate_weeks
    ADD CONSTRAINT finding_rate_weeks_batch_id_fkey FOREIGN KEY (batch_id) REFERENCES public.roster_import_batches(id) ON DELETE CASCADE;


--
-- Name: finding_rate_weeks finding_rate_weeks_mission_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.finding_rate_weeks
    ADD CONSTRAINT finding_rate_weeks_mission_id_fkey FOREIGN KEY (mission_id) REFERENCES public.missions(id);


--
-- Name: finding_rate_weeks finding_rate_weeks_zone_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.finding_rate_weeks
    ADD CONSTRAINT finding_rate_weeks_zone_id_fkey FOREIGN KEY (zone_id) REFERENCES public.zones(id);


--
-- Name: baptismal_date_person_area_assignments friend_area_assignments_area_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.baptismal_date_person_area_assignments
    ADD CONSTRAINT friend_area_assignments_area_id_fkey FOREIGN KEY (area_id) REFERENCES public.areas(id) ON DELETE RESTRICT;


--
-- Name: baptismal_date_person_area_assignments friend_area_assignments_friend_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.baptismal_date_person_area_assignments
    ADD CONSTRAINT friend_area_assignments_friend_id_fkey FOREIGN KEY (baptismal_date_person_id) REFERENCES public.baptismal_date_people(id) ON DELETE CASCADE;


--
-- Name: baptismal_date_people friends_created_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.baptismal_date_people
    ADD CONSTRAINT friends_created_by_fkey FOREIGN KEY (created_by) REFERENCES auth.users(id) ON DELETE SET NULL;


--
-- Name: historical_planning_details historical_planning_details_weekly_area_report_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: supabase_admin
--

ALTER TABLE ONLY public.historical_planning_details
    ADD CONSTRAINT historical_planning_details_weekly_area_report_id_fkey FOREIGN KEY (weekly_area_report_id) REFERENCES public.weekly_area_reports(id) ON DELETE CASCADE;


--
-- Name: import_weekly_planning_area_map import_weekly_planning_area_map_mission_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: supabase_admin
--

ALTER TABLE ONLY public.import_weekly_planning_area_map
    ADD CONSTRAINT import_weekly_planning_area_map_mission_id_fkey FOREIGN KEY (mission_id) REFERENCES public.missions(id);


--
-- Name: import_weekly_planning_area_map import_weekly_planning_area_map_target_area_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: supabase_admin
--

ALTER TABLE ONLY public.import_weekly_planning_area_map
    ADD CONSTRAINT import_weekly_planning_area_map_target_area_id_fkey FOREIGN KEY (target_area_id) REFERENCES public.areas(id);


--
-- Name: leadership_assignments leadership_assignments_district_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.leadership_assignments
    ADD CONSTRAINT leadership_assignments_district_id_fkey FOREIGN KEY (district_id) REFERENCES public.districts(id) ON DELETE SET NULL;


--
-- Name: leadership_assignments leadership_assignments_mission_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.leadership_assignments
    ADD CONSTRAINT leadership_assignments_mission_id_fkey FOREIGN KEY (mission_id) REFERENCES public.missions(id) ON DELETE SET NULL;


--
-- Name: leadership_assignments leadership_assignments_missionary_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.leadership_assignments
    ADD CONSTRAINT leadership_assignments_missionary_id_fkey FOREIGN KEY (missionary_id) REFERENCES public.missionaries(id) ON DELETE CASCADE;


--
-- Name: leadership_assignments leadership_assignments_zone_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.leadership_assignments
    ADD CONSTRAINT leadership_assignments_zone_id_fkey FOREIGN KEY (zone_id) REFERENCES public.zones(id) ON DELETE SET NULL;


--
-- Name: missionary_assignments missionary_assignments_area_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.missionary_assignments
    ADD CONSTRAINT missionary_assignments_area_id_fkey FOREIGN KEY (area_id) REFERENCES public.areas(id) ON DELETE RESTRICT;


--
-- Name: missionary_assignments missionary_assignments_missionary_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.missionary_assignments
    ADD CONSTRAINT missionary_assignments_missionary_id_fkey FOREIGN KEY (missionary_id) REFERENCES public.missionaries(id) ON DELETE CASCADE;


--
-- Name: missionary_language_assignments missionary_language_assignments_missionary_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: supabase_admin
--

ALTER TABLE ONLY public.missionary_language_assignments
    ADD CONSTRAINT missionary_language_assignments_missionary_id_fkey FOREIGN KEY (missionary_id) REFERENCES public.missionaries(id) ON DELETE CASCADE;


--
-- Name: new_member_area_assignments new_member_area_assignments_area_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.new_member_area_assignments
    ADD CONSTRAINT new_member_area_assignments_area_id_fkey FOREIGN KEY (area_id) REFERENCES public.areas(id) ON DELETE RESTRICT;


--
-- Name: new_member_area_assignments new_member_area_assignments_new_member_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.new_member_area_assignments
    ADD CONSTRAINT new_member_area_assignments_new_member_id_fkey FOREIGN KEY (new_member_id) REFERENCES public.new_members(id) ON DELETE CASCADE;


--
-- Name: new_member_area_assignments new_member_area_assignments_unit_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.new_member_area_assignments
    ADD CONSTRAINT new_member_area_assignments_unit_id_fkey FOREIGN KEY (unit_id) REFERENCES public.units(id) ON DELETE RESTRICT;


--
-- Name: new_members new_members_area_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.new_members
    ADD CONSTRAINT new_members_area_id_fkey FOREIGN KEY (area_id) REFERENCES public.areas(id) ON DELETE CASCADE;


--
-- Name: new_members new_members_baptismal_date_person_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.new_members
    ADD CONSTRAINT new_members_baptismal_date_person_id_fkey FOREIGN KEY (baptismal_date_person_id) REFERENCES public.baptismal_date_people(id) ON DELETE SET NULL;


--
-- Name: new_members new_members_created_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.new_members
    ADD CONSTRAINT new_members_created_by_fkey FOREIGN KEY (created_by) REFERENCES auth.users(id) ON DELETE SET NULL;


--
-- Name: new_members new_members_stake_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.new_members
    ADD CONSTRAINT new_members_stake_id_fkey FOREIGN KEY (stake_id) REFERENCES public.stakes(id) ON DELETE SET NULL;


--
-- Name: new_members new_members_unit_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.new_members
    ADD CONSTRAINT new_members_unit_id_fkey FOREIGN KEY (unit_id) REFERENCES public.units(id) ON DELETE SET NULL;


--
-- Name: people_match_decisions people_match_decisions_mission_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.people_match_decisions
    ADD CONSTRAINT people_match_decisions_mission_id_fkey FOREIGN KEY (mission_id) REFERENCES public.missions(id);


--
-- Name: planning_question_grid_rows planning_question_grid_rows_question_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.planning_question_grid_rows
    ADD CONSTRAINT planning_question_grid_rows_question_id_fkey FOREIGN KEY (question_id) REFERENCES public.planning_questions(id) ON DELETE CASCADE;


--
-- Name: planning_question_options planning_question_options_question_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.planning_question_options
    ADD CONSTRAINT planning_question_options_question_id_fkey FOREIGN KEY (question_id) REFERENCES public.planning_questions(id) ON DELETE CASCADE;


--
-- Name: planning_questions planning_questions_section_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.planning_questions
    ADD CONSTRAINT planning_questions_section_id_fkey FOREIGN KEY (section_id) REFERENCES public.planning_question_sections(id) ON DELETE CASCADE;


--
-- Name: planning_question_visibility_rules planning_visibility_child_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.planning_question_visibility_rules
    ADD CONSTRAINT planning_visibility_child_fkey FOREIGN KEY (child_question_key) REFERENCES public.planning_questions(question_key) ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: planning_question_visibility_rules planning_visibility_parent_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.planning_question_visibility_rules
    ADD CONSTRAINT planning_visibility_parent_fkey FOREIGN KEY (parent_question_key) REFERENCES public.planning_questions(question_key) ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: referral_archive_weeks referral_archive_weeks_area_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.referral_archive_weeks
    ADD CONSTRAINT referral_archive_weeks_area_id_fkey FOREIGN KEY (area_id) REFERENCES public.areas(id);


--
-- Name: referral_archive_weeks referral_archive_weeks_batch_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.referral_archive_weeks
    ADD CONSTRAINT referral_archive_weeks_batch_id_fkey FOREIGN KEY (batch_id) REFERENCES public.roster_import_batches(id) ON DELETE CASCADE;


--
-- Name: referral_archive_weeks referral_archive_weeks_mission_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.referral_archive_weeks
    ADD CONSTRAINT referral_archive_weeks_mission_id_fkey FOREIGN KEY (mission_id) REFERENCES public.missions(id);


--
-- Name: referral_archive_weeks referral_archive_weeks_zone_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.referral_archive_weeks
    ADD CONSTRAINT referral_archive_weeks_zone_id_fkey FOREIGN KEY (zone_id) REFERENCES public.zones(id);


--
-- Name: roster_import_batches roster_import_batches_mission_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: supabase_admin
--

ALTER TABLE ONLY public.roster_import_batches
    ADD CONSTRAINT roster_import_batches_mission_id_fkey FOREIGN KEY (mission_id) REFERENCES public.missions(id);


--
-- Name: roster_import_changes roster_import_changes_batch_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: supabase_admin
--

ALTER TABLE ONLY public.roster_import_changes
    ADD CONSTRAINT roster_import_changes_batch_id_fkey FOREIGN KEY (batch_id) REFERENCES public.roster_import_batches(id) ON DELETE CASCADE;


--
-- Name: stakes stakes_mission_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.stakes
    ADD CONSTRAINT stakes_mission_id_fkey FOREIGN KEY (mission_id) REFERENCES public.missions(id) ON DELETE CASCADE;


--
-- Name: units units_stake_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.units
    ADD CONSTRAINT units_stake_id_fkey FOREIGN KEY (stake_id) REFERENCES public.stakes(id) ON DELETE SET NULL;


--
-- Name: user_profiles user_profiles_home_mission_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.user_profiles
    ADD CONSTRAINT user_profiles_home_mission_id_fkey FOREIGN KEY (home_mission_id) REFERENCES public.missions(id);


--
-- Name: user_profiles user_profiles_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.user_profiles
    ADD CONSTRAINT user_profiles_id_fkey FOREIGN KEY (id) REFERENCES auth.users(id) ON DELETE CASCADE;


--
-- Name: user_profiles user_profiles_missionary_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.user_profiles
    ADD CONSTRAINT user_profiles_missionary_id_fkey FOREIGN KEY (missionary_id) REFERENCES public.missionaries(id) ON DELETE SET NULL;


--
-- Name: weekly_area_reports weekly_area_reports_area_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.weekly_area_reports
    ADD CONSTRAINT weekly_area_reports_area_id_fkey FOREIGN KEY (area_id) REFERENCES public.areas(id) ON DELETE RESTRICT;


--
-- Name: weekly_area_reports weekly_area_reports_import_batch_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.weekly_area_reports
    ADD CONSTRAINT weekly_area_reports_import_batch_id_fkey FOREIGN KEY (import_batch_id) REFERENCES public.roster_import_batches(id);


--
-- Name: weekly_area_reports weekly_area_reports_reporting_week_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.weekly_area_reports
    ADD CONSTRAINT weekly_area_reports_reporting_week_id_fkey FOREIGN KEY (reporting_week_id) REFERENCES public.reporting_weeks(id) ON DELETE CASCADE;


--
-- Name: weekly_area_reports weekly_area_reports_submitted_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.weekly_area_reports
    ADD CONSTRAINT weekly_area_reports_submitted_by_fkey FOREIGN KEY (submitted_by) REFERENCES auth.users(id) ON DELETE SET NULL;


--
-- Name: weekly_area_reports weekly_area_reports_unit_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.weekly_area_reports
    ADD CONSTRAINT weekly_area_reports_unit_id_fkey FOREIGN KEY (unit_id) REFERENCES public.units(id);


--
-- Name: weekly_baptismal_date_friends weekly_baptismal_date_friends_baptismal_date_person_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.weekly_baptismal_date_friends
    ADD CONSTRAINT weekly_baptismal_date_friends_baptismal_date_person_id_fkey FOREIGN KEY (baptismal_date_person_id) REFERENCES public.baptismal_date_people(id);


--
-- Name: weekly_baptismal_date_friends weekly_baptismal_date_friends_stake_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.weekly_baptismal_date_friends
    ADD CONSTRAINT weekly_baptismal_date_friends_stake_id_fkey FOREIGN KEY (stake_id) REFERENCES public.stakes(id);


--
-- Name: weekly_baptismal_date_friends weekly_baptismal_date_friends_weekly_area_report_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.weekly_baptismal_date_friends
    ADD CONSTRAINT weekly_baptismal_date_friends_weekly_area_report_id_fkey FOREIGN KEY (weekly_area_report_id) REFERENCES public.weekly_area_reports(id) ON DELETE CASCADE;


--
-- Name: weekly_high_potential_friends weekly_high_potential_friends_weekly_area_report_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.weekly_high_potential_friends
    ADD CONSTRAINT weekly_high_potential_friends_weekly_area_report_id_fkey FOREIGN KEY (weekly_area_report_id) REFERENCES public.weekly_area_reports(id) ON DELETE CASCADE;


--
-- Name: weekly_new_members weekly_new_members_new_member_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.weekly_new_members
    ADD CONSTRAINT weekly_new_members_new_member_id_fkey FOREIGN KEY (new_member_id) REFERENCES public.new_members(id);


--
-- Name: weekly_new_members weekly_new_members_weekly_area_report_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.weekly_new_members
    ADD CONSTRAINT weekly_new_members_weekly_area_report_id_fkey FOREIGN KEY (weekly_area_report_id) REFERENCES public.weekly_area_reports(id) ON DELETE CASCADE;


--
-- Name: weekly_planning_answers weekly_planning_answers_weekly_area_report_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.weekly_planning_answers
    ADD CONSTRAINT weekly_planning_answers_weekly_area_report_id_fkey FOREIGN KEY (weekly_area_report_id) REFERENCES public.weekly_area_reports(id) ON DELETE CASCADE;


--
-- Name: zone_history_weeks zone_history_weeks_batch_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.zone_history_weeks
    ADD CONSTRAINT zone_history_weeks_batch_id_fkey FOREIGN KEY (batch_id) REFERENCES public.roster_import_batches(id) ON DELETE CASCADE;


--
-- Name: zone_history_weeks zone_history_weeks_mission_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.zone_history_weeks
    ADD CONSTRAINT zone_history_weeks_mission_id_fkey FOREIGN KEY (mission_id) REFERENCES public.missions(id);


--
-- Name: zone_history_weeks zone_history_weeks_zone_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.zone_history_weeks
    ADD CONSTRAINT zone_history_weeks_zone_id_fkey FOREIGN KEY (zone_id) REFERENCES public.zones(id);


--
-- Name: zones zones_mission_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.zones
    ADD CONSTRAINT zones_mission_id_fkey FOREIGN KEY (mission_id) REFERENCES public.missions(id) ON DELETE CASCADE;


--
-- Name: activity; Type: ROW SECURITY; Schema: portal; Owner: postgres
--

ALTER TABLE portal.activity ENABLE ROW LEVEL SECURITY;

--
-- Name: announcement_reads; Type: ROW SECURITY; Schema: portal; Owner: postgres
--

ALTER TABLE portal.announcement_reads ENABLE ROW LEVEL SECURITY;

--
-- Name: announcements; Type: ROW SECURITY; Schema: portal; Owner: postgres
--

ALTER TABLE portal.announcements ENABLE ROW LEVEL SECURITY;

--
-- Name: attachments; Type: ROW SECURITY; Schema: portal; Owner: postgres
--

ALTER TABLE portal.attachments ENABLE ROW LEVEL SECURITY;

--
-- Name: attendance; Type: ROW SECURITY; Schema: portal; Owner: postgres
--

ALTER TABLE portal.attendance ENABLE ROW LEVEL SECURITY;

--
-- Name: events; Type: ROW SECURITY; Schema: portal; Owner: postgres
--

ALTER TABLE portal.events ENABLE ROW LEVEL SECURITY;

--
-- Name: presentation_access; Type: ROW SECURITY; Schema: portal; Owner: postgres
--

ALTER TABLE portal.presentation_access ENABLE ROW LEVEL SECURITY;

--
-- Name: presentation_access presentation_access_service_role; Type: POLICY; Schema: portal; Owner: postgres
--

CREATE POLICY presentation_access_service_role ON portal.presentation_access TO service_role USING (true) WITH CHECK (true);


--
-- Name: push_subscriptions; Type: ROW SECURITY; Schema: portal; Owner: postgres
--

ALTER TABLE portal.push_subscriptions ENABLE ROW LEVEL SECURITY;

--
-- Name: user_preferences; Type: ROW SECURITY; Schema: portal; Owner: postgres
--

ALTER TABLE portal.user_preferences ENABLE ROW LEVEL SECURITY;

--
-- Name: whiteboard_files; Type: ROW SECURITY; Schema: portal; Owner: postgres
--

ALTER TABLE portal.whiteboard_files ENABLE ROW LEVEL SECURITY;

--
-- Name: whiteboards; Type: ROW SECURITY; Schema: portal; Owner: postgres
--

ALTER TABLE portal.whiteboards ENABLE ROW LEVEL SECURITY;

--
-- Name: areas Authenticated users can read areas; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY "Authenticated users can read areas" ON public.areas FOR SELECT TO authenticated USING (true);


--
-- Name: districts Authenticated users can read districts; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY "Authenticated users can read districts" ON public.districts FOR SELECT TO authenticated USING (true);


--
-- Name: missions Authenticated users can read missions; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY "Authenticated users can read missions" ON public.missions FOR SELECT TO authenticated USING (true);


--
-- Name: planning_question_grid_rows Authenticated users can read planning grid rows; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY "Authenticated users can read planning grid rows" ON public.planning_question_grid_rows FOR SELECT TO authenticated USING ((active = true));


--
-- Name: planning_question_options Authenticated users can read planning question options; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY "Authenticated users can read planning question options" ON public.planning_question_options FOR SELECT TO authenticated USING ((active = true));


--
-- Name: planning_questions Authenticated users can read planning questions; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY "Authenticated users can read planning questions" ON public.planning_questions FOR SELECT TO authenticated USING ((active = true));


--
-- Name: planning_question_sections Authenticated users can read planning sections; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY "Authenticated users can read planning sections" ON public.planning_question_sections FOR SELECT TO authenticated USING ((active = true));


--
-- Name: planning_question_visibility_rules Authenticated users can read planning visibility rules; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY "Authenticated users can read planning visibility rules" ON public.planning_question_visibility_rules FOR SELECT TO authenticated USING (((active = true) AND (EXISTS ( SELECT 1
   FROM (public.planning_questions p
     JOIN public.planning_question_sections s ON ((s.id = p.section_id)))
  WHERE ((p.question_key = planning_question_visibility_rules.parent_question_key) AND p.active AND s.active)))));


--
-- Name: reporting_weeks Authenticated users can read reporting weeks; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY "Authenticated users can read reporting weeks" ON public.reporting_weeks FOR SELECT TO authenticated USING (true);


--
-- Name: stakes Authenticated users can read stakes; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY "Authenticated users can read stakes" ON public.stakes FOR SELECT TO authenticated USING (true);


--
-- Name: planning_catalog_version Authenticated users can read the planning catalogue version; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY "Authenticated users can read the planning catalogue version" ON public.planning_catalog_version FOR SELECT TO authenticated USING (true);


--
-- Name: units Authenticated users can read units; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY "Authenticated users can read units" ON public.units FOR SELECT TO authenticated USING (true);


--
-- Name: zones Authenticated users can read zones; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY "Authenticated users can read zones" ON public.zones FOR SELECT TO authenticated USING (true);


--
-- Name: weekly_baptismal_date_friends Users can read accessible baptismal date friends; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY "Users can read accessible baptismal date friends" ON public.weekly_baptismal_date_friends FOR SELECT TO authenticated USING ((EXISTS ( SELECT 1
   FROM public.weekly_area_reports war
  WHERE ((war.id = weekly_baptismal_date_friends.weekly_area_report_id) AND public.can_access_area(war.area_id)))));


--
-- Name: companionship_members Users can read accessible companionship members; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY "Users can read accessible companionship members" ON public.companionship_members FOR SELECT TO authenticated USING ((EXISTS ( SELECT 1
   FROM public.companionships c
  WHERE ((c.id = companionship_members.companionship_id) AND public.can_access_area(c.area_id)))));


--
-- Name: companionships Users can read accessible companionships; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY "Users can read accessible companionships" ON public.companionships FOR SELECT TO authenticated USING (public.can_access_area(area_id));


--
-- Name: weekly_high_potential_friends Users can read accessible high potential friends; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY "Users can read accessible high potential friends" ON public.weekly_high_potential_friends FOR SELECT TO authenticated USING ((EXISTS ( SELECT 1
   FROM public.weekly_area_reports war
  WHERE ((war.id = weekly_high_potential_friends.weekly_area_report_id) AND public.can_access_area(war.area_id)))));


--
-- Name: missionary_assignments Users can read accessible missionary assignments; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY "Users can read accessible missionary assignments" ON public.missionary_assignments FOR SELECT TO authenticated USING (public.can_access_area(area_id));


--
-- Name: weekly_new_members Users can read accessible weekly new members; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY "Users can read accessible weekly new members" ON public.weekly_new_members FOR SELECT TO authenticated USING ((EXISTS ( SELECT 1
   FROM public.weekly_area_reports war
  WHERE ((war.id = weekly_new_members.weekly_area_report_id) AND public.can_access_area(war.area_id)))));


--
-- Name: missionaries Users can read missionaries in accessible areas; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY "Users can read missionaries in accessible areas" ON public.missionaries FOR SELECT TO authenticated USING ((EXISTS ( SELECT 1
   FROM public.missionary_assignments ma
  WHERE ((ma.missionary_id = missionaries.id) AND (ma.start_date <= CURRENT_DATE) AND ((ma.end_date IS NULL) OR (ma.end_date >= CURRENT_DATE)) AND public.can_access_area(ma.area_id)))));


--
-- Name: weekly_planning_answers Users can read planning answers in accessible areas; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY "Users can read planning answers in accessible areas" ON public.weekly_planning_answers FOR SELECT TO authenticated USING ((EXISTS ( SELECT 1
   FROM public.weekly_area_reports war
  WHERE ((war.id = weekly_planning_answers.weekly_area_report_id) AND public.can_access_area(war.area_id)))));


--
-- Name: leadership_assignments Users can read relevant leadership assignments; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY "Users can read relevant leadership assignments" ON public.leadership_assignments FOR SELECT TO authenticated USING (((missionary_id = ( SELECT up.missionary_id
   FROM public.user_profiles up
  WHERE (up.id = ( SELECT auth.uid() AS uid)))) OR (EXISTS ( SELECT 1
   FROM public.user_profiles up
  WHERE ((up.id = ( SELECT auth.uid() AS uid)) AND ((up.app_role = 'DATA_ADMIN'::text) OR ('DATA_ADMIN'::text = ANY (up.additional_roles))))))));


--
-- Name: weekly_area_reports Users can read reports in accessible areas; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY "Users can read reports in accessible areas" ON public.weekly_area_reports FOR SELECT TO authenticated USING (public.can_access_area(area_id));


--
-- Name: user_profiles Users can read their own profile; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY "Users can read their own profile" ON public.user_profiles FOR SELECT TO authenticated USING ((id = ( SELECT auth.uid() AS uid)));


--
-- Name: archetype_notes; Type: ROW SECURITY; Schema: public; Owner: postgres
--

ALTER TABLE public.archetype_notes ENABLE ROW LEVEL SECURITY;

--
-- Name: archetype_settings; Type: ROW SECURITY; Schema: public; Owner: postgres
--

ALTER TABLE public.archetype_settings ENABLE ROW LEVEL SECURITY;

--
-- Name: archetype_settings_history; Type: ROW SECURITY; Schema: public; Owner: postgres
--

ALTER TABLE public.archetype_settings_history ENABLE ROW LEVEL SECURITY;

--
-- Name: area_profiles; Type: ROW SECURITY; Schema: public; Owner: postgres
--

ALTER TABLE public.area_profiles ENABLE ROW LEVEL SECURITY;

--
-- Name: areas; Type: ROW SECURITY; Schema: public; Owner: postgres
--

ALTER TABLE public.areas ENABLE ROW LEVEL SECURITY;

--
-- Name: missionary_language_assignments assigned_languages_read; Type: POLICY; Schema: public; Owner: supabase_admin
--

CREATE POLICY assigned_languages_read ON public.missionary_language_assignments FOR SELECT TO authenticated USING (((missionary_id IN ( SELECT up.missionary_id
   FROM public.user_profiles up
  WHERE ((up.id = auth.uid()) AND up.active))) OR (EXISTS ( SELECT 1
   FROM (((public.user_profiles up
     LEFT JOIN LATERAL ( SELECT la.mission_id
           FROM public.leadership_assignments la
          WHERE ((la.missionary_id = up.missionary_id) AND (la.role = 'AP'::text) AND (la.start_date <= CURRENT_DATE) AND ((la.end_date IS NULL) OR (la.end_date >= CURRENT_DATE)))
          ORDER BY la.start_date DESC, la.id DESC
         LIMIT 1) ap ON (true))
     LEFT JOIN LATERAL ( SELECT own.mission_id
           FROM public.current_missionary_assignments own
          WHERE (own.missionary_id = up.missionary_id)
          ORDER BY own.start_date DESC, own.assignment_id DESC
         LIMIT 1) own_scope ON (true))
     JOIN LATERAL ( SELECT target.mission_id
           FROM public.current_missionary_assignments target
          WHERE (target.missionary_id = missionary_language_assignments.missionary_id)
          ORDER BY target.start_date DESC, target.assignment_id DESC
         LIMIT 1) target_scope ON ((target_scope.mission_id = COALESCE(ap.mission_id, own_scope.mission_id))))
  WHERE ((up.id = auth.uid()) AND up.active AND ((up.app_role = ANY (ARRAY['PRESIDENT'::text, 'DATA_ADMIN'::text])) OR ('DATA_ADMIN'::text = ANY (up.additional_roles)) OR (ap.mission_id IS NOT NULL)))))));


--
-- Name: baptism_history_weeks; Type: ROW SECURITY; Schema: public; Owner: postgres
--

ALTER TABLE public.baptism_history_weeks ENABLE ROW LEVEL SECURITY;

--
-- Name: baptismal_date_people; Type: ROW SECURITY; Schema: public; Owner: postgres
--

ALTER TABLE public.baptismal_date_people ENABLE ROW LEVEL SECURITY;

--
-- Name: baptismal_date_people baptismal_date_people_read_scope; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY baptismal_date_people_read_scope ON public.baptismal_date_people FOR SELECT TO authenticated USING ((EXISTS ( SELECT 1
   FROM public.baptismal_date_person_area_assignments faa
  WHERE ((faa.baptismal_date_person_id = baptismal_date_people.id) AND (faa.end_date IS NULL) AND public.can_access_area(faa.area_id)))));


--
-- Name: baptismal_date_person_area_assignments; Type: ROW SECURITY; Schema: public; Owner: postgres
--

ALTER TABLE public.baptismal_date_person_area_assignments ENABLE ROW LEVEL SECURITY;

--
-- Name: baptismal_date_person_area_assignments baptismal_date_person_area_assignments_read; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY baptismal_date_person_area_assignments_read ON public.baptismal_date_person_area_assignments FOR SELECT TO authenticated USING (public.can_access_area(area_id));


--
-- Name: call_in_area_updates; Type: ROW SECURITY; Schema: public; Owner: postgres
--

ALTER TABLE public.call_in_area_updates ENABLE ROW LEVEL SECURITY;

--
-- Name: call_in_area_updates call_in_area_updates_select; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY call_in_area_updates_select ON public.call_in_area_updates FOR SELECT TO authenticated USING ((EXISTS ( SELECT 1
   FROM public.call_in_districts cid
  WHERE ((cid.id = call_in_area_updates.district_call_in_id) AND public.can_access_district(cid.district_id)))));


--
-- Name: call_in_districts; Type: ROW SECURITY; Schema: public; Owner: postgres
--

ALTER TABLE public.call_in_districts ENABLE ROW LEVEL SECURITY;

--
-- Name: call_in_districts call_in_districts_select; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY call_in_districts_select ON public.call_in_districts FOR SELECT TO authenticated USING (public.can_access_district(district_id));


--
-- Name: call_in_zones; Type: ROW SECURITY; Schema: public; Owner: postgres
--

ALTER TABLE public.call_in_zones ENABLE ROW LEVEL SECURITY;

--
-- Name: call_in_zones call_in_zones_select; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY call_in_zones_select ON public.call_in_zones FOR SELECT TO authenticated USING (public.can_edit_zl_zone_call_in(zone_id));


--
-- Name: cleanup_029_revoked_grants; Type: ROW SECURITY; Schema: public; Owner: postgres
--

ALTER TABLE public.cleanup_029_revoked_grants ENABLE ROW LEVEL SECURITY;

--
-- Name: cleanup_030_removed_rows; Type: ROW SECURITY; Schema: public; Owner: postgres
--

ALTER TABLE public.cleanup_030_removed_rows ENABLE ROW LEVEL SECURITY;

--
-- Name: companionship_members; Type: ROW SECURITY; Schema: public; Owner: postgres
--

ALTER TABLE public.companionship_members ENABLE ROW LEVEL SECURITY;

--
-- Name: companionships; Type: ROW SECURITY; Schema: public; Owner: postgres
--

ALTER TABLE public.companionships ENABLE ROW LEVEL SECURITY;

--
-- Name: data_name_matches; Type: ROW SECURITY; Schema: public; Owner: postgres
--

ALTER TABLE public.data_name_matches ENABLE ROW LEVEL SECURITY;

--
-- Name: districts; Type: ROW SECURITY; Schema: public; Owner: postgres
--

ALTER TABLE public.districts ENABLE ROW LEVEL SECURITY;

--
-- Name: finding_people; Type: ROW SECURITY; Schema: public; Owner: postgres
--

ALTER TABLE public.finding_people ENABLE ROW LEVEL SECURITY;

--
-- Name: finding_rate_weeks; Type: ROW SECURITY; Schema: public; Owner: postgres
--

ALTER TABLE public.finding_rate_weeks ENABLE ROW LEVEL SECURITY;

--
-- Name: historical_planning_details; Type: ROW SECURITY; Schema: public; Owner: supabase_admin
--

ALTER TABLE public.historical_planning_details ENABLE ROW LEVEL SECURITY;

--
-- Name: leadership_assignments; Type: ROW SECURITY; Schema: public; Owner: postgres
--

ALTER TABLE public.leadership_assignments ENABLE ROW LEVEL SECURITY;

--
-- Name: missionaries; Type: ROW SECURITY; Schema: public; Owner: postgres
--

ALTER TABLE public.missionaries ENABLE ROW LEVEL SECURITY;

--
-- Name: missionary_assignments; Type: ROW SECURITY; Schema: public; Owner: postgres
--

ALTER TABLE public.missionary_assignments ENABLE ROW LEVEL SECURITY;

--
-- Name: missionary_language_assignments; Type: ROW SECURITY; Schema: public; Owner: supabase_admin
--

ALTER TABLE public.missionary_language_assignments ENABLE ROW LEVEL SECURITY;

--
-- Name: missions; Type: ROW SECURITY; Schema: public; Owner: postgres
--

ALTER TABLE public.missions ENABLE ROW LEVEL SECURITY;

--
-- Name: new_member_area_assignments; Type: ROW SECURITY; Schema: public; Owner: postgres
--

ALTER TABLE public.new_member_area_assignments ENABLE ROW LEVEL SECURITY;

--
-- Name: new_member_area_assignments new_member_area_assignments_read; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY new_member_area_assignments_read ON public.new_member_area_assignments FOR SELECT TO authenticated USING (public.can_access_area(area_id));


--
-- Name: new_members; Type: ROW SECURITY; Schema: public; Owner: postgres
--

ALTER TABLE public.new_members ENABLE ROW LEVEL SECURITY;

--
-- Name: new_members new_members_insert_own_area; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY new_members_insert_own_area ON public.new_members FOR INSERT TO authenticated WITH CHECK ((area_id = public.current_user_area_id()));


--
-- Name: new_members new_members_read_scope; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY new_members_read_scope ON public.new_members FOR SELECT TO authenticated USING (public.can_access_area(area_id));


--
-- Name: new_members new_members_update_own_area; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY new_members_update_own_area ON public.new_members FOR UPDATE TO authenticated USING ((area_id = public.current_user_area_id())) WITH CHECK ((area_id = public.current_user_area_id()));


--
-- Name: people_match_decisions; Type: ROW SECURITY; Schema: public; Owner: postgres
--

ALTER TABLE public.people_match_decisions ENABLE ROW LEVEL SECURITY;

--
-- Name: planning_catalog_changes; Type: ROW SECURITY; Schema: public; Owner: postgres
--

ALTER TABLE public.planning_catalog_changes ENABLE ROW LEVEL SECURITY;

--
-- Name: planning_catalog_version; Type: ROW SECURITY; Schema: public; Owner: postgres
--

ALTER TABLE public.planning_catalog_version ENABLE ROW LEVEL SECURITY;

--
-- Name: planning_question_grid_rows; Type: ROW SECURITY; Schema: public; Owner: postgres
--

ALTER TABLE public.planning_question_grid_rows ENABLE ROW LEVEL SECURITY;

--
-- Name: planning_question_options; Type: ROW SECURITY; Schema: public; Owner: postgres
--

ALTER TABLE public.planning_question_options ENABLE ROW LEVEL SECURITY;

--
-- Name: planning_question_sections; Type: ROW SECURITY; Schema: public; Owner: postgres
--

ALTER TABLE public.planning_question_sections ENABLE ROW LEVEL SECURITY;

--
-- Name: planning_question_visibility_rules; Type: ROW SECURITY; Schema: public; Owner: postgres
--

ALTER TABLE public.planning_question_visibility_rules ENABLE ROW LEVEL SECURITY;

--
-- Name: planning_questions; Type: ROW SECURITY; Schema: public; Owner: postgres
--

ALTER TABLE public.planning_questions ENABLE ROW LEVEL SECURITY;

--
-- Name: weekly_baptismal_date_friends portal_planning_delete; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY portal_planning_delete ON public.weekly_baptismal_date_friends FOR DELETE TO authenticated USING (public.can_edit_planning_report(weekly_area_report_id));


--
-- Name: weekly_high_potential_friends portal_planning_delete; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY portal_planning_delete ON public.weekly_high_potential_friends FOR DELETE TO authenticated USING (public.can_edit_planning_report(weekly_area_report_id));


--
-- Name: weekly_new_members portal_planning_delete; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY portal_planning_delete ON public.weekly_new_members FOR DELETE TO authenticated USING (public.can_edit_planning_report(weekly_area_report_id));


--
-- Name: weekly_planning_answers portal_planning_delete; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY portal_planning_delete ON public.weekly_planning_answers FOR DELETE TO authenticated USING (public.can_edit_planning_report(weekly_area_report_id));


--
-- Name: weekly_area_reports portal_planning_insert; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY portal_planning_insert ON public.weekly_area_reports FOR INSERT TO authenticated WITH CHECK ((public.can_edit_planning_area(area_id) AND (status = 'DRAFT'::text) AND (submitted_by = auth.uid())));


--
-- Name: weekly_baptismal_date_friends portal_planning_insert; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY portal_planning_insert ON public.weekly_baptismal_date_friends FOR INSERT TO authenticated WITH CHECK (public.can_edit_planning_report(weekly_area_report_id));


--
-- Name: weekly_high_potential_friends portal_planning_insert; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY portal_planning_insert ON public.weekly_high_potential_friends FOR INSERT TO authenticated WITH CHECK (public.can_edit_planning_report(weekly_area_report_id));


--
-- Name: weekly_new_members portal_planning_insert; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY portal_planning_insert ON public.weekly_new_members FOR INSERT TO authenticated WITH CHECK (public.can_edit_planning_report(weekly_area_report_id));


--
-- Name: weekly_planning_answers portal_planning_insert; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY portal_planning_insert ON public.weekly_planning_answers FOR INSERT TO authenticated WITH CHECK (public.can_edit_planning_report(weekly_area_report_id));


--
-- Name: weekly_area_reports portal_planning_update; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY portal_planning_update ON public.weekly_area_reports FOR UPDATE TO authenticated USING ((public.can_edit_planning_area(area_id) OR public.can_unlock_planning_area(area_id))) WITH CHECK ((public.can_edit_planning_area(area_id) OR public.can_unlock_planning_area(area_id)));


--
-- Name: weekly_baptismal_date_friends portal_planning_update; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY portal_planning_update ON public.weekly_baptismal_date_friends FOR UPDATE TO authenticated USING (public.can_edit_planning_report(weekly_area_report_id)) WITH CHECK (public.can_edit_planning_report(weekly_area_report_id));


--
-- Name: weekly_high_potential_friends portal_planning_update; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY portal_planning_update ON public.weekly_high_potential_friends FOR UPDATE TO authenticated USING (public.can_edit_planning_report(weekly_area_report_id)) WITH CHECK (public.can_edit_planning_report(weekly_area_report_id));


--
-- Name: weekly_new_members portal_planning_update; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY portal_planning_update ON public.weekly_new_members FOR UPDATE TO authenticated USING (public.can_edit_planning_report(weekly_area_report_id)) WITH CHECK (public.can_edit_planning_report(weekly_area_report_id));


--
-- Name: weekly_planning_answers portal_planning_update; Type: POLICY; Schema: public; Owner: postgres
--

CREATE POLICY portal_planning_update ON public.weekly_planning_answers FOR UPDATE TO authenticated USING (public.can_edit_planning_report(weekly_area_report_id)) WITH CHECK (public.can_edit_planning_report(weekly_area_report_id));


--
-- Name: referral_archive_weeks; Type: ROW SECURITY; Schema: public; Owner: postgres
--

ALTER TABLE public.referral_archive_weeks ENABLE ROW LEVEL SECURITY;

--
-- Name: reporting_weeks; Type: ROW SECURITY; Schema: public; Owner: postgres
--

ALTER TABLE public.reporting_weeks ENABLE ROW LEVEL SECURITY;

--
-- Name: roster_import_batches; Type: ROW SECURITY; Schema: public; Owner: supabase_admin
--

ALTER TABLE public.roster_import_batches ENABLE ROW LEVEL SECURITY;

--
-- Name: roster_import_changes; Type: ROW SECURITY; Schema: public; Owner: supabase_admin
--

ALTER TABLE public.roster_import_changes ENABLE ROW LEVEL SECURITY;

--
-- Name: stakes; Type: ROW SECURITY; Schema: public; Owner: postgres
--

ALTER TABLE public.stakes ENABLE ROW LEVEL SECURITY;

--
-- Name: units; Type: ROW SECURITY; Schema: public; Owner: postgres
--

ALTER TABLE public.units ENABLE ROW LEVEL SECURITY;

--
-- Name: user_profiles; Type: ROW SECURITY; Schema: public; Owner: postgres
--

ALTER TABLE public.user_profiles ENABLE ROW LEVEL SECURITY;

--
-- Name: weekly_area_reports; Type: ROW SECURITY; Schema: public; Owner: postgres
--

ALTER TABLE public.weekly_area_reports ENABLE ROW LEVEL SECURITY;

--
-- Name: weekly_baptismal_date_friends; Type: ROW SECURITY; Schema: public; Owner: postgres
--

ALTER TABLE public.weekly_baptismal_date_friends ENABLE ROW LEVEL SECURITY;

--
-- Name: weekly_high_potential_friends; Type: ROW SECURITY; Schema: public; Owner: postgres
--

ALTER TABLE public.weekly_high_potential_friends ENABLE ROW LEVEL SECURITY;

--
-- Name: weekly_new_members; Type: ROW SECURITY; Schema: public; Owner: postgres
--

ALTER TABLE public.weekly_new_members ENABLE ROW LEVEL SECURITY;

--
-- Name: weekly_planning_answers; Type: ROW SECURITY; Schema: public; Owner: postgres
--

ALTER TABLE public.weekly_planning_answers ENABLE ROW LEVEL SECURITY;

--
-- Name: zone_history_weeks; Type: ROW SECURITY; Schema: public; Owner: postgres
--

ALTER TABLE public.zone_history_weeks ENABLE ROW LEVEL SECURITY;

--
-- Name: zones; Type: ROW SECURITY; Schema: public; Owner: postgres
--

ALTER TABLE public.zones ENABLE ROW LEVEL SECURITY;

--
-- Rights. A new Supabase database hands every new table, view, function and sequence to anon, authenticated and
-- service_role by itself (its default privileges). The live system took those away again one by one over the months, so
-- first take them all away here, and then give back exactly what the live system has (the GRANT lines below).
--
REVOKE ALL ON ALL TABLES IN SCHEMA public, dashboards, portal FROM anon, authenticated, service_role;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA public, dashboards, portal FROM anon, authenticated, service_role;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA public, dashboards, portal FROM anon, authenticated, service_role;

--
-- Name: SCHEMA dashboards; Type: ACL; Schema: -; Owner: postgres
--

GRANT USAGE ON SCHEMA dashboards TO gfm_dashboard_reader;


--
-- Name: SCHEMA portal; Type: ACL; Schema: -; Owner: postgres
--

GRANT USAGE ON SCHEMA portal TO service_role;


--
-- Name: SCHEMA public; Type: ACL; Schema: -; Owner: pg_database_owner
--

GRANT USAGE ON SCHEMA public TO postgres;
GRANT USAGE ON SCHEMA public TO anon;
GRANT USAGE ON SCHEMA public TO authenticated;
GRANT USAGE ON SCHEMA public TO service_role;


--
-- Name: FUNCTION archetype_plan_rows(); Type: ACL; Schema: dashboards; Owner: postgres
--

REVOKE ALL ON FUNCTION dashboards.archetype_plan_rows() FROM PUBLIC;
GRANT ALL ON FUNCTION dashboards.archetype_plan_rows() TO gfm_dashboard_reader;


--
-- Name: FUNCTION area_week_rows(); Type: ACL; Schema: dashboards; Owner: postgres
--

REVOKE ALL ON FUNCTION dashboards.area_week_rows() FROM PUBLIC;
GRANT ALL ON FUNCTION dashboards.area_week_rows() TO gfm_dashboard_reader;


--
-- Name: FUNCTION archive_baptismal_date_person(target_baptismal_date_person_id bigint, archive_reason text); Type: ACL; Schema: public; Owner: postgres
--

REVOKE ALL ON FUNCTION public.archive_baptismal_date_person(target_baptismal_date_person_id bigint, archive_reason text) FROM PUBLIC;
GRANT ALL ON FUNCTION public.archive_baptismal_date_person(target_baptismal_date_person_id bigint, archive_reason text) TO authenticated;
GRANT ALL ON FUNCTION public.archive_baptismal_date_person(target_baptismal_date_person_id bigint, archive_reason text) TO service_role;


--
-- Name: FUNCTION archive_expired_new_members(); Type: ACL; Schema: public; Owner: postgres
--

REVOKE ALL ON FUNCTION public.archive_expired_new_members() FROM PUBLIC;
GRANT ALL ON FUNCTION public.archive_expired_new_members() TO service_role;


--
-- Name: FUNCTION archive_new_member(target_new_member_id bigint, archive_reason text); Type: ACL; Schema: public; Owner: postgres
--

REVOKE ALL ON FUNCTION public.archive_new_member(target_new_member_id bigint, archive_reason text) FROM PUBLIC;
GRANT ALL ON FUNCTION public.archive_new_member(target_new_member_id bigint, archive_reason text) TO authenticated;
GRANT ALL ON FUNCTION public.archive_new_member(target_new_member_id bigint, archive_reason text) TO service_role;


--
-- Name: FUNCTION can_access_area(target_area_id bigint); Type: ACL; Schema: public; Owner: postgres
--

REVOKE ALL ON FUNCTION public.can_access_area(target_area_id bigint) FROM PUBLIC;
GRANT ALL ON FUNCTION public.can_access_area(target_area_id bigint) TO authenticated;
GRANT ALL ON FUNCTION public.can_access_area(target_area_id bigint) TO service_role;


--
-- Name: FUNCTION can_access_district(target_district_id bigint); Type: ACL; Schema: public; Owner: postgres
--

REVOKE ALL ON FUNCTION public.can_access_district(target_district_id bigint) FROM PUBLIC;
GRANT ALL ON FUNCTION public.can_access_district(target_district_id bigint) TO authenticated;
GRANT ALL ON FUNCTION public.can_access_district(target_district_id bigint) TO service_role;


--
-- Name: FUNCTION can_access_mission(target_mission_id bigint); Type: ACL; Schema: public; Owner: postgres
--

REVOKE ALL ON FUNCTION public.can_access_mission(target_mission_id bigint) FROM PUBLIC;
GRANT ALL ON FUNCTION public.can_access_mission(target_mission_id bigint) TO authenticated;
GRANT ALL ON FUNCTION public.can_access_mission(target_mission_id bigint) TO service_role;


--
-- Name: FUNCTION can_access_zone(target_zone_id bigint); Type: ACL; Schema: public; Owner: postgres
--

REVOKE ALL ON FUNCTION public.can_access_zone(target_zone_id bigint) FROM PUBLIC;
GRANT ALL ON FUNCTION public.can_access_zone(target_zone_id bigint) TO authenticated;
GRANT ALL ON FUNCTION public.can_access_zone(target_zone_id bigint) TO service_role;


--
-- Name: FUNCTION can_current_user_report_for_unit(target_unit_id bigint); Type: ACL; Schema: public; Owner: postgres
--

REVOKE ALL ON FUNCTION public.can_current_user_report_for_unit(target_unit_id bigint) FROM PUBLIC;
GRANT ALL ON FUNCTION public.can_current_user_report_for_unit(target_unit_id bigint) TO authenticated;
GRANT ALL ON FUNCTION public.can_current_user_report_for_unit(target_unit_id bigint) TO service_role;


--
-- Name: FUNCTION can_edit_dl_call_in(target_district_id bigint); Type: ACL; Schema: public; Owner: postgres
--

REVOKE ALL ON FUNCTION public.can_edit_dl_call_in(target_district_id bigint) FROM PUBLIC;
GRANT ALL ON FUNCTION public.can_edit_dl_call_in(target_district_id bigint) TO authenticated;
GRANT ALL ON FUNCTION public.can_edit_dl_call_in(target_district_id bigint) TO service_role;


--
-- Name: FUNCTION can_edit_planning_area(target_area_id bigint); Type: ACL; Schema: public; Owner: postgres
--

REVOKE ALL ON FUNCTION public.can_edit_planning_area(target_area_id bigint) FROM PUBLIC;
GRANT ALL ON FUNCTION public.can_edit_planning_area(target_area_id bigint) TO authenticated;
GRANT ALL ON FUNCTION public.can_edit_planning_area(target_area_id bigint) TO service_role;


--
-- Name: FUNCTION can_edit_planning_report(target_report_id bigint); Type: ACL; Schema: public; Owner: postgres
--

REVOKE ALL ON FUNCTION public.can_edit_planning_report(target_report_id bigint) FROM PUBLIC;
GRANT ALL ON FUNCTION public.can_edit_planning_report(target_report_id bigint) TO authenticated;
GRANT ALL ON FUNCTION public.can_edit_planning_report(target_report_id bigint) TO service_role;


--
-- Name: FUNCTION can_edit_zl_call_in(target_district_id bigint); Type: ACL; Schema: public; Owner: postgres
--

REVOKE ALL ON FUNCTION public.can_edit_zl_call_in(target_district_id bigint) FROM PUBLIC;
GRANT ALL ON FUNCTION public.can_edit_zl_call_in(target_district_id bigint) TO authenticated;
GRANT ALL ON FUNCTION public.can_edit_zl_call_in(target_district_id bigint) TO service_role;


--
-- Name: FUNCTION can_edit_zl_zone_call_in(target_zone_id bigint); Type: ACL; Schema: public; Owner: postgres
--

REVOKE ALL ON FUNCTION public.can_edit_zl_zone_call_in(target_zone_id bigint) FROM PUBLIC;
GRANT ALL ON FUNCTION public.can_edit_zl_zone_call_in(target_zone_id bigint) TO authenticated;
GRANT ALL ON FUNCTION public.can_edit_zl_zone_call_in(target_zone_id bigint) TO service_role;


--
-- Name: FUNCTION can_unlock_planning_area(target_area_id bigint); Type: ACL; Schema: public; Owner: postgres
--

REVOKE ALL ON FUNCTION public.can_unlock_planning_area(target_area_id bigint) FROM PUBLIC;
GRANT ALL ON FUNCTION public.can_unlock_planning_area(target_area_id bigint) TO authenticated;
GRANT ALL ON FUNCTION public.can_unlock_planning_area(target_area_id bigint) TO service_role;


--
-- Name: FUNCTION can_view_call_in(target_level text, target_id bigint); Type: ACL; Schema: public; Owner: postgres
--

REVOKE ALL ON FUNCTION public.can_view_call_in(target_level text, target_id bigint) FROM PUBLIC;
GRANT ALL ON FUNCTION public.can_view_call_in(target_level text, target_id bigint) TO authenticated;
GRANT ALL ON FUNCTION public.can_view_call_in(target_level text, target_id bigint) TO service_role;


--
-- Name: FUNCTION carry_people_into_report(p_report_id bigint); Type: ACL; Schema: public; Owner: postgres
--

REVOKE ALL ON FUNCTION public.carry_people_into_report(p_report_id bigint) FROM PUBLIC;
GRANT ALL ON FUNCTION public.carry_people_into_report(p_report_id bigint) TO service_role;


--
-- Name: FUNCTION complete_dl_call_in(target_district_id bigint, target_reporting_week_id bigint); Type: ACL; Schema: public; Owner: postgres
--

REVOKE ALL ON FUNCTION public.complete_dl_call_in(target_district_id bigint, target_reporting_week_id bigint) FROM PUBLIC;
GRANT ALL ON FUNCTION public.complete_dl_call_in(target_district_id bigint, target_reporting_week_id bigint) TO authenticated;
GRANT ALL ON FUNCTION public.complete_dl_call_in(target_district_id bigint, target_reporting_week_id bigint) TO service_role;


--
-- Name: TABLE new_members; Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON TABLE public.new_members TO authenticated;
GRANT ALL ON TABLE public.new_members TO service_role;


--
-- Name: FUNCTION convert_baptismal_date_person_to_new_member(target_baptismal_date_person_id bigint, new_baptismal_date_extended date, new_baptism_date date, new_confirmation_date date, new_date_of_birth date, new_age_range text, new_gender text, new_marital_status text, new_child_dependents integer, new_living_situation text, new_native_language text, new_second_language text, new_mission_language_competency text, new_country_of_origin text, new_conversion_success_notes text); Type: ACL; Schema: public; Owner: postgres
--

REVOKE ALL ON FUNCTION public.convert_baptismal_date_person_to_new_member(target_baptismal_date_person_id bigint, new_baptismal_date_extended date, new_baptism_date date, new_confirmation_date date, new_date_of_birth date, new_age_range text, new_gender text, new_marital_status text, new_child_dependents integer, new_living_situation text, new_native_language text, new_second_language text, new_mission_language_competency text, new_country_of_origin text, new_conversion_success_notes text) FROM PUBLIC;
GRANT ALL ON FUNCTION public.convert_baptismal_date_person_to_new_member(target_baptismal_date_person_id bigint, new_baptismal_date_extended date, new_baptism_date date, new_confirmation_date date, new_date_of_birth date, new_age_range text, new_gender text, new_marital_status text, new_child_dependents integer, new_living_situation text, new_native_language text, new_second_language text, new_mission_language_competency text, new_country_of_origin text, new_conversion_success_notes text) TO authenticated;
GRANT ALL ON FUNCTION public.convert_baptismal_date_person_to_new_member(target_baptismal_date_person_id bigint, new_baptismal_date_extended date, new_baptism_date date, new_confirmation_date date, new_date_of_birth date, new_age_range text, new_gender text, new_marital_status text, new_child_dependents integer, new_living_situation text, new_native_language text, new_second_language text, new_mission_language_competency text, new_country_of_origin text, new_conversion_success_notes text) TO service_role;


--
-- Name: TABLE baptismal_date_people; Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON TABLE public.baptismal_date_people TO authenticated;
GRANT ALL ON TABLE public.baptismal_date_people TO service_role;


--
-- Name: FUNCTION create_baptismal_date_person(new_first_name text, new_last_name text, new_finding_source text, selected_unit_id bigint); Type: ACL; Schema: public; Owner: postgres
--

REVOKE ALL ON FUNCTION public.create_baptismal_date_person(new_first_name text, new_last_name text, new_finding_source text, selected_unit_id bigint) FROM PUBLIC;
GRANT ALL ON FUNCTION public.create_baptismal_date_person(new_first_name text, new_last_name text, new_finding_source text, selected_unit_id bigint) TO authenticated;
GRANT ALL ON FUNCTION public.create_baptismal_date_person(new_first_name text, new_last_name text, new_finding_source text, selected_unit_id bigint) TO service_role;


--
-- Name: FUNCTION create_new_member(new_first_name text, new_last_name text, new_stake_id bigint, new_unit_id bigint, new_baptismal_date_extended date, new_baptism_date date, new_confirmation_date date, new_finding_source text, new_date_of_birth date, new_age_range text, new_gender text, new_marital_status text, new_child_dependents integer, new_living_situation text, new_native_language text, new_second_language text, new_mission_language_competency text, new_country_of_origin text, new_conversion_success_notes text); Type: ACL; Schema: public; Owner: postgres
--

REVOKE ALL ON FUNCTION public.create_new_member(new_first_name text, new_last_name text, new_stake_id bigint, new_unit_id bigint, new_baptismal_date_extended date, new_baptism_date date, new_confirmation_date date, new_finding_source text, new_date_of_birth date, new_age_range text, new_gender text, new_marital_status text, new_child_dependents integer, new_living_situation text, new_native_language text, new_second_language text, new_mission_language_competency text, new_country_of_origin text, new_conversion_success_notes text) FROM PUBLIC;
GRANT ALL ON FUNCTION public.create_new_member(new_first_name text, new_last_name text, new_stake_id bigint, new_unit_id bigint, new_baptismal_date_extended date, new_baptism_date date, new_confirmation_date date, new_finding_source text, new_date_of_birth date, new_age_range text, new_gender text, new_marital_status text, new_child_dependents integer, new_living_situation text, new_native_language text, new_second_language text, new_mission_language_competency text, new_country_of_origin text, new_conversion_success_notes text) TO authenticated;
GRANT ALL ON FUNCTION public.create_new_member(new_first_name text, new_last_name text, new_stake_id bigint, new_unit_id bigint, new_baptismal_date_extended date, new_baptism_date date, new_confirmation_date date, new_finding_source text, new_date_of_birth date, new_age_range text, new_gender text, new_marital_status text, new_child_dependents integer, new_living_situation text, new_native_language text, new_second_language text, new_mission_language_competency text, new_country_of_origin text, new_conversion_success_notes text) TO service_role;


--
-- Name: FUNCTION current_reporting_sunday(); Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON FUNCTION public.current_reporting_sunday() TO anon;
GRANT ALL ON FUNCTION public.current_reporting_sunday() TO authenticated;
GRANT ALL ON FUNCTION public.current_reporting_sunday() TO service_role;


--
-- Name: FUNCTION current_user_area_id(); Type: ACL; Schema: public; Owner: postgres
--

REVOKE ALL ON FUNCTION public.current_user_area_id() FROM PUBLIC;
GRANT ALL ON FUNCTION public.current_user_area_id() TO authenticated;
GRANT ALL ON FUNCTION public.current_user_area_id() TO service_role;


--
-- Name: FUNCTION delete_baptismal_date_person_added_by_mistake(target_baptismal_date_person_id bigint); Type: ACL; Schema: public; Owner: postgres
--

REVOKE ALL ON FUNCTION public.delete_baptismal_date_person_added_by_mistake(target_baptismal_date_person_id bigint) FROM PUBLIC;
GRANT ALL ON FUNCTION public.delete_baptismal_date_person_added_by_mistake(target_baptismal_date_person_id bigint) TO authenticated;
GRANT ALL ON FUNCTION public.delete_baptismal_date_person_added_by_mistake(target_baptismal_date_person_id bigint) TO service_role;


--
-- Name: FUNCTION delete_new_member_added_by_mistake(target_new_member_id bigint); Type: ACL; Schema: public; Owner: postgres
--

REVOKE ALL ON FUNCTION public.delete_new_member_added_by_mistake(target_new_member_id bigint) FROM PUBLIC;
GRANT ALL ON FUNCTION public.delete_new_member_added_by_mistake(target_new_member_id bigint) TO authenticated;
GRANT ALL ON FUNCTION public.delete_new_member_added_by_mistake(target_new_member_id bigint) TO service_role;


--
-- Name: FUNCTION ensure_reporting_week(target_sunday date); Type: ACL; Schema: public; Owner: postgres
--

REVOKE ALL ON FUNCTION public.ensure_reporting_week(target_sunday date) FROM PUBLIC;
GRANT ALL ON FUNCTION public.ensure_reporting_week(target_sunday date) TO service_role;


--
-- Name: FUNCTION fill_current_week_plans(); Type: ACL; Schema: public; Owner: postgres
--

REVOKE ALL ON FUNCTION public.fill_current_week_plans() FROM PUBLIC;
GRANT ALL ON FUNCTION public.fill_current_week_plans() TO service_role;


--
-- Name: FUNCTION fill_weekly_baptismal_date_context(); Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON FUNCTION public.fill_weekly_baptismal_date_context() TO anon;
GRANT ALL ON FUNCTION public.fill_weekly_baptismal_date_context() TO authenticated;
GRANT ALL ON FUNCTION public.fill_weekly_baptismal_date_context() TO service_role;


--
-- Name: FUNCTION get_call_in_people(target_level text, target_id bigint, target_reporting_week_id bigint); Type: ACL; Schema: public; Owner: postgres
--

REVOKE ALL ON FUNCTION public.get_call_in_people(target_level text, target_id bigint, target_reporting_week_id bigint) FROM PUBLIC;
GRANT ALL ON FUNCTION public.get_call_in_people(target_level text, target_id bigint, target_reporting_week_id bigint) TO authenticated;
GRANT ALL ON FUNCTION public.get_call_in_people(target_level text, target_id bigint, target_reporting_week_id bigint) TO service_role;


--
-- Name: FUNCTION get_call_in_planning_metrics(target_reporting_week_id bigint, target_area_id bigint, target_district_id bigint, target_zone_id bigint, target_mission_id bigint); Type: ACL; Schema: public; Owner: postgres
--

REVOKE ALL ON FUNCTION public.get_call_in_planning_metrics(target_reporting_week_id bigint, target_area_id bigint, target_district_id bigint, target_zone_id bigint, target_mission_id bigint) FROM PUBLIC;
GRANT ALL ON FUNCTION public.get_call_in_planning_metrics(target_reporting_week_id bigint, target_area_id bigint, target_district_id bigint, target_zone_id bigint, target_mission_id bigint) TO authenticated;
GRANT ALL ON FUNCTION public.get_call_in_planning_metrics(target_reporting_week_id bigint, target_area_id bigint, target_district_id bigint, target_zone_id bigint, target_mission_id bigint) TO service_role;


--
-- Name: FUNCTION get_call_in_planning_previous_goals(target_reporting_week_id bigint, target_area_id bigint, target_district_id bigint, target_zone_id bigint, target_mission_id bigint); Type: ACL; Schema: public; Owner: postgres
--

REVOKE ALL ON FUNCTION public.get_call_in_planning_previous_goals(target_reporting_week_id bigint, target_area_id bigint, target_district_id bigint, target_zone_id bigint, target_mission_id bigint) FROM PUBLIC;
GRANT ALL ON FUNCTION public.get_call_in_planning_previous_goals(target_reporting_week_id bigint, target_area_id bigint, target_district_id bigint, target_zone_id bigint, target_mission_id bigint) TO authenticated;
GRANT ALL ON FUNCTION public.get_call_in_planning_previous_goals(target_reporting_week_id bigint, target_area_id bigint, target_district_id bigint, target_zone_id bigint, target_mission_id bigint) TO service_role;


--
-- Name: FUNCTION get_dl_call_in_baptismal_dates(target_district_id bigint, target_reporting_week_id bigint); Type: ACL; Schema: public; Owner: postgres
--

REVOKE ALL ON FUNCTION public.get_dl_call_in_baptismal_dates(target_district_id bigint, target_reporting_week_id bigint) FROM PUBLIC;
GRANT ALL ON FUNCTION public.get_dl_call_in_baptismal_dates(target_district_id bigint, target_reporting_week_id bigint) TO authenticated;
GRANT ALL ON FUNCTION public.get_dl_call_in_baptismal_dates(target_district_id bigint, target_reporting_week_id bigint) TO service_role;


--
-- Name: FUNCTION get_dl_call_in_bd_activity(target_district_id bigint, target_reporting_week_id bigint); Type: ACL; Schema: public; Owner: postgres
--

REVOKE ALL ON FUNCTION public.get_dl_call_in_bd_activity(target_district_id bigint, target_reporting_week_id bigint) FROM PUBLIC;
GRANT ALL ON FUNCTION public.get_dl_call_in_bd_activity(target_district_id bigint, target_reporting_week_id bigint) TO authenticated;
GRANT ALL ON FUNCTION public.get_dl_call_in_bd_activity(target_district_id bigint, target_reporting_week_id bigint) TO service_role;


--
-- Name: FUNCTION get_dl_call_in_high_potentials(target_district_id bigint, target_reporting_week_id bigint); Type: ACL; Schema: public; Owner: postgres
--

REVOKE ALL ON FUNCTION public.get_dl_call_in_high_potentials(target_district_id bigint, target_reporting_week_id bigint) FROM PUBLIC;
GRANT ALL ON FUNCTION public.get_dl_call_in_high_potentials(target_district_id bigint, target_reporting_week_id bigint) TO authenticated;
GRANT ALL ON FUNCTION public.get_dl_call_in_high_potentials(target_district_id bigint, target_reporting_week_id bigint) TO service_role;


--
-- Name: FUNCTION get_dl_call_in_hp_activity(target_district_id bigint, target_reporting_week_id bigint); Type: ACL; Schema: public; Owner: postgres
--

REVOKE ALL ON FUNCTION public.get_dl_call_in_hp_activity(target_district_id bigint, target_reporting_week_id bigint) FROM PUBLIC;
GRANT ALL ON FUNCTION public.get_dl_call_in_hp_activity(target_district_id bigint, target_reporting_week_id bigint) TO authenticated;
GRANT ALL ON FUNCTION public.get_dl_call_in_hp_activity(target_district_id bigint, target_reporting_week_id bigint) TO service_role;


--
-- Name: FUNCTION get_dl_call_in_new_members(target_district_id bigint, target_reporting_week_id bigint); Type: ACL; Schema: public; Owner: postgres
--

REVOKE ALL ON FUNCTION public.get_dl_call_in_new_members(target_district_id bigint, target_reporting_week_id bigint) FROM PUBLIC;
GRANT ALL ON FUNCTION public.get_dl_call_in_new_members(target_district_id bigint, target_reporting_week_id bigint) TO authenticated;
GRANT ALL ON FUNCTION public.get_dl_call_in_new_members(target_district_id bigint, target_reporting_week_id bigint) TO service_role;


--
-- Name: FUNCTION get_dl_call_in_nm_activity(target_district_id bigint, target_reporting_week_id bigint); Type: ACL; Schema: public; Owner: postgres
--

REVOKE ALL ON FUNCTION public.get_dl_call_in_nm_activity(target_district_id bigint, target_reporting_week_id bigint) FROM PUBLIC;
GRANT ALL ON FUNCTION public.get_dl_call_in_nm_activity(target_district_id bigint, target_reporting_week_id bigint) TO authenticated;
GRANT ALL ON FUNCTION public.get_dl_call_in_nm_activity(target_district_id bigint, target_reporting_week_id bigint) TO service_role;


--
-- Name: FUNCTION get_dl_call_in_summary(target_district_id bigint, target_reporting_week_id bigint); Type: ACL; Schema: public; Owner: postgres
--

REVOKE ALL ON FUNCTION public.get_dl_call_in_summary(target_district_id bigint, target_reporting_week_id bigint) FROM PUBLIC;
GRANT ALL ON FUNCTION public.get_dl_call_in_summary(target_district_id bigint, target_reporting_week_id bigint) TO authenticated;
GRANT ALL ON FUNCTION public.get_dl_call_in_summary(target_district_id bigint, target_reporting_week_id bigint) TO service_role;


--
-- Name: FUNCTION get_dl_call_in_summary_with_planning(target_district_id bigint, target_reporting_week_id bigint); Type: ACL; Schema: public; Owner: postgres
--

REVOKE ALL ON FUNCTION public.get_dl_call_in_summary_with_planning(target_district_id bigint, target_reporting_week_id bigint) FROM PUBLIC;
GRANT ALL ON FUNCTION public.get_dl_call_in_summary_with_planning(target_district_id bigint, target_reporting_week_id bigint) TO authenticated;
GRANT ALL ON FUNCTION public.get_dl_call_in_summary_with_planning(target_district_id bigint, target_reporting_week_id bigint) TO service_role;


--
-- Name: FUNCTION get_dl_call_in_ward_coordination(target_district_id bigint, target_reporting_week_id bigint); Type: ACL; Schema: public; Owner: postgres
--

REVOKE ALL ON FUNCTION public.get_dl_call_in_ward_coordination(target_district_id bigint, target_reporting_week_id bigint) FROM PUBLIC;
GRANT ALL ON FUNCTION public.get_dl_call_in_ward_coordination(target_district_id bigint, target_reporting_week_id bigint) TO authenticated;
GRANT ALL ON FUNCTION public.get_dl_call_in_ward_coordination(target_district_id bigint, target_reporting_week_id bigint) TO service_role;


--
-- Name: FUNCTION get_mission_call_in_bd_activity(target_mission_id bigint, target_reporting_week_id bigint); Type: ACL; Schema: public; Owner: postgres
--

REVOKE ALL ON FUNCTION public.get_mission_call_in_bd_activity(target_mission_id bigint, target_reporting_week_id bigint) FROM PUBLIC;
GRANT ALL ON FUNCTION public.get_mission_call_in_bd_activity(target_mission_id bigint, target_reporting_week_id bigint) TO authenticated;
GRANT ALL ON FUNCTION public.get_mission_call_in_bd_activity(target_mission_id bigint, target_reporting_week_id bigint) TO service_role;


--
-- Name: FUNCTION get_mission_call_in_hp_activity(target_mission_id bigint, target_reporting_week_id bigint); Type: ACL; Schema: public; Owner: postgres
--

REVOKE ALL ON FUNCTION public.get_mission_call_in_hp_activity(target_mission_id bigint, target_reporting_week_id bigint) FROM PUBLIC;
GRANT ALL ON FUNCTION public.get_mission_call_in_hp_activity(target_mission_id bigint, target_reporting_week_id bigint) TO authenticated;
GRANT ALL ON FUNCTION public.get_mission_call_in_hp_activity(target_mission_id bigint, target_reporting_week_id bigint) TO service_role;


--
-- Name: FUNCTION get_mission_call_in_nm_activity(target_mission_id bigint, target_reporting_week_id bigint); Type: ACL; Schema: public; Owner: postgres
--

REVOKE ALL ON FUNCTION public.get_mission_call_in_nm_activity(target_mission_id bigint, target_reporting_week_id bigint) FROM PUBLIC;
GRANT ALL ON FUNCTION public.get_mission_call_in_nm_activity(target_mission_id bigint, target_reporting_week_id bigint) TO authenticated;
GRANT ALL ON FUNCTION public.get_mission_call_in_nm_activity(target_mission_id bigint, target_reporting_week_id bigint) TO service_role;


--
-- Name: FUNCTION get_mission_call_in_summary(target_mission_id bigint, target_reporting_week_id bigint); Type: ACL; Schema: public; Owner: postgres
--

REVOKE ALL ON FUNCTION public.get_mission_call_in_summary(target_mission_id bigint, target_reporting_week_id bigint) FROM PUBLIC;
GRANT ALL ON FUNCTION public.get_mission_call_in_summary(target_mission_id bigint, target_reporting_week_id bigint) TO authenticated;
GRANT ALL ON FUNCTION public.get_mission_call_in_summary(target_mission_id bigint, target_reporting_week_id bigint) TO service_role;


--
-- Name: FUNCTION get_mission_call_in_summary_with_planning(target_mission_id bigint, target_reporting_week_id bigint); Type: ACL; Schema: public; Owner: postgres
--

REVOKE ALL ON FUNCTION public.get_mission_call_in_summary_with_planning(target_mission_id bigint, target_reporting_week_id bigint) FROM PUBLIC;
GRANT ALL ON FUNCTION public.get_mission_call_in_summary_with_planning(target_mission_id bigint, target_reporting_week_id bigint) TO authenticated;
GRANT ALL ON FUNCTION public.get_mission_call_in_summary_with_planning(target_mission_id bigint, target_reporting_week_id bigint) TO service_role;


--
-- Name: FUNCTION get_previous_planning_answers(target_unit_id bigint); Type: ACL; Schema: public; Owner: postgres
--

REVOKE ALL ON FUNCTION public.get_previous_planning_answers(target_unit_id bigint) FROM PUBLIC;
GRANT ALL ON FUNCTION public.get_previous_planning_answers(target_unit_id bigint) TO authenticated;
GRANT ALL ON FUNCTION public.get_previous_planning_answers(target_unit_id bigint) TO service_role;


--
-- Name: TABLE weekly_new_members; Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON TABLE public.weekly_new_members TO authenticated;
GRANT ALL ON TABLE public.weekly_new_members TO service_role;


--
-- Name: FUNCTION get_previous_weekly_new_members(target_unit_id bigint); Type: ACL; Schema: public; Owner: postgres
--

REVOKE ALL ON FUNCTION public.get_previous_weekly_new_members(target_unit_id bigint) FROM PUBLIC;
GRANT ALL ON FUNCTION public.get_previous_weekly_new_members(target_unit_id bigint) TO authenticated;
GRANT ALL ON FUNCTION public.get_previous_weekly_new_members(target_unit_id bigint) TO service_role;


--
-- Name: FUNCTION get_zl_call_in_area_updates(target_zone_id bigint, target_reporting_week_id bigint); Type: ACL; Schema: public; Owner: postgres
--

REVOKE ALL ON FUNCTION public.get_zl_call_in_area_updates(target_zone_id bigint, target_reporting_week_id bigint) FROM PUBLIC;
GRANT ALL ON FUNCTION public.get_zl_call_in_area_updates(target_zone_id bigint, target_reporting_week_id bigint) TO authenticated;
GRANT ALL ON FUNCTION public.get_zl_call_in_area_updates(target_zone_id bigint, target_reporting_week_id bigint) TO service_role;


--
-- Name: FUNCTION get_zl_call_in_baptismal_dates(target_zone_id bigint, target_reporting_week_id bigint); Type: ACL; Schema: public; Owner: postgres
--

REVOKE ALL ON FUNCTION public.get_zl_call_in_baptismal_dates(target_zone_id bigint, target_reporting_week_id bigint) FROM PUBLIC;
GRANT ALL ON FUNCTION public.get_zl_call_in_baptismal_dates(target_zone_id bigint, target_reporting_week_id bigint) TO authenticated;
GRANT ALL ON FUNCTION public.get_zl_call_in_baptismal_dates(target_zone_id bigint, target_reporting_week_id bigint) TO service_role;


--
-- Name: FUNCTION get_zl_call_in_bd_activity(target_zone_id bigint, target_reporting_week_id bigint); Type: ACL; Schema: public; Owner: postgres
--

REVOKE ALL ON FUNCTION public.get_zl_call_in_bd_activity(target_zone_id bigint, target_reporting_week_id bigint) FROM PUBLIC;
GRANT ALL ON FUNCTION public.get_zl_call_in_bd_activity(target_zone_id bigint, target_reporting_week_id bigint) TO authenticated;
GRANT ALL ON FUNCTION public.get_zl_call_in_bd_activity(target_zone_id bigint, target_reporting_week_id bigint) TO service_role;


--
-- Name: FUNCTION get_zl_call_in_high_potentials(target_zone_id bigint, target_reporting_week_id bigint); Type: ACL; Schema: public; Owner: postgres
--

REVOKE ALL ON FUNCTION public.get_zl_call_in_high_potentials(target_zone_id bigint, target_reporting_week_id bigint) FROM PUBLIC;
GRANT ALL ON FUNCTION public.get_zl_call_in_high_potentials(target_zone_id bigint, target_reporting_week_id bigint) TO authenticated;
GRANT ALL ON FUNCTION public.get_zl_call_in_high_potentials(target_zone_id bigint, target_reporting_week_id bigint) TO service_role;


--
-- Name: FUNCTION get_zl_call_in_hp_activity(target_zone_id bigint, target_reporting_week_id bigint); Type: ACL; Schema: public; Owner: postgres
--

REVOKE ALL ON FUNCTION public.get_zl_call_in_hp_activity(target_zone_id bigint, target_reporting_week_id bigint) FROM PUBLIC;
GRANT ALL ON FUNCTION public.get_zl_call_in_hp_activity(target_zone_id bigint, target_reporting_week_id bigint) TO authenticated;
GRANT ALL ON FUNCTION public.get_zl_call_in_hp_activity(target_zone_id bigint, target_reporting_week_id bigint) TO service_role;


--
-- Name: FUNCTION get_zl_call_in_new_members(target_zone_id bigint, target_reporting_week_id bigint); Type: ACL; Schema: public; Owner: postgres
--

REVOKE ALL ON FUNCTION public.get_zl_call_in_new_members(target_zone_id bigint, target_reporting_week_id bigint) FROM PUBLIC;
GRANT ALL ON FUNCTION public.get_zl_call_in_new_members(target_zone_id bigint, target_reporting_week_id bigint) TO authenticated;
GRANT ALL ON FUNCTION public.get_zl_call_in_new_members(target_zone_id bigint, target_reporting_week_id bigint) TO service_role;


--
-- Name: FUNCTION get_zl_call_in_nm_activity(target_zone_id bigint, target_reporting_week_id bigint); Type: ACL; Schema: public; Owner: postgres
--

REVOKE ALL ON FUNCTION public.get_zl_call_in_nm_activity(target_zone_id bigint, target_reporting_week_id bigint) FROM PUBLIC;
GRANT ALL ON FUNCTION public.get_zl_call_in_nm_activity(target_zone_id bigint, target_reporting_week_id bigint) TO authenticated;
GRANT ALL ON FUNCTION public.get_zl_call_in_nm_activity(target_zone_id bigint, target_reporting_week_id bigint) TO service_role;


--
-- Name: FUNCTION get_zl_call_in_summary(target_zone_id bigint, target_reporting_week_id bigint); Type: ACL; Schema: public; Owner: postgres
--

REVOKE ALL ON FUNCTION public.get_zl_call_in_summary(target_zone_id bigint, target_reporting_week_id bigint) FROM PUBLIC;
GRANT ALL ON FUNCTION public.get_zl_call_in_summary(target_zone_id bigint, target_reporting_week_id bigint) TO authenticated;
GRANT ALL ON FUNCTION public.get_zl_call_in_summary(target_zone_id bigint, target_reporting_week_id bigint) TO service_role;


--
-- Name: FUNCTION get_zl_call_in_summary_with_planning(target_zone_id bigint, target_reporting_week_id bigint); Type: ACL; Schema: public; Owner: postgres
--

REVOKE ALL ON FUNCTION public.get_zl_call_in_summary_with_planning(target_zone_id bigint, target_reporting_week_id bigint) FROM PUBLIC;
GRANT ALL ON FUNCTION public.get_zl_call_in_summary_with_planning(target_zone_id bigint, target_reporting_week_id bigint) TO authenticated;
GRANT ALL ON FUNCTION public.get_zl_call_in_summary_with_planning(target_zone_id bigint, target_reporting_week_id bigint) TO service_role;


--
-- Name: FUNCTION get_zl_call_in_zone_notes(target_zone_id bigint, target_reporting_week_id bigint); Type: ACL; Schema: public; Owner: postgres
--

REVOKE ALL ON FUNCTION public.get_zl_call_in_zone_notes(target_zone_id bigint, target_reporting_week_id bigint) FROM PUBLIC;
GRANT ALL ON FUNCTION public.get_zl_call_in_zone_notes(target_zone_id bigint, target_reporting_week_id bigint) TO authenticated;
GRANT ALL ON FUNCTION public.get_zl_call_in_zone_notes(target_zone_id bigint, target_reporting_week_id bigint) TO service_role;


--
-- Name: FUNCTION guard_call_in_write(); Type: ACL; Schema: public; Owner: postgres
--

REVOKE ALL ON FUNCTION public.guard_call_in_write() FROM PUBLIC;
GRANT ALL ON FUNCTION public.guard_call_in_write() TO authenticated;
GRANT ALL ON FUNCTION public.guard_call_in_write() TO service_role;


--
-- Name: FUNCTION guard_shared_planning_child(); Type: ACL; Schema: public; Owner: postgres
--

REVOKE ALL ON FUNCTION public.guard_shared_planning_child() FROM PUBLIC;
GRANT ALL ON FUNCTION public.guard_shared_planning_child() TO authenticated;
GRANT ALL ON FUNCTION public.guard_shared_planning_child() TO service_role;


--
-- Name: FUNCTION guard_shared_planning_report(); Type: ACL; Schema: public; Owner: postgres
--

REVOKE ALL ON FUNCTION public.guard_shared_planning_report() FROM PUBLIC;
GRANT ALL ON FUNCTION public.guard_shared_planning_report() TO authenticated;
GRANT ALL ON FUNCTION public.guard_shared_planning_report() TO service_role;


--
-- Name: FUNCTION is_assignment_admin(); Type: ACL; Schema: public; Owner: postgres
--

REVOKE ALL ON FUNCTION public.is_assignment_admin() FROM PUBLIC;
GRANT ALL ON FUNCTION public.is_assignment_admin() TO authenticated;
GRANT ALL ON FUNCTION public.is_assignment_admin() TO service_role;


--
-- Name: FUNCTION is_call_in_district_leader(target_district_id bigint); Type: ACL; Schema: public; Owner: postgres
--

REVOKE ALL ON FUNCTION public.is_call_in_district_leader(target_district_id bigint) FROM PUBLIC;
GRANT ALL ON FUNCTION public.is_call_in_district_leader(target_district_id bigint) TO authenticated;
GRANT ALL ON FUNCTION public.is_call_in_district_leader(target_district_id bigint) TO service_role;


--
-- Name: FUNCTION is_call_in_zone_leader(target_zone_id bigint); Type: ACL; Schema: public; Owner: postgres
--

REVOKE ALL ON FUNCTION public.is_call_in_zone_leader(target_zone_id bigint) FROM PUBLIC;
GRANT ALL ON FUNCTION public.is_call_in_zone_leader(target_zone_id bigint) TO authenticated;
GRANT ALL ON FUNCTION public.is_call_in_zone_leader(target_zone_id bigint) TO service_role;


--
-- Name: FUNCTION is_current_user_area(target_area_id bigint); Type: ACL; Schema: public; Owner: postgres
--

REVOKE ALL ON FUNCTION public.is_current_user_area(target_area_id bigint) FROM PUBLIC;
GRANT ALL ON FUNCTION public.is_current_user_area(target_area_id bigint) TO authenticated;
GRANT ALL ON FUNCTION public.is_current_user_area(target_area_id bigint) TO service_role;


--
-- Name: FUNCTION is_mission_manager_for_area(target_area_id bigint); Type: ACL; Schema: public; Owner: postgres
--

REVOKE ALL ON FUNCTION public.is_mission_manager_for_area(target_area_id bigint) FROM PUBLIC;
GRANT ALL ON FUNCTION public.is_mission_manager_for_area(target_area_id bigint) TO authenticated;
GRANT ALL ON FUNCTION public.is_mission_manager_for_area(target_area_id bigint) TO service_role;


--
-- Name: FUNCTION planning_catalog_bump_version(); Type: ACL; Schema: public; Owner: postgres
--

REVOKE ALL ON FUNCTION public.planning_catalog_bump_version() FROM PUBLIC;
GRANT ALL ON FUNCTION public.planning_catalog_bump_version() TO authenticated;
GRANT ALL ON FUNCTION public.planning_catalog_bump_version() TO service_role;


--
-- Name: FUNCTION planning_catalog_no_truncate(); Type: ACL; Schema: public; Owner: postgres
--

REVOKE ALL ON FUNCTION public.planning_catalog_no_truncate() FROM PUBLIC;
GRANT ALL ON FUNCTION public.planning_catalog_no_truncate() TO authenticated;
GRANT ALL ON FUNCTION public.planning_catalog_no_truncate() TO service_role;


--
-- Name: FUNCTION planning_catalog_touch(); Type: ACL; Schema: public; Owner: postgres
--

REVOKE ALL ON FUNCTION public.planning_catalog_touch() FROM PUBLIC;
GRANT ALL ON FUNCTION public.planning_catalog_touch() TO authenticated;
GRANT ALL ON FUNCTION public.planning_catalog_touch() TO service_role;


--
-- Name: FUNCTION planning_kpi_value(answer_value numeric, fallback_value integer); Type: ACL; Schema: public; Owner: postgres
--

REVOKE ALL ON FUNCTION public.planning_kpi_value(answer_value numeric, fallback_value integer) FROM PUBLIC;
GRANT ALL ON FUNCTION public.planning_kpi_value(answer_value numeric, fallback_value integer) TO authenticated;
GRANT ALL ON FUNCTION public.planning_kpi_value(answer_value numeric, fallback_value integer) TO service_role;


--
-- Name: FUNCTION planning_option_used(target_question_key text, target_value text); Type: ACL; Schema: public; Owner: postgres
--

REVOKE ALL ON FUNCTION public.planning_option_used(target_question_key text, target_value text) FROM PUBLIC;


--
-- Name: FUNCTION planning_question_grid_rows_guard(); Type: ACL; Schema: public; Owner: postgres
--

REVOKE ALL ON FUNCTION public.planning_question_grid_rows_guard() FROM PUBLIC;
GRANT ALL ON FUNCTION public.planning_question_grid_rows_guard() TO authenticated;
GRANT ALL ON FUNCTION public.planning_question_grid_rows_guard() TO service_role;


--
-- Name: FUNCTION planning_question_options_guard(); Type: ACL; Schema: public; Owner: postgres
--

REVOKE ALL ON FUNCTION public.planning_question_options_guard() FROM PUBLIC;
GRANT ALL ON FUNCTION public.planning_question_options_guard() TO authenticated;
GRANT ALL ON FUNCTION public.planning_question_options_guard() TO service_role;


--
-- Name: FUNCTION planning_question_sections_guard(); Type: ACL; Schema: public; Owner: postgres
--

REVOKE ALL ON FUNCTION public.planning_question_sections_guard() FROM PUBLIC;
GRANT ALL ON FUNCTION public.planning_question_sections_guard() TO authenticated;
GRANT ALL ON FUNCTION public.planning_question_sections_guard() TO service_role;


--
-- Name: FUNCTION planning_questions_guard(); Type: ACL; Schema: public; Owner: postgres
--

REVOKE ALL ON FUNCTION public.planning_questions_guard() FROM PUBLIC;
GRANT ALL ON FUNCTION public.planning_questions_guard() TO authenticated;
GRANT ALL ON FUNCTION public.planning_questions_guard() TO service_role;


--
-- Name: FUNCTION planning_visibility_rules_guard(); Type: ACL; Schema: public; Owner: postgres
--

REVOKE ALL ON FUNCTION public.planning_visibility_rules_guard() FROM PUBLIC;
GRANT ALL ON FUNCTION public.planning_visibility_rules_guard() TO authenticated;
GRANT ALL ON FUNCTION public.planning_visibility_rules_guard() TO service_role;


--
-- Name: FUNCTION portal_planning_trusted_write(); Type: ACL; Schema: public; Owner: postgres
--

REVOKE ALL ON FUNCTION public.portal_planning_trusted_write() FROM PUBLIC;
GRANT ALL ON FUNCTION public.portal_planning_trusted_write() TO authenticated;
GRANT ALL ON FUNCTION public.portal_planning_trusted_write() TO service_role;


--
-- Name: FUNCTION reactivate_new_member(target_new_member_id bigint); Type: ACL; Schema: public; Owner: postgres
--

REVOKE ALL ON FUNCTION public.reactivate_new_member(target_new_member_id bigint) FROM PUBLIC;
GRANT ALL ON FUNCTION public.reactivate_new_member(target_new_member_id bigint) TO service_role;


--
-- Name: FUNCTION reactivate_new_member(target_new_member_id bigint, target_unit_id bigint); Type: ACL; Schema: public; Owner: postgres
--

REVOKE ALL ON FUNCTION public.reactivate_new_member(target_new_member_id bigint, target_unit_id bigint) FROM PUBLIC;
GRANT ALL ON FUNCTION public.reactivate_new_member(target_new_member_id bigint, target_unit_id bigint) TO service_role;


--
-- Name: FUNCTION reopen_dl_call_in(target_district_id bigint, target_reporting_week_id bigint); Type: ACL; Schema: public; Owner: postgres
--

REVOKE ALL ON FUNCTION public.reopen_dl_call_in(target_district_id bigint, target_reporting_week_id bigint) FROM PUBLIC;
GRANT ALL ON FUNCTION public.reopen_dl_call_in(target_district_id bigint, target_reporting_week_id bigint) TO authenticated;
GRANT ALL ON FUNCTION public.reopen_dl_call_in(target_district_id bigint, target_reporting_week_id bigint) TO service_role;


--
-- Name: FUNCTION reopen_weekly_report(target_report_id bigint); Type: ACL; Schema: public; Owner: postgres
--

REVOKE ALL ON FUNCTION public.reopen_weekly_report(target_report_id bigint) FROM PUBLIC;
GRANT ALL ON FUNCTION public.reopen_weekly_report(target_report_id bigint) TO authenticated;
GRANT ALL ON FUNCTION public.reopen_weekly_report(target_report_id bigint) TO service_role;


--
-- Name: FUNCTION reporting_sunday_at(at_time timestamp with time zone); Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON FUNCTION public.reporting_sunday_at(at_time timestamp with time zone) TO anon;
GRANT ALL ON FUNCTION public.reporting_sunday_at(at_time timestamp with time zone) TO authenticated;
GRANT ALL ON FUNCTION public.reporting_sunday_at(at_time timestamp with time zone) TO service_role;


--
-- Name: FUNCTION save_call_in_area_update(target_district_id bigint, target_reporting_week_id bigint, target_area_id bigint, new_update_text text); Type: ACL; Schema: public; Owner: postgres
--

REVOKE ALL ON FUNCTION public.save_call_in_area_update(target_district_id bigint, target_reporting_week_id bigint, target_area_id bigint, new_update_text text) FROM PUBLIC;
GRANT ALL ON FUNCTION public.save_call_in_area_update(target_district_id bigint, target_reporting_week_id bigint, target_area_id bigint, new_update_text text) TO authenticated;
GRANT ALL ON FUNCTION public.save_call_in_area_update(target_district_id bigint, target_reporting_week_id bigint, target_area_id bigint, new_update_text text) TO service_role;


--
-- Name: FUNCTION save_current_planning_answer(target_unit_id bigint, question_key text, answer_text text, answer_number numeric, answer_boolean boolean, answer_json jsonb); Type: ACL; Schema: public; Owner: postgres
--

REVOKE ALL ON FUNCTION public.save_current_planning_answer(target_unit_id bigint, question_key text, answer_text text, answer_number numeric, answer_boolean boolean, answer_json jsonb) FROM PUBLIC;
GRANT ALL ON FUNCTION public.save_current_planning_answer(target_unit_id bigint, question_key text, answer_text text, answer_number numeric, answer_boolean boolean, answer_json jsonb) TO authenticated;
GRANT ALL ON FUNCTION public.save_current_planning_answer(target_unit_id bigint, question_key text, answer_text text, answer_number numeric, answer_boolean boolean, answer_json jsonb) TO service_role;


--
-- Name: FUNCTION save_dl_call_in_notes(target_district_id bigint, target_reporting_week_id bigint, new_dl_notes text, new_thank_you text); Type: ACL; Schema: public; Owner: postgres
--

REVOKE ALL ON FUNCTION public.save_dl_call_in_notes(target_district_id bigint, target_reporting_week_id bigint, new_dl_notes text, new_thank_you text) FROM PUBLIC;
GRANT ALL ON FUNCTION public.save_dl_call_in_notes(target_district_id bigint, target_reporting_week_id bigint, new_dl_notes text, new_thank_you text) TO authenticated;
GRANT ALL ON FUNCTION public.save_dl_call_in_notes(target_district_id bigint, target_reporting_week_id bigint, new_dl_notes text, new_thank_you text) TO service_role;


--
-- Name: FUNCTION save_zl_call_in_notes(target_district_id bigint, target_reporting_week_id bigint, new_zl_notes text); Type: ACL; Schema: public; Owner: postgres
--

REVOKE ALL ON FUNCTION public.save_zl_call_in_notes(target_district_id bigint, target_reporting_week_id bigint, new_zl_notes text) FROM PUBLIC;
GRANT ALL ON FUNCTION public.save_zl_call_in_notes(target_district_id bigint, target_reporting_week_id bigint, new_zl_notes text) TO authenticated;
GRANT ALL ON FUNCTION public.save_zl_call_in_notes(target_district_id bigint, target_reporting_week_id bigint, new_zl_notes text) TO service_role;


--
-- Name: FUNCTION save_zl_zone_call_in_notes(target_zone_id bigint, target_reporting_week_id bigint, new_zone_notes text); Type: ACL; Schema: public; Owner: postgres
--

REVOKE ALL ON FUNCTION public.save_zl_zone_call_in_notes(target_zone_id bigint, target_reporting_week_id bigint, new_zone_notes text) FROM PUBLIC;
GRANT ALL ON FUNCTION public.save_zl_zone_call_in_notes(target_zone_id bigint, target_reporting_week_id bigint, new_zone_notes text) TO authenticated;
GRANT ALL ON FUNCTION public.save_zl_zone_call_in_notes(target_zone_id bigint, target_reporting_week_id bigint, new_zone_notes text) TO service_role;


--
-- Name: FUNCTION start_current_weekly_report(); Type: ACL; Schema: public; Owner: postgres
--

REVOKE ALL ON FUNCTION public.start_current_weekly_report() FROM PUBLIC;
GRANT ALL ON FUNCTION public.start_current_weekly_report() TO authenticated;
GRANT ALL ON FUNCTION public.start_current_weekly_report() TO service_role;


--
-- Name: FUNCTION start_current_weekly_report(target_unit_id bigint); Type: ACL; Schema: public; Owner: postgres
--

REVOKE ALL ON FUNCTION public.start_current_weekly_report(target_unit_id bigint) FROM PUBLIC;
GRANT ALL ON FUNCTION public.start_current_weekly_report(target_unit_id bigint) TO service_role;
GRANT ALL ON FUNCTION public.start_current_weekly_report(target_unit_id bigint) TO authenticated;


--
-- Name: FUNCTION submit_current_weekly_report(target_unit_id bigint); Type: ACL; Schema: public; Owner: postgres
--

REVOKE ALL ON FUNCTION public.submit_current_weekly_report(target_unit_id bigint) FROM PUBLIC;
GRANT ALL ON FUNCTION public.submit_current_weekly_report(target_unit_id bigint) TO authenticated;
GRANT ALL ON FUNCTION public.submit_current_weekly_report(target_unit_id bigint) TO service_role;


--
-- Name: FUNCTION sync_baptismal_date_person_display_name(); Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON FUNCTION public.sync_baptismal_date_person_display_name() TO anon;
GRANT ALL ON FUNCTION public.sync_baptismal_date_person_display_name() TO authenticated;
GRANT ALL ON FUNCTION public.sync_baptismal_date_person_display_name() TO service_role;


--
-- Name: FUNCTION sync_current_companionships(); Type: ACL; Schema: public; Owner: postgres
--

REVOKE ALL ON FUNCTION public.sync_current_companionships() FROM PUBLIC;
GRANT ALL ON FUNCTION public.sync_current_companionships() TO service_role;
GRANT ALL ON FUNCTION public.sync_current_companionships() TO authenticated;


--
-- Name: FUNCTION sync_new_member_display_name(); Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON FUNCTION public.sync_new_member_display_name() TO anon;
GRANT ALL ON FUNCTION public.sync_new_member_display_name() TO authenticated;
GRANT ALL ON FUNCTION public.sync_new_member_display_name() TO service_role;


--
-- Name: FUNCTION sync_user_profile_roles(); Type: ACL; Schema: public; Owner: postgres
--

REVOKE ALL ON FUNCTION public.sync_user_profile_roles() FROM PUBLIC;
GRANT ALL ON FUNCTION public.sync_user_profile_roles() TO service_role;


--
-- Name: FUNCTION transfer_baptismal_date_person(target_baptismal_date_person_id bigint, target_area_id bigint, target_unit_id bigint); Type: ACL; Schema: public; Owner: postgres
--

REVOKE ALL ON FUNCTION public.transfer_baptismal_date_person(target_baptismal_date_person_id bigint, target_area_id bigint, target_unit_id bigint) FROM PUBLIC;
GRANT ALL ON FUNCTION public.transfer_baptismal_date_person(target_baptismal_date_person_id bigint, target_area_id bigint, target_unit_id bigint) TO authenticated;
GRANT ALL ON FUNCTION public.transfer_baptismal_date_person(target_baptismal_date_person_id bigint, target_area_id bigint, target_unit_id bigint) TO service_role;


--
-- Name: FUNCTION transfer_new_member(target_new_member_id bigint, target_area_id bigint); Type: ACL; Schema: public; Owner: postgres
--

REVOKE ALL ON FUNCTION public.transfer_new_member(target_new_member_id bigint, target_area_id bigint) FROM PUBLIC;
GRANT ALL ON FUNCTION public.transfer_new_member(target_new_member_id bigint, target_area_id bigint) TO authenticated;
GRANT ALL ON FUNCTION public.transfer_new_member(target_new_member_id bigint, target_area_id bigint) TO service_role;


--
-- Name: FUNCTION transfer_new_member(target_new_member_id bigint, target_area_id bigint, target_unit_id bigint); Type: ACL; Schema: public; Owner: postgres
--

REVOKE ALL ON FUNCTION public.transfer_new_member(target_new_member_id bigint, target_area_id bigint, target_unit_id bigint) FROM PUBLIC;
GRANT ALL ON FUNCTION public.transfer_new_member(target_new_member_id bigint, target_area_id bigint, target_unit_id bigint) TO authenticated;
GRANT ALL ON FUNCTION public.transfer_new_member(target_new_member_id bigint, target_area_id bigint, target_unit_id bigint) TO service_role;


--
-- Name: FUNCTION unsubmit_weekly_report(target_report_id bigint); Type: ACL; Schema: public; Owner: postgres
--

REVOKE ALL ON FUNCTION public.unsubmit_weekly_report(target_report_id bigint) FROM PUBLIC;
GRANT ALL ON FUNCTION public.unsubmit_weekly_report(target_report_id bigint) TO authenticated;
GRANT ALL ON FUNCTION public.unsubmit_weekly_report(target_report_id bigint) TO service_role;


--
-- Name: FUNCTION update_baptismal_date_person(target_baptismal_date_person_id bigint, new_first_name text, new_last_name text, new_finding_source text); Type: ACL; Schema: public; Owner: postgres
--

REVOKE ALL ON FUNCTION public.update_baptismal_date_person(target_baptismal_date_person_id bigint, new_first_name text, new_last_name text, new_finding_source text) FROM PUBLIC;
GRANT ALL ON FUNCTION public.update_baptismal_date_person(target_baptismal_date_person_id bigint, new_first_name text, new_last_name text, new_finding_source text) TO authenticated;
GRANT ALL ON FUNCTION public.update_baptismal_date_person(target_baptismal_date_person_id bigint, new_first_name text, new_last_name text, new_finding_source text) TO service_role;


--
-- Name: FUNCTION update_current_weekly_report(target_unit_id bigint, new_friends_found_actual integer, new_friends_found_goal integer, new_lessons_with_friends_actual integer, new_lessons_with_friends_goal integer, new_lessons_with_members_actual integer, new_lessons_with_members_goal integer, new_sacrament_attendance_actual integer, new_sacrament_attendance_goal integer, new_first_time_sacrament_actual integer, new_baptismal_dates_actual integer, new_baptismal_dates_goal integer, new_baptisms_confirmations_actual integer, new_baptisms_confirmations_goal integer, new_new_member_sacrament_actual integer, new_new_member_sacrament_goal integer, new_follow_up_lessons_actual integer, new_follow_up_lessons_goal integer, new_notes text); Type: ACL; Schema: public; Owner: postgres
--

REVOKE ALL ON FUNCTION public.update_current_weekly_report(target_unit_id bigint, new_friends_found_actual integer, new_friends_found_goal integer, new_lessons_with_friends_actual integer, new_lessons_with_friends_goal integer, new_lessons_with_members_actual integer, new_lessons_with_members_goal integer, new_sacrament_attendance_actual integer, new_sacrament_attendance_goal integer, new_first_time_sacrament_actual integer, new_baptismal_dates_actual integer, new_baptismal_dates_goal integer, new_baptisms_confirmations_actual integer, new_baptisms_confirmations_goal integer, new_new_member_sacrament_actual integer, new_new_member_sacrament_goal integer, new_follow_up_lessons_actual integer, new_follow_up_lessons_goal integer, new_notes text) FROM PUBLIC;
GRANT ALL ON FUNCTION public.update_current_weekly_report(target_unit_id bigint, new_friends_found_actual integer, new_friends_found_goal integer, new_lessons_with_friends_actual integer, new_lessons_with_friends_goal integer, new_lessons_with_members_actual integer, new_lessons_with_members_goal integer, new_sacrament_attendance_actual integer, new_sacrament_attendance_goal integer, new_first_time_sacrament_actual integer, new_baptismal_dates_actual integer, new_baptismal_dates_goal integer, new_baptisms_confirmations_actual integer, new_baptisms_confirmations_goal integer, new_new_member_sacrament_actual integer, new_new_member_sacrament_goal integer, new_follow_up_lessons_actual integer, new_follow_up_lessons_goal integer, new_notes text) TO authenticated;
GRANT ALL ON FUNCTION public.update_current_weekly_report(target_unit_id bigint, new_friends_found_actual integer, new_friends_found_goal integer, new_lessons_with_friends_actual integer, new_lessons_with_friends_goal integer, new_lessons_with_members_actual integer, new_lessons_with_members_goal integer, new_sacrament_attendance_actual integer, new_sacrament_attendance_goal integer, new_first_time_sacrament_actual integer, new_baptismal_dates_actual integer, new_baptismal_dates_goal integer, new_baptisms_confirmations_actual integer, new_baptisms_confirmations_goal integer, new_new_member_sacrament_actual integer, new_new_member_sacrament_goal integer, new_follow_up_lessons_actual integer, new_follow_up_lessons_goal integer, new_notes text) TO service_role;


--
-- Name: FUNCTION update_new_member_profile(target_new_member_id bigint, new_first_name text, new_last_name text, new_baptismal_date_extended date, new_baptism_date date, new_confirmation_date date, new_finding_source text, new_date_of_birth date, new_age_range text, new_gender text, new_marital_status text, new_child_dependents integer, new_living_situation text, new_native_language text, new_second_language text, new_mission_language_competency text, new_country_of_origin text, new_conversion_success_notes text); Type: ACL; Schema: public; Owner: postgres
--

REVOKE ALL ON FUNCTION public.update_new_member_profile(target_new_member_id bigint, new_first_name text, new_last_name text, new_baptismal_date_extended date, new_baptism_date date, new_confirmation_date date, new_finding_source text, new_date_of_birth date, new_age_range text, new_gender text, new_marital_status text, new_child_dependents integer, new_living_situation text, new_native_language text, new_second_language text, new_mission_language_competency text, new_country_of_origin text, new_conversion_success_notes text) FROM PUBLIC;
GRANT ALL ON FUNCTION public.update_new_member_profile(target_new_member_id bigint, new_first_name text, new_last_name text, new_baptismal_date_extended date, new_baptism_date date, new_confirmation_date date, new_finding_source text, new_date_of_birth date, new_age_range text, new_gender text, new_marital_status text, new_child_dependents integer, new_living_situation text, new_native_language text, new_second_language text, new_mission_language_competency text, new_country_of_origin text, new_conversion_success_notes text) TO authenticated;
GRANT ALL ON FUNCTION public.update_new_member_profile(target_new_member_id bigint, new_first_name text, new_last_name text, new_baptismal_date_extended date, new_baptism_date date, new_confirmation_date date, new_finding_source text, new_date_of_birth date, new_age_range text, new_gender text, new_marital_status text, new_child_dependents integer, new_living_situation text, new_native_language text, new_second_language text, new_mission_language_competency text, new_country_of_origin text, new_conversion_success_notes text) TO service_role;


--
-- Name: TABLE areas; Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON TABLE public.areas TO authenticated;
GRANT ALL ON TABLE public.areas TO service_role;


--
-- Name: TABLE districts; Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON TABLE public.districts TO authenticated;
GRANT ALL ON TABLE public.districts TO service_role;


--
-- Name: TABLE zones; Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON TABLE public.zones TO authenticated;
GRANT ALL ON TABLE public.zones TO service_role;


--
-- Name: TABLE archetype_area_profile; Type: ACL; Schema: dashboards; Owner: postgres
--

GRANT SELECT ON TABLE dashboards.archetype_area_profile TO gfm_dashboard_reader;


--
-- Name: TABLE roster_import_batches; Type: ACL; Schema: public; Owner: supabase_admin
--

GRANT ALL ON TABLE public.roster_import_batches TO postgres;
GRANT ALL ON TABLE public.roster_import_batches TO authenticated;
GRANT ALL ON TABLE public.roster_import_batches TO service_role;


--
-- Name: TABLE baptism_history_week; Type: ACL; Schema: dashboards; Owner: postgres
--

GRANT SELECT ON TABLE dashboards.baptism_history_week TO gfm_dashboard_reader;


--
-- Name: TABLE finding_area_week; Type: ACL; Schema: dashboards; Owner: postgres
--

GRANT SELECT ON TABLE dashboards.finding_area_week TO gfm_dashboard_reader;


--
-- Name: TABLE referral_archive_week; Type: ACL; Schema: dashboards; Owner: postgres
--

GRANT SELECT ON TABLE dashboards.referral_archive_week TO gfm_dashboard_reader;


--
-- Name: TABLE findechristus_referrals_week; Type: ACL; Schema: dashboards; Owner: postgres
--

GRANT SELECT ON TABLE dashboards.findechristus_referrals_week TO gfm_dashboard_reader;


--
-- Name: TABLE kpi_area_week; Type: ACL; Schema: dashboards; Owner: postgres
--

GRANT SELECT ON TABLE dashboards.kpi_area_week TO gfm_dashboard_reader;


--
-- Name: TABLE kpi_area_total_week; Type: ACL; Schema: dashboards; Owner: postgres
--

GRANT SELECT ON TABLE dashboards.kpi_area_total_week TO gfm_dashboard_reader;


--
-- Name: TABLE archetype_area_week; Type: ACL; Schema: dashboards; Owner: postgres
--

GRANT SELECT ON TABLE dashboards.archetype_area_week TO gfm_dashboard_reader;


--
-- Name: TABLE area_profile; Type: ACL; Schema: dashboards; Owner: postgres
--

GRANT SELECT ON TABLE dashboards.area_profile TO gfm_dashboard_reader;


--
-- Name: TABLE finding_cohort_week; Type: ACL; Schema: dashboards; Owner: postgres
--

GRANT SELECT ON TABLE dashboards.finding_cohort_week TO gfm_dashboard_reader;


--
-- Name: TABLE finding_rate_week; Type: ACL; Schema: dashboards; Owner: postgres
--

GRANT SELECT ON TABLE dashboards.finding_rate_week TO gfm_dashboard_reader;


--
-- Name: TABLE kpi_district_week; Type: ACL; Schema: dashboards; Owner: postgres
--

GRANT SELECT ON TABLE dashboards.kpi_district_week TO gfm_dashboard_reader;


--
-- Name: TABLE kpi_mission_week; Type: ACL; Schema: dashboards; Owner: postgres
--

GRANT SELECT ON TABLE dashboards.kpi_mission_week TO gfm_dashboard_reader;


--
-- Name: TABLE kpi_zone_week; Type: ACL; Schema: dashboards; Owner: postgres
--

GRANT SELECT ON TABLE dashboards.kpi_zone_week TO gfm_dashboard_reader;


--
-- Name: TABLE zone_history_week; Type: ACL; Schema: dashboards; Owner: postgres
--

GRANT SELECT ON TABLE dashboards.zone_history_week TO gfm_dashboard_reader;


--
-- Name: TABLE mission_history_week; Type: ACL; Schema: dashboards; Owner: postgres
--

GRANT SELECT ON TABLE dashboards.mission_history_week TO gfm_dashboard_reader;


--
-- Name: TABLE reporting_weeks; Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON TABLE public.reporting_weeks TO authenticated;
GRANT ALL ON TABLE public.reporting_weeks TO service_role;


--
-- Name: TABLE weekly_area_reports; Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON TABLE public.weekly_area_reports TO authenticated;
GRANT ALL ON TABLE public.weekly_area_reports TO service_role;


--
-- Name: TABLE weekly_baptismal_date_friends; Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON TABLE public.weekly_baptismal_date_friends TO authenticated;
GRANT ALL ON TABLE public.weekly_baptismal_date_friends TO service_role;


--
-- Name: TABLE weekly_high_potential_friends; Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON TABLE public.weekly_high_potential_friends TO authenticated;
GRANT ALL ON TABLE public.weekly_high_potential_friends TO service_role;


--
-- Name: TABLE people_area_week; Type: ACL; Schema: dashboards; Owner: postgres
--

GRANT SELECT ON TABLE dashboards.people_area_week TO gfm_dashboard_reader;


--
-- Name: TABLE people_district_week; Type: ACL; Schema: dashboards; Owner: postgres
--

GRANT SELECT ON TABLE dashboards.people_district_week TO gfm_dashboard_reader;


--
-- Name: TABLE people_mission_week; Type: ACL; Schema: dashboards; Owner: postgres
--

GRANT SELECT ON TABLE dashboards.people_mission_week TO gfm_dashboard_reader;


--
-- Name: TABLE people_zone_week; Type: ACL; Schema: dashboards; Owner: postgres
--

GRANT SELECT ON TABLE dashboards.people_zone_week TO gfm_dashboard_reader;


--
-- Name: TABLE presentation_access; Type: ACL; Schema: portal; Owner: postgres
--

GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE portal.presentation_access TO service_role;


--
-- Name: TABLE planning_question_sections; Type: ACL; Schema: public; Owner: postgres
--

GRANT SELECT ON TABLE public.planning_question_sections TO anon;
GRANT SELECT ON TABLE public.planning_question_sections TO authenticated;
GRANT ALL ON TABLE public.planning_question_sections TO service_role;


--
-- Name: TABLE planning_questions; Type: ACL; Schema: public; Owner: postgres
--

GRANT SELECT ON TABLE public.planning_questions TO anon;
GRANT SELECT ON TABLE public.planning_questions TO authenticated;
GRANT ALL ON TABLE public.planning_questions TO service_role;


--
-- Name: TABLE active_planning_questions; Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON TABLE public.active_planning_questions TO authenticated;
GRANT ALL ON TABLE public.active_planning_questions TO service_role;


--
-- Name: TABLE missions; Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON TABLE public.missions TO authenticated;
GRANT ALL ON TABLE public.missions TO service_role;


--
-- Name: TABLE area_reporting_status; Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON TABLE public.area_reporting_status TO authenticated;
GRANT ALL ON TABLE public.area_reporting_status TO service_role;


--
-- Name: TABLE area_units; Type: ACL; Schema: public; Owner: postgres
--

GRANT SELECT ON TABLE public.area_units TO authenticated;
GRANT ALL ON TABLE public.area_units TO service_role;


--
-- Name: SEQUENCE area_units_id_seq; Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON SEQUENCE public.area_units_id_seq TO service_role;


--
-- Name: SEQUENCE areas_id_seq; Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON SEQUENCE public.areas_id_seq TO authenticated;
GRANT ALL ON SEQUENCE public.areas_id_seq TO service_role;


--
-- Name: SEQUENCE baptismal_date_people_id_seq; Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON SEQUENCE public.baptismal_date_people_id_seq TO authenticated;
GRANT ALL ON SEQUENCE public.baptismal_date_people_id_seq TO service_role;


--
-- Name: TABLE baptismal_date_person_area_assignments; Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON TABLE public.baptismal_date_person_area_assignments TO authenticated;
GRANT ALL ON TABLE public.baptismal_date_person_area_assignments TO service_role;


--
-- Name: SEQUENCE baptismal_date_person_area_assignments_id_seq; Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON SEQUENCE public.baptismal_date_person_area_assignments_id_seq TO authenticated;
GRANT ALL ON SEQUENCE public.baptismal_date_person_area_assignments_id_seq TO service_role;


--
-- Name: TABLE call_in_area_updates; Type: ACL; Schema: public; Owner: postgres
--

GRANT SELECT,REFERENCES,TRIGGER ON TABLE public.call_in_area_updates TO authenticated;
GRANT ALL ON TABLE public.call_in_area_updates TO service_role;


--
-- Name: SEQUENCE call_in_area_updates_id_seq; Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON SEQUENCE public.call_in_area_updates_id_seq TO authenticated;
GRANT ALL ON SEQUENCE public.call_in_area_updates_id_seq TO service_role;


--
-- Name: TABLE call_in_districts; Type: ACL; Schema: public; Owner: postgres
--

GRANT SELECT,REFERENCES,TRIGGER ON TABLE public.call_in_districts TO authenticated;
GRANT ALL ON TABLE public.call_in_districts TO service_role;


--
-- Name: SEQUENCE call_in_districts_id_seq; Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON SEQUENCE public.call_in_districts_id_seq TO authenticated;
GRANT ALL ON SEQUENCE public.call_in_districts_id_seq TO service_role;


--
-- Name: TABLE units; Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON TABLE public.units TO authenticated;
GRANT ALL ON TABLE public.units TO service_role;


--
-- Name: TABLE weekly_planning_answers; Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON TABLE public.weekly_planning_answers TO authenticated;
GRANT ALL ON TABLE public.weekly_planning_answers TO service_role;


--
-- Name: TABLE weekly_area_reports_with_planning_metrics; Type: ACL; Schema: public; Owner: postgres
--

GRANT SELECT ON TABLE public.weekly_area_reports_with_planning_metrics TO authenticated;
GRANT SELECT ON TABLE public.weekly_area_reports_with_planning_metrics TO service_role;


--
-- Name: TABLE call_in_planning_details; Type: ACL; Schema: public; Owner: postgres
--

GRANT SELECT ON TABLE public.call_in_planning_details TO authenticated;
GRANT SELECT ON TABLE public.call_in_planning_details TO service_role;


--
-- Name: TABLE call_in_zones; Type: ACL; Schema: public; Owner: postgres
--

GRANT SELECT,REFERENCES,TRIGGER ON TABLE public.call_in_zones TO authenticated;
GRANT ALL ON TABLE public.call_in_zones TO service_role;


--
-- Name: SEQUENCE call_in_zones_id_seq; Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON SEQUENCE public.call_in_zones_id_seq TO authenticated;
GRANT ALL ON SEQUENCE public.call_in_zones_id_seq TO service_role;


--
-- Name: TABLE companionship_members; Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON TABLE public.companionship_members TO authenticated;
GRANT ALL ON TABLE public.companionship_members TO service_role;


--
-- Name: TABLE companionships; Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON TABLE public.companionships TO authenticated;
GRANT ALL ON TABLE public.companionships TO service_role;


--
-- Name: SEQUENCE companionships_id_seq; Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON SEQUENCE public.companionships_id_seq TO authenticated;
GRANT ALL ON SEQUENCE public.companionships_id_seq TO service_role;


--
-- Name: TABLE current_reporting_week; Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON TABLE public.current_reporting_week TO authenticated;
GRANT ALL ON TABLE public.current_reporting_week TO service_role;


--
-- Name: TABLE current_area_reporting_status; Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON TABLE public.current_area_reporting_status TO authenticated;
GRANT ALL ON TABLE public.current_area_reporting_status TO service_role;


--
-- Name: TABLE current_baptismal_date_people; Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON TABLE public.current_baptismal_date_people TO authenticated;
GRANT ALL ON TABLE public.current_baptismal_date_people TO service_role;


--
-- Name: TABLE leadership_assignments; Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON TABLE public.leadership_assignments TO authenticated;
GRANT ALL ON TABLE public.leadership_assignments TO service_role;


--
-- Name: TABLE current_leadership_assignments; Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON TABLE public.current_leadership_assignments TO authenticated;
GRANT ALL ON TABLE public.current_leadership_assignments TO service_role;


--
-- Name: TABLE missionaries; Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON TABLE public.missionaries TO authenticated;
GRANT ALL ON TABLE public.missionaries TO service_role;


--
-- Name: TABLE missionary_assignments; Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON TABLE public.missionary_assignments TO authenticated;
GRANT ALL ON TABLE public.missionary_assignments TO service_role;


--
-- Name: TABLE user_profiles; Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON TABLE public.user_profiles TO authenticated;
GRANT ALL ON TABLE public.user_profiles TO service_role;


--
-- Name: TABLE current_user_context; Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON TABLE public.current_user_context TO authenticated;
GRANT ALL ON TABLE public.current_user_context TO service_role;


--
-- Name: TABLE current_mission_areas; Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON TABLE public.current_mission_areas TO authenticated;
GRANT ALL ON TABLE public.current_mission_areas TO service_role;


--
-- Name: TABLE current_missionary_assignments; Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON TABLE public.current_missionary_assignments TO authenticated;
GRANT ALL ON TABLE public.current_missionary_assignments TO service_role;


--
-- Name: TABLE new_member_area_assignments; Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON TABLE public.new_member_area_assignments TO authenticated;
GRANT ALL ON TABLE public.new_member_area_assignments TO service_role;


--
-- Name: TABLE current_new_members; Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON TABLE public.current_new_members TO authenticated;
GRANT ALL ON TABLE public.current_new_members TO service_role;


--
-- Name: TABLE current_user_area_units; Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON TABLE public.current_user_area_units TO authenticated;
GRANT ALL ON TABLE public.current_user_area_units TO service_role;


--
-- Name: TABLE current_user_scope; Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON TABLE public.current_user_scope TO authenticated;
GRANT ALL ON TABLE public.current_user_scope TO service_role;


--
-- Name: TABLE current_weekly_reports; Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON TABLE public.current_weekly_reports TO authenticated;
GRANT ALL ON TABLE public.current_weekly_reports TO service_role;


--
-- Name: SEQUENCE districts_id_seq; Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON SEQUENCE public.districts_id_seq TO authenticated;
GRANT ALL ON SEQUENCE public.districts_id_seq TO service_role;


--
-- Name: TABLE gfm_schema_migrations; Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON TABLE public.gfm_schema_migrations TO service_role;


--
-- Name: SEQUENCE gfm_schema_migrations_id_seq; Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON SEQUENCE public.gfm_schema_migrations_id_seq TO service_role;


--
-- Name: TABLE historical_planning_details; Type: ACL; Schema: public; Owner: supabase_admin
--

GRANT ALL ON TABLE public.historical_planning_details TO postgres;
GRANT ALL ON TABLE public.historical_planning_details TO authenticated;
GRANT ALL ON TABLE public.historical_planning_details TO service_role;


--
-- Name: TABLE import_weekly_baptismal_date_friends; Type: ACL; Schema: public; Owner: supabase_admin
--

GRANT ALL ON TABLE public.import_weekly_baptismal_date_friends TO postgres;
GRANT ALL ON TABLE public.import_weekly_baptismal_date_friends TO service_role;


--
-- Name: TABLE import_weekly_high_potential_friends; Type: ACL; Schema: public; Owner: supabase_admin
--

GRANT ALL ON TABLE public.import_weekly_high_potential_friends TO postgres;
GRANT ALL ON TABLE public.import_weekly_high_potential_friends TO service_role;


--
-- Name: TABLE import_weekly_new_members; Type: ACL; Schema: public; Owner: supabase_admin
--

GRANT ALL ON TABLE public.import_weekly_new_members TO postgres;
GRANT ALL ON TABLE public.import_weekly_new_members TO service_role;


--
-- Name: TABLE import_weekly_planning_answers; Type: ACL; Schema: public; Owner: supabase_admin
--

GRANT ALL ON TABLE public.import_weekly_planning_answers TO postgres;
GRANT ALL ON TABLE public.import_weekly_planning_answers TO service_role;


--
-- Name: TABLE import_weekly_planning_area_map; Type: ACL; Schema: public; Owner: supabase_admin
--

GRANT ALL ON TABLE public.import_weekly_planning_area_map TO postgres;
GRANT ALL ON TABLE public.import_weekly_planning_area_map TO service_role;


--
-- Name: TABLE import_weekly_planning_reports; Type: ACL; Schema: public; Owner: supabase_admin
--

GRANT ALL ON TABLE public.import_weekly_planning_reports TO postgres;
GRANT ALL ON TABLE public.import_weekly_planning_reports TO service_role;


--
-- Name: SEQUENCE leadership_assignments_id_seq; Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON SEQUENCE public.leadership_assignments_id_seq TO authenticated;
GRANT ALL ON SEQUENCE public.leadership_assignments_id_seq TO service_role;


--
-- Name: SEQUENCE missionaries_id_seq; Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON SEQUENCE public.missionaries_id_seq TO authenticated;
GRANT ALL ON SEQUENCE public.missionaries_id_seq TO service_role;


--
-- Name: SEQUENCE missionary_assignments_id_seq; Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON SEQUENCE public.missionary_assignments_id_seq TO authenticated;
GRANT ALL ON SEQUENCE public.missionary_assignments_id_seq TO service_role;


--
-- Name: TABLE missionary_language_assignments; Type: ACL; Schema: public; Owner: supabase_admin
--

GRANT ALL ON TABLE public.missionary_language_assignments TO postgres;
GRANT ALL ON TABLE public.missionary_language_assignments TO authenticated;
GRANT ALL ON TABLE public.missionary_language_assignments TO service_role;


--
-- Name: SEQUENCE missions_id_seq; Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON SEQUENCE public.missions_id_seq TO authenticated;
GRANT ALL ON SEQUENCE public.missions_id_seq TO service_role;


--
-- Name: SEQUENCE new_member_area_assignments_id_seq; Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON SEQUENCE public.new_member_area_assignments_id_seq TO authenticated;
GRANT ALL ON SEQUENCE public.new_member_area_assignments_id_seq TO service_role;


--
-- Name: SEQUENCE new_members_id_seq; Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON SEQUENCE public.new_members_id_seq TO authenticated;
GRANT ALL ON SEQUENCE public.new_members_id_seq TO service_role;


--
-- Name: TABLE planning_catalog_version; Type: ACL; Schema: public; Owner: postgres
--

GRANT SELECT ON TABLE public.planning_catalog_version TO authenticated;
GRANT SELECT ON TABLE public.planning_catalog_version TO service_role;


--
-- Name: TABLE planning_question_grid_rows; Type: ACL; Schema: public; Owner: postgres
--

GRANT SELECT ON TABLE public.planning_question_grid_rows TO anon;
GRANT SELECT ON TABLE public.planning_question_grid_rows TO authenticated;
GRANT ALL ON TABLE public.planning_question_grid_rows TO service_role;


--
-- Name: SEQUENCE planning_question_grid_rows_id_seq; Type: ACL; Schema: public; Owner: postgres
--

GRANT SELECT ON SEQUENCE public.planning_question_grid_rows_id_seq TO authenticated;
GRANT ALL ON SEQUENCE public.planning_question_grid_rows_id_seq TO service_role;


--
-- Name: TABLE planning_question_options; Type: ACL; Schema: public; Owner: postgres
--

GRANT SELECT ON TABLE public.planning_question_options TO anon;
GRANT SELECT ON TABLE public.planning_question_options TO authenticated;
GRANT ALL ON TABLE public.planning_question_options TO service_role;


--
-- Name: SEQUENCE planning_question_options_id_seq; Type: ACL; Schema: public; Owner: postgres
--

GRANT SELECT ON SEQUENCE public.planning_question_options_id_seq TO authenticated;
GRANT ALL ON SEQUENCE public.planning_question_options_id_seq TO service_role;


--
-- Name: SEQUENCE planning_question_sections_id_seq; Type: ACL; Schema: public; Owner: postgres
--

GRANT SELECT ON SEQUENCE public.planning_question_sections_id_seq TO authenticated;
GRANT ALL ON SEQUENCE public.planning_question_sections_id_seq TO service_role;


--
-- Name: TABLE planning_question_visibility_rules; Type: ACL; Schema: public; Owner: postgres
--

GRANT SELECT ON TABLE public.planning_question_visibility_rules TO anon;
GRANT SELECT ON TABLE public.planning_question_visibility_rules TO authenticated;
GRANT ALL ON TABLE public.planning_question_visibility_rules TO service_role;


--
-- Name: SEQUENCE planning_question_visibility_rules_id_seq; Type: ACL; Schema: public; Owner: postgres
--

GRANT SELECT ON SEQUENCE public.planning_question_visibility_rules_id_seq TO authenticated;
GRANT ALL ON SEQUENCE public.planning_question_visibility_rules_id_seq TO service_role;


--
-- Name: SEQUENCE planning_questions_id_seq; Type: ACL; Schema: public; Owner: postgres
--

GRANT SELECT ON SEQUENCE public.planning_questions_id_seq TO authenticated;
GRANT ALL ON SEQUENCE public.planning_questions_id_seq TO service_role;


--
-- Name: SEQUENCE reporting_weeks_id_seq; Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON SEQUENCE public.reporting_weeks_id_seq TO authenticated;
GRANT ALL ON SEQUENCE public.reporting_weeks_id_seq TO service_role;


--
-- Name: TABLE roster_import_changes; Type: ACL; Schema: public; Owner: supabase_admin
--

GRANT ALL ON TABLE public.roster_import_changes TO postgres;
GRANT ALL ON TABLE public.roster_import_changes TO authenticated;
GRANT ALL ON TABLE public.roster_import_changes TO service_role;


--
-- Name: TABLE stakes; Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON TABLE public.stakes TO authenticated;
GRANT ALL ON TABLE public.stakes TO service_role;


--
-- Name: SEQUENCE stakes_id_seq; Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON SEQUENCE public.stakes_id_seq TO authenticated;
GRANT ALL ON SEQUENCE public.stakes_id_seq TO service_role;


--
-- Name: SEQUENCE units_id_seq; Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON SEQUENCE public.units_id_seq TO authenticated;
GRANT ALL ON SEQUENCE public.units_id_seq TO service_role;


--
-- Name: SEQUENCE weekly_area_reports_id_seq; Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON SEQUENCE public.weekly_area_reports_id_seq TO authenticated;
GRANT ALL ON SEQUENCE public.weekly_area_reports_id_seq TO service_role;


--
-- Name: SEQUENCE weekly_baptismal_date_friends_id_seq1; Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON SEQUENCE public.weekly_baptismal_date_friends_id_seq1 TO authenticated;
GRANT ALL ON SEQUENCE public.weekly_baptismal_date_friends_id_seq1 TO service_role;


--
-- Name: SEQUENCE weekly_high_potential_friends_id_seq; Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON SEQUENCE public.weekly_high_potential_friends_id_seq TO authenticated;
GRANT ALL ON SEQUENCE public.weekly_high_potential_friends_id_seq TO service_role;


--
-- Name: SEQUENCE weekly_new_members_id_seq; Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON SEQUENCE public.weekly_new_members_id_seq TO authenticated;
GRANT ALL ON SEQUENCE public.weekly_new_members_id_seq TO service_role;


--
-- Name: SEQUENCE weekly_planning_answers_id_seq; Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON SEQUENCE public.weekly_planning_answers_id_seq TO authenticated;
GRANT ALL ON SEQUENCE public.weekly_planning_answers_id_seq TO service_role;


--
-- Name: SEQUENCE zones_id_seq; Type: ACL; Schema: public; Owner: postgres
--

GRANT ALL ON SEQUENCE public.zones_id_seq TO authenticated;
GRANT ALL ON SEQUENCE public.zones_id_seq TO service_role;


--
-- Name: DEFAULT PRIVILEGES FOR SEQUENCES; Type: DEFAULT ACL; Schema: public; Owner: postgres
--

ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public GRANT ALL ON SEQUENCES  TO postgres;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public GRANT ALL ON SEQUENCES  TO authenticated;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public GRANT ALL ON SEQUENCES  TO service_role;


--
-- Name: DEFAULT PRIVILEGES FOR SEQUENCES; Type: DEFAULT ACL; Schema: public; Owner: supabase_admin
--

ALTER DEFAULT PRIVILEGES FOR ROLE supabase_admin IN SCHEMA public GRANT ALL ON SEQUENCES  TO postgres;
ALTER DEFAULT PRIVILEGES FOR ROLE supabase_admin IN SCHEMA public GRANT ALL ON SEQUENCES  TO authenticated;
ALTER DEFAULT PRIVILEGES FOR ROLE supabase_admin IN SCHEMA public GRANT ALL ON SEQUENCES  TO service_role;


--
-- Name: DEFAULT PRIVILEGES FOR FUNCTIONS; Type: DEFAULT ACL; Schema: public; Owner: postgres
--

ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public GRANT ALL ON FUNCTIONS  TO postgres;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public GRANT ALL ON FUNCTIONS  TO authenticated;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public GRANT ALL ON FUNCTIONS  TO service_role;


--
-- Name: DEFAULT PRIVILEGES FOR FUNCTIONS; Type: DEFAULT ACL; Schema: public; Owner: supabase_admin
--

ALTER DEFAULT PRIVILEGES FOR ROLE supabase_admin IN SCHEMA public GRANT ALL ON FUNCTIONS  TO postgres;
ALTER DEFAULT PRIVILEGES FOR ROLE supabase_admin IN SCHEMA public GRANT ALL ON FUNCTIONS  TO authenticated;
ALTER DEFAULT PRIVILEGES FOR ROLE supabase_admin IN SCHEMA public GRANT ALL ON FUNCTIONS  TO service_role;


--
-- Name: DEFAULT PRIVILEGES FOR TABLES; Type: DEFAULT ACL; Schema: public; Owner: postgres
--

ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public GRANT ALL ON TABLES  TO postgres;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public GRANT ALL ON TABLES  TO authenticated;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public GRANT ALL ON TABLES  TO service_role;


--
-- Name: DEFAULT PRIVILEGES FOR TABLES; Type: DEFAULT ACL; Schema: public; Owner: supabase_admin
--

ALTER DEFAULT PRIVILEGES FOR ROLE supabase_admin IN SCHEMA public GRANT ALL ON TABLES  TO postgres;
ALTER DEFAULT PRIVILEGES FOR ROLE supabase_admin IN SCHEMA public GRANT ALL ON TABLES  TO authenticated;
ALTER DEFAULT PRIVILEGES FOR ROLE supabase_admin IN SCHEMA public GRANT ALL ON TABLES  TO service_role;


--
-- PostgreSQL database dump complete
--



-- New objects must not be handed to anon by default either (the live system has no such default).
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public REVOKE ALL ON TABLES FROM anon;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public REVOKE ALL ON SEQUENCES FROM anon;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public REVOKE ALL ON FUNCTIONS FROM anon;
ALTER DEFAULT PRIVILEGES FOR ROLE supabase_admin IN SCHEMA public REVOKE ALL ON TABLES FROM anon;
ALTER DEFAULT PRIVILEGES FOR ROLE supabase_admin IN SCHEMA public REVOKE ALL ON SEQUENCES FROM anon;
ALTER DEFAULT PRIVILEGES FOR ROLE supabase_admin IN SCHEMA public REVOKE ALL ON FUNCTIONS FROM anon;

-- The rows a new system needs.
--
-- Data for Name: missions; Type: TABLE DATA; Schema: public; Owner: postgres
--

SET SESSION AUTHORIZATION DEFAULT;

ALTER TABLE public.missions DISABLE TRIGGER ALL;

INSERT INTO public.missions (id, name, created_at) VALUES (2, 'Germany Frankfurt Mission', '2026-08-10 20:09:19.892682+00');


ALTER TABLE public.missions ENABLE TRIGGER ALL;

--
-- Data for Name: archetype_settings; Type: TABLE DATA; Schema: public; Owner: postgres
--

ALTER TABLE public.archetype_settings DISABLE TRIGGER ALL;

INSERT INTO public.archetype_settings (mission_id, settings, version, updated_at, updated_by, updated_by_name) VALUES (2, '{"bands": [{"from": 120, "name": "Outstanding", "color": "#34b36a"}, {"from": 110, "name": "Strong", "color": "#a3e39a"}, {"from": 90, "name": "Average", "color": "#fff1c1"}, {"from": 80, "name": "Needs attention", "color": "#ffc49e"}, {"from": null, "name": "High priority", "color": "#ff9f9f"}], "weights": {"finding": {"friends_found": 45, "follow_up_lessons": 10, "lessons_with_friends": 20, "sacrament_attendance": 5, "first_time_first_week_sacrament": 20}, "bringing": {"first_time_sacrament": 30, "sacrament_attendance": 20, "first_time_first_week_sacrament": 50}, "teaching": {"baptismal_dates": 10, "follow_up_lessons": 35, "members_at_lessons": 25, "lessons_with_friends": 30}, "baptizing": {"baptismal_dates": 45, "baptisms_confirmations": 55}, "reactivating": {"members_at_lessons": 5, "member_meals_active": 5, "member_visits_active": 5, "member_meals_less_active": 25, "member_meals_part_member": 25, "member_visits_less_active": 15, "member_visits_part_member": 15, "new_member_lessons_per_member": 5}, "fellowshipping": {"new_member_sacrament_share": 55, "new_member_lessons_per_member": 45}}, "diagnoses": {"patterns": {"steady": {"steps": ["Thank the companions and ask what is going well.", "Ask how you can help them keep going."], "title": "Steady work", "meaning": "Nothing is far below what similar areas usually see."}, "stalled": {"steps": ["Start by listening: ask the companions how they are doing and how you can help.", "Plan together one simple goal for each day of the coming week.", "Invite a member or the ward mission leader to join a lesson or a finding activity."], "title": "A season to regroup", "meaning": "This week every part of the work is below what similar areas usually see. It often means the companions are tired, discouraged or facing something new, not that they are not trying."}, "balanced": {"steps": ["Thank the companions for their steady work.", "Choose together one part of the work to grow in this month."], "title": "An even balance", "meaning": "No single strength stands out: the work is even across all its parts."}, "finding_low": {"steps": ["Plan daily finding time and try one new way to find this week.", "Ask members whom they could invite to meet the missionaries."], "title": "Help with finding", "meaning": "Fewer new people are found than in similar areas. Finding is often easiest together with members."}, "bringing_low": {"steps": ["Invite every person you teach to sacrament meeting and offer to go with them.", "Ask members to sit with them and introduce them to others."], "title": "Help with coming to church", "meaning": "Fewer friends and new members at sacrament meeting than in similar areas."}, "teaching_low": {"steps": ["Set the next appointment at the end of every lesson.", "Invite a member to join lessons this week."], "title": "Help with teaching", "meaning": "Fewer lessons than in similar areas. People progress when they are taught regularly, with members."}, "baptizing_low": {"steps": ["Invite people to be baptized, with a specific date.", "Talk with the companions about what each person needs to keep their date."], "title": "Help with commitments", "meaning": "Fewer baptismal dates and baptisms than in similar areas. Clear invitations and loving follow-up help people move forward."}, "reactivating_low": {"steps": ["Ask the ward council which less-active members and part-member families to visit.", "Plan visits and meals together with members."], "title": "Help with less-active members", "meaning": "Fewer visits and meals with less-active members and part-member families than in similar areas."}, "fellowshipping_low": {"steps": ["Keep teaching each new member, with a member present.", "Counsel with the ward about a friend and a calling for each new member."], "title": "Help for new members", "meaning": "New members are less connected than in similar areas: fewer lessons or fewer at church."}, "finding_low_teaching_strong": {"steps": ["Thank them for their teaching, then plan daily finding time together.", "Ask everyone they teach and every member they visit whom they know who would like to hear the message."], "title": "Teaching well, few new people", "meaning": "The companions teach well, but few new people are coming in. Without new people to teach, strong teaching slows down within a few weeks."}, "finding_strong_bringing_low": {"steps": ["Invite each new person to sacrament meeting in the first or second lesson.", "Ask members to sit with them or bring them along.", "Remind them kindly on Saturday and offer to meet them at the door."], "title": "Finding many, few at church", "meaning": "Many new people are found, but few come to sacrament meeting. Coming to church early helps people feel the Spirit and meet members."}, "teaching_strong_baptizing_low": {"steps": ["Invite people to be baptized early, with a specific date.", "Help each person keep one commitment at a time, and follow up soon.", "Pray with the companions about each person''s next step."], "title": "Teaching well, few commitments", "meaning": "Lessons are going well, but few people set or keep a baptismal date. People may need a clear invitation and help to keep commitments."}, "baptizing_strong_fellowshipping_low": {"steps": ["Celebrate each baptism, then counsel with the ward council about every new member.", "Keep teaching new members, with a member present.", "Make sure each new member has ministering brothers or sisters."], "title": "New members need friends", "meaning": "People are being baptized, but new members are not yet well connected. The first months after baptism are when friends and teaching matter most."}}, "strengths": {"finding": "Creates and replenishes teaching opportunities.", "bringing": "Brings friends and new members to church consistently.", "teaching": "Strong, consistent teaching, and people are progressing.", "baptizing": "Turns teaching into commitments and ordinances.", "reactivating": "Helps less-active members come back and feel welcome.", "fellowshipping": "Strengthens and keeps new members close."}}, "peer_group": {"fallback": true, "attributes": ["urban_type", "assignment_type", "density"], "density_bins": [200, 500, 700, 1200], "minimum_size": 5}, "weeks_to_average": 1, "balance_threshold": 0.2}', 2, '2026-10-02 12:11:27.37373+00', NULL, 'Migration 038');


ALTER TABLE public.archetype_settings ENABLE TRIGGER ALL;

--
-- Data for Name: planning_catalog_version; Type: TABLE DATA; Schema: public; Owner: postgres
--

ALTER TABLE public.planning_catalog_version DISABLE TRIGGER ALL;

INSERT INTO public.planning_catalog_version (id, version, changed_at) VALUES (true, 40, '2026-10-03 12:43:40.238837+00');


ALTER TABLE public.planning_catalog_version ENABLE TRIGGER ALL;

--
-- Data for Name: planning_question_sections; Type: TABLE DATA; Schema: public; Owner: postgres
--

ALTER TABLE public.planning_question_sections DISABLE TRIGGER ALL;

INSERT INTO public.planning_question_sections (id, section_key, section_title, description, display_order, active, created_at, updated_at) VALUES (10, 'key_indicators_conversion', 'Key Indicators of Conversion', 'How the people you are teaching progressed this week, and your goals and plans for next week.', 10, true, '2026-09-27 10:50:29.846696+00', '2026-09-27 21:13:31.341766+00');
INSERT INTO public.planning_question_sections (id, section_key, section_title, description, display_order, active, created_at, updated_at) VALUES (12, 'member_work', 'Member Work', 'Time with members: meals, visits and asking for referrals.', 20, true, '2026-09-27 10:50:29.846696+00', '2026-10-03 12:43:36.03025+00');
INSERT INTO public.planning_question_sections (id, section_key, section_title, description, display_order, active, created_at, updated_at) VALUES (13, 'ward_coordination', 'Ward Coordination', 'Your GEMIKO (ward mission coordination) meeting: was it held, and who came?', 30, true, '2026-09-27 10:50:29.846696+00', '2026-10-03 12:43:38.51614+00');
INSERT INTO public.planning_question_sections (id, section_key, section_title, description, display_order, active, created_at, updated_at) VALUES (14, 'youth_service', 'Youth/Service', 'Youth activities, mini-missions and service in your ward or branch.', 40, true, '2026-09-27 10:50:29.846696+00', '2026-10-03 12:43:39.465425+00');
INSERT INTO public.planning_question_sections (id, section_key, section_title, description, display_order, active, created_at, updated_at) VALUES (15, 'weekly_plans', 'Weekly Plans', 'Your plan for the coming week, and anything your leaders should know.', 50, true, '2026-09-27 10:50:29.846696+00', '2026-10-03 12:43:40.238837+00');
INSERT INTO public.planning_question_sections (id, section_key, section_title, description, display_order, active, created_at, updated_at) VALUES (11, 'social_media', 'Social Media', 'Finding and teaching online this week.', 60, false, '2026-09-27 10:50:29.846696+00', '2026-10-03 12:43:40.238837+00');


ALTER TABLE public.planning_question_sections ENABLE TRIGGER ALL;

--
-- Data for Name: planning_questions; Type: TABLE DATA; Schema: public; Owner: postgres
--

ALTER TABLE public.planning_questions DISABLE TRIGGER ALL;

INSERT INTO public.planning_questions (id, section_id, question_key, question_label, help_text, question_type, required, display_order, active, created_at, updated_at, min_value, max_value, integer_only, placeholder, value_when_hidden, protected) VALUES (69, 12, 'member_referral_asks_actual', 'Out of all member Meals and Visits, how many times did you ask for a friend referral?', NULL, 'NUMBER', true, 90, true, '2026-08-20 18:52:12.624934+00', '2026-08-20 18:52:12.624934+00', NULL, NULL, true, NULL, NULL, false);
INSERT INTO public.planning_questions (id, section_id, question_key, question_label, help_text, question_type, required, display_order, active, created_at, updated_at, min_value, max_value, integer_only, placeholder, value_when_hidden, protected) VALUES (70, 12, 'less_active_sacrament_actual', 'Number of Less-Active Members you have been working with who attended Sacrament', NULL, 'NUMBER', true, 100, true, '2026-08-20 18:52:12.624934+00', '2026-08-20 18:52:12.624934+00', NULL, NULL, true, NULL, NULL, false);
INSERT INTO public.planning_questions (id, section_id, question_key, question_label, help_text, question_type, required, display_order, active, created_at, updated_at, min_value, max_value, integer_only, placeholder, value_when_hidden, protected) VALUES (73, 14, 'unit_weekly_youth_activities', 'Does your assigned unit hold regular weekly youth activities?', NULL, 'BOOLEAN', true, 10, true, '2026-08-20 18:52:12.624934+00', '2026-08-20 18:52:12.624934+00', NULL, NULL, true, NULL, NULL, false);
INSERT INTO public.planning_questions (id, section_id, question_key, question_label, help_text, question_type, required, display_order, active, created_at, updated_at, min_value, max_value, integer_only, placeholder, value_when_hidden, protected) VALUES (74, 14, 'youth_activities_actual', 'Youth Activities — Actual', NULL, 'NUMBER', true, 20, true, '2026-08-20 18:52:12.624934+00', '2026-08-20 18:52:12.624934+00', NULL, NULL, true, NULL, NULL, false);
INSERT INTO public.planning_questions (id, section_id, question_key, question_label, help_text, question_type, required, display_order, active, created_at, updated_at, min_value, max_value, integer_only, placeholder, value_when_hidden, protected) VALUES (75, 14, 'youth_activities_goal', 'Youth Activities — Goal for Next Week', NULL, 'NUMBER', true, 30, true, '2026-08-20 18:52:12.624934+00', '2026-08-20 18:52:12.624934+00', NULL, NULL, true, NULL, NULL, false);
INSERT INTO public.planning_questions (id, section_id, question_key, question_label, help_text, question_type, required, display_order, active, created_at, updated_at, min_value, max_value, integer_only, placeholder, value_when_hidden, protected) VALUES (76, 14, 'mini_mission_actual', 'Mini-Mission — Actual', NULL, 'NUMBER', true, 40, true, '2026-08-20 18:52:12.624934+00', '2026-08-20 18:52:12.624934+00', NULL, NULL, true, NULL, NULL, false);
INSERT INTO public.planning_questions (id, section_id, question_key, question_label, help_text, question_type, required, display_order, active, created_at, updated_at, min_value, max_value, integer_only, placeholder, value_when_hidden, protected) VALUES (77, 14, 'mini_mission_goal', 'Mini-Mission — Goal for Next Week', NULL, 'NUMBER', true, 50, true, '2026-08-20 18:52:12.624934+00', '2026-08-20 18:52:12.624934+00', NULL, NULL, true, NULL, NULL, false);
INSERT INTO public.planning_questions (id, section_id, question_key, question_label, help_text, question_type, required, display_order, active, created_at, updated_at, min_value, max_value, integer_only, placeholder, value_when_hidden, protected) VALUES (78, 14, 'service_hours_actual', 'Service Hours — Actual', NULL, 'NUMBER', true, 60, true, '2026-08-20 18:52:12.624934+00', '2026-08-20 18:52:12.624934+00', NULL, NULL, true, NULL, NULL, false);
INSERT INTO public.planning_questions (id, section_id, question_key, question_label, help_text, question_type, required, display_order, active, created_at, updated_at, min_value, max_value, integer_only, placeholder, value_when_hidden, protected) VALUES (79, 14, 'service_hours_goal', 'Service Hours — Goal for Next Week', NULL, 'NUMBER', true, 70, true, '2026-08-20 18:52:12.624934+00', '2026-08-20 18:52:12.624934+00', NULL, NULL, true, NULL, NULL, false);
INSERT INTO public.planning_questions (id, section_id, question_key, question_label, help_text, question_type, required, display_order, active, created_at, updated_at, min_value, max_value, integer_only, placeholder, value_when_hidden, protected) VALUES (38, 10, 'nm_sacrament_attendance_goal', 'NM Sacrament Attendance — Goal', NULL, 'NUMBER', true, 20, true, '2026-08-20 18:52:12.624934+00', '2026-09-27 10:50:29.846696+00', NULL, NULL, true, NULL, NULL, true);
INSERT INTO public.planning_questions (id, section_id, question_key, question_label, help_text, question_type, required, display_order, active, created_at, updated_at, min_value, max_value, integer_only, placeholder, value_when_hidden, protected) VALUES (40, 10, 'baptisms_confirmations_actual', 'Baptisms and Confirmations — Actual', NULL, 'NUMBER', true, 40, true, '2026-08-20 18:52:12.624934+00', '2026-09-27 10:50:29.846696+00', NULL, NULL, true, NULL, NULL, true);
INSERT INTO public.planning_questions (id, section_id, question_key, question_label, help_text, question_type, required, display_order, active, created_at, updated_at, min_value, max_value, integer_only, placeholder, value_when_hidden, protected) VALUES (41, 10, 'baptisms_confirmations_goal', 'Baptisms and Confirmations — Goal', NULL, 'NUMBER', true, 50, true, '2026-08-20 18:52:12.624934+00', '2026-09-27 10:50:29.846696+00', NULL, NULL, true, NULL, NULL, true);
INSERT INTO public.planning_questions (id, section_id, question_key, question_label, help_text, question_type, required, display_order, active, created_at, updated_at, min_value, max_value, integer_only, placeholder, value_when_hidden, protected) VALUES (44, 10, 'baptismal_dates_goal', 'Baptismal Dates — Goal', NULL, 'NUMBER', true, 80, true, '2026-08-20 18:52:12.624934+00', '2026-09-27 10:50:29.846696+00', NULL, NULL, true, NULL, NULL, true);
INSERT INTO public.planning_questions (id, section_id, question_key, question_label, help_text, question_type, required, display_order, active, created_at, updated_at, min_value, max_value, integer_only, placeholder, value_when_hidden, protected) VALUES (49, 10, 'sacrament_attendance_goal', 'Sacrament Attendance — Goal', NULL, 'NUMBER', true, 130, true, '2026-08-20 18:52:12.624934+00', '2026-09-27 10:50:29.846696+00', NULL, NULL, true, NULL, NULL, true);
INSERT INTO public.planning_questions (id, section_id, question_key, question_label, help_text, question_type, required, display_order, active, created_at, updated_at, min_value, max_value, integer_only, placeholder, value_when_hidden, protected) VALUES (37, 10, 'nm_sacrament_attendance', 'NM Sacrament Attendance — Actual', NULL, 'NUMBER', true, 10, true, '2026-08-20 18:52:12.624934+00', '2026-09-27 10:50:29.846696+00', NULL, NULL, true, NULL, NULL, true);
INSERT INTO public.planning_questions (id, section_id, question_key, question_label, help_text, question_type, required, display_order, active, created_at, updated_at, min_value, max_value, integer_only, placeholder, value_when_hidden, protected) VALUES (43, 10, 'baptismal_dates_actual', 'Baptismal Dates — Actual', NULL, 'NUMBER', true, 70, true, '2026-08-20 18:52:12.624934+00', '2026-09-27 10:50:29.846696+00', NULL, NULL, true, NULL, NULL, true);
INSERT INTO public.planning_questions (id, section_id, question_key, question_label, help_text, question_type, required, display_order, active, created_at, updated_at, min_value, max_value, integer_only, placeholder, value_when_hidden, protected) VALUES (59, 11, 'findechristus_interactions', 'Did you _____ FindeChristus this week?', NULL, 'GRID', true, 30, false, '2026-08-20 18:52:12.624934+00', '2026-10-02 07:31:40.997743+00', NULL, NULL, true, NULL, NULL, false);
INSERT INTO public.planning_questions (id, section_id, question_key, question_label, help_text, question_type, required, display_order, active, created_at, updated_at, min_value, max_value, integer_only, placeholder, value_when_hidden, protected) VALUES (60, 11, 'social_media_plan', 'Optional: Social Media Action Plan', 'What will you do, with whom, and when? Include how members can help.', 'LONG_TEXT', false, 40, false, '2026-08-20 18:52:12.624934+00', '2026-10-02 07:32:00.514265+00', NULL, NULL, true, NULL, NULL, false);
INSERT INTO public.planning_questions (id, section_id, question_key, question_label, help_text, question_type, required, display_order, active, created_at, updated_at, min_value, max_value, integer_only, placeholder, value_when_hidden, protected) VALUES (46, 10, 'sacrament_attendance_actual', 'Sacrament Attendance — Actual', NULL, 'NUMBER', true, 100, true, '2026-08-20 18:52:12.624934+00', '2026-09-27 10:50:29.846696+00', NULL, NULL, true, NULL, NULL, true);
INSERT INTO public.planning_questions (id, section_id, question_key, question_label, help_text, question_type, required, display_order, active, created_at, updated_at, min_value, max_value, integer_only, placeholder, value_when_hidden, protected) VALUES (52, 10, 'members_at_lessons_goal', 'Members at Lessons — Goal', NULL, 'NUMBER', true, 160, true, '2026-08-20 18:52:12.624934+00', '2026-09-27 10:50:29.846696+00', NULL, NULL, true, NULL, NULL, true);
INSERT INTO public.planning_questions (id, section_id, question_key, question_label, help_text, question_type, required, display_order, active, created_at, updated_at, min_value, max_value, integer_only, placeholder, value_when_hidden, protected) VALUES (61, 12, 'member_meals_active_actual', 'Member Meals — with active member — Actual', NULL, 'NUMBER', true, 10, true, '2026-08-20 18:52:12.624934+00', '2026-09-27 10:50:29.846696+00', NULL, NULL, true, NULL, NULL, true);
INSERT INTO public.planning_questions (id, section_id, question_key, question_label, help_text, question_type, required, display_order, active, created_at, updated_at, min_value, max_value, integer_only, placeholder, value_when_hidden, protected) VALUES (62, 12, 'member_meals_less_active_actual', 'Member Meals — with less-active member — Actual', NULL, 'NUMBER', true, 20, true, '2026-08-20 18:52:12.624934+00', '2026-09-27 10:50:29.846696+00', NULL, NULL, true, NULL, NULL, true);
INSERT INTO public.planning_questions (id, section_id, question_key, question_label, help_text, question_type, required, display_order, active, created_at, updated_at, min_value, max_value, integer_only, placeholder, value_when_hidden, protected) VALUES (63, 12, 'member_meals_part_member_actual', 'Member Meals — with part-member family — Actual', NULL, 'NUMBER', true, 30, true, '2026-08-20 18:52:12.624934+00', '2026-09-27 10:50:29.846696+00', NULL, NULL, true, NULL, NULL, true);
INSERT INTO public.planning_questions (id, section_id, question_key, question_label, help_text, question_type, required, display_order, active, created_at, updated_at, min_value, max_value, integer_only, placeholder, value_when_hidden, protected) VALUES (64, 12, 'member_meals_goal', 'Member Meals — Goal for Next Week', NULL, 'NUMBER', true, 40, true, '2026-08-20 18:52:12.624934+00', '2026-09-27 10:50:29.846696+00', NULL, NULL, true, NULL, NULL, true);
INSERT INTO public.planning_questions (id, section_id, question_key, question_label, help_text, question_type, required, display_order, active, created_at, updated_at, min_value, max_value, integer_only, placeholder, value_when_hidden, protected) VALUES (65, 12, 'member_visits_active_actual', 'Member Visits — with active member — Actual', NULL, 'NUMBER', true, 50, true, '2026-08-20 18:52:12.624934+00', '2026-09-27 10:50:29.846696+00', NULL, NULL, true, NULL, NULL, true);
INSERT INTO public.planning_questions (id, section_id, question_key, question_label, help_text, question_type, required, display_order, active, created_at, updated_at, min_value, max_value, integer_only, placeholder, value_when_hidden, protected) VALUES (66, 12, 'member_visits_less_active_actual', 'Member Visits — with less-active member — Actual', NULL, 'NUMBER', true, 60, true, '2026-08-20 18:52:12.624934+00', '2026-09-27 10:50:29.846696+00', NULL, NULL, true, NULL, NULL, true);
INSERT INTO public.planning_questions (id, section_id, question_key, question_label, help_text, question_type, required, display_order, active, created_at, updated_at, min_value, max_value, integer_only, placeholder, value_when_hidden, protected) VALUES (67, 12, 'member_visits_part_member_actual', 'Member Visits — with part-member family — Actual', NULL, 'NUMBER', true, 70, true, '2026-08-20 18:52:12.624934+00', '2026-09-27 10:50:29.846696+00', NULL, NULL, true, NULL, NULL, true);
INSERT INTO public.planning_questions (id, section_id, question_key, question_label, help_text, question_type, required, display_order, active, created_at, updated_at, min_value, max_value, integer_only, placeholder, value_when_hidden, protected) VALUES (68, 12, 'member_visits_goal', 'Member Visits — Goal for Next Week', NULL, 'NUMBER', true, 80, true, '2026-08-20 18:52:12.624934+00', '2026-09-27 10:50:29.846696+00', NULL, NULL, true, NULL, NULL, true);
INSERT INTO public.planning_questions (id, section_id, question_key, question_label, help_text, question_type, required, display_order, active, created_at, updated_at, min_value, max_value, integer_only, placeholder, value_when_hidden, protected) VALUES (71, 13, 'ward_coordination_held', 'Was Ward missionary Coordination meeting held this week?', NULL, 'BOOLEAN', true, 10, true, '2026-08-20 18:52:12.624934+00', '2026-09-27 10:50:29.846696+00', NULL, NULL, true, NULL, NULL, true);
INSERT INTO public.planning_questions (id, section_id, question_key, question_label, help_text, question_type, required, display_order, active, created_at, updated_at, min_value, max_value, integer_only, placeholder, value_when_hidden, protected) VALUES (80, 14, 'long_term_service', 'Are You In Long Term Service?', NULL, 'BOOLEAN', true, 80, true, '2026-08-20 18:52:12.624934+00', '2026-09-27 10:50:29.846696+00', NULL, NULL, true, NULL, NULL, true);
INSERT INTO public.planning_questions (id, section_id, question_key, question_label, help_text, question_type, required, display_order, active, created_at, updated_at, min_value, max_value, integer_only, placeholder, value_when_hidden, protected) VALUES (51, 10, 'members_at_lessons_actual', 'Members at Lessons — Actual', NULL, 'NUMBER', true, 150, true, '2026-08-20 18:52:12.624934+00', '2026-09-27 10:50:29.846696+00', NULL, NULL, true, NULL, NULL, true);
INSERT INTO public.planning_questions (id, section_id, question_key, question_label, help_text, question_type, required, display_order, active, created_at, updated_at, min_value, max_value, integer_only, placeholder, value_when_hidden, protected) VALUES (72, 13, 'ward_coordination_attendance', 'Who was there?', NULL, 'GRID', true, 20, true, '2026-08-20 18:52:12.624934+00', '2026-09-27 10:50:29.846696+00', NULL, NULL, true, NULL, NULL, true);
INSERT INTO public.planning_questions (id, section_id, question_key, question_label, help_text, question_type, required, display_order, active, created_at, updated_at, min_value, max_value, integer_only, placeholder, value_when_hidden, protected) VALUES (47, 10, 'sacrament_first_time', '1st Time', NULL, 'NUMBER', true, 110, true, '2026-08-20 18:52:12.624934+00', '2026-09-27 10:50:29.846696+00', NULL, NULL, true, NULL, '0', false);
INSERT INTO public.planning_questions (id, section_id, question_key, question_label, help_text, question_type, required, display_order, active, created_at, updated_at, min_value, max_value, integer_only, placeholder, value_when_hidden, protected) VALUES (48, 10, 'sacrament_first_time_first_week', '1st Time 1st Week', NULL, 'NUMBER', true, 120, true, '2026-08-20 18:52:12.624934+00', '2026-09-27 10:50:29.846696+00', NULL, NULL, true, NULL, '0', false);
INSERT INTO public.planning_questions (id, section_id, question_key, question_label, help_text, question_type, required, display_order, active, created_at, updated_at, min_value, max_value, integer_only, placeholder, value_when_hidden, protected) VALUES (54, 10, 'friends_found_actual', 'New People Being Taught — Actual', NULL, 'NUMBER', true, 180, true, '2026-08-20 18:52:12.624934+00', '2026-10-02 07:41:22.449997+00', NULL, NULL, false, NULL, NULL, true);
INSERT INTO public.planning_questions (id, section_id, question_key, question_label, help_text, question_type, required, display_order, active, created_at, updated_at, min_value, max_value, integer_only, placeholder, value_when_hidden, protected) VALUES (55, 10, 'friends_found_goal', 'New People Being Taught — Goal', NULL, 'NUMBER', true, 190, true, '2026-08-20 18:52:12.624934+00', '2026-09-27 21:13:31.341766+00', NULL, NULL, true, NULL, NULL, true);
INSERT INTO public.planning_questions (id, section_id, question_key, question_label, help_text, question_type, required, display_order, active, created_at, updated_at, min_value, max_value, integer_only, placeholder, value_when_hidden, protected) VALUES (50, 10, 'sacrament_attendance_plan', 'Sacrament Attendance — Action Plan', 'What will you do, with whom, and when? Include how members can help.', 'LONG_TEXT', true, 140, true, '2026-08-20 18:52:12.624934+00', '2026-09-27 21:13:31.341766+00', NULL, NULL, true, NULL, NULL, true);
INSERT INTO public.planning_questions (id, section_id, question_key, question_label, help_text, question_type, required, display_order, active, created_at, updated_at, min_value, max_value, integer_only, placeholder, value_when_hidden, protected) VALUES (39, 10, 'nm_sacrament_attendance_plan', 'Optional: NM Sacrament Attendance — Action Plan', 'What will you do, with whom, and when? Include how members can help.', 'LONG_TEXT', false, 30, true, '2026-08-20 18:52:12.624934+00', '2026-09-27 21:13:31.341766+00', NULL, NULL, true, NULL, NULL, true);
INSERT INTO public.planning_questions (id, section_id, question_key, question_label, help_text, question_type, required, display_order, active, created_at, updated_at, min_value, max_value, integer_only, placeholder, value_when_hidden, protected) VALUES (42, 10, 'baptisms_confirmations_plan', 'Optional: Baptisms and Confirmations — Action Plan', 'What will you do, with whom, and when? Include how members can help.', 'LONG_TEXT', false, 60, true, '2026-08-20 18:52:12.624934+00', '2026-09-27 21:13:31.341766+00', NULL, NULL, true, NULL, NULL, true);
INSERT INTO public.planning_questions (id, section_id, question_key, question_label, help_text, question_type, required, display_order, active, created_at, updated_at, min_value, max_value, integer_only, placeholder, value_when_hidden, protected) VALUES (45, 10, 'baptismal_dates_plan', 'Optional: Baptismal Dates — Action Plan', 'What will you do, with whom, and when? Include how members can help.', 'LONG_TEXT', false, 90, true, '2026-08-20 18:52:12.624934+00', '2026-09-27 21:13:31.341766+00', NULL, NULL, true, NULL, NULL, true);
INSERT INTO public.planning_questions (id, section_id, question_key, question_label, help_text, question_type, required, display_order, active, created_at, updated_at, min_value, max_value, integer_only, placeholder, value_when_hidden, protected) VALUES (82, 15, 'weekly_action_plan', 'Weekly Action Plan', 'What will you do, with whom, and when? Include how members can help.', 'LONG_TEXT', true, 20, true, '2026-08-20 18:52:12.624934+00', '2026-09-27 21:13:31.341766+00', NULL, NULL, true, NULL, NULL, true);
INSERT INTO public.planning_questions (id, section_id, question_key, question_label, help_text, question_type, required, display_order, active, created_at, updated_at, min_value, max_value, integer_only, placeholder, value_when_hidden, protected) VALUES (53, 10, 'members_at_lessons_plan', 'Members at Lessons — Action Plan', 'What will you do, with whom, and when? Include how members can help.', 'LONG_TEXT', true, 170, true, '2026-08-20 18:52:12.624934+00', '2026-09-27 21:13:31.341766+00', NULL, NULL, true, NULL, NULL, true);
INSERT INTO public.planning_questions (id, section_id, question_key, question_label, help_text, question_type, required, display_order, active, created_at, updated_at, min_value, max_value, integer_only, placeholder, value_when_hidden, protected) VALUES (56, 10, 'friends_found_plan', 'New People Being Taught — Action Plan', 'What will you do, with whom, and when? Include how members can help.', 'LONG_TEXT', true, 200, true, '2026-08-20 18:52:12.624934+00', '2026-09-27 21:13:31.341766+00', NULL, NULL, true, NULL, NULL, true);
INSERT INTO public.planning_questions (id, section_id, question_key, question_label, help_text, question_type, required, display_order, active, created_at, updated_at, min_value, max_value, integer_only, placeholder, value_when_hidden, protected) VALUES (81, 15, 'information_up_chain', 'Information for leaders (optional)', 'Anything your district leader should know or can help with.', 'LONG_TEXT', false, 10, true, '2026-08-20 18:52:12.624934+00', '2026-09-27 21:13:31.341766+00', NULL, NULL, true, NULL, NULL, true);
INSERT INTO public.planning_questions (id, section_id, question_key, question_label, help_text, question_type, required, display_order, active, created_at, updated_at, min_value, max_value, integer_only, placeholder, value_when_hidden, protected) VALUES (57, 11, 'facebook_finding_days', 'Days of Facebook Finding', NULL, 'NUMBER', true, 10, false, '2026-08-20 18:52:12.624934+00', '2026-10-02 12:11:27.37373+00', NULL, NULL, true, NULL, NULL, false);
INSERT INTO public.planning_questions (id, section_id, question_key, question_label, help_text, question_type, required, display_order, active, created_at, updated_at, min_value, max_value, integer_only, placeholder, value_when_hidden, protected) VALUES (58, 11, 'facebook_friends_found', 'Friends Found through Facebook', NULL, 'NUMBER', true, 20, false, '2026-08-20 18:52:12.624934+00', '2026-10-02 12:11:27.37373+00', NULL, NULL, true, NULL, NULL, false);


ALTER TABLE public.planning_questions ENABLE TRIGGER ALL;

--
-- Data for Name: planning_question_grid_rows; Type: TABLE DATA; Schema: public; Owner: postgres
--

ALTER TABLE public.planning_question_grid_rows DISABLE TRIGGER ALL;

INSERT INTO public.planning_question_grid_rows (id, question_id, row_key, row_label, display_order, active, created_at, updated_at) VALUES (32, 72, 'elders_quorum_representative', 'Elders Quorum Representative', 10, true, '2026-09-12 09:44:59.939594+00', '2026-09-27 10:50:29.846696+00');
INSERT INTO public.planning_question_grid_rows (id, question_id, row_key, row_label, display_order, active, created_at, updated_at) VALUES (33, 72, 'relief_society_representative', 'Relief Society Representative', 20, true, '2026-09-12 09:44:59.939594+00', '2026-09-27 10:50:29.846696+00');
INSERT INTO public.planning_question_grid_rows (id, question_id, row_key, row_label, display_order, active, created_at, updated_at) VALUES (34, 72, 'primary_presidency_representative', 'Primary Presidency Representative', 30, true, '2026-09-12 09:44:59.939594+00', '2026-09-27 10:50:29.846696+00');
INSERT INTO public.planning_question_grid_rows (id, question_id, row_key, row_label, display_order, active, created_at, updated_at) VALUES (35, 72, 'ward_missionaries', 'Ward missionaries', 40, true, '2026-09-12 09:44:59.939594+00', '2026-09-27 10:50:29.846696+00');
INSERT INTO public.planning_question_grid_rows (id, question_id, row_key, row_label, display_order, active, created_at, updated_at) VALUES (36, 72, 'priests_quorum_assistant', 'An assistant in the priests quorum, or the teachers/deacons quorum president when applicable', 50, true, '2026-09-12 09:44:59.939594+00', '2026-09-27 10:50:29.846696+00');
INSERT INTO public.planning_question_grid_rows (id, question_id, row_key, row_label, display_order, active, created_at, updated_at) VALUES (37, 72, 'oldest_young_women_presidency', 'A presidency member of the oldest Young Women class', 60, true, '2026-09-12 09:44:59.939594+00', '2026-09-27 10:50:29.846696+00');
INSERT INTO public.planning_question_grid_rows (id, question_id, row_key, row_label, display_order, active, created_at, updated_at) VALUES (38, 72, 'senior_service_missionaries', 'Full-time missionaries — Senior/Service', 70, true, '2026-09-12 09:44:59.939594+00', '2026-09-27 10:50:29.846696+00');
INSERT INTO public.planning_question_grid_rows (id, question_id, row_key, row_label, display_order, active, created_at, updated_at) VALUES (39, 72, 'gemiko_leader', 'Gemiko Leader', 80, true, '2026-09-12 09:44:59.939594+00', '2026-09-27 10:50:29.846696+00');
INSERT INTO public.planning_question_grid_rows (id, question_id, row_key, row_label, display_order, active, created_at, updated_at) VALUES (27, 59, 'like', 'Like', 10, false, '2026-09-12 09:44:59.939594+00', '2026-10-02 07:40:20.582636+00');
INSERT INTO public.planning_question_grid_rows (id, question_id, row_key, row_label, display_order, active, created_at, updated_at) VALUES (28, 59, 'comment_on', 'Comment on', 20, false, '2026-09-12 09:44:59.939594+00', '2026-10-02 07:40:22.302729+00');
INSERT INTO public.planning_question_grid_rows (id, question_id, row_key, row_label, display_order, active, created_at, updated_at) VALUES (29, 59, 'share_facebook', 'Share on Facebook', 30, false, '2026-09-12 09:44:59.939594+00', '2026-10-02 07:40:22.990947+00');
INSERT INTO public.planning_question_grid_rows (id, question_id, row_key, row_label, display_order, active, created_at, updated_at) VALUES (30, 59, 'share_members', 'Share with Members', 40, false, '2026-09-12 09:44:59.939594+00', '2026-10-02 07:40:23.501767+00');
INSERT INTO public.planning_question_grid_rows (id, question_id, row_key, row_label, display_order, active, created_at, updated_at) VALUES (31, 59, 'member_repost', 'Have a member re-post', 50, false, '2026-09-12 09:44:59.939594+00', '2026-10-02 07:40:24.578584+00');


ALTER TABLE public.planning_question_grid_rows ENABLE TRIGGER ALL;

--
-- Data for Name: planning_question_options; Type: TABLE DATA; Schema: public; Owner: postgres
--

ALTER TABLE public.planning_question_options DISABLE TRIGGER ALL;

INSERT INTO public.planning_question_options (id, question_id, option_value, option_label, display_order, active, created_at, updated_at) VALUES (12, 59, 'no', 'No', 20, true, '2026-09-12 09:43:23.897664+00', '2026-09-27 10:50:29.846696+00');
INSERT INTO public.planning_question_options (id, question_id, option_value, option_label, display_order, active, created_at, updated_at) VALUES (13, 72, 'yes', 'Yes', 10, true, '2026-09-12 09:43:23.897664+00', '2026-09-27 10:50:29.846696+00');
INSERT INTO public.planning_question_options (id, question_id, option_value, option_label, display_order, active, created_at, updated_at) VALUES (14, 72, 'no', 'No', 20, true, '2026-09-12 09:43:23.897664+00', '2026-09-27 10:50:29.846696+00');
INSERT INTO public.planning_question_options (id, question_id, option_value, option_label, display_order, active, created_at, updated_at) VALUES (15, 72, 'dont_have_one', 'Don''t Have One', 30, true, '2026-09-12 09:43:23.897664+00', '2026-09-27 10:50:29.846696+00');


ALTER TABLE public.planning_question_options ENABLE TRIGGER ALL;

--
-- Data for Name: planning_question_visibility_rules; Type: TABLE DATA; Schema: public; Owner: postgres
--

ALTER TABLE public.planning_question_visibility_rules DISABLE TRIGGER ALL;

INSERT INTO public.planning_question_visibility_rules (id, child_question_key, parent_question_key, operator, comparison_value, active, created_at, updated_at) VALUES (1, 'sacrament_first_time', 'sacrament_attendance_actual', 'greater_than', '0', true, '2026-08-22 09:55:23.25442+00', '2026-09-27 10:50:29.846696+00');
INSERT INTO public.planning_question_visibility_rules (id, child_question_key, parent_question_key, operator, comparison_value, active, created_at, updated_at) VALUES (2, 'sacrament_first_time_first_week', 'sacrament_attendance_actual', 'greater_than', '0', true, '2026-08-22 09:55:23.25442+00', '2026-09-27 10:50:29.846696+00');
INSERT INTO public.planning_question_visibility_rules (id, child_question_key, parent_question_key, operator, comparison_value, active, created_at, updated_at) VALUES (3, 'ward_coordination_attendance', 'ward_coordination_held', 'equals', 'true', true, '2026-08-22 09:55:23.25442+00', '2026-09-27 10:50:29.846696+00');
INSERT INTO public.planning_question_visibility_rules (id, child_question_key, parent_question_key, operator, comparison_value, active, created_at, updated_at) VALUES (4, 'sacrament_first_time_first_week', 'sacrament_first_time', 'greater_than', '0', true, '2026-09-27 10:50:29.846696+00', '2026-09-27 10:50:29.846696+00');


ALTER TABLE public.planning_question_visibility_rules ENABLE TRIGGER ALL;

--
-- Name: missions_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.missions_id_seq', 9, true);


--
-- Name: planning_question_grid_rows_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.planning_question_grid_rows_id_seq', 41, true);


--
-- Name: planning_question_options_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.planning_question_options_id_seq', 17, true);


--
-- Name: planning_question_sections_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.planning_question_sections_id_seq', 15, true);


--
-- Name: planning_question_visibility_rules_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.planning_question_visibility_rules_id_seq', 11, true);


--
-- Name: planning_questions_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.planning_questions_id_seq', 82, true);


--
-- PostgreSQL database dump complete
--



-- Identity counters continue after the rows above.
DO $$
DECLARE r record;
BEGIN
  FOR r IN SELECT * FROM (VALUES ('public.missions'), ('public.planning_question_sections'), ('public.planning_questions'),
        ('public.planning_question_options'), ('public.planning_question_grid_rows'),
        ('public.planning_question_visibility_rules')) AS t(name)
  LOOP
    IF pg_get_serial_sequence(r.name, 'id') IS NOT NULL THEN
      EXECUTE format('SELECT setval(%L, coalesce((SELECT max(id) FROM %s), 1))', pg_get_serial_sequence(r.name, 'id'), r.name);
    END IF;
  END LOOP;
END $$;

INSERT INTO public.gfm_schema_migrations (migration_name) VALUES ('000_baseline.sql (the state after migration 040)');
