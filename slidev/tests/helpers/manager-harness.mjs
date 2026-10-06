// TEST ONLY: runs the real presentation manager (manager/server.mjs) from a copy in a temporary folder, so a test can
// talk to its real routes without Slidev, Supabase or portal-api and never touches real decks:
//   - Slidev's folder is <tmp> (PRESENTATION_SLIDEV_HOME, manager/settings.mjs), so its decks are <tmp>/decks;
//   - `slidev` (<tmp>/node_modules/.bin/slidev) is a small shell stand-in: `slidev build` writes one page, and
//     starting an editor fails at once (with `editor: true` a tiny stand-in editor answers every page instead);
//   - the four packages the manager imports (http-proxy, archiver, @slidev/parser, yaml) are small stand-ins in
//     <tmp>/node_modules, enough for simple headmatter.
// Supabase Auth, PostgREST and portal-api are whatever the caller points SUPABASE_URL and PRESENTATION_ACL_API_URL
// at (startStub and supabaseAnswer below help). Needs a POSIX shell (the node:24-alpine test container).
// With `real: true` it runs the installed manager and the real Slidev instead, for the Edge check that opens really
// built decks (deck-origin/edge_deck_origin.ps1).
// Used by deck-origin.test.mjs, zone-decks.test.mjs, protected-decks.test.mjs, whiteboard.test.mjs,
// i18n-serve-library.mjs and deck-origin/serve-deck-origin.mjs.
import { spawn } from 'node:child_process';
import fs from 'node:fs/promises';
import http from 'node:http';
import net from 'node:net';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const MANAGER_DIR = fileURLToPath(new URL('../../manager/', import.meta.url));

const STUBS = {
  'http-proxy': 'export default { createProxyServer: () => ({ on() { return this; }, web() {}, ws() {} }) };\n',
  archiver: 'export class ZipArchive { on() {} pipe(res) { this.res = res; } directory() {} async finalize() { this.res.end("zip"); } }\n',
  yaml: 'export const stringify = value => JSON.stringify(String(value)) + "\\n";\n',
  // Enough of Slidev's parser for `---\\nkey: value\\n---` headmatter: the title and where its value is.
  '@slidev/parser': `export function parseSync(markdown) {
  const match = /^---.*\\r?\\n([\\s\\S]*?)---/.exec(markdown);
  if (!match) return { slides: [{}] };
  const items = [], frontmatter = {};
  let at = 0;
  for (const line of match[1].split('\\n')) {
    const kv = /^([A-Za-z_][\\w-]*):[ \\t]*(.*)$/.exec(line);
    if (kv) {
      const start = at + line.length - kv[2].length;
      items.push({ key: { value: kv[1] }, value: { range: [start, start + kv[2].length] } });
      frontmatter[kv[1]] = kv[2].startsWith('"') ? JSON.parse(kv[2]) : kv[2];
    }
    at += line.length + 1;
  }
  return { slides: [{ frontmatterStyle: 'frontmatter', frontmatterDoc: { errors: [], contents: { items } }, frontmatter }] };
}
`,
};

// `slidev build <file> --out <dir> --base <base>` writes a one-page build; anything else (an editor) stops at once.
const SLIDEV_STANDIN = `#!/bin/sh
[ "$1" = "build" ] || exit 3
out=''
while [ $# -gt 0 ]; do
  if [ "$1" = "--out" ]; then out="$2"; shift; fi
  shift
done
mkdir -p "$out" && printf '<!doctype html><html><head><title>built</title></head><body>deck</body></html>\\n' > "$out/index.html"
`;

// With `editor: true` (the edit pass tests of round 8): the same build, and instead of stopping, a stand-in editor
// (Slidev's development server) on --port that answers every page with a small HTML page and stops when asked for
// /__exit, so a test can stop an editor.
const STANDIN_EDITOR_START = `if [ "$1" != "build" ]; then
  port=''
  while [ $# -gt 0 ]; do
    if [ "$1" = "--port" ]; then port="$2"; shift; fi
    shift
  done
  exec node -e 'require("http").createServer((q, r) => { if (q.url === "/__exit") { r.end("bye"); setTimeout(() => process.exit(0), 20); return; } r.writeHead(200, { "Content-Type": "text/html" }); r.end("<!doctype html><html><head><title>editor</title></head><body>editor</body></html>"); }).listen(Number(process.argv[1]), "127.0.0.1")' "$port"
fi`;
const SLIDEV_STANDIN_EDITOR = SLIDEV_STANDIN.replace('[ "$1" = "build" ] || exit 3', () => STANDIN_EDITOR_START);

// The list of protected-decks.mjs (empty since round 6), as it is written in that file.
const EMPTY_PROTECTED_LIST = 'export const PROTECTED_DECKS = Object.freeze([]);';

export const freePort = () => new Promise((resolve, reject) => {
  const s = net.createServer().listen(0, '127.0.0.1', () => { const { port } = s.address(); s.close(() => resolve(port)); }).on('error', reject);
});

export const readJson = async req => { let raw = ''; for await (const chunk of req) raw += chunk; return raw ? JSON.parse(raw) : {}; };

/** A small HTTP stand-in: handler(req, url, body) returns [status, value]. */
export function startStub(handler, port = 0, host = '127.0.0.1') {
  return new Promise(resolve => {
    const server = http.createServer(async (req, res) => {
      const url = new URL(req.url, 'http://stub');
      const body = req.method === 'POST' ? await readJson(req) : {};
      const [status, value] = await handler(req, url, body);
      res.writeHead(status, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify(value));
    });
    server.listen(port, host, () => resolve(server));
  });
}

/** Supabase Auth + PostgREST stand-in: the person is the token's `sub`, always active. */
export function supabaseAnswer(req, url) {
  if (url.pathname === '/auth/v1/user') {
    const sub = JSON.parse(Buffer.from(String(req.headers.authorization).slice(7).split('.')[1], 'base64url').toString()).sub;
    return [200, { id: sub }];
  }
  if (url.pathname === '/rest/v1/current_user_context') {
    const id = url.searchParams.get('user_id').replace(/^eq\./, '');
    return [200, [{ user_id: id, user_active: true, mission_id: 1 }]];
  }
  return null;
}

const b64 = value => Buffer.from(JSON.stringify(value)).toString('base64url');
/** A token the stand-in accepts (never a real one). */
export const token = (sub, seconds = 3600) => `${b64({ alg: 'HS256', typ: 'JWT' })}.${b64({ sub, exp: Math.floor(Date.now() / 1000) + seconds })}.stub`;

/**
 * The manager copy with the stand-ins above, in a temporary folder. protectedDecks: slugs the copy's
 * protected-decks.mjs lists (the live list is empty since round 6), so the protection can still be tested.
 * Returns { tmp, serverFile, decksDir }.
 */
async function managerCopy(protectedDecks, editor = false) {
  const tmp = await fs.mkdtemp(path.join(os.tmpdir(), 'manager-'));
  const decksDir = path.join(tmp, 'decks');
  await fs.cp(MANAGER_DIR, path.join(tmp, 'manager'), { recursive: true });
  if (protectedDecks) {
    const listFile = path.join(tmp, 'manager', 'protected-decks.mjs');
    const source = await fs.readFile(listFile, 'utf8');
    if (!source.includes(EMPTY_PROTECTED_LIST)) throw new Error(`protected-decks.mjs should contain ${EMPTY_PROTECTED_LIST}`);
    await fs.writeFile(listFile, source.replace(EMPTY_PROTECTED_LIST, () => `export const PROTECTED_DECKS = Object.freeze(${JSON.stringify(protectedDecks)});`));
  }
  await fs.mkdir(decksDir, { recursive: true });
  await fs.mkdir(path.join(tmp, 'node_modules', '.bin'), { recursive: true });
  await fs.writeFile(path.join(tmp, 'node_modules', '.bin', 'slidev'), editor ? SLIDEV_STANDIN_EDITOR : SLIDEV_STANDIN, { mode: 0o755 });
  for (const [name, code] of Object.entries(STUBS)) {
    const dir = path.join(tmp, 'node_modules', name);
    await fs.mkdir(dir, { recursive: true });
    await fs.writeFile(path.join(dir, 'package.json'), JSON.stringify({ name, type: 'module', exports: './index.js' }));
    await fs.writeFile(path.join(dir, 'index.js'), code);
  }
  return { tmp, serverFile: path.join(tmp, 'manager', 'server.mjs'), decksDir };
}

/**
 * Starts the manager copy. decks: { slug: title }. env: SUPABASE_URL, PRESENTATION_ACL_API_URL (and anything else).
 * protectedDecks: see managerCopy. port / deckPort: the manager address's and the deck address's ports (free ones
 * when not given). bind: the network address both listen on. editor: a stand-in editor starts (see
 * SLIDEV_STANDIN_EDITOR) instead of failing. log: print the manager's output as it comes (for manual runs).
 * Returns { url, deckUrl, decks, log, stop }.
 * real: run the installed manager itself (/slidev/manager/server.mjs) with the real Slidev (/slidev/node_modules) and
 * decks in /slidev/decks, so decks are really built. Only inside a throw-away test container with that layout
 * (deck-origin/edge_deck_origin.ps1); never on the live system.
 */
export async function startManager({ decks = {}, env = {}, port = 0, deckPort = 0, bind = '127.0.0.1', real = false, protectedDecks = null, editor = false, log: echo = false } = {}) {
  const { tmp, serverFile, decksDir } = real
    ? { tmp: await fs.mkdtemp(path.join(os.tmpdir(), 'manager-')), serverFile: '/slidev/manager/server.mjs', decksDir: '/slidev/decks' }
    : await managerCopy(protectedDecks, editor);
  for (const [slug, title] of Object.entries(decks)) await writeDeck(decksDir, slug, title);
  const managerPort = port || await freePort();
  const deckAddressPort = deckPort || await freePort();
  let log = '';
  const child = spawn(process.execPath, [serverFile], {
    cwd: real ? '/slidev' : tmp,
    env: {
      ...process.env, PRESENTATION_MANAGER_PORT: String(managerPort), SUPABASE_SERVICE_ROLE_KEY: 'stub',
      // The deck address on its own port; browsers use the same ports here (no Docker port mapping).
      PRESENTATION_DECK_SERVER_PORT: String(deckAddressPort), PRESENTATIONS_DECK_PORT: String(deckAddressPort),
      PRESENTATIONS_PUBLIC_PORT: String(managerPort), PRESENTATION_BIND_ADDRESS: bind,
      ...(real ? {} : { PRESENTATION_SLIDEV_HOME: tmp }),
      PORTAL_SERVICE_KEY: 'stub', SLIDEV_PRESTART: '0', SLIDEV_ADDON_REBUILD: '0', ...env,
    },
    stdio: ['ignore', 'pipe', 'pipe'],
  });
  child.stdout.on('data', d => { log += d; if (echo) process.stdout.write(d); });
  child.stderr.on('data', d => { log += d; if (echo) process.stderr.write(d); });
  const url = `http://127.0.0.1:${managerPort}`;
  const deckUrl = `http://127.0.0.1:${deckAddressPort}`;
  for (let i = 0; ; i++) {
    if (await fetch(`${url}/health`).then(r => r.ok, () => false) && await fetch(`${deckUrl}/health`).then(r => r.ok, () => false)) break;
    if (i > 100 || child.exitCode !== null) throw new Error(`the manager did not start:\n${log}`);
    await new Promise(r => setTimeout(r, 100));
  }
  return {
    url, deckUrl, decks: decksDir, log: () => log,
    async stop() {
      if (child.exitCode === null) { child.kill(); await new Promise(r => child.once('exit', r)); }
      await fs.rm(tmp, { recursive: true, force: true });
    },
  };
}

/** A deck with a title slide: <decksDir>/<slug>/slides.md. */
export async function writeDeck(decksDir, slug, title, extra = '') {
  await fs.mkdir(path.join(decksDir, slug), { recursive: true });
  await fs.writeFile(path.join(decksDir, slug, 'slides.md'), `---\ntitle: ${title}\ntheme: default\n---\n\n# ${title}\n${extra}`);
}
