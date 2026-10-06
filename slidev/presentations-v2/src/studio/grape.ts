// GrapesJS Core as the slide canvas. One editor shows the selected slide; the order of slides and every slide's data
// live outside it (the deck), so a slide is loaded into the editor when it is selected and read back when left.
//
// GrapesJS gives: selecting, dragging (absolute mode), resizing, undo, keyboard delete/copy/paste, drag from blocks.
// What is ours: one component type, "gfm-part", whose look comes from components/parts.ts (the same code Reveal
// uses) and whose settings (`gfmProps`) are plain data. Nothing is saved as GrapesJS HTML: a deck is the JSON of
// parts (x, y, width, height in percent of a 960 x 540 slide), which is what the server checks and Reveal draws.
import grapesjs, { type Component, type Editor } from 'grapesjs';
import 'grapesjs/dist/css/grapes.min.css';
import { renderPart, type PartHandle } from '../components/parts';
import { SLIDE_H, SLIDE_W, type Part, type PartType, type Slide } from '../shared/types';

export const PART_LABELS: Record<PartType, string> = {
  text: 'Text', heading: 'Heading', image: 'Image', shape: 'Shape', chart: 'GFM Chart', kpi: 'GFM KPI', table: 'GFM Table',
};

const px = (n: number) => `${Math.round(n * 10) / 10}px`;
const num = (v: unknown, fallback: number) => { const n = parseFloat(String(v ?? '')); return Number.isFinite(n) ? n : fallback; };
export const newId = (prefix: string) => `${prefix}-${Math.random().toString(36).slice(2, 8)}`;

export function defaultPart(type: PartType): Part {
  const sizes: Record<PartType, [number, number]> = { text: [40, 14], heading: [70, 14], image: [30, 40], shape: [20, 20], chart: [80, 70], kpi: [26, 24], table: [60, 50] };
  const [width, height] = sizes[type];
  const props: Record<string, any> = {
    text: { text: 'Text', size: 28, color: '#193746' }, heading: { text: 'Heading', size: 48, color: '#17394b' },
    image: { asset: '', alt: '' }, shape: { color: '#087f8c', round: false },
  }[type as 'text'] ?? {
    title: '', chartType: 'bar', transitionId: '', calcs: [], fields: [], sortBy: '', sortDir: 'none', scenes: [], advanced: null, filter: null,
    query: { v: 1, measures: ['friends_found.actual'], level: 'zone', by: 'unit', filter: {}, weeks: { last: 1 }, includeCurrent: true, transform: 'none', sort: 'none', top: 0 },
  };
  return { id: newId(type), type, x: 10, y: 10, width, height, props };
}

export interface StudioEditor {
  editor: Editor;
  load(slide: Slide): void;
  read(): Part[];
  addPart(type: PartType): void;
  setPartProps(model: Component, props: Record<string, any>): void;
  fit(): void;
}

export function createEditor(container: HTMLElement, slug: string, hooks: { dirty(): void; selected(model: Component | null): void }): StudioEditor {
  const handles = new WeakMap<object, PartHandle>();
  const partOf = (model: Component): Part => ({
    id: model.get('gfmId'), type: model.get('gfmType'), x: 0, y: 0, width: 0, height: 0, props: model.get('gfmProps') || {},
  });

  const editor = grapesjs.init({
    container, height: '100%', width: 'auto', fromElement: false, storageManager: false,
    // Nothing is fetched from or sent to anywhere else: no Font Awesome from a CDN (the toolbar uses text symbols) and
    // no usage telemetry (the manager's policy would refuse both anyway).
    cssIcons: '', telemetry: false,
    panels: { defaults: [] }, deviceManager: { devices: [] },
    dragMode: 'absolute',
    richTextEditor: { actions: [] },
    selectorManager: { componentFirst: true },
    canvas: {
      styles: [],
    },
    undoManager: { trackSelection: false },
  });

  editor.Components.addType('gfm-part', {
    isComponent: () => false,
    model: {
      defaults: {
        tagName: 'div', droppable: false, draggable: true, removable: true, copyable: true, selectable: true, highlightable: true,
        resizable: { tl: 1, tc: 1, tr: 1, cl: 1, cr: 1, bl: 1, bc: 1, br: 1, unitWidth: 'px', unitHeight: 'px', keyWidth: 'width', keyHeight: 'height' },
        stylable: ['top', 'left', 'width', 'height'],
        traits: [],
        toolbar: [
          { label: '✥', attributes: { title: 'Move', style: 'cursor:move' }, command: 'tlb-move' },
          { label: '⧉', attributes: { title: 'Copy' }, command: 'tlb-clone' },
          { label: '✕', attributes: { title: 'Delete' }, command: 'tlb-delete' },
        ],
        gfmId: '', gfmType: 'text', gfmProps: {},
      },
    },
    view: {
      init() {
        this.listenTo(this.model, 'change:gfmProps', () => {
          const handle = handles.get(this as any);
          handle?.update({ ...partOf(this.model as Component) });
          hooks.dirty();
        });
      },
      onRender({ el, model }: { el: HTMLElement; model: Component }) {
        handles.get(this as any)?.destroy();
        el.style.position = 'absolute';
        el.style.overflow = 'hidden';
        handles.set(this as any, renderPart(el, partOf(model), { slug }));
      },
      onRemove() { handles.get(this as any)?.destroy(); },
    },
  });

  editor.on('load', () => {
    const wrapper = editor.getWrapper();
    wrapper?.setStyle({ position: 'relative', width: px(SLIDE_W), height: px(SLIDE_H), background: '#ffffff', overflow: 'hidden', margin: '24px auto', 'box-shadow': '0 2px 14px rgba(20,40,50,.25)' });
    const frame = editor.Canvas.getFrameEl();
    const style = frame.contentDocument!.createElement('style');
    style.textContent = 'html{background:#dfe7ea} body{min-height:0} .gjs-selected{outline:2px solid #087f8c !important}';
    frame.contentDocument!.head.appendChild(style);
    fit();
  });
  // `update` is GrapesJS's own "something changed" event (add, remove, move, resize, undo).
  editor.on('update', () => hooks.dirty());
  editor.on('component:selected', (m: Component) => hooks.selected(m.get('gfmType') ? m : null));
  editor.on('component:deselected', () => hooks.selected(null));

  // The frame is a fixed 992 x 588 (the slide plus a margin) scaled to fit the middle column: GrapesJS then keeps
  // dragging and resizing exact at any zoom.
  function fit() {
    const w = container.clientWidth, h = container.clientHeight;
    const frame = editor.Canvas.getFrames()[0];
    if (!w || !h || !frame) return;
    const fw = SLIDE_W + 32, fh = SLIDE_H + 48;
    frame.set({ width: `${fw}px`, height: `${fh}px`, x: (w - fw) / 2, y: (h - fh) / 2 } as any);
    editor.Canvas.setZoom(Math.max(15, Math.min(150, Math.min(w / fw, h / fh) * 96)));
  }
  new ResizeObserver(fit).observe(container);

  const modelDef = (part: Part) => ({
    type: 'gfm-part', gfmId: part.id, gfmType: part.type, gfmProps: part.props,
    style: { position: 'absolute', left: px((part.x / 100) * SLIDE_W), top: px((part.y / 100) * SLIDE_H), width: px((part.width / 100) * SLIDE_W), height: px((part.height / 100) * SLIDE_H) },
  });

  return {
    editor,
    fit,
    load(slide) {
      editor.UndoManager.clear();
      editor.getWrapper()?.components().reset();
      editor.addComponents(slide.components.map(modelDef) as any);
      editor.select(undefined as any);
    },
    read() {
      const seen = new Set<string>();
      return (editor.getWrapper()?.components().models ?? []).filter(m => m.get('gfmType')).map(model => {
        const st = model.getStyle() as Record<string, string>;
        const clamp = (n: number) => Math.round(Math.min(100, Math.max(0, n)) * 100) / 100;
        let id = String(model.get('gfmId'));
        if (seen.has(id)) { id = newId(String(model.get('gfmType'))); model.set('gfmId', id); } // a pasted copy gets its own id
        seen.add(id);
        return {
          id, type: model.get('gfmType') as PartType,
          x: clamp((num(st.left, 0) / SLIDE_W) * 100), y: clamp((num(st.top, 0) / SLIDE_H) * 100),
          width: clamp((num(st.width, 100) / SLIDE_W) * 100), height: clamp((num(st.height, 50) / SLIDE_H) * 100),
          props: JSON.parse(JSON.stringify(model.get('gfmProps') || {})),
        };
      });
    },
    addPart(type) {
      const part = defaultPart(type);
      // Each new part sits a little lower and to the right of the last, so it does not hide it.
      const shift = ((editor.getWrapper()?.components().length ?? 0) % 6) * 3;
      part.x += shift; part.y += shift;
      const [added] = editor.addComponents(modelDef(part) as any);
      editor.select(added);
    },
    setPartProps(model, props) { model.set('gfmProps', props); },
  };
}
