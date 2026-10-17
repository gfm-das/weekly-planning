// Draws one slide of a demo deck as static HTML/CSS, the way the Mmm* components of the real add-on do
// (slidev/manager/gfm-addon/components/*.vue). The CSS is the components' own (mmm.css); the numbers are invented (fake.js).
import { goalCard, shareCard, periodCard, gaugeModel, unitRows, pairSums, readAnswer, percentText, numberText, toneOf } from './mmm-core.mjs';
import { answerFor, weekLabels, PEOPLE, futureDate } from './fake.js';

const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const listOf = v => (Array.isArray(v) ? v.map(String) : typeof v === 'string' && v.trim() ? v.trim().split('|').map(s => s.trim()) : []);
const rowsOf = v => (Array.isArray(v) ? v : typeof v === 'string' && v.trim() ? v.trim().split(';').map(r => r.split('|').map(s => s.trim())).filter(r => r.some(Boolean)) : []);
const typed = v => (v === undefined || v === null || v === '' || !Number.isFinite(Number(v)) ? null : Number(v));
const place = (p, h = true) => `left:calc(${p.x} * var(--u));top:calc(${p.y} * var(--u));width:calc(${p.w} * var(--u));${h && p.h !== undefined ? `height:calc(${p.h} * var(--u));` : ''}`;
const hashOf = s => [...String(s)].reduce((h, c) => (Math.imul(h, 31) + c.charCodeAt(0)) >>> 0, 11);

// ---- What a leader types by hand in the real decks is filled with invented words here --------------------------------
function fakeCell(head, r) {
  const h = String(head).toLowerCase();
  if (/month/.test(h)) return ['Sep', 'Oct', 'Oct', 'Oct'][r % 4];
  if (/friend|name/.test(h)) return PEOPLE[r % PEOPLE.length];
  if (/date/.test(h)) return futureDate(r);
  if (/companionship/.test(h)) return ['Elders Sample', 'Sisters Demo', 'Elders Test'][r % 3];
  if (/unit|stake/.test(h)) return ['Alpha Ward', 'Beta Branch', 'Gamma Ward'][r % 3];
  if (/leader/.test(h)) return PEOPLE[(r + 1) % PEOPLE.length];
  if (/topic/.test(h)) return ['Finding new friends', 'Teaching with members', 'Baptismal dates', 'Follow-up lessons'][r % 4];
  if (/how are they/.test(h)) return ['Doing well', 'At church', 'Needs a visit'][r % 3];
  if (/gemiko/.test(h)) return ['Yes', 'Not yet', 'Yes'][r % 3];
  if (/support/.test(h)) return ['Member visits', 'Ride to church', 'Dinner invite'][r % 3];
  return 'Sample text';
}
function fillRows(heads, rows) {
  if (heads.join('|') === 'Notes|Action items|Report back' && !rows.length) {
    return [['Invite more friends', 'Call by Tuesday', 'Done: 2'], ['Plan with members', 'Set two dates', 'In progress'], ['Share the video', 'Visit the ward', 'Next week']];
  }
  return rows.map((row, r) => row.map((c, i) => (/^type/i.test(c) ? fakeCell(heads[i], r) : c)));
}
const GAUGE_FILL = { 'Contact Rate': [0.58, 1.2], 'Teaching Rate': [0.41, -0.8], '% Active': [0.72, 1.6] };

// ---- The pieces ----------------------------------------------------------------------------------------------------
function card(p0) {
  const p = { x: 55, y: 100, w: 190, h: 190, title: '', mode: 'goal', tone: 'green', period: 'month', digits: 1, lastLabel: 'Last', goalLabel: 'Goal', naText: 'N/A', goalAt: 'bottom', lastAt: 'left', ...p0 };
  if (p.mode === 'manual' && typed(p.value) === null) { const v = 3 + (hashOf(p.title) % 12); p.value = v; p.last = Math.max(0, v - 3); p.goal = v + 5; }
  const answer = p.mode === 'manual' ? null : answerFor(p.query);
  let m;
  if (p.mode === 'manual') { const value = typed(p.value), goal = typed(p.goal) || null; m = { ready: true, value, last: typed(p.last), goal, ratio: goal ? value / goal : null }; }
  else if (!answer) m = { ready: false };
  else if (p.mode === 'share') { const s = shareCard(answer); m = s.ready ? { ...s, goal: null } : s; }
  else if (p.mode === 'period') m = periodCard(answer, { period: p.period, target: p.goal });
  else m = goalCard(answer);
  const ratio = m.ratio ?? null;
  const pct = ratio === null ? p.naText : percentText(ratio, p.digits);
  const bar = `${Math.round(Math.max(0, Math.min(1, ratio ?? 0)) * 100)}%`;
  const big = m.ready ? numberText(m.value) : '–';
  const lastText = numberText(m.last) || '–';
  let goalText;
  if (p.target) goalText = p.target;
  else if (m.goal === null || m.goal === undefined) goalText = p.mode === 'goal' ? '0' : '–';
  else goalText = numberText(m.goal);
  return `<div class="mmm-box mmm-card mmm-card--${p.tone} mmm-card--${toneOf(ratio)}" style="${place(p)}" role="group" aria-label="${esc(p.title)}">
    <div class="mmm-card__body mmm-panel"><div class="mmm-card__title">${esc(p.title)}</div><div class="mmm-card__big">${esc(big)}</div>
    ${p.noPct ? '' : `<div class="mmm-card__pct">${esc(pct)}</div>`}${p.noBar ? '' : `<div class="mmm-card__bar"><i style="width:${bar}"></i></div>`}
    ${p.barLabel ? `<div class="mmm-card__barlabel">${esc(p.barLabel)}</div>` : ''}${p.footerText ? `<div class="mmm-card__foot">${esc(p.footerText)}</div>` : ''}</div>
    ${!p.noBadges && !p.hideLast ? `<div class="mmm-badge mmm-badge--last${p.lastAt === 'right' ? ' mmm-badge--right' : ''}"><b>${esc(p.lastLabel)}</b><span>${esc(lastText)}</span></div>` : ''}
    ${!p.noBadges && !p.hideGoal && (p.mode !== 'share' || p.target) ? `<div class="mmm-badge mmm-badge--goal${p.goalAt === 'top' ? ' mmm-badge--top' : ''}"><b>${esc(p.goalLabel)}</b><span>${esc(goalText)}</span></div>` : ''}</div>`;
}

const CX = 170, CY = 176, RO = 160, RI = 122;
const at = (r, ratio) => { const a = Math.PI * (1 - ratio); return [CX + r * Math.cos(a), CY - r * Math.sin(a)]; };
function band(from, to) {
  to = Math.min(to, 0.9995);
  if (to - from <= 0.0005) return '';
  const [ox1, oy1] = at(RO, from), [ox2, oy2] = at(RO, to), [ix2, iy2] = at(RI, to), [ix1, iy1] = at(RI, from);
  const f = n => n.toFixed(2);
  return `M${f(ox1)} ${f(oy1)}A${RO} ${RO} 0 0 1 ${f(ox2)} ${f(oy2)}L${f(ix2)} ${f(iy2)}A${RI} ${RI} 0 0 0 ${f(ix1)} ${f(iy1)}Z`;
}
function gauge(p0) {
  const p = { x: 735, y: 325, w: 362, h: 250, title: '', mode: 'value', tone: 'cyan', max: 100, minLabel: '0', maxLabel: '', ...p0 };
  if (p.mode === 'manual' && typed(p.value) === null) { const [v, c] = GAUGE_FILL[p.title] || [0.5, 0.5]; p.value = v; p.change = c; }
  const model = gaugeModel(p.query ? answerFor(p.query) : null, { mode: p.mode, max: p.max, target: p.target === '' ? null : p.target, value: p.value, change: p.change });
  const ratio = model.ready ? model.ratio : 0;
  const tick = (() => {
    const t = model.tick;
    if (t === null || t === undefined || !model.ready) return '';
    const r = Math.max(0, Math.min(1, model.max > 1 ? t / model.max : t));
    const [x1, y1] = at(RI - 4, r), [x2, y2] = at(RO + 4, r);
    return `<line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" class="mmm-gauge__tick"/>`;
  })();
  const c = model.change;
  let change = '';
  if (c !== null && c !== undefined && Number.isFinite(c)) {
    const body = model.changeIsPoints ? `${Math.abs(c).toFixed(2)}%` : String(Math.abs(Math.round(c * 100) / 100));
    change = `<div class="mmm-gauge__change ${c < 0 ? 'is-down' : 'is-up'}">${c < 0 ? '-' : ''}${body}</div>`;
  }
  const top = p.maxLabel || (model.ready ? (model.percent ? '1' : String(model.max)) : '1');
  return `<div class="mmm-box mmm-gauge mmm-panel mmm-gauge--${p.tone}" style="${place(p)}" role="img" aria-label="${esc(p.title)}: ${esc(model.display || '')}">
    <svg class="mmm-gauge__svg" viewBox="0 0 340 200" preserveAspectRatio="xMidYMid meet" aria-hidden="true">${band(ratio, 1) ? `<path d="${band(ratio, 1)}" class="mmm-gauge__rest"/>` : ''}${band(0, ratio) ? `<path d="${band(0, ratio)}" class="mmm-gauge__fill"/>` : ''}${tick}</svg>
    <div class="mmm-gauge__num">${esc(model.ready ? model.display : '–')}</div>${change}<div class="mmm-gauge__end mmm-gauge__end--min">${esc(p.minLabel)}</div><div class="mmm-gauge__end mmm-gauge__end--max">${esc(top)}</div>
    <div class="mmm-gauge__title">${esc(p.title)}</div></div>`;
}

function table(p0) {
  const p = { x: 38, y: 325, w: 520, h: 250, top: 6, ratio: true, ...p0 };
  const answer = answerFor(p.query), heads = listOf(p.headers);
  const count = answer ? Math.min(8, readAnswer(answer).actuals.length) : 0;
  const rows = answer ? unitRows(answer, { columns: Array.from({ length: count }, (_, i) => i), ratioOf: [0, 1], top: p.top }) : [];
  const showRatio = p.ratio && count >= 2;
  const cols = `2.3fr repeat(${Math.max(1, count)}, 1fr)${showRatio ? ' 1fr' : ''}`;
  const hs = heads.slice(0, 1 + count + (showRatio ? 1 : 0));
  return `<div class="mmm-box mmm-table mmm-panel${p.dense ? ' is-dense' : ''}" style="${place(p)}--mmm-cols:${cols}" role="table">
    <div class="mmm-table__head" role="row">${hs.map((h, i) => `<span role="columnheader">${esc(h)} ${i === 1 ? '<i>▼</i>' : ''}</span>`).join('')}</div>
    ${rows.map((r, i) => `<div class="mmm-table__row${i % 2 === 0 ? ' is-odd' : ''}" role="row"><span role="cell" class="mmm-table__name">${esc(r.name)}</span>${r.cells.map(c => `<span role="cell">${esc(numberText(c))}</span>`).join('')}${showRatio ? `<span role="cell">${r.ratio === null ? '–' : percentText(r.ratio, 0)}</span>` : ''}</div>`).join('')}</div>`;
}

function manual(p0) {
  const p = { x: 28, y: 90, w: 1096, h: 485, sorted: 1, goalLabel: 'Goal', goal: '', ...p0 };
  const heads = listOf(p.headers), body = fillRows(heads, rowsOf(p.rows));
  const widths = heads.length === 4 ? '260fr 268fr 268fr 260fr' : `repeat(${Math.max(1, heads.length)}, 1fr)`;
  return `<div class="mmm-box mmm-manual" style="${place(p)}grid-template-columns:${widths}" role="table">
    ${heads.map((h, c) => `<div class="mmm-manual__col mmm-panel" role="rowgroup"><div class="mmm-manual__head" role="columnheader">${esc(h)} ${c === p.sorted ? '<i>▲</i>' : ''}</div>${body.map(r => `<div class="mmm-manual__cell" role="cell">${esc(r[c])}</div>`).join('')}</div>`).join('')}
    ${p.goal ? `<div class="mmm-badge mmm-badge--goal mmm-badge--top mmm-manual__goal" style="--t:var(--mmm-red-tint)"><b>${esc(p.goalLabel)}</b><span>${esc(p.goal)}</span></div>` : ''}</div>`;
}

function chips(p0) {
  const p = { x: 40, y: 120, w: 240, align: 'center', ...p0 };
  const names = listOf(p.items).filter(Boolean).map((n, i) => (/^type here$/i.test(n) ? PEOPLE[i % PEOPLE.length] : n.replace(/type the topic here/i, 'Finding new friends').replace(/type here/i, 'Elder Sample')));
  return `<div class="mmm-box mmm-chips" style="${place(p, false)}">${names.map(n => `<div class="mmm-chip${p.align === 'start' ? ' is-start' : ''}">${esc(n)}</div>`).join('')}</div>`;
}

function pair(p0) {
  const p = { x: 900, y: 60, w: 110, weeks: 4, ...p0 };
  const sums = pairSums(answerFor(p.query), { weeks: p.weeks }), names = listOf(p.labels);
  return `<div class="mmm-box mmm-pair" style="${place(p, false)}"><div class="mmm-pair__label">${esc(names[0])}</div><div class="mmm-pair__box mmm-pair__box--actual">${esc(numberText(sums.actual) || '–')}</div>
    <div class="mmm-pair__label">${esc(names[1])}</div><div class="mmm-pair__box mmm-pair__box--goal">${esc(numberText(sums.goal) || '–')}</div></div>`;
}

// A video or picture place of the real decks (empty and dashed there): the demo shows a made-up poster instead.
function slot(p0) {
  const p = { x: 40, y: 90, w: 540, h: 420, kind: 'image', caption: '', ...p0 };
  const video = p.kind === 'video';
  const icon = video ? '<path d="M20 18v12l10-6z"/>' : '<path d="M9 35l10-11 7 8 5-6 8 9"/>';
  return `<figure class="mmm-box mmm-slot" style="${place(p)}"><div class="mmm-slot__frame mmm-panel demo-poster ${video ? 'is-video' : 'is-image'}">
    <svg viewBox="0 0 48 48" aria-hidden="true"><rect x="5" y="9" width="38" height="30" rx="4"/>${icon}</svg><span>${video ? 'Sample video (demo)' : 'Sample picture (demo)'}</span></div>
    ${p.caption ? `<figcaption class="mmm-slot__caption">${esc(p.caption)}</figcaption>` : ''}</figure>`;
}

function trend(p0) {
  const p = { x: 55, y: 325, w: 660, h: 250, title: '', trend: false, goal: false, values: false, legend: true, smooth: true, ...p0 };
  return `<div class="mmm-box mmm-trend mmm-panel" style="${place(p)}" role="figure" aria-label="${esc(p.title)}">${p.title ? `<div class="mmm-trend__title">${esc(p.title)}</div>` : ''}<div class="mmm-trend__plot" data-trend="${esc(JSON.stringify(p))}"></div></div>`;
}

const PIECES = { Card: card, Gauge: gauge, Table: table, Manual: manual, Chips: chips, Pair: pair, Slot: slot, Trend: trend };

// ---- A slide ------------------------------------------------------------------------------------------------------------
export function slideHtml(slide) {
  if (slide.cover) {
    const c = { line1: '', line2: '', below: '', below2: '', ...slide.cover };
    const withPicture = !!c.pictureSlot || !!c.picture;
    const line1 = c.line1 === 'Zone name' ? 'Alpha Zone' : c.line1;
    return `<div class="mmm-frame mmm-cover${withPicture ? ' has-picture' : ''}">
      ${withPicture ? '<div class="mmm-cover__picture demo-poster is-image"><span>Sample picture (demo)</span></div>' : ''}
      <div class="mmm-cover__text">${line1 ? `<div class="mmm-cover__big">${esc(line1)}</div>` : ''}${c.line2 ? `<div class="mmm-cover__big">${esc(c.line2)}</div>` : ''}<hr>
      ${c.below ? `<div class="mmm-cover__big">${esc(c.below)}</div>` : ''}${c.below2 ? `<div class="mmm-cover__big">${esc(c.below2)}</div>` : ''}</div></div>`;
  }
  const f = { tone: 'green', tone2: 'cyan', x2: 750, corners: 'a', footerLead: 'Supporting Missionaries in', footerFaith: 'Faith,', footerHope: 'Hope,', footerCharity: '& Charity:', verse: 'Moroni 10: 20-21', ...slide.frame };
  return `<div class="mmm-frame mmm-corners-${f.corners} mmm-tone-${f.tone}${f.dark ? ' mmm-dark' : ''}">
    <div class="mmm-shape mmm-shape--one"></div><div class="mmm-shape mmm-shape--two"></div>
    ${f.heading ? `<div class="mmm-heading mmm-tone-${f.tone}" style="left:calc(35 * var(--u))">${esc(f.heading)}</div>` : ''}
    ${f.heading2 ? `<div class="mmm-heading mmm-tone-${f.tone2}" style="left:calc(${f.x2} * var(--u))">${esc(f.heading2)}</div>` : ''}
    ${slide.pieces.map(x => PIECES[x.t](x.p)).join('')}
    ${f.noFooter ? '' : `<div class="mmm-footer"><span class="mmm-footer__lead">${esc(f.footerLead)} <span class="mmm-c-green">${esc(f.footerFaith)}</span> <span class="mmm-c-red">${esc(f.footerHope)}</span> <span class="mmm-c-cyan">${esc(f.footerCharity)}</span></span><span class="mmm-footer__verse">${esc(f.verse)}</span></div>`}</div>`;
}

// The line charts (MmmTrend) are drawn after the slide is in the page, because they need its size.
function trendOption(p, frame) {
  const answer = answerFor(p.query), read = readAnswer(answer);
  const dark = frame.classList.contains('mmm-dark');
  const k = frame.clientWidth / 1152, fs = Math.max(8, Math.round(12.5 * k * 10) / 10);
  const ink = dark ? '#f1f3f5' : '#2d505e', grid = dark ? '#4a4a4a' : '#d9dde2';
  const PALETTE = ['#4da580', '#ffa90a', '#ffe600', '#d32f2f', '#2e7d32', '#1f6fd1'];
  const names = listOf(p.labels), colors = listOf(p.colors).length ? listOf(p.colors) : PALETTE;
  const sets = p.goal ? [...read.actuals, ...read.goals] : read.actuals;
  const line = values => {
    const n = values.length, sx = n * (n - 1) / 2, sxx = (n - 1) * n * (2 * n - 1) / 6, sy = values.reduce((a, v) => a + v, 0), sxy = values.reduce((a, v, i) => a + i * v, 0);
    const d = n * sxx - sx * sx, m = d ? (n * sxy - sx * sy) / d : 0, b = (sy - m * sx) / n;
    return values.map((_, i) => Math.max(0, m * i + b));
  };
  const series = [];
  sets.forEach((s, i) => {
    const color = colors[i % colors.length], name = names[i] || s.name;
    series.push({ name, type: 'line', smooth: p.smooth, symbol: p.values ? 'circle' : 'none', symbolSize: 6 * k, data: s.values, lineStyle: { color, width: 2.4 * k }, itemStyle: { color },
      areaStyle: { color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1, colorStops: [{ offset: 0, color: `${color}55` }, { offset: 1, color: `${color}05` }] } },
      label: p.values ? { show: true, position: 'top', color: ink, fontSize: fs, fontFamily: 'inherit' } : { show: false }, connectNulls: true, animation: false, z: 3 + i });
    if (p.trend) series.push({ name: `${name} (trend)`, type: 'line', symbol: 'none', data: line(s.values), lineStyle: { color: dark ? '#ddd' : '#111', width: 1.4 * k, type: [8 * k, 5 * k] }, silent: true, animation: false, z: 2 });
  });
  const labels = read.labels.map(l => { const [, m, d] = l.split('-'); return `${+m}/${+d}`; });
  return {
    animation: false, textStyle: { fontFamily: 'Montserrat, "Segoe UI", Inter, system-ui, sans-serif', color: ink, fontSize: fs },
    grid: { left: 36 * k, right: 12 * k, top: (p.legend ? 36 : 14) * k, bottom: 38 * k, containLabel: false },
    legend: p.legend ? { show: true, top: 4 * k, right: 10 * k, itemWidth: 22 * k, itemHeight: 2 * k, itemGap: 26 * k, textStyle: { color: ink, fontSize: fs * 0.95 }, data: series.filter(s => !String(s.name).endsWith('(trend)')).map(s => s.name) } : { show: false },
    xAxis: { type: 'category', data: labels, boundaryGap: false, axisLine: { lineStyle: { color: grid } }, axisTick: { show: false }, axisLabel: { color: ink, fontSize: fs, interval: 'auto', hideOverlap: true } },
    yAxis: { type: 'value', min: 0, splitLine: { lineStyle: { color: grid } }, axisLabel: { color: ink, fontSize: fs } },
    series,
  };
}

/** Puts a slide into `host` (an element with class "slide-host"), draws its charts, returns { redraw, destroy }. */
export function mount(host, slide) {
  host.innerHTML = slideHtml(slide);
  const frame = host.firstElementChild;
  let charts = [];
  const compact = () => frame.querySelectorAll('.mmm-card').forEach(card => {
    const title = card.querySelector('.mmm-card__title'), size = parseFloat(getComputedStyle(title).fontSize) || 17;
    card.classList.toggle('is-compact', title.offsetHeight > size * 1.15 * 1.5);
  });
  const draw = () => {
    charts.forEach(c => c.dispose()); charts = [];
    if (!window.echarts) return;
    frame.querySelectorAll('[data-trend]').forEach(el => {
      if (!el.clientWidth) return;
      const c = window.echarts.init(el);
      c.setOption(trendOption(JSON.parse(el.dataset.trend), frame));
      charts.push(c);
    });
    compact();
  };
  draw();
  return { redraw: draw, destroy: () => { charts.forEach(c => c.dispose()); charts = []; } };
}
