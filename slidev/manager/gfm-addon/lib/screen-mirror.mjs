// Screen mirroring in the presenter view (Slidev's "Screen Mirror" tab).
//
// Slidev 52 mirrors the projector back into the presenter view with
// navigator.mediaDevices.getDisplayMedia (internals/ScreenCaptureMirror.vue).
// Browsers offer that only in a secure context (https, or http://localhost),
// and inside a frame only when the frame is allowed "display-capture". On the
// office network the portal is plain http (http://192.168.x.x:8070 and :3030),
// so navigator.mediaDevices does not exist there and Slidev's button did
// nothing at all. The addon puts its own copy of that panel in place
// (presenter/ScreenMirror.vue, swapped in by setup/vite-plugins.ts) that says
// why mirroring cannot start and what to do instead. No Vue or Slidev imports
// here, so it runs in plain Node (tests/present.test.mjs).

// The origin of the top page (the portal around the deck), or this page's own.
function outerOrigin(win) {
  const location = win?.location || {}
  const ancestors = location.ancestorOrigins
  if (ancestors && ancestors.length) {
    const top = ancestors[ancestors.length - 1]
    if (top && top !== 'null') return String(top)
  }
  return String(location.origin || '')
}

// The same address on the computer itself, where http://localhost counts as secure.
export function localAddress(win) {
  try {
    const url = new URL(outerOrigin(win))
    if (url.protocol !== 'http:' && url.protocol !== 'https:') return ''
    url.hostname = 'localhost'
    return url.origin
  }
  catch {
    return ''
  }
}

function allowsDisplayCapture(doc) {
  const policy = doc?.permissionsPolicy || doc?.featurePolicy
  if (!policy || typeof policy.allowsFeature !== 'function') return true
  try {
    return policy.allowsFeature('display-capture') !== false
  }
  catch {
    return true
  }
}

/**
 * Why screen mirroring cannot start in this window, or null when it can.
 * Returns { kind, title, lines, link? } for the presenter view to show.
 */
export function mirrorProblem(win) {
  if (!win) return null
  const origin = outerOrigin(win)
  if (win.isSecureContext === false) {
    const local = localAddress(win)
    const lines = [
      `Browsers allow screen capture only on a secure (https) address or on localhost. This presentation is open at ${origin || 'an http address'}.`,
      'You can still present: choose Slides above. It shows the slide the audience sees and follows every click.',
    ]
    if (local)
      lines.push(`On the computer that runs the mission system, open ${local} and present from there: mirroring works on that address.`)
    lines.push('On any other computer, ask the data office to allow this address for screen capture in Edge or Chrome.')
    return { kind: 'insecure', title: 'Screen mirroring is not available at this address', lines }
  }
  if (typeof win.navigator?.mediaDevices?.getDisplayMedia !== 'function') {
    return {
      kind: 'unsupported',
      title: 'This browser cannot mirror the screen',
      lines: [
        'Screen capture needs Edge, Chrome or Firefox on a computer; phones and tablets cannot do it.',
        'Choose Slides above to present without mirroring.',
      ],
    }
  }
  if (!allowsDisplayCapture(win.document)) {
    const href = String(win.location?.href || '')
    return {
      kind: 'frame',
      title: 'Screen mirroring is blocked by the page around this presentation',
      lines: [
        'The page this presentation is shown in does not allow screen capture yet (it needs an update).',
        'Until then, open the presenter view in its own tab and mirror from there.',
      ],
      link: href ? { href, text: 'Open the presenter view in a new tab' } : undefined,
    }
  }
  return null
}

/** A sentence for a getDisplayMedia failure (after the button was clicked). */
export function mirrorFailure(error) {
  const name = String(error?.name || '')
  if (name === 'NotAllowedError' || name === 'AbortError')
    return 'Screen mirroring did not start: sharing was cancelled or not allowed. Click Start Screen Mirroring again, choose your other screen or window, then click Share.'
  if (name === 'NotFoundError')
    return 'Screen mirroring did not start: no screen or window to capture was found.'
  if (name === 'NotReadableError')
    return 'Screen mirroring did not start: the screen could not be captured. Stop other screen sharing and try again.'
  if (name === 'SecurityError' || name === 'TypeError')
    return 'Screen mirroring is not available at this address. Choose Slides above to present without mirroring.'
  const detail = [name, String(error?.message || '')].filter(Boolean).join(': ')
  return `Screen mirroring did not start${detail ? ` (${detail})` : ''}.`
}

// Slidev's presenter page imports its mirror panel as
// '../internals/ScreenCaptureMirror.vue'; the addon's Vite plugin answers that
// import with presenter/ScreenMirror.vue.
const PRESENTER_PAGE = /(?:^|\/)@slidev\/client\/pages\/presenter\.vue$/
const MIRROR_IMPORT = /(?:^|\/)internals\/ScreenCaptureMirror\.vue$/

export function isSlidevScreenMirror(source, importer) {
  if (!source || !importer) return false
  const from = String(importer).split('?')[0].replaceAll('\\', '/')
  return MIRROR_IMPORT.test(String(source).split('?')[0]) && PRESENTER_PAGE.test(from)
}
