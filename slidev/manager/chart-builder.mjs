// The chart builder in /studio (round 6): a two-pane dialog that makes or
// changes one <MissionChart> on a slide. The live preview is on the left
// (drawn by the same engine as the slides, chart-engine.mjs); the settings are
// on the right in four tabs: Numbers (mission numbers from the database, a
// pasted table or typed rows), Chart type (every ECharts series type), Settings
// (grouped: title, series, axes, labels, legend, tooltip, colours, trend line,
// reference lines, colour by value, zoom and tools, animation, numbers, size)
// and All options (the whole ECharts option as JSON, with ECharts' names
// offered as you type and checked). Undo and Redo work inside the dialog.
//
// A chart is its numbers plus an ECharts option; the builder writes
// <MissionChart chart-id="…" :query='…' | :rows="…" :option='…' />. The
// chart-id is how Edit chart finds the chart again when it saves, so it never
// changes another chart on the slide.
//
// Who uses it: studio.html loads it on the first click on "Add chart" or "Edit
// chart" (import('/_manager/chart/chart-builder.mjs')); the portal's
// Whiteboard uses it too (whiteboard-builder.mjs).
// How it fits: the manager serves this file and the modules it imports from
// /_manager/chart/ (chart-access.mjs builderFiles, numbers.mjs). Reading and
// writing chart tags is chart-builder-core.mjs (tested in Node); this file is
// the dialog around it. Wording: the Preach My Gospel guide (people first,
// plain).
import { KPI_NAMES, PALETTE, parseRows, TREND_METHODS } from './chart-core.mjs'
import { chartView, legacyToOption, readOption, viewOption } from './chart-engine.mjs'
import { applyKind, blockAt, CHART_KINDS, chartIds, chartName, chartTitle, getPath, insertChart, KEY_INDICATORS, KIND_HINTS, kindOf, LOCATE_PROBLEMS, locateChart, newChartId, numbersName, pickChartTag, readChart, replaceTag, setPath, tableRows, WEEK_CHOICES, writeChart } from './chart-builder-core.mjs'
import { canonicalJson, MAX_WEEKS, normalizeSpec } from './chart-spec.mjs'
import { checkOption, optionSchema } from './chart-schema.mjs'
import { safeChartOption } from './safe-chart-option.mjs'

const TABS = [['data', 'Numbers'], ['type', 'Chart type'], ['settings', 'Settings'], ['json', 'All options']]
const TREND_NAMES = { 'none': 'Off', 'linear': 'Straight', 'polynomial': 'Curved', 'exponential': 'Growing', 'logarithmic': 'Levelling off', 'moving-average': 'Moving average' }
const LEVEL_PLURAL = { zone: 'zones', district: 'districts', area: 'areas' }
const TRANSFORM_NAMES = { none: 'The numbers', pct_of_goal: '% of goal', cumulative: 'Running total', rolling4: 'Average of 4 weeks', per_area: 'Per area' }
const COMPARE_NAMES = { previous_goal: 'Goal set the week before', goal: "Next week's goal", none: 'Nothing' }
const PRIVACY = 'Charts show totals only, never names or notes.'
const NOT_LOADED = 'The numbers could not load. Try again in a minute.'
const NO_TABLE = 'Add a row of headings and at least one row of numbers.'
const AXIS_KINDS = new Set(['bar', 'line', 'area', 'stacked', 'sideways', 'combo', 'pictorial', 'scatter', 'ripple', 'multiples'])
const PALETTES = {
  mission: null,
  warm: ['#d96b2b', '#b88400', '#cf4545', '#a64f8e', '#6656c9', '#3f8a3a'],
  cool: ['#00869e', '#2a5f99', '#6656c9', '#3f8a3a', '#1aa3b0', '#a64f8e'],
  calm: ['#4e7d8c', '#8aa6a3', '#c9a66b', '#a3677a', '#6c7fa6', '#7a9a62'],
}
const EASINGS = ['cubicOut', 'cubicInOut', 'linear', 'quadraticOut', 'elasticOut', 'bounceOut', 'backOut']

// Little pictures for the type picker (24×24, drawn with currentColor).
const ICONS = {
  bar: '<rect x="3" y="12" width="4" height="9"/><rect x="10" y="6" width="4" height="15"/><rect x="17" y="9" width="4" height="12"/>',
  line: '<polyline points="3,17 9,11 14,14 21,5" fill="none" stroke-width="2.2"/>',
  area: '<path d="M3 20 L3 15 L9 10 L14 13 L21 6 L21 20 Z" opacity=".55"/><polyline points="3,15 9,10 14,13 21,6" fill="none" stroke-width="2"/>',
  pie: '<path d="M12 3 A9 9 0 1 1 3 12 L12 12 Z"/><path d="M12 3 L12 12 L3 12 A9 9 0 0 1 12 3 Z" opacity=".5"/>',
  donut: '<circle cx="12" cy="12" r="7" fill="none" stroke-width="4.5"/>',
  tile: '<text x="12" y="15" text-anchor="middle" font-size="11" font-weight="700" stroke="none">42</text><polyline points="4,20 9,18 14,19 20,16" fill="none" stroke-width="1.5"/>',
  gauge: '<path d="M4 17 A8 8 0 0 1 20 17" fill="none" stroke-width="3"/><line x1="12" y1="17" x2="16" y2="10" stroke-width="2"/>',
  stacked: '<rect x="3" y="13" width="4" height="8"/><rect x="3" y="8" width="4" height="5" opacity=".5"/><rect x="10" y="9" width="4" height="12"/><rect x="10" y="4" width="4" height="5" opacity=".5"/><rect x="17" y="12" width="4" height="9"/><rect x="17" y="7" width="4" height="5" opacity=".5"/>',
  sideways: '<rect x="3" y="4" width="12" height="4"/><rect x="3" y="10" width="18" height="4"/><rect x="3" y="16" width="8" height="4"/>',
  combo: '<rect x="3" y="12" width="4" height="9" opacity=".6"/><rect x="10" y="8" width="4" height="13" opacity=".6"/><rect x="17" y="10" width="4" height="11" opacity=".6"/><polyline points="3,9 10,5 17,7 21,4" fill="none" stroke-width="2"/>',
  pictorial: '<rect x="3" y="17" width="5" height="3"/><rect x="3" y="13" width="5" height="3"/><rect x="10" y="17" width="5" height="3"/><rect x="10" y="13" width="5" height="3"/><rect x="10" y="9" width="5" height="3"/><rect x="10" y="5" width="5" height="3"/><rect x="17" y="17" width="4" height="3"/><rect x="17" y="13" width="4" height="3"/><rect x="17" y="9" width="4" height="3"/>',
  polar: '<path d="M12 12 L12 3 A9 9 0 0 1 20 9 Z"/><path d="M12 12 L20 9 A9 9 0 0 1 16 19 Z" opacity=".6"/><path d="M12 12 L16 19 A9 9 0 0 1 5 17 Z" opacity=".35"/>',
  rose: '<path d="M12 12 L12 2 A10 10 0 0 1 21 9 Z"/><path d="M12 12 L19 11 A7 7 0 0 1 15 18 Z" opacity=".6"/><path d="M12 12 L13 17 A5 5 0 0 1 7 13 Z" opacity=".35"/>',
  radar: '<polygon points="12,3 20,9 17,19 7,19 4,9" fill="none" stroke-width="1.4"/><polygon points="12,7 17,10 15,16 9,15 7,10" opacity=".6"/>',
  funnel: '<rect x="3" y="4" width="18" height="4"/><rect x="6" y="10" width="12" height="4" opacity=".75"/><rect x="9" y="16" width="6" height="4" opacity=".5"/>',
  multiples: '<rect x="3" y="3" width="8" height="8" fill="none" stroke-width="1.4"/><rect x="13" y="3" width="8" height="8" fill="none" stroke-width="1.4"/><rect x="3" y="13" width="8" height="8" fill="none" stroke-width="1.4"/><rect x="13" y="13" width="8" height="8" fill="none" stroke-width="1.4"/><polyline points="4,9 7,6 10,7" fill="none" stroke-width="1.2"/><polyline points="14,9 17,5 20,6" fill="none" stroke-width="1.2"/>',
  scatter: '<circle cx="5" cy="17" r="2"/><circle cx="9" cy="12" r="2"/><circle cx="14" cy="14" r="2"/><circle cx="19" cy="6" r="2"/>',
  ripple: '<circle cx="8" cy="15" r="2.2"/><circle cx="8" cy="15" r="5" fill="none" stroke-width="1" opacity=".6"/><circle cx="17" cy="7" r="2.2"/><circle cx="17" cy="7" r="4.5" fill="none" stroke-width="1" opacity=".6"/>',
  heatmap: '<rect x="3" y="3" width="5" height="5"/><rect x="10" y="3" width="5" height="5" opacity=".4"/><rect x="17" y="3" width="4" height="5" opacity=".7"/><rect x="3" y="10" width="5" height="5" opacity=".6"/><rect x="10" y="10" width="5" height="5"/><rect x="17" y="10" width="4" height="5" opacity=".3"/><rect x="3" y="17" width="5" height="4" opacity=".3"/><rect x="10" y="17" width="5" height="4" opacity=".8"/><rect x="17" y="17" width="4" height="4"/>',
  calendar: '<rect x="3" y="5" width="18" height="16" rx="2" fill="none" stroke-width="1.5"/><line x1="3" y1="9" x2="21" y2="9" stroke-width="1.5"/><rect x="6" y="12" width="3" height="3"/><rect x="11" y="12" width="3" height="3" opacity=".5"/><rect x="16" y="12" width="3" height="3" opacity=".8"/><rect x="6" y="16" width="3" height="3" opacity=".4"/><rect x="11" y="16" width="3" height="3"/>',
  river: '<path d="M2 14 C6 8 9 16 13 10 S20 12 22 8 L22 13 C18 17 16 13 12 16 S5 16 2 18 Z"/><path d="M2 18 C6 16 9 20 13 17 S19 18 22 14 L22 19 C18 21 14 20 11 21 S5 21 2 21 Z" opacity=".5"/>',
  boxplot: '<line x1="12" y1="3" x2="12" y2="21" stroke-width="1.5"/><rect x="7" y="8" width="10" height="8"/><line x1="7" y1="12" x2="17" y2="12" stroke="#fff" stroke-width="1.5"/>',
  candlestick: '<line x1="6" y1="4" x2="6" y2="20" stroke-width="1.4"/><rect x="4" y="8" width="4" height="8"/><line x1="12" y1="3" x2="12" y2="18" stroke-width="1.4"/><rect x="10" y="6" width="4" height="6" opacity=".5"/><line x1="18" y1="6" x2="18" y2="21" stroke-width="1.4"/><rect x="16" y="10" width="4" height="8"/>',
  range: '<rect x="4" y="8" width="4" height="10" rx="1"/><rect x="10" y="4" width="4" height="9" rx="1" opacity=".7"/><rect x="16" y="10" width="4" height="9" rx="1"/>',
  waterfall: '<rect x="3" y="10" width="4" height="11"/><rect x="8" y="6" width="4" height="4" opacity=".6"/><rect x="13" y="6" width="4" height="7" opacity=".35"/><rect x="18" y="13" width="3" height="8"/>',
  timeline: '<rect x="4" y="10" width="4" height="7"/><rect x="10" y="5" width="4" height="12"/><rect x="16" y="8" width="4" height="9"/><line x1="3" y1="21" x2="21" y2="21" stroke-width="1.5"/><circle cx="9" cy="21" r="1.8"/>',
  treemap: '<rect x="3" y="3" width="10" height="18"/><rect x="14" y="3" width="7" height="10" opacity=".6"/><rect x="14" y="14" width="7" height="7" opacity=".35"/>',
  sunburst: '<circle cx="12" cy="12" r="4"/><path d="M12 3 A9 9 0 0 1 21 12 L17 12 A5 5 0 0 0 12 7 Z" opacity=".6"/><path d="M21 12 A9 9 0 0 1 5 18 L8 15 A5 5 0 0 0 17 12 Z" opacity=".35"/>',
  tree: '<circle cx="5" cy="12" r="2"/><circle cx="18" cy="5" r="2"/><circle cx="18" cy="12" r="2"/><circle cx="18" cy="19" r="2"/><path d="M7 12 C12 12 12 5 16 5 M7 12 L16 12 M7 12 C12 12 12 19 16 19" fill="none" stroke-width="1.4"/>',
  sankey: '<rect x="3" y="4" width="3" height="16"/><rect x="18" y="3" width="3" height="8"/><rect x="18" y="13" width="3" height="8"/><path d="M6 4 C12 4 12 3 18 3 L18 11 C12 11 12 12 6 12 Z" opacity=".45"/><path d="M6 12 C12 12 12 13 18 13 L18 21 C12 21 12 20 6 20 Z" opacity=".3"/>',
  chord: '<circle cx="12" cy="12" r="9" fill="none" stroke-width="2"/><path d="M5 7 C10 12 14 12 19 7" fill="none" stroke-width="1.6" opacity=".7"/><path d="M4 14 C10 13 13 17 15 20.5" fill="none" stroke-width="1.6" opacity=".5"/>',
  graph: '<circle cx="6" cy="7" r="2.5"/><circle cx="18" cy="6" r="2"/><circle cx="12" cy="17" r="3"/><circle cx="20" cy="17" r="1.8"/><path d="M6 7 L18 6 M6 7 L12 17 M18 6 L12 17 M12 17 L20 17" fill="none" stroke-width="1.2"/>',
  parallel: '<line x1="4" y1="3" x2="4" y2="21" stroke-width="1.2"/><line x1="12" y1="3" x2="12" y2="21" stroke-width="1.2"/><line x1="20" y1="3" x2="20" y2="21" stroke-width="1.2"/><polyline points="4,6 12,14 20,8" fill="none" stroke-width="1.8"/><polyline points="4,16 12,9 20,18" fill="none" stroke-width="1.8" opacity=".6"/>',
  lines: '<circle cx="5" cy="18" r="2"/><circle cx="19" cy="6" r="2"/><circle cx="18" cy="18" r="2"/><path d="M5 18 Q9 6 19 6 M5 18 Q12 13 18 18" fill="none" stroke-width="1.6"/>',
}

const h = value => String(value ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c])
const j = value => h(JSON.stringify(value ?? null))
const same = (a, b) => JSON.stringify(a ?? null) === JSON.stringify(b ?? null)
const typing = el => !!el && ((el.tagName === 'INPUT' && !['checkbox', 'radio', 'button'].includes(el.type)) || el.tagName === 'TEXTAREA' || el.isContentEditable)

// ---- the chart libraries (the same vendored files the slides use) ----------------

let libraries = null
function loadScript(src) {
  return new Promise((resolve, reject) => {
    const script = document.createElement('script')
    script.src = src
    script.onload = () => resolve()
    script.onerror = () => { script.remove(); reject(new Error('The chart library could not be loaded.')) }
    document.head.appendChild(script)
  })
}
function loadLibraries() {
  const g = globalThis
  libraries ||= Promise.all([g.echarts?.init ? null : loadScript('/_manager/chart/echarts.min.js'), g.ecStat?.regression ? null : loadScript('/_manager/chart/ecStat.min.js')])
    .then(() => {
      if (!g.__gfmTransforms && g.ecStat?.transform) {
        for (const t of Object.values(g.ecStat.transform)) { try { g.echarts.registerTransform(t) } catch {} }
        g.__gfmTransforms = true
      }
      return { echarts: g.echarts, ecStat: g.ecStat }
    })
    .catch((error) => { libraries = null; throw error })
  return libraries
}

// ---- styles (injected once) ----------------------------------------------------

const STYLES = `
.cb{border:0;padding:0;margin:auto;width:min(1280px,calc(100vw - 24px));height:min(860px,calc(100dvh - 24px));max-height:none;max-width:none;border-radius:16px;background:var(--panel);color:var(--text);box-shadow:0 30px 80px rgba(0,0,0,.3);overflow:hidden}
.cb[open]{display:flex;flex-direction:column}
.cb::backdrop{background:rgba(10,20,30,.45)}
.cb *{box-sizing:border-box}
.cb-head{flex:none;display:flex;align-items:center;gap:10px;padding:10px 14px;border-bottom:1px solid var(--line)}
.cb-head h2{margin:0;font-size:18px;color:var(--navy);line-height:1.25}
.cb-head p{margin:2px 0 0;font-size:13px;color:var(--muted);line-height:1.35}
.cb-head .grow{flex:1;min-width:0}
.cb-history{display:flex;gap:4px}
.cb-icon{min-width:44px;min-height:44px;display:inline-flex;align-items:center;justify-content:center;border:1px solid var(--line);border-radius:10px;background:var(--panel);color:var(--navy);font:inherit;font-size:18px;cursor:pointer}
.cb-icon:disabled{opacity:.4;cursor:default}
.cb-icon:not(:disabled):hover{background:var(--soft)}
.cb-body{flex:1;min-height:0;display:flex}
.cb-preview{flex:1 1 56%;min-width:0;display:flex;flex-direction:column;gap:8px;padding:16px;background:var(--page);overflow:auto}
.cb-side{flex:0 0 44%;min-width:0;display:flex;flex-direction:column;border-left:1px solid var(--line)}
.cb-tabs{flex:none;display:flex;gap:2px;padding:6px 10px 0;border-bottom:1px solid var(--line);overflow-x:auto}
.cb-tabs button{flex:none;border:0;background:none;color:var(--muted);font:inherit;font-size:15px;font-weight:650;padding:10px 12px 12px;min-height:44px;border-bottom:3px solid transparent;cursor:pointer}
.cb-tabs button[aria-selected="true"]{color:var(--teal);border-bottom-color:var(--teal)}
[data-theme="dark"] .cb-tabs button[aria-selected="true"]{color:#5cc6cf;border-bottom-color:#5cc6cf}
.cb-panels{flex:1;min-height:0;overflow-y:auto;padding:12px 14px 24px}
.cb-panels [data-panel="json"]{display:flex;flex-direction:column;min-height:100%}
.cb-stagebox{position:relative;flex:none;width:100%;overflow:hidden;border-radius:10px;border:1px solid var(--line);background:#fff}
.cb-stagebox.dark{background:#121212}
.cb-stage{position:absolute;left:0;top:0;width:980px;transform-origin:0 0}
.cb-chart{width:100%;height:100%}
.cb-msg{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;text-align:center;padding:20px;font-size:15px;color:#556d7a;background:inherit}
.cb-stagebox.dark .cb-msg{color:#9fb3bb}
.cb-status{margin:0;font-size:13px;line-height:1.45;color:var(--muted)}
.cb-status.error{color:var(--danger)}
.cb-privacy{margin:0;font-size:12.5px;line-height:1.4;color:var(--muted)}
.cb-foot{flex:none;display:flex;align-items:center;gap:10px;flex-wrap:wrap;padding:10px 14px;border-top:1px solid var(--line);background:var(--panel)}
.cb-foot .grow{flex:1;min-width:120px;font-size:13px;color:var(--muted)}
.cb-foot .error{color:var(--danger)}
.cb .btn{min-height:44px;font-size:15px}
.cb select{font:inherit;font-size:16px;color:var(--text);background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:8px 10px;min-height:44px}
.cb h3{font-size:14px;margin:16px 0 8px;color:var(--navy)}
.cb h3:first-child{margin-top:2px}
.cb .cb-question{font-size:17px;margin:2px 0 10px}
.cb .hint{font-size:13px;color:var(--muted);margin:4px 0 8px;line-height:1.45}
.cb-chips{display:flex;flex-wrap:wrap;gap:6px}
.cb-chip{display:inline-flex;align-items:center;gap:6px;min-height:44px;padding:8px 13px;border:1px solid var(--line);border-radius:22px;background:var(--panel);color:var(--navy);font:inherit;font-size:14.5px;font-weight:600;cursor:pointer;text-align:left}
.cb-chip:hover{background:var(--soft)}
.cb-chip[aria-pressed="true"]{border-color:var(--teal);background:var(--soft);color:var(--teal)}
[data-theme="dark"] .cb-chip[aria-pressed="true"]{color:#5cc6cf;border-color:#5cc6cf}
.cb-chip:focus-visible,.cb-tabs button:focus-visible,.cb-type:focus-visible,.cb-icon:focus-visible{outline:3px solid rgba(8,127,140,.4);outline-offset:1px}
.cb-check{display:flex;align-items:center;gap:10px;min-height:44px;padding:4px 2px;font-size:15px;cursor:pointer;line-height:1.3}
.cb-check input{width:20px;height:20px;flex:none;accent-color:var(--teal)}
.cb-group{border:1px solid var(--line);border-radius:12px;padding:2px 12px;margin:0 0 8px;background:var(--panel)}
.cb-group>summary{min-height:44px;display:flex;align-items:center;gap:8px;font-weight:650;font-size:15px;cursor:pointer;color:var(--navy);list-style:none}
.cb-group>summary::-webkit-details-marker{display:none}
.cb-group>summary::before{content:"›";display:inline-block;width:14px;transition:transform .15s;color:var(--muted)}
.cb-group[open]>summary::before{transform:rotate(90deg)}
.cb-group>summary .note{margin-left:auto;font-weight:500;font-size:13px;color:var(--muted)}
.cb-group[open]>summary{border-bottom:1px solid var(--line);margin-bottom:8px}
.cb-group>div{padding-bottom:6px}
.cb-field{display:flex;flex-direction:column;gap:5px;margin:0 0 10px;font-size:14px;font-weight:600;color:var(--navy)}
.cb-field input[type=text],.cb-field input[type=number],.cb-field select,.cb textarea{font:inherit;font-size:16px;font-weight:400;color:var(--text);background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:10px 12px;min-height:44px;width:100%}
.cb textarea{min-height:180px;font-family:ui-monospace,SFMono-Regular,Consolas,monospace;line-height:1.45;resize:vertical}
.cb-field input[type=color],.cb-color input{width:52px;height:44px;border:1px solid var(--line);border-radius:10px;padding:3px;background:var(--panel)}
.cb-row{display:flex;gap:10px;flex-wrap:wrap}
.cb-row>.cb-field{flex:1 1 130px;min-width:0}
.cb-colors{display:flex;flex-wrap:wrap;gap:8px 14px}
.cb-color{display:flex;align-items:center;gap:8px;font-size:14px;min-height:44px}
.cb-kinds h4{font-size:13px;color:var(--muted);margin:12px 0 6px;font-weight:650}
.cb-kinds h4:first-child{margin-top:0}
.cb-types{display:grid;grid-template-columns:repeat(auto-fill,minmax(104px,1fr));gap:8px}
.cb-type{display:flex;flex-direction:column;align-items:center;justify-content:center;gap:6px;min-height:80px;padding:8px 4px;border:1px solid var(--line);border-radius:12px;background:var(--panel);color:var(--navy);font:inherit;font-size:13.5px;font-weight:600;cursor:pointer;text-align:center;line-height:1.2}
.cb-type svg{width:30px;height:30px;fill:currentColor;stroke:currentColor;stroke-width:0;color:var(--teal)}
.cb-type[aria-pressed="true"]{border-color:var(--teal);background:var(--soft);box-shadow:inset 0 0 0 1px var(--teal)}
.cb-table{width:100%;border-collapse:collapse;font-size:13px;margin-top:8px}
.cb-table th,.cb-table td{border:1px solid var(--line);padding:5px 7px;text-align:left}
.cb-table th{background:var(--soft)}
.cb-grid{overflow-x:auto;max-width:100%}
.cb-grid table{border-collapse:collapse}
.cb-grid td{padding:2px}
.cb-grid input{font:inherit;font-size:16px;width:112px;min-height:44px;padding:8px;border:1px solid var(--line);border-radius:8px;background:var(--panel);color:var(--text)}
.cb-grid tr:first-child input{font-weight:650;background:var(--soft)}
.cb-monaco{flex:1;min-height:320px;border:1px solid var(--line);border-radius:10px;overflow:hidden}
.cb-code{white-space:pre-wrap;word-break:break-all;font:12.5px/1.5 ui-monospace,SFMono-Regular,Consolas,monospace;background:var(--soft);border:1px solid var(--line);border-radius:10px;padding:10px;margin:0;max-height:160px;overflow:auto}
.cb-problems{margin:6px 0;padding:0;list-style:none;font-size:13.5px}
.cb-problems li{margin:3px 0}
.cb-problems .error{color:var(--danger)}
.cb-problems .warn{color:var(--warn)}
.cb-problem{color:var(--danger);font-size:13.5px;margin:6px 0}
.cb-link{display:inline-flex;align-items:center;min-height:44px;padding:8px 2px;border:0;background:none;color:var(--teal);font:inherit;font-size:15px;font-weight:650;cursor:pointer;text-decoration:underline;text-underline-offset:3px}
[data-theme="dark"] .cb-link{color:#5cc6cf}
.cb-where{min-width:0}
@media(max-width:760px){
  .cb{width:100vw;height:100dvh;max-height:100dvh;border-radius:0;margin:0}
  .cb-body{flex-direction:column;overflow:hidden}
  .cb-preview{flex:none;max-height:40dvh;padding:8px 10px;gap:4px;border-bottom:1px solid var(--line)}
  .cb-side{flex:1;min-height:0;border-left:0}
  .cb-panels{padding:10px 12px 20px}
  .cb-head{padding:8px 10px;gap:6px}
  .cb-head h2{font-size:16px}
  .cb-head p{font-size:12.5px;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
  .cb-head .btn{padding:8px 10px}
  .cb-history{gap:2px}
  .cb-tabs{padding:2px 4px 0}
  .cb-tabs button{padding:10px 9px 12px;font-size:14px}
  .cb-foot{padding:8px 10px}
  .cb-foot .grow{flex-basis:100%;order:-1}
  .cb-foot .btn,.cb-foot select{flex:1}
  .cb-privacy{font-size:12px}
  .cb-types{grid-template-columns:repeat(auto-fill,minmax(92px,1fr))}
}
`

function injectStyles() {
  if (document.getElementById('cb-styles')) return
  const style = document.createElement('style')
  style.id = 'cb-styles'
  style.textContent = STYLES
  document.head.appendChild(style)
}

// Round 8: what a zone's presentation shows (portal-api charts.deck_units); in portal/i18n/catalogs.json.
const ZONE_DECK_NUMBERS = "In a zone's presentation, everyone sees only that zone's numbers, managers too."

// ---- the dialog ----------------------------------------------------------------

let current = null

/**
 * Opens the builder. options: { slug, api (PresentationSession.api), frame (the
 * Studio iframe), slideNo() (the slide the editor shows; round 8), selection ({ no, range, tag, sig, chartId } of Studio's
 * selection or null; sig is Studio's fingerprint of the clicked tag and
 * chartId the chart's chart-id, from the element on the slide), edit (true:
 * change the selected chart), toast(text, warn), loadMonaco(), onSaved({ no,
 * chartId }) (the shell selects the chart again) }.
 *
 * The portal's Whiteboard opens it without a deck (whiteboard-builder.mjs),
 * with options.target = { model (the board chart to change, or none for a new
 * one), number (true: "Add a key number", starting as a key-number tile),
 * save(model) } and options.onClose(). The chart is then handed to save() as
 * a board model (boardModel: { v: 2, source, spec | rows, option }) instead of
 * being written into a slide. Its numbers are asked for without a deck, like
 * the preview, so only managers get them.
 */
export async function openChartBuilder(options) {
  if (current?.dialog?.open) { current.dialog.focus(); return }
  injectStyles()
  const builder = new Builder(options)
  current = builder
  await builder.open()
}

/** The settings a new chart starts with: New people being taught, week by week, with the goal. */
function newState() {
  return {
    source: 'mission', tableMode: 'paste',
    tableText: 'Week\tNew people being taught\nAug 3\t12\nAug 10\t15\nAug 17\t14\nAug 24\t19',
    q: { measures: ['friends_found.actual'], compare: 'previous_goal', lastCompare: 'previous_goal', level: 'mission', filter: { zones: [], districts: [], areas: [] }, weeks: 12, includeCurrent: true, by: 'week', transform: 'none', sort: 'none', top: 0, audience: null },
    option: { title: { text: 'New people being taught' }, series: [{ type: 'bar' }] },
    height: 360,
    autoTitle: true,
  }
}

class Builder {
  constructor(options) {
    this.o = options
    this.slug = options.slug
    // The whiteboard (see openChartBuilder): no slide; the finished chart goes to target.save().
    this.target = options.target || null
    this.S = {
      ...newState(), tab: 'data', catalog: null, catalogError: '', answer: null, dataError: '', loading: false,
      editing: null, notes: [], keep: [], chartId: '', where: 'slide', slideNo: 1, saving: false, saveError: '',
      optionText: '', jsonProblems: { errors: [], warnings: [] }, moreNumbers: false, closing: false,
    }
    this.answers = new Map()
    this.history = []
    this.at = -1
    this.timers = {}
    this.chart = null
    this.monaco = null
  }

  // ---- slides (the same API Studio uses, routed by the Referer to this deck's editor) ----
  slideUrl(no) { return `/__slidev/slides/${no}.json` }
  referrer(no) { return `${location.origin}/edit/${encodeURIComponent(this.slug)}/${no}` }
  readSlide(no) { return this.o.api(this.slideUrl(no), { referrer: this.referrer(no), cache: 'no-store' }) }
  writeSlide(no, content) { return this.o.api(this.slideUrl(no), { method: 'POST', referrer: this.referrer(no), body: JSON.stringify({ content }) }) }

  currentSlideNo() {
    // Round 8: the editor runs on the deck address, so /studio cannot read the frame's address; it passes the
    // slide the editor says it shows (options.slideNo, from editor-bridge.js).
    const told = Number(this.o.slideNo?.())
    if (told > 0) return told
    try {
      const m = this.o.frame?.contentWindow?.location?.pathname?.match(/\/(\d+)\/?$/)
      if (m) return Number(m[1])
    } catch {}
    return this.o.selection?.no || 1
  }

  async open() {
    const S = this.S
    if (this.target) return this.openForBoard()
    S.slideNo = this.o.edit && this.o.selection ? this.o.selection.no : this.currentSlideNo()
    this.build()
    this.dialog.showModal()
    this.loadCatalog()
    if (this.o.edit) {
      try { await this.loadSelected() }
      catch (error) {
        this.o.toast(error.message, true)
        this.dialog.close()
        return
      }
    }
    S.optionText = JSON.stringify(S.option, null, 2)
    this.remember(true)
    this.renderAll()
    this.showTab(this.o.edit ? 'settings' : 'data')
    this.refreshData()
  }

  // ---- the whiteboard (target) ----
  /** Opens for the whiteboard: the board chart to change, a new key number, or a new chart. */
  openForBoard() {
    const S = this.S
    const { model, number } = this.target
    try {
      if (model) {
        this.fromBoardModel(model)
        S.editing = { board: true }
        S.autoTitle = false
      }
      else if (number) {
        // A key number of the last finished week against the goal set the week before, as on the Dashboards deck:
        // the week still being reported starts near 0.
        S.q.includeCurrent = false
        S.option = applyKind(S.option, 'tile')
      }
    }
    catch (error) {
      this.o.toast?.(error instanceof Error && error.message ? `This chart cannot be opened: ${error.message}` : 'This chart cannot be opened.', true)
      this.o.onClose?.()
      return
    }
    this.build()
    this.dialog.showModal()
    this.loadCatalog()
    S.optionText = JSON.stringify(S.option, null, 2)
    S.jsonProblems = checkOption(S.option)
    this.remember(true)
    this.renderAll()
    this.showTab(model ? 'settings' : 'data')
    this.refreshData()
  }

  /**
   * A board chart into the builder: { v: 2, source, spec | rows, option }. A chart the older builder placed
   * ({ v: 1, props, spec | rows, option? }) opens as the same chart drawn from an option (legacyToOption).
   */
  fromBoardModel(model) {
    const S = this.S
    if (!model || typeof model !== 'object' || Array.isArray(model)) throw new Error('its settings are missing.')
    let option
    if (model.props && typeof model.props === 'object') option = legacyToOption({ ...model.props, option: typeof model.option === 'string' ? model.option : undefined })
    else option = model.option && typeof model.option === 'object' && !Array.isArray(model.option) ? JSON.parse(JSON.stringify(model.option)) : null
    if (!option) throw new Error('its settings are missing.')
    S.option = option
    if (model.spec) this.fromSpec(normalizeSpec(model.spec))
    else if (Array.isArray(model.rows) && model.rows.length) {
      S.source = 'table'
      S.tableMode = 'paste'
      S.tableText = model.rows.map(String).join('\n')
    }
    else throw new Error('it has no numbers.')
  }

  /** The chart as the whiteboard keeps it (no chart-id or height: the board element is both). */
  boardModel() {
    const S = this.S
    const model = { v: 2, source: S.source === 'table' ? 'table' : 'mission', option: readOption(S.option).value ?? {} }
    if (model.source === 'mission') {
      const { spec, problem } = this.checkedSpec()
      if (!spec) throw new Error(problem)
      model.spec = spec
    }
    else {
      model.rows = tableRows(S.tableText)
      if (!model.rows) throw new Error(NO_TABLE)
    }
    // The chart frame's limits (whiteboard-chart.mjs boardLimitProblem, given as target.check).
    const problem = this.target?.check?.(model)
    if (problem) throw new Error(problem)
    return model
  }

  /** On the whiteboard: what keeps this chart off the board ('' when nothing does). */
  boardProblem() {
    try { this.boardModel(); return '' }
    catch (error) { return error?.message || '' }
  }

  /** Reads the selected chart from the slide: by its chart-id, or (older charts) by its lines and Studio's fingerprint. */
  async loadSelected() {
    const { no, range, sig, chartId } = this.o.selection
    const info = await this.readSlide(no)
    const content = String(info?.content ?? '')
    const located = locateChart(content, { id: chartId, range, sig })
    if (!located.found) throw new Error(LOCATE_PROBLEMS[located.problem] || LOCATE_PROBLEMS.none)
    const model = readChart(located.found)
    const S = this.S
    // Saving finds the chart by its chart-id; a chart without one (made before
    // round 6) is found by these lines and Studio's fingerprint, and gets an id.
    const picked = !chartId && Array.isArray(range) ? pickChartTag(blockAt(content, range), sig) : {}
    S.editing = { no, range: Array.isArray(range) ? [...range] : null, block: Array.isArray(range) ? content.split(/\r?\n/).slice(range[0], range[1]).join('\n') : '', sig: located.found.sig, chartId: model.chartId, index: picked.index ?? 0, count: picked.count ?? 1, duplicate: located.duplicate }
    S.chartId = model.chartId
    S.notes = model.notes
    S.keep = model.keep
    S.option = model.option
    S.height = model.height
    S.autoTitle = false
    if (model.spec) this.fromSpec(model.spec)
    else if (model.source === 'table') { S.source = 'table'; S.tableText = (model.rows || []).join('\n') }
    else if (model.source === 'data') S.source = 'data'
  }

  fromSpec(spec) {
    const q = this.S.q
    this.S.source = 'mission'
    const goals = spec.measures.filter(m => /\.(previous_goal|goal)$/.test(m))
    const main = spec.measures.filter(m => !goals.includes(m))
    // A goal whose number is also chosen is "Compare with"; a goal on its own stays a number.
    const paired = goals.filter(g => main.includes(g.replace(/\.(previous_goal|goal)$/, '.actual')))
    q.measures = [...main, ...goals.filter(g => !paired.includes(g))]
    q.compare = paired.some(g => g.endsWith('.previous_goal')) ? 'previous_goal' : paired.some(g => g.endsWith('.goal')) ? 'goal' : 'none'
    q.level = spec.level
    q.filter = { zones: spec.filter.zones || [], districts: spec.filter.districts || [], areas: spec.filter.areas || [] }
    q.weeks = spec.weeks.last
    q.includeCurrent = spec.includeCurrent
    q.by = spec.by
    q.transform = spec.transform
    q.sort = spec.sort
    q.top = spec.top
    q.audience = spec.audience
    this.S.moreNumbers = q.measures.length !== 1 || !KEY_INDICATORS.includes(q.measures[0].replace(/\.actual$/, ''))
  }

  async loadCatalog() {
    try {
      this.S.catalog = await this.o.api('/api/charts/catalog')
      this.S.catalogError = ''
      // Zone presentations (round 7): a ZL or STL is offered only their own zone (portal-api charts.py).
      if (!this.offeredLevels().includes(this.S.q.level)) { this.S.q.level = this.offeredLevels()[0]; this.S.q.audience = null }
    }
    catch (error) {
      this.S.catalogError = error.status && error.message ? error.message : 'The list of numbers could not load. Try again in a minute.'
    }
    if (this.dialog?.open) { this.render('data'); this.scheduleData() }
  }

  measure(id) { return this.S.catalog?.measures?.find(m => m.id === id) || null }

  /** The levels this person may chart: all four for managers; a ZL's or STL's list has no "The mission" (round 7). */
  offeredLevels() {
    const ids = (this.S.catalog?.levels || []).map(level => level.id)
    return ids.length ? ids : ['mission', 'zone', 'district', 'area']
  }

  /** True for a ZL or STL, whose list holds only their own zone (round 7). */
  zoneOnly() { return this.S.catalog?.scope === 'zone' }

  /** A number's goals ({ previous_goal: id, goal: id }) from the catalogue; before it loads, a guess from the id. */
  goalsOf(id) {
    const m = this.measure(id)
    if (m) return m.goals || {}
    return /\.actual$/.test(id) ? { previous_goal: id.replace(/\.actual$/, '.previous_goal'), goal: id.replace(/\.actual$/, '.goal') } : {}
  }

  /** The kinds of goal at least one chosen number has, in the order Compare with shows them. */
  goalKinds() {
    const kinds = new Set(this.S.q.measures.flatMap(id => Object.keys(this.goalsOf(id))))
    return Object.keys(COMPARE_NAMES).filter(k => kinds.has(k))
  }

  defaultAudience(level) { return level === 'mission' || level === 'zone' ? 'deck' : 'stewardship' }

  /** The query for the current choices (not yet checked). */
  specFromState() {
    const q = this.S.q
    const measures = []
    for (const id of q.measures) {
      measures.push(id)
      const goals = this.goalsOf(id)
      if (q.compare !== 'none' && goals[q.compare]) measures.push(goals[q.compare])
    }
    const allowed = { mission: [], zone: ['zones'], district: ['zones', 'districts'], area: ['zones', 'districts', 'areas'] }[q.level]
    const filter = {}
    for (const key of allowed) if (q.filter[key]?.length) filter[key] = q.filter[key]
    const by = q.level === 'mission' ? 'week' : q.by
    return {
      measures, level: q.level, by, filter, weeks: { last: q.weeks }, includeCurrent: q.includeCurrent,
      transform: by === 'unit' && ['cumulative', 'rolling4'].includes(q.transform) ? 'none' : q.transform,
      sort: by === 'unit' ? q.sort : 'none', top: by === 'unit' ? q.top : 0,
      audience: q.audience || this.defaultAudience(q.level),
    }
  }

  checkedSpec() {
    try { return { spec: normalizeSpec(this.specFromState()), problem: '' } }
    catch (error) { return { spec: null, problem: error.message } }
  }

  /** The title that says what the chart shows (while it follows the numbers), '' when none fits, null before the numbers are a chart. */
  autoTitleText() {
    const { spec } = this.checkedSpec()
    if (!spec) return null
    const label = id => this.measure(id)?.label || KPI_NAMES[id.replace(/\.actual$/, '')] || ''
    let name = numbersName(this.S.q.measures.map(label))
    if (!name) {
      const groups = new Set(this.S.q.measures.map(id => this.measure(id)?.group))
      name = groups.size === 1 ? this.S.catalog?.groups?.find(g => g.id === [...groups][0])?.label || '' : ''
    }
    return name ? chartTitle(spec, name) : ''
  }

  // ---- undo and redo (inside the dialog) ----
  snapshot() {
    const S = this.S
    return JSON.stringify({ source: S.source, tableMode: S.tableMode, tableText: S.tableText, q: S.q, option: S.option, height: S.height, autoTitle: S.autoTitle, moreNumbers: S.moreNumbers })
  }

  /** Remembers the chart as it is now (once per change; typing is remembered when it pauses). */
  remember(now = false) {
    clearTimeout(this.timers.history)
    const save = () => {
      const snap = this.snapshot()
      if (this.history[this.at] === snap) return
      this.history = this.history.slice(0, this.at + 1)
      this.history.push(snap)
      if (this.history.length > 200) this.history.shift()
      this.at = this.history.length - 1
      this.renderHistory()
    }
    if (now) save()
    else this.timers.history = setTimeout(save, 500)
  }

  undo(step) {
    clearTimeout(this.timers.history)
    // Typing not yet remembered is remembered first, so Undo takes it back.
    if (this.history[this.at] !== this.snapshot()) this.remember(true)
    const to = this.at + step
    if (to < 0 || to >= this.history.length) return
    this.at = to
    const snap = JSON.parse(this.history[to])
    const specBefore = this.S.source === 'mission' ? canonicalJson(this.checkedSpec().spec || {}) : ''
    Object.assign(this.S, snap)
    this.S.optionText = JSON.stringify(this.S.option, null, 2)
    this.S.jsonProblems = checkOption(this.S.option)
    this.syncJson(true)
    this.renderAll()
    this.renderHistory()
    const specNow = this.S.source === 'mission' ? canonicalJson(this.checkedSpec().spec || {}) : ''
    if (specNow !== specBefore) this.scheduleData()
    else this.scheduleDraw()
  }

  renderHistory() {
    if (!this.dialog) return
    this.$('#cbUndo').disabled = this.at <= 0 && this.history[this.at] === this.snapshot()
    this.$('#cbRedo').disabled = this.at >= this.history.length - 1
  }

  // ---- building the dialog ----
  build() {
    const d = document.createElement('dialog')
    d.className = 'cb'
    d.setAttribute('aria-labelledby', 'cbTitle')
    d.innerHTML = `
      <header class="cb-head"><div class="grow"><h2 id="cbTitle"></h2><p id="cbWhere"></p></div>
        <div class="cb-history"><button type="button" class="cb-icon" id="cbUndo" data-act="undo" title="Undo (Ctrl+Z)" aria-label="Undo">↶</button><button type="button" class="cb-icon" id="cbRedo" data-act="redo" title="Redo (Ctrl+Y)" aria-label="Redo">↷</button></div>
        <button type="button" class="btn" data-act="close">Close</button></header>
      <div class="cb-body">
        <section class="cb-preview" aria-label="Preview">
          <div class="cb-stagebox" id="cbStagebox"><div class="cb-stage" id="cbStage"><div class="cb-chart" id="cbChart"></div></div><div class="cb-msg" id="cbMsg" hidden></div></div>
          <p class="cb-status" id="cbStatus" role="status" aria-live="polite"></p>
          <p class="cb-privacy" id="cbPrivacy">${PRIVACY}</p>
        </section>
        <section class="cb-side">
          <nav class="cb-tabs" role="tablist" aria-label="Chart settings">${TABS.map(([id, label]) => `<button type="button" role="tab" id="cbTab-${id}" aria-controls="cbPanel-${id}" data-tab="${id}">${label}</button>`).join('')}</nav>
          <div class="cb-panels" id="cbPanels">${TABS.map(([id]) => `<div role="tabpanel" id="cbPanel-${id}" aria-labelledby="cbTab-${id}" data-panel="${id}"></div>`).join('')}</div>
        </section>
      </div>
      <footer class="cb-foot"><span class="grow" id="cbFootNote" role="status"></span><select class="cb-where" id="cbWhereSelect" aria-label="Where the chart goes"></select><button type="button" class="btn primary" id="cbSave"></button></footer>`
    document.body.appendChild(d)
    this.dialog = d
    this.$ = sel => d.querySelector(sel)
    d.addEventListener('close', () => this.destroy())
    d.addEventListener('cancel', (e) => { e.preventDefault(); this.close() })
    d.addEventListener('click', e => this.onClick(e))
    d.addEventListener('input', e => this.onInput(e))
    d.addEventListener('change', e => this.onChange(e))
    d.addEventListener('keydown', e => this.onKey(e))
    // A section skipped while someone typed in it is drawn when they leave it.
    d.addEventListener('focusout', () => setTimeout(() => { for (const id of Object.keys(this.pending || {})) this.render(id) }, 0))
    d.addEventListener('toggle', (e) => { if (e.target.matches?.('details[data-group]')) (this.openGroups ||= new Set())[e.target.open ? 'add' : 'delete'](e.target.dataset.group) }, true)
    this.$('#cbSave').addEventListener('click', () => this.save())
    this.$('#cbWhereSelect').addEventListener('change', (e) => { this.S.where = e.target.value; this.renderFrame() })
    this.resize = new ResizeObserver(() => this.fitStage())
    this.resize.observe(this.$('.cb-preview'))
  }

  destroy() {
    for (const t of Object.values(this.timers)) clearTimeout(t)
    this.resize?.disconnect()
    try { this.chart?.dispose() } catch {}
    try { this.monacoModel?.dispose(); this.monaco?.dispose() } catch {}
    this.dialog?.remove()
    if (current === this) current = null
    this.o.onClose?.()
  }

  /** Close (the button at the top, or Esc): a chart with changes asks once, so no work is lost by a stray tap. */
  close() {
    const S = this.S
    if (S.saving) return
    const changed = this.history.length > 1 && this.history[0] !== this.snapshot()
    if (changed && !S.closing) {
      S.closing = true
      this.foot(`This chart is not saved yet. Choose Close again to close without saving, or ${this.saveText()} to keep it.`, true)
      if (S.editing) this.foot('Your changes are not saved yet. Choose Close again to close without saving, or Update chart to keep them.', true)
      return
    }
    this.dialog.close()
  }

  foot(text, error = false) {
    const el = this.$('#cbFootNote')
    el.textContent = text
    el.className = `grow${error ? ' error' : ''}`
  }

  renderAll() {
    const S = this.S
    this.$('#cbTitle').textContent = this.headingText()
    this.$('#cbSave').textContent = this.saveText()
    for (const [id] of TABS) this.render(id)
    this.renderFrame()
  }

  /** The dialog's heading and main button (the whiteboard has its own words). */
  headingText() {
    if (this.S.editing) return 'Edit chart'
    return this.target?.number ? 'Add a key number' : 'Add a chart'
  }

  saveText() {
    if (this.S.editing) return 'Update chart'
    return this.target ? 'Add to the whiteboard' : 'Insert chart'
  }

  whereText() {
    const S = this.S
    if (this.target) return S.editing ? `Editing ${chartName(this.titleText())} on the whiteboard.` : 'It goes on the whiteboard, where you can move it and change its size.'
    if (S.editing) return `Editing ${chartName(this.titleText(), S.editing.index, S.editing.count)} on slide ${S.editing.no}.${S.notes.length ? ` ${S.notes.join(' ')}` : ''}`
    return S.where === 'newSlide' ? `The chart goes on a new slide after slide ${S.slideNo}.` : `The chart goes on slide ${S.slideNo}.`
  }

  titleText() {
    const t = this.S.option?.title
    return String((Array.isArray(t) ? t[0]?.text : t?.text) ?? '').trim()
  }

  renderFrame() {
    const S = this.S
    this.$('#cbWhere').textContent = this.whereText()
    const where = this.$('#cbWhereSelect')
    where.hidden = !!S.editing || !!this.target
    const options = [['slide', `On slide ${S.slideNo}`], ['newSlide', 'On a new slide after it']]
    const html = options.map(([v, l]) => `<option value="${v}" ${S.where === v ? 'selected' : ''}>${h(l)}</option>`).join('')
    if (where.innerHTML !== html) where.innerHTML = html
    this.$('#cbPrivacy').hidden = S.source !== 'mission'
    this.renderHistory()
  }

  showTab(tab) {
    this.S.tab = tab
    for (const b of this.dialog.querySelectorAll('[data-tab]')) {
      const on = b.dataset.tab === tab
      b.setAttribute('aria-selected', on ? 'true' : 'false')
      b.tabIndex = on ? 0 : -1
    }
    for (const p of this.dialog.querySelectorAll('[data-panel]')) p.hidden = p.dataset.panel !== tab
    if (tab === 'json') this.ensureMonaco()
    this.$('#cbPanels').scrollTop = 0
  }

  /**
   * Draws a tab again, only where it changed. A section being typed in is
   * left alone until the typing moves elsewhere (nothing typed is lost or
   * jumps); buttons and lists keep their focus.
   */
  render(id) {
    const panel = this.$(`[data-panel="${id}"]`)
    if (!panel) return
    if (id === 'json') { this.renderJson(panel); return }
    const html = this[`${id}Panel`]()
    if (panel._html === html) { if (this.pending) delete this.pending[id]; return }
    const active = document.activeElement
    if (panel.contains(active) && (typing(active) || active.type === 'color')) {
      (this.pending ||= {})[id] = true
      return
    }
    if (this.pending) delete this.pending[id]
    const focusKey = panel.contains(active) ? active.dataset.key || active.dataset.set || active.dataset.path : null
    const scroll = this.$('#cbPanels').scrollTop
    panel.innerHTML = html
    panel._html = html
    if (focusKey) panel.querySelector(`[data-key="${CSS.escape(focusKey)}"],[data-set="${CSS.escape(focusKey)}"],[data-path="${CSS.escape(focusKey)}"]`)?.focus({ preventScroll: true })
    this.$('#cbPanels').scrollTop = scroll
  }

  // ---- small controls ----
  chip(key, label, pressed, extra = '') {
    return `<button type="button" class="cb-chip" data-key="${h(key)}" aria-pressed="${pressed ? 'true' : 'false'}" ${extra}>${h(label)}</button>`
  }

  /** A chip that sets an option path to a value (null removes it). */
  setChip(path, value, label) {
    return `<button type="button" class="cb-chip" data-set="${h(path)}" data-val="${j(value)}" aria-pressed="${same(this.get(path) ?? null, value) ? 'true' : 'false'}">${h(label)}</button>`
  }

  field(key, label, value, type = 'text', attrs = '') {
    return `<label class="cb-field">${h(label)}<input type="${type}" data-key="${h(key)}" value="${h(value ?? '')}" ${type === 'number' ? 'inputmode="decimal"' : ''} ${attrs}></label>`
  }

  /** A text or number box bound to an option path (empty removes the setting). */
  input(path, label, type = 'text', attrs = '') {
    const value = this.get(path)
    return `<label class="cb-field">${h(label)}<input type="${type}" data-path="${h(path)}" value="${h(value ?? '')}" ${type === 'number' ? 'inputmode="decimal"' : ''} ${attrs}></label>`
  }

  /** A check box bound to an option path: ticked writes `on`, unticked `off` (null removes). */
  toggle(path, label, on = true, off = null) {
    const now = this.get(path)
    const checked = on === true ? now === true || (off === false && now === undefined) : same(now, on)
    return `<label class="cb-check"><input type="checkbox" data-path="${h(path)}" data-on="${j(on)}" data-off="${j(off)}" ${checked ? 'checked' : ''}> ${h(label)}</label>`
  }

  /** A list bound to an option path; values are JSON (null removes). */
  choose(path, label, choices) {
    const now = this.get(path) ?? null
    return `<label class="cb-field">${h(label)}<select data-path="${h(path)}">${choices.map(([v, l]) => `<option value="${j(v)}" ${same(now, v) ? 'selected' : ''}>${h(l)}</option>`).join('')}</select></label>`
  }

  select(key, label, value, options) {
    return `<label class="cb-field">${h(label)}<select data-key="${h(key)}">${options.map(([v, l]) => `<option value="${h(v)}" ${String(value) === String(v) ? 'selected' : ''}>${h(l)}</option>`).join('')}</select></label>`
  }

  check(key, label, on) {
    return `<label class="cb-check"><input type="checkbox" data-key="${h(key)}" ${on ? 'checked' : ''}> ${h(label)}</label>`
  }

  group(id, title, body, note = '') {
    const open = this.openGroups?.has(id) ? 'open' : ''
    return `<details class="cb-group" data-group="${id}" ${open}><summary>${h(title)}${note ? `<span class="note">${h(note)}</span>` : ''}</summary><div>${body}</div></details>`
  }

  // ---- the option: reading and changing settings ----
  /** A setting of the option; "series.*" means the first series (they are set together). */
  get(path) {
    return getPath(this.S.option, path.replace('series.*', 'series.0'))
  }

  /** Changes a setting ("series.*": every series written in the option) and draws again. */
  set(path, value) {
    let option = this.S.option
    if (path.startsWith('series.*')) {
      const count = Math.max(1, (Array.isArray(option.series) ? option.series : [option.series ?? {}]).length)
      for (let i = 0; i < count; i++) option = setPath(option, path.replace('series.*', `series.${i}`), value)
    }
    else option = setPath(option, path, value)
    this.setOption(option)
  }

  /** The option changed (from the form): the JSON pane follows, the preview draws, and Undo can take it back. */
  setOption(option, fromJson = false) {
    const S = this.S
    S.option = option
    S.closing = false
    if (!fromJson) {
      S.optionText = JSON.stringify(option, null, 2)
      S.jsonProblems = checkOption(option)
      this.syncJson(false)
    }
    this.render('type')
    this.render('settings')
    if (!fromJson) this.renderJsonProblems()
    this.renderFrame()
    this.scheduleDraw()
    this.remember()
  }

  kind() { return kindOf(this.S.option) }
  onAxes() { return AXIS_KINDS.has(this.kind()) }
  horizontal() { return this.kind() === 'sideways' }

  // ---- tab 1: numbers ----
  dataPanel() {
    const S = this.S
    let out = `<h3 class="cb-question" id="cbQuestion">What would you like to show?</h3>
      <div class="cb-chips" role="group" aria-labelledby="cbQuestion">${this.chip('source:mission', 'Mission numbers', S.source === 'mission')}${this.chip('source:paste', 'Paste a table', S.source === 'table' && S.tableMode === 'paste')}${this.chip('source:grid', 'Type the numbers', S.source === 'table' && S.tableMode === 'grid')}</div>`
    if (S.source === 'data') return `${out}<p class="hint">This chart's numbers are written as <code>data</code> in the slide; the builder keeps them. Choose another source to replace them.</p>`
    if (S.source === 'table') return out + (S.tableMode === 'grid' ? this.gridEditor() : this.pasteEditor())
    return out + this.missionNumbers()
  }

  pasteEditor() {
    const S = this.S
    const rows = tableRows(S.tableText)
    const table = rows ? parseRows(rows) : null
    let out = `<p class="hint">Copy the cells from a spreadsheet and paste them here, or type one row per line with commas: the first row holds the headings, the first column the labels.</p>
      <textarea data-key="tableText" aria-label="Your numbers" spellcheck="false">${h(S.tableText)}</textarea>`
    if (table?.problem) out += `<p class="cb-problem">${h(table.problem)}</p>`
    else if (table) {
      const shown = table.labels.slice(0, 6)
      out += `<table class="cb-table"><thead><tr><th></th>${table.series.map(s => `<th>${h(s.name)}</th>`).join('')}</tr></thead><tbody>${shown.map((label, i) => `<tr><th>${h(label)}</th>${table.series.map(s => `<td>${h(s.values[i] ?? '–')}</td>`).join('')}</tr>`).join('')}</tbody></table>${table.labels.length > 6 ? `<p class="hint">…and ${table.labels.length - 6} more rows.</p>` : ''}`
    }
    else out += `<p class="cb-problem">${NO_TABLE}</p>`
    // On the whiteboard: a table the chart frame could not draw is said here, before "Add to the whiteboard".
    const board = table && !table.problem && this.target?.check ? this.boardProblem() : ''
    if (board) out += `<p class="cb-problem">${h(board)}</p>`
    return out
  }

  /** The table as cells (headings first) for the typed grid. */
  cells() {
    // A row of empty boxes (just added) is kept: its tabs mark the columns.
    const rows = String(this.S.tableText ?? '').replace(/\r\n?/g, '\n').split('\n').filter(l => l.trim() || l.includes('\t'))
    const split = rows.map(r => (r.includes('\t') ? r.split('\t') : r.split(/\s*[,;]\s*/)).map(c => c.trim()))
    const width = Math.max(2, ...split.map(r => r.length))
    const out = split.length ? split : [['Label', 'Value']]
    return out.map(r => [...r, ...Array(width - r.length).fill('')])
  }

  gridEditor() {
    const cells = this.cells()
    return `<p class="hint">The first row holds the headings, the first column the labels. Tab moves to the next box.</p>
      <div class="cb-grid"><table><tbody>${cells.map((r, i) => `<tr>${r.map((c, k) => `<td><input type="text" data-cell="${i}:${k}" data-key="cell:${i}:${k}" value="${h(c)}" aria-label="${i ? `Row ${i}` : 'Heading'}, column ${k + 1}" ${i && k ? 'inputmode="decimal"' : ''}></td>`).join('')}</tr>`).join('')}</tbody></table></div>
      <div class="cb-chips" style="margin-top:8px">${this.chip('grid:addRow', 'Add a row', false)}${this.chip('grid:addColumn', 'Add a column', false)}${cells.length > 2 ? this.chip('grid:removeRow', 'Remove the last row', false) : ''}${cells[0].length > 2 ? this.chip('grid:removeColumn', 'Remove the last column', false) : ''}</div>`
  }

  missionNumbers() {
    const S = this.S, q = S.q
    let out = ''
    if (S.catalogError) out += `<p class="cb-problem">${h(S.catalogError)}</p><button type="button" class="btn" data-act="catalog">Try again</button>`
    const kpi = q.measures.length === 1 ? q.measures[0].replace(/\.actual$/, '') : ''
    out += `<h3>Which key indicator?</h3><div class="cb-chips">${KEY_INDICATORS.map(id => this.chip(`kpi:${id}`, this.measure(`${id}.actual`)?.label || KPI_NAMES[id], kpi === id && !S.moreNumbers)).join('')}</div>`
    out += `<button type="button" class="cb-link" data-key="moreNumbers" aria-expanded="${S.moreNumbers ? 'true' : 'false'}">${S.moreNumbers ? 'Only the key indicators' : 'Other numbers (lessons, plans, new members …)'}</button>`
    if (S.moreNumbers) {
      if (!S.catalog) out += '<p class="hint">Loading the list of mission numbers…</p>'
      else {
        for (const g of S.catalog.groups || []) {
          const items = S.catalog.measures.filter(m => m.group === g.id && m.kind !== 'goal')
          if (!items.length) continue
          const chosen = items.filter(m => q.measures.includes(m.id)).length
          out += `<details class="cb-group" ${chosen ? 'open' : ''}><summary>${h(g.label)}${chosen ? `<span class="note">${chosen} chosen</span>` : ''}</summary><div>${items.map(m => `<label class="cb-check"><input type="checkbox" data-key="measure:${h(m.id)}" ${q.measures.includes(m.id) ? 'checked' : ''}> ${h(m.label)}</label>`).join('')}</div></details>`
        }
      }
    }
    const kinds = this.goalKinds()
    if (kinds.length) {
      const shown = kinds.includes(q.compare) ? q.compare : 'none'
      out += `<h3>Compare with</h3><div class="cb-chips">${[...kinds, 'none'].map(id => this.chip(`compare:${id}`, COMPARE_NAMES[id], shown === id)).join('')}</div>`
      if (kinds.includes('previous_goal')) out += '<p class="hint">Call-ins measure each week against the goal set the week before.</p>'
    }
    const offered = this.offeredLevels()
    out += `<h3>For</h3><div class="cb-chips">${[['mission', 'The mission'], ['zone', 'Each zone'], ['district', 'Each district'], ['area', 'Each area']].filter(([id]) => offered.includes(id)).map(([id, label]) => this.chip(`level:${id}`, label, q.level === id)).join('')}</div>`
    if (q.level !== 'mission' && S.catalog) out += this.unitPicker()
    if (q.level !== 'mission') {
      out += `<h3>Show</h3><div class="cb-chips">${this.chip('by:week', 'Week by week', q.by === 'week')}${this.chip('by:unit', `One bar per ${q.level}, weeks added up`, q.by === 'unit')}</div>`
      if (q.by === 'unit') {
        const counts = [0, 3, 5, 10, 20]
        if (!counts.includes(q.top)) counts.push(q.top)
        out += `<div class="cb-row" style="margin-top:10px">${this.select('spec:sort', 'Order', q.sort, [['desc', 'Highest first'], ['asc', 'Lowest first'], ['none', 'By name']])}${this.select('spec:top', 'How many', q.top, counts.sort((a, b) => a - b).map(n => [n, n ? `The first ${n}` : `All ${LEVEL_PLURAL[q.level]}`]))}</div>`
      }
    }
    const transforms = Object.keys(TRANSFORM_NAMES).filter(t => !(q.by === 'unit' && q.level !== 'mission' && ['cumulative', 'rolling4'].includes(t)))
    out += `<h3>As</h3><div class="cb-chips">${transforms.map(t => this.chip(`transform:${t}`, TRANSFORM_NAMES[t], q.transform === t)).join('')}</div>`
    if (q.transform === 'pct_of_goal') out += '<p class="hint">Only weeks that had a goal are counted.</p>'
    out += `<h3>Weeks</h3><div class="cb-chips">${WEEK_CHOICES.map(n => this.chip(`weeks:${n}`, n === 1 ? 'This week' : `Last ${n} weeks`, q.weeks === n)).join('')}</div>
      <div class="cb-row" style="margin-top:8px">${this.field('weeksNumber', `Or a number of weeks (1–${MAX_WEEKS})`, q.weeks, 'number', `min="1" max="${MAX_WEEKS}"`)}</div>
      ${this.check('includeCurrent', 'Include the current week (its plans may still change)', q.includeCurrent)}`
    // Round 6: every DL, ZL and STL sees only their own stewardship, in every chart (portal-api charts.py). The old
    // choice "everyone sees the same numbers" is retired; charts keep their audience setting only so that the ones
    // already in decks keep their pinned hash.
    // Round 7: DLs have no Presentations; a ZL or STL sees only their own zone.
    // Round 8: in a zone's presentation everyone, managers too, sees only that zone (portal-api charts.deck_units).
    out += `<h3>Who sees what</h3><p class="hint">Mission leaders see the whole mission. Each ZL and STL sees only their own zone: a chart of the whole mission shows them their own zone instead.</p><p class="hint" data-i18n="charts.zone.zoneDeckNumbers">${ZONE_DECK_NUMBERS}</p>`
    return out
  }

  unitPicker() {
    const S = this.S, q = S.q, c = S.catalog
    const zones = c.zones || [], districts = c.districts || [], areas = c.areas || []
    // A ZL or STL has one zone (their own): nothing to choose among zones (round 7).
    if (this.zoneOnly() && q.level === 'zone') return ''
    let out = `<h3>Which ${LEVEL_PLURAL[q.level]}</h3>`
    if (!this.zoneOnly()) out += `<p class="hint">${q.level === 'zone' ? 'None chosen means every zone.' : 'Choose zones to narrow the list, or leave them all off for the whole mission.'}</p><div class="cb-chips">${zones.map(z => this.chip(`zone:${z.id}`, z.name, q.filter.zones.includes(z.id))).join('')}</div>`
    if (q.level === 'district' || q.level === 'area') {
      const shown = districts.filter(d => !q.filter.zones.length || q.filter.zones.includes(d.zone_id))
      out += `<details class="cb-group" style="margin-top:8px" ${q.filter.districts.length ? 'open' : ''}><summary>Districts<span class="note">${q.filter.districts.length ? `${q.filter.districts.length} chosen` : 'all'}</span></summary><div>${shown.map(d => `<label class="cb-check"><input type="checkbox" data-key="district:${d.id}" ${q.filter.districts.includes(d.id) ? 'checked' : ''}> ${h(d.name)}</label>`).join('')}</div></details>`
      if (q.level === 'area') {
        const list = areas.filter(a => (!q.filter.districts.length || q.filter.districts.includes(a.district_id)) && (!q.filter.zones.length || q.filter.zones.includes(a.zone_id)))
        out += `<details class="cb-group" ${q.filter.areas.length ? 'open' : ''}><summary>Areas<span class="note">${q.filter.areas.length ? `${q.filter.areas.length} chosen` : `all ${list.length}`}</span></summary><div>${list.map(a => `<label class="cb-check"><input type="checkbox" data-key="area:${a.id}" ${q.filter.areas.includes(a.id) ? 'checked' : ''}> ${h(a.name)}</label>`).join('')}</div></details>`
      }
    }
    return out
  }

  // ---- tab 2: chart type ----
  typePanel() {
    const kind = this.kind()
    const groups = [...new Set(CHART_KINDS.map(k => k.group))]
    const hint = KIND_HINTS[kind]
    return `<div class="cb-kinds">${groups.map(g => `<h4>${h(g)}</h4><div class="cb-types">${CHART_KINDS.filter(k => k.group === g).map(k => `<button type="button" class="cb-type" data-key="kind:${k.id}" aria-pressed="${kind === k.id ? 'true' : 'false'}"><svg viewBox="0 0 24 24" aria-hidden="true">${ICONS[k.id] || ICONS.bar}</svg>${h(k.label)}</button>`).join('')}</div>`).join('')}</div>
      ${hint ? `<p class="hint" style="margin-top:12px">${h(hint)}</p>` : ''}
      <p class="hint">Changing the type keeps the title, colours, legend and tools. Every setting of every type is under All options.</p>`
  }

  // ---- tab 3: settings ----
  /** The names of the series the preview draws (the table's columns). */
  columnNames() {
    return (this.view().table?.series || []).map(s => s.name)
  }

  settingsPanel() {
    const S = this.S
    const axes = this.onAxes()
    const kind = this.kind()
    const names = this.columnNames()
    const palette = PALETTE[this.dark() ? 'dark' : 'light']
    const colors = Array.isArray(S.option.color) ? S.option.color : null
    const vAxis = this.horizontal() ? 'xAxis' : 'yAxis', cAxis = this.horizontal() ? 'yAxis' : 'xAxis'
    let out = ''
    out += this.group('title', 'Title', `${this.input('title.text', 'Title')}${this.input('title.subtext', 'A line under the title')}`, this.titleText() ? '' : 'none')
    // Series: how each column is drawn.
    let series = ''
    if (axes && kind !== 'multiples') {
      const list = Array.isArray(S.option.series) ? S.option.series : [S.option.series ?? {}]
      series += '<p class="hint">Each column of the numbers is one series. Choose how each is drawn; the last choice is used for the columns after it.</p>'
      series += names.slice(0, 12).map((name, i) => {
        const s = list[Math.min(i, list.length - 1)] ?? {}
        const now = s.type === 'line' ? (s.areaStyle ? 'area' : 'line') : s.type === 'scatter' ? 'scatter' : s.type === 'pictorialBar' ? 'pictorialBar' : 'bar'
        return this.select(`drawn:${i}`, name, now, [['bar', 'Bars'], ['line', 'Line'], ['area', 'Area'], ['scatter', 'Dots'], ['pictorialBar', 'Picture bars']])
      }).join('')
      series += this.toggle('series.*.smooth', 'Smooth lines')
      series += this.toggle('series.*.stack', 'Stack the series on each other', 'total')
      series += this.toggle('series.*.showSymbol', 'Dots on the lines', true, false)
      series += this.toggle('series.*.step', 'Steps instead of slopes', 'middle')
      series += `<div class="cb-row">${this.input('series.*.lineStyle.width', 'Line width', 'number', 'min="0.5" max="12" step="0.5"')}${this.input('series.*.barMaxWidth', 'Widest bar (pixels)', 'number', 'min="4" max="200"')}</div>`
      series += this.toggle('series.*.showBackground', 'A pale track behind each bar')
      series += this.toggle('series.*.realtimeSort', 'Sort bars by size as they change')
    }
    else if (['pie', 'donut', 'rose'].includes(kind)) {
      series += this.choose('series.0.roseType', 'Slices', [[null, 'By share (pie)'], ['radius', 'Longer for bigger numbers (rose)'], ['area', 'Rose by area']])
      series += `<div class="cb-row">${this.input('series.0.startAngle', 'Start angle', 'number', 'min="-360" max="360"')}${this.input('series.0.padAngle', 'Gap between slices', 'number', 'min="0" max="10"')}</div>`
      series += this.toggle('series.0.clockwise', 'Clockwise', true, false)
    }
    else if (kind === 'funnel') series += this.choose('series.0.sort', 'Order', [[null, 'As in the table'], ['descending', 'Largest first'], ['ascending', 'Smallest first']])
    else if (kind === 'gauge') series += `<div class="cb-row">${this.input('series.0.min', 'Lowest', 'number')}${this.input('series.0.max', 'Highest (empty: the goal column)', 'number')}</div>`
    else if (kind === 'graph') series += this.choose('series.0.layout', 'Layout', [[null, 'Spread out (force)'], ['circular', 'In a circle'], ['none', 'As written']]) + this.toggle('series.0.roam', 'Drag and zoom', true, false)
    else if (kind === 'tree') series += this.choose('series.0.layout', 'Layout', [[null, 'Left to right'], ['radial', 'Round']]) + this.choose('series.0.orient', 'Direction', [[null, 'Left to right'], ['TB', 'Top to bottom'], ['RL', 'Right to left'], ['BT', 'Bottom to top']])
    else if (kind === 'sankey') series += this.choose('series.0.orient', 'Direction', [[null, 'Left to right'], ['vertical', 'Top to bottom']]) + this.choose('series.0.nodeAlign', 'Line up the ends', [[null, 'Spread (justify)'], ['left', 'Left'], ['right', 'Right']])
    else if (kind === 'radar') series += this.choose('radar.shape', 'Shape', [[null, 'Corners'], ['circle', 'Round']])
    else if (kind === 'treemap' || kind === 'sunburst') series += this.toggle('series.0.nodeClick', 'Click a part to zoom into it', 'zoomToNode', false)
    else if (kind === 'timeline') series += `${this.toggle('timeline.autoPlay', 'Play on its own when the slide is shown')}${this.toggle('timeline.loop', 'Start again at the end', true, false)}${this.input('timeline.playInterval', 'Time per step (milliseconds)', 'number', 'min="200" max="10000" step="100"')}`
    if (series) out += this.group('series', 'Series', series)
    if (axes) {
      out += this.group('axes', 'Axes', `
        <div class="cb-row">${this.input(`${cAxis}.name`, 'Title under the chart')}${this.input(`${vAxis}.name`, 'Title beside the numbers')}</div>
        <div class="cb-row">${this.input(`${vAxis}.min`, 'Lowest number', 'number')}${this.input(`${vAxis}.max`, 'Highest number', 'number')}</div>
        <div class="cb-row">${this.input(`${cAxis}.axisLabel.rotate`, 'Turn the labels (degrees)', 'number', 'min="-90" max="90"')}${this.input(`${vAxis}.splitNumber`, 'About how many lines', 'number', 'min="1" max="20"')}</div>
        ${this.toggle(`${vAxis}.type`, 'Logarithmic scale (for numbers that grow very fast)', 'log', 'value')}
        ${this.toggle(`${vAxis}.splitLine.show`, 'Grid lines', true, false)}
        ${this.toggle(`${vAxis}.inverse`, 'Upside down')}
        ${this.toggle(`${cAxis}.axisLabel.showMaxLabel`, 'Always show the last label')}`)
    }
    out += this.group('labels', 'Labels', `
      ${this.toggle('series.*.label.show', 'Show the numbers on the chart')}
      <div class="cb-row">${this.choose('series.*.label.position', 'Where', [[null, 'Automatic'], ['top', 'Above'], ['inside', 'Inside'], ['insideBottom', 'At the bottom'], ['right', 'Right'], ['outside', 'Outside (pies)']])}${this.input('series.*.label.fontSize', 'Size', 'number', 'min="8" max="40"')}</div>
      ${this.toggle('series.*.label.valueAnimation', 'Numbers count up when they change')}
      ${axes ? this.toggle('series.*.endLabel.show', 'The series name at the end of each line') : ''}`)
    out += this.group('legend', 'Legend', `<div class="cb-chips">${this.setChip('legend', null, 'Automatic')}${this.setChip('legend', {}, 'Top')}${this.setChip('legend', { bottom: 0, left: 'center' }, 'Bottom')}${this.setChip('legend', { orient: 'vertical', right: 0, top: 'middle' }, 'Right')}${this.setChip('legend', { orient: 'vertical', left: 0, top: 'middle' }, 'Left')}${this.setChip('legend', { show: false }, 'None')}</div>`)
    out += this.group('tooltip', 'Tooltip', `
      ${this.toggle('tooltip.show', 'Show the numbers when pointing at the chart', true, false)}
      ${this.choose('tooltip.trigger', 'For', [[null, 'Automatic'], ['axis', 'Every series at that point'], ['item', 'The one point'], ['none', 'Nothing']])}
      ${this.choose('tooltip.axisPointer.type', 'Pointer', [[null, 'Automatic'], ['line', 'A line'], ['shadow', 'A shaded band'], ['cross', 'Crosshairs'], ['none', 'None']])}
      ${this.choose('tooltip.order', 'Order', [[null, 'As the series'], ['valueDesc', 'Highest first'], ['valueAsc', 'Lowest first']])}`)
    const colorInputs = names.slice(0, 12).map((name, i) => `<label class="cb-color"><input type="color" data-key="color:${i}" value="${h((colors && colors[i]) || palette[i % palette.length])}"> ${h(name)}</label>`).join('')
    out += this.group('colours', 'Colours', `<div class="cb-chips">${Object.keys(PALETTES).map(p => this.chip(`palette:${p}`, { mission: 'Mission colours', warm: 'Warm', cool: 'Cool', calm: 'Calm' }[p], p === 'mission' ? !colors : same(colors, PALETTES[p]))).join('')}</div>
      ${colorInputs ? `<h3>Each series</h3><div class="cb-colors">${colorInputs}</div>` : ''}
      ${this.toggle('aria.decal.show', 'Patterns as well as colours (easier for colour-blind readers)')}`)
    if (axes) {
      const t = this.get('series.*.gfm.trend')
      const method = t ? (t === true ? 'linear' : t.method || 'linear') : 'none'
      let body = `<div class="cb-chips">${TREND_METHODS.map(m => this.chip(`trend:${m}`, TREND_NAMES[m], method === m)).join('')}</div>`
      if (method !== 'none') {
        if (method === 'polynomial') body += this.choose('series.*.gfm.trend.degree', 'How curved', [[null, '2: one bend'], [3, '3'], [4, '4'], [5, '5'], [6, '6: many bends']])
        if (method === 'moving-average') body += this.input('series.*.gfm.trend.window', 'Average over how many points (2–52)', 'number', 'min="2" max="52"')
        body += `<div class="cb-row">${this.input('series.*.gfm.trend.forecast', 'Carry it on for (periods)', 'number', 'min="0" max="52"')}${this.input('series.*.gfm.trend.width', 'Width', 'number', 'min="0.5" max="8" step="0.5"')}</div>
          <div class="cb-row"><label class="cb-field">Colour<input type="color" data-key="trendColor" value="${h(this.get('series.*.gfm.trend.color') || palette[0])}"></label>${this.choose('series.*.gfm.trend.style', 'Line', [[null, 'Dashed'], ['dotted', 'Dotted'], ['solid', 'Solid']])}</div>
          ${this.input('series.*.gfm.trend.label', 'Name in the legend (empty: "Trend")')}
          ${this.get('series.*.gfm.trend.color') ? this.chip('trendColorReset', 'Same colour as the series', false) : ''}`
      }
      out += this.group('trend', 'Trend line', `<p class="hint">A trend line shows the direction over time, worked out from the numbers.</p>${body}`, method === 'none' ? 'off' : TREND_NAMES[method])
      out += this.group('lines', 'Reference lines', this.referenceLines())
      out += this.group('zoom', 'Zoom and tools', this.zoomTools())
    }
    else out += this.group('zoom', 'Tools', this.zoomTools(false))
    out += this.group('visual', 'Colour by value', this.visualMap())
    out += this.group('animation', 'Animation', `
      ${this.toggle('animation', 'Animate when the slide is shown', true, false)}
      <div class="cb-row">${this.input('animationDuration', 'How long (milliseconds)', 'number', 'min="0" max="10000" step="100"')}${this.choose('animationEasing', 'Style', [[null, 'Smooth (default)'], ...EASINGS.map(e => [e, e])])}</div>
      ${this.input('animationDurationUpdate', 'Changes take (milliseconds)', 'number', 'min="0" max="10000" step="100"')}
      ${this.toggle('series.*.universalTransition', 'Morph from one chart type to another', true, false)}`)
    const fmt = this.get('gfm.format') ?? {}
    out += this.group('numbers', 'Numbers', `<div class="cb-row">${this.choose('gfm.format.style', 'Written as', [[null, 'Automatic'], ['plain', 'Whole numbers'], ['percent', 'Percent'], ['compact', 'Short (1.2K)'], ['decimals', 'Fixed decimals']])}${this.input('gfm.format.decimals', 'Decimal places', 'number', 'min="0" max="4"')}</div>
      <div class="cb-row">${this.input('gfm.format.prefix', 'Before each number (e.g. €)')}${this.input('gfm.format.suffix', 'After each number (e.g. people)')}</div>`, fmt.style || '')
    // On the whiteboard the chart's size is its box on the board (pull a corner there).
    if (!this.target) out += this.group('size', 'Size', this.field('height', 'Height in slide pixels (a slide is 980 wide)', S.height, 'number', 'min="120" max="2000" step="10"'))
    return out
  }

  /** The first series' reference lines: a line at a number (the goal), the average, highest and lowest, a shaded band. */
  referenceLines() {
    const axis = this.horizontal() ? 'xAxis' : 'yAxis'
    const data = this.get('series.0.markLine.data') || []
    const target = data.find(d => d && typeof d[axis] === 'number')
    const average = data.some(d => d?.type === 'average')
    const points = this.get('series.0.markPoint.data') || []
    const band = (this.get('series.0.markArea.data') || [])[0]
    const hasGoal = (this.view().table?.series || []).some(s => s.role === 'goal')
    let out = ''
    if (hasGoal) out += `<label class="cb-field">Goal line colour<input type="color" data-key="goalColor" value="${h(this.get('gfm.goal.lineStyle.color') || PALETTE[this.dark() ? 'dark' : 'light'][1])}"></label>`
    out += `<div class="cb-row">${this.field('target', 'A line at this number', target?.[axis], 'number')}${this.field('targetName', 'Its name', target ? target.name ?? '' : 'Goal')}</div>`
    out += this.check('average', 'Average line', average)
    out += this.check('maxmin', 'Mark the highest and lowest', points.some(p => p?.type === 'max'))
    out += `<div class="cb-row">${this.field('bandFrom', 'A shaded band from', band?.[0]?.[axis], 'number')}${this.field('bandTo', 'to', band?.[1]?.[axis], 'number')}${this.field('bandName', 'Its name', band?.[0]?.name ?? '')}</div>`
    return out
  }

  zoomTools(axes = true) {
    const zoom = Array.isArray(this.S.option.dataZoom) ? this.S.option.dataZoom : this.S.option.dataZoom ? [this.S.option.dataZoom] : []
    const feature = this.get('toolbox.feature') || {}
    let out = ''
    if (axes) out += this.check('zoomSlider', 'A zoom slider under the chart', zoom.some(z => z?.type === 'slider')) + this.check('zoomInside', 'Zoom with the mouse wheel or two fingers', zoom.some(z => z?.type === 'inside'))
    out += `<h3>Buttons on the chart</h3>${this.check('tool:saveAsImage', 'Save as a picture', !!feature.saveAsImage)}${this.check('tool:dataView', 'Show the numbers as a table', !!feature.dataView)}${axes ? this.check('tool:magicType', 'Switch between lines and bars', !!feature.magicType) : ''}${this.check('tool:restore', 'Back to the start', !!feature.restore)}`
    if (axes) out += this.check('brush', 'Draw a box to pick out points', this.S.option.brush !== undefined)
    return out
  }

  visualMap() {
    const vm = this.get('visualMap')
    const now = vm === undefined ? 'off' : vm.type === 'piecewise' ? 'steps' : 'smooth'
    const required = ['heatmap', 'calendar'].includes(this.kind())
    const colors = vm?.inRange?.color || []
    const palette = PALETTE[this.dark() ? 'dark' : 'light']
    let out = `<p class="hint">Colours the chart from pale for small numbers to strong for big ones.</p><div class="cb-chips">${required ? '' : this.chip('visual:off', 'Off', now === 'off')}${this.chip('visual:smooth', 'A smooth scale', now === 'smooth')}${this.chip('visual:steps', 'In steps', now === 'steps')}</div>`
    if (now !== 'off') {
      out += `<div class="cb-row"><label class="cb-field">Small numbers<input type="color" data-key="visualLow" value="${h(colors[0] || '#e3f1f3')}"></label><label class="cb-field">Big numbers<input type="color" data-key="visualHigh" value="${h(colors[colors.length - 1] || palette[0])}"></label></div>`
      out += `<div class="cb-row">${this.input('visualMap.min', 'From', 'number')}${this.input('visualMap.max', 'To', 'number')}${now === 'steps' ? this.input('visualMap.splitNumber', 'Steps', 'number', 'min="2" max="10"') : ''}</div>`
      out += this.toggle('visualMap.show', 'Show the colour scale', true, false)
    }
    return out
  }

  // ---- tab 4: all options (JSON) ----
  renderJson(panel) {
    if (!panel.childElementCount) {
      panel.innerHTML = `<p class="hint" style="margin-top:0">The whole chart as an ECharts option. ECharts' names are offered as you type (Ctrl+Space shows them); the numbers come from the Numbers tab (dataset 0), so they are not written here. See echarts.apache.org for every setting.</p>
        <div class="cb-monaco" id="cbMonaco"><textarea data-key="optionText" aria-label="All options (JSON)" spellcheck="false" style="min-height:320px;height:100%;border:0;border-radius:0"></textarea></div>
        <ul class="cb-problems" id="cbProblems"></ul>
        <div class="cb-chips">${this.chip('formatJson', 'Tidy the layout', false)}${this.target ? '' : this.chip('copyTag', 'Copy the slide tag', false)}</div>
        ${this.target ? '' : '<h3>What the slide gets</h3><pre class="cb-code" id="cbTag"></pre>'}`
      this.syncJson(true)
    }
    this.renderJsonProblems()
  }

  renderJsonProblems() {
    const list = this.$('#cbProblems')
    if (!list) return
    const { errors, warnings } = this.S.jsonProblems
    list.innerHTML = [...errors.map(e => `<li class="error">${h(e)}</li>`), ...warnings.slice(0, 6).map(w => `<li class="warn">${h(w)}</li>`)].join('')
    const tag = this.$('#cbTag')
    if (tag) {
      try { tag.textContent = this.tagText() }
      catch (error) { tag.textContent = error.message }
    }
  }

  /** The JSON pane shows the option (not while someone types in it, unless `force`). */
  syncJson(force) {
    const text = this.S.optionText || JSON.stringify(this.S.option, null, 2)
    if (this.monaco) {
      if (!force && this.monaco.hasTextFocus()) return
      if (this.monaco.getValue() !== text) {
        this.applyingJson = true
        this.monacoModel.pushEditOperations([], [{ range: this.monacoModel.getFullModelRange(), text }], () => null)
        this.applyingJson = false
      }
      return
    }
    const area = this.$('[data-key="optionText"]')
    if (area && (force || document.activeElement !== area) && area.value !== text) area.value = text
  }

  /** JSON typed in the All options pane: read, checked, and used when it is a chart. */
  fromJson(text) {
    const S = this.S
    S.optionText = text
    let value
    try { value = JSON.parse(text) }
    catch (error) {
      S.jsonProblems = { errors: [`This is not valid JSON yet (${String(error.message).replace(/^JSON\.parse: /, '')}). Check the quotes, commas and brackets.`], warnings: [] }
      this.renderJsonProblems()
      this.foot('All options has a mistake; the preview shows the last good version.', true)
      return
    }
    S.jsonProblems = checkOption(value)
    this.renderJsonProblems()
    if (S.jsonProblems.errors.length) { this.foot('All options has a mistake; the preview shows the last good version.', true); return }
    this.foot('')
    if (value?.title?.text !== undefined && value.title.text !== this.titleText()) S.autoTitle = false
    this.setOption(value, true)
  }

  async ensureMonaco() {
    if (this.monaco || this.monacoLoading || !this.o.loadMonaco) return
    this.monacoLoading = true
    try {
      const monaco = await this.o.loadMonaco()
      const box = this.$('#cbMonaco')
      if (!this.dialog?.open || !box) return
      const json = monaco.languages?.json?.jsonDefaults ?? monaco.json?.jsonDefaults
      json?.setDiagnosticsOptions({ validate: true, allowComments: false, enableSchemaRequest: false, schemaValidation: 'warning', schemas: [{ uri: 'https://gfm.invalid/schemas/echarts-option.json', fileMatch: ['gfm-chart-option.json'], schema: optionSchema() }] })
      const uri = monaco.Uri.parse('inmemory://gfm/gfm-chart-option.json')
      monaco.editor.getModel(uri)?.dispose()
      const area = this.$('[data-key="optionText"]')
      if (area) this.S.optionText = area.value
      this.monacoModel = monaco.editor.createModel(this.S.optionText, 'json', uri)
      box.innerHTML = ''
      this.monaco = monaco.editor.create(box, {
        model: this.monacoModel, theme: this.dark() ? 'vs-dark' : 'vs', minimap: { enabled: false }, automaticLayout: true, fixedOverflowWidgets: true,
        fontSize: 14, lineHeight: 21, tabSize: 2, scrollBeyondLastLine: false, wordWrap: 'on', padding: { top: 8 },
        quickSuggestions: { strings: true, other: true, comments: false }, suggestOnTriggerCharacters: true, formatOnPaste: true,
      })
      this.monaco.onDidChangeModelContent(() => {
        if (this.applyingJson) return
        clearTimeout(this.timers.json)
        this.timers.json = setTimeout(() => this.fromJson(this.monaco.getValue()), 250)
      })
    }
    catch {
      // The text box stays: the same checks, without the names offered as you type.
    }
    finally { this.monacoLoading = false }
  }

  // ---- events ----
  onKey(e) {
    const tab = e.target.closest?.('[role="tab"]')
    if (tab && (e.key === 'ArrowRight' || e.key === 'ArrowLeft')) {
      const ids = TABS.map(t => t[0])
      const next = ids[(ids.indexOf(tab.dataset.tab) + (e.key === 'ArrowRight' ? 1 : ids.length - 1)) % ids.length]
      this.showTab(next)
      this.$(`#cbTab-${next}`).focus()
      e.preventDefault()
      return
    }
    // Undo and Redo of the dialog; a text box and the JSON editor keep their own.
    const mod = e.ctrlKey || e.metaKey
    if (mod && !typing(e.target) && !e.target.closest?.('.monaco-editor')) {
      const key = e.key.toLowerCase()
      if (key === 'z') { e.preventDefault(); this.undo(e.shiftKey ? 1 : -1) }
      else if (key === 'y') { e.preventDefault(); this.undo(1) }
    }
  }

  onClick(e) {
    const act = e.target.closest('[data-act]')?.dataset.act
    if (act === 'close') { this.close(); return }
    if (act === 'undo' || act === 'redo') { this.undo(act === 'undo' ? -1 : 1); return }
    if (act === 'catalog') { this.S.catalogError = ''; this.render('data'); this.loadCatalog(); return }
    const tab = e.target.closest('[data-tab]')?.dataset.tab
    if (tab) { this.showTab(tab); return }
    const setter = e.target.closest('button[data-set]')
    if (setter) {
      const value = JSON.parse(setter.dataset.val)
      this.set(setter.dataset.set, value === null ? undefined : value)
      return
    }
    const button = e.target.closest('button[data-key]')
    if (!button) return
    const [kind, value] = button.dataset.key.split(/:(.*)/s)
    const S = this.S, q = S.q
    let data = false
    switch (kind) {
      case 'source':
        if (value === 'mission') S.source = 'mission'
        else { S.source = 'table'; S.tableMode = value }
        data = true
        break
      case 'kpi':
        q.measures = [`${value}.actual`]
        S.moreNumbers = false
        if (q.transform === 'pct_of_goal' && q.compare === 'none') q.compare = 'previous_goal'
        data = true
        break
      case 'moreNumbers': S.moreNumbers = !S.moreNumbers; this.render('data'); return
      case 'compare': this.setCompare(value); data = true; break
      case 'level':
        q.level = value
        if (value === 'mission') q.by = 'week'
        q.audience = null
        data = true
        break
      case 'zone': this.flip(q.filter.zones, Number(value)); q.filter.districts = []; q.filter.areas = []; data = true; break
      case 'weeks': q.weeks = Number(value); data = true; break
      case 'by':
        q.by = value
        if (value === 'week') { q.sort = 'none'; q.top = 0 }
        else {
          if (['cumulative', 'rolling4'].includes(q.transform)) q.transform = 'none'
          if (q.sort === 'none') q.sort = 'desc'
        }
        data = true
        break
      case 'transform': q.transform = value; if (value === 'pct_of_goal' && q.compare === 'none') q.compare = q.lastCompare; data = true; break
      case 'audience': q.audience = value; data = true; break
      case 'grid': this.gridAction(value); return
      case 'kind': this.setOption(applyKind(S.option, value)); return
      case 'trend': this.setTrend(value); return
      case 'trendColorReset': this.set('series.*.gfm.trend.color', undefined); return
      case 'palette': this.set('color', PALETTES[value] ? [...PALETTES[value]] : undefined); return
      case 'visual': this.setVisual(value); return
      case 'formatJson':
        try { this.S.optionText = JSON.stringify(JSON.parse(this.monaco ? this.monaco.getValue() : this.S.optionText), null, 2); this.syncJson(true) }
        catch { this.foot('All options has a mistake, so it cannot be tidied yet.', true) }
        return
      case 'copyTag':
        try { navigator.clipboard?.writeText(this.tagText()); this.foot('The slide tag is copied.') }
        catch (error) { this.foot(error.message, true) }
        return
      default: return
    }
    if (data) this.afterData()
  }

  /** After a change to the numbers: the title follows them (until someone types one), the tab, the preview. */
  afterData() {
    const S = this.S
    S.closing = false
    if (S.autoTitle && S.source === 'mission') {
      const title = this.autoTitleText()
      if (title !== null) {
        S.option = title ? setPath(S.option, 'title.text', title) : setPath(S.option, 'title.text', undefined)
        S.optionText = JSON.stringify(S.option, null, 2)
        this.syncJson(false)
      }
    }
    this.render('data')
    this.render('settings')
    this.renderFrame()
    this.scheduleData()
    this.remember()
  }

  setCompare(value) {
    const q = this.S.q
    q.compare = value
    if (value !== 'none') q.lastCompare = value
    if (value === 'none' && q.transform === 'pct_of_goal') q.transform = 'none'
  }

  flip(list, value) {
    const i = list.indexOf(value)
    if (i >= 0) list.splice(i, 1)
    else list.push(value)
  }

  gridAction(action) {
    const cells = this.cells()
    if (action === 'addRow') cells.push(Array(cells[0].length).fill(''))
    if (action === 'addColumn') cells.forEach((r, i) => r.push(i ? '' : `Series ${r.length}`))
    if (action === 'removeRow' && cells.length > 2) cells.pop()
    if (action === 'removeColumn' && cells[0].length > 2) cells.forEach(r => r.pop())
    this.S.tableText = cells.map(r => r.join('\t')).join('\n')
    this.afterData()
    if (action === 'addRow') this.$(`[data-cell="${cells.length - 1}:0"]`)?.focus()
  }

  setTrend(method) {
    if (method === 'none') { this.set('series.*.gfm.trend', undefined); return }
    const now = this.get('series.*.gfm.trend')
    const keep = now && now !== true ? { ...now } : {}
    if (method !== 'polynomial') delete keep.degree
    if (method !== 'moving-average') delete keep.window
    this.set('series.*.gfm.trend', { ...keep, method })
  }

  setVisual(mode) {
    const now = this.get('visualMap') ?? {}
    if (mode === 'off') { this.set('visualMap', undefined); return }
    const colors = now.inRange?.color
    const next = { ...now, type: mode === 'steps' ? 'piecewise' : 'continuous', ...(mode === 'steps' ? { splitNumber: now.splitNumber ?? 5 } : {}) }
    if (mode !== 'steps') delete next.splitNumber
    if (colors) next.inRange = { ...now.inRange, color: colors }
    if (this.onAxes() && next.dimension === undefined) next.dimension = 1
    this.set('visualMap', next)
  }

  onInput(e) {
    const t = e.target
    const S = this.S
    const key = t.dataset?.key
    if (t.dataset?.path && (t.type === 'text' || t.type === 'number')) {
      const raw = t.value
      const value = raw === '' ? undefined : t.type === 'number' ? (Number.isFinite(Number(raw)) ? Number(raw) : undefined) : raw
      if (t.dataset.path === 'title.text') S.autoTitle = false
      this.set(t.dataset.path, value)
      return
    }
    if (!key) return
    if (key === 'tableText') {
      S.tableText = t.value
      clearTimeout(this.timers.table)
      this.timers.table = setTimeout(() => this.afterData(), 300)
      return
    }
    if (key === 'optionText') { clearTimeout(this.timers.json); this.timers.json = setTimeout(() => this.fromJson(t.value), 250); return }
    if (key.startsWith('cell:')) {
      const [, row, col] = key.split(':').map(Number)
      const cells = this.cells()
      cells[row][col] = t.value.replace(/\t/g, ' ')
      S.tableText = cells.map(r => r.join('\t')).join('\n')
      clearTimeout(this.timers.table)
      this.timers.table = setTimeout(() => this.afterData(), 250)
      return
    }
    if (key === 'weeksNumber') {
      const n = Math.round(Number(t.value))
      if (n >= 1 && n <= MAX_WEEKS) { S.q.weeks = n; this.scheduleData(); this.remember() }
      return
    }
    if (key === 'height') {
      const n = Number(t.value)
      if (n >= 120 && n <= 2000) { S.height = n; this.fitStage(); this.scheduleDraw(); this.remember() }
      return
    }
    if (key.startsWith('color:')) {
      const names = this.columnNames()
      const palette = PALETTE[this.dark() ? 'dark' : 'light']
      const colors = names.map((_, i) => (Array.isArray(S.option.color) && S.option.color[i]) || palette[i % palette.length])
      colors[Number(key.slice(6))] = t.value
      this.set('color', colors)
      return
    }
    if (key === 'trendColor') { this.set('series.*.gfm.trend.color', t.value); return }
    if (key === 'goalColor') { this.set('gfm.goal', { ...(this.get('gfm.goal') ?? {}), lineStyle: { color: t.value }, itemStyle: { color: t.value } }); return }
    if (key === 'visualLow' || key === 'visualHigh') {
      const colors = [...(this.get('visualMap.inRange.color') || ['#e3f1f3', PALETTE.light[0]])]
      if (key === 'visualLow') colors[0] = t.value
      else colors[colors.length - 1] = t.value
      this.set('visualMap.inRange.color', colors)
      return
    }
    if (['target', 'targetName'].includes(key)) { this.setTarget(); return }
    if (['bandFrom', 'bandTo', 'bandName'].includes(key)) this.setBand()
  }

  onChange(e) {
    const t = e.target
    const S = this.S, q = S.q
    if (t.dataset?.path && t.type === 'checkbox') {
      const value = JSON.parse(t.checked ? t.dataset.on : t.dataset.off)
      this.set(t.dataset.path, value === null ? undefined : value)
      return
    }
    if (t.dataset?.path && t.tagName === 'SELECT') {
      const value = JSON.parse(t.value)
      this.set(t.dataset.path, value === null ? undefined : value)
      return
    }
    const key = t.dataset?.key
    if (!key) return
    const [kind, value] = key.split(/:(.*)/s)
    if (t.type === 'checkbox') {
      if (kind === 'measure') { this.flip(q.measures, value); this.afterData(); return }
      if (kind === 'district') { this.flip(q.filter.districts, Number(value)); q.filter.areas = []; this.afterData(); return }
      if (kind === 'area') { this.flip(q.filter.areas, Number(value)); this.afterData(); return }
      if (key === 'includeCurrent') { q.includeCurrent = t.checked; this.afterData(); return }
      if (key === 'average') { this.setAverage(t.checked); return }
      if (key === 'maxmin') { this.set('series.0.markPoint', t.checked ? { data: [{ type: 'max' }, { type: 'min' }] } : undefined); return }
      if (key === 'zoomSlider' || key === 'zoomInside') { this.setZoom(key === 'zoomSlider' ? 'slider' : 'inside', t.checked); return }
      if (kind === 'tool') { this.setTool(value, t.checked); return }
      if (key === 'brush') { this.setBrush(t.checked) }
      return
    }
    if (t.tagName === 'SELECT') {
      if (kind === 'spec') { q[value] = value === 'top' ? Number(t.value) : t.value; this.afterData(); return }
      if (kind === 'drawn') this.setDrawn(Number(value), t.value)
      return
    }
    if (key === 'weeksNumber') this.render('data')
  }

  /** How column `i` is drawn: series are written out up to it (the last one repeats for the columns after). */
  setDrawn(i, as) {
    const option = JSON.parse(JSON.stringify(this.S.option))
    const list = Array.isArray(option.series) ? option.series : [option.series ?? { type: 'bar' }]
    while (list.length <= i) {
      const copy = JSON.parse(JSON.stringify(list[list.length - 1]))
      delete copy.name
      delete copy.markLine
      delete copy.markPoint
      delete copy.markArea
      list.push(copy)
    }
    const s = list[i]
    s.type = as === 'area' ? 'line' : as
    if (as === 'area') s.areaStyle = s.areaStyle ?? {}
    else delete s.areaStyle
    if (s.type !== 'line') { delete s.smooth; delete s.step; delete s.showSymbol }
    option.series = list
    this.setOption(option)
  }

  setTarget() {
    const axis = this.horizontal() ? 'xAxis' : 'yAxis'
    const value = this.$('[data-key="target"]').value
    const name = this.$('[data-key="targetName"]').value
    const data = (this.get('series.0.markLine.data') || []).filter(d => !(d && typeof d[axis] === 'number'))
    if (value !== '' && Number.isFinite(Number(value))) data.unshift({ [axis]: Number(value), name: name || 'Goal', lineStyle: { type: 'solid' } })
    this.set('series.0.markLine', data.length ? { ...(this.get('series.0.markLine') || {}), data } : undefined)
  }

  setAverage(on) {
    const data = (this.get('series.0.markLine.data') || []).filter(d => d?.type !== 'average')
    if (on) data.push({ type: 'average' })
    this.set('series.0.markLine', data.length ? { ...(this.get('series.0.markLine') || {}), data } : undefined)
  }

  setBand() {
    const axis = this.horizontal() ? 'xAxis' : 'yAxis'
    const from = this.$('[data-key="bandFrom"]').value, to = this.$('[data-key="bandTo"]').value
    const name = this.$('[data-key="bandName"]').value
    const ok = v => v !== '' && Number.isFinite(Number(v))
    this.set('series.0.markArea', ok(from) && ok(to) ? { data: [[{ [axis]: Number(from), ...(name ? { name } : {}) }, { [axis]: Number(to) }]] } : undefined)
  }

  setZoom(type, on) {
    const list = (Array.isArray(this.S.option.dataZoom) ? this.S.option.dataZoom : this.S.option.dataZoom ? [this.S.option.dataZoom] : []).filter(z => z?.type !== type)
    if (on) list.push(this.horizontal() ? { type, yAxisIndex: 0 } : { type })
    this.set('dataZoom', list.length ? list : undefined)
  }

  setTool(name, on) {
    const feature = { ...(this.get('toolbox.feature') || {}) }
    if (on) feature[name] = name === 'magicType' ? { type: ['line', 'bar'] } : name === 'saveAsImage' ? { title: 'Save as a picture' } : name === 'dataView' ? { readOnly: true, title: 'The numbers', lang: ['The numbers', 'Close', 'Refresh'] } : { title: 'Back to the start' }
    else delete feature[name]
    this.set('toolbox', Object.keys(feature).length ? { ...(this.get('toolbox') || {}), feature } : undefined)
  }

  setBrush(on) {
    let option = setPath(this.S.option, 'brush', on ? { toolbox: ['rect', 'polygon', 'clear'], brushMode: 'single' } : undefined)
    const feature = { ...(getPath(option, 'toolbox.feature') || {}) }
    if (on) feature.brush = { type: ['rect', 'polygon', 'clear'] }
    else delete feature.brush
    option = setPath(option, 'toolbox', Object.keys(feature).length ? { ...(getPath(option, 'toolbox') || {}), feature } : undefined)
    this.setOption(option)
  }

  // ---- numbers and the preview ----
  scheduleData() {
    clearTimeout(this.timers.data)
    this.timers.data = setTimeout(() => this.refreshData(), 350)
    this.scheduleDraw()
  }

  scheduleDraw() {
    clearTimeout(this.timers.draw)
    this.timers.draw = setTimeout(() => this.draw(), 90)
  }

  async refreshData() {
    const S = this.S
    if (S.source !== 'mission') { this.draw(); return }
    const { spec, problem } = this.checkedSpec()
    if (!spec) { S.dataError = problem; S.answer = null; this.draw(); return }
    const key = canonicalJson(spec)
    if (this.answers.has(key)) { S.answer = this.answers.get(key); S.dataError = ''; this.afterAnswer(); return }
    S.loading = true
    this.draw()
    try {
      const answer = await this.o.api('/api/charts/data', { method: 'POST', body: JSON.stringify({ deck: this.slug, spec }) })
      this.answers.set(key, answer)
      if (canonicalJson(this.checkedSpec().spec || {}) !== key) return
      S.answer = answer
      S.dataError = ''
    }
    catch (error) {
      S.answer = null
      S.dataError = error.status && error.message ? error.message : NOT_LOADED
    }
    finally { S.loading = false }
    this.afterAnswer()
  }

  afterAnswer() {
    // Colours and the goal line depend on the series the numbers brought.
    this.render('settings')
    this.draw()
  }

  /** The settings the slide would get, and what the preview draws from them. */
  props() {
    const S = this.S
    const props = { option: S.option, height: S.height, chartId: S.chartId || 'preview' }
    if (S.source === 'mission') {
      const { spec } = this.checkedSpec()
      if (spec) props.query = spec
    }
    else if (S.source === 'table') props.rows = tableRows(S.tableText) ?? []
    return props
  }

  view() {
    const S = this.S
    const props = this.props()
    if (S.source === 'table' && !props.rows.length) return { mode: 'option', table: null, option: S.option, problem: NO_TABLE }
    if (S.source === 'mission' && !S.answer) return { mode: 'option', table: null, option: S.option, problem: S.dataError }
    if (S.source === 'data') return { mode: 'option', table: null, option: S.option, problem: 'The preview cannot show numbers written as data. The slide shows them.' }
    return chartView(props, S.source === 'mission' ? S.answer : null)
  }

  dark() { return document.documentElement.dataset.theme === 'dark' }

  fitStage() {
    const box = this.$('#cbStagebox'), stage = this.$('#cbStage')
    if (!box || !stage) return
    const height = Math.max(120, Math.min(2000, Number(this.S.height) || 360))
    const width = box.clientWidth || 980
    const scale = Math.min(1, width / 980)
    const phone = window.matchMedia('(max-width: 760px)').matches
    const room = phone ? Math.round(window.innerHeight * 0.3) : Math.round(this.$('.cb-preview').clientHeight - 70)
    const fit = Math.min(scale, room > 60 ? room / height : scale)
    stage.style.height = `${height}px`
    stage.style.transform = `scale(${fit})`
    box.style.height = `${Math.round(height * fit)}px`
    if (this.chart && (this.chart.getWidth() !== 980 || this.chart.getHeight() !== height)) this.chart.resize({ width: 980, height })
  }

  async draw() {
    if (!this.dialog?.open) return
    const S = this.S
    const status = this.$('#cbStatus'), msg = this.$('#cbMsg')
    this.$('#cbStagebox').classList.toggle('dark', this.dark())
    this.fitStage()
    const view = this.view()
    let problem = view.problem || ''
    if (S.source === 'mission' && S.loading && !S.answer) problem = 'Loading mission numbers…'
    let lib
    try { lib = await loadLibraries() }
    catch (error) { problem = error.message }
    if (!this.dialog?.open) return
    if (!problem && lib) {
      const height = Math.max(120, Math.min(2000, Number(S.height) || 360))
      if (!this.chart) this.chart = lib.echarts.init(this.$('#cbChart'), null, { renderer: 'svg', width: 980, height })
      const style = getComputedStyle(document.body)
      try {
        // This page is on the manager address and the chart may come from a zone's slide: nothing in its settings
        // is drawn as HTML (safe-chart-option.mjs, round 8 review).
        const option = safeChartOption(viewOption(view, { dark: this.dark(), font: style.fontFamily || 'system-ui, sans-serif', animate: true, ecStat: lib.ecStat, width: 980, height }))
        if (option) this.chart.setOption(option, { notMerge: true })
        else problem = 'Add numbers to show this chart.'
      }
      catch (error) { problem = `This chart cannot be drawn with these settings (${error.message}).` }
    }
    msg.hidden = !problem
    msg.textContent = problem
    status.className = `cb-status${S.dataError ? ' error' : ''}`
    status.textContent = this.statusText()
    if (!S.closing && !S.jsonProblems.errors.length) this.foot(S.saveError, !!S.saveError)
  }

  statusText() {
    const S = this.S
    if (S.source === 'table') return `Numbers from your table. They are saved ${this.target ? 'with the board' : 'in the slide'}.`
    if (S.source === 'data') return ''
    if (S.dataError) return S.dataError
    const meta = S.answer?.meta
    if (!meta) return S.loading ? 'Loading mission numbers…' : ''
    const weeks = meta.weeks || []
    const range = weeks.length ? (weeks.length === 1 ? `the week of ${weeks[0]}` : `${weeks.length} weeks, ${weeks[0]} to ${weeks[weeks.length - 1]}`) : 'no reported weeks yet'
    // Round 8: a manager's numbers narrowed by portal-api (meta.stewardship) mean this is a zone's presentation.
    const who = this.zoneOnly() ? ' You see only your own zone; mission leaders see the whole mission.'
      : meta.stewardship ? ` ${ZONE_DECK_NUMBERS}` : ' Leaders will see only their own stewardship; you see the whole mission.'
    const hidden = meta.suppressed ? ' Area numbers below 3 are hidden.' : ''
    return `Live numbers: ${range}.${who}${hidden}`
  }

  /** The tag the slide gets (the chart-id is filled in when it is saved). */
  tagText(chartId = this.S.chartId || 'new') {
    const S = this.S
    const model = { chartId, height: S.height, option: S.option, keep: S.keep, source: S.source }
    if (S.source === 'mission') {
      const { spec, problem } = this.checkedSpec()
      if (!spec) throw new Error(problem)
      model.spec = spec
    }
    else if (S.source === 'table') {
      model.rows = tableRows(S.tableText)
      if (!model.rows) throw new Error(NO_TABLE)
    }
    return writeChart(model)
  }

  // ---- saving ----
  async save() {
    const S = this.S
    if (S.saving) return
    S.saveError = ''
    let tag
    try {
      if (S.jsonProblems.errors.length) throw new Error('All options has a mistake. Fix it on the All options tab, or undo it.')
      if (S.source === 'mission' && !S.q.measures.length) throw new Error('Choose what to show on the Numbers tab.')
      // A chart that cannot draw (a flow chart without from and to, an empty table) is not saved;
      // mission numbers that could not load right now do not stop a save.
      const problem = this.view().problem
      if (problem && S.source !== 'data' && !S.loading && !(S.source === 'mission' && (S.dataError || !S.answer))) throw new Error(problem)
      if (this.target) this.boardModel()
      else this.tagText('check')
    }
    catch (error) {
      S.saveError = error.message
      this.foot(S.saveError, true)
      return
    }
    S.saving = true
    const button = this.$('#cbSave')
    button.disabled = true
    button.textContent = 'Saving…'
    try {
      if (this.target) {
        // The whiteboard places (or changes) the chart and saves the board itself.
        await this.target.save(this.boardModel())
      }
      else if (S.editing) {
        const { no, range, block, sig, chartId } = S.editing
        const info = await this.readSlide(no)
        const content = String(info?.content ?? '')
        const located = locateChart(content, { id: chartId, range, block, sig })
        if (!located.found) throw new Error(LOCATE_PROBLEMS[located.problem] || LOCATE_PROBLEMS.changed)
        // A chart without an id, or whose id a copy shares, gets its own.
        const id = chartId && !located.duplicate ? chartId : newChartId(chartIds(content))
        tag = this.tagText(id)
        await this.writeSlide(no, replaceTag(content, located.found, tag))
        this.o.toast(`Chart updated on slide ${no}.`)
        this.o.onSaved?.({ no, chartId: id })
      }
      else if (S.where === 'newSlide') {
        const id = newChartId()
        tag = this.tagText(id)
        await this.o.api('/@studio/deck', { method: 'POST', referrer: this.referrer(S.slideNo), body: JSON.stringify({ action: 'insert', after: S.slideNo, content: tag }) })
        this.o.toast(`Chart inserted on a new slide ${S.slideNo + 1}.`)
        this.o.onSaved?.({ no: S.slideNo + 1, chartId: id })
      }
      else {
        const no = S.slideNo
        const info = await this.readSlide(no)
        const content = String(info?.content ?? '')
        const id = newChartId(chartIds(content))
        tag = this.tagText(id)
        const sel = this.o.selection
        const after = sel && sel.no === no && Array.isArray(sel.range) && sel.range[1] <= content.split(/\r?\n/).length ? sel.range : null
        await this.writeSlide(no, insertChart(content, tag, after))
        this.o.toast(`Chart inserted on slide ${no}.`)
        this.o.onSaved?.({ no, chartId: id })
      }
      S.saving = false
      this.dialog.close()
    }
    catch (error) {
      S.saving = false
      S.saveError = error.message || 'The chart could not be saved. Please try again.'
      button.disabled = false
      button.textContent = this.saveText()
      this.foot(S.saveError, true)
    }
  }
}
