// The public name https://dashboards.<the mission's public domain> (a Cloudflare tunnel route to 8088, round 10,
// docs/handoff/round10/public-dashboards.md): the files that carry it, read as text. No network, no packages:
//   node --test "tests/*.test.mjs"   (in dataease/)
// The browser run (the portal's frame, the cookie for the domain, sign-out) is portal-api/tests/edge_public_dashboards.ps1.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const read = name => fs.readFileSync(path.join(HERE, '..', name), 'utf8');
const conf = read('web/default.conf');
const compose = read('compose.yml');
// The office address is a setting (GFM_HOST_IP, default this server's), written as ${GFM_HOST_IP:-192.168.1.20}.
const HOST = '${GFM_HOST_IP:-192.168.1.20}';
const OFFICE = `'self' http://localhost:8070 http://127.0.0.1:8070 http://${HOST}:8070`;

test('compose.yml: the portal on its public address may frame DataEase; the office addresses stay', () => {
  assert.ok(compose.includes(`DATAEASE_HTTP_FRAMEANCESTORS: \${GFM_PORTAL_FRAME_ORIGINS:-${OFFICE}\${GFM_PUBLIC_DOMAIN:+ https://$GFM_PUBLIC_DOMAIN https://www.$GFM_PUBLIC_DOMAIN}}`));
  assert.ok(compose.includes(`DATAEASE_ORIGINLIST: \${GFM_DATAEASE_ORIGINS:-http://localhost:8088,http://127.0.0.1:8088,http://${HOST}:8088\${GFM_PUBLIC_DOMAIN:+,https://dashboards.$GFM_PUBLIC_DOMAIN}}`));
  // Still one published port, the web front's; DataEase, MySQL and the gate publish none.
  assert.equal((compose.match(/^\s+ports:/gm) || []).length, 1);
  assert.match(compose, /\$\{GFM_DATAEASE_BIND:-0\.0\.0\.0\}:\$\{GFM_DATAEASE_PORT:-8088\}:80/);
});

test('default.conf: a name "dashboards.<domain>" only (not the office addresses, not the bare domain)', () => {
  const rule = /map \$host \$gfm_public_host \{\s*~\*(\S+) 1;\s*default "";\s*\}/.exec(conf);
  assert.ok(rule, 'the map of the public name');
  const pattern = new RegExp(rule[1], 'i');
  for (const host of ['dashboards.example.org', 'DASHBOARDS.Example.ORG', 'dashboards.example.org']) assert.ok(pattern.test(host), host);
  for (const host of ['192.168.1.20', 'localhost', 'example.org', 'www.example.org', 'dashboards', 'dashboards.',
    'xdashboards.example.org', 'dashboardsxexample.org', 'dashboards.example.org:8088']) {
    assert.ok(!pattern.test(host), host);
  }
});

test('default.conf: /gfm-signout also clears the domain cookie on the public name, nothing new on the office addresses', () => {
  const signout = /location = \/gfm-signout \{([^}]*)\}/.exec(conf)[1];
  assert.equal((signout.match(/add_header Set-Cookie/g) || []).length, 2);
  assert.match(signout, /add_header Set-Cookie "gfm_dataease=; Path=\/; Max-Age=0; Expires=Thu, 01 Jan 1970 00:00:00 GMT; HttpOnly; SameSite=Strict" always;/);
  assert.match(signout, /add_header Set-Cookie \$gfm_signout_domain_cookie always;/);
  const map = /map \$gfm_public_host \$gfm_signout_domain_cookie \{([^}]*)\}/.exec(conf)[1];
  assert.match(map, /1 "gfm_dataease=; Domain=\$gfm_site_domain; Path=\/; Max-Age=0; Expires=[^"]+; HttpOnly; Secure; SameSite=Strict";/);
  assert.match(map, /default "";/, 'empty on the office addresses: nginx leaves the header out');
});

test('default.conf: the gate health is not answered on the public name; every DataEase path still needs the sign-in', () => {
  assert.match(/location = \/gfm-gate-health \{([^}]*\}[^}]*)\}/.exec(conf)[1], /if \(\$gfm_public_host\) \{ return 404; \}/);
  for (const location of ['location = /gfm-start {', 'location ~ ^/(index\\.html|mobile\\.html)?$ {', 'location /de2api/ {', 'location / {']) {
    const at = conf.indexOf(location);
    assert.ok(at > 0, location);
    assert.match(conf.slice(at, conf.indexOf('\n    }', at)), /auth_request \/gfm-gate-check;/, location);
  }
  assert.match(conf, /location \/de2api\/ \{\s*if \(\$http_sec_fetch_site ~\* "\^\(same-site\|cross-site\)\$"\) \{ return 403; \}/,
    'another subdomain (same-site) cannot use the cookie against the API');
});

test('the small pages: the portal is https://<domain> on the name dashboards.<domain>, port 8070 elsewhere', () => {
  const portalFor = (source, hostname, protocol = 'http:') => {
    const document = { createElement: () => ({}), head: { appendChild(s) { document.src = s.src; } } };
    vm.runInNewContext(source, { location: { hostname, protocol }, document });
    return document.src;
  };
  for (const page of ['signin.html', 'refused.html', 'starting.html']) {
    const script = /<script>(\(function\(\)\{var s=document\.createElement[^<]*)<\/script>/.exec(read('web/gfm/' + page))[1];
    assert.equal(portalFor(script, 'dashboards.example.org', 'https:'), 'https://example.org/i18n.js?v=5', page);
    assert.equal(portalFor(script, '192.168.1.20'), 'http://192.168.1.20:8070/i18n.js?v=5', page);
    assert.equal(portalFor(script, 'example.org', 'https:'), 'https://example.org:8070/i18n.js?v=5', page);
  }
  const signin = read('web/gfm/signin.js');
  const linkFor = (hostname, protocol) => {
    const link = {};
    const window = { parent: null };
    window.parent = window; // not in a frame: only the link is set
    vm.runInNewContext(signin, { location: { hostname, protocol }, document: { getElementById: id => (id === 'portal' ? link : {}) }, window, sessionStorage: { getItem: () => null } });
    return link.href;
  };
  assert.equal(linkFor('dashboards.example.org', 'https:'), 'https://example.org/#insights');
  assert.equal(linkFor('192.168.1.20', 'http:'), 'http://192.168.1.20:8070/#insights');
  assert.equal(linkFor('localhost', 'http:'), 'http://localhost:8070/#insights');
});
