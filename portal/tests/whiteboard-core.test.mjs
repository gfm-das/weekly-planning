// The Whiteboard page's rules (portal/whiteboard/board-core.js) in plain Node: chart elements and their frame
// address, where new things go, what a save keeps and sends (pictures over several saves), the two drawing styles,
// names of copies, Excalidraw's language, and the sentences about saving. The frame's reading of the address
// (slidev/manager/whiteboard-chart.mjs) is checked against this file in slidev/tests/whiteboard.test.mjs.
// Run from the repository root: node --test portal/tests/whiteboard-core.test.mjs
import test from 'node:test'
import assert from 'node:assert/strict'
import * as core from '../whiteboard/board-core.js'

const model = { v: 2, source: 'mission', spec: { measures: ['friends_found.actual', 'friends_found.previous_goal'], weeks: 12 }, option: { title: { text: 'New people being taught – Zürich' }, series: [{ type: 'bar' }] } }
const tile = { v: 2, source: 'mission', spec: { measures: ['friends_found.actual'] }, option: { gfm: { kind: 'tile' }, series: [{ type: 'line' }] } }

test('chart elements: our link, an embeddable, and a chart model', () => {
  assert.equal(core.chartLink('a b'), 'https://gfm-whiteboard.invalid/chart/a%20b')
  assert.ok(core.isChartLink(core.chartLink('x')))
  assert.ok(!core.isChartLink('https://example.org/chart/'))
  assert.ok(core.isChartElement({ type: 'embeddable', link: core.chartLink('x'), customData: { gfmChart: model } }))
  assert.ok(!core.isChartElement({ type: 'embeddable', link: 'https://www.youtube.com/embed/x', customData: { gfmChart: model } }))
  assert.ok(!core.isChartElement({ type: 'rectangle', link: core.chartLink('x'), customData: { gfmChart: model } }))
  assert.ok(!core.isChartElement({ type: 'embeddable', link: core.chartLink('x') }))
})

test('the frame address: the chart after "#" (never sent to a server)', () => {
  const url = core.chartFrameUrl('http://192.168.1.20:3030/', model, true)
  assert.match(url, /^http:\/\/192\.168\.1\.20:3030\/whiteboard\/chart\?theme=dark#[A-Za-z0-9_-]+$/)
  assert.equal(core.chartFrameUrl('http://h:3030', model, false).split('#')[0], 'http://h:3030/whiteboard/chart?theme=light')
  const read = JSON.parse(Buffer.from(url.split('#')[1], 'base64url').toString('utf8'))
  assert.deepEqual(read, model, 'the whole model, umlauts and dashes included')
})

test('the Presentations address: the shell tells it; otherwise this host on port 3030', () => {
  const location = { protocol: 'http:', hostname: '192.168.1.20' }
  assert.equal(core.presentationsAddress(location, 'http://localhost:3030/'), 'http://localhost:3030')
  assert.equal(core.presentationsAddress(location, undefined), 'http://192.168.1.20:3030')
  assert.equal(core.presentationsAddress(location, 'javascript:alert(1)'), 'http://192.168.1.20:3030')
  assert.equal(core.presentationsAddress(location, 'http://evil.test/path'), 'http://192.168.1.20:3030')
})

test('new things go in the middle, or beside what is already there, never on top of it', () => {
  assert.deepEqual(core.freeSpot([], { x: 500, y: 300 }, 200, 100), { x: 400, y: 250 })
  const note = { id: 'n', x: 400, y: 250, width: 200, height: 100 }
  const spot = core.freeSpot([note], { x: 500, y: 300 }, 560, 340)
  const overlaps = (a, b) => a.x < b.x + b.width && b.x < a.x + a.width && a.y < b.y + b.height && b.y < a.y + a.height
  assert.ok(!overlaps({ ...spot, width: 560, height: 340 }, note), JSON.stringify(spot))
  // Deleted elements and text inside a note do not count.
  assert.deepEqual(core.freeSpot([{ ...note, isDeleted: true }, { x: 400, y: 250, width: 10, height: 10, containerId: 'n' }], { x: 500, y: 300 }, 200, 100), { x: 400, y: 250 })
  // Negative sizes (drawn from right to left) are boxes too.
  const back = { x: 600, y: 350, width: -200, height: -100 }
  assert.ok(!overlaps({ ...core.freeSpot([back], { x: 500, y: 300 }, 100, 50), width: 100, height: 50 }, { x: 400, y: 250, width: 200, height: 100 }))
})

test('sizes and titles of charts and key numbers (round 6 options and older settings)', () => {
  assert.deepEqual(core.chartSize(model), core.CHART_SIZE.chart)
  assert.deepEqual(core.chartSize(tile), core.CHART_SIZE.tile)
  assert.deepEqual(core.chartSize({ props: { type: 'tile' } }), core.CHART_SIZE.tile)
  assert.equal(core.chartTitle(model), 'New people being taught – Zürich')
  assert.equal(core.chartTitle({ option: { title: [{ text: ' First ' }] } }), 'First')
  assert.equal(core.chartTitle({ props: { title: 'Older' } }), 'Older')
  assert.equal(core.chartTitle(tile), '')
})

test('what a save keeps: elements still on the board, the board settings, the style', () => {
  const elements = [{ id: 'a', version: 2, versionNonce: 5 }, { id: 'b', version: 1, versionNonce: 1, isDeleted: true }]
  const appState = { viewBackgroundColor: '#fff', zoom: { value: 2 }, selectedElementIds: { a: true }, currentItemRoughness: 0, onChange: () => {} }
  const scene = core.sceneFor(elements, appState, 'clean')
  assert.deepEqual(scene, { type: 'gfm-whiteboard', v: 1, style: 'clean', elements: [elements[0]], appState: { viewBackgroundColor: '#fff', currentItemRoughness: 0 } })
  assert.equal(core.sceneFor([], {}, 'fancy').style, 'hand')
  const signature = core.sceneSignature(scene)
  assert.notEqual(core.sceneSignature(core.sceneFor([{ id: 'a', version: 3, versionNonce: 5 }], appState, 'clean')), signature, 'an element changed')
  assert.notEqual(core.sceneSignature(core.sceneFor(elements, appState, 'hand')), signature, 'the style changed')
  assert.notEqual(core.sceneSignature(core.sceneFor(elements, { ...appState, viewBackgroundColor: '#000' }, 'clean')), signature, 'a board setting changed')
  assert.equal(core.sceneSignature(core.sceneFor(elements, { ...appState, zoom: { value: 1 } }, 'clean')), signature, 'zoom is personal')
})

test('iframe elements never go on a board: Excalidraw would run the HTML they carry', () => {
  const page = { status: 'done', html: '<form>Session expired</form><script>alert(1)</script>' }
  const elements = [
    { id: 'f', type: 'iframe', link: core.chartLink('x'), customData: { generationData: page } },
    { id: 'c', type: 'embeddable', link: core.chartLink('c'), customData: { gfmChart: model, generationData: page } },
    { id: 'n', type: 'rectangle', customData: { generationData: page, mine: 1 } },
    { id: 'r', type: 'rectangle' },
  ]
  assert.ok(core.isForbiddenElement(elements[0]))
  assert.ok(!core.isForbiddenElement(elements[1]) && !core.isForbiddenElement(elements[3]) && !core.isForbiddenElement(null))
  const safe = core.safeElements(elements)
  assert.deepEqual(safe.map(e => e.id), ['c', 'n', 'r'])
  assert.deepEqual(safe[0].customData, { gfmChart: model })
  assert.deepEqual(safe[1].customData, { mine: 1 })
  assert.equal(safe[2], elements[3], 'elements without generationData are kept as they are')
  assert.ok(!JSON.stringify(safe).includes('Session expired'))
  assert.deepEqual(core.safeElements(undefined), [])
  assert.deepEqual(core.sceneFor(elements, {}, 'hand').elements.map(e => e.id), ['c', 'n', 'r'], 'never saved either')
})

test("someone else's save: only the board's own settings follow into a board open elsewhere", () => {
  const theirs = { viewBackgroundColor: '#123456', gridModeEnabled: true, gridSize: 20, currentItemStrokeColor: '#e03131', currentItemRoughness: 2, zoom: { value: 3 }, scrollX: 40 }
  assert.deepEqual(core.boardAppState(theirs), { viewBackgroundColor: '#123456', gridModeEnabled: true, gridSize: 20 })
  assert.deepEqual(core.boardAppState(undefined), {})
  for (const key of core.BOARD_APP_STATE) assert.ok(core.SAVED_APP_STATE.includes(key), key)
})

test('pictures: in use, sizes, when to make them smaller', () => {
  const elements = [{ type: 'image', fileId: 'p1' }, { type: 'image', fileId: 'p2', isDeleted: true }, { type: 'rectangle', fileId: 'p3' }, { type: 'image', fileId: 'p1' }]
  assert.deepEqual([...core.usedFileIds(elements)], ['p1'])
  const url = 'data:image/png;base64,' + Buffer.alloc(3000).toString('base64')
  assert.equal(core.dataUrlBytes(url), 3000)
  assert.equal(core.dataUrlBytes('data:image/png;base64,' + Buffer.alloc(3001).toString('base64')), 3001)
  assert.equal(core.dataUrlBytes('nonsense'), 0)
  assert.ok(!core.needsShrink({ mimeType: 'image/png', dataURL: url }))
  assert.ok(core.needsShrink({ mimeType: 'image/png', dataURL: url }, 2999), 'larger than the limit')
  assert.ok(core.needsShrink({ mimeType: 'image/bmp', dataURL: url }), 'not a type the board keeps')
  assert.deepEqual(core.shrinkSize(4000, 3000), { width: 1600, height: 1200 })
  assert.deepEqual(core.shrinkSize(800, 600), { width: 800, height: 600 }, 'never made larger')
  assert.deepEqual(core.shrinkSize(3000, 10, 900), { width: 900, height: 3 })
})

test('a save sends only pictures the server lacks, and many big ones over several saves', () => {
  const pic = n => ({ mimeType: 'image/webp', dataURL: 'data:image/webp;base64,' + 'A'.repeat(n) })
  const elements = ['a', 'b', 'c', 'd', 'e'].map(id => ({ type: 'image', fileId: id }))
  const files = { a: pic(10), b: pic(3_000_000), c: pic(3_000_000), d: pic(3_000_000) }
  const prepared = { b: pic(1_000) }
  const first = core.filesToSend(elements, files, new Set(['a']), prepared)
  assert.deepEqual(Object.keys(first.files), ['b', 'c', 'd'], 'the smaller copy of b counts')
  assert.equal(first.files.b.dataURL, prepared.b.dataURL)
  assert.deepEqual(first.missing, ['e'], 'a picture this browser does not have')
  assert.equal(first.left, 0)
  const budget = core.filesToSend(elements, { ...files, b: pic(5_000_000) }, new Set(['a']), {}, 8_000_000)
  assert.deepEqual(Object.keys(budget.files), ['b'], 'the budget keeps the rest for the next save')
  assert.equal(budget.left, 2)
  const oneBig = core.filesToSend([{ type: 'image', fileId: 'z' }], { z: pic(9_000_000) }, new Set(), {}, 8_000_000)
  assert.deepEqual(Object.keys(oneBig.files), ['z'], 'at least one picture always goes')
  assert.ok(core.SEND_BUDGET <= 8 * 1024 * 1024 && core.SEND_BUDGET + 4 * 1024 * 1024 < 16 * 1024 * 1024, 'a save stays under the 16 MB request limit')
})

test('the two styles: straight shapes and a plain font, or sketchy shapes and a handwritten font', () => {
  const elements = [
    { id: 'r', type: 'rectangle', roughness: 1 }, { id: 'a', type: 'arrow', roughness: 2 }, { id: 't', type: 'text', roughness: 1, fontFamily: 5 },
    { id: 'c', type: 'text', roughness: 1, fontFamily: 8 }, { id: 'i', type: 'image', roughness: 1 }, { id: 'e', type: 'embeddable', roughness: 0 },
    { id: 'gone', type: 'rectangle', roughness: 1, isDeleted: true },
  ]
  assert.deepEqual(core.styleChanges(elements, 'clean'), [{ id: 'r', roughness: 0 }, { id: 'a', roughness: 0 }, { id: 't', fontFamily: 6 }])
  const clean = elements.map(e => ({ ...e, ...(core.styleChanges(elements, 'clean').find(c => c.id === e.id) || {}) }))
  assert.deepEqual(core.styleChanges(clean, 'hand'), [{ id: 'r', roughness: 1 }, { id: 'a', roughness: 1 }, { id: 't', fontFamily: 5 }])
  assert.deepEqual(core.styleChanges(elements, 'hand'), [], 'a sketchier shape (2) stays as it is')
  assert.deepEqual(core.styleDefaults('clean'), { currentItemRoughness: 0, currentItemFontFamily: 6 })
  assert.equal(core.guessStyle({ elements: [{ type: 'rectangle', roughness: 0 }] }), 'clean')
  assert.equal(core.guessStyle({ elements: [{ type: 'rectangle', roughness: 1 }, { type: 'rectangle', roughness: 0 }] }), 'hand')
  assert.equal(core.guessStyle({ style: 'clean', elements: [] }), 'clean')
})

test('names of copies, and Excalidraw language', () => {
  assert.equal(core.copyName('Zone council', ['Zone council']), 'Zone council (copy)')
  assert.equal(core.copyName('Zone council (copy)', ['Zone council', 'zone council (COPY)']), 'Zone council (copy 2)')
  assert.equal(core.copyName('Plan', ['Plan'], 'my copy'), 'Plan (my copy)')
  assert.ok(core.copyName('x'.repeat(80), []).length <= 80)
  const codes = ['en', 'de-DE', 'es-ES', 'fr-FR', 'pt-BR', 'pt-PT', 'zh-CN']
  assert.equal(core.excalidrawLanguage('de', codes), 'de-DE')
  assert.equal(core.excalidrawLanguage('pt', codes), 'pt-PT')
  assert.equal(core.excalidrawLanguage('pt-BR', codes), 'pt-BR')
  assert.equal(core.excalidrawLanguage('en-GB', codes), 'en')
  assert.equal(core.excalidrawLanguage('zh', codes), 'zh-CN')
  assert.equal(core.excalidrawLanguage('tl', codes), 'en')
  assert.equal(core.excalidrawLanguage('', codes), 'en')
})

test('the sentences about saving', () => {
  const now = new Date('2026-09-28T14:30:00')
  const board = { updated_at: new Date('2026-09-28T14:05:00').toISOString(), updated_by_name: 'Elder Example' }
  assert.match(core.lastSavedText(board, 'en-GB', now), /^Last saved by Elder Example at 14:05$/)
  assert.match(core.lastSavedText({ ...board, updated_at: new Date('2026-09-26T09:00:00').toISOString() }, 'en-GB', now), /^Last saved by Elder Example on 26 Sept?, 09:00$/)
  assert.equal(core.lastSavedText({}, 'en', now), '')
  const conflict = core.conflictText(board, 'en-GB', now)
  assert.match(conflict, /^Elder Example saved this board \(14:05\) while you were working on it/)
  assert.match(conflict, /Reload to see their version, or keep yours as a new board\.$/)
  assert.match(core.conflictText({}, 'en', now), /^Someone else saved this board while/)
})
