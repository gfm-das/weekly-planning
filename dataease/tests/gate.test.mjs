// The sign-in gate in front of DataEase (dataease/gate/gate.mjs): the portal's cookie, DataEase's own sign-in and
// what nginx gets back. Plain Node 24, no network (DataEase is a stand-in).
//   docker run --rm -v <repo>/dataease:/d -w /d node:24-alpine node --test tests/
import assert from 'node:assert/strict';
import http from 'node:http';
import { test } from 'node:test';
import { COOKIE_NAME, Keeper, changeLine, cookieValue, handler, isPhone, sign, signingKey, startTarget, tokenExpiry, verify } from '../gate/gate.mjs';
import { DataEaseError } from '../lib/dataease-client.mjs';

const KEY = Buffer.from('k'.repeat(40));
const NOW = 1_790_000_000_000;
// The same example as portal-api/tests/test_dataease_auth.py: portal-api signs, the gate must accept it.
const VECTOR_IDENTITY = { sub: '6f1c0a52-3c1d-4d7e-9a53-0d3f8f2c1a10', exp: 1_790_000_900 };
const VECTOR = 'eyJleHAiOjE3OTAwMDA5MDAsInN1YiI6IjZmMWMwYTUyLTNjMWQtNGQ3ZS05YTUzLTBkM2Y4ZjJjMWExMCJ9.kqW8zu3RZA_ONlKm09zZfSVPOil9hVF2CyFgBTnb8tU';

test('the gate accepts exactly what portal-api signs (shared example)', () => {
  assert.equal(sign(VECTOR_IDENTITY, KEY), VECTOR);
  assert.deepEqual(verify(VECTOR, KEY, NOW), VECTOR_IDENTITY);
  assert.deepEqual(verify(VECTOR, KEY, NOW + 899_000), VECTOR_IDENTITY);
});

test('expired, forged, foreign and malformed cookies are refused', () => {
  assert.equal(verify(VECTOR, KEY, NOW + 900_000), null, 'expired');
  assert.equal(verify(VECTOR, Buffer.from('another-secret-of-sufficient-length!!'), NOW), null, 'other secret');
  const [body, mac] = VECTOR.split('.');
  const longer = Buffer.from(JSON.stringify({ ...VECTOR_IDENTITY, exp: VECTOR_IDENTITY.exp + 1e6 })).toString('base64url');
  assert.equal(verify(`${longer}.${mac}`, KEY, NOW), null, 'changed body');
  assert.equal(verify(`${body}.${mac.slice(0, -1)}${mac.endsWith('A') ? 'B' : 'A'}`, KEY, NOW), null, 'changed signature');
  for (const bad of [undefined, null, '', '.', 'abc', 'a.b.c', 'ä.ö', 'x'.repeat(5000), '!!!.???', 123, `${body}.`, `.${mac}`]) {
    assert.equal(verify(bad, KEY, NOW), null, String(bad).slice(0, 20));
  }
  for (const payload of [[1, 2], 'text', { ...VECTOR_IDENTITY, exp: '1790000900' }, { ...VECTOR_IDENTITY, exp: true },
    { ...VECTOR_IDENTITY, exp: 1.5e9 + 0.5 }, { ...VECTOR_IDENTITY, sub: '' }, { ...VECTOR_IDENTITY, sub: 5 }, { exp: VECTOR_IDENTITY.exp }]) {
    const value = sign(payload, KEY);
    assert.equal(verify(value, KEY, NOW), null, JSON.stringify(payload));
  }
});

test('the cookie is found among others, by its exact name', () => {
  assert.equal(cookieValue(`a=1; ${COOKIE_NAME}=${VECTOR}; b=2`), VECTOR);
  assert.equal(cookieValue(`${COOKIE_NAME}x=1; x${COOKIE_NAME}=2`), '');
  assert.equal(cookieValue(''), '');
  assert.equal(cookieValue(undefined), '');
  assert.equal(cookieValue(`${COOKIE_NAME}=first; ${COOKIE_NAME}=second`), 'first');
});

test('a missing, short or example secret stops the gate', () => {
  for (const value of [undefined, '', 'x'.repeat(31), 'REPLACE_WITH_GENERATED_VALUE', 'replace' + 'x'.repeat(40)]) {
    assert.throws(() => signingKey(value), /at least 32/);
  }
  assert.deepEqual(signingKey('x'.repeat(32)), Buffer.from('x'.repeat(32)));
});

const jwt = claims => `${Buffer.from('{"alg":"HS256"}').toString('base64url')}.${Buffer.from(JSON.stringify(claims)).toString('base64url')}.sig`;

test('tokenExpiry reads DataEase\'s JWT', () => {
  assert.equal(tokenExpiry(jwt({ uid: 1, exp: 1_790_172_800 })), 1_790_172_800_000);
  assert.equal(tokenExpiry(jwt({ uid: 1 })), null);
  assert.equal(tokenExpiry('garbage'), null);
});

// A stand-in for DataEase's API as the client sees it.
const TREE = [{ id: '0', name: 'root', leaf: false, children: [
  { id: '1150000000000001000', name: 'Mission', leaf: false, children: [
    { id: '1150000000000001003', name: 'Covenant path', leaf: true },
    { id: '1150000000000101001', name: 'Key indicators', leaf: true },
  ] },
  { id: '1302133453109727232', name: 'Key indicators', leaf: true },
] }];

function fakeDataEase({ password = 'Secret-pass1', expSeconds = NOW / 1000 + 48 * 3600, tree = TREE } = {}) {
  const state = { password, logins: 0, infos: 0, changed: 0, valid: new Set(), reachable: true, tree, trees: 0 };
  const client = () => ({
    token: null,
    async login(pwd) {
      if (!state.reachable) throw new TypeError('fetch failed');
      if (pwd !== state.password) throw new DataEaseError('POST /login/localLogin: wrong name or password');
      state.logins += 1;
      this.token = jwt({ uid: 1, oid: 1, exp: expSeconds, n: state.logins });
      state.valid.add(this.token);
      return this;
    },
    async raw(path, { token }) {
      if (path === '/dataVisualization/tree') {
        state.trees += 1;
        return state.valid.has(token) ? { status: 200, json: { code: 0, data: state.tree } } : { status: 401, json: { code: 401 } };
      }
      state.infos += 1;
      return state.valid.has(token) ? { status: 200, json: { code: 0 } } : { status: 401, json: { code: 401 } };
    },
    async publicKey() {
      const { publicKey } = (await import('node:crypto')).generateKeyPairSync('rsa', { modulusLength: 1024 });
      return publicKey.export({ type: 'spki', format: 'pem' });
    },
    async post(path) {
      assert.equal(path, '/user/modifyPwd');
      state.changed += 1;
      state.password = 'Secret-pass1';
      state.valid.clear();
    },
  });
  return { state, client };
}

test('the keeper signs in once, reuses the sign-in, checks it every few minutes and signs in again when it ends', async () => {
  let now = NOW;
  const { state, client } = fakeDataEase();
  const logs = [];
  const keeper = new Keeper({ base: 'http://dataease:8100', password: 'Secret-pass1', client, now: () => now, log: m => logs.push(m) });
  const first = await keeper.getToken();
  assert.equal(state.logins, 1);
  assert.equal(await keeper.getToken(), first, 'reused');
  assert.equal(state.infos, 0, 'no check within the first minutes');
  const [a, b] = await Promise.all([keeper.getToken(), keeper.getToken()]);
  assert.equal(a, b);
  now += 4 * 60 * 1000;
  assert.equal(await keeper.getToken(), first, 'still accepted after a check');
  assert.equal(state.infos, 1);
  state.valid.clear(); // DataEase restarted with another secret, or someone ended the sign-in
  now += 4 * 60 * 1000;
  const second = await keeper.getToken();
  assert.notEqual(second, first);
  assert.equal(state.logins, 2);
  now = NOW + 47.5 * 3600 * 1000; // less than an hour before DataEase's sign-in ends
  await keeper.getToken();
  assert.equal(state.logins, 3, 'signed in again before it ran out');
  assert.equal(keeper.status().dataease, 'signed-in');
  assert.ok(logs.every(line => !line.includes('Secret-pass1') && !line.includes(first)), 'no password or token in the log');
});

test('first start: the keeper replaces DataEase\'s published default password, and only that one', async () => {
  const { state, client } = fakeDataEase({ password: 'DataEase@123456' });
  const logs = [];
  const keeper = new Keeper({ base: 'x', password: 'Secret-pass1', client, now: () => NOW, log: m => logs.push(m) });
  await keeper.getToken();
  assert.equal(state.changed, 1);
  assert.equal(state.password, 'Secret-pass1');
  assert.ok(logs.some(line => line.includes('default password was replaced')));

  const other = fakeDataEase({ password: 'Someone-Else9' });
  const refused = new Keeper({ base: 'x', password: 'Secret-pass1', client: other.client, now: () => NOW, log: () => {} });
  await assert.rejects(refused.getToken(), /refused the password in dataease\/.env/);
  assert.equal(other.state.changed, 0);
  assert.equal(refused.status().dataease, 'not-signed-in');
});

test('DataEase not reachable: the keeper says so and tries again on the next request', async () => {
  const { state, client } = fakeDataEase();
  state.reachable = false;
  const keeper = new Keeper({ base: 'x', password: 'Secret-pass1', client, now: () => NOW, log: () => {} });
  await assert.rejects(keeper.getToken(), /cannot be reached yet/);
  assert.match(keeper.status().problem, /cannot be reached/);
  state.reachable = true;
  assert.ok(await keeper.getToken());
  assert.equal(keeper.status().problem, null);
});

async function serve(keeper, lines = []) {
  const server = http.createServer(handler({ key: KEY, keeper, log: line => lines.push(line) }));
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const base = `http://127.0.0.1:${server.address().port}`;
  return { base, close: () => new Promise(resolve => server.close(resolve)) };
}

test('what nginx gets: 200 with DataEase\'s sign-in for a valid cookie, 401 otherwise, 503 while DataEase is away', async () => {
  const { state, client } = fakeDataEase();
  const keeper = new Keeper({ base: 'x', password: 'Secret-pass1', client, log: () => {} });
  const { base, close } = await serve(keeper);
  try {
    const good = sign({ sub: 'u-ap', exp: Math.floor(Date.now() / 1000) + 600 }, KEY);
    const ok = await fetch(`${base}/check`, { headers: { cookie: `other=1; ${COOKIE_NAME}=${good}` } });
    assert.equal(ok.status, 200);
    assert.ok(state.valid.has(ok.headers.get('x-de-token')), 'DataEase\'s current sign-in');
    assert.equal(ok.headers.get('cache-control'), 'no-store');
    for (const headers of [{}, { cookie: `${COOKIE_NAME}=abc.def` },
      { cookie: `${COOKIE_NAME}=${sign({ sub: 'u-ap', exp: Math.floor(Date.now() / 1000) - 1 }, KEY)}` },
      { cookie: `${COOKIE_NAME}=${sign({ sub: 'u-ap', exp: Math.floor(Date.now() / 1000) + 600 }, Buffer.from('z'.repeat(40)))}` },
      { 'x-de-token': 'anything' }]) {
      const refused = await fetch(`${base}/check`, { headers });
      assert.equal(refused.status, 401, JSON.stringify(headers).slice(0, 40));
      assert.equal(refused.headers.get('x-de-token'), null);
    }
    assert.equal((await fetch(`${base}/check`, { method: 'POST', headers: { cookie: `${COOKIE_NAME}=${good}` } })).status, 405);
    assert.equal((await fetch(`${base}/elsewhere`)).status, 404);
    const health = await fetch(`${base}/health`);
    assert.equal(health.status, 200);
    const body = await health.json();
    assert.equal(body.dataease, 'signed-in');
    assert.ok(!JSON.stringify(body).includes(state.valid.values().next().value), 'no token in the health answer');
    assert.equal((await fetch(`${base}/alive`)).status, 200);

    state.reachable = false;
    state.valid.clear();
    keeper.checkedAt = 0;
    const away = await fetch(`${base}/check`, { headers: { cookie: `${COOKIE_NAME}=${good}` } });
    assert.equal(away.status, 503);
    assert.equal((await fetch(`${base}/health`)).status, 503);
  } finally {
    await close();
  }
});

test('the start address: "Key indicators" in the folder "Mission", else its first dashboard, else the list', () => {
  assert.equal(startTarget(TREE), '/#/preview?dvId=1150000000000101001', 'a computer: the dashboard alone, on the preview page of DataEase');
  const renamed = JSON.parse(JSON.stringify(TREE));
  renamed[0].children[0].children[1].name = 'Key indicators (old)';
  assert.equal(startTarget(renamed), '/#/preview?dvId=1150000000000001003');
  assert.equal(startTarget([{ id: '0', name: 'root', leaf: false, children: [{ id: '5', name: 'Mission', leaf: false, children: null }] }]), '/#/panel/index');
  assert.equal(startTarget(null), '/#/panel/index');
  const odd = JSON.parse(JSON.stringify(TREE));
  odd[0].children[0].children = [{ id: 'javascript:alert(1)', name: 'Key indicators', leaf: true }];
  assert.equal(startTarget(odd), '/#/panel/index', 'only a numeric id goes into the address');
  assert.equal(startTarget(TREE, true), '/mobile.html#/panel/mobile?dvId=1150000000000101001', 'a phone gets the phone page of DataEase');
});

test('phones are told apart from computers and tablets as DataEase does', () => {
  const iphone = 'Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1';
  const android = 'Mozilla/5.0 (Linux; Android 15; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Mobile Safari/537.36';
  const ipad = 'Mozilla/5.0 (iPad; CPU OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1';
  const androidTablet = 'Mozilla/5.0 (Linux; Android 15; SM-X710) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36';
  const windows = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36 Edg/140.0';
  assert.equal(isPhone(iphone), true);
  assert.equal(isPhone(android), true);
  assert.equal(isPhone(ipad), false);
  assert.equal(isPhone(androidTablet), false);
  assert.equal(isPhone(windows), false);
  assert.equal(isPhone(undefined), false);
});

test('/start sends a signed-in manager on to the start dashboard; without the cookie 401', async () => {
  const { state, client } = fakeDataEase();
  const keeper = new Keeper({ base: 'x', password: 'Secret-pass1', client, log: () => {} });
  const { base, close } = await serve(keeper);
  try {
    const good = sign({ sub: 'u-ap', exp: Math.floor(Date.now() / 1000) + 600 }, KEY);
    const moved = await fetch(`${base}/start`, { headers: { cookie: `${COOKIE_NAME}=${good}` }, redirect: 'manual' });
    assert.equal(moved.status, 302);
    assert.equal(moved.headers.get('location'), '/#/preview?dvId=1150000000000101001');
    assert.equal(moved.headers.get('x-de-token'), null, 'the sign-in of DataEase never goes to the browser');
    assert.equal((await fetch(`${base}/start`, { redirect: 'manual' })).status, 401);
    state.tree = null;
    const fallback = await fetch(`${base}/start`, { headers: { cookie: `${COOKIE_NAME}=${good}` }, redirect: 'manual' });
    assert.equal(fallback.headers.get('location'), '/#/panel/index');
  } finally {
    await close();
  }
});

test('changes are written to the gate log with the portal user id only; reads are not', async () => {
  const who = { sub: 'u-ap-1', exp: 1 };
  assert.equal(changeLine('POST', '/de2api/dataVisualization/updateCanvas', who), 'Change by portal user u-ap-1: POST /de2api/dataVisualization/updateCanvas');
  assert.equal(changeLine('POST', '/de2api/datasetTree/save?x=1', who), 'Change by portal user u-ap-1: POST /de2api/datasetTree/save');
  assert.equal(changeLine('POST', '/de2api/chartData/getData', who), null, 'a read that uses POST');
  assert.equal(changeLine('POST', '/de2api/dataVisualization/tree', who), null);
  assert.equal(changeLine('GET', '/de2api/datasource/delete/12', who), 'Change by portal user u-ap-1: GET /de2api/datasource/delete/12', 'DataEase deletes a data source with GET');
  assert.equal(changeLine('GET', '/de2api/dataVisualization/findById', who), null);
  assert.equal(changeLine(undefined, '/de2api/x/save', who), null);
  const { client } = fakeDataEase();
  const lines = [];
  const keeper = new Keeper({ base: 'x', password: 'Secret-pass1', client, log: () => {} });
  const { base, close } = await serve(keeper, lines);
  try {
    const good = sign({ sub: 'u-ap-2', exp: Math.floor(Date.now() / 1000) + 600 }, KEY);
    await fetch(`${base}/check`, { headers: { cookie: `${COOKIE_NAME}=${good}`, 'x-original-method': 'POST', 'x-original-uri': '/de2api/dataVisualization/updateCanvas' } });
    await fetch(`${base}/check`, { headers: { cookie: `${COOKIE_NAME}=${good}`, 'x-original-method': 'POST', 'x-original-uri': '/de2api/chartData/getData' } });
    await fetch(`${base}/start`, { headers: { cookie: `${COOKIE_NAME}=${good}` }, redirect: 'manual' });
    assert.deepEqual(lines, ['Change by portal user u-ap-2: POST /de2api/dataVisualization/updateCanvas', 'Dashboards opened by portal user u-ap-2.']);
  } finally {
    await close();
  }
});

// Languages (dataease/lib/languages.mjs): the ids of seed-dashboards.mjs, and the copies translate-dashboards.mjs makes
// in the language folders inside "Mission" (German = 01, Arabic = 13).
const LANG_TREE = [{ id: '0', name: 'root', leaf: false, children: [
  { id: '1150000000000000000', name: 'Mission', leaf: false, children: [
    { id: '1150100000000000000', name: 'Deutsch', leaf: false, children: [
      { id: '1150101000000000000', name: 'Hauptindikatoren', leaf: true },
      { id: '1150103000000000000', name: 'Weg der Bündnisse', leaf: true },
    ] },
    { id: '1151300000000000000', name: 'العربية', leaf: false, children: [
      { id: '1151301010000000000', name: 'المؤشرات الرئيسة', leaf: true }, // a later generation (01)
    ] },
    { id: '1150001000000000000', name: 'Key indicators', leaf: true },
    { id: '1150003000000000000', name: 'Covenant path', leaf: true },
  ] },
] }];

test('languages: /start opens the copy in the viewer\'s language when there is one, and passes the language on', () => {
  assert.equal(startTarget(LANG_TREE), '/#/preview?dvId=1150001000000000000', 'no language: English, as before');
  assert.equal(startTarget(LANG_TREE, false, 'en'), '/?gfmLang=en#/preview?dvId=1150001000000000000');
  assert.equal(startTarget(LANG_TREE, false, 'de'), '/?gfmLang=de#/preview?dvId=1150101000000000000', 'German: the German copy');
  assert.equal(startTarget(LANG_TREE, false, 'de-AT'), '/?gfmLang=de#/preview?dvId=1150101000000000000');
  assert.equal(startTarget(LANG_TREE, true, 'ar'), '/mobile.html?gfmLang=ar#/panel/mobile?dvId=1151301010000000000', 'Arabic on a phone: any generation of the copy');
  assert.equal(startTarget(LANG_TREE, false, 'fr'), '/?gfmLang=fr#/preview?dvId=1150001000000000000', 'no French copy yet: English, with French words around it');
  assert.equal(startTarget(LANG_TREE, false, 'xx'), '/#/preview?dvId=1150001000000000000', 'an unknown language is ignored');
  assert.equal(startTarget(LANG_TREE, false, 'de"><script>'), '/#/preview?dvId=1150001000000000000', 'nothing odd goes into the address');
  assert.equal(startTarget(null, false, 'de'), '/?gfmLang=de#/panel/index');
  // The copies are never taken for the English start dashboard, even when "Key indicators" is gone.
  const noEnglish = JSON.parse(JSON.stringify(LANG_TREE));
  noEnglish[0].children[0].children = noEnglish[0].children[0].children.filter(n => n.name !== 'Key indicators');
  assert.equal(startTarget(noEnglish, false, 'en'), '/?gfmLang=en#/preview?dvId=1150003000000000000');
  assert.equal(startTarget(noEnglish, false, 'de'), '/?gfmLang=de#/preview?dvId=1150103000000000000');
});

test('languages: /start reads ?gfmLang= (nginx passes it on) and answers with the copy', async () => {
  const { client } = fakeDataEase({ tree: LANG_TREE });
  const keeper = new Keeper({ base: 'x', password: 'Secret-pass1', client, log: () => {} });
  const { base, close } = await serve(keeper);
  try {
    const good = sign({ sub: 'u-ap', exp: Math.floor(Date.now() / 1000) + 600 }, KEY);
    const de = await fetch(`${base}/start?gfmLang=de`, { headers: { cookie: `${COOKIE_NAME}=${good}` }, redirect: 'manual' });
    assert.equal(de.headers.get('location'), '/?gfmLang=de#/preview?dvId=1150101000000000000');
    const en = await fetch(`${base}/start?gfmLang=en`, { headers: { cookie: `${COOKIE_NAME}=${good}` }, redirect: 'manual' });
    assert.equal(en.headers.get('location'), '/?gfmLang=en#/preview?dvId=1150001000000000000');
    assert.equal((await fetch(`${base}/start?gfmLang=de`, { redirect: 'manual' })).status, 401, 'the language changes nothing about the sign-in');
  } finally {
    await close();
  }
});
