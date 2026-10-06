-- Rollback of migration 041: signed-in people may call delete_new_member_added_by_mistake() again (as after migration 023).
-- Run on Beta as supabase_admin, then migration 019 again. (The portal-api code of this change must be reverted too for the
-- button to come back.)
BEGIN;
GRANT EXECUTE ON FUNCTION public.delete_new_member_added_by_mistake(bigint) TO authenticated, service_role;
COMMIT;
