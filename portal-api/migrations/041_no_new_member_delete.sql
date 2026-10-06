-- Migration 041 (Oct 2026): a New Member can no longer be deleted by a signed-in person. Run on Beta only, as supabase_admin.
--
-- Why: the owner asked for the "Delete" action of New Members to go (portal-api no longer offers it). This closes the same
-- door in the database: a signed-in person could still call delete_new_member_added_by_mistake() directly. service_role and
-- postgres keep it (portal-api/tools/remove_test_data.py, the owner's tool for removing test entries, uses it).
-- Friends with a baptismal date keep their Delete.
-- Rollback: 041_no_new_member_delete_rollback.sql.
BEGIN;

REVOKE ALL ON FUNCTION public.delete_new_member_added_by_mistake(bigint) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.delete_new_member_added_by_mistake(bigint) TO service_role;

DO $$
BEGIN
  IF has_function_privilege('authenticated', 'public.delete_new_member_added_by_mistake(bigint)', 'EXECUTE')
     OR has_function_privilege('anon', 'public.delete_new_member_added_by_mistake(bigint)', 'EXECUTE') THEN
    RAISE EXCEPTION 'Check failed: a signed-in person can still delete a New Member.';
  END IF;
  IF NOT has_function_privilege('authenticated', 'public.delete_baptismal_date_person_added_by_mistake(bigint)', 'EXECUTE') THEN
    RAISE EXCEPTION 'Check failed: the friends'' Delete was changed by mistake.';
  END IF;
END $$;

COMMIT;
