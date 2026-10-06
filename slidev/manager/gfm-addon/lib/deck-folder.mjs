// A presentation may include files only from its own folder (round 7, zone
// presentations). Slidev can pull another Markdown file into a deck with
// `src:` in a slide's settings, and a file's text into a code block with a
// `<<<` line. Slidev itself refuses files outside /slidev, but every deck
// lives under /slidev/decks, so without this a Zone Leader could show (and,
// through the editor, change) another zone's deck from their own. This
// preparser leaves such a slide empty and drops such a line, in the editor
// and in builds, for every deck. No deck used either when this was added.
import { existsSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

// /slidev/manager: this addon and the chart code it imports (lib/ is two levels down).
const MANAGER_DIR = fileURLToPath(new URL('../../', import.meta.url));

/** True when the path stays inside the deck's folder: relative, no `..` step. */
export function staysInDeck(filePath, { snippet = false } = {}) {
  let text = String(filePath || '').trim();
  // Slidev reads `@/x` in a snippet, and `/x` in `src:`, from the deck's folder.
  if (snippet && text.startsWith('@/')) text = text.slice(2);
  else if (!snippet && text.startsWith('/')) text = text.slice(1);
  if (!text || text.startsWith('/') || text.startsWith('~') || /^[a-z]:/i.test(text)) return false;
  return !text.split(/[\\/]/).includes('..');
}

// `<<< path` (optionally followed by #region, a language or {lines}), as Slidev reads it.
const SNIPPET_LINE = /^\s*<<<\s*(\S+)/;

function snippetPath(line) {
  const match = SNIPPET_LINE.exec(line);
  return match ? match[1].replace(/#.*$/, '').replace(/\{.*$/, '') : null;
}

export function deckFolderPreparser() {
  return [{
    name: 'gfm-addon:deck-folder',
    transformRawLines(lines) {
      for (let i = 0; i < lines.length; i++) {
        const target = snippetPath(lines[i]);
        if (target !== null && !staysInDeck(target, { snippet: true })) lines[i] = '';
      }
    },
    transformSlide(content, frontmatter) {
      if (!frontmatter || typeof frontmatter !== 'object' || !Object.hasOwn(frontmatter, 'src')) return undefined;
      const source = String(frontmatter.src ?? '').split('#')[0];
      if (staysInDeck(source)) return undefined;
      delete frontmatter.src;
      return '';
    },
  }];
}

// ---- Files a deck's page code may load (round 7) ----
// A slide can hold page code (`<script setup>` with `import ... from '<path>'`).
// In the editor, the manager and Vite stop requests for other folders, but in
// `slidev build` nothing did: the build copied any file it could read into the
// published deck, for example another zone's slides.md, or the manager's
// settings through /proc. This Vite plugin refuses to load any file outside
// the deck's own folder, the installed packages (node_modules) and the
// manager's own code (this addon, the chart builder), in builds and in the
// editor. Modules that are not files (Slidev's and Vite's own) pass.

/** True when `file` is `root` itself or inside it (both absolute). */
function isInside(file, root) {
  const rel = path.relative(root, file);
  return rel === '' || (rel.split(path.sep)[0] !== '..' && !path.isAbsolute(rel));
}

/** The file a Vite module id points at, or null for a module that is not a file (`\0…`, `virtual:…`, `/@slidev/…`). */
export function fileOfModule(id) {
  const text = String(id || '');
  if (!text || text.startsWith('\0')) return null;
  const file = text.split('?')[0].split('#')[0];
  if (!path.isAbsolute(file) || !existsSync(file)) return null;
  return path.resolve(file);
}

/** The folders a deck may load files from: its own, node_modules (from Slidev's cliRoot) and the manager's code. */
export function allowedFolders({ userRoot, cliRoot }) {
  const packages = String(cliRoot || '').replace(/[\\/]+$/, '');
  const at = packages.lastIndexOf(`${path.sep}node_modules${path.sep}`);
  return [
    userRoot,
    at === -1 ? null : packages.slice(0, at + `${path.sep}node_modules`.length),
    MANAGER_DIR,
  ].filter(Boolean).map(folder => path.resolve(folder));
}

/** May a deck load this file? True for files in the allowed folders. */
export function deckMayLoad(file, folders) {
  return folders.some(folder => isInside(file, folder));
}

// A slide's `<style>` can also name files. Vite reads those itself (not through
// `load`), so they are checked here:
//   - `@import "x"` and `url(x)`;
//   - any quoted path, so `image-set("x")`, `-webkit-image-set("x")`,
//     `cross-fade("x")` and the like cannot pull in another zone's file. Vite's
//     CSS plugin reads the string candidates in those functions itself, which
//     `url(` and `@import` do not cover.
const CSS_FILE = /@import\s+(?:url\(\s*)?["']?([^"')\s;]+)|url\(\s*["']?([^"')\s]+)/g;
const CSS_QUOTED = /["']([^"'\n]+)["']/g;
const STYLE_MODULE = /[?&]vue&type=style\b|\.(?:css|pcss|postcss)(?:$|\?)/;
const HAS_SCHEME = /^[a-z][a-z0-9+.-]+:/i; // data:, https:, …: not a file here

/** True when this CSS names an existing file outside the allowed folders. `folder`: the CSS file's folder. */
export function cssLeavesDeck(css, folder, userRoot, folders) {
  const text = String(css);
  const targets = [];
  for (const match of text.matchAll(CSS_FILE)) targets.push(match[1] || match[2]);
  for (const match of text.matchAll(CSS_QUOTED)) targets.push(match[1]);
  for (const raw of targets) {
    const target = raw.split('?')[0].split('#')[0];
    if (!target || HAS_SCHEME.test(target)) continue;
    // Vite tries the path next to the CSS and, for `/x`, inside the deck's folder.
    for (const file of [path.resolve(folder, target), path.join(userRoot, target)]) {
      if (existsSync(file) && !deckMayLoad(path.resolve(file), folders)) return true;
    }
  }
  return false;
}

// A slide's own code must not ask where its file lives on the server. Vite turns
// `new URL('<path>', import.meta.url)` into a file read of its own (the
// vite:asset-import-meta-url plugin resolves the path and reads the file), which
// never goes through `load`. A Zone Leader could otherwise write
// `new URL('../other-zone/slides.md', import.meta.url)` or
// `new URL('/proc/1/environ', import.meta.url)` (the manager's service keys) and
// have the file copied into their published deck. A deck has no honest use for
// `import.meta.url`, so it is refused outright in a deck's own code: that cannot
// be got around by building the path or the base URL up in pieces.
const IMPORT_META_URL = /import\s*\.\s*meta\s*\.\s*url/;

const OUTSIDE = 'A presentation may use only the files in its own folder.';

/** The Vite plugin (setup/vite-plugins.ts). `options` are Slidev's (userRoot, cliRoot). */
export function deckFilesPlugin(options = {}) {
  const folders = allowedFolders(options);
  const userRoot = path.resolve(options.userRoot || '.');
  return {
    name: 'gfm-addon:deck-files',
    enforce: 'pre',
    load(id) {
      const file = fileOfModule(id);
      if (!file || deckMayLoad(file, folders)) return null;
      throw new Error(OUTSIDE);
    },
    // Only the deck's own code is checked: themes and addons are installed code.
    transform(code, id) {
      const file = String(id).split('?')[0];
      if (!isInside(path.resolve(file), userRoot)) return null;
      // A slide's code may not read files through `new URL(x, import.meta.url)`.
      if (IMPORT_META_URL.test(code)) throw new Error(OUTSIDE);
      // A slide's `<style>` may name only files in the deck's own folder.
      if (STYLE_MODULE.test(id) && cssLeavesDeck(code, path.dirname(file), userRoot, folders)) throw new Error(OUTSIDE);
      return null;
    },
  };
}
