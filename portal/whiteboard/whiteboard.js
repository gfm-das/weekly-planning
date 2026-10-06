// whiteboard.js: the page script of the Whiteboard tab (index.html loads it; board-core.js holds its rules).
//
// Who: APs, the President and Data Analysts. Named boards shared by the managers of the mission, drawn with
// Excalidraw, with live charts and key numbers from the Presentations chart engine.
//
// - Boards: listed, created, renamed, duplicated, deleted and opened through portal-api (/api/whiteboards,
//   portal-api/whiteboards.py), with the portal sign-in (the shell renews it: window.parent.ensureMissionSession).
// - Saving: a few seconds after each change, with the version the board was opened at. When someone else saved in
//   between, the server says so (409) and the page offers "Reload their version" or "Keep mine as a new board".
//   While nothing is changed here, other people's saves are loaded quietly (every 20 seconds).
//   A save the server refuses (a limit, sign-in, a server error) is said as the server says it and tried again after
//   the next change; only a dropped connection or a restarting server (502, 503, 504) is tried again by itself.
//   Other people's saves change the drawing only: the view (zoom, scroll) and each person's colours stay.
// - Pictures: made smaller in the browser when needed (at most 2 MB each), and sent once.
// - No "iframe" element ever shows (opened, pasted or added another way): Excalidraw would run the HTML it carries.
//   Charts are "embeddable" elements drawn by our own frames.
// - Charts: "Add chart" and "Add number" open the chart builder of Presentations in a frame over the page
//   (<Presentations>/whiteboard/builder); the chart is placed as an embeddable element whose customData holds the
//   builder's model, drawn live by <Presentations>/whiteboard/chart. This page signs the frames in to
//   Presentations (POST <Presentations>/api/session with the portal token, as the shell does for Presentations) and
//   renews that sign-in for them when they ask.
// - Words: plain English in this file (say() lets the portal's translation catalog translate them); Excalidraw's own
//   words follow the portal language (or ?lang=de in the address) in its 50-odd languages.
import * as X from './vendor/gfm-excalidraw.js'
import * as core from './board-core.js'

const { React, createRoot, Excalidraw, MainMenu, WelcomeScreen, CaptureUpdateAction, restoreElements, newElementWith, viewportCoordsToSceneCoords } = X
const h = React.createElement
const $ = id => document.getElementById(id)

const SAVE_DELAY_MS = 2500
const SAVE_MAX_WAIT_MS = 10000
const RETRY_MS = 15000
const POLL_MS = 20000
// Saves tried again by themselves: no answer at all (0), or the server is being restarted or is busy.
const RETRY_STATUS = new Set([0, 502, 503, 504])
const SESSION_RENEW_MS = 4 * 60 * 1000
const LAST_BOARD_KEY = 'gfm-whiteboard-board'

/** Interface words through the portal's translation catalog when it has them. */
function say(text) {
  try { return window.MissionI18n?.translate ? window.MissionI18n.translate(text) : text }
  catch { return text }
}

// Everything the page remembers:
// - boards, canEdit: the list; current: the open board ({id, name, version …}); api: Excalidraw's handle to it;
//   initialData: what Excalidraw starts from; style: 'hand' or 'clean'; fitOnOpen: zoom to the drawing once.
// - opened: counts openBoard() calls; it is Excalidraw's key, so only opening a board starts Excalidraw afresh from
//   initialData (renaming, "Keep mine as a new board", the theme or the language keep the drawing on screen).
// - saving: savedSignature (the drawing as last saved), savedFileIds (pictures the server holds), unstorable
//   (pictures it would not take), prepared/pending (pictures made smaller, or still being made smaller),
//   checkedFiles, userActed, dirty/dirtySince (unsaved changes and since when), saving (the save on its way),
//   saveAgain (a change came in during it), saveTimer, retryTimer, refused (the server's reason), blocked
//   ('conflict' or 'gone': saving stops until the person chooses).
// - charts: selectedChart, builderFor (the chart the builder frame is open for), builderTimer.
// - theme ('light'/'dark' for Excalidraw), lang, and the Presentations address that draws the charts.
const state = {
  boards: [], canEdit: false, current: null, initialData: null, api: null, style: 'hand', opened: 0, fitOnOpen: false,
  savedSignature: null, savedFileIds: new Set(), unstorable: new Set(), prepared: {}, pending: {}, checkedFiles: new Set(),
  userActed: false, dirty: false, dirtySince: 0, saving: null, saveAgain: false, saveTimer: 0, retryTimer: 0, refused: '',
  blocked: null, selectedChart: null, builderFor: null, builderTimer: 0,
  theme: 'light', lang: 'en', presentations: '', presentationsOrigin: '',
}

// ---- where things are ------------------------------------------------------------

function shell() {
  try { return window.parent !== window && window.parent.location.origin === location.origin ? window.parent : null }
  catch { return null }
}

state.presentations = core.presentationsAddress(location, (() => { try { return shell()?.portalPresentationsUrl?.() } catch { return '' } })())
state.presentationsOrigin = new URL(state.presentations).origin

// ---- the portal API --------------------------------------------------------------

async function portalToken() {
  const parent = shell()
  const token = parent?.ensureMissionSession ? await parent.ensureMissionSession() : localStorage.getItem('mission_access_token')
  if (!token) throw Object.assign(new Error(say('Sign in to the mission portal to use the whiteboard.')), { status: 401 })
  return token
}

async function api(path, { method = 'GET', body, keepalive = false } = {}) {
  const token = await portalToken()
  let response
  try {
    response = await fetch('/api/' + path, {
      method, keepalive, cache: 'no-store',
      headers: { Authorization: 'Bearer ' + token, ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}) },
      body: body !== undefined ? JSON.stringify(body) : undefined,
    })
  }
  catch {
    throw Object.assign(new Error(say('The whiteboard cannot reach the server right now. Check the connection.')), { status: 0 })
  }
  const data = await response.json().catch(() => ({}))
  if (!response.ok) throw Object.assign(new Error(data.error || say('Something went wrong. Please try again.')), { status: response.status, data })
  return data
}

// ---- the Presentations sign-in for the chart frames ------------------------------

const session = { until: 0, at: 0, last: null, running: null }

function presentationsSession(force = false) {
  if (!force && session.until - Date.now() > 90000) return Promise.resolve(session.last)
  if (session.last && Date.now() - session.at < 5000) return Promise.resolve(session.last)
  session.running ||= (async () => {
    const token = await portalToken()
    let response
    try {
      response = await fetch(state.presentations + '/api/session', { method: 'POST', credentials: 'include', headers: { Authorization: 'Bearer ' + token } })
    }
    catch { throw new Error(say('Live charts cannot reach Presentations right now. Try again in a minute.')) }
    const data = await response.json().catch(() => ({}))
    if (!response.ok) throw new Error(data.error || say('Live charts are not available right now.'))
    session.until = Date.parse(data.expires_at) || Date.now() + SESSION_RENEW_MS
    session.at = Date.now()
    session.last = data
    return data
  })().finally(() => { session.running = null })
  return session.running
}

setInterval(() => {
  if (state.current && document.visibilityState === 'visible') presentationsSession(true).catch(() => {})
}, SESSION_RENEW_MS)

/** Frames of this page (the chart frames and the builder) may ask for a renewed sign-in, as they ask the shell elsewhere. */
function ownFrame(source) {
  return [...document.querySelectorAll('iframe')].some(frame => frame.contentWindow === source)
}

window.addEventListener('message', (event) => {
  const data = event.data || {}
  if (event.origin === location.origin && event.source === window.parent) {
    if (data.type === 'portal-theme') setTheme(data.theme)
    if (data.type === 'mission-language') setLanguage(data.language)
    return
  }
  if (event.origin !== state.presentationsOrigin || !ownFrame(event.source)) return
  if (data.type === 'presentations-session-request') {
    presentationsSession(true).then(
      done => event.source.postMessage({ type: 'presentations-session-refreshed', expires_at: done?.expires_at }, state.presentationsOrigin),
      error => event.source.postMessage({ type: 'presentations-session-error', message: error.message }, state.presentationsOrigin))
    return
  }
  if (event.source !== $('builder').contentWindow || !state.builderFor) return
  if (data.type === 'gfm-whiteboard-builder-ready') {
    clearTimeout(state.builderTimer)
    $('busy').hidden = true
    $('builder').contentWindow.postMessage({ type: 'gfm-whiteboard-builder-open', model: state.builderFor.model || null, number: !!state.builderFor.number }, state.presentationsOrigin)
  }
  else if (data.type === 'gfm-whiteboard-chart' && data.model && typeof data.model === 'object') placeChart(data.model)
  else if (data.type === 'gfm-whiteboard-builder-closed') closeBuilder()
})

// ---- theme and language ------------------------------------------------------------

function setTheme(theme) {
  const value = ['mission', 'light', 'dark'].includes(theme) ? theme : 'mission'
  document.documentElement.dataset.theme = value
  const next = value === 'dark' ? 'dark' : 'light'
  if (next !== state.theme) { state.theme = next; renderBoard() }
}

function setLanguage(language) {
  const lang = String(language || 'en')
  if (lang === state.lang) return
  state.lang = lang
  if (window.MissionI18n?.setLanguage && new URLSearchParams(location.search).get('lang')) window.MissionI18n.setLanguage(lang)
  renderBoard()
  renderStatus()
  renderList()
}

function startingLanguage() {
  const asked = new URLSearchParams(location.search).get('lang')
  if (asked && /^[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8})*$/.test(asked)) return asked
  try { return sessionStorage.getItem('mission_language') || 'en' } catch { return 'en' }
}

// ---- messages --------------------------------------------------------------------

let toastTimer = 0
function toast(text, warn = false) {
  const box = $('toast')
  box.textContent = text
  box.className = 'wb-toast show' + (warn ? ' warn' : '')
  clearTimeout(toastTimer)
  toastTimer = setTimeout(() => { box.className = 'wb-toast' }, warn ? 7000 : 3500)
}

function busy(text) {
  $('busy').hidden = !text
  if (text) $('busyText').textContent = text
}

function renderStatus() {
  const box = $('saveState')
  if (!state.current) return
  let text = say(core.lastSavedText(state.current, state.lang)) || say('Not saved yet')
  let kind = ''
  if (state.blocked) { text = say('Not saved: see the message above.'); kind = 'error' }
  else if (state.refused) { text = state.refused; kind = 'error' }
  else if (state.saving) { text = say('Saving…'); kind = 'busy' }
  else if (state.retryTimer) { text = say('Not saved yet: the connection dropped. Trying again…'); kind = 'warn' }
  else if (state.dirty) { text = say('Changes not saved yet'); kind = 'warn' }
  else text = `${say('All changes saved')} · ${text}`
  box.textContent = text
  box.title = text
  box.className = 'wb-state' + (kind ? ' ' + kind : '')
}

function showBanner(text, { reload = true, copy = true } = {}) {
  $('bannerText').textContent = text
  $('bannerReload').hidden = !reload
  $('bannerCopy').hidden = !copy
  $('banner').hidden = !text
}

// ---- the list of boards --------------------------------------------------------------

async function loadList() {
  const data = await api('whiteboards')
  state.boards = data.boards || []
  state.canEdit = true
  if (data.limits) Object.assign(core.LIMITS, { name: data.limits.name, pictureBytes: data.limits.picture_bytes, pictures: data.limits.pictures, picturesBytes: data.limits.pictures_bytes, sceneBytes: data.limits.scene_bytes })
  return state.boards
}

function renderList() {
  if (state.current) return
  const grid = $('boards')
  grid.textContent = ''
  const message = $('listMessage')
  message.classList.remove('error')
  $('newBoard').hidden = !state.canEdit
  if (!state.canEdit) return
  message.textContent = state.boards.length
    ? say('Open a board to draw, write notes and add live charts. Everything saves by itself.')
    : say('No boards yet. Start one for a council, a training or a plan.')
  for (const board of state.boards) {
    const card = document.createElement('div')
    card.className = 'wb-card'
    card.tabIndex = 0
    card.setAttribute('role', 'button')
    card.dataset.board = board.id
    const title = document.createElement('h2')
    title.textContent = board.name
    title.setAttribute('data-i18n-ignore', '')
    const saved = document.createElement('p')
    saved.textContent = say(core.lastSavedText(board, state.lang))
    const detail = document.createElement('p')
    detail.textContent = board.pictures ? `${board.pictures} ${say(board.pictures === 1 ? 'picture' : 'pictures')}` : ''
    const actions = document.createElement('div')
    actions.className = 'wb-card-actions'
    for (const [act, label] of [['rename', 'Rename'], ['duplicate', 'Duplicate'], ['delete', 'Delete']]) {
      const button = document.createElement('button')
      button.type = 'button'
      button.className = 'btn small'
      button.dataset.act = act
      button.textContent = say(label)
      actions.append(button)
    }
    card.append(title, saved, detail, actions)
    grid.append(card)
  }
}

async function showList(message = '') {
  clearTimeout(state.saveTimer)
  clearTimeout(state.retryTimer)
  state.current = null
  state.api = null
  state.initialData = null
  $('boardHead').hidden = true
  $('listHead').hidden = false
  $('stage').hidden = true
  $('list').hidden = false
  showBanner('')
  try { sessionStorage.removeItem(LAST_BOARD_KEY) } catch {}
  renderBoard()
  try {
    await loadList()
    renderList()
    if (message) toast(message)
  }
  catch (error) {
    state.canEdit = false
    $('newBoard').hidden = true
    $('boards').textContent = ''
    $('listMessage').textContent = error.message
    $('listMessage').classList.add('error')
  }
}

$('boards').addEventListener('click', (event) => {
  const card = event.target.closest('.wb-card')
  if (!card) return
  const board = state.boards.find(b => b.id === card.dataset.board)
  if (!board) return
  const act = event.target.closest('[data-act]')?.dataset.act
  if (act === 'rename') return renameBoard(board)
  if (act === 'duplicate') return duplicateBoard(board)
  if (act === 'delete') return deleteBoard(board)
  openBoard(board.id)
})
$('boards').addEventListener('keydown', (event) => {
  if ((event.key === 'Enter' || event.key === ' ') && event.target.classList?.contains('wb-card')) { event.preventDefault(); openBoard(event.target.dataset.board) }
})

// ---- names, creating, renaming, duplicating, deleting --------------------------------

function askName({ title, label = 'Name', ok, value = '' }) {
  const dialog = $('nameDialog')
  $('nameTitle').textContent = say(title)
  $('nameLabel').textContent = say(label)
  $('nameOk').textContent = say(ok)
  $('nameInput').value = value
  $('nameError').hidden = true
  return new Promise((resolve) => {
    const done = (result) => { cleanup(); dialog.close(); resolve(result) }
    const onSubmit = (event) => {
      event.preventDefault()
      const name = $('nameInput').value.trim().replace(/\s+/g, ' ')
      if (!name) { $('nameError').textContent = say('Give the board a name.'); $('nameError').hidden = false; return }
      done(name)
    }
    const onCancel = () => done(null)
    const onClose = () => { cleanup(); resolve(null) }
    function cleanup() {
      $('nameForm').removeEventListener('submit', onSubmit)
      $('nameCancel').removeEventListener('click', onCancel)
      dialog.removeEventListener('close', onClose)
    }
    $('nameForm').addEventListener('submit', onSubmit)
    $('nameCancel').addEventListener('click', onCancel)
    dialog.addEventListener('close', onClose)
    dialog.showModal()
    setTimeout(() => $('nameInput').select(), 30)
  })
}

function confirmDelete(name) {
  const dialog = $('confirmDialog')
  $('confirmName').textContent = name
  return new Promise((resolve) => {
    dialog.addEventListener('close', () => resolve(dialog.returnValue === 'ok'), { once: true })
    dialog.returnValue = ''
    dialog.showModal()
    $('confirmCancel').focus()
  })
}

async function createBoard() {
  let value = ''
  for (;;) {
    const name = await askName({ title: 'New board', ok: 'Create', value })
    if (!name) return
    try {
      const { board } = await api('whiteboards', { method: 'POST', body: { name } })
      return openBoard(board.id)
    }
    catch (error) { toast(error.message, true); value = name }
  }
}

async function renameBoard(board) {
  const name = await askName({ title: 'Rename board', ok: 'Rename', value: board.name })
  if (!name || name === board.name) return
  try {
    const { board: renamed } = await api('whiteboards/' + board.id, { method: 'PATCH', body: { name } })
    if (state.current?.id === renamed.id) { state.current.name = renamed.name; $('boardName').textContent = renamed.name; renderBoard() }
    else { await loadList(); renderList() }
    toast(say('Renamed.'))
  }
  catch (error) { toast(error.message, true) }
}

async function duplicateBoard(board) {
  busy(say('Copying the board…'))
  try {
    // The server copies the drawing and its pictures.
    const name = core.copyName(board.name, state.boards.map(b => b.name), say('copy'))
    await api('whiteboards', { method: 'POST', body: { name, copy_of: board.id } })
    await loadList()
    renderList()
    toast(say('Copied.'))
  }
  catch (error) { toast(error.message, true) }
  finally { busy('') }
}

async function deleteBoard(board) {
  if (!await confirmDelete(board.name)) return
  try {
    await api('whiteboards/' + board.id, { method: 'DELETE' })
    await loadList()
    renderList()
    toast(say('Board deleted.'))
  }
  catch (error) { toast(error.message, true) }
}

$('newBoard').addEventListener('click', createBoard)

// ---- opening a board ---------------------------------------------------------------

function resetBoardState(data) {
  clearTimeout(state.saveTimer)
  clearTimeout(state.retryTimer)
  Object.assign(state, {
    current: { ...data.board }, style: core.guessStyle(data.scene), savedSignature: null,
    savedFileIds: new Set(data.board.file_ids || []), unstorable: new Set(), prepared: {}, pending: {}, checkedFiles: new Set(Object.keys(data.files || {})),
    userActed: false, dirty: false, dirtySince: 0, saving: null, saveTimer: 0, retryTimer: 0, refused: '', blocked: null, selectedChart: null,
  })
}

async function openBoard(id) {
  busy(say('Opening the board…'))
  try {
    if (state.current) await flushSave()
    const [data] = await Promise.all([api('whiteboards/' + id), presentationsSession().catch(() => null)])
    resetBoardState(data)
    state.api = null
    state.opened += 1
    state.fitOnOpen = true
    state.initialData = {
      elements: restoreElements(core.safeElements(data.scene.elements), null),
      appState: { ...core.styleDefaults(state.style), ...(data.scene.appState || {}), theme: state.theme },
      files: data.files || {},
      scrollToContent: true,
    }
    try { sessionStorage.setItem(LAST_BOARD_KEY, id) } catch {}
    $('listHead').hidden = true
    $('boardHead').hidden = false
    $('list').hidden = true
    $('stage').hidden = false
    $('boardName').textContent = state.current.name
    showBanner('')
    renderStyle()
    renderBoard()
    renderStatus()
  }
  catch (error) {
    if (!state.current) await showList()
    toast(error.message, true)
  }
  finally { busy('') }
}

/**
 * Someone else's saved version, loaded into the open board (their changes; this page's unsaved ones are dropped).
 * The view stays where this person has it (zoom and scroll), and so do their current colours and styles: only the
 * drawing, the board's own settings (background, grid) and its style follow.
 */
async function reloadBoard(quiet = false) {
  if (!state.current) return
  const id = state.current.id
  const data = await api('whiteboards/' + id)
  if (state.current?.id !== id || !state.api) return
  resetBoardState(data)
  state.api.addFiles(Object.values(data.files || {}))
  state.api.updateScene({
    elements: restoreElements(core.safeElements(data.scene.elements), null),
    appState: { ...core.boardAppState(data.scene.appState), ...core.styleDefaults(state.style) },
    captureUpdate: CaptureUpdateAction.NEVER,
  })
  // What is on screen now is what is saved: no save for it, and the view is not fitted again as when opening.
  state.savedSignature = currentSignature()
  $('boardName').textContent = state.current.name
  showBanner('')
  renderStyle()
  renderBoard()
  renderStatus()
  if (quiet) toast(`${say('Updated with the latest changes of')} ${data.board.updated_by_name || say('another manager')}.`)
}

$('backToBoards').addEventListener('click', async () => {
  busy(say('Saving…'))
  try { await flushSave() } finally { busy('') }
  if (state.dirty && !state.blocked) {
    toast(say('Your latest changes could not be saved yet. Stay on the board and try again in a moment.'), true)
    return
  }
  showList()
})
$('boardName').addEventListener('click', () => state.current && renameBoard(state.current))

// ---- Excalidraw --------------------------------------------------------------------

const root = createRoot($('stage'))
const LANGUAGE_CODES = X.languages.map(l => l.code)

function chartFrame(element, appState) {
  if (!core.isChartElement(element)) return null
  const model = element.customData.gfmChart
  return h('iframe', {
    className: 'excalidraw__embeddable wb-chart-frame',
    src: core.chartFrameUrl(state.presentations, model, appState.theme === 'dark'),
    title: core.chartTitle(model) || say('Live chart'),
    scrolling: 'no',
    referrerPolicy: 'no-referrer',
    'data-chart': element.id,
  })
}

function renderBoard() {
  if (!state.current || !state.initialData) { root.render(null); return }
  root.render(h(Excalidraw, {
    key: 'board-' + state.opened,
    initialData: state.initialData,
    excalidrawAPI: (value) => { state.api = value },
    onChange,
    theme: state.theme,
    langCode: core.excalidrawLanguage(state.lang, LANGUAGE_CODES),
    name: state.current.name,
    aiEnabled: false,
    UIOptions: {
      canvasActions: { loadScene: false, saveToActiveFile: false, export: false, toggleTheme: false, clearCanvas: false, changeViewBackgroundColor: true, saveAsImage: true },
      tools: { image: true },
    },
    validateEmbeddable: url => core.isChartLink(url),
    renderEmbeddable: chartFrame,
    // Pasted drawings (from another Excalidraw, or a crafted clipboard) come without iframe elements (see
    // core.isForbiddenElement); everything else in them is pasted as usual.
    onPaste: (data) => {
      if (Array.isArray(data?.elements)) {
        const safe = core.safeElements(data.elements)
        if (safe.length < data.elements.length) toast(say('Embedded web pages cannot go on the whiteboard, so they were left out.'), true)
        data.elements = safe
      }
      return true
    },
    // A chart's link icon (top right) opens it in the chart builder instead of following the link.
    onLinkOpen: (element, event) => {
      if (!core.isChartLink(element.link)) return
      event.preventDefault()
      if (core.isChartElement(element)) openBuilder({ elementId: element.id, model: element.customData.gfmChart })
    },
  },
  h(MainMenu, null,
    h(MainMenu.DefaultItems.SaveAsImage),
    h(MainMenu.DefaultItems.SearchMenu),
    h(MainMenu.DefaultItems.Help),
    h(MainMenu.DefaultItems.ChangeCanvasBackground)),
  h(WelcomeScreen, null,
    h(WelcomeScreen.Hints.ToolbarHint),
    h(WelcomeScreen.Hints.MenuHint),
    h(WelcomeScreen.Hints.HelpHint),
    h(WelcomeScreen.Center, null,
      h(WelcomeScreen.Center.Heading, null, say('Draw, write notes and add live charts. Everything saves by itself for the APs, the President and the Data Analysts.'))))))
}

function onChange(elements, appState, files) {
  if (!state.current || !state.api) return
  if (removeForbidden(elements)) return
  findSelectedChart(elements, appState)
  checkPictures(elements, files)
  const scene = core.sceneFor(elements, appState, state.style)
  const signature = core.sceneSignature(scene)
  if (state.savedSignature === null) {
    state.savedSignature = signature
    // A board opens showing all of it (at most at 100 %), so every note and chart is in view. Only when it opens:
    // other people's saves loaded later leave the view where this person has it.
    if (state.fitOnOpen) { state.fitOnOpen = false; setTimeout(fitBoard, 0) }
    return
  }
  if (signature === state.savedSignature || !state.userActed || state.blocked) return
  if (!state.dirty) { state.dirty = true; state.dirtySince = Date.now() }
  if (state.refused) state.refused = ''
  scheduleSave()
  renderStatus()
}

// Changes count only after someone works on the board: Excalidraw also changes elements by itself right after
// opening (for example when a font has loaded), and saving those would tell others "someone saved" for nothing.
for (const type of ['pointerdown', 'keydown', 'paste', 'drop', 'wheel']) {
  $('stage').addEventListener(type, () => { if (type !== 'wheel') state.userActed = true }, true)
}

function fitBoard() {
  const elements = state.api?.getSceneElements() || []
  if (elements.length) state.api.scrollToContent(elements, { fitToContent: true, viewportZoomFactor: 0.9, animate: false })
}

function currentSignature() {
  return core.sceneSignature(core.sceneFor(state.api.getSceneElementsIncludingDeleted(), state.api.getAppState(), state.style))
}

/**
 * An iframe element that reached the board some other way (a dropped file, the library): taken off at once, before
 * anything is saved. Returns whether one was found (the change it makes comes back through onChange).
 */
function removeForbidden(elements) {
  if (!elements.some(e => !e.isDeleted && core.isForbiddenElement(e))) return false
  const next = state.api.getSceneElementsIncludingDeleted().map(e => (!e.isDeleted && core.isForbiddenElement(e) ? newElementWith(e, { isDeleted: true }) : e))
  state.api.updateScene({ elements: next, captureUpdate: CaptureUpdateAction.NEVER })
  toast(say('Embedded web pages cannot go on the whiteboard, so one was taken off.'), true)
  return true
}

// The last guard: a frame showing HTML written into the page (srcdoc, what Excalidraw uses for iframe elements) is
// emptied and fully sandboxed the moment it appears, before its scripts can run. Our charts are frames with an
// address (src), so they are not touched.
function emptyInlineFrames(node) {
  const frames = node.matches?.('iframe[srcdoc]') ? [node] : [...(node.querySelectorAll?.('iframe[srcdoc]') || [])]
  for (const frame of frames) {
    frame.setAttribute('sandbox', '')
    frame.removeAttribute('srcdoc')
    frame.hidden = true
  }
}
new MutationObserver((records) => {
  for (const record of records) {
    if (record.type === 'attributes') { if (record.target.hasAttribute?.('srcdoc')) emptyInlineFrames(record.target) }
    else for (const node of record.addedNodes) if (node.nodeType === 1) emptyInlineFrames(node)
  }
}).observe($('stage'), { childList: true, subtree: true, attributes: true, attributeFilter: ['srcdoc'] })

function findSelectedChart(elements, appState) {
  const ids = Object.keys(appState.selectedElementIds || {}).filter(id => appState.selectedElementIds[id])
  const chart = ids.length === 1 ? elements.find(e => e.id === ids[0] && core.isChartElement(e) && !e.isDeleted) : null
  const id = chart?.id || null
  if (id !== state.selectedChart) { state.selectedChart = id; $('editChart').hidden = !id }
}

// ---- saving --------------------------------------------------------------------------

/** The pictures the server does not hold yet (and can keep) and this browser can send. */
function skipIds() {
  return new Set([...state.savedFileIds, ...state.unstorable])
}

function unsentPictures() {
  if (!state.api) return 0
  return Object.keys(core.filesToSend(state.api.getSceneElements(), state.api.getFiles(), skipIds(), state.prepared, Infinity).files).length
}

function scheduleSave(delay = SAVE_DELAY_MS) {
  clearTimeout(state.saveTimer)
  const waited = state.dirtySince ? Date.now() - state.dirtySince : 0
  state.saveTimer = setTimeout(() => save(), waited > SAVE_MAX_WAIT_MS ? 0 : delay)
}

async function flushSave() {
  clearTimeout(state.saveTimer)
  if (state.saving) await state.saving.catch(() => {})
  if (state.dirty && !state.blocked) await save()
}

/** The server kept the save: the board's new version, the pictures it now holds. */
function saveKept(answer, files, signature) {
  Object.assign(state.current, answer.board)
  state.savedFileIds = new Set(answer.board.file_ids || [])
  // A picture sent but not kept (the server did not take it) is not sent again and again.
  for (const id of Object.keys(files)) if (!state.savedFileIds.has(id)) state.unstorable.add(id)
  state.savedSignature = signature
  state.refused = ''
}

/** The server did not keep the save: what that means for the board, and whether to try again. */
function saveFailed(error, signature) {
  if (error.status === 409 && error.data?.conflict) {
    // Someone else saved in between: the banner offers "Reload their version" or "Keep mine as a new board".
    state.blocked = 'conflict'
    showBanner(say(core.conflictText(error.data.board, state.lang)))
  }
  else if (error.status === 404) {
    state.blocked = 'gone'
    showBanner(say('This board was deleted by someone else. Your drawing is still here: keep it as a new board, or go back to the boards.'), { reload: false })
  }
  else if (error.status === 413 || error.status === 400) {
    // Too large, or not accepted: said as the server says it; tried again after the next change.
    state.refused = error.message
    state.savedSignature = signature
  }
  else if (RETRY_STATUS.has(error.status)) {
    // The connection dropped or the server is restarting: the same save again in a moment.
    state.retryTimer = setTimeout(() => { state.retryTimer = 0; save() }, RETRY_MS)
  }
  else {
    // Refused for another reason (sign-in, rights, a server error): said as the server says it, and tried again
    // after the next change, not over and over.
    state.refused = error.message
    if (error.status >= 500) state.savedSignature = signature
  }
}

/** Sends the board's drawing (and new pictures) once. Only one save runs at a time; a change meanwhile saves again. */
function save() {
  if (!state.current || !state.api || state.blocked) return Promise.resolve()
  if (state.saving) { state.saveAgain = true; return state.saving }
  const run = (async () => {
    const board = state.current
    await Promise.all(Object.values(state.pending))
    if (state.current !== board || !state.api) return
    const elements = state.api.getSceneElementsIncludingDeleted()
    const scene = core.sceneFor(elements, state.api.getAppState(), state.style)
    const signature = core.sceneSignature(scene)
    if (signature === state.savedSignature && !unsentPictures()) { state.dirty = false; return }
    // Many new pictures go over several saves (core.SEND_BUDGET), so no request is too large.
    const { files } = core.filesToSend(scene.elements, state.api.getFiles(), skipIds(), state.prepared)
    clearTimeout(state.retryTimer)
    state.retryTimer = 0
    renderStatus()
    try {
      const answer = await api('whiteboards/' + board.id, { method: 'PUT', body: { version: board.version, scene, files } })
      if (state.current === board) saveKept(answer, files, signature)
    }
    catch (error) {
      if (state.current === board) saveFailed(error, signature)
    }
  })()
  state.saving = run
  renderStatus()
  return run.finally(() => {
    if (state.saving === run) state.saving = null
    if (!state.current || !state.api) return
    state.dirty = (currentSignature() !== state.savedSignature || unsentPictures() > 0) && !state.refused
    if (state.saveAgain || (state.dirty && !state.blocked && !state.retryTimer)) { state.saveAgain = false; scheduleSave(500) }
    renderStatus()
  })
}

$('bannerReload').addEventListener('click', async () => {
  busy(say('Loading their version…'))
  try { await reloadBoard() }
  catch (error) { toast(error.message, true) }
  finally { busy('') }
})

$('bannerCopy').addEventListener('click', async () => {
  if (!state.current || !state.api) return
  const name = await askName({ title: 'Keep mine as a new board', ok: 'Save as new board', value: core.copyName(state.current.name, state.boards.map(b => b.name), say('my copy')) })
  if (!name) return
  busy(say('Saving your version…'))
  try {
    await Promise.all(Object.values(state.pending))
    const scene = core.sceneFor(state.api.getSceneElementsIncludingDeleted(), state.api.getAppState(), state.style)
    // Pictures the old board holds are copied on the server; a deleted board holds none, so all are sent.
    const gone = state.blocked === 'gone'
    const { files } = core.filesToSend(scene.elements, state.api.getFiles(), gone ? new Set() : state.savedFileIds, state.prepared)
    const body = { name, scene, files }
    if (!gone) body.files_from = state.current.id
    const { board } = await api('whiteboards', { method: 'POST', body })
    // The drawing on screen now belongs to the new board and stays on screen as it is (Excalidraw is not started
    // again: its key changes only when a board is opened). Changes made while this was saving, and pictures still
    // missing there, go with the next save.
    Object.assign(state, { current: { ...board }, savedSignature: core.sceneSignature(scene), savedFileIds: new Set(board.file_ids || []), unstorable: new Set(), blocked: null, dirty: false, refused: '' })
    if (currentSignature() !== state.savedSignature || unsentPictures()) { state.dirty = true; state.dirtySince = Date.now(); scheduleSave(300) }
    try { sessionStorage.setItem(LAST_BOARD_KEY, board.id) } catch {}
    $('boardName').textContent = board.name
    showBanner('')
    renderBoard()
    renderStatus()
    loadList().catch(() => {})
    toast(say('Your version is saved as a new board.'))
  }
  catch (error) { toast(error.message, true) }
  finally { busy('') }
})

// Other people's saves: loaded quietly while nothing is changed here; the next save finds them otherwise.
setInterval(async () => {
  if (!state.current || document.visibilityState !== 'visible' || state.blocked || state.saving) return
  try {
    const boards = await loadList()
    const mine = state.current && boards.find(b => b.id === state.current.id)
    if (!state.current) return
    if (!mine) {
      if (!state.dirty && !state.userActed) return showList(say('This board was deleted by someone else.'))
      state.blocked = 'gone'
      showBanner(say('This board was deleted by someone else. Your drawing is still here: keep it as a new board, or go back to the boards.'), { reload: false })
      return renderStatus()
    }
    if (mine.name !== state.current.name) { state.current.name = mine.name; $('boardName').textContent = mine.name }
    if (mine.version > state.current.version && !state.dirty && !state.saving) await reloadBoard(true)
  }
  catch {}
}, POLL_MS)

document.addEventListener('visibilitychange', () => {
  if (document.visibilityState === 'hidden') { if (state.dirty) save() }
  else if (state.current) presentationsSession().catch(() => {})
})

// Leaving the page (another portal tab, sign-out): one last save when it is small enough to go along.
window.addEventListener('pagehide', () => {
  if (!state.dirty || !state.current || !state.api || state.saving || state.blocked) return
  const scene = core.sceneFor(state.api.getSceneElementsIncludingDeleted(), state.api.getAppState(), state.style)
  const { files } = core.filesToSend(scene.elements, state.api.getFiles(), skipIds(), state.prepared)
  const body = { version: state.current.version, scene, files }
  if (JSON.stringify(body).length < 60000) api('whiteboards/' + state.current.id, { method: 'PUT', body, keepalive: true }).catch(() => {})
})

// ---- pictures --------------------------------------------------------------------------

function checkPictures(elements, files) {
  for (const id of core.usedFileIds(elements)) {
    if (state.checkedFiles.has(id)) continue
    const file = files?.[id]
    if (!file?.dataURL) continue
    state.checkedFiles.add(id)
    if (!core.needsShrink(file, core.LIMITS.pictureBytes)) continue
    state.pending[id] = shrinkPicture(file)
      .then((small) => {
        if (small) state.prepared[id] = small
        else removePicture(id)
      })
      .finally(() => { delete state.pending[id] })
  }
}

function loadImage(dataURL) {
  return new Promise((resolve, reject) => {
    const image = new Image()
    image.onload = () => resolve(image)
    image.onerror = () => reject(new Error('picture'))
    image.src = dataURL
  })
}

/** A smaller copy of a picture (WebP, or JPEG where the browser cannot write WebP) within the limit, or null. */
async function shrinkPicture(file) {
  let image
  try { image = await loadImage(file.dataURL) }
  catch { return null }
  for (const [side, quality] of [[1600, 0.85], [1200, 0.8], [900, 0.72]]) {
    const size = core.shrinkSize(image.naturalWidth || image.width, image.naturalHeight || image.height, side)
    const canvas = document.createElement('canvas')
    canvas.width = size.width
    canvas.height = size.height
    const context = canvas.getContext('2d')
    context.drawImage(image, 0, 0, size.width, size.height)
    let dataURL = canvas.toDataURL('image/webp', quality)
    let mimeType = 'image/webp'
    if (!dataURL.startsWith('data:image/webp')) {
      context.globalCompositeOperation = 'destination-over'
      context.fillStyle = '#ffffff'
      context.fillRect(0, 0, size.width, size.height)
      dataURL = canvas.toDataURL('image/jpeg', quality)
      mimeType = 'image/jpeg'
    }
    if (core.dataUrlBytes(dataURL) <= core.LIMITS.pictureBytes) return { id: file.id, mimeType, dataURL }
  }
  return null
}

function removePicture(fileId) {
  if (!state.api) return
  const elements = state.api.getSceneElementsIncludingDeleted().map(e => (e.type === 'image' && e.fileId === fileId && !e.isDeleted ? newElementWith(e, { isDeleted: true }) : e))
  state.api.updateScene({ elements, captureUpdate: CaptureUpdateAction.IMMEDIATELY })
  toast(say('This picture is too large for the whiteboard (at most 2 MB), so it was taken off. Try a smaller picture or a screenshot.'), true)
}

// ---- notes, charts and style -----------------------------------------------------------

function randomId() {
  const bytes = new Uint8Array(12)
  crypto.getRandomValues(bytes)
  return Array.from(bytes, b => b.toString(36).padStart(2, '0')).join('').slice(0, 20)
}

/** A free place near the middle of what is on screen, in board coordinates, for a new thing of this size. */
function middleFor(width, height) {
  const appState = state.api.getAppState()
  const middle = viewportCoordsToSceneCoords({ clientX: appState.offsetLeft + appState.width / 2, clientY: appState.offsetTop + appState.height / 2 }, appState)
  return core.freeSpot(state.api.getSceneElements(), middle, width, height)
}

function addElements(created, select) {
  state.userActed = true
  state.api.updateScene({
    elements: [...state.api.getSceneElementsIncludingDeleted(), ...created],
    appState: { selectedElementIds: { [select]: true } },
    captureUpdate: CaptureUpdateAction.IMMEDIATELY,
  })
  // Bring it into view when the free place is beside what is on screen.
  const appState = state.api.getAppState()
  const topLeft = viewportCoordsToSceneCoords({ clientX: appState.offsetLeft, clientY: appState.offsetTop }, appState)
  const bottomRight = viewportCoordsToSceneCoords({ clientX: appState.offsetLeft + appState.width, clientY: appState.offsetTop + appState.height }, appState)
  const shown = created.every(e => e.x >= topLeft.x && e.y >= topLeft.y && e.x + e.width <= bottomRight.x && e.y + e.height <= bottomRight.y)
  if (!shown) state.api.scrollToContent(created, { animate: true })
}

$('addNote').addEventListener('click', () => {
  if (!state.api) return
  const width = 220, height = 150
  const { x, y } = middleFor(width, height)
  const style = core.STYLES[state.style]
  const created = X.convertToExcalidrawElements([{
    type: 'rectangle', x, y, width, height, backgroundColor: '#ffec99', strokeColor: '#e8a100', fillStyle: 'solid', strokeWidth: 1,
    roughness: style.roughness, roundness: { type: 3 },
    label: { text: say('Note'), fontSize: 20, fontFamily: style.font, strokeColor: '#1e1e1e', textAlign: 'center', verticalAlign: 'middle' },
  }])
  addElements(created, created[0].id)
})

function openBuilder(options) {
  if (!state.api) return
  state.builderFor = options
  busy(say('Opening the chart builder…'))
  presentationsSession().catch(() => null).then(() => {
    if (state.builderFor !== options) return
    const frame = $('builder')
    frame.hidden = false
    frame.src = `${state.presentations}/whiteboard/builder?theme=${encodeURIComponent(document.documentElement.dataset.theme || 'mission')}`
    clearTimeout(state.builderTimer)
    state.builderTimer = setTimeout(() => {
      if (state.builderFor !== options) return
      closeBuilder()
      toast(say('The chart builder could not be opened. Check that Presentations is running, then try again.'), true)
    }, 25000)
  })
}

function closeBuilder() {
  clearTimeout(state.builderTimer)
  state.builderFor = null
  busy('')
  const frame = $('builder')
  frame.hidden = true
  frame.src = 'about:blank'
}

$('addChart').addEventListener('click', () => openBuilder({}))
$('addNumber').addEventListener('click', () => openBuilder({ number: true }))
$('editChart').addEventListener('click', () => {
  const element = state.api?.getSceneElements().find(e => e.id === state.selectedChart)
  if (element && core.isChartElement(element)) openBuilder({ elementId: element.id, model: element.customData.gfmChart })
})

/** The builder's chart: a new chart in the middle of the screen, or the changed chart in its place. */
function placeChart(model) {
  if (!state.api || !state.builderFor) return
  const target = state.builderFor
  state.userActed = true
  if (target.elementId) {
    const elements = state.api.getSceneElementsIncludingDeleted().map(e => (e.id === target.elementId ? newElementWith(e, { customData: { ...(e.customData || {}), gfmChart: model } }) : e))
    state.api.updateScene({ elements, captureUpdate: CaptureUpdateAction.IMMEDIATELY })
    toast(say('Chart updated.'))
    return
  }
  const { width, height } = core.chartSize(model)
  const { x, y } = middleFor(width, height)
  const id = randomId()
  const [element] = restoreElements([{
    id, type: 'embeddable', x, y, width, height, angle: 0, strokeColor: 'transparent', backgroundColor: 'transparent', fillStyle: 'solid',
    strokeWidth: 1, strokeStyle: 'solid', roughness: 0, opacity: 100, roundness: null, groupIds: [], frameId: null, boundElements: null,
    seed: Math.floor(Math.random() * 2 ** 31), version: 1, versionNonce: Math.floor(Math.random() * 2 ** 31), isDeleted: false,
    updated: Date.now(), locked: false, link: core.chartLink(id), customData: { gfmChart: model },
  }], null)
  addElements([element], element.id)
  toast(core.isKeyNumber(model) ? say('Key number added. Drag it where you want it; pull a corner to change its size.') : say('Chart added. Drag it where you want it; pull a corner to change its size.'))
}

function renderStyle() {
  for (const button of document.querySelectorAll('.wb-style button')) button.setAttribute('aria-pressed', String(button.dataset.style === state.style))
}

document.querySelector('.wb-style').addEventListener('click', (event) => {
  const style = event.target.closest('[data-style]')?.dataset.style
  if (!style || !state.api || style === state.style) return
  state.style = style
  state.userActed = true
  const changes = new Map(core.styleChanges(state.api.getSceneElements(), style).map(c => [c.id, c]))
  let elements = state.api.getSceneElementsIncludingDeleted().map((e) => {
    const change = changes.get(e.id)
    if (!change) return e
    const { id, ...fields } = change
    return newElementWith(e, fields)
  })
  // Text in another font needs its box measured again.
  if ([...changes.values()].some(c => c.fontFamily)) elements = restoreElements(elements, null, { refreshDimensions: true, repairBindings: true })
  state.api.updateScene({ elements, appState: core.styleDefaults(style), captureUpdate: CaptureUpdateAction.IMMEDIATELY })
  renderStyle()
  toast(style === 'clean' ? say('Clean lines: straight shapes and a plain font.') : say('Hand-drawn: sketchy shapes and a handwritten font.'))
})

// ---- start -------------------------------------------------------------------------

// For checks and support (portal-api/tests/edge_whiteboard.ps1): what is open, read from this page's own objects.
window.gfmWhiteboard = {
  get api() { return state.api },
  get board() { return state.current ? { ...state.current } : null },
  get saving() { return { dirty: state.dirty, saving: !!state.saving, blocked: state.blocked, refused: state.refused, style: state.style } },
  sceneCoordsToViewportCoords: X.sceneCoordsToViewportCoords,
  convertToExcalidrawElements: X.convertToExcalidrawElements,
  restoreElements,
}

async function start() {
  state.lang = startingLanguage()
  try { window.parent.postMessage({ type: 'portal-theme-request' }, location.origin) } catch {}
  if (!shell()) setTheme(window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'mission')
  if (window.MissionI18n?.ready) window.MissionI18n.ready.then(() => { if (new URLSearchParams(location.search).get('lang')) window.MissionI18n.setLanguage(state.lang); renderList(); renderStatus() })
  window.addEventListener('mission-i18n-change', () => { renderList(); renderStatus(); renderBoard() })
  const asked = new URLSearchParams(location.search).get('board')
  let last = asked
  if (!last) try { last = sessionStorage.getItem(LAST_BOARD_KEY) } catch {}
  await showList()
  if (last && state.boards.some(b => b.id === last)) openBoard(last)
}

start()
