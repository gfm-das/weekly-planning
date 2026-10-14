// The round-13 dashboards (Areas, Trend, Per 10,000 residents) and the three older ones, made in memory with the
// stand-in datasets of tests/fake-datasets.mjs, then copied into all 13 other languages with lib/copies.mjs:
// every word must have a translation, the ids must follow the id rule, and the copies must read the same datasets.
// No DataEase, no network:   node --test "tests/*.test.mjs"   (in dataease/)
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { test } from 'node:test';
import { DASHBOARDS_DIR, buildDashboard, loadBase } from '../lib/build.mjs';
import { LANGUAGES, makeId, parseId } from '../lib/languages.mjs';
import { copyDashboard, translator } from '../lib/copies.mjs';
import { fakeDatasets } from './fake-datasets.mjs';

const FILES = ['key-indicators.json', 'zones-districts.json', 'covenant-path.json', 'areas.json', 'trend.json', 'per-capita.json'];
const datasets = fakeDatasets();
const base = loadBase();
const english = FILES.map(file => buildDashboard(JSON.parse(fs.readFileSync(path.join(DASHBOARDS_DIR, file), 'utf8')), datasets, base));

test('six English dashboards, numbered 01 to 06, each with charts', () => {
  assert.equal(english.length, 6);
  english.forEach((dv, i) => {
    assert.deepEqual(parseId(dv.id), { language: 0, dashboard: i + 1, generation: 0, part: 0 }, dv.name);
    assert.ok(Object.keys(dv.canvasViewInfo).length >= 4, dv.name);
  });
});

for (const lang of LANGUAGES) {
  test(`${lang.code}: every dashboard copies with every word translated, new ids, the same datasets`, () => {
    const translate = translator(lang.code);
    english.forEach((dv, i) => {
      const copy = copyDashboard(dv, lang.code, translate);
      assert.deepEqual(copy.missing, [], `${dv.name} in ${lang.code}: words without a translation`);
      assert.equal(copy.id, makeId({ language: lang.number, dashboard: i + 1 }));
      assert.ok(copy.name.length <= 100, `${lang.code} "${copy.name}" is longer than DataEase allows`);
      const text = JSON.stringify([copy.componentData, copy.canvasViewInfo]);
      for (const id of [dv.id, ...dv.componentData.map(c => c.id)]) assert.ok(!text.includes(id), `${dv.name} in ${lang.code}: English id ${id} left`);
      const tables = views => Object.values(views).map(v => v.tableId).sort();
      assert.deepEqual(tables(copy.canvasViewInfo), tables(dv.canvasViewInfo));
      assert.equal(Object.keys(copy.canvasViewInfo).length, Object.keys(dv.canvasViewInfo).length);
      for (const view of Object.values(copy.canvasViewInfo)) {
        assert.equal(view.sceneId, copy.id);
        if (view.title) assert.ok(view.title.length <= 100, `${lang.code} "${view.title}"`);
      }
    });
  });
}

test('the new dashboards are translated, not copied in English (German and Arabic spot checks)', () => {
  const [, , , areas, trend, perCapita] = english;
  const de = [areas, trend, perCapita].map(dv => copyDashboard(dv, 'de', translator('de')));
  assert.equal(de[0].name, 'Gebiete');
  assert.equal(de[1].name, 'Trend');
  assert.equal(de[2].name, 'Pro 10.000 Einwohner');
  const titles = copy => Object.values(copy.canvasViewInfo).map(v => v.title).filter(Boolean);
  assert.ok(titles(de[2]).includes('Neue Personen, die unterwiesen werden pro 10.000 Einwohner'));
  assert.ok(titles(de[0]).some(t => t.startsWith('Gebiete, die vielleicht Hilfe brauchen')));
  const ar = [areas, trend, perCapita].map(dv => copyDashboard(dv, 'ar', translator('ar')));
  assert.equal(ar[2].name, 'لكل 10,000 نسمة');
  const sentence = Object.values(ar[2].canvasViewInfo).map(v => v.customStyle.text.remark).filter(Boolean);
  assert.ok(sentence.length > 0 && sentence.every(s => /[؀-ۿ]/.test(s)), 'notes in Arabic');
});
