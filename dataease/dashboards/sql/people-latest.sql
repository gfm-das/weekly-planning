-- The covenant path in the last COMPLETE reporting week, counts only, one row per district that reported that
-- week (count-only views of migration 025; 0 when a district had nobody on its plans).
-- Speed: dashboards.kpi_district_week is read once (kdw) and used 2 times below. PostgreSQL works
-- out a WITH part that is used more than once only once; reading the view is most of the work of this query.
WITH kdw AS (
  SELECT * FROM dashboards.kpi_district_week
), cur AS (
  SELECT ((now() AT TIME ZONE 'Europe/Berlin')::date
          - extract(dow FROM (now() AT TIME ZONE 'Europe/Berlin'))::int) AS sunday
), latest AS (
  SELECT max(k.sunday) AS sunday FROM kdw k, cur WHERE k.sunday < cur.sunday
), districts AS (
  SELECT DISTINCT k.zone, k.district_id, k.district
  FROM kdw k JOIN latest ON k.sunday = latest.sunday
)
SELECT latest.sunday AS week, to_char(latest.sunday, 'FMDD Mon YYYY') AS week_label, d.zone, d.district,
       coalesce(p.new_members, 0) AS new_members,
       coalesce(p.new_members_at_church, 0) AS new_members_at_church,
       coalesce(p.new_members_temple_recommend, 0) AS new_members_temple_recommend,
       coalesce(p.new_members_calling, 0) AS new_members_calling,
       coalesce(p.new_members_aaronic_priesthood, 0) AS new_members_aaronic_priesthood,
       coalesce(p.new_members_melchizedek_priesthood, 0) AS new_members_melchizedek_priesthood,
       coalesce(p.baptismal_date_friends, 0) AS baptismal_date_friends,
       coalesce(p.baptismal_date_friends_next_4_weeks, 0) AS baptismal_date_friends_next_4_weeks,
       coalesce(p.baptismal_date_friends_at_church, 0) AS baptismal_date_friends_at_church,
       coalesce(p.high_potentials, 0) AS high_potentials,
       coalesce(p.high_potentials_at_church, 0) AS high_potentials_at_church
FROM latest
CROSS JOIN districts d
LEFT JOIN dashboards.people_district_week p ON p.sunday = latest.sunday AND p.district_id = d.district_id
