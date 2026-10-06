---
theme: default
title: Chart gallery
info: |
  Every chart type and style setting of the chart components, with sample
  figures. Each slide shows the settings it uses.
colorSchema: auto
fonts:
  provider: none
  sans: Inter
  mono: Cascadia Mono, Consolas
transition: fade
themeConfig:
  primary: '#087f8c'
defaults:
  class: 'text-[#17394b] dark:text-[#e8f1f3]'
layout: cover
class: text-white
---

<div class="text-[0.8rem] font-600 uppercase tracking-[0.2em] text-[#9fe7ea]">Germany Frankfurt Mission · Presentations</div>

# Chart gallery

<div class="max-w-[32rem] text-xl leading-8 opacity-90">More ways to show our numbers: trend lines in our own colours, goals and targets, and new kinds of charts.</div>

<div class="mt-10 text-sm opacity-80">All figures in this deck are samples, made up for this demonstration.</div>

<style>
.slidev-layout.cover {
  background: linear-gradient(135deg, #17394b 0%, #125a69 60%, #0e6f7c 100%) !important;
}
</style>

<!--
- This deck shows every chart type and the most useful settings, with made-up sample figures.
- Each slide names the settings it uses, so you can copy them into your own deck.
- Simple first: a chart needs only a type and a table. Everything else is optional.
-->

---

<div class="text-[0.8rem] leading-5 font-600 uppercase tracking-[0.16em] text-[#087f8c] dark:text-[#5cc6cf]">Trend lines · sample figures</div>

# A trend line in its own colour, with a forecast

<MissionChart type="bar" title="New people being taught per week (sample)" trend="polynomial" :degree="2" trend-color="#d96b2b" trend-style="solid" :trend-width="3" trend-label="Direction" :forecast="3" :target="30" target-label="Zone goal" :height="380" csv="Week,New people being taught; Aug 2,14; Aug 9,17; Aug 16,16; Aug 23,21; Aug 30,20; Sep 6,24; Sep 13,23; Sep 20,27" />

<div class="text-sm opacity-70 -mt-1">trend="polynomial" · trend-color · trend-style="solid" · trend-width · trend-label · forecast="3" · target="30"</div>

<!--
- The trend line can have its own colour, width and style (solid, dashed or dotted) and its own name in the legend.
- Trend methods: linear, polynomial (degree 2 to 6), exponential, logarithmic and a moving average.
- A forecast carries the trend on for a few more weeks; the shaded band marks the forecast.
- A target draws a straight line at a number, here the zone's goal of 30.
-->

---
layout: two-cols
layoutClass: gap-x-10
---

<div class="text-[0.8rem] leading-5 font-600 uppercase tracking-[0.16em] text-[#087f8c] dark:text-[#5cc6cf]">Bars · sample figures</div>

# Stacked and horizontal

<MissionChart type="bar" title="Lessons by zone (sample)" stack legend="bottom" :height="380" csv="Week,North,South,East,West; Aug 30,18,14,11,16; Sep 6,21,15,13,15; Sep 13,19,17,14,18; Sep 20,24,18,16,19" />

<div class="text-sm opacity-70">stack · legend="bottom"</div>

::right::

<div class="h-[4.7rem]"></div>

<MissionChart type="bar" title="Members at lessons (sample)" horizontal show-values value-position="inside" :height="380" csv="District,Members at lessons; District 1,31; District 2,26; District 3,22; District 4,18; District 5,12" />

<div class="text-sm opacity-70">horizontal · show-values · value-position="inside"</div>

<!--
- Left: stacked bars add up the zones, so the height of each bar is the mission total.
- Right: horizontal bars are easier to read with long names. The values are written inside the bars.
-->

---

<div class="text-[0.8rem] leading-5 font-600 uppercase tracking-[0.16em] text-[#087f8c] dark:text-[#5cc6cf]">Combined · sample figures</div>

# Bars and a line together, with the goal and the average

<MissionChart type="bar" title="Sacrament attendance (sample)" :series-types="['bar', 'line']" goal="Goal" goal-color="#6656c9" average average-color="#3f8a3a" y-title="People" :y-min="0" :height="400" csv="Week,Attendance,Last year,Goal; Aug 2,382,360,400; Aug 9,395,371,400; Aug 16,388,365,410; Aug 23,402,380,410; Aug 30,411,377,420; Sep 6,406,383,420; Sep 13,418,390,430; Sep 20,425,388,430" />

<div class="text-sm opacity-70 -mt-1">series-types="bar, line" · goal="Goal" · goal-color · average · y-title · y-min</div>

<!--
- Each column can be its own kind: this year as bars, last year as a line.
- The column named in goal is drawn as the goal line, in its own colour.
- The average line shows the average of the weeks shown.
-->

---

<div class="text-[0.8rem] leading-5 font-600 uppercase tracking-[0.16em] text-[#087f8c] dark:text-[#5cc6cf]">Key numbers · sample figures</div>

# One big number, with the weeks before it

<div class="grid grid-cols-3 gap-8 mt-6">
<MissionChart type="tile" title="Baptismal dates" :height="230" csv="Week,Baptismal dates,Goal; Aug 23,14,16; Aug 30,15,16; Sep 6,17,18; Sep 13,16,18; Sep 20,19,20" />
<MissionChart type="tile" title="Sacrament attendance" :colors="['#d96b2b']" :height="230" csv="Week,Attendance,Goal; Aug 23,402,410; Aug 30,411,420; Sep 6,406,420; Sep 13,418,430; Sep 20,425,430" />
<MissionChart type="tile" title="New members at church" :colors="['#6656c9']" :height="230" csv="Week,New members,Goal; Aug 23,21,24; Aug 30,23,24; Sep 6,22,25; Sep 13,24,25; Sep 20,26,26" />
</div>

<div class="text-sm opacity-70 mt-4">type="tile" · the second column is the goal</div>

<!--
- A key number shows the latest week large, the change from the week before, how close it came to the goal and a small line of the weeks before.
- Live charts can show a key number too: MissionKpiChart with chart="tile".
-->

---
layout: two-cols
layoutClass: gap-x-10
---

<div class="text-[0.8rem] leading-5 font-600 uppercase tracking-[0.16em] text-[#087f8c] dark:text-[#5cc6cf]">Patterns · sample figures</div>

# Heat map and radar

<MissionChart type="heatmap" title="New people being taught by zone (sample)" show-values :height="360" csv="Week,North,South,East,West; Aug 23,5,3,4,6; Aug 30,7,4,3,5; Sep 6,6,6,5,7; Sep 13,8,5,6,6; Sep 20,9,7,6,8" />

<div class="text-sm opacity-70">type="heatmap" · show-values</div>

::right::

<div class="h-[4.7rem]"></div>

<MissionChart type="radar" title="Share of the goal by zone, % (sample)" :max="120" :height="360" csv="Key indicator,North,South; New people being taught,96,82; Baptismal dates,88,104; Sacrament attendance,101,93; Members at lessons,78,90; New members at church,92,86" />

<div class="text-sm opacity-70">type="radar" · max="120"</div>

<!--
- A heat map shows a table as coloured cells: darker is more. It helps us see which weeks and zones stand out.
- A radar compares a few zones across several key indicators at once.
-->

---
layout: two-cols
layoutClass: gap-x-10
---

<div class="text-[0.8rem] leading-5 font-600 uppercase tracking-[0.16em] text-[#087f8c] dark:text-[#5cc6cf]">Steps and changes · sample figures</div>

# Funnel and waterfall

<MissionChart type="funnel" title="From finding to baptism (sample)" show-values :height="360" csv="Step,People; New people being taught,120; Came to church,74; Lessons with a member,41; Baptismal date,19; Baptized and confirmed,11" />

<div class="text-sm opacity-70">type="funnel" · show-values</div>

::right::

<div class="h-[4.7rem]"></div>

<MissionChart type="waterfall" title="Sacrament attendance, what changed (sample)" show-values :height="360" csv="Change,People; Last month,380; New members,9; Came back,14; Moved away,-6; Travelling,-11" />

<div class="text-sm opacity-70">type="waterfall" · the rows add up to the total</div>

<!--
- A funnel shows the steps on the covenant path, from finding to baptism, and how many friends reached each one.
- A waterfall starts from a number and shows each change up or down; the last bar is where it ends.
-->

---
layout: two-cols
layoutClass: gap-x-10
---

<div class="text-[0.8rem] leading-5 font-600 uppercase tracking-[0.16em] text-[#087f8c] dark:text-[#5cc6cf]">Parts of a whole · sample figures</div>

# Tree map and sunburst

<MissionChart type="treemap" title="New people being taught, zone and district (sample)" show-values :height="360" csv="Area,Friends; North / District 1,12; North / District 2,9; South / District 3,11; South / District 4,8; West / District 5,10; West / District 6,6" />

<div class="text-sm opacity-70">type="treemap" · "Zone / District" in the first column</div>

::right::

<div class="h-[4.7rem]"></div>

<MissionChart type="sunburst" title="The same, as a sunburst (sample)" :height="360" csv="Area,Friends; North / District 1,12; North / District 2,9; South / District 3,11; South / District 4,8; West / District 5,10; West / District 6,6" />

<div class="text-sm opacity-70">type="sunburst"</div>

<!--
- Both show how a whole is made up, level by level: the mission, its zones and their districts.
- Write the levels with a slash in the first column: Zone / District.
-->

---
layout: two-cols
layoutClass: gap-x-10
---

<div class="text-[0.8rem] leading-5 font-600 uppercase tracking-[0.16em] text-[#087f8c] dark:text-[#5cc6cf]">Spread and comparison · sample figures</div>

# Box plot and small charts

<MissionChart type="boxplot" title="Lessons per week, by zone (sample)" :height="360" csv="Week,North,South,East,West; 1,18,14,11,16; 2,21,15,13,15; 3,19,17,14,18; 4,24,18,16,19; 5,22,16,12,30; 6,20,19,15,17" />

<div class="text-sm opacity-70">type="boxplot" · one box per column</div>

::right::

<div class="h-[4.7rem]"></div>

<MissionChart type="line" title="New people being taught (sample)" multiples trend="linear" :height="360" csv="Week,North,South,East,West; Aug 23,5,3,4,6; Aug 30,7,4,3,5; Sep 6,6,6,5,7; Sep 13,8,5,6,6; Sep 20,9,7,6,8" />

<div class="text-sm opacity-70">multiples · one small chart per column, same scale</div>

<!--
- A box plot shows the spread of each zone's weeks: the box holds the middle half, the line in it is the middle value, and a lone dot is an unusual week.
- Small charts side by side make it easy to compare zones without one busy chart.
-->

---

<div class="text-[0.8rem] leading-5 font-600 uppercase tracking-[0.16em] text-[#087f8c] dark:text-[#5cc6cf]">Numbers and axes · sample figures</div>

# Percentages, axis titles and a zoom slider

<MissionChart type="area" title="Share of friends at church (sample)" format="percent" :decimals="0" x-title="Week" y-title="Share of friends" :y-min="0" :y-max="100" smooth data-zoom trend="moving-average" :window="4" trend-color="#6656c9" :height="350" csv="Week,At church; W1,31; W2,34; W3,29; W4,38; W5,41; W6,37; W7,44; W8,46; W9,43; W10,49; W11,52; W12,50" />

<div class="text-sm opacity-70 -mt-1">format="percent" · decimals · x-title · y-title · y-min · y-max · smooth · data-zoom · trend="moving-average" · window="4"</div>

<!--
- Numbers can be written as percentages, compact (1.2K), with fixed decimals, or with a word before or after them.
- The zoom slider lets us look at a few weeks up close while presenting.
- A moving average smooths out the ups and downs of single weeks.
-->

---
layout: center
---

<div class="w-[860px]">

<div class="text-[0.8rem] leading-5 font-600 uppercase tracking-[0.16em] text-[#087f8c] dark:text-[#5cc6cf]">Try it yourself</div>

# The same settings in Source

<div class="text-sm leading-6 opacity-75 mt-4 mb-2">Every setting also works in a chart block. Write it with dashes, like trend-color:</div>

````md
```chart type=bar trend=linear trend-color=#d96b2b trend-style=dotted target=20 show-values
Week,Baptismal dates
Sep 6,14
Sep 13,17
Sep 20,19
```
````

```chart type=bar trend=linear trend-color=#d96b2b trend-style=dotted target=20 show-values height=220
Week,Baptismal dates
Sep 6,14
Sep 13,17
Sep 20,19
```

</div>

<!--
- In Studio, choose a chart and change its settings in the Element panel. The everyday settings come first; the ones marked More fine-tune the chart.
- In Source, a code block that starts with the word chart becomes a chart. Settings are written with dashes.
-->
