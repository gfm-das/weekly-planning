<script setup lang="ts">
/**
 * MmmFrame - the page of the Monday Morning Meeting (MMM), zone conference (ZOKO) and Stake coordination decks: the
 * pale page with two soft round shapes in the corners, the underlined heading and the footer line
 * "Supporting Missionaries in Faith, Hope, & Charity:" with the scripture on the right. Put it first on a slide that
 * uses layout: gfm-freeform and place the pieces (MmmCard, MmmGauge, MmmTrend, MmmTable, MmmManual, MmmSlot) in it.
 *
 * Sizes are measured in "u": 1 u is 1/1152 of the slide's width, so a piece placed at x="55" y="100" sits where the
 * same piece sat on the 1152 x 648 picture of the reference presentation. The frame is a size container, so the
 * pieces scale with the slide on screen, in the presenter view and in the PDF.
 */
withDefaults(defineProps<{
  heading?: string
  tone?: 'green' | 'cyan' | 'red' | 'amber'
  heading2?: string
  tone2?: 'green' | 'cyan' | 'red' | 'amber'
  x2?: number
  dark?: boolean
  corners?: 'a' | 'b' | 'c'
  footerLead?: string
  footerFaith?: string
  footerHope?: string
  footerCharity?: string
  verse?: string
  noFooter?: boolean
}>(), {
  heading: '',
  tone: 'green',
  heading2: '',
  tone2: 'cyan',
  x2: 750,
  dark: false,
  corners: 'a',
  footerLead: 'Supporting Missionaries in',
  footerFaith: 'Faith,',
  footerHope: 'Hope,',
  footerCharity: '& Charity:',
  verse: 'Moroni 10: 20-21',
  noFooter: false,
})
</script>

<template>
  <div class="mmm-frame" :class="[`mmm-corners-${corners}`, `mmm-tone-${tone}`, { 'mmm-dark': dark }]">
    <div class="mmm-shape mmm-shape--one" />
    <div class="mmm-shape mmm-shape--two" />
    <div v-if="heading" class="mmm-heading" :class="`mmm-tone-${tone}`" :style="{ left: 'calc(35 * var(--u))' }">{{ heading }}</div>
    <div v-if="heading2" class="mmm-heading" :class="`mmm-tone-${tone2}`" :style="{ left: `calc(${x2} * var(--u))` }">{{ heading2 }}</div>
    <slot />
    <div v-if="!noFooter" class="mmm-footer">
      <span class="mmm-footer__lead">{{ footerLead }} <span class="mmm-c-green">{{ footerFaith }}</span> <span class="mmm-c-red">{{ footerHope }}</span> <span class="mmm-c-cyan">{{ footerCharity }}</span></span>
      <span class="mmm-footer__verse">{{ verse }}</span>
    </div>
  </div>
</template>

<style>
/* The palette of the reference presentations. */
.mmm-frame {
  --u: calc(100cqw / 1152);
  --mmm-ink: #2d505e;
  --mmm-page: #f6f7f9;
  --mmm-card: #ffffff;
  --mmm-line: #000000;
  --mmm-green: #4da580;
  --mmm-green-tint: #c5e3d1;
  --mmm-amber: #ffa90a;
  --mmm-amber-tint: #fff0b8;
  --mmm-red: #b71c1c;
  --mmm-red-tint: #f5c6c1;
  --mmm-cyan: #4dd0e1;
  --mmm-cyan-tint: #b2ebf2;
  --mmm-yellow: #ffe600;
  --mmm-blue: #1f6fd1;
  --mmm-grid: #d9dde2;
  --mmm-muted: #8a9aa3;
  --mmm-shape-green: #b7d9cc;
  --mmm-shape-blue: #d9eaf8;
  --mmm-shape-pink: #ffa5a2;
  position: absolute;
  inset: 0;
  container-type: inline-size;
  overflow: hidden;
  background: var(--mmm-page);
  color: var(--mmm-ink);
  font-family: Montserrat, "Segoe UI", Inter, system-ui, -apple-system, sans-serif;
  font-size: calc(16 * var(--u));
  line-height: 1.25;
  box-sizing: border-box;
  border: 1px solid #555;
}
.mmm-frame *, .mmm-frame *::before, .mmm-frame *::after { box-sizing: border-box; }
.mmm-frame.mmm-dark {
  --mmm-ink: #f1f3f5;
  --mmm-page: #2b2b2b;
  --mmm-card: #333333;
  --mmm-line: #8c8c8c;
  --mmm-grid: #4a4a4a;
  --mmm-muted: #b7b7b7;
  border-color: #111;
}
.mmm-tone-green { --mmm-accent: var(--mmm-green); --mmm-accent-tint: var(--mmm-green-tint); }
.mmm-tone-cyan { --mmm-accent: var(--mmm-cyan); --mmm-accent-tint: var(--mmm-cyan-tint); }
.mmm-tone-red { --mmm-accent: var(--mmm-red); --mmm-accent-tint: var(--mmm-red-tint); }
.mmm-tone-amber { --mmm-accent: var(--mmm-amber); --mmm-accent-tint: var(--mmm-amber-tint); }

/* The two soft round shapes in the corners (a different pair for each variant, like the reference slides). */
.mmm-shape { position: absolute; border-radius: 50%; pointer-events: none; }
.mmm-corners-a .mmm-shape--one { right: calc(-130 * var(--u)); top: calc(-215 * var(--u)); width: calc(480 * var(--u)); height: calc(480 * var(--u)); background: var(--mmm-shape-green); }
.mmm-corners-a .mmm-shape--two { left: calc(-180 * var(--u)); bottom: calc(-150 * var(--u)); width: calc(330 * var(--u)); height: calc(330 * var(--u)); background: var(--mmm-shape-green); }
.mmm-corners-b .mmm-shape--one { right: calc(-130 * var(--u)); top: calc(-215 * var(--u)); width: calc(480 * var(--u)); height: calc(480 * var(--u)); background: var(--mmm-shape-blue); }
.mmm-corners-b .mmm-shape--two { left: calc(-180 * var(--u)); bottom: calc(-150 * var(--u)); width: calc(330 * var(--u)); height: calc(330 * var(--u)); background: var(--mmm-shape-blue); }
.mmm-corners-c .mmm-shape--one { right: calc(-130 * var(--u)); top: calc(-215 * var(--u)); width: calc(480 * var(--u)); height: calc(480 * var(--u)); background: var(--mmm-shape-pink); }
.mmm-corners-c .mmm-shape--two { left: calc(-180 * var(--u)); bottom: calc(-150 * var(--u)); width: calc(330 * var(--u)); height: calc(330 * var(--u)); background: var(--mmm-shape-pink); }
.mmm-dark .mmm-shape { display: none; }

.mmm-heading {
  position: absolute;
  top: calc(36 * var(--u));
  font-family: Impact, Haettenschweiler, "Arial Narrow Bold", "Arial Black", sans-serif;
  font-size: calc(30 * var(--u));
  line-height: 1.1;
  text-decoration: underline;
  text-decoration-thickness: calc(2.5 * var(--u));
  text-underline-offset: calc(2 * var(--u));
  color: var(--mmm-accent);
  white-space: nowrap;
  z-index: 3;
}

.mmm-footer {
  position: absolute;
  left: calc(35 * var(--u));
  right: calc(35 * var(--u));
  bottom: calc(10 * var(--u));
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  gap: calc(20 * var(--u));
  font-size: calc(17 * var(--u));
  font-weight: 700;
  color: var(--mmm-ink);
  z-index: 3;
}
.mmm-c-green { color: var(--mmm-green); }
.mmm-c-red { color: var(--mmm-red); }
.mmm-c-cyan { color: var(--mmm-cyan); }
.mmm-dark .mmm-c-red { color: #ff6b6b; }

/* Every placed piece: a box at x, y, w, h (u). */
.mmm-box { position: absolute; z-index: 2; }
.mmm-panel {
  background: var(--mmm-card);
  border: calc(2 * var(--u)) solid var(--mmm-line);
  border-radius: calc(9 * var(--u));
}
.mmm-hint { color: var(--mmm-muted); }
.mmm-message { position: absolute; inset: 0; display: flex; align-items: center; justify-content: center; text-align: center; padding: calc(12 * var(--u)); color: var(--mmm-muted); font-size: calc(14 * var(--u)); }
/* A hand-typed place, so nobody mistakes it for a live number: a small dashed tag. */
.mmm-manual-tag {
  position: absolute; right: calc(6 * var(--u)); top: calc(4 * var(--u)); z-index: 5;
  font-size: calc(10 * var(--u)); font-weight: 700; letter-spacing: 0.08em; text-transform: uppercase;
  color: #8a5a00; background: #fff3cd; border: calc(1.2 * var(--u)) dashed #c9a227; border-radius: calc(4 * var(--u)); padding: calc(1 * var(--u)) calc(5 * var(--u));
}
@media print { .mmm-manual-tag { display: none; } }
[dir="rtl"] .mmm-footer { flex-direction: row-reverse; }
/* Numbers and references keep their own left-to-right order inside a right-to-left slide (Arabic, Persian). */
.mmm-footer__verse, .mmm-card__big, .mmm-card__pct, .mmm-badge span, .mmm-gauge__num, .mmm-gauge__change, .mmm-gauge__end, .mmm-pair__box, .mmm-table__row span, .mmm-chip { unicode-bidi: isolate; direction: ltr; }
</style>

<studio>
description: "The page of the Monday Morning Meeting, zone conference and Stake coordination presentations - pale page, soft corner shapes, underlined heading and the footer line. Place the other Mmm pieces inside it."
category: GFM content
snippet: '<MmmFrame heading="Key Indicators of Conversion" tone="green"></MmmFrame>'
props:
  heading:
    label: Heading
  tone:
    label: Colour of the heading
    options:
      - green
      - cyan
      - red
      - amber
  dark:
    label: Dark page (Stake coordination)
  corners:
    label: Corner shapes
    options:
      - a
      - b
      - c
</studio>
