// Checks of the terminal mode (install/app/cli.mjs and terminalIo in setup.mjs): scripted answers, no network.
//   docker run --rm --network none -v "${PWD}\install:/i" -v "${PWD}\portal\i18n:/i18n:ro" -w /i node:24-alpine node --test tests/*.test.mjs
import test from 'node:test';
import assert from 'node:assert/strict';
import { Readable, Writable } from 'node:stream';
import { runCli } from '../app/cli.mjs';
import { terminalIo } from '../app/setup.mjs';

const languages = [{ code: 'en', name: 'English', english: 'English' }, { code: 'de', name: 'Deutsch', english: 'German' }, { code: 'fa', name: 'فارسی', english: 'Persian' }];
const options = { languages: languages.map(l => l.code), timeZones: ['UTC', 'Europe/Berlin'] };

/** An io that answers from a list, in order, and records what was asked and said. */
function scripted(answers) {
  const log = { asked: [], said: [] };
  const next = question => { log.asked.push(question); if (!answers.length) throw new Error('asked more than expected: ' + question); return answers.shift(); };
  return { log, say: t => log.said.push(t), ask: async (q, d) => next(q) || d || '', secret: async q => next(q) };
}

const MINIMUM = [
  'Testland Mission', '',                  // name, short code (default)
  '',                                      // logo: none
  '2',                                     // language: number 2 = de
  '',                                      // request another language: none
  'Pat Example', 'pat@example.org', 'a long password', 'a long password',
  'n',                                     // email now?
  '', 'Europe/Berlin',                     // public name, time zone
  '',                                      // tunnel token
];

test('the shortest run: the required answers only', async () => {
  const io = scripted([...MINIMUM]);
  const r = await runCli(io, options, { languages });
  assert.equal(r.answers.missionName, 'Testland Mission');
  assert.equal(r.answers.missionCode, 'TM');
  assert.equal(r.answers.language, 'de');
  assert.equal(r.answers.admin.email, 'pat@example.org');
  assert.equal(r.answers.timeZone, 'Europe/Berlin');
  assert.equal(r.answers.email, null);
  assert.equal(r.answers.cloudflareToken, '');
  assert.equal(r.logo, null);
});

test('a wrong answer is explained and asked again, and only that one', async () => {
  const answers = [...MINIMUM];
  answers.splice(6, 1, 'not an email', 'pat@example.org'); // asked again at once, the second try is accepted
  const io = scripted(answers);
  const r = await runCli(io, options, { languages });
  assert.equal(r.answers.admin.email, 'pat@example.org');
  assert.ok(io.log.said.some(t => t.includes('valid email')));
  assert.equal(io.log.asked.filter(q => q.startsWith('Display name')).length, 1, 'the name was not asked again');
  assert.equal(io.log.asked.filter(q => q.startsWith('Email (')).length, 2);
});

test('passwords that differ are both asked again', async () => {
  const answers = [...MINIMUM];
  answers.splice(7, 2, 'a long password', 'another one!!', 'good password 1', 'good password 1');
  const r = await runCli(scripted(answers), options, { languages });
  assert.equal(r.answers.admin.password, 'good password 1');
});

test('a language by code, a language request, email settings, a public name and a token', async () => {
  const answers = [
    'Testland Mission', 'TLM', '', 'fa',
    'Polish', 'pat@example.org',
    'Pat Example', 'pat@example.org', 'a long password', 'a long password',
    'y', 'smtp.example.org', '2525', 'mailer', 'secret-key', 'office@example.org', '',
    'Testland.Example', 'UTC',
    Buffer.from(JSON.stringify({ a: 'a'.repeat(32), t: '6f1c0a52-3c1d-4d7e-9a53-0d3f8f2c1a10', s: 'c2VjcmV0c2VjcmV0c2VjcmV0' })).toString('base64'),
  ];
  const r = await runCli(scripted(answers), options, { languages });
  assert.equal(r.answers.missionCode, 'TLM');
  assert.equal(r.answers.language, 'fa');
  assert.deepEqual(r.answers.languageRequest, { name: 'Polish', email: 'pat@example.org' });
  assert.equal(r.answers.email.host, 'smtp.example.org');
  assert.equal(r.answers.email.port, 2525);
  assert.equal(r.answers.email.password, 'secret-key');
  assert.equal(r.answers.publicDomain, 'testland.example');
  assert.ok(r.answers.cloudflareToken.startsWith('eyJ'));
});

test('a logo file that cannot be read is said so and skipped; one that can is used', async () => {
  const a1 = [...MINIMUM]; a1[2] = 'missing.png';
  const io = scripted(a1);
  assert.equal((await runCli(io, options, { languages, readLogoFile: () => null })).logo, null);
  assert.ok(io.log.said.some(t => t.includes('could not read')));
  const a2 = [...MINIMUM]; a2[2] = 'logo.png';
  const r = await runCli(scripted(a2), options, { languages, readLogoFile: () => 'data:image/png;base64,' + Buffer.from('png!').toString('base64') });
  assert.equal(r.logo.ext, 'png');
});

test('too many wrong answers stop the run', async () => {
  await assert.rejects(runCli(scripted(Array(60).fill('')), options, { languages }), /Too many wrong answers/);
});

test('the real terminal: piped answers work, and a secret is never echoed', async () => {
  const lines = ['Hello', 'sekrit-value', 'last'];
  const input = Readable.from(lines.map(l => l + '\n'));
  let shown = '';
  const output = new Writable({ write(chunk, enc, done) { shown += chunk; done(); } });
  const io = terminalIo(input, output);
  assert.equal(await io.ask('First'), 'Hello');
  assert.equal(await io.secret('Hidden'), 'sekrit-value');
  assert.equal(await io.ask('Third', 'fallback'), 'last');
  io.close();
  assert.ok(shown.includes('First: ') && shown.includes('Hidden: '));
  assert.ok(!shown.includes('sekrit-value'), 'the secret must not appear on the screen');
});

test('the real terminal: answers that run out give a clear error, an empty answer takes the default', async () => {
  const io = terminalIo(Readable.from(['\n']), new Writable({ write(c, e, d) { d(); } }));
  assert.equal(await io.ask('One', 'dflt'), 'dflt');
  await assert.rejects(io.ask('Two'), /answers ended/);
});
