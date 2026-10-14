// Round 14: a fresh install must not seed Facebook / social-media Weekly Planning questions.
// Run: node portal/tests/no-social-media-seed-check.cjs
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const root = path.join(__dirname, '..', '..');
const SOCIAL = /facebook_finding_days|facebook_friends_found|findechristus_interactions|social_media_plan|'social_media'/i;
const files = [
  'portal-api/baseline/000_baseline.sql',
  ...fs.readdirSync(path.join(root, 'portal-api/migrations'))
    .filter(f => /^\d{3}_.*\.sql$/.test(f) && !f.includes('rollback'))
    .map(f => path.join('portal-api/migrations', f)),
];
let failures = 0;
for (const rel of files) {
  const text = fs.readFileSync(path.join(root, rel), 'utf8');
  const inserts = text.split(/\n/).filter(line =>
    /INSERT INTO public\.planning_(questions|question_sections|question_options|question_grid_rows|question_visibility_rules)/i.test(line)
    && SOCIAL.test(line));
  for (const line of inserts) {
    console.error('FAIL', rel, line.slice(0, 160));
    failures++;
  }
}
assert.equal(failures, 0, 'fresh-install seed must not contain Facebook/social-media catalogue rows');
console.log(`no-social-media-seed: ${files.length} files checked, clean`);
