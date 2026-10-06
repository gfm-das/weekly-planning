-- Supabase start-up script (from Supabase's own docker setup): the _supavisor schema for the connection pooler.

\set pguser `echo "$POSTGRES_USER"`
\c _supabase
create schema if not exists _supavisor;
alter schema _supavisor owner to :pguser;
\c postgres
