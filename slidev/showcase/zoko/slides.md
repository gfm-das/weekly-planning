---
theme: default
title: "ZOKO zone conference"
colorSchema: light
fonts:
  provider: none
  sans: Montserrat
htmlAttrs:
  lang: en
  dir: ltr
layout: gfm-freeform
---

<MmmCover line-1="Zone name" below="The Numbers" picture-slot picture-text="Put a picture here" tag="Manual" />

<!--
Places marked Manual are typed by hand: the portal does not hold that number yet, or shows no names in a chart. Type this week’s names or numbers before the meeting; the tag goes away when you delete the word placeholder from the piece.
-->

---
layout: gfm-freeform
---

<MmmFrame heading="Key Indicators of Conversion" tone="green" corners="a" footer-lead="Supporting Missionaries in" footer-faith="Faith," footer-hope="Hope," footer-charity="&amp; Charity:" verse="Moroni 10: 20-21">
<MmmCard x="55" y="100" w="190" h="190" tone="green" title="Friends Found" last-label="Last" goal-label="Goal" na-text="N/A" tag="Manual" :query='{"measures":["friends_found.actual","friends_found.previous_goal"],"weeks":4,"includeCurrent":false}' />
<MmmCard x="335" y="100" w="190" h="190" tone="amber" title="Church Attendance" last-label="Last" goal-label="Goal" na-text="N/A" tag="Manual" :query='{"measures":["sacrament_attendance.actual","sacrament_attendance.previous_goal"],"weeks":4,"includeCurrent":false}' />
<MmmCard x="615" y="100" w="190" h="190" tone="red" title="Baptismal Dates" last-label="Last" goal-label="Goal" na-text="N/A" tag="Manual" :query='{"measures":["baptismal_dates.actual","baptismal_dates.previous_goal"],"weeks":4,"includeCurrent":false}' />
<MmmCard x="908" y="100" w="190" h="190" tone="cyan" title="Baptisms" last-label="Last" goal-label="Goal" na-text="N/A" tag="Manual" :query='{"measures":["baptisms_confirmations.actual","baptisms_confirmations.previous_goal"],"weeks":4,"includeCurrent":false}' />
<MmmTrend x="55" y="325" w="660" h="250" title="Last 90 Days" :labels='["Friends Found","Church Attendance","First Time First Week Attendance"]' :colors='["#4da580","#ffa90a","#ffe600"]'  :query='{"measures":["friends_found.actual","sacrament_attendance.actual","first_time_sacrament.actual"],"weeks":13,"includeCurrent":false}' />
<MmmGauge x="735" y="325" w="362" h="250" tone="yellow" title="First Time First Week Attendance" tag="Manual" mode="value" :max="30" :query='{"measures":["first_time_sacrament.actual"],"weeks":4,"includeCurrent":false}' />
</MmmFrame>

<!--
The numbers on this slide load live from the weekly plans when the slide opens (the last finished week). Say what they mean for the friends we teach, then counsel together.
-->

---
layout: gfm-freeform
---

<MmmFrame heading="Referral Rates" tone="green" corners="b" footer-lead="Supporting Missionaries in" footer-faith="Faith," footer-hope="Hope," footer-charity="&amp; Charity:" verse="Moroni 10: 20-21">
<MmmGauge x="178" y="82" w="362" h="235" tone="green" title="Contact Rate" tag="Manual" mode="manual" :max="1" placeholder />
<MmmGauge x="634" y="82" w="362" h="235" tone="cyan" title="Teaching Rate" tag="Manual" mode="manual" :max="1" placeholder />
<MmmSlot x="55" y="335" w="1047" h="240" kind="image" empty="Paste the referral trend picture here" tag="Manual" />
</MmmFrame>

<!--
Places marked Manual are typed by hand: the portal does not hold that number yet, or shows no names in a chart. Type this week’s names or numbers before the meeting; the tag goes away when you delete the word placeholder from the piece.
-->

---
layout: gfm-freeform
---

<MmmFrame heading="Baptismal Goal" tone="cyan" corners="b" footer-lead="Supporting Missionaries in" footer-faith="Faith," footer-hope="Hope," footer-charity="&amp; Charity:" verse="Moroni 10: 20-21">
<MmmCard x="290" y="108" w="190" h="190" tone="cyan" title="This Month Actual" last-label="Last" goal-label="Goal" na-text="N/A" tag="Manual" mode="period" period="month" :digits="0" goal="" hide-goal last-at="right" no-bar no-pct footer-text="Zone" :query='{"measures":["baptisms_confirmations.actual"],"weeks":30,"includeCurrent":false}' />
<MmmCard x="630" y="108" w="190" h="190" tone="cyan" title="This Quarter" last-label="Last" goal-label="Goal" na-text="N/A" tag="Manual" mode="manual" :digits="0" placeholder hide-last goal-at="top" bar-label="Mission" footer-text="" value="" goal="" last="" />
<MmmTrend x="55" y="325" w="665" h="250" title="Zone Baptisms this Year" :labels='["Baptisms"]' :colors='["#4dd0e1"]' values :legend="false" :query='{"measures":["baptisms_confirmations.actual"],"weeks":42,"includeCurrent":false,"transform":"cumulative"}' />
<MmmGauge x="738" y="325" w="362" h="250" tone="cyan" title="Percent of the year done" tag="Manual" mode="year" />
</MmmFrame>

<!--
The numbers on this slide load live from the weekly plans when the slide opens (the last finished week). Say what they mean for the friends we teach, then counsel together.

Places marked Manual are typed by hand: the portal does not hold that number yet, or shows no names in a chart. Type this week’s names or numbers before the meeting; the tag goes away when you delete the word placeholder from the piece.
-->

---
layout: gfm-freeform
---

<MmmFrame heading="Coming This Week" tone="red" corners="c" footer-lead="Supporting Missionaries in" footer-faith="Faith," footer-hope="Hope," footer-charity="&amp; Charity:" verse="Moroni 10: 20-21">
<MmmManual x="28" y="90" w="1096" h="485" headers="Friend|Baptismal Date|Companionship|Unit" rows="Type here|Type here|Type here|Type here;Type here|Type here|Type here|Type here;Type here|Type here|Type here|Type here" tag="Manual" placeholder  />
</MmmFrame>

<!--
Places marked Manual are typed by hand: the portal does not hold that number yet, or shows no names in a chart. Type this week’s names or numbers before the meeting; the tag goes away when you delete the word placeholder from the piece.
-->

---
layout: gfm-freeform
---

<MmmFrame heading="On Date" tone="red" corners="c" footer-lead="Supporting Missionaries in" footer-faith="Faith," footer-hope="Hope," footer-charity="&amp; Charity:" verse="Moroni 10: 20-21">
<MmmManual x="28" y="90" w="1096" h="485" headers="Friend|Baptismal Date|Companionship|Unit" rows="Type here|Type here|Type here|Type here;Type here|Type here|Type here|Type here;Type here|Type here|Type here|Type here" tag="Manual" placeholder goal="–" goal-label="Goal" />
</MmmFrame>

<!--
Places marked Manual are typed by hand: the portal does not hold that number yet, or shows no names in a chart. Type this week’s names or numbers before the meeting; the tag goes away when you delete the word placeholder from the piece.
-->

---
layout: gfm-freeform
---

<MmmFrame heading="Member Present" tone="green" corners="a" footer-lead="Supporting Missionaries in" footer-faith="Faith," footer-hope="Hope," footer-charity="&amp; Charity:" verse="Moroni 10: 20-21">
<MmmCard x="290" y="105" w="190" h="190" tone="green" title="Lessons with Member" last-label="Last" goal-label="Goal" na-text="N/A" tag="Manual" :query='{"measures":["members_at_lessons.actual","members_at_lessons.previous_goal"],"weeks":4,"includeCurrent":false}' />
<MmmCard x="690" y="110" w="190" h="190" tone="green" title="Follow-up Lessons" last-label="Last" goal-label="Goal" na-text="N/A" tag="Manual" mode="share" goal-at="top" hide-last target="–" :query='{"measures":["follow_up_lessons.actual","members_at_lessons.actual"],"weeks":4,"includeCurrent":false}' />
<MmmTrend x="65" y="325" w="640" h="250" title="Last 90 Days" :labels='["Follow-up Lessons","Lessons with Member"]' :colors='["#d32f2f","#2e7d32"]'  :query='{"measures":["follow_up_lessons.actual","members_at_lessons.actual"],"weeks":13,"includeCurrent":false}' />
<MmmGauge x="712" y="325" w="362" h="250" tone="green" title="% with Member" tag="Manual" mode="ratio" :target="0.55" :query='{"measures":["follow_up_lessons.actual","members_at_lessons.actual"],"weeks":4,"includeCurrent":false}' />
</MmmFrame>

<!--
The numbers on this slide load live from the weekly plans when the slide opens (the last finished week). Say what they mean for the friends we teach, then counsel together.

Places marked Manual are typed by hand: the portal does not hold that number yet, or shows no names in a chart. Type this week’s names or numbers before the meeting; the tag goes away when you delete the word placeholder from the piece.
-->

---
layout: gfm-freeform
---

<MmmFrame heading="New Member Activity" tone="cyan" corners="b" footer-lead="Supporting Missionaries in" footer-faith="Faith," footer-hope="Hope," footer-charity="&amp; Charity:" verse="Moroni 10: 20-21">
<MmmCard x="180" y="98" w="190" h="190" tone="cyan" title="Church Attendance" last-label="Last" goal-label="Goal" na-text="N/A" tag="Manual" :query='{"measures":["new_member_sacrament.actual","new_member_sacrament.previous_goal"],"weeks":4,"includeCurrent":false}' />
<MmmGauge x="450" y="82" w="252" h="205" tone="cyan" title="% Active" tag="Manual" mode="manual" :max="1" placeholder />
<MmmCard x="803" y="98" w="190" h="190" tone="cyan" title="Total New Members" last-label="Last" goal-label="Goal" na-text="N/A" tag="Manual" mode="share" goal-at="top" hide-last target="–" bar-label="At Church" :query='{"measures":["new_members.total","new_members.at_church"],"weeks":1,"includeCurrent":false}' />
<MmmTable x="38" y="325" w="520" h="250" :headers='["Companionship","Total","Church?","At Church %"]' :top="6" :query='{"measures":["new_members.total","new_members.at_church"],"level":"area","by":"unit","weeks":1,"includeCurrent":false}' />
<MmmTrend x="595" y="325" w="520" h="250" title="Last 90 Days" :labels='["Total New Members","At Church"]' :colors='["#d32f2f","#2e7d32"]' trend :query='{"measures":["new_members.total","new_members.at_church"],"weeks":13,"includeCurrent":false}' />
</MmmFrame>

<!--
The numbers on this slide load live from the weekly plans when the slide opens (the last finished week). Say what they mean for the friends we teach, then counsel together.

Places marked Manual are typed by hand: the portal does not hold that number yet, or shows no names in a chart. Type this week’s names or numbers before the meeting; the tag goes away when you delete the word placeholder from the piece.
-->
