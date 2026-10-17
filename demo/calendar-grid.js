/* calendar-grid.js: the date arithmetic behind the month and week grid of calendar.html (round 13, task 20).
 *
 * Who uses it: calendar.html (loaded before its own script) and portal/tests/calendar-grid-check.cjs.
 * It only works out days: which days a month or week grid shows, which day an event falls on in the mission's time zone,
 * which dates to ask portal-api for, and where a deck link points. It reads no data and decides no rights: portal-api
 * still decides which events a person gets (the grid is just another way to draw the same answer).
 *
 * A "day key" is "2026-10-12" (year-month-day). Weeks start on Monday (the mission is in Germany); changing WEEK_START to
 * 0 would start them on Sunday. Everything is plain UTC arithmetic on the numbers of the key, so summer time cannot move
 * a day.
 */
(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.CalendarGrid = api;
})(typeof self !== 'undefined' ? self : this, function () {
  const WEEK_START = 1; // 1 = Monday
  const DAY = 86400000;

  const pad = (n) => String(n).padStart(2, '0');
  const toKey = (ms) => {
    const d = new Date(ms);
    return `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())}`;
  };
  const fromKey = (key) => {
    const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(key));
    if (!m) throw new Error('Not a day: ' + key);
    return Date.UTC(+m[1], +m[2] - 1, +m[3]);
  };
  const addDays = (key, n) => toKey(fromKey(key) + n * DAY);

  /** The day (key) a moment falls on in the given time zone. */
  function dayKey(moment, zone) {
    const text = new Intl.DateTimeFormat('sv-SE', { timeZone: zone, year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date(moment));
    return text; // "2026-10-12"
  }

  /** 0 (first column) to 6 for a day key: its place in the week. */
  const weekdayIndex = (key, weekStart = WEEK_START) => (new Date(fromKey(key)).getUTCDay() - weekStart + 7) % 7;

  /** The first day of the week that holds this day. */
  const weekStartOf = (key, weekStart = WEEK_START) => addDays(key, -weekdayIndex(key, weekStart));

  /** The seven days of the week that holds this day: [{key, day, month}] (day and month are numbers). */
  function weekDays(key, weekStart = WEEK_START) {
    const first = weekStartOf(key, weekStart);
    return Array.from({ length: 7 }, (_, i) => {
      const k = addDays(first, i);
      const d = new Date(fromKey(k));
      return { key: k, day: d.getUTCDate(), month: d.getUTCMonth() + 1 };
    });
  }

  /** The weeks a month grid shows (4 to 6 rows of 7): [[{key, day, month, inMonth}]]. month is 1 to 12. */
  function monthWeeks(year, month, weekStart = WEEK_START) {
    const firstOfMonth = `${year}-${pad(month)}-01`;
    const lastOfMonth = toKey(Date.UTC(year, month, 0));
    const weeks = [];
    for (let start = weekStartOf(firstOfMonth, weekStart); start <= lastOfMonth; start = addDays(start, 7)) {
      weeks.push(weekDays(start, weekStart).map((d) => ({ ...d, inMonth: d.key >= firstOfMonth && d.key <= lastOfMonth })));
    }
    return weeks;
  }

  /** The anchor day one month / one week on (n may be negative). A month step keeps the day number where it exists. */
  function shift(view, key, n) {
    if (view === 'week') return addDays(key, 7 * n);
    const d = new Date(fromKey(key));
    const target = new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth() + n, 1));
    const last = new Date(Date.UTC(target.getUTCFullYear(), target.getUTCMonth() + 1, 0)).getUTCDate();
    return toKey(Date.UTC(target.getUTCFullYear(), target.getUTCMonth(), Math.min(d.getUTCDate(), last)));
  }

  /** The first and last day (keys) a view shows around an anchor day: a month view includes the grey days of the
   * neighbouring months, because the grid shows them too. */
  function range(view, key, weekStart = WEEK_START) {
    if (view === 'week') {
      const days = weekDays(key, weekStart);
      return { from: days[0].key, to: days[6].key };
    }
    const d = new Date(fromKey(key));
    const weeks = monthWeeks(d.getUTCFullYear(), d.getUTCMonth() + 1, weekStart);
    return { from: weeks[0][0].key, to: weeks[weeks.length - 1][6].key };
  }

  /** The events by day: a Map of day key to the events on that day, earliest first. An event is listed on every day it
   * touches (a meeting past midnight is on both days), at most 31 days. `index` is kept so a click finds the event again. */
  function groupByDay(events, zone) {
    const days = new Map();
    events.forEach((event, index) => {
      const first = dayKey(event.starts_at, zone);
      let last = dayKey(new Date(Math.max(new Date(event.starts_at), new Date(event.ends_at) - 1)), zone);
      if (last < first) last = first;
      for (let key = first, n = 0; key <= last && n < 31; key = addDays(key, 1), n++) {
        if (!days.has(key)) days.set(key, []);
        days.get(key).push({ event, index });
      }
    });
    for (const list of days.values()) list.sort((a, b) => new Date(a.event.starts_at) - new Date(b.event.starts_at));
    return days;
  }

  /** A deck link as stored (/p/<deck>/), or '' when it is not one. The check portal-api and the database make, repeated
   * so the page never builds a link from anything else (a web address, another path, a script). */
  function deckPath(value) {
    const m = /^\/p\/([a-z0-9]+(?:-[a-z0-9]+)*)\/$/.exec(String(value || ''));
    return m && String(value).length <= 90 ? m[0] : '';
  }

  /** Where to open a deck link: on the Presentations deck address the portal shell knows (no trailing slash), or the path
   * itself when the page does not know it. '' when the link is not a deck path. */
  function deckHref(value, base) {
    const path = deckPath(value);
    if (!path) return '';
    const origin = String(base || '').replace(/\/+$/, '');
    return /^https?:\/\/[^\s/]+(:\d+)?$/.test(origin) ? origin + path : path;
  }

  return { WEEK_START, addDays, dayKey, weekdayIndex, weekStartOf, weekDays, monthWeeks, shift, range, groupByDay, deckPath, deckHref, fromKey, toKey };
});
