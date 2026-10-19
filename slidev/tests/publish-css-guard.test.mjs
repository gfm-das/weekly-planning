// Round 16 (item 6): one bad style must not stop a publish.
//   Slidev 52.19's CSS minifier (lightningcss) refuses a selector like `::after:1.5rem` ("Invalid token in pseudo
//   element") and ended the whole build, so the owner could not publish. Checked here without Slidev:
//   1. the addon's Vite hook switches the CSS minifier off for builds;
//   2. a failed publish answers 422 with Slidev's log lines and the dialog has a translated "Copy details" button.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const MANAGER = path.join(HERE, '..', 'manager');
const read = file => fs.readFileSync(path.join(MANAGER, file), 'utf8');

// A pseudo-element followed by a colon and a number with a unit, written in a style or in an arbitrary variant.
const BAD_SELECTOR = /::[a-zA-Z-]+(\([^)]*\))?:-?\.?\d/;

test('the addon\'s styles and components have no such selector either', () => {
  const roots = ['gfm-addon/styles', 'gfm-addon/components', 'gfm-addon/layouts', 'gfm-addon/presenter'];
  for (const root of roots) {
    for (const name of fs.readdirSync(path.join(MANAGER, root))) {
      assert.doesNotMatch(read(path.join(root, name)), BAD_SELECTOR, `${root}/${name}`);
    }
  }
});

test('builds do not minify CSS, so a rule lightningcss refuses cannot stop a publish', () => {
  const hook = read('gfm-addon/setup/vite-plugins.ts');
  assert.match(hook, /apply: 'build'[\s\S]{0,200}cssMinify: false/);
});

test('a failed publish answers 422 with the log lines', () => {
  const routes = read('manager-routes.mjs');
  assert.match(routes, /error\.buildFailed \? 422 : 500, \{ error: publishErrorMessage\(error\), log: error\.log \|\| '' \}/);
  const builds = read('builds.mjs');
  assert.match(builds, /error\.log = output\.slice\(-20\)\.join/);
});

test('the publish dialog shows the log and has a Copy details button in all 14 languages', () => {
  const studio = read('studio.html');
  assert.match(studio, /id="publishCopy"[^>]*>Copy details</);
  assert.match(studio, /id="publishLog"/);
  assert.match(studio, /Details copied\./);
  const catalogs = path.join(HERE, '..', '..', 'portal', 'i18n');
  const en = JSON.parse(fs.readFileSync(path.join(catalogs, 'en.json'), 'utf8'));
  assert.equal(en['pres.copyDetails'], 'Copy details');
  assert.equal(en['pres.detailsCopied'], 'Details copied.');
  for (const file of fs.readdirSync(catalogs).filter(f => /^[a-z]{2}\.json$/.test(f))) {
    const catalog = JSON.parse(fs.readFileSync(path.join(catalogs, file), 'utf8'));
    assert.ok(catalog['pres.copyDetails'] && catalog['pres.detailsCopied'], file);
  }
});
