// The V2 deck as saved (the server checks it again: manager/v2-deck.mjs).
export type PartType = 'text' | 'heading' | 'image' | 'chart' | 'kpi' | 'table' | 'shape';
export type ChartKind = 'bar' | 'ranked-bar' | 'line' | 'area' | 'pie' | 'gauge' | 'funnel' | 'scatter';

export interface Calc { name: string; label: string; formula: string; format: 'number' | 'percent' }
export interface Scene { name: string; fields: string[] }
export interface ValueFilter { field: string; op: '>' | '>=' | '<' | '<='; value: number }

export interface DataProps {
  title: string;
  query: Record<string, any>;
  chartType: ChartKind;
  transitionId: string;
  calcs: Calc[];
  fields: string[];
  sortBy: string;
  sortDir: 'none' | 'desc' | 'asc';
  filter?: ValueFilter | null;
  scenes: Scene[];
  advanced: Record<string, any> | null;
}

export interface Part {
  id: string;
  type: PartType;
  x: number; y: number; width: number; height: number; // percent of the 960 x 540 slide
  props: Record<string, any>;
}

export interface Slide { id: string; transition: string; autoAnimate: boolean; notes: string; components: Part[] }
export interface Deck { version: 1; name: string; theme: 'gfm'; slides: Slide[] }

/** portal-api's chart answer (charts.py run_chart). */
export interface ChartAnswer {
  table: { labels: string[]; series: { name: string; values: (number | null)[]; role?: string }[] };
  meta: { suppressed?: boolean; stewardship?: boolean; weeks?: string[]; unit?: string; [k: string]: any };
}

/** A table the charts draw: one row per label, one column per field (a measure or a calculated field). */
export interface Frame {
  labels: string[];
  fields: { key: string; slot: number; label: string; values: (number | null)[]; format: 'number' | 'percent'; role?: string }[];
  meta: ChartAnswer['meta'];
}

export const SLIDE_W = 960;
export const SLIDE_H = 540;

export const TRANSITIONS_LIST = ['none', 'fade', 'slide', 'convex', 'concave', 'zoom'];
