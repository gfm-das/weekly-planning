// Text checks of the round 13 migrations 053 (Presentations V2 data) and 054 (social-media catalogue). No database here:
// the real run needs PostgreSQL (see docs/handoff/round13/misc2.md). These tests only keep the safety rules from being edited away.
// Run: cd install && node --test tests/migrations-053-054.test.mjs
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const DIR = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..', 'portal-api', 'migrations');
const read = name => fs.readFileSync(path.join(DIR, name.startsWith('054_') ? 'optional' : '.', name), 'utf8').replace(/\r\n/g, '\n');
const strip = sql => sql.split('\n').filter(l => !l.trim().startsWith('--')).join('\n');
const FILES = ['053_remove_presentations_v2_data'];
// 054 lives in migrations/optional/: the updater only reads NNN_name.sql directly in migrations/, so an installed system never runs it by itself.
// It stops when saved answers use the social-media questions, which would otherwise fail a whole update.

for (const name of FILES) {
  test(`${name}: one transaction, a rollback partner, run as the admin login`, () => {
    for (const file of [`${name}.sql`, `${name}_rollback.sql`]) {
      const sql = strip(read(file));
      assert.equal((sql.match(/^BEGIN;/gm) || []).length, 1, file);
      assert.equal((sql.match(/^COMMIT;/gm) || []).length, 1, file);
      assert.match(sql, /session_user NOT IN \('supabase_admin', 'postgres'\)/, file);
      assert.match(sql, /lock_timeout/, file);
    }
  });
}

test('053: copies the v2- rows into the backup table before it deletes them, drops nothing', () => {
  const sql = strip(read('053_remove_presentations_v2_data.sql'));
  const insert = sql.indexOf('INSERT INTO portal.presentation_access_v2_removed');
  const del = sql.indexOf("DELETE FROM portal.presentation_access WHERE deck_slug LIKE 'v2-%'");
  assert.ok(insert > 0 && del > insert, 'copy first, delete second');
  assert.ok(sql.indexOf('CREATE TABLE IF NOT EXISTS portal.presentation_access_v2_removed') < insert);
  assert.doesNotMatch(sql, /DROP TABLE|TRUNCATE/i);
  assert.match(sql, /already holds rows/, 'never overwrites a backup');
  assert.match(sql, /ENABLE ROW LEVEL SECURITY/);
  assert.match(sql, /REVOKE ALL ON portal\.presentation_access_v2_removed FROM PUBLIC, anon, authenticated/);
  const down = strip(read('053_remove_presentations_v2_data_rollback.sql'));
  assert.match(down, /FROM portal\.presentation_access_v2_removed/);
  assert.match(down, /ON CONFLICT \(mission_id, deck_slug\) DO NOTHING/);
  assert.doesNotMatch(down, /DROP TABLE/i);
});

test('056: deletes social-media answers and catalogue for real, keeps no copies, guards stay on', () => {
  const sql = strip(read('056_delete_social_media.sql'));
  assert.equal((sql.match(/^BEGIN;/gm) || []).length, 1);
  assert.match(sql, /session_user NOT IN \('supabase_admin', 'postgres'\)/);
  assert.match(sql, /DELETE FROM public\.weekly_planning_answers/);
  assert.match(sql, /DELETE FROM public\.planning_question_sections WHERE section_key = 'social_media'/);
  assert.match(sql, /DROP TABLE IF EXISTS portal\.presentation_access_v2_removed/);
  assert.doesNotMatch(sql, /planning_catalog_changes/, 'no change-log copy');
  assert.match(sql, /ENABLE TRIGGER planning_catalog_guard/);
  assert.ok(!fs.existsSync(path.join(DIR, 'optional')) || !fs.readdirSync(path.join(DIR, 'optional')).some(f => f.startsWith('054_')), 'optional 054 is gone');
});
