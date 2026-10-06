-- Migration 010 (history): the portal's own schema `portal`: calendar events, announcements and who read them, attendance,
-- attachments, push subscriptions, the activity log, reminder deliveries and user preferences. A new install gets all of
-- this from portal-api/baseline/000_baseline.sql instead.

BEGIN;
CREATE SCHEMA IF NOT EXISTS portal;
REVOKE ALL ON SCHEMA portal FROM PUBLIC, anon, authenticated;
CREATE TABLE IF NOT EXISTS portal.events (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), mission_id bigint NOT NULL REFERENCES public.missions(id),
 author_id uuid NOT NULL REFERENCES public.user_profiles(id), title text NOT NULL CHECK(length(title) BETWEEN 1 AND 180),
 description text NOT NULL DEFAULT '', starts_at timestamptz NOT NULL, ends_at timestamptz NOT NULL,
 timezone text NOT NULL DEFAULT 'Europe/Berlin', recurrence jsonb, roles text[] NOT NULL DEFAULT '{}',
 zone_ids bigint[] NOT NULL DEFAULT '{}', location text NOT NULL DEFAULT '', meeting_url text NOT NULL DEFAULT '',
 reminder_minutes integer NOT NULL DEFAULT 30 CHECK(reminder_minutes BETWEEN 0 AND 10080),
 created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(), CHECK(ends_at>starts_at)
);
CREATE TABLE IF NOT EXISTS portal.announcements (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), mission_id bigint NOT NULL REFERENCES public.missions(id),
 author_id uuid NOT NULL REFERENCES public.user_profiles(id), title text NOT NULL CHECK(length(title) BETWEEN 1 AND 180),
 body text NOT NULL, roles text[] NOT NULL DEFAULT '{}', zone_ids bigint[] NOT NULL DEFAULT '{}',
 district_ids bigint[] NOT NULL DEFAULT '{}', area_ids bigint[] NOT NULL DEFAULT '{}', user_ids uuid[] NOT NULL DEFAULT '{}',
 pinned boolean NOT NULL DEFAULT false, urgent boolean NOT NULL DEFAULT false, expires_at timestamptz,
 created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS portal.announcement_reads (
 announcement_id uuid REFERENCES portal.announcements(id) ON DELETE CASCADE,
 user_id uuid REFERENCES public.user_profiles(id) ON DELETE CASCADE, read_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(announcement_id,user_id)
);
CREATE TABLE IF NOT EXISTS portal.attendance (
 event_id uuid REFERENCES portal.events(id) ON DELETE CASCADE, occurrence timestamptz NOT NULL,
 user_id uuid REFERENCES public.user_profiles(id), attended boolean NOT NULL, recorded_by uuid REFERENCES public.user_profiles(id),
 recorded_at timestamptz NOT NULL DEFAULT now(), PRIMARY KEY(event_id,occurrence,user_id)
);
CREATE TABLE IF NOT EXISTS portal.attachments (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), mission_id bigint NOT NULL, uploader_id uuid NOT NULL,
 event_id uuid REFERENCES portal.events(id) ON DELETE CASCADE, announcement_id uuid REFERENCES portal.announcements(id) ON DELETE CASCADE,
 filename text NOT NULL, storage_name text NOT NULL UNIQUE, mime_type text NOT NULL, bytes bigint NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(), CHECK((event_id IS NULL)<>(announcement_id IS NULL))
);
CREATE TABLE IF NOT EXISTS portal.push_subscriptions (
 id bigserial PRIMARY KEY, user_id uuid NOT NULL REFERENCES public.user_profiles(id) ON DELETE CASCADE,
 endpoint text NOT NULL UNIQUE, keys jsonb NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS portal.activity (
 user_id uuid PRIMARY KEY REFERENCES public.user_profiles(id) ON DELETE CASCADE,
 area_id bigint, last_activity timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS portal.reminder_deliveries (
 user_id uuid NOT NULL, kind text NOT NULL, reference text NOT NULL, sent_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(user_id,kind,reference)
);
CREATE TABLE IF NOT EXISTS portal.user_preferences (
 user_id uuid PRIMARY KEY REFERENCES public.user_profiles(id) ON DELETE CASCADE, language text NOT NULL
);
CREATE INDEX IF NOT EXISTS portal_events_mission_start ON portal.events(mission_id,starts_at);
CREATE INDEX IF NOT EXISTS portal_announcements_mission ON portal.announcements(mission_id,created_at DESC);
ALTER TABLE portal.events ENABLE ROW LEVEL SECURITY;
ALTER TABLE portal.announcements ENABLE ROW LEVEL SECURITY;
ALTER TABLE portal.attachments ENABLE ROW LEVEL SECURITY;
ALTER TABLE portal.attendance ENABLE ROW LEVEL SECURITY;
ALTER TABLE portal.announcement_reads ENABLE ROW LEVEL SECURITY;
ALTER TABLE portal.push_subscriptions ENABLE ROW LEVEL SECURITY;
ALTER TABLE portal.activity ENABLE ROW LEVEL SECURITY;
ALTER TABLE portal.user_preferences ENABLE ROW LEVEL SECURITY;
COMMIT;
