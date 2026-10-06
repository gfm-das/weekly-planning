-- DA Management migration 001 (history, applied in September 2026): keeps each missionary's roster email in the database so
-- Account Manager still works after the roster file is gone.

begin;

-- Persist roster email so Account Manager can work after the upload is finished.
alter table public.missionaries
  add column if not exists email text;

-- Mission Portal provides a stable Church unit number in the Unit column.
alter table public.units
  add column if not exists unit_number text;

create index if not exists missionaries_email_lower_idx
  on public.missionaries (lower(email))
  where email is not null and email <> '';

create unique index if not exists units_unit_number_unique_idx
  on public.units (unit_number)
  where unit_number is not null and unit_number <> '';

commit;
