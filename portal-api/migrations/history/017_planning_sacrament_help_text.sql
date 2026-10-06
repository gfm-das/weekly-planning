-- Optional, text only: the show/hide rules live in portal/planning.html (conditionalRules).
-- Brings the help text of "1st Time 1st Week" in line with the new rule. NOT applied live.
BEGIN;
UPDATE public.planning_questions
   SET help_text = 'Only show when Sacrament Attendance and 1st Time are greater than 0.'
 WHERE question_key = 'sacrament_first_time_first_week'
   AND help_text = 'Only show when Sacrament Attendance is greater than 0.';
COMMIT;
