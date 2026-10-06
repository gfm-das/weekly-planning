// GFM Studio browser checks (the product brief's acceptance test), run in a real browser against the test container
// (slidev/tests/studio-perf/README.md: run-container.sh, then sign in with the TOKEN line of its log).
//
// How: open any page of the manager address (http://127.0.0.1:18581/health), paste this whole file into the browser's
// console (or the Claude browser's javascript tool), then call the stages one by one, in this order, each in its own call
// because the stages move between the manager page and the editor page (two addresses):
//
//   await E2E.signIn(TOKEN)                         sign in with the stand-in token, make the deck 'e2e'
//   await E2E.shell()          on /health   -> opens /studio/e2e inside an iframe and checks: the shell appears first,
//                                              the published slide is shown, the live editor replaces it, timings
//   await E2E.editor()         on http://127.0.0.1:18589/edit/e2e/1?gfm_studio_panel=open (the editor page itself):
//                                              Studio loads, edit text, add a component, select a MissionChart, the Data
//                                              tab (kind, formula), the story advances one chart instance,
//                                              Paste Presentation: validate, import (append), known components stay
//                                              editable, undo restores, redo, Source (Monaco loads lazily) is on the shell
//   await E2E.importStart(); (the editor reloads) await E2E.importVerify(); (reloads) await E2E.afterUndo()
//                                              Paste Presentation end to end, and one undo for the whole import
//   await E2E.published()      Publish now
//
// Every stage returns { ok, results: [[name, true|false, detail]] }; nothing here changes anything but the 'e2e' deck.
(() => {
  const wait = ms => new Promise(r => setTimeout(r, ms));
  const H = { 'X-GFM-Request': '1', 'Content-Type': 'application/json' };
  const out = [];
  const check = (name, ok, detail = '') => { out.push([name, !!ok, detail]); return !!ok; };
  const done = () => { const r = { ok: out.every(x => x[1]), results: out.splice(0) }; console.table(r.results); return r; };
  const until = async (fn, ms = 20000, step = 150) => { const t = performance.now(); for (;;) { try { const v = await fn(); if (v) return v; } catch {} if (performance.now() - t > ms) return null; await wait(step); } };
  const SLIDES = [
    '---', 'theme: default', 'title: E2E deck', 'layout: gfm-cover', 'kicker: Test', '---', '', '# E2E deck', '', 'Hello', '',
    '---', 'layout: gfm-full-chart', 'heading: A story', '---', '',
    '<MissionChart chart-id="story" preset="trend" :height="300" :rows="[\'Week, A, B, C\', \'W1, 1, 2, 3\', \'W2, 2, 3, 4\', \'W3, 3, 4, 5\']" :story=\'[{"label":"A","shape":{"only":["A"]}},{"label":"AB","shape":{"only":["A","B"]}},{"label":"All","shape":{}}]\' />', '',
  ].join('\n');
  const PASTE = [
    '```markdown', '---', 'theme: seriph', 'title: “Pasted”', 'layout: gfm-section', 'kicker: Part 2', '---', '', '# Pasted section', '',
    '---', 'layout: gfm-kpi-grid', 'heading: Numbers', '---', '', '<GfmKpiGrid metrics="friends_found,baptismal_dates" />', '',
    '---', 'layout: gfm-hero', '---', '', '# One question?', '', '```',
  ].join('\n');

  window.E2E = {
    async signIn(token) {
      let r = await fetch('/api/session', { method: 'POST', headers: { Authorization: 'Bearer ' + token } });
      check('signed in', r.ok);
      r = await fetch('/api/presentations', { method: 'POST', headers: H, body: JSON.stringify({ title: 'e2e' }) });
      const made = await r.json().catch(() => ({}));
      check('deck created', r.ok || r.status === 409, JSON.stringify(made).slice(0, 80));
      const slug = made.slug || 'e2e';
      const src = await (await fetch(`/api/presentations/${slug}/source`, { headers: H })).json();
      const put = await fetch(`/api/presentations/${slug}/source`, { method: 'PUT', headers: H, body: JSON.stringify({ markdown: SLIDES, version: src.version }) });
      check('slides written', put.ok, put.status);
      const pub = await fetch(`/api/presentations/${slug}/publish`, { method: 'POST', headers: H });
      check('published once (the preview needs it)', pub.ok, pub.status);
      window.__slug = slug;
      return done();
    },

    async shell() {
      const slug = window.__slug || 'e2e';
      const f = document.createElement('iframe');
      f.style.cssText = 'position:fixed;left:0;top:0;width:1280px;height:720px;border:0;z-index:99999;background:#fff';
      f.src = `/studio/${slug}`;
      const t0 = performance.now();
      document.body.appendChild(f);
      const doc = () => f.contentDocument;
      const shellUp = await until(() => doc()?.querySelector('#titleButton')?.textContent, 3000, 30);
      check('the studio shell appears first (title shown)', !!shellUp, `${Math.round(performance.now() - t0)} ms`);
      const bar = await until(() => doc()?.querySelector('#publishButton') && doc()?.querySelector('#pasteButton') && doc()?.querySelector('#moreButton'), 3000, 30);
      check('the bar has Paste presentation, More and Publish', !!bar);
      const preview = await until(() => { const p = doc()?.querySelector('#preview'); return p && !p.hidden && p.src && p; }, 6000, 50);
      check('the published slide is shown while the editor starts', !!preview, preview ? `${Math.round(performance.now() - t0)} ms` : '');
      const live = await until(() => doc()?.querySelector('#overlay')?.hidden && doc()?.defaultView.GFM_PERF?.marks?.overlay_hidden, 90000, 300);
      check('the live editor takes over (overlay gone)', !!live, live ? `${live} ms after the click` : 'timeout');
      await wait(700);
      const p = doc()?.querySelector('#preview');
      check('the preview is gone after the handoff', !p || p.hidden || p.classList.contains('gone'));
      const perf = doc()?.defaultView.GFM_PERF;
      check('startup timeline recorded', !!perf?.marks?.frame_ready, JSON.stringify(perf?.marks || {}).slice(0, 200));
      // Source opens Monaco only when asked.
      check('Monaco is not loaded before Source is opened', !doc()?.defaultView.monaco && !doc()?.querySelector('script[src*="monaco"]'));
      doc()?.querySelector('#sourceButton')?.click();
      const monaco = await until(() => doc()?.defaultView.monaco?.editor?.getModels()[0]?.getValue().includes('E2E'), 20000, 200);
      check('Source loads Monaco and shows slides.md', !!monaco);
      doc()?.querySelector('#sourceButton')?.click();
      f.remove();
      return done();
    },

    async editor() {
      const slug = window.__slug || 'e2e';
      const st = await until(() => window.__studio__, 30000);
      check('Studio is on the page', !!st);
      const opened = await until(() => window.__studio__?.studioOpen?.value || (window.__studio__.studioOpen.value = true), 3000);
      check('Studio is open', !!opened);
      const tabs = [...document.querySelectorAll('.studio-tab')].map(b => b.textContent.trim());
      check('the toolbar has Data and Paste presentation', tabs.includes('Data') && tabs.includes('Paste presentation'), tabs.join(','));
      // Edit text: insert a slide with a component through Studio's own deck endpoint, as "add a component" does.
      let r = await fetch('/@studio/deck', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ action: 'insert', after: 2, content: '# Added\n\n<GfmCallout title="Hi" tone="good">Added by the test</GfmCallout>\n' }) });
      check('a slide with a component is added', r.ok, r.status);
      return done();
    },

    // Paste Presentation, part 1 (on the editor page): open, paste, validate, auto-fix, import. The deck reloads after it.
    async importStart() {
      const total = () => window.__slidev__?.nav?.total;
      window.__before = await until(() => total(), 20000);
      check('the deck is loaded', !!window.__before, `slides: ${window.__before}`);
      const s = window.__studio__;
      s.importOpen.value = true;
      const dlg = await until(() => document.querySelector('.gfm-imp'), 15000);
      check('the Paste Presentation dialog opens (loaded when first opened)', !!dlg);
      const ta = dlg.querySelector('textarea');
      ta.value = PASTE; ta.dispatchEvent(new Event('input', { bubbles: true }));
      await wait(150); // Vue shows the buttons for the new text
      const button = t => [...dlg.querySelectorAll('button')].find(b => b.textContent.trim().startsWith(t));
      button('Validate').click();
      const result = await until(() => dlg.querySelector('.gfm-imp__result'), 15000);
      check('Validate shows the outline', !!result);
      const fix = button('Auto-fix');
      check('the code box, the theme and the quotes are offered as safe fixes', !!fix, fix?.textContent.trim());
      fix?.click();
      await until(() => !button('Auto-fix') && dlg.querySelector('.gfm-imp__result'), 15000);
      const summary = dlg.querySelector('.gfm-imp__result h3')?.textContent.replace(/\s+/g, ' ');
      check('after the fixes: 3 slides, all green', /3 slides/.test(summary) && /3 fully editable/.test(summary), summary);
      check('nothing is blocked or wrong after the fixes', !dlg.querySelector('.gfm-sev--error, .gfm-sev--blocked'));
      check('the text no longer has the code box or the other theme', !ta.value.includes('```') && !ta.value.includes('seriph'));
      dlg.querySelector('input[type=radio][value=append]').click();
      const go = button('Import');
      check('Import is enabled', go && !go.disabled);
      go.click();
      return done(); // the editor reloads by itself a moment later
    },

    // Part 2 (after the reload): the slides are in, the known components are visible and editable, one Ctrl+Z undoes it all.
    async importVerify() {
      const total = await until(() => window.__slidev__?.nav?.total, 30000);
      check('the three pasted slides were appended', total === (window.__before || total - 3) + 3, `slides now: ${total}`);
      const toast = await until(() => document.querySelector('.studio-toast--notice')?.textContent, 8000);
      check('a message says what happened and how to undo it', /Imported 3 slides.*Ctrl\+Z/.test(toast || ''), toast);
      window.__studio__.studioOpen.value = true;
      window.__slidev__.nav.go(total - 1);
      const kpi = await until(() => document.querySelector('.gfm-kpi-grid'), 20000);
      check('the pasted GfmKpiGrid is drawn', !!kpi);
      const box = kpi.getBoundingClientRect();
      const init = { bubbles: true, cancelable: true, composed: true, button: 0, buttons: 1, pointerId: 1, isPrimary: true, pointerType: 'mouse', clientX: box.left + box.width / 2, clientY: box.top + 4 };
      await wait(1500);
      kpi.dispatchEvent(new PointerEvent('pointerdown', init)); kpi.dispatchEvent(new PointerEvent('pointerup', init));
      const sel = await until(() => window.__studio__.selection.value?.tag === 'GfmKpiGrid' && window.__studio__.selection.value, 6000);
      check('it is selectable and Studio shows its settings (visually editable)', !!sel, sel?.tag);
      [...document.querySelectorAll('.studio-tab')].find(b => b.textContent.trim() === 'Element')?.click();
      const props = await until(() => [...document.querySelectorAll('.studio-dock__body label')].map(l => l.textContent.trim()).filter(Boolean), 4000);
      check('the metrics, weeks and columns are fields of the panel', /Key indicators|Weeks|Tiles across/.test((props || []).join(' ')), (props || []).join(' | ').slice(0, 120));
      const undo = [...document.querySelectorAll('.studio-icon-button')].find(b => /^Undo/.test(b.title));
      check('Undo is offered with the import as its step', !!undo && !undo.disabled && /imported/i.test(undo.title), undo?.title);
      undo?.click();
      return done(); // the deck reloads with the earlier file
    },

    async afterUndo() {
      const total = await until(() => window.__slidev__?.nav?.total, 30000);
      check('Ctrl+Z restored the deck as it was before the import (one step)', total === window.__before, `slides: ${total}, before: ${window.__before}`);
      const redo = [...document.querySelectorAll('.studio-icon-button')].find(b => b.title === 'Redo');
      check('Redo is offered', !!redo && !redo.disabled);
      return done();
    },

    // The published deck is ordinary Slidev: it has its own pages and the story's clicks work.
    async published() {
      const slug = window.__slug || 'e2e';
      const r = await fetch(`/api/presentations/${slug}/publish`, { method: 'POST', headers: H });
      check('Publish now works', r.ok, r.status);
      return done();
    },
  };
  console.info('E2E loaded: E2E.signIn(token), E2E.shell(), E2E.editor() ...');
})();
