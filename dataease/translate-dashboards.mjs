// Makes (or brings up to date) the copies of the English dashboards in the 13 other portal languages.
// Plain Node 24, no packages. It talks to DataEase's own web API as the one Community Edition account ("admin"), like
// seed-dashboards.mjs. Run it through dataease/translate-dashboards.ps1 (a short-lived container on DataEase's
// private network, with dataease/.env); never with the password on a command line.
//
//   node dataease/translate-dashboards.mjs           make or update every copy (safe to run again and again)
//   node dataease/translate-dashboards.mjs --check   only read: which copies exist, and which words have no
//                                                    translation yet
//   node dataease/translate-dashboards.mjs --only de,ar   only these languages
//   node dataease/translate-dashboards.mjs --remove  delete every copy and language folder (rollback; the English
//                                                    dashboards are not touched)
//
// What it does, for each dashboard directly in the folder "Mission" that seed-dashboards.mjs made (Key indicators,
// Zones & districts, Covenant path):
//  1. reads the English dashboard as it is in DataEase now (so changes people made in DataEase are copied too);
//  2. makes a copy per language with lib/copies.mjs: translated name, chart titles, notes, filter labels, text boxes
//     and field display names (the words DataEase draws on its charts), using the files in dataease/i18n/;
//  3. saves it in the language's folder inside "Mission" (Deutsch, Español, ... العربية), under the fixed id of
//     lib/languages.mjs (the English id with the language number in it), and publishes it.
// A copy is replaced every time: never edit a copy in DataEase, edit the English dashboard and run this again.
// The portal opens the viewer's language by that id rule (gate/gate.mjs); no list needs updating.
// Prints names and counts only; never passwords, tokens or people's data.
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { DataEase, flattenTree } from './lib/dataease-client.mjs';
import { LANGUAGES, isCopyOf, makeId, parseId } from './lib/languages.mjs';
import { copyDashboard, translator } from './lib/copies.mjs';
import {
  MAX_GENERATIONS, createFolder, dashboardNodes, dashboardState, deleteDashboard, findDashboard, saveAndPublish,
} from './lib/dashboard-store.mjs';

const args = process.argv.slice(2);
const CHECK_ONLY = args.includes('--check');
const REMOVE = args.includes('--remove');
const onlyAt = args.indexOf('--only');
const ONLY = onlyAt >= 0 ? String(args[onlyAt + 1] || '').split(',').map(s => s.trim()).filter(Boolean) : null;
const MISSION_FOLDER = 'Mission';
const base = (process.env.DE_BASE || 'http://dataease:8100').trim();
const say = message => console.log(message);
let failures = 0;
const fail = message => { failures += 1; console.log('FAIL ' + message); };

async function signIn() {
  const password = (process.env.DE_ADMIN_PASSWORD || '').trim();
  if (!password || /REPLACE|example/i.test(password)) throw new Error('DE_ADMIN_PASSWORD is missing in dataease/.env (run dataease/init-env.ps1).');
  const de = new DataEase(base);
  await de.login(password);
  say('Signed in to DataEase.');
  return de;
}

/** A language folder inside "Mission" (Deutsch, Español...): id 115 LL 00 GG 0000 000000 with LL above 00. */
export function isLanguageFolder(node) {
  const p = parseId(node.id);
  return !node.leaf && !!p && p.language > 0 && p.dashboard === 0;
}

/** A dashboard seed-dashboards.mjs made in English (id 115 00 DD ... with DD above 00). */
export function isEnglishDashboard(node) {
  const p = parseId(node.id);
  return !!p && p.language === 0 && p.dashboard > 0;
}

// The id to use for a dashboard or folder of ours: the live one (any generation), else the first free one.
// DataEase keeps deleted rows, so a deleted id can never be used again (seed-dashboards.mjs does the same).
async function place(de, nodes, parts) {
  for (let generation = 0; generation < MAX_GENERATIONS; generation += 1) {
    const id = makeId({ ...parts, generation });
    if (nodes.some(n => String(n.id) === id)) return { id, generation, live: true };
    if ((await dashboardState(de, id)) === 'free') return { id, generation, live: false };
  }
  throw new Error(`No free id left for ${JSON.stringify(parts)}.`);
}

async function ensureLanguageFolder(de, nodes, lang, missionId) {
  const spot = await place(de, nodes, { language: lang.number });
  if (!spot.live) {
    await createFolder(de, { id: spot.id, name: lang.name, parentId: missionId });
    say(`Folder "${lang.name}" created in "${MISSION_FOLDER}".`);
  }
  return spot.id;
}

// Rollback: the language folders (and the copies in them) go; DataEase only marks them deleted (so their ids are not
// used again: a later run takes the next generation).
async function removeCopies(de, nodes) {
  for (const folder of nodes.filter(isLanguageFolder)) {
    for (const leaf of flattenTree(folder.children).filter(n => n.leaf)) await deleteDashboard(de, leaf.id);
    await deleteDashboard(de, folder.id);
    say(`Removed the folder "${folder.name}" and its copies.`);
  }
  const left = (await dashboardNodes(de)).filter(n => parseId(n.id)?.language > 0);
  if (left.length) fail(`${left.length} copies or folders are still there.`);
  else say('No copies are left; the English dashboards are unchanged.');
}

// The English dashboards of the folder "Mission" (the tree's nodes). Dashboards made by hand there are named.
function englishDashboardNodes(mission) {
  const leaves = (mission.children || []).filter(n => n.leaf);
  const english = leaves.filter(isEnglishDashboard);
  for (const node of leaves.filter(n => !english.includes(n))) {
    say(`"${node.name}" was made by hand in DataEase: it stays English only (see dataease/i18n/README.md).`);
  }
  if (!english.length) throw new Error(`No dashboard of seed-dashboards.mjs in "${MISSION_FOLDER}".`);
  return english;
}

// Those dashboards as DataEase keeps them, with their charts.
async function readDashboards(de, nodes) {
  const dashboards = [];
  for (const node of nodes) dashboards.push(await findDashboard(de, String(node.id)));
  say(`English dashboards: ${dashboards.map(d => `"${d.name}"`).join(', ')}.`);
  return dashboards;
}

function chosenLanguages() {
  const languages = LANGUAGES.filter(l => !ONLY || ONLY.includes(l.code));
  if (ONLY && languages.length !== ONLY.length) throw new Error(`Unknown language in --only ${ONLY.join(',')}.`);
  return languages;
}

// --check: is there a copy, and which words have no translation yet (the copy is made in memory only).
function checkCopy(dv, lang, translate, nodes, missing) {
  const existing = nodes.find(n => isCopyOf(n, lang.number, parseId(dv.id).dashboard));
  copyDashboard(dv, lang.code, translate).missing.forEach(t => missing.add(t));
  if (existing) say(`  ok  ${lang.code} "${existing.name}" (copy of "${dv.name}")`);
  else fail(`${lang.code}: "${dv.name}" has no copy yet (run without --check).`);
}

// Makes or replaces one copy, publishes it, and checks that DataEase kept every chart.
async function makeCopy(de, dv, lang, translate, nodes, folderId, missing) {
  try {
    const spot = await place(de, nodes, { language: lang.number, dashboard: parseId(dv.id).dashboard });
    const copy = copyDashboard(dv, lang.code, translate, spot.generation);
    copy.missing.forEach(t => missing.add(t));
    await saveAndPublish(de, copy, { folderId, exists: spot.live });
    const saved = await findDashboard(de, copy.id);
    const charts = Object.keys(saved?.canvasViewInfo || {}).length;
    const expected = Object.keys(copy.canvasViewInfo).length;
    if (charts !== expected) fail(`${lang.code} "${copy.name}": ${charts} of ${expected} charts saved.`);
    else say(`  ok  ${lang.code} "${copy.name}" ${spot.live ? 'updated' : 'created'} (${charts} charts).`);
  } catch (error) {
    fail(`${lang.code} copy of "${dv.name}": ${error.message}`);
  }
}

function reportMissing(lang, missing) {
  if (!missing.size) return;
  const shown = [...missing].map(t => JSON.stringify(t.length > 70 ? t.slice(0, 67) + '...' : t)).join(', ');
  say(`  ${lang.code}: no translation yet for ${missing.size} text(s), shown in English: ${shown}`);
}

async function main() {
  const de = await signIn();
  let nodes = await dashboardNodes(de);
  if (REMOVE) {
    await removeCopies(de, nodes);
    if (failures) process.exitCode = 1;
    return;
  }
  const mission = nodes.find(n => !n.leaf && n.name === MISSION_FOLDER && parseId(n.id)?.language === 0);
  if (!mission) throw new Error(`The folder "${MISSION_FOLDER}" is missing: run seed-dashboards.ps1 first.`);
  const english = englishDashboardNodes(mission);
  const languages = chosenLanguages();
  const dashboards = await readDashboards(de, english);

  for (const lang of languages) {
    const translate = translator(lang.code);
    const folderId = CHECK_ONLY ? null : await ensureLanguageFolder(de, nodes, lang, String(mission.id));
    const missing = new Set();
    for (const dv of dashboards) {
      if (CHECK_ONLY) checkCopy(dv, lang, translate, nodes, missing);
      else await makeCopy(de, dv, lang, translate, nodes, folderId, missing);
    }
    nodes = await dashboardNodes(de);
    reportMissing(lang, missing);
  }
  if (failures) { console.log(`${failures} problem(s).`); process.exitCode = 1; } else say(CHECK_ONLY ? 'All copies are there.' : 'All copies are made and published.');
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  main().catch(error => { console.log('ERROR ' + error.message); process.exitCode = 1; });
}
