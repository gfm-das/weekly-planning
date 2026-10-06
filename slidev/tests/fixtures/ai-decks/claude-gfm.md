---
theme: default
title: Weekly review
layout: gfm-cover
kicker: Germany Frankfurt Mission
footer: Week of October 5
fonts:
  provider: none
  sans: Inter
transition: fade
---

# This week in the mission

Key numbers, what they mean and what we do next

<!--
Welcome everyone. Today: the numbers, what they mean, and one invitation.
-->

---
layout: gfm-kpi-grid
heading: This week at a glance
kicker: Key indicators
note: The last finished week, against the goal set the week before
---

<GfmKpiGrid metrics="friends_found,baptismal_dates,sacrament_attendance" />

---
layout: gfm-chart-insight
heading: New people being taught
kicker: Trend
---

<MissionChart chart-id="t1" preset="trend" :height="330"
  :rows="['Week, Taught', 'Aug 3, 12', 'Aug 10, 15', 'Aug 17, 14', 'Aug 24, 19']" />

::right::

<GfmInsight>

Teaching rose three weeks in a row.

</GfmInsight>

<GfmBigNumber value="19" label="This week" change="+5 from last week" tone="good" />

---
layout: gfm-three-column
heading: Our three focuses
---

## Find

Invite one friend this week.

::middle::

## Teach

Plan the next lesson together.

::right::

## Invite

Ask for a clear commitment.

---
layout: gfm-chart-insight
heading: Contact rate by zone
---

<MissionChart chart-id="r1" preset="ranked-bar" :height="330"
  :rows="['Zone, Referrals Received, Successfully Contacted', 'Frankfurt, 40, 30', 'Mannheim, 25, 12']"
  :calc='[{"name":"Rate","formula":"[Successfully Contacted] / [Referrals Received]","format":"percent"}]'
  :shape='{"only":["Rate"]}' />

::right::

<GfmCallout title="Invitation" tone="info">Share this with one friend.</GfmCallout>

---
layout: gfm-hero
kicker: One question
---

# What will you invite someone to this week?
