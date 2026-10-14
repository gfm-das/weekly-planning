// The installer's two standing rules (round 13, task 17), checked on the real files. release/scan.sh checks the same on every release tree.
//   1. A new install starts with no Facebook / social-media Weekly Planning question or indicator that is switched on.
//   2. The installer's own files hold no fixed IP address or web address: names and addresses are variables (installer settings, .env).
// Run like the other installer tests: cd install && node --test tests/*.test.mjs
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { buildEnvFiles } from '../app/generate.mjs';

const REPO = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const SOCIAL = /facebook|social_media|social media|instagram|tiktok|whatsapp/i;

/** Every file of install/ except tests/ and .work/ (what a mission installs and runs). */
function installerFiles(dir = path.join(REPO, 'install')) {
  const out = [];
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    if (entry.name === 'tests' || entry.name === '.work' || entry.name === 'node_modules') continue;
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) out.push(...installerFiles(full));
    else out.push(full);
  }
  return out;
}
const textOf = file => fs.readFileSync(file, 'utf8');
const isText = file => !textOf(file).includes('\u0000');

test('the installer\'s own files name no social media', () => {
  const hits = installerFiles().filter(isText).filter(f => SOCIAL.test(textOf(f))).map(f => path.relative(REPO, f));
  assert.deepEqual(hits, []);
});

test('the starting database holds no Facebook / social-media catalogue row at all (retired rows were deleted, round 13)', () => {
  const sqlFiles = [
    path.join(REPO, 'portal-api', 'baseline', '000_baseline.sql'),
    ...fs.readdirSync(path.join(REPO, 'portal-api', 'migrations')).filter(n => /^\d{3}_.*\.sql$/.test(n) && !n.endsWith('_rollback.sql')).map(n => path.join(REPO, 'portal-api', 'migrations', n)),
  ];
  const rows = /^INSERT INTO public\.planning_(questions|question_sections|question_options|question_grid_rows|question_visibility_rules) /;
  const found = [];
  for (const file of sqlFiles) {
    for (const line of textOf(file).split(/\r?\n/)) {
      if (rows.test(line) && SOCIAL.test(line)) found.push(`${path.basename(file)}: ${line.slice(0, 120)}`);
    }
  }
  assert.deepEqual(found, []);
});

test('the baseline catalogue is consistent: every choice and grid row belongs to a question that is in the baseline', () => {
  const lines = textOf(path.join(REPO, 'portal-api', 'baseline', '000_baseline.sql')).split(/\r?\n/);
  const questionIds = new Set();
  const sectionIds = new Set();
  for (const line of lines) {
    let m = /^INSERT INTO public\.planning_questions .* VALUES \((\d+), (\d+), /.exec(line);
    if (m) questionIds.add(m[1]);
    m = /^INSERT INTO public\.planning_question_sections .* VALUES \((\d+), /.exec(line);
    if (m) sectionIds.add(m[1]);
  }
  assert.ok(questionIds.size > 20 && sectionIds.size > 3, 'the check found the catalogue');
  const orphans = [];
  for (const line of lines) {
    let m = /^INSERT INTO public\.planning_questions .* VALUES \((\d+), (\d+), /.exec(line);
    if (m && !sectionIds.has(m[2])) orphans.push(`question ${m[1]} -> section ${m[2]}`);
    m = /^INSERT INTO public\.planning_question_(?:options|grid_rows) .* VALUES \((\d+), (\d+), /.exec(line);
    if (m && !questionIds.has(m[2])) orphans.push(`row ${m[1]} -> question ${m[2]}`);
  }
  assert.deepEqual(orphans, []);
});
test('the installer holds no fixed IP address (127.0.0.1 and 0.0.0.0 only)', () => {
  const found = [];
  for (const file of installerFiles().filter(isText)) {
    for (const m of textOf(file).matchAll(/\b\d{1,3}(?:\.\d{1,3}){3}\b/g)) {
      if (m[0] !== '127.0.0.1' && m[0] !== '0.0.0.0') found.push(`${path.relative(REPO, file)}: ${m[0]}`);
    }
  }
  assert.deepEqual(found, []);
});

test('the installer holds no fixed web address (only localhost, 127.0.0.1, variables and documentation sites)', () => {
  const allowed = /^https?:\/\/(localhost|127\.0\.0\.1|x$|docs\.docker\.com|git-scm\.com|github\.com)/;
  const found = [];
  for (const file of installerFiles().filter(isText)) {
    for (const m of textOf(file).matchAll(/https?:\/\/[^\] "<>,/)`']+/g)) {
      if (!allowed.test(m[0]) && !/[${}]/.test(m[0])) found.push(`${path.relative(REPO, file)}: ${m[0]}`);
    }
  }
  assert.deepEqual(found, []);
});

test('the database stack\'s container names come from the project name, not from fixed text', () => {
  const answers = { missionName: 'Testland Mission', missionCode: 'TM', language: 'de', admin: { name: 'Pat', email: 'pat@example.org', password: 'x'.repeat(12) },
    email: null, publicDomain: '', timeZone: 'Europe/Berlin', cloudflareToken: '' };
  const dflt = buildEnvFiles(answers).files['portal-api/.env'];
  assert.match(dflt, /@gfm-beta-supabase-db-1:5432\//);
  assert.match(dflt, /SUPABASE_URL=http:\/\/gfm-beta-supabase-kong-1:8000/);
  const other = buildEnvFiles(answers, { supaProject: 'my-stack' }).files['portal-api/.env'];
  assert.match(other, /@my-stack-supabase-db-1:5432\//);
  assert.match(other, /SUPABASE_URL=http:\/\/my-stack-supabase-kong-1:8000/);
  assert.doesNotMatch(other, /gfm-beta/);
  assert.throws(() => buildEnvFiles(answers, { supaProject: 'bad name; rm' }), /GFM_SUPA_PROJECT/);
});
