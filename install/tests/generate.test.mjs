// Checks of install/app/generate.mjs (the settings files the installer writes). No network.
// Run with the whole repository mounted (the checks read the compose files and .env.example files next to install/):
//   docker run --rm --network none -v "${PWD}:/r" -w /r/install node:24-alpine node --test tests/*.test.mjs
import test from 'node:test';
import assert from 'node:assert/strict';
import crypto from 'node:crypto';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { execFileSync, spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { secret, makeJwt, makeVapid, dataeaseAdminPassword, renderEnv, shellQuote, buildEnvFiles } from '../app/generate.mjs';

const REPO = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const answers = {
  missionName: "Testland Mission", missionCode: 'TM', language: 'de', admin: { name: 'Pat', email: 'pat@example.org', password: 'x'.repeat(12) },
  email: null, publicDomain: '', timeZone: 'Europe/Berlin', cloudflareToken: '',
};
const parse = text => Object.fromEntries(text.split('\n').filter(l => l && !l.startsWith('#')).map(l => [l.slice(0, l.indexOf('=')), l.slice(l.indexOf('=') + 1)]));

test('secret: the right length and alphabet, different every time', () => {
  assert.match(secret(32), /^[A-Za-z0-9]{32}$/);
  assert.match(secret(64, '0123456789abcdef'), /^[0-9a-f]{64}$/);
  assert.notEqual(secret(32), secret(32));
});

test('makeJwt: a token Supabase accepts (HS256, role, 10 years)', () => {
  const token = makeJwt('s'.repeat(48), 'service_role', 1_800_000_000);
  const [h, b, s] = token.split('.');
  assert.deepEqual(JSON.parse(Buffer.from(h, 'base64url')), { alg: 'HS256', typ: 'JWT' });
  const body = JSON.parse(Buffer.from(b, 'base64url'));
  assert.equal(body.role, 'service_role');
  assert.equal(body.iss, 'supabase');
  assert.equal(body.exp - body.iat, 10 * 365 * 24 * 3600);
  assert.equal(s, crypto.createHmac('sha256', 's'.repeat(48)).update(`${h}.${b}`).digest('base64url'));
  assert.match(token, /^eyJ/, 'the portal deploy accepts a key only if it starts with eyJ');
});

test('makeVapid: a P-256 key pair in the form pywebpush reads', () => {
  const { publicKey, privateKey } = makeVapid();
  assert.equal(Buffer.from(publicKey, 'base64url').length, 65);
  assert.equal(Buffer.from(publicKey, 'base64url')[0], 4);
  assert.equal(Buffer.from(privateKey, 'base64url').length, 32);
});

test('dataeaseAdminPassword follows DataEase\'s rule', () => {
  for (let i = 0; i < 50; i++) {
    const p = dataeaseAdminPassword();
    assert.equal(p.length, 20);
    assert.match(p, /[a-z]/); assert.match(p, /[A-Z]/); assert.match(p, /[0-9]/);
    assert.match(p, /^[A-Za-z0-9]{19}[@\-_.+]$/);
  }
});

test('renderEnv and shellQuote', () => {
  assert.equal(renderEnv(['# c', ['A', 1], ['B', '']]), '# c\nA=1\nB=\n');
  assert.throws(() => renderEnv([['A', 'x\ny']]));
  assert.equal(shellQuote("it's"), `'it'\\''s'`);
});

test('every part gets its file, with no placeholder left', () => {
  const { files } = buildEnvFiles(answers, { host: '192.168.1.20' });
  assert.deepEqual(Object.keys(files).sort(), ['dataease/.env', 'nightly-backup/.env', 'nightly-backup/secrets/db-password', 'portal-api/.env', 'portal/.env', 'roster-importer/.env', 'slidev/.env', 'supabase/.env']);
  for (const [name, text] of Object.entries(files)) assert.doesNotMatch(text, /CHANGE_ME|REPLACE|Frankfurt|deutschland/i, name);
});

test('the settings agree with each other', () => {
  const { files } = buildEnvFiles(answers, { host: '192.168.1.20' });
  const sup = parse(files['supabase/.env']), api = parse(files['portal-api/.env']), imp = parse(files['roster-importer/.env']);
  const slidev = parse(files['slidev/.env']), de = parse(files['dataease/.env']);
  assert.equal(files['nightly-backup/secrets/db-password'], sup.SERVICE_PASSWORD_POSTGRES);
  assert.ok(api.DATABASE_URL.includes(`:${sup.SERVICE_PASSWORD_POSTGRES}@`));
  assert.equal(api.DATABASE_URL, imp.DATABASE_URL);
  for (const env of [api, imp, slidev]) assert.equal(env.SUPABASE_SERVICE_ROLE_KEY, sup.SERVICE_SUPABASESERVICE_KEY);
  assert.equal(api.PORTAL_SERVICE_KEY, slidev.PORTAL_SERVICE_KEY, 'portal-api and Presentations share one service key');
  assert.equal(api.DATAEASE_PROXY_SECRET, de.GFM_DATAEASE_PROXY_SECRET, 'portal-api and DataEase share the Dashboards cookie secret');
  assert.equal(imp.MISSION_ID, '1'); assert.equal(slidev.MISSION_ID, '1');
  assert.equal(sup.GFM_SITE_URL, 'http://192.168.1.20:8070');
  assert.equal(imp.PASSWORD_REDIRECT_URL, 'http://192.168.1.20:8070/');
  assert.equal(sup.SERVICE_URL_SUPABASEKONG, 'http://localhost:18000');
  // the anon and service keys are signed with the JWT secret
  for (const [key, role] of [[sup.SERVICE_SUPABASEANON_KEY, 'anon'], [sup.SERVICE_SUPABASESERVICE_KEY, 'service_role']]) {
    const [h, b, s] = key.split('.');
    assert.equal(s, crypto.createHmac('sha256', sup.SERVICE_PASSWORD_JWT).update(`${h}.${b}`).digest('base64url'));
    assert.equal(JSON.parse(Buffer.from(b, 'base64url')).role, role);
  }
  assert.equal(sup.SERVICE_PASSWORD_VAULTENC.length, 32);
  assert.equal(sup.SERVICE_PASSWORD_JWT.length, 48);
});

test('a tunnel token gets its own file; without one there is no file', () => {
  const token = Buffer.from(JSON.stringify({ a: 'a'.repeat(32), t: '6f1c0a52-3c1d-4d7e-9a53-0d3f8f2c1a10', s: 'c2VjcmV0' })).toString('base64');
  const none = buildEnvFiles(answers, { host: '10.0.0.5' });
  assert.ok(!('cloudflared/.env' in none.files));
  assert.equal(none.shell.GFM_CLOUDFLARE, 'no');
  const withTunnel = buildEnvFiles({ ...answers, publicDomain: 'testland.example', cloudflareToken: token }, { host: '10.0.0.5' });
  assert.equal(parse(withTunnel.files['cloudflared/.env']).TUNNEL_TOKEN, token);
  assert.equal(withTunnel.shell.GFM_CLOUDFLARE, 'yes');
  for (const [name, text] of Object.entries(withTunnel.files)) if (name !== 'cloudflared/.env') assert.ok(!text.includes(token), name + ' must not hold the token');
  assert.ok(!JSON.stringify(withTunnel.shell).includes(token), 'install.env holds no token');
});

test('a public name and email settings change the right lines', () => {
  const { files, shell } = buildEnvFiles({ ...answers, publicDomain: 'testland.example', email: { host: 'smtp.example.org', port: 2525, user: 'u', password: 'p', sender: 'office@example.org', senderName: 'Office' } }, { host: '10.0.0.5' });
  const sup = parse(files['supabase/.env']);
  assert.equal(sup.GFM_SITE_URL, 'https://testland.example');
  assert.equal(sup.GFM_PUBLIC_DOMAIN, 'testland.example');
  assert.equal(sup.SMTP_HOST, 'smtp.example.org'); assert.equal(sup.SMTP_PORT, '2525'); assert.equal(sup.SMTP_ADMIN_EMAIL, 'office@example.org');
  assert.equal(parse(files['roster-importer/.env']).PASSWORD_REDIRECT_URL, 'https://testland.example/');
  assert.equal(parse(files['portal/.env']).GFM_PUBLIC_DOMAIN, 'testland.example');
  assert.equal(shell.GFM_SITE_URL, 'https://testland.example');
});

test('every setting the Supabase compose file needs is in the generated supabase/.env', { skip: !fs.existsSync(path.join(REPO, 'supabase/supabase-compose.yml')) }, () => {
  const compose = fs.readFileSync(path.join(REPO, 'supabase/supabase-compose.yml'), 'utf8') + fs.readFileSync(path.join(REPO, 'supabase/beta-override.yml'), 'utf8');
  const needed = new Set([...compose.matchAll(/\$\{([A-Z][A-Z0-9_]*)(?::?[-+][^}]*)?\}/g)].filter(m => !/:?-/.test(m[0].slice(m[1].length + 2))).map(m => m[1]));
  const have = parse(buildEnvFiles(answers, { host: '127.0.0.1' }).files['supabase/.env']);
  const missing = [...needed].filter(name => !(name in have) && !['GFM_HOST_IP'].includes(name));
  assert.deepEqual(missing, []);
});

test('every name in the other parts\' .env.example files is written (or deliberately optional)', () => {
  const OPTIONAL = new Set(['VAPID_SUBJECT']);
  const built = buildEnvFiles(answers, { host: '127.0.0.1' }).files;
  for (const part of ['portal-api', 'roster-importer', 'slidev', 'dataease']) {
    const example = path.join(REPO, part, '.env.example');
    if (!fs.existsSync(example)) continue;
    const names = fs.readFileSync(example, 'utf8').split('\n').filter(l => /^[A-Z][A-Z0-9_]*=/.test(l)).map(l => l.split('=')[0]);
    const written = parse(built[`${part}/.env`]);
    // PRESENTATIONS_PORTAL_ORIGINS and the like are written; PORTAL_SERVICE_KEY etc. must be there
    assert.deepEqual(names.filter(n => !(n in written) && !OPTIONAL.has(n)), [], part);
  }
});

test('the command writes the files, never replaces one, and keeps secrets out of its messages', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'gfm-gen-'));
  const repo = path.join(dir, 'repo'); fs.mkdirSync(repo);
  const work = path.join(dir, 'work'); fs.mkdirSync(work);
  fs.writeFileSync(path.join(work, 'answers.json'), JSON.stringify(answers));
  const run = () => spawnSync('node', [path.join(REPO, 'install/app/generate.mjs'), path.join(work, 'answers.json'), repo], { encoding: 'utf8', env: { ...process.env, GFM_HOST_IP: '10.1.1.1' } });
  const first = run();
  assert.equal(first.status, 0, first.stderr);
  assert.match(first.stdout, /Wrote 8 settings files/);
  assert.ok(fs.existsSync(path.join(repo, 'portal-api/.env')));
  const shellText = fs.readFileSync(path.join(work, 'install.env'), 'utf8');
  assert.match(shellText, /^GFM_MISSION_NAME='Testland Mission'$/m);
  assert.match(shellText, /^GFM_HOST_IP='10\.1\.1\.1'$/m);
  assert.doesNotMatch(shellText, /password|key|secret/i, 'install.env holds no secrets');
  const dbPassword = parse(fs.readFileSync(path.join(repo, 'supabase/.env'), 'utf8')).SERVICE_PASSWORD_POSTGRES;
  const second = run();
  assert.equal(second.status, 2);
  assert.match(second.stderr, /exists already/);
  assert.ok(!(first.stdout + second.stderr).includes(dbPassword));
  assert.equal(parse(fs.readFileSync(path.join(repo, 'supabase/.env'), 'utf8')).SERVICE_PASSWORD_POSTGRES, dbPassword, 'the first files are untouched');
  fs.rmSync(dir, { recursive: true, force: true });
});
