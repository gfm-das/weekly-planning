// The portal Whiteboard's two frames on the Presentation Manager (round 6):
//   GET /whiteboard/chart    one live chart or key number (manager/whiteboard-chart.mjs, drawn by chart-engine.mjs)
//   GET /whiteboard/builder  the chart builder placing its chart on a board (manager/whiteboard-builder.mjs)
//
// 1. Plain Node: the paths, the frame-ancestors list, the pages; reading a chart from the frame address (the
//    address portal/whiteboard/board-core.js writes), what the frame draws for round-6 charts, key numbers and
//    charts the older builder placed, and the builder's message check. The frame modules are imported from a
//    flat copy of the builder files, exactly as the manager serves them at /_manager/chart/<name>.
// 2. The real manager (tests/helpers/manager-harness.mjs: a copy in a temporary folder with stand-ins for
//    Slidev's packages, Supabase and portal-api): the frames answer managers only, may be framed by the portal only,
//    and their code is served; a chart's numbers without a deck are for managers only. Needs a POSIX shell
//    (node:24-alpine); skipped on Windows.
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { after, before, test } from 'node:test';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { builderFiles } from '../manager/chart-access.mjs';
import { chartPageCsp, frameAncestors, whiteboardFrame, whiteboardFramePage } from '../manager/whiteboard-frames.mjs';
import * as board from '../../portal/whiteboard/board-core.js';
import { startManager, startStub, supabaseAnswer, token } from './helpers/manager-harness.mjs';

const MANAGER_DIR = fileURLToPath(new URL('../manager/', import.meta.url));
const ecStat = createRequire(import.meta.url)('../manager/vendor/ecStat.min.js');
const ctx = { dark: false, font: 'Inter', animate: false, ecStat, width: 560, height: 340 };
const ANSWER = { table: { labels: ['2026-08-02', '2026-08-09', '2026-08-16'], series: [{ name: 'New people being taught', values: [3, 5, 4] }, { name: 'Goal set the week before', values: [4, 4, 5], role: 'goal' }] }, meta: { by: 'week', unit: 'count', level: 'mission' } };
const SPEC = { measures: ['friends_found.actual', 'friends_found.previous_goal'], weeks: 12 };

let flat, frame, builderFrame;
before(async () => {
  flat = await fs.mkdtemp(path.join(os.tmpdir(), 'whiteboard-flat-'));
  for (const [name, file] of Object.entries(builderFiles(MANAGER_DIR))) await fs.copyFile(file, path.join(flat, name));
  frame = await import(pathToFileURL(path.join(flat, 'whiteboard-chart.mjs')).href);
  builderFrame = await import(pathToFileURL(path.join(flat, 'whiteboard-builder.mjs')).href);
});
after(async () => { if (flat) await fs.rm(flat, { recursive: true, force: true }); });

// ---- 1. Plain Node ----

test('the two frame paths, nothing else', () => {
  assert.equal(whiteboardFrame('/whiteboard/chart'), 'chart');
  assert.equal(whiteboardFrame('/whiteboard/builder'), 'builder');
  for (const p of ['/whiteboard/', '/whiteboard/chart/', '/whiteboard/charts', '/whiteboard/__proto__', '/whiteboard/constructor', '/p/whiteboard/chart', ''])
    assert.equal(whiteboardFrame(p), null, p);
});

test('only the portal may frame them: its configured addresses and the portal port on the host used', () => {
  const header = frameAncestors('192.168.1.20:3030', new Set(['http://localhost:8070']), new Set(['http:8070']));
  assert.equal(header, "frame-ancestors 'self' http://localhost:8070 http://192.168.1.20:8070");
  assert.equal(frameAncestors('evil host;script-src *', new Set(['http://localhost:8070']), new Set(['http:8070'])), "frame-ancestors 'self' http://localhost:8070");
  assert.equal(frameAncestors('[::1]:3030', new Set(), new Set(['https:'])), "frame-ancestors 'self' https://[::1]");
});

test('the pages load the session bridge and their module, and carry no data', () => {
  const chart = whiteboardFramePage('chart', 'data:image/svg+xml,x', 'abc123==');
  assert.match(chart, /<script src="\/_manager\/portal-bridge.js"><\/script>/);
  assert.match(chart, /<script type="module" nonce="abc123==">import \{ startChartFrame \} from '\/_manager\/chart\/whiteboard-chart.mjs'/);
  assert.match(chart, /id="plot"/);
  // Round 9: the chart frame asks for its code and the chart libraries at once, from the manager's own files only.
  const preloads = [...chart.matchAll(/<link rel="(modulepreload|preload)"( as="script")? href="([^"]+)" \/>/g)].map(m => m[3]);
  assert.deepEqual(preloads, ['whiteboard-chart.mjs', 'chart-core.mjs', 'chart-engine.mjs', 'formula.mjs', 'chart-presets.mjs', 'chart-spec.mjs', 'safe-chart-option.mjs', 'echarts.min.js', 'ecStat.min.js'].map(name => `/_manager/chart/${name}`));
  const builder = whiteboardFramePage('builder', 'data:image/svg+xml,x', 'abc123==');
  assert.match(builder, /<script type="module" nonce="abc123==">import \{ startBuilderFrame \} from '\/_manager\/chart\/whiteboard-builder.mjs'/);
  assert.doesNotMatch(chart + builder, /token|Bearer/i);
  assert.match(whiteboardFramePage('chart', 'x', '"><script>'), /nonce="script"/, 'nothing odd gets into the page');
});

test('round 8 review: the pages that draw charts on the manager address run only their own scripts', () => {
  const csp = chartPageCsp('192.168.1.20:3030', new Set(['http://localhost:8070']), new Set(['http:8070']), { nonce: 'n0nce', frames: ['http://192.168.1.20:8089'] });
  const parts = Object.fromEntries(csp.split('; ').map(part => [part.split(' ')[0], part.split(' ').slice(1)]));
  assert.deepEqual(parts['script-src'], ["'self'", "'nonce-n0nce'", 'http://localhost:8070', 'http://192.168.1.20:8070'], 'no unsafe-inline: an injected onerror= or <script> never runs');
  assert.deepEqual(parts['connect-src'], ["'self'", 'http://localhost:8070', 'http://192.168.1.20:8070'], 'talks only to itself and the portal');
  assert.deepEqual(parts['img-src'], ["'self'", 'data:', 'blob:'], 'no pictures from elsewhere (nothing can be sent away in an address)');
  assert.deepEqual(parts['frame-src'], ['http://192.168.1.20:8089'], "/studio's editor frame on the deck address");
  assert.deepEqual(parts['object-src'], ["'none'"]);
  assert.deepEqual(parts['base-uri'], ["'none'"]);
  assert.deepEqual(parts['frame-ancestors'], ["'self'", 'http://localhost:8070', 'http://192.168.1.20:8070']);
  assert.match(chartPageCsp('h:3030', new Set(), new Set(), { nonce: 'x' }), /frame-src 'none'/);
});

test('the frame reads the chart the board wrote after "#" (umlauts included)', () => {
  const model = { v: 2, source: 'mission', spec: SPEC, option: { title: { text: 'Neue Personen – Zürich' }, series: [{ type: 'bar' }] } };
  const url = board.chartFrameUrl('http://h:3030', model, false);
  assert.equal(board.encodeChartModel(model), frame.encodeModel(model), 'the page and the frame encode alike');
  const { model: read, problem } = frame.decodeModel('#' + url.split('#')[1]);
  assert.equal(problem, '');
  assert.equal(read.props.option.title.text, 'Neue Personen – Zürich');
  assert.equal(read.props.chartId, 'whiteboard', 'drawn from its option (round 6)');
  assert.equal(read.spec.includeCurrent, true, 'the query is checked like a slide\'s (defaults filled in)');
  assert.equal(read.props.query, read.spec);
});

test('what the frame refuses to draw, in plain sentences', () => {
  const cases = [
    [null, 'This chart has no settings'],
    [{ v: 2, spec: SPEC }, 'This chart has no settings'],
    [{ v: 2, option: { series: [{ type: 'bar' }] } }, 'This chart has no numbers'],
    [{ v: 2, option: { series: [{ type: 'bar' }] }, rows: [] }, 'This chart has no numbers'],
    [{ v: 2, option: { series: [{ type: 'bar' }] }, spec: { measures: [] } }, "The chart's settings have a mistake"],
    [{ v: 2, option: { series: [{ type: 'bar' }] }, rows: Array(501).fill('a,1') }, 'The table of this chart is too long'],
    [{ v: 2, option: { series: [{ type: 'bar' }] }, rows: [{ not: 'text' }] }, 'The table of this chart is too long'],
    [{ v: 2, option: { title: { text: 'x'.repeat(50000) }, series: [{ type: 'bar' }] }, rows: ['a,1'] }, 'too long'],
    [{ props: { type: 'bar' }, option: 'x'.repeat(50000), rows: ['a,1'] }, 'too long'],
  ];
  for (const [raw, start] of cases) {
    const { model, problem } = frame.checkModel(raw);
    assert.equal(model, null, JSON.stringify(raw)?.slice(0, 80));
    assert.ok(problem.includes(start), `${problem} / ${start}`);
  }
  assert.match(frame.decodeModel('#not base64 json').problem, /cannot be read/);
  assert.match(frame.decodeModel('#' + 'A'.repeat(70000)).problem, /too long/);
  assert.match(frame.decodeModel('').problem, /no settings/);
});

test('the builder refuses exactly what the frame could not draw, with its own sentence', async () => {
  const { tableRows } = await import(pathToFileURL(path.join(flat, 'chart-builder-core.mjs')).href);
  const option = { series: [{ type: 'bar' }] };
  const table = (n, width = 6) => tableRows(['Week\tFriends', ...Array.from({ length: n }, (_, i) => `W${i}\t${String(i).padStart(width, '1')}`)].join('\n'));
  const models = [
    { v: 2, source: 'table', rows: table(2), option },
    { v: 2, source: 'table', rows: table(499), option },
    { v: 2, source: 'table', rows: table(500), option },
    { v: 2, source: 'table', rows: table(501), option },
    { v: 2, source: 'table', rows: table(1200), option },
    { v: 2, source: 'table', rows: table(450, 120), option },
    { v: 2, source: 'table', rows: ['A\tB', `x\t${'1'.repeat(4001)}`], option },
    { v: 2, source: 'table', rows: table(3), option: { title: { text: 'x'.repeat(41000) }, series: [{ type: 'bar' }] } },
    { v: 2, source: 'mission', spec: SPEC, option },
  ];
  for (const model of models) {
    const said = frame.boardLimitProblem(model);
    const drawn = frame.decodeModel('#' + board.encodeChartModel(model));
    assert.equal(said === '', drawn.model !== null, `${model.rows?.length ?? 'mission'} rows: builder "${said}" / frame "${drawn.problem}"`);
  }
  assert.equal(frame.boardLimitProblem(models[1]), '', '500 short rows (headings and 499 weeks) fit');
  assert.match(frame.boardLimitProblem(models[2]), /at most 500 rows, headings included; this one has 501\./);
  assert.match(frame.boardLimitProblem(models[4]), /this one has 1201\./);
  assert.match(frame.boardLimitProblem(models[5]), /too large for the whiteboard/);
  assert.match(frame.boardLimitProblem(models[6]), /longer than 4,000 characters/);
  assert.match(frame.boardLimitProblem(models[7]), /too long for the whiteboard/);
  // The builder asks the frame's check before "Add to the whiteboard" and under a pasted table.
  const builder = await fs.readFile(path.join(MANAGER_DIR, 'chart-builder.mjs'), 'utf8');
  const wiring = await fs.readFile(path.join(MANAGER_DIR, 'whiteboard-builder.mjs'), 'utf8');
  assert.ok(builder.includes('const problem = this.target?.check?.(model)') && builder.includes('this.boardProblem()'));
  assert.match(wiring, /import \{ boardLimitProblem \} from '\.\/whiteboard-chart\.mjs'/);
  assert.match(wiring, /check: boardLimitProblem/);
});

test('round-6 charts: a bar chart of mission numbers, a pasted table, a key number', () => {
  const bar = frame.checkModel({ v: 2, source: 'mission', spec: SPEC, option: { title: { text: 'New people being taught' }, series: [{ type: 'bar' }] } }).model;
  const loading = frame.chartView(bar, null)
  assert.equal(loading.problem, '', 'no mistake while its numbers load (the frame says it is loading)');
  const drawn = frame.chartView(bar, ANSWER);
  assert.equal(drawn.problem, '');
  const option = frame.frameOption(drawn.view, ctx);
  assert.ok(option.series.some(s => s.type === 'bar'), 'bars');
  assert.equal(frame.sizeAware(bar), false);

  const table = frame.checkModel({ v: 2, source: 'table', rows: ['Week\tFriends', 'Aug 3\t12', 'Aug 10\t15'], option: { series: [{ type: 'line' }] } }).model;
  const view = frame.chartView(table, null);
  assert.equal(view.problem, '');
  assert.ok(frame.frameOption(view.view, ctx).series.some(s => s.type === 'line'));

  const tile = frame.checkModel({ v: 2, source: 'mission', spec: SPEC, option: { gfm: { kind: 'tile' }, title: { text: 'New people being taught' }, series: [{ type: 'line' }] } }).model;
  assert.equal(frame.sizeAware(tile), true, 'a key number is laid out again when its box changes size');
  const tileOption = frame.frameOption(frame.chartView(tile, ANSWER).view, ctx);
  assert.ok(tileOption && JSON.stringify(tileOption).includes('4'), 'the key number shows the last week');
});

test('round 8 review: the frame (on the manager address) never draws a chart setting as HTML', () => {
  const evil = '<img src=x onerror="parent.postMessage(1,\'*\')">';
  const model = frame.checkModel({ v: 2, source: 'table', rows: ['Week\tFriends', 'Aug 3\t12'], option: { title: { text: 'T', link: 'javascript:alert(1)' }, tooltip: { formatter: evil }, series: [{ type: 'bar', tooltip: { formatter: evil } }] } }).model;
  const option = frame.frameOption(frame.chartView(model, null).view, ctx);
  assert.equal(option.tooltip.renderMode, 'richText');
  assert.doesNotMatch(JSON.stringify(option), /<img|javascript:/);
  assert.ok(option.series.some(s => s.type === 'bar'), 'the chart itself is drawn');
});

test('a chart the older builder placed is drawn the older way', () => {
  const older = frame.checkModel({ v: 1, props: { type: 'line', title: 'Older', trend: 'linear' }, spec: SPEC }).model;
  assert.equal(older.props.type, 'line');
  const { view, problem } = frame.chartView(older, ANSWER);
  assert.equal(problem, '');
  assert.equal(view.mode, 'legacy');
  assert.ok(frame.frameOption(view, ctx).series.length >= 2);
  assert.equal(frame.sizeAware(frame.checkModel({ v: 1, props: { type: 'tile' }, rows: ['Week, A', 'Aug 3, 1'] }).model), true);
});

test('the builder frame listens only to the page holding it, on a portal address', () => {
  const parent = {};
  const portals = ['http://localhost:8070', 'http://192.168.1.20:8070'];
  assert.ok(builderFrame.fromPortal({ source: parent, origin: 'http://localhost:8070' }, parent, portals));
  assert.ok(!builderFrame.fromPortal({ source: {}, origin: 'http://localhost:8070' }, parent, portals), 'another window');
  assert.ok(!builderFrame.fromPortal({ source: parent, origin: 'http://evil.test' }, parent, portals), 'another address');
  assert.ok(!builderFrame.fromPortal(null, parent, portals));
  assert.deepEqual(Object.values(builderFrame.MESSAGES).sort(), ['gfm-whiteboard-builder-closed', 'gfm-whiteboard-builder-open', 'gfm-whiteboard-builder-ready', 'gfm-whiteboard-chart']);
});

test('the builder has a whiteboard mode that hands the chart back instead of writing a slide', async () => {
  const source = await fs.readFile(path.join(MANAGER_DIR, 'chart-builder.mjs'), 'utf8');
  for (const piece of ['this.target = options.target', 'openForBoard()', 'boardModel()', "'Add to the whiteboard'", "'Add a key number'", 'await this.target.save(this.boardModel())', 'this.o.onClose?.()'])
    assert.ok(source.includes(piece), piece);
  // The key number starts as a tile of the last finished week.
  assert.match(source, /S\.q\.includeCurrent = false\s+S\.option = applyKind\(S\.option, 'tile'\)/);
});

// ---- 2. The real manager ----

const posix = process.platform !== 'win32';
const skip = posix ? false : 'needs a POSIX shell (run in node:24-alpine)';
const AP = token('user-ap'), DL = token('user-dl');
let manager, stub, managerUrl;
const dataCalls = [];

// Supabase Auth + PostgREST + portal-api: an AP (manager) and a DL (leader); chart data records who asked.
function stubAnswer(req, url, body) {
  if (url.pathname === '/rest/v1/current_user_context') {
    const id = url.searchParams.get('user_id').replace(/^eq\./, '');
    return [200, [{ user_id: id, user_active: true, app_role: id === 'user-dl' ? 'DL' : 'AP', mission_id: 1 }]];
  }
  const supabase = supabaseAnswer(req, url);
  if (supabase) return supabase;
  if (url.pathname === '/internal/presentations/check') {
    return [200, body.user_id === 'user-ap' ? { can_manage: true, role: 'AP', allowed_slugs: body.deck_slugs || [] } : { can_manage: false, role: 'DL', allowed_slugs: [] }];
  }
  if (url.pathname === '/internal/presentations/chart-data') { dataCalls.push(body.user_id); return [200, ANSWER]; }
  return [404, { error: 'stub: not found' }];
}

before(async () => {
  if (!posix) return;
  stub = await startStub(stubAnswer);
  const stubUrl = `http://127.0.0.1:${stub.address().port}`;
  manager = await startManager({ env: { SUPABASE_URL: stubUrl, PRESENTATION_ACL_API_URL: stubUrl, PRESENTATIONS_PORTAL_ORIGINS: 'http://localhost:8070', GFM_PUBLIC_DOMAIN: 'example.org' } });
  managerUrl = manager.url;
});

after(async () => {
  await manager?.stop();
  if (stub) await new Promise(r => stub.close(r));
});

const get = (pathname, as, headers = {}) => fetch(`${managerUrl}${pathname}`, { headers: { ...(as ? { Authorization: `Bearer ${as}` } : {}), ...headers }, redirect: 'manual' });

test('the frames answer managers only, and only the portal may frame them', { skip }, async () => {
  for (const kind of ['chart', 'builder']) {
    const ok = await get(`/whiteboard/${kind}`, AP);
    assert.equal(ok.status, 200, kind);
    // Round 8 review: only the page's own scripts run (a nonce, no inline handlers), and only the portal may frame it.
    const csp = ok.headers.get('content-security-policy');
    const nonce = /'nonce-([A-Za-z0-9+/=]+)'/.exec(csp)?.[1];
    assert.ok(nonce, csp);
    // Round 10: and the portal on its public addresses.
    const PUBLIC = 'https://example.org https://www.example.org';
    assert.ok(csp.endsWith(`frame-ancestors 'self' http://localhost:8070 ${PUBLIC} http://127.0.0.1:8070`), csp);
    assert.match(csp, /script-src 'self' 'nonce-[^']+' http:\/\/localhost:8070 https:\/\/example\.org https:\/\/www\.example\.org http:\/\/127\.0\.0\.1:8070;/);
    assert.doesNotMatch(csp, /script-src[^;]*'unsafe-inline'/);
    assert.match(csp, /frame-src 'none'/);
    assert.equal(ok.headers.get('cache-control'), 'no-store');
    const page = await ok.text();
    assert.match(page, new RegExp(kind === 'chart' ? 'startChartFrame' : 'startBuilderFrame'));
    assert.ok(page.includes(`<script type="module" nonce="${nonce}">`), 'its inline module carries the nonce');
    const again = (await get(`/whiteboard/${kind}`, AP)).headers.get('content-security-policy');
    assert.notEqual(/'nonce-([^']+)'/.exec(again)[1], nonce, 'a new nonce for every page');
    const leader = await get(`/whiteboard/${kind}`, DL);
    assert.equal(leader.status, 403, `a DL is refused the ${kind} frame`);
    const nobody = await get(`/whiteboard/${kind}`);
    assert.ok([401, 302, 303].includes(nobody.status), `no sign-in: ${nobody.status}`);
  }
});

test('the frames\' code is served beside the builder\'s (code only)', { skip }, async () => {
  for (const name of ['whiteboard-chart.mjs', 'whiteboard-builder.mjs', 'chart-engine.mjs', 'chart-builder.mjs']) {
    const response = await get(`/_manager/chart/${name}`, AP);
    assert.equal(response.status, 200, name);
    assert.match(response.headers.get('content-type') || '', /javascript/, name);
  }
  assert.equal((await get('/_manager/chart/whiteboards.py', AP)).status, 404);
});

test('a chart\'s numbers without a deck: managers only (the whiteboard never names a deck)', { skip }, async () => {
  const ask = as => fetch(`${managerUrl}/api/charts/data`, { method: 'POST', headers: { Authorization: `Bearer ${as}`, 'Content-Type': 'application/json' }, body: JSON.stringify({ spec: SPEC }) });
  const manager = await ask(AP);
  assert.equal(manager.status, 200);
  assert.deepEqual((await manager.json()).table.labels, ANSWER.table.labels);
  const leader = await ask(DL);
  assert.equal(leader.status, 403);
  assert.ok(!dataCalls.includes('user-dl'), 'portal-api is not even asked for a leader');
});
