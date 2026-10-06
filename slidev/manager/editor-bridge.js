// Round 8: the editor's side of the talk between the /studio page and the editor inside it.
//
// The /studio page (studio.html) stays on the manager address (port 3030); the editor it shows in a frame (Slidev
// with Studio) runs on the deck address (port 8089), because the editor runs the deck's own code
// (deck-origin.mjs). Two addresses cannot look into each other's pages, so they send each other messages.
// Who uses it: deck-routes.mjs puts this script into the editor page (pages.mjs addEditorScripts) and fills in
// __SHELL_ORIGIN__ (the manager address). The other side is the script of studio.html.
//
// This page tells the /studio page (never anyone else):
//   gfm-editor-state  whether slides are on screen, whether Studio is saving, Studio's last error, what is
//                     selected (slide number, line range, tag, Studio's fingerprint, chart id) and the slide shown;
//   gfm-editor-input  the person just clicked on the slide or pressed a key that moves the selection.
// The /studio page may ask this page (and nobody else may):
//   gfm-editor-reload        load the editor again (after Source saved the slides);
//   gfm-editor-select-chart  select chart <chartId> on slide <no>, as a click would (go: first show that slide).
// Nothing secret goes either way. The deck's own code could send the same messages; the /studio page only uses
// them to show state and to select things in this same deck.
(() => {
  const SHELL = __SHELL_ORIGIN__;
  // The /studio page asks for Studio's side panel when it opens the editor on a wide screen (?gfm_studio_panel=open).
  // Studio keeps that setting in this address's own storage. The word is taken out of the address at once (before
  // Slidev starts), so a reload keeps whatever the person chose.
  const params = new URLSearchParams(location.search);
  if (params.get('gfm_studio_panel') === 'open') {
    try { localStorage.setItem('slidev-studio:open', 'true'); } catch {}
    params.delete('gfm_studio_panel');
    const rest = params.toString();
    history.replaceState(history.state, '', location.pathname + (rest ? '?' + rest : '') + location.hash);
  }
  if (window.parent === window || !SHELL) return;
  const post = message => { try { window.parent.postMessage(message, SHELL); } catch {} };
  // A new number each time the page loads, so the /studio page can tell a reload from the same page.
  const page = Math.random().toString(36).slice(2);

  // ---- GFM Studio startup measurement ----
  // What this page load cost, seen from inside the editor: when Studio, the first slide and the Studio panel appeared,
  // the long main-thread tasks (> 50 ms) and what was fetched (count and size by kind). Sent to the /studio page as
  // gfm-editor-perf when the editor is editable (and when asked: gfm-editor-perf-get), which adds the click-to-editable
  // timeline and prints it (window.GFM_PERF, console "[GFM STUDIO STARTUP]"). Times are ms since this page started loading.
  const perf = { loads: 1, marks: {}, longTasks: [] };
  const mark = name => { if (!(name in perf.marks)) perf.marks[name] = Math.round(performance.now()); };
  try {
    const loadsKey = 'gfm-perf-loads:' + location.pathname;
    perf.loads = Number(sessionStorage.getItem(loadsKey) || 0) + 1;
    sessionStorage.setItem(loadsKey, String(perf.loads));
    performance.setResourceTimingBufferSize(3000);
    new PerformanceObserver(list => { for (const e of list.getEntries()) perf.longTasks.push([Math.round(e.startTime), Math.round(e.duration)]); }).observe({ type: 'longtask', buffered: true });
  } catch {}
  function perfSnapshot() {
    const nav = performance.getEntriesByType('navigation')[0] || {};
    const kinds = {}, groups = {};
    let count = 0, wire = 0, size = 0, deps = 0, studioFiles = 0, upstreamStudioFiles = 0;
    const slow = [];
    for (const e of performance.getEntriesByType('resource')) {
      count++;
      wire += e.encodedBodySize || 0;
      size += e.decodedBodySize || 0;
      const kind = /\.css(\?|$)/.test(e.name) ? 'css' : /\.(png|jpe?g|svg|webp|gif|woff2?)(\?|$)/.test(e.name) ? 'media' : /\.(vue|ts|js|mjs)(\?|$)|\/@|\/node_modules\//.test(e.name) ? 'script' : e.initiatorType || 'other';
      (kinds[kind] ||= { n: 0, kb: 0 }).n++;
      kinds[kind].kb += Math.round((e.encodedBodySize || 0) / 1024);
      const group = (() => {
        const n = e.name.replace(location.origin, "");
        let m = n.match(/\/addons\/gfm-studio\/client\/ui\/(panels|parts)\//); if (m) return 'studio ' + m[1];
        if (/\/addons\/gfm-studio\//.test(n)) return 'studio other';
        if (/\/gfm-addon\//.test(n)) return 'gfm-addon';
        m = n.match(/\.vite\/deps\/([^?]+)/); if (m) return 'dep ' + m[1].replace(/\.js$/, '');
        m = n.match(/node_modules\/((?:@[^/]+\/)?[^/?]+)/); if (m) return m[1];
        return 'other';
      })();
      const g = (groups[group] ||= { n: 0, kb: 0 }); g.n++; g.kb += Math.round((e.decodedBodySize || 0) / 1024);
      if (/node_modules\/\.vite\/deps/.test(e.name)) deps++;
      if (/\/addons\/gfm-studio\//.test(e.name)) studioFiles++;
      else if (/slidev-addon-studio/.test(e.name)) upstreamStudioFiles++;
      slow.push([Math.round(e.duration), e.name.replace(location.origin, '').slice(0, 90)]);
    }
    slow.sort((a, b) => b[0] - a[0]);
    const long = perf.longTasks;
    const before = perf.marks.editable ?? Infinity;
    return {
      charts: window.__gfmChartPerf || null,
      loads: perf.loads, marks: perf.marks, nav: { response_end: Math.round(nav.responseEnd || 0), dom_interactive: Math.round(nav.domInteractive || 0), dcl: Math.round(nav.domContentLoadedEventEnd || 0), load: Math.round(nav.loadEventEnd || 0) },
      resources: { count, wire_kb: Math.round(wire / 1024), decoded_kb: Math.round(size / 1024), vite_deps: deps, studio_files: studioFiles, upstream_studio_files: upstreamStudioFiles, by_kind: kinds, groups, slowest: slow.slice(0, 5) },
      long_tasks: { count: long.length, total_ms: long.reduce((s, t) => s + t[1], 0), before_editable_ms: long.filter(t => t[0] < before).reduce((s, t) => s + t[1], 0), worst: long.slice().sort((a, b) => b[1] - a[1]).slice(0, 5) },
    };
  }
  function perfMarks() {
    if (document.querySelector('#slide-content, .slidev-page, .slidev-layout')) mark('first_slide_dom');
    if (window.__studio__) mark('studio_global');
    if (document.querySelector('.slidev-studio')) mark('studio_panel_dom');
    if (ready()) {
      mark('ready');
      if (window.__studio__ && document.querySelector('.slidev-studio') && !perf.marks.editable) { mark('editable'); post({ type: 'gfm-editor-perf', perf: perfSnapshot() }); }
    }
  }
  setInterval(perfMarks, 50);

  // Ready = a slide is on screen and Slidev's CSS utilities apply (they are missing for a moment on a cold start).
  function ready() {
    if (!document.body || !document.querySelector('#slide-content, .slidev-page, .slidev-layout')) return false;
    const probe = document.createElement('div');
    probe.className = 'absolute flex bottom-0 left-0';
    probe.style.visibility = 'hidden';
    document.body.appendChild(probe);
    const style = getComputedStyle(probe), ok = style.position === 'absolute' && style.display === 'flex';
    probe.remove();
    return ok;
  }

  // Studio's selection as plain values (its element cannot be sent).
  function selection(value) {
    if (!value) return null;
    let sig = '', chartId = '';
    try { sig = String(value.el?.dataset?.studioSig || ''); } catch {}
    try { chartId = String(value.el?.closest?.('[data-chart-id]')?.dataset?.chartId || value.el?.dataset?.chartId || ''); } catch {}
    const range = Array.isArray(value.range) ? [Number(value.range[0]), Number(value.range[1])] : null;
    return { no: Number(value.no) || 0, range, tag: String(value.tag || ''), sig, chartId };
  }

  function slideShown() {
    const m = location.pathname.match(/\/(\d+)\/?$/);
    return m ? Number(m[1]) : 0;
  }

  // The state, sent whenever it changes (checked every 300 ms).
  let last = '';
  function report() {
    const studio = window.__studio__;
    let busy = false, error = '', selected = null;
    try { busy = !!studio?.busy?.value; error = String(studio?.lastError?.value || ''); selected = selection(studio?.selection?.value); } catch {}
    const state = { type: 'gfm-editor-state', page, ready: ready(), busy, error: error.slice(0, 500), selection: selected, slide: slideShown() };
    const text = JSON.stringify(state);
    if (text !== last) { last = text; post(state); }
  }
  setInterval(report, 300);
  window.addEventListener('load', report);

  // Only what picks something on the slide counts: a press on the slide (not on Studio's panels or handles) or a
  // key that moves or clears the selection. Typing in the Element panel does not.
  const KEYS = ['Escape', 'Delete', 'Backspace', 'Tab', 'ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight', 'PageUp', 'PageDown', ' ', 'Enter'];
  function input(event) {
    if (!event.isTrusted) return;
    const target = event.target instanceof Element ? event.target : null;
    if (event.type === 'keydown' && (!KEYS.includes(event.key) || target?.closest('input, textarea, select, [contenteditable]'))) return;
    if (event.type === 'pointerdown' && target?.closest('.slidev-studio') && !target.closest('.studio-move')) return;
    post({ type: 'gfm-editor-input' });
  }
  window.addEventListener('pointerdown', input, true);
  window.addEventListener('keydown', input, true);

  /** The element of chart `chartId` on slide `no`, or null. */
  function chartElement(no, chartId) {
    try { return document.querySelector(`#slide-content [data-slidev-no="${Number(no)}"] [data-chart-id="${CSS.escape(chartId)}"]`); } catch { return null; }
  }

  /** Selects a chart the way a click does (Studio's own pointer handler reads the element). */
  function clickChart(el) {
    const box = el.getBoundingClientRect();
    const init = { bubbles: true, cancelable: true, composed: true, button: 0, buttons: 1, pointerId: 1, isPrimary: true, pointerType: 'mouse', clientX: box.left + box.width / 2, clientY: box.top + box.height / 2 };
    (el.querySelector('.gfm-chart__plot') || el).dispatchEvent(new PointerEvent('pointerdown', init));
    el.dispatchEvent(new PointerEvent('pointerup', init));
  }

  const busy = () => { try { return !!window.__studio__?.busy?.value; } catch { return false; } };

  function selectChart(no, chartId, go) {
    if (!chartId) return;
    if (!go) {
      // Studio moved its selection off the chart the person had picked: select it again.
      setTimeout(() => { const el = chartElement(no, chartId); if (el && !busy()) try { clickChart(el); } catch {} }, 60);
      return;
    }
    // After the chart builder saved: show that slide, wait until the chart is drawn again, then select it.
    const until = Date.now() + 5000;
    (function tryIt() {
      let current = 0;
      try { current = Number(window.__slidev__?.nav?.currentSlideNo || 0); } catch {}
      if (current && current !== no) { try { window.__slidev__.nav.go(no); } catch {} }
      if (chartElement(no, chartId) && !busy()) {
        // Studio re-finds its own selection first (up to about 1.5 s); ours comes after it.
        setTimeout(() => { const again = chartElement(no, chartId); if (again) try { clickChart(again); } catch {} }, 250);
        return;
      }
      if (Date.now() < until) setTimeout(tryIt, 150);
    })();
  }

  window.addEventListener('message', event => {
    if (event.source !== window.parent || event.origin !== SHELL) return;
    const data = event.data || {};
    if (data.type === 'gfm-editor-open-import') {
      // GFM Studio: the editor page's Paste presentation button (and a Markdown file chosen in its menu).
      try { const s = window.__studio__; if (data.text) s.importPrefill.value = String(data.text).slice(0, 1500000); s.importOpen.value = true; } catch {}
    }
    else if (data.type === 'gfm-editor-perf-get') post({ type: 'gfm-editor-perf', perf: perfSnapshot() });
    else if (data.type === 'gfm-editor-reload') location.reload();
    else if (data.type === 'gfm-editor-select-chart') selectChart(Number(data.no) || 0, String(data.chartId || ''), data.go === true);
  });
})();
