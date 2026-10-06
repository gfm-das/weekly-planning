-- Districts that may need help: the last 4 COMPLETE reporting weeks added up, one row per district, with the
-- result as a % of the goals its areas set the week before (empty when there was no goal). The charts show the
-- lowest first; each district is measured against its own goals, not against the other districts.
-- Speed: dashboards.kpi_district_week is read once (kdw) and used 2 times below. PostgreSQL works
-- out a WITH part that is used more than once only once; reading the view is most of the work of this query.
WITH kdw AS (
  SELECT * FROM dashboards.kpi_district_week
), cur AS (
  SELECT ((now() AT TIME ZONE 'Europe/Berlin')::date
          - extract(dow FROM (now() AT TIME ZONE 'Europe/Berlin'))::int) AS sunday
), weeks AS (
  SELECT DISTINCT k.sunday FROM kdw k, cur
  WHERE k.sunday < cur.sunday ORDER BY k.sunday DESC LIMIT 4
), sums AS (
  SELECT k.zone, k.district,
         sum(k.friends_found_actual) AS npbt_actual, sum(k.friends_found_previous_goal) AS npbt_goal,
         sum(k.sacrament_attendance_actual) AS sa_actual, sum(k.sacrament_attendance_previous_goal) AS sa_goal
  FROM kdw k
  WHERE k.sunday IN (SELECT sunday FROM weeks)
  GROUP BY k.zone, k.district
)
SELECT zone, district,
       coalesce(npbt_actual, 0) AS npbt_actual, coalesce(npbt_goal, 0) AS npbt_goal,
       round(100.0 * npbt_actual / nullif(npbt_goal, 0)) AS npbt_pct_of_goal,
       coalesce(sa_actual, 0) AS sa_actual, coalesce(sa_goal, 0) AS sa_goal,
       round(100.0 * sa_actual / nullif(sa_goal, 0)) AS sa_pct_of_goal
FROM sums
