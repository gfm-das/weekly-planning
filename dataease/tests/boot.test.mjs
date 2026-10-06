// /gfm/boot.js, round 10 (docs/handoff/round10/public-everything.md): the dashboards bar and the way back after
// DataEase's "Log out" load the page again at the NEW address. Before, a reload straight after location.replace()
// reloaded the old one (Edge), so the bar's other dashboards and "All dashboards and Edit" did nothing.
// Runs boot.js in a small pretend browser (node:vm). No network, no packages:
//   node --test "tests/*.test.mjs"   (in dataease/)
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const BOOT = fs.readFileSync(path.join(HERE, '..', 'web', 'gfm', 'boot.js'), 'utf8');
const conf = fs.readFileSync(path.join(HERE, '..', 'web', 'default.conf'), 'utf8');

// A pretend browser with Edge's behaviour: replace() to an address that differs after '#' changes the address and
// fires "hashchange" a moment later (a task); reload() loads whatever the address is at that moment.
function browser(hash) {
  const listeners = {};
  const timers = [];
  const loads = [];
  const elements = [];
  const element = tag => {
    const el = { tag, children: [], attrs: {}, className: '', textContent: '', listeners: {}, classList: { add() {}, remove() {} },
      setAttribute(k, v) { this.attrs[k] = String(v); }, getAttribute(k) { return this.attrs[k] ?? null; },
      appendChild(c) { this.children.push(c); c.parentNode = this; return c; }, removeChild() {},
      addEventListener(type, fn) { (this.listeners[type] ||= []).push(fn); } };
    Object.defineProperty(el, 'href', { get() { return this.attrs.href; }, set(v) { this.attrs.href = v; } });
    elements.push(el);
    return el;
  };
  const body = element('body');
  const location = {
    pathname: '/', search: '', hash,
    get href() { return 'https://dashboards.example' + this.pathname + this.search + this.hash; },
    replace(url) {
      const at = url.indexOf('#');
      const next = at < 0 ? '' : url.slice(at);
      const changed = next !== this.hash;
      this.hash = next;
      if (changed) timers.push({ ms: 0, fn: () => (listeners.hashchange || []).slice().forEach(fn => fn({})) });
    },
    reload() { loads.push(this.hash); },
  };
  const storage = () => { const m = new Map(); return { getItem: k => m.get(k) ?? null, setItem: (k, v) => m.set(k, String(v)) }; };
  const window = {
    addEventListener(type, fn) { (listeners[type] ||= []).push(fn); },
    removeEventListener(type, fn) { listeners[type] = (listeners[type] || []).filter(f => f !== fn); },
  };
  const context = {
    window, location, localStorage: storage(), sessionStorage: storage(),
    document: { title: '', head: element('head'), body, documentElement: { classList: { add() {}, remove() {} } },
      createElement: element, getElementById: () => null, addEventListener() {} },
    fetch: () => new Promise(() => {}),
    setTimeout: (fn, ms) => { timers.push({ ms, fn }); return timers.length; },
    Date, JSON, Number, String, RegExp, encodeURIComponent, decodeURIComponent,
  };
  vm.runInNewContext(BOOT, context);
  // Runs the waiting tasks: the ones due first first (hashchange before the 300 ms fallback).
  const run = () => { while (timers.length) { timers.sort((a, b) => a.ms - b.ms); timers.shift().fn(); } };
  return { location, loads, run, elements };
}

const barLink = (b, text) => b.elements.find(el => el.tag === 'a' && el.textContent === text);

test('the bar: "All dashboards and Edit" loads the page again at the panel address, once', () => {
  const b = browser('#/preview?dvId=1150001');
  const link = barLink(b, 'All dashboards and Edit');
  assert.ok(link, 'the bar has the link');
  let prevented = false;
  link.listeners.click[0].call(link, { preventDefault() { prevented = true; } });
  assert.ok(prevented);
  assert.deepEqual(b.loads, [], 'no reload before the new address is in place');
  b.run();
  assert.deepEqual(b.loads, ['#/panel/index?dvId=1150001']);
});

test('the bar: the link of the open dashboard (same address) still loads the page again, once', () => {
  const b = browser('#/preview?dvId=1150001');
  const link = { getAttribute: () => '/#/preview?dvId=1150001' };
  barLink(b, 'All dashboards and Edit').listeners.click[0].call(link, { preventDefault() {} });
  b.run();
  assert.deepEqual(b.loads, ['#/preview?dvId=1150001']);
});

test('the bar: another dashboard (tab) loads the page again at that dashboard', () => {
  const b = browser('#/preview?dvId=1150001');
  const link = { getAttribute: () => '/#/preview?dvId=1150002' };
  barLink(b, 'All dashboards and Edit').listeners.click[0].call(link, { preventDefault() {} });
  b.run();
  assert.deepEqual(b.loads, ['#/preview?dvId=1150002']);
});

test('after DataEase\'s own "Log out" the page goes back to where it was (the new address), once', () => {
  const b = browser('#/login?redirect=%2Fpanel%2Findex');
  b.run();
  assert.deepEqual(b.loads, ['#/panel/index']);
});

test('default.conf: boot.js is asked for with a version (old copies in browsers are not used) and never kept', () => {
  assert.match(conf, /sub_filter '<head>' '<head><script src="\/gfm\/boot\.js\?v=2"><\/script><script src="\/gfm\/preload\.js\?v=1"><\/script>';/);
  const gfm = /location \/gfm\/ \{([^}]*)\}/.exec(conf)[1];
  assert.match(gfm, /add_header Cache-Control "no-store" always;/);
  assert.doesNotMatch(gfm, /no-cache/);
});

test('default.conf: DataEase\'s websocket may upgrade, still behind the sign-in', () => {
  const root = /\n    location \/ \{([^}]*)\}/.exec(conf)[1];
  assert.match(root, /auth_request \/gfm-gate-check;/);
  assert.match(root, /proxy_set_header Upgrade \$http_upgrade;/);
  assert.match(root, /proxy_set_header Connection \$connection_upgrade;/);
  assert.match(root, /proxy_set_header X-DE-TOKEN "";/);
});

test('default.conf: the versioned DataEase scripts and styles are kept a year by the viewer browser only, behind the sign-in (round 12)', () => {
  const found = /location ~ \^\/\(assets\/\(chunk\|css\)\/\|js\/\)[^{]*\{([^}]*)\}/.exec(conf);
  assert.ok(found, 'a location for the versioned files');
  const block = found[1];
  assert.match(block, /auth_request \/gfm-gate-check;/);
  assert.match(block, /proxy_hide_header Cache-Control;/);
  assert.match(block, /add_header Cache-Control "private, max-age=31536000, immutable" always;/);
  assert.doesNotMatch(block, /public/);
  // The chart library is rewritten here: it keeps asking whether it changed.
  const start = conf.indexOf('location ~ ^/assets/chunk/antv');
  const antv = conf.slice(start, start + conf.slice(start).search(/\r?\n    \}\r?\n/));  // its sub_filter lines hold braces of their own
  assert.match(antv, /Cache-Control "no-cache"/);
  assert.ok(conf.indexOf(antv) < conf.indexOf(block), 'the chart library location comes first (nginx uses the first matching pattern)');
});

test('preload.js asks for the script and style files of the Dashboards page at once', () => {
  const src = fs.readFileSync(path.join(HERE, '..', 'web', 'gfm', 'preload.js'), 'utf8');
  const links = [];
  const document = {head: {appendChild: link => links.push(link)}, createElement: () => ({})};
  vm.runInNewContext(src, {document});
  assert.ok(links.length > 100);
  assert.ok(links.every(l => /^\/(assets\/(chunk|css)\/|js\/)[^?]*-\d+\.\d+\.\d+-dataease\.(js|css)$/.test(l.href)));
  assert.ok(links.some(l => l.rel === 'modulepreload'));
  assert.ok(links.filter(l => /\.css$/.test(l.href)).every(l => l.rel === 'preload' && l.as === 'style'));
});
