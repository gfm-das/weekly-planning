// The overlay is wired into the live DataEase front (dataease/web/default.conf, dataease/compose.yml, web/gfm/).
// Text checks only; the real nginx check is `nginx -t` in a throw-away nginx:alpine (README.md, Tests).
//   node --test "dataease/i18n/tests/*.test.mjs"
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const dataease = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const read = file => fs.readFileSync(path.join(dataease, file), 'utf8');
const conf = read('web/default.conf');
const code = conf.replace(/#.*$/gm, '');

// The body of a location block (no nested blocks inside our locations except "if (...) { return ...; }").
function location(match) {
  const at = code.indexOf(match);
  assert.ok(at >= 0, `default.conf has ${match}`);
  let depth = 0;
  for (let i = code.indexOf('{', at); i < code.length; i += 1) {
    if (code[i] === '{') depth += 1;
    if (code[i] === '}' && --depth === 0) return code.slice(at, i + 1);
  }
  throw new Error('unbalanced');
}

test('default.conf includes the language files inside its server block, before DataEase\'s own locations', () => {
  const include = code.indexOf('include /etc/nginx/gfm-i18n/web-i18n.conf;');
  assert.ok(include > code.indexOf('server {'), 'inside the server block');
  assert.ok(include < code.indexOf('location / {'), 'before the catch-all location');
  assert.equal(code.split('include /etc/nginx/gfm-i18n/web-i18n.conf;').length, 2, 'once');
});

test('the app pages get boot.js first and the language script at the end of <head>, both in their own location', () => {
  const app = location('location ~ ^/(index\\.html|mobile\\.html)?$');
  const filters = [...app.matchAll(/sub_filter '([^']+)' '([^']+)';/g)].map(m => [m[1], m[2]]);
  assert.deepEqual(filters, [
    ['<head>', '<head><script src="/gfm/boot.js"></script>'],
    ['</head>', '<script src="/gfm-i18n/gfm-i18n.js"></script></head>'],
  ]);
  assert.match(app, /sub_filter_once on;/);
  assert.match(app, /proxy_set_header Accept-Encoding "";/, 'the page comes uncompressed, so it can be changed');
  assert.match(app, /auth_request \/gfm-gate-check;/, 'the app pages still need the portal sign-in');
});

test('/gfm-start passes ?gfmLang= on to the gate', () => {
  assert.match(location('location = /gfm-start'), /proxy_pass http:\/\/\$gate_host:8099\/start\$is_args\$args;/);
});

test('web-i18n.conf serves exactly the script and the 14 language files, without the sign-in, nothing else', () => {
  const web = read('i18n/web-i18n.conf').replace(/#.*$/gm, '');
  assert.match(web, /location ~ \^\/gfm-i18n\/\(gfm-i18n\\\.js\|\(\?:en\|de\|es\|fr\|pt\|uk\|ru\|it\|tr\|fa\|ro\|sv\|da\|ar\)\\\.json\)\$ \{/);
  assert.match(web, /alias \/etc\/nginx\/gfm-i18n\/\$1;/);
  assert.match(web, /location \/gfm-i18n\/ \{\s*return 404;\s*\}/);
  assert.doesNotMatch(web, /sub_filter|proxy_pass/);
});

test('compose.yml mounts dataease/i18n read-only where default.conf includes it from', () => {
  const compose = read('compose.yml');
  const web = compose.slice(compose.indexOf('\n  web:'), compose.indexOf('\n  dbproxy:'));
  assert.match(web, /- \.\/i18n:\/etc\/nginx\/gfm-i18n:ro/);
  assert.match(web, /- \.\/web\/default\.conf:\/etc\/nginx\/conf\.d\/default\.conf:ro/);
  assert.doesNotMatch(web, /\.\/i18n:\/etc\/nginx\/conf\.d/, 'not in conf.d (nginx would load web-i18n.conf at the wrong level)');
  const gate = compose.slice(compose.indexOf('\n  gate:'), compose.indexOf('\n  web:'));
  assert.match(gate, /- \.\/lib:\/gate\/lib:ro/, 'the gate reads lib/languages.mjs from its lib mount');
});

test('the front\'s own pages load the language script too', () => {
  for (const page of ['signin.html', 'refused.html', 'starting.html']) {
    const html = read(`web/gfm/${page}`);
    assert.match(html, /<script src="\/gfm-i18n\/gfm-i18n\.js"><\/script>\s*<\/head>/, page);
  }
});
