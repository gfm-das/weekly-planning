-- Per capita: the six key indicators of the last 4 COMPLETE reporting weeks added up per area and shown per 10,000
-- residents (2 decimals), one row per area that has a population in Geo data (DA Management > Data uploads > Geo
-- data, migration 046). An area without a population is left out here (dataset "Geo data coverage" lists it).
-- From dashboards.area_week_per_capita: counts and organisation names only, no people.
-- Speed: dashboards.area_week_per_capita is read once (pc) and used 2 times below. PostgreSQL works
-- out a WITH part that is used more than once only once; reading the view is most of the work of this query.
WITH pc AS (
  SELECT * FROM dashboards.area_week_per_capita
), cur AS (
  SELECT ((now() AT TIME ZONE 'Europe/Berlin')::date
          - extract(dow FROM (now() AT TIME ZONE 'Europe/Berlin'))::int) AS sunday
), weeks AS (
  SELECT DISTINCT p.sunday FROM pc p, cur
  WHERE p.sunday < cur.sunday ORDER BY p.sunday DESC LIMIT 4
), sums AS (
  SELECT p.zone, p.district, p.area, max(p.population) AS population,
         sum(p.friends_found_actual) AS npbt, sum(p.baptisms_confirmations_actual) AS bc,
         sum(p.baptismal_dates_actual) AS bd, sum(p.sacrament_attendance_actual) AS sa,
         sum(p.members_at_lessons_actual) AS ml, sum(p.new_member_sacrament_actual) AS nms
  FROM pc p
  WHERE p.sunday IN (SELECT sunday FROM weeks)
  GROUP BY p.zone, p.district, p.area
)
SELECT s.zone, s.district, s.area, s.population,
       round(coalesce(s.npbt, 0) * 10000.0 / s.population, 2) AS npbt_per_10k,
       round(coalesce(s.bc, 0) * 10000.0 / s.population, 2) AS bc_per_10k,
       round(coalesce(s.bd, 0) * 10000.0 / s.population, 2) AS bd_per_10k,
       round(coalesce(s.sa, 0) * 10000.0 / s.population, 2) AS sa_per_10k,
       round(coalesce(s.ml, 0) * 10000.0 / s.population, 2) AS ml_per_10k,
       round(coalesce(s.nms, 0) * 10000.0 / s.population, 2) AS nms_per_10k
FROM sums s
WHERE s.population > 0
