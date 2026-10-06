// Calculated fields: a small, safe formula language for charts.
//
//   [Successfully Contacted] / [Referrals Received]
//   IF([Actual] >= [Goal], 1, 0)
//   PERCENT_CHANGE([New people being taught])
//
// Pure JavaScript, no imports, no Vue, no Slidev; runs in the slides, the editor and the tests. Formulas are parsed
// into a tree and evaluated by this file only: nothing here calls eval, Function or any JavaScript the writer typed,
// and a formula can only read the numbers of the chart it belongs to (the columns of its table), so it can never
// show a viewer a number the chart's own query did not already give them.
//
// Values. Every column of a chart is a list of numbers (null = no number) with one entry per row (a week, a zone ...).
// A formula works on whole columns at once: `[A] / [B]` divides row by row. A number written in the formula
// (`100`) is the same in every row. Dividing by 0 or by "no number" gives no number (a gap in the chart) and is
// counted, so the editor can say so.
//
// Functions (see FUNCTIONS for the help texts the editor shows):
//   SUM AVG MIN MAX COUNT   one column: over all rows (one number for the chart); several values: row by row
//   IF  SAFE_DIVIDE  DIFFERENCE  PERCENT_CHANGE  CUMULATIVE_SUM  MOVING_AVG  LAG  ROUND  ABS
// Operators: + - * / % ^  comparisons = <> < <= > >=  and AND OR NOT  with the usual order and ( ).

export const MAX_FORMULA_LENGTH = 500
export const MAX_DEPTH = 40
export const MAX_ROWS = 2000
export const MAX_CALCULATED = 12

/** A mistake in a formula, with a sentence for the writer and where it is (`at`: the character, from 0). */
export class FormulaError extends Error {
  constructor(message, at = null) {
    super(message)
    this.at = at
  }
}

// ---- the functions (also the editor's help) ----------------------------------------------------------------------

/** name: how it is written, what it does, an example. `min`/`max`: how many values it takes. */
export const FUNCTIONS = {
  SUM: { min: 1, max: 8, signature: 'SUM(column) or SUM(a, b, ...)', help: 'One column: the total of all rows. Several values: their sum, row by row.', example: 'SUM([Baptisms])' },
  AVG: { min: 1, max: 8, signature: 'AVG(column) or AVG(a, b, ...)', help: 'One column: the average of all rows. Several values: their average, row by row.', example: 'AVG([New people being taught])' },
  MIN: { min: 1, max: 8, signature: 'MIN(column) or MIN(a, b, ...)', help: 'One column: the lowest row. Several values: the lowest, row by row.', example: 'MIN([Actual], [Goal])' },
  MAX: { min: 1, max: 8, signature: 'MAX(column) or MAX(a, b, ...)', help: 'One column: the highest row. Several values: the highest, row by row.', example: 'MAX([Actual], [Goal])' },
  COUNT: { min: 1, max: 1, signature: 'COUNT(column)', help: 'How many rows have a number.', example: 'COUNT([Actual])' },
  IF: { min: 3, max: 3, signature: 'IF(test, then, otherwise)', help: 'Gives "then" where the test is true and "otherwise" where it is not.', example: 'IF([Actual] >= [Goal], 1, 0)' },
  SAFE_DIVIDE: { min: 2, max: 3, signature: 'SAFE_DIVIDE(a, b, instead)', help: 'a divided by b; where b is 0 or missing it gives "instead" (no number if you leave it out).', example: 'SAFE_DIVIDE([Taught], [Contacted], 0)' },
  DIFFERENCE: { min: 1, max: 2, signature: 'DIFFERENCE(column, rows back)', help: 'The change from the row before (or from that many rows back).', example: 'DIFFERENCE([Baptisms])' },
  PERCENT_CHANGE: { min: 1, max: 2, signature: 'PERCENT_CHANGE(column, rows back)', help: 'The change from the row before as a fraction of it: (this - before) / before.', example: 'PERCENT_CHANGE([Baptisms])' },
  CUMULATIVE_SUM: { min: 1, max: 1, signature: 'CUMULATIVE_SUM(column)', help: 'The running total from the first row to this one.', example: 'CUMULATIVE_SUM([Baptisms])' },
  MOVING_AVG: { min: 2, max: 2, signature: 'MOVING_AVG(column, rows)', help: 'The average of this row and the rows before it (up to that many rows).', example: 'MOVING_AVG([Baptisms], 4)' },
  LAG: { min: 1, max: 2, signature: 'LAG(column, rows back)', help: 'The value from the row before (or that many rows back).', example: 'LAG([Baptisms])' },
  ROUND: { min: 1, max: 2, signature: 'ROUND(value, decimals)', help: 'Rounds to that many decimals (0 if you leave it out).', example: 'ROUND([Rate], 1)' },
  ABS: { min: 1, max: 1, signature: 'ABS(value)', help: 'Removes a minus sign.', example: 'ABS(DIFFERENCE([Baptisms]))' },
}

/** How a calculated field is shown (the chart engine's number formats). */
export const FORMATS = ['number', 'percent', 'integer', 'compact', 'decimals']

// ---- reading a formula -------------------------------------------------------------------------------------------

const KEYWORDS = new Set(['AND', 'OR', 'NOT', 'TRUE', 'FALSE'])

function tokenize(source) {
  const tokens = []
  let i = 0
  while (i < source.length) {
    const c = source[i]
    if (/\s/.test(c)) { i++; continue }
    if (c === '[') {
      const end = source.indexOf(']', i + 1)
      if (end < 0) throw new FormulaError('A field name starts with [ but there is no ] to end it.', i)
      const name = source.slice(i + 1, end).trim()
      if (!name) throw new FormulaError('There is no field name between [ and ].', i)
      tokens.push({ type: 'field', value: name, at: i })
      i = end + 1
      continue
    }
    if (/[0-9.]/.test(c)) {
      const m = /^(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?/.exec(source.slice(i))
      if (!m) throw new FormulaError(`“${c}” is not a number.`, i)
      tokens.push({ type: 'number', value: Number(m[0]), at: i })
      i += m[0].length
      continue
    }
    if (/[A-Za-z_]/.test(c)) {
      const m = /^[A-Za-z_][A-Za-z0-9_]*/.exec(source.slice(i))
      tokens.push({ type: 'word', value: m[0].toUpperCase(), at: i })
      i += m[0].length
      continue
    }
    const two = source.slice(i, i + 2)
    if (['<=', '>=', '<>', '!=', '=='].includes(two)) {
      tokens.push({ type: 'op', value: two === '!=' ? '<>' : two === '==' ? '=' : two, at: i })
      i += 2
      continue
    }
    if ('+-*/%^<>=(),'.includes(c)) {
      tokens.push({ type: c === '(' || c === ')' || c === ',' ? c : 'op', value: c, at: i })
      i++
      continue
    }
    if (c === '"' || c === "'") throw new FormulaError('Text is not used in formulas. Put a field name in [ ] and write numbers as they are.', i)
    throw new FormulaError(`“${c}” cannot be used in a formula.`, i)
  }
  return tokens
}

// Order of operators, weakest first. `^` is right-to-left.
const BINARY = [['OR'], ['AND'], ['=', '<>', '<', '<=', '>', '>='], ['+', '-'], ['*', '/', '%'], ['^']]

/**
 * Reads a formula into a tree: { fields: [names], functions: [names], tree }. Throws FormulaError.
 * Field names are as written; checking them against a chart's columns is evaluateFormula's job.
 */
export function parseFormula(source) {
  const text = String(source ?? '')
  if (!text.trim()) throw new FormulaError('Write a formula, for example [A] / [B].')
  if (text.length > MAX_FORMULA_LENGTH) throw new FormulaError(`A formula can be up to ${MAX_FORMULA_LENGTH} characters.`)
  const tokens = tokenize(text)
  let p = 0
  const fields = new Set()
  const functions = new Set()
  const peek = () => tokens[p]
  const isOp = (t, ...values) => t && (t.type === 'op' || t.type === 'word') && values.includes(t.value)
  const where = t => (t ? t.at : text.length)

  function expression(level, depth) {
    if (depth > MAX_DEPTH) throw new FormulaError('This formula has too many brackets inside brackets.', where(peek()))
    if (level >= BINARY.length) return unary(depth)
    let left = expression(level + 1, depth)
    while (isOp(peek(), ...BINARY[level])) {
      const op = tokens[p++]
      // ^ is right to left: 2 ^ 3 ^ 2 is 2 ^ (3 ^ 2).
      const right = BINARY[level][0] === '^' ? expression(level, depth + 1) : expression(level + 1, depth)
      left = { kind: 'binary', op: op.value, left, right, at: op.at }
    }
    return left
  }

  function unary(depth) {
    const t = peek()
    if (isOp(t, '-', '+')) {
      p++
      const operand = unary(depth + 1)
      return t.value === '-' ? { kind: 'negate', operand, at: t.at } : operand
    }
    if (isOp(t, 'NOT')) {
      p++
      return { kind: 'not', operand: unary(depth + 1), at: t.at }
    }
    return atom(depth)
  }

  function atom(depth) {
    const t = tokens[p]
    if (!t) throw new FormulaError('The formula ends too soon: something is missing after the last sign.', text.length)
    p++
    if (t.type === 'number') return { kind: 'number', value: t.value, at: t.at }
    if (t.type === 'field') {
      fields.add(t.value)
      return { kind: 'field', name: t.value, at: t.at }
    }
    if (t.type === '(') {
      const inner = expression(0, depth + 1)
      if (peek()?.type !== ')') throw new FormulaError('A ( has no ) to close it.', t.at)
      p++
      return inner
    }
    if (t.type === 'word') {
      if (t.value === 'TRUE' || t.value === 'FALSE') return { kind: 'number', value: t.value === 'TRUE' ? 1 : 0, at: t.at }
      if (peek()?.type === '(') {
        const info = FUNCTIONS[t.value]
        if (!info) throw new FormulaError(`There is no function called ${t.value}.${suggest(t.value, Object.keys(FUNCTIONS))}`, t.at)
        p++
        const args = []
        if (peek()?.type === ')') p++
        else {
          for (;;) {
            args.push(expression(0, depth + 1))
            const next = tokens[p++]
            if (next?.type === ',') continue
            if (next?.type === ')') break
            throw new FormulaError(`${t.value}( has no ) to close it.`, next ? next.at : text.length)
          }
        }
        if (args.length < info.min || args.length > info.max) {
          const wants = info.min === info.max ? `${info.min}` : `${info.min} to ${info.max}`
          throw new FormulaError(`${t.value} takes ${wants} value${info.max === 1 ? '' : 's'}: ${info.signature}.`, t.at)
        }
        functions.add(t.value)
        return { kind: 'call', name: t.value, args, at: t.at }
      }
      if (KEYWORDS.has(t.value)) throw new FormulaError(`${t.value} is used between two tests, for example [A] > 1 ${t.value} [B] > 1.`, t.at)
      throw new FormulaError(`“${text.slice(t.at, t.at + t.value.length)}” is not a field or a function. Write a field name in [ ], for example [${text.slice(t.at, t.at + t.value.length)}].`, t.at)
    }
    throw new FormulaError(`“${t.value}” is not expected here.`, t.at)
  }

  const tree = expression(0, 0)
  if (p < tokens.length) throw new FormulaError(`“${tokens[p].value}” is not expected here.`, tokens[p].at)
  return { fields: [...fields], functions: [...functions], tree }
}

// "Did you mean …?" for a name that is almost one that exists.
function distance(a, b) {
  const row = Array.from({ length: b.length + 1 }, (_, j) => j)
  for (let i = 1; i <= a.length; i++) {
    let prev = row[0]
    row[0] = i
    for (let j = 1; j <= b.length; j++) {
      const keep = row[j]
      row[j] = Math.min(row[j] + 1, row[j - 1] + 1, prev + (a[i - 1] === b[j - 1] ? 0 : 1))
      prev = keep
    }
  }
  return row[b.length]
}

function suggest(name, options) {
  const lower = String(name).toLowerCase()
  let best = null
  for (const option of options) {
    const d = distance(lower, option.toLowerCase())
    if (d <= Math.max(2, Math.floor(option.length / 3)) && (!best || d < best.d)) best = { option, d }
  }
  return best ? ` Did you mean ${best.option}?` : ''
}

// ---- working it out ----------------------------------------------------------------------------------------------

const isNum = v => typeof v === 'number' && Number.isFinite(v)

/**
 * Works a formula out. `fields` is { name: [numbers or null] } (every list the same length). Returns
 * { values: [numbers or null], notes: { divisionByZero: rows } }. Throws FormulaError (an unknown field names the
 * fields there are).
 */
export function evaluateFormula(formula, fields) {
  const parsed = typeof formula === 'object' && formula?.tree ? formula : parseFormula(formula)
  const names = Object.keys(fields)
  const lower = new Map(names.map(n => [n.trim().toLowerCase(), n]))
  const rows = names.length ? fields[names[0]].length : 0
  if (rows > MAX_ROWS) throw new FormulaError(`A chart can have up to ${MAX_ROWS} rows for a formula.`)
  const notes = { divisionByZero: 0 }

  // A value is a list of `rows` entries; a number written in the formula is `{ constant }` until a row needs it.
  const full = v => (Array.isArray(v) ? v : Array.from({ length: rows }, () => v))
  const each = (a, b, f) => {
    const x = full(a), y = full(b)
    return x.map((v, i) => f(v, y[i]))
  }

  function run(node) {
    switch (node.kind) {
      case 'number': return node.value
      case 'field': {
        const key = lower.get(node.name.trim().toLowerCase())
        if (!key) throw new FormulaError(`There is no field called [${node.name}] in this chart.${names.length ? suggest(node.name, names).replace('Did you mean ', 'Did you mean [').replace(/\?$/, ']?') : ''}${names.length ? ` The fields are: ${names.map(n => `[${n}]`).join(', ')}.` : ''}`, node.at)
        return fields[key].map(v => (isNum(v) ? v : null))
      }
      case 'negate': return full(run(node.operand)).map(v => (isNum(v) ? -v : null))
      case 'not': return full(run(node.operand)).map(v => (isNum(v) ? (v ? 0 : 1) : null))
      case 'binary': return binary(node.op, run(node.left), run(node.right))
      case 'call': return call(node.name, node.args.map(run), node)
      default: throw new FormulaError('This formula cannot be worked out.')
    }
  }

  function binary(op, a, b) {
    return each(a, b, (x, y) => {
      if (op === 'AND') return isNum(x) && isNum(y) ? (x && y ? 1 : 0) : null
      if (op === 'OR') return isNum(x) && isNum(y) ? (x || y ? 1 : 0) : null
      if (!isNum(x) || !isNum(y)) return null
      switch (op) {
        case '+': return x + y
        case '-': return x - y
        case '*': return x * y
        case '/': if (y === 0) { notes.divisionByZero++; return null } return x / y
        case '%': if (y === 0) { notes.divisionByZero++; return null } return x % y
        case '^': { const r = x ** y; return Number.isFinite(r) ? r : null }
        case '=': return x === y ? 1 : 0
        case '<>': return x !== y ? 1 : 0
        case '<': return x < y ? 1 : 0
        case '<=': return x <= y ? 1 : 0
        case '>': return x > y ? 1 : 0
        case '>=': return x >= y ? 1 : 0
        default: return null
      }
    })
  }

  const whole = (v, what, node) => {
    const n = full(v)[0]
    if (!isNum(n) || !Number.isInteger(n) || n < 0 || n > rows + 1000) throw new FormulaError(`${what} must be a whole number, for example 1 or 4.`, node.at)
    return n
  }
  const lag = (v, n) => full(v).map((_, i) => (i - n >= 0 ? full(v)[i - n] : null))

  function call(name, args, node) {
    const numbers = v => full(v).filter(isNum)
    switch (name) {
      case 'SUM': case 'AVG': case 'MIN': case 'MAX': {
        const pick = list => {
          if (!list.length) return null
          if (name === 'SUM') return list.reduce((s, v) => s + v, 0)
          if (name === 'AVG') return list.reduce((s, v) => s + v, 0) / list.length
          return name === 'MIN' ? Math.min(...list) : Math.max(...list)
        }
        if (args.length === 1 && Array.isArray(args[0])) return pick(numbers(args[0]))
        // Row by row: a row with a missing value among the values has no result.
        return Array.from({ length: rows }, (_, i) => {
          const row = args.map(a => (Array.isArray(a) ? a[i] : a))
          return row.every(isNum) ? pick(row) : null
        })
      }
      case 'COUNT': return numbers(args[0]).length
      case 'IF': {
        const [test, yes, no] = args.map(full)
        return test.map((t, i) => (isNum(t) ? (t ? yes[i] : no[i]) : null))
      }
      case 'SAFE_DIVIDE': {
        const [a, b, instead] = args
        const fallback = args.length > 2 ? full(instead) : null
        return each(a, b, (x, y) => (!isNum(x) || !isNum(y) || y === 0 ? null : x / y)).map((v, i) => (v !== null ? v : fallback ? (isNum(fallback[i]) ? fallback[i] : null) : null))
      }
      case 'DIFFERENCE': {
        const before = lag(args[0], args.length > 1 ? whole(args[1], 'The number of rows back', node) : 1)
        return each(args[0], before, (x, y) => (isNum(x) && isNum(y) ? x - y : null))
      }
      case 'PERCENT_CHANGE': {
        const before = lag(args[0], args.length > 1 ? whole(args[1], 'The number of rows back', node) : 1)
        return each(args[0], before, (x, y) => (isNum(x) && isNum(y) && y !== 0 ? (x - y) / Math.abs(y) : null))
      }
      case 'CUMULATIVE_SUM': {
        let total = 0
        return full(args[0]).map(v => { if (isNum(v)) total += v; return isNum(v) ? total : null })
      }
      case 'MOVING_AVG': {
        const size = whole(args[1], 'The number of rows', node)
        if (size < 1) throw new FormulaError('MOVING_AVG needs at least 1 row.', node.at)
        const v = full(args[0])
        return v.map((x, i) => {
          if (!isNum(x)) return null
          const part = v.slice(Math.max(0, i - size + 1), i + 1).filter(isNum)
          return part.reduce((s, n) => s + n, 0) / part.length
        })
      }
      case 'LAG': return lag(args[0], args.length > 1 ? whole(args[1], 'The number of rows back', node) : 1)
      case 'ROUND': {
        const digits = args.length > 1 ? full(args[1])[0] : 0
        if (!isNum(digits) || digits < 0 || digits > 8) throw new FormulaError('ROUND keeps 0 to 8 decimals.', node.at)
        const k = 10 ** digits
        return full(args[0]).map(v => (isNum(v) ? Math.round(v * k) / k : null))
      }
      case 'ABS': return full(args[0]).map(v => (isNum(v) ? Math.abs(v) : null))
      default: throw new FormulaError(`There is no function called ${name}.`, node.at)
    }
  }

  const result = run(parsed.tree)
  const values = full(result).map(v => (isNum(v) ? v : null))
  return { values, notes }
}

// ---- calculated fields of a chart --------------------------------------------------------------------------------

/**
 * Adds the calculated fields to a chart's table. `calc` is a list (or JSON text) of
 *   { name, formula, format?: 'number'|'percent'|'integer'|'compact'|'decimals', decimals?, hide? }
 * A field may use the fields before it. Returns { table, problems: [{ name, message }], notes: [{ name, text }] }:
 * a field that cannot be worked out is left out (and listed in problems); the rest still draw.
 * A `percent` field is shown as a percentage: its fractions are multiplied by 100, and when every drawn series is a
 * percentage the table's unit is percent (the axis and tooltips show %).
 * `hide`: a helper to build on that is not drawn (it stays out of the table).
 */
export function applyCalculated(table, calc) {
  let list = calc
  const problems = []
  const notes = []
  if (typeof list === 'string') {
    try { list = JSON.parse(list) }
    catch { return { table, problems: [{ name: '', message: 'The calculated fields are not valid JSON.' }], notes } }
  }
  if (!Array.isArray(list) || !list.length || !table?.series) return { table, problems, notes }
  if (list.length > MAX_CALCULATED) problems.push({ name: '', message: `A chart can have up to ${MAX_CALCULATED} calculated fields.` })

  const fields = {}
  for (const s of table.series) if (s.role !== 'goal' || !(s.name in fields)) fields[s.name] = s.values
  const added = []
  const hidden = new Set()
  const taken = new Set(Object.keys(fields).map(n => n.toLowerCase()))
  for (const entry of list.slice(0, MAX_CALCULATED)) {
    const name = String(entry?.name ?? '').trim()
    try {
      if (!name) throw new FormulaError('Give the calculated field a name.')
      if (taken.has(name.toLowerCase())) throw new FormulaError(`There is already a field called [${name}]. Choose another name.`)
      if (/[[\]]/.test(name)) throw new FormulaError('A name cannot contain [ or ].')
      const format = entry.format === undefined || entry.format === '' ? 'number' : entry.format
      if (!FORMATS.includes(format)) throw new FormulaError(`Choose one of ${FORMATS.join(', ')} for the format.`)
      const { values, notes: n } = evaluateFormula(String(entry.formula ?? ''), fields)
      if (n.divisionByZero) notes.push({ name, text: `Divided by 0 in ${n.divisionByZero} ${n.divisionByZero === 1 ? 'row' : 'rows'}: those rows have no number.` })
      const shown = format === 'percent' ? values.map(v => (v === null ? null : v * 100)) : format === 'integer' ? values.map(v => (v === null ? null : Math.round(v))) : values
      fields[name] = values
      taken.add(name.toLowerCase())
      if (entry.hide) { hidden.add(name); continue }
      added.push({ name, values: shown, calc: true, format, ...(Number.isFinite(Number(entry.decimals)) && entry.decimals !== '' && entry.decimals !== null ? { decimals: Number(entry.decimals) } : {}) })
    } catch (error) {
      if (!(error instanceof FormulaError)) throw error
      problems.push({ name, message: error.message })
    }
  }
  if (!added.length) return { table, problems, notes }
  const series = [...table.series, ...added]
  const drawn = series.filter(s => s.role !== 'goal')
  const allPercent = drawn.length > 0 && drawn.every(s => s.format === 'percent')
  return { table: { ...table, series, ...(allPercent ? { unit: 'percent' } : {}) }, problems, notes }
}

/** The field names a formula may use for a chart's table (for the editor's autocomplete). */
export function fieldNames(table) {
  return (table?.series ?? []).filter(s => s.role !== 'goal').map(s => s.name)
}

/**
 * What a formula gives for a table, as the editor's preview: { ok, values, sample, problem, notes }.
 * `sample` is the last row that has a number, formatted for `format`.
 */
export function previewFormula(table, formula, format = 'number', decimals = null) {
  try {
    const fields = Object.fromEntries((table?.series ?? []).map(s => [s.name, s.values]))
    const { values, notes } = evaluateFormula(formula, fields)
    const last = [...values].reverse().find(isNum)
    const shown = last === undefined ? null : formatValue(last, format, decimals)
    return { ok: true, values, sample: shown, problem: '', notes }
  } catch (error) {
    if (!(error instanceof FormulaError)) throw error
    return { ok: false, values: [], sample: null, problem: error.message, at: error.at, notes: { divisionByZero: 0 } }
  }
}

/** A number as a calculated field's format shows it (63.4 -> "63.4%" for percent of a fraction). */
export function formatValue(value, format = 'number', decimals = null) {
  if (!isNum(value)) return '–'
  const d = decimals === null || decimals === undefined || decimals === '' ? null : Math.max(0, Math.min(4, Math.round(Number(decimals))))
  const up = (n, digits) => n.toLocaleString('en', { maximumFractionDigits: digits })
  const fixed = (n, digits) => n.toLocaleString('en', { minimumFractionDigits: digits, maximumFractionDigits: digits })
  switch (format) {
    case 'percent': return `${d === null ? up(value * 100, 1) : fixed(value * 100, d)}%`
    case 'integer': return up(Math.round(value), 0)
    case 'compact': return value.toLocaleString('en', { notation: 'compact', maximumFractionDigits: d ?? 1 })
    case 'decimals': return fixed(value, d ?? 1)
    default: return d === null ? up(value, 2) : fixed(value, d)
  }
}
