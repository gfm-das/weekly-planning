---
theme: default
title: Mission charts
info: |
  A short tour of the chart components in Presentations: live key indicators
  from Call-ins, goals and trend lines, charts made from your own numbers, and
  charts straight from the weekly plans made with Add chart.
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
background: /cover.svg
class: text-white
---

<div class="text-[0.8rem] font-600 uppercase tracking-[0.2em] text-[#9fe7ea]">Germany Frankfurt Mission · Presentations</div>

# Mission charts

<div class="max-w-[30rem] text-xl leading-8 opacity-90">Live key indicators, goals and trends, and charts from your own numbers, right inside our slides.</div>

<div class="mt-12 flex gap-3 text-[0.8rem] leading-5">
  <span class="px-3 py-1 rounded-full border border-white/35 bg-white/10">Six key indicators</span>
  <span class="px-3 py-1 rounded-full border border-white/35 bg-white/10">Goals set in faith</span>
  <span class="px-3 py-1 rounded-full border border-white/35 bg-white/10">Trends over time</span>
</div>

<!--
- Welcome. This short deck shows what the new chart pieces in Presentations can do.
- There are two kinds: live charts of our six key indicators, straight from Call-ins, and charts made from any small table we paste in.
- Every number here stands for people: a friend we are teaching, a family at church, a new member finding their place. The charts help us see them and counsel together; they are not for comparing or judging.
- To move through the slides use the arrow keys or Space. Press O to see all slides at once, and D to switch between light and dark.
-->

---
layout: two-cols-header
layoutClass: 'gap-x-8 text-[#17394b] dark:text-[#e8f1f3]'
---

<div class="text-[0.8rem] leading-5 font-600 uppercase tracking-[0.16em] text-[#087f8c] dark:text-[#5cc6cf]">Live from Call-ins</div>

# Six key indicators at a glance

Each live chart loads the latest mission totals the moment its slide opens.

::left::

<MissionKpiChart kpi="Baptisms and confirmations" :weeks="12" chart="bar" :height="262" />

::right::

<MissionKpiChart kpi="New people being taught" :weeks="12" chart="line" :height="262" />

::bottom::

<div class="mt-4 pt-3 border-t border-[#17394b]/15 dark:border-white/15 grid grid-cols-3 gap-x-6 gap-y-1 text-[0.85rem] leading-6">
  <span><span class="text-[#087f8c] dark:text-[#5cc6cf]">●</span> New people being taught</span>
  <span><span class="text-[#087f8c] dark:text-[#5cc6cf]">●</span> Baptisms and confirmations</span>
  <span><span class="text-[#087f8c] dark:text-[#5cc6cf]">●</span> Baptismal dates</span>
  <span><span class="text-[#087f8c] dark:text-[#5cc6cf]">●</span> Sacrament attendance</span>
  <span><span class="text-[#087f8c] dark:text-[#5cc6cf]">●</span> Members at lessons</span>
  <span><span class="text-[#087f8c] dark:text-[#5cc6cf]">●</span> New members at sacrament meeting</span>
</div>

<!--
- These two charts are live. They load the latest mission totals from Call-ins when this slide opens, so the deck never goes out of date.
- Left: baptisms and confirmations over the last 12 weeks, the joyful fruit of many weeks of teaching. Right: new people being taught, where that work begins.
- The small squares are the goal the companionships set the week before. The dashed line is the trend.
- The six names at the bottom are our key indicators. The next slides look at them one at a time.
- The most recent week can still grow while companionships finish their reports.
-->

---

<div class="text-[0.8rem] leading-5 font-600 uppercase tracking-[0.16em] text-[#087f8c] dark:text-[#5cc6cf]">Live · Sacrament meeting</div>

# Sacrament meeting attendance

Every point is a week of friends worshipping with the Saints.

<div class="grid grid-cols-[1fr_232px] gap-8 items-start">
<div class="min-w-0">
<MissionKpiChart kpi="Sacrament attendance" title="Mission total per week" :weeks="16" chart="line" trend="linear" :height="312" />
<div class="mt-2 text-xs opacity-60">Line chart · 16 weeks · linear trend · goal shown</div>
</div>
<div class="text-[0.95rem] leading-6 border-l-2 border-[#087f8c]/40 dark:border-[#5cc6cf]/40 pl-5">

**How to read it**

The solid line is the mission total for each week.

The squares are the goal set the week before.

The dashed line shows the direction over the whole period.

</div>
</div>

<!--
- This is the first of five live charts, one for each key indicator.
- The solid line is what happened each week, added up across the mission. The squares are the goal the companionships set the week before, the same pairing we use in Call-ins.
- The dashed straight line is a linear trend: it smooths out the ups and downs so we can see the direction over four months.
- A question to counsel about: what helped in the weeks that rose, and how can we help friends feel welcome at church again this Sunday?
-->

---

<div class="text-[0.8rem] leading-5 font-600 uppercase tracking-[0.16em] text-[#087f8c] dark:text-[#5cc6cf]">Live · Finding</div>

# New people being taught

Each bar is a week of new friends who agreed to learn about the Savior.

<div class="grid grid-cols-[1fr_232px] gap-8 items-start">
<div class="min-w-0">
<MissionKpiChart kpi="New people being taught" title="Mission total per week" :weeks="16" chart="bar" trend="polynomial" :degree="2" :height="312" />
<div class="mt-2 text-xs opacity-60">Bar chart · 16 weeks · curved trend (polynomial, degree 2) · goal shown</div>
</div>
<div class="text-[0.95rem] leading-6 border-l-2 border-[#087f8c]/40 dark:border-[#5cc6cf]/40 pl-5">

**A curved trend**

A curved trend line can bend, so it shows whether finding is speeding up or levelling off.

**Ask together**

Which finding efforts were blessed in the weeks when the bars rose?

</div>
</div>

<!--
- Every conversion story begins with a new person being taught.
- Each bar is the mission total for one week, and the squares are the goals set the week before.
- This time the trend line is curved (a polynomial of degree 2). Unlike a straight line it can bend, so we can see whether finding is speeding up or levelling off.
- Invite the leaders to share what helped in the strong weeks: member referrals, service, finding activities, online contacts.
-->

---

<div class="text-[0.8rem] leading-5 font-600 uppercase tracking-[0.16em] text-[#087f8c] dark:text-[#5cc6cf]">Live · Baptismal dates</div>

# Baptismal dates

Friends preparing for baptism, week by week, beside the goals we set.

<div class="grid grid-cols-[1fr_232px] gap-8 items-start">
<div class="min-w-0">
<MissionKpiChart kpi="Baptismal dates" title="Mission total per week" :weeks="16" chart="line" trend="none" show-goal :height="312" />
<div class="mt-2 text-xs opacity-60">Line chart · 16 weeks · goal shown · no trend line</div>
</div>
<div class="text-[0.95rem] leading-6 border-l-2 border-[#087f8c]/40 dark:border-[#5cc6cf]/40 pl-5">

**Goals made in faith**

The squares are the goals the companionships set the week before.

The space between the two lines is not a failure. It is where we counsel together and plan again.

</div>
</div>

<!--
- Here the trend line is switched off so we can look only at what happened and at the goals.
- The squares are the goals set the week before. A goal is a plan made in faith: it shows what we hope to help the Lord do, and it helps us act.
- When the actual line sits below the goal line, that is a place to counsel together, not a reason for discouragement. When it rises above, we give thanks.
- Question for the council: which friends with a baptismal date need extra help this week, and who in the ward can support them?
-->

---

<div class="text-[0.8rem] leading-5 font-600 uppercase tracking-[0.16em] text-[#087f8c] dark:text-[#5cc6cf]">Live · Members at lessons</div>

# Lessons with members participating

When members join a lesson, friends gain a friend at church.

<div class="grid grid-cols-[1fr_232px] gap-8 items-start">
<div class="min-w-0">
<MissionKpiChart kpi="Members at lessons" title="Mission total per week" :weeks="12" chart="bar" trend="none" :show-goal="false" show-values :height="312" />
<div class="mt-2 text-xs opacity-60">Bar chart · 12 weeks · numbers shown · goal and trend hidden</div>
</div>
<div class="text-[0.95rem] leading-6 border-l-2 border-[#087f8c]/40 dark:border-[#5cc6cf]/40 pl-5">

**Numbers on the bars**

This chart hides the goal and trend lines and writes each week's total on its bar, for when exact figures matter.

**Ask together**

Which wards and members could we thank this week?

</div>
</div>

<!--
- Lessons with a member participating are some of the most important lessons we teach. The member becomes a friend who will still be there after baptism.
- This chart shows another way to set up a live chart: the goal and trend lines are switched off and each week's number is written on its bar.
- Use it when leaders want exact figures on the screen, for example in a mission leadership council.
- A good follow-up: thank the ward leaders and members who helped, and ask how we can make it easy for members to join us.
-->

---

<div class="text-[0.8rem] leading-5 font-600 uppercase tracking-[0.16em] text-[#087f8c] dark:text-[#5cc6cf]">Live · New members</div>

# New members at sacrament meeting

Half a year of new members staying close to the Savior and the ward.

<div class="grid grid-cols-[1fr_232px] gap-8 items-start">
<div class="min-w-0">
<MissionKpiChart kpi="New member sacrament attendance" title="Mission total per week" :weeks="26" chart="line" trend="polynomial" :degree="3" :height="312" />
<div class="mt-2 text-xs opacity-60">Line chart · 26 weeks · curved trend (polynomial, degree 3) · goal shown</div>
</div>
<div class="text-[0.95rem] leading-6 border-l-2 border-[#087f8c]/40 dark:border-[#5cc6cf]/40 pl-5">

**The longer story**

Twenty-six weeks with a curved trend show the long view, across several transfers.

**Ask together**

Which new members have we not seen for a while, and who will visit them?

</div>
</div>

<!--
- New members who come to sacrament meeting each week keep growing in their faith and in their friendships at church.
- This chart looks back 26 weeks, about half a year, so we see several transfers at once.
- The curved trend line (degree 3) follows the longer ups and downs without reacting to every single week.
- Invite the council to think of names, not numbers: which new members could use a visit, a ride or a friend to sit with this Sunday?
-->

---
layout: section
---

<div class="text-[0.8rem] leading-5 font-600 uppercase tracking-[0.16em] text-[#087f8c] dark:text-[#5cc6cf]">Part two</div>

# Your own numbers

<div class="mx-auto mt-2 max-w-[34rem] text-lg leading-7 opacity-75">Zone conferences, district councils, a ward's plan: any small table can become a chart in a few seconds.</div>

<div class="mx-auto mt-8 h-1 w-16 rounded-full bg-[#087f8c] dark:bg-[#5cc6cf]"></div>

<!--
- So far every chart came straight from Call-ins. The same chart pieces also work with numbers we type or paste ourselves.
- That is useful for things Call-ins does not collect: a zone conference follow-up, a district's own plan, or a comparison we want to show in council.
- The next two slides use sample figures, made up for this demonstration.
-->

---
layout: two-cols
layoutClass: gap-x-10
---

<div class="text-[0.8rem] leading-5 font-600 uppercase tracking-[0.16em] text-[#087f8c] dark:text-[#5cc6cf]">Your own numbers · sample figures</div>

# After zone conference

One zone's weekly lessons with a member present, pasted from a spreadsheet.

```text
Week,Lessons with a member
Aug 2,21
Aug 9,19
Aug 16,24
Aug 23,26
Aug 30,25
Sep 6,31
Sep 13,33
Sep 20,36
```

<div class="mt-3 text-sm leading-6 opacity-75">Zone conference was held in the week of Aug 30. The dashed trend line is worked out for us.</div>

::right::

<MissionChart type="line" title="Lessons with a member present (sample)" trend="linear" :height="440" csv="
Week,Lessons with a member
Aug 2,21
Aug 9,19
Aug 16,24
Aug 23,26
Aug 30,25
Sep 6,31
Sep 13,33
Sep 20,36
" />

<!--
- These are sample figures, made up for this demonstration.
- Imagine a zone that chose, at zone conference, to invite a member to more lessons. The zone leaders keep a small table in a spreadsheet.
- They copied the cells and pasted them into the chart. The first row holds the headings, the first column the weeks, and each other column becomes one line.
- The dashed line is a linear trend worked out automatically. Here it shows the steady rise after the conference.
- The same works for a district council or a ward's plan: any small table with a heading row.
-->

---
layout: two-cols-header
layoutClass: '!grid-cols-[2fr_1fr] gap-x-8 text-[#17394b] dark:text-[#e8f1f3]'
---

<div class="text-[0.8rem] leading-5 font-600 uppercase tracking-[0.16em] text-[#087f8c] dark:text-[#5cc6cf]">More chart types · sample figures</div>

# Shares and progress

A donut shows how a whole is made up. A gauge shows how close we are to a goal.

::left::

<MissionChart type="donut" title="Where friends were found (sample)" show-values :height="320" csv="Source,Friends; Members,18; Finding,12; Online,9; Service,5" />

::right::

<MissionChart type="gauge" title="This week's goal (sample)" :height="320" csv="Measure,Actual,Goal; Sacrament attendance,412,450" />

<!--
- These are sample figures again, made up for this demonstration.
- Left, a donut chart: how the new people we began teaching in one week came to us: through members, our own finding, online contacts and service. With the numbers switched on, each slice shows its count and its share.
- Right, a gauge: one number measured against a goal. Here 412 people at sacrament meeting against a goal of 450, which is 92 percent.
- Pie charts and bar, line, area and scatter charts are also available. All of them follow dark mode and the mission colours automatically.
-->

---
layout: section
---

<div class="text-[0.8rem] leading-5 font-600 uppercase tracking-[0.16em] text-[#087f8c] dark:text-[#5cc6cf]">Part three</div>

# Straight from our plans

<div class="mx-auto mt-2 max-w-[34rem] text-lg leading-7 opacity-75">Any number from Weekly Planning and Call-ins, for the mission, a zone, a district or an area, made with Add chart in the editor.</div>

<div class="mx-auto mt-8 h-1 w-16 rounded-full bg-[#087f8c] dark:bg-[#5cc6cf]"></div>

<!--
- The last part shows charts that read our weekly plans directly: the key indicators, lessons, and how the people we teach are progressing.
- They load the latest numbers when the slide opens, like the live charts at the start.
- They are made with Add chart in the editor. No typing is needed.
-->

---
layout: two-cols-header
layoutClass: 'gap-x-8 text-[#17394b] dark:text-[#e8f1f3]'
---

<div class="text-[0.8rem] leading-5 font-600 uppercase tracking-[0.16em] text-[#087f8c] dark:text-[#5cc6cf]">From the database · zones</div>

# Zones side by side

The last four weeks added up, one bar per zone.

::left::

<MissionChart type="bar" title="Sacrament attendance" show-values :height="300" :query='{"measures":["sacrament_attendance.actual"],"level":"zone","by":"unit","weeks":4,"sort":"desc"}' />

::right::

<MissionChart type="bar" title="Baptismal dates: % of the goal" show-values :height="300" :colors="['#d96b2b']" :query='{"measures":["baptismal_dates.actual","baptismal_dates.previous_goal"],"level":"zone","by":"unit","weeks":4,"transform":"pct_of_goal"}' />

::bottom::

<div class="mt-3 text-xs opacity-60">Left: highest first · Right: each zone against the goals it set the week before; the line is 100 %</div>

<!--
- Two ways to compare zones over the same four weeks.
- Left: sacrament meeting attendance, added up and sorted from highest to lowest. Bigger zones have bigger numbers, so this is a picture of where our friends and members are, not a ranking.
- Right: baptismal dates against the goals each zone set the week before. The line at 100 percent is the goal. This is the fairer comparison, because each zone is measured against its own goal.
- A question to counsel about: what is helping the zones near or above the line, and what could we share?
-->

---
layout: two-cols-header
layoutClass: '!grid-cols-[2fr_1fr] gap-x-8 text-[#17394b] dark:text-[#e8f1f3]'
---

<div class="text-[0.8rem] leading-5 font-600 uppercase tracking-[0.16em] text-[#087f8c] dark:text-[#5cc6cf]">From the database · new chart types</div>

# Every week, every zone

::left::

<MissionChart type="heatmap" title="New people being taught per zone and week" show-values :height="330" :query='{"measures":["friends_found.actual"],"level":"zone","weeks":12,"includeCurrent":false}' />

::right::

<MissionChart type="tile" title="Baptisms and confirmations" :height="330" :query='{"measures":["baptisms_confirmations.actual","baptisms_confirmations.previous_goal"],"weeks":8,"includeCurrent":false}' />

<!--
- Left: a heat map of the last twelve finished weeks. Each row is a zone and each column a week; the brighter the square, the more new people were being taught. It shows at a glance which weeks were strong across the whole mission and where a zone might need encouragement.
- Right: a key number. The big figure is the last finished week of baptisms and confirmations, with the change from the week before, how it compares with the goal set the week before, and a small line of the last eight weeks.
- Behind every square and every number is a person the Lord is preparing.
-->

---
layout: two-cols-header
layoutClass: 'gap-x-8 text-[#17394b] dark:text-[#e8f1f3]'
---

<div class="text-[0.8rem] leading-5 font-600 uppercase tracking-[0.16em] text-[#087f8c] dark:text-[#5cc6cf]">From the database · the people we teach</div>

# Along the covenant path

Counts from the weekly plans, never names.

::left::

<MissionChart type="line" title="New members" smooth legend="bottom" :height="300" :colors="['#00869e', '#3f8a3a', '#6656c9']" :query='{"measures":["new_members.total","new_members.at_church","new_members.calling"],"weeks":12}' />

::right::

<MissionChart type="bar" title="Friends with a baptismal date" legend="bottom" trend="moving-average" :window="3" trend-color="#d96b2b" trend-style="solid" trend-label="Average of 3 weeks" :height="300" :query='{"measures":["baptismal_date_friends.total"],"weeks":12}' />

<!--
- These charts count the people on our weekly plans. They never show names or notes.
- Left: new members we are ministering to each week, how many of them were at church, and how many have a calling. A calling is one of the surest ways a new member finds a home in the ward.
- Right: friends with a baptismal date each week. The orange line is a three-week average, so a single busy or quiet week does not hide the direction.
- For a single area, numbers below three are hidden, so no one can be picked out.
-->

---
layout: two-cols
layoutClass: gap-x-10
---

<div class="text-[0.8rem] leading-5 font-600 uppercase tracking-[0.16em] text-[#087f8c] dark:text-[#5cc6cf]">From the database · your stewardship</div>

# Each leader sees their own

One chart for everyone, with the numbers of each person's stewardship.

<div class="mt-5 space-y-3 text-[0.95rem] leading-6">

- A **district leader** sees the areas of their district.
- A **zone leader** sees the areas of their zone.
- The Assistants, the President and the data office see the whole mission.

</div>

<div class="mt-5 text-sm leading-6 opacity-75">Set in the chart builder under <b>Who sees what</b>. Area numbers identify companionships, so this is the choice for district and area charts.</div>

::right::

<MissionChart type="bar" horizontal title="New people being taught per area, last 4 weeks" show-values :height="440" :query='{"measures":["friends_found.actual"],"level":"area","by":"unit","weeks":4,"sort":"desc","top":10,"audience":"stewardship"}' />

<!--
- This chart is written once, but everyone sees the numbers of their own stewardship.
- A district leader who opens this deck sees the areas of their district; a zone leader the areas of their zone. We see the ten areas with the most new people being taught in the whole mission.
- That way a deck can be shared with every district leader for district council without showing any companionship's numbers to the whole mission.
- As always, these numbers are for counselling and rejoicing together, not for comparing companionships.
-->

---
layout: center
---

<div class="w-[868px]">

<div class="text-[0.8rem] leading-5 font-600 uppercase tracking-[0.16em] text-[#087f8c] dark:text-[#5cc6cf]">Try it yourself</div>

# Make your own chart

<div class="grid grid-cols-[1fr_330px] gap-10 items-start mt-6">
<div class="space-y-4 text-[0.95rem] leading-6">
  <div class="flex gap-4">
    <span class="shrink-0 w-8 h-8 rounded-full grid place-items-center text-sm font-700 text-white bg-[#087f8c]">1</span>
    <div><b>Open the editor.</b> In Presentations, open the menu on a deck (the three dots) and choose <b>Edit</b>.</div>
  </div>
  <div class="flex gap-4">
    <span class="shrink-0 w-8 h-8 rounded-full grid place-items-center text-sm font-700 text-white bg-[#087f8c]">2</span>
    <div><b>Add a chart.</b> Click <b>Add chart</b> at the top and say what you would like to show. Choose the numbers, a chart type and a look, then <b>Insert chart</b>.</div>
  </div>
  <div class="flex gap-4">
    <span class="shrink-0 w-8 h-8 rounded-full grid place-items-center text-sm font-700 text-white bg-[#087f8c]">3</span>
    <div><b>Change it later.</b> Click the chart on the slide and choose <b>Edit chart</b>, or change a setting in the <b>Element</b> panel. Saved changes are published on their own.</div>
  </div>
</div>
<div class="min-w-0">
<div class="text-sm leading-6 opacity-75 mb-2">Prefer typing? In <b>Source</b>, a chart block does the same:</div>

````md
```chart type=bar trend=linear
Week,Baptismal dates
Sep 6,14
Sep 13,17
Sep 20,19
```
````

</div>
</div>

</div>

<!--
- Anyone who can edit presentations can do this: the Assistants, the President and the data office.
- Step 1: in Presentations, open the menu on a deck (the three dots) and choose Edit.
- Step 2: click Add chart at the top of the editor. It first asks what you would like to show: a key indicator over time, zones or districts side by side, progress toward this week's goals, or your own numbers. Then choose the numbers, for the mission or each zone, district or area, a chart type and a look. The preview shows exactly what the slide will get. Choose Insert chart.
- Step 3: to change a chart later, click it on the slide and choose Edit chart. Small changes also work in the Element panel. The Components panel under Charts still offers MissionChart and MissionKpiChart as before.
- Saved changes are published automatically after a moment. Publish now shows them straight away.
- For those who like typing: in Source, a code block that starts with the word chart becomes a chart.
- A new deck is only visible to the Assistants, the President and the data office until someone chooses Manage access.
-->

---
layout: end
class: text-white
---

<div class="max-w-[40rem] mx-auto tracking-normal select-text">

<div class="text-[0.8rem] font-600 uppercase tracking-[0.2em] text-[#9fe7ea]">Thank you</div>

<div class="mt-4 text-5xl font-600 leading-tight text-white">Every number is a person</div>

<div class="mt-6 text-lg leading-8 text-white/85">Behind each point on these charts is a friend learning about the Savior, a family at church, a new member finding a home in the ward. May these charts help us counsel together, plan in faith and rejoice in every step.</div>

</div>

<style>
.slidev-layout.end {
  background: linear-gradient(135deg, #17394b 0%, #125a69 60%, #0e6f7c 100%) !important;
}
</style>

<!--
- Close by bringing it back to people. Each point on these charts is someone the Lord knows by name.
- Invite everyone to try one chart in their next council or zone presentation.
- Questions or ideas for new charts can go to the data office.
-->
