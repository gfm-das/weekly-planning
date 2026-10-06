---
theme: default
title: GFM layouts and components
layout: gfm-cover
kicker: Germany Frankfurt Mission
footer: Weekly review
fonts:
  provider: none
  sans: Inter
transition: fade
---

# This week in the mission

Key numbers, what they mean and what we do next

---
layout: gfm-kpi-grid
title: This week at a glance
kicker: Key indicators
note: The last finished week, against the goal set the week before
---

<GfmKpiGrid />

---
layout: gfm-chart-insight
title: New people being taught
kicker: Trend
---

<MissionChart :rows="['Week, Taught', 'W1, 31', 'W2, 36', 'W3, 33', 'W4, 41', 'W5, 47']" :option='{"series":[{"type":"bar"}]}' :height="330" />

::right::

<GfmInsight>

Teaching rose five weeks in a row.

</GfmInsight>

<GfmBigNumber value="47" label="This week" change="+6 from last week" tone="good" />

---
layout: gfm-comparison
title: Two zones
leftTitle: Frankfurt
rightTitle: Mannheim
---

<GfmComparison leftLabel="Last week" :leftValue="41" rightLabel="This week" :rightValue="47" />

::right::

<GfmProgress label="Baptismal dates" :value="31" :goal="40" />
<GfmProgress label="Sacrament attendance" :value="118" :goal="120" />

---
layout: gfm-three-column
title: Our three focuses
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
layout: gfm-section
kicker: Part 2
---

# Looking ahead

---
layout: gfm-hero
kicker: One question
---

# What will you invite someone to this week?

---
layout: gfm-image-message
kicker: Remember
imageSide: right
---

# By small and simple things

<GfmQuote author="Alma 37:6">Great things are brought to pass.</GfmQuote>

<GfmCallout title="Invitation" tone="info">Share this with one friend.</GfmCallout>

---
layout: gfm-full-chart
title: Full chart
caption: Source - the weekly plans
---

<MissionChart :rows="['Zone, Value', 'A, 31', 'B, 44', 'C, 27', 'D, 39']" :option='{"series":[{"type":"bar"}]}' :height="360" />

---
layout: gfm-two-chart
title: Two charts
---

<MissionChart :rows="['Week, Value', 'W1, 3', 'W2, 5', 'W3, 4']" :option='{"series":[{"type":"line"}]}' :height="300" />

::right::

<MissionChart :rows="['Zone, Value', 'A, 3', 'B, 5', 'C, 4']" :option='{"series":[{"type":"bar"}]}' :height="300" />

---
layout: gfm-freeform
---

<div class="p-10 text-2xl">A blank slide: drag things where you want them.</div>

---
layout: gfm-full-chart
title: A data story (click to advance)
caption: One chart, four steps - the same chart moves from step to step
---

<MissionChart chart-id="story" preset="trend" :height="330"
  :rows="['Week, Received, Attempted, Successful, Taught', 'W1, 12, 9, 6, 3', 'W2, 15, 11, 7, 4', 'W3, 14, 12, 9, 6', 'W4, 19, 14, 10, 7']"
  :story='[{"label":"Received","shape":{"only":["Received"]}},{"label":"Attempted","shape":{"only":["Received","Attempted"]}},{"label":"Successful","shape":{"only":["Received","Attempted","Successful"]}},{"label":"The funnel","preset":"funnel","shape":{}}]'
  storyTransition="morph" :storyDuration="700" />

---
layout: gfm-full-chart
title: A calculated field
caption: Successful contact rate = Successfully Contacted / Referrals Received
---

<MissionChart chart-id="calc" preset="ranked-bar" :height="330"
  :rows="['Zone, Referrals Received, Successfully Contacted', 'Frankfurt, 40, 30', 'Mannheim, 25, 12', 'Wiesbaden, 31, 25', 'Darmstadt, 18, 9']"
  :calc='[{"name":"Successful Contact Rate","formula":"[Successfully Contacted] / [Referrals Received]","format":"percent"}]'
  :shape='{"only":["Successful Contact Rate"]}' />
