-- Geo data coverage: one row per open area with the figures Geo data holds for it (population, size, density), the
-- source and the date they are from, and whether the area has a population yet. Not by week: the week_label of
-- the last COMPLETE reporting week is only there for the page's heading. From dashboards.area_geo_data (migration
-- 046): counts and organisation names only, no people.
WITH cur AS (
  SELECT ((now() AT TIME ZONE 'Europe/Berlin')::date
          - extract(dow FROM (now() AT TIME ZONE 'Europe/Berlin'))::int) AS sunday
), latest AS (
  SELECT max(k.sunday) AS sunday FROM dashboards.kpi_district_week k, cur WHERE k.sunday < cur.sunday
)
SELECT (SELECT to_char(l.sunday, 'FMDD Mon YYYY') FROM latest l) AS week_label,
       g.zone, g.district, g.area,
       CASE WHEN g.population > 0 THEN 1 ELSE 0 END AS has_population,
       1 AS area_count,
       coalesce(g.population, 0) AS population,
       coalesce(g.size_km2, 0) AS size_km2,
       coalesce(g.density_per_km2, 0) AS density_per_km2,
       coalesce(g.source, '') AS source,
       coalesce(to_char(g.data_date, 'YYYY-MM-DD'), '') AS data_date
FROM dashboards.area_geo_data g
WHERE g.active
