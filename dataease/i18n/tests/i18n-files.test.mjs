// Checks of the 14 language files: valid JSON, every key of en.json, no empty values, placeholders kept, and the
// official Preach My Gospel wording for the key indicators. Plain Node, no packages:
//   node --test "dataease/i18n/tests/*.test.mjs"
// The PMG wording is read from pmg-terms.json: $GFM_PMG_TERMS, else the first one found next to or above the
// repository (/path/to\gfm-worktrees\pmg-terms.json on the build machine).
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const dir = path.join(path.dirname(fileURLToPath(import.meta.url)), '..');
const repo = path.join(dir, '..', '..');
const LANGS = ['en', 'de', 'es', 'fr', 'pt', 'uk', 'ru', 'it', 'tr', 'fa', 'ro', 'sv', 'da', 'ar'];
const INDICATORS = ['indicator.friends', 'indicator.sacrament', 'indicator.dates', 'indicator.baptisms', 'indicator.members', 'indicator.newMembers'];

const files = {};
for (const lang of LANGS) {
  const text = fs.readFileSync(path.join(dir, lang + '.json'), 'utf8');
  try { files[lang] = JSON.parse(text); } catch (e) { files[lang] = e; }
}
const en = files.en;
const tokens = s => [...(s.match(/\{[^{}]*\}/g) || []), ...(s.match(/%s/g) || []), ...(s.match(/<\/?[a-z][^>]*>/gi) || [])].sort().join(' ');

const pmgPath = [process.env.GFM_PMG_TERMS, path.join(repo, 'pmg-terms.json'), path.join(repo, '..', 'pmg-terms.json'), path.join(repo, '..', 'gfm-worktrees', 'pmg-terms.json')]
  .filter(Boolean).find(p => fs.existsSync(p));
const pmgTerms = pmgPath ? JSON.parse(fs.readFileSync(pmgPath, 'utf8')).terms : null;

test('all 14 language files exist and are valid JSON with _meta, pmg, gfm and messages', () => {
  for (const lang of LANGS) {
    const f = files[lang];
    assert.ok(!(f instanceof Error), `${lang}.json: ${f && f.message}`);
    assert.equal(f._meta.language, lang);
    assert.equal(f._meta.dir, lang === 'fa' || lang === 'ar' ? 'rtl' : 'ltr');
    assert.equal(typeof f.pmg, 'object');
    assert.equal(typeof f.gfm, 'object');
    assert.equal(typeof f.messages, 'object');
  }
});

test('every language file has every key of en.json, nothing more, and no empty value', () => {
  for (const section of ['messages', 'pmg', 'gfm']) {
    const keys = Object.keys(en[section]);
    assert.ok(keys.length > (section === 'messages' ? 1000 : 20), `${section}: ${keys.length} keys`);
    for (const lang of LANGS) {
      const s = files[lang][section];
      const missing = keys.filter(k => typeof s[k] !== 'string' || !s[k].trim());
      const extra = Object.keys(s).filter(k => !(k in en[section]));
      assert.deepEqual(missing, [], `${lang}.json ${section}: missing or empty`);
      assert.deepEqual(extra, [], `${lang}.json ${section}: not in en.json`);
    }
  }
});

test('placeholders and markup are kept, and no Chinese is left', () => {
  for (const lang of LANGS) {
    const bad = Object.entries(en.messages).filter(([k, v]) => tokens(files[lang].messages[k]) !== tokens(v)).map(([k]) => k);
    assert.deepEqual(bad, [], `${lang}.json: placeholders differ`);
    const han = Object.entries(files[lang].messages).filter(([, v]) => /[\u4e00-\u9fff]/.test(v)).map(([k]) => k);
    assert.deepEqual(han, [], `${lang}.json: Chinese characters`);
  }
});

test('the English texts are distinct (one translation per text)', () => {
  const seen = new Map();
  for (const [k, v] of Object.entries(en.messages)) {
    assert.ok(!seen.has(v), `"${v}" is both ${seen.get(v)} and ${k}`);
    seen.set(v, k);
  }
});

test('every non-English file names the six key indicators in its own words, the same under every English name', () => {
  for (const lang of LANGS.filter(l => l !== 'en')) {
    const p = files[lang].pmg;
    for (const id of INDICATORS) {
      assert.ok(p[id] && p[id] !== en.pmg[id], `${lang}: ${id} is not translated`);
      for (const alias of Object.keys(en.pmg).filter(k => k.startsWith(id + '@'))) assert.equal(p[alias], p[id], `${lang}: ${alias}`);
    }
  }
});

test('the PMG block uses the official Preach My Gospel wording of pmg-terms.json; its gaps are listed', { skip: pmgTerms ? false : 'pmg-terms.json not found (set GFM_PMG_TERMS)' }, () => {
  for (const lang of LANGS) {
    const f = files[lang];
    const gaps = [];
    for (const key of Object.keys(en.pmg)) {
      if (key.includes('@')) continue; // other English names: checked above (= the label)
      const [id, field] = key.endsWith('.short') ? [key.slice(0, -6), 'short'] : [key, 'label'];
      const official = pmgTerms[id] && pmgTerms[id][lang] && pmgTerms[id][lang][field];
      if (official) assert.equal(f.pmg[key], official, `${lang}: ${key}`);
      else gaps.push(key);
    }
    assert.deepEqual([...f._meta.pmgGaps].sort(), gaps.sort(), `${lang}: _meta.pmgGaps must list exactly the keys PMG has no wording for`);
    if (lang !== 'fa') assert.ok(INDICATORS.every(id => !gaps.includes(id)), `${lang}: a key indicator has no PMG label`);
  }
});
