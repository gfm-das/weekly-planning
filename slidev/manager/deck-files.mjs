// A deck's files: its folder, its slides.md and its title.
//
// What it is: every deck is one folder, /slidev/decks/<deck>/, named by its "slug" (the deck's name in small letters
// with dashes, for example "zone-conference"). Inside: slides.md (the slides, written in Markdown), the deck's own
// pictures, and dist/ (the published copy, made by builds.mjs). The deck's title is the `title:` line at the top
// of slides.md (its "headmatter").
// Who uses it: nearly every other file of the manager's server.
// How it fits: this file only finds and reads decks (and writes slides.md); making, copying, renaming and deleting
// a deck is deck-actions.mjs. The title is read with Slidev's own parser, so the manager and Slidev always agree.
import crypto from 'node:crypto';
import fs from 'node:fs/promises';
import path from 'node:path';
// Both packages come with @slidev/cli (in /slidev/node_modules).
import { parseSync } from '@slidev/parser';
import { stringify as yamlStringify } from 'yaml';
import { withProtection } from './protected-decks.mjs';
import { DECKS_DIR } from './settings.mjs';
import { httpError } from './web.mjs';

// ---- names ----

/**
 * The folder name for a NEW Slidev deck: slugify, but never starting with "v2-" (that start is how GFM Presentations V2
 * names its decks in the sharing table, v2-routes.mjs accessKey). Decks that already have such a name keep it.
 */
export function newDeckSlug(title) {
  const slug = slugify(title);
  return slug.startsWith('v2-') ? `deck-${slug}` : slug;
}

/** A deck's folder name for a title: small letters, digits and dashes ("Zone Conference!" gives "zone-conference"). */
export function slugify(value) {
  return String(value || '')
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '');
}

/** The slug itself when it is a clean folder name; otherwise an error (nothing outside /slidev/decks can be named). */
export function safeSlug(value) {
  const slug = slugify(value);
  if (!slug || slug !== value) throw new Error('Invalid presentation id.');
  return slug;
}

/** The deck named by a published deck's address (/p/<deck>/…), or null. */
export function presentationSlugFromPath(pathname) {
  return pathname.match(/^\/p\/([a-z0-9-]+)(?:\/|$)/)?.[1] || null;
}

/** The 404 error for a deck that does not exist. */
export function notFound() {
  return httpError(404, 'Presentation not found.');
}

// ---- where a deck's files are ----

export function deckDir(slug) {
  return path.join(DECKS_DIR, safeSlug(slug));
}

export function deckFile(slug) {
  return path.join(deckDir(slug), 'slides.md');
}

/** The published copy (what viewers see). */
export function builtDir(slug) {
  return path.join(deckDir(slug), 'dist');
}

export async function deckExists(slug) {
  try {
    await fs.access(deckFile(slug));
    return true;
  } catch {
    return false;
  }
}

/**
 * Files that are not part of the deck's own source: the published copy, Slidev's cache, half-finished builds and
 * saves, and `.viewer.md` (left in some folders by an older version of the manager).
 */
export function isGeneratedEntry(name) {
  return name === 'dist' || name === 'node_modules' || name === '.viewer.md' || name === 'slides.md.saving' || name.startsWith('.dist-');
}

// ---- reading ----

/** Every deck (folders with a slides.md), sorted by title: { slug, title, updated_at } plus the protected mark. */
export async function listDecks() {
  await fs.mkdir(DECKS_DIR, { recursive: true });
  const decks = [];
  for (const item of await fs.readdir(DECKS_DIR, { withFileTypes: true })) {
    if (!item.isDirectory() || item.name.startsWith('.')) continue;
    const slug = item.name;
    const file = path.join(DECKS_DIR, slug, 'slides.md');
    try {
      const [markdown, stat] = await Promise.all([fs.readFile(file, 'utf8'), fs.stat(file)]);
      // Protected decks (protected-decks.mjs) carry the reason the library shows instead of Rename and Delete.
      decks.push(withProtection({ slug, title: getTitle(markdown, slug), updated_at: stat.mtime.toISOString() }));
    } catch {
      // A folder without slides.md is not a deck (a few leftover folders exist).
    }
  }
  decks.sort((a, b) => a.title.localeCompare(b.title));
  return decks;
}

/** A deck's title as the library shows it (its folder name when slides.md has none). */
export async function deckTitle(slug) {
  return getTitle(await fs.readFile(deckFile(slug), 'utf8'), slug);
}

/** When the deck's own files last changed (the newest file, published copy and caches left out). */
export async function latestDeckSourceMtime(dir) {
  let latest = 0;
  for (const entry of await fs.readdir(dir, { withFileTypes: true })) {
    if (isGeneratedEntry(entry.name)) continue;
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      latest = Math.max(latest, await latestDeckSourceMtime(full));
      continue;
    }
    const stat = await fs.stat(full).catch(() => null);
    if (stat) latest = Math.max(latest, stat.mtimeMs);
  }
  return latest;
}

/** A short fingerprint of the slides' text. The Source pane sends it back, so a save never overwrites newer work. */
export function sourceVersion(markdown) {
  return crypto.createHash('sha256').update(markdown).digest('hex').slice(0, 20);
}

// ---- writing ----

/** Saves slides.md in one step (written beside it, then renamed), so a reader never sees half a file. */
export async function writeDeckSource(slug, markdown) {
  const file = deckFile(slug);
  const temporary = file + '.saving';
  await fs.writeFile(temporary, markdown, 'utf8');
  await fs.rename(temporary, file);
}

// ---- the title ----

/** A title on one line, without control characters, at most 200 characters. */
export function cleanTitle(value) {
  return String(value ?? '').replace(/[\u0000-\u001f\u007f]+/g, ' ').replace(/\s+/g, ' ').trim().slice(0, 200);
}

/**
 * A title that is safe to write into slides.md. Slidev shows the title as Markdown inside a Vue template, so angle
 * brackets and {{ }} in a new name would break the whole deck's build.
 */
export function safeTitle(value) {
  return cleanTitle(String(value ?? '').replace(/[<>]/g, ' ').replaceAll('{{', '{ ').replaceAll('}}', ' }'));
}

/** Text for a Markdown heading that Slidev shows as written (no HTML, no Vue). */
export function headingText(title) {
  return safeTitle(title).replaceAll('&', '&amp;');
}

// The first slide's settings block (the headmatter), read with Slidev's own parser; null when there is none.
function headmatterOf(markdown) {
  const first = parseSync(markdown, 'slides.md', { preserveCR: true }).slides[0];
  return first?.frontmatterStyle === 'frontmatter' && first.frontmatterDoc ? first : null;
}

/** The deck's title (the headmatter's `title`), or `fallback`. */
export function getTitle(markdown, fallback) {
  try {
    const title = headmatterOf(markdown)?.frontmatter?.title;
    if (title !== undefined && title !== null && String(title).trim()) return cleanTitle(title);
  } catch {
    // Settings Slidev cannot read: the fallback.
  }
  return fallback;
}

function titleError() {
  return httpError(422, 'The settings at the top of this presentation have a mistake, so the name could not be changed. Fix them in Source, then try again.');
}

/**
 * slides.md with a new title. Only the title changes; every other character stays as it was. Several ways are
 * tried in order, and the first whose result Slidev reads back as exactly this title wins.
 */
export function setTitle(markdown, title) {
  const clean = safeTitle(title);
  for (const attempt of titleAttempts(markdown, clean)) {
    try {
      const next = attempt();
      if (getTitle(next, null) === clean) return next;
    } catch {
      // This way did not work; try the next one.
    }
  }
  throw titleError();
}

// The ways to write the title, best first.
function titleAttempts(markdown, clean) {
  const value = yamlStringify(clean, { lineWidth: 0 }).trimEnd();
  const eol = markdown.includes('\r\n') ? '\r\n' : '\n';
  const head = headmatterOf(markdown);
  if (!head) {
    // No settings block yet: add one. A leading bare `---` is only a slide separator, so it becomes the block.
    const block = `---${eol}title: ${value}${eol}theme: default${eol}---${eol}`;
    return [() => (/^---[ \t]*\r?\n[ \t]*\r?\n/.test(markdown) ? block + markdown.replace(/^---[ \t]*\r?\n/, '') : `${block}${eol}${markdown}`)];
  }
  const doc = head.frontmatterDoc;
  if (doc.errors?.length) throw titleError();
  const match = /^---.*\r?\n([\s\S]*?)---/.exec(markdown);
  const offset = match[0].length - 3 - match[1].length;
  const map = doc.contents;
  const pair = map?.items?.find(item => (item.key?.value ?? item.key) === 'title');
  const attempts = [];
  // Best: replace just the value, or add one `title:` line.
  if (pair?.value?.range) attempts.push(() => markdown.slice(0, offset + pair.value.range[0]) + value + markdown.slice(offset + pair.value.range[1]));
  else if (!pair && (!map || (map.items && !map.flow))) attempts.push(() => markdown.slice(0, offset) + `title: ${value}${eol}` + markdown.slice(offset));
  // For unusual settings: write the whole block again through the YAML library.
  attempts.push(() => {
    doc.set('title', clean);
    return markdown.slice(0, offset) + doc.toString({ lineWidth: 0 }).replace(/\r?\n/g, eol) + markdown.slice(offset + match[1].length);
  });
  return attempts;
}
