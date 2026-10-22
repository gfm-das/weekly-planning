// Paste Presentation: the Copy AI instructions button works on the portal's plain http too (no clipboard API there),
// shows the instructions selected when the browser refuses, speaks the reader's language (the editor page sends the
// words) and the instructions name the components the decks use (MissionChart steps, MissionList, MissionKpiChart).
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { copyText, copyWords, COPY_WORDS } from '../manager/addons/gfm-studio/gfm/copy-text.mjs';
import { analyzeDeck } from '../manager/addons/gfm-studio/gfm/import-analyze.mjs';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const MANAGER = path.join(HERE, '..', 'manager');
const read = p => fs.readFile(path.join(MANAGER, p), 'utf8');

function fakeDoc({ copies = true, throws = false } = {}) {
  const doc = { added: [], removed: 0, commands: [], activeElement: null };
  doc.body = { appendChild: el => doc.added.push(el) };
  doc.createElement = () => ({ style: {}, setAttribute() {}, select() { this.selected = true; }, remove() { doc.removed++; } });
  doc.execCommand = cmd => { doc.commands.push(cmd); if (throws) throw new Error('no'); return copies; };
  return doc;
}

test('copy uses the clipboard API where the browser has it (https, localhost)', async () => {
  let got = null;
  const win = { isSecureContext: true, navigator: { clipboard: { writeText: async t => { got = t; } } } };
  const doc = fakeDoc();
  assert.equal(await copyText('hello', { win, doc }), true);
  assert.equal(got, 'hello');
  assert.deepEqual(doc.commands, [], 'no fallback needed');
});

test('copy on plain http (no clipboard API): a selected hidden text box and execCommand', async () => {
  const doc = fakeDoc();
  assert.equal(await copyText('the instructions', { win: { isSecureContext: false, navigator: {} }, doc }), true);
  assert.deepEqual(doc.commands, ['copy']);
  assert.equal(doc.added[0].value, 'the instructions');
  assert.equal(doc.added[0].selected, true);
  assert.equal(doc.removed, 1, 'the box is taken away again');
});

test('a clipboard API that refuses falls back too; when everything refuses, copy says so', async () => {
  const win = { isSecureContext: true, navigator: { clipboard: { writeText: async () => { throw new Error('denied'); } } } };
  const ok = fakeDoc();
  assert.equal(await copyText('x', { win, doc: ok }), true);
  assert.deepEqual(ok.commands, ['copy']);
  assert.equal(await copyText('x', { win, doc: fakeDoc({ copies: false }) }), false);
  const thrown = fakeDoc({ throws: true });
  assert.equal(await copyText('x', { win, doc: thrown }), false);
  assert.equal(thrown.removed, 1);
  assert.equal(await copyText('x', { win: {}, doc: {} }), false, 'no document body: false, no error');
});

test('the dialog words: English by default, only known short strings from the editor page', () => {
  assert.deepEqual(copyWords(undefined), COPY_WORDS);
  const w = copyWords({ copy: 'KI-Anleitung kopieren', show: 42, evil: 'x', hide: 'y'.repeat(500), steps: '  ' });
  assert.equal(w.copy, 'KI-Anleitung kopieren');
  assert.equal(w.show, COPY_WORDS.show);
  assert.equal(w.hide, COPY_WORDS.hide);
  assert.equal(w.steps, COPY_WORDS.steps);
  assert.equal('evil' in w, false);
});

test('every word of the copy part is in the catalogue and sent, translated, by the editor page', async () => {
  const studio = await read('studio.html');
  const en = JSON.parse(await fs.readFile(path.join(HERE, '..', '..', 'portal', 'i18n', 'en.json'), 'utf8'));
  const texts = new Set(Object.values(en));
  for (const [k, v] of Object.entries(COPY_WORDS)) {
    assert.ok(texts.has(v), `en.json has "${v}"`);
    assert.ok(studio.includes(`${k}: tr('${v}')`), `studio.html sends ${k}`);
  }
  for (const lang of ['ar', 'da', 'de', 'es', 'fa', 'fr', 'it', 'pt', 'ro', 'ru', 'sv', 'tr', 'uk']) {
    const cat = JSON.parse(await fs.readFile(path.join(HERE, '..', '..', 'portal', 'i18n', `${lang}.json`), 'utf8'));
    for (const key of ['pres.aiStepsCopyThenPaste', 'pres.showInstructions', 'pres.hideInstructions', 'pres.copyBlockedInstructionsSelected'])
      assert.ok(cat[key] && cat[key] !== en[key], `${lang} translates ${key}`);
  }
  assert.match(studio, /gfm-editor-open-import', labels: importLabels\(\)/);
  assert.doesNotMatch(studio, /navigator\.clipboard\.writeText\(text\);\s*\n\s*toast/, 'Copy AI instructions no longer relies on the clipboard API alone');
  assert.match(await read('editor-bridge.js'), /s\.importLabels\.value = data\.labels/);
});

test('the dialog: a visible Copy AI instructions button, the copy with a fallback, the instructions shown when blocked', async () => {
  const vue = await read('addons/gfm-studio/gfm/ImportDialog.vue');
  assert.match(vue, /<button class="gfm-btn gfm-btn--go" data-gfm-copy-instructions @click="copyInstructions">/);
  assert.match(vue, /if \(await copyText\(aiPrompt\)\)/);
  assert.doesNotMatch(vue, /navigator\.clipboard/);
  assert.match(vue, /copyBlocked\.value = true; showPrompt\.value = true; selectPrompt\(\)/);
  assert.match(vue, /<textarea v-if="showPrompt" ref="promptBox"[^>]*readonly[^>]*:value="aiPrompt"/);
  assert.match(await read('addons/gfm-studio/client/state.ts'), /importOpen, importPrefill, importLabels, notice/);
});

test('the instructions name the live components the decks use, and their examples pass the check', async () => {
  const prompt = await read('gfm-addon/ai/gfm-ai-prompt.txt');
  const spec = JSON.parse(await read('gfm-addon/ai/gfm-spec.json'));
  const names = spec.components.map(c => c.name);
  for (const c of ['MissionChart', 'MissionList', 'MissionKpiChart']) { assert.ok(names.includes(c), `spec knows ${c}`); assert.ok(prompt.includes(`<${c} `), `prompt shows ${c}`); }
  assert.match(prompt, /:story=/, 'chart steps (a chart that changes with each click)');
  assert.match(prompt, /:steps is the same/);
  assert.ok(prompt.length < 6000);
  const showcase = await read('shipped-decks/gfm-showcase/slides.md');
  for (const c of ['MissionList', 'MissionKpiChart', ':steps=']) assert.ok(showcase.includes(c), `the showcase uses ${c}`);
  const examples = prompt.split('\n').map(l => /(<Mission(?:List|KpiChart)\b.*\/>)/.exec(l)?.[1]).filter(Boolean);
  assert.equal(examples.length, 2);
  const r = analyzeDeck(`---\ntheme: default\n---\n\n# x\n\n${examples.join('\n\n')}\n`, { spec });
  assert.deepEqual(r.issues.filter(i => i.severity !== 'info'), [], JSON.stringify(r.issues));
});
