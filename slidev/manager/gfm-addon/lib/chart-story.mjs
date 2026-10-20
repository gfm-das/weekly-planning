// Data stories: one chart that changes step by step as the presenter clicks.
//
//   <MissionChart :query='...' preset="funnel"
//     :story='[{"label":"Received","shape":{"only":["Received"]}},
//              {"label":"Attempted","shape":{"only":["Received","Attempted"]}},
//              {"label":"All steps","shape":{}}]'
//     storyTransition="morph" :storyDuration="700" />
//
// Each step is a small change to the chart's own settings: the kind (`preset`), the numbers it shows (`shape`: only,
// hide, sort, top), calculated fields (`calc`), `title`, `colors` and any ECharts `option` (merged over the chart's).
// Step 1 is the chart as written with the first step on it; every click goes to the next step. The chart is one ECharts
// instance that lives through the whole story: a step changes it with setOption (series keep stable ids, and a series
// that changes kind morphs with ECharts' universal transition), so it moves from one state to the next instead of
// being drawn again. See charts.ts (useMissionChart) for how a step is applied.
//
// Pure JavaScript. The click counting is the component's (it is Slidev's); this file reads the story and builds each
// step's settings and its animation.
import { mergeOption, readOverride } from './chart-core.mjs'

export const MAX_STEPS = 12
/** The settings a step may change. Everything else of the chart (the query, the height, the id) is the chart's. */
export const STEP_KEYS = ['label', 'preset', 'presetTop', 'presetAggregate', 'presetTarget', 'shape', 'calc', 'title', 'colors', 'option']
export const TRANSITIONS = ['morph', 'fade', 'none']
export const EASINGS = ['cubicInOut', 'cubicOut', 'linear', 'elasticOut', 'backOut']

const plain = v => !!v && typeof v === 'object' && !Array.isArray(v)

/**
 * The steps of a story: { steps, problem }. `value` is a list or JSON text. A mistake gives no steps and a sentence;
 * the chart is then drawn as written, without a story.
 */
export function parseStory(value) {
  let list = value
  if (typeof list === 'string') {
    if (!list.trim()) return { steps: [], problem: '' }
    try { list = JSON.parse(list) }
    catch { return { steps: [], problem: 'The story is not valid JSON.' } }
  }
  if (list === undefined || list === null) return { steps: [], problem: '' }
  if (!Array.isArray(list)) return { steps: [], problem: 'A story is a list of steps.' }
  if (list.length > MAX_STEPS) return { steps: [], problem: `A story can have up to ${MAX_STEPS} steps.` }
  const steps = []
  for (let i = 0; i < list.length; i++) {
    const step = list[i]
    if (!plain(step)) return { steps: [], problem: `Step ${i + 1} of the story must be a list of settings in { }.` }
    const unknown = Object.keys(step).filter(k => !STEP_KEYS.includes(k))
    if (unknown.length) return { steps: [], problem: `Step ${i + 1} of the story has an unknown setting: ${unknown[0]}. A step can change: ${STEP_KEYS.join(', ')}.` }
    steps.push(step)
  }
  return { steps, problem: '' }
}

/** The chart's settings with step `index` (0-based) on top. `shape` and `option` are merged, the rest replaces. */
export function stepSettings(props, steps, index) {
  const step = steps[Math.max(0, Math.min(steps.length - 1, index | 0))]
  if (!step) return props
  const out = { ...props }
  for (const key of STEP_KEYS) {
    if (key === 'label' || !Object.hasOwn(step, key)) continue
    if (key === 'option') {
      const base = readOverride(props.option, 5000).value ?? {}
      out.option = mergeOption(base, plain(step.option) ? step.option : {})
    }
    else if (key === 'shape') out.shape = { ...(plain(props.shape) ? props.shape : {}), ...(plain(step.shape) ? step.shape : {}) }
    else out[key] = step[key]
  }
  return out
}

/** The label of a step (for the editor's step list): its `label`, or "Step 3". */
export function stepLabel(steps, index) {
  const label = String(steps[index]?.label ?? '').trim()
  return label || `Step ${index + 1}`
}

/**
 * How the story moves: { kind: 'morph'|'fade'|'none', duration, easing }. Invalid settings fall back to the defaults.
 */
export function storyMotion(props = {}) {
  const kind = TRANSITIONS.includes(props.storyTransition) ? props.storyTransition : 'morph'
  const d = Number(props.storyDuration)
  const duration = kind === 'none' ? 0 : Number.isFinite(d) ? Math.max(0, Math.min(3000, Math.round(d))) : 700
  const easing = EASINGS.includes(props.storyEasing) ? props.storyEasing : 'cubicInOut'
  return { kind, duration, easing }
}

/**
 * An option made ready to be applied on top of the previous step's (`previous`: the option this function returned for
 * the step before, or null): every series and axis gets a stable id, the animation is the story's, and with a morph
 * the series carry the keys ECharts' universal transition matches old and new shapes by (see morphKeys).
 */
export function stabilize(option, motion, previous = null) {
  if (!plain(option)) return option
  const out = { ...option }
  const named = (list, prefix) => (Array.isArray(list) ? list : list === undefined ? [] : [list]).map((item, i) => (plain(item) ? { ...item, id: item.id ?? `${prefix}${i}` } : item))
  const used = new Set()
  let series = (Array.isArray(out.series) ? out.series : out.series === undefined ? [] : [out.series]).map((s, i) => {
    if (!plain(s)) return s
    let id = s.id ?? (s.name !== undefined && s.name !== '' ? `series:${s.name}` : `series:${i}`)
    while (used.has(id)) id += '_'
    used.add(id)
    return { ...s, id }
  })
  if (motion.kind === 'morph') series = morphKeys(series, plain(previous) ? previous.series : null)
  if (series.length) out.series = series
  for (const axis of ['xAxis', 'yAxis']) if (out[axis] !== undefined) out[axis] = named(out[axis], `${axis}:`)
  if (motion.kind === 'none') {
    out.animation = false
  }
  else {
    out.animation = true
    out.animationDurationUpdate = motion.kind === 'fade' ? Math.round(motion.duration / 2) : motion.duration
    out.animationEasingUpdate = motion.easing
    out.animationDuration = motion.duration
  }
  return out
}

/** Series types whose single series lists named parts (a slice, a funnel step, a tile) that a morph can grow from. */
export const PART_TYPES = ['pie', 'funnel', 'treemap', 'sunburst']

const asList = v => (Array.isArray(v) ? v : v === undefined || v === null ? [] : [v])
const itemName = item => (plain(item) ? item.name : undefined)

/**
 * The keys of a real morph (ECharts universal transition), worked out from the step before:
 * - Same series ids before and after (line -> bar, bar -> line, more or fewer series): ECharts moves each series' shapes
 *   into the new ones by itself.
 * - Several series -> one series of named parts (lines or bars -> funnel, pie): the new series' `seriesKey` lists the
 *   old series' ids and each part's `groupId` is the series name, so all the points or bars of "Received" melt into
 *   the "Received" step of the funnel.
 * - One series of parts -> another (funnel -> pie): it keeps the same `seriesKey`, so the trapezoids bend into slices.
 * - One series of parts -> several series (back again): each new series is found under the old `seriesKey` and its
 *   `dataGroupId`, so the part splits back into that series' points or bars.
 * Every series that is not made of parts carries `dataGroupId` (its name) so the next step can find it. A step that matches none of these
 * cross-fades (ECharts adds the new shapes and removes the old). Exported for the tests.
 */
export function morphKeys(series, previousSeries) {
  const before = asList(previousSeries).filter(plain)
  const morph = { enabled: true, divideShape: 'clone' }
  let out = series.map((s) => {
    if (!plain(s)) return s
    const ut = plain(s.universalTransition) ? { ...morph, ...s.universalTransition } : morph
    const next = { ...s, universalTransition: ut }
    // A series of parts is matched part by part (groupId); any other series as a whole (dataGroupId).
    if (!PART_TYPES.includes(next.type) && next.dataGroupId === undefined && next.name !== undefined && next.name !== '') next.dataGroupId = String(next.name)
    if (PART_TYPES.includes(next.type) && Array.isArray(next.data))
      next.data = next.data.map(item => (plain(item) && item.name !== undefined && item.groupId === undefined ? { ...item, groupId: String(item.name) } : item))
    return next
  })
  const real = out.filter(plain)
  if (!before.length || real.length !== 1 || real[0].universalTransition.seriesKey !== undefined) return out
  const only = real[0]
  // ECharts finds the old series under its seriesKey (or its id when it has none), so a key is passed on even when the
  // id stays the same (funnel -> pie).
  const priorKey = before.length === 1 ? before[0].universalTransition?.seriesKey : undefined
  let key
  if (priorKey !== undefined) key = Array.isArray(priorKey) ? [...priorKey] : priorKey
  else if (before.some(s => s.id === only.id)) return out
  else if (before.length === 1) key = before[0].id
  else if (PART_TYPES.includes(only.type)) {
    // Only old series whose name is one of the new parts: ECharts needs every id in the list to exist before.
    const parts = new Set(asList(only.data).map(itemName).filter(n => n !== undefined).map(String))
    const matched = before.filter(s => s.name !== undefined && parts.has(String(s.name))).map(s => s.id)
    if (matched.length) key = matched
  }
  if (key === undefined) return out
  // ECharts matches a string key with the old series' id, so one -> one keeps the old id instead of naming a key.
  out = out.map(s => (s === only ? (typeof key === 'string' && priorKey === undefined ? { ...s, id: key } : { ...s, universalTransition: { ...s.universalTransition, seriesKey: key } }) : s))
  return out
}

/** What setOption must replace (not merge) when a step changes the chart: the parts whose items can come and go. */
export const REPLACE_MERGE = ['series', 'xAxis', 'yAxis', 'dataset', 'legend', 'grid', 'visualMap']
