# GFM AI PRESENTATION SPEC v1

How to write a complete **GFM Slidev presentation** that GFM Studio can import (Paste Presentation) and then edit visually.
This file is made from the layouts and components themselves (`slidev/tools/make-ai-spec.mjs`); do not edit it by hand.

## Output rules

- Return **only** the complete `slides.md`, as plain text. No explanations before or after it. Do not wrap it in a code fence.
- Slides are separated by a line with three dashes (`---`). The first block is the deck's settings (the headmatter), and it is also the first slide's settings.
- Use the layouts and components below. Prefer them to hand-written HTML: they look right without styling and stay editable in Studio.
- Do **not** import packages, add `<script>` blocks, load external scripts, use `<iframe>`, inline event handlers (`onclick=`) or `javascript:` links. Do not call `fetch`, `eval`, `localStorage` or `document.cookie`.
- Do not invent components, layouts or settings. Anything not listed here may be refused or shown as an error.
- Pictures: use files the deck already has (a path such as `/photo.jpg`); do not link to other websites for pictures.
- Write for a video call: a few words per slide, one idea each. Add speaker notes as an HTML comment at the end of a slide (`<!-- … -->`).
- Numbers: never invent mission numbers. Use the live components (`GfmKpiGrid`, `GfmKpi`) for key indicators, or mark an example value clearly (for example "example: 12").

## The first block (headmatter)

```yaml
---
theme: default
title: Weekly review
layout: gfm-cover
kicker: Germany Frankfurt Mission
fonts:
  provider: none
  sans: Inter
transition: fade
---
```

Use `theme: default` (the only theme installed). Slide settings such as `layout` go in the block at the top of each slide:

```
---
layout: gfm-section
kicker: Part 2
---

# Looking ahead
```

Slidev keeps some setting names for itself and never hands them to a layout: `title`, `level`, `src`, `lang`, `hide`, `layout`, `transition`, `clicks`. A GFM layout's heading is the setting `heading` (a slide written with `title:` also works).

## Layouts

Slidev's own layouts that may be used: `default`, `center`, `cover`, `end`, `fact`, `full`, `iframe`, `iframe-left`, `iframe-right`, `image`, `image-left`, `image-right`, `intro`, `none`, `quote`, `section`, `statement`, `two-cols`, `two-cols-header`.

### `gfm-chart-insight`

A chart on the left and what it means on the right. Put the chart first, then a line with ::right:: and the message.

Parts of the slide: the main text, then `::right::` on a line of its own to start each further part.

Settings: `heading`, `kicker`.

### `gfm-comparison`

Two things side by side, such as this week and last week, or two zones. Put the first, then a line with ::right:: and the second.

Parts of the slide: the main text, then `::right::` on a line of its own to start each further part.

Settings: `heading`, `kicker`, `leftTitle`, `rightTitle`.

### `gfm-cover`

Opening slide. A big title (a # heading), a line under it, a small label above and a footer line.

Settings: `kicker`, `footer`.

### `gfm-freeform`

A blank slide for placing things freely - drag, resize and rotate anything. Use it when no other layout fits.

### `gfm-full-chart`

One chart, as large as the slide allows, with a title and an optional source line. Put a chart (height about 360) in the slide.

Settings: `heading`, `kicker`, `caption`.

### `gfm-hero`

One message, large and centred - a statement, a big number or a question for the whole group.

Settings: `kicker`.

### `gfm-image-message`

A picture beside a message. The picture fills one side of the slide; the text sits on the other.

Settings: `image`, `imageSide` (left | right), `kicker`.

### `gfm-kpi-grid`

A set of key numbers. Put a GfmKpiGrid (the mission's key indicators) or several GfmBigNumber in the slide.

Settings: `heading`, `kicker`, `note`.

### `gfm-section`

Starts a new part of the presentation. A big heading on a teal background, with an optional label such as "Part 2".

Settings: `kicker`.

### `gfm-three-column`

Three equal cards, each with a heading and a few lines. Separate the cards with ::middle:: and ::right::.

Parts of the slide: the main text, then `::middle::`, `::right::` on a line of its own to start each further part.

Settings: `heading`, `kicker`.

### `gfm-two-chart`

Two charts side by side (height about 300 each). Put the first chart, then a line with ::right:: and the second.

Parts of the slide: the main text, then `::right::` on a line of its own to start each further part.

Settings: `heading`, `kicker`.

## Components

Slidev's own components that may be used: `Arrow`, `AutoFitText`, `Link`, `RenderWhen`, `SlideCurrentNo`, `SlidesTotal`, `Toc`, `Transform`, `Tweet`, `Youtube`, `VClick`, `VClicks`, `VAfter`, `VSwitch`, `VDrag`, `VDragArrow`, `SlidevVideo`, `LightOrDark`.

### `GfmBigNumber`

One number shown large, with its label, the change from before and a short note.

Settings: `value`, `label`, `change`, `tone` (good | warn | bad | neutral), `note`.

```
<GfmBigNumber value="47" label="New people being taught" change="+6 from last week" tone="good" />
```

### `GfmCallout`

A box that points something out - an invitation, a reminder or a warning - with a small heading.

Settings: `title`, `tone` (info | good | warn | bad).

```
<GfmCallout title="Invitation" tone="info">
Invite one friend this week.
</GfmCallout>
```

### `GfmComparison`

Two numbers side by side with the change between them - this week and last week, or two zones.

Settings: `leftLabel`, `leftValue`, `rightLabel`, `rightValue`, `unit`.

```
<GfmComparison leftLabel="Last week" :leftValue="41" rightLabel="This week" :rightValue="47" />
```

### `GfmInsight`

What the numbers mean, in one or two sentences, set apart with a teal bar.

Settings: `label`.

```
<GfmInsight>
Most zones taught more people than last week.
</GfmInsight>
```

### `GfmKpi`

One key indicator of the mission as a tile - the last finished week against the goal set the week before, with a small line of the weeks. Live from the weekly plans.

Settings: `weeks`, `height`, `highlight`.

```
<GfmKpi metric="New people being taught" />
```

### `GfmKpiGrid`

Key indicators of the mission as a grid of tiles, live from the weekly plans. Choose which ones, how many weeks the small lines show, and whether the first is outlined.

Settings: `metrics`, `weeks`, `columns`, `highlightFirst`.

```
<GfmKpiGrid metrics="friends_found,baptismal_dates,sacrament_attendance" />
```

### `GfmProgress`

How far along a goal is: a bar with the numbers and the percentage.

Settings: `label`, `value`, `goal`, `unit`.

```
<GfmProgress label="Baptismal dates" :value="31" :goal="40" />
```

### `GfmQuote`

A quotation or scripture, large, with the source underneath.

Settings: `author`.

```
<GfmQuote author="Alma 37:6">
By small and simple things are great things brought to pass.
</GfmQuote>
```

### `MissionChart`

A chart from your own numbers or from mission numbers, drawn with ECharts. Use Add chart at the top of the editor to make one, and Edit chart to change the selected chart (every chart type, the numbers, and every setting). The settings below are for charts written the older way.

```
<MissionChart :rows="['Label, Value', 'A, 3', 'B, 5', 'C, 4']" :option='{"series":[{"type":"bar"}]}' />
```

### `MissionKpiChart`

Live mission numbers for one key indicator, week by week, with the goal and a trend line. The first settings are the everyday ones; the ones marked More fine-tune the chart.

Settings: `weeks`, `chart` (bar | line | area | tile), `showGoal`, `trend` (linear | polynomial | exponential | logarithmic | moving-average | none), `degree`, `trendColor`, `colors`, `goalColor`, `title`, `height`, `showValues`, `trendStyle` (dashed | dotted | solid), `trendWidth`, `trendLabel`, `window`, `forecast`, `target`, `targetLabel`, `targetColor`, `average`, `averageColor`, `legend` (auto | top | bottom | right | none), `yMin`, `yMax`, `smooth`, `valuePosition` (auto | top | inside | bottom), `dataZoom`.

```
<MissionKpiChart kpi="New people being taught" :weeks="12" chart="bar" trend="linear" />
```

## Charts (`MissionChart`)

A chart is its numbers plus a chart kind. Write the numbers as rows (the first row holds the headings, the first column the labels):

```
<MissionChart chart-id="trend1" preset="trend" :height="330"
  :rows="['Week, New people being taught', 'Aug 3, 12', 'Aug 10, 15', 'Aug 17, 14']" />
```

- `chart-id`: a short unique name for each chart (letters and digits).
- `height`: slide pixels (a slide is 980 wide); 300 to 360 fits under a heading.
- Mission numbers from the weekly plans can only be added with **Add chart** in GFM Studio; do not write a `query` yourself.

### Chart kinds (`preset`)

Curated kinds: `trend` (weeks), `goal-vs-actual` (goal), `ranked-bar` (units), `comparison` (two numbers), `big-number` (one number), `progress` (goal), `cumulative-goal` (weeks), `funnel` (several numbers), `conversion-funnel` (several numbers), `leaderboard` (units), `small-multiples` (several numbers).

Every chart type, as `type-<name>`: `type-line`, `type-area`, `type-stacked-area`, `type-bar`, `type-stacked-bar`, `type-horizontal-bar`, `type-scatter`, `type-effect-scatter`, `type-pictorial-bar`, `type-pie`, `type-donut`, `type-gauge`, `type-radar`, `type-heatmap`, `type-matrix-heatmap`, `type-calendar-heatmap`, `type-treemap`, `type-sunburst`, `type-boxplot`, `type-candlestick`, `type-waterfall`, `type-range`, `type-errorbar`, `type-tree`, `type-graph`, `type-sankey`, `type-chord`, `type-theme-river`, `type-parallel`, `type-polar-bar`.

### Calculated fields (`calc`)

```
:calc='[{"name":"Successful Contact Rate","formula":"[Successfully Contacted] / [Referrals Received]","format":"percent"}]'
```

Formats: `number`, `percent`, `integer`, `compact`, `decimals`. Formulas use a field's name in square brackets, `+ - * / % ^`, comparisons, `AND OR NOT` and these functions:

- `SUM(column) or SUM(a, b, ...)`: One column: the total of all rows. Several values: their sum, row by row.
- `AVG(column) or AVG(a, b, ...)`: One column: the average of all rows. Several values: their average, row by row.
- `MIN(column) or MIN(a, b, ...)`: One column: the lowest row. Several values: the lowest, row by row.
- `MAX(column) or MAX(a, b, ...)`: One column: the highest row. Several values: the highest, row by row.
- `COUNT(column)`: How many rows have a number.
- `IF(test, then, otherwise)`: Gives "then" where the test is true and "otherwise" where it is not.
- `SAFE_DIVIDE(a, b, instead)`: a divided by b; where b is 0 or missing it gives "instead" (no number if you leave it out).
- `DIFFERENCE(column, rows back)`: The change from the row before (or from that many rows back).
- `PERCENT_CHANGE(column, rows back)`: The change from the row before as a fraction of it: (this - before) / before.
- `CUMULATIVE_SUM(column)`: The running total from the first row to this one.
- `MOVING_AVG(column, rows)`: The average of this row and the rows before it (up to that many rows).
- `LAG(column, rows back)`: The value from the row before (or that many rows back).
- `ROUND(value, decimals)`: Rounds to that many decimals (0 if you leave it out).
- `ABS(value)`: Removes a minus sign.

### Which numbers show (`shape`)

```
:shape='{"only":["Received","Attempted"],"sort":"desc","top":5}'
```

### Data stories (`story`)

One chart that changes with each click. Each step may change: `label`, `preset`, `presetTop`, `presetAggregate`, `presetTarget`, `shape`, `calc`, `title`, `colors`, `option`.

```
<MissionChart chart-id="story1" preset="trend" :rows="[…]"
  :story='[{"label":"Received","shape":{"only":["Received"]}},{"label":"All","shape":{}}]'
  storyTransition="morph" :storyDuration="700" />
```

`storyTransition`: `morph`, `fade`, `none`. `storyEasing`: `cubicInOut`, `cubicOut`, `linear`, `elasticOut`, `backOut`.

## Animation

Reveal items one click at a time with Slidev's `<v-clicks>` (around a list) or `v-click` on an element. A story chart brings its own clicks.

## Mission key indicators

Use these names or ids with `GfmKpi` / `GfmKpiGrid`:

- `New people being taught` (`friends_found`)
- `Baptisms and confirmations` (`baptisms_confirmations`)
- `Baptismal dates` (`baptismal_dates`)
- `Sacrament attendance` (`sacrament_attendance`)
- `Members at lessons` (`members_at_lessons`)
- `New member sacrament attendance` (`new_member_sacrament`)

## Patterns that work

1. Cover (`gfm-cover`) → this week at a glance (`gfm-kpi-grid` with `<GfmKpiGrid />`) → one chart with its meaning (`gfm-chart-insight`) → three focuses (`gfm-three-column`) → a question for the group (`gfm-hero`).
2. A comparison slide (`gfm-comparison` with two `GfmBigNumber`) before a ranked chart (`preset="ranked-bar"`).
3. Close with `gfm-hero` and one invitation.
