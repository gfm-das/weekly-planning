// Invented numbers for the demo decks. answerFor(query) returns what POST /api/charts/data answers in the real portal:
// { table: { labels, series: [{ name, values, role }] }, meta: { by } }. Everything here is made up.

// [typical weekly number, the goal that went with it]
const BASE = {
  'friends_found.actual': 46, 'friends_found.previous_goal': 52,
  'sacrament_attendance.actual': 318, 'sacrament_attendance.previous_goal': 335,
  'baptismal_dates.actual': 15, 'baptismal_dates.previous_goal': 17,
  'baptisms_confirmations.actual': 9, 'baptisms_confirmations.previous_goal': 11,
  'first_time_sacrament.actual': 24, 'first_time_sacrament.previous_goal': 30,
  'members_at_lessons.actual': 74, 'members_at_lessons.previous_goal': 82,
  'follow_up_lessons.actual': 128, 'follow_up_lessons.previous_goal': 140, 'follow_up_lessons.goal': 140,
  'new_member_sacrament.actual': 13, 'new_member_sacrament.previous_goal': 16,
  'new_members.total': 52, 'new_members.at_church': 34,
};
export const ZONES = ['Alpha', 'Beta', 'Gamma', 'Delta', 'Epsilon', 'Zeta'];
export const AREAS = [];
['Alpha', 'Beta', 'Gamma'].forEach(z => [1, 2, 3].forEach(d => ['a', 'b'].forEach(ch => AREAS.push(`${z} ${d}-${ch}`))));

function rand(seed) {
  let a = seed >>> 0;
  return () => { a = (a + 0x6D2B79F5) >>> 0; let t = a; t = Math.imul(t ^ (t >>> 15), t | 1); t ^= t + Math.imul(t ^ (t >>> 7), t | 61); return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
}
const hash = s => [...s].reduce((h, c) => (Math.imul(h, 31) + c.charCodeAt(0)) >>> 0, 7);
const iso = d => d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');

/** The Sundays of the last n complete weeks, oldest first. */
export function weekLabels(n) {
  const now = new Date(); now.setHours(12, 0, 0, 0);
  now.setDate(now.getDate() - now.getDay());
  return Array.from({ length: n }, (_, i) => { const d = new Date(now); d.setDate(d.getDate() - 7 * (n - i)); return iso(d); });
}

const isGoal = m => /\.(previous_goal|goal)$/.test(m);

function weekly(measure, n) {
  const base = BASE[measure] ?? 20, r = rand(hash(measure.replace('previous_goal', 'goal')));
  const goal = isGoal(measure);
  return Array.from({ length: n }, (_, i) => {
    const drift = 1 + 0.012 * (i - n);
    if (goal) return Math.max(0, Math.round(base * (0.94 + 0.12 * r()) * (1 + 0.006 * (i - n))));
    return Math.max(0, Math.round(base * drift * (0.82 + 0.34 * r())));
  });
}

export function answerFor(query) {
  if (!query || !Array.isArray(query.measures)) return null;
  const n = Math.max(1, query.weeks || 4);
  if (query.by === 'unit') {
    const labels = (query.level === 'area' ? AREAS : ZONES).slice();
    const series = query.measures.map(m => {
      const r = rand(hash(m + query.level));
      const total = (BASE[m] ?? 20) * n, share = total / labels.length;
      return { name: m, role: isGoal(m) ? 'goal' : 'actual', values: labels.map(() => Math.round(share * (0.4 + 1.2 * r()))) };
    });
    return { table: { labels, series }, meta: { by: 'unit' } };
  }
  const labels = weekLabels(n);
  const series = query.measures.map(m => {
    let values = weekly(m, n);
    if (query.transform === 'cumulative') { let s = 0; values = values.map(v => (s += v)); }
    return { name: m, role: isGoal(m) ? 'goal' : 'actual', values };
  });
  return { table: { labels, series }, meta: {} };
}

// Words that stand in for what a leader types by hand in the real decks ("Type here"). Invented names only.
export const PEOPLE = ['Elder Sample', 'Sister Demo', 'Friend Example', 'Elder Test', 'Sister Sample', 'Friend Demo'];
export function futureDate(i) { const d = new Date(); d.setDate(d.getDate() + 2 + i * 3); return d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short' }); }
