// TEST ONLY (round 9, speed): the real presentation manager with the real Slidev, for edge_speed.ps1, in a
// throw-away container. Like deck-origin/serve-deck-origin.mjs, with three made-up decks:
//   zone-council       a zone's deck with one live chart (the owner row is written by the .ps1)
//   mission-training   a mission deck with one live chart
//   mission-dashboard  a big deck made here (13 slides, six live key numbers on slide 1, a 12-week line on each other slide)
// Supabase is a stand-in (the person is the token's `sub`); portal-api is the real one on a throw-away copy.
//   node /slidev/tests/speed/serve-speed.mjs   (env: PORT, DECK_PORT, PRESENTATION_ACL_API_URL, PORTAL_SERVICE_KEY, PORTAL_ORIGIN)
import fs from 'node:fs/promises';
import path from 'node:path';
import { startManager, startStub, supabaseAnswer } from '../helpers/manager-harness.mjs';

const port = Number(process.env.PORT || 18581);
const deckPort = Number(process.env.DECK_PORT || 18589);
const CHART = `<MissionChart chart-id="zones" :query='{"measures":["friends_found.actual"],"level":"zone","by":"unit","weeks":{"last":4}}' :height="260" />`;
const deck = title => `---\ntitle: ${title}\ntheme: default\n---\n\n# ${title}\n\n${CHART}\n\n---\n\n# Second slide\n\nSome text.\n`;

// The big deck: its 12-week query is the one edge_speed.ps1 asks /api/charts/data for (written in the deck, so allowed).
const KPIS = ['friends_found', 'baptisms_confirmations', 'baptismal_dates', 'sacrament_attendance', 'members_at_lessons', 'new_member_sacrament'];
const tile = id => `<MissionChart type="tile" :query='${JSON.stringify({ measures: [`${id}.actual`, `${id}.previous_goal`], weeks: 4, includeCurrent: false })}' />`;
const line = id => `<MissionChart type="line" :height="320" :query='${JSON.stringify({ measures: [`${id}.actual`, `${id}.previous_goal`], weeks: 12, includeCurrent: false })}' />`;
const bigDeck = () => `---\ntitle: Mission Dashboard\ntheme: default\n---\n\n# Mission Dashboard\n\n${KPIS.map(tile).join('\n')}\n`
  + Array.from({ length: 12 }, (_, i) => `\n---\n\n# Slide ${i + 2}\n\n${line(KPIS[i % 6])}\n`).join('');

const supabase = await startStub((req, url) => supabaseAnswer(req, url) || [404, { error: 'stand-in: not found' }]);
const titles = { 'zone-council': 'Our zone council', 'mission-training': 'Mission training' };
const manager = await startManager({
  port, deckPort, bind: '0.0.0.0', real: true, decks: titles, log: true,
  env: {
    SUPABASE_URL: `http://127.0.0.1:${supabase.address().port}`,
    PRESENTATION_ACL_API_URL: process.env.PRESENTATION_ACL_API_URL,
    PORTAL_SERVICE_KEY: process.env.PORTAL_SERVICE_KEY,
    // A throw-away portal (nginx with this repository's portal/): the pages load its i18n.js as they do live.
    PRESENTATIONS_PORTAL_ORIGINS: process.env.PORTAL_ORIGIN || 'http://127.0.0.1:18599',
  },
});
for (const [slug, title] of Object.entries(titles)) await fs.writeFile(path.join(manager.decks, slug, 'slides.md'), deck(title));
await fs.mkdir(path.join(manager.decks, 'mission-dashboard'), { recursive: true });
await fs.writeFile(path.join(manager.decks, 'mission-dashboard', 'slides.md'), bigDeck());
console.log(`speed test manager on ports ${port} (manager) and ${deckPort} (decks)`);
const stop = async () => { await manager.stop(); supabase.close(); process.exit(0); };
process.on('SIGTERM', stop);
process.on('SIGINT', stop);
