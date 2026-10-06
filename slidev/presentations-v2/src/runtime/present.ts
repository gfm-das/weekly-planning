// The V2 presentation: one generic Reveal.js runtime that draws any deck from its JSON (no build per deck).
//
// Reveal gives next/previous, keyboard, fullscreen (F), fragments, speaker notes (N shows them on the slide),
// Auto-Animate and the slide transitions. What is ours:
//  - the parts of a slide are drawn by components/parts.ts (the same code as the editor);
//  - SHARED CHARTS: charts on different slides with the same "transition id" are one ECharts instance that lives
//    above the slides. When the slide changes, the instance glides to the new chart's place while its option changes,
//    and ECharts' universalTransition morphs the bars/lines/pie into the new data. It is not a fade between two charts.
//  - STORY MODE: a chart with scenes gets one Reveal fragment per extra scene; each fragment draws the next scene on
//    the chart that is already there (setOption with universalTransition), so the chart morphs step by step.
import 'reveal.js/dist/reveal.css';
import './present.css';
import { GfmChartController, loadFrame, optionFor } from '../charts/controller';
import { renderPart, type PartHandle } from '../components/parts';
import { mark } from '../shared/perf';
import { isProjector, onProjector, setProjector, startProjector } from '../shared/projector';
import { SLIDE_H, SLIDE_W, type DataProps, type Deck, type Frame, type Part, type Slide } from '../shared/types';

interface SlideState { slide: Slide; section: HTMLElement; handles: PartHandle[] | null }
interface Layer { id: string; el: HTMLElement; controller: GfmChartController; visible: boolean; part: Part | null }

const isShared = (p: Part) => p.type === 'chart' && !!p.props.transitionId;
const sceneCount = (p: Part) => Math.max(1, (p.props.scenes || []).length);

function makePart(d: Document, part: Part): HTMLElement {
  const el = d.createElement('div');
  el.className = 'gfm-part';
  el.dataset.id = part.id; // Auto-Animate matches parts of neighbouring slides by this
  el.style.cssText = `left:${part.x}%;top:${part.y}%;width:${part.width}%;height:${part.height}%`;
  return el;
}

export async function startPresentation(host: HTMLElement, deck: Deck, slug: string): Promise<void> {
  const d = host.ownerDocument;
  host.className = 'reveal';
  const slidesEl = d.createElement('div');
  slidesEl.className = 'slides';
  host.replaceChildren(slidesEl);

  const states: SlideState[] = deck.slides.map(slide => {
    const section = d.createElement('section');
    // A slide with a shared chart always fades: the chart lives above the slides and would stay still while the rest slid.
    section.dataset.transition = slide.components.some(isShared) ? 'fade' : slide.transition;
    if (slide.autoAnimate) section.dataset.autoAnimate = '';
    const stage = d.createElement('div');
    stage.className = 'gfm-stage';
    section.appendChild(stage);
    for (const part of slide.components) {
      const el = makePart(d, part);
      stage.appendChild(el);
      if (part.type === 'chart' && sceneCount(part) > 1) {
        // Story mode: the first scene is shown at once; each further scene is one step (a Reveal fragment).
        for (let i = 1; i < sceneCount(part); i++) {
          const step = d.createElement('span');
          step.className = 'fragment gfm-step';
          step.dataset.fragmentIndex = String(i);
          step.dataset.gfmScene = part.id;
          stage.appendChild(step);
        }
      }
    }
    if (slide.notes) {
      const notes = d.createElement('aside');
      notes.className = 'notes';
      notes.textContent = slide.notes;
      section.appendChild(notes);
    }
    slidesEl.appendChild(section);
    return { slide, section, handles: null };
  });

  const { default: Reveal } = await import('reveal.js');
  const reveal = new Reveal(host, {
    width: SLIDE_W, height: SLIDE_H, margin: 0.03, center: false, hash: true, controls: true, progress: true, slideNumber: 'c/t',
    transition: 'slide', autoAnimateDuration: 0.8, autoAnimateEasing: 'ease-in-out', plugins: [],
  } as any);

  // ---- the parts of each slide, drawn when the slide is near ----
  const ensure = (i: number) => {
    const st = states[i];
    if (!st || st.handles) return;
    st.handles = st.slide.components.map((part, k) => {
      const el = st.section.querySelectorAll<HTMLElement>('.gfm-part')[k];
      return renderPart(el, part, { slug, skipChart: p => isShared(p) });
    });
  };
  const near = () => {
    const { h } = reveal.getIndices();
    [h, h + 1, h - 1].forEach(ensure);
  };

  // ---- shared charts ----
  const layers = new Map<string, Layer>();
  const frames = new WeakMap<Part, Frame>(); // by part (two slides may hold parts with the same id)
  const frameOf = async (part: Part) => {
    const hit = frames.get(part);
    if (hit) return hit;
    const frame = await loadFrame(slug, part.props as DataProps);
    frames.set(part, frame);
    return frame;
  };
  const layerFor = (id: string): Layer => {
    let layer = layers.get(id);
    if (!layer) {
      const el = d.createElement('div');
      el.className = 'gfm-shared-chart';
      host.appendChild(el);
      layer = { id, el, controller: new GfmChartController(el, slug), visible: false, part: null };
      layers.set(id, layer);
    }
    return layer;
  };
  const stageRect = () => (reveal.getSlidesElement() as HTMLElement).getBoundingClientRect();
  const place = (layer: Layer, part: Part, animate: boolean) => {
    const r = stageRect();
    const s = layer.el.style;
    s.transition = animate ? 'left .9s ease-in-out, top .9s ease-in-out, width .9s ease-in-out, height .9s ease-in-out, opacity .4s' : 'none';
    s.left = `${r.left + (part.x / 100) * r.width}px`;
    s.top = `${r.top + (part.y / 100) * r.height}px`;
    s.width = `${(part.width / 100) * r.width}px`;
    s.height = `${(part.height / 100) * r.height}px`;
  };
  const sceneOf = (section: HTMLElement, partId: string) => section.querySelectorAll(`.gfm-step[data-gfm-scene="${CSS.escape(partId)}"].visible`).length;

  async function syncLayers(animate: boolean) {
    const current = reveal.getCurrentSlide() as HTMLElement | undefined;
    const st = states.find(s => s.section === current);
    const here = new Map<string, Part>();
    st?.slide.components.filter(isShared).forEach(p => here.set(p.props.transitionId, p));
    for (const [id, part] of here) {
      const layer = layerFor(id);
      const frame = await frameOf(part);
      if (reveal.getCurrentSlide() !== current) return; // the person moved on while the numbers loaded
      const option = optionFor(frame, part.props as DataProps, sceneOf(current!, part.id));
      const glide = animate && layer.visible;
      place(layer, part, glide);
      layer.el.style.opacity = '1';
      layer.visible = true;
      layer.part = part;
      await layer.controller.applyOption(option); // same instance, new option: universalTransition morphs it
      mark('first chart render');
    }
    for (const [id, layer] of layers) {
      if (!here.has(id)) { layer.el.style.opacity = '0'; layer.visible = false; layer.part = null; }
    }
  }

  const scenes = () => {
    const current = reveal.getCurrentSlide() as HTMLElement | undefined;
    const st = states.find(s => s.section === current);
    if (!st || !current) return;
    st.slide.components.forEach((part, k) => {
      if (part.type !== 'chart' || sceneCount(part) < 2) return;
      const scene = sceneOf(current, part.id);
      if (isShared(part)) {
        const layer = layers.get(part.props.transitionId);
        const frame = frames.get(part);
        if (layer && frame) void layer.controller.applyOption(optionFor(frame, part.props as DataProps, scene));
      } else {
        st.handles?.[k]?.chart?.setScene(scene);
      }
    });
  };

  const changed = (animate: boolean) => { near(); void syncLayers(animate); };
  reveal.on('ready', () => { mark('first render'); changed(false); });
  reveal.on('slidechanged', () => changed(true));
  reveal.on('resize', () => { for (const l of layers.values()) if (l.part && l.visible) place(l, l.part, false); });
  reveal.on('fragmentshown', scenes);
  reveal.on('fragmenthidden', scenes);
  d.addEventListener('keydown', e => { if (e.key === 'n' || e.key === 'N') reveal.configure({ showNotes: !reveal.getConfig().showNotes } as any); });

  // ---- projector ----
  startProjector();
  const toolbar = d.createElement('div');
  toolbar.className = 'gfm-toolbar';
  const button = (label: string, title: string, run: () => void) => {
    const b = d.createElement('button');
    b.type = 'button'; b.textContent = label; b.title = title; b.setAttribute('aria-label', title);
    b.addEventListener('click', e => { e.stopPropagation(); run(); b.blur(); });
    toolbar.appendChild(b);
    return b;
  };
  const toggleFullscreen = () => { if (d.fullscreenElement) void d.exitFullscreen(); else void d.documentElement.requestFullscreen?.().catch(() => {}); };
  button('⛶', 'Fullscreen (F)', toggleFullscreen);
  const pBtn = button('◐', 'Projector mode: larger text, black surround (P)', () => setProjector(!isProjector()));
  button('✎', 'Speaker notes (N)', () => reveal.configure({ showNotes: !reveal.getConfig().showNotes } as any));
  button('?', 'Keyboard help', () => reveal.toggleHelp());
  host.appendChild(toolbar);
  const lookOfProjector = () => {
    pBtn.setAttribute('aria-pressed', String(isProjector()));
    pBtn.classList.toggle('on', isProjector());
    reveal.configure({ margin: isProjector() ? 0 : 0.03 } as any);
    reveal.layout();
    void syncLayers(false); // shared charts are redrawn in the new look and put in the stage's new place
  };
  onProjector(lookOfProjector);
  // Fullscreen means a projector or a big screen: switch to projector mode for it, and back afterwards.
  let beforeFullscreen = false;
  d.addEventListener('fullscreenchange', () => {
    if (d.fullscreenElement) { beforeFullscreen = isProjector(); setProjector(true, false); } else setProjector(beforeFullscreen, false);
  });
  d.addEventListener('keydown', e => {
    if ((e.key === 'p' || e.key === 'P') && !e.ctrlKey && !e.metaKey && !e.altKey) setProjector(!isProjector());
  });
  // Nothing but the slide: after 3 s without the mouse or a key, the cursor, toolbar, arrows and progress bar fade away.
  let idle = 0;
  const awake = () => { host.classList.remove('gfm-idle'); clearTimeout(idle); idle = window.setTimeout(() => host.classList.add('gfm-idle'), 3000); };
  for (const type of ['mousemove', 'mousedown', 'keydown', 'touchstart']) d.addEventListener(type, awake, { passive: true });
  awake();
  // The screen stays on while presenting (a browser needs one tap or key first; losing it, for example by switching tabs, asks again).
  let lock: any = null;
  const keepAwake = async () => {
    try { lock = await (navigator as any).wakeLock?.request('screen'); lock?.addEventListener?.('release', () => { lock = null; }); } catch { /* not allowed or not supported: fine */ }
  };
  d.addEventListener('click', () => { if (!lock) void keepAwake(); });
  d.addEventListener('keydown', () => { if (!lock) void keepAwake(); });
  d.addEventListener('visibilitychange', () => { if (d.visibilityState === 'visible' && !lock) void keepAwake(); });

  await reveal.initialize();
  lookOfProjector();
  // Numbers for the shared charts are asked for at once (in parallel), so the first morph does not wait for the network.
  void Promise.all(deck.slides.flatMap(s => s.components.filter(isShared)).map(p => frameOf(p).catch(() => null)));
}
