// The Whiteboard page's rules without the page: what a board keeps, what a save sends, how a chart on the board is
// written and shown, the two drawing styles, and the sentences about saving. No DOM and no Excalidraw, so
// portal/tests/whiteboard-core.test.mjs runs it in plain Node. whiteboard.js is the page that uses it.

// A chart or key number on a board is an Excalidraw "embeddable" element: its link marks it as ours (the page
// allows no other embeds) and customData.gfmChart holds the chart builder's model. The frame that draws it is
// served by the Presentation Manager (managers only): <presentations>/whiteboard/chart#<model>.
export const CHART_LINK = 'https://gfm-whiteboard.invalid/chart/'
export const PICTURE_TYPES = ['image/png', 'image/jpeg', 'image/gif', 'image/webp', 'image/svg+xml']
// The same limits as portal-api/whiteboards.py (it checks them again and says so).
export const LIMITS = { name: 80, pictureBytes: 2 * 1024 * 1024, pictures: 60, picturesBytes: 12 * 1024 * 1024, sceneBytes: 3 * 1024 * 1024 }
// The settings of the board itself: when someone else's save is loaded into an open board, only these follow (the
// current colours and styles below stay each person's own choice until their next save).
export const BOARD_APP_STATE = ['viewBackgroundColor', 'gridModeEnabled', 'gridSize', 'gridStep']
// Board settings saved with the drawing (portal-api keeps exactly these); zoom, scroll and selection stay personal.
export const SAVED_APP_STATE = [
  'viewBackgroundColor', 'gridModeEnabled', 'gridSize', 'gridStep', 'currentItemRoughness', 'currentItemFontFamily',
  'currentItemStrokeColor', 'currentItemBackgroundColor', 'currentItemFillStyle', 'currentItemStrokeWidth',
  'currentItemStrokeStyle', 'currentItemOpacity', 'currentItemFontSize', 'currentItemTextAlign',
  'currentItemRoundness', 'currentItemArrowType', 'currentItemStartArrowhead', 'currentItemEndArrowhead',
]
// Excalidraw's font numbers: Excalifont (hand-drawn), Nunito (clean). Other fonts someone picks stay as they are.
export const FONTS = { hand: 5, clean: 6 }
export const STYLES = {
  hand: { roughness: 1, font: FONTS.hand },
  clean: { roughness: 0, font: FONTS.clean },
}
// New charts and key numbers, in board pixels.
export const CHART_SIZE = { chart: { width: 560, height: 340 }, tile: { width: 300, height: 190 } }

export function isChartLink(url) {
  return typeof url === 'string' && url.startsWith(CHART_LINK)
}

export function chartLink(id) {
  return CHART_LINK + encodeURIComponent(id)
}

/** A chart element of the board: an embeddable with our link and a chart model. */
export function isChartElement(element) {
  return !!element && element.type === 'embeddable' && isChartLink(element.link) && !!element.customData?.gfmChart
}

/**
 * An element the whiteboard never shows: an Excalidraw "iframe" element. Excalidraw runs the HTML it carries
 * (customData.generationData) with scripts allowed, whatever its link says; our charts are "embeddable" elements.
 * portal-api drops them too (whiteboards.py clean_scene).
 */
export function isForbiddenElement(element) {
  return !!element && element.type === 'iframe'
}

/** Elements as the whiteboard may show them: no iframe element, and no generationData (the HTML such an element runs). */
export function safeElements(elements) {
  const out = []
  for (const e of elements || []) {
    if (!e || isForbiddenElement(e)) continue
    if (e.customData && typeof e.customData === 'object' && 'generationData' in e.customData) {
      const { generationData, ...customData } = e.customData
      out.push({ ...e, customData })
    }
    else out.push(e)
  }
  return out
}

function toBase64Url(bytes) {
  let binary = ''
  for (let i = 0; i < bytes.length; i += 0x8000) binary += String.fromCharCode(...bytes.subarray(i, i + 0x8000))
  return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
}

/** The chart model as it goes after '#' in the chart frame's address (slidev/manager/whiteboard-chart.mjs reads it). */
export function encodeChartModel(model) {
  return toBase64Url(new TextEncoder().encode(JSON.stringify(model)))
}

/** The address of the frame that draws a chart: the model after '#', so it never reaches a server log. */
export function chartFrameUrl(presentations, model, dark) {
  return `${String(presentations).replace(/\/+$/, '')}/whiteboard/chart?theme=${dark ? 'dark' : 'light'}#${encodeChartModel(model)}`
}

/** The Presentations address as the portal shell has it (URLS.presentations: this host on port 3030). */
export function presentationsAddress(location, fromShell) {
  if (typeof fromShell === 'string' && /^https?:\/\/[^/\s]+$/.test(fromShell.replace(/\/+$/, ''))) return fromShell.replace(/\/+$/, '')
  return `${location.protocol}//${location.hostname}:3030`
}

/**
 * Where to put something new of this size: the middle of the screen (`middle`, board coordinates) when that is free,
 * else the nearest free place beside or below it. Charts are drawn above the drawing, so they must not cover notes.
 * elements: what is on the board. Returns { x, y } (top left).
 */
export function freeSpot(elements, middle, width, height, gap = 24) {
  const boxes = (elements || []).filter(e => e && !e.isDeleted && !e.containerId).map(e => ({
    x: Math.min(e.x, e.x + e.width), y: Math.min(e.y, e.y + e.height), w: Math.abs(e.width), h: Math.abs(e.height),
  }))
  const start = { x: middle.x - width / 2, y: middle.y - height / 2 }
  const free = (x, y) => boxes.every(b => x + width + gap <= b.x || b.x + b.w + gap <= x || y + height + gap <= b.y || b.y + b.h + gap <= y)
  const steps = [[0, 0]]
  for (let r = 1; r <= 3; r++) for (const step of [[r, 0], [0, r], [r, r], [-r, 0], [0, -r], [-r, r], [r, -r], [-r, -r]]) steps.push(step)
  for (const [dx, dy] of steps) {
    const x = start.x + dx * (width + gap), y = start.y + dy * (height + gap)
    if (free(x, y)) return { x: Math.round(x), y: Math.round(y) }
  }
  return { x: Math.round(start.x + gap), y: Math.round(start.y + gap) }
}

/** Whether a chart model is a key number (a tile): round 6's option (gfm.kind) or the older settings (type). */
export function isKeyNumber(model) {
  return model?.option?.gfm?.kind === 'tile' || model?.props?.type === 'tile'
}

/** New charts and key numbers: their size on the board. */
export function chartSize(model) {
  return isKeyNumber(model) ? CHART_SIZE.tile : CHART_SIZE.chart
}

/** A chart's title, for its frame's name ('' when it has none). */
export function chartTitle(model) {
  const title = model?.option?.title
  const text = Array.isArray(title) ? title[0]?.text : title?.text
  return String(text ?? model?.props?.title ?? '').trim()
}

/** The board settings to keep from Excalidraw's appState. */
export function savedAppState(appState) {
  const out = {}
  for (const key of SAVED_APP_STATE) {
    const value = appState?.[key]
    if (value === undefined || typeof value === 'function') continue
    out[key] = value
  }
  return out
}

/** The board settings of a saved drawing's appState that follow into a board open elsewhere (BOARD_APP_STATE). */
export function boardAppState(appState) {
  const out = {}
  for (const key of BOARD_APP_STATE) if (appState?.[key] !== undefined) out[key] = appState[key]
  return out
}

/** The drawing as it is saved: the elements still on the board, the board settings and the style. */
export function sceneFor(elements, appState, style) {
  return {
    type: 'gfm-whiteboard', v: 1, style: STYLES[style] ? style : 'hand',
    elements: (elements || []).filter(e => e && !e.isDeleted && !isForbiddenElement(e)),
    appState: savedAppState(appState),
  }
}

/** A short fingerprint of a drawing: changes whenever an element, a board setting or the style changes. */
export function sceneSignature(scene) {
  const parts = scene.elements.map(e => `${e.id}:${e.version}:${e.versionNonce}`)
  return `${scene.style}|${JSON.stringify(scene.appState)}|${parts.join(',')}`
}

/** The picture ids that the drawing's picture elements use. */
export function usedFileIds(elements) {
  const ids = new Set()
  for (const e of elements || []) if (e && !e.isDeleted && e.type === 'image' && typeof e.fileId === 'string') ids.add(e.fileId)
  return ids
}

/** Bytes of a data URL's content (base64), without decoding it. */
export function dataUrlBytes(dataURL) {
  const text = String(dataURL || '')
  const at = text.indexOf(',')
  if (at < 0) return 0
  const b64 = text.slice(at + 1).replace(/\s/g, '')
  return Math.floor(b64.length * 3 / 4) - (b64.endsWith('==') ? 2 : b64.endsWith('=') ? 1 : 0)
}

/** Whether a picture must be made smaller (or turned into a common format) before it can be saved. */
export function needsShrink(file, limit = LIMITS.pictureBytes) {
  if (!file?.dataURL) return false
  return !PICTURE_TYPES.includes(file.mimeType) || dataUrlBytes(file.dataURL) > limit
}

/** The size to draw a picture at when making it smaller: at most `side` pixels on its longer side. */
export function shrinkSize(width, height, side = 1600) {
  const w = Math.max(1, Math.round(Number(width) || 1)), h = Math.max(1, Math.round(Number(height) || 1))
  const scale = Math.min(1, side / Math.max(w, h))
  return { width: Math.max(1, Math.round(w * scale)), height: Math.max(1, Math.round(h * scale)) }
}

// Pictures sent with one save, at most (their data URLs): with the drawing (at most 3 MB) a save stays well below
// the portal's 16 MB request limit. The rest go with the next save, a moment later.
export const SEND_BUDGET = 8 * 1024 * 1024

/**
 * The pictures a save must send: those in use that the server does not hold yet, as { id: { mimeType, dataURL } },
 * at most `budget` characters of data URLs (always at least one). prepared holds smaller versions made for saving
 * (by id); missing lists pictures in use whose data this browser does not have (they cannot be sent); left counts
 * the pictures kept for the next save because of the budget.
 */
export function filesToSend(elements, files, savedIds, prepared = {}, budget = SEND_BUDGET) {
  const out = {}
  const missing = []
  let left = 0
  let size = 0
  for (const id of usedFileIds(elements)) {
    if (savedIds.has(id)) continue
    const file = prepared[id] || files?.[id]
    if (!file?.dataURL) { missing.push(id); continue }
    const length = String(file.dataURL).length
    if (size && size + length > budget) { left++; continue }
    size += length
    out[id] = { mimeType: file.mimeType, dataURL: file.dataURL }
  }
  return { files: out, missing, left }
}

/**
 * The changes that give a drawing the other style: straight or sketchy lines, and the matching font for text
 * written in the other style's font. [{ id, roughness?, fontFamily? }] for the elements that change.
 */
export function styleChanges(elements, style) {
  const want = STYLES[style]
  if (!want) return []
  const other = style === 'clean' ? STYLES.hand : STYLES.clean
  const changes = []
  for (const e of elements || []) {
    if (!e || e.isDeleted) continue
    const change = { id: e.id }
    if (typeof e.roughness === 'number' && e.type !== 'image' && e.type !== 'embeddable' && e.type !== 'text' && e.roughness !== want.roughness
        && (style === 'clean' || e.roughness === other.roughness)) change.roughness = want.roughness
    if (e.type === 'text' && e.fontFamily === other.font) change.fontFamily = want.font
    if (Object.keys(change).length > 1) changes.push(change)
  }
  return changes
}

/** The defaults for new elements in a style (Excalidraw's appState). */
export function styleDefaults(style) {
  const s = STYLES[style] || STYLES.hand
  return { currentItemRoughness: s.roughness, currentItemFontFamily: s.font }
}

/** The style a drawing looks most like, for boards saved without one. */
export function guessStyle(scene) {
  if (STYLES[scene?.style]) return scene.style
  const shapes = (scene?.elements || []).filter(e => typeof e.roughness === 'number' && e.type !== 'text')
  return shapes.length && shapes.every(e => e.roughness === 0) ? 'clean' : 'hand'
}

/** "New people being taught (copy)", "... (copy 2)": a name for a copy that no other board has. */
export function copyName(name, taken, word = 'copy') {
  const used = new Set([...taken].map(n => String(n).toLowerCase()))
  const base = String(name || 'Board').replace(/ \((?:copy|my copy)(?: \d+)?\)$/i, '').slice(0, LIMITS.name - 14)
  for (let n = 1; n < 1000; n++) {
    const candidate = `${base} (${word}${n > 1 ? ` ${n}` : ''})`
    if (!used.has(candidate.toLowerCase())) return candidate
  }
  return `${base} (${Date.now()})`
}

/** Excalidraw's language for the portal's (de → de-DE, pt → pt-PT, en → en); English when it has none. */
export function excalidrawLanguage(lang, available) {
  const codes = (available || []).map(l => (typeof l === 'string' ? l : l.code))
  const wanted = String(lang || 'en').trim()
  if (!wanted) return 'en'
  const exact = codes.find(c => c.toLowerCase() === wanted.toLowerCase())
  if (exact) return exact
  const base = wanted.toLowerCase().split('-')[0]
  if (base === 'en') return 'en'
  const main = codes.find(c => c.toLowerCase() === `${base}-${base}`)
  return main || codes.find(c => c.toLowerCase().startsWith(`${base}-`)) || 'en'
}

/** "14:05" today, "Sep 27, 14:05" another day, in the page's language. */
export function whenText(iso, lang, now = new Date()) {
  const at = new Date(iso)
  if (Number.isNaN(at.getTime())) return ''
  const time = at.toLocaleTimeString(lang || undefined, { hour: '2-digit', minute: '2-digit' })
  if (at.toDateString() === now.toDateString()) return time
  return `${at.toLocaleDateString(lang || undefined, { month: 'short', day: 'numeric' })}, ${time}`
}

/** "Last saved by Elder Example at 14:05". */
export function lastSavedText(board, lang, now = new Date()) {
  if (!board?.updated_at) return ''
  const who = board.updated_by_name || 'someone'
  const when = whenText(board.updated_at, lang, now)
  const today = new Date(board.updated_at).toDateString() === now.toDateString()
  return `Last saved by ${who} ${today ? 'at' : 'on'} ${when}`
}

/** The message when someone else saved first. */
export function conflictText(board, lang, now = new Date()) {
  const who = board?.updated_by_name || 'Someone else'
  const when = board?.updated_at ? ` (${whenText(board.updated_at, lang, now)})` : ''
  return `${who} saved this board${when} while you were working on it, so your latest changes are not saved. Reload to see their version, or keep yours as a new board.`
}
