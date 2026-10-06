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
 * An option made ready to be applied on top of the previous step's: every series and axis gets a stable id (so
 * ECharts matches the old series with the new one and moves it), a series that changes kind morphs
 * (universalTransition) and the animation is the story's.
 */
export function stabilize(option, motion) {
  if (!plain(option)) return option
  const out = { ...option }
  const named = (list, prefix) => (Array.isArray(list) ? list : list === undefined ? [] : [list]).map((item, i) => (plain(item) ? { ...item, id: item.id ?? `${prefix}${i}` } : item))
  const used = new Set()
  const series = (Array.isArray(out.series) ? out.series : out.series === undefined ? [] : [out.series]).map((s, i) => {
    if (!plain(s)) return s
    let id = s.id ?? (s.name !== undefined && s.name !== '' ? `series:${s.name}` : `series:${i}`)
    while (used.has(id)) id += '_'
    used.add(id)
    return { ...s, id, ...(motion.kind === 'morph' ? { universalTransition: { enabled: true, divideShape: 'clone' } } : {}) }
  })
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

/** What setOption must replace (not merge) when a step changes the chart: the parts whose items can come and go. */
export const REPLACE_MERGE = ['series', 'xAxis', 'yAxis', 'dataset', 'legend', 'grid', 'visualMap']
