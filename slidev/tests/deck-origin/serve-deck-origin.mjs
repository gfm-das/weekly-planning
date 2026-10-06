// TEST ONLY (round 8, the deck address): the real presentation manager with the real Slidev for the headless Edge
// check edge_deck_origin.ps1, in a throw-away container. The manager address is PORT, the deck address DECK_PORT
// (browsers use the same ports here: no Docker port mapping in between). Supabase Auth and PostgREST are a stand-in
// (the person is the token's `sub`); portal-api is the real one of this branch at PRESENTATION_ACL_API_URL, on a
// throw-away database copy. The decks are made up; their owners are written into the copy by the .ps1.
//   node slidev/tests/deck-origin/serve-deck-origin.mjs   (env: PORT, DECK_PORT, PRESENTATION_ACL_API_URL, PORTAL_SERVICE_KEY)
import fs from 'node:fs/promises';
import path from 'node:path';
import { startManager, startStub, supabaseAnswer } from '../helpers/manager-harness.mjs';

const port = Number(process.env.PORT || 18481);
const deckPort = Number(process.env.DECK_PORT || 18489);

// One live chart on slide 1: New people being taught of each zone, the last four weeks. Written as plain JSON, so it
// is "pinned" (leaders may see it). In a zone's deck everyone sees only that zone (portal-api, round 8); in a
// mission deck a manager sees every zone.
const CHART = `<MissionChart chart-id="zones" :query='{"measures":["friends_found.actual"],"level":"zone","by":"unit","weeks":{"last":4}}' :height="260" />`;
// Round 8 review: the zone deck's chart also carries a tooltip text a Zone Leader could write, with HTML that runs
// script (written with < escapes, as the chart builder writes it). On the deck address that is the deck's own
// code; in the chart builder on the manager address (/studio, Edit chart) it must never run.
const EVIL_CHART = CHART.replace(' :height="260"', ` :option='{"series":[{"type":"bar"}],"tooltip":{"trigger":"item","formatter":"\\u003cimg src=x onerror=window.__pwned=1\\u003e"}}' :height="260"`);
const deck = (title, chart = CHART) => `---\ntitle: ${title}\ntheme: default\n---\n\n# ${title}\n\n${chart}\n\n---\n\n# Second slide\n`;

const supabase = await startStub((req, url) => supabaseAnswer(req, url) || [404, { error: 'stand-in: not found' }]);
const titles = { 'zone-council': 'Our zone council', 'other-zone-council': 'Other zone council', 'mission-training': 'Mission training' };
const manager = await startManager({
  port, deckPort, bind: '0.0.0.0', real: true, decks: titles,
  env: {
    SUPABASE_URL: `http://127.0.0.1:${supabase.address().port}`,
    PRESENTATION_ACL_API_URL: process.env.PRESENTATION_ACL_API_URL,
    PORTAL_SERVICE_KEY: process.env.PORTAL_SERVICE_KEY,
    PRESENTATIONS_PORTAL_ORIGINS: 'http://127.0.0.1:8070',
  },
});
// The decks with their chart (nothing is built yet: the first view builds each deck).
for (const [slug, title] of Object.entries(titles)) await fs.writeFile(path.join(manager.decks, slug, 'slides.md'), deck(title, slug === 'zone-council' ? EVIL_CHART : CHART));
console.log(`deck address test manager on ports ${port} (manager) and ${deckPort} (decks)`);
const stop = async () => { await manager.stop(); supabase.close(); process.exit(0); };
process.on('SIGTERM', stop);
process.on('SIGINT', stop);
