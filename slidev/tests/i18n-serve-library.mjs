// TEST ONLY (round 6, docs/handoff/round6/i18n.md): the real presentation manager with made-up decks and stand-ins
// (tests/helpers/manager-harness.mjs), so the Presentations library and the /studio bar can be opened in a browser
// in another language without Slidev, its packages, Supabase or portal-api. Needs a POSIX shell:
//   docker run -d --name gfm-test-i18n-slidev --network gfm-test-i18n-net --memory 256m -p 127.0.0.1:18692:18692 \
//     -v <repo>/slidev:/slidev-src:ro -e PORTAL=http://127.0.0.1:18671 node:24-alpine node /slidev-src/tests/i18n-serve-library.mjs
// PORTAL is where the browser reaches the portal (i18n.js and the catalogs). Then, in the browser on
// http://127.0.0.1:18692/?lang=de, POST /api/session with "Authorization: Bearer <token>" (printed below) and reload.
import { startManager, startStub, supabaseAnswer, token } from './helpers/manager-harness.mjs';

const PORT = Number(process.env.PORT || 18692);
const PORTAL = process.env.PORTAL || 'http://127.0.0.1:18671';

// Supabase Auth + PostgREST + portal-api /internal/presentations/*: one AP (a manager).
function stubAnswer(req, url, body) {
  if (url.pathname === '/rest/v1/current_user_context') return [200, [{ user_id: 'user-ap', user_active: true, app_role: 'AP', mission_id: 1 }]];
  const supabase = supabaseAnswer(req, url);
  if (supabase) return supabase;
  if (url.pathname === '/internal/presentations/check') return [200, { can_manage: true, role: 'AP', allowed_slugs: body.deck_slugs || [] }];
  if (url.pathname === '/internal/presentations/access') {
    return [200, {
      ok: true, access: { roles: [], zone_ids: [], district_ids: [], user_ids: [], everyone: false },
      options: { zones: [{ id: 1, name: 'Frankfurt' }], districts: [{ id: 11, name: 'Frankfurt 1', zone_id: 1 }], users: [] },
    }];
  }
  return [404, { error: 'stub: not found' }];
}

const stub = await startStub(stubAnswer);
const stubUrl = `http://127.0.0.1:${stub.address().port}`;
// Made-up decks (titles are deck content and stay as written). The browser reaches the manager through Docker's
// port mapping, so it listens on every address of the container.
const manager = await startManager({
  port: PORT, bind: '0.0.0.0', log: true,
  decks: { 'mission-dashboard': 'Mission Dashboard', 'zone-conference': 'Zone conference', 'district-council': 'District council' },
  env: { SUPABASE_URL: stubUrl, PRESENTATION_ACL_API_URL: stubUrl, PRESENTATIONS_PORTAL_ORIGINS: PORTAL },
});
console.log(`[i18n] library on :${PORT}; sign in with Authorization: Bearer ${token('user-ap', 86400)}`);
const stop = () => manager.stop().finally(() => { stub.close(); process.exit(0); });
process.on('SIGTERM', stop);
process.on('SIGINT', stop);
