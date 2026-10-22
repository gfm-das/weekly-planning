/* Demo Dashboards: a look-alike of the six DataEase dashboards (dataease/dashboards/*.json) on invented numbers.
   Same tiles, charts, tables and filters; drawn with the portal's echarts. Nothing here is real data. */
(() => {
'use strict';

// ---- Invented data -----------------------------------------------------------------------------------------------
const IND = [
  { k: 'npbt', name: 'New People Being Taught', tag: 'The key indicator', base: 3.2 },
  { k: 'bc', name: 'Baptisms and confirmations', base: 0.8 },
  { k: 'bd', name: 'Baptismal dates', base: 1.0 },
  { k: 'sa', name: 'Sacrament attendance', base: 13 },
  { k: 'ml', name: 'Members at lessons', base: 3.4 },
  { k: 'nms', name: 'New member sacrament attendance', base: 1.7 },
];
const ZONES = ['Alpha', 'Beta', 'Gamma'];
const NW = 30; // complete weeks of invented history

function rng(seed) {
  let a = seed >>> 0;
  return () => { a = (a + 0x6D2B79F5) >>> 0; let t = a; t = Math.imul(t ^ (t >>> 15), t | 1); t ^= t + Math.imul(t ^ (t >>> 7), t | 61); return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
}
const R = rng(20261015);

// Weeks: the Sundays of the last NW complete reporting weeks (the week still being reported is left out).
const iso = d => d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
const today = new Date(); today.setHours(12, 0, 0, 0);
const curSunday = new Date(today); curSunday.setDate(today.getDate() - today.getDay());
const WEEKS = Array.from({ length: NW }, (_, i) => { const d = new Date(curSunday); d.setDate(d.getDate() - 7 * (NW - i)); return iso(d); });

const AREAS = [];
ZONES.forEach((zone, zi) => {
  for (let d = 1; d <= 3; d++) {
    const district = `${zone} ${d}`;
    'abc'.split('').forEach((ch, ai) => {
      const area = `${district}-${ch}`;
      const f = 0.6 + R() * 0.8;
      const hasPop = !(zi === 2 && d === 3 && ai === 2) && !(zi === 1 && d === 2 && ai === 0);
      const a = { zone, district, area, f, data: {}, pop: hasPop ? Math.round((16000 + R() * 78000) / 100) * 100 : null,
        km2: hasPop ? Math.round((8 + R() * 140) * 10) / 10 : null, src: hasPop ? (R() < 0.5 ? 'Census sample' : 'Demo estimate') : '', geoDate: hasPop ? `2025-0${1 + Math.floor(R() * 9)}-01` : '' };
      IND.forEach(ind => {
        const g = [], x = [];
        for (let w = 0; w < NW; w++) {
          const goal = Math.max(0, Math.round(ind.base * (0.8 + R() * 0.5) * (1 + w * 0.004)));
          const act = goal === 0 ? (R() < 0.18 ? 1 : 0) : Math.max(0, Math.round(goal * f * (0.6 + R() * 0.75) + (R() - 0.35)));
          g.push(goal); x.push(act);
        }
        a.data[ind.k] = { a: x, g };
      });
      AREAS.push(a);
    });
  }
});
const DISTRICTS = [...new Set(AREAS.map(a => a.district))];
const zoneOf = d => AREAS.find(a => a.district === d).zone;

// People on the weekly plans (Covenant path): counts per district and week.
const PEOPLE = {};
DISTRICTS.forEach(d => {
  const base = 5 + R() * 4, rows = [];
  for (let w = 0; w < NW; w++) {
    const nm = Math.max(0, Math.round(base + w * 0.12 + (R() - 0.5) * 2));
    const bdf = Math.max(0, Math.round(4 + R() * 3));
    const hp = Math.max(0, Math.round(5 + R() * 4));
    rows.push({ new_members: nm, new_members_at_church: Math.round(nm * (0.5 + R() * 0.25)), new_members_temple_recommend: Math.round(nm * (0.15 + R() * 0.15)),
      new_members_calling: Math.round(nm * (0.35 + R() * 0.2)), new_members_aaronic_priesthood: Math.round(nm * (0.08 + R() * 0.08)), new_members_melchizedek_priesthood: Math.round(nm * (0.12 + R() * 0.1)),
      baptismal_date_friends: bdf, baptismal_date_friends_next_4_weeks: Math.round(bdf * (0.4 + R() * 0.3)), baptismal_date_friends_at_church: Math.round(bdf * (0.4 + R() * 0.3)),
      high_potentials: hp, high_potentials_at_church: Math.round(hp * (0.4 + R() * 0.3)) });
  }
  PEOPLE[d] = rows;
});

// ---- Filters and sums --------------------------------------------------------------------------------------------
const F = { zone: '', district: '', area: '', weeks: 26 };
const sel = () => AREAS.filter(a => (!F.zone || a.zone === F.zone) && (!F.district || a.district === F.district) && (!F.area || a.area === F.area));
const weekRange = n => Array.from({ length: n }, (_, i) => NW - n + i);
function sumAt(areas, k, w, which) { let s = 0; for (const a of areas) s += a.data[k][which][w]; return s; }
function sumRange(areas, k, from, to, which) { let s = 0; for (let w = from; w <= to; w++) s += sumAt(areas, k, w, which); return s; }
const last4 = (areas, k, which) => sumRange(areas, k, NW - 4, NW - 1, which);
const pctOf = (a, g) => (g > 0 ? Math.round(100 * a / g) : null);
const fmt = n => (n === null || n === undefined ? '' : new Intl.NumberFormat('en').format(n));
const esc = s => String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

// ---- Theme for the charts ----------------------------------------------------------------------------------------
function T() {
  const dark = document.documentElement.dataset.theme === 'dark';
  return dark
    ? { dark, text: '#edf7f8', muted: '#a9bdc3', line: '#2d414b', panel: '#18262f', result: '#4fd1c5', goal: '#fbbf24', trend: '#cbd5e1', heat: ['#21343d', '#2a6f78', '#4fd1c5'],
        pal: ['#4fd1c5', '#fbbf24', '#c4b5fd', '#86efac', '#fda4af', '#93c5fd'] }
    : { dark, text: '#17394b', muted: '#4f6672', line: '#dfe8eb', panel: '#ffffff', result: '#087f8c', goal: '#b45309', trend: '#4f6672', heat: ['#e3f1f2', '#7cc3ca', '#04545c'],
        pal: ['#087f8c', '#b45309', '#6d28d9', '#15803d', '#be123c', '#1d4ed8'] };
}
const tip = t => ({ trigger: 'axis', confine: true, backgroundColor: t.panel, borderColor: t.line, textStyle: { color: t.text, fontSize: 12 } });
function baseOpt(extra) {
  const t = T();
  return Object.assign({
    animation: false, color: t.pal,
    textStyle: { color: t.muted, fontFamily: '"Segoe UI", Roboto, Helvetica, Arial, sans-serif', fontSize: 12 },
    tooltip: tip(t),
    legend: { top: 0, textStyle: { color: t.text, fontSize: 12 }, itemWidth: 18, itemHeight: 3, type: 'scroll', pageTextStyle: { color: t.text }, pageIconColor: t.text, pageIconInactiveColor: t.muted },
    grid: { left: 8, right: 14, top: 36, bottom: 8, containLabel: true },
  }, extra);
}
const axisX = data => ({ type: 'category', data, boundaryGap: false, axisLine: { lineStyle: { color: T().line } }, axisTick: { show: false }, axisLabel: { color: T().muted, hideOverlap: true, interval: 'auto' } });
const axisY = extra => Object.assign({ type: 'value', min: 0, splitLine: { lineStyle: { color: T().line } }, axisLabel: { color: T().muted } }, extra);

function trendLine(vals) {
  const n = vals.length, sx = n * (n - 1) / 2, sxx = (n - 1) * n * (2 * n - 1) / 6;
  const sy = vals.reduce((p, v) => p + v, 0), sxy = vals.reduce((p, v, i) => p + i * v, 0);
  const d = n * sxx - sx * sx, m = d ? (n * sxy - sx * sy) / d : 0, b = (sy - m * sx) / n;
  return vals.map((_, i) => Math.round(Math.max(0, m * i + b) * 10) / 10);
}

function lineKpiChart(ind, areas) {
  const t = T(), idx = weekRange(Math.min(F.weeks, NW));
  const act = idx.map(w => sumAt(areas, ind.k, w, 'a')), goal = idx.map(w => sumAt(areas, ind.k, w, 'g'));
  // The trend is fitted over the last 26 weeks and a shorter range shows its part of the line.
  const full = trendLine(weekRange(26).map(w => sumAt(areas, ind.k, w, 'a')));
  const tr = full.slice(full.length - idx.length);
  return baseOpt({
    xAxis: axisX(idx.map(w => WEEKS[w])), yAxis: axisY(),
    series: [
      { name: 'Result', type: 'line', data: act, symbol: 'circle', symbolSize: 4, lineStyle: { width: 2.5, color: t.result }, itemStyle: { color: t.result } },
      { name: 'Goal set the week before', type: 'line', data: goal, symbol: 'none', lineStyle: { width: 2, color: t.goal }, itemStyle: { color: t.goal } },
      { name: 'Trend', type: 'line', data: tr, symbol: 'none', lineStyle: { width: 1.5, color: t.trend, type: 'dashed' }, itemStyle: { color: t.trend } },
    ],
  });
}

// ---- Block builders ----------------------------------------------------------------------------------------------
const B = {
  title(text, rest) { return { span: 12, cls: 'plain', html: `<h1>${esc(text)}</h1><p class="sub">Last complete week: <strong>${WEEKS[NW - 1]}</strong> (Sunday). ${esc(rest)}</p>` }; },
  filters(list) {
    const opts = {
      zone: ['Zone', ['', ...ZONES]],
      district: ['District', ['', ...DISTRICTS.filter(d => !F.zone || zoneOf(d) === F.zone)]],
      area: ['Area', ['', ...AREAS.filter(a => (!F.zone || a.zone === F.zone) && (!F.district || a.district === F.district)).map(a => a.area)]],
      weeks: ['Weeks', [8, 13, 26]],
    };
    const html = list.map(f => {
      const [label, vals] = opts[f], cur = String(F[f]);
      return `<label>${label}<select data-f="${f}">${vals.map(v => `<option value="${esc(v)}"${String(v) === cur ? ' selected' : ''}>${v === '' ? 'All' : (f === 'weeks' ? v + ' weeks' : esc(v))}</option>`).join('')}</select></label>`;
    }).join('');
    return { span: 12, html: `<div class="filters">${html}</div>` };
  },
  tile(ind, a, g, before) {
    const p = pctOf(a, g);
    return { span: 2, cls: 'tile', html: `<h3${ind.tag ? ' class="key"' : ''}>${esc(ind.name)}</h3><p class="tag">${esc(ind.tag || '')}</p><div class="big">${fmt(a)}</div><p class="pct">${p === null ? 'No goal set' : p + '% of the goal (' + fmt(g) + ')'}</p><p>Week before: ${fmt(before)}</p>` };
  },
  chart(title, note, option, span = 6, tall = false) { return { span, title, note, option, tall }; },
  table(title, note, head, rows, opts = {}) { return { span: 12, title, note, table: { head, rows, low: opts.low || [], sort: 0, dir: 1 } }; },
  note(text) { return { span: 12, cls: 'plain', html: `<p class="foot">${esc(text)}</p>` }; },
};

function kpiTiles(areas) {
  return IND.map(ind => B.tile(ind, sumAt(areas, ind.k, NW - 1, 'a'), sumAt(areas, ind.k, NW - 1, 'g'), sumAt(areas, ind.k, NW - 2, 'a')));
}

// Lowest first: the 10 units furthest below their own goals over the last 4 complete weeks.
function lowestUnits(units, k) {
  return units.map(u => ({ name: u.name, p: pctOf(last4(u.areas, k, 'a'), last4(u.areas, k, 'g')) })).filter(x => x.p !== null).sort((a, b) => a.p - b.p).slice(0, 10);
}
function hbar(rows, name, valueFmt, mark) {
  const t = T(), data = rows.slice().reverse();
  return baseOpt({
    legend: { show: false }, grid: { left: 8, right: 44, top: 12, bottom: 8, containLabel: true },
    tooltip: Object.assign(tip(t), { axisPointer: { type: 'shadow' } }),
    xAxis: axisY({ axisLabel: { color: t.muted, formatter: mark ? '{value}%' : '{value}' } }),
    yAxis: { type: 'category', data: data.map(r => r.name), axisTick: { show: false }, axisLine: { lineStyle: { color: t.line } }, axisLabel: { color: t.text } },
    series: [{ name, type: 'bar', data: data.map(r => r.p), itemStyle: { color: t.result }, barMaxWidth: 18,
      label: { show: true, position: 'right', color: t.text, formatter: p => valueFmt(p.value) },
      markLine: mark ? { silent: true, symbol: 'none', label: { show: false }, lineStyle: { color: t.goal, type: 'dashed' }, data: [{ xAxis: mark }] } : undefined }],
  });
}
const pctFmt = v => v + '%';

// ---- The six dashboards ------------------------------------------------------------------------------------------
const DASH = [
  { id: 'key-indicators', name: 'Key indicators', build() {
    const areas = sel(), bl = [B.title('Key indicators', 'Results are measured against the goal the areas set the week before; the week still being reported is left out, so the lines do not dip.'), B.filters(['zone', 'district', 'weeks']), ...kpiTiles(areas)];
    IND.forEach(ind => bl.push(B.chart(ind.name, 'Result each complete week, the goal the areas set the week before, and a straight trend line over the 26 weeks (least squares).', lineKpiChart(ind, areas))));
    bl.push(B.note('The trend is a straight line fitted to the last 26 complete weeks of the zones and districts chosen; a shorter week range shows its part of that line. To change a chart, choose All dashboards and Edit at the top right (not in this demo). Numbers are invented.'));
    return bl;
  } },
  { id: 'zones-districts', name: 'Zones & districts', build() {
    const t = T(), zoneAreas = ZONES.filter(z => !F.zone || z === F.zone).map(z => ({ name: z, areas: AREAS.filter(a => a.zone === z && (!F.district || a.district === F.district)) })).filter(u => u.areas.length);
    const bl = [B.title('Zones & districts', 'Every zone and district is measured against the goals its own areas set the week before, so a small zone can be at 100% too.'), B.filters(['zone', 'district', 'weeks'])];
    [['npbt', 'New People Being Taught'], ['sa', 'Sacrament attendance']].forEach(([k, n]) => {
      bl.push(B.chart(n + ' by zone, last complete week', "Result and the goal the zone's areas set the week before.", baseOpt({
        xAxis: { type: 'category', data: zoneAreas.map(u => u.name), axisTick: { show: false }, axisLine: { lineStyle: { color: t.line } }, axisLabel: { color: t.text } }, yAxis: axisY(),
        tooltip: Object.assign(tip(t), { axisPointer: { type: 'shadow' } }),
        series: [{ name: 'Result', type: 'bar', data: zoneAreas.map(u => sumAt(u.areas, k, NW - 1, 'a')), itemStyle: { color: t.result }, barMaxWidth: 42 },
          { name: 'Goal set the week before', type: 'bar', data: zoneAreas.map(u => sumAt(u.areas, k, NW - 1, 'g')), itemStyle: { color: t.goal }, barMaxWidth: 42 }] })));
    });
    const idx = weekRange(Math.min(F.weeks, NW));
    [['npbt', 'New People Being Taught', 'Each square is one zone in one complete week: the result as a % of the goal its areas set the week before. Darker is nearer or above the goal; an empty square had no goal. The District filter does not apply here.'], ['sa', 'Sacrament attendance', 'As above, for sacrament attendance.']].forEach(([k, n, note]) => {
      const zs = ZONES.filter(z => !F.zone || z === F.zone), data = [];
      zs.forEach((z, yi) => idx.forEach((w, xi) => { const ar = AREAS.filter(a => a.zone === z), p = pctOf(sumAt(ar, k, w, 'a'), sumAt(ar, k, w, 'g')); if (p !== null) data.push([xi, yi, p]); }));
      bl.push(B.chart(n + ': % of goal, zones by week', note, baseOpt({
        legend: { show: false }, grid: { left: 8, right: 14, top: 8, bottom: 56, containLabel: true },
        tooltip: { position: 'top', confine: true, backgroundColor: t.panel, borderColor: t.line, textStyle: { color: t.text, fontSize: 12 }, formatter: p => `${zs[p.value[1]]}, ${WEEKS[idx[p.value[0]]]}: ${p.value[2]}% of goal` },
        xAxis: { type: 'category', data: idx.map(w => WEEKS[w]), axisLine: { lineStyle: { color: t.line } }, axisTick: { show: false }, axisLabel: { color: t.muted, hideOverlap: true } },
        yAxis: { type: 'category', data: zs, axisTick: { show: false }, axisLine: { lineStyle: { color: t.line } }, axisLabel: { color: t.text } },
        visualMap: { min: 40, max: 140, orient: 'horizontal', left: 'center', bottom: 0, calculable: false, itemWidth: 14, itemHeight: 140, text: ['140%', '40%'], textStyle: { color: t.text }, inRange: { color: t.heat } },
        series: [{ type: 'heatmap', data, itemStyle: { borderColor: t.panel, borderWidth: 2 } }] }), 12));
    });
    const dist = DISTRICTS.filter(d => (!F.zone || zoneOf(d) === F.zone) && (!F.district || d === F.district)).map(d => ({ name: d, areas: AREAS.filter(a => a.district === d) }));
    [['npbt', 'New People Being Taught'], ['sa', 'Sacrament attendance']].forEach(([k, n]) => {
      const note = k === 'npbt' ? 'The 10 districts furthest below their own goals over the last 4 complete weeks (result as a % of the goals set the week before). A district with no goals is not shown. Talk with the leaders before drawing conclusions.' : 'The 10 districts furthest below their own goals over the last 4 complete weeks.';
      bl.push(B.chart('Districts that may need help: ' + n, note, hbar(lowestUnits(dist, k), n, pctFmt, 100)));
    });
    bl.push(B.table('Districts, last 4 complete weeks', '', ['Zone', 'District', 'New People Being Taught', 'Goals set the week before', '% of goal', 'Sacrament attendance', 'Goals set the week before ', '% of goal '],
      dist.map(d => [d.areas[0].zone, d.name, last4(d.areas, 'npbt', 'a'), last4(d.areas, 'npbt', 'g'), pctOf(last4(d.areas, 'npbt', 'a'), last4(d.areas, 'npbt', 'g')), last4(d.areas, 'sa', 'a'), last4(d.areas, 'sa', 'g'), pctOf(last4(d.areas, 'sa', 'a'), last4(d.areas, 'sa', 'g'))]), { low: [4, 7] }));
    return bl;
  } },
  { id: 'areas', name: 'Areas', build() {
    const areas = sel(), units = areas.map(a => ({ name: a.area, areas: [a] })), bl = [B.title('Areas', 'One area is the work of one companionship. Numbers only: no names of missionaries or of the people they teach. Each area is measured against the goal it set the week before.'), B.filters(['zone', 'district', 'area']), ...kpiTiles(areas)];
    [['npbt', 'New People Being Taught', 'The 10 areas furthest below their own goals over the last 4 complete weeks (result as a % of the goals set the week before). An area with no goals is not shown. Talk with the leaders before drawing conclusions.'], ['bc', 'Baptisms and confirmations', 'The 10 areas furthest below their own goals over the last 4 complete weeks.']].forEach(([k, n, note]) => bl.push(B.chart('Areas that may need help: ' + n, note, hbar(lowestUnits(units, k), n, pctFmt, 100))));
    bl.push(B.table('Areas, last 4 complete weeks', 'Each indicator as a % of the goal the area set the week before, over the last 4 complete weeks. An empty cell means no goal was set.', ['Zone', 'District', 'Area', ...IND.map(i => i.name)],
      areas.map(a => [a.zone, a.district, a.area, ...IND.map(i => pctOf(last4([a], i.k, 'a'), last4([a], i.k, 'g')))]), { low: [3, 4, 5, 6, 7, 8] }));
    return bl;
  } },
  { id: 'trend', name: 'Trend', build() {
    const t = T(), areas = sel(), idx = weekRange(Math.min(F.weeks, NW));
    const bl = [B.title('Trend', 'The last 4 complete weeks compared with the 4 weeks before, and how each key indicator moved over 26 weeks.'), B.filters(['zone', 'district', 'weeks'])];
    IND.forEach(ind => {
      const l = last4(areas, ind.k, 'a'), p = sumRange(areas, ind.k, NW - 8, NW - 5, 'a'), c = p > 0 ? Math.round(100 * (l - p) / p) : null;
      bl.push({ span: 2, cls: 'tile', html: `<h3${ind.tag ? ' class="key"' : ''}>${esc(ind.name)}</h3><p class="tag">Last 4 weeks</p><div class="big">${fmt(l)}</div><p>Previous 4 weeks: ${fmt(p)}</p><p class="pct">Change: ${c === null ? '' : (c > 0 ? '+' : '') + c + '%'}</p>` });
    });
    bl.push(B.chart('All six key indicators: % of goal', "Each key indicator's result as a % of the goal set the week before; 100 means the goal was reached. The lines follow the Zone and District choices.", baseOpt({
      xAxis: axisX(idx.map(w => WEEKS[w])), yAxis: axisY({ axisLabel: { color: t.muted, formatter: '{value}%' } }),
      series: IND.map(ind => ({ name: ind.name, type: 'line', symbol: 'none', lineStyle: { width: 2 }, data: idx.map(w => pctOf(sumAt(areas, ind.k, w, 'a'), sumAt(areas, ind.k, w, 'g'))), connectNulls: true })) }), 12, true));
    IND.forEach(ind => {
      const act = idx.map(w => sumAt(areas, ind.k, w, 'a'));
      const avg = idx.map(w => { let s = 0; for (let j = 0; j < 4; j++) s += sumAt(areas, ind.k, w - j, 'a'); return Math.round(s / 4 * 10) / 10; });
      bl.push(B.chart(ind.name, 'Result each complete week and the average of that week and the 3 before it.', baseOpt({
        xAxis: axisX(idx.map(w => WEEKS[w])), yAxis: axisY(),
        series: [{ name: 'Result', type: 'line', data: act, symbol: 'none', lineStyle: { width: 2, color: t.result }, itemStyle: { color: t.result } }, { name: 'Average of 4 weeks', type: 'line', data: avg, symbol: 'none', lineStyle: { width: 2.5, color: t.goal }, itemStyle: { color: t.goal } }] })));
    });
    return bl;
  } },
  { id: 'per-capita', name: 'Per 10,000 residents', build() {
    const areas = sel(), withPop = areas.filter(a => a.pop), per = (a, k) => Math.round(last4([a], k, 'a') / a.pop * 10000 * 10) / 10;
    const bl = [B.title('Per 10,000 residents', `The last 4 complete weeks, per 10,000 residents of each area. The population comes from Geo data (made up here). Areas with a population: ${withPop.length}. All areas: ${areas.length}.`), B.filters(['zone', 'district', 'area'])];
    IND.forEach(ind => {
      const rows = withPop.map(a => ({ name: a.area, p: per(a, ind.k) })).sort((x, y) => y.p - x.p).slice(0, 10);
      bl.push(B.chart(ind.name + ' per 10,000 residents', 'The 10 areas with the highest numbers per 10,000 residents, added up over the last 4 complete weeks. Areas without a population are not shown.', hbar(rows, ind.name, v => v, 0)));
    });
    bl.push(B.table('Areas: key indicators per 10,000 residents, last 4 complete weeks', 'Population from Geo data. Each indicator is the last 4 complete weeks added up, per 10,000 residents. An empty cell means the area has no population yet.',
      ['Zone', 'District', 'Area', 'Population', ...IND.map(i => i.name)], areas.map(a => [a.zone, a.district, a.area, a.pop, ...IND.map(i => (a.pop ? per(a, i.k) : null))])));
    bl.push(B.table('Geo data of the areas', 'The figures behind the per-resident numbers: population, size and density, with where they come from and the date they are from. In the full system you add or change them under Geo data in DA Management.',
      ['Zone', 'District', 'Area', 'Source', 'Data date', 'Population', 'Size (km²)', 'People per km²'], areas.map(a => [a.zone, a.district, a.area, a.src, a.geoDate, a.pop, a.km2, a.pop ? Math.round(a.pop / a.km2) : null])));
    return bl;
  } },
  { id: 'covenant-path', name: 'Covenant path', build() {
    const ds = DISTRICTS.filter(d => (!F.zone || zoneOf(d) === F.zone) && (!F.district || d === F.district)), idx = weekRange(Math.min(F.weeks, NW));
    const at = (key, w) => ds.reduce((s, d) => s + PEOPLE[d][w][key], 0), now = k => at(k, NW - 1);
    const line = (keys, names) => baseOpt({ xAxis: axisX(idx.map(w => WEEKS[w])), yAxis: axisY(), series: keys.map((k, i) => ({ name: names[i], type: 'line', symbol: 'none', lineStyle: { width: 2 }, data: idx.map(w => at(k, w)) })) });
    return [B.title('Covenant path', "People on the companionships' weekly plans, counted (no names). A 0 means no one has been added to the plans yet."), B.filters(['zone', 'district', 'weeks']),
      { span: 4, cls: 'tile', html: `<h3>New members</h3><div class="big">${now('new_members')}</div><p>At church: ${now('new_members_at_church')} · Temple recommend: ${now('new_members_temple_recommend')}</p><p>Calling: ${now('new_members_calling')} · Aaronic Priesthood: ${now('new_members_aaronic_priesthood')} · Melchizedek Priesthood: ${now('new_members_melchizedek_priesthood')}</p>` },
      { span: 4, cls: 'tile', html: `<h3>Friends with a baptismal date</h3><div class="big">${now('baptismal_date_friends')}</div><p>Date within 4 weeks: ${now('baptismal_date_friends_next_4_weeks')}</p><p>At church: ${now('baptismal_date_friends_at_church')}</p>` },
      { span: 4, cls: 'tile', html: `<h3>High-potential friends</h3><div class="big">${now('high_potentials')}</div><p>At church: ${now('high_potentials_at_church')}</p>` },
      B.chart('New members, and those at church', 'New members on the weekly plans each complete week, and how many of them were at church.', line(['new_members', 'new_members_at_church'], ['New members', 'At church'])),
      B.chart('New members: next steps', "Temple recommend, calling, Aaronic and Melchizedek Priesthood (the priesthood questions are 'Not applicable' for sisters and children).", line(['new_members_temple_recommend', 'new_members_calling', 'new_members_aaronic_priesthood', 'new_members_melchizedek_priesthood'], ['Temple recommend', 'Calling', 'Aaronic Priesthood', 'Melchizedek Priesthood'])),
      B.chart('Friends with a baptismal date', 'All friends with a baptismal date on the weekly plans, those whose date is within 4 weeks, and those at church.', line(['baptismal_date_friends', 'baptismal_date_friends_next_4_weeks', 'baptismal_date_friends_at_church'], ['With a baptismal date', 'Date within 4 weeks', 'At church'])),
      B.chart('High-potential friends', 'High-potential friends on the weekly plans, and those at church.', line(['high_potentials', 'high_potentials_at_church'], ['High-potential friends', 'At church']))];
  } },
];

// ---- Drawing -----------------------------------------------------------------------------------------------------
const page = document.getElementById('page'), bar = document.getElementById('bar');
let current = DASH[0], charts = [], tables = {};

function drawTable(id) {
  const t = tables[id], rows = t.rows.slice();
  rows.sort((a, b) => { const x = a[t.sort], y = b[t.sort]; if (x === y) return 0; if (x === null || x === '') return 1; if (y === null || y === '') return -1; return (typeof x === 'number' ? x - y : String(x).localeCompare(String(y))) * t.dir; });
  const head = t.head.map((h, i) => `<th scope="col" aria-sort="${t.sort === i ? (t.dir > 0 ? 'ascending' : 'descending') : 'none'}"><button type="button" data-t="${id}" data-c="${i}">${esc(h)}${t.sort === i ? (t.dir > 0 ? ' ▲' : ' ▼') : ''}</button></th>`).join('');
  const body = rows.map(r => `<tr>${r.map((c, i) => `<td${t.low.includes(i) && c !== null && c < 80 ? ' class="low"' : ''}>${typeof c === 'number' ? fmt(c) + (t.low.includes(i) ? '%' : '') : esc(c === null ? '' : c)}</td>`).join('')}</tr>`).join('');
  document.querySelector(`[data-tw="${id}"]`).innerHTML = `<table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>`;
}

function render() {
  const y = window.scrollY;
  charts.forEach(c => c.dispose()); charts = []; tables = {};
  const blocks = current.build();
  page.innerHTML = blocks.map((b, n) => {
    const id = 'b' + n, span = 's' + b.span;
    if (b.html) return `<section class="c ${span} ${b.cls || ''}">${b.html}</section>`;
    const head = `<h3>${esc(b.title)}</h3>${b.note ? `<p class="note">${esc(b.note)}</p>` : ''}`;
    if (b.option) return `<section class="c ${span} ch">${head}<div class="plot${b.tall ? ' tall' : ''}" id="${id}" role="img" aria-label="${esc(b.title)}"></div></section>`;
    tables[id] = b.table;
    return `<section class="c ${span} ch">${head}<div class="tw" data-tw="${id}" tabindex="0"></div></section>`;
  }).join('');
  blocks.forEach((b, n) => {
    const id = 'b' + n;
    if (b.option) { const c = echarts.init(document.getElementById(id)); c.setOption(b.option); charts.push(c); }
    else if (b.table) drawTable(id);
  });
  bar.querySelectorAll('button[data-d]').forEach(x => { if (x.dataset.d === current.id) x.setAttribute('aria-current', 'page'); else x.removeAttribute('aria-current'); });
  document.title = current.name + ' · Dashboards';
  window.scrollTo(0, y);
}

function open(id, push) {
  current = DASH.find(d => d.id === id) || DASH[0];
  if (push) { try { history.replaceState(null, '', '#' + current.id); } catch (e) {} }
  window.scrollTo(0, 0);
  render();
}

bar.innerHTML = DASH.map(d => `<button type="button" data-d="${d.id}">${esc(d.name)}</button>`).join('') + '<button type="button" class="edit" data-edit="1">All dashboards and Edit</button>';
bar.addEventListener('click', e => {
  const b = e.target.closest('button'); if (!b) return;
  if (b.dataset.d) open(b.dataset.d, true);
  else if (b.dataset.edit) {
    const t = document.createElement('div'); t.className = 'toast'; t.setAttribute('role', 'status'); t.textContent = 'Editing dashboards needs the full system. This demo shows invented numbers.';
    document.body.append(t); setTimeout(() => t.remove(), 3500);
  }
});
page.addEventListener('change', e => {
  const f = e.target.dataset && e.target.dataset.f; if (!f) return;
  F[f] = f === 'weeks' ? Number(e.target.value) : e.target.value;
  if (f === 'zone') { F.district = ''; F.area = ''; }
  if (f === 'district') F.area = '';
  render();
  const again = page.querySelector(`select[data-f="${f}"]`); if (again) again.focus();
});
page.addEventListener('click', e => {
  const b = e.target.closest('button[data-t]'); if (!b) return;
  const t = tables[b.dataset.t], c = Number(b.dataset.c);
  if (t.sort === c) t.dir = -t.dir; else { t.sort = c; t.dir = 1; }
  drawTable(b.dataset.t);
  document.querySelector(`button[data-t="${b.dataset.t}"][data-c="${c}"]`).focus();
});
window.addEventListener('resize', () => charts.forEach(c => c.resize()));
window.__redraw = render;
window.addEventListener('hashchange', () => open(location.hash.slice(1), false));
try { parent.postMessage({ type: 'portal-theme-request' }, '*'); } catch (e) {}
open(location.hash.slice(1), false);
})();
