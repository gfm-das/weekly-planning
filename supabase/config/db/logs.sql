-- Supabase start-up script (from Supabase's own docker setup): the _analytics schema for the logs service.

\set pguser `echo "$POSTGRES_USER"`
\c _supabase
create schema if not exists _analytics;
alter schema _analytics owner to :pguser;
\c postgres
