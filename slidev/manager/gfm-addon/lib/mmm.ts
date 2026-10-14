// The Vue side of the MMM / ZOKO / Stake pieces (<MmmCard>, <MmmGauge>, <MmmTrend>, <MmmTable>, <MmmPair>): asking for
// the numbers of one chart query the way <MissionChart :query> does (the same endpoint, the same "pinning": a leader
// sees a query only when it is written in the deck's slides as plain JSON, `:query='{...}'`), and the shared helpers
// of their drawings. The arithmetic is in mmm-core.mjs (tested with plain Node).
import type { Ref } from 'vue'
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import type { ChartAnswer } from './charts'
import { ChartDataError, fetchChartData, peekChartData } from './charts'
import { canonicalJson, deckOfPath, normalizeSpec } from './chart-spec.mjs'

export * from './mmm-core.mjs'

const STALE_MS = 10 * 60 * 1000

/**
 * Loads the numbers of `query` (a chart query, an object or JSON text). `state` is loading, ready or error; `message`
 * is what a piece says instead of numbers (the server's own sentence for a refusal); the answer is asked for again
 * when the slide has been left for ten minutes (`refresh`, called when the slide comes into view).
 */
export function useMmmQuery(query: Ref<any> | (() => any)) {
  const read = typeof query === 'function' ? query : () => query.value
  const has = computed(() => { const q = read(); return q !== undefined && q !== null && q !== '' })
  const spec = computed(() => {
    if (!has.value) return { value: null as any, key: '', problem: '' }
    try {
      const value = normalizeSpec(read())
      return { value, key: canonicalJson(value), problem: '' }
    }
    catch (error: any) {
      return { value: null, key: '', problem: `The settings have a mistake: ${error?.message || error}` }
    }
  })
  const deck = typeof location === 'undefined' ? '' : deckOfPath(location.pathname)
  const answer = ref<ChartAnswer | null>(spec.value.key ? peekChartData(deck, spec.value.key) : null)
  const state = ref<'loading' | 'ready' | 'error'>(answer.value ? 'ready' : 'loading')
  const loadError = ref('')
  let loadedAt = 0
  let request = 0

  async function load() {
    const { value, key } = spec.value
    if (!value) return
    const mine = ++request
    if (!answer.value) state.value = 'loading'
    try {
      const got = await fetchChartData(deck, value, key)
      if (mine !== request) return
      answer.value = got
      loadedAt = Date.now()
      state.value = 'ready'
    }
    catch (error) {
      if (mine !== request) return
      loadError.value = error instanceof ChartDataError ? error.message : 'The numbers could not load. Try again in a minute.'
      if (!answer.value || error instanceof ChartDataError) {
        answer.value = null
        state.value = 'error'
      }
    }
  }
  let timer: ReturnType<typeof setInterval> | null = null
  onMounted(() => { if (has.value) load(); timer = setInterval(refresh, 60000) })
  onBeforeUnmount(() => { if (timer) clearInterval(timer) })
  watch(() => spec.value.key, (now, before) => {
    if (now === before) return
    answer.value = now ? peekChartData(deck, now) : null
    if (now) load()
  })
  const message = computed(() => {
    if (!has.value) return ''
    if (spec.value.problem) return spec.value.problem
    if (state.value === 'error') return loadError.value
    if (state.value === 'loading') return 'Loading mission numbers…'
    return ''
  })
  function refresh() {
    if (has.value && (state.value === 'error' || (state.value === 'ready' && Date.now() - loadedAt > STALE_MS))) load()
  }
  return { has, answer, state, message, refresh, suppressed: computed(() => !!answer.value?.meta?.suppressed) }
}

/** A list setting written in a slide as an array or as text separated by `|` (the Studio panel gives text). */
export function listOf(value: any): string[] {
  if (Array.isArray(value)) return value.map(v => String(v ?? ''))
  if (typeof value === 'string' && value.trim()) {
    const text = value.trim()
    if (text.startsWith('[')) { try { const parsed = JSON.parse(text); if (Array.isArray(parsed)) return parsed.map(v => String(v ?? '')) } catch {} }
    return text.split('|').map(s => s.trim())
  }
  return []
}

/** The rows of a hand-made table: an array of rows, or text with one row per `;` and cells split by `|`. */
export function manualRows(value: any): string[][] {
  if (Array.isArray(value)) return value.map(row => (Array.isArray(row) ? row.map(c => String(c ?? '')) : String(row ?? '').split('|').map(s => s.trim())))
  if (typeof value === 'string' && value.trim()) {
    const text = value.trim()
    if (text.startsWith('[')) { try { const parsed = JSON.parse(text); if (Array.isArray(parsed)) return manualRows(parsed) } catch {} }
    return text.split(';').map(row => row.split('|').map(s => s.trim())).filter(row => row.some(Boolean))
  }
  return []
}
