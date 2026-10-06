-- Rollback of migration 039. Run on Beta as supabase_admin:
--   Get-Content portal-api/migrations/039_people_from_uploads_rollback.sql -Raw | docker exec -i gfm-beta-supabase-db-1 psql -U supabase_admin -d postgres -v ON_ERROR_STOP=1
-- It puts back the two views and start_current_weekly_report as they were before 039, and drops the new functions and
-- table. People made by uploads stay (undo the upload in DA Management > Import history first).
BEGIN;
-- Undo (and remove from Import history) every People upload batch first: the old constraint does not know the kind.
ALTER TABLE public.roster_import_batches DROP CONSTRAINT IF EXISTS roster_import_batches_kind_check;
ALTER TABLE public.roster_import_batches ADD CONSTRAINT roster_import_batches_kind_check CHECK (kind IN (
  'TRANSFER', 'HISTORICAL', 'ACCOUNT',
  'AREA_DATA', 'FINDING', 'ZONE_HISTORY', 'REFERRAL_ARCHIVE', 'RATES', 'BAPTISMS'));
DROP FUNCTION IF EXISTS public.fill_current_week_plans();
DROP FUNCTION IF EXISTS public.carry_people_into_report(bigint);
DROP TABLE IF EXISTS public.people_match_decisions;

CREATE OR REPLACE VIEW public.current_new_members AS
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
   FROM new_members nm
  WHERE ((nm.follow_up_status = 'current'::text) AND ((nm.baptism_date IS NULL) OR (nm.baptism_date > (CURRENT_DATE - '1 year'::interval))) AND (EXISTS ( SELECT 1
           FROM new_member_area_assignments nmaa
          WHERE ((nmaa.new_member_id = nm.id) AND (nmaa.end_date IS NULL) AND (nmaa.area_id = nm.area_id)))));

ALTER VIEW public.current_new_members SET (security_invoker = true);

-- The friend view had one more column after the migration; a view cannot lose a column in place.
DROP VIEW public.current_baptismal_date_people;
CREATE VIEW public.current_baptismal_date_people WITH (security_invoker=true) AS
 SELECT f.id,
    f.first_name,
    f.last_name,
    f.display_name,
    f.finding_source,
    faa.area_id,
    faa.start_date AS area_start_date
   FROM (baptismal_date_people f
     JOIN baptismal_date_person_area_assignments faa ON ((faa.baptismal_date_person_id = f.id)))
  WHERE (faa.end_date IS NULL);
ALTER VIEW public.current_baptismal_date_people OWNER TO postgres;
GRANT ALL ON public.current_baptismal_date_people TO postgres, authenticated, service_role;

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
$function$

;

COMMIT;
