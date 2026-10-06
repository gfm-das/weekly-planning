// Turns the dashboard descriptions in dataease/dashboards/*.json into the objects DataEase v2.10 saves
// (componentData, canvasViewInfo, canvasStyleData). No network here, so it can be tested on its own
// (dataease/tests/build.test.mjs). The long style objects come from dataease/dashboards/base/, which are DataEase's
// own defaults (taken from its sample dashboard, English labels); this file only sets what differs.
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
export const DASHBOARDS_DIR = path.resolve(HERE, '..', 'dashboards');

const readJson = file => JSON.parse(fs.readFileSync(file, 'utf8'));
const clone = value => JSON.parse(JSON.stringify(value));

export function loadBase(dir = path.join(DASHBOARDS_DIR, 'base')) {
  return {
    chart: readJson(path.join(dir, 'view-chart.json')),
    table: readJson(path.join(dir, 'view-table.json')),
    richText: readJson(path.join(dir, 'view-richtext.json')),
    component: readJson(path.join(dir, 'component.json')),
    canvasStyle: readJson(path.join(dir, 'canvas-style.json')),
  };
}

// The calm colours of the Presentations charts (slidev/manager/gfm-addon/lib/chart-core.mjs, light theme).
export const COLORS = {
  result: '#00869e', goal: '#d96b2b', trend: '#6656c9', extra: ['#b88400', '#a64f8e', '#3f8a3a', '#2a5f99', '#cf4545'],
  ink: '#17394b', soft: '#3d5866', muted: '#556d7a', grid: '#e3eaee', axis: '#b8c6cd', page: '#e9eff1', surface: '#ffffff',
};
// DataEase fills a colour list up to its own 9 default colours place by place, so every list here has 9 colours.
const PALETTE = [COLORS.result, COLORS.goal, COLORS.trend, ...COLORS.extra, '#6b7f8a'];
// The canvas the dashboards are laid out on. DataEase scales a dashboard's text by 1.2 x the smaller of (space it gets
// / canvas width) and (height it gets / canvas height), and its grid rows by the height it gets. At 1280 x 800 the
// text keeps about its written size in the portal frame of a 1366 x 768 laptop (DataEase's usual 1920 x 1080 made it
// about half as big there, 6 px), and the key-number tiles still fit their rows on wide, short screens.
export const CANVAS = { width: 1280, height: 800 };
// Week axes: every week keeps its label, the last complete week included (the Dashboards deck's round-4 rule). The
// labels stand upright, so 26 of them fit beside each other on a computer.
export const WEEK_LABEL_ROTATE = -90;
export const HEAT_WEEK_LABEL_ROTATE = -45;
// The font of the portal and the Presentations charts.
export const FONT_FAMILY = "'Segoe UI', Roboto, Helvetica, Arial, sans-serif";
// Heat maps: light (far below the goal) to deep teal (at or above it), in 9 even steps.
const HEAT = ['#eef5f7', '#d6eaef', '#bcdde5', '#9ccdd8', '#77b9c8', '#4fa3b6', '#2a8ca2', '#11788e', '#00667a'];
// The lists of fields a chart (DataEase "view") has: axes, stacks, labels, tooltips, colours, drill-down, table.
export const CHART_FIELD_LISTS = ['xAxis', 'xAxisExt', 'yAxis', 'yAxisExt', 'extStack', 'extBubble', 'extLabel', 'extTooltip', 'extColor', 'drillFields', 'viewFields'];

// ---- SQL -------------------------------------------------------------------------------------------------------

/** The SQL DataEase runs: the repository file without its comment lines (DataEase wraps it in a subquery). */
export function datasetSql(file) {
  return fs.readFileSync(file, 'utf8').split(/\r?\n/).filter(line => !/^\s*--/.test(line)).join('\n').trim().replace(/;\s*$/, '');
}

// ---- fields ----------------------------------------------------------------------------------------------------

/**
 * Stable ids: DataEase lets the page choose the ids of fields, charts and dashboards, so re-running updates in
 * place. They must not repeat across kinds (DataEase looks some ids up in several tables at once): the folder,
 * dashboards and charts use 1150..., dataset fields and SQL tables 1160... Both lie below the ids DataEase makes
 * itself (about 1.3e18 in 2026, growing with time) and clear of its own starting data (checked on a fresh install).
 * Every id is at least 10000 away from any other: DataEase keeps dashboard ids (and some chart and field ids) as
 * text and MySQL compares them with numbers as floating point, which cannot tell apart ids closer than about 256
 * here (two dashboards 1 apart were mixed up in a test; at 7.1e18 DataEase failed outright).
 */
export function fieldId(datasetIndex, columnIndex) {
  return String(1160000000000000000n + BigInt(datasetIndex) * 1000000000n + BigInt(columnIndex) * 10000n);
}
export function tableId(datasetIndex) {
  return String(1160000000000000000n + BigInt(datasetIndex) * 1000000000n + 900000000n);
}

/** A dataset field (as saved in the dataset) prepared for use in a chart. */
export function chartField(field, options = {}) {
  const quota = options.groupType ? options.groupType === 'q' : field.groupType === 'q';
  const { gfmKey, ...saved } = clone(field);
  return {
    ...saved,
    groupType: options.groupType || field.groupType,
    summary: options.summary ?? (field.extField === 2 && options.agg ? '' : quota ? 'sum' : 'count'),
    sort: options.sort || 'none',
    dateStyle: options.dateStyle || 'y_M_d',
    datePattern: 'date_sub',
    dateShowFormat: null,
    chartType: options.chartType || 'bar',
    compareCalc: { type: 'none', resultData: 'percent', field: null, custom: null },
    logic: null,
    filterType: null,
    index: options.index ?? 0,
    formatterCfg: { type: 'auto', unitLanguage: 'en', unit: 1, suffix: options.suffix || '', decimalCount: options.decimals ?? 0, thousandSeparator: true },
    chartShowName: options.label || null,
    filter: [],
    customSort: [],
    busiType: null,
    hide: false,
    field: null,
    agg: !!options.agg,
  };
}

/** A dataset field by its key: the SQL column name, or the name of a calculated field in datasets.json. */
export function fieldByKey(dataset, key) {
  const field = dataset.fields.find(f => f.gfmKey === key);
  if (!field) throw new Error(`Dataset "${dataset.name}" has no field "${key}".`);
  return field;
}

// ---- charts ----------------------------------------------------------------------------------------------------

// The look every chart shares: our colours, thin lines with small dots, no value labels, a white tooltip.
function baseChartAttr(view, colors) {
  const basic = view.customAttr.basicStyle;
  basic.colors = colors;
  basic.colorScheme = 'custom';
  basic.gradient = false;
  basic.alpha = 100;
  basic.lineWidth = 2;
  basic.lineSymbol = 'circle';
  basic.lineSymbolSize = 4;
  basic.lineSmooth = false;
  basic.barDefault = true;
  const label = view.customAttr.label;
  if (label) { label.show = false; label.color = COLORS.soft; label.fontSize = 12; }
  const tooltip = view.customAttr.tooltip;
  if (tooltip) { tooltip.show = true; tooltip.backgroundColor = '#ffffff'; tooltip.color = COLORS.ink; }
}

// Title, legend and axes in the portal's colours and sizes; week axes with every label (see WEEK_LABEL_ROTATE).
function baseChartStyle(view, spec) {
  const style = view.customStyle;
  if (style.text) {
    Object.assign(style.text, { show: true, fontSize: 15, color: COLORS.ink, hPosition: 'left', vPosition: 'top', isBolder: true, isItalic: false, fontFamily: 'Microsoft YaHei', remarkShow: !!spec.note, remark: spec.note || '' });
  }
  if (style.legend) Object.assign(style.legend, { show: spec.legend !== false, hPosition: 'left', vPosition: 'top', orient: 'horizontal', icon: 'circle', color: COLORS.soft, fontSize: 13 });
  for (const axis of ['xAxis', 'yAxis']) {
    const a = style[axis];
    if (!a) continue;
    Object.assign(a, { color: COLORS.muted, fontSize: 12 });
    if (a.axisLabel) Object.assign(a.axisLabel, { color: COLORS.muted, fontSize: 12 });
    if (a.axisLine?.lineStyle) a.axisLine.lineStyle.color = COLORS.axis;
    if (a.splitLine?.lineStyle) a.splitLine.lineStyle.color = COLORS.grid;
    if (a.axisLabelFormatter) a.axisLabelFormatter.decimalCount = 0;
  }
  if (view.customAttr.tooltip?.tooltipFormatter) view.customAttr.tooltip.tooltipFormatter.decimalCount = 1;
  // A chart over weeks (line or column): upright labels, so none is left out (see WEEK_LABEL_ROTATE).
  // 11 px: 26 upright week labels, each with G2's 6 px gap, fit beside each other in the portal on a 1366 x 768 laptop.
  if (spec.x === 'week' && style.xAxis?.axisLabel && ['line', 'bar', 'area'].includes(spec.type)) Object.assign(style.xAxis.axisLabel, { rotate: WEEK_LABEL_ROTATE, fontSize: 11 });
  // A heat map over weeks is as wide as the page: slanted labels fit there.
  if (spec.x === 'week' && style.xAxis?.axisLabel && spec.type === 't-heatmap') style.xAxis.axisLabel.rotate = HEAT_WEEK_LABEL_ROTATE;
  if (spec.yName !== undefined && style.yAxis) style.yAxis.name = spec.yName;
  if (spec.xName !== undefined && style.xAxis) style.xAxis.name = spec.xName;
}

/** One chart (DataEase "view") of type line, bar, bar-horizontal, t-heatmap, table-normal or rich-text. */
export function buildView(spec, ctx) {
  const { base, datasets, dashboardId } = ctx;
  const dataset = spec.dataset ? datasets[spec.dataset] : null;
  if (spec.dataset && !dataset) throw new Error(`Chart "${spec.id}" uses unknown dataset "${spec.dataset}".`);
  const kind = spec.type;
  const template = kind === 'rich-text' ? base.richText : kind === 'table-normal' ? base.table : base.chart;
  const view = clone(template);
  Object.assign(view, {
    id: spec.id,
    title: spec.title || '',
    sceneId: dashboardId,
    tableId: dataset ? dataset.id : (ctx.anyDatasetId || null),
    type: kind,
    render: kind === 'rich-text' ? 'custom' : 'antv',
    resultMode: spec.top ? 'custom' : 'all',
    resultCount: spec.top || 1000,
    customFilter: { logic: null, items: null },
    stylePriority: 'panel',
    chartType: 'private',
    dataFrom: 'calc',
    refreshViewEnable: false,
    linkageActive: false,
    jumpActive: false,
  });
  for (const list of CHART_FIELD_LISTS) view[list] = [];

  const colors = spec.colors || PALETTE;
  baseChartAttr(view, colors);
  baseChartStyle(view, spec);

  const dim = (key, options = {}) => chartField(fieldByKey(dataset, key), { chartType: kind, ...options });
  const quota = (entry, index) => {
    const item = typeof entry === 'string' ? { field: entry } : entry;
    const field = fieldByKey(dataset, item.field);
    const made = chartField(field, { chartType: kind, index, label: item.label, agg: field.extField === 2 && !!field.gfmAgg, decimals: item.decimals, suffix: item.suffix, sort: item.sort, summary: item.summary });
    Object.defineProperty(made, 'gfmKeyOf', { value: item.field, enumerable: false });
    return made;
  };

  if (kind === 'rich-text') {
    view.yAxis = (spec.values || []).map((entry, i) => quota(entry, i));
    view.customStyle.text.show = false;
  } else if (kind === 't-heatmap') {
    view.xAxis = [dim(spec.x, { sort: 'asc', dateStyle: spec.dateStyle || 'y_M_d' })];
    view.xAxisExt = [dim(spec.y, { sort: 'asc' })];
    view.extColor = [quota(spec.value, 0)];
    view.customAttr.basicStyle.colors = spec.colors || HEAT;
    view.stylePriority = 'view'; // its own light-to-teal scale, not the dashboard's series colours
    view.customAttr.label.show = true;
    view.customAttr.label.color = COLORS.ink;
    view.customStyle.legend.show = true;
  } else if (kind === 'table-normal') {
    view.xAxis = (spec.columns || []).filter(c => c.dimension).map((c, i) => dim(c.field, { label: c.label, sort: c.sort, index: i }));
    view.yAxis = (spec.columns || []).filter(c => !c.dimension).map((c, i) => quota(c, i));
    view.customAttr.basicStyle.tablePageMode = 'pull';
    view.customAttr.basicStyle.tableColumnMode = 'adapt';
    view.customAttr.tableHeader.showIndex = false;
    view.customAttr.tableHeader.tableHeaderBgColor = '#f1f6f8';
    view.customAttr.tableHeader.tableHeaderFontColor = COLORS.ink;
    view.customAttr.tableCell.tableFontColor = COLORS.ink;
    view.customAttr.tableCell.tableItemBgColor = '#ffffff';
  } else {
    view.xAxis = [dim(spec.x, { sort: spec.xSort || (spec.sortBy ? 'none' : 'asc'), dateStyle: spec.dateStyle || 'y_M_d' })];
    view.yAxis = (spec.y || []).map((entry, i) => quota(entry, i));
    if (spec.sortBy) {
      const sortField = fieldByKey(dataset, spec.sortBy.field);
      const target = view.yAxis.find(f => f.id === sortField.id);
      if (!target) throw new Error(`Chart "${spec.id}" sorts by "${spec.sortBy.field}", which it does not show.`);
      target.sort = spec.sortBy.order || 'asc';
    }
    if (spec.labels) {
      view.customAttr.label.show = true;
      // Beside the end of a horizontal bar (DataEase would put it in the middle of the bar, hard to read there).
      if (kind === 'bar-horizontal') view.customAttr.label.position = 'right';
    }
    if (spec.assistLines?.length) {
      view.senior.assistLineCfg = {
        enable: true,
        assistLine: spec.assistLines.map((line, i) => ({
          id: `${spec.id}-line-${i}`, name: line.name, field: '0', fieldId: '', summary: 'avg', axis: 'left', value: String(line.value),
          lineType: 'dashed', color: line.color || COLORS.muted, fontSize: 11, curField: {}, yAxisType: 'left',
        })),
      };
    }
  }
  return view;
}

// ---- components --------------------------------------------------------------------------------------------------

/** {column} in a description becomes DataEase's live value [Field name] (the name people see in DataEase). */
export function richTextHtml(html, view) {
  return html.replace(/\{([a-z0-9_]+)\}/g, (_, key) => {
    const field = view.yAxis.find(f => f.gfmKeyOf === key);
    if (!field) throw new Error(`Rich text ${view.id} shows {${key}}, which is not among its values.`);
    return `<span class="mceNonEditable" contenteditable="false" data-mce-content="[${field.name}]">[${field.name}]</span>`;
  });
}

/** The box a chart sits in on the canvas: its place and size (spec.pos), a white card (or none: spec.plain). */
export function buildComponent(spec, base, dragId, view) {
  const component = clone(base.component);
  const kind = spec.type;
  Object.assign(component, {
    id: spec.id,
    name: spec.title || spec.id,
    label: spec.title || spec.id,
    component: 'UserView',
    innerType: kind,
    render: kind === 'rich-text' ? 'custom' : 'antv',
    x: spec.pos[0], y: spec.pos[1], sizeX: spec.pos[2], sizeY: spec.pos[3],
    propValue: kind === 'rich-text' ? { textValue: richTextHtml(spec.html || '', view), innerType: 'rich-text', render: 'custom' } : { textValue: '', urlList: [] },
    _dragId: dragId,
    linkageFilters: [],
  });
  component.style = { rotate: 0, opacity: 1, width: 0, height: 0, left: 0, top: 0 };
  component.commonBackground = {
    backgroundColorSelect: !spec.plain,
    backgroundImageEnable: false,
    backgroundType: 'innerImage',
    innerImage: 'board/board_1.svg',
    outerImage: null,
    innerPadding: spec.plain ? 4 : 12,
    borderRadius: 10,
    backgroundColor: spec.plain ? 'rgba(255, 255, 255, 0)' : 'rgba(255, 255, 255, 1)',
    innerImageColor: 'rgba(16, 148, 229,1)',
  };
  return component;
}

const WEEK_DATASETS = ['kpi-weeks', 'zone-heat', 'people-weeks'];

/** The filters row (DataEase "query component"): a select for zone and district and a week range. */
export function buildQuery(spec, views, datasets, dragId) {
  const conditions = spec.conditions.map((c, i) => {
    const checkedFields = [];
    const checkedFieldsMap = {};
    // Weeks apply to the charts over several weeks only; a "last complete week" chart keeps its week.
    const allowed = c.datasets || (c.kind === 'weeks' ? WEEK_DATASETS : null);
    for (const view of Object.values(views)) {
      if (view.type === 'rich-text' && !view.yAxis.length) continue;
      const [key, dataset] = Object.entries(datasets).find(([, d]) => d.id === view.tableId) || [];
      if (allowed && !allowed.includes(key)) continue;
      const field = dataset?.fields.find(f => f.gfmKey === c.field);
      if (!field) continue;
      checkedFields.push(view.id);
      checkedFieldsMap[view.id] = field.id;
    }
    const time = c.kind === 'weeks';
    return {
      id: `${spec.id}-${i + 1}`,
      name: c.label,
      showError: true,
      timeGranularity: 'date',
      timeGranularityMultiple: 'daterange',
      field: { id: '', type: time ? 'DATE' : 'VARCHAR', name: c.label, deType: time ? 1 : 0 },
      displayId: '',
      sortId: '',
      sort: 'asc',
      defaultMapValue: [],
      mapValue: [],
      conditionType: 0,
      conditionValueOperatorF: 'eq', conditionValueF: '', conditionValueOperatorS: 'like', conditionValueS: '',
      defaultConditionValueOperatorF: 'eq', defaultConditionValueF: '', defaultConditionValueOperatorS: 'like', defaultConditionValueS: '',
      timeType: 'fixed', relativeToCurrent: 'custom', required: false, timeNum: 0, relativeToCurrentType: 'date', around: 'f',
      parametersStart: null, parametersEnd: null, arbitraryTime: null, timeNumRange: 0, relativeToCurrentTypeRange: 'date', aroundRange: 'f',
      arbitraryTimeRange: null, auto: false, defaultValue: [], selectValue: [], optionValueSource: 0, valueSource: [],
      dataset: { id: '', name: '', fields: [] },
      visible: true, defaultValueCheck: false, multiple: !time, displayType: time ? '7' : '0',
      checkedFields, parameters: [], parametersCheck: false, parametersList: [], checkedFieldsMap,
      hideConditionSwitching: false, resultMode: 0, treeDatasetId: '', setTimeRange: false, showEmpty: false,
      defaultNumValueStart: null, defaultNumValueEnd: null, numValueEnd: null, numValueStart: null, displayFormat: 0,
      timeRange: { intervalType: 'none', dynamicWindow: false, maximumSingleQuery: 0, regularOrTrends: 'fixed', regularOrTrendsValue: '', relativeToCurrent: 'custom', timeNum: 0, relativeToCurrentType: 'year', around: 'f', timeNumRange: 0, relativeToCurrentTypeRange: 'year', aroundRange: 'f' },
      oldTreeLoad: false, treeCheckedList: [], defaultValueFirstItem: false, treeFieldList: [],
      placeholder: c.placeholder || '',
      // On a phone: narrower boxes, so they fit beside their labels (a range is two boxes), down to 320 px screens.
      mQueryConditionWidth: time ? 110 : 200,
      // On a computer: narrower than DataEase's 227 px (a range is two boxes), so Zone, District, Weeks and the
      // Query button fit on one line of a portal frame about 1000 px wide.
      queryConditionWidth: time ? 140 : (c.field === 'zone' ? 170 : 190),
    };
  });
  return {
    animations: [], canvasId: 'canvas-main', events: {}, groupStyle: {}, isLock: false, isShow: true,
    collapseName: ['position', 'background', 'style'],
    linkage: { duration: 0, data: [{ id: '', label: '', event: '', style: [{ key: '', value: '' }] }] },
    component: 'VQuery', name: spec.title || 'Filters', label: spec.title || 'Filters', propValue: conditions,
    icon: 'icon_search', innerType: 'VQuery', isHang: false, freeze: false,
    x: spec.pos[0], y: spec.pos[1], sizeX: spec.pos[2], sizeY: spec.pos[3],
    style: { rotate: 0, opacity: 1, width: 0, height: 0, left: 0, top: 0 },
    request: { method: 'GET', data: [], url: '', series: false, time: 1000, paramType: '', requestCount: 0 },
    matrixStyle: {},
    commonBackground: { backgroundColorSelect: true, backgroundImageEnable: false, backgroundType: 'innerImage', innerImage: 'board/board_1.svg', outerImage: null, innerPadding: 12, borderRadius: 10, backgroundColor: 'rgba(255, 255, 255, 1)', innerImageColor: 'rgba(16, 148, 229,1)' },
    state: 'ready', render: 'custom', id: spec.id, _dragId: dragId, show: true, linkageFilters: [], canvasActive: false,
  };
}

/** The page the dashboard is drawn on: size, background, font and the default look of its parts. */
export function buildCanvasStyle(base) {
  const style = clone(base.canvasStyle);
  Object.assign(style, {
    width: CANVAS.width, height: CANVAS.height,
    // Legends, axes and filters in a plain sans-serif (DataEase's default, Microsoft YaHei, is missing on many
    // computers, which then show a serif font).
    fontFamily: FONT_FAMILY,
    backgroundColorSelect: true, backgroundImageEnable: false, backgroundType: 'backgroundColor', background: '',
    backgroundColor: COLORS.page, color: COLORS.ink, fontSize: 14, refreshViewEnable: false,
  });
  style.dashboard = { ...(style.dashboard || {}), gap: 'yes', gapSize: 6, resultMode: 'all', resultCount: 1000, themeColor: 'light' };
  const component = style.component || {};
  if (component.chartTitle) Object.assign(component.chartTitle, { fontSize: '15', color: COLORS.ink, isBolder: true, fontFamily: 'Microsoft YaHei' });
  if (component.chartColor?.basicStyle) Object.assign(component.chartColor.basicStyle, { colorScheme: 'custom', colors: PALETTE, gradient: false });
  if (component.chartCommonStyle) Object.assign(component.chartCommonStyle, { backgroundColorSelect: true, backgroundImageEnable: false, backgroundColor: 'rgba(255, 255, 255, 1)', borderRadius: 10, innerPadding: 12 });
  if (component.filterStyle) Object.assign(component.filterStyle, { labelColor: COLORS.ink, titleColor: COLORS.ink, color: COLORS.ink, text: COLORS.ink, borderColor: COLORS.axis, bgColor: '#FFFFFF' });
  style.component = component;
  return style;
}

/**
 * The phone layout (DataEase's mobile page; the same 72 columns, stacked): every part full width in the order of
 * the computer layout, except key-number tiles narrower than a third of the page, which go two to a row.
 * A component may set "mobile": { "w": columns, "h": rows } in its dashboard file.
 */
export function mobileLayout(components) {
  const ordered = [...components].sort((a, b) => a.y - b.y || a.x - b.x);
  let y = 1, x = 1, rowHeight = 0;
  for (const c of ordered) {
    const own = c.gfmMobile || {};
    const text = c.innerType === 'rich-text';
    const plainText = text && c.commonBackground?.backgroundColorSelect === false; // a heading or a note
    const narrowTile = text && !plainText && c.sizeX < 24;
    const w = own.w || (narrowTile ? 36 : 72);
    const h = own.h || (c.component === 'VQuery' ? 12 : plainText ? Math.max(6, c.sizeY + 2) : text ? (narrowTile ? 9 : 8) : c.innerType === 'table-normal' ? 30 : 20);
    if (x + w - 1 > 72) { y += rowHeight; x = 1; rowHeight = 0; }
    Object.assign(c, { inMobile: true, mx: x, my: y, mSizeX: w, mSizeY: h });
    rowHeight = Math.max(rowHeight, h);
    x += w;
    if (x > 72) { y += rowHeight; x = 1; rowHeight = 0; }
  }
  for (const c of components) delete c.gfmMobile;
  return components;
}

/**
 * The whole dashboard: { id, name, canvasStyleData, componentData, canvasViewInfo }.
 * spec: a dataease/dashboards/*.json description; datasets: { key: { id, name, fields: [saved fields] } }.
 */
export function buildDashboard(spec, datasets, base = loadBase()) {
  const anyDatasetId = Object.values(datasets)[0]?.id || null;
  const ctx = { base, datasets, dashboardId: spec.id, anyDatasetId };
  const views = {};
  const components = [];
  let drag = 0;
  for (const item of spec.components) {
    if (item.type === 'filters') continue;
    views[item.id] = buildView(item, ctx);
    components.push(buildComponent(item, base, drag++, views[item.id]));
  }
  const filters = spec.components.find(c => c.type === 'filters');
  if (filters) components.splice(spec.components.indexOf(filters), 0, buildQuery(filters, views, datasets, drag++));
  // A part's own phone size ("mobile" in the dashboard file) is used by mobileLayout.
  for (const component of components) {
    const own = spec.components.find(item => item.id === component.id)?.mobile;
    if (own) component.gfmMobile = own;
  }
  mobileLayout(components);
  return {
    id: spec.id,
    name: spec.name,
    canvasStyleData: buildCanvasStyle(base),
    componentData: components,
    canvasViewInfo: views,
  };
}
