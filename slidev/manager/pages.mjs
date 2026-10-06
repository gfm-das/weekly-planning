// The pages the manager makes itself, and the small pieces it adds to Slidev's pages.
//
// What it is:
//   - the library (library.html) and the editor page /studio (studio.html), filled in with the deck's data;
//   - small message pages: "Not available", "Presentation not found", "Signing you in…", "Please open the
//     presentation again", and the confirm page "Open this presentation?";
//   - pieces added to Slidev's pages: the ✎ edit button on a published deck, the script that keeps a deck page's
//     pass alive, and the editor's two helper scripts (a one-time reload on a cold start, editor-bridge.js).
// The pages load the portal's i18n.js (directly or through portal-bridge.js), which shows their English texts in
// the person's language. Every text here is in portal/i18n/<language>.json.
// Who uses it: manager-routes.mjs and deck-routes.mjs.
// How it fits: plain strings of HTML. Anything that comes from a person (a deck's title) is escaped first.
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { hostnameOf, PASS_KEEPALIVE_MS } from './deck-origin.mjs';
import { FAVICON_DATA_URL } from './gfm-addon/lib/favicon.mjs';
import { MANAGER_DIR, PORTAL_ORIGINS, PORTAL_PORTS } from './settings.mjs';
import { OPEN_AGAIN } from './sign-in.mjs';
import { escapeHtml, keptText } from './web.mjs';
import { portalSources } from './whiteboard-frames.mjs';

const read = name => readFileSync(path.join(MANAGER_DIR, name), 'utf8');

// ---- the library and the editor page ----

/** The library page (library.html with the tab icon). */
export const LIBRARY_PAGE = read('library.html').split('__FAVICON__').join(FAVICON_DATA_URL);

// studio.html cut at its placeholders once, when the manager starts. Filling the pieces in one by one means a deck's
// title can never be read as a placeholder or as a replace pattern ($' or $&).
const STUDIO_PARTS = read('studio.html').split(/(__TITLE_HTML__|__STUDIO_DATA__|__FAVICON__|__NONCE__)/);

/**
 * The /studio page for a deck. data: what the page's script gets as window.STUDIO ({ slug, title, protected_reason,
 * deck_origin }); nonce: the one its Content-Security-Policy names (its two inline scripts carry it).
 */
export function studioPage(title, data, nonce) {
  const fill = {
    __TITLE_HTML__: escapeHtml(title),
    __STUDIO_DATA__: JSON.stringify(data).replaceAll('<', '\\u003c'),
    __FAVICON__: FAVICON_DATA_URL,
    __NONCE__: nonce,
  };
  return STUDIO_PARTS.map((part, i) => (i % 2 ? fill[part] : part)).join('');
}

// ---- the shared browser scripts ----

/**
 * portal-bridge.js with the portal's addresses filled in (it asks only them to renew the sign-in), kept packed
 * (web.mjs keptText; manager-routes.mjs sends it with sendKept).
 */
export const PORTAL_BRIDGE = keptText(read('portal-bridge.js')
  .replace('const ORIGINS = __PORTAL_ORIGINS__;', () => `const ORIGINS = ${JSON.stringify([...PORTAL_ORIGINS])};`));

// Put into the editor page on the deck address, so it can talk to the /studio page around it (round 8).
const EDITOR_BRIDGE_JS = read('editor-bridge.js');

// ---- small pages ----

// The look of the small pages below.
const SMALL_PAGE_STYLE = '<style>:root{--teal:#087f8c;--navy:#17394b;--page:#eef4f5;--panel:#fff;--muted:#6b828d;--line:#d9e5e8;font-family:Inter,system-ui,-apple-system,"Segoe UI",sans-serif;color:var(--navy);background:var(--page)}@media(prefers-color-scheme:dark){:root{--navy:#edf7f8;--page:#101a21;--panel:#18262f;--muted:#a9bdc3;--line:#2d414b;color-scheme:dark}}body{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;background:var(--page);padding:20px;box-sizing:border-box}.box{max-width:460px;background:var(--panel);border:1px solid var(--line);border-radius:16px;padding:24px 26px}h1{font-size:20px;margin:0 0 8px}p{color:var(--muted);line-height:1.5;margin:0 0 16px}.deck{color:var(--navy);font-weight:650}a{display:inline-block;background:var(--teal);color:#fff;text-decoration:none;font-weight:650;border-radius:10px;padding:9px 14px;margin:0 8px 8px 0}a.second{background:transparent;color:var(--teal);border:1px solid var(--line)}</style>';

// The look of messagePage (it follows the portal's theme, set by portal-bridge.js).
const MESSAGE_PAGE_STYLE = '<style>:root{--teal:#087f8c;--navy:#17394b;--page:#eef4f5;--panel:#fff;--muted:#6b828d;--line:#d9e5e8;font-family:Inter,system-ui,-apple-system,"Segoe UI",sans-serif;color:var(--navy);background:var(--page)}[data-theme="light"]{--page:#f7f8fa}[data-theme="dark"]{--navy:#edf7f8;--page:#101a21;--panel:#18262f;--muted:#a9bdc3;--line:#2d414b;color-scheme:dark}body{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;background:var(--page);padding:20px;box-sizing:border-box}.box{max-width:460px;background:var(--panel);border:1px solid var(--line);border-radius:16px;padding:24px 26px}h1{font-size:20px;margin:0 0 8px}p{color:var(--muted);line-height:1.5;margin:0 0 16px}a{display:inline-block;background:var(--teal);color:#fff;text-decoration:none;font-weight:650;border-radius:10px;padding:9px 14px}</style>';

// With signIn: the page asks the portal to renew the sign-in and reloads (at most once in 20 seconds).
const RENEW_SIGN_IN_SCRIPT = `<script>(()=>{const key='gfm-signin-retry:'+location.pathname,last=Number(sessionStorage.getItem(key)||0),t=document.getElementById('t'),m=document.getElementById('m'),fail=text=>{t.textContent=document.title='Please open Presentations again';m.textContent=text};if(Date.now()-last<20000)return fail('Your sign-in could not be renewed. Reload the mission portal and open Presentations again.');m.textContent='Renewing your sign-in…';PresentationSession.refresh().then(()=>{sessionStorage.setItem(key,String(Date.now()));location.reload()},e=>fail(e.message))})();</script>`;

/**
 * A small page for a browser that opened something on the manager address and cannot see it (signed out, not
 * allowed, not found). With signIn: it renews the sign-in through the portal and reloads.
 */
export function messagePage(title, text, { signIn = false } = {}) {
  return `<!doctype html><html lang="en" data-theme="mission"><head><meta charset="utf-8" /><meta name="viewport" content="width=device-width,initial-scale=1" /><title>${escapeHtml(title)}</title><link rel="icon" href="${FAVICON_DATA_URL}" /><script src="/_manager/portal-bridge.js"></script>
${MESSAGE_PAGE_STYLE}</head>
<body><div class="box"><h1 id="t">${escapeHtml(title)}</h1><p id="m">${escapeHtml(text)}</p><a href="/">Go to the presentation library</a></div>
${signIn ? RENEW_SIGN_IN_SCRIPT : ''}</body></html>`;
}

/**
 * Round 8: a page on the deck address asked the manager address to open a deck or its editor. Nothing is opened for
 * it: the person sees this page and chooses Continue themselves (a link on this server's own page, which the browser
 * then counts as this server's own request). A deck's code cannot click it: it cannot see into this address, and
 * this page may be framed only by the portal.
 */
export function confirmPage(kind, title, target) {
  const heading = kind === 'edit' ? 'Open this presentation in the editor?' : 'Open this presentation?';
  return `<!doctype html><html lang="en"><head><meta charset="utf-8" /><meta name="viewport" content="width=device-width,initial-scale=1" /><title>${escapeHtml(heading)}</title><link rel="icon" href="${FAVICON_DATA_URL}" /><script src="/_manager/portal-bridge.js"></script>${SMALL_PAGE_STYLE}</head>
<body><div class="box"><h1>${escapeHtml(heading)}</h1><p class="deck" data-i18n-ignore>${escapeHtml(title)}</p><p>You came here from a presentation page. To keep your sign-in safe, please confirm.</p><a href="${escapeHtml(target)}">Continue</a><a class="second" href="/">Go to the presentation library</a></div></body></html>`;
}

/**
 * The portal's address for the computer name the browser used; on a public name (round 10) the portal of its
 * domain (presentations.example.org: https://example.org); else the first
 * configured one; or ''.
 */
export function portalAddressFor(host) {
  return pickPortal(portalSources(host, PORTAL_ORIGINS, PORTAL_PORTS), hostnameOf(host));
}

/**
 * The portal among `sources` for a page on computer name `name`: the portal of its parent domain (a public name),
 * else the same computer name (an office address, localhost; its portal port), else the first one.
 */
export function pickPortal(sources, name) {
  const hostname = origin => { try { return new URL(origin).hostname; } catch { return ''; } };
  return sources.find(origin => hostname(origin) && String(name).endsWith('.' + hostname(origin)))
    || sources.find(origin => hostname(origin) === name)
    || sources[0] || '';
}

const DECK_MESSAGES = {
  open: ['Please open the presentation again', OPEN_AGAIN],
  refused: ['Not available', 'This presentation is not assigned to you.'],
  missing: ['Presentation not found', 'It may have been renamed or deleted.'],
};

/**
 * Round 8: a page of the deck address that cannot show the deck (no pass, not allowed, not found). It links back to
 * the library on the manager address, where the deck is opened again. Its only script is the portal's i18n.js.
 */
export function deckMessagePage(kind, library, portal) {
  const [title, text] = DECK_MESSAGES[kind];
  const i18n = portal ? `<script src="${escapeHtml(portal)}/i18n.js"></script>` : '';
  return `<!doctype html><html lang="en"><head><meta charset="utf-8" /><meta name="viewport" content="width=device-width,initial-scale=1" /><title>${escapeHtml(title)}</title><link rel="icon" href="${FAVICON_DATA_URL}" />${i18n}${SMALL_PAGE_STYLE}</head>
<body><div class="box"><h1>${escapeHtml(title)}</h1><p>${escapeHtml(text)}</p><a href="${escapeHtml(library)}/">Go to the presentation library</a></div></body></html>`;
}

// ---- pieces added to a published deck's page ----

/**
 * Round 8 review: an open deck page uses its pass every few minutes (GET /api/deck-pass), so the pass lasts while
 * the page is open and ends soon after it is closed (deck-origin.mjs PASS_IDLE_MS).
 */
export function addPassKeepAlive(html) {
  const script = `<script>setInterval(function(){fetch('/api/deck-pass',{credentials:'same-origin',cache:'no-store'}).catch(function(){})},${PASS_KEEPALIVE_MS});</script>`;
  return html.includes('</head>') ? html.replace('</head>', () => `${script}</head>`) : script + html;
}

/**
 * The ✎ button (and the E key) on a published deck, for people who may change it. It opens the editor page in the
 * same frame. The deck is on the deck address and the editor page on the manager address, which first asks the
 * person to confirm (confirmPage).
 */
export function addEditorLauncher(html, slug, managerAddress) {
  const editUrl = `${managerAddress}/studio/${encodeURIComponent(slug)}`;
  const launcher = `
<style>
#portal-edit-presentation {
  position: fixed;
  right: 18px;
  bottom: 18px;
  z-index: 2147483647;
  width: 46px;
  height: 46px;
  border: 0;
  border-radius: 999px;
  background: rgba(25,25,25,.88);
  color: white;
  font-size: 21px;
  cursor: pointer;
  box-shadow: 0 4px 18px rgba(0,0,0,.25);
  opacity: .75;
}
#portal-edit-presentation:hover {
  opacity: 1;
}
/* On a phone, Slidev's buttons stay at the bottom: the ✎ button sits above them, not on them. */
@media (max-width: 767px) {
  #portal-edit-presentation {
    bottom: 64px;
  }
}
/* Not on the pages of a PDF made with Download PDF (the browser's print). */
@media print {
  #portal-edit-presentation,
  #portal-edit-loading {
    display: none !important;
  }
}
#portal-edit-loading {
  position: fixed;
  inset: 0;
  z-index: 2147483646;
  display: none;
  align-items: center;
  justify-content: center;
  background: rgba(15,15,15,.92);
  color: white;
  font: 600 16px system-ui,sans-serif;
}
#portal-edit-loading.visible {
  display: flex;
}
.portal-edit-spinner {
  width: 22px;
  height: 22px;
  margin-right: 12px;
  border: 3px solid rgba(255,255,255,.25);
  border-top-color: white;
  border-radius: 50%;
  animation: portal-edit-spin .75s linear infinite;
}
@keyframes portal-edit-spin {
  to { transform: rotate(360deg); }
}
</style>

<button
  id="portal-edit-presentation"
  type="button"
  title="Edit presentation (E)"
  aria-label="Edit presentation"
>✎</button>

<div id="portal-edit-loading">
  <div class="portal-edit-spinner"></div>
  Opening editor…
</div>

<script>
(() => {
  const editUrl = "${editUrl}";
  const button = document.getElementById('portal-edit-presentation');
  const loading = document.getElementById('portal-edit-loading');

  let opening = false;

  function openEditor() {
    if (opening) return;
    opening = true;
    loading.classList.add('visible');
    location.href = editUrl;
  }

  button.addEventListener('click', openEditor);

  window.addEventListener('keydown', event => {
    if (event.defaultPrevented) return;

    const target = event.target;
    const tag = target?.tagName?.toLowerCase();

    if (
      tag === 'input' ||
      tag === 'textarea' ||
      tag === 'select' ||
      target?.isContentEditable
    ) return;

    if (
      event.key.toLowerCase() === 'e' &&
      !event.ctrlKey &&
      !event.metaKey &&
      !event.altKey
    ) {
      event.preventDefault();
      openEditor();
    }
  }, true);
})();
</script>
`;
  if (html.includes('</body>')) return html.replace('</body>', launcher + '</body>');
  return html + launcher;
}

// ---- pieces added to the editor's page ----

// On a cold start, UnoCSS's style rules can be missing for a moment. If they have not arrived 6 s after the page
// loaded, it reloads once (the sessionStorage flag stops a loop). The warm-up (editors.mjs) normally prevents this.
const COLD_START_SCRIPT = `
<script>
(() => {
  const key = 'slidev-editor-css-reload:' + location.pathname;

  function utilitiesWork() {
    const test = document.createElement('div');
    test.className = 'absolute flex bottom-0 left-0';
    test.style.visibility = 'hidden';
    document.body.appendChild(test);

    const cs = getComputedStyle(test);

    const ok =
      cs.position === 'absolute' &&
      cs.display === 'flex' &&
      cs.bottom === '0px' &&
      cs.left === '0px';

    test.remove();
    return ok;
  }

  window.addEventListener('load', () => {
    if (utilitiesWork()) {
      sessionStorage.removeItem(key);
      return;
    }

    if (sessionStorage.getItem(key))
      return;

    sessionStorage.setItem(key, '1');

    const started = Date.now();

    const timer = setInterval(() => {
      if (utilitiesWork()) {
        clearInterval(timer);

        setTimeout(() => {
          location.reload();
        }, 250);

        return;
      }

      // The editor is warmed up before it opens (warmEditor), so the
      // utilities are normally there at once; this is only a safety net.
      if (Date.now() - started > 6000) {
        clearInterval(timer);

        // Last-resort reload once. The sessionStorage flag
        // prevents an infinite loop.
        location.reload();
      }
    }, 250);
  });
})();
</script>`;

/**
 * The editor page with its two helper scripts: the cold-start reload, and editor-bridge.js, which talks to the
 * /studio page around it (shellOrigin: the manager address).
 */
export function addEditorScripts(html, shellOrigin) {
  const bridgeScript = `<script>${EDITOR_BRIDGE_JS.replace('const SHELL = __SHELL_ORIGIN__;', () => `const SHELL = ${JSON.stringify(shellOrigin)};`)}</script>`;
  return html.replace('</head>', COLD_START_SCRIPT + '\n' + bridgeScript + '\n</head>');
}
