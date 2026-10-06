-- "Friends Found" becomes "New People Being Taught", and the Preach My Gospel wording of the planning form.
-- Run on Beta only, as supabase_admin.
--
-- Why: the mission uses the key indicator names of Preach My Gospel, which calls this indicator "New People Being
-- Taught" (user decision, round 3). People see the name of a Weekly Planning question through its label, which
-- lives in the catalogue (planning_questions.question_label): the portal's Weekly Planning page, Beta (Appsmith),
-- DA Management and the Call-ins action plans all read it from there, so changing the label here changes it
-- everywhere they show it. The hidden names stay: question keys friends_found_*, the report columns
-- (weekly_area_reports.friends_found_*), the dashboards views' columns and every JSON key keep their names,
-- because saved plans, reports, Grafana panels and chart queries find the numbers by them.
-- The same round's Preach My Gospel wording guide also gives the planning form's section descriptions, the help
-- text of the action plans and a plainer name for "Information you want sent up the chain"; they are stored in
-- the same catalogue, so they are set here too (part 2).
--
-- What changes (data only; no table, view, function, trigger or grant is created or changed):
-- 1. The labels of the three protected questions friends_found_actual, friends_found_goal and friends_found_plan:
--    "Friends Found" becomes "New People Being Taught" wherever it appears in them, so "Friends Found - Actual"
--    becomes "New People Being Taught - Actual" (with the em dash the other labels use), "- Goal" and
--    "- Action Plan" the same. Migration 024's guards allow this: a protected question keeps its key, type and
--    place on the form, and its wording may change. The key of "Friends Found through Facebook"
--    (facebook_friends_found) is not the key indicator and its label is left as it is.
-- 2. Preach My Gospel wording (docs: /path/to\gfm-worktrees\pmg-guide.md, section 3.3), each only where the text is
--    still the one Beta has had so far (a text someone already changed in DA Management is left alone and named
--    in a NOTICE):
--    - the descriptions of the six sections (key_indicators_conversion, social_media, member_work,
--      ward_coordination, youth_service, weekly_plans);
--    - the help text of every action plan (the guide says all *_plan questions: the six key indicator plans,
--      social_media_plan and the companionship's weekly_action_plan), where it is still empty: "What will you do,
--      with whom, and when? Include how members can help.";
--    - information_up_chain: label "Information for leaders (optional)" (was "Optional: Information you want sent
--      up the chain") and help text "Anything your district leader should know or can help with."
-- Every change is written to planning_catalog_changes with actor 'Migration 028' (like 024's seeding), so DA
-- Management's change history shows it, and the rollback reads those rows. Plans that are still drafts show the
-- new wording at once; submitted plans keep their answers (only the question's wording changes, as always).
--
-- Not changed on purpose (found by a read-only search of the whole live database on 27 Sep 2026):
-- - historical_planning_details and import_weekly_planning_answers keep the old spreadsheet's column names
--   (only "Friends Found through Facebook"): they are how the historical importer matches old spreadsheets;
-- - the notes of 418 historical reports start with the old spreadsheet heading "Optional: Friends Found Action
--   Plan": imported text that no page shows, and Undo in Import history compares it with what was imported;
-- - roster_import_changes and planning_catalog_changes: audit rows, never rewritten.
-- No view, function or comment in the database shows "Friends Found" to people (the dashboards views use the
-- column names friends_found_*; Grafana shows its own panel titles).
--
-- Apply (back up Beta first). The file is plain ASCII (the em dash is written as U&'\2014'), so PowerShell may
-- pipe it as it is:
--   Get-Content portal-api/migrations/028_new_people_being_taught.sql -Raw |
--     docker exec -i gfm-beta-supabase-db-1 psql -U supabase_admin -d postgres -v ON_ERROR_STOP=1
--   (Git Bash: sed 's/\r$//' portal-api/migrations/028_new_people_being_taught.sql | docker exec -i ...)
-- Then run 019 again as a check (it must end with COMMIT):
--   Get-Content portal-api/migrations/019_restrict_public_functions.sql -Raw |
--     docker exec -i gfm-beta-supabase-db-1 psql -U supabase_admin -d postgres -v ON_ERROR_STOP=1
-- It briefly locks the catalogue rows it changes. If a long query holds them, the file stops after 10 seconds
-- (lock timeout) and changes nothing; run it again.
-- Safe to run again: every change is made only where it is still needed, so a second run changes nothing and
-- writes no history. The last block checks the result and stops on any problem.
-- Rollback: 028_new_people_being_taught_rollback.sql (puts back every text this file changed, where it is still
-- the one this file wrote, and records that in the history as 'Migration 028 rollback').
BEGIN;
SET LOCAL lock_timeout = '10s';

DO $$
BEGIN
  IF NOT (SELECT rolsuper FROM pg_roles WHERE rolname = current_user) THEN
    RAISE EXCEPTION 'Run this file as supabase_admin (see its header), not as %.', current_user;
  END IF;
  IF to_regclass('public.planning_catalog_changes') IS NULL
     OR NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public'
                    AND table_name = 'planning_questions' AND column_name = 'protected') THEN
    RAISE EXCEPTION 'Apply 024_planning_catalog.sql first.';
  END IF;
END $$;
-- Like 024: the catalogue belongs to postgres, the login of portal-api and DA Management.
SET LOCAL ROLE postgres;

-- 1. New People Being Taught ------------------------------------------------------------------------------------
WITH old AS (
  SELECT q.id, q.question_key, q.question_label FROM public.planning_questions q
  WHERE q.question_key IN ('friends_found_actual', 'friends_found_goal', 'friends_found_plan')
    AND q.question_label ~* 'friends\s+found'
  FOR UPDATE
), renamed AS (
  UPDATE public.planning_questions q
  SET question_label = regexp_replace(old.question_label, 'friends\s+found', 'New People Being Taught', 'gi')
  FROM old WHERE q.id = old.id
  RETURNING q.question_key, old.question_label AS before_label, q.question_label AS after_label
)
INSERT INTO public.planning_catalog_changes (actor, table_name, row_key, before_row, after_row, note)
SELECT 'Migration 028', 'planning_questions', jsonb_build_object('question_key', question_key),
       jsonb_build_object('question_label', before_label), jsonb_build_object('question_label', after_label),
       'Friends Found is now New People Being Taught, the name Preach My Gospel uses. The key stays.'
FROM renamed;

-- 2. Preach My Gospel wording -------------------------------------------------------------------------------------
-- Section descriptions, only where the description is still the one Beta has had so far.
WITH wanted(section_key, old_description, new_description) AS (VALUES
  ('key_indicators_conversion', 'Key indicators, goals, and weekly plans.',
   'How the people you are teaching progressed this week, and your goals and plans for next week.'),
  ('social_media', 'Social media finding and FindeChristus activity.',
   'Finding and teaching online this week.'),
  ('member_work', 'Member meals, visits, referrals, and member-supported work.',
   'Time with members: meals, visits and asking for referrals.'),
  ('ward_coordination', 'Ward missionary coordination meeting and attendance.',
   'Your GEMIKO (ward mission coordination) meeting: was it held, and who came?'),
  ('youth_service', 'Youth activities, mini-missions, and service.',
   'Youth activities, mini-missions and service in your ward or branch.'),
  ('weekly_plans', 'Information for leaders and the companionship''s weekly action plan.',
   'Your plan for the coming week, and anything your leaders should know.')
), old AS (
  SELECT s.id, s.section_key, s.description, w.new_description FROM public.planning_question_sections s
  JOIN wanted w ON w.section_key = s.section_key AND s.description = w.old_description
  FOR UPDATE OF s
), changed AS (
  UPDATE public.planning_question_sections s SET description = old.new_description
  FROM old WHERE s.id = old.id
  RETURNING s.section_key, old.description AS before_text, s.description AS after_text
)
INSERT INTO public.planning_catalog_changes (actor, table_name, row_key, before_row, after_row, note)
SELECT 'Migration 028', 'planning_question_sections', jsonb_build_object('section_key', section_key),
       jsonb_build_object('description', before_text), jsonb_build_object('description', after_text),
       'Preach My Gospel wording for the planning form.'
FROM changed;

-- Help text of every action plan (all *_plan questions on Beta), only where it is still empty.
WITH old AS (
  SELECT q.id, q.question_key, q.help_text FROM public.planning_questions q
  WHERE q.question_key IN ('nm_sacrament_attendance_plan', 'baptisms_confirmations_plan', 'baptismal_dates_plan',
                           'sacrament_attendance_plan', 'members_at_lessons_plan', 'friends_found_plan', 'social_media_plan',
                           'weekly_action_plan')
    AND nullif(btrim(coalesce(q.help_text, '')), '') IS NULL
  FOR UPDATE
), changed AS (
  UPDATE public.planning_questions q
  SET help_text = 'What will you do, with whom, and when? Include how members can help.'
  FROM old WHERE q.id = old.id
  RETURNING q.question_key, old.help_text AS before_text, q.help_text AS after_text
)
INSERT INTO public.planning_catalog_changes (actor, table_name, row_key, before_row, after_row, note)
SELECT 'Migration 028', 'planning_questions', jsonb_build_object('question_key', question_key),
       jsonb_build_object('help_text', before_text), jsonb_build_object('help_text', after_text),
       'Preach My Gospel wording: invite, help, follow up.'
FROM changed;

-- "Information you want sent up the chain": its label (where unchanged) and its help text (where empty).
WITH old AS (
  SELECT q.id, q.question_label, q.help_text FROM public.planning_questions q
  WHERE q.question_key = 'information_up_chain'
    AND (q.question_label = 'Optional: Information you want sent up the chain'
         OR nullif(btrim(coalesce(q.help_text, '')), '') IS NULL)
  FOR UPDATE
), changed AS (
  UPDATE public.planning_questions q
  SET question_label = CASE WHEN old.question_label = 'Optional: Information you want sent up the chain'
                            THEN 'Information for leaders (optional)' ELSE q.question_label END,
      help_text = coalesce(nullif(btrim(coalesce(old.help_text, '')), ''),
                           'Anything your district leader should know or can help with.')
  FROM old WHERE q.id = old.id
  RETURNING old.question_label AS before_label, q.question_label AS after_label, old.help_text AS before_text,
            q.help_text AS after_text
)
INSERT INTO public.planning_catalog_changes (actor, table_name, row_key, before_row, after_row, note)
SELECT 'Migration 028', 'planning_questions', jsonb_build_object('question_key', 'information_up_chain'),
       jsonb_strip_nulls(jsonb_build_object(
         'question_label', CASE WHEN before_label IS DISTINCT FROM after_label THEN before_label END))
         || CASE WHEN before_text IS DISTINCT FROM after_text THEN jsonb_build_object('help_text', before_text) ELSE '{}' END,
       jsonb_strip_nulls(jsonb_build_object(
         'question_label', CASE WHEN before_label IS DISTINCT FROM after_label THEN after_label END))
         || CASE WHEN before_text IS DISTINCT FROM after_text THEN jsonb_build_object('help_text', after_text) ELSE '{}' END,
       'Preach My Gospel wording: Information for leaders.'
FROM changed WHERE before_label IS DISTINCT FROM after_label OR before_text IS DISTINCT FROM after_text;

-- 3. Check --------------------------------------------------------------------------------------------------------
DO $$
DECLARE
  found text;
  em text := U&' \2014 ';
BEGIN
  -- The three key indicator questions: new name, same keys, still protected, active and required as before.
  SELECT string_agg(k, ', ') INTO found
  FROM unnest(ARRAY['friends_found_actual', 'friends_found_goal', 'friends_found_plan']) k
  WHERE NOT EXISTS (SELECT 1 FROM public.planning_questions q WHERE q.question_key = k AND q.protected AND q.active
                    AND q.question_label ~ 'New People Being Taught' AND q.question_label !~* 'friends\s+found');
  IF found IS NOT NULL THEN RAISE EXCEPTION 'Check failed: not renamed, not protected or not active: %', found; END IF;
  IF (SELECT count(*) FROM public.planning_questions WHERE question_key IN ('friends_found_actual', 'friends_found_goal')
      AND question_type = 'NUMBER' AND required) <> 2 THEN
    RAISE EXCEPTION 'Check failed: the actual and goal questions must stay required number questions.';
  END IF;
  -- The names Call-ins make from these labels (text before the dash, without "Optional:" and "- Action Plan").
  IF EXISTS (SELECT 1 FROM public.planning_questions q
             WHERE q.question_key IN ('friends_found_actual', 'friends_found_goal', 'friends_found_plan')
               AND btrim(regexp_replace(regexp_replace(q.question_label, '^Optional: ', ''), '\s*' || btrim(em) || '.*$', ''))
                   <> 'New People Being Taught') THEN
    RAISE NOTICE 'Note: a New People Being Taught label was worded differently in DA Management; Call-ins show it as it is.';
  END IF;
  -- Nothing else of the catalogue still says Friends Found, except the Facebook question (not the key indicator).
  SELECT string_agg(question_key, ', ') INTO found FROM public.planning_questions
  WHERE (question_label ~* 'friends\s+found' OR coalesce(help_text, '') ~* 'friends\s+found'
         OR coalesce(placeholder, '') ~* 'friends\s+found')
    AND question_key <> 'facebook_friends_found';
  IF found IS NOT NULL THEN RAISE EXCEPTION 'Check failed: still "Friends Found" in %', found; END IF;
  IF EXISTS (SELECT 1 FROM public.planning_question_sections WHERE section_title ~* 'friends\s+found'
             OR coalesce(description, '') ~* 'friends\s+found')
     OR EXISTS (SELECT 1 FROM public.planning_question_options WHERE option_label ~* 'friends\s+found')
     OR EXISTS (SELECT 1 FROM public.planning_question_grid_rows WHERE row_label ~* 'friends\s+found') THEN
    RAISE EXCEPTION 'Check failed: still "Friends Found" in a section, choice or grid row.';
  END IF;
  -- Texts left alone because someone already changed them in DA Management.
  SELECT string_agg(section_key, ', ') INTO found FROM public.planning_question_sections
  WHERE section_key IN ('key_indicators_conversion', 'social_media', 'member_work', 'ward_coordination', 'youth_service',
                        'weekly_plans')
    AND description IS DISTINCT FROM CASE section_key
      WHEN 'key_indicators_conversion' THEN 'How the people you are teaching progressed this week, and your goals and plans for next week.'
      WHEN 'social_media' THEN 'Finding and teaching online this week.'
      WHEN 'member_work' THEN 'Time with members: meals, visits and asking for referrals.'
      WHEN 'ward_coordination' THEN 'Your GEMIKO (ward mission coordination) meeting: was it held, and who came?'
      WHEN 'youth_service' THEN 'Youth activities, mini-missions and service in your ward or branch.'
      WHEN 'weekly_plans' THEN 'Your plan for the coming week, and anything your leaders should know.' END;
  IF found IS NOT NULL THEN
    RAISE NOTICE 'Left as they are (changed in DA Management before this file ran): the descriptions of %', found;
  END IF;
  SELECT string_agg(question_key, ', ') INTO found FROM public.planning_questions
  WHERE question_key IN ('nm_sacrament_attendance_plan', 'baptisms_confirmations_plan', 'baptismal_dates_plan',
                         'sacrament_attendance_plan', 'members_at_lessons_plan', 'friends_found_plan', 'social_media_plan',
                         'weekly_action_plan')
    AND help_text IS DISTINCT FROM 'What will you do, with whom, and when? Include how members can help.';
  IF found IS NOT NULL THEN
    RAISE NOTICE 'Left as they are (a help text was already written in DA Management): %', found;
  END IF;
  IF (SELECT question_label FROM public.planning_questions WHERE question_key = 'information_up_chain')
     IS DISTINCT FROM 'Information for leaders (optional)' THEN
    RAISE NOTICE 'Left as it is (changed in DA Management before this file ran): the label of information_up_chain';
  END IF;
  -- This file creates nothing, so there is no new right to check; the catalogue must stay closed to the API keys.
  IF has_table_privilege('anon', 'public.planning_questions', 'UPDATE')
     OR has_table_privilege('authenticated', 'public.planning_questions', 'UPDATE')
     OR has_table_privilege('authenticated', 'public.planning_catalog_changes', 'SELECT') THEN
    RAISE EXCEPTION 'Check failed: the API keys may change the catalogue or read its history (see 024).';
  END IF;
  RAISE NOTICE 'Migration 028: % label, description or help text change(s) recorded so far.',
    (SELECT count(*) FROM public.planning_catalog_changes WHERE actor = 'Migration 028');
END $$;

NOTIFY pgrst, 'reload schema';
COMMIT;

-- Verify afterwards (read only):
--   BEGIN READ ONLY; SELECT question_key, question_label FROM public.planning_questions
--   WHERE question_key LIKE 'friends_found%' ORDER BY question_key; ROLLBACK;
-- Expected: friends_found_actual "New People Being Taught - Actual" (em dash), _goal "... - Goal",
-- _plan "... - Action Plan".
