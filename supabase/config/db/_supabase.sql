-- Supabase start-up script (from Supabase's own docker setup): creates the internal database _supabase on the first start.

\set pguser `echo "$POSTGRES_USER"`

CREATE DATABASE _supabase WITH OWNER :pguser;
