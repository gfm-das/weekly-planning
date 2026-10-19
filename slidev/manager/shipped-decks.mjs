// Decks that ship with the product: today one, the showcase "Everything a deck can do" (shipped-decks/gfm-showcase/).
//
// What it is: when the manager starts, each shipped deck is copied into /slidev/decks once, so it appears in the
// library on a fresh install and, after an update, on an existing one. It never overwrites anything: a folder with the
// same name (a person's own deck) is left alone, and a deck once offered is never offered again, so deleting it in the
// library keeps it deleted. What was offered is written down in /slidev/decks/.gfm-shipped.json.
// Who uses it: server.mjs (at start). SLIDEV_SHIPPED_DECKS=0 turns it off (the tests' manager copies do).
// How it fits: plain Node, no packages; like a deck made with + New Presentation, it has no access rule, so only
// managers see it until they share it.
import fs from 'node:fs/promises';
import path from 'node:path';
import { DECKS_DIR, MANAGER_DIR } from './settings.mjs';

export const SHIPPED_DIR = path.join(MANAGER_DIR, 'shipped-decks');
const LEDGER = '.gfm-shipped.json';

/** Copies every shipped deck not offered before and not already there. Returns { added, kept } (slugs). */
export async function offerShippedDecks({ from = SHIPPED_DIR, to = DECKS_DIR } = {}) {
  await fs.mkdir(to, { recursive: true });
  const ledgerFile = path.join(to, LEDGER);
  const offered = new Set(await fs.readFile(ledgerFile, 'utf8').then(JSON.parse, () => []));
  const added = [], kept = [];
  for (const slug of (await fs.readdir(from).catch(() => [])).sort()) {
    if (offered.has(slug) || !await fs.stat(path.join(from, slug, 'slides.md')).then(() => true, () => false)) continue;
    const target = path.join(to, slug);
    if (await fs.stat(target).then(() => true, () => false)) kept.push(slug);
    else { await fs.cp(path.join(from, slug), target, { recursive: true, force: false, errorOnExist: true }); added.push(slug); }
    offered.add(slug);
  }
  if (added.length || kept.length) await fs.writeFile(ledgerFile, JSON.stringify([...offered].sort(), null, 1) + '\n');
  return { added, kept };
}
