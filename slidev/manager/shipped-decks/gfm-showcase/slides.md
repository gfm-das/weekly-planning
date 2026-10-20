---
theme: default
title: Everything a deck can do
info: |
  The showcase deck of the Presentation Library: every chart type, every chart kind and every way to bring a
  slide to life, with made-up numbers and names (Elder Sample and friends). Duplicate it to experiment.
layout: gfm-cover
kicker: Presentation Library showcase
footer: Made-up numbers and names only
colorSchema: auto
fonts:
  provider: none
  sans: Inter
  mono: Cascadia Mono, Consolas
transition: fade
---

# Everything a deck can do

Every chart, every trick, one deck. Press <kbd>→</kbd> or click to begin.

<!--
Welcome! This deck shows what Presentations can do. Every number and name in it is made up.
Open the presenter view (the ⋯ menu at the bottom left, or press P) to see these notes, the next slide and a timer.
-->

---
layout: gfm-three-column
title: "How to drive this deck"
kicker: "Before we start"
---

## Move
<kbd>→</kbd> <kbd>Space</kbd> next step · <kbd>←</kbd> back · <kbd>O</kbd> all slides · <kbd>F</kbd> full screen

::middle::

## Present
**Presenter view** (<kbd>P</kbd> or the ⋯ menu): your notes, the next slide and a **timer** with a reset button. **Screen Mirror** shows the projector beside it.

::right::

## Draw and share
<kbd>D</kbd> opens the **pen**: draw, highlight, erase while you talk. **Download PDF** in the library's ⋮ menu prints one page per slide (charts included).

<!--
Try P now: the presenter view opens in a new window. The timer starts when the window opens; click it to pause or reset.
-->

---
layout: gfm-section
kicker: "Part 1"
---

# Charts from your own numbers

Type or paste a table, choose a type. No database needed.

---
layout: gfm-full-chart
title: "Line: a trend over time"
kicker: "Charts"
caption: "Use it for anything week by week. Here with a linear trend line and a 3-week forecast band."
---

<MissionChart chart-id="line" :rows="['Week, Taught, Goal', 'W1, 31, 22', 'W2, 36, 28', 'W3, 33, 26', 'W4, 41, 35', 'W5, 47, 42', 'W6, 44, 35', 'W7, 52, 44', 'W8, 55, 48']" :option='{"series":[{"type":"line","smooth":true,"gfm":{"trend":{"method":"linear","forecast":3}}},{"type":"line","lineStyle":{"type":"dashed"}}]}' :height="330" />

<!--
Trend methods: linear, polynomial (with a degree), exponential, logarithmic, moving average.
-->

---
layout: gfm-two-chart
title: "Area and stacked area"
kicker: "Charts · when the size of the total matters"
---

<MissionChart chart-id="area" :rows="['Week, Taught', 'W1, 31', 'W2, 36', 'W3, 33', 'W4, 41', 'W5, 47', 'W6, 44', 'W7, 52', 'W8, 55']" :option='{"series":[{"type":"line","areaStyle":{}}]}' :height="300" />

::right::

<MissionChart chart-id="stacked-area" :rows="['Week, North, South, East', 'W1, 31, 22, 13', 'W2, 36, 28, 20', 'W3, 33, 26, 19', 'W4, 41, 35, 24', 'W5, 47, 42, 32', 'W6, 44, 35, 26', 'W7, 52, 44, 36', 'W8, 55, 48, 41']" :option='{"series":[{"type":"line","stack":"all","areaStyle":{}}]}' :height="300" />

<!--
Area shows volume; stacked area shows how parts add up to the whole.
-->

---
layout: gfm-two-chart
title: "Bars: side by side, stacked, horizontal"
kicker: "Charts"
---

<MissionChart chart-id="bar" :rows="['Week, North, South', 'W1, 31, 22', 'W2, 36, 28', 'W3, 33, 26', 'W4, 41, 35', 'W5, 47, 42', 'W6, 44, 35', 'W7, 52, 44', 'W8, 55, 48']" :option='{"series":[{"type":"bar"}]}' :height="300" />

::right::

<MissionChart chart-id="hbar" :rows="['Zone, Taught', 'Frankfurt, 47', 'Mannheim, 39', 'Wiesbaden, 33', 'Darmstadt, 28', 'Mainz, 22']" :option='{"yAxis":{"type":"category"},"xAxis":{"type":"value"},"series":[{"type":"bar","encode":{"y":"Zone","x":"Taught"}}]}' :height="300" />

<!--
Bars compare amounts. Horizontal bars are best when the labels are long.
-->

---
layout: gfm-two-chart
title: "Pie and donut"
kicker: "Charts"
---

<MissionChart chart-id="pie" :rows="['Source, Friends', 'Members, 18', 'Own finding, 12', 'Online, 9', 'Service, 5']" :option='{"series":[{"type":"pie"}]}' :height="300" />

::right::

<MissionChart chart-id="donut" :rows="['Source, Friends', 'Members, 18', 'Own finding, 12', 'Online, 9', 'Service, 5']" :option='{"series":[{"type":"pie","radius":["45%","72%"]}]}' :height="300" />

<!--
Parts of one whole. Keep it to five or six slices.
-->

---
layout: gfm-two-chart
title: "Scatter and effect scatter"
kicker: "Charts"
---

<MissionChart chart-id="scatter" :rows="['Lessons, Baptismal dates', '4, 1', '6, 2', '8, 2', '9, 3', '11, 4', '13, 4', '15, 6']" :option='{"xAxis":{"type":"value"},"series":[{"type":"scatter","symbolSize":14,"gfm":{"trend":{"method":"linear"}}}]}' :height="300" />

::right::

<MissionChart chart-id="effect" :rows="['Lessons, Baptismal dates', '4, 1', '8, 2', '11, 4', '15, 6']" :option='{"xAxis":{"type":"value"},"series":[{"type":"effectScatter","symbolSize":16}]}' :height="300" />

<!--
Scatter shows whether two numbers move together. Effect scatter makes a few points pulse for attention.
-->

---
layout: gfm-full-chart
title: "Pictorial bar"
kicker: "Charts"
caption: "A bar drawn with symbols: playful for a small, countable number."
---

<MissionChart chart-id="picto" :rows="['Zone, Baptisms', 'Frankfurt, 6', 'Mannheim, 4', 'Wiesbaden, 3']" :option='{"yAxis":{"type":"category"},"xAxis":{"type":"value"},"series":[{"type":"pictorialBar","symbol":"circle","symbolRepeat":true,"symbolSize":22,"encode":{"y":"Zone","x":"Baptisms"}}]}' :height="300" />

---
layout: gfm-chart-insight
title: "Gauge and key number"
kicker: "Chart and insight"
---

<MissionChart chart-id="gauge" :rows="['Measure, Value, Max', 'Baptismal dates, 31, 40']" :option='{"series":[{"type":"gauge"}]}' :height="300" />

::right::

<GfmBigNumber value="47" label="New people being taught" change="+6 from last week" tone="good" />

<GfmProgress label="Baptismal dates" :value="31" :goal="40" />

<!--
A gauge or a progress bar shows how close a goal is. A big number is the one thing to remember.
-->

---
layout: gfm-two-chart
title: "Radar and funnel"
kicker: "Charts"
---

<MissionChart chart-id="radar" :rows="['Key indicator, North, South', 'Taught, 96, 82', 'Baptismal dates, 70, 88', 'Church, 85, 64', 'Member lessons, 60, 75', 'Baptisms, 50, 66']" :option='{"series":[{"type":"radar","areaStyle":{"opacity":0.2}}]}' :height="300" />

::right::

<MissionChart chart-id="funnel" :rows="['Step, People', 'Taught, 120', 'Came to church, 74', 'Lesson with a member, 41', 'Baptismal date, 18', 'Baptized, 9']" :option='{"series":[{"type":"funnel"}]}' :height="300" />

<!--
Radar compares a few groups on several measures. A funnel shows how many make it from step to step.
-->

---
layout: gfm-two-chart
title: "Heat maps: a grid and a calendar"
kicker: "Charts"
---

<MissionChart chart-id="heat" :rows="['Week, North, South, East, West', 'W1, 5, 3, 4, 6', 'W2, 7, 4, 3, 5', 'W3, 6, 6, 5, 7', 'W4, 9, 5, 6, 8']" :option='{"series":[{"type":"heatmap"}]}' :height="300" />

::right::

<MissionChart chart-id="cal" :rows="['Day, Lessons', '2026-09-01, 3', '2026-09-02, 5', '2026-09-03, 2', '2026-09-07, 6', '2026-09-09, 4', '2026-09-14, 7', '2026-09-16, 3', '2026-09-21, 8', '2026-09-24, 5', '2026-09-28, 6']" :option='{"calendar":{"range":"2026-09"},"series":[{"type":"heatmap","coordinateSystem":"calendar"}]}' :height="300" />

<!--
Brighter squares are bigger numbers: spot the busy weeks or days at a glance.
-->

---
layout: gfm-two-chart
title: "Tree map and sunburst"
kicker: "Charts"
---

<MissionChart chart-id="treemap" :rows="['Area, Friends', 'North / Frankfurt 1, 12', 'North / Frankfurt 2, 9', 'North / Offenbach, 7', 'South / Mannheim, 10', 'South / Heidelberg, 6']" :option='{"series":[{"type":"treemap"}]}' :height="300" />

::right::

<MissionChart chart-id="sunburst" :rows="['Area, Friends', 'North / Frankfurt 1, 12', 'North / Frankfurt 2, 9', 'North / Offenbach, 7', 'South / Mannheim, 10', 'South / Heidelberg, 6']" :option='{"series":[{"type":"sunburst"}]}' :height="300" />

<!--
Zone / district / area: the size of each box is its share. Write the levels with a slash.
-->

---
layout: gfm-two-chart
title: "Box plot and candlestick"
kicker: "Charts"
---

<MissionChart chart-id="box" :rows="['Week, North, South, East', 'W1, 5, 3, 4', 'W2, 7, 4, 3', 'W3, 6, 6, 5', 'W4, 9, 5, 6', 'W5, 4, 8, 7', 'W6, 8, 2, 5']" :option='{"series":[{"type":"boxplot"}]}' :height="300" />

::right::

<MissionChart chart-id="candle" :rows="['Week, Open, Close, Low, High', 'W1, 30, 34, 28, 36', 'W2, 34, 31, 29, 37', 'W3, 31, 38, 30, 40', 'W4, 38, 42, 35, 44']" :option='{"series":[{"type":"candlestick"}]}' :height="300" />

<!--
Box plot: the spread of many weeks. Candlestick: where a week started, ended and its lowest and highest point.
-->

---
layout: gfm-two-chart
title: "Waterfall and error bars"
kicker: "Charts"
---

<MissionChart chart-id="waterfall" :rows="['Step, Change', 'Last month, 120', 'New, 18', 'Moved in, 6', 'Moved away, -9', 'Total, 0']" :option='{"series":[{"type":"custom","renderItem":"waterfall"}]}' :height="300" />

::right::

<MissionChart chart-id="errorbar" :rows="['Zone, Average, Low, High', 'North, 12, 9, 15', 'South, 10, 6, 13', 'East, 8, 7, 11']" :option='{"series":[{"type":"custom","renderItem":"errorbar"}]}' :height="300" />

<!--
A waterfall explains how one number became another. Error bars show a range around each value.
-->

---
layout: gfm-two-chart
title: "Sankey and chord"
kicker: "Charts"
---

<MissionChart chart-id="sankey" :rows="['From, To, People', 'Members, Taught, 18', 'Own finding, Taught, 12', 'Online, Taught, 9', 'Taught, Baptismal date, 14', 'Taught, Still learning, 25']" :option='{"series":[{"type":"sankey"}]}' :height="300" />

::right::

<MissionChart chart-id="chord" :rows="['From, To, Referrals', 'North, South, 6', 'South, East, 4', 'East, North, 5', 'North, East, 3']" :option='{"series":[{"type":"chord"}]}' :height="300" />

<!--
Flows: where people came from and where they went.
-->

---
layout: gfm-two-chart
title: "Network graph and tree"
kicker: "Charts"
---

<MissionChart chart-id="graph" :rows="['From, To, Visits', 'Elder Sample, Sister Example, 3', 'Sister Example, Elder Demo, 2', 'Elder Demo, Elder Sample, 4', 'Sister Test, Elder Demo, 1']" :option='{"series":[{"type":"graph","layout":"force","roam":true}]}' :height="300" />

::right::

<MissionChart chart-id="tree" :rows="['Unit, Missionaries', 'Mission / North / Frankfurt 1, 2', 'Mission / North / Frankfurt 2, 2', 'Mission / South / Mannheim, 4']" :option='{"series":[{"type":"tree"}]}' :height="300" />

<!--
A graph shows who is connected to whom; a tree shows how units nest.
-->

---
layout: gfm-two-chart
title: "Theme river and parallel lines"
kicker: "Charts"
---

<MissionChart chart-id="river" :rows="['Week, North, South, East', '2026-08-02, 5, 3, 4', '2026-08-09, 7, 4, 3', '2026-08-16, 6, 6, 5', '2026-08-23, 9, 5, 6']" :option='{"series":[{"type":"themeRiver"}]}' :height="300" />

::right::

<MissionChart chart-id="parallel" :rows="['Area, Taught, Church, Dates', 'Frankfurt 1, 12, 8, 3', 'Frankfurt 2, 9, 6, 2', 'Mannheim, 10, 9, 4']" :option='{"series":[{"type":"parallel"}]}' :height="300" />

<!--
Theme river: how the mix changes over time. Parallel lines: compare areas on several measures at once.
-->

---
layout: gfm-two-chart
title: "Polar bars and small multiples"
kicker: "Charts"
---

<MissionChart chart-id="polar" :rows="['Day, Lessons', 'Mon, 4', 'Tue, 7', 'Wed, 6', 'Thu, 8', 'Fri, 5', 'Sat, 9', 'Sun, 3']" :option='{"polar":{},"angleAxis":{"type":"category"},"radiusAxis":{},"series":[{"type":"bar","coordinateSystem":"polar"}]}' :height="300" />

::right::

<MissionChart chart-id="multiples" type="line" multiples :rows="['Week, North, South, East, West', 'W1, 31, 22, 13, 4', 'W2, 36, 28, 20, 12', 'W3, 33, 26, 19, 7', 'W4, 41, 35, 24, 18', 'W5, 47, 42, 32, 22', 'W6, 44, 35, 26, 17', 'W7, 52, 44, 36, 28', 'W8, 55, 48, 41, 29']" :height="300" />

<!--
Polar bars for the days of a week; small multiples give each zone its own little chart on one scale.
-->

---
layout: gfm-section
kicker: "Part 2"
---

# Chart kinds and calculated fields

One table, many ready-made looks.

---
layout: gfm-two-chart
title: "Chart kinds: ranked bar and goal vs actual"
kicker: "Chart kinds"
---

<MissionChart chart-id="ranked" preset="ranked-bar" :rows="['Area, Taught', 'Frankfurt 1, 12', 'Mannheim, 10', 'Frankfurt 2, 9', 'Offenbach, 7', 'Heidelberg, 6']" :height="300" />

::right::

<MissionChart chart-id="goalactual" preset="goal-vs-actual" :rows="['Week, Actual, Goal', 'W1, 31, 22', 'W2, 36, 28', 'W3, 33, 26', 'W4, 41, 35', 'W5, 47, 42', 'W6, 44, 35', 'W7, 52, 44', 'W8, 55, 48']" :height="300" />

<!--
A kind chooses order, labels and how many to show. Others: trend, comparison, big-number, progress, cumulative-goal, funnel, conversion-funnel, leaderboard, small-multiples.
-->

---
layout: gfm-two-chart
title: "Chart kinds: cumulative goal and leaderboard"
kicker: "Chart kinds"
---

<MissionChart chart-id="cumulative" preset="cumulative-goal" :rows="['Week, Baptisms, Goal', 'W1, 31, 22', 'W2, 36, 28', 'W3, 33, 26', 'W4, 41, 35', 'W5, 47, 42', 'W6, 44, 35', 'W7, 52, 44', 'W8, 55, 48']" :height="300" />

::right::

<MissionChart chart-id="leader" preset="leaderboard" :rows="['Area, Lessons with a member', 'Frankfurt 1, 14', 'Mannheim, 11', 'Offenbach, 9', 'Heidelberg, 7']" :height="300" />

---
layout: gfm-full-chart
title: "A calculated field"
kicker: "Calculated fields"
caption: "Successful contact rate = Successfully contacted ÷ Referrals received, worked out inside the chart."
---

<MissionChart chart-id="calc" preset="ranked-bar" :height="330" :rows="['Zone, Referrals Received, Successfully Contacted', 'Frankfurt, 40, 30', 'Mannheim, 25, 12', 'Wiesbaden, 31, 25', 'Darmstadt, 18, 9']"
  :calc='[{"name":"Successful Contact Rate","formula":"[Successfully Contacted] / [Referrals Received]","format":"percent"}]'
  :shape='{"only":["Successful Contact Rate"]}' />

<!--
Formulas: + - * / and SUM, AVG, IF, SAFE_DIVIDE, PERCENT_CHANGE, CUMULATIVE_SUM, MOVING_AVG and more.
-->

---
layout: gfm-section
kicker: "Part 3"
---

# Bring it to life

Click steps, morphing charts, reveals and motion.

---
layout: gfm-full-chart
title: "A data story: one chart morphs into another"
kicker: "Click steps"
caption: "Click: Received → + Attempted → + Successful → the lines become bars → the bars melt into a funnel → the funnel bends into a pie. Click back and it morphs back."
---

<MissionChart chart-id="story" preset="trend" :height="330" :rows="['Week, Received, Attempted, Successful', 'W1, 12, 9, 6', 'W2, 15, 11, 7', 'W3, 14, 12, 9', 'W4, 19, 14, 10']"
  :steps='[{"label":"Received","shape":{"only":["Received"]}},{"label":"+ Attempted","shape":{"only":["Received","Attempted"]}},{"label":"+ Successful","shape":{}},{"label":"As bars","option":{"series":[{"type":"bar"},{"type":"bar"},{"type":"bar"}]}},{"label":"As a funnel","preset":"funnel","presetAggregate":"sum"},{"label":"As a pie","preset":"funnel","presetAggregate":"sum","option":{"series":[{"type":"pie","radius":["30%","70%"]}]}}]'
  :storyDuration="1000" />

<!--
One chart the whole time (ECharts universal transition): the points glide into bars, all the bars of "Received" melt into the
"Received" step of the funnel, and the funnel's steps bend into slices. Each click is one step; going back morphs back, and the
audience screen follows the presenter's clicks. Write it with :steps (a list of chart settings, one per click).
-->

---
layout: gfm-full-chart
title: "The same morph with live numbers"
kicker: "Click steps · live"
caption: "Live mission numbers for the last 6 finished weeks. Without a connection the sample numbers below are used (and the chart says so)."
---

<MissionChart chart-id="story-live" :height="330"
  :query='{"measures":["friends_found.actual","baptismal_dates.actual","baptisms_confirmations.actual"],"level":"mission","by":"week","weeks":{"last":6},"includeCurrent":false}'
  :sample="['Week, New people being taught, Baptismal dates, Baptisms and confirmations', 'W1, 41, 9, 4', 'W2, 38, 11, 5', 'W3, 45, 10, 3', 'W4, 52, 13, 6', 'W5, 47, 12, 5', 'W6, 55, 14, 7']"
  preset="trend"
  :steps='[{"label":"Lines"},{"label":"Bars","option":{"series":[{"type":"bar"},{"type":"bar"},{"type":"bar"}]}},{"label":"Funnel","preset":"funnel","presetAggregate":"sum"},{"label":"Pie","preset":"funnel","presetAggregate":"sum","option":{"series":[{"type":"pie","radius":["30%","70%"]}]}}]' />

<!--
A live query plus :sample. Leaders see their own stewardship, like every live chart.
-->

---
layout: default
---

# Reveals, one click at a time

<v-clicks>

- **Find** – every companionship invites one new friend
- **Teach** – plan each lesson together, with a member
- **Baptize** – help friends keep their baptismal date

</v-clicks>

<div v-click class="mt-8 text-xl">…and this line appears last. <span v-mark.underline.orange="4">Hand-drawn marks</span> come with a click too.</div>

<div v-motion :initial="{ x: -120, opacity: 0 }" :enter="{ x: 0, opacity: 1, transition: { delay: 300 } }" class="mt-8 p-4 rounded-xl bg-teal-600 text-white inline-block">I slide in with v-motion when the slide opens.</div>

<!--
v-click, v-clicks (each list item), v-after, v-mark (underline, circle, highlight) and v-motion animations all work.
-->

---
layout: two-cols
kicker: "Lists of names"
---

# This week's baptisms

<MissionList :rows="['Name, Zone, Area, Missionaries', 'Anna Beispiel, Frankfurt, Frankfurt 1, Elder Sample & Elder Demo', 'Jonas Muster, Mannheim, Mannheim, Sister Example & Sister Test', 'Lea Probe, Frankfurt, Offenbach, Elder Placeholder & Elder Mock', 'Noah Vorlage, Mannheim, Heidelberg, Sister Draft & Sister Trial']"
  columns="Name, Area, Missionaries" group-by="Zone" sort="Zone" reveal />

::right::

# Transfers

<MissionList :rows="['Missionary, From, To', 'Elder Sample, Frankfurt 1, Mannheim', 'Sister Example, Mainz, Wiesbaden', 'Elder Demo, Darmstadt, Frankfurt 2', 'Sister Test, Heidelberg, Mainz']" sort="Missionary" numbered />

<p class="text-sm opacity-70 mt-6">Names are typed into the slide (MissionList with rows). Live lists count by place, never by name.</p>

<!--
Each baptism appears with a click (reveal), grouped by zone. All names here are made up. Type the real ones before the meeting and delete them after.
-->

---
layout: two-cols
kicker: "Live lists"
---

# Friends found by zone

<MissionList :query='{"measures":["friends_found.actual","friends_found.previous_goal"],"level":"zone","by":"unit","weeks":{"last":4},"includeCurrent":false}'
  sort="New people being taught:desc" :limit="8" numbered
  :sample="['Zone, New people being taught, Goal', 'Frankfurt, 31, 28', 'Mannheim, 24, 26', 'Mainz, 22, 20', 'Darmstadt, 19, 22', 'Heidelberg, 17, 15', 'Wiesbaden, 15, 18']" />

::right::

# Every area, page by page

<MissionList :query='{"measures":["baptismal_dates.actual"],"level":"area","by":"unit","weeks":{"last":4},"includeCurrent":false}'
  sort="Baptismal dates:desc" :page-size="6" paging="auto" :auto-seconds="5"
  :sample="['Area, Baptismal dates', 'Frankfurt 1, 4', 'Frankfurt 2, 3', 'Mannheim, 3', 'Offenbach, 2', 'Mainz, 2', 'Wiesbaden, 2', 'Darmstadt, 1', 'Heidelberg, 1', 'Hanau, 1', 'Worms, 1', 'Bad Homburg, 0', 'Rüsselsheim, 0', 'Gießen, 0', 'Fulda, 0']" />

<!--
Live lists use the same safe path as live charts: a row per zone, district, area or week, a column per number, and only the
viewer's own stewardship. The right list turns its pages every 5 seconds (paging="click" turns them with clicks instead).
Without a connection both show their :sample rows and say so.
-->

---
layout: gfm-section
kicker: "Part 4"
---

# Live mission numbers

Charts that read the weekly plans, scoped to who is watching.

---
layout: gfm-two-chart
title: "Key indicators, live (with sample numbers beside them)"
kicker: "Live data"
---

<GfmKpiGrid metrics="friends_found,baptismal_dates,sacrament_attendance,baptisms_confirmations" :columns="2" />

::right::

<div class="grid grid-cols-2 gap-3">
<GfmBigNumber value="47" label="New people being taught (sample)" change="+6 from last week" tone="good" />
<GfmBigNumber value="31" label="Baptismal dates (sample)" change="-2 from last week" tone="warn" />
<GfmBigNumber value="118" label="Sacrament attendance (sample)" change="+4 from last week" tone="good" />
<GfmBigNumber value="9" label="Baptisms (sample)" change="on goal" tone="good" />
</div>

<!--
Left: live tiles from the weekly plans (the last finished week against the goal set the week before). Right: the same idea with typed sample numbers, which always draw. Opened outside the portal (a download, the demo), the live tiles say the numbers could not load.
-->

---
layout: gfm-two-chart
title: "A live chart, its query, and a sample answer"
kicker: "Live data"
---

<MissionKpiChart kpi="New people being taught" :weeks="12" chart="bar" trend="linear" :height="190" />

<MissionChart chart-id="live-zones" :height="170" :query='{"measures":["friends_found.actual"],"level":"zone","by":"unit","weeks":{"last":4},"includeCurrent":false}' :option='{"series":[{"type":"bar"}]}' />

::right::

```json
{ "measures": ["friends_found.actual"],
  "level": "zone", "by": "unit",
  "weeks": { "last": 4 }, "includeCurrent": false }
```

<MissionChart chart-id="sample-zones" :height="190" :rows="['Zone, New people being taught (sample)', 'Frankfurt, 47', 'Mannheim, 39', 'Wiesbaden, 33', 'Darmstadt, 28']" :option='{"series":[{"type":"bar"}]}' />

<p class="text-xs opacity-70">Left: live (made with <b>Add chart</b>; a district leader sees their district, a zone leader their zone). Right: the query and what its answer looks like, with sample numbers.</p>

<!--
If the portal can't be reached, the two live charts say so instead of drawing; the sample on the right always draws.
-->

---
layout: gfm-section
kicker: "Part 5"
---

# Layouts and building blocks

---
layout: gfm-comparison
title: "Comparison"
kicker: "Layouts"
leftTitle: "Last transfer"
rightTitle: "This transfer"
---

<GfmComparison leftLabel="Lessons" :leftValue="41" rightLabel="Lessons" :rightValue="47" />

::right::

<GfmCallout title="Invitation" tone="info">Invite one friend to church this Sunday.</GfmCallout>

<GfmInsight>Teaching rose five weeks in a row.</GfmInsight>

---
layout: gfm-image-message
kicker: "Layouts"
imageSide: right
image: data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCA4MDAgNjAwIj48ZGVmcz48bGluZWFyR3JhZGllbnQgaWQ9InMiIHgxPSIwIiB5MT0iMCIgeDI9IjAiIHkyPSIxIj48c3RvcCBvZmZzZXQ9IjAiIHN0b3AtY29sb3I9IiMwODdmOGMiLz48c3RvcCBvZmZzZXQ9IjEiIHN0b3AtY29sb3I9IiM5ZmU3ZWEiLz48L2xpbmVhckdyYWRpZW50PjwvZGVmcz48cmVjdCB3aWR0aD0iODAwIiBoZWlnaHQ9IjYwMCIgZmlsbD0idXJsKCNzKSIvPjxjaXJjbGUgY3g9IjYwMCIgY3k9IjE1MCIgcj0iNjAiIGZpbGw9IiNmZmU3YTMiLz48cGF0aCBkPSJNMCA2MDAgTDIyMCAyNjAgTDM2MCA0NTAgTDUwMCAyMjAgTDgwMCA2MDAgWiIgZmlsbD0iIzE3Mzk0YiIvPjxwYXRoIGQ9Ik01MDAgMjIwIEw1NjAgMzAwIEw1MjAgMjkwIEw0ODAgMzIwIEw0NTAgMjkwIFoiIGZpbGw9IiNmZmYiIG9wYWNpdHk9Ii44NSIvPjwvc3ZnPgo=
---

# Picture and message

<GfmQuote author="Alma 37:6">By small and simple things are great things brought to pass.</GfmQuote>

<!--
Put your own picture in the Assets panel and name it in the image setting.
-->

---
layout: gfm-hero
kicker: "Layouts"
---

# One question, big and bold

What will you invite someone to this week?

---
layout: quote
---

# "Every member a missionary."

David O. McKay

---
layout: default
---

# Code, with click steps

```js {1|2-3|all}
const invite = friend => `Come and see, ${friend}!`
const friends = ['Anna', 'Jonas', 'Lea']
friends.map(invite)
```

<LightOrDark>
<template #dark>🌙 You are watching in <b>dark mode</b>: press the moon/sun button (or the theme in the portal) to switch.</template>
<template #light>☀️ You are watching in <b>light mode</b>: every chart follows dark mode on its own.</template>
</LightOrDark>

<!--
Line highlights follow clicks: {1|2-3|all}. LightOrDark shows different content for each theme.
-->

---
layout: end
---

# That's everything!

Duplicate this deck (⋮ → Duplicate) and make it your own. Have a great zone conference!
