#!/usr/bin/env node
// Renames the key indicator "Friends found" to "New people being taught"
// (Preach My Gospel's name) in the text people read in existing decks:
// headings, titles, lists and text, speaker notes, chart titles and legends
// (title=, csv=, :rows=, trend-label= …) and kpi="Friends found".
//
// It never touches what the numbers depend on:
// - a chart's query (:query, query=, v-bind:query) or a v-bind object, so a
//   pinned chart keeps its hash;
// - code: fenced blocks in a programming language (```js, ```ts, ```vue,
//   ```json, ```sql …), <script> and <style>;
// - ids such as friends_found.actual (the pattern needs a space, so an
//   underscore or a dash never matches).
// kpi="Friends found" becomes kpi="New people being taught"; both names (and
// the id friends_found) mean the same indicator in <MissionKpiChart>, before
// and after the round-3 addon.
//
// Decks copied from the showcase (Chart gallery, Mission charts) get the
// showcase's own new sentences first: a line that is exactly as the round-2
// showcase had it (SHOWCASE_LINES) becomes the line the showcase has now. So
// the sample funnel reads "New people being taught, Came to church, …" (not
// "…, Taught"), the notes read "Every conversion story begins with a new person
// being taught.", and the text about the old Chart button says Add chart.
// These lines keep every query exactly as it was (tested).
//
// Usage, inside the Slidev container (node is there), as root:
//   node rename-friends-found.mjs /slidev/decks              (a dry run: prints what would change)
//   node rename-friends-found.mjs /slidev/decks --apply      (changes slides.md, keeps a .bak copy)
// Arguments: a folder of decks, deck folders, or slides.md files. --summary
// prints counts only (no slide text). Each changed slides.md is first copied
// to slides.md.<YYYYMMDD-HHMMSS>.bak next to it, then replaced in one step
// (written to slides.md.renaming, then renamed), keeping its line endings.
// Run it while nobody has the deck open in the editor.
import { copyFile, readdir, readFile, rename, stat, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

export const OLD_NAME = 'Friends found';
export const NEW_NAME = 'New people being taught';

// "Friends found" with any capitalisation and spaces or tabs between the words.
const PATTERN = /\b(friends)([ \t]+)(found)\b/gi;

/**
 * [the line as the round-2 showcase had it (git 9114ffe), the line in the
 * round-3 showcase, showcase deck, its line number there]. Made from the git
 * diff of slidev/showcase/<deck>/slides.md (one line for one line);
 * tests/rename-friends-found.test.mjs checks each pair against the showcase.
 */
export const SHOWCASE_LINES = [
  ["<MissionChart type=\"bar\" title=\"Friends found per week (sample)\" trend=\"polynomial\" :degree=\"2\" trend-color=\"#d96b2b\" trend-style=\"solid\" :trend-width=\"3\" trend-label=\"Direction\" :forecast=\"3\" :target=\"30\" target-label=\"Zone goal\" :height=\"380\" csv=\"Week,Friends found; Aug 2,14; Aug 9,17; Aug 16,16; Aug 23,21; Aug 30,20; Sep 6,24; Sep 13,23; Sep 20,27\" />",
   "<MissionChart type=\"bar\" title=\"New people being taught per week (sample)\" trend=\"polynomial\" :degree=\"2\" trend-color=\"#d96b2b\" trend-style=\"solid\" :trend-width=\"3\" trend-label=\"Direction\" :forecast=\"3\" :target=\"30\" target-label=\"Zone goal\" :height=\"380\" csv=\"Week,New people being taught; Aug 2,14; Aug 9,17; Aug 16,16; Aug 23,21; Aug 30,20; Sep 6,24; Sep 13,23; Sep 20,27\" />", 'chart-gallery', 47],
  ["<MissionChart type=\"heatmap\" title=\"Friends found by zone (sample)\" show-values :height=\"360\" csv=\"Week,North,South,East,West; Aug 23,5,3,4,6; Aug 30,7,4,3,5; Sep 6,6,6,5,7; Sep 13,8,5,6,6; Sep 20,9,7,6,8\" />",
   "<MissionChart type=\"heatmap\" title=\"New people being taught by zone (sample)\" show-values :height=\"360\" csv=\"Week,North,South,East,West; Aug 23,5,3,4,6; Aug 30,7,4,3,5; Sep 6,6,6,5,7; Sep 13,8,5,6,6; Sep 20,9,7,6,8\" />", 'chart-gallery', 128],
  ["<MissionChart type=\"radar\" title=\"Share of the goal by zone, % (sample)\" :max=\"120\" :height=\"360\" csv=\"Key indicator,North,South; Friends found,96,82; Baptismal dates,88,104; Sacrament attendance,101,93; Members at lessons,78,90; New members at church,92,86\" />",
   "<MissionChart type=\"radar\" title=\"Share of the goal by zone, % (sample)\" :max=\"120\" :height=\"360\" csv=\"Key indicator,North,South; New people being taught,96,82; Baptismal dates,88,104; Sacrament attendance,101,93; Members at lessons,78,90; New members at church,92,86\" />", 'chart-gallery', 136],
  ["<MissionChart type=\"funnel\" title=\"From finding to baptism (sample)\" show-values :height=\"360\" csv=\"Step,Friends; Friends found,120; Taught,74; Lessons with a member,41; Baptismal date,19; Baptized and confirmed,11\" />",
   "<MissionChart type=\"funnel\" title=\"From finding to baptism (sample)\" show-values :height=\"360\" csv=\"Step,People; New people being taught,120; Came to church,74; Lessons with a member,41; Baptismal date,19; Baptized and confirmed,11\" />", 'chart-gallery', 154],
  ["<MissionChart type=\"treemap\" title=\"Friends found, zone and district (sample)\" show-values :height=\"360\" csv=\"Area,Friends; North / District 1,12; North / District 2,9; South / District 3,11; South / District 4,8; West / District 5,10; West / District 6,6\" />",
   "<MissionChart type=\"treemap\" title=\"New people being taught, zone and district (sample)\" show-values :height=\"360\" csv=\"Area,Friends; North / District 1,12; North / District 2,9; South / District 3,11; South / District 4,8; West / District 5,10; West / District 6,6\" />", 'chart-gallery', 180],
  ["<MissionChart type=\"line\" title=\"Friends found (sample)\" multiples trend=\"linear\" :height=\"360\" csv=\"Week,North,South,East,West; Aug 23,5,3,4,6; Aug 30,7,4,3,5; Sep 6,6,6,5,7; Sep 13,8,5,6,6; Sep 20,9,7,6,8\" />",
   "<MissionChart type=\"line\" title=\"New people being taught (sample)\" multiples trend=\"linear\" :height=\"360\" csv=\"Week,North,South,East,West; Aug 23,5,3,4,6; Aug 30,7,4,3,5; Sep 6,6,6,5,7; Sep 13,8,5,6,6; Sep 20,9,7,6,8\" />", 'chart-gallery', 214],
  ["  charts straight from the weekly plans made with the Chart button.",
   "  charts straight from the weekly plans made with Add chart.", 'mission-charts', 7],
  ["<MissionKpiChart kpi=\"Friends found\" :weeks=\"12\" chart=\"line\" :height=\"262\" />",
   "<MissionKpiChart kpi=\"New people being taught\" :weeks=\"12\" chart=\"line\" :height=\"262\" />", 'mission-charts', 59],
  ["  <span><span class=\"text-[#087f8c] dark:text-[#5cc6cf]\">●</span> Friends found</span>",
   "  <span><span class=\"text-[#087f8c] dark:text-[#5cc6cf]\">●</span> New people being taught</span>", 'mission-charts', 64],
  ["- Left: baptisms and confirmations over the last 12 weeks, the joyful fruit of many weeks of teaching. Right: friends found, where that work begins.",
   "- Left: baptisms and confirmations over the last 12 weeks, the joyful fruit of many weeks of teaching. Right: new people being taught, where that work begins.", 'mission-charts', 74],
  ["# Friends found",
   "# New people being taught", 'mission-charts', 117],
  ["<MissionKpiChart kpi=\"Friends found\" title=\"Mission total per week\" :weeks=\"16\" chart=\"bar\" trend=\"polynomial\" :degree=\"2\" :height=\"312\" />",
   "<MissionKpiChart kpi=\"New people being taught\" title=\"Mission total per week\" :weeks=\"16\" chart=\"bar\" trend=\"polynomial\" :degree=\"2\" :height=\"312\" />", 'mission-charts', 123],
  ["- Friends found is where every conversion story begins.",
   "- Every conversion story begins with a new person being taught.", 'mission-charts', 140],
  ["- Left, a donut chart: how the friends found in one week came to us: through members, our own finding, online contacts and service. With the numbers switched on, each slice shows its count and its share.",
   "- Left, a donut chart: how the new people we began teaching in one week came to us: through members, our own finding, online contacts and service. With the numbers switched on, each slice shows its count and its share.", 'mission-charts', 329],
  ["<div class=\"mx-auto mt-2 max-w-[34rem] text-lg leading-7 opacity-75\">Any number from Weekly Planning and Call-ins, for the mission, a zone, a district or an area, made with the Chart button in the editor.</div>",
   "<div class=\"mx-auto mt-2 max-w-[34rem] text-lg leading-7 opacity-75\">Any number from Weekly Planning and Call-ins, for the mission, a zone, a district or an area, made with Add chart in the editor.</div>", 'mission-charts', 342],
  ["- They are made with the new Chart button in the editor. No typing is needed.",
   "- They are made with Add chart in the editor. No typing is needed.", 'mission-charts', 349],
  ["<MissionChart type=\"heatmap\" title=\"Friends found per zone and week\" show-values :height=\"330\" :query='{\"measures\":[\"friends_found.actual\"],\"level\":\"zone\",\"weeks\":12,\"includeCurrent\":false}' />",
   "<MissionChart type=\"heatmap\" title=\"New people being taught per zone and week\" show-values :height=\"330\" :query='{\"measures\":[\"friends_found.actual\"],\"level\":\"zone\",\"weeks\":12,\"includeCurrent\":false}' />", 'mission-charts', 393],
  ["- Left: a heat map of the last twelve finished weeks. Each row is a zone and each column a week; the brighter the square, the more friends were found. It shows at a glance which weeks were strong across the whole mission and where a zone might need encouragement.",
   "- Left: a heat map of the last twelve finished weeks. Each row is a zone and each column a week; the brighter the square, the more new people were being taught. It shows at a glance which weeks were strong across the whole mission and where a zone might need encouragement.", 'mission-charts', 400],
  ["<MissionChart type=\"bar\" horizontal title=\"Friends found per area, last 4 weeks\" show-values :height=\"440\" :query='{\"measures\":[\"friends_found.actual\"],\"level\":\"area\",\"by\":\"unit\",\"weeks\":4,\"sort\":\"desc\",\"top\":10,\"audience\":\"stewardship\"}' />",
   "<MissionChart type=\"bar\" horizontal title=\"New people being taught per area, last 4 weeks\" show-values :height=\"440\" :query='{\"measures\":[\"friends_found.actual\"],\"level\":\"area\",\"by\":\"unit\",\"weeks\":4,\"sort\":\"desc\",\"top\":10,\"audience\":\"stewardship\"}' />", 'mission-charts', 454],
  ["- A district leader who opens this deck sees the areas of their district; a zone leader the areas of their zone. We see the ten areas with the most friends found in the whole mission.",
   "- A district leader who opens this deck sees the areas of their district; a zone leader the areas of their zone. We see the ten areas with the most new people being taught in the whole mission.", 'mission-charts', 458],
  ["    <div><b>Add a chart.</b> Click <b>Chart</b> at the top. Pick mission numbers (or paste a table), a type and a style, then choose <b>Add chart</b>.</div>",
   "    <div><b>Add a chart.</b> Click <b>Add chart</b> at the top and say what you would like to show. Choose the numbers, a chart type and a look, then <b>Insert chart</b>.</div>", 'mission-charts', 481],
  ["- Step 2: click Chart at the top of the editor. The first step offers ready-made charts, such as friends found with the goal, or sacrament attendance by zone. Choose the numbers, for the mission or each zone, district or area, then a chart type and a style. The preview shows exactly what the slide will get. Choose Add chart.",
   "- Step 2: click Add chart at the top of the editor. It first asks what you would like to show: a key indicator over time, zones or districts side by side, progress toward this week's goals, or your own numbers. Then choose the numbers, for the mission or each zone, district or area, a chart type and a look. The preview shows exactly what the slide will get. Choose Insert chart.", 'mission-charts', 508],
];
let showcase = null;
/**
 * The showcase lines whose new wording is more than the plain rename (a line
 * such as "# Friends found" needs no special case: the rename gives the same).
 */
function showcaseMap() {
  showcase ||= new Map(SHOWCASE_LINES.filter(([from, to]) => renamePhrase(from).text !== to).map(([from, to, deck, line]) => [from, { to, deck, line }]));
  return showcase;
}

// Fenced blocks in these languages are code: left alone.
const CODE_LANGUAGES = new Set(['js', 'javascript', 'mjs', 'ts', 'typescript', 'tsx', 'jsx', 'vue', 'json', 'jsonc', 'json5', 'sql', 'py', 'python', 'sh', 'bash', 'shell', 'powershell', 'ps1', 'html', 'xml', 'css', 'scss', 'yaml', 'yml', 'diff']);

/** The new name in the capitalisation of the old one. */
export function newNameLike(found) {
  const letters = found.replace(/[^a-z]/gi, '');
  if (letters === letters.toUpperCase()) return NEW_NAME.toUpperCase();
  const words = found.trim().split(/[ \t]+/);
  if (words.every(w => w[0] === w[0].toUpperCase())) return NEW_NAME.replace(/\b[a-z]/g, c => c.toUpperCase());
  if (found[0] === found[0].toUpperCase()) return NEW_NAME;
  return NEW_NAME.toLowerCase();
}

// A chart's query or v-bind object, in either quote.
export const QUERY = /(?<![\w-])((?::|v-bind:)?query|v-bind)\s*=\s*("[^"]*"|'[^']*')/g;

/** [start, end, kind, code] ranges of the text that must stay as they are (code: a code block, script or style). */
function protectedRanges(text) {
  const ranges = [];
  // Fenced code blocks (``` or ~~~, three or more; the closing fence is at least as long).
  const lines = text.split('\n');
  let offset = 0;
  let fence = null;
  for (const line of lines) {
    const end = offset + line.length + 1;
    const bare = line.replace(/\r$/, '');
    if (!fence) {
      const open = bare.match(/^\s*(`{3,}|~{3,})\s*([\w+-]*)/);
      if (open) fence = { char: open[1][0], size: open[1].length, lang: open[2].toLowerCase(), start: offset };
    }
    else {
      const close = bare.match(/^\s*(`{3,}|~{3,})\s*$/);
      if (close && close[1][0] === fence.char && close[1].length >= fence.size) {
        if (CODE_LANGUAGES.has(fence.lang)) ranges.push([fence.start, end, `code (${fence.lang})`, true]);
        fence = null;
      }
    }
    offset = end;
  }
  if (fence && CODE_LANGUAGES.has(fence.lang)) ranges.push([fence.start, text.length, `code (${fence.lang})`, true]);
  for (const match of text.matchAll(/<(script|style)\b[\s\S]*?<\/\1\s*>/gi)) ranges.push([match.index, match.index + match[0].length, match[1].toLowerCase(), true]);
  for (const match of text.matchAll(QUERY)) ranges.push([match.index, match.index + match[0].length, match[1], false]);
  return ranges;
}

/** What kind of text a position is in, for the report. */
function kindAt(text, at) {
  const before = text.slice(0, at);
  const comment = before.lastIndexOf('<!--');
  if (comment >= 0 && comment > before.lastIndexOf('-->')) return 'speaker notes';
  const open = before.lastIndexOf('<');
  if (open >= 0 && open > before.lastIndexOf('>')) {
    // Inside a tag: the attribute whose quoted value is still open here.
    const tag = before.slice(open);
    let attr = null;
    for (const m of tag.matchAll(/([:@\w.-]+)\s*=\s*(["'])/g))
      if (tag.indexOf(m[2], m.index + m[0].length) < 0) attr = m[1];
    const name = tag.match(/^<([\w-]+)/)?.[1] ?? 'tag';
    return attr ? `${name} ${attr.replace(/^:/, '')}` : name;
  }
  const lineStart = before.lastIndexOf('\n') + 1;
  const line = text.slice(lineStart, text.indexOf('\n', at) < 0 ? text.length : text.indexOf('\n', at));
  if (/^\s*#{1,6}\s/.test(line)) return 'heading';
  if (/^\s*([-*+]|\d+\.)\s/.test(line)) return 'list';
  if (/^\s*title\s*:/.test(line)) return 'headmatter title';
  return 'text';
}

function lineOf(text, at) {
  let n = 1;
  for (let i = text.indexOf('\n'); i >= 0 && i < at; i = text.indexOf('\n', i + 1)) n++;
  return n;
}

/**
 * Lines exactly as a round-2 showcase had them (outside code) take the
 * showcase's new wording, keeping the line's own ending (\r\n or \n).
 */
function showcaseLines(text, changes) {
  const code = protectedRanges(text).filter(range => range[3]);
  let offset = 0;
  return text.split('\n').map((line, i) => {
    const start = offset;
    offset += line.length + 1;
    const cr = line.endsWith('\r') ? '\r' : '';
    const known = showcaseMap().get(cr ? line.slice(0, -1) : line);
    if (!known || code.some(([from, to]) => start >= from && start < to)) return line;
    changes.push({ line: i + 1, kind: 'showcase text', showcase: `slidev/showcase/${known.deck}/slides.md line ${known.line}` });
    return known.to + cr;
  }).join('\n');
}

/**
 * The text with the name changed where people read it: { text, changes: [{ line, kind, from, to }
 * or { line, kind: 'showcase text', showcase }], kept: [{ line, kind }] } (kept: occurrences left
 * alone because they are code or a query).
 */
export function renameText(source) {
  const changes = [];
  // Showcase lines are replaced one for one, so the line numbers stay the same.
  const text = showcaseLines(String(source), changes);
  const renamed = renamePhrase(text);
  return { text: renamed.text, changes: [...changes, ...renamed.changes].sort((x, y) => x.line - y.line), kept: renamed.kept };
}

/** The plain rename of the phrase outside queries and code: { text, changes, kept }. */
function renamePhrase(text) {
  const ranges = protectedRanges(text);
  const changes = [];
  const kept = [];
  const out = text.replace(PATTERN, (found, a, gap, b, at) => {
    const guard = ranges.find(([start, end]) => at >= start && at < end);
    if (guard) {
      kept.push({ line: lineOf(text, at), kind: guard[2] });
      return found;
    }
    const to = newNameLike(found);
    changes.push({ line: lineOf(text, at), kind: kindAt(text, at), from: found, to });
    return to;
  });
  return { text: out, changes, kept };
}

/** Counts by kind: { 'speaker notes': 3, heading: 1, … }. */
export function countKinds(list) {
  const counts = {};
  for (const { kind } of list) counts[kind] = (counts[kind] ?? 0) + 1;
  return counts;
}

async function slideFiles(args) {
  const files = [];
  for (const arg of args) {
    const info = await stat(arg).catch(() => null);
    if (!info) { console.error(`Not found: ${arg}`); process.exitCode = 1; continue; }
    if (info.isFile()) { files.push(arg); continue; }
    const own = path.join(arg, 'slides.md');
    if (await stat(own).catch(() => null)) { files.push(own); continue; }
    for (const entry of (await readdir(arg, { withFileTypes: true })).sort((x, y) => x.name.localeCompare(y.name))) {
      const file = path.join(arg, entry.name, 'slides.md');
      if (entry.isDirectory() && await stat(file).catch(() => null)) files.push(file);
    }
  }
  return files;
}

function stamp(date = new Date()) {
  const p = n => String(n).padStart(2, '0');
  return `${date.getFullYear()}${p(date.getMonth() + 1)}${p(date.getDate())}-${p(date.getHours())}${p(date.getMinutes())}${p(date.getSeconds())}`;
}

function describe(counts) {
  return Object.entries(counts).map(([kind, n]) => `${kind} ${n}`).join(', ');
}

export async function main(argv = process.argv.slice(2)) {
  const apply = argv.includes('--apply');
  const summary = argv.includes('--summary');
  const args = argv.filter(a => !a.startsWith('--'));
  if (!args.length) {
    console.error('usage: node rename-friends-found.mjs <decks folder | deck folder | slides.md>... [--apply] [--summary]');
    return 2;
  }
  const when = stamp();
  let total = 0, decks = 0;
  for (const file of await slideFiles(args)) {
    const deck = path.basename(path.dirname(file));
    const before = await readFile(file, 'utf8');
    const { text, changes, kept } = renameText(before);
    const keptNote = kept.length ? `; left alone: ${describe(countKinds(kept))}` : '';
    if (!changes.length) { console.log(`[${deck}] no change${keptNote}`); continue; }
    decks++;
    total += changes.length;
    console.log(`[${deck}] ${changes.length} change${changes.length === 1 ? '' : 's'} (${describe(countKinds(changes))})${keptNote}${apply ? '' : ' (dry run)'}`);
    if (!summary) for (const c of changes) console.log(c.showcase ? `  line ${c.line}, ${c.kind}: the showcase's new wording (${c.showcase})` : `  line ${c.line}, ${c.kind}: "${c.from}" -> "${c.to}"`);
    if (!apply) continue;
    const backup = `${file}.${when}.bak`;
    await copyFile(file, backup);
    await writeFile(`${file}.renaming`, text, 'utf8');
    await rename(`${file}.renaming`, file);
    console.log(`  saved; the old file is ${path.basename(backup)}`);
  }
  console.log(`${total} change${total === 1 ? '' : 's'} in ${decks} deck${decks === 1 ? '' : 's'}${apply ? '' : ' (dry run: nothing was written; add --apply to change the files)'}.`);
  return process.exitCode ?? 0;
}

if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) {
  main().then(code => { process.exitCode = code; }, (error) => { console.error(error.message); process.exitCode = 1; });
}
