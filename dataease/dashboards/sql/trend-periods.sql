-- Trend: the last 4 COMPLETE reporting weeks compared with the 4 complete weeks before them, one row per district,
-- for the six key indicators (<kpi>_last4 and <kpi>_prev4: results added up). The dashboard works out the change in
-- % after the zone and district filters, so it is right for any choice. A district without a row counts 0.
-- Speed: dashboards.kpi_district_week is read once (kdw) and used 2 times below. PostgreSQL works
-- out a WITH part that is used more than once only once; reading the view is most of the work of this query.
WITH kdw AS (
  SELECT * FROM dashboards.kpi_district_week
), cur AS (
  SELECT ((now() AT TIME ZONE 'Europe/Berlin')::date
          - extract(dow FROM (now() AT TIME ZONE 'Europe/Berlin'))::int) AS sunday
), ranked AS (
  SELECT s.sunday, row_number() OVER (ORDER BY s.sunday DESC) AS n
  FROM (SELECT DISTINCT k.sunday FROM kdw k, cur WHERE k.sunday < cur.sunday) s
)
SELECT k.zone, k.district,
       (SELECT to_char(r1.sunday, 'FMDD Mon YYYY') FROM ranked r1 WHERE r1.n = 1) AS week_label,
       coalesce(sum(k.friends_found_actual) FILTER (WHERE r.n <= 4), 0) AS npbt_last4,
       coalesce(sum(k.friends_found_actual) FILTER (WHERE r.n > 4), 0) AS npbt_prev4,
       coalesce(sum(k.baptisms_confirmations_actual) FILTER (WHERE r.n <= 4), 0) AS bc_last4,
       coalesce(sum(k.baptisms_confirmations_actual) FILTER (WHERE r.n > 4), 0) AS bc_prev4,
       coalesce(sum(k.baptismal_dates_actual) FILTER (WHERE r.n <= 4), 0) AS bd_last4,
       coalesce(sum(k.baptismal_dates_actual) FILTER (WHERE r.n > 4), 0) AS bd_prev4,
       coalesce(sum(k.sacrament_attendance_actual) FILTER (WHERE r.n <= 4), 0) AS sa_last4,
       coalesce(sum(k.sacrament_attendance_actual) FILTER (WHERE r.n > 4), 0) AS sa_prev4,
       coalesce(sum(k.members_at_lessons_actual) FILTER (WHERE r.n <= 4), 0) AS ml_last4,
       coalesce(sum(k.members_at_lessons_actual) FILTER (WHERE r.n > 4), 0) AS ml_prev4,
       coalesce(sum(k.new_member_sacrament_actual) FILTER (WHERE r.n <= 4), 0) AS nms_last4,
       coalesce(sum(k.new_member_sacrament_actual) FILTER (WHERE r.n > 4), 0) AS nms_prev4
FROM kdw k
JOIN ranked r ON r.sunday = k.sunday
WHERE r.n <= 8
GROUP BY k.zone, k.district
