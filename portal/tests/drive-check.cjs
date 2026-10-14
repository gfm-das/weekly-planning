// Round 14: Mission drive is a sidebar hyperlink (new tab), not a portal page. No network, no Google.
// Run: node portal/tests/drive-check.cjs
const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const ROOT = path.join(__dirname, '..', '..');
const read = (...p) => fs.readFileSync(path.join(ROOT, ...p), 'utf8');

assert.ok(!fs.existsSync(path.join(ROOT, 'portal', 'drive.html')), 'drive.html is gone (Mission drive is not a page)');

// 1. nothing hard-coded: no drive address with an ID in the sources
for (const file of [['portal', 'portal-enhancements.js'], ['portal', 'site-config.js'], ['portal', 'deploy.sh'],
                    ['install', 'app', 'validate.mjs'], ['install', 'app', 'generate.mjs'], ['install', 'app', 'cli.mjs']]) {
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

// 3. the shell builds a new-tab link when the ID is set, and hides it when empty
const shell = read('portal', 'portal-enhancements.js');
assert.ok(/function missionDriveUrl\(/.test(shell) && /function menuLink\(/.test(shell), 'shell: missionDriveUrl and menuLink');
assert.ok(/menuLink\('navDrive', 'Mission drive'/.test(shell) || /menuLink\('navDrive'/.test(shell), 'shell: Mission drive uses menuLink');
assert.ok(!/URLS\.drive\s*=/.test(shell), 'shell: no drive page URL');
assert.ok(!/'drive'/.test(shell.match(/const pages = \[([^\]]+)\]/)[1]), 'shell: drive is not an in-frame page');

function driveUrl(driveId) {
  const context = { window: { GFM_SITE: { driveId } }, encodeURIComponent };
  return vm.runInNewContext(`(${shell.match(/function missionDriveUrl\(\) \{[\s\S]*?\n    \}/)[0]})()`, context);
}
assert.strictEqual(driveUrl(''), '');
assert.strictEqual(driveUrl('bad id!'), '');
assert.strictEqual(driveUrl('0Atestdrive1234567AB'), 'https://drive.google.com/drive/folders/0Atestdrive1234567AB');

// 4. catalogs still have the Mission drive label (menu text)
const en = JSON.parse(read('portal', 'i18n', 'en.json'));
assert.ok(Object.values(en).includes('Mission drive'), 'en catalog has Mission drive');
const catalogs = Object.keys(JSON.parse(read('portal', 'i18n', 'catalogs.json')).languages);
for (const code of catalogs) {
  const c = JSON.parse(read('portal', 'i18n', `${code}.json`));
  const key = Object.keys(en).find(k => en[k] === 'Mission drive');
  assert.ok(key && String(c[key] || '').trim(), `${code}: Mission drive translated`);
}

console.log('drive-check: passed (sidebar link, setting, no page, 14 catalogs)');
