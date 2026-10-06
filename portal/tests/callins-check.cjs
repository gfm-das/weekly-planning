// Checks the Call-ins page's own code (portal/callins.html) without a browser. The page script is split into
// numbered parts ("// 4. MOVING AROUND ..."); this check runs parts 1 to 12 (everything but the start) in a small
// sandbox with a stand-in page, then calls the page's functions:
//  - the address: what ?level=&id=&week=&tab= may say, and the address for a place in Call-ins;
//  - the status chips of a mission, zone, district and area, and the status column of the big table;
//  - sorting the big table (names A to Z first, numbers highest first, no number last);
//  - where each note or area update is saved, and how the saved text reaches the page's data;
//  - "Notes" only where there are notes, the timing of a baptismal date, and GEMIKO attendance (old and new form);
//  - one button for each thing (round 9): Go deeper only once per table row, Save all only for two or more notes.
// The behaviour in a browser (typing, saving, Complete / Reopen) is checked by portal-api/tests/edge_callins_checks.ps1.
// Run: node portal/tests/callins-check.cjs
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const page = fs.readFileSync(path.join(__dirname, '../callins.html'), 'utf8').replace(/\r/g, '');

// The code of numbered parts first to last, from the first part's title line up to the title line after the last.
function parts(first, last) {
  const start = page.indexOf(`      // ${first}. `);
  const end = page.indexOf(`      // ${last + 1}. `);
  assert.ok(start > 0 && end > start, `parts ${first} to ${last} not found in callins.html`);
  return page.slice(start, end);
}

// --- The parts are there, in order ----------------------------------------------------------------------------------
const titles = [...page.matchAll(/^ {6}\/\/ (\d+)\. [A-Z]/gm)].map((m) => Number(m[1]));
assert.deepEqual(titles, Array.from({ length: 13 }, (_, i) => i + 1), 'the page script has the parts 1 to 13, in order');

// --- A stand-in page: every element accepts listeners and text; nothing is fetched -----------------------------------
const element = () => ({ addEventListener() {}, querySelector: () => null, querySelectorAll: () => [], classList: { toggle() {} } });
const escapeHTML = (value) =>
  String(value ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
const context = {
  window: { escapeHTML },
  document: { getElementById: element, querySelector: () => null, querySelectorAll: () => [] },
  location: { pathname: '/callins.html', search: '' },
  history: { state: null, pushState() {}, replaceState() {} },
  addEventListener() {},
  URLSearchParams,
  portalAPI: () => assert.fail('the check never asks portal-api'),
};
vm.createContext(context);
const api = [
  'paramsFromSearch', 'urlFor', 'queryString', 'keyOf', 'statusChips', 'rowStatusText', 'sortedChildren', 'fieldTarget',
  'hasNotes', 'timing', 'gemikoAttendance', 'gemikoValue', 'goButton', 'scopeRow', 'DASH', 'state',
];
vm.runInContext(parts(1, 12) + `\nthis.api = { ${api.join(', ')} };`, context);
const callins = context.api;
// Objects made inside the sandbox have another prototype: copy them out so assert compares plain objects.
const plain = (value) => JSON.parse(JSON.stringify(value));

// --- The address ---------------------------------------------------------------------------------------------------------
assert.deepEqual(plain(callins.paramsFromSearch('?level=district&id=51&week=2026-09-27&tab=notes')), { level: 'district', id: 51, week: '2026-09-27', tab: 'notes' });
assert.deepEqual(plain(callins.paramsFromSearch('')), { level: null, id: null, week: '', tab: 'overview' }, 'no address: the viewer\'s own call-in');
assert.deepEqual(plain(callins.paramsFromSearch('?level=planet&id=1')), { level: null, id: null, week: '', tab: 'overview' }, 'an unknown level is ignored');
assert.deepEqual(plain(callins.paramsFromSearch('?level=zone&id=five&tab=admin&week=27.9.2026')), { level: null, id: null, week: '', tab: 'overview' }, 'a bad id, tab or week is ignored');
assert.equal(callins.urlFor({ level: 'zone', id: 5, week: '', tab: 'overview' }), '/callins.html?level=zone&id=5', 'the Overview tab is not written in the address');
assert.equal(callins.urlFor({ level: 'area', id: 511, week: '2026-09-20', tab: 'people' }), '/callins.html?level=area&id=511&week=2026-09-20&tab=people');
assert.equal(callins.urlFor({ level: null, id: null, week: '', tab: 'overview' }), '/callins.html');
assert.equal(callins.queryString({ level: 'district', id: 0, week: '', tab: null, extra: undefined }), 'level=district&id=0', 'empty values are left out, 0 is kept');
assert.equal(callins.keyOf('district', 51, '2026-09-27'), 'district:51:2026-09-27');
console.log('call-ins address: what the address may say, and back');

// --- Status chips and the table's status column ------------------------------------------------------------------------
const chips = (level, status, header) => [...callins.statusChips(level, status, header).matchAll(/<span class="chip( ok| warn)?">([^<]*)<\/span>/g)].map((m) => `${(m[1] || '').trim() || 'plain'}: ${m[2]}`);
assert.deepEqual(chips('mission', { completed_district_count: 4, district_count: 4, zone_count: 2, zones_with_all_reports: 1 }), ['ok: 4 of 4 district call-ins complete', 'warn: Plans in from 1 of 2 zones']);
assert.deepEqual(chips('mission', { completed_district_count: 0, district_count: 0 }), ['warn: 0 of 0 district call-ins complete'], 'no districts is not "all done"');
assert.deepEqual(chips('zone', { completed_district_count: 1, district_count: 3, all_reports_submitted: true }), ['warn: 1 of 3 district call-ins complete', 'ok: All plans submitted']);
assert.deepEqual(chips('district', { dl_call_in_complete: false, all_reports_submitted: false, area_count: 1 }), ['warn: Call-in not complete', 'warn: Plans not submitted yet', 'plain: 1 area']);
assert.deepEqual(chips('area', { all_reports_submitted: false, report_count: 0, dl_call_in_complete: true }), ['warn: No plan yet'], 'on a card an area shows only its plan');
assert.deepEqual(chips('area', { all_reports_submitted: false, report_count: 1, dl_call_in_complete: true }, true), ['warn: Plan not submitted', 'ok: District call-in complete'], 'in the header also the district call-in');
assert.equal(callins.statusChips('zone', null), '', 'no status: no chips');
assert.equal(callins.rowStatusText({ completed_district_count: 2, district_count: 3 }, 'zone'), '2 / 3');
assert.equal(callins.rowStatusText({ dl_call_in_complete: true }, 'district'), 'Complete');
assert.equal(callins.rowStatusText({}, 'area'), 'Missing');
console.log('call-ins status: chips and the table column');

// --- Sorting the big table -------------------------------------------------------------------------------------------------
const kids = [
  { name: 'beta', status: { all_reports_submitted: true }, metrics: { friends_found: { actual: 3 } } },
  { name: 'Alpha', status: { all_reports_submitted: false }, metrics: { friends_found: { actual: null } } },
  { name: 'gamma', status: { all_reports_submitted: true }, metrics: { friends_found: { actual: 7 } } },
];
const order = (sort) => plain(callins.sortedChildren(kids, sort).map((c) => c.name));
assert.deepEqual(order(null), ['beta', 'Alpha', 'gamma'], 'unsorted: as portal-api sent them');
assert.deepEqual(order({ column: 'name', dir: 'ascending' }), ['Alpha', 'beta', 'gamma'], 'names ignore capital letters');
assert.deepEqual(order({ column: 'friends_found', dir: 'descending' }), ['gamma', 'beta', 'Alpha'], 'highest first, no number last');
assert.deepEqual(order({ column: 'reports', dir: 'ascending' }), ['Alpha', 'beta', 'gamma']);
assert.deepEqual(kids.map((c) => c.name), ['beta', 'Alpha', 'gamma'], 'sorting leaves the bundle as it was');
console.log('call-ins table: sorting');

// --- Where notes and area updates are saved ---------------------------------------------------------------------------------
assert.deepEqual(plain({ ...callins.fieldTarget('dl-51'), apply: undefined }), { path: 'callins/districts/51/dl-notes', body: 'dl_notes' });
assert.equal(callins.fieldTarget('zone-5').path, 'callins/zones/5');
assert.equal(callins.fieldTarget('area-511').body, 'update_text');
assert.equal(callins.fieldTarget('secret-1'), null, 'an unknown field is never saved');
// The ZL notes of a district, saved on the zone page: the district's card gets them too.
const zonePage = { scope: { level: 'zone' }, notes: {}, children: [{ id: 51, notes: {} }, { id: 52, notes: {} }] };
callins.fieldTarget('zl-52').apply(zonePage, 'Visit on Wednesday');
assert.deepEqual(plain(zonePage.children.map((c) => c.notes.zl_notes ?? null)), [null, 'Visit on Wednesday']);
assert.equal(zonePage.notes.zl_notes, undefined, 'the zone\'s own notes are not touched');
// An area update saved on the area's own page and on its district page.
const areaPage = { scope: { level: 'area' }, detail: { id: 511 }, children: [] };
callins.fieldTarget('area-511').apply(areaPage, 'Doing well');
assert.equal(areaPage.detail.area_update, 'Doing well');
const districtPage = { scope: { level: 'district' }, children: [{ id: 511 }, { id: 512 }] };
callins.fieldTarget('area-512').apply(districtPage, 'Needs a member');
assert.deepEqual(plain(districtPage.children.map((c) => c.area_update ?? null)), [null, 'Needs a member']);
console.log('call-ins saving: each field goes to its own address');

// --- Small things: the Notes tab, timing, GEMIKO, Go deeper ----------------------------------------------------------------
assert.equal(callins.hasNotes({ scope: { level: 'area' }, notes: { dl_notes: 'x' } }), false, 'an area has no Notes tab');
assert.equal(callins.hasNotes({ scope: { level: 'zone' }, notes: {}, children: [{ notes: {} }] }), false);
assert.equal(callins.hasNotes({ scope: { level: 'zone' }, notes: {}, children: [{ notes: { dl_notes: null } }] }), true, 'a district with a DL notes box');
const timing = (days) => callins.timing({ days_until: days });
assert.deepEqual([null, -1, 0, 7, 8, 15].map(timing), [callins.DASH, 'Date has passed. Talk about a new date?', 'Today', 'This week', '1 week away', '2 weeks away']);
assert.deepEqual(['yes', true, 'no', false, 'dont_have_one', undefined].map(callins.gemikoValue), ['Yes', 'Yes', 'No', 'No', "Don't have one", callins.DASH]);
const oldForm = callins.gemikoAttendance(['Bishop', 'Relief Society']);
assert.ok(/Who came/.test(oldForm) && /Bishop, Relief Society/.test(oldForm), 'older plans list who came');
assert.equal(callins.gemikoAttendance([]), '', 'nobody listed: no line');
const newForm = callins.gemikoAttendance({ elders_quorum_representative: 'yes', gemiko_leader: 'dont_have_one' });
assert.equal((newForm.match(/class="row"/g) || []).length, 8, 'one line per GEMIKO role');
assert.ok(newForm.includes('<span>Elders quorum</span><span>Yes</span>') && newForm.includes("<span>GEMIKO leader</span><span>Don&#39;t have one</span>"));
assert.equal(callins.goButton({ allowed: false, level: 'zone', id: 5, name: 'North' }), '', 'no way in: no button');
assert.ok(/^<button type="button" data-go-level="zone" data-go-id="5"/.test(callins.goButton({ allowed: true, level: 'zone', id: 5, name: 'North' })));
assert.ok(/^<button type="button" class="go" /.test(callins.goButton({ allowed: true, level: 'zone', id: 5, name: 'North' }, true)), 'the table\'s smaller button');
assert.ok(/aria-label="Go deeper into A&amp;B"/.test(callins.goButton({ allowed: true, level: 'zone', id: 5, name: 'A&B' })), 'names are escaped');
console.log('call-ins details: Notes tab, timing, GEMIKO and Go deeper');

// --- One button for each thing (round 9) ---------------------------------------------------------------------------------
// A row of the big table has one button (Go deeper); the name is plain text.
const tableRow = callins.scopeRow({ allowed: true, level: 'zone', id: 5, name: 'A&B', status: {}, metrics: {} },
  { scope: { child_level: 'zone' }, metrics: [{ key: 'friends_found' }] });
assert.equal((tableRow.match(/<button/g) || []).length, 1, 'one button per table row');
assert.ok(tableRow.includes('<td class="name">A&amp;B</td>') && tableRow.includes('>Go deeper ›</button>'), 'the name is plain text');
// The bar at the bottom: one waiting note has its own Save under it, so the bar has Save all only for two or more.
// This stand-in page finds every note box, and nothing else.
const barPage = { barButtons: { innerHTML: '' }, barState: { textContent: '' }, actionBar: { ...element(), hidden: true } };
const barContext = vm.createContext({
  ...context,
  document: {
    getElementById: (id) => barPage[id] || element(),
    querySelector: (selector) => (selector.includes('[data-field=') ? {} : null),
    querySelectorAll: () => [],
  },
});
vm.runInContext(parts(1, 12) + '\nthis.api = { renderBar, drafts, state };', barContext);
const bar = barContext.api;
const waiting = (id) => bar.drafts.set(`2026-09-27|${id}`, { id, week: '2026-09-27', text: 'typed', kept: false });
bar.state.data = { week: { sunday: '2026-09-27' }, scope: { level: 'zone' }, can: {} };
waiting('zone-5');
bar.renderBar();
assert.ok(barPage.actionBar.hidden && !barPage.barButtons.innerHTML.includes('Save'), 'one waiting note: no second Save in the bar');
waiting('zl-51');
bar.renderBar();
assert.ok(!barPage.actionBar.hidden && barPage.barButtons.innerHTML.includes('>Save all (2)</button>'), 'two waiting notes: Save all (2)');
bar.drafts.clear();
bar.state.data = { week: { sunday: '2026-09-27' }, scope: { level: 'district' }, can: { complete: true }, status: {} };
waiting('dl-51');
bar.renderBar();
assert.ok(!barPage.barButtons.innerHTML.includes('>Save') && barPage.barButtons.innerHTML.includes('class="" data-bar="complete"'),
  'a district with one waiting note: Complete call-in is the main button (it saves the note first)');
assert.equal(barPage.barState.textContent, 'Not saved yet', 'the bar still says a note waits');
console.log('call-ins: one button for each thing (table rows, Save all)');
