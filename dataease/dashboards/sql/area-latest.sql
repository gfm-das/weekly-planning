-- Key indicators of the last COMPLETE reporting week, one row per area (one area = the work of one companionship),
-- with the goal the area set the week before (<kpi>_previous_goal, as in Call-ins) and the result of the week
-- before (for the change). From dashboards.kpi_area_total_week (area totals, units added up). Numbers only: the
-- view holds no names of missionaries or of the people they teach.
-- Speed: dashboards.kpi_area_total_week is read once (kat) and used 4 times below. PostgreSQL works
-- out a WITH part that is used more than once only once; reading the view is most of the work of this query.
WITH kat AS (
  SELECT * FROM dashboards.kpi_area_total_week
), cur AS (
  SELECT ((now() AT TIME ZONE 'Europe/Berlin')::date
          - extract(dow FROM (now() AT TIME ZONE 'Europe/Berlin'))::int) AS sunday
), latest AS (
  SELECT max(k.sunday) AS sunday FROM kat k, cur WHERE k.sunday < cur.sunday
), before AS (
  SELECT max(k.sunday) AS sunday FROM kat k, latest WHERE k.sunday < latest.sunday
)
SELECT k.sunday AS week,
       to_char(k.sunday, 'FMDD Mon YYYY') AS week_label,
       k.zone, k.district, k.area,
       coalesce(k.friends_found_actual, 0) AS npbt_actual,
       coalesce(k.friends_found_previous_goal, 0) AS npbt_goal,
       coalesce(b.friends_found_actual, 0) AS npbt_week_before,
       coalesce(k.baptisms_confirmations_actual, 0) AS bc_actual,
       coalesce(k.baptisms_confirmations_previous_goal, 0) AS bc_goal,
       coalesce(b.baptisms_confirmations_actual, 0) AS bc_week_before,
       coalesce(k.baptismal_dates_actual, 0) AS bd_actual,
       coalesce(k.baptismal_dates_previous_goal, 0) AS bd_goal,
       coalesce(b.baptismal_dates_actual, 0) AS bd_week_before,
       coalesce(k.sacrament_attendance_actual, 0) AS sa_actual,
       coalesce(k.sacrament_attendance_previous_goal, 0) AS sa_goal,
       coalesce(b.sacrament_attendance_actual, 0) AS sa_week_before,
       coalesce(k.members_at_lessons_actual, 0) AS ml_actual,
       coalesce(k.members_at_lessons_previous_goal, 0) AS ml_goal,
       coalesce(b.members_at_lessons_actual, 0) AS ml_week_before,
       coalesce(k.new_member_sacrament_actual, 0) AS nms_actual,
       coalesce(k.new_member_sacrament_previous_goal, 0) AS nms_goal,
       coalesce(b.new_member_sacrament_actual, 0) AS nms_week_before
FROM kat k
JOIN latest ON k.sunday = latest.sunday
LEFT JOIN before ON true
LEFT JOIN kat b ON b.sunday = before.sunday AND b.area_id = k.area_id
