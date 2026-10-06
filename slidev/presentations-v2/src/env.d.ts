/// <reference types="vite/client" />
declare module '*.vue' {
  import type { DefineComponent } from 'vue';
  const component: DefineComponent<object, object, unknown>;
  export default component;
}
declare module '../../../manager/gfm-addon/lib/chart-spec.mjs' {
  export function normalizeSpec(raw: unknown): Record<string, any>;
  export function canonicalJson(value: unknown): string;
  export class SpecError extends Error {}
}
declare module '../../../manager/safe-chart-option.mjs' {
  export function safeChartOption(option: any): any;
}
declare module 'reveal.js' {
  const Reveal: any;
  export default Reveal;
}
declare module 'reveal.js/dist/reveal.css';
