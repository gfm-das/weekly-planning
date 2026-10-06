---
theme: default
title: Mission Dashboard
titleTemplate: '%s'
info: |
  The mission's key indicators, zones, districts and the people on the covenant
  path, live from the weekly plans. Opened by the Dashboards button in the portal.
  Every chart loads the latest finished weeks when its slide is shown.
colorSchema: auto
fonts:
  provider: none
  sans: Inter
  mono: Cascadia Mono, Consolas
transition: fade
themeConfig:
  primary: '#087f8c'
defaults:
  class: 'text-[#17394b] dark:text-[#e8f1f3] !px-12 !pt-8 !pb-9'
routeAlias: start
class: 'text-[#17394b] dark:text-[#e8f1f3] !px-8 !pt-8 !pb-9'
---

<div class="flex items-end justify-between gap-6">
<div>
<div class="kicker">Mission Dashboard · live from the weekly plans</div>
<h1 class="!text-[2.1rem] !leading-tight !mb-0">This week at a glance</h1>
</div>
<div class="text-right text-[0.9rem] leading-5 opacity-75 pb-1">The last finished week,<br>against the goal set the week before</div>
</div>

<div class="grid grid-cols-3 gap-3 mt-5">
<div class="tile tile--first">
<span class="tile__badge">The key indicator</span>
<MissionChart type="tile" :height="168" :query='{"measures":["friends_found.actual","friends_found.previous_goal"],"weeks":12,"includeCurrent":false}' />
</div>
<div class="tile">
<MissionChart type="tile" :height="168" :query='{"measures":["baptisms_confirmations.actual","baptisms_confirmations.previous_goal"],"weeks":12,"includeCurrent":false}' />
</div>
<div class="tile">
<MissionChart type="tile" :height="168" :query='{"measures":["baptismal_dates.actual","baptismal_dates.previous_goal"],"weeks":12,"includeCurrent":false}' />
</div>
<div class="tile">
<MissionChart type="tile" :height="168" :query='{"measures":["sacrament_attendance.actual","sacrament_attendance.previous_goal"],"weeks":12,"includeCurrent":false}' />
</div>
<div class="tile">
<MissionChart type="tile" :height="168" :query='{"measures":["members_at_lessons.actual","members_at_lessons.previous_goal"],"weeks":12,"includeCurrent":false}' />
</div>
<div class="tile">
<MissionChart type="tile" :height="168" :query='{"measures":["new_member_sacrament.actual","new_member_sacrament.previous_goal"],"weeks":12,"includeCurrent":false}' />
</div>
</div>

<div class="jump mt-4">
<span class="opacity-70">Look closer:</span>
<Link to="kpis">Each key indicator</Link>
<Link to="zones">Zones</Link>
<Link to="people">The covenant path</Link>
<Link to="districts">Districts to help</Link>
</div>

<!--
- Welcome. This dashboard shows the mission's six key indicators from the weekly plans. It loads the latest numbers every time a slide is shown.
- Each tile is the last finished week: the big number, the change from the week before, how it compares with the goal the companionships set the week before, and a small line of the last twelve weeks.
- This week's plans are still being filled in, so the week in progress is left out. It appears here once the week is over.
- New people being taught comes first: every conversion begins with a new person being taught.
- Use the arrow keys, Space or a swipe to move on, or the links at the bottom. Press O to see every slide at once.
-->

---
routeAlias: kpis
---

<div class="kicker">Key indicator 1 of 6 · Finding</div>

# New people being taught

<p class="lead">Every conversion begins here: see whether the bars reach the goal the companionships set, and which way the curve is bending.</p>

<MissionChart type="bar" trend="polynomial" :degree="2" trend-color="#6656c9" trend-label="Curved trend" :height="352" :option='{"xAxis":{"axisLabel":{"showMaxLabel":true}}}' :query='{"measures":["friends_found.actual","friends_found.previous_goal"],"weeks":26,"includeCurrent":false}' />

<!--
- The bars are the new people being taught across the mission each week, for the last 26 finished weeks (or as many as we have).
- The orange squares are the goal the companionships set the week before, the same goal Call-ins uses.
- The violet dashed line is a curved trend. It can bend, so it shows whether finding is growing, levelling off or easing.
- A question to counsel about: what helped in the weeks when the bars rose, and how can we help every companionship find someone this week?
-->

---

<div class="kicker">Key indicator 2 of 6 · Covenants</div>

# Baptisms and confirmations

<p class="lead">These numbers are small and move a lot from week to week, so let the straight trend line show the direction rather than any single week.</p>

<MissionChart type="bar" trend="linear" trend-color="#6656c9" trend-label="Straight trend" :height="352" :option='{"xAxis":{"axisLabel":{"showMaxLabel":true}}}' :query='{"measures":["baptisms_confirmations.actual","baptisms_confirmations.previous_goal"],"weeks":26,"includeCurrent":false}' />

<!--
- Each bar is a week of baptisms and confirmations across the mission: people making sacred covenants with God.
- The orange squares are the goal set the week before. The violet dashed line is a straight trend over the whole period.
- With small numbers, one week says little. The trend line shows the direction.
-->

---

<div class="kicker">Key indicator 3 of 6 · Preparing</div>

# Baptismal dates

<p class="lead">Friends with a baptismal date are the baptisms of the coming weeks; a rising line means more friends preparing to make a covenant.</p>

<MissionChart type="bar" trend="linear" trend-color="#6656c9" trend-label="Straight trend" :height="352" :option='{"xAxis":{"axisLabel":{"showMaxLabel":true}}}' :query='{"measures":["baptismal_dates.actual","baptismal_dates.previous_goal"],"weeks":26,"includeCurrent":false}' />

<!--
- Each bar is the number of friends with a baptismal date that week, across the mission.
- The orange squares are the goal set the week before. The violet dashed line is a straight trend.
- A question to counsel about: which friends with a date need a member friend, a visit or help getting to church this week?
-->

---

<div class="kicker">Key indicator 4 of 6 · Worship</div>

# Sacrament attendance

<p class="lead">Each point is a week of friends and members at sacrament meeting; follow the curve across the season more than the ups and downs.</p>

<MissionChart type="area" trend="polynomial" :degree="2" trend-color="#6656c9" trend-label="Curved trend" :height="352" :option='{"xAxis":{"axisLabel":{"showMaxLabel":true}}}' :query='{"measures":["sacrament_attendance.actual","sacrament_attendance.previous_goal"],"weeks":26,"includeCurrent":false}' />

<!--
- The line is the mission total at sacrament meeting each week. The orange squares are the goal set the week before.
- The violet dashed line is a curved trend, so it shows the shape of the season: rising, steady or easing.
- A question to counsel about: who could we invite, remind or accompany to church this Sunday?
-->

---

<div class="kicker">Key indicator 5 of 6 · Members</div>

# Members at lessons

<p class="lead">When members join our lessons, friends gain friends in the ward; compare the line with the goal and with the curve.</p>

<MissionChart type="line" trend="polynomial" :degree="2" trend-color="#6656c9" trend-label="Curved trend" :height="352" :option='{"xAxis":{"axisLabel":{"showMaxLabel":true}}}' :query='{"measures":["members_at_lessons.actual","members_at_lessons.previous_goal"],"weeks":26,"includeCurrent":false}' />

<!--
- The line is how many members took part in lessons each week across the mission. The orange squares are the goal set the week before.
- The violet dashed line is a curved trend.
- Members who teach with us become the friends who stay with new converts. Which wards and members could we invite more often?
-->

---

<div class="kicker">Key indicator 6 of 6 · New members</div>

# New member sacrament attendance

<p class="lead">New members at church each week are the surest sign that they are finding a home in their ward.</p>

<MissionChart type="line" trend="linear" trend-color="#6656c9" trend-label="Straight trend" :height="352" :option='{"xAxis":{"axisLabel":{"showMaxLabel":true}}}' :query='{"measures":["new_member_sacrament.actual","new_member_sacrament.previous_goal"],"weeks":26,"includeCurrent":false}' />

<!--
- The line is how many new members were at sacrament meeting each week. The orange squares are the goal set the week before.
- The violet dashed line is a straight trend.
- Every new member needs a friend, a responsibility and nourishing by the good word of God. The covenant path slides show more about them.
-->

---
routeAlias: zones
---

<div class="kicker">Zones · the last finished week</div>

# Zones against their own goals

<p class="lead">Each zone is measured against the goal it set the week before, so large and small zones compare fairly; the line is 100 %.</p>

<div class="grid grid-cols-2 gap-8">
<div class="min-w-0">
<MissionChart type="bar" title="New people being taught" show-values :height="330" :decimals="0" :query='{"measures":["friends_found.actual","friends_found.previous_goal"],"level":"zone","by":"unit","weeks":1,"includeCurrent":false,"transform":"pct_of_goal"}' />
</div>
<div class="min-w-0">
<MissionChart type="bar" title="Sacrament attendance" show-values :height="330" :colors="['#2a5f99']" :decimals="0" :query='{"measures":["sacrament_attendance.actual","sacrament_attendance.previous_goal"],"level":"zone","by":"unit","weeks":1,"includeCurrent":false,"transform":"pct_of_goal"}' />
</div>
</div>

<!--
- Left: new people being taught in each zone last week, as a share of the goal the zone set the week before. Right: sacrament attendance the same way.
- The line at 100 percent is the goal. A zone above it reached its goal; below it, the zone may welcome encouragement.
- Zones are in alphabetical order on purpose: this is for counselling together, not for ranking.
-->

---

<div class="kicker">Zones · week by week</div>

# New people being taught in every zone

<p class="lead">Each square is a zone in one week against its own goal; the stronger the colour, the closer to or above the goal.</p>

<MissionChart type="heatmap" show-values format="percent" :height="372" :decimals="0" :option='{"xAxis":{"axisLabel":{"showMaxLabel":true}}}' :query='{"measures":["friends_found.actual","friends_found.previous_goal"],"level":"zone","weeks":12,"includeCurrent":false,"transform":"pct_of_goal"}' />

<!--
- Each row is a zone and each column one of the last twelve finished weeks. The number is the share of the goal the zone set the week before.
- Look for rows that stay pale for several weeks: that zone may need a visit, a training or simply our love and encouragement.
- Look for columns that are dark everywhere: what happened in the mission that week?
-->

---
routeAlias: people
---

<div class="kicker">The covenant path · counts, never names</div>

# New members on the covenant path

<p class="lead">Each number is a new member finding their place: at church, the temple, a calling, the priesthood.</p>

<div class="grid grid-cols-3 gap-4">
<div class="tile">
<MissionChart type="tile" :height="140" :colors="['#6656c9']" :query='{"measures":["new_members.total"],"weeks":12,"includeCurrent":false}' />
</div>
<div class="tile">
<MissionChart type="tile" :height="140" :colors="['#6656c9']" :query='{"measures":["new_members.at_church"],"weeks":12,"includeCurrent":false}' />
</div>
<div class="tile">
<MissionChart type="tile" :height="140" :colors="['#6656c9']" :query='{"measures":["new_members.temple_recommend"],"weeks":12,"includeCurrent":false}' />
</div>
<div class="tile">
<MissionChart type="tile" :height="140" :colors="['#6656c9']" :query='{"measures":["new_members.calling"],"weeks":12,"includeCurrent":false}' />
</div>
<div class="tile">
<MissionChart type="tile" :height="140" :colors="['#6656c9']" :query='{"measures":["new_members.aaronic_priesthood"],"weeks":12,"includeCurrent":false}' />
</div>
<div class="tile">
<MissionChart type="tile" :height="140" :colors="['#6656c9']" :query='{"measures":["new_members.melchizedek_priesthood"],"weeks":12,"includeCurrent":false}' />
</div>
</div>

<div class="footnote">Counted only from the people companionships add to their weekly plans in Weekly Planning: a 0 means no one has been added yet, not that no one is there.</div>

<!--
- These tiles count the new members on the companionships' weekly plans in the last finished week. They never show names or notes.
- The small line under each number shows the last twelve weeks. The numbers grow as companionships add the people they teach to their plans in Weekly Planning.
- Few people are on the weekly plans yet, so these tiles may show 0 for now. A 0 means not recorded yet, not that no one is progressing.
- The priesthood questions are for brethren; sisters and children are counted as not applicable there.
- A question to counsel about: which new member needs a calling, a temple recommend interview or a ministering friend this week?
-->

---

<div class="kicker">The covenant path · counts, never names</div>

# Friends preparing for baptism

<p class="lead">Friends with a baptismal date soon, and friends at church, are the ones to love and help most this week.</p>

<div class="grid grid-cols-2 gap-4">
<div class="tile">
<MissionChart type="tile" :height="140" :colors="['#6656c9']" :query='{"measures":["baptismal_date_friends.total"],"weeks":12,"includeCurrent":false}' />
</div>
<div class="tile">
<MissionChart type="tile" :height="140" :colors="['#6656c9']" :query='{"measures":["baptismal_date_friends.next_4_weeks"],"weeks":12,"includeCurrent":false}' />
</div>
<div class="tile">
<MissionChart type="tile" :height="140" :colors="['#6656c9']" :query='{"measures":["baptismal_date_friends.at_church"],"weeks":12,"includeCurrent":false}' />
</div>
<div class="tile">
<MissionChart type="tile" :height="140" :colors="['#6656c9']" :query='{"measures":["high_potentials.total"],"weeks":12,"includeCurrent":false}' />
</div>
</div>

<div class="footnote">Counted only from the people companionships add to their weekly plans in Weekly Planning: a 0 means no one has been added yet, not that no one is there.</div>

<!--
- These tiles count the friends on the weekly plans in the last finished week: friends with a baptismal date, those whose date is within the next four weeks, those with a date who came to church, and high-potential friends.
- Counts only, never names. For a single area, numbers below three are hidden elsewhere; here we see the whole mission.
- Few friends are on the weekly plans yet, so these tiles may show 0 for now. A 0 means not recorded yet, not that no one is preparing.
- A question to counsel about: who could sit with these friends at church, and which of them needs a baptismal interview soon?
-->

---
routeAlias: districts
---

<div class="kicker">Districts · the last four finished weeks</div>

# Districts to help first

<p class="lead">The districts furthest from the goals they set, lowest first: a call to their district leader, to listen and to help, is the next step.</p>

<div class="grid grid-cols-2 gap-8">
<div class="min-w-0">
<MissionChart type="bar" horizontal title="New people being taught" show-values :height="352" :decimals="0" :query='{"measures":["friends_found.actual","friends_found.previous_goal"],"level":"district","by":"unit","weeks":4,"includeCurrent":false,"transform":"pct_of_goal","sort":"asc","top":8,"audience":"stewardship"}' />
</div>
<div class="min-w-0">
<MissionChart type="bar" horizontal title="Sacrament attendance" show-values :height="352" :colors="['#2a5f99']" :decimals="0" :query='{"measures":["sacrament_attendance.actual","sacrament_attendance.previous_goal"],"level":"district","by":"unit","weeks":4,"includeCurrent":false,"transform":"pct_of_goal","sort":"asc","top":8,"audience":"stewardship"}' />
</div>
</div>

<!--
- The eight districts with the lowest share of their own goals over the last four finished weeks, lowest at the top. Weeks without a goal are left out.
- This is not a ranking of people. A district below the line may be new, may have lost a companionship to transfers, or may be facing something we do not see.
- The next step is love: a call to the district leader, a question about how we can help, and a plan to follow up.
-->

---

<div class="kicker">Mission Dashboard · for the Assistants, the President and the data office</div>

# Change this dashboard

<div class="grid grid-cols-[1fr_300px] gap-10 items-start mt-6">
<div class="space-y-4 text-[0.95rem] leading-6">
<div class="flex gap-4"><span class="step">1</span><div><b>Open the editor.</b> Press <b>E</b> or the pencil in the corner. The dashboard opens in the presentation editor.</div></div>
<div class="flex gap-4"><span class="step">2</span><div><b>Change a chart.</b> Click a chart and choose <b>Edit chart</b>: another key indicator, more weeks, a straight or curved trend line, other colours. <b>Add chart</b> makes a new one.</div></div>
<div class="flex gap-4"><span class="step">3</span><div><b>Publish.</b> Changes are published on their own after a moment; <b>Publish now</b> shows them at once. The Dashboards button always opens the newest version.</div></div>
</div>
<div class="text-[0.9rem] leading-6 border-l-2 border-[#087f8c]/40 dark:border-[#5cc6cf]/40 pl-5">

**People before numbers**

Every number here is someone the Lord knows by name. Let the charts lead us to counsel together, to plan in faith and to minister one by one.

</div>
</div>

<div class="footnote mt-8">Please keep the name <b>Mission Dashboard</b>, and do not delete it or use Manage access on it: the Dashboards button opens this presentation by its name, for the Assistants, the President and the data office only.</div>

<!--
- Only the Assistants, the President and the data office see this dashboard, and only they can change it.
- Keep its name, Mission Dashboard, and leave its access as it is (managers only). The Dashboards button in the portal opens it by that name: if it is renamed or deleted, Dashboards shows an error until it is renamed back to exactly "Mission Dashboard" or installed again.
- To change a chart, open the editor, click the chart and choose Edit chart. The numbers stay counts from the weekly plans; no names or notes can appear.
-->

