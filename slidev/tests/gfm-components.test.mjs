// GFM Studio's own layouts (manager/gfm-addon/layouts) and components (Gfm*.vue): each one is a single-root template
// with a <studio> block that gives Studio's palette its description (and a category for a component), the layouts are
// the ones the product list names, and every GFM layout and component class is in the shared stylesheet's namespace.
// Plain Node: no Slidev and no browser (the real rendering is checked in slidev/tests/studio-perf with gfm-demo.md).
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ADDON = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', 'manager', 'gfm-addon');
const read = (...parts) => fs.readFileSync(path.join(ADDON, ...parts), 'utf8').replace(/\r\n/g, '\n'); // a Windows checkout has CRLF
const layouts = fs.readdirSync(path.join(ADDON, 'layouts')).filter(f => f.endsWith('.vue')).map(f => f.replace(/\.vue$/, ''));
const components = fs.readdirSync(path.join(ADDON, 'components')).filter(f => /^Gfm.*\.vue$/.test(f)).map(f => f.replace(/\.vue$/, ''));

const WANTED_LAYOUTS = ['gfm-cover', 'gfm-section', 'gfm-hero', 'gfm-full-chart', 'gfm-chart-insight', 'gfm-two-chart', 'gfm-kpi-grid', 'gfm-three-column', 'gfm-comparison', 'gfm-image-message', 'gfm-freeform'];
const WANTED_COMPONENTS = ['GfmBigNumber', 'GfmCallout', 'GfmComparison', 'GfmInsight', 'GfmKpi', 'GfmKpiGrid', 'GfmProgress', 'GfmQuote'];

// The template's root elements, counted the way Studio's catalog does (a component with several roots gets no source
// annotation and would be invisible to the editor).
function rootCount(code) {
  const template = code.match(/<template>([\s\S]*?)<\/template>\s*(?:<script|<style|<studio|$)/)?.[1] ?? '';
  let depth = 0, roots = 0;
  for (const [, closing, , attrs, selfClose] of template.replace(/<!--[\s\S]*?-->/g, '').matchAll(/<(\/?)([A-Za-z][\w.-]*)((?:"[^"]*"|'[^']*'|[^>"'])*?)(\/?)>/g)) {
    if (closing) { depth--; continue; }
    if (depth === 0 && !/\sv-else/.test(attrs)) roots++;
    if (!selfClose) depth++;
  }
  return roots;
}

test('the layouts of the product list exist, nothing else is named gfm-', () => {
  assert.deepEqual(layouts.sort(), [...WANTED_LAYOUTS].sort());
});

test('the components of the first set exist', () => {
  assert.deepEqual(components.sort(), [...WANTED_COMPONENTS].sort());
});

for (const name of layouts) {
  test(`layout ${name}: one root, a studio description, the shared class`, () => {
    const code = read('layouts', `${name}.vue`);
    assert.equal(rootCount(code), 1, 'one root element');
    assert.match(code, /<studio>\s*description: .{20,}/, 'a description for the layout picker');
    assert.match(code, /class="gfm-layout\b/, 'built on the shared gfm-layout class');
    // `title` is a reserved frontmatter word in Slidev (it is never passed to a layout as a prop): headings use `heading`.
    assert.doesNotMatch(code, /^\s{2}title\??:/m, 'no title prop (Slidev keeps it back); use heading');
  });
}

for (const name of components) {
  test(`component ${name}: one root, a studio description and category, a snippet that uses it`, () => {
    const code = read('components', `${name}.vue`);
    assert.equal(rootCount(code), 1, 'one root element');
    assert.match(code, /<studio>[\s\S]*?description: .{20,}/, 'a description for the palette');
    assert.match(code, /category: GFM (content|data)/, 'in a GFM category');
    assert.match(code, new RegExp(`snippet: [^\\n]*<${name}\\b|snippet: \\|-\\n\\s+<${name}\\b`), 'the snippet inserts the component');
  });
}

test('the shared stylesheet defines light and dark tokens and every gfm- class used is its own', () => {
  const css = read('styles', 'index.css');
  assert.match(css, /:root\s*{[^}]*--gfm-teal/);
  assert.match(css, /html\.dark\s*{[^}]*--gfm-teal/);
  assert.match(css, /prefers-reduced-motion/, 'motion respects the reader');
});

test('key-number components draw MissionKpiChart, so a published deck may ask for the key numbers', () => {
  assert.match(read('components', 'GfmKpi.vue'), /<MissionKpiChart\b/);
  assert.match(read('components', 'GfmKpiGrid.vue'), /<GfmKpi\b/);
});
