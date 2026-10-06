// Checks of install/app/first-account.mjs with a stand-in for Supabase Auth (no network).
import test from 'node:test';
import assert from 'node:assert/strict';
import { createSignIn, waitForAuth, envValue } from '../app/first-account.mjs';

const reply = (status, body) => ({ ok: status < 300, status, json: async () => body });

test('envValue reads a name from an .env text', () => {
  assert.equal(envValue('A=1\nSERVICE_SUPABASESERVICE_KEY=eyJabc\nB=2\n', 'SERVICE_SUPABASESERVICE_KEY'), 'eyJabc');
  assert.equal(envValue('A="quoted value"\r\n', 'A'), 'quoted value');
  assert.equal(envValue('A=1\n', 'MISSING'), '');
});

test('createSignIn sends the typed details as a confirmed sign-in and returns the id', async () => {
  let seen;
  const id = await createSignIn({ base: 'http://auth/auth/v1', key: 'KEY', email: 'pat@example.org', password: 'a long password', name: 'Pat',
    fetchImpl: async (url, init) => { seen = { url, init, body: JSON.parse(init.body) }; return reply(200, { id: '6f1c0a52-3c1d-4d7e-9a53-0d3f8f2c1a10' }); } });
  assert.equal(id, '6f1c0a52-3c1d-4d7e-9a53-0d3f8f2c1a10');
  assert.equal(seen.url, 'http://auth/auth/v1/admin/users');
  assert.equal(seen.init.headers.Authorization, 'Bearer KEY');
  assert.deepEqual(seen.body, { email: 'pat@example.org', password: 'a long password', email_confirm: true, user_metadata: { display_name: 'Pat' } });
});

test('a refusal from Auth is reported in its words, without the password', async () => {
  await assert.rejects(createSignIn({ base: 'http://a', key: 'K', email: 'e@x.org', password: 'secret-password-1', name: 'N',
    fetchImpl: async () => reply(422, { msg: 'A user with this email address has already been registered' }) }),
    e => /already been registered/.test(e.message) && !e.message.includes('secret-password-1'));
  await assert.rejects(createSignIn({ base: 'http://a', key: 'K', email: 'e@x.org', password: 'p', name: 'N', fetchImpl: async () => reply(500, {}) }), /HTTP 500/);
  await assert.rejects(createSignIn({ base: 'http://a', key: 'K', email: 'e@x.org', password: 'p', name: 'N', fetchImpl: async () => reply(200, {}) }), /did not say its id/);
});

test('waitForAuth tries again until Auth answers, and gives up with a clear message', async () => {
  let calls = 0;
  await waitForAuth('http://a', 'K', { tries: 5, delay: 1, fetchImpl: async () => { calls++; if (calls < 3) throw new Error('refused'); return reply(200, {}); } });
  assert.equal(calls, 3);
  await assert.rejects(waitForAuth('http://a', 'K', { tries: 2, delay: 1, fetchImpl: async () => reply(503, {}) }), /did not answer/);
});
