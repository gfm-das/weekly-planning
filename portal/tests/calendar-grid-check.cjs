// Round 13, task 20: the calendar's month/week grid and the deck link. Runs the real day arithmetic of
// portal/calendar-grid.js, and reads calendar.html and the 14 catalogs as text (no browser here).
// Run: node portal/tests/calendar-grid-check.cjs
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const portal = path.join(__dirname, '..');
const read = name => fs.readFileSync(path.join(portal, name), 'utf8').replace(/\r\n/g, '\n');
const G = require(path.join(portal, 'calendar-grid.js'));
const page = read('calendar.html');
let passed = 0;
const ok = (value, message) => { assert.ok(value, message); passed++; };
const eq = (a, b, message) => { assert.deepEqual(a, b, message); passed++; };

// ---- Month grid ----------------------------------------------------------------------------------------------------
{
  const weeks = G.monthWeeks(2026, 10); // October 2026 starts on a Thursday
  eq(weeks.length, 5, 'October 2026 needs five rows');
  ok(weeks.every(w => w.length === 7), 'every row has seven days');
  eq(weeks[0][0].key, '2026-09-28', 'the grid starts on the Monday before the 1st');
  eq(weeks[0][3], { key: '2026-10-01', day: 1, month: 10, inMonth: true }, 'the 1st is a Thursday');
  eq(weeks[0].slice(0, 3).map(d => d.inMonth), [false, false, false], 'the days before are grey');
  eq(weeks[4][6].key, '2026-11-01', 'the last row ends on Sunday 1 Nov');
  eq(weeks[4][6].inMonth, false, 'and it is grey');
  eq(weeks.flat().filter(d => d.inMonth).length, 31, 'all 31 days are in');
  // February 2027: 28 days starting on a Monday: exactly four rows.
  eq(G.monthWeeks(2027, 2).length, 4, 'a four-row February');
  // A month that needs six rows (March 2025 starts on a Saturday).
  eq(G.monthWeeks(2025, 3).length, 6, 'a six-row month');
  // A leap day and the year change.
  ok(G.monthWeeks(2028, 2).flat().some(d => d.key === '2028-02-29' && d.inMonth), 'leap day');
  eq(G.monthWeeks(2026, 12).at(-1).at(-1).key, '2027-01-03', 'December runs into January');
  // Summer time cannot shift a day: every row is seven consecutive days.
  for (const [y, m] of [[2026, 3], [2026, 10], [2027, 3], [2027, 10]]) {
    const days = G.monthWeeks(y, m).flat();
    ok(days.every((d, i) => i === 0 || d.key === G.addDays(days[i - 1].key, 1)), `consecutive days in ${y}-${m}`);
  }
  // Weeks may start on Sunday if WEEK_START is changed in the call.
  eq(G.monthWeeks(2026, 10, 0)[0][0].key, '2026-09-27', 'Sunday start');
  eq(G.WEEK_START, 1, 'Monday is the default week start');
}

// ---- Week grid, moving, ranges ------------------------------------------------------------------------------------
{
  eq(G.weekDays('2026-10-14').map(d => d.key), ['2026-10-12', '2026-10-13', '2026-10-14', '2026-10-15', '2026-10-16', '2026-10-17', '2026-10-18'], 'Monday 12 to Sunday 18 Oct');
  eq(G.weekDays('2026-10-18')[0].key, '2026-10-12', 'a Sunday belongs to the week before');
  eq(G.shift('week', '2026-10-14', 1), '2026-10-21', 'a week on');
  eq(G.shift('week', '2026-10-14', -3), '2026-09-23', 'three weeks back');
  eq(G.shift('month', '2026-10-31', 1), '2026-11-30', 'a month on keeps the day where it exists, else the last day');
  eq(G.shift('month', '2026-01-31', 1), '2026-02-28', 'February');
  eq(G.shift('month', '2026-12-15', 1), '2027-01-15', 'into the next year');
  eq(G.shift('month', '2026-01-15', -1), '2025-12-15', 'back into the last year');
  eq(G.range('week', '2026-10-14'), { from: '2026-10-12', to: '2026-10-18' }, 'week range');
  eq(G.range('month', '2026-10-14'), { from: '2026-09-28', to: '2026-11-01' }, 'month range includes the grey days');
  const span = (new Date(G.range('month', '2026-03-10').to) - new Date(G.range('month', '2026-03-10').from)) / 86400000;
  ok(span < 366, 'a grid never asks for more than the API allows (one year)');
  eq(G.weekdayIndex('2026-10-12'), 0, 'Monday is column 0');
  eq(G.weekdayIndex('2026-10-18'), 6, 'Sunday is column 6');
}

// ---- Events on days, in the mission's time zone ---------------------------------------------------------------------
{
  const berlin = 'Europe/Berlin';
  // 22:30 UTC on 11 Oct is 00:30 on 12 Oct in Berlin (summer time, UTC+2).
  eq(G.dayKey('2026-10-11T22:30:00Z', berlin), '2026-10-12', 'the day is the Berlin day, not the UTC day');
  eq(G.dayKey('2026-10-11T22:30:00Z', 'UTC'), '2026-10-11', 'another zone, another day');
  eq(G.dayKey('2026-12-31T23:30:00Z', berlin), '2027-01-01', 'the new year in winter time');
  const events = [
    { title: 'late', starts_at: '2026-10-12T17:00:00Z', ends_at: '2026-10-12T18:00:00Z' },
    { title: 'early', starts_at: '2026-10-12T05:00:00Z', ends_at: '2026-10-12T06:00:00Z' },
    { title: 'overnight', starts_at: '2026-10-13T20:00:00Z', ends_at: '2026-10-13T23:30:00Z' }, // 22:00 to 01:30 Berlin
    { title: 'ends at midnight', starts_at: '2026-10-14T20:00:00Z', ends_at: '2026-10-14T22:00:00Z' }, // 22:00 to 00:00 Berlin
  ];
  const days = G.groupByDay(events, berlin);
  eq(days.get('2026-10-12').map(x => x.event.title), ['early', 'late'], 'earliest first');
  eq(days.get('2026-10-12').map(x => x.index), [1, 0], 'the index finds the event again');
  eq([...days.keys()].sort(), ['2026-10-12', '2026-10-13', '2026-10-14'], 'the days with events');
  ok(days.get('2026-10-13').some(x => x.event.title === 'overnight'), 'an overnight meeting is on its first day');
  ok(!days.has('2026-10-15'), 'a meeting that ends exactly at midnight is not on the next day');
  // Not more than 31 days for one event.
  const long = G.groupByDay([{ starts_at: '2026-01-01T10:00:00Z', ends_at: '2026-12-31T10:00:00Z' }], berlin);
  eq(long.size, 31, 'a very long event is cut at 31 days');
  eq(G.groupByDay([], berlin).size, 0, 'no events');
}

// ---- Deck links: only this portal's own presentations ---------------------------------------------------------------
{
  eq(G.deckPath('/p/mmm/'), '/p/mmm/', 'a deck path');
  eq(G.deckPath('/p/zoko-2026/'), '/p/zoko-2026/', 'a deck path with digits and a hyphen');
  for (const bad of ['https://example.org/p/mmm/', '//evil.example/p/mmm/', 'javascript:alert(1)', '/p/mmm', '/p/mmm/x', '/p/MMM/', '/p/../x/', '/edit/mmm/', '/p/mmm/?a=1', 'mmm', '', null, undefined, '/p/' + 'a'.repeat(100) + '/']) {
    eq(G.deckPath(bad), '', 'refused: ' + bad);
  }
  eq(G.deckHref('/p/mmm/', 'http://192.0.2.10:3030'), 'http://192.0.2.10:3030/p/mmm/', 'opens on the Presentations address');
  eq(G.deckHref('/p/mmm/', 'https://presentations.example.org/'), 'https://presentations.example.org/p/mmm/', 'a trailing slash is dropped');
  eq(G.deckHref('/p/mmm/', ''), '/p/mmm/', 'without the address the relative path stays');
  eq(G.deckHref('/p/mmm/', 'javascript:alert(1)'), '/p/mmm/', 'a base that is not http(s) is ignored');
  eq(G.deckHref('https://evil.example/', 'http://192.0.2.10:3030'), '', 'a web address never becomes a link');
}

// ---- The page ------------------------------------------------------------------------------------------------------
{
  ok(/<script src="calendar-grid\.js"><\/script>/.test(page), 'the page loads calendar-grid.js');
  ok(page.indexOf('calendar-grid.js') < page.indexOf('<script src="portal-client.js">'), 'before the page script');
  for (const id of ['viewList', 'viewMonth', 'viewWeek', 'periodNav', 'prevPeriod', 'nextPeriod', 'todayPeriod', 'periodTitle', 'grid', 'dayDialog', 'dayEvents', 'dayNew', 'closeDay', 'deck', 'events', 'listToolbar']) {
    ok(page.includes(`id="${id}"`), 'has #' + id);
  }
  ok(/id="viewList"[^>]*aria-pressed="true"/.test(page), 'the list view is the default (the original page stays as it was)');
  ok(/role="group" aria-label="Calendar view"/.test(page), 'the view switch is a labelled group');
  ok(/aria-live="polite"/.test(page), 'the period title is announced');
  // Keyboard: one Tab stop in the grid (roving tabindex), arrows, Home/End, Page keys, labels on the day buttons.
  ok(/tabindex="\$\{d\.key === focusKey \? 0 : -1\}"/.test(page), 'roving tab stop');
  for (const key of ['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown', 'Home', 'End']) ok(page.includes(key + ':'), 'handles ' + key);
  ok(/direction === "rtl"/.test(page), 'left/right follow the page direction');
  ok(/aria-current="date"/.test(page), 'today is marked');
  ok(/<th scope="col"/.test(page), 'weekday headings are column headers');
  ok(/scope: ?"col"|<th scope="col" abbr=/.test(page), 'with their long name');
  // Rights: the grid asks the same endpoint; nothing here can add rights. Editors-only things still hang on can_edit.
  ok((page.match(/portalAPI\(`events\?start=/g) || []).length === 1, 'one request for the events, shared by every view');
  ok(/canEditNow = canEdit/.test(page) && /canEditNow \? "" : "none"/.test(page), 'the new-event button of the day dialog follows can_edit');
  ok(/eventActions\(e, index\)/.test(page) && /const actions = canEdit \?/.test(page), 'edit and delete buttons only for editors');
  // The deck link
  ok(/deck_link: \$\("deck"\)\.value/.test(page), 'the editor sends deck_link');
  ok(/\$\("deck"\)\.value = event\?\.deck_link \|\| ""/.test(page), 'and shows the stored one');
  ok(/G\.deckHref\(e\.deck_link, deckBase\(\)\)/.test(page), 'the event shows the link through deckHref (relative deck paths only)');
  ok(/target="_blank" rel="noopener">Open presentation/.test(page), 'opens in a new tab without opener');
  ok(!/innerHTML[^;]*deck_link/.test(page.replace(/G\.deckHref\(e\.deck_link/g, '')), 'the raw deck_link is never put into the page');
  // Layout: phone, right to left, dark mode
  ok(/@media \(max-width: 700px\)/.test(page), 'a phone layout');
  ok(/\.cal-grid\.week, \.cal-grid\.week tbody/.test(page), 'the week stacks into a list on a phone');
  ok(/min-height: 44px/.test(page), 'touch targets of 44 px');
  ok(/html\[dir="rtl"\] \.arrow/.test(page), 'the arrows turn in right-to-left languages');
  ok(/border-inline-end/.test(page) && /margin-inline-end/.test(page) && /text-align: start/.test(page), 'logical (direction-aware) properties');
  ok(!/margin-left|margin-right|padding-left|padding-right|text-align: left|text-align: right|float: ?(left|right)/.test(page.split('<style>')[1].split('</style>')[0]), 'no left/right only styling in the new styles');
  ok(/\[data-theme="dark"\] \.chip/.test(page), 'dark mode colours');
  ok(/outline: 3px solid/.test(page), 'a visible focus ring');
  ok(/prefers-reduced-motion|transition|animation/.test(page) === false, 'no motion to switch off');
  ok(/mission-i18n-change/.test(page), 'the grid is redrawn when the language changes');
  // The per-person convenience is kept safely
  ok(/try \{\s*const saved = localStorage\.getItem\("calendar_view"\)/.test(page) && /localStorage\.setItem\("calendar_view", view\);\s*\} catch/.test(page), 'the chosen view is remembered, guarded');
  // The old wording hook (portal-api/tests/test_wording.py reads the confirm questions) is untouched
  ok(page.includes('title: "Delete which events?"') && page.includes('title: "Delete this event?"') && page.includes('title: "Remove this attachment?"'), 'confirm questions unchanged');
}

// ---- Texts: 14 catalogs --------------------------------------------------------------------------------------------
{
  const codes = ['en', 'de', 'es', 'fr', 'pt', 'uk', 'ru', 'it', 'tr', 'fa', 'ro', 'sv', 'da', 'ar'];
  const keys = ['viewList', 'viewMonth', 'viewWeek', 'viewSwitch', 'previous', 'next', 'today', 'gridLabel', 'dayCount', 'noEventsDay', 'moreEvents', 'deckLink', 'deckLinkHint', 'openDeck', 'deckLinkInvalid'].map(k => 'calendar.' + k);
  const en = JSON.parse(read('i18n/en.json'));
  for (const code of codes) {
    const raw = read(`i18n/${code}.json`);
    const catalog = JSON.parse(raw);
    for (const key of keys) {
      ok(typeof catalog[key] === 'string' && catalog[key].length > 0, `${code}: ${key}`);
      const names = s => (s.match(/\{\w+\}/g) || []).sort().join(',');
      eq(names(catalog[key]), names(en[key]), `${code}: ${key} keeps its {values}`);
      if (code !== 'en') ok(!/^\s|\s$/.test(catalog[key]), `${code}: ${key} has no stray spaces`);
    }
    // The block is in one piece, so other branches' blocks and this one do not collide.
    const order = Object.keys(catalog);
    const first = order.indexOf(keys[0]);
    eq(order.slice(first, first + keys.length), keys, `${code}: the keys form one block`);
    // (It was once required to be the LAST block; later branches append their own blocks after it, so only "one piece" is checked.)
    ok(!raw.includes('\u0000'), code + ': no stray bytes');
  }
  // The texts in the page are the English catalog texts exactly (that is how the page is translated).
  const texts = { 'List': 'viewList', 'Month': 'viewMonth', 'Week': 'viewWeek', 'Previous': 'previous', 'Next': 'next', 'Today': 'today' };
  for (const [text, key] of Object.entries(texts)) {
    eq(en['calendar.' + key], text, `the English text of calendar.${key}`);
    ok(page.includes(`>${text}</`), `the page shows "${text}"`);
  }
  ok(page.includes(en['calendar.deckLinkHint']), 'the deck hint is the catalog text');
  ok(page.includes('Open presentation ↗') && en['calendar.openDeck'] === 'Open presentation ↗', 'the link text');
  ok(page.includes('No events on this day.') && en['calendar.noEventsDay'] === 'No events on this day.', 'the empty-day text');
  ok(page.includes('"{date} · Events: {count}"') && en['calendar.dayCount'] === '{date} · Events: {count}', 'the day label');
  // The server's refusal reaches the person in their language.
  const api = fs.readFileSync(path.join(portal, '..', 'portal-api', 'app.py'), 'utf8');
  ok(api.includes(en['calendar.deckLinkInvalid']), "the API's refusal text is the catalog text");
}

console.log(`calendar grid and deck link: ${passed} checks passed (days of a month and week, time zone, deck path rules, page structure, keyboard, phone, right to left, 14 catalogs)`);
