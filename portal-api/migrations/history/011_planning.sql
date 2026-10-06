-- Keep the existing Appsmith RPC signature while requiring a leader unlock.
-- Run on Beta only. No report, answer, role, or production data is rewritten.
BEGIN;

CREATE OR REPLACE FUNCTION public.unsubmit_weekly_report(target_report_id bigint)
RETURNS TABLE(weekly_report_id bigint, status text, submitted_by uuid, submitted_at timestamptz)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $function$
DECLARE
    v_area_id bigint;
    v_status text;
    v_allowed boolean;
BEGIN
    SELECT war.area_id, war.status INTO v_area_id, v_status
    FROM public.weekly_area_reports war
    WHERE war.id = target_report_id
    FOR UPDATE;

    IF v_area_id IS NULL THEN
        RAISE EXCEPTION 'This plan is not available.' USING ERRCODE = '42501';
    END IF;

    SELECT EXISTS (
        SELECT 1
        FROM public.user_profiles up
        JOIN public.areas a ON a.id = v_area_id
        JOIN public.districts d ON d.id = a.district_id
        JOIN public.zones z ON z.id = d.zone_id
        WHERE up.id = auth.uid() AND up.active
          AND (
              (up.app_role IN ('AP', 'PRESIDENT', 'DATA_ADMIN') AND EXISTS (
                  SELECT 1 FROM public.current_user_scope scope
                  WHERE scope.user_id = auth.uid()
                    AND coalesce(scope.leadership_mission_id, scope.mission_id) = z.mission_id
              ))
              OR EXISTS (
                  SELECT 1 FROM public.leadership_assignments la
                  WHERE la.missionary_id = up.missionary_id
                    AND la.start_date <= CURRENT_DATE
                    AND (la.end_date IS NULL OR la.end_date >= CURRENT_DATE)
                    AND (
                        (la.role = 'DL' AND la.district_id = d.id)
                        OR (la.role = 'ZL' AND la.zone_id = z.id)
                    )
              )
          )
    ) INTO v_allowed;

    IF NOT v_allowed THEN
        RAISE EXCEPTION 'A leader within this stewardship must unlock this plan.' USING ERRCODE = '42501';
    END IF;
    IF v_status <> 'SUBMITTED' THEN
        RAISE EXCEPTION 'Only a submitted plan can be reopened.' USING ERRCODE = '22023';
    END IF;

    RETURN QUERY
    UPDATE public.weekly_area_reports war
    SET status = 'DRAFT', submitted_by = NULL, submitted_at = NULL, updated_at = now()
    WHERE war.id = target_report_id AND war.status = 'SUBMITTED'
    RETURNING war.id, war.status, war.submitted_by, war.submitted_at;
END;
$function$;

REVOKE EXECUTE ON FUNCTION public.unsubmit_weekly_report(bigint) FROM PUBLIC, anon;
GRANT EXECUTE ON FUNCTION public.unsubmit_weekly_report(bigint) TO authenticated;

COMMIT;
