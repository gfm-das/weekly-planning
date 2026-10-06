-- Zones by week: the last 26 COMPLETE reporting weeks, one row per week and zone, with the result as a % of the
-- goal the zone's areas set the week before (empty when there was no goal; weeks in which nobody had set goals
-- the week before, like the first week of the data, are left out). From dashboards.kpi_zone_week, whose
-- previous goals equal Call-ins' for every zone and week.
-- Speed: dashboards.kpi_zone_week is read once (kzw) and used 2 times below. PostgreSQL works
-- out a WITH part that is used more than once only once; reading the view is most of the work of this query.
WITH kzw AS (
  SELECT * FROM dashboards.kpi_zone_week
), cur AS (
  SELECT ((now() AT TIME ZONE 'Europe/Berlin')::date
          - extract(dow FROM (now() AT TIME ZONE 'Europe/Berlin'))::int) AS sunday
), weeks AS (
  SELECT z.sunday FROM kzw z, cur
  WHERE z.sunday < cur.sunday
  GROUP BY z.sunday HAVING count(z.friends_found_previous_goal) > 0
  ORDER BY z.sunday DESC LIMIT 26
)
SELECT z.sunday AS week, z.zone,
       coalesce(z.friends_found_actual, 0) AS npbt_actual,
       coalesce(z.friends_found_previous_goal, 0) AS npbt_goal,
       round(100.0 * z.friends_found_actual / nullif(z.friends_found_previous_goal, 0)) AS npbt_pct_of_goal,
       coalesce(z.sacrament_attendance_actual, 0) AS sa_actual,
       coalesce(z.sacrament_attendance_previous_goal, 0) AS sa_goal,
       round(100.0 * z.sacrament_attendance_actual / nullif(z.sacrament_attendance_previous_goal, 0)) AS sa_pct_of_goal
FROM kzw z
WHERE z.sunday IN (SELECT sunday FROM weeks)
