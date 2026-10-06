// Calculated fields (manager/gfm-addon/lib/formula.mjs): the formulas of the product brief, every function, division by
// zero, friendly errors, the limits, and that nothing a writer types can run as JavaScript. Plain Node.
import test from 'node:test';
import assert from 'node:assert/strict';
import { applyCalculated, evaluateFormula, FormulaError, formatValue, fieldNames, parseFormula, previewFormula, FUNCTIONS } from '../manager/gfm-addon/lib/formula.mjs';

const fields = {
  'Referrals Received': [10, 20, 0, 40],
  'Successfully Contacted': [5, 10, 0, 30],
  Taught: [2, null, 1, 12],
  Actual: [8, 12, 15, 9],
  Goal: [10, 10, 10, 10],
};
const run = (formula, f = fields) => evaluateFormula(formula, f).values;
const rounded = list => list.map(v => (v === null ? null : Math.round(v * 1e6) / 1e6));

test('the brief\'s examples', () => {
  // Successful Contact Rate = Successfully Contacted / Referrals Received (0 referrals: no number, not Infinity)
  assert.deepEqual(run('[Successfully Contacted] / [Referrals Received]'), [0.5, 0.5, null, 0.75]);
  // Goal Achievement = Actual / Goal
  assert.deepEqual(run('[Actual] / [Goal]'), [0.8, 1.2, 1.5, 0.9]);
  // Week Change = (Current - Previous) / Previous
  assert.deepEqual(rounded(run('([Actual] - LAG([Actual])) / LAG([Actual])')), [null, 0.5, 0.25, -0.4]);
  // Teaching Conversion = Taught / Successfully Contacted
  assert.deepEqual(run('[Taught] / [Successfully Contacted]'), [0.4, null, null, 0.4]);
});

test('operators, order, brackets, minus, power, remainder, comparisons', () => {
  assert.deepEqual(run('[Actual] + [Goal] * 2'), [28, 32, 35, 29]);
  assert.deepEqual(run('([Actual] + [Goal]) * 2'), [36, 44, 50, 38]);
  assert.deepEqual(run('2 ^ 3 ^ 2', { A: [0] }), [512]);
  assert.deepEqual(run('-[Actual]'), [-8, -12, -15, -9]);
  assert.deepEqual(run('[Actual] % 5'), [3, 2, 0, 4]);
  assert.deepEqual(run('[Actual] >= [Goal]'), [0, 1, 1, 0]);
  assert.deepEqual(run('[Actual] >= [Goal] AND [Actual] < 15'), [0, 1, 0, 0]);
  assert.deepEqual(run('NOT ([Actual] > 9) OR [Actual] = 15'), [1, 0, 1, 1]);
  assert.deepEqual(run('1e1 + .5', { A: [0, 0] }), [10.5, 10.5]);
});

test('field names: spaces, capital letters and the order of the columns do not matter', () => {
  assert.deepEqual(run('[  actual  ] / [GOAL]'), [0.8, 1.2, 1.5, 0.9]);
});

test('aggregates: one column over all rows, several values row by row', () => {
  assert.deepEqual(run('SUM([Actual])'), [44, 44, 44, 44]);
  assert.deepEqual(run('AVG([Actual])'), [11, 11, 11, 11]);
  assert.deepEqual(run('MIN([Actual])'), [8, 8, 8, 8]);
  assert.deepEqual(run('MAX([Actual])'), [15, 15, 15, 15]);
  assert.deepEqual(run('COUNT([Taught])'), [3, 3, 3, 3]);
  assert.deepEqual(run('SUM([Actual], [Goal])'), [18, 22, 25, 19]);
  assert.deepEqual(run('MIN([Actual], [Goal])'), [8, 10, 10, 9]);
  assert.deepEqual(run('SUM([Taught], 1)'), [3, null, 2, 13], 'a row with a missing value has no result');
  assert.deepEqual(run('[Actual] / AVG([Actual])').map(v => Math.round(v * 100) / 100), [0.73, 1.09, 1.36, 0.82], 'a total mixed with rows');
});

test('IF, SAFE_DIVIDE, DIFFERENCE, PERCENT_CHANGE, CUMULATIVE_SUM, MOVING_AVG, LAG, ROUND, ABS', () => {
  assert.deepEqual(run('IF([Actual] >= [Goal], 1, 0)'), [0, 1, 1, 0]);
  assert.deepEqual(run('IF([Actual] > 10, [Actual], [Goal])'), [10, 12, 15, 10]);
  assert.deepEqual(run('SAFE_DIVIDE([Successfully Contacted], [Referrals Received])'), [0.5, 0.5, null, 0.75]);
  assert.deepEqual(run('SAFE_DIVIDE([Successfully Contacted], [Referrals Received], 0)'), [0.5, 0.5, 0, 0.75]);
  assert.deepEqual(run('DIFFERENCE([Actual])'), [null, 4, 3, -6]);
  assert.deepEqual(run('DIFFERENCE([Actual], 2)'), [null, null, 7, -3]);
  assert.deepEqual(rounded(run('PERCENT_CHANGE([Actual])')), [null, 0.5, 0.25, -0.4]);
  assert.deepEqual(run('CUMULATIVE_SUM([Actual])'), [8, 20, 35, 44]);
  assert.deepEqual(run('CUMULATIVE_SUM([Taught])'), [2, null, 3, 15], 'a missing value stays missing and does not stop the total');
  assert.deepEqual(run('MOVING_AVG([Actual], 2)'), [8, 10, 13.5, 12]);
  assert.deepEqual(run('LAG([Actual], 2)'), [null, null, 8, 12]);
  assert.deepEqual(run('ROUND([Actual] / 3, 1)'), [2.7, 4, 5, 3]);
  assert.deepEqual(run('ROUND(2.5)', { A: [0] }), [3]);
  assert.deepEqual(run('ABS(DIFFERENCE([Actual]))'), [null, 4, 3, 6]);
});

test('division by zero gives no number and is counted for the editor', () => {
  const { values, notes } = evaluateFormula('[Successfully Contacted] / [Referrals Received]', fields);
  assert.equal(values[2], null);
  assert.equal(notes.divisionByZero, 1);
  assert.equal(evaluateFormula('[Actual] % 0', fields).notes.divisionByZero, 4);
  assert.deepEqual(run('1 / 0', { A: [0, 0] }), [null, null]);
});

test('friendly errors, with where they are', () => {
  const bad = (formula, pattern, f = fields) => assert.throws(() => evaluateFormula(formula, f), error => error instanceof FormulaError && pattern.test(error.message), formula);
  bad('', /Write a formula/);
  bad('[Actual', /no \] to end it/);
  bad('[]', /no field name/);
  bad('[Actual] +', /ends too soon/);
  bad('([Actual] + 1', /no \) to close it/);
  bad('[Actual] + * 2', /not expected here/);
  bad('[Actual] [Goal]', /not expected here/);
  bad('[Actaul] / [Goal]', /no field called \[Actaul\].*Did you mean \[Actual\]\?.*The fields are: \[Referrals Received\]/);
  bad('SUMM([Actual])', /no function called SUMM.*Did you mean SUM\?/);
  bad('ROUND()', /ROUND takes 1 to 2 values: ROUND\(value, decimals\)/);
  bad('IF([Actual])', /IF takes 3 values/);
  bad('Actual / Goal', /not a field or a function.*\[Actual\]/);
  bad('"text"', /Text is not used/);
  bad('[Actual] & 1', /“&” cannot be used/);
  bad('MOVING_AVG([Actual], 0)', /at least 1 row/);
  bad('LAG([Actual], -1)', /whole number/);
  bad('ROUND([Actual], 20)', /0 to 8 decimals/);
  bad('1 AND', /ends too soon/);
});

test('where an error is: the character of the mistake', () => {
  try { parseFormula('[A] + #'); assert.fail('should throw'); } catch (error) { assert.equal(error.at, 6); }
  try { parseFormula('FOO([A])'); assert.fail('should throw'); } catch (error) { assert.equal(error.at, 0); }
});

test('limits: length, brackets inside brackets, rows', () => {
  assert.throws(() => parseFormula(`[A]${' + 1'.repeat(200)}`), /up to 500 characters/);
  assert.throws(() => parseFormula(`${'('.repeat(60)}1${')'.repeat(60)}`), /too many brackets/);
  assert.throws(() => evaluateFormula('[A] + 1', { A: new Array(2001).fill(1) }), /up to 2000 rows/);
  assert.deepEqual(parseFormula('[A] / [B] + SUM([A])').fields, ['A', 'B']);
  assert.deepEqual(parseFormula('[A] / [B] + SUM([A])').functions, ['SUM']);
});

test('nothing a writer types is run as JavaScript', () => {
  const attacks = [
    'constructor', 'process.exit()', '[A].constructor', 'globalThis', '__proto__', 'this', 'eval("1")', 'alert(1)', '`1`', '[A];1', 'new Function("return 1")()',
    "[A] + ''", 'import("x")', '{}', '[constructor]', '[__proto__]', '[toString]',
  ];
  for (const text of attacks) {
    assert.throws(() => evaluateFormula(text, { A: [1] }), FormulaError, text);
  }
  // A field called like an object's own members is just a missing field, and a real one with such a name works.
  assert.throws(() => evaluateFormula('[constructor]', { A: [1] }), /no field called \[constructor\]/);
  assert.deepEqual(run('[constructor] + 1', { constructor: [1] }), [2]);
});

test('applyCalculated: adds fields after the chart\'s own, in order, and keeps drawing when one fails', () => {
  const table = { labels: ['W1', 'W2', 'W3', 'W4'], series: [{ name: 'Referrals Received', values: [10, 20, 0, 40] }, { name: 'Successfully Contacted', values: [5, 10, 0, 30] }], head: 'Week', unit: 'count' };
  const { table: out, problems, notes } = applyCalculated(table, [
    { name: 'Successful Contact Rate', formula: '[Successfully Contacted] / [Referrals Received]', format: 'percent' },
    { name: 'Gap', formula: '[Referrals Received] - [Successfully Contacted]' },
    { name: 'Broken', formula: '[Nope] + 1' },
    { name: 'Gap', formula: '1' },
    { name: 'Gap share', formula: '[Gap] / SUM([Gap])', hide: true },
    { name: 'Top', formula: 'IF([Gap share] > 0.3, [Gap], 0)' },
  ]);
  assert.deepEqual(out.series.map(s => s.name), ['Referrals Received', 'Successfully Contacted', 'Successful Contact Rate', 'Gap', 'Top']);
  assert.deepEqual(out.series[2].values, [50, 50, null, 75], 'a percentage field holds percent numbers');
  assert.equal(out.series[2].format, 'percent');
  assert.equal(out.series[2].calc, true);
  assert.deepEqual(out.series[3].values, [5, 10, 0, 10]);
  assert.deepEqual(out.series[4].values, [0, 10, 0, 10], "a hidden helper can be used but is not drawn");
  assert.equal(out.unit, 'count', 'a mix of counts and a percentage keeps the counts\' unit');
  assert.deepEqual(problems.map(p => p.name), ['Broken', 'Gap'], 'two mistakes, listed by name');
  assert.match(problems[0].message, /no field called \[Nope\]/);
  assert.match(problems[1].message, /already a field called \[Gap\]/);
  assert.equal(notes.length, 1);
  assert.match(notes[0].text, /Divided by 0 in 1 row/);
  assert.equal(table.series.length, 2, 'the chart\'s own table is not changed');
});

test('applyCalculated: goal columns are left alone, formats and mistakes', () => {
  const table = { labels: ['A', 'B'], series: [{ name: 'Actual', values: [8, 12] }, { name: 'Goal', values: [10, 10], role: 'goal' }], head: 'Zone', unit: 'count' };
  const only = applyCalculated({ ...table, series: [{ name: 'Actual', values: [8, 12] }] }, [{ name: 'Rate', formula: '[Actual] / 10', format: 'percent' }]);
  assert.equal(only.table.series.length, 2);
  const mixed = applyCalculated(table, [{ name: 'Rate', formula: '[Actual] / [Goal]', format: 'percent' }]);
  assert.equal(mixed.table.series.at(-1).name, 'Rate');
  assert.deepEqual(mixed.table.series.at(-1).values, [80, 120]);
  assert.equal(applyCalculated(table, []).table, table);
  assert.equal(applyCalculated(table, 'not json').problems[0].message, 'The calculated fields are not valid JSON.');
  assert.equal(applyCalculated(table, '[{"name":"X","formula":"[Actual]"}]').table.series.at(-1).name, 'X', 'JSON text works too');
  assert.match(applyCalculated(table, [{ name: '', formula: '1' }]).problems[0].message, /Give the calculated field a name/);
  assert.match(applyCalculated(table, [{ name: 'a[b]', formula: '1' }]).problems[0].message, /cannot contain/);
  assert.match(applyCalculated(table, [{ name: 'X', formula: '1', format: 'bogus' }]).problems[0].message, /Choose one of/);
  assert.equal(applyCalculated(table, new Array(20).fill({ name: 'N', formula: '1' })).problems[0].message.includes('up to 12'), true);
});

test('the editor\'s preview and formats', () => {
  const table = { labels: ['A', 'B'], series: [{ name: 'Taught', values: [3, 5] }, { name: 'Contacted', values: [4, 8] }] };
  assert.deepEqual(fieldNames(table), ['Taught', 'Contacted']);
  const ok = previewFormula(table, '[Taught] / [Contacted]', 'percent');
  assert.equal(ok.ok, true);
  assert.equal(ok.sample, '62.5%');
  const bad = previewFormula(table, '[Taught] / [Missing]');
  assert.equal(bad.ok, false);
  assert.match(bad.problem, /no field called \[Missing\]/);
  assert.equal(typeof bad.at, 'number');
  assert.equal(formatValue(0.647, 'percent'), '64.7%');
  assert.equal(formatValue(0.6471, 'percent', 2), '64.71%');
  assert.equal(formatValue(1234.567), '1,234.57');
  assert.equal(formatValue(1234.5, 'integer'), '1,235');
  assert.equal(formatValue(12345, 'compact'), '12.3K');
  assert.equal(formatValue(3, 'decimals'), '3.0');
  assert.equal(formatValue(null), '–');
});

test('the help for every function is complete (the editor shows it)', () => {
  for (const [name, info] of Object.entries(FUNCTIONS)) {
    assert.ok(info.signature.startsWith(name), name);
    assert.ok(info.help.length > 10 && info.example.includes(name), name);
    assert.ok(info.min >= 1 && info.max >= info.min, name);
    assert.doesNotThrow(() => parseFormula(info.example), `${name}'s example must parse`);
  }
});
