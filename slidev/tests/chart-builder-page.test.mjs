// The chart builder of /studio (manager/chart-builder.mjs) in its page: the chart libraries on a page with Monaco's
// AMD loader, mission numbers that never answer, and the editor's answers when a slide is read or saved.
//   v1.0.19 (PR #30) started loading Monaco's loader.js while the slides open (studio.html preloadTools). The ECharts
//   and ecStat files are UMD bundles: with an AMD `define` on the page they registered as AMD modules instead of
//   setting window.echarts, the preview threw on every draw and stayed on "Loading mission numbers…", even with
//   Paste a table. Mission numbers that never answered also kept the preview loading for ever.
// Plain Node: the builder's files are put together as the manager serves them (/_manager/chart/, builderFiles) and
// loaded with a tiny stand-in for the page's document.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { builderFiles } from '../manager/chart-access.mjs';

const MANAGER = fileURLToPath(new URL('../manager/', import.meta.url));

async function loadBuilder() {
  const dir = await fs.mkdtemp(path.join(os.tmpdir(), 'builder-'));
  for (const [name, file] of Object.entries(builderFiles(MANAGER))) await fs.copyFile(file, path.join(dir, name));
  return { dir, builder: await import(pathToFileURL(path.join(dir, 'chart-builder.mjs')).href) };
}

/** A page with an AMD loader like Monaco's; appended scripts run their file from `dir` (as the browser would). */
function fakePage(dir, { amd = true } = {}) {
  const g = globalThis;
  const defined = [];
  if (amd) { g.define = (...args) => { defined.push(args); }; g.define.amd = { jQuery: true }; }
  g.document = {
    createElement: () => ({ remove() {} }),
    head: {
      appendChild(script) {
        setTimeout(async () => {
          try {
            const name = script.src.replace('/_manager/chart/', '');
            vm.runInThisContext(await fs.readFile(path.join(dir, name), 'utf8'), { filename: name });
            script.onload();
          }
          catch (error) { script.onerror(error); }
        }, 0);
      },
    },
  };
  return { defined, done() { delete g.document; delete g.define; delete g.echarts; delete g.ecStat; delete g.__gfmTransforms; } };
}

test('on a page with Monaco\'s AMD loader, ECharts and ecStat still set their globals and the loader keeps define.amd', async () => {
  const { dir, builder } = await loadBuilder();
  const page = fakePage(dir);
  try {
    const lib = await builder.loadLibraries();
    assert.equal(typeof lib.echarts?.init, 'function', 'echarts is there');
    assert.equal(typeof lib.ecStat?.regression, 'function', 'ecStat is there');
    assert.deepEqual(page.defined, [], 'nothing was handed to the AMD loader');
    assert.deepEqual(globalThis.define.amd, { jQuery: true }, 'define.amd is back for Monaco');
  }
  finally { page.done(); }
});

test('without the fix the same page had no chart library (what made the preview hang)', async () => {
  const { dir } = await loadBuilder();
  const page = fakePage(dir);
  try {
    vm.runInThisContext(await fs.readFile(path.join(dir, 'echarts.min.js'), 'utf8'));
    assert.equal(globalThis.echarts, undefined);
    assert.equal(page.defined.length, 1, 'ECharts went to the AMD loader');
  }
  finally { page.done(); }
});

test('mission numbers that never answer end in a message, not "Loading…" for ever', async () => {
  const { builder } = await loadBuilder();
  await assert.rejects(builder.withTimeout(new Promise(() => {}), 20, 'late'), error => error.timeout === true && error.message === 'late');
  assert.equal(await builder.withTimeout(Promise.resolve(7), 1000, 'late'), 7);
  assert.ok(builder.DATA_TIMEOUT_MS > 0 && builder.DATA_TIMEOUT_MS <= 30000);
});

test('a slide that cannot be read or saved says what failed (not "Something went wrong")', async () => {
  const { builder } = await loadBuilder();
  const generic = Object.assign(new Error('Something went wrong. Please try again.'), { status: 502, data: {} });
  assert.match(builder.slideError(generic, 'write', 3).message, /^The chart could not be saved on slide 3 \(error 502\)\./);
  assert.match(builder.slideError(Object.assign(new Error('x'), { status: 404, data: {} }), 'read', 2).message, /^Slide 2 could not be read from the editor \(error 404\)\./);
  assert.match(builder.slideError(new TypeError('Failed to fetch'), 'read', 1).message, /connection to the editor was lost/);
  const own = Object.assign(new Error('This file is not part of your presentation.'), { status: 403, data: { error: 'This file is not part of your presentation.' } });
  assert.equal(builder.slideError(own, 'read', 1), own, 'the manager\'s own sentence is kept');
});
