-- DA Management migration 002 (history, applied in September 2026): the tables behind Account Manager languages, Import
-- history with Undo (batches and the rows each changed) and the details kept by the Historical CSV import.

begin;

create table if not exists public.missionary_language_assignments (
  missionary_id bigint primary key references public.missionaries(id) on delete cascade,
  primary_language text not null default 'en',
  additional_languages text[] not null default '{}',
  assigned_by text,
  updated_at timestamptz not null default now(),
  constraint language_primary_code check (primary_language ~ '^[a-zA-Z]{2,3}(-[a-zA-Z0-9]{2,8})*$'),
  constraint language_primary_not_additional check (not (primary_language = any(additional_languages)))
);
alter table public.missionary_language_assignments enable row level security;
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
grant select on public.missionary_language_assignments to authenticated;

do $$ declare c record; begin
  for c in select conname from pg_constraint where conrelid='public.user_profiles'::regclass
    and contype='c' and pg_get_constraintdef(oid) like '%app_role%' loop
    execute format('alter table public.user_profiles drop constraint %I',c.conname);
  end loop;
end $$;
alter table public.user_profiles add constraint user_profiles_app_role_management_check
check (app_role in ('MISSIONARY','DL','STL','ZL','AP','OFFICE','PRESIDENT','DATA_ADMIN'));

create table if not exists public.roster_import_batches (
  id uuid primary key,
  mission_id bigint not null references public.missions(id),
  kind text not null check (kind in ('TRANSFER','HISTORICAL')),
  filename text not null,
  effective_date date,
  actor text not null,
  status text not null default 'APPLIED' check (status in ('APPLIED','UNDONE')),
  summary jsonb not null default '{}',
  created_at timestamptz not null default now(),
  undone_at timestamptz,
  undone_by text
);
create table if not exists public.roster_import_changes (
  batch_id uuid not null references public.roster_import_batches(id) on delete cascade,
  sequence integer not null,
  table_name text not null,
  row_key jsonb not null,
  before_row jsonb,
  after_row jsonb,
  primary key(batch_id,sequence)
);
alter table public.roster_import_batches enable row level security;
alter table public.roster_import_changes enable row level security;

alter table public.import_weekly_planning_area_map
  add column if not exists mission_id bigint references public.missions(id),
  add column if not exists target_area_id bigint references public.areas(id),
  add column if not exists confirmed_at timestamptz,
  add column if not exists confirmed_by text;
update public.import_weekly_planning_area_map m set target_area_id=a.id,mission_id=z.mission_id
from public.areas a join public.districts d on d.id=a.district_id join public.zones z on z.id=d.zone_id
where m.target_area_id is null and lower(m.target_area_name)=lower(a.name)
and (select count(*) from public.areas aa where lower(aa.name)=lower(a.name))=1;

alter table public.weekly_area_reports
  add column if not exists historical_source_area text,
  add column if not exists historical_source_key text,
  add column if not exists import_batch_id uuid references public.roster_import_batches(id);
create unique index if not exists weekly_area_reports_historical_source_key_idx
on public.weekly_area_reports(historical_source_key) where historical_source_key is not null;

create table if not exists public.historical_planning_details (
  weekly_area_report_id bigint primary key references public.weekly_area_reports(id) on delete cascade,
  source_companionship text not null,
  source_unit text,
  answers jsonb not null default '[]',
  new_members jsonb not null default '[]',
  baptismal_date_friends jsonb not null default '[]',
  high_potential_friends jsonb not null default '[]'
);
alter table public.historical_planning_details enable row level security;

-- The importer connects as postgres; restored staging tables are owned by supabase_admin.
grant select,insert,update,delete on public.missionary_language_assignments,
  public.roster_import_batches,public.roster_import_changes,public.historical_planning_details,
  public.import_weekly_planning_area_map,public.import_weekly_planning_reports,
  public.import_weekly_planning_answers,public.import_weekly_new_members,
  public.import_weekly_baptismal_date_friends,public.import_weekly_high_potential_friends to postgres;

notify pgrst, 'reload schema';
commit;
