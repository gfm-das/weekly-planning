<script setup lang="ts">
/**
 * MmmCard - a key-number card of the Monday Morning Meeting, zone conference and Stake decks: the title, the big
 * number, how far it is toward the goal (a coloured percent and a bar) and two small badges, "Last" (the week or
 * period before) and "Goal".
 *
 * Live from the weekly plans, like <MissionChart :query>:
 * <MmmCard x="55" y="100" w="190" h="190" tone="green" title="Friends Found"
 *   :query='{"measures":["friends_found.actual","friends_found.previous_goal"],"weeks":4}' />
 *
 * `mode`: goal (the latest week against the goal set the week before), share (the second number as a share of the
 * first, e.g. new members at church), period (the sum for this month / quarter / year against a goal typed in the
 * slide) or manual (every number typed in the slide: value, last, goal). A hand-typed place carries a small
 * "Manual" tag while `placeholder` is on, so nobody takes it for a live number. The query must be written in the slide
 * as plain JSON (like every chart), or a leader cannot see it.
 */
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { goalCard, numberText, percentText, periodCard, shareCard, toneOf, useMmmQuery } from '../lib/mmm'

const props = withDefaults(defineProps<{
  x?: number
  y?: number
  w?: number
  h?: number
  title?: string
  query?: Record<string, any> | string
  mode?: 'goal' | 'share' | 'period' | 'manual'
  tone?: 'green' | 'amber' | 'red' | 'cyan'
  period?: 'month' | 'quarter' | 'year'
  value?: number | string
  last?: number | string
  goal?: number | string
  target?: string
  barLabel?: string
  digits?: number
  lastLabel?: string
  goalLabel?: string
  naText?: string
  tag?: string
  placeholder?: boolean
  goalAt?: 'bottom' | 'top'
  noBadges?: boolean
  hideGoal?: boolean
  hideLast?: boolean
  lastAt?: 'left' | 'right'
  noPct?: boolean
  noBar?: boolean
  footerText?: string
}>(), {
  x: 55, y: 100, w: 190, h: 190, title: '', mode: 'goal', tone: 'green', period: 'month', digits: 1,
  lastLabel: 'Last', goalLabel: 'Goal', naText: 'N/A', tag: 'Manual', placeholder: false, goalAt: 'bottom', noBadges: false, hideGoal: false, hideLast: false, lastAt: 'left', noPct: false, noBar: false, barLabel: '', footerText: '',
})

const { answer, message, has } = useMmmQuery(() => props.query)
const locale = typeof document === 'undefined' ? undefined : document.documentElement.lang || undefined
const typed = (v: any) => (v === undefined || v === null || v === '' || !Number.isFinite(Number(v)) ? null : Number(v))

const model = computed(() => {
  if (props.mode === 'manual' || !has.value) {
    const value = typed(props.value), goal = typed(props.goal) || null
    return value === null ? { ready: false } : { ready: true, value, last: typed(props.last), goal, ratio: goal ? value / goal : null }
  }
  if (!answer.value) return { ready: false }
  if (props.mode === 'share') {
    const s: any = shareCard(answer.value)
    return s.ready ? { ...s, goal: null } : s
  }
  if (props.mode === 'period') return periodCard(answer.value, { period: props.period, target: props.goal })
  return goalCard(answer.value)
})

const ratio = computed<number | null>(() => (model.value as any).ratio ?? null)
const percent = computed(() => (ratio.value === null ? props.naText : percentText(ratio.value, props.digits)))
const bar = computed(() => `${Math.round(Math.max(0, Math.min(1, ratio.value ?? 0)) * 100)}%`)
const big = computed(() => ((model.value as any).ready ? numberText((model.value as any).value, locale) : '–'))
const lastText = computed(() => numberText((model.value as any).last, locale) || '–')
const goalText = computed(() => {
  if (props.target) return props.target
  const g = (model.value as any).goal
  // A goal-mode card without a goal says 0 (a zone with no Baptisms goal, as in the reference); a goal typed in the
  // slide that is still empty says –.
  if (g === null || g === undefined) return props.mode === 'goal' ? numberText(0, locale) : '–'
  return numberText(g, locale)
})
const place = computed(() => ({
  left: `calc(${props.x} * var(--u))`, top: `calc(${props.y} * var(--u))`, width: `calc(${props.w} * var(--u))`, height: `calc(${props.h} * var(--u))`,
}))
// A low ratio is drawn in the card's own colour; the bar never goes grey while a number is there.
// A title that wraps onto two lines makes room: the number and the bar move down a little and the number gets smaller.
const titleEl = ref<HTMLElement>()
const compact = ref(false)
function measure() {
  const el = titleEl.value
  if (!el) return
  const size = parseFloat(getComputedStyle(el).fontSize) || 17
  compact.value = el.offsetHeight > size * 1.15 * 1.5
}
onMounted(() => nextTick(measure))
watch(() => props.title, () => nextTick(measure))
const tone = computed(() => `mmm-card--${props.tone} mmm-card--${toneOf(ratio.value)}`)
</script>

<template>
  <div class="mmm-box mmm-card" :class="[tone, { 'is-compact': compact }]" :style="place" role="group" :aria-label="title">
    <div class="mmm-card__body mmm-panel">
      <span v-if="placeholder" class="mmm-manual-tag">{{ tag }}</span>
      <div ref="titleEl" class="mmm-card__title">{{ title }}</div>
      <div class="mmm-card__big">{{ big }}</div>
      <div v-if="!noPct" class="mmm-card__pct">{{ percent }}</div>
      <div v-if="!noBar" class="mmm-card__bar"><i :style="{ width: bar }" /></div>
      <div v-if="barLabel" class="mmm-card__barlabel">{{ barLabel }}</div>
      <div v-if="footerText" class="mmm-card__foot">{{ footerText }}</div>
      <div v-if="message" class="mmm-card__note" :title="message">{{ message }}</div>
    </div>
    <div v-if="!noBadges && !hideLast" class="mmm-badge mmm-badge--last" :class="{ 'mmm-badge--right': lastAt === 'right' }"><b>{{ lastLabel }}</b><span>{{ lastText }}</span></div>
    <div v-if="!noBadges && !hideGoal && (mode !== 'share' || target)" class="mmm-badge mmm-badge--goal" :class="{ 'mmm-badge--top': goalAt === 'top' }"><b>{{ goalLabel }}</b><span>{{ goalText }}</span></div>
  </div>
</template>

<style>
.mmm-card { --c: var(--mmm-green); --t: var(--mmm-green-tint); }
.mmm-card--green { --c: var(--mmm-green); --t: var(--mmm-green-tint); }
.mmm-card--amber { --c: var(--mmm-amber); --t: var(--mmm-amber-tint); }
.mmm-card--red { --c: var(--mmm-red); --t: var(--mmm-red-tint); }
.mmm-card--cyan { --c: var(--mmm-cyan); --t: var(--mmm-cyan-tint); }
.mmm-card__body { position: absolute; inset: 0; text-align: center; overflow: visible; }
.mmm-card__title { position: absolute; left: 4%; right: 4%; top: calc(24 * var(--u)); font-weight: 700; font-size: calc(17 * var(--u)); line-height: 1.15; }
.mmm-card__big { position: absolute; left: 0; right: 0; top: calc(50 * var(--u)); font-size: calc(48 * var(--u)); font-weight: 300; line-height: 1.1; }
.mmm-card__pct { position: absolute; left: 0; right: 0; top: calc(106 * var(--u)); font-size: calc(21 * var(--u)); font-weight: 400; color: var(--c); }
.mmm-card__bar { position: absolute; left: 13%; right: 13%; top: calc(137 * var(--u)); height: calc(14 * var(--u)); background: #ececec; border-radius: 99px; overflow: hidden; }
.mmm-dark .mmm-card__bar { background: #4a4a4a; }
.mmm-card__bar i { display: block; height: 100%; background: var(--c); border-radius: 99px; min-width: calc(8 * var(--u)); }
.mmm-card__barlabel { position: absolute; left: 0; right: 0; top: calc(154 * var(--u)); font-size: calc(10 * var(--u)); font-weight: 700; }
.mmm-card__foot { position: absolute; left: 0; right: 0; bottom: calc(8 * var(--u)); font-size: calc(14 * var(--u)); font-weight: 700; }
.mmm-card__note { position: absolute; left: 6%; right: 6%; bottom: calc(6 * var(--u)); font-size: calc(10 * var(--u)); color: var(--mmm-muted); }
.mmm-badge {
  position: absolute; z-index: 4; width: calc(56 * var(--u)); text-align: center; line-height: 1; padding-top: calc(4 * var(--u));
  background: var(--t); border: calc(2 * var(--u)) solid #000; border-radius: calc(7 * var(--u)); color: var(--mmm-ink);
}
.mmm-dark .mmm-badge { border-color: #000; color: #1b2a31; }
.mmm-badge b { display: block; font-size: calc(14 * var(--u)); font-weight: 700; }
.mmm-badge span { display: block; font-size: calc(20 * var(--u)); font-weight: 300; margin-top: calc(1 * var(--u)); }
.mmm-badge--last { left: calc(-17 * var(--u)); top: calc(-21 * var(--u)); height: calc(44 * var(--u)); }
.mmm-badge--last.mmm-badge--right { left: auto; right: calc(-17 * var(--u)); }
.mmm-card .mmm-manual-tag { top: auto; right: auto; left: 50%; bottom: calc(-12 * var(--u)); transform: translateX(-50%); }
.mmm-card.is-compact .mmm-card__title { top: calc(16 * var(--u)); }
.mmm-card.is-compact .mmm-card__big { top: calc(60 * var(--u)); font-size: calc(42 * var(--u)); }
.mmm-card.is-compact .mmm-card__pct { top: calc(109 * var(--u)); }
.mmm-card.is-compact .mmm-card__bar { top: calc(140 * var(--u)); }
.mmm-badge--goal { right: calc(-28 * var(--u)); bottom: calc(-27 * var(--u)); height: calc(50 * var(--u)); padding-top: calc(7 * var(--u)); }
.mmm-badge--goal.mmm-badge--top { bottom: auto; top: calc(-21 * var(--u)); right: calc(-17 * var(--u)); height: calc(44 * var(--u)); padding-top: calc(4 * var(--u)); }
</style>

<studio>
description: "A key-number card - the big number, how far it is toward the goal, and the Last and Goal badges. Live from the weekly plans (or typed, marked Manual)."
category: GFM data
snippet: '<MmmCard x="55" y="100" w="190" h="190" tone="green" title="Friends Found" :query=''{"measures":["friends_found.actual","friends_found.previous_goal"],"weeks":4}'' />'
props:
  title:
    label: Title
  tone:
    label: Colour
    options:
      - green
      - amber
      - red
      - cyan
  mode:
    label: What it shows
    options:
      - goal
      - share
      - period
      - manual
  placeholder:
    label: Mark as typed by hand (Manual tag)
</studio>
