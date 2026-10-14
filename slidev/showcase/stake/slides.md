---
theme: default
title: "Stake coordination"
colorSchema: light
fonts:
  provider: none
  sans: Montserrat
htmlAttrs:
  lang: en
  dir: ltr
layout: gfm-freeform
---

<MmmCover line-1="Frankfurt Stake Monthly Coordination Meeting" />

---
layout: gfm-freeform
---

<MmmFrame heading="Baptisms" tone="cyan" corners="a" dark no-footer footer-lead="Supporting Missionaries in" footer-faith="Faith," footer-hope="Hope," footer-charity="&amp; Charity:" verse="Moroni 10: 20-21">
<MmmTrend x="55" y="100" w="840" h="440" title="" :labels='["Actual","Goal"]' :colors='["#3d8bef","#e0343c"]' goal trend :query='{"measures":["baptisms_confirmations.actual","baptisms_confirmations.previous_goal"],"weeks":26,"includeCurrent":false}' />
<MmmPair x="945" y="190" w="130" labels="Actual|Goal" :weeks="4" tag="Manual" :query='{"measures":["baptisms_confirmations.actual","baptisms_confirmations.previous_goal"],"weeks":4,"includeCurrent":false}' />
</MmmFrame>

<!--
The numbers on this slide load live from the weekly plans when the slide opens (the last finished week). Say what they mean for the friends we teach, then counsel together.
-->

---
layout: gfm-freeform
---

<MmmFrame heading="Follow-up Lessons" tone="cyan" corners="a" dark no-footer footer-lead="Supporting Missionaries in" footer-faith="Faith," footer-hope="Hope," footer-charity="&amp; Charity:" verse="Moroni 10: 20-21">
<MmmTrend x="55" y="100" w="840" h="440" title="" :labels='["Actual","Goal"]' :colors='["#3d8bef","#e0343c"]' goal trend :query='{"measures":["follow_up_lessons.actual","follow_up_lessons.goal"],"weeks":26,"includeCurrent":false}' />
<MmmPair x="945" y="190" w="130" labels="Actual|Goal" :weeks="4" tag="Manual" :query='{"measures":["follow_up_lessons.actual","follow_up_lessons.goal"],"weeks":4,"includeCurrent":false}' />
</MmmFrame>

<!--
The numbers on this slide load live from the weekly plans when the slide opens (the last finished week). Say what they mean for the friends we teach, then counsel together.
-->

---
layout: gfm-freeform
---

<MmmFrame heading="Lessons with Member" tone="cyan" corners="a" dark no-footer footer-lead="Supporting Missionaries in" footer-faith="Faith," footer-hope="Hope," footer-charity="&amp; Charity:" verse="Moroni 10: 20-21">
<MmmTrend x="55" y="100" w="840" h="440" title="" :labels='["Actual","Goal"]' :colors='["#3d8bef","#e0343c"]' goal trend :query='{"measures":["members_at_lessons.actual","members_at_lessons.previous_goal"],"weeks":26,"includeCurrent":false}' />
<MmmPair x="945" y="190" w="130" labels="Actual|Goal" :weeks="4" tag="Manual" :query='{"measures":["members_at_lessons.actual","members_at_lessons.previous_goal"],"weeks":4,"includeCurrent":false}' />
</MmmFrame>

<!--
The numbers on this slide load live from the weekly plans when the slide opens (the last finished week). Say what they mean for the friends we teach, then counsel together.
-->

---
layout: gfm-freeform
---

<MmmFrame heading="Member Present" tone="cyan" corners="a" dark no-footer footer-lead="Supporting Missionaries in" footer-faith="Faith," footer-hope="Hope," footer-charity="&amp; Charity:" verse="Moroni 10: 20-21">
<MmmPair x="170" y="150" w="170" labels="Follow-up Lessons (Actual)|Goal" :weeks="4" :query='{"measures":["follow_up_lessons.actual","follow_up_lessons.goal"],"weeks":4,"includeCurrent":false}' />
<MmmPair x="430" y="150" w="170" labels="Lessons with Member (Actual)|Goal" :weeks="4" :query='{"measures":["members_at_lessons.actual","members_at_lessons.previous_goal"],"weeks":4,"includeCurrent":false}' />
<MmmGauge x="690" y="110" w="330" h="330" tone="cyan" title="% with Member" tag="Manual" mode="ratio" :target="0.55" placeholder :query='{"measures":["follow_up_lessons.actual","members_at_lessons.actual"],"weeks":4,"includeCurrent":false}' />
</MmmFrame>

<!--
The numbers on this slide load live from the weekly plans when the slide opens (the last finished week). Say what they mean for the friends we teach, then counsel together.

Places marked Manual are typed by hand: the portal does not hold that number yet, or shows no names in a chart. Type this week’s names or numbers before the meeting; the tag goes away when you delete the word placeholder from the piece.
-->

---
layout: gfm-freeform
---

<MmmFrame heading="Dinner Appointments / Youth Activities / Mini Missions" tone="cyan" corners="a" dark no-footer footer-lead="Supporting Missionaries in" footer-faith="Faith," footer-hope="Hope," footer-charity="&amp; Charity:" verse="Moroni 10: 20-21">
<MmmCard x="110" y="130" w="190" h="190" tone="cyan" title="Dinner Appointments" last-label="Last" goal-label="Goal" na-text="N/A" tag="Manual" mode="manual" placeholder no-bar no-pct value="" last="" goal="" />
<MmmCard x="480" y="130" w="190" h="190" tone="cyan" title="Youth Activities" last-label="Last" goal-label="Goal" na-text="N/A" tag="Manual" mode="manual" placeholder no-bar no-pct value="" last="" goal="" />
<MmmCard x="850" y="130" w="190" h="190" tone="cyan" title="Mini Missions" last-label="Last" goal-label="Goal" na-text="N/A" tag="Manual" mode="manual" placeholder no-bar no-pct value="" last="" goal="" />
</MmmFrame>

<!--
Places marked Manual are typed by hand: the portal does not hold that number yet, or shows no names in a chart. Type this week’s names or numbers before the meeting; the tag goes away when you delete the word placeholder from the piece.
-->

---
layout: gfm-freeform
---

<MmmFrame heading="Church Visitors" tone="cyan" corners="a" dark no-footer footer-lead="Supporting Missionaries in" footer-faith="Faith," footer-hope="Hope," footer-charity="&amp; Charity:" verse="Moroni 10: 20-21">
<MmmTrend x="55" y="100" w="840" h="440" title="" :labels='["Actual","Goal"]' :colors='["#3d8bef","#e0343c"]' goal trend :query='{"measures":["sacrament_attendance.actual","sacrament_attendance.previous_goal"],"weeks":26,"includeCurrent":false}' />
<MmmPair x="945" y="190" w="130" labels="Actual|Goal" :weeks="4" tag="Manual" :query='{"measures":["sacrament_attendance.actual","sacrament_attendance.previous_goal"],"weeks":4,"includeCurrent":false}' />
</MmmFrame>

<!--
The numbers on this slide load live from the weekly plans when the slide opens (the last finished week). Say what they mean for the friends we teach, then counsel together.
-->

---
layout: gfm-freeform
---

<MmmFrame heading="Stake Total" tone="cyan" corners="a" dark no-footer footer-lead="Supporting Missionaries in" footer-faith="Faith," footer-hope="Hope," footer-charity="&amp; Charity:" verse="Moroni 10: 20-21">
<MmmTable x="40" y="95" w="1072" h="470" dense :top="16" :headers='["Area","Follow-up Lessons","Lessons with Member","Baptisms","Baptismal Dates","Church Attendance","% with Member"]' :query='{"measures":["follow_up_lessons.actual","members_at_lessons.actual","baptisms_confirmations.actual","baptismal_dates.actual","sacrament_attendance.actual"],"level":"area","by":"unit","weeks":4,"includeCurrent":false}' />
</MmmFrame>

<!--
The numbers on this slide load live from the weekly plans when the slide opens (the last finished week). Say what they mean for the friends we teach, then counsel together.
-->

---
layout: gfm-freeform
---

<MmmFrame heading="New Members" tone="cyan" corners="a" dark no-footer footer-lead="Supporting Missionaries in" footer-faith="Faith," footer-hope="Hope," footer-charity="&amp; Charity:" verse="Moroni 10: 20-21">
<MmmManual x="30" y="95" w="1092" h="470" headers="Month|Name|Stake|How are they doing?|Discussed in Gemiko?|How will you support them?" rows="Type here|Type here|Stake|Type here|Type here|Type here;Type here|Type here|Stake|Type here|Type here|Type here;Type here|Type here|Stake|Type here|Type here|Type here" tag="Manual" placeholder :sorted="-1" />
</MmmFrame>

<!--
Places marked Manual are typed by hand: the portal does not hold that number yet, or shows no names in a chart. Type this week’s names or numbers before the meeting; the tag goes away when you delete the word placeholder from the piece.
-->
