// The chart builder for the portal's Whiteboard: GET /whiteboard/builder on the Presentation Manager (managers only,
// whiteboard-frames.mjs). The whiteboard lays this page over itself in a frame and talks to it by postMessage:
//
//   frame -> whiteboard  { type: 'gfm-whiteboard-builder-ready' }                      the page listens
//   whiteboard -> frame  { type: 'gfm-whiteboard-builder-open', model?, number? }      what to open
//   frame -> whiteboard  { type: 'gfm-whiteboard-chart', model }                       Add to the whiteboard / Update chart
//   frame -> whiteboard  { type: 'gfm-whiteboard-builder-closed' }                     the dialog closed
//
// Messages go only to, and are taken only from, the portal addresses Presentations trusts
// (PresentationSession.portals, from PRESENTATIONS_PORTAL_ORIGINS), and only from the page that holds this frame.
// A model holds chart settings only, never a token or numbers.
// Who uses it: the page GET /whiteboard/builder (whiteboard-frames.mjs), which loads it from
// /_manager/chart/whiteboard-builder.mjs.
// How it fits: the dialog itself is the chart builder of /studio (chart-builder.mjs) in its whiteboard mode.
import { openChartBuilder } from './chart-builder.mjs'
import { boardLimitProblem } from './whiteboard-chart.mjs'

export const MESSAGES = {
  ready: 'gfm-whiteboard-builder-ready',
  open: 'gfm-whiteboard-builder-open',
  chart: 'gfm-whiteboard-chart',
  closed: 'gfm-whiteboard-builder-closed',
}

/** Whether a message came from the page holding this frame, on a trusted portal address. */
export function fromPortal(event, parent, portals) {
  return !!event && event.source === parent && Array.isArray(portals) && portals.includes(event.origin)
}

function toast(text, warn) {
  const box = document.getElementById('toast')
  box.textContent = text
  box.className = `toast show${warn ? ' warn' : ''}`
  clearTimeout(toast.timer)
  toast.timer = setTimeout(() => { box.className = 'toast' }, warn ? 6000 : 3200)
}

let monaco = null
function loadMonaco() {
  monaco ||= new Promise((resolve, reject) => {
    const script = document.createElement('script')
    script.src = '/vendor/monaco/vs/loader.js'
    script.onerror = () => reject(new Error('The text editor could not be loaded. Check your connection and try again.'))
    script.onload = () => {
      window.require.config({ paths: { vs: '/vendor/monaco/vs' } })
      window.require(['vs/editor/editor.main'], () => resolve(window.monaco), () => reject(new Error('The text editor could not be loaded.')))
    }
    document.head.appendChild(script)
  })
  monaco.catch(() => { monaco = null })
  return monaco
}

/** Starts the page: says it is ready, then opens the builder with what the whiteboard sends. */
export function startBuilderFrame() {
  const P = window.PresentationSession
  const portals = P?.portals || []
  const theme = new URLSearchParams(location.search).get('theme')
  if (['mission', 'light', 'dark'].includes(theme)) document.documentElement.dataset.theme = theme
  let origin = ''
  let opened = false
  const tell = message => { if (origin) window.parent.postMessage(message, origin) }

  window.addEventListener('message', async (event) => {
    if (!fromPortal(event, window.parent, portals) || event.data?.type !== MESSAGES.open || opened) return
    opened = true
    origin = event.origin
    const model = event.data.model && typeof event.data.model === 'object' ? event.data.model : null
    try {
      await openChartBuilder({
        api: P.api, toast, loadMonaco,
        // check: the chart frame's own limits, so the builder refuses what the frame could not draw.
        target: { model, number: !model && !!event.data.number, check: boardLimitProblem, save: async (made) => tell({ type: MESSAGES.chart, model: made }) },
        onClose: () => tell({ type: MESSAGES.closed }),
      })
    }
    catch (error) {
      toast(error?.message || 'The chart builder could not be opened.', true)
      setTimeout(() => tell({ type: MESSAGES.closed }), 2500)
    }
  })
  for (const portal of portals) {
    try { window.parent.postMessage({ type: MESSAGES.ready }, portal) } catch {}
  }
}
