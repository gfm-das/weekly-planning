// Slidev's Markdown transformer hook of the GFM addon: a ```chart block in a slide becomes a <MissionChart>.
//
// ```chart type=line trend=linear title="New people being taught"
// Week,New people being taught
// Aug 3,12
// ```
// becomes <MissionChart type="line" trend="linear" title="New people being taught" csv="..." />.
// All values travel as one JSON object in v-bind, so quotes, `<` and `&` in
// the table or title cannot break the slide.
//
// Settings are written kebab-case or camelCase (trend-color=#d96b2b or
// trendColor=#d96b2b). Switches (show-values, stack …) are on when written
// alone or as =true. Lists (colors, series-types) have commas between the
// entries. `option` is JSON in single quotes: option='{"yAxis":{"min":0}}'.
// `query` too (a chart from the database; the table under it is then not used):
// query='{"measures":["friends_found.actual"],"weeks":12}'.
const RE_CHART = /^chart(?:\s+(.*))?$/
const RE_OPTION = /([\w-]+)(?:=("[^"]*"|'[^']*'|\S+))?/g
const TEXT = new Set([
  'type', 'trend', 'title', 'trendColor', 'trendStyle', 'trendLabel', 'goal', 'goalColor', 'targetLabel', 'targetColor', 'averageColor',
  'legend', 'xTitle', 'yTitle', 'format', 'prefix', 'suffix', 'valuePosition', 'option', 'query',
])
const NUMBER = new Set(['degree', 'height', 'max', 'trendWidth', 'window', 'forecast', 'target', 'yMin', 'yMax', 'labelRotate', 'decimals'])
const SWITCH = new Set(['showValues', 'average', 'stack', 'horizontal', 'smooth', 'multiples', 'dataZoom'])
const LIST = new Set(['colors', 'seriesTypes'])

function camel(name: string) {
  return name.replace(/-([a-z])/g, (_, c) => c.toUpperCase())
}

function chartBlock({ info, code }: { info: string, code: string }) {
  const match = info.trim().match(RE_CHART)
  if (!match) return undefined
  const props: Record<string, unknown> = { csv: code.replace(/\s+$/, '') }
  for (const [, rawName, rawValue] of (match[1] ?? '').matchAll(RE_OPTION)) {
    const name = camel(rawName)
    const value = rawValue === undefined ? undefined : rawValue.replace(/^(["'])([\s\S]*)\1$/, '$2')
    if (TEXT.has(name) && value !== undefined) props[name] = value
    else if (NUMBER.has(name) && value !== undefined && value.trim() !== '' && Number.isFinite(Number(value))) props[name] = Number(value)
    else if (SWITCH.has(name)) props[name] = value === undefined || value === 'true'
    else if (LIST.has(name) && value) props[name] = value.split(',').map(c => c.trim()).filter(Boolean)
  }
  // JSON's own \u escapes keep the attribute quote, tags and entities out of the HTML.
  const json = JSON.stringify(props).replace(/'/g, '\\u0027').replace(/</g, '\\u003c').replace(/>/g, '\\u003e').replace(/&/g, '\\u0026')
  return `<MissionChart v-bind='${json}' />`
}

export default () => ({ codeblocks: [chartBlock] })
