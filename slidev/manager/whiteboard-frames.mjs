// The pages of the portal's Whiteboard frames, and the framing rules of every page on the manager address.
//
// What it is: the two pages the portal's Whiteboard shows in frames, for managers only (AP, President, Data
// Analyst), because they use the manager's chart engine and chart numbers:
//   GET /whiteboard/chart    one live chart or key number (whiteboard-chart.mjs)
//   GET /whiteboard/builder  the chart builder of /studio, placing its chart on the board (whiteboard-builder.mjs)
// Both may be framed only by the portal (Content-Security-Policy frame-ancestors). The same rules (frameAncestors,
// chartPageCsp) protect the library and /studio.
// Who uses it: manager-routes.mjs (and deck-routes.mjs for the deck address's frame rule).
// How it fits: plain Node, no packages, so slidev/tests/whiteboard.test.mjs can test it directly.

const PAGES = { '/whiteboard/chart': 'chart', '/whiteboard/builder': 'builder' }

/** 'chart', 'builder' or null for a path. */
export function whiteboardFrame(pathname) {
  return Object.hasOwn(PAGES, pathname) ? PAGES[pathname] : null
}

/**
 * The portal's addresses: every configured portal address, and the portal on this same machine (the host the browser
 * used) on a configured portal port, as the session check accepts (isPortalOrigin). portalPorts holds
 * "<scheme><port>" entries such as "http:8070".
 */
export function portalSources(host, portalOrigins, portalPorts) {
  const list = new Set()
  for (const origin of portalOrigins) list.add(origin)
  let hostname = ''
  try { hostname = new URL(`http://${host}`).hostname } catch {}
  if (hostname && /^[a-z0-9.:[\]-]+$/i.test(hostname)) {
    for (const entry of portalPorts) {
      const m = /^(https?:)(\d*)$/.exec(entry)
      if (m) list.add(`${m[1]}//${hostname}${m[2] ? `:${m[2]}` : ''}`)
    }
  }
  return [...list]
}

/** The frame-ancestors list: this server's own pages and the portal's addresses (portalSources). */
export function frameAncestors(host, portalOrigins, portalPorts) {
  return `frame-ancestors ${["'self'", ...portalSources(host, portalOrigins, portalPorts)].join(' ')}`
}

/**
 * Round 8 review: the Content-Security-Policy of the manager's pages that draw a chart's settings, which a Zone
 * Leader may have written (/studio with its chart builder, and the two Whiteboard frames). The browser then runs only
 * this server's own script files, the portal's i18n.js and the page's own inline scripts (they carry this page's
 * random nonce): never a script, an inline event handler (onerror=…) or a javascript: link that someone slipped into
 * the page as HTML. The page talks only to this server and the portal, shows images only from itself, frames only
 * `frames` (the deck address, for the editor inside /studio) and may be framed only by the portal.
 */
export function chartPageCsp(host, portalOrigins, portalPorts, { nonce, frames = [] }) {
  const portal = portalSources(host, portalOrigins, portalPorts)
  const plusPortal = (...items) => [...items, ...portal].join(' ')
  return [
    "default-src 'self'",
    `script-src ${plusPortal("'self'", `'nonce-${nonce}'`)}`,
    `style-src ${plusPortal("'self'", "'unsafe-inline'")}`,
    "img-src 'self' data: blob:",
    "font-src 'self' data:",
    `connect-src ${plusPortal("'self'")}`,
    `frame-src ${frames.length ? frames.join(' ') : "'none'"}`,
    "worker-src 'self' blob:",
    "object-src 'none'",
    "base-uri 'none'",
    "form-action 'self'",
    frameAncestors(host, portalOrigins, portalPorts),
  ].join('; ')
}

// The builder's colours are studio.html's (its dialog uses these variables).
const COLOURS = `:root{--teal:#087f8c;--teal-dark:#066a75;--navy:#17394b;--page:#eef4f5;--panel:#fff;--text:#193746;--muted:#6b828d;--line:#d9e5e8;--soft:#e8f1f2;--danger:#b42318;--warn:#8a5a00;--ok:#127a4a;--shadow:0 14px 38px rgba(20,30,40,.18);color-scheme:light;font-family:Inter,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;color:var(--text)}
[data-theme="light"]{--navy:#27313a;--page:#f7f8fa;--text:#27313a;--muted:#6d7780;--line:#e1e5e9;--soft:#f0f2f4}
[data-theme="dark"]{--navy:#edf7f8;--page:#101a21;--panel:#18262f;--text:#edf7f8;--muted:#a9bdc3;--line:#2d414b;--soft:#21343d;--danger:#ff9b91;--warn:#f2c46d;--ok:#6fd3a0;--shadow:0 14px 38px rgba(0,0,0,.45);color-scheme:dark}`

const BUTTONS = `.btn{display:inline-flex;align-items:center;justify-content:center;gap:7px;border:1px solid var(--line);background:var(--panel);color:var(--navy);border-radius:10px;padding:8px 13px;font-size:14px;font-weight:650;cursor:pointer;text-decoration:none;white-space:nowrap}.btn:hover{background:var(--soft)}.btn:focus-visible{outline:3px solid rgba(8,127,140,.35);outline-offset:1px}.btn:disabled{opacity:.55;cursor:default}
.btn.primary{background:var(--teal);border-color:var(--teal);color:#fff}.btn.primary:hover{background:var(--teal-dark)}
.toast{position:fixed;left:50%;bottom:22px;transform:translate(-50%,20px);opacity:0;pointer-events:none;background:var(--navy);color:var(--panel);padding:10px 16px;border-radius:12px;font-size:14px;font-weight:600;box-shadow:var(--shadow);transition:.18s ease;z-index:50;max-width:calc(100vw - 32px)}.toast.show{opacity:1;transform:translate(-50%,0)}.toast.warn{background:#8a5a00;color:#fff}`

// nonce: the page's own inline script runs only with it (chartPageCsp).
const nonceOf = nonce => String(nonce || '').replace(/[^A-Za-z0-9+/=]/g, '')

// Everything the chart frame loads, asked for at once instead of one after the other (the frame's code, what it
// imports, then the chart libraries): a board shows many of these frames.
const CHART_FRAME_FILES = ['whiteboard-chart.mjs', 'chart-core.mjs', 'chart-engine.mjs', 'formula.mjs', 'chart-presets.mjs', 'chart-spec.mjs', 'safe-chart-option.mjs']
  .map(name => `<link rel="modulepreload" href="/_manager/chart/${name}" />`).join('')
  + ['echarts.min.js', 'ecStat.min.js'].map(name => `<link rel="preload" as="script" href="/_manager/chart/${name}" />`).join('')

function chartPage(favicon, nonce) {
  return `<!doctype html><html lang="en" data-theme="light"><head><meta charset="utf-8" /><meta name="viewport" content="width=device-width,initial-scale=1" />
<title>Whiteboard chart</title><link rel="icon" href="${favicon}" />${CHART_FRAME_FILES}<script src="/_manager/portal-bridge.js"></script>
<style>${COLOURS}
html,body{margin:0;height:100%;overflow:hidden}body{background:#fff;font-family:Inter,system-ui,-apple-system,"Segoe UI",sans-serif}
[data-theme="dark"] body{background:#121212}
#plot{position:absolute;inset:6px 6px 16px 6px}
#message{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;text-align:center;padding:12px;font-size:14px;line-height:1.45;color:#556d7a}
[data-theme="dark"] #message{color:#9fb3bb}
#message.busy::before{content:"";width:14px;height:14px;margin-right:8px;border:2px solid currentColor;border-right-color:transparent;border-radius:50%;animation:spin .8s linear infinite;flex:none}
#note{position:absolute;right:6px;bottom:1px;font-size:10.5px;line-height:14px;color:#6b828d;opacity:.8}
#note::before{content:"";display:inline-block;width:6px;height:6px;border-radius:50%;background:#3f8a3a;margin-right:4px;vertical-align:1px}
[data-theme="dark"] #note{color:#9fb3bb}
[hidden]{display:none!important}@keyframes spin{to{transform:rotate(360deg)}}</style></head>
<body><div id="plot" role="img" aria-label="Chart"></div><div id="message" role="status" aria-live="polite" hidden></div><div id="note" hidden></div>
<script type="module" nonce="${nonceOf(nonce)}">import { startChartFrame } from '/_manager/chart/whiteboard-chart.mjs'; startChartFrame();</script></body></html>`
}

function builderPage(favicon, nonce) {
  return `<!doctype html><html lang="en" data-theme="mission"><head><meta charset="utf-8" /><meta name="viewport" content="width=device-width,initial-scale=1" />
<title>Add a chart</title><link rel="icon" href="${favicon}" /><script src="/_manager/portal-bridge.js"></script>
<style>${COLOURS}
${BUTTONS}
*{box-sizing:border-box}html,body{margin:0;height:100%;background:transparent}[hidden]{display:none!important}</style></head>
<body><div id="toast" class="toast" role="status" aria-live="polite"></div>
<script type="module" nonce="${nonceOf(nonce)}">import { startBuilderFrame } from '/_manager/chart/whiteboard-builder.mjs'; startBuilderFrame();</script></body></html>`
}

/** The page for 'chart' or 'builder'. nonce: the one its Content-Security-Policy names (chartPageCsp). */
export function whiteboardFramePage(kind, favicon, nonce = '') {
  return kind === 'builder' ? builderPage(favicon, nonce) : chartPage(favicon, nonce)
}
