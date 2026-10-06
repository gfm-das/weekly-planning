// Chart presets: a Frame (labels and fields) in, an ECharts option out. No 200 controls: the preset decides.
// Every series has a stable `id` (the field) and every data item an `id` (its label), with universalTransition on,
// so changing the data, the fields or the preset makes ECharts morph the old chart into the new one.
import type { ChartKind, Frame } from '../shared/types';

// The GFM palette and text colours (the same as the Slidev charts: manager/gfm-addon/lib/chart-core.mjs).
export const PALETTE = ['#00869e', '#d96b2b', '#6656c9', '#b88400', '#a64f8e', '#3f8a3a', '#2a5f99', '#cf4545'];
export const INK = '#17394b';
const SOFT = '#3d5866', GRID = '#e3eaee', AXIS = '#b8c6cd';
const FONT = 'Inter, system-ui, -apple-system, "Segoe UI", sans-serif';
export const ANIMATION = { animationDuration: 900, animationDurationUpdate: 1100, animationEasing: 'cubicOut', animationEasingUpdate: 'cubicInOut' } as const;

type Field = Frame['fields'][number];

export function formatValue(v: number | null | undefined, format: Field['format']): string {
  if (v == null || !Number.isFinite(v)) return '–';
  if (format === 'percent') return `${(v * 100).toLocaleString(undefined, { maximumFractionDigits: 1 })}%`;
  return v.toLocaleString(undefined, { maximumFractionDigits: 2 });
}

const axisLabel = { color: SOFT, fontFamily: FONT, fontSize: 13 };
const base = (frame: Frame, title?: string) => ({
  color: PALETTE,
  backgroundColor: 'transparent',
  textStyle: { fontFamily: FONT, color: INK },
  title: title ? { text: title, left: 0, top: 0, textStyle: { color: INK, fontSize: 18, fontWeight: 600, fontFamily: FONT } } : undefined,
  tooltip: { trigger: 'item', renderMode: 'richText', confine: true },
  legend: frame.fields.length > 1 ? { top: title ? 30 : 4, textStyle: { color: SOFT, fontSize: 13, fontFamily: FONT } } : undefined,
  ...ANIMATION,
});

function cartesian(frame: Frame, type: 'bar' | 'line', opts: { title?: string; horizontal?: boolean; area?: boolean }) {
  const horizontal = !!opts.horizontal;
  const percentFields = frame.fields.filter(f => f.format === 'percent').length;
  // Counts and percentages in one chart: percentages get their own axis on the other side.
  const mixed = percentFields > 0 && percentFields < frame.fields.length;
  const mainFormat: Field['format'] = mixed || percentFields === 0 ? 'number' : 'percent';
  const category = { type: 'category', data: frame.labels, axisLabel, axisLine: { lineStyle: { color: AXIS } }, axisTick: { show: false }, inverse: horizontal };
  const valueAxis = (format: Field['format'], second = false) => ({
    type: 'value', axisLabel: { ...axisLabel, formatter: (v: number) => formatValue(v, format) },
    splitLine: { show: !second, lineStyle: { color: GRID } }, ...(second ? { position: horizontal ? 'top' : 'right' } : {}),
  });
  const values = [valueAxis(mainFormat), ...(mixed ? [valueAxis('percent', true)] : [])];
  const top = (opts.title ? 34 : 8) + (frame.fields.length > 1 ? 30 : 0);
  return {
    ...base(frame, opts.title),
    tooltip: { trigger: 'axis', renderMode: 'richText', confine: true, valueFormatter: (v: number) => formatValue(v, mainFormat) },
    grid: { left: 8, right: horizontal ? 56 : mixed ? 48 : 16, top: horizontal && mixed ? top + 18 : top, bottom: 8, containLabel: true },
    xAxis: horizontal ? values : category,
    yAxis: horizontal ? category : values,
    series: frame.fields.map(f => ({
      id: `s${f.slot}`, name: f.label, type,
      ...(horizontal ? { xAxisIndex: mixed && f.format === 'percent' ? 1 : 0 } : { yAxisIndex: mixed && f.format === 'percent' ? 1 : 0 }),
      ...(opts.area ? { areaStyle: { opacity: 0.25 }, smooth: true } : type === 'line' ? { smooth: true } : {}),
      ...(type === 'bar' ? { barMaxWidth: 64, itemStyle: { borderRadius: horizontal ? [0, 6, 6, 0] : [6, 6, 0, 0] } } : { symbolSize: 8 }),
      data: frame.labels.map((label, k) => ({ id: label, name: label, value: f.values[k] ?? null })),
      label: frame.fields.length <= 3 && frame.labels.length <= 14 && type === 'bar'
        ? { show: true, position: horizontal ? 'right' : 'top', color: SOFT, fontSize: 12, fontFamily: FONT, formatter: (p: any) => formatValue(p.value, f.format) }
        : { show: false },
      universalTransition: { enabled: true },
    })),
  };
}

function pie(frame: Frame, title?: string) {
  const f = frame.fields[0];
  return {
    ...base(frame, title), legend: { type: 'scroll', bottom: 0, textStyle: { color: SOFT, fontSize: 13, fontFamily: FONT } },
    series: [{
      id: 's0', type: 'pie', radius: ['38%', '68%'], center: ['50%', '48%'],
      label: { color: SOFT, fontFamily: FONT, fontSize: 13, formatter: (p: any) => `${p.name}\n${formatValue(p.value, f?.format ?? 'number')}` },
      data: frame.labels.map((label, k) => ({ id: label, name: label, value: f?.values[k] ?? 0 })),
      universalTransition: { enabled: true },
    }],
  };
}

function funnel(frame: Frame, title?: string) {
  const f = frame.fields[0];
  // One row (the mission) and several fields: the fields are the stages of the funnel.
  const stages = frame.labels.length === 1 && frame.fields.length > 1;
  const rows = (stages ? frame.fields.map(x => ({ label: x.label, v: x.values[0] ?? 0 })) : frame.labels.map((label, k) => ({ label, v: f?.values[k] ?? 0 }))).sort((a, b) => b.v - a.v);
  return {
    ...base(frame, title), legend: undefined,
    series: [{
      id: 's0', type: 'funnel', left: '8%', right: '8%', top: title ? 44 : 12, bottom: 12, sort: 'descending', gap: 4,
      label: { color: '#fff', fontFamily: FONT, fontSize: 14, formatter: (p: any) => `${p.name}  ${formatValue(p.value, f?.format ?? 'number')}` },
      data: rows.map(r => ({ id: r.label, name: r.label, value: r.v })),
      universalTransition: { enabled: true },
    }],
  };
}

function gauge(frame: Frame, title?: string) {
  const f = frame.fields[0];
  const value = f?.values.find(v => v != null) ?? 0;
  const max = f?.format === 'percent' ? 1 : Math.max(10, Math.pow(10, Math.ceil(Math.log10(Math.max(value, 1) + 1))));
  return {
    ...base(frame, title), legend: undefined,
    series: [{
      id: 's0', type: 'gauge', min: 0, max, progress: { show: true, width: 18 }, axisLine: { lineStyle: { width: 18 } },
      axisTick: { show: false }, splitLine: { length: 10 }, axisLabel: { color: SOFT, fontFamily: FONT, formatter: (v: number) => formatValue(v, f?.format ?? 'number') },
      detail: { valueAnimation: true, color: INK, fontFamily: FONT, fontSize: 34, formatter: (v: number) => formatValue(v, f?.format ?? 'number') },
      title: { color: SOFT, fontFamily: FONT }, data: [{ id: frame.labels[0] ?? 'value', name: f?.label ?? '', value }],
    }],
  };
}

function scatter(frame: Frame, title?: string) {
  const [fx, fy] = frame.fields;
  const fmt = (f?: Field) => (v: number) => formatValue(v, f?.format ?? 'number');
  return {
    ...base(frame, title), legend: undefined,
    tooltip: { trigger: 'item', renderMode: 'richText', confine: true, formatter: (p: any) => `${p.data?.name}\n${fx?.label}: ${formatValue(p.value?.[0], fx?.format ?? 'number')}\n${fy?.label ?? ''}: ${formatValue(p.value?.[1], fy?.format ?? 'number')}` },
    grid: { left: 8, right: 24, top: title ? 44 : 12, bottom: 8, containLabel: true },
    xAxis: { type: 'value', name: fx?.label, nameLocation: 'middle', nameGap: 28, axisLabel: { ...axisLabel, formatter: fmt(fx) }, splitLine: { lineStyle: { color: GRID } } },
    yAxis: { type: 'value', name: fy?.label, axisLabel: { ...axisLabel, formatter: fmt(fy) }, splitLine: { lineStyle: { color: GRID } } },
    series: [{
      id: 's0', type: 'scatter', symbolSize: 16,
      data: frame.labels.map((label, k) => ({ id: label, name: label, value: [fx?.values[k] ?? null, fy?.values[k] ?? fx?.values[k] ?? null] })),
      label: { show: frame.labels.length <= 14, formatter: (p: any) => p.data.name, position: 'right', color: SOFT, fontFamily: FONT, fontSize: 12 },
      universalTransition: { enabled: true },
    }],
  };
}

/** The ECharts option of a preset for a frame. */
export function buildOption(kind: ChartKind, frame: Frame, title?: string): Record<string, any> {
  switch (kind) {
    case 'line': return cartesian(frame, 'line', { title });
    case 'area': return cartesian(frame, 'line', { title, area: true });
    case 'ranked-bar': {
      // The same table, biggest first, drawn sideways (rank 1 on top).
      const f = frame.fields[0];
      const order = frame.labels.map((_, i) => i).sort((a, b) => (f?.values[b] ?? -Infinity) - (f?.values[a] ?? -Infinity));
      const ranked: Frame = { ...frame, labels: order.map(i => frame.labels[i]), fields: frame.fields.map(x => ({ ...x, values: order.map(i => x.values[i]) })) };
      return cartesian(ranked, 'bar', { title, horizontal: true });
    }
    case 'pie': return pie(frame, title);
    case 'funnel': return funnel(frame, title);
    case 'gauge': return gauge(frame, title);
    case 'scatter': return scatter(frame, title);
    case 'bar':
    default: return cartesian(frame, 'bar', { title });
  }
}

export const CHART_KIND_LABELS: Record<ChartKind, string> = {
  bar: 'Bar', 'ranked-bar': 'Ranked bar', line: 'Line', area: 'Area', pie: 'Pie', gauge: 'Gauge', funnel: 'Funnel', scatter: 'Scatter',
};
