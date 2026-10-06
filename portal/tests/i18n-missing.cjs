'use strict';
// Lists the interface text of pages that is not in the English catalog yet (the helper for new pages).
//   node portal/tests/i18n-missing.cjs portal/glimpse.html [more files]
//   node portal/tests/i18n-missing.cjs            (every page i18n-check.cjs checks)
// Add each listed text to portal/i18n/en.json under a key, with the same key in the 13 other catalogs; text that is
// not for people (a code, an id) goes into portal/tests/i18n-ignore.json under the file's name instead.
const fs = require('node:fs');
const path = require('node:path');
const { scan, shape } = require('./i18n-scan.cjs');

const ROOT = path.join(__dirname, '..', '..');
const I18N = path.join(ROOT, 'portal', 'i18n');
// Every page and script with interface text (paths from the repository root).
const PAGES = [
  'portal/index.template.html', 'portal/portal-enhancements.js', 'portal/portal-client.js', 'portal/home.html',
  'portal/calendar.html', 'portal/announcements.html', 'portal/planning.html', 'portal/callins.html',
  'portal/office-only.html',
  'portal-api/app.py', 'portal-api/planning.py', 'portal-api/callins.py', 'portal-api/roles.py', 'portal-api/reminders.py',
  // DA Management (roster-importer/, split into small files in round 9: its README lists them).
  'roster-importer/app.py', 'roster-importer/page.py', 'roster-importer/sign_in.py', 'roster-importer/supabase_auth.py',
  'roster-importer/database.py', 'roster-importer/batches.py', 'roster-importer/roles.py', 'roster-importer/places.py',
  'roster-importer/roster_file.py', 'roster-importer/transfer.py', 'roster-importer/transfer_pages.py',
  'roster-importer/account_manager.py', 'roster-importer/account_links.py', 'roster-importer/account_page.py',
  'roster-importer/account_roles.py', 'roster-importer/account_changes.py', 'roster-importer/account_moves.py',
  'roster-importer/staff_accounts.py', 'roster-importer/planning_questions.py', 'roster-importer/planning_questions_pages.py',
  'roster-importer/historical_import.py', 'roster-importer/historical_units.py', 'roster-importer/historical_preview.py',
  'roster-importer/historical_apply.py', 'roster-importer/historical_pages.py', 'roster-importer/mappings_page.py',
  'roster-importer/import_history.py', 'roster-importer/undo.py', 'roster-importer/docs_page.py',
  'portal-api/charts.py', 'slidev/manager/server.mjs', 'slidev/manager/studio.html', 'slidev/manager/chart-builder.mjs', 'slidev/manager/portal-bridge.js',
  // The presentation manager's server, split out of server.mjs in round 9 (slidev/manager/README.md).
  'slidev/manager/library.html', 'slidev/manager/pages.mjs', 'slidev/manager/manager-routes.mjs', 'slidev/manager/deck-routes.mjs',
  'slidev/manager/sign-in.mjs', 'slidev/manager/access.mjs', 'slidev/manager/deck-files.mjs', 'slidev/manager/deck-actions.mjs',
  'slidev/manager/builds.mjs', 'slidev/manager/editors.mjs', 'slidev/manager/numbers.mjs', 'slidev/manager/settings.mjs', 'slidev/manager/web.mjs',
  'slidev/manager/gfm-addon/lib/chart-builder-core.mjs', 'slidev/manager/gfm-addon/lib/chart-spec.mjs',
  // Pages other streams add (glimpse r5/portalx, Whiteboard r6/whiteboard2, zone presentations r6/zonedecks, Data uploads
  // r7/uploads): checked once they are merged (a file that does not exist yet is skipped).
  'portal/glimpse.js', 'portal/whiteboard/index.html', 'portal/whiteboard/whiteboard.js', 'portal/whiteboard/board-core.js',
  'slidev/manager/whiteboard-chart.mjs', 'slidev/manager/whiteboard-builder.mjs', 'slidev/manager/whiteboard-frames.mjs',
  'portal-api/whiteboards.py', 'portal-api/dashboard.py', 'slidev/manager/zone-decks.mjs', 'slidev/manager/chart-access.mjs',
  'roster-importer/data_text.py', 'roster-importer/data_uploads.py', 'roster-importer/data_upload_pages.py',
  'roster-importer/data_types.py', 'roster-importer/data_files.py', 'roster-importer/data_names.py',
  // Merged after round 6: Archetypal Health (r6/archetypes), DA Management › Updates (r7/updater), the Dashboards
  // gate pages of DataEase (r6/dataease; DataEase's own interface is r6/dataease-i18n).
  'portal/archetypes.html', 'portal/archetype-settings.html', 'portal/archetypes-common.js',
  'portal-api/archetypes.py', 'portal-api/archetype_model.py', 'portal-api/dataease_auth.py',
  'roster-importer/updates_page.py',
  'dataease/web/gfm/starting.html', 'dataease/web/gfm/refused.html', 'dataease/web/gfm/signin.html', 'dataease/web/gfm/signin.js',
];

function englishShapes() {
  const en = JSON.parse(fs.readFileSync(path.join(I18N, 'en.json'), 'utf8'));
  const shapes = new Set();
  for (const value of Object.values(en)) for (const text of (value && typeof value === 'object' ? Object.values(value) : [value])) shapes.add(shape(text));
  return shapes;
}
function ignored() {
  try { return JSON.parse(fs.readFileSync(path.join(__dirname, 'i18n-ignore.json'), 'utf8')); } catch { return {}; }
}
function missing(files = PAGES) {
  const shapes = englishShapes(), skip = ignored(), all = skip['*'] || [];
  const result = [];
  for (const file of files) {
    const relative = path.relative(ROOT, path.resolve(ROOT, file)).split(path.sep).join('/');
    if (!fs.existsSync(path.join(ROOT, relative))) continue;
    const own = new Set([...(skip[relative] || []), ...all].map(shape));
    const seen = new Set();
    for (const found of scan(relative, fs.readFileSync(path.join(ROOT, relative), 'utf8'))) {
      const s = shape(found.text);
      // As i18n.js reads it: a piece after a code or name ("· required") is the rest on its own.
      const rest = s.replace(/^[·•|:]\s+/, '');
      if (shapes.has(s) || shapes.has(rest) || own.has(s) || seen.has(s)) continue;
      seen.add(s);
      result.push(found);
    }
  }
  return result;
}
module.exports = { PAGES, missing, englishShapes };

if (require.main === module) {
  const list = missing(process.argv.length > 2 ? process.argv.slice(2) : PAGES);
  for (const r of list) console.log(`${r.file}:${r.line}\t${r.attr ? '[' + r.attr + '] ' : ''}${r.text}`);
  console.error(list.length + ' texts are not in portal/i18n/en.json');
  process.exitCode = list.length ? 1 : 0;
}
