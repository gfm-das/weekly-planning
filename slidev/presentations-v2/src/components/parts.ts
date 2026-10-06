// How each part of a slide is drawn. The editor's canvas and the Reveal presentation both call renderPart, so there is
// one implementation. Text is always set as text (never as HTML): a deck is data, and the manager address, where the
// sign-in lives, must never run markup someone else wrote.
import { GfmChartController, loadFrame } from '../charts/controller';
import { formatValue } from '../charts/presets';
import { assetUrl } from '../shared/api';
import { onProjector } from '../shared/projector';
import type { DataProps, Part } from '../shared/types';

export interface PartHandle {
  update(part: Part): void;
  destroy(): void;
  chart?: GfmChartController;
}

export interface PartContext {
  slug: string;
  /** Charts that share a transition id are drawn by the presentation's shared chart layer, not inside the slide. */
  skipChart?: (part: Part) => boolean;
}

const doc = (el: HTMLElement) => el.ownerDocument;

function box(el: HTMLElement, part: Part) {
  el.dataset.partType = part.type;
  el.dataset.partId = part.id;
}

function text(el: HTMLElement, part: Part, tag: 'div' | 'h1'): PartHandle {
  const inner = doc(el).createElement(tag);
  inner.style.cssText = 'margin:0;width:100%;height:100%;overflow:hidden;white-space:pre-wrap;word-break:break-word;font-family:Inter,system-ui,sans-serif;line-height:1.2;text-align:left;text-transform:none';
  el.replaceChildren(inner);
  let size = 28;
  // Projector mode makes text bigger; text that then no longer fits its box is made smaller again until it does.
  const fit = () => {
    const scale = parseFloat(el.ownerDocument.documentElement.style.getPropertyValue('--gfm-text-scale')) || 1;
    for (let k = 1; k >= 0.5; k -= 0.05) {
      inner.style.fontSize = `${Math.round(size * scale * k * 10) / 10}px`;
      if (!inner.clientHeight || inner.scrollHeight <= inner.clientHeight + 1) break;
    }
  };
  const watcher = new ResizeObserver(fit); // also runs when a hidden slide is shown (its parts have no size before that)
  watcher.observe(inner);
  const stop = onProjector(fit);
  const update = (p: Part) => {
    inner.textContent = p.props.text ?? '';
    size = Number(p.props.size) || 28;
    inner.style.color = p.props.color || '#193746';
    inner.style.fontWeight = tag === 'h1' ? '700' : '400';
    fit();
  };
  update(part);
  return { update, destroy() { watcher.disconnect(); stop(); } };
}

function image(el: HTMLElement, part: Part, ctx: PartContext): PartHandle {
  const img = doc(el).createElement('img');
  img.style.cssText = 'width:100%;height:100%;object-fit:contain;display:block';
  el.replaceChildren(img);
  const update = (p: Part) => {
    if (p.props.asset) img.src = assetUrl(ctx.slug, p.props.asset);
    else img.removeAttribute('src');
    img.alt = p.props.alt ?? '';
  };
  update(part);
  return { update, destroy() {} };
}

function shapePart(el: HTMLElement, part: Part): PartHandle {
  const update = (p: Part) => { el.style.background = p.props.color || '#087f8c'; el.style.borderRadius = p.props.round ? '999px' : '10px'; };
  update(part);
  return { update, destroy() {} };
}

function chartPart(el: HTMLElement, part: Part, ctx: PartContext): PartHandle {
  const holder = doc(el).createElement('div');
  holder.style.cssText = 'position:absolute;inset:0';
  el.replaceChildren(holder);
  const controller = new GfmChartController(holder, ctx.slug);
  if (!ctx.skipChart?.(part)) void controller.setConfig(part.props as DataProps);
  return { chart: controller, update: p => { if (!ctx.skipChart?.(p)) void controller.setConfig(p.props as DataProps); }, destroy: () => controller.dispose() };
}

// A big number: the first field, added up over the rows shown (or its one value).
function kpiPart(el: HTMLElement, part: Part, ctx: PartContext): PartHandle {
  const d = doc(el);
  const wrap = d.createElement('div');
  wrap.style.cssText = 'height:100%;display:flex;flex-direction:column;justify-content:center;align-items:flex-start;font-family:Inter,system-ui,sans-serif;color:#17394b';
  const value = d.createElement('div');
  value.style.cssText = 'font-size:calc(72px * var(--gfm-text-scale, 1));font-weight:700;line-height:1';
  const label = d.createElement('div');
  label.style.cssText = 'font-size:calc(20px * var(--gfm-text-scale, 1));color:#3d5866;margin-top:8px';
  wrap.append(value, label);
  el.replaceChildren(wrap);
  let serial = 0;
  const update = (p: Part) => {
    const mine = ++serial;
    const props = p.props as DataProps;
    label.textContent = props.title || '';
    value.textContent = '…';
    loadFrame(ctx.slug, props).then(frame => {
      if (mine !== serial) return;
      const f = frame.fields[0];
      const nums = (f?.values ?? []).filter((v): v is number => v != null);
      value.textContent = f ? formatValue(f.format === 'percent' && nums.length > 1 ? nums.reduce((a, b) => a + b, 0) / nums.length : nums.reduce((a, b) => a + b, 0), f.format) : '–';
      if (!props.title && f) label.textContent = f.label;
    }).catch(e => { if (mine === serial) { value.textContent = '–'; label.textContent = (e as Error).message; } });
  };
  update(part);
  return { update, destroy() { serial++; } };
}

// A table built with the DOM (cells hold text only).
function tablePart(el: HTMLElement, part: Part, ctx: PartContext): PartHandle {
  const d = doc(el);
  let serial = 0;
  const update = (p: Part) => {
    const mine = ++serial;
    const props = p.props as DataProps;
    loadFrame(ctx.slug, props).then(frame => {
      if (mine !== serial) return;
      const table = d.createElement('table');
      table.style.cssText = 'width:100%;border-collapse:collapse;font:calc(18px * var(--gfm-text-scale, 1)) Inter,system-ui,sans-serif;color:#17394b';
      const head = table.createTHead().insertRow();
      ['', ...frame.fields.map(f => f.label)].forEach(h => { const th = d.createElement('th'); th.textContent = h; th.style.cssText = 'text-align:right;padding:6px 10px;border-bottom:2px solid #b8c6cd;font-weight:600'; head.appendChild(th); });
      (head.firstChild as HTMLElement).style.textAlign = 'left';
      const body = table.createTBody();
      frame.labels.forEach((label, i) => {
        const row = body.insertRow();
        const first = row.insertCell(); first.textContent = label; first.style.cssText = 'padding:6px 10px;border-bottom:1px solid #e3eaee';
        frame.fields.forEach(f => { const c = row.insertCell(); c.textContent = formatValue(f.values[i], f.format); c.style.cssText = 'padding:6px 10px;text-align:right;border-bottom:1px solid #e3eaee'; });
      });
      el.replaceChildren(table);
    }).catch(e => { if (mine === serial) el.textContent = (e as Error).message; });
  };
  update(part);
  return { update, destroy() { serial++; } };
}

/** Draws `part` into `el` (which the caller has placed and sized). */
export function renderPart(el: HTMLElement, part: Part, ctx: PartContext): PartHandle {
  box(el, part);
  switch (part.type) {
    case 'text': return text(el, part, 'div');
    case 'heading': return text(el, part, 'h1');
    case 'image': return image(el, part, ctx);
    case 'shape': return shapePart(el, part);
    case 'chart': return chartPart(el, part, ctx);
    case 'kpi': return kpiPart(el, part, ctx);
    case 'table': return tablePart(el, part, ctx);
    default: return { update() {}, destroy() {} };
  }
}
