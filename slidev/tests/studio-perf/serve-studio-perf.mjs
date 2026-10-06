// TEST ONLY (GFM Studio, startup measurement): the real presentation manager with the real Slidev in a throw-away
// container, with stand-ins for Supabase Auth and portal-api (the person is always a manager). Nothing here touches
// the live system. Used to measure "click Edit -> editable" in a real browser (docs: slidev/tests/studio-perf/README.md).
//   docker run ... node /slidev/tests/studio-perf/serve-studio-perf.mjs   (env: PORT, DECK_PORT, SEED_DECKS_FROM)
import fs from 'node:fs/promises';
import path from 'node:path';
import { startManager, startStub, supabaseAnswer, token } from '../helpers/manager-harness.mjs';
import { kpiWeeks } from '../chart-cases.mjs';

const port = Number(process.env.PORT || 18581);
const deckPort = Number(process.env.DECK_PORT || 18589);
const supabase = await startStub((req, url) => supabaseAnswer(req, url) || [404, { error: 'stand-in: not found' }]);
const acl = await startStub((req, url, body) => {
  if (url.pathname === '/internal/presentations/check') return [200, { can_manage: true, can_create: true, role: 'AP', can_use: true, allowed_slugs: [], editable_slugs: [], owner_zones: {} }];
  if (url.pathname === '/internal/presentations/access') return [200, { ok: true, access: {}, options: {} }];
  if (url.pathname === '/internal/presentations/chart-data') return [200, { table: { labels: ['A', 'B', 'C'], series: [{ name: 'Friends', data: [3, 5, 2] }] }, meta: {} }];
  if (url.pathname === '/internal/presentations/kpis') return [200, kpiWeeks(30)];
  return [404, { error: 'stand-in' }];
});
const CHART = `<MissionChart chart-id="zones" :query='{"measures":["friends_found.actual"],"level":"zone","by":"unit","weeks":{"last":4}}' :height="260" />`;
const small = `---\ntitle: Small test deck\ntheme: default\n---\n\n# Small test deck\n\n${CHART}\n\n---\n\n# Second slide\n\nSome text.\n`;
const manager = await startManager({
  port, deckPort, bind: '0.0.0.0', real: true, log: true,
  env: {
    SUPABASE_URL: `http://127.0.0.1:${supabase.address().port}`,
    PRESENTATION_ACL_API_URL: `http://127.0.0.1:${acl.address().port}`,
    PORTAL_SERVICE_KEY: 'stub',
    PRESENTATIONS_PORTAL_ORIGINS: 'http://127.0.0.1:8070',
    PRESENTATIONS_PUBLIC_MANAGER_ORIGIN: '', PRESENTATIONS_PUBLIC_DECK_ORIGIN: '', PRESENTATIONS_PUBLIC_COOKIE_DOMAIN: '',
    PRESENTATIONS_HOST: '127.0.0.1',
    SLIDEV_PRESTART: process.env.STUDIO_PRESTART || '0',
  },
});
await fs.mkdir(path.join(manager.decks, 'small'), { recursive: true });
await fs.writeFile(path.join(manager.decks, 'small', 'slides.md'), small);
// Real example decks (read-only copy of the live volume's decks): SEED_DECKS_FROM=/livedecks SEED=chart-gallery,mission-charts-database
for (const slug of (process.env.SEED || '').split(',').filter(Boolean)) {
  await fs.cp(path.join(process.env.SEED_DECKS_FROM || '/livedecks', slug), path.join(manager.decks, slug), { recursive: true, filter: s => !/node_modules|[\/]dist([\/]|$)/.test(s) });
}
await fs.copyFile('/slidev/tests/studio-perf/gfm-demo.md', path.join(manager.decks, 'gfm-demo', 'slides.md')).catch(async () => { await fs.mkdir(path.join(manager.decks, 'gfm-demo'), { recursive: true }); await fs.copyFile('/slidev/tests/studio-perf/gfm-demo.md', path.join(manager.decks, 'gfm-demo', 'slides.md')); });
console.log(`TOKEN ${token('00000000-0000-4000-8000-000000000001', 86400)}`);
console.log(`studio perf manager on ports ${port} (manager) and ${deckPort} (decks)`);
const stop = async () => { await manager.stop(); supabase.close(); acl.close(); process.exit(0); };
process.on('SIGTERM', stop);
process.on('SIGINT', stop);

// A tiny control port for the measurement runs (CONTROL_PORT, default 18599): GET /kill stops the running Slidev
// editor process (the manager starts a new one when the next /studio page asks), so a run can repeat a cold-process
// start with a warm Vite cache. Test only.
const { createServer } = await import('node:http');
const { execFileSync } = await import('node:child_process');
createServer(async (req, res) => {
  res.setHeader('Access-Control-Allow-Origin', '*');
  if (req.url === '/kill') {
    let killed = 0;
    try {
      for (const line of execFileSync('ps', ['-o', 'pid,args']).toString().split('\n')) {
        const m = /^\s*(\d+)\s+.*node_modules\/\.bin\/slidev /.exec(line);
        if (m) { process.kill(Number(m[1])); killed++; }
      }
    } catch {}
    return res.end(String(killed));
  }
  if (req.url === '/e2e.js') { res.setHeader('Content-Type', 'text/javascript; charset=utf-8'); return res.end((await import('node:fs')).readFileSync('/slidev/tests/e2e/studio-e2e.js')); }
  res.statusCode = 404; res.end('no');
}).listen(Number(process.env.CONTROL_PORT || 18599), '0.0.0.0');
