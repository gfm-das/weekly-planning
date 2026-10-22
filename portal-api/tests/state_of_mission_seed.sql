-- SYNTHETIC data only (round 28 end-to-end test). No real mission data.
BEGIN;
INSERT INTO public.missions(id,name) VALUES (1,'Test Mission');
INSERT INTO public.zones(id,mission_id,name) VALUES (1,1,'Zone A');
INSERT INTO public.districts(id,zone_id,name) VALUES (1,1,'District A1');
INSERT INTO public.units(id,name) VALUES (1,'Ward Alpha'),(2,'Ward Beta'),(3,'Branch Gamma');
INSERT INTO public.areas(id,district_id,name,unit_id) VALUES (1,1,'Area One',1),(2,1,'Area Two',2),(3,1,'Area Three',3),(4,1,'Area Four',3);
INSERT INTO public.reporting_weeks(id,sunday) SELECT row_number() OVER (), d::date FROM generate_series('2026-07-05'::date,'2026-09-27'::date,'7 days') d;
INSERT INTO public.weekly_area_reports(id,area_id,reporting_week_id,unit_id,status,friends_found_actual,friends_found_goal)
  SELECT row_number() OVER (), a.id, w.id, a.unit_id, 'SUBMITTED', 3, 4 FROM public.areas a CROSS JOIN public.reporting_weeks w;
INSERT INTO public.missionaries(id,last_name,display_name,missionary_type) VALUES
 (1,'T1','Test 1','Elder'),(2,'T2','Test 2','Elder'),(3,'T3','Test 3','Elder'),(4,'T4','Test 4','Elder'),
 (5,'T5','Test 5','Elder'),(6,'T6','Test 6','Elder'),(7,'T7','Test 7','Sister'),(8,'T8','Test 8','Sister'),(9,'T9','Test 9','Elder');
INSERT INTO public.missionary_assignments(id,missionary_id,area_id,start_date,end_date) VALUES
 (1,1,1,'2026-06-01',NULL),(2,2,1,'2026-06-01',NULL),(3,3,1,'2026-06-01',NULL),(4,4,1,'2026-06-01',NULL),
 (5,5,2,'2026-06-01',NULL),(6,6,2,'2026-06-01',NULL),
 (7,7,3,'2026-08-01',NULL),(8,8,3,'2026-08-01',NULL),
 (9,9,2,'2026-01-01','2026-05-31');
-- area 1: two companionships; area 2: a stale row whose member no longer serves there (must not count);
-- areas 2 and 3 otherwise have no rows (counted as one companionship each).
INSERT INTO public.companionships(id,area_id,start_date,end_date) VALUES (1,1,'2026-06-01',NULL),(2,1,'2026-06-01',NULL),(3,2,'2026-01-01',NULL);
INSERT INTO public.companionship_members(companionship_id,missionary_id) VALUES (1,1),(1,2),(2,3),(2,4),(3,9);
COMMIT;
