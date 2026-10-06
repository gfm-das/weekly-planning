-- Key indicators: the last 26 COMPLETE reporting weeks (the week still being reported is left out, so trends do
-- not dip at the start of each week), one row per week and district. Result = <kpi>_actual, goal = the goal the
-- areas set the week before for this week (<kpi>_previous_goal, as in Call-ins). Only weeks with goals from the
-- week before count, so the first week of the data (nobody had set goals yet) does not pull the goal line to 0.
-- A district without a row in a week counts 0, so every district has all 26 weeks and the trend of any group of
-- districts is exactly the sum of their trends: a straight line (least squares) over the 26 weeks, per district.
-- Speed: dashboards.kpi_district_week is read once (kdw) and used 3 times below. PostgreSQL works
-- out a WITH part that is used more than once only once; reading the view is most of the work of this query.
WITH kdw AS (
  SELECT * FROM dashboards.kpi_district_week
), cur AS (
  SELECT ((now() AT TIME ZONE 'Europe/Berlin')::date
          - extract(dow FROM (now() AT TIME ZONE 'Europe/Berlin'))::int) AS sunday
), weeks AS (
  SELECT k.sunday FROM kdw k, cur
  WHERE k.sunday < cur.sunday
  GROUP BY k.sunday HAVING count(k.friends_found_previous_goal) > 0
  ORDER BY k.sunday DESC LIMIT 26
), districts AS (
  SELECT DISTINCT k.zone, k.district_id, k.district FROM kdw k
  WHERE k.sunday IN (SELECT sunday FROM weeks)
), grid AS (
  SELECT w.sunday, d.zone, d.district_id, d.district,
         (w.sunday - DATE '2024-01-07') / 7 AS x
  FROM weeks w CROSS JOIN districts d
), rows AS (
  SELECT g.sunday, g.zone, g.district, g.district_id, g.x,
         coalesce(k.friends_found_actual, 0) AS npbt_actual,
         coalesce(k.friends_found_previous_goal, 0) AS npbt_goal,
         coalesce(k.baptisms_confirmations_actual, 0) AS bc_actual,
         coalesce(k.baptisms_confirmations_previous_goal, 0) AS bc_goal,
         coalesce(k.baptismal_dates_actual, 0) AS bd_actual,
         coalesce(k.baptismal_dates_previous_goal, 0) AS bd_goal,
         coalesce(k.sacrament_attendance_actual, 0) AS sa_actual,
         coalesce(k.sacrament_attendance_previous_goal, 0) AS sa_goal,
         coalesce(k.members_at_lessons_actual, 0) AS ml_actual,
         coalesce(k.members_at_lessons_previous_goal, 0) AS ml_goal,
         coalesce(k.new_member_sacrament_actual, 0) AS nms_actual,
         coalesce(k.new_member_sacrament_previous_goal, 0) AS nms_goal
  FROM grid g
  LEFT JOIN kdw k ON k.sunday = g.sunday AND k.district_id = g.district_id
)
SELECT r.sunday AS week, r.zone, r.district,
       r.npbt_actual, r.npbt_goal,
       round((regr_intercept(r.npbt_actual, r.x) OVER d + regr_slope(r.npbt_actual, r.x) OVER d * r.x)::numeric, 3) AS npbt_trend,
       r.bc_actual, r.bc_goal,
       round((regr_intercept(r.bc_actual, r.x) OVER d + regr_slope(r.bc_actual, r.x) OVER d * r.x)::numeric, 3) AS bc_trend,
       r.bd_actual, r.bd_goal,
       round((regr_intercept(r.bd_actual, r.x) OVER d + regr_slope(r.bd_actual, r.x) OVER d * r.x)::numeric, 3) AS bd_trend,
       r.sa_actual, r.sa_goal,
       round((regr_intercept(r.sa_actual, r.x) OVER d + regr_slope(r.sa_actual, r.x) OVER d * r.x)::numeric, 3) AS sa_trend,
       r.ml_actual, r.ml_goal,
       round((regr_intercept(r.ml_actual, r.x) OVER d + regr_slope(r.ml_actual, r.x) OVER d * r.x)::numeric, 3) AS ml_trend,
       r.nms_actual, r.nms_goal,
       round((regr_intercept(r.nms_actual, r.x) OVER d + regr_slope(r.nms_actual, r.x) OVER d * r.x)::numeric, 3) AS nms_trend
FROM rows r
WINDOW d AS (PARTITION BY r.district_id)
