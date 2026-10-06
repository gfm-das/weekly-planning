-- Upgrade existing management installs to current, mission-scoped language reads.
begin;
drop policy if exists assigned_languages_read on public.missionary_language_assignments;
create policy assigned_languages_read on public.missionary_language_assignments for select to authenticated
using (
  missionary_id in (
    select up.missionary_id from public.user_profiles up where up.id=auth.uid() and up.active
  )
  or exists (
    select 1 from public.user_profiles up
    left join lateral (
      select la.mission_id from public.leadership_assignments la
      where la.missionary_id=up.missionary_id and la.role='AP' and la.start_date<=current_date
        and (la.end_date is null or la.end_date>=current_date)
      order by la.start_date desc,la.id desc limit 1
    ) ap on true
    left join lateral (
      select own.mission_id from public.current_missionary_assignments own
      where own.missionary_id=up.missionary_id
      order by own.start_date desc,own.assignment_id desc limit 1
    ) own_scope on true
    join lateral (
      select target.mission_id from public.current_missionary_assignments target
      where target.missionary_id=missionary_language_assignments.missionary_id
      order by target.start_date desc,target.assignment_id desc limit 1
    ) target_scope on target_scope.mission_id=coalesce(ap.mission_id,own_scope.mission_id)
    where up.id=auth.uid() and up.active
      and (up.app_role in ('AP','PRESIDENT','DATA_ADMIN') or ap.mission_id is not null)
  )
);
notify pgrst, 'reload schema';
commit;
