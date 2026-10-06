// Round 8 review: charts drawn on the manager address (3030), where the manager's sign-in is.
//
// A chart's settings (its ECharts "option") are written in a slide, and since round 7 Zone Leaders and Sister
// Training Leaders write slides too. Two pages on 3030 draw such settings: the chart builder of /studio ("Edit
// chart" on any deck) and the Whiteboard's chart frames (a chart a manager copied onto a board). ECharts writes a few
// settings into the page as HTML, and HTML written by someone else must never run where the manager is signed in.
// So safeChartOption() below changes a chart's settings before 3030 draws them:
//   - the box that appears when pointing at the chart ("tooltip") is drawn by ECharts itself as plain text
//     (renderMode 'richText'), never as HTML; its text keeps its line breaks but loses any <tags>, and its extra
//     CSS is left out;
//   - the toolbox's "data view" is left out (ECharts writes its labels as HTML);
//   - links are left out: a title's link and sublink, and "open a link on click" of treemap and sunburst charts
//     (a link can hold "javascript:").
// Everything else draws exactly as written; only the pointing box looks a little plainer in the builder.
// On the deck address (8089) the slides draw charts as written: code there cannot reach the manager's sign-in.
//
// The pages that draw on 3030 also forbid inline scripts (Content-Security-Policy with a nonce,
// whiteboard-frames.mjs chartPageCsp), so even HTML that got through could not run. This file is the first line;
// that is the second.
//
// Who uses it: the chart builder (chart-builder.mjs) and the Whiteboard's chart frame (whiteboard-chart.mjs).
// How it fits: plain JavaScript, no DOM: the browser loads it from /_manager/chart/safe-chart-option.mjs, and
// slidev/tests/safe-chart-option.test.mjs tests it with Node.

function plain(value) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false
  const proto = Object.getPrototypeOf(value)
  return proto === Object.prototype || proto === null
}

/** A tooltip text with its <br> kept as line breaks and every other tag (and any stray < or >) taken out. */
export function plainTooltipText(text) {
  return String(text)
    .replace(/<br\s*\/?>/gi, '\n')
    .replace(/<[^>]*>/g, '')
    .replace(/[<>]/g, '')
}

// A tooltip setting (anywhere: the chart's, a series', a data item's, the legend's): no HTML text, no extra CSS.
function safeTooltip(tooltip) {
  if (!plain(tooltip)) return tooltip
  const out = { ...tooltip }
  if (typeof out.formatter === 'string') out.formatter = plainTooltipText(out.formatter)
  delete out.extraCssText
  return out
}

// Every level of the option: tooltips cleaned wherever they are, "link" clicks of treemaps and sunbursts left out.
function walk(value, depth) {
  if (depth > 40) return value
  if (Array.isArray(value)) return value.map(item => walk(item, depth + 1))
  if (!plain(value)) return value
  const out = {}
  for (const [key, item] of Object.entries(value)) {
    if (key === '__proto__' || key === 'constructor' || key === 'prototype') continue
    if (key === 'nodeClick' && item === 'link') continue
    if (key === 'tooltip') out[key] = Array.isArray(item) ? item.map(t => safeTooltip(walk(t, depth + 1))) : safeTooltip(walk(item, depth + 1))
    else out[key] = walk(item, depth + 1)
  }
  return out
}

const each = (value, change) => (Array.isArray(value) ? value.map(change) : change(value))

/**
 * The chart's settings as 3030 may draw them (a new object; the one given is not changed). Anything that is not a
 * plain object (null, a problem) is given back as it is.
 */
export function safeChartOption(option) {
  if (!plain(option)) return option
  const out = walk(option, 0)
  // The chart's own tooltip decides how every tooltip of the chart is drawn: as text, never as HTML. A chart without
  // one has no tooltip at all, so none is added.
  if (out.tooltip !== undefined) out.tooltip = each(out.tooltip, t => (plain(t) ? { ...t, renderMode: 'richText' } : t))
  if (out.title !== undefined) out.title = each(out.title, t => { if (!plain(t)) return t; const { link, sublink, ...rest } = t; return rest })
  if (out.toolbox !== undefined) {
    out.toolbox = each(out.toolbox, box => {
      if (!plain(box) || !plain(box.feature)) return box
      const { dataView, ...feature } = box.feature
      return { ...box, feature }
    })
  }
  return out
}
