// Makes the GFM AI Presentation Spec from the layouts and components themselves, so it can never drift from them:
//   slidev/manager/gfm-addon/ai/gfm-spec.json        the manifest (layouts, components, props, chart settings): what the
//                                                    import check in GFM Studio reads
//   slidev/manager/gfm-addon/ai/gfm-ai-spec-v1.md    the full specification (versioned in Git)
//   slidev/manager/gfm-addon/ai/gfm-ai-prompt.txt    the concise instructions "Copy AI instructions" puts on the clipboard
// Run after changing a layout, a component, a chart kind or a formula function (needs `yaml`: the Slidev container has it):
//   docker run --rm -v <repo>:/repo -v <nm volume>:/slidev/node_modules -w /repo/slidev node:24-alpine node tools/make-ai-spec.mjs
// tests/ai-spec.test.mjs fails when the committed files are not what this script makes.
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const ROOT = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', 'manager', 'gfm-addon');
export const SPEC_VERSION = 1;

/** Slidev's own layouts of the default theme and what it brings (the deck uses theme "default"). */
export const SLIDEV_LAYOUTS = ['default', 'center', 'cover', 'end', 'fact', 'full', 'iframe', 'iframe-left', 'iframe-right', 'image', 'image-left', 'image-right', 'intro', 'none', 'quote', 'section', 'statement', 'two-cols', 'two-cols-header'];
/** Slidev's built-in components a slide may use. */
export const SLIDEV_COMPONENTS = ['Arrow', 'AutoFitText', 'Link', 'RenderWhen', 'SlideCurrentNo', 'SlidesTotal', 'Toc', 'Transform', 'Tweet', 'Youtube', 'VClick', 'VClicks', 'VAfter', 'VSwitch', 'VDrag', 'VDragArrow', 'SlidevVideo', 'LightOrDark'];

function studioBlock(YAML, code) {
  const m = /<studio>\s*([\s\S]*?)<\/studio>/.exec(code);
  if (!m) return {};
  try { return YAML.parse(m[1]) ?? {}; } catch { return {}; }
}

/** The props of `defineProps<{ … }>`: name, type text, required; and a trailing `// comment`. */
function propsOf(code) {
  const m = /defineProps<\{([\s\S]*?)\n?\}>\(\)/.exec(code) ?? /defineProps<\{([\s\S]*?)\}>\(/.exec(code);
  if (!m) return [];
  const out = [];
  for (const line of m[1].split('\n')) {
    const p = /^\s*([A-Za-z_]\w*)(\?)?:\s*([^/\n]+?)\s*(?:\/\/\s*(.*))?$/.exec(line);
    if (p) out.push({ name: p[1], type: p[3].trim(), required: !p[2], ...(p[4] ? { note: p[4].trim() } : {}) });
  }
  return out;
}

function withMeta(props, meta) {
  const info = meta?.props ?? {};
  return props
    .map(p => {
      const i = info[p.name] ?? {};
      const options = Array.isArray(i.options) ? i.options.map(String) : (p.type.match(/'[^']+'/g) ?? []).map(s => s.slice(1, -1));
      return { name: p.name, type: p.type, ...(i.label ? { label: i.label } : {}), ...(options.length ? { options } : {}), ...(i.hidden ? { hidden: true } : {}) };
    });
}

export async function buildManifest(YAML, pins = {}) {
  const read = (...p) => fs.readFileSync(path.join(ROOT, ...p), 'utf8');
  const layouts = fs.readdirSync(path.join(ROOT, 'layouts')).filter(f => f.endsWith('.vue')).sort().map(f => {
    const code = read('layouts', f);
    const meta = studioBlock(YAML, code);
    const slots = [...new Set(['default', ...[...code.matchAll(/<slot name="(\w+)"/g)].map(m => m[1])])];
    return { name: f.replace(/\.vue$/, ''), description: String(meta.description ?? '').trim(), slots, props: withMeta(propsOf(code), meta).filter(p => p.name !== 'frontmatter') };
  });
  const components = fs.readdirSync(path.join(ROOT, 'components')).filter(f => /^(Gfm|Mission).*\.vue$/.test(f)).sort().map(f => {
    const code = read('components', f);
    const meta = studioBlock(YAML, code);
    return { name: f.replace(/\.vue$/, ''), category: meta.category ?? 'Charts', description: String(meta.description ?? '').trim(), snippet: String(meta.snippet ?? '').trim(), props: withMeta(propsOf(code), meta), slot: /<slot\b/.test(code) };
  });
  const presets = await import(pathToFileURL(path.join(ROOT, 'lib', 'chart-presets.mjs')).href);
  const formula = await import(pathToFileURL(path.join(ROOT, 'lib', 'formula.mjs')).href);
  const story = await import(pathToFileURL(path.join(ROOT, 'lib', 'chart-story.mjs')).href);
  const core = await import(pathToFileURL(path.join(ROOT, 'lib', 'chart-core.mjs')).href);
  const engine = await import(pathToFileURL(path.join(ROOT, 'lib', 'chart-engine.mjs')).href);
  return {
    version: SPEC_VERSION,
    slidevLayouts: SLIDEV_LAYOUTS,
    slidevComponents: SLIDEV_COMPONENTS,
    layouts,
    components,
    chart: {
      kpis: core.KPI_NAMES,
      kinds: presets.PRESET_IDS.map(id => ({ id, label: presets.PRESETS[id].label, group: presets.PRESETS[id].group, needs: presets.PRESETS[id].needs })),
      seriesTypes: engine.SERIES_TYPES,
      functions: Object.fromEntries(Object.entries(formula.FUNCTIONS).map(([n, f]) => [n, { signature: f.signature, help: f.help, example: f.example }])),
      formats: formula.FORMATS,
      storyKeys: story.STEP_KEYS,
      transitions: story.TRANSITIONS,
      easings: story.EASINGS,
    },
    ...pins,
  };
}

const tick = s => `\`${s}\``;

export function specMarkdown(m) {
  const L = [];
  L.push(`# GFM AI PRESENTATION SPEC v${m.version}`, '');
  L.push('How to write a complete **GFM Slidev presentation** that GFM Studio can import (Paste Presentation) and then edit visually.');
  L.push('This file is made from the layouts and components themselves (`slidev/tools/make-ai-spec.mjs`); do not edit it by hand.', '');
  L.push('## Output rules', '');
  L.push('- Return **only** the complete `slides.md`, as plain text. No explanations before or after it. Do not wrap it in a code fence.');
  L.push('- Slides are separated by a line with three dashes (`---`). The first block is the deck\'s settings (the headmatter), and it is also the first slide\'s settings.');
  L.push('- Use the layouts and components below. Prefer them to hand-written HTML: they look right without styling and stay editable in Studio.');
  L.push('- Do **not** import packages, add `<script>` blocks, load external scripts, use `<iframe>`, inline event handlers (`onclick=`) or `javascript:` links. Do not call `fetch`, `eval`, `localStorage` or `document.cookie`.');
  L.push('- Do not invent components, layouts or settings. Anything not listed here may be refused or shown as an error.');
  L.push('- Pictures: use files the deck already has (a path such as `/photo.jpg`); do not link to other websites for pictures.');
  L.push('- Write for a video call: a few words per slide, one idea each. Add speaker notes as an HTML comment at the end of a slide (`<!-- … -->`).');
  L.push('- Numbers: never invent mission numbers. Use the live components (`GfmKpiGrid`, `GfmKpi`) for key indicators, or mark an example value clearly (for example "example: 12").', '');
  L.push('## The first block (headmatter)', '', '```yaml', '---', 'theme: default', 'title: Weekly review', 'layout: gfm-cover', 'kicker: Germany Frankfurt Mission', 'fonts:', '  provider: none', '  sans: Inter', 'transition: fade', '---', '```', '');
  L.push(`Use \`theme: default\` (the only theme installed). Slide settings such as \`layout\` go in the block at the top of each slide:`, '', '```', '---', 'layout: gfm-section', 'kicker: Part 2', '---', '', '# Looking ahead', '```', '');
  L.push('Slidev keeps some setting names for itself and never hands them to a layout: `title`, `level`, `src`, `lang`, `hide`, `layout`, `transition`, `clicks`. A GFM layout\'s heading is the setting `heading` (a slide written with `title:` also works).', '');
  L.push('## Layouts', '');
  L.push('Slidev\'s own layouts that may be used: ' + m.slidevLayouts.map(tick).join(', ') + '.', '');
  for (const l of m.layouts) {
    L.push(`### ${tick(l.name)}`, '', l.description, '');
    if (l.slots.length > 1) L.push(`Parts of the slide: the main text, then ${l.slots.slice(1).map(s => `\`::${s}::\``).join(', ')} on a line of its own to start each further part.`, '');
    if (l.props.length) L.push('Settings: ' + l.props.map(p => `${tick(p.name)}${p.options ? ` (${p.options.join(' | ')})` : ''}`).join(', ') + '.', '');
  }
  L.push('## Components', '');
  L.push('Slidev\'s own components that may be used: ' + m.slidevComponents.map(tick).join(', ') + '.', '');
  for (const c of m.components) {
    L.push(`### ${tick(c.name)}`, '', c.description, '');
    if (c.props.length && c.name !== 'MissionChart') L.push('Settings: ' + c.props.filter(p => !p.hidden).map(p => `${tick(p.name)}${p.options ? ` (${p.options.join(' | ')})` : ''}`).join(', ') + '.', '');
    if (c.snippet) L.push('```', c.snippet, '```', '');
  }
  L.push('## Charts (`MissionChart`)', '');
  L.push('A chart is its numbers plus a chart kind. Write the numbers as rows (the first row holds the headings, the first column the labels):', '');
  L.push('```', '<MissionChart chart-id="trend1" preset="trend" :height="330"', '  :rows="[\'Week, New people being taught\', \'Aug 3, 12\', \'Aug 10, 15\', \'Aug 17, 14\']" />', '```', '');
  L.push('- `chart-id`: a short unique name for each chart (letters and digits).', '- `height`: slide pixels (a slide is 980 wide); 300 to 360 fits under a heading.');
  L.push('- Mission numbers from the weekly plans can only be added with **Add chart** in GFM Studio; do not write a `query` yourself.', '');
  L.push('### Chart kinds (`preset`)', '');
  L.push('Curated kinds: ' + m.chart.kinds.filter(k => k.group === 'kind').map(k => `${tick(k.id)} (${k.needs})`).join(', ') + '.', '');
  L.push('Every chart type, as `type-<name>`: ' + m.chart.kinds.filter(k => k.group === 'type').map(k => tick(k.id)).join(', ') + '.', '');
  L.push('### Calculated fields (`calc`)', '');
  L.push('```', ':calc=\'[{"name":"Successful Contact Rate","formula":"[Successfully Contacted] / [Referrals Received]","format":"percent"}]\'', '```', '');
  L.push(`Formats: ${m.chart.formats.map(tick).join(', ')}. Formulas use a field's name in square brackets, \`+ - * / % ^\`, comparisons, \`AND OR NOT\` and these functions:`, '');
  for (const [name, f] of Object.entries(m.chart.functions)) L.push(`- ${tick(f.signature)}: ${f.help}`);
  L.push('', '### Which numbers show (`shape`)', '', '```', ':shape=\'{"only":["Received","Attempted"],"sort":"desc","top":5}\'', '```', '');
  L.push('### Data stories (`story`)', '');
  L.push(`One chart that changes with each click. Each step may change: ${m.chart.storyKeys.map(tick).join(', ')}.`, '');
  L.push('```', '<MissionChart chart-id="story1" preset="trend" :rows="[…]"', '  :story=\'[{"label":"Received","shape":{"only":["Received"]}},{"label":"All","shape":{}}]\'', '  storyTransition="morph" :storyDuration="700" />', '```', '');
  L.push(`\`storyTransition\`: ${m.chart.transitions.map(tick).join(', ')}. \`storyEasing\`: ${m.chart.easings.map(tick).join(', ')}.`, '');
  L.push('## Animation', '', 'Reveal items one click at a time with Slidev\'s `<v-clicks>` (around a list) or `v-click` on an element. A story chart brings its own clicks.', '');
  L.push('## Mission key indicators', '', 'Use these names or ids with `GfmKpi` / `GfmKpiGrid`:', '');
  for (const [id, name] of Object.entries(m.chart.kpis)) L.push(`- ${tick(name)} (${tick(id)})`);
  L.push('', '## Patterns that work', '');
  L.push('1. Cover (`gfm-cover`) → this week at a glance (`gfm-kpi-grid` with `<GfmKpiGrid />`) → one chart with its meaning (`gfm-chart-insight`) → three focuses (`gfm-three-column`) → a question for the group (`gfm-hero`).');
  L.push('2. A comparison slide (`gfm-comparison` with two `GfmBigNumber`) before a ranked chart (`preset="ranked-bar"`).');
  L.push('3. Close with `gfm-hero` and one invitation.', '');
  return L.join('\n');
}

export function promptText(m) {
  const L = [];
  L.push(`Create a GFM Slidev presentation (GFM AI PRESENTATION SPEC v${m.version}).`, '');
  L.push('Return ONLY the complete slides.md as plain text: no explanation, no code fence around it.', '');
  L.push('Rules:');
  L.push('- Slides are separated by a line with three dashes (---). The first block is the deck settings and the first slide settings: theme: default, title, layout, fonts: { provider: none, sans: Inter }, transition: fade.');
  L.push('- Use the GFM layouts and components below. Do not import packages, add <script> blocks, use <iframe>, inline event handlers or external scripts. Do not invent components or settings.');
  L.push('- A layout\'s heading is the setting "heading" (Slidev keeps "title" for itself). Parts of a slide are started with a line like ::right::.');
  L.push('- Pictures only from files the deck already has (a path like /photo.jpg). Never invent mission numbers: use <GfmKpiGrid /> for key indicators or label example values as examples.');
  L.push('- Write for a video call: few words, one idea per slide. Speaker notes go in an HTML comment at the end of a slide.', '');
  L.push('Layouts: ' + [...m.layouts.map(l => `${l.name} [${l.props.map(p => p.name).join(', ')}${l.slots.length > 1 ? `; parts ${l.slots.slice(1).map(s => `::${s}::`).join(' ')}` : ''}]`), ...m.slidevLayouts.filter(n => ['default', 'center', 'cover', 'section', 'two-cols', 'two-cols-header', 'end', 'quote', 'fact', 'statement'].includes(n))].join('; ') + '.', '');
  L.push('Components:');
  for (const c of m.components.filter(c => c.name.startsWith('Gfm'))) L.push(`- ${c.name}${c.props.length ? ` (${c.props.filter(p => !p.hidden).map(p => p.name + (p.options ? `=${p.options.join('|')}` : '')).join(', ')})` : ''}: ${c.description.split('.')[0]}.`);
  L.push('- MissionChart: <MissionChart chart-id="c1" preset="trend" :height="330" :rows="[\'Week, Value\', \'Aug 3, 12\', \'Aug 10, 15\']" />');
  L.push(`  preset: ${m.chart.kinds.filter(k => k.group === 'kind').map(k => k.id).join(', ')}, or type-<name> (${m.chart.kinds.filter(k => k.group === 'type').map(k => k.id.slice(5)).join(', ')}).`);
  L.push('  Optional: :calc=\'[{"name":"Rate","formula":"[A] / [B]","format":"percent"}]\' (functions: ' + Object.keys(m.chart.functions).join(', ') + '), :shape=\'{"only":["A"],"sort":"desc","top":5}\', :story=\'[{"label":"Step 1","shape":{"only":["A"]}},{"label":"All","shape":{}}]\' for a chart that changes with each click.', '');
  L.push('Example slide:', '---', 'layout: gfm-chart-insight', 'heading: New people being taught', 'kicker: Trend', '---', '', '<MissionChart chart-id="t1" preset="trend" :height="330" :rows="[\'Week, Taught\', \'Aug 3, 12\', \'Aug 10, 15\']" />', '', '::right::', '', '<GfmInsight>Teaching rose two weeks in a row.</GfmInsight>', '');
  L.push('Now create the presentation about: ');
  return L.join('\n');
}

const out = (name, text) => fs.writeFileSync(path.join(ROOT, 'ai', name), text.endsWith('\n') ? text : text + '\n');

if (process.argv[1] && pathToFileURL(process.argv[1]).href === import.meta.url) {
  const YAML = (await import('yaml')).default;
  const manifest = await buildManifest(YAML);
  fs.mkdirSync(path.join(ROOT, 'ai'), { recursive: true });
  out('gfm-spec.json', JSON.stringify(manifest, null, 1));
  out('gfm-ai-spec-v1.md', specMarkdown(manifest));
  out('gfm-ai-prompt.txt', promptText(manifest));
  console.log(`spec v${manifest.version}: ${manifest.layouts.length} layouts, ${manifest.components.length} components`);
}
