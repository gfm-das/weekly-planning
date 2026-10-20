// Lists in slides: <MissionList> shows a table of rows (names, places, numbers) from the slide itself or from live
// mission numbers, with columns, sort, limit, groups, pages and rows that appear one click at a time.
//
//   <MissionList title="Friends found by zone (last 4 weeks)"
//     :query='{"measures":["friends_found.actual"],"level":"zone","by":"unit","weeks":{"last":4},"includeCurrent":false}'
//     sort="New people being taught:desc" :limit="10" :sample="['Zone, New people being taught', 'Frankfurt, 31']" />
//
//   <MissionList :rows="['Name, Zone, Date', 'Elder Sample, Mainz, 3 May']" group-by="Zone" reveal />
//
// The live numbers come through the same safe path as a live chart (POST /api/charts/data, the read-only dashboard
// reader, the viewer's own stewardship, pinned queries for leaders): a row per unit (by:"unit") or per week, one column
// per number. That path never gives names of people, so lists of names are typed into the slide (`rows`).
// `sample` is drawn instead when the live numbers cannot load (no database, the demo, a viewer without access).
//
// Pure JavaScript with no imports, so the tests and the component share it.

export const MAX_ROWS = 500
export const MAX_COLUMNS = 12

const plain = v => !!v && typeof v === 'object' && !Array.isArray(v)
const norm = v => String(v ?? '').trim().toLowerCase()

/** One line of typed rows into cells: tabs, then semicolons, then commas separate the cells. */
export function splitRow(line) {
  const text = String(line ?? '')
  const mark = text.includes('\t') ? '\t' : text.includes(';') ? ';' : ','
  return text.split(mark).map(c => c.trim())
}

/**
 * Typed rows (`['Name, Zone', 'Elder Sample, Mainz']`, or one text with a row per line) into { columns, rows, problem }.
 * The first row holds the headings. Cells stay text; a number-looking cell is sorted as a number.
 */
export function listFromRows(rows) {
  const lines = (Array.isArray(rows) ? rows : typeof rows === 'string' ? [rows] : [])
    .flatMap(r => String(r ?? '').replace(/\r\n?/g, '\n').split('\n'))
    .filter(l => l.trim())
  if (!lines.length) return { columns: [], rows: [], problem: '' }
  const columns = splitRow(lines[0]).slice(0, MAX_COLUMNS).map((c, i) => c || `Column ${i + 1}`)
  const body = lines.slice(1, MAX_ROWS + 1).map(l => {
    const cells = splitRow(l)
    return columns.map((_, i) => cells[i] ?? '')
  })
  return { columns, rows: body, problem: '' }
}

/**
 * Live mission numbers (the answer of /api/charts/data) into a list: the first column is the unit or the week, then
 * one column per number. `table` is chart-engine's answerTable (labels, series, head). Goal columns are kept.
 */
export function listFromTable(table) {
  if (!table || table.problem || !Array.isArray(table.labels) || !Array.isArray(table.series)) return { columns: [], rows: [], problem: table?.problem || '' }
  const series = table.series.slice(0, MAX_COLUMNS - 1)
  const columns = [String(table.head || 'Label'), ...series.map(s => String(s.name ?? ''))]
  const rows = table.labels.slice(0, MAX_ROWS).map((label, i) => [String(label ?? ''), ...series.map(s => (s.values?.[i] ?? null))])
  return { columns, rows, problem: '' }
}

/** `columns` as written (names or a comma list) into the indexes of the list's columns, in that order; unknown names are skipped. */
export function pickColumns(list, wanted) {
  const names = typeof wanted === 'string' ? wanted.split(',') : Array.isArray(wanted) ? wanted : []
  const all = list.columns.map(norm)
  const picked = names.map(n => all.indexOf(norm(n))).filter(i => i >= 0)
  return picked.length ? [...new Set(picked)] : list.columns.map((_, i) => i)
}

const asNumber = (v) => {
  if (typeof v === 'number') return Number.isFinite(v) ? v : null
  const t = String(v ?? '').trim().replace(/\s/g, '')
  if (!/^[-+]?\d+([.,]\d+)?%?$/.test(t)) return null
  return Number(t.replace('%', '').replace(',', '.'))
}

/** "Column" or "Column:desc" (or asc) into { index, desc }; null when it names no column. */
export function readSort(list, sort) {
  const text = String(sort ?? '').trim()
  if (!text) return null
  const m = /^(.*?)(?::\s*(asc|desc))?$/i.exec(text)
  const index = list.columns.map(norm).indexOf(norm(m[1]))
  return index < 0 ? null : { index, desc: norm(m[2]) === 'desc' }
}

function compare(a, b) {
  const x = asNumber(a), y = asNumber(b)
  if (x !== null && y !== null) return x - y
  if (x !== null) return -1
  if (y !== null) return 1
  return String(a ?? '').localeCompare(String(b ?? ''), undefined, { sensitivity: 'base', numeric: true })
}

/**
 * What the list shows: { columns, groups: [{ name, rows }], total, shown, pages } after `sort`, `limit` and
 * `groupBy` (a column name: rows are grouped in their sorted order, the group column left out of the rows), with
 * the rows split into pages of `pageSize` (0 = one page). Each shown row is { cells, n } where n is its place (0-based)
 * across the whole list (a click per row counts with it).
 */
export function listView(list, options = {}) {
  const idx = pickColumns(list, options.columns)
  let rows = list.rows.slice()
  const sort = readSort(list, options.sort)
  if (sort) rows.sort((a, b) => (sort.desc ? -1 : 1) * compare(a[sort.index], b[sort.index]))
  const total = rows.length
  const limit = Math.max(0, Math.min(MAX_ROWS, Math.round(Number(options.limit) || 0)))
  if (limit) rows = rows.slice(0, limit)
  const groupAt = options.groupBy ? list.columns.map(norm).indexOf(norm(options.groupBy)) : -1
  const shownIdx = groupAt >= 0 ? idx.filter(i => i !== groupAt) : idx
  const groups = []
  let n = 0
  for (const row of rows) {
    const name = groupAt >= 0 ? String(row[groupAt] ?? '') : ''
    let group = groups.find(g => g.name === name)
    if (!group) groups.push(group = { name, rows: [] })
    group.rows.push(row)
  }
  // Rows are numbered in the order they are shown (group by group).
  const numbered = groups.map(g => ({ name: g.name, rows: g.rows.map(r => ({ cells: shownIdx.map(i => r[i]), n: n++ })) }))
  const size = Math.max(0, Math.round(Number(options.pageSize) || 0))
  const pages = size && n > size ? Math.ceil(n / size) : 1
  return { columns: shownIdx.map(i => list.columns[i]), groups: numbered, total, shown: n, pages, pageSize: pages > 1 ? size : n, grouped: groupAt >= 0 }
}

/** The groups of one page (0-based): only the rows whose place falls on it; empty groups are left out. */
export function pageOf(view, page) {
  if (view.pages <= 1) return view.groups
  const from = Math.max(0, Math.min(view.pages - 1, page | 0)) * view.pageSize
  const to = from + view.pageSize
  return view.groups.map(g => ({ name: g.name, rows: g.rows.filter(r => r.n >= from && r.n < to) })).filter(g => g.rows.length)
}

/** True for a number or a cell that reads as one ("12", "3,5", "40%"): shown right-aligned. */
export function isNumberish(value) {
  return asNumber(value) !== null
}

/** A cell as text: numbers with the deck's thousands separators, empty for nothing. */
export function cellText(value, locale) {
  if (value === null || value === undefined) return ''
  if (typeof value === 'number') return Number.isFinite(value) ? value.toLocaleString(locale || undefined, { maximumFractionDigits: 1 }) : ''
  return String(value)
}

/** How many clicks the list takes: `reveal` = one per shown row, `paging="click"` = one per further page, else none. */
export function listClicks(view, { reveal = false, paging = 'click' } = {}) {
  if (reveal) return view.shown
  if (paging === 'click' && view.pages > 1) return view.pages - 1
  return 0
}

export const isPlainOptions = plain
