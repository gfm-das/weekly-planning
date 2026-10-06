// GfmChart: the one chart component of V2. The editor's slide canvas and the Reveal presentation both use it, so a
// chart looks and behaves the same in both. (It is plain TypeScript, not a Vue component, because the editor draws
// inside GrapesJS's own frame, where Vue does not run.)
//
// data (portal-api, through the manager) -> Arquero (calculated fields, filter, sort, select) -> Frame -> preset ->
// ECharts option -> safeChartOption (the manager address never draws HTML written by someone else) -> ECharts.
import { safeChartOption } from '../../../manager/safe-chart-option.mjs';
import { computeFrame } from '../data/worker-api';
import { queryChart } from '../shared/api';
import { mark, timed } from '../shared/perf';
import type { DataProps, Frame } from '../shared/types';
import { isProjector, onProjector, projectorOption } from '../shared/projector';
import { buildOption } from './presets';

/** The numbers of a data part as a Frame (calculated fields and sorting done, in the data worker). */
export async function loadFrame(slug: string, props: DataProps): Promise<Frame> {
  return computeFrame(await queryChart(slug, props.query), props);
}

/** The frame with only the fields of a scene (story mode); no scene or an empty one: all of them. */
export function sceneFrame(frame: Frame, props: DataProps, scene: number): Frame {
  const wanted = props.scenes?.[scene]?.fields;
  if (!wanted?.length) return frame;
  return { ...frame, fields: frame.fields.filter(f => wanted.includes(f.key)) };
}

export function optionFor(frame: Frame, props: DataProps, scene = 0): Record<string, any> {
  const shown = sceneFrame(frame, props, scene);
  const option = buildOption(props.chartType, shown, props.title || undefined);
  const safe = safeChartOption(props.advanced ? mergeAdvanced(option, props.advanced) : option);
  return isProjector() ? projectorOption(safe) : safe;
}

function mergeAdvanced(option: any, extra: any): any {
  if (Array.isArray(extra) || typeof extra !== 'object' || extra === null) return option;
  const out: any = { ...option };
  for (const [key, value] of Object.entries(extra)) {
    if (key === '__proto__' || key === 'constructor' || key === 'prototype') continue;
    if (key === 'series' && Array.isArray(value)) out.series = (option.series || []).map((s: any, i: number) => ({ ...s, ...(typeof value[i] === 'object' && value[i] ? value[i] : {}) }));
    else if (value && typeof value === 'object' && !Array.isArray(value) && out[key] && typeof out[key] === 'object' && !Array.isArray(out[key])) out[key] = mergeAdvanced(out[key], value);
    else out[key] = value;
  }
  return out;
}

export class GfmChartController {
  chart: import('echarts/core').ECharts | null = null;
  frame: Frame | null = null;
  props: DataProps | null = null;
  scene = 0;
  private note: HTMLElement;
  private watcher: ResizeObserver | null = null;
  private serial = 0;
  private stopProjector: () => void;

  constructor(public el: HTMLElement, public slug: string) {
    this.note = el.ownerDocument.createElement('div');
    this.note.style.cssText = 'position:absolute;inset:auto 8px 4px auto;font:12px system-ui,sans-serif;color:#556d7a;pointer-events:none;z-index:1';
    if (getComputedStyle(el).position === 'static') el.style.position = 'relative';
    // Projector mode on or off: draw the same numbers again in the other look.
    this.stopProjector = onProjector(() => this.setScene(this.scene));
  }

  private say(text: string, error = false) {
    this.note.textContent = text;
    this.note.style.color = error ? '#b42318' : '#556d7a';
    if (!this.note.parentNode) this.el.appendChild(this.note);
  }

  private async ensureChart() {
    if (this.chart) return this.chart;
    const { echarts } = await import('./echarts-setup');
    this.chart = echarts.init(this.el, undefined, { renderer: 'canvas' });
    this.watcher = new ResizeObserver(() => this.chart?.resize());
    this.watcher.observe(this.el);
    return this.chart;
  }

  /** Loads the numbers for `props` and draws the chart (scene `scene`). A failure is written in the chart, not thrown. */
  async setConfig(props: DataProps, scene = 0): Promise<void> {
    const mine = ++this.serial;
    this.props = props;
    this.scene = scene;
    try {
      const frame = await loadFrame(this.slug, props);
      if (mine !== this.serial) return;
      this.frame = frame;
      const chart = await this.ensureChart();
      this.note.textContent = frame.meta?.suppressed ? 'Small counts are hidden.' : '';
      if (!frame.labels.length) this.say('No numbers for this chart yet.');
      chart.setOption(optionFor(frame, props, scene) as any, { notMerge: true, lazyUpdate: false });
      mark('first chart render');
    } catch (error) {
      if (mine === this.serial) this.say((error as Error).message || 'The numbers could not load.', true);
    }
  }

  /** Story mode: draws scene `i` on the chart that is already there (ECharts morphs the change). */
  setScene(i: number) {
    if (!this.chart || !this.frame || !this.props) return;
    this.scene = i;
    this.chart.setOption(optionFor(this.frame, this.props, i) as any, { notMerge: true, lazyUpdate: false });
  }

  /** Draws a ready option (the presentation's shared chart moves between slides this way). */
  applyOption(option: Record<string, any>) {
    return this.ensureChart().then(chart => chart.setOption(option as any, { notMerge: true, lazyUpdate: false }));
  }

  resize() { this.chart?.resize(); }

  dispose() {
    this.serial++;
    this.stopProjector();
    this.watcher?.disconnect();
    this.chart?.dispose();
    this.chart = null;
    this.note.remove();
  }
}

export { timed };
