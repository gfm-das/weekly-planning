// Checks of the Mission drive page (portal/drive.html) and its setting (round 13, task 18). No network, no Google.
// Run: node portal/tests/drive-check.cjs
// 1. The drive's ID is a setting, never written in the code: not in drive.html, site-config.js, deploy.sh, the installer or the catalogs.
// 2. The setting travels: portal/.env (GFM_DRIVE_ID) -> deploy.sh -> site-config.js (driveId) -> the page; the installer writes it.
// 3. The page's own script, run against a tiny stand-in for the browser: valid ID, empty ID, an ID with bad characters.
// 4. The texts are in all 14 catalogs, and the English texts in the page are the catalog's.
const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const ROOT = path.join(__dirname, '..', '..');
const read = (...p) => fs.readFileSync(path.join(ROOT, ...p), 'utf8');
const html = read('portal', 'drive.html');
const TEST_ID = '0Atestdrive1234567AB';   // made up; the real ID is only ever a setting

// 1. nothing hard-coded: no drive address with an ID in the sources, no long ID-like token after /folders/ or id=
for (const file of [['portal', 'drive.html'], ['portal', 'site-config.js'], ['portal', 'deploy.sh'], ['install', 'app', 'validate.mjs'], ['install', 'app', 'generate.mjs'], ['install', 'app', 'cli.mjs']]) {
  const text = read(...file);
  assert.ok(!/folders\/[A-Za-z0-9_-]{10,}/.test(text), file.join('/') + ': a drive ID is written in the code');
  assert.ok(!/[?&]id=[A-Za-z0-9_-]{10,}/.test(text), file.join('/') + ': a drive ID is written in the code');
}
assert.ok(/driveId: ""/.test(read('portal', 'site-config.js')), 'site-config.js default has an empty driveId');

// 2. the setting travels
const deploy = read('portal', 'deploy.sh');
assert.ok(/GFM_DRIVE_ID/.test(deploy) && /driveId: "%s"/.test(deploy), 'deploy.sh writes driveId to site-config.js');
assert.ok(/A-Za-z0-9_-\]\{10,64\}/.test(deploy), 'deploy.sh checks the ID');
assert.ok(/GFM_DRIVE_ID/.test(read('portal', '.env.example')), 'portal/.env.example documents GFM_DRIVE_ID');
(async () => {
  const { validate } = await import(path.join(ROOT, 'install', 'app', 'validate.mjs').replace(/\\/g, '/').replace(/^([A-Za-z]):/, 'file:///$1:'));
  const { buildEnvFiles } = await import(path.join(ROOT, 'install', 'app', 'generate.mjs').replace(/\\/g, '/').replace(/^([A-Za-z]):/, 'file:///$1:'));
  const options = { languages: ['en', 'de'], timeZones: ['UTC', 'Europe/Berlin'] };
  const base = { missionName: 'Testland Mission', missionCode: 'TM', language: 'en', admin: { name: 'Pat', email: 'pat@example.org', password: 'x'.repeat(12) }, timeZone: 'UTC' };
  assert.strictEqual(validate(base, options).answers.driveId, '', 'optional');
  assert.strictEqual(validate({ ...base, driveId: ' ' + TEST_ID + ' ' }, options).answers.driveId, TEST_ID);
  assert.strictEqual(validate({ ...base, driveId: 'https://drive.google.com/drive/folders/' + TEST_ID + '?usp=sharing' }, options).answers.driveId, TEST_ID, 'a pasted folder address is reduced to the ID');
  const bad = validate({ ...base, driveId: 'not an id!' }, options);
  assert.ok(!bad.ok && bad.errors.driveId, 'bad characters are refused');
  const files = buildEnvFiles(validate({ ...base, driveId: TEST_ID }, options).answers).files;
  assert.ok(files['portal/.env'].split('\n').includes('GFM_DRIVE_ID=' + TEST_ID), 'portal/.env gets GFM_DRIVE_ID');
  assert.ok(buildEnvFiles(validate(base, options).answers).files['portal/.env'].split('\n').includes('GFM_DRIVE_ID='), 'empty by default');

  // 3. the page script
  const script = html.match(/<script>\s*([\s\S]*?)<\/script>\s*<\/body>/)[1];
  function run(driveId) {
    const els = {};
    const make = (id) => els[id] || (els[id] = {
      id, hidden: id === 'frame', textContent: '', href: '', attrs: {}, listeners: {},
      addEventListener(type, fn) { this.listeners[type] = fn; },
      setAttribute(k, v) { this.attrs[k] = String(v); }, getAttribute(k) { return this.attrs[k] || null; },
    });
    const docListeners = {};
    const written = [];
    const context = {
      window: { GFM_SITE: driveId === undefined ? {} : { driveId }, MissionI18n: { t: (k) => k } },
      document: { getElementById: make, addEventListener: (t, f) => { docListeners[t] = f; } },
      navigator: { clipboard: { writeText: async (t) => { written.push(t); } } },
      encodeURIComponent,
    };
    ['notset', 'ready', 'badge', 'open', 'browse', 'copy', 'frame', 'status'].forEach(make);
    els.notset.hidden = true; els.ready.hidden = true; els.badge.hidden = true;
    vm.runInNewContext(script, context);
    return { els, written, docListeners };
  }
  let page = run(TEST_ID);
  assert.strictEqual(page.els.ready.hidden, false); assert.strictEqual(page.els.notset.hidden, true);
  assert.strictEqual(page.els.open.href, 'https://drive.google.com/drive/folders/' + TEST_ID);
  assert.strictEqual(page.els.frame.getAttribute('src'), null, 'nothing is loaded from Google until "Show the files here" is pressed');
  page.els.browse.listeners.click();
  assert.strictEqual(page.els.frame.hidden, false);
  assert.strictEqual(page.els.frame.getAttribute('src'), 'https://drive.google.com/embeddedfolderview?id=' + TEST_ID + '#list');
  assert.strictEqual(page.els.browse.textContent, 'drive.hide');
  assert.strictEqual(page.els.browse.getAttribute('aria-expanded'), 'true');
  page.els.browse.listeners.click();
  assert.strictEqual(page.els.frame.hidden, true); assert.strictEqual(page.els.browse.textContent, 'drive.browse');
  await page.els.copy.listeners.click();
  assert.deepStrictEqual(page.written, ['https://drive.google.com/drive/folders/' + TEST_ID]);
  assert.strictEqual(page.els.status.textContent, 'drive.copied');
  for (const wrong of [undefined, '', '   ', 'x', 'a b c d e f g h i j', '../../evil"onload=x', 'a'.repeat(65)]) {
    page = run(wrong);
    assert.strictEqual(page.els.notset.hidden, false, 'not set up: ' + JSON.stringify(wrong));
    assert.strictEqual(page.els.ready.hidden, true);
    assert.strictEqual(page.els.open.href, '');
  }

  // 4. the texts
  const keys = ['title', 'intro', 'badge', 'notSet', 'open', 'browse', 'hide', 'copy', 'copied', 'hint', 'frameTitle'].map((k) => 'drive.' + k);
  const codes = JSON.parse(read('portal', 'i18n', 'catalogs.json'));
  const list = Object.keys(codes.languages);
  assert.strictEqual(list.length, 14, 'fourteen languages');
  const en = JSON.parse(read('portal', 'i18n', 'en.json'));
  for (const code of list) {
    const cat = JSON.parse(read('portal', 'i18n', code + '.json'));
    for (const k of keys) assert.ok(typeof cat[k] === 'string' && cat[k].length > 2, code + ' lacks ' + k);
    if (code !== 'en') assert.notStrictEqual(cat['drive.intro'], en['drive.intro'], code + ': drive.intro is still English');
    assert.ok(!/0A[A-Za-z0-9_-]{15,}/.test(cat['drive.hint'] + cat['drive.intro']), code + ': an ID in a text');
  }
  // the English words of the page are the catalog's (i18n.js swaps a text that equals an English catalog text)
  const visible = [
    ['<h1>', '</h1>', 'drive.title'], ['<p class="muted">', '</p>', 'drive.intro'], ['id="badge" hidden>', '</span>', 'drive.badge'],
    ['id="notset" class="notice" hidden>', '</div>', 'drive.notSet'], ['rel="noopener noreferrer">', '</a>', 'drive.open'], ['aria-controls="frame">', '</button>', 'drive.browse'],
    ['id="copy">', '</button>', 'drive.copy'], ['<p class="muted" id="hint">', '</p>', 'drive.hint'],
  ];
  for (const [a, b, key] of visible) {
    const i = html.indexOf(a); assert.ok(i >= 0, 'page lacks ' + a);
    const text = html.slice(i + a.length, html.indexOf(b, i + a.length)).trim();
    assert.strictEqual(text, en[key], key + ' differs from the page text');
  }
  assert.ok(html.includes('title="' + en['drive.frameTitle'] + '"'), 'frame title');
  assert.ok(html.includes('<title>' + en['drive.title'] + '</title>'));
  console.log('drive-check: passed (setting, page script, 14 catalogs)');
})().catch((error) => { console.error(error); process.exit(1); });
