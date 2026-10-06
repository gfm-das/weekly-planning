// Our own words in the 14 languages (the "gfm" part of each language file): the dashboards bar, the front's sign-in
// pages and messages, and the three dashboards' titles, chart titles, filter labels, notes and text boxes.
// Plain Node, no packages:  node --test "dataease/i18n/tests/*.test.mjs"
//  - every word those files show has a translation in every language (so nothing on them stays English);
//  - a key indicator named inside one of our titles uses that language's Preach My Gospel label;
//  - our English words are distinct and do not repeat a PMG entry (PMG has the last word on those).
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';

const dir = path.join(path.dirname(fileURLToPath(import.meta.url)), '..');
const dataease = path.join(dir, '..');
const i18n = createRequire(import.meta.url)(path.join(dir, 'gfm-i18n.js'));
const LANGS = i18n.LANGS;
const read = file => fs.readFileSync(path.join(dataease, file), 'utf8');
const files = Object.fromEntries(LANGS.map(l => [l, JSON.parse(fs.readFileSync(path.join(dir, l + '.json'), 'utf8'))]));
const en = files.en;

const decode = s => s.replace(/&amp;/g, '&').replace(/&nbsp;/g, ' ').replace(/&#39;/g, "'").replace(/&quot;/g, '"');
const hasLetters = s => /\p{L}/u.test(s);

// The pieces of text a text box shows between its tags and its live numbers ({column} in the dashboard files).
function htmlPieces(html) {
  return (html.match(/>([^<]+)</g) || []).map(m => decode(m.slice(1, -1)))
    .flatMap(t => t.split(/\{[a-z0-9_]+\}/)).map(t => t.trim()).filter(t => t && hasLetters(t));
}

/** Every English word our files put on screen. */
function ourWords() {
  const words = new Set();
  const add = t => { if (typeof t === 'string' && t.trim() && hasLetters(t)) words.add(t.trim()); };
  for (const name of ['key-indicators', 'zones-districts', 'covenant-path']) {
    const d = JSON.parse(read(`dashboards/${name}.json`));
    add(d.name);
    for (const c of d.components) {
      add(c.title); add(c.note);
      for (const y of c.y || []) add(y.label);
      if (c.value) add(c.value.label);
      for (const col of c.columns || []) add(col.label);
      for (const q of c.conditions || []) add(q.label);
      if (c.html) htmlPieces(c.html).forEach(add);
    }
  }
  // Field names DataEase shows where a chart has no display name of its own (tooltips, axis titles).
  for (const set of JSON.parse(read('dashboards/datasets.json')).datasets) for (const key of ['week', 'zone', 'district']) add(set.labels?.[key]);
  add('Mission'); // the folder, and DataEase's account name ("管理员" is shown as "Mission")
  const boot = read('web/gfm/boot.js');
  for (const s of ["'Dashboards'", "'All dashboards and Edit'"]) assert.ok(boot.includes(s), `boot.js still says ${s}`);
  add('Dashboards'); add('All dashboards and Edit');
  const backIn = /<p>(Dashboards open from the mission portal[^<]+)<\/p>/.exec(boot.replace(/' \+\s*'/g, ''));
  assert.ok(backIn, 'boot.js still has its "Dashboards open from the mission portal" page');
  add(backIn[1]);
  for (const page of ['signin.html', 'refused.html', 'starting.html']) {
    const body = read(`web/gfm/${page}`).split('<body>')[1].replace(/<!--[\s\S]*?-->/g, '');
    (body.match(/>([^<]+)</g) || []).map(m => m.slice(1, -1)).forEach(add);
  }
  for (const m of read('web/gfm/signin.js').matchAll(/(?:textContent = |\|\| )'([^']+)'/g)) add(m[1]);
  for (const json of ['signin.json', 'refused.json', 'starting.json']) add(JSON.parse(read(`web/gfm/${json}`)).msg);
  for (const m of read('web/default.conf').matchAll(/"msg":"([^"]+)"/g)) add(m[1]);
  return [...words];
}

test('every word on the dashboards bar, the sign-in pages and the three dashboards has a translation in every language', () => {
  const words = ourWords();
  assert.ok(words.length > 70, `${words.length} words found`);
  for (const lang of LANGS.filter(l => l !== 'en')) {
    const dict = i18n.buildDictionary(en, files[lang]);
    const same = new Set(['messages', 'gfm', 'pmg'].flatMap(s => Object.keys(en[s]).filter(k => files[lang][s][k] === en[s][k]).map(k => en[s][k].trim())));
    const missing = words.filter(w => i18n.translateString(dict, w) === null && !same.has(w.replace(/:$/, '').replace(/^·\s*/, '')));
    assert.deepEqual(missing, [], `${lang}: no translation`);
  }
});

test('our English words are distinct and do not repeat a Preach My Gospel entry', () => {
  const seen = new Map();
  const pmg = new Set(Object.values(en.pmg).map(v => v.toLowerCase()));
  for (const [key, value] of Object.entries(en.gfm)) {
    assert.ok(!seen.has(value), `"${value}" is both ${seen.get(value)} and ${key}`);
    seen.set(value, key);
    assert.ok(!pmg.has(value.toLowerCase()), `gfm ${key} "${value}" belongs to the pmg part`);
  }
});

test('a key indicator named in one of our titles or notes uses that language\'s PMG label', () => {
  const INDICATORS = ['indicator.friends', 'indicator.sacrament', 'indicator.dates', 'indicator.baptisms', 'indicator.members', 'indicator.newMembers'];
  for (const lang of LANGS.filter(l => l !== 'en')) {
    const p = files[lang].pmg;
    for (const [key, text] of Object.entries(en.gfm)) {
      for (const id of INDICATORS) {
        const names = Object.keys(en.pmg).filter(k => k === id || k.startsWith(id + '@')).map(k => en.pmg[k].toLowerCase());
        if (!names.some(n => text.toLowerCase().includes(n))) continue;
        // The label, or the indicator's PMG short form. "Sacrament attendance" (the English short title) may also be
        // said with PMG's "sacrament meeting" in any grammatical form (every word of it, by its first 4 letters).
        const accepted = [p[id], p[id + '.short']].filter(Boolean).map(s => s.toLowerCase());
        const translated = files[lang].gfm[key].toLowerCase();
        const meeting = id === 'indicator.sacrament' && p['term.sacramentMeeting'].toLowerCase().split(/\s+/).every(w => translated.includes(w.slice(0, 4)));
        assert.ok(meeting || accepted.some(a => translated.includes(a)), `${lang} gfm ${key}: "${files[lang].gfm[key]}" should name ${id} as "${p[id]}"`);
      }
    }
  }
});

test('our translations keep numbers and the % sign where the English has them, and are not empty', () => {
  for (const lang of LANGS.filter(l => l !== 'en')) {
    for (const [key, text] of Object.entries(en.gfm)) {
      const out = files[lang].gfm[key];
      assert.ok(out && out.trim(), `${lang} ${key} is empty`);
      for (const n of text.match(/\d+/g) || []) assert.ok(out.includes(n) || /[۰-۹]/.test(out), `${lang} ${key}: the number ${n}`);
      if (text.includes('%')) assert.ok(/[%٪]/.test(out) || /(درصد|نسبة مئوية|yüzde)/.test(out), `${lang} ${key}: the % sign`);
    }
  }
});

test('names fit DataEase: dashboard names, chart titles and filter labels have at most 100 characters', () => {
  // DataEase refuses to save a chart or component whose name is longer ("Name cannot exceed 100 characters").
  const titles = ['dash.', 'zd.npbt', 'zd.sa', 'zd.table', 'cp.newMembersAtChurch', 'cp.nextSteps', 'cp.highPotential', 'word.'];
  for (const lang of LANGS) {
    for (const [key, text] of Object.entries(files[lang].gfm)) {
      if (titles.some(t => key.startsWith(t)) && !key.includes('note')) assert.ok(text.length <= 100, `${lang} gfm ${key} has ${text.length} characters`);
    }
    for (const [key, text] of Object.entries(files[lang].pmg)) assert.ok(text.length <= 100, `${lang} pmg ${key} has ${text.length} characters`);
  }
});
