// The browser script every page on the manager address loads first (GET /_manager/portal-bridge.js).
//
// What it is: the pages' link to the mission portal around them.
// - Sign-in: the portal keeps the Presentations sign-in alive by calling POST /api/session itself. Pages here only
//   ask it to do that with a 'presentations-session-request' message; no token ever reaches this address by
//   postMessage. PresentationSession.api() calls the manager and asks for a renewal once when the sign-in ended.
// - Theme: the portal's colour theme (mission, light, dark), sent by the portal.
// - Language: it loads the portal's i18n.js, which shows every English text of the page in the person's language.
// Who uses it: the library (library.html), the editor page (studio.html), the small message pages (pages.mjs) and
// the Whiteboard frames (whiteboard-frames.mjs).
// How it fits: pages.mjs fills in ORIGINS (PRESENTATIONS_PORTAL_ORIGINS) when the manager starts.
(() => {
  const ORIGINS = __PORTAL_ORIGINS__;
  // Like the server: the portal on this same machine (the hostname used for
  // this page) on a configured portal port counts too, so a new LAN address
  // or a hostname keeps working without a configuration change.
  const PORTALS = [...new Set(ORIGINS.concat(ORIGINS.map(origin => { try { const u = new URL(origin); u.hostname = location.hostname; return u.origin; } catch { return origin; } })))];
  const root = document.documentElement, THEMES = ['mission', 'light', 'dark'], THEME_KEY = 'gfm-presentations-theme';
  const inPortal = window.parent !== window;
  let expiresAt = 0, timer = 0, pending = null;

  // Interface translation (round 6, docs/handoff/round6/i18n.md): the portal's i18n.js and catalogs translate the
  // library, the /studio bar and the chart builder into the language the portal chose (the gfm_lang cookie on this
  // host, the portal's {type:'mission-language'} messages, or ?lang=). Deck content is never translated.
  const language = (/(?:^|;\s*)gfm_lang=([^;]+)/.exec(document.cookie) || [])[1] || new URLSearchParams(location.search).get('lang') || '';
  if (/^(fa|ar|pes|ara)(-|$)/i.test(decodeURIComponent(language))) root.dir = 'rtl';
  // On a public name (round 10, presentations.example.org) the portal of its domain
  // (https://example.org), else the portal of this computer name, like pages.mjs pickPortal.
  const hostnameOf = origin => { try { return new URL(origin).hostname; } catch { return ''; } };
  const portal = PORTALS.find(origin => hostnameOf(origin) && location.hostname.endsWith('.' + hostnameOf(origin)))
    || PORTALS.find(origin => hostnameOf(origin) === location.hostname)
    || PORTALS[0];
  if (portal && !window.MissionI18n) {
    const i18n = document.createElement('script');
    i18n.src = portal + '/i18n.js';
    document.head.appendChild(i18n);
  }

  try { const saved = localStorage.getItem(THEME_KEY); if (THEMES.includes(saved)) root.dataset.theme = saved; } catch {}

  function note(value) {
    const at = typeof value === 'number' ? value : Date.parse(value || '');
    if (!at) return;
    expiresAt = at; clearTimeout(timer);
    // Ask a few minutes early; the shell's own timer usually gets there first.
    timer = setTimeout(() => refresh().catch(() => {}), Math.max(30000, expiresAt - Date.now() - 180000));
  }

  function settle(ok, value) {
    if (!pending) return;
    const current = pending; pending = null; clearTimeout(current.timeout);
    ok ? current.resolve(value) : current.reject(value);
  }

  function refresh(timeoutMs = 10000) {
    if (!inPortal) return Promise.reject(new Error('Your presentation sign-in has ended. Open Presentations from the mission portal to continue.'));
    if (pending) return pending.promise;
    const current = {};
    current.promise = new Promise((resolve, reject) => { current.resolve = resolve; current.reject = reject; });
    current.timeout = setTimeout(() => settle(false, new Error('The mission portal did not renew your sign-in. Reload the portal and try again.')), timeoutMs);
    pending = current;
    // The request carries no secret. Posting to each allowed portal origin
    // means only the real portal receives it; the others are dropped.
    for (const origin of PORTALS) try { window.parent.postMessage({ type: 'presentations-session-request' }, origin); } catch {}
    return current.promise;
  }

  window.addEventListener('message', event => {
    if (!inPortal || event.source !== window.parent || !PORTALS.includes(event.origin)) return;
    const data = event.data || {};
    if (data.type === 'portal-theme') {
      const theme = THEMES.includes(data.theme) ? data.theme : 'mission';
      root.dataset.theme = theme;
      try { localStorage.setItem(THEME_KEY, theme); } catch {}
      window.dispatchEvent(new CustomEvent('gfm-theme', { detail: theme }));
    } else if (data.type === 'presentations-session-refreshed') {
      note(data.expires_at); settle(true, data.expires_at);
    } else if (data.type === 'presentations-session-error') {
      settle(false, new Error(data.message || 'Your sign-in could not be renewed. Reload the portal and try again.'));
    }
  });

  // X-GFM-Request: the manager answers its data routes only with this header (round 8, deck-origin.mjs). A page
  // on another address, such as a deck page, cannot send it, because the manager never allows that address.
  async function request(url, options = {}, retry = true) {
    const headers = { 'X-GFM-Request': '1', ...(options.body ? { 'Content-Type': 'application/json' } : {}), ...(options.headers || {}) };
    const response = await fetch(url, { credentials: 'same-origin', ...options, headers });
    if (response.status === 401 && retry) { await refresh(); return request(url, options, false); }
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      const error = new Error(data.error || 'Something went wrong. Please try again.');
      error.status = response.status; error.data = data; throw error;
    }
    return data;
  }

  // Makes sure this page has a presentation session, asking the portal for one if needed.
  async function ensure() {
    const response = await fetch('/api/session', { credentials: 'same-origin', headers: { 'X-GFM-Request': '1' } });
    if (response.ok) return note((await response.json()).expires_at);
    await refresh();
  }

  // portals: the portal origins this page trusts (the whiteboard frames answer only them).
  window.PresentationSession = { api: request, ensure, refresh, inPortal, portals: PORTALS.slice(), get expiresAt() { return expiresAt; } };
})();
