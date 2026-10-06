-- Supabase start-up script (from Supabase's own docker setup): the _realtime schema for the realtime service.

\set pguser `echo "$POSTGRES_USER"`

create schema if not exists _realtime;
alter schema _realtime owner to :pguser;
