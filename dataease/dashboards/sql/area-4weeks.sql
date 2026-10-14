-- Areas that may need help: the last 4 COMPLETE reporting weeks added up, one row per area, for the six key
-- indicators, with the result as a % of the goals the area set the week before (empty when there was no goal). Each
-- area is measured against its own goals, not against the other areas. Numbers only, no names of people.
-- Speed: dashboards.kpi_area_total_week is read once (kat) and used 2 times below. PostgreSQL works
-- out a WITH part that is used more than once only once; reading the view is most of the work of this query.
WITH kat AS (
  SELECT * FROM dashboards.kpi_area_total_week
), cur AS (
  SELECT ((now() AT TIME ZONE 'Europe/Berlin')::date
          - extract(dow FROM (now() AT TIME ZONE 'Europe/Berlin'))::int) AS sunday
), weeks AS (
  SELECT DISTINCT k.sunday FROM kat k, cur
  WHERE k.sunday < cur.sunday ORDER BY k.sunday DESC LIMIT 4
), sums AS (
  SELECT k.zone, k.district, k.area,
         sum(k.friends_found_actual) AS npbt_actual, sum(k.friends_found_previous_goal) AS npbt_goal,
         sum(k.baptisms_confirmations_actual) AS bc_actual, sum(k.baptisms_confirmations_previous_goal) AS bc_goal,
         sum(k.baptismal_dates_actual) AS bd_actual, sum(k.baptismal_dates_previous_goal) AS bd_goal,
         sum(k.sacrament_attendance_actual) AS sa_actual, sum(k.sacrament_attendance_previous_goal) AS sa_goal,
         sum(k.members_at_lessons_actual) AS ml_actual, sum(k.members_at_lessons_previous_goal) AS ml_goal,
         sum(k.new_member_sacrament_actual) AS nms_actual, sum(k.new_member_sacrament_previous_goal) AS nms_goal
  FROM kat k
  WHERE k.sunday IN (SELECT sunday FROM weeks)
  GROUP BY k.zone, k.district, k.area
)
SELECT zone, district, area,
       coalesce(npbt_actual, 0) AS npbt_actual, coalesce(npbt_goal, 0) AS npbt_goal,
       round(100.0 * npbt_actual / nullif(npbt_goal, 0)) AS npbt_pct_of_goal,
       coalesce(bc_actual, 0) AS bc_actual, coalesce(bc_goal, 0) AS bc_goal,
       round(100.0 * bc_actual / nullif(bc_goal, 0)) AS bc_pct_of_goal,
       coalesce(bd_actual, 0) AS bd_actual, coalesce(bd_goal, 0) AS bd_goal,
       round(100.0 * bd_actual / nullif(bd_goal, 0)) AS bd_pct_of_goal,
       coalesce(sa_actual, 0) AS sa_actual, coalesce(sa_goal, 0) AS sa_goal,
       round(100.0 * sa_actual / nullif(sa_goal, 0)) AS sa_pct_of_goal,
       coalesce(ml_actual, 0) AS ml_actual, coalesce(ml_goal, 0) AS ml_goal,
       round(100.0 * ml_actual / nullif(ml_goal, 0)) AS ml_pct_of_goal,
       coalesce(nms_actual, 0) AS nms_actual, coalesce(nms_goal, 0) AS nms_goal,
       round(100.0 * nms_actual / nullif(nms_goal, 0)) AS nms_pct_of_goal
FROM sums
