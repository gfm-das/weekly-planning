// Checks the Weekly Planning page's own code (portal/planning.html) without a browser. The page script is split into
// numbered parts ("// 2. SHOW/HIDE RULES ..."); each check below runs one or more whole parts in a small sandbox.
//  - The show/hide rules (part 2) must work exactly like the server's (planning._rule_passes and planning._visibility,
//    see portal-api/tests/test_planning_catalog.py).
//  - The grid code (part 3: gridChanges and mergeGrid) is run through two companions answering the same grid: a row
//    this page never changed must never be sent, so a companion's answer in it is never overwritten.
//  - The number boxes (part 5) have whole limits when only whole numbers are allowed.
//  - Small helpers: "Last week: ..." (part 5), what counts as answered (part 9), the details under a person's name
//    and the Yes / No pills (part 6), and the checks of the create / edit / Baptized form (part 13).
//  - Nothing is left over from Appsmith Beta: the page no longer posts 'mission-planning-activity' (round 9).
//  - The bar at the bottom (round 9): Save is only there after a save failed; a submitted plan has no bar.
//  - The ward or branch (round 9): a list only when the area has more than one, else its name as text.
// Run: node portal/tests/planning-rules-check.cjs
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const page = fs.readFileSync(path.join(__dirname, '../planning.html'), 'utf8');

// The code of numbered part n of the page script, from its title line up to the next part's title line.
function part(n) {
  const start = page.indexOf(`      // ${n}. `);
  const end = page.indexOf(`      // ${n + 1}. `);
  assert.ok(start > 0 && end > start, `part ${n} not found in planning.html`);
  return page.slice(start, end);
}
// A sandbox with the given globals that has run the given parts; api names what the checks call.
function sandbox(globals, parts, api) {
  const context = { ...globals };
  vm.createContext(context);
  vm.runInContext(parts.map(part).join('\n') + `\nthis.api = { ${api.join(', ')} };`, context);
  return context;
}
// Objects made inside a sandbox have another prototype: copy them out so assert compares plain objects.
const plain = (value) => JSON.parse(JSON.stringify(value));

// --- The parts are there, in order ----------------------------------------------------------------------------------
const titles = [...page.matchAll(/^ {6}\/\/ (\d+)\. ([A-Z][A-Z' /:-]+)/gm)].map((m) => Number(m[1]));
assert.deepEqual(titles, Array.from({ length: 15 }, (_, i) => i + 1), 'the page script has the parts 1 to 15, in order');
assert.ok(!page.includes('mission-planning-activity'), 'nothing posts the old Appsmith activity message');
assert.ok(!/parent\.postMessage/.test(page), 'the page sends no messages to the portal frame');

// --- Show/hide rules (part 2) ---------------------------------------------------------------------------------------
const rules = sandbox({ data: null }, [2], ['rulePasses', 'applyConditions', 'blank', 'hiddenAnswer', 'hasHiddenAnswer']);
const { rulePasses, applyConditions, blank, hiddenAnswer, hasHiddenAnswer } = rules.api;

const q = (key, type, extra = {}) => ({ question_key: key, question_type: type, rules: [], value_when_hidden: null, ...extra });
const gt0 = (parent) => ({ parent, operator: 'greater_than', value: '0' });
const rule = (operator, value) => ({ parent: 'p', operator, value });

// Single rules, as the server's _rule_passes (and Appsmith Beta's passesVisibilityRule before it).
assert.ok(rulePasses(rule('equals', 'true'), true) && rulePasses(rule('equals', 'TRUE'), 'true') && !rulePasses(rule('equals', 'true'), null));
assert.ok(rulePasses(rule('equals', 'false'), false) && !rulePasses(rule('equals', 'false'), ''));
assert.ok(rulePasses(rule('equals', 'visit'), 'visit') && !rulePasses(rule('equals', 'visit'), 'phone'));
assert.ok(rulePasses(rule('not_equals', 'visit'), null));
assert.ok(rulePasses(rule('equals', '3'), 3));
assert.ok(rulePasses(rule('greater_than', '0'), 1) && !rulePasses(rule('greater_than', '0'), 0));
assert.ok(!rulePasses(rule('greater_than', '0'), null) && !rulePasses(rule('greater_than', '0'), '') && !rulePasses(rule('greater_than', '0'), true));
assert.ok(rulePasses(rule('greater_than_or_equal', '2'), '2') && rulePasses(rule('less_than', '2'), 1.5));
assert.ok(rulePasses(rule('less_than_or_equal', '2'), 2) && !rulePasses(rule('less_than', 'x'), 1));
assert.ok(rulePasses(rule('contains', 'x'), null), 'an unknown rule shows the question');

// The sacrament follow-ups (migration 024 rules and value_when_hidden '0').
rules.data = {
  questions: [
    q('sacrament_attendance_actual', 'NUMBER'),
    q('sacrament_first_time', 'NUMBER', { value_when_hidden: '0', rules: [gt0('sacrament_attendance_actual')] }),
    q('sacrament_first_time_first_week', 'NUMBER', { value_when_hidden: '0', rules: [gt0('sacrament_attendance_actual'), gt0('sacrament_first_time')] }),
    q('ward_coordination_held', 'BOOLEAN'),
    q('ward_coordination_attendance', 'GRID', { rules: [{ parent: 'ward_coordination_held', operator: 'equals', value: 'true' }] }),
  ],
};
const run = (answers) => {
  const values = { sacrament_first_time: 7, sacrament_first_time_first_week: 7, ward_coordination_attendance: { a: 'yes' }, ...answers };
  return { hidden: [...applyConditions(values)].sort(), values };
};
let result = run({ sacrament_attendance_actual: 0 });
assert.deepEqual(result.hidden, ['sacrament_first_time', 'sacrament_first_time_first_week', 'ward_coordination_attendance']);
assert.equal(result.values.sacrament_first_time, 0);
assert.equal(result.values.sacrament_first_time_first_week, 0);
assert.deepEqual(result.values.ward_coordination_attendance, { a: 'yes' }, 'no value when hidden: the answer is kept');
result = run({ sacrament_attendance_actual: '' });
assert.equal(result.values.sacrament_first_time, '');
assert.equal(result.values.sacrament_first_time_first_week, '');
result = run({ sacrament_attendance_actual: 5, sacrament_first_time: 0, ward_coordination_held: true });
assert.deepEqual(result.hidden, ['sacrament_first_time_first_week']);
assert.equal(result.values.sacrament_first_time_first_week, 0);
result = run({ sacrament_attendance_actual: 5, sacrament_first_time: 2, ward_coordination_held: true });
assert.deepEqual(result.hidden, []);

// A hidden parent hides its children, in whatever order the questions come.
const chain = [q('a', 'NUMBER'), q('b', 'NUMBER', { rules: [gt0('a')] }), q('c', 'BOOLEAN', { rules: [{ parent: 'b', operator: 'less_than', value: '100' }] })];
for (const questions of [chain, [...chain].reverse()]) {
  rules.data = { questions };
  assert.deepEqual([...applyConditions({ a: 0, b: 5, c: '' })].sort(), ['b', 'c']);
}
// A rule on a question that is not on the form (retired) is ignored.
rules.data = { questions: [q('child', 'NUMBER', { rules: [gt0('retired_question')] })] };
assert.deepEqual([...applyConditions({ child: '' })], []);

// The small helpers of the rules: no answer, and what a hidden follow-up counts as.
assert.ok([null, undefined, '', [], {}].every(blank) && ![0, false, 'x', ['a'], { a: 1 }].some(blank), 'blank: only "no answer" is blank');
assert.equal(hiddenAnswer(q('n', 'NUMBER', { value_when_hidden: '0' })), 0);
assert.equal(hiddenAnswer(q('b', 'BOOLEAN', { value_when_hidden: 'TRUE' })), true);
assert.equal(hiddenAnswer(q('t', 'TEXT', { value_when_hidden: 'none' })), 'none');
assert.ok(hasHiddenAnswer(q('f', 'NUMBER', { value_when_hidden: '0', rules: [gt0('a')] })));
assert.ok(!hasHiddenAnswer(q('f', 'NUMBER', { value_when_hidden: '0' })), 'a value when hidden without a rule is never used');
assert.ok(!hasHiddenAnswer(q('f', 'NUMBER', { value_when_hidden: '', rules: [gt0('a')] })));
console.log('planning rules: page and server agree');

// --- Grid answers: merged row by row (part 3) -----------------------------------------------------------------------
const grid = sandbox({ data: null }, [3], ['gridChanges', 'mergeGrid']);
const { mergeGrid } = grid.api;
const gridChanges = (key, value) => plain(grid.api.gridChanges(key, value));

// A grid on the page: one radio input per row and choice (only what mergeGrid and questionValue read).
const ROWS = ['elders', 'relief', 'young_women', 'seniors'];
const makeGrid = () => {
  const inputs = ROWS.flatMap((row) => ['yes', 'no'].map((value) => ({ dataset: { row }, value, checked: false })));
  return { inputs, querySelectorAll: () => inputs };
};
const shown = (wrap) => Object.fromEntries(wrap.inputs.filter((i) => i.checked).map((i) => [i.dataset.row, i.value]));
const click = (wrap, row, value) => wrap.inputs.filter((i) => i.dataset.row === row).forEach((i) => (i.checked = i.value === value));
// One page (companion A) and the saved plan on the server.
const pageOf = (server) => {
  const wrap = makeGrid();
  grid.data = { answers: { w: { ...server } } };
  wrap.inputs.forEach((i) => (i.checked = server[i.dataset.row] === i.value));
  return {
    wrap,
    // What A's save sends for the grid (changedAnswers), then (after `meanwhile`, e.g. a companion's save or
    // a click while the save is on its way) the server merges it and A merges the reply (mergeAnswers).
    save(meanwhile) {
      const sent = gridChanges('w', shown(wrap));
      Object.assign(server, sent);
      meanwhile?.();
      const before = grid.data.answers.w, fresh = { ...server };
      grid.data.answers = { w: fresh };
      mergeGrid(wrap, before, fresh, Object.keys(sent).length ? sent : undefined);
      return sent;
    },
  };
};

// The review's case: B answers a row A never touches; A then answers two other rows.
let server = {};
let a = pageOf(server);
server.young_women = 'yes'; // B's save
click(a.wrap, 'relief', 'yes');
assert.deepEqual(a.save(), { relief: 'yes' });
assert.equal(shown(a.wrap).young_women, 'yes', "A's page shows B's answer after A's next save");
click(a.wrap, 'seniors', 'yes');
assert.deepEqual(a.save(), { seniors: 'yes' }, "A's second save sends only its own row");
assert.deepEqual(server, { young_women: 'yes', relief: 'yes', seniors: 'yes' }, "B's answer survives");

// B changes a row A answered earlier: A shows B's newer answer and does not send its older one again.
server = { elders: 'yes' };
a = pageOf(server);
server.elders = 'no'; // B's save
click(a.wrap, 'relief', 'no');
a.save();
assert.equal(shown(a.wrap).elders, 'no');
click(a.wrap, 'seniors', 'no');
assert.deepEqual(a.save(), { seniors: 'no' });
assert.equal(server.elders, 'no');

// A clicks another row while its save is on the way: that row stays as clicked and goes with the next save.
server = {};
a = pageOf(server);
click(a.wrap, 'elders', 'yes');
a.save(() => click(a.wrap, 'relief', 'no'));
assert.deepEqual(shown(a.wrap), { elders: 'yes', relief: 'no' });
assert.deepEqual(gridChanges('w', shown(a.wrap)), { relief: 'no' });
// ... or clicks the row it just sent again: the new click wins.
a.save(() => click(a.wrap, 'relief', 'yes'));
assert.equal(shown(a.wrap).relief, 'yes');
assert.deepEqual(gridChanges('w', shown(a.wrap)), { relief: 'yes' });
// B answers the row A just sent, after A's save: A shows B's newer answer and sends nothing more.
server = {};
a = pageOf(server);
click(a.wrap, 'elders', 'yes');
a.save(() => (server.elders = 'no'));
assert.equal(shown(a.wrap).elders, 'no');
assert.deepEqual(gridChanges('w', shown(a.wrap)), {});
console.log('planning grid: companions keep each other\'s rows');

// --- Number boxes: a whole-number box has whole limits (part 5) ------------------------------------------------------
// A box counts its steps from min, so min="0.5" step="1" would make every whole number wrong (the review's case:
// 2 was refused as "Enter a whole number" and never saved). The page rounds such limits inwards.
const controls = sandbox({ data: { can_edit: true }, esc: (value) => String(value), blank }, [5], ['questionControl', 'previousText', 'questionWidth']);
const box = (extra) => controls.api.questionControl(q('count', 'NUMBER', { integer_only: true, min_value: null, max_value: null, ...extra }), '');
const attr = (html, name) => (html.match(new RegExp(` ${name}="([^"]*)"`)) || [])[1];
let html = box({ min_value: 0.5, max_value: 9.5 });
assert.deepEqual([attr(html, 'min'), attr(html, 'max'), attr(html, 'step')], ['1', '9', '1'], html);
html = box({ min_value: -2.5 });
assert.deepEqual([attr(html, 'min'), attr(html, 'max'), attr(html, 'step')], ['-2', undefined, '1'], html);
html = box({});
assert.deepEqual([attr(html, 'min'), attr(html, 'step'), attr(html, 'inputmode')], ['0', '1', 'numeric'], html);
html = box({ integer_only: false, min_value: 0.5, max_value: 9.5 });
assert.deepEqual([attr(html, 'min'), attr(html, 'max'), attr(html, 'step')], ['0.5', '9.5', 'any'], 'decimals keep their limits');
console.log('planning numbers: whole-number boxes have whole limits');

// --- Other question controls and "Last week: ..." (part 5) -----------------------------------------------------------
const yesNo = controls.api.questionControl(q('held', 'BOOLEAN'), '');
assert.equal((yesNo.match(/type="radio"/g) || []).length, 2, 'Yes / No: two choices');
assert.ok(!/checked/.test(yesNo), 'Yes / No stays unanswered until chosen');
assert.ok(/value="false" checked/.test(controls.api.questionControl(q('held', 'BOOLEAN'), false)), 'No is shown as chosen');
controls.data = { can_edit: false };
assert.ok(/ disabled>/.test(controls.api.questionControl(q('t', 'TEXT'), 'x')), 'a plan that cannot be edited has disabled boxes');
controls.data = { can_edit: true };
const choices = [{ value: 'a', label: 'Apple' }, { value: 'b', label: 'Banana' }];
const previous = (type, value, extra = {}) => controls.api.previousText(q('p', type, { previous: value, options: choices, ...extra }));
assert.equal(previous('NUMBER', null), '', 'nothing last week: no line');
assert.equal(previous('BOOLEAN', true), 'Yes');
assert.equal(previous('BOOLEAN', false), 'No');
assert.equal(previous('SELECT', 'b'), 'Banana', 'a choice shows its words, not its code');
assert.equal(previous('RADIO', 'gone'), 'gone', 'a choice no longer offered shows what was saved');
assert.equal(previous('CHECKBOX', ['a', 'b']), 'Apple, Banana');
assert.equal(previous('GRID', { r1: 'a', r2: 'b' }, { rows: [{ key: 'r1', label: 'Elders' }, { key: 'r2', label: 'Relief Society' }] }), 'Elders: Apple · Relief Society: Banana');
assert.equal(previous('LONG_TEXT', 'x'.repeat(200)).length, 140, 'long text is cut to 140 characters');
assert.ok(previous('LONG_TEXT', 'x'.repeat(200)).endsWith('…'));
assert.deepEqual(plain(['LONG_TEXT', 'CHECKBOX', 'RADIO', 'GRID', 'NUMBER'].map(controls.api.questionWidth)), ['long', 'long', 'long', 'grid-question', '']);
console.log('planning questions: controls and last week\'s answers');

// --- What counts as answered (parts 2 and 9) --------------------------------------------------------------------------
const answered = sandbox({}, [2, 9], ['isAnswered', 'cannotBeAnswered', 'blankAnswer']).api;
assert.ok(answered.isAnswered(q('b', 'BOOLEAN'), false) && !answered.isAnswered(q('b', 'BOOLEAN'), ''), 'Yes / No: No is an answer');
const rows = { rows: [{ key: 'r1' }, { key: 'r2' }] };
assert.ok(answered.isAnswered(q('g', 'GRID', rows), { r1: 'a', r2: 'b' }) && !answered.isAnswered(q('g', 'GRID', rows), { r1: 'a' }), 'a grid needs every row');
assert.ok(answered.isAnswered(q('n', 'NUMBER'), 0), 'zero is an answer');
assert.ok(!answered.isAnswered(q('t', 'TEXT'), '   '), 'spaces are no answer');
assert.ok(answered.cannotBeAnswered(q('s', 'SELECT', { options: [] })) && answered.cannotBeAnswered(q('g', 'GRID', { options: choices, rows: [] })));
assert.ok(!answered.cannotBeAnswered(q('s', 'SELECT', { options: choices })) && !answered.cannotBeAnswered(q('n', 'NUMBER')));
assert.ok(answered.blankAnswer(null) && answered.blankAnswer(' ') && !answered.blankAnswer(false) && !answered.blankAnswer(0));
console.log('planning submit check: what counts as answered');

// --- Person cards (parts 4 and 6) ---------------------------------------------------------------------------------------
const people = sandbox({ data: { can_edit: true }, esc: (value) => String(value), REQUIRED_MARK: '*' }, [4, 6], ['personDetails', 'field', 'personActions', 'tabLabel']).api;
const shortDate = (date) => new Date(date + 'T12:00:00').toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' });
assert.deepEqual(plain(people.personDetails({ person: { baptism_date: '2026-08-02', finding_source: 'Member' } }, 'new_members')),
  ['Baptized ' + shortDate('2026-08-02'), 'Not confirmed yet', 'Found through Member']);
assert.deepEqual(plain(people.personDetails({ person: {} }, 'new_members')), [], 'nothing known yet: no details');
assert.deepEqual(plain(people.personDetails({ person: {} }, 'baptismal_friends')), ['Finding source not entered yet (use Edit details)']);
const pills = people.field('reading', 'yesno', null), threeWay = people.field('has_calling', 'yesnona', 'not_applicable');
assert.ok(/data-pills="yesno"/.test(pills) && (pills.match(/type="radio"/g) || []).length === 2 && !/checked/.test(pills), 'Yes / No pills start unanswered');
assert.ok((threeWay.match(/type="radio"/g) || []).length === 3 && /value="not_applicable" checked/.test(threeWay));
assert.ok(/max="100"/.test(people.field('pmg_lessons_percentage', 'number', 50)), 'the percentage cannot go over 100');
assert.ok(!/\*/.test(people.field('notes', 'textarea', '', { label: 'Notes (optional)', optional: true })), 'an optional question has no star');
assert.ok(/data-person-action="baptized"/.test(people.personActions({ baptismal_date_person_id: 9 }, 'baptismal_friends')));
assert.equal(people.personActions({ new_member_id: 9, is_current: false }, 'new_members'), '', 'no actions for someone no longer in the area');
assert.equal(people.tabLabel('high_potential', { name: 'New High Potential' }), 'New friend', 'a friend without a name yet');
console.log('planning people: details, pills and actions');

// --- The bar at the bottom (parts 7, 10 and 11, round 9): Save only after a save failed --------------------------------
// Saving is automatic, so the bar shows Submit; Save appears only when a save did not go through (it tries again), and
// a submitted plan has no bar at all.
assert.match(page, /<button class="secondary" id="saveBtn" hidden>Save<\/button/, 'Save starts hidden');
assert.match(part(7), /\$\("actions"\)\.hidden = !data\.can_edit;/, 'a submitted plan has no save bar');
{
  const saveBtn = { hidden: true }, saveState = { textContent: '' }, message = { textContent: '', className: '' };
  const bar = sandbox({
    $: (id) => (id === 'saveBtn' ? saveBtn : null), saveState, message, window: {}, addEventListener: () => {},
    data: { report: { report_id: 1 }, questions: [] }, changed: { answers: new Set(), people: new Map(), removals: new Set() },
    hasChanges: () => false, badNumbers: () => [],
  }, [10, 11], ['showSaveError', 'useSaveReplies']).api;
  assert.throws(() => bar.showSaveError(new Error('The planning service is not reachable right now.')), /not reachable/);
  assert.ok(!saveBtn.hidden && saveState.textContent === 'Not saved', 'a failed save shows Save, to try again');
  const ok = { status: 'fulfilled', value: { ok: true } };
  bar.useSaveReplies([ok, ok], 1, { answers: new Set(), people: new Map(), removals: new Set() }, {}, true);
  assert.ok(saveBtn.hidden && saveState.textContent === 'Saved just now' && message.textContent === '', 'a good save hides it again');
}
console.log('planning bar: Submit, and Save only to try again');

// --- The ward or branch (part 7, round 9): a list only when there is a choice ---------------------------------------
// Most areas have one ward or branch: its name is then shown as text, not as a list with one choice.
{
  const unitSelect = { hidden: false, innerHTML: '' }, unitName = { hidden: true, textContent: '' };
  const week = sandbox({ $: (id) => (id === 'unitName' ? unitName : null), unitSelect, esc: (value) => String(value), data: null }, [7], ['fillUnitSelect']);
  const ward = { unit_id: 5, unit: 'Sample Ward' }, branch = { unit_id: 6, unit: 'Sample Branch' };
  week.data = { units: [ward], report: { unit_id: 5 } };
  week.api.fillUnitSelect();
  assert.ok(unitSelect.hidden && !unitName.hidden && unitName.textContent === 'Sample Ward', 'one ward: its name as text, no list');
  assert.match(unitSelect.innerHTML, /value="5" selected/, 'the hidden list still holds the plan\'s ward (the page reads it)');
  week.data = { units: [ward, branch], report: { unit_id: 6 } };
  week.api.fillUnitSelect();
  assert.ok(!unitSelect.hidden && unitName.hidden && unitName.textContent === '', 'two: the list to choose from');
  assert.match(unitSelect.innerHTML, /value="6" selected/);
}
console.log('planning week card: the ward or branch as a list only when there is a choice');

// --- The create / edit / Baptized form's own check (part 13) --------------------------------------------------------
// $() finds a box only for the fields the form shows: in "convert" (Baptized) the name and finding source are shown as
// text, not asked.
const boxes = new Set();
const create = sandbox({
  data: { person_options: { new_member_required: ['last_name', 'baptism_date', 'confirmation_date', 'child_dependents'] } },
  $: (id) => (boxes.has(id) ? { validity: {} } : null),
}, [13], ['createErrors']);
const createErrors = (kind, mode, values) => {
  vm.runInContext(`createKind = ${JSON.stringify(kind)}; createMode = ${JSON.stringify(mode)};`, create);
  const shownAsText = mode === 'convert' ? vm.runInContext('FROM_FRIEND_RECORD', create) : [];
  boxes.clear();
  for (const [key] of vm.runInContext(`CREATE_FORMS[${JSON.stringify(kind)}].fields`, create))
    if (!shownAsText.includes(key)) boxes.add('create-' + key);
  return plain(create.api.createErrors(values));
};
const later = new Date(Date.now() + 2 * 86400000).toLocaleDateString('en-CA');
assert.deepEqual(createErrors('baptismal_friends', 'create', { first_name: 'Mia', last_name: 'Klein' }), { finding_source: 'Please choose one.' });
let errors = createErrors('new_members', 'create', { first_name: 'Lena', last_name: '', baptism_date: '2026-08-10', confirmation_date: '2026-08-01', child_dependents: '31' });
assert.deepEqual(errors, {
  last_name: 'Enter the last name.',
  confirmation_date: 'Confirmation cannot be before the baptism date.',
  child_dependents: 'Enter a whole number from 0 to 30.',
});
// "Not confirmed yet" was removed from the form (eabcb51): the confirmation date is always required.
errors = createErrors('new_members', 'create', { first_name: 'Lena', last_name: 'Vogel', baptism_date: later, child_dependents: '0' });
assert.deepEqual(errors, { baptism_date: 'The baptism date cannot be in the future.', confirmation_date: 'Enter the confirmation date.' });
errors = createErrors('new_members', 'create', { first_name: 'Lena', last_name: 'Vogel', baptismal_date_extended: '2026-08-05', baptism_date: '2026-08-01', confirmation_date: '2026-08-02', child_dependents: '2' });
assert.deepEqual(errors, { baptism_date: 'Baptism cannot be before the date it was extended.' });
assert.deepEqual(createErrors('new_members', 'convert', { baptism_date: '2026-08-01', confirmation_date: '2026-08-02', child_dependents: '1' }), {},
  'Baptized: the name and finding source come from the friend and are not asked');
console.log('planning create form: the page checks like the server');
