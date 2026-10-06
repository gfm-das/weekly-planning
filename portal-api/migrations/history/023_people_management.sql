-- Weekly Planning people: transfer with a ward or branch, edit details, delete a person added by mistake,
-- last week's baptismal dates carried over, and tighter rights on the people functions. Run on Beta only.
--
-- Why:
-- * transfer_new_member(person, area) never set a ward or branch (unit). start_current_weekly_report only adds
--   New Members whose new_members.unit_id is the plan's unit, so a transferred New Member never showed up on the
--   new area's plan (in Beta too). reactivate_new_member had the same gap.
-- * The portal's Weekly Planning now lets the companionship manage the people on its plan: edit details,
--   transfer (area + ward or branch), end follow-up / drop, "Baptized", and delete someone added by mistake.
--   Editing a friend with a baptismal date and deleting had no database function yet.
-- * The two baptismal dates of a friend started blank every week.
-- * Every people function could be run by anon (the public API key), and archive_expired_new_members() (no access
--   check at all; it ends follow-up for every New Member baptized a year ago, mission-wide) by anyone signed in.
--
-- What changes (nothing else is touched; tables, policies and data stay as they are):
-- 1. New transfer_new_member(person, area, unit): moves the New Member to the area AND ward or branch (the new
--    assignment, new_members.area_id/unit_id/stake_id). The same area with another ward or branch is allowed.
--    The old transfer_new_member(person, area) (used by Beta) now keeps the person's ward or branch when the new
--    area reports for it, otherwise it uses the new area's main one, and then does the same.
-- 2. New reactivate_new_member(person, unit); the old reactivate_new_member(person) keeps the ward or branch when
--    the area still reports for it, otherwise it uses the area's main one. (Nothing calls either today.)
-- 3. New update_new_member_profile(...) and update_baptismal_date_person(...): the "Edit details" dialogs. Same
--    access rule as the other people functions (can_access_area of the person's current area), with checks on
--    names, lengths, dates and child dependants. Editing a friend's finding source also updates the copy on the
--    friend's rows in draft plans (Call-ins read that copy).
-- 4. New delete_new_member_added_by_mistake(person) and delete_baptismal_date_person_added_by_mistake(person):
--    a real delete, only for a current person who is only on this week's drafts: never on a submitted or locked
--    plan, never on a plan of an earlier week (whatever its status: a leader's "Unlock" makes a submitted plan a
--    draft again and clears its submitted time, and an earlier week's plan cannot be submitted again), and on no
--    other area's draft. Otherwise they stop with SQLSTATE GF409 and a message to use End follow-up / Drop.
--    Deleting a New Member who came from "Baptized" puts the friend back on the baptismal date list where they
--    were (the returned id), so a mistaken "Baptized" can be undone.
-- 5. start_current_weekly_report(unit) (called by the portal and Beta when a plan opens): unchanged, plus a
--    friend's empty "date set" / "current baptismal date" on this week's draft are filled from their latest
--    earlier weekly row.
-- 6. Rights: every people function runs as postgres with search_path = public, pg_temp; PUBLIC and anon cannot
--    run any of them; signed-in users (authenticated) and service_role can run the others, except the ones no page
--    (the portal or Beta) uses: archive_expired_new_members() (no access check; mission-wide) and
--    reactivate_new_member (both), which only service_role (and postgres) can run. Grant authenticated again when a
--    page needs one (e.g. a "Re-activate" button). get_previous_weekly_new_members(unit) is unused too, but keeps
--    authenticated: 019, which is run again after every migration as a check, grants it to authenticated by name
--    (it only returns last week's New Member rows of the caller's own area and ward or branch).
--
-- Review fixes (27 Sep, after the first version of this file went live at 12:50): Delete now also keeps anyone on
-- an earlier week's plan (item 4; an unlocked earlier plan made them look "never submitted"), and signed-in users
-- lost EXECUTE on the two unused reactivate_new_member functions (item 6). Running this file again on a Beta that
-- has the first version applies just these changes (everything else in it is the same). To undo only them, run
-- the first version again the same way:  git show aa8d609:portal-api/migrations/023_people_management.sql
--
-- Apply (back up Beta first; after 019. Runs as supabase_admin like the other migrations of this round; every
-- object is created as postgres, the owner of the existing functions). Join the lines with plain line feeds so
-- Windows line ends do not end up inside the functions:
--   (Get-Content portal-api/migrations/023_people_management.sql) -join "`n" |
--     docker exec -i gfm-beta-supabase-db-1 psql -U supabase_admin -d postgres -v ON_ERROR_STOP=1
--   (Git Bash: sed 's/\r$//' portal-api/migrations/023_people_management.sql | docker exec -i ...)
-- Then run 019 again as a check (it must end with COMMIT):
--   Get-Content portal-api/migrations/019_restrict_public_functions.sql -Raw |
--     docker exec -i gfm-beta-supabase-db-1 psql -U supabase_admin -d postgres -v ON_ERROR_STOP=1
-- If a plan is being opened at that moment the file waits at most 10 seconds for it (lock timeout), then stops;
-- run it again.
-- Safe to run again: only CREATE OR REPLACE, ALTER FUNCTION, REVOKE and GRANT, then a check that stops on any
-- problem.
-- Rollback: 023_people_management_rollback.sql (same way of running; see its header). People deleted with
-- function 4 stay deleted; units set by transfers and edited details stay as they are.
BEGIN;
SET LOCAL lock_timeout = '10s';

DO $$
BEGIN
  IF session_user NOT IN ('supabase_admin', 'postgres') THEN
    RAISE EXCEPTION 'Run this file as supabase_admin (see its header), not as %.', session_user;
  END IF;
END $$;

-- The existing people functions belong to postgres; the new ones must too (they run with their owner's rights).
SET LOCAL ROLE postgres;

-- 1. Transfer a New Member to an area and ward or branch.
CREATE OR REPLACE FUNCTION public.transfer_new_member(target_new_member_id bigint, target_area_id bigint, target_unit_id bigint)
 RETURNS void
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path = public, pg_temp
AS $function$
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
$function$;

-- Beta chooses only an area: keep the person's ward or branch when the new area reports for it, otherwise use the
-- new area's main ward or branch, so the person shows up on that area's plan.
CREATE OR REPLACE FUNCTION public.transfer_new_member(target_new_member_id bigint, target_area_id bigint)
 RETURNS void
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path = public, pg_temp
AS $function$
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
$function$;

-- 2. Restore follow-up with a ward or branch.
CREATE OR REPLACE FUNCTION public.reactivate_new_member(target_new_member_id bigint, target_unit_id bigint)
 RETURNS void
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path = public, pg_temp
AS $function$
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
$function$;

CREATE OR REPLACE FUNCTION public.reactivate_new_member(target_new_member_id bigint)
 RETURNS void
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path = public, pg_temp
AS $function$
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
$function$;

-- 3. Edit details. Every argument is required (null clears a value, except the first name). The portal checks the
-- choice lists and its "required" rules; this checks what must never be stored.
CREATE OR REPLACE FUNCTION public.update_new_member_profile(
    target_new_member_id bigint, new_first_name text, new_last_name text,
    new_baptismal_date_extended date, new_baptism_date date, new_confirmation_date date,
    new_finding_source text, new_date_of_birth date, new_age_range text, new_gender text,
    new_marital_status text, new_child_dependents integer, new_living_situation text,
    new_native_language text, new_second_language text, new_mission_language_competency text,
    new_country_of_origin text, new_conversion_success_notes text)
 RETURNS public.new_members
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path = public, pg_temp
AS $function$
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
$function$;

CREATE OR REPLACE FUNCTION public.update_baptismal_date_person(
    target_baptismal_date_person_id bigint, new_first_name text, new_last_name text, new_finding_source text)
 RETURNS public.baptismal_date_people
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path = public, pg_temp
AS $function$
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
$function$;

-- 4. Delete someone added by mistake. SQLSTATE GF409 = "keep the record, use End follow-up / Drop instead".
-- The messages carry no names (the database log may keep them); the portal adds the name.
-- "Kept for the reports" = on a plan that is not a draft, or on any plan of an earlier week. An earlier week counts
-- whatever its status: unsubmit_weekly_report (a leader's "Unlock") sets a submitted plan back to DRAFT and clears
-- submitted_at, so the status alone forgets that it was submitted, and an earlier week's plan cannot be submitted
-- again. planning._report_people (on_submitted_plan) uses the same rule to decide whether the page offers Delete.
CREATE OR REPLACE FUNCTION public.delete_new_member_added_by_mistake(target_new_member_id bigint)
 RETURNS bigint
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path = public, pg_temp
AS $function$
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
$function$;

CREATE OR REPLACE FUNCTION public.delete_baptismal_date_person_added_by_mistake(target_baptismal_date_person_id bigint)
 RETURNS void
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path = public, pg_temp
AS $function$
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
$function$;

-- 5. Same as before (pre-023 text), plus the carry-over of the two baptismal dates at the end.
CREATE OR REPLACE FUNCTION public.start_current_weekly_report(target_unit_id bigint)
 RETURNS bigint
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path = public, pg_temp
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
        -- A friend's "date set" and "current baptismal date" do not change every week: fill this week's empty
        -- ones from the friend's latest earlier weekly row (any area, so a transfer keeps them). Rows that already
        -- have them, or whose earlier rows have none, are not touched.
        WITH previous AS (
            SELECT DISTINCT ON (w.id) w.id, p.baptismal_date_set_on, p.current_baptismal_date
            FROM public.weekly_baptismal_date_friends w
            JOIN public.weekly_baptismal_date_friends p
              ON p.baptismal_date_person_id = w.baptismal_date_person_id AND p.id <> w.id
            JOIN public.weekly_area_reports pr ON pr.id = p.weekly_area_report_id
            JOIN public.reporting_weeks prw ON prw.id = pr.reporting_week_id
            WHERE w.weekly_area_report_id = v_report_id
              AND prw.sunday < public.current_reporting_sunday()
              AND ((w.baptismal_date_set_on IS NULL AND p.baptismal_date_set_on IS NOT NULL)
                   OR (w.current_baptismal_date IS NULL AND p.current_baptismal_date IS NOT NULL))
            ORDER BY w.id, prw.sunday DESC, p.updated_at DESC NULLS LAST, p.id DESC
        )
        UPDATE public.weekly_baptismal_date_friends w
        SET baptismal_date_set_on = coalesce(w.baptismal_date_set_on, previous.baptismal_date_set_on),
            current_baptismal_date = coalesce(w.current_baptismal_date, previous.current_baptismal_date)
        FROM previous
        WHERE w.id = previous.id;
    END IF;
    RETURN v_report_id;
END;
$function$;

-- 6. Rights. New and replaced functions: signed-in users (the portal and Beta call them as the user) and
-- service_role; never PUBLIC or anon (Supabase's default privileges grant anon on new functions).
REVOKE ALL ON FUNCTION
  public.transfer_new_member(bigint, bigint, bigint),
  public.transfer_new_member(bigint, bigint),
  public.update_new_member_profile(bigint, text, text, date, date, date, text, date, text, text, text, integer, text, text, text, text, text, text),
  public.update_baptismal_date_person(bigint, text, text, text),
  public.delete_new_member_added_by_mistake(bigint),
  public.delete_baptismal_date_person_added_by_mistake(bigint),
  public.start_current_weekly_report(bigint)
FROM PUBLIC, anon;
GRANT EXECUTE ON FUNCTION
  public.transfer_new_member(bigint, bigint, bigint),
  public.transfer_new_member(bigint, bigint),
  public.update_new_member_profile(bigint, text, text, date, date, date, text, date, text, text, text, integer, text, text, text, text, text, text),
  public.update_baptismal_date_person(bigint, text, text, text),
  public.delete_new_member_added_by_mistake(bigint),
  public.delete_baptismal_date_person_added_by_mistake(bigint),
  public.start_current_weekly_report(bigint)
TO authenticated, service_role;

-- The other people functions are not rewritten, only given the same search_path and rights. anon never had a
-- use for them: without a signed-in user they stop at their own checks.
ALTER FUNCTION public.create_new_member(text, text, bigint, bigint, date, date, date, text, date, text, text, text, integer, text, text, text, text, text, text) SET search_path = public, pg_temp;
ALTER FUNCTION public.create_baptismal_date_person(text, text, text, bigint) SET search_path = public, pg_temp;
ALTER FUNCTION public.archive_new_member(bigint, text) SET search_path = public, pg_temp;
ALTER FUNCTION public.archive_baptismal_date_person(bigint, text) SET search_path = public, pg_temp;
ALTER FUNCTION public.transfer_baptismal_date_person(bigint, bigint, bigint) SET search_path = public, pg_temp;
ALTER FUNCTION public.convert_baptismal_date_person_to_new_member(bigint, date, date, date, date, text, text, text, integer, text, text, text, text, text, text) SET search_path = public, pg_temp;
ALTER FUNCTION public.get_previous_weekly_new_members(bigint) SET search_path = public, pg_temp;
ALTER FUNCTION public.archive_expired_new_members() SET search_path = public, pg_temp;
REVOKE ALL ON FUNCTION
  public.create_new_member(text, text, bigint, bigint, date, date, date, text, date, text, text, text, integer, text, text, text, text, text, text),
  public.create_baptismal_date_person(text, text, text, bigint),
  public.archive_new_member(bigint, text),
  public.archive_baptismal_date_person(bigint, text),
  public.transfer_baptismal_date_person(bigint, bigint, bigint),
  public.convert_baptismal_date_person_to_new_member(bigint, date, date, date, date, text, text, text, integer, text, text, text, text, text, text),
  public.get_previous_weekly_new_members(bigint)
FROM PUBLIC, anon;
GRANT EXECUTE ON FUNCTION
  public.create_new_member(text, text, bigint, bigint, date, date, date, text, date, text, text, text, integer, text, text, text, text, text, text),
  public.create_baptismal_date_person(text, text, text, bigint),
  public.archive_new_member(bigint, text),
  public.archive_baptismal_date_person(bigint, text),
  public.transfer_baptismal_date_person(bigint, bigint, bigint),
  public.convert_baptismal_date_person_to_new_member(bigint, date, date, date, date, text, text, text, integer, text, text, text, text, text, text),
  public.get_previous_weekly_new_members(bigint)
TO authenticated, service_role;
-- No page (the portal or Beta) calls these three: only service_role (and postgres). archive_expired_new_members()
-- has no access check and works mission-wide; the other two check access, but nothing needs them as the user.
-- reactivate_new_member(person) still works for service_role: it runs as postgres and calls the other one itself.
REVOKE ALL ON FUNCTION
  public.reactivate_new_member(bigint, bigint),
  public.reactivate_new_member(bigint),
  public.archive_expired_new_members()
FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION
  public.reactivate_new_member(bigint, bigint),
  public.reactivate_new_member(bigint),
  public.archive_expired_new_members()
TO service_role;

-- Check: every people function runs as postgres with the fixed search_path; PUBLIC and anon cannot run any of them;
-- service_role can run all; signed-in users can run all except the three above.
DO $$
DECLARE
  found text;
BEGIN
  SELECT string_agg(p.oid::regprocedure::text, ', ') INTO found
  FROM pg_proc p
  WHERE p.oid IN (
      'public.transfer_new_member(bigint,bigint,bigint)'::regprocedure,
      'public.transfer_new_member(bigint,bigint)'::regprocedure,
      'public.reactivate_new_member(bigint,bigint)'::regprocedure,
      'public.reactivate_new_member(bigint)'::regprocedure,
      'public.update_new_member_profile(bigint,text,text,date,date,date,text,date,text,text,text,integer,text,text,text,text,text,text)'::regprocedure,
      'public.update_baptismal_date_person(bigint,text,text,text)'::regprocedure,
      'public.delete_new_member_added_by_mistake(bigint)'::regprocedure,
      'public.delete_baptismal_date_person_added_by_mistake(bigint)'::regprocedure,
      'public.start_current_weekly_report(bigint)'::regprocedure,
      'public.create_new_member(text,text,bigint,bigint,date,date,date,text,date,text,text,text,integer,text,text,text,text,text,text)'::regprocedure,
      'public.create_baptismal_date_person(text,text,text,bigint)'::regprocedure,
      'public.archive_new_member(bigint,text)'::regprocedure,
      'public.archive_baptismal_date_person(bigint,text)'::regprocedure,
      'public.transfer_baptismal_date_person(bigint,bigint,bigint)'::regprocedure,
      'public.convert_baptismal_date_person_to_new_member(bigint,date,date,date,date,text,text,text,integer,text,text,text,text,text,text)'::regprocedure,
      'public.get_previous_weekly_new_members(bigint)'::regprocedure,
      'public.archive_expired_new_members()'::regprocedure)
    AND (NOT p.prosecdef OR pg_get_userbyid(p.proowner) <> 'postgres'
         OR NOT coalesce(p.proconfig, '{}') @> ARRAY['search_path=public, pg_temp']
         OR has_function_privilege('public', p.oid, 'EXECUTE') OR has_function_privilege('anon', p.oid, 'EXECUTE')
         OR NOT has_function_privilege('service_role', p.oid, 'EXECUTE')
         OR has_function_privilege('authenticated', p.oid, 'EXECUTE')
            <> (p.proname NOT IN ('archive_expired_new_members', 'reactivate_new_member')));
  IF found IS NOT NULL THEN
    RAISE EXCEPTION 'Unexpected owner, search_path or EXECUTE rights on: %', found;
  END IF;
  IF (SELECT count(*) FROM pg_proc WHERE pronamespace = 'public'::regnamespace AND proname = 'transfer_new_member') <> 2
     OR (SELECT count(*) FROM pg_proc WHERE pronamespace = 'public'::regnamespace AND proname = 'reactivate_new_member') <> 2 THEN
    RAISE EXCEPTION 'Expected exactly two transfer_new_member and two reactivate_new_member functions.';
  END IF;
END $$;

NOTIFY pgrst, 'reload schema';
COMMIT;

-- Verify (read-only, after applying):
-- 1. Run 019 again as supabase_admin (see Apply); it must end with COMMIT.
-- 2. The self-check above passed if the file ended with COMMIT. To look again:
--      docker exec gfm-beta-supabase-db-1 psql -U postgres -d postgres -c "SELECT p.oid::regprocedure, p.proconfig, has_function_privilege('anon', p.oid, 'EXECUTE') AS anon, has_function_privilege('authenticated', p.oid, 'EXECUTE') AS signed_in FROM pg_proc p WHERE p.pronamespace = 'public'::regnamespace AND p.proname ~ '(new_member|baptismal_date_person|start_current_weekly_report)' ORDER BY 1"
-- 3. Open Weekly Planning as a missionary with a friend on date: the two dates are filled from last week.
