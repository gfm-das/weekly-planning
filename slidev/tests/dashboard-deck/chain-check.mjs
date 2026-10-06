// TEST ONLY: the Mission Dashboard deck through the whole chain on a THROWAWAY database copy:
//   browser requests -> presentation manager (this repository's slidev/manager, the deck installed as
//   /slidev/decks/mission-dashboard, no access rule) -> portal-api (this repository's code, on the copy)
//   -> the dashboards views, with supabase_stub.py standing in for Supabase Auth and PostgREST (ids only).
// Checks: an AP gets a presentation session, opens /p/mission-dashboard/ (the first view builds it) and every chart
// query written in the deck answers with numbers and is pinned; a DL and a ZL get their session (they are leaders)
// but are refused the deck page and every one of its charts.
// Prints counts and timings only.
//
//   docker run --rm --network gfm-test-r2-net -v <repo>/slidev:/repo:ro node:24-alpine \
//       node /repo/tests/dashboard-deck/chain-check.mjs http://gfm-test-dash-mgr:3040 http://gfm-test-dash-auth:8000
import { readFileSync } from 'node:fs'
import { canonicalJson, normalizeSpec } from '../../manager/gfm-addon/lib/chart-spec.mjs'

const [MANAGER = 'http://gfm-test-dash-mgr:3040', STUB = 'http://gfm-test-dash-auth:8000'] = process.argv.slice(2)
const DECK = 'mission-dashboard'
const deckFile = new URL('../../showcase/mission-dashboard/slides.md', import.meta.url)
const results = []
const check = (name, ok, detail = '') => {
  results.push(!!ok)
  console.log(`${ok ? 'PASS' : 'FAIL'} ${name}${detail !== '' ? ` - ${String(detail).slice(0, 300)}` : ''}`)
}

const b64 = value => Buffer.from(JSON.stringify(value)).toString('base64url')
const token = sub => `${b64({ alg: 'HS256', typ: 'JWT' })}.${b64({ sub, exp: Math.floor(Date.now() / 1000) + 3600, role: 'authenticated' })}.stub`

async function signIn(sub) {
  const response = await fetch(`${MANAGER}/api/session`, { method: 'POST', headers: { Authorization: `Bearer ${token(sub)}` } })
  const cookie = (response.headers.get('set-cookie') || '').split(';')[0]
  return { status: response.status, cookie, body: await response.json().catch(() => ({})) }
}

async function get(path, cookie, accept = 'text/html') {
  const started = Date.now()
  const response = await fetch(`${MANAGER}${path}`, { headers: { Cookie: cookie, Accept: accept } })
  const text = await response.text()
  return { status: response.status, text, took: (Date.now() - started) / 1000 }
}

async function chart(cookie, spec) {
  const started = Date.now()
  const response = await fetch(`${MANAGER}/api/charts/data`, {
    method: 'POST', headers: { Cookie: cookie, 'Content-Type': 'application/json', Accept: 'application/json' },
    body: JSON.stringify({ deck: DECK, spec }),
  })
  return { status: response.status, body: await response.json().catch(() => ({})), took: (Date.now() - started) / 1000 }
}

const health = await fetch(`${MANAGER}/health`).then(r => r.json())
check('the manager answers /health', health.ok === true, `chart addon ${health.chart_addon}`)
const users = await fetch(`${STUB}/stub/users`).then(r => r.json())
check('the copy has an AP, a DL and a ZL', users.ap && users.dl && users.zl)

const ap = await signIn(users.ap), dl = await signIn(users.dl), zl = await signIn(users.zl)
check('an AP gets a presentation session', ap.status === 200 && ap.cookie.startsWith('presentation_session='), ap.status)
check('a DL and a ZL get their own session (they are leaders)', dl.status === 200 && zl.status === 200 && dl.cookie && zl.cookie, `${dl.status} ${zl.status}`)

// The deck page. The first view builds it (one build at a time), so allow a while.
const page = await get(`/p/${DECK}/`, ap.cookie)
check('an AP opens /p/mission-dashboard/ (built on the first view)', page.status === 200 && page.text.includes('<div id="app"'), `${page.status} in ${page.took}s`)
check('the AP gets the edit button (editable in /studio)', page.text.includes('portal-edit-presentation') && page.text.includes(`/studio/${DECK}`))
const title = page.text.match(/<title>([^<]*)<\/title>/)?.[1]
check('the page is titled Mission Dashboard', title === 'Mission Dashboard', title)
const again = await get(`/p/${DECK}/`, ap.cookie)
check('a second view is served from the build', again.status === 200 && again.took < 2, `${again.took}s`)
for (const [who, session] of [['DL', dl], ['ZL', zl]]) {
  const refused = await get(`/p/${DECK}/`, session.cookie)
  check(`a ${who} is refused the deck page`, refused.status === 403 && refused.text.includes('not assigned to you'), refused.status)
  const deep = await get(`/p/${DECK}/3`, session.cookie)
  check(`a ${who} is refused a slide address too`, deep.status === 403, deep.status)
}

// Every chart query in the deck.
const text = readFileSync(deckFile, 'utf8')
const queries = [...text.matchAll(/:query='([^']*)'/g)].map(m => normalizeSpec(JSON.parse(m[1])))
check('the deck has its charts', queries.length >= 20, queries.length)
let answered = 0, pinned = 0, slowest = 0
const problems = []
for (const spec of queries) {
  const got = await chart(ap.cookie, spec)
  slowest = Math.max(slowest, got.took)
  const values = (got.body.table?.series ?? []).flatMap(s => s.values)
  if (got.status === 200 && got.body.table?.labels?.length && values.some(v => v !== null)) answered++
  else problems.push(`${got.status} ${canonicalJson(spec).slice(0, 80)} ${got.body.error || ''}`)
  if (got.body.meta?.pinned === true) pinned++
}
check(`every chart answers for an AP with numbers (${queries.length})`, answered === queries.length, problems.slice(0, 3).join(' | '))
check('every chart is pinned in the deck (written as plain JSON)', pinned === queries.length, `${pinned}/${queries.length}`)
check('the slowest chart answers in under 2 s', slowest < 2, `${slowest}s`)
for (const [who, session] of [['DL', dl], ['ZL', zl]]) {
  const statuses = new Set()
  for (const spec of queries) statuses.add((await chart(session.cookie, spec)).status)
  check(`a ${who} is refused every chart of the deck`, statuses.size === 1 && statuses.has(403), [...statuses].join(','))
}
const nobody = await chart('', queries[0])
check('without a session a chart is refused', nobody.status === 401, nobody.status)

const passed = results.filter(Boolean).length
console.log(`\n${passed} of ${results.length} checks passed`)
process.exit(passed === results.length ? 0 : 1)
