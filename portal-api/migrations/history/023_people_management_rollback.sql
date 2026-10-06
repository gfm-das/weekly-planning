-- Rollback of 023_people_management.sql: puts the people functions back exactly as they were on Beta before 023
-- (27 Sep 2026). Run on Beta only, the same way as 023 (as supabase_admin; objects stay owned by postgres), with
-- plain line feeds:
--   (Get-Content portal-api/migrations/023_people_management_rollback.sql) -join "`n" |
--     docker exec -i gfm-beta-supabase-db-1 psql -U supabase_admin -d postgres -v ON_ERROR_STOP=1
--   (Git Bash: sed 's/\r$//' portal-api/migrations/023_people_management_rollback.sql | docker exec -i ...)
--
-- What it does:
-- 1. transfer_new_member(person, area), reactivate_new_member(person) and start_current_weekly_report(unit) get
--    their pre-023 text back (pg_get_functiondef output from Beta before 023).
-- 2. The functions 023 added are dropped: transfer_new_member(person, area, unit), reactivate_new_member(person,
--    unit), update_new_member_profile, update_baptismal_date_person, delete_new_member_added_by_mistake and
--    delete_baptismal_date_person_added_by_mistake. The portal's Weekly Planning then refuses Transfer, Edit
--    details and Delete with an error; roll back portal-api and planning.html first (see
--    docs/handoff/round2/people.md).
-- 3. The other people functions get search_path = public again, and anon gets EXECUTE back; so does
--    authenticated on archive_expired_new_members() and reactivate_new_member(person).
-- To undo only the review fixes of 27 Sep and keep the rest of 023, do not run this file: run the first version of
-- 023 again instead (see the header of 023).
-- Data is not touched: units set by transfers, edited details and filled-in baptismal dates stay; people deleted
-- through the new delete functions stay deleted (restore them from the pre-023 backup if ever needed).
-- It stops unless the 11 pre-existing people functions end up with their pre-023 definitions: it checks their
-- fingerprint (96e863e7dda9b89d4b0a33eb53057518 on Beta before 023, line feeds only), then the rights.
-- Safe to run again.
BEGIN;
SET LOCAL lock_timeout = '10s';

DO $$
BEGIN
  IF session_user NOT IN ('supabase_admin', 'postgres') THEN
    RAISE EXCEPTION 'Run this file as supabase_admin (see its header), not as %.', session_user;
  END IF;
END $$;

SET LOCAL ROLE postgres;

-- 1. Pre-023 definitions.
CREATE OR REPLACE FUNCTION public.reactivate_new_member(target_new_member_id bigint)
 RETURNS void
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public'
AS $function$
declare
    v_area_id bigint;
    v_baptism_date date;
begin

    select
        nm.area_id,
        nm.baptism_date
    into
        v_area_id,
        v_baptism_date
    from public.new_members nm
    where nm.id = target_new_member_id;


    if v_area_id is null then
        raise exception 'New Member record not found.';
    end if;


    if not public.can_access_area(v_area_id) then
        raise exception
            'You do not have permission to restore follow-up for this New Member.';
    end if;


    if v_baptism_date is not null
       and v_baptism_date <= current_date - interval '1 year' then
        raise exception
            'This person has been a member for one year or longer.';
    end if;


    update public.new_members
    set
        follow_up_status = 'current',
        follow_up_ended_at = null,
        follow_up_end_reason = null,

        -- Legacy compatibility.
        active = true,
        inactive_at = null,
        inactive_reason = null,

        updated_at = now()
    where id = target_new_member_id;


    if not exists (
        select 1
        from public.new_member_area_assignments
        where new_member_id = target_new_member_id
          and end_date is null
    ) then

        insert into public.new_member_area_assignments (
            new_member_id,
            area_id,
            start_date,
            transfer_reason
        )
        values (
            target_new_member_id,
            v_area_id,
            current_date,
            'follow_up_restored'
        );

    end if;

end;
$function$
;

CREATE OR REPLACE FUNCTION public.start_current_weekly_report(target_unit_id bigint)
 RETURNS bigint
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public', 'pg_temp'
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
$function$
;

CREATE OR REPLACE FUNCTION public.transfer_new_member(target_new_member_id bigint, target_area_id bigint)
 RETURNS void
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public'
AS $function$
declare
    v_source_area_id bigint;
    v_source_mission_id bigint;
    v_target_mission_id bigint;
begin

    select
        nmaa.area_id
    into
        v_source_area_id
    from public.new_member_area_assignments nmaa
    where nmaa.new_member_id = target_new_member_id
      and nmaa.end_date is null;


    if v_source_area_id is null then
        raise exception
            'New Member does not have a current area assignment.';
    end if;


    if not public.can_access_area(v_source_area_id) then
        raise exception
            'You do not have permission to transfer this New Member.';
    end if;


    if v_source_area_id = target_area_id then
        raise exception
            'New Member is already assigned to this area.';
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
            'Use the end-follow-up workflow when someone moves outside the mission.';
    end if;


    -- Close old assignment.
    update public.new_member_area_assignments
    set
        end_date = current_date,
        transfer_reason = 'transferred_within_mission'
    where new_member_id = target_new_member_id
      and end_date is null;


    -- Start new assignment.
    insert into public.new_member_area_assignments (
        new_member_id,
        area_id,
        start_date,
        transfer_reason
    )
    values (
        target_new_member_id,
        target_area_id,
        current_date,
        'transferred_within_mission'
    );


    -- Temporary compatibility field.
    -- Remove when Appsmith no longer depends on new_members.area_id.
    update public.new_members
    set
        area_id = target_area_id,
        updated_at = now()
    where id = target_new_member_id;

end;
$function$
;

-- 2. Added by 023.
DROP FUNCTION IF EXISTS public.transfer_new_member(bigint, bigint, bigint);
DROP FUNCTION IF EXISTS public.reactivate_new_member(bigint, bigint);
DROP FUNCTION IF EXISTS public.update_new_member_profile(bigint, text, text, date, date, date, text, date, text, text, text, integer, text, text, text, text, text, text);
DROP FUNCTION IF EXISTS public.update_baptismal_date_person(bigint, text, text, text);
DROP FUNCTION IF EXISTS public.delete_new_member_added_by_mistake(bigint);
DROP FUNCTION IF EXISTS public.delete_baptismal_date_person_added_by_mistake(bigint);

-- 3. Pre-023 search_path and rights.
ALTER FUNCTION public.create_new_member(text, text, bigint, bigint, date, date, date, text, date, text, text, text, integer, text, text, text, text, text, text) SET search_path = public;
ALTER FUNCTION public.create_baptismal_date_person(text, text, text, bigint) SET search_path = public;
ALTER FUNCTION public.archive_new_member(bigint, text) SET search_path = public;
ALTER FUNCTION public.archive_baptismal_date_person(bigint, text) SET search_path = public;
ALTER FUNCTION public.transfer_baptismal_date_person(bigint, bigint, bigint) SET search_path = public;
ALTER FUNCTION public.convert_baptismal_date_person_to_new_member(bigint, date, date, date, date, text, text, text, integer, text, text, text, text, text, text) SET search_path = public;
ALTER FUNCTION public.get_previous_weekly_new_members(bigint) SET search_path = public;
ALTER FUNCTION public.archive_expired_new_members() SET search_path = public;
GRANT EXECUTE ON FUNCTION
  public.create_new_member(text, text, bigint, bigint, date, date, date, text, date, text, text, text, integer, text, text, text, text, text, text),
  public.create_baptismal_date_person(text, text, text, bigint),
  public.archive_new_member(bigint, text),
  public.archive_baptismal_date_person(bigint, text),
  public.transfer_baptismal_date_person(bigint, bigint, bigint),
  public.convert_baptismal_date_person_to_new_member(bigint, date, date, date, date, text, text, text, integer, text, text, text, text, text, text),
  public.get_previous_weekly_new_members(bigint),
  public.archive_expired_new_members(),
  public.transfer_new_member(bigint, bigint),
  public.reactivate_new_member(bigint)
TO anon, authenticated, service_role;
GRANT EXECUTE ON FUNCTION public.start_current_weekly_report(bigint) TO authenticated, service_role;

-- Check: the 11 functions are exactly as before 023, and the rights are the pre-023 ones.
DO $$
DECLARE
  fingerprint text;
  found text;
BEGIN
  SELECT md5(string_agg(replace(pg_get_functiondef(p.oid), E'\r', ''), E'\n' ORDER BY p.oid::regprocedure::text))
    INTO fingerprint
  FROM pg_proc p
  WHERE p.oid IN (
      'public.archive_baptismal_date_person(bigint,text)'::regprocedure,
      'public.archive_expired_new_members()'::regprocedure,
      'public.archive_new_member(bigint,text)'::regprocedure,
      'public.convert_baptismal_date_person_to_new_member(bigint,date,date,date,date,text,text,text,integer,text,text,text,text,text,text)'::regprocedure,
      'public.create_baptismal_date_person(text,text,text,bigint)'::regprocedure,
      'public.create_new_member(text,text,bigint,bigint,date,date,date,text,date,text,text,text,integer,text,text,text,text,text,text)'::regprocedure,
      'public.get_previous_weekly_new_members(bigint)'::regprocedure,
      'public.reactivate_new_member(bigint)'::regprocedure,
      'public.start_current_weekly_report(bigint)'::regprocedure,
      'public.transfer_baptismal_date_person(bigint,bigint,bigint)'::regprocedure,
      'public.transfer_new_member(bigint,bigint)'::regprocedure);
  RAISE NOTICE 'fingerprint %', fingerprint;
  IF fingerprint IS DISTINCT FROM '96e863e7dda9b89d4b0a33eb53057518' THEN
    RAISE EXCEPTION 'The people functions differ from Beta before 023 (fingerprint %).', fingerprint;
  END IF;
  SELECT string_agg(p.oid::regprocedure::text, ', ') INTO found
  FROM pg_proc p
  WHERE p.pronamespace = 'public'::regnamespace
    AND p.proname IN ('create_new_member', 'create_baptismal_date_person', 'archive_new_member',
                      'archive_baptismal_date_person', 'transfer_baptismal_date_person',
                      'convert_baptismal_date_person_to_new_member', 'get_previous_weekly_new_members',
                      'archive_expired_new_members', 'transfer_new_member', 'reactivate_new_member',
                      'start_current_weekly_report')
    AND p.oid <> 'public.start_current_weekly_report()'::regprocedure
    AND (has_function_privilege('public', p.oid, 'EXECUTE')
         OR NOT has_function_privilege('authenticated', p.oid, 'EXECUTE')
         OR NOT has_function_privilege('service_role', p.oid, 'EXECUTE')
         OR has_function_privilege('anon', p.oid, 'EXECUTE') <> (p.proname <> 'start_current_weekly_report'));
  IF found IS NOT NULL THEN
    RAISE EXCEPTION 'Unexpected EXECUTE rights on: %', found;
  END IF;
  IF EXISTS (SELECT 1 FROM pg_proc WHERE pronamespace = 'public'::regnamespace
             AND proname IN ('update_new_member_profile', 'update_baptismal_date_person',
                             'delete_new_member_added_by_mistake', 'delete_baptismal_date_person_added_by_mistake')) THEN
    RAISE EXCEPTION 'A function added by 023 is still there.';
  END IF;
END $$;

NOTIFY pgrst, 'reload schema';
COMMIT;
