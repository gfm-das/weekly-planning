// Checks of install/app/validate.mjs (the setup form's rules): no network, no packages.
//   docker run --rm --network none -v "${PWD}\install:/i" -w /i node:24-alpine node --test tests/*.test.mjs
import test from 'node:test';
import assert from 'node:assert/strict';
import { validate, shortCode, readLogo, tunnelToken } from '../app/validate.mjs';

const options = { languages: ['en', 'de', 'fa'], timeZones: ['UTC', 'Europe/Berlin'] };
const good = () => ({
  missionName: 'Germany Frankfurt Mission', missionCode: '', language: 'de',
  admin: { name: 'Pat Example', email: 'Pat@Example.org', password: 'a long password', passwordAgain: 'a long password' },
  timeZone: 'Europe/Berlin',
});

test('shortCode: the first letter of each word', () => {
  assert.equal(shortCode('Germany Frankfurt Mission'), 'GFM');
  assert.equal(shortCode('  utah  salt-lake city mission '), 'USLCM');
  assert.equal(shortCode('Åland Öst'), 'AO');
  assert.equal(shortCode('One Two Three Four Five Six Seven'), 'OTTFFS');
  assert.equal(shortCode(''), '');
});

test('a good form passes and is cleaned', () => {
  const r = validate(good(), options);
  assert.ok(r.ok, JSON.stringify(r.errors));
  assert.equal(r.answers.missionCode, 'GFM', 'an empty code is made from the name');
  assert.equal(r.answers.admin.email, 'pat@example.org');
  assert.equal(r.answers.email, null);
  assert.equal(r.answers.languageRequest, null);
  assert.equal(r.logo, null);
});

test('the required parts each name their problem', () => {
  const r = validate({ missionName: '', language: 'xx', admin: { name: '', email: 'nope', password: 'short' }, timeZone: 'Mars/Base' }, options);
  assert.deepEqual(Object.keys(r.errors).sort(), ['adminEmail', 'adminName', 'adminPassword', 'language', 'missionCode', 'missionName', 'timeZone']);
});

test('passwords: length, not the email, both typed the same', () => {
  const bad = pw => validate({ ...good(), admin: { ...good().admin, password: pw, passwordAgain: pw } }, options).errors.adminPassword;
  assert.ok(bad('123456789'));
  assert.equal(bad('1234567890'), undefined);
  assert.ok(validate({ ...good(), admin: { name: 'P', email: 'pat@example.org', password: 'PAT@example.org' } }, options).errors.adminPassword);
  assert.ok(validate({ ...good(), admin: { ...good().admin, passwordAgain: 'something else' } }, options).errors.adminPasswordAgain);
});

test('the short code can be edited, and is checked', () => {
  assert.equal(validate({ ...good(), missionCode: 'ffm' }, options).answers.missionCode, 'FFM');
  assert.ok(validate({ ...good(), missionCode: 'a b' }, options).errors.missionCode);
  assert.ok(validate({ ...good(), missionCode: 'TOOLONGCODE' }, options).errors.missionCode);
});

test('"Request another language" needs a name; the email is optional but must look right', () => {
  assert.deepEqual(validate({ ...good(), requestLanguageName: 'Polish' }, options).answers.languageRequest, { name: 'Polish', email: '' });
  assert.ok(validate({ ...good(), requestLanguageEmail: 'a@b.org' }, options).errors.requestLanguageName);
  assert.ok(validate({ ...good(), requestLanguageName: 'Polish', requestLanguageEmail: 'broken' }, options).errors.requestLanguageEmail);
});

test('email settings are all or nothing', () => {
  assert.equal(validate({ ...good(), email: {} }, options).answers.email, null);
  const r = validate({ ...good(), email: { host: 'smtp.example.org', port: '2525', user: 'u', password: 'p', sender: 'office@example.org' } }, options);
  assert.ok(r.ok, JSON.stringify(r.errors));
  assert.equal(r.answers.email.port, 2525);
  assert.equal(r.answers.email.senderName, 'Germany Frankfurt Mission');
  assert.ok(validate({ ...good(), email: { host: 'smtp.example.org' } }, options).errors.emailSender);
  assert.ok(validate({ ...good(), email: { host: 'x', sender: 'a@b.org' } }, options).errors.emailHost);
  assert.ok(validate({ ...good(), email: { host: 'smtp.example.org', port: '99999', sender: 'a@b.org' } }, options).errors.emailPort);
});

test('the public address is a plain web name', () => {
  assert.equal(validate({ ...good(), publicDomain: 'https://www.Example.org/portal' }, options).answers.publicDomain, 'example.org');
  assert.ok(validate({ ...good(), publicDomain: 'not a domain' }, options).errors.publicDomain);
  assert.ok(validate({ ...good(), publicDomain: 'localhost' }, options).errors.publicDomain);
  assert.equal(validate(good(), options).answers.publicDomain, '');
});

// A token as Cloudflare makes it: base64 of {"a": account, "t": tunnel id, "s": secret}.
const makeToken = (extra = {}) => Buffer.from(JSON.stringify({ a: 'a'.repeat(32), t: '6f1c0a52-3c1d-4d7e-9a53-0d3f8f2c1a10', s: 'c2VjcmV0c2VjcmV0c2VjcmV0', ...extra })).toString('base64');

test('the Cloudflare token: empty is fine; a real one needs the public web name', () => {
  assert.ok(validate({ ...good(), cloudflareToken: '' }, options).ok);
  assert.equal(validate({ ...good(), cloudflareToken: '   ' }, options).answers.cloudflareToken, '');
  const ok = validate({ ...good(), publicDomain: 'example.org', cloudflareToken: makeToken() }, options);
  assert.ok(ok.ok, JSON.stringify(ok.errors));
  assert.equal(ok.answers.cloudflareToken, makeToken());
  assert.match(validate({ ...good(), cloudflareToken: makeToken() }, options).errors.cloudflareToken, /public web name/);
});

test('the Cloudflare token: the whole command from the Cloudflare page works, anything else is refused', () => {
  const token = makeToken();
  for (const pasted of [`cloudflared.exe service install ${token}`, `sudo cloudflared service install ${token}\n`, `docker run cloudflare/cloudflared tunnel run --token ${token}`]) {
    assert.equal(tunnelToken(pasted).token, token, pasted.slice(0, 30));
  }
  for (const bad of ['too short', 'a b '.repeat(20), 'eyJ' + 'x'.repeat(60), Buffer.from('{"hello":"world"}').toString('base64'), Buffer.from('not json at all, long enough to pass').toString('base64'),
    makeToken({ t: 'not-a-uuid' }), makeToken({ s: undefined })]) {
    assert.ok(tunnelToken(bad).error, bad.slice(0, 30));
    assert.ok(validate({ ...good(), publicDomain: 'example.org', cloudflareToken: bad }, options).errors.cloudflareToken);
  }
  assert.deepEqual(tunnelToken(''), { token: '' });
});

test('the logo: PNG, JPG or SVG as a data URL, not too big', () => {
  const png = 'data:image/png;base64,' + Buffer.from('not really a picture').toString('base64');
  assert.equal(readLogo(png).ext, 'png');
  assert.ok(readLogo('data:text/html;base64,PGI+').error);
  assert.ok(readLogo('data:image/png;base64,').error);
  assert.ok(readLogo('data:image/png;base64,' + Buffer.alloc(400 * 1024).toString('base64')).error);
  const r = validate({ ...good(), logo: png }, options);
  assert.ok(r.ok);
  assert.equal(r.logo.ext, 'png');
  assert.ok(validate({ ...good(), logo: 'data:text/html;base64,PGI+' }, options).errors.logo);
});
