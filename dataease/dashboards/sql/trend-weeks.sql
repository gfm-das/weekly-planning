-- Trend: the last 26 COMPLETE reporting weeks (the week still being reported is left out), one row per week and
-- district, for the six key indicators: the result (<kpi>_actual), the goal set the week before (<kpi>_goal) and
-- the average of that week and the 3 before it (<kpi>_avg4, rounded to 2 decimals). The average reads 3 weeks
-- further back than the first week shown, so it is complete from the first week on. Only weeks with goals from the
-- week before count (the first week of the data had none). A district without a row in a week counts 0, so every
-- district has all 26 weeks and the average of any group of districts is exactly the sum of their averages.
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
  ORDER BY k.sunday DESC LIMIT 29
), shown AS (
  SELECT sunday FROM weeks ORDER BY sunday DESC LIMIT 26
), districts AS (
  SELECT DISTINCT k.zone, k.district_id, k.district FROM kdw k
  WHERE k.sunday IN (SELECT sunday FROM weeks)
), grid AS (
  SELECT w.sunday, d.zone, d.district_id, d.district
  FROM weeks w CROSS JOIN districts d
), rows AS (
  SELECT g.sunday, g.zone, g.district, g.district_id,
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
), calc AS (
  SELECT r.*,
         round(avg(r.npbt_actual) OVER w4, 2) AS npbt_avg4,
         round(avg(r.bc_actual) OVER w4, 2) AS bc_avg4,
         round(avg(r.bd_actual) OVER w4, 2) AS bd_avg4,
         round(avg(r.sa_actual) OVER w4, 2) AS sa_avg4,
         round(avg(r.ml_actual) OVER w4, 2) AS ml_avg4,
         round(avg(r.nms_actual) OVER w4, 2) AS nms_avg4
  FROM rows r
  WINDOW w4 AS (PARTITION BY r.district_id ORDER BY r.sunday ROWS BETWEEN 3 PRECEDING AND CURRENT ROW)
)
SELECT c.sunday AS week, c.zone, c.district,
       c.npbt_actual, c.npbt_goal, c.npbt_avg4,
       c.bc_actual, c.bc_goal, c.bc_avg4,
       c.bd_actual, c.bd_goal, c.bd_avg4,
       c.sa_actual, c.sa_goal, c.sa_avg4,
       c.ml_actual, c.ml_goal, c.ml_avg4,
       c.nms_actual, c.nms_goal, c.nms_avg4
FROM calc c
WHERE c.sunday IN (SELECT sunday FROM shown)
