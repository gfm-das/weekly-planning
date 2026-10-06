// Making, copying, renaming and deleting decks, and a deck's state for the editor page.
//
// What it is: the library's "+ New Presentation", and the ⋮ menu's Duplicate, Rename and Delete. Each one changes a
// deck's folder under /slidev/decks. The routes ask portal-api to move the deck's access rule along with it, so a
// deck and its sharing never get separated.
// Who uses it: manager-routes.mjs.
// How it fits: deck-files.mjs finds and reads decks; this file changes them. A protected deck (protected-decks.mjs:
// another page opens it by its name) is never renamed or deleted.
import fs from 'node:fs/promises';
import path from 'node:path';
import { buildStatus, closeDeckWatcher, forgetBuild } from './builds.mjs';
import { builtDir, deckDir, deckExists, deckFile, getTitle, headingText, latestDeckSourceMtime, notFound, safeSlug, safeTitle, setTitle, newDeckSlug, slugify, sourceVersion, writeDeckSource } from './deck-files.mjs';
import { editorStage, stopEditor } from './editors.mjs';
import { refuseIfProtected } from './protected-decks.mjs';
import { DECKS_DIR } from './settings.mjs';

// Files a copy leaves out: the published copy, Slidev's cache and half-finished saves and builds.
const NOT_COPIED = new Set(['slides.md', 'dist', 'node_modules', '.viewer.md', 'slides.md.saving']);

/**
 * Writes slides.md into the first free folder for this title ("zone-conference", then "zone-conference-2" ...). An
 * empty or leftover folder without slides.md (a few exist) is used again, not an error. Returns the slug.
 */
async function claimDeck(title, markdown) {
  const base = newDeckSlug(title);
  if (!base) throw new Error('Presentation name is required.');
  for (let n = 1; n < 500; n++) {
    const slug = n === 1 ? base : `${base}-${n}`;
    if (await deckExists(slug)) continue;
    await fs.mkdir(deckDir(slug), { recursive: true });
    try {
      await fs.writeFile(deckFile(slug), markdown, { encoding: 'utf8', flag: 'wx' });
      // A leftover folder used again must not show an old published copy under this name.
      await fs.rm(builtDir(slug), { recursive: true, force: true });
      return slug;
    } catch (error) {
      if (error.code !== 'EEXIST') throw error;
    }
  }
  throw new Error('Choose a different presentation name.');
}

/** A new deck with a title slide and one empty slide. Returns its slug. */
export async function createDeck(title) {
  const clean = safeTitle(title);
  if (!slugify(clean)) throw new Error('Presentation name is required.');
  const template = `---\ntheme: default\n---\n\n# ${headingText(clean)}\n\n---\n\n# New Slide\n\nStart building your presentation.\n`;
  return claimDeck(clean, setTitle(template, clean));
}

/** A copy of a deck named "<title> Copy" (its own files, not its published copy). Returns the copy's slug. */
export async function duplicateDeck(slug) {
  safeSlug(slug);
  if (!await deckExists(slug)) throw notFound();
  const sourceMarkdown = await fs.readFile(deckFile(slug), 'utf8');
  const newTitle = safeTitle(`${getTitle(sourceMarkdown, slug)} Copy`);
  const newSlug = await claimDeck(newTitle, setTitle(sourceMarkdown, newTitle));
  for (const entry of await fs.readdir(deckDir(slug))) {
    if (NOT_COPIED.has(entry) || entry.startsWith('.dist-')) continue;
    await fs.cp(path.join(deckDir(slug), entry), path.join(deckDir(newSlug), entry), { recursive: true, force: false });
  }
  return newSlug;
}

// The first free folder name for a title; `exclude` is the deck's own current name (keeping it is fine).
async function uniqueSlugFromTitle(title, exclude = null) {
  const base = newDeckSlug(title);
  if (!base) throw new Error('Presentation name is required.');
  let candidate = base;
  let n = 2;
  while (candidate !== exclude && await deckExists(candidate)) candidate = `${base}-${n++}`;
  return candidate;
}

/**
 * Renames a deck: its title, and its folder when the new title gives another folder name. Then access.move(newSlug)
 * moves the access rule first: if that fails, nothing has changed and trying again is safe. If the folder then
 * cannot follow, access.restore(newSlug) moves the rule back. Publishing is left to the caller. A protected deck is
 * refused before anything changes. Returns { slug, title }.
 */
export async function renameDeck(slug, title, access = {}) {
  safeSlug(slug);
  refuseIfProtected(slug);
  if (!await deckExists(slug)) throw notFound();
  const clean = safeTitle(title);
  if (!slugify(clean)) throw new Error('Presentation name is required.');
  const markdown = setTitle(await fs.readFile(deckFile(slug), 'utf8'), clean);
  const targetSlug = await uniqueSlugFromTitle(clean, slug);
  if (targetSlug === slug) {
    await writeDeckSource(slug, markdown);
    return { slug, title: clean };
  }
  if (access.move) await access.move(targetSlug);
  await moveDeckFolder(slug, targetSlug, markdown, access);
  forgetBuild(slug);
  // The old published copy points at /p/<old-name>/: never show it under the new name.
  await fs.rm(builtDir(targetSlug), { recursive: true, force: true }).catch(error => console.error(`[${targetSlug}:rename]`, error.message));
  // Slidev's cache knows the old folder; it is made again on the next start.
  await fs.rm(path.join(deckDir(targetSlug), 'node_modules'), { recursive: true, force: true }).catch(() => {});
  return { slug: targetSlug, title: clean };
}

// Moves the folder and writes the new title. On a failure the folder (and then the access rule) moves back.
async function moveDeckFolder(slug, targetSlug, markdown, access) {
  let moved = false;
  try {
    await stopEditor(slug);
    closeDeckWatcher(slug);
    if (await fs.stat(deckDir(targetSlug)).then(() => true, () => false)) {
      // A leftover folder without slides.md: keep it out of the way.
      await fs.rename(deckDir(targetSlug), path.join(DECKS_DIR, `.leftover-${targetSlug}-${Date.now()}`));
    }
    await fs.rename(deckDir(slug), deckDir(targetSlug));
    moved = true;
    await writeDeckSource(targetSlug, markdown);
  } catch (error) {
    const back = !moved || await fs.rename(deckDir(targetSlug), deckDir(slug)).then(() => true, e => {
      console.error(`[${slug}:rename] could not move the folder back from ${targetSlug}`, e.message);
      return false;
    });
    // Only move the rule back when the deck is back under its old name too.
    if (back && access.restore) await access.restore(targetSlug).catch(e => console.error(`[${slug}:rename] access rule left under ${targetSlug}`, e.message));
    throw error;
  }
}

/** Deletes a deck's folder (its editor stops first). A protected deck is refused before anything changes. */
export async function deleteDeck(slug) {
  safeSlug(slug);
  refuseIfProtected(slug);
  if (!await deckExists(slug)) throw notFound();
  await stopEditor(slug);
  closeDeckWatcher(slug);
  await fs.rm(deckDir(slug), { recursive: true, force: true });
  forgetBuild(slug);
}

/**
 * What the editor page's status line shows: the title, the slides' version (for Source), when they changed, whether
 * viewers see the latest version, whether a build runs or failed, and the editor's stage.
 */
export async function deckStatus(slug) {
  const markdown = await fs.readFile(deckFile(slug), 'utf8');
  const [sourceMtime, built] = await Promise.all([
    latestDeckSourceMtime(deckDir(slug)),
    fs.stat(path.join(builtDir(slug), 'index.html')).catch(() => null),
  ]);
  return {
    slug,
    title: getTitle(markdown, slug),
    version: sourceVersion(markdown),
    updated_at: new Date(sourceMtime).toISOString(),
    published_at: built ? built.mtime.toISOString() : null,
    up_to_date: !!built && built.mtimeMs >= sourceMtime,
    ...buildStatus(slug),
    editor: editorStage(slug).stage,
  };
}
