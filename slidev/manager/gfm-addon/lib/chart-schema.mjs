// A JSON schema of the ECharts 6 option, for the builder's "All options" pane:
// Monaco's JSON editor offers these names as you type (with a short note for
// each) and underlines settings ECharts does not know at the top level. Also
// checkOption(), the same check without Monaco (the text box fallback and the
// tests). Plain JavaScript; the manager serves it at /_manager/chart/.
import { RENDERERS, SERIES_TYPES } from './chart-engine.mjs'

const STR = { type: 'string' }
const NUM = { type: 'number' }
const BOOL = { type: 'boolean' }
const ANY = {}
const COLOR = { type: ['string', 'object'], description: 'A colour: #d96b2b, rgb(…), or a gradient object.' }
const NUM_OR_STR = { type: ['number', 'string'] }
const ARR = { type: 'array' }

function obj(properties, description) {
  return { type: 'object', ...(description ? { description } : {}), properties }
}
function oneOrMany(schema, description) {
  return { description, anyOf: [schema, { type: 'array', items: schema }] }
}
function names(list, schema = ANY) {
  return Object.fromEntries(list.map(n => [n, schema]))
}

const BOX = { left: NUM_OR_STR, top: NUM_OR_STR, right: NUM_OR_STR, bottom: NUM_OR_STR, width: NUM_OR_STR, height: NUM_OR_STR, z: NUM, zlevel: NUM, show: BOOL, id: STR }
const TEXT = obj({
  color: COLOR, fontSize: NUM_OR_STR, fontWeight: NUM_OR_STR, fontFamily: STR, fontStyle: { enum: ['normal', 'italic', 'oblique'] }, lineHeight: NUM,
  width: NUM_OR_STR, height: NUM_OR_STR, overflow: { enum: ['none', 'truncate', 'break', 'breakAll'] }, ellipsis: STR,
  textBorderColor: COLOR, textBorderWidth: NUM, textShadowColor: COLOR, textShadowBlur: NUM, backgroundColor: COLOR,
  borderColor: COLOR, borderWidth: NUM, borderRadius: NUM_OR_STR, padding: ANY, align: { enum: ['left', 'center', 'right'] },
  verticalAlign: { enum: ['top', 'middle', 'bottom'] }, rich: { type: 'object', description: 'Named text styles used in a formatter as {name|text}.' },
}, 'Text style')
const LINE = obj({ color: COLOR, width: NUM, type: { description: 'solid, dashed, dotted or a dash list like [4, 4]', anyOf: [{ enum: ['solid', 'dashed', 'dotted'] }, ARR] }, opacity: NUM, cap: { enum: ['butt', 'round', 'square'] }, join: { enum: ['bevel', 'round', 'miter'] }, dashOffset: NUM, shadowBlur: NUM, shadowColor: COLOR, shadowOffsetX: NUM, shadowOffsetY: NUM, curveness: NUM }, 'Line style')
const ITEM = obj({ color: COLOR, color0: COLOR, borderColor: COLOR, borderColor0: COLOR, borderWidth: NUM, borderType: ANY, borderRadius: { type: ['number', 'array'] }, opacity: NUM, shadowBlur: NUM, shadowColor: COLOR, shadowOffsetX: NUM, shadowOffsetY: NUM, decal: ANY, gapWidth: NUM, borderCap: STR }, 'Item style (bars, points, slices)')
const AREA = obj({ color: COLOR, opacity: NUM, origin: { anyOf: [{ enum: ['auto', 'start', 'end'] }, NUM] }, shadowBlur: NUM, shadowColor: COLOR }, 'Area fill under a line')
const POSITIONS = ['top', 'left', 'right', 'bottom', 'inside', 'insideLeft', 'insideRight', 'insideTop', 'insideBottom', 'insideTopLeft', 'insideBottomLeft', 'insideTopRight', 'insideBottomRight', 'outside', 'center', 'start', 'middle', 'end', 'insideStart', 'insideStartTop', 'insideStartBottom', 'insideMiddle', 'insideMiddleTop', 'insideMiddleBottom', 'insideEnd', 'insideEndTop', 'insideEndBottom']
const LABEL = obj({
  ...TEXT.properties, show: BOOL, position: { anyOf: [{ enum: POSITIONS }, ARR] }, distance: NUM, rotate: NUM, offset: ARR,
  formatter: { type: 'string', description: 'Text with {a} series, {b} name, {c} value, {d} percent, {@Heading} a column, {name|text} a rich style.' },
  valueAnimation: BOOL, minMargin: NUM, silent: BOOL,
}, 'Labels on the chart')
const EMPHASIS = obj({ disabled: BOOL, focus: { enum: ['none', 'self', 'series', 'adjacency', 'ancestor', 'descendant'] }, blurScope: { enum: ['coordinateSystem', 'series', 'global'] }, scale: { type: ['boolean', 'number'] }, itemStyle: ITEM, label: LABEL, lineStyle: LINE, areaStyle: AREA }, 'How it looks when pointed at')
const MARK_DATA = { type: 'array', description: 'Entries like {"yAxis": 30, "name": "Goal"}, {"type": "average"}, {"type": "max"}, or pairs [{…}, {…}] for areas.' }
const MARK = extra => obj({ data: MARK_DATA, silent: BOOL, symbol: ANY, symbolSize: ANY, precision: NUM, label: LABEL, lineStyle: LINE, itemStyle: ITEM, emphasis: EMPHASIS, animation: BOOL, ...extra })

const AXIS = obj({
  ...BOX, type: { enum: ['value', 'category', 'time', 'log'] }, name: STR, nameLocation: { enum: ['start', 'middle', 'center', 'end'] }, nameGap: NUM, nameRotate: NUM, nameTextStyle: TEXT,
  inverse: BOOL, boundaryGap: { type: ['boolean', 'array'] }, min: ANY, max: ANY, scale: BOOL, splitNumber: NUM, minInterval: NUM, maxInterval: NUM, interval: NUM, logBase: NUM,
  startValue: NUM, data: ARR, position: { enum: ['top', 'bottom', 'left', 'right'] }, offset: NUM, gridIndex: NUM, alignTicks: BOOL, silent: BOOL, triggerEvent: BOOL,
  axisLine: obj({ show: BOOL, onZero: BOOL, symbol: ANY, lineStyle: LINE }), axisTick: obj({ show: BOOL, alignWithLabel: BOOL, interval: ANY, inside: BOOL, length: NUM, lineStyle: LINE }),
  axisLabel: obj({ ...TEXT.properties, show: BOOL, interval: ANY, inside: BOOL, rotate: NUM, margin: NUM, formatter: STR, showMinLabel: BOOL, showMaxLabel: BOOL, hideOverlap: BOOL, alignMinLabel: STR, alignMaxLabel: STR }),
  splitLine: obj({ show: BOOL, interval: ANY, lineStyle: LINE }), splitArea: obj({ show: BOOL, areaStyle: AREA }), minorTick: ANY, minorSplitLine: ANY,
  axisPointer: ANY, breaks: { type: 'array', description: 'ECharts 6 axis breaks: [{"start": 100, "end": 900, "gap": "4%"}].' }, breakArea: ANY, breakLabelLayout: ANY,
  jitter: { type: 'number', description: 'ECharts 6: spread points of the same category by this many pixels.' }, jitterOverlap: BOOL, jitterMargin: NUM, animation: BOOL,
}, 'An axis')

const SERIES_PROPS = {
  type: { enum: SERIES_TYPES, description: 'The chart type of this series.' },
  id: STR, name: { type: 'string', description: 'The name in the legend and the tooltip (default: the column heading).' },
  coordinateSystem: { enum: ['cartesian2d', 'polar', 'singleAxis', 'calendar', 'parallel', 'matrix', 'none'] },
  ...names(['xAxisIndex', 'yAxisIndex', 'polarIndex', 'radarIndex', 'singleAxisIndex', 'parallelIndex', 'calendarIndex', 'datasetIndex'], NUM),
  datasetId: STR, seriesLayoutBy: { enum: ['column', 'row'] },
  encode: { type: 'object', description: 'Which columns this series draws, by number or heading: {"x": 0, "y": "Goal"}.' },
  dimensions: ARR, data: { description: 'Numbers written in the option (without it, the chart\'s table is used).' },
  colorBy: { enum: ['series', 'data'] }, legendHoverLink: BOOL, stack: { type: 'string', description: 'Series with the same stack name are stacked.' }, stackStrategy: { enum: ['samesign', 'all', 'positive', 'negative'] },
  smooth: { type: ['boolean', 'number'] }, smoothMonotone: { enum: ['x', 'y'] }, step: { enum: [false, 'start', 'middle', 'end'] }, connectNulls: BOOL, clip: BOOL,
  showSymbol: BOOL, showAllSymbol: ANY, symbol: STR, symbolSize: ANY, symbolRotate: NUM, symbolKeepAspect: BOOL, symbolOffset: ARR, sampling: { enum: ['lttb', 'average', 'min', 'max', 'minmax', 'sum'] },
  label: LABEL, labelLine: obj({ show: BOOL, length: NUM, length2: NUM, smooth: ANY, lineStyle: LINE }), labelLayout: ANY, endLabel: LABEL,
  itemStyle: ITEM, lineStyle: LINE, areaStyle: AREA, emphasis: EMPHASIS, blur: ANY, select: ANY, selectedMode: ANY,
  barWidth: NUM_OR_STR, barMaxWidth: NUM_OR_STR, barMinWidth: NUM_OR_STR, barMinHeight: NUM, barGap: STR, barCategoryGap: STR, showBackground: BOOL, backgroundStyle: ITEM, roundCap: BOOL, realtimeSort: BOOL,
  large: BOOL, largeThreshold: NUM, progressive: NUM,
  radius: ANY, center: ARR, roseType: { enum: [false, 'radius', 'area'] }, startAngle: NUM, endAngle: NUM, clockwise: BOOL, minAngle: NUM, padAngle: NUM, avoidLabelOverlap: BOOL, percentPrecision: NUM, stillShowZeroSum: BOOL,
  sort: { enum: ['none', 'ascending', 'descending', null] }, gap: NUM, min: NUM, max: NUM, minSize: NUM_OR_STR, maxSize: NUM_OR_STR, funnelAlign: { enum: ['left', 'center', 'right'] }, orient: { enum: ['horizontal', 'vertical', 'LR', 'RL', 'TB', 'BT'] },
  ...BOX, splitNumber: NUM, progress: ANY, pointer: ANY, anchor: ANY, axisLine: ANY, axisTick: ANY, splitLine: ANY, axisLabel: ANY, title: ANY, detail: ANY,
  layout: { enum: ['none', 'force', 'circular', 'orthogonal', 'radial'] }, force: obj({ repulsion: ANY, gravity: NUM, edgeLength: ANY, friction: NUM, layoutAnimation: BOOL }), circular: ANY,
  roam: { type: ['boolean', 'string'] }, zoom: NUM, draggable: BOOL, edgeSymbol: ARR, edgeSymbolSize: ANY, edgeLabel: LABEL, links: ARR, edges: ARR, nodes: ARR, categories: ARR,
  nodeWidth: NUM, nodeGap: NUM, nodeAlign: { enum: ['justify', 'left', 'right'] }, layoutIterations: NUM, levels: ARR,
  expandAndCollapse: BOOL, initialTreeDepth: NUM, edgeShape: { enum: ['curve', 'polyline'] }, edgeForkPosition: STR, leaves: ANY,
  breadcrumb: ANY, nodeClick: { enum: [false, 'zoomToNode', 'link'] }, upperLabel: LABEL, leafDepth: NUM, visibleMin: NUM, squareRatio: NUM,
  boxWidth: ARR, rippleEffect: obj({ brushType: { enum: ['stroke', 'fill'] }, scale: NUM, period: NUM, number: NUM, color: COLOR }), showEffectOn: { enum: ['render', 'emphasis'] }, effect: ANY, polyline: BOOL,
  symbolRepeat: ANY, symbolRepeatDirection: STR, symbolMargin: ANY, symbolClip: BOOL, symbolBoundingData: ANY, symbolPatternSize: NUM,
  renderItem: { enum: RENDERERS, description: 'The drawing of a custom series: waterfall (changes from a start), range (a bar from one column to the next) or errorbar.' },
  markLine: MARK({}), markPoint: MARK({}), markArea: MARK({}), tooltip: ANY,
  universalTransition: { type: ['boolean', 'object'], description: 'Morph between chart types and data (on by default).' },
  animation: BOOL, animationDuration: NUM, animationEasing: STR, animationDelay: ANY, animationDurationUpdate: NUM, animationEasingUpdate: STR, silent: BOOL, cursor: STR,
  gfm: obj({
    trend: obj({
      method: { enum: ['linear', 'polynomial', 'exponential', 'logarithmic', 'moving-average'] }, degree: { type: 'number', minimum: 2, maximum: 6 }, window: { type: 'number', minimum: 2, maximum: 52 },
      forecast: { type: 'number', minimum: 0, maximum: 52 }, color: STR, width: NUM, style: { enum: ['dashed', 'dotted', 'solid'] }, label: STR,
    }, 'A trend line through this series (and every series it is repeated for).'),
  }, 'Mission chart settings of this series'),
}

const SERIES = { type: 'object', properties: SERIES_PROPS, required: ['type'] }

const TOP = {
  title: oneOrMany(obj({ ...BOX, text: STR, subtext: STR, link: STR, textStyle: TEXT, subtextStyle: TEXT, textAlign: STR, textVerticalAlign: STR, padding: ANY, itemGap: NUM, backgroundColor: COLOR, borderColor: COLOR, borderWidth: NUM, borderRadius: ANY }), 'The title'),
  legend: oneOrMany(obj({ ...BOX, type: { enum: ['plain', 'scroll'] }, orient: { enum: ['horizontal', 'vertical'] }, align: STR, padding: ANY, itemGap: NUM, itemWidth: NUM, itemHeight: NUM, itemStyle: ITEM, lineStyle: LINE, icon: STR, formatter: STR, selectedMode: ANY, inactiveColor: COLOR, selected: ANY, textStyle: TEXT, data: ARR, backgroundColor: COLOR, borderColor: COLOR, borderRadius: ANY, pageIconColor: COLOR, pageTextStyle: TEXT, selector: ANY, tooltip: ANY }), 'The legend'),
  grid: oneOrMany(obj({ ...BOX, containLabel: BOOL, outerBoundsMode: STR, outerBounds: ANY, backgroundColor: COLOR, borderColor: COLOR, borderWidth: NUM, tooltip: ANY }), 'Where x/y charts are drawn; a list for several charts side by side'),
  xAxis: oneOrMany(AXIS, 'The x axis'), yAxis: oneOrMany(AXIS, 'The y axis'),
  polar: oneOrMany(obj({ id: STR, z: NUM, center: ARR, radius: ANY, tooltip: ANY }), 'A round coordinate system'),
  radiusAxis: oneOrMany(AXIS), angleAxis: oneOrMany(obj({ ...AXIS.properties, startAngle: NUM, endAngle: NUM, clockwise: BOOL })),
  radar: oneOrMany(obj({ ...BOX, center: ARR, radius: ANY, startAngle: NUM, axisName: ANY, nameGap: NUM, splitNumber: NUM, shape: { enum: ['polygon', 'circle'] }, scale: BOOL, axisLine: ANY, axisTick: ANY, axisLabel: ANY, splitLine: ANY, splitArea: ANY, indicator: { type: 'array', description: '[{"name": "…", "max": 100}] (default: one spoke per row).' } })),
  dataZoom: oneOrMany(obj({ ...BOX, type: { enum: ['inside', 'slider'] }, disabled: BOOL, xAxisIndex: ANY, yAxisIndex: ANY, radiusAxisIndex: ANY, angleAxisIndex: ANY, singleAxisIndex: ANY, filterMode: { enum: ['filter', 'weakFilter', 'empty', 'none'] }, start: NUM, end: NUM, startValue: ANY, endValue: ANY, minSpan: NUM, maxSpan: NUM, orient: STR, zoomLock: BOOL, throttle: NUM, rangeMode: ARR, zoomOnMouseWheel: ANY, moveOnMouseMove: ANY, moveOnMouseWheel: ANY, showDetail: BOOL, showDataShadow: ANY, realtime: BOOL, brushSelect: BOOL, handleSize: ANY, handleStyle: ITEM, fillerColor: COLOR, borderColor: COLOR, backgroundColor: COLOR, dataBackground: ANY, textStyle: TEXT, labelFormatter: STR }), 'Zoom: "inside" (wheel and drag) or "slider"'),
  visualMap: oneOrMany(obj({ ...BOX, type: { enum: ['continuous', 'piecewise'] }, min: NUM, max: NUM, range: ARR, calculable: BOOL, realtime: BOOL, inverse: BOOL, precision: NUM, itemWidth: NUM, itemHeight: NUM, align: STR, text: ARR, textGap: NUM, dimension: NUM_OR_STR, seriesIndex: ANY, hoverLink: BOOL, inRange: obj({ color: ARR, symbolSize: ANY, opacity: ANY, colorLightness: ANY, colorSaturation: ANY }), outOfRange: ANY, controller: ANY, orient: { enum: ['horizontal', 'vertical'] }, splitNumber: NUM, pieces: ARR, categories: ARR, minOpen: BOOL, maxOpen: BOOL, selectedMode: ANY, showLabel: BOOL, itemGap: NUM, itemSymbol: STR, formatter: STR, textStyle: TEXT }), 'Colour by value'),
  tooltip: obj({ show: BOOL, trigger: { enum: ['item', 'axis', 'none'] }, axisPointer: obj({ type: { enum: ['line', 'shadow', 'cross', 'none'] }, axis: STR, snap: BOOL, label: ANY, lineStyle: LINE, shadowStyle: ANY, crossStyle: ANY }), showContent: BOOL, alwaysShowContent: BOOL, triggerOn: { enum: ['mousemove', 'click', 'mousemove|click', 'none'] }, showDelay: NUM, hideDelay: NUM, enterable: BOOL, renderMode: { enum: ['html', 'richText'] }, confine: BOOL, transitionDuration: NUM, position: ANY, formatter: STR, backgroundColor: COLOR, borderColor: COLOR, borderWidth: NUM, padding: ANY, textStyle: TEXT, extraCssText: STR, order: { enum: ['seriesAsc', 'seriesDesc', 'valueAsc', 'valueDesc'] } }, 'The box that appears when pointing at the chart'),
  axisPointer: ANY,
  toolbox: oneOrMany(obj({ ...BOX, orient: STR, itemSize: NUM, itemGap: NUM, showTitle: BOOL, iconStyle: ITEM, emphasis: ANY, feature: obj({ saveAsImage: obj({ type: { enum: ['png', 'jpg', 'svg'] }, name: STR, backgroundColor: COLOR, pixelRatio: NUM, title: STR }), restore: ANY, dataView: obj({ readOnly: BOOL, title: STR, lang: ARR }), dataZoom: ANY, magicType: obj({ type: { type: 'array', items: { enum: ['line', 'bar', 'stack'] } }, title: ANY }), brush: ANY }) }), 'Buttons: save as image, see the numbers, zoom, switch line/bar'),
  brush: oneOrMany(obj({ toolbox: { type: 'array', items: { enum: ['rect', 'polygon', 'lineX', 'lineY', 'keep', 'clear'] } }, brushLink: ANY, seriesIndex: ANY, xAxisIndex: ANY, yAxisIndex: ANY, brushType: { enum: ['rect', 'polygon', 'lineX', 'lineY'] }, brushMode: { enum: ['single', 'multiple'] }, transformable: BOOL, brushStyle: ITEM, throttleType: STR, throttleDelay: NUM, removeOnClick: BOOL, inBrush: ANY, outOfBrush: ANY, z: NUM }), 'Select points by drawing a box'),
  parallel: oneOrMany(obj({ ...BOX, layout: { enum: ['horizontal', 'vertical'] }, axisExpandable: BOOL, axisExpandCenter: NUM, axisExpandCount: NUM, axisExpandWidth: NUM, parallelAxisDefault: ANY })),
  parallelAxis: oneOrMany(obj({ ...AXIS.properties, dim: NUM, parallelIndex: NUM, realtime: BOOL, areaSelectStyle: ANY })),
  singleAxis: oneOrMany(obj({ ...AXIS.properties, orient: { enum: ['horizontal', 'vertical'] } })),
  timeline: obj({ ...BOX, type: STR, axisType: { enum: ['value', 'category', 'time'] }, currentIndex: NUM, autoPlay: BOOL, rewind: BOOL, loop: BOOL, playInterval: NUM, realtime: BOOL, replaceMerge: ANY, controlPosition: { enum: ['left', 'right'] }, orient: STR, inverse: BOOL, symbol: STR, symbolSize: ANY, lineStyle: LINE, label: LABEL, itemStyle: ITEM, checkpointStyle: ANY, controlStyle: ANY, progress: ANY, emphasis: ANY, data: ARR }, 'Play through the rows of the table one at a time'),
  calendar: oneOrMany(obj({ ...BOX, range: ANY, cellSize: ANY, orient: { enum: ['horizontal', 'vertical'] }, splitLine: ANY, itemStyle: ITEM, dayLabel: obj({ show: BOOL, firstDay: NUM, margin: NUM, position: STR, nameMap: ANY, color: COLOR }), monthLabel: ANY, yearLabel: ANY, silent: BOOL }), 'A calendar (labels as dates)'),
  matrix: ANY, thumbnail: ANY,
  dataset: oneOrMany(obj({ id: STR, source: ANY, dimensions: ARR, sourceHeader: ANY, transform: { description: '{"type": "filter" | "sort" | "boxplot" | "ecStat:regression" | "ecStat:histogram" | "ecStat:clustering", "config": {…}}' }, fromDatasetIndex: NUM, fromDatasetId: STR, fromTransformResult: NUM }), 'More datasets (dataset 0 is always the chart\'s table)'),
  graphic: { description: 'Shapes and text drawn on top: [{"type": "text", "right": 10, "top": 10, "style": {"text": "…"}}].' },
  aria: obj({ enabled: BOOL, label: obj({ enabled: BOOL, description: STR, general: ANY, series: ANY, data: ANY }), decal: obj({ show: BOOL, decals: ANY }) }, 'What screen readers say; patterns for colour-blind readers'),
  series: { type: 'array', items: SERIES, description: 'The series: one per column of the table (the last one repeats for the columns after it).' },
  color: { type: 'array', items: STR, description: 'The colours, in order (default: the mission colours).' },
  backgroundColor: COLOR, textStyle: TEXT, darkMode: ANY, useUTC: BOOL,
  animation: BOOL, animationThreshold: NUM, animationDuration: NUM, animationEasing: STR, animationDelay: ANY, animationDurationUpdate: NUM, animationEasingUpdate: STR, animationDelayUpdate: ANY, stateAnimation: ANY, blendMode: STR, hoverLayerThreshold: NUM,
  options: ARR, baseOption: ANY, media: ARR,
  gfm: obj({
    format: obj({ style: { enum: ['auto', 'plain', 'percent', 'compact', 'decimals'] }, decimals: { type: 'number', minimum: 0, maximum: 4 }, prefix: STR, suffix: STR }, 'Numbers in the deck\'s language'),
    kind: { enum: ['tile', 'multiples'], description: 'tile: a key number; multiples: one small chart per column.' },
    goal: { type: 'object', description: 'How goal columns are drawn ({"column": "Goal", "lineStyle": {"color": "#d96b2b"}}).' },
    target: { type: 'number', description: 'The goal of a key number.' },
  }, 'Mission chart settings'),
}

/** The top-level names an ECharts option may have. */
export const TOP_LEVEL = Object.keys(TOP)

/** The JSON schema of an option (draft 7), for Monaco. */
export function optionSchema() {
  return { $schema: 'http://json-schema.org/draft-07/schema#', type: 'object', properties: TOP, additionalProperties: false }
}

/**
 * The same check without Monaco: { errors, warnings } as sentences. Errors
 * stop the chart from being saved; warnings are settings ECharts would
 * ignore.
 */
export function checkOption(option) {
  const errors = [], warnings = []
  if (!option || typeof option !== 'object' || Array.isArray(option)) return { errors: ['The options must be a list of settings in { }.'], warnings }
  for (const key of Object.keys(option)) if (!TOP.hasOwnProperty(key)) warnings.push(`“${key}” is not an ECharts setting; it is ignored.`)
  const series = option.series === undefined ? [] : Array.isArray(option.series) ? option.series : [option.series]
  series.forEach((s, i) => {
    if (!s || typeof s !== 'object' || Array.isArray(s)) { errors.push(`Series ${i + 1} must be a list of settings in { }.`); return }
    if (!s.type) errors.push(`Series ${i + 1} needs a "type" (for example "bar").`)
    else if (s.type === 'map') errors.push('Map charts need a map file, and none is installed.')
    else if (!SERIES_TYPES.includes(s.type)) errors.push(`“${s.type}” is not a chart type ECharts knows.`)
    for (const key of Object.keys(s)) if (!SERIES_PROPS.hasOwnProperty(key)) warnings.push(`Series ${i + 1}: “${key}” is not a series setting; it is ignored.`)
  })
  const kind = option.gfm?.kind
  if (kind !== undefined && !['tile', 'multiples'].includes(kind)) errors.push('"gfm.kind" is "tile" or "multiples".')
  return { errors, warnings }
}
