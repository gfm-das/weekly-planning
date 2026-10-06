// The language copies of the dashboards (lib/languages.mjs: the id rule; lib/copies.mjs: the copy), checked on the
// three dashboards exactly as DataEase stored them (dashboards/export/*.dataease.json). No network, no packages:
//   node --test "tests/*.test.mjs"   (in dataease/)
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import { CODES, LANGUAGES, copyInTree, isCopyId, makeId, normalizeLanguage, parseId } from '../lib/languages.mjs';
import { copyDashboard, translateHtml, translator } from '../lib/copies.mjs';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const EXPORTS = ['key-indicators', 'zones-districts', 'covenant-path']
  .map(name => JSON.parse(fs.readFileSync(path.join(HERE, '..', 'dashboards', 'export', name + '.dataease.json'), 'utf8')));
const overlay = createRequire(import.meta.url)('../i18n/gfm-i18n.js');

test('the id rule: 115 LL DD GG PPPP 000000, English = 00, the examples of lib/languages.mjs', () => {
  assert.equal(makeId({ dashboard: 1 }), '1150001000000000000', 'Key indicators in English: the id seed-dashboards.mjs has always used');
  assert.equal(makeId({ language: 1, dashboard: 1 }), '1150101000000000000', 'its German copy');
  assert.equal(makeId({ language: 1 }), '1150100000000000000', 'the folder "Deutsch"');
  assert.equal(makeId({ language: 13, dashboard: 3, generation: 2, part: 15 }), '1151303020015000000');
  assert.deepEqual(parseId('1151303020015000000'), { language: 13, dashboard: 3, generation: 2, part: 15 });
  assert.equal(parseId('1302280795569917952'), null, 'an id DataEase made itself is not ours');
  assert.equal(parseId('1150000000000101001'), null);
  assert.throws(() => makeId({ generation: 90 }));
  assert.throws(() => makeId({ part: 10000 }));
  assert.equal(isCopyId('1150101000003000000'), true);
  assert.equal(isCopyId('1150001000003000000'), false);
  // Every id stays in the block the builder keeps clear (1.15e18 up to the dataset ids at 1.16e18).
  const top = BigInt(makeId({ language: 99, dashboard: 99, generation: 89, part: 9999 }));
  assert.ok(top < 1160000000000000000n);
  // Numbers 1-13, one per language, the same codes as the page script.
  assert.deepEqual(LANGUAGES.map(l => l.number), [...Array(13)].map((_, i) => i + 1));
  assert.deepEqual([...CODES].sort(), [...overlay.LANGS].sort());
  assert.equal(normalizeLanguage(' DE-at '), 'de');
  assert.equal(normalizeLanguage('xx'), null);
});

test('copyInTree finds the copy of any generation, only for our English dashboards', () => {
  const tree = [{ id: '1150000000000000000', leaf: false, children: [
    { id: '1150100000000000000', leaf: false, children: [{ id: '1150102030000000000', leaf: true }] },
    { id: '1150002000000000000', leaf: true },
  ] }];
  assert.equal(copyInTree(tree, '1150002000000000000', 'de'), '1150102030000000000');
  assert.equal(copyInTree(tree, '1150002000000000000', 'fr'), null);
  assert.equal(copyInTree(tree, '1150002000000000000', 'en'), null);
  assert.equal(copyInTree(tree, '1302280795569917952', 'de'), null);
});

for (const code of ['de', 'ar']) {
  test(`copies in ${code}: new ids everywhere, the same datasets, every word translated`, () => {
    const translate = translator(code);
    const lang = LANGUAGES.find(l => l.code === code);
    for (const dv of EXPORTS) {
      const copy = copyDashboard(dv, code, translate);
      const d = parseId(dv.id).dashboard;
      assert.equal(copy.id, makeId({ language: lang.number, dashboard: d }));
      assert.deepEqual(copy.missing, [], `${dv.name}: words without a ${code} translation`);
      assert.notEqual(copy.name, dv.name, 'the name is translated');

      // No English id is left; every chart id is a part of the copy's id.
      const text = JSON.stringify([copy.componentData, copy.canvasViewInfo]);
      const englishIds = new Set([String(dv.id), ...dv.componentData.map(c => String(c.id)), ...Object.keys(dv.canvasViewInfo)]);
      for (const id of englishIds) assert.ok(!text.includes(id), `${dv.name}: English id ${id} left in the copy`);
      for (const [id, view] of Object.entries(copy.canvasViewInfo)) {
        const p = parseId(id);
        assert.ok(p && p.language === lang.number && p.dashboard === d && p.part > 0, `chart id ${id}`);
        assert.equal(view.id, id);
        assert.equal(view.sceneId, copy.id, 'each chart belongs to the copy');
      }

      // The same datasets and fields as the English dashboard (so the same numbers).
      const tables = views => Object.values(views).map(v => v.tableId).sort();
      assert.deepEqual(tables(copy.canvasViewInfo), tables(dv.canvasViewInfo));
      const fields = views => Object.values(views).flatMap(v => [...v.xAxis, ...v.yAxis, ...(v.xAxisExt || []), ...(v.extColor || [])].map(f => f.id)).sort();
      assert.deepEqual(fields(copy.canvasViewInfo), fields(dv.canvasViewInfo));

      // Titles, notes and the words drawn on the charts (legends, table headers).
      const english = Object.values(dv.canvasViewInfo);
      const copied = Object.values(copy.canvasViewInfo);
      for (let i = 0; i < english.length; i += 1) {
        const [e, c] = [english[i], copied[i]]; // the same order: only the ids changed
        if (e.title) assert.notEqual(c.title, e.title, `title "${e.title}"`);
        if (e.customStyle?.text?.remark) assert.notEqual(c.customStyle.text.remark, e.customStyle.text.remark, `note of "${e.title}"`);
      }
      for (const v of copied.filter(v => v.type !== 'rich-text')) {
        for (const f of [...v.yAxis, ...(v.extColor || [])]) assert.ok(f.chartShowName && /[^\x00-\x7f]|[a-z]/i.test(f.chartShowName), `${v.title}: shown name of ${f.id}`);
      }
      // Filter labels.
      const query = copy.componentData.find(c => c.component === 'VQuery');
      const englishQuery = dv.componentData.find(c => c.component === 'VQuery');
      assert.deepEqual(query.propValue.map(p => p.name), englishQuery.propValue.map(p => translate(p.name)));
      assert.ok(query.propValue.every((p, i) => p.id === `${query.id}-${i + 1}`), 'filter conditions follow their component');
      for (const p of query.propValue) for (const viewId of p.checkedFields) assert.ok(copy.canvasViewInfo[viewId], 'filters point at the copy\'s charts');

      // Text boxes: translated, with every [Field] placeholder kept exactly.
      const placeholders = html => (html.match(/\[[^\]<]*\]/g) || []).sort();
      dv.componentData.filter(c => c.innerType === 'rich-text').forEach((e, i) => {
        const c = copy.componentData.filter(x => x.innerType === 'rich-text')[i];
        assert.deepEqual(placeholders(c.propValue.textValue), placeholders(e.propValue.textValue));
        assert.equal(c.propValue.textValue.replace(/>[^<]*</g, '><'), e.propValue.textValue.replace(/>[^<]*</g, '><'), 'the same tags and styles');
      });
    }
  });
}

test('the German Key indicators copy uses the Preach My Gospel names', () => {
  const copy = copyDashboard(EXPORTS[0], 'de', translator('de'));
  assert.equal(copy.name, 'Hauptindikatoren');
  const titles = Object.values(copy.canvasViewInfo).map(v => v.title).filter(Boolean);
  assert.ok(titles.includes('Neue Personen, die unterwiesen werden'));
  assert.ok(titles.includes('Personen, die unterwiesen werden und die Abendmahlsversammlung besuchen'));
  const legend = Object.values(copy.canvasViewInfo).find(v => v.title === 'Neue Personen, die unterwiesen werden').yAxis.map(f => f.chartShowName);
  assert.deepEqual(legend, ['Ergebnis', 'In der Vorwoche gesetztes Ziel', 'Trend']);
  const tiles = copy.componentData.filter(c => c.innerType === 'rich-text').map(c => c.propValue.textValue).join('\n');
  assert.ok(tiles.includes('>% des Ziels (<'), 'the "% of the goal (" piece between two live numbers');
  assert.ok(tiles.includes('>Vorwoche: <'));
});

test('a later generation moves every id by the same step; a dashboard made by hand gets no copy', () => {
  const copy = copyDashboard(EXPORTS[1], 'fr', translator('fr'), 3);
  assert.equal(copy.id, '1150302030000000000');
  assert.ok(Object.keys(copy.canvasViewInfo).every(id => parseId(id).generation === 3));
  assert.throws(() => copyDashboard({ ...EXPORTS[0], id: '1302280795569917952' }, 'de', translator('de')), /not made by seed-dashboards/);
  assert.throws(() => copyDashboard(EXPORTS[0], 'en', translator('de')), /not one of the 13/);
});

test('text boxes: entities, placeholders and untranslated text', () => {
  const t = translator('de');
  assert.equal(translateHtml('<p><strong>Zones &amp; districts</strong></p>', t), '<p><strong>Zonen &amp; Distrikte</strong></p>');
  assert.equal(translateHtml('<span>[Last complete week]</span>', t), '<span>[Last complete week]</span>');
  const seen = [];
  assert.equal(translateHtml('<p>Nothing like this</p><p>&nbsp;</p>', t, s => seen.push(s)), '<p>Nothing like this</p><p>&nbsp;</p>');
  assert.deepEqual(seen, ['Nothing like this']);
});
