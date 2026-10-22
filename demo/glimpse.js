/*
 * glimpse.js: the mission glimpse, the top of the Overview (home.html) for the managers.
 *
 * WHAT IT SHOWS
 *   The last finished week of the whole mission: one tile per key indicator ("New people being taught" first) with
 *   the result, the goal companionships set the week before and a small line of the last weeks; a short summary in
 *   words; a chart of result and goal week by week with a straight trend line; the same by zone; and all of it as a
 *   table. Green with a tick ("Goal reached") only at or over the goal; no red, because these are not verdicts.
 *
 * WHO USES IT
 *   APs, the President and Data Analysts (also as an additional role; portal-api roles.shows_glimpse). Everyone
 *   else gets the Overview cards only.
 *
 * HOW IT FITS
 *   - Numbers: GET /api/dashboard (portal-api dashboard.py), read as the signed-in person through row-level security.
 *   - Charts: Apache ECharts (echarts.min.js, vendored 6.0.0), loaded only when the glimpse starts.
 *   - Start: the shell opens the managers' Overview as /home.html?glimpse=1, so the glimpse shows (and asks for its
 *     numbers) at once. home.html then calls MissionGlimpse.update() with /api/overview's "glimpse" flag, which
 *     decides in the end (and hides the glimpse while a manager looks at another area's goals). A 403 hides it quietly.
 *   - Words: text put into the page is plain English that i18n.js translates like the rest of the Overview; the
 *     sentences with numbers are in WORDS below, in one place; text drawn inside the charts goes through tr().
 *   - Look: glimpse.css. Tests: portal/tests/glimpse-check.cjs, portal-api/tests/edge_glimpse.ps1.
 */
(() => {
  'use strict';

  // Read now: portal-client.js (loaded after this file) takes the query off the address.
  const hinted = new URLSearchParams(location.search).get('glimpse') === '1';

  // ---- Interface text (plain English) ---------------------------------------------------------------------------
  const WORDS = {
    weekOf: date => `Week of ${date}`,
    latestWeek: date => `Week of ${date} (latest)`,
    subtitle: date => `Finished weeks only, each measured against the goal companionships set the week before. ` +
      `The week of ${date} is still being planned, so it is counted once it ends.`,
    asOf: time => `Numbers as of ${time}.`,
    keyLine: (label, actual, goal, percent) => !goal
      ? `${label}: ${actual}. No goal was set for it the week before.`
      : percent == null
        ? `${label}: no result yet, with a goal of ${goal} set the week before.`
        : `${label}: ${actual}, with a goal of ${goal} set the week before (${percent}%).`,
    allReached: 'Every key indicator reached the goal set for it.',
    reached: labels => `Goal reached: ${labels.join(', ')}.`,
    closest: (label, actual, goal, percent) => `Closest to its goal: ${label}, ${actual} of ${goal} (${percent}%).`,
    rose: (label, by) => `${label} rose by ${by} from the week before.`,
    plans: (submitted, total) => `${submitted} of ${total} weekly plans were submitted.`,
    firstWeek: 'This is the first week with numbers, so there is no earlier goal to compare it with.',
    noPlans: 'No weekly plans were saved for this week.',
    noWeeks: 'No finished reporting weeks yet. The numbers appear here once the first week has ended.',
    goal: value => `goal ${value}`,
    ofGoal: percent => `${percent}% of the goal`,
    more: value => `${value} more than the week before`,
    fewer: value => `${value} fewer than the week before`,
    trendTitle: (label, weeks) => `${label}: result and goal, ${weeks} ${weeks === 1 ? 'week' : 'weeks'}`,
    zoneTitle: date => `By zone, week of ${date}`,
    trendCaption: label => `${label}, the whole mission, by week`,
    zoneCaption: (label, date) => `${label} by zone, week of ${date}`,
    submittedOf: (submitted, total) => `${submitted} of ${total}`,
    gathering: weeks => `Gathering ${weeks} weeks of numbers…`,
    expired: 'Your portal session has expired. Please sign in again.',
    failed: 'The mission\'s numbers could not load. Check your connection, then choose Try again.',
    noLibrary: 'The charts could not load. Choose Try again, and if it keeps happening, tell the data analysts.',
  };
  // Drawn inside the charts (legends, tooltips): translated here once a catalog has the text, otherwise English.
  const tr = text => {
    try { return window.MissionI18n?.translate ? window.MissionI18n.translate(text) : text; } catch { return text; }
  };

  const MARKUP = `
    <div class="gl-head">
      <div>
        <div class="gl-eyebrow"><span>Mission glimpse</span><span id="glMission" data-i18n-ignore></span></div>
        <h2 id="glTitle">The mission at a glance</h2>
        <p class="gl-sub" id="glSub">Finished weeks only, each measured against the goal companionships set the week before.</p>
      </div>
      <div class="gl-controls">
        <label class="gl-field">Finished week<select id="glWeek" disabled></select></label>
        <div class="gl-range" role="group" aria-label="Weeks shown in the charts">
          <button type="button" data-span="8" aria-pressed="false">8 weeks</button>
          <button type="button" data-span="12" aria-pressed="true">12 weeks</button>
          <button type="button" data-span="26" aria-pressed="false">26 weeks</button>
        </div>
        <button type="button" class="gl-toggle" id="glToggle" aria-controls="glMore" aria-expanded="true">Hide the charts</button>
      </div>
    </div>
    <div class="gl-status" id="glStatus" role="status" aria-live="polite"></div>
    <div class="gl-summary">
      <h3 id="glWeekTitle">The last finished week</h3>
      <p id="glSummary"><span class="gl-skeleton"></span></p>
    </div>
    <div class="gl-tiles" id="glTiles" role="group" aria-label="Key indicators. Choose one to see it by week and by zone."><span class="gl-skeleton"></span></div>
    <div class="gl-more" id="glMore">
      <div class="gl-charts">
        <section class="gl-card" aria-labelledby="glTrendTitle">
          <div class="gl-card-head">
            <div><h3 id="glTrendTitle">Result and goal by week</h3>
              <p>Each week's result next to the goal companionships set for it the week before, with a straight trend line.</p></div>
            <button type="button" class="gl-link" data-open="insights">More in Dashboards</button>
          </div>
          <div class="gl-chart gl-chart-trend" id="glTrend" data-i18n-ignore></div>
        </section>
        <section class="gl-card" aria-labelledby="glZoneTitle">
          <div class="gl-card-head">
            <div><h3 id="glZoneTitle">By zone</h3>
              <p>Each zone's result and the goal it set the week before. Zones by name, not a ranking.</p></div>
          </div>
          <div class="gl-chart" id="glZones" data-i18n-ignore></div>
        </section>
      </div>
      <details class="gl-card gl-table">
        <summary>Show the numbers as a table</summary>
        <div class="gl-table-wrap" id="glTrendTable"></div>
        <div class="gl-table-wrap" id="glZoneTable"></div>
      </details>
    </div>
    <p class="gl-note"><span>Every weekly plan counts, drafts too, as in Call-ins.</span><span id="glAsOf"></span></p>`;

  // started: mounted once. allowed: the server lets this person see it. shown: on screen. loading, data: the answer
  // of /api/dashboard. week: the chosen finished week (its Sunday). span: weeks in the charts (8, 12, 26); wanted: weeks
  // asked for. key: the indicator chosen in the tiles. ticket: only the newest answer is drawn. charts: ECharts by id.
  const state = {
    started: false, allowed: true, shown: false, loading: false, data: null, week: null, span: 12, wanted: 12,
    key: 'friends_found', ticket: 0, charts: {},
  };
  const root = () => document.getElementById('glimpse');
  const $ = id => document.getElementById(id);
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'})[c]);
  const reducedMotion = () => window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;

  // Dates and numbers follow the page language (English: day month year).
  const locale = () => {
    const lang = document.documentElement.lang || 'en';
    return /^en(-|$)/i.test(lang) ? 'en-GB' : lang;
  };
  function day(iso, options = {day: 'numeric', month: 'short'}) {
    const date = new Date(iso + 'T12:00:00');
    try { return date.toLocaleDateString(locale(), options); } catch { return date.toLocaleDateString('en-GB', options); }
  }
  const longDay = iso => day(iso, {day: 'numeric', month: 'long', year: 'numeric'});
  function num(value) {
    if (value == null) return '—';
    try { return new Intl.NumberFormat(locale(), {maximumFractionDigits: 1}).format(value); }
    catch { return new Intl.NumberFormat('en-GB', {maximumFractionDigits: 1}).format(value); }
  }
  // "Goal reached" (green with a tick) is decided from the numbers themselves, never from a rounded percentage: 311 of
  // a goal of 312 is not reached. The percentage is rounded down for the same reason, so it says 99%, not 100%.
  const reachedGoal = (actual, goal) => actual != null && goal > 0 && actual >= goal;
  const pct = (actual, goal) => actual == null || !goal ? null : Math.floor(actual / goal * 100);
  const css = name => getComputedStyle(root()).getPropertyValue(name).trim();

  // ---- ECharts, loaded once, only for the glimpse -------------------------------------------------------------------
  let library = null;
  function echartsReady() {
    if (window.echarts) return Promise.resolve(window.echarts);
    if (!library) {
      library = new Promise((resolve, reject) => {
        const script = document.createElement('script');
        script.src = 'echarts.min.js?v=6.0.0'; // the version in the address lets browsers keep it (nginx.conf)
        script.onload = () => (window.echarts ? resolve(window.echarts) : reject(Object.assign(Error('no chart library'), {library: true})));
        script.onerror = () => {
          library = null;
          script.remove();
          reject(Object.assign(Error('no chart library'), {library: true}));
        };
        document.head.append(script);
      });
    }
    return library;
  }

  // ---- numbers ----------------------------------------------------------------------------------------------------
  const weeks = () => state.data.weeks;
  const selected = () => weeks().findIndex(w => w.sunday === state.week);
  function range() {
    const end = selected(), start = Math.max(0, end - state.span + 1);
    return Array.from({length: end - start + 1}, (_, n) => start + n);
  }
  const indicator = key => state.data.indicators.find(i => i.key === key) || state.data.indicators[0];
  function missionFigures(i, key) {
    const m = weeks()[i].mission;
    return {actual: m.actual[key], goal: m.previous_goal[key], reports: m.reports, submitted: m.submitted};
  }
  function zoneFigures(i, key, zoneId) {
    const cell = weeks()[i].zones[String(zoneId)];
    return cell ? {actual: cell.actual[key], goal: cell.previous_goal[key], reports: cell.reports, submitted: cell.submitted}
      : {actual: null, goal: null, reports: 0, submitted: 0};
  }
  // Least-squares straight line through the weeks that have a result (at least three).
  function straightTrend(values) {
    const points = values.map((y, x) => [x, y]).filter(([, y]) => y != null);
    if (points.length < 3) return null;
    const n = points.length, sx = points.reduce((s, [x]) => s + x, 0), sy = points.reduce((s, [, y]) => s + y, 0);
    const sxx = points.reduce((s, [x]) => s + x * x, 0), sxy = points.reduce((s, [x, y]) => s + x * y, 0);
    const slope = (n * sxy - sx * sy) / (n * sxx - sx * sx || 1), start = (sy - slope * sx) / n;
    return values.map((_, x) => Math.round((start + slope * x) * 10) / 10);
  }

  // ---- charts -----------------------------------------------------------------------------------------------------
  function chart(id) {
    const el = $(id);
    if (state.charts[id] && state.charts[id].getDom() !== el) { state.charts[id].dispose(); delete state.charts[id]; }
    if (!state.charts[id]) state.charts[id] = window.echarts.init(el, null, {renderer: 'svg'});
    return state.charts[id];
  }
  function dispose(prefix = '') {
    for (const [id, instance] of Object.entries(state.charts)) {
      if (id.startsWith(prefix)) { instance.dispose(); delete state.charts[id]; }
    }
  }
  const axis = () => ({axisLine: {lineStyle: {color: css('--gl-axis')}}, axisTick: {show: false},
    axisLabel: {color: css('--muted'), fontSize: 11}, splitLine: {lineStyle: {color: css('--gl-grid')}}});
  const tooltip = () => ({backgroundColor: css('--panel'), borderColor: css('--line'), textStyle: {color: css('--text'), fontSize: 12},
    extraCssText: 'border-radius:10px;box-shadow:0 8px 24px #0000002a;'});
  const wash = alpha => new window.echarts.graphic.LinearGradient(0, 0, 0, 1, [
    {offset: 0, color: `rgba(${css('--gl-result-rgb')},${alpha})`}, {offset: 1, color: `rgba(${css('--gl-result-rgb')},0)`}]);
  const chartsShown = () => state.shown && !$('glMore').hidden;
  const LINE = 'path://M0 0H18V2.4H0Z';
  const DASHES = 'path://M0 0H5V2.4H0Z M6.5 0H11.5V2.4H6.5Z M13 0H18V2.4H13Z';
  const GOAL_ACROSS = 'path://M0 0H14V3.5H0Z';
  const GOAL_UPRIGHT = 'path://M0 0H3V14H0Z';

  // ---- rendering --------------------------------------------------------------------------------------------------
  function renderSummary() {
    const i = selected();
    const m = weeks()[i].mission;
    $('glWeekTitle').textContent = WORDS.weekOf(longDay(state.week));
    if (!m.reports) {
      $('glSummary').textContent = WORDS.noPlans;
      return;
    }
    const rows = state.data.indicators.map(ind => {
      const f = missionFigures(i, ind.key);
      return {...ind, ...f, p: pct(f.actual, f.goal), reached: reachedGoal(f.actual, f.goal),
        before: i > 0 ? weeks()[i - 1].mission.actual[ind.key] : null};
    });
    const key = rows.find(r => r.key_indicator) || rows[0];
    const parts = [WORDS.keyLine(key.label, num(key.actual), key.goal ? num(key.goal) : null, key.p)];
    const measured = rows.filter(r => r.p != null);
    const reached = measured.filter(r => r.reached);
    if (!measured.length) parts.push(WORDS.firstWeek);
    else if (reached.length === rows.length) parts.push(WORDS.allReached);
    else if (reached.length) parts.push(WORDS.reached(reached.map(r => r.label)));
    else {
      const closest = measured.slice().sort((a, b) => b.actual / b.goal - a.actual / a.goal)[0];
      if (closest !== key) parts.push(WORDS.closest(closest.label, num(closest.actual), num(closest.goal), closest.p));
    }
    const rise = rows.filter(r => r.actual != null && r.before != null && r.actual > r.before)
      .sort((a, b) => (b.actual - b.before) / Math.max(b.before, 1) - (a.actual - a.before) / Math.max(a.before, 1))[0];
    if (rise) parts.push(WORDS.rose(rise.label, num(rise.actual - rise.before)));
    parts.push(WORDS.plans(num(m.submitted), num(m.reports)));
    // One sentence per element, so each can be translated as a whole.
    $('glSummary').replaceChildren(...parts.flatMap((text, n) => {
      const sentence = document.createElement('span');
      sentence.textContent = text;
      return n ? [document.createTextNode(' '), sentence] : [sentence];
    }));
  }

  // A tile's foot: "Goal reached" (with a tick) or how far it got, then the change from the week before.
  function tileStatus(f, p) {
    if (reachedGoal(f.actual, f.goal)) return `<span class="gl-reached"><i aria-hidden="true">✓</i><span>Goal reached</span></span>`;
    return `<span>${esc(p != null ? WORDS.ofGoal(p) : f.goal ? 'No result yet' : 'No goal set')}</span>`;
  }

  function tileChange(change) {
    if (change == null) return '';
    if (change === 0) return '<span class="gl-delta">Same as the week before</span>';
    return `<span class="gl-delta${change > 0 ? ' up' : ''}"><span aria-hidden="true">${change > 0 ? '▲' : '▼'} </span>` +
      `${esc(change > 0 ? WORDS.more(num(change)) : WORDS.fewer(num(-change)))}</span>`;
  }

  // One tile: the indicator's name, the result and goal of week i, a bar towards the goal, and room for its sparkline.
  function tileMarkup(ind, i) {
    const f = missionFigures(i, ind.key), p = pct(f.actual, f.goal);
    const before = i > 0 ? weeks()[i - 1].mission.actual[ind.key] : null;
    const change = f.actual != null && before != null ? f.actual - before : null;
    return `<button type="button" class="gl-tile" data-key="${esc(ind.key)}" aria-pressed="${ind.key === state.key}">
        <span class="gl-tile-label"><span>${esc(ind.label)}</span>${ind.key_indicator ? '<span class="gl-chip">Key indicator</span>' : ''}</span>
        <span class="gl-figure"><strong data-i18n-ignore>${esc(num(f.actual))}</strong><span>${f.goal ? esc(WORDS.goal(num(f.goal))) : ''}</span></span>
        <span class="gl-meter" aria-hidden="true"><span style="width:${p == null ? 0 : Math.min(p, 100)}%"></span></span>
        <span class="gl-foot">${tileStatus(f, p)}${tileChange(change)}</span>
        <span class="gl-spark" id="spark-${esc(ind.key)}" aria-hidden="true" data-i18n-ignore></span>
      </button>`;
  }

  // The small line in a tile: the results of the weeks shown, the last one marked with a dot.
  function drawSparkline(ind, idx) {
    const values = idx.map(n => missionFigures(n, ind.key).actual);
    const last = values.length - 1;
    chart('spark-' + ind.key).setOption({
      animation: false, silent: true, grid: {left: 5, right: 5, top: 6, bottom: 5},
      xAxis: {type: 'category', show: false, boundaryGap: false, data: idx.map(n => weeks()[n].sunday)},
      yAxis: {type: 'value', show: false, scale: true},
      series: [{type: 'line', smooth: 0.3, data: values, showSymbol: false, lineStyle: {width: 2, color: css('--gl-result')},
        areaStyle: {color: wash(0.16)},
        markPoint: {symbol: 'circle', symbolSize: 8, label: {show: false},
          itemStyle: {color: css('--gl-result'), borderColor: css('--panel'), borderWidth: 2},
          data: last >= 0 && values[last] != null ? [{coord: [weeks()[idx[last]].sunday, values[last]]}] : []}}],
    });
  }

  function renderTiles() {
    const i = selected(), idx = range();
    dispose('spark-');
    $('glTiles').innerHTML = state.data.indicators.map(ind => tileMarkup(ind, i)).join('');
    for (const ind of state.data.indicators) drawSparkline(ind, idx);
  }

  function trendRows() {
    return range().map(n => ({sunday: weeks()[n].sunday, ...missionFigures(n, state.key)}));
  }
  function zoneRows() {
    const i = selected();
    return state.data.zones.map(z => ({...z, ...zoneFigures(i, state.key, z.id)})).map(r => ({...r, p: pct(r.actual, r.goal)}));
  }

  function renderTrend() {
    const rows = trendRows(), trend = straightTrend(rows.map(r => r.actual)), label = indicator(state.key).label;
    $('glTrendTitle').textContent = WORDS.trendTitle(label, rows.length);
    if (!chartsShown()) return;
    const a = axis(), names = {result: tr('Result'), goal: tr('Goal set the week before'), trend: tr('Trend (straight line)')};
    chart('glTrend').setOption({
      aria: {enabled: true}, animation: !reducedMotion(), animationDuration: 500,
      grid: {left: 8, right: 52, top: 40, bottom: 8, containLabel: true},
      // Legend keys drawn like the marks: a solid line, the goal's short bar, a dashed line.
      legend: {top: 0, left: 0, itemWidth: 18, itemHeight: 8, textStyle: {color: css('--text'), fontSize: 12},
        data: [{name: names.result, icon: LINE, itemStyle: {color: css('--gl-result'), borderWidth: 0}},
          {name: names.goal, icon: GOAL_ACROSS, itemStyle: {color: css('--gl-goal')}},
          ...(trend ? [{name: names.trend, icon: DASHES, itemStyle: {color: css('--gl-trend')}}] : [])]},
      tooltip: {trigger: 'axis', ...tooltip(), axisPointer: {type: 'line', lineStyle: {color: css('--gl-axis')}},
        formatter: items => {
          const n = items[0].dataIndex, r = rows[n], p = pct(r.actual, r.goal);
          return `<b>${esc(tr(WORDS.weekOf(longDay(r.sunday))))}</b><br>${esc(names.result)}: <b>${esc(num(r.actual))}</b><br>` +
            `${esc(names.goal)}: ${esc(num(r.goal))}${p != null ? ' · ' + esc(tr(WORDS.ofGoal(p))) : ''}<br>` +
            (trend ? `${esc(names.trend)}: ${esc(num(trend[n]))}<br>` : '') +
            `<span style="opacity:.75">${esc(tr(WORDS.plans(num(r.submitted), num(r.reports))))}</span>`;
        }},
      xAxis: {type: 'category', boundaryGap: false, data: rows.map(r => day(r.sunday)), ...a, splitLine: {show: false},
        axisLabel: {...a.axisLabel, showMaxLabel: true, hideOverlap: true}},
      yAxis: {type: 'value', ...a, axisLine: {show: false}, minInterval: 1},
      series: [
        {name: names.result, type: 'line', data: rows.map(r => r.actual), smooth: 0.25, symbol: 'circle', symbolSize: 8,
          showSymbol: rows.length <= 16, lineStyle: {width: 2, color: css('--gl-result')},
          itemStyle: {color: css('--gl-result'), borderColor: css('--panel'), borderWidth: 2}, areaStyle: {color: wash(0.1)}, z: 3,
          endLabel: {show: rows.some(r => r.actual != null), formatter: p => num(p.value), color: css('--text'), fontWeight: 700, distance: 8}},
        {name: names.goal, type: 'scatter', data: rows.map(r => r.goal), symbol: 'rect', symbolSize: [14, 3],
          itemStyle: {color: css('--gl-goal'), opacity: 0.85}, z: 4},
        ...(trend ? [{name: names.trend, type: 'line', data: trend, symbol: 'none', smooth: false,
          lineStyle: {width: 2, type: [6, 5], color: css('--gl-trend')}, itemStyle: {color: css('--gl-trend')}, z: 2}] : []),
      ],
    }, true);
  }

  function renderZones() {
    const rows = zoneRows();
    $('glZoneTitle').textContent = WORDS.zoneTitle(day(state.week));
    if (!chartsShown()) return;
    const el = $('glZones');
    el.style.height = Math.max(180, rows.length * 40 + 56) + 'px';
    const a = axis(), names = {result: tr('Result'), goal: tr('Goal set the week before')};
    const instance = chart('glZones');
    instance.resize();
    instance.setOption({
      aria: {enabled: true}, animation: !reducedMotion(), animationDuration: 500,
      grid: {left: 4, right: 4, top: 30, bottom: 4, containLabel: true},
      legend: {top: 0, left: 0, itemWidth: 14, itemHeight: 8, textStyle: {color: css('--text'), fontSize: 12},
        data: [{name: names.result, icon: 'roundRect', itemStyle: {color: css('--gl-result')}},
          {name: names.goal, icon: GOAL_UPRIGHT, itemStyle: {color: css('--gl-goal')}}]},
      tooltip: {trigger: 'axis', axisPointer: {type: 'shadow', shadowStyle: {color: css('--soft')}}, ...tooltip(),
        formatter: items => {
          const r = rows[items[0].dataIndex];
          return `<b>${esc(r.name)}</b><br>${esc(names.result)}: <b>${esc(num(r.actual))}</b><br>${esc(names.goal)}: ${esc(num(r.goal))}` +
            `${r.p != null ? ' · ' + esc(tr(WORDS.ofGoal(r.p))) : ''}<br>` +
            `<span style="opacity:.75">${esc(tr(WORDS.plans(num(r.submitted), num(r.reports))))}</span>`;
        }},
      yAxis: [
        {type: 'category', inverse: true, data: rows.map(r => r.name), ...a, axisLine: {show: false},
          axisLabel: {color: css('--text'), fontSize: 12, fontWeight: 600, width: 104, overflow: 'truncate'}},
        {type: 'category', inverse: true, position: 'right', axisLine: {show: false}, axisTick: {show: false},
          axisLabel: {color: css('--muted'), fontSize: 11, margin: 10},
          data: rows.map(r => r.reports
            ? `${num(r.actual)}${r.goal ? ' / ' + num(r.goal) : ''}${r.p != null ? ' · ' + r.p + '%' : ''}` : tr('No plans'))},
      ],
      xAxis: {type: 'value', ...a, axisLine: {show: false}, minInterval: 1, axisLabel: {...a.axisLabel, hideOverlap: true}},
      series: [
        {name: names.result, type: 'bar', barMaxWidth: 16, data: rows.map(r => r.actual ?? 0),
          itemStyle: {color: css('--gl-result'), borderRadius: [0, 4, 4, 0]}},
        {name: names.goal, type: 'scatter', data: rows.map(r => r.goal), symbol: 'rect', symbolSize: [3, 22],
          itemStyle: {color: css('--gl-goal')}, z: 3},
      ],
    }, true);
  }

  // The table view: every value of both charts, readable without a chart.
  function renderTables() {
    const label = indicator(state.key).label;
    const head = first => `<thead><tr><th>${first}</th><th>Result</th><th>Goal set the week before</th><th>% of the goal</th><th>Plans submitted</th></tr></thead>`;
    const cells = r => {
      const p = pct(r.actual, r.goal);
      return `<td data-i18n-ignore>${esc(num(r.actual))}</td><td data-i18n-ignore>${esc(num(r.goal))}</td>` +
        `<td data-i18n-ignore>${p == null ? '—' : esc(p + '%')}</td><td data-i18n-ignore>${esc(WORDS.submittedOf(num(r.submitted), num(r.reports)))}</td>`;
    };
    $('glTrendTable').innerHTML = `<table><caption>${esc(WORDS.trendCaption(label))}</caption>${head('Week of')}<tbody>${
      trendRows().reverse().map(r => `<tr><td data-i18n-ignore>${esc(day(r.sunday, {day: 'numeric', month: 'short', year: 'numeric'}))}</td>${cells(r)}</tr>`).join('')
    }</tbody></table>`;
    $('glZoneTable').innerHTML = `<table><caption>${esc(WORDS.zoneCaption(label, longDay(state.week)))}</caption>${head('Zone')}<tbody>${
      zoneRows().map(r => `<tr><td data-i18n-ignore>${esc(r.name)}</td>${cells(r)}</tr>`).join('')
    }</tbody></table>`;
  }

  function renderWeeks() {
    const list = weeks(), latest = list.at(-1).sunday;
    $('glWeek').innerHTML = list.slice().reverse().map(w => `<option value="${esc(w.sunday)}"${w.sunday === state.week ? ' selected' : ''}>${
      esc(w.sunday === latest ? WORDS.latestWeek(longDay(w.sunday)) : WORDS.weekOf(longDay(w.sunday)))}</option>`).join('');
    $('glWeek').disabled = false;
    $('glSub').textContent = WORDS.subtitle(longDay(state.data.current_week));
    $('glAsOf').textContent = state.data.read_at
      ? WORDS.asOf(new Date(state.data.read_at).toLocaleTimeString(locale(), {hour: '2-digit', minute: '2-digit'})) : '';
  }

  // Everything, from state.data. Nothing is drawn while the glimpse is hidden (charts need their size); showing it
  // again draws it.
  function render() {
    if (!state.data || !state.shown) return;
    $('glMission').textContent = state.data.mission ? ' · ' + state.data.mission : '';
    if (!weeks().length) {
      $('glWeekTitle').textContent = 'The last finished week';
      $('glSummary').textContent = WORDS.noWeeks;
      $('glTiles').innerHTML = '';
      $('glMore').hidden = true;
      $('glToggle').hidden = true;
      return;
    }
    if (!state.week || !weeks().some(w => w.sunday === state.week)) state.week = weeks().at(-1).sunday;
    renderWeeks();
    renderSummary();
    renderTiles();
    renderTrend();
    renderZones();
    renderTables();
  }

  // ---- loading ----------------------------------------------------------------------------------------------------
  function say(message, error = false) {
    const status = $('glStatus');
    status.replaceChildren();
    status.classList.toggle('error', !!error);
    if (!message) return;
    const text = document.createElement('span');
    text.textContent = message;
    status.append(text);
    if (error) {
      const retry = document.createElement('button');
      retry.type = 'button';
      retry.className = 'gl-retry';
      retry.textContent = 'Try again';
      retry.addEventListener('click', () => load(state.wanted));
      status.append(retry);
    }
  }

  async function numbers(weeksWanted, retry = true) {
    try {
      return await window.portalAPI('dashboard' + (weeksWanted !== 12 ? '?weeks=' + weeksWanted : ''));
    } catch (error) {
      if (retry && error.message === 'Your session changed. Please retry.') return numbers(weeksWanted, false);
      throw error;
    }
  }

  async function load(weeksWanted) {
    const ticket = ++state.ticket;
    state.loading = true;
    state.wanted = weeksWanted;
    const refreshing = !!state.data;
    if (refreshing) {
      root().classList.add('gl-refreshing');
      say(WORDS.gathering(weeksWanted));
    }
    try {
      // The chart library has been loading since start(); a refusal (403) is known before it is needed.
      const data = await numbers(weeksWanted);
      await echartsReady();
      if (ticket !== state.ticket) return;
      state.data = data;
      say('');
      render();
    } catch (error) {
      if (ticket !== state.ticket) return;
      if (error.status === 403) {
        // Not a manager (any more): no glimpse, and nothing to say about it.
        state.allowed = false;
        setShown(false);
        return;
      }
      const message = error.library ? WORDS.noLibrary : error.status === 401 ? WORDS.expired : WORDS.failed;
      say(message, true);
      if (!state.data) {
        $('glSummary').textContent = message;
        $('glTiles').innerHTML = '';
      }
    } finally {
      if (ticket === state.ticket) {
        state.loading = false;
        root()?.classList.remove('gl-refreshing');
      }
    }
  }

  // ---- showing, hiding, controls ----------------------------------------------------------------------------------
  // Drawn again only when it comes back into view: every /api/overview answer calls start() through update(), and
  // drawing the charts a second time (on a phone about a second) held up the Overview's own cards.
  function setShown(shown) {
    const el = root();
    if (!el) return;
    const appears = shown && !state.shown;
    el.hidden = !shown;
    state.shown = shown;
    if (appears) render();
  }

  const CHARTS_KEY = 'gfm_glimpse_charts';
  function setChartsOpen(open, remember) {
    $('glMore').hidden = !open;
    $('glToggle').setAttribute('aria-expanded', String(open));
    $('glToggle').textContent = open ? 'Hide the charts' : 'Show the charts';
    if (remember) {
      try { if (open) localStorage.removeItem(CHARTS_KEY); else localStorage.setItem(CHARTS_KEY, 'hidden'); } catch {}
    }
    if (open && state.data && weeks().length) { renderTrend(); renderZones(); }
  }

  function mount() {
    const el = root();
    el.innerHTML = MARKUP;
    let open = true;
    try { open = localStorage.getItem(CHARTS_KEY) !== 'hidden'; } catch {}
    setChartsOpen(open, false);
    $('glWeek').addEventListener('change', event => { state.week = event.target.value; render(); });
    el.querySelector('.gl-range').addEventListener('click', event => {
      const button = event.target.closest('button[data-span]');
      if (!button || !state.data) return;
      state.span = Number(button.dataset.span);
      el.querySelectorAll('.gl-range button').forEach(b => b.setAttribute('aria-pressed', String(b === button)));
      if (state.span > state.data.weeks_shown && state.data.finished_weeks > state.data.weeks_shown) load(state.span);
      else render();
    });
    $('glToggle').addEventListener('click', () => setChartsOpen($('glMore').hidden, true));
    $('glTiles').addEventListener('click', event => {
      const tile = event.target.closest('.gl-tile');
      if (!tile) return;
      state.key = tile.dataset.key;
      el.querySelectorAll('.gl-tile').forEach(t => t.setAttribute('aria-pressed', String(t === tile)));
      renderTrend();
      renderZones();
      renderTables();
    });
    // "More in Dashboards": the portal shell opens it (only for someone who has it); on its own, the portal does.
    el.addEventListener('click', event => {
      const button = event.target.closest('[data-open]');
      if (!button) return;
      if (window.parent !== window) window.parent.postMessage({type: 'gfm-open-page', page: button.dataset.open}, location.origin);
      else location.href = '/#' + button.dataset.open;
    });
  }

  // Redraw on a theme change (the colours come from CSS), a language change and a new size.
  let redraw = 0;
  const redrawSoon = () => {
    cancelAnimationFrame(redraw);
    redraw = requestAnimationFrame(() => render());
  };
  new MutationObserver(redrawSoon).observe(document.documentElement, {attributes: true, attributeFilter: ['data-theme', 'lang']});
  window.addEventListener('mission-i18n-change', redrawSoon);
  let resizeTimer = 0;
  window.addEventListener('resize', () => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(() => {
      for (const instance of Object.values(state.charts)) instance.resize();
      if (state.data && state.shown && weeks().length) renderZones();
    }, 150);
  });

  // ---- for home.html ----------------------------------------------------------------------------------------------
  const api = {
    hinted,
    // Shows the glimpse and, the first time, asks for its numbers.
    start() {
      if (!root() || !state.allowed) return;
      if (!state.started) {
        state.started = true;
        mount();
        echartsReady().catch(() => {});
        setShown(true);
        load(12);
        return;
      }
      setShown(true);
      if (!state.data && !state.loading) load(12);
    },
    // From home.html after each /api/overview answer: allowed = its "glimpse" flag; viewingArea = the manager is
    // looking at another area's goals (the glimpse is their own mission's, so it steps aside until they go back).
    update({allowed, viewingArea}) {
      if (!allowed) {
        state.allowed = false;
        state.ticket++;
        state.loading = false;
        setShown(false);
        return;
      }
      state.allowed = true;
      if (viewingArea) setShown(false);
      else api.start();
    },
  };
  window.MissionGlimpse = api;

  if (hinted) {
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', () => api.start(), {once: true});
    else api.start();
  }
})();
