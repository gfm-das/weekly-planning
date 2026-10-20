// Every script the manager sends to a browser must at least be valid JavaScript.
//   A line break inside a quoted string in studio.html (round 16, the "Copy details" button) made the whole editor page's
//   script fail with "Uncaught SyntaxError": the page stayed on "Step 1 of 3: starting the slide tools." for ever,
//   because the code that asks for the editor never ran. No other test opened the page, so nothing noticed.
// Plain Node, no browser: the inline <script> blocks of the two pages and the two bridge scripts are compiled (not run).
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

const read = name => readFileSync(new URL(`../manager/${name}`, import.meta.url), 'utf8');

/** The inline <script> blocks of a page (not the ones with a src). */
function inlineScripts(html) {
  return [...html.matchAll(/<script(?![^>]*\ssrc=)[^>]*>([\s\S]*?)<\/script>/g)].map(match => match[1]);
}

function compiles(code, name) {
  assert.doesNotThrow(() => new vm.Script(code, { filename: name }), `${name} is not valid JavaScript`);
}

for (const page of ['studio.html', 'library.html']) {
  test(`${page}: every inline script is valid JavaScript`, () => {
    // The placeholders the manager fills in are replaced by plain values, as pages.mjs does.
    const html = read(page).replace('window.STUDIO=__STUDIO_DATA__;', 'window.STUDIO={};').replace('const ORIGINS = __PORTAL_ORIGINS__;', 'const ORIGINS = [];');
    const scripts = inlineScripts(html);
    assert.ok(scripts.length > 0, `${page} should have scripts`);
    scripts.forEach((code, i) => compiles(code, `${page} script ${i + 1}`));
  });
}

test('the studio page script starts the editor (the code behind "Step 1 of 3" is there and compiles)', () => {
  const big = inlineScripts(read('studio.html')).sort((a, b) => b.length - a.length)[0];
  assert.match(big, /async function startStudio\(/);
  assert.match(big, /startStudio\(\)/);
});

for (const file of ['editor-bridge.js', 'portal-bridge.js']) {
  test(`${file} is valid JavaScript`, () => {
    compiles(read(file).replace('const SHELL = __SHELL_ORIGIN__;', 'const SHELL = "";'), file);
  });
}
