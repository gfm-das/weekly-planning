-- mission.sql: makes the new mission (number 1) from the baseline's example row. The baseline ships Frankfurt as mission 2
-- (and its Archetypal Health settings); here the mission becomes number 1 with the name and default language the person
-- typed, and keeps those settings. Run by install/run-install.sh as supabase_admin, with psql variables
--   -v mission_name=... -v default_language=... -v time_zone=...    (psql quotes them, so any name is safe)
\set ON_ERROR_STOP on
BEGIN;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM public.missions WHERE id = 1) THEN
        RAISE EXCEPTION 'Mission 1 exists already: this database was set up before.';
    END IF;
END $$;

-- The example row gets a placeholder name first, so the new mission may have any name (the names are unique).
UPDATE public.missions SET name = '(example mission, removed by the installer)' WHERE id = 2;
INSERT INTO public.missions (id, name, default_language, time_zone) VALUES (1, :'mission_name', :'default_language', :'time_zone');
UPDATE public.archetype_settings SET mission_id = 1 WHERE mission_id = 2;
DELETE FROM public.missions WHERE id = 2;
SELECT setval(pg_get_serial_sequence('public.missions', 'id'), 1);

COMMIT;
