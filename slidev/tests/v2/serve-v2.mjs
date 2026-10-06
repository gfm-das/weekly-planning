// TEST ONLY: the real presentation manager with the built V2 app and made-up numbers, for looking at the V2 pages in a
// browser (Edge check). Supabase and portal-api are stand-ins: the person is the token's `sub` ("manager" manages, "viewer"
// is a district leader who was given the deck "referral-demo").
//   docker run --rm -p 18701:18701 -v <repo>:/r -w /r/slidev node:24-alpine node tests/v2/serve-v2.mjs
// Then, in the browser console of http://127.0.0.1:18701/ :  the printed login snippet gives a session cookie.
import fs from 'node:fs/promises';
import path from 'node:path';
import { startManager, startStub, supabaseAnswer, token } from '../helpers/manager-harness.mjs';

const port = Number(process.env.PORT || 18701);
const ZONES = ['Frankfurt 1', 'Frankfurt 2', 'Mainz', 'Darmstadt', 'Kassel', 'Wiesbaden'];
const MEASURES = [
  ['friends_found.actual', 'kpi', 'New people being taught', 'actual'], ['friends_found.previous_goal', 'kpi', 'New people being taught: goal set the week before', 'goal'],
  ['baptismal_dates.actual', 'kpi', 'Baptismal dates', 'actual'], ['baptisms_confirmations.actual', 'kpi', 'Baptisms and confirmations', 'actual'],
  ['sacrament_attendance.actual', 'kpi', 'Sacrament attendance', 'actual'], ['members_at_lessons.actual', 'kpi', 'Members at lessons', 'actual'],
  ['plans.started', 'plans', 'Plans started', 'count'], ['plans.submitted', 'plans', 'Plans submitted', 'count'],
];
const BASE = { friends_found: 20, baptismal_dates: 7, baptisms_confirmations: 4, sacrament_attendance: 30, members_at_lessons: 12, plans: 9 };
const hash = text => [...text].reduce((a, c) => (a * 31 + c.charCodeAt(0)) % 9973, 7);
const value = (measure, unit, week) => {
  const topic = measure.split('.')[0];
  const base = BASE[topic] ?? 10;
  if (unit === 'Mission') return Math.round(base * 6.2);
  const n = Math.round(base * (0.45 + ((hash(measure + unit) % 100) / 100) * 0.9) * (1 + (week % 3) * 0.05));
  return measure.endsWith('previous_goal') ? n + 2 : n;
};

const catalog = {
  measures: MEASURES.map(([id, group, label, kind]) => ({ id, group, topic: id.split('.')[0], field: id.split('.')[1], kind, label, short: label.replace(/: goal.*/, ' goal'), goals: {} })),
  groups: [{ id: 'kpi', label: 'Key indicators' }, { id: 'plans', label: 'Plans' }],
  levels: [{ id: 'mission', label: 'The mission' }, { id: 'zone', label: 'Zones' }], scope: 'mission',
  zones: ZONES.map((name, i) => ({ id: i + 1, name })), districts: [], areas: [], weeks: { current: '2026-10-04', available: [] },
  limits: { weeks: 104, measures: 8, top: 50, filter: 200, series: 24 }, transforms: ['none'], audiences: ['deck', 'stewardship'],
};

const viewing = { roles: [], zone_ids: [], district_ids: [], user_ids: [], everyone: false };
const portal = await startStub((req, url, body) => {
  if (req.headers['x-service-key'] !== 'stub') return [401, { error: 'key' }];
  if (url.pathname === '/internal/presentations/check') {
    if (body.user_id === 'manager') return [200, { can_manage: true, can_create: true, role: 'DA', allowed_slugs: [], editable_slugs: [], owner_zones: [] }];
    return [200, { can_manage: false, can_create: false, role: 'DL', allowed_slugs: ['referral-demo'], editable_slugs: [], owner_zones: [] }];
  }
  if (url.pathname === '/internal/presentations/access') {
    if (body.operation === 'get') return [200, { access: viewing, options: { roles: ['DL', 'ZL', 'STL'], zones: catalog.zones, districts: [{ id: 1, name: 'Frankfurt A', zone_id: 1 }], users: [{ user_id: 'u1', name: 'Elder Example' }, { user_id: 'u2', name: 'Sister Sample' }] } }];
    if (body.operation === 'save') { Object.assign(viewing, body.rule); return [200, { ok: true }]; }
    return [200, { ok: true }];
  }
  if (url.pathname === '/internal/presentations/chart-catalog') return [200, catalog];
  if (url.pathname === '/internal/presentations/chart-data') {
    const spec = body.spec;
    const byWeek = spec.by === 'week';
    const labels = byWeek ? Array.from({ length: spec.weeks.last }, (_, i) => `2026-0${8 + Math.floor(i / 5)}-${String(((i % 5) * 7) + 2).padStart(2, '0')}`) : spec.level === 'mission' ? ['Mission'] : ZONES;
    const series = spec.measures.map(m => ({
      name: catalog.measures.find(x => x.id === m)?.short ?? m,
      values: labels.map((l, i) => value(m, byWeek ? 'Mission' : l, i)),
    }));
    return [200, { table: { labels, series }, meta: { level: spec.level, by: spec.by, unit: 'count', stewardship: !body.pinned === false && false, suppressed: false } }];
  }
  return [404, { error: 'stand-in' }];
});
const supabase = await startStub((req, url) => supabaseAnswer(req, url) || [404, {}]);
const manager = await startManager({
  port, bind: '0.0.0.0', log: true,
  env: {
    SUPABASE_URL: `http://127.0.0.1:${supabase.address().port}`, PRESENTATION_ACL_API_URL: `http://127.0.0.1:${portal.address().port}`,
    PRESENTATION_V2_APP_DIR: path.resolve(import.meta.dirname, '../../presentations-v2/dist'), PRESENTATIONS_PORTAL_ORIGINS: `http://127.0.0.1:${port}`,
  },
});
const dir = path.join(manager.decks, '..', 'decks-v2', 'referral-demo');
await fs.mkdir(path.join(dir, 'assets'), { recursive: true });
if (process.env.SEED !== '0') await fs.copyFile(path.resolve(import.meta.dirname, '../../presentations-v2/demo/referral-demo.deck.json'), path.join(dir, 'deck.json'));
console.log(`V2 test manager: http://127.0.0.1:${port}/`);
console.log(`manager token: ${token('manager', 36000)}`);
console.log(`viewer token: ${token('viewer', 36000)}`);
const stop = async () => { await manager.stop(); process.exit(0); };
process.on('SIGTERM', stop);
process.on('SIGINT', stop);
