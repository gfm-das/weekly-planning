// The presentation templates of the library: MMM MAIN, MMM Media, MMM Breakout rooms, ZOKO (zone conference) and Stake
// coordination, plus the blank presentation. "+ New Presentation" in the library lets the person pick one, and the
// language of its words (texts.mjs: 14 languages); createDeck() in deck-actions.mjs writes the result as the new deck's
// slides.md.
//
// What a template is: plain Markdown for Slidev, made of the Mmm* pieces of the GFM add-on (gfm-addon/components:
// MmmFrame, MmmCard, MmmGauge, MmmTrend, MmmTable, MmmManual, MmmChips, MmmSlot, MmmCover). Live numbers are
// `:query='{...}'` charts written in the slide as plain JSON, exactly like <MissionChart :query>, so the deck's
// "pinning" lets the leaders who open the deck see them, and a zone's deck shows only that zone's numbers (the
// portal decides by the deck's owner, zone-decks.mjs). A hand-typed place says so with `placeholder` (a "Manual" tag
// on screen): see docs/handoff/round13/presentations.md for the list.
// Who uses it: deck-actions.mjs (createDeck), manager-routes.mjs (GET /api/presentations/templates), the showcase decks
// (slidev/showcase/mmm-*), slidev/tests/mmm-templates.test.mjs.
// How it fits: no Slidev, no Vue, no I/O: strings in, a string out, so it is tested with plain Node.
import { LANGUAGES, LANGUAGE_INFO, text } from './texts.mjs';

export { LANGUAGES, LANGUAGE_INFO };

/** The templates the library offers, in this order. `blank` is the presentation "+ New Presentation" always made. */
export const TEMPLATE_IDS = ['blank', 'mmm-main', 'mmm-media', 'mmm-breakout', 'zoko', 'stake'];

/** English names and descriptions (the library shows them through the portal's translations: portal/i18n). */
export const TEMPLATE_INFO = {
  blank: { name: 'Blank presentation', description: 'A title slide and one empty slide.', zone: true, language: false },
  'mmm-main': { name: 'MMM MAIN', description: 'The Monday Morning Meeting: key indicators, baptismal goal, coming this week, members present, new members, temple and baptisms. Live from the weekly plans.', zone: false, language: true },
  'mmm-media': { name: 'MMM Media', description: 'The Monday Morning Meeting media part: places for videos and pictures with captions.', zone: false, language: true },
  'mmm-breakout': { name: 'MMM Breakout rooms', description: 'One section for each breakout room: topic, leader, notes, action items and report back. Topics are yours to change.', zone: false, language: true },
  zoko: { name: 'ZOKO zone conference', description: 'The zone conference numbers for one zone: key indicators, referral rates, baptismal goal, coming this week, members present, new members. Shows only the zone that owns the deck.', zone: true, language: true },
  stake: { name: 'Stake coordination', description: 'The monthly Stake coordination report: baptisms, follow-up lessons, lessons with a member, church visitors, totals by area and new members.', zone: false, language: true },
};

// ---- small writers ---------------------------------------------------------------------------------------------

const esc = value => String(value ?? '').replaceAll('&', '&amp;').replaceAll('"', '&quot;').replaceAll('<', '&lt;').replaceAll('>', '&gt;');
// A list written the way the pieces read it: "a|b|c".
// A list or object written as JSON inside single quotes: a straight apostrophe in a word becomes a typographic one.
const jsonAttr = value => JSON.stringify(value).replaceAll("'", '’');
const bar = list => list.map(item => String(item).replaceAll('|', '/').replaceAll(';', ',')).join('|');
// A query: the numbers, and what limits them. It is written as JSON in single quotes, which is what the portal's
// "pinning" looks for in the deck's slides.
const query = (measures, extra = {}) => `:query='${JSON.stringify({ measures, ...extra })}'`;
const kpi = id => [`${id}.actual`, `${id}.previous_goal`];
const FINISHED = { includeCurrent: false };

function noteBlock(lines) {
  const body = lines.filter(Boolean).join('\n\n').replaceAll('--', '- -');
  return body ? `<!--\n${body}\n-->` : '';
}

// One slide: its settings block, its content and its speaker notes (seen in the presenter view).
function slideText(content, notes = []) {
  return `layout: gfm-freeform\n---\n\n${content.trim()}\n${notes.length ? `\n${noteBlock(notes)}\n` : ''}`;
}

/** The headmatter and the slides joined: slide 1's settings come first, every later slide opens with its own block. */
function deckText(title, lang, slides) {
  const info = LANGUAGE_INFO[lang] || LANGUAGE_INFO.en;
  // Digits stay Western in Persian and Arabic, like the rest of the portal ("-u-nu-latn").
  const tag = lang === 'fa' || lang === 'ar' ? `${lang}-u-nu-latn` : lang;
  const head = `---\ntheme: default\ntitle: ${JSON.stringify(title)}\ncolorSchema: light\nfonts:\n  provider: none\n  sans: Montserrat\nhtmlAttrs:\n  lang: ${tag}\n  dir: ${info.dir}\n`;
  return head + slides.map((slide, i) => (i === 0 ? '' : '\n---\n') + slide).join('');
}

// ---- the pieces, with the template's words ---------------------------------------------------------------------

function words(lang) {
  const t = key => text(lang, key);
  const footer = `footer-lead="${esc(t('footerLead'))}" footer-faith="${esc(t('faith'))}" footer-hope="${esc(t('hope'))}" footer-charity="${esc(t('charity'))}" verse="${esc(t('verse'))}"`;
  const frame = (heading, tone, corners, inner, extra = '') => `<MmmFrame ${[`heading="${esc(heading)}"`, `tone="${tone}"`, `corners="${corners}"`, extra, footer].filter(Boolean).join(' ')}>\n${inner}\n</MmmFrame>`;
  const common = `last-label="${esc(t('last'))}" goal-label="${esc(t('goal'))}" na-text="${esc(t('na'))}" tag="${esc(t('manual'))}"`;
  const card = (x, y, title, tone, extra) => `<MmmCard x="${x}" y="${y}" w="190" h="190" tone="${tone}" title="${esc(title)}" ${common} ${extra} />`;
  const kpiCard = (x, y, title, tone, id) => card(x, y, title, tone, query(kpi(id), { weeks: 4, ...FINISHED }));
  const gauge = (x, y, w, h, title, tone, extra) => `<MmmGauge x="${x}" y="${y}" w="${w}" h="${h}" tone="${tone}" title="${esc(title)}" tag="${esc(t('manual'))}" ${extra} />`;
  const trend = (x, y, w, h, title, labels, colors, measures, extra = '', spec = {}) => `<MmmTrend x="${x}" y="${y}" w="${w}" h="${h}" title="${esc(title)}" :labels='${jsonAttr(labels)}' :colors='${jsonAttr(colors)}' ${extra} ${query(measures, { weeks: 13, ...FINISHED, ...spec })} />`;
  const manual = (x, y, w, h, headers, rows, extra = '') => `<MmmManual x="${x}" y="${y}" w="${w}" h="${h}" headers="${esc(bar(headers))}" rows="${esc(rows)}" tag="${esc(t('manual'))}" placeholder ${extra} />`;
  return { t, footer, frame, common, card, kpiCard, gauge, trend, manual };
}

// The first Key Indicators page (the same for the mission and for a zone): the four conversion cards, the 90 days and
// the First Time First Week gauge.
function keyIndicators(w, { gaugeMax, note }) {
  const { t } = w;
  const inner = [
    w.kpiCard(55, 100, t('friendsFound'), 'green', 'friends_found'),
    w.kpiCard(335, 100, t('churchAttendance'), 'amber', 'sacrament_attendance'),
    w.kpiCard(615, 100, t('baptismalDates'), 'red', 'baptismal_dates'),
    w.kpiCard(908, 100, t('baptisms'), 'cyan', 'baptisms_confirmations'),
    w.trend(55, 325, 660, 250, t('last90'), [t('friendsFound'), t('churchAttendance'), t('ftfw')], ['#4da580', '#ffa90a', '#ffe600'],
      ['friends_found.actual', 'sacrament_attendance.actual', 'first_time_sacrament.actual']),
    w.gauge(735, 325, 362, 250, t('ftfw'), 'yellow', `mode="value" :max="${gaugeMax}" ${query(['first_time_sacrament.actual'], { weeks: 4, ...FINISHED })}`),
  ].join('\n');
  return slideText(w.frame(t('keyIndicators'), 'green', 'a', inner), [t('noteLive'), note]);
}

function baptismalGoal(w, { zoneScoped, now }) {
  const { t } = w;
  const month = w.card(290, 108, t('thisMonth'), 'cyan',
    `mode="period" period="month" :digits="0" goal="" hide-goal last-at="right" ${zoneScoped ? 'no-bar no-pct' : ''} ${zoneScoped ? `footer-text="${esc(t('zoneLabel'))}"` : ''} ${query(['baptisms_confirmations.actual'], { weeks: 30, ...FINISHED })}`);
  const quarter = w.card(630, 108, t('thisQuarter'), 'cyan',
    zoneScoped
      ? `mode="manual" :digits="0" placeholder hide-last goal-at="top" bar-label="${esc(t('missionLabel'))}" footer-text="" value="" goal="" last=""`
      : `mode="period" period="quarter" :digits="0" placeholder goal="" hide-last goal-at="top" ${query(['baptisms_confirmations.actual'], { weeks: 30, ...FINISHED })}`);
  const weeksSoFar = weeksSince(now);
  const inner = [
    month, quarter,
    w.trend(55, 325, 665, 250, zoneScoped ? t('zoneBaptisms') : t('baptismsThisYear'), [t('baptisms')], ['#4dd0e1'], ['baptisms_confirmations.actual'], 'values :legend="false"', { weeks: weeksSoFar, transform: 'cumulative' }),
    w.gauge(738, 325, 362, 250, t('yearDone'), 'cyan', 'mode="year"'),
  ].join('\n');
  return slideText(w.frame(t('baptismalGoal'), 'cyan', 'b', inner), [t('noteLive'), t('noteManual')]);
}

function comingThisWeek(w, { heading, goal = '' }) {
  const { t } = w;
  const hint = t('typeHere');
  const rows = [0, 1, 2].map(() => bar([hint, hint, hint, hint])).join(';');
  const inner = w.manual(28, 90, 1096, 485, [t('friend'), t('baptismalDate'), t('companionship'), t('unit')], rows, goal ? `goal="${esc(goal)}" goal-label="${esc(t('goal'))}"` : '');
  return slideText(w.frame(heading, 'red', 'c', inner), [t('noteManual')]);
}

function memberPresent(w) {
  const { t } = w;
  const both = ['follow_up_lessons.actual', 'members_at_lessons.actual'];
  const inner = [
    w.card(290, 105, t('lessonsMember'), 'green', query(kpi('members_at_lessons'), { weeks: 4, ...FINISHED })),
    w.card(690, 110, t('followUp'), 'green', `mode="share" goal-at="top" hide-last target="–" ${query(both, { weeks: 4, ...FINISHED })}`),
    w.trend(65, 325, 640, 250, t('last90'), [t('followUp'), t('lessonsMember')], ['#d32f2f', '#2e7d32'], both),
    w.gauge(712, 325, 362, 250, t('pctMember'), 'green', `mode="ratio" :target="0.55" ${query(both, { weeks: 4, ...FINISHED })}`),
  ].join('\n');
  return slideText(w.frame(t('memberPresent'), 'green', 'a', inner), [t('noteLive'), t('noteManual')]);
}

function newMemberActivity(w, { byArea }) {
  const { t } = w;
  const people = ['new_members.total', 'new_members.at_church'];
  const inner = [
    w.card(180, 98, t('churchAttendance'), 'cyan', query(kpi('new_member_sacrament'), { weeks: 4, ...FINISHED })),
    w.gauge(450, 82, 252, 205, t('pctActive'), 'cyan', 'mode="manual" :max="1" placeholder'),
    w.card(803, 98, t('totalNew'), 'cyan', `mode="share" goal-at="top" hide-last target="–" bar-label="${esc(t('atChurch'))}" ${query(people, { weeks: 1, ...FINISHED })}`),
    `<MmmTable x="38" y="325" w="520" h="250" :headers='${jsonAttr(byArea ? [t('companionship'), t('total'), t('churchQ'), t('atChurchPct')] : [t('zone'), t('total'), t('atChurch'), t('atChurchPct')])}' :top="6" ${query(people, byArea ? { level: 'area', by: 'unit', weeks: 1, ...FINISHED } : { level: 'zone', by: 'unit', weeks: 1, ...FINISHED })} />`,
    w.trend(595, 325, 520, 250, t('last90'), [t('totalNew'), t('atChurch')], ['#d32f2f', '#2e7d32'], people, 'trend', { weeks: 13 }),
  ].join('\n');
  return slideText(w.frame(t('newMemberActivity'), 'cyan', 'b', inner), [t('noteLive'), t('noteManual')]);
}

function weeksSince(now) {
  const start = new Date(now.getFullYear(), 0, 1);
  return Math.min(104, Math.max(1, Math.ceil((now - start) / 86400000 / 7) + 1));
}

// ---- the templates -----------------------------------------------------------------------------------------------

function mmmMain(lang, title, now) {
  const w = words(lang);
  const { t } = w;
  const hint = t('typeHere');
  const cover = slideText(`<MmmCover line-1="Deutschland" line-2="Frankfurt Mission" below="${esc(t('mmm'))}" />`);
  const temple = w.frame(t('templeFirst'), 'red', 'b', [
    `<MmmChips x="140" y="150" w="250" items="${esc(bar([hint, hint, hint]))}" tag="${esc(t('manual'))}" placeholder />`,
    `<MmmChips x="700" y="150" w="250" items="${esc(bar([hint, hint, hint]))}" tag="${esc(t('manual'))}" placeholder />`,
  ].join('\n'), `heading2="${esc(t('baptismsLastWeek'))}" tone2="cyan" :x2="640"`);
  return deckText(title, lang, [
    cover,
    keyIndicators(w, { gaugeMax: 100, note: '' }),
    baptismalGoal(w, { zoneScoped: false, now }),
    comingThisWeek(w, { heading: t('comingWeek') }),
    memberPresent(w),
    newMemberActivity(w, { byArea: false }),
    slideText(temple, [t('noteManual')]),
  ]);
}

function mmmMedia(lang, title) {
  const w = words(lang);
  const { t } = w;
  const slot = (x, y, wd, h, kind, caption) => `<MmmSlot x="${x}" y="${y}" w="${wd}" h="${h}" kind="${kind}" empty="${esc(t(kind === 'video' ? 'putVideo' : 'putImage'))}" tag="${esc(t('manual'))}" caption="${esc(caption)}" />`;
  const named = (kind, n) => `${t(kind)} ${n}`;
  const cover = slideText(`<MmmCover line-1="Deutschland" line-2="Frankfurt Mission" below="${esc(t('media'))}" below-2="${esc(t('mmm'))}" />`, [t('noteMedia')]);
  const one = slideText(w.frame(t('videoOfWeek'), 'green', 'a', slot(176, 95, 800, 450, 'video', t('caption'))), [t('noteMedia')]);
  const two = slideText(w.frame(t('videos'), 'cyan', 'b', [slot(45, 100, 510, 380, 'video', named('video', 1)), slot(597, 100, 510, 380, 'video', named('video', 2))].join('\n')), [t('noteMedia')]);
  const three = slideText(w.frame(t('pictures'), 'red', 'c', [slot(40, 110, 340, 380, 'image', named('image', 1)), slot(406, 110, 340, 380, 'image', named('image', 2)), slot(772, 110, 340, 380, 'image', named('image', 3))].join('\n')), [t('noteMedia')]);
  return deckText(title, lang, [cover, one, two, three]);
}

const ROOM_TONES = ['green', 'cyan', 'red', 'amber'];

function mmmBreakout(lang, title) {
  const w = words(lang);
  const { t } = w;
  const hint = t('typeHere');
  const cover = slideText(`<MmmCover line-1="Deutschland" line-2="Frankfurt Mission" below="${esc(t('breakoutRooms'))}" below-2="${esc(t('mmm'))}" />`, [t('noteBreakout')]);
  const overviewRows = [1, 2, 3, 4].map(n => bar([`${t('room')} ${n}`, t('topicHere'), hint])).join(';');
  const overview = slideText(w.frame(t('rooms'), 'green', 'a', w.manual(60, 100, 1040, 330, [t('room'), t('topic'), t('leader')], overviewRows, ':sorted="-1"')),[t('noteBreakout'), t('noteManual')]);
  const room = n => slideText(w.frame(`${t('room')} ${n}`, ROOM_TONES[(n - 1) % 4], ['a', 'b', 'c', 'a'][(n - 1) % 4], [
    `<MmmChips x="55" y="92" w="520" align="start" items="${esc(bar([`${t('topic')}: ${t('topicHere')}`]))}" tag="${esc(t('manual'))}" placeholder />`,
    `<MmmChips x="620" y="92" w="480" align="start" items="${esc(bar([`${t('leader')}: ${hint}`]))}" />`,
    `<MmmManual x="40" y="150" w="1072" h="410" headers="${esc(bar([t('notes'), t('actions'), t('reportBack')]))}" rows="" :sorted="-1" />`,
  ].join('\n')), [t('noteBreakout')]);
  return deckText(title, lang, [cover, overview, room(1), room(2), room(3), room(4)]);
}

function zoko(lang, title, now) {
  const w = words(lang);
  const { t } = w;
  const cover = slideText(`<MmmCover line-1="${esc(t('zoneName'))}" below="${esc(t('theNumbers'))}" picture-slot picture-text="${esc(t('putImage'))}" tag="${esc(t('manual'))}" />`, [t('noteManual')]);
  const referral = slideText(w.frame(t('referralRates'), 'green', 'b', [
    w.gauge(178, 82, 362, 235, t('contactRate'), 'green', 'mode="manual" :max="1" placeholder'),
    w.gauge(634, 82, 362, 235, t('teachingRate'), 'cyan', 'mode="manual" :max="1" placeholder'),
    `<MmmSlot x="55" y="335" w="1047" h="240" kind="image" empty="${esc(t('referralPicture'))}" tag="${esc(t('manual'))}" />`,
  ].join('\n')), [t('noteManual')]);
  return deckText(title, lang, [
    cover,
    keyIndicators(w, { gaugeMax: 30, note: '' }),
    referral,
    baptismalGoal(w, { zoneScoped: true, now }),
    comingThisWeek(w, { heading: t('comingWeek') }),
    comingThisWeek(w, { heading: t('onDate'), goal: '–' }),
    memberPresent(w),
    newMemberActivity(w, { byArea: true }),
  ]);
}

const BLUE = '#3d8bef';
const RED = '#e0343c';

function stake(lang, title) {
  const w = words(lang);
  const { t } = w;
  const dark = 'dark no-footer';
  // A chart of one number with its goal, and the blue and red boxes beside it.
  const section = (heading, measures, extra = {}) => slideText(w.frame(heading, 'cyan', 'a', [
    w.trend(55, 100, 840, 440, '', [t('actual'), t('goal')], [BLUE, RED], measures, 'goal trend', { weeks: 26, ...extra }),
    `<MmmPair x="945" y="190" w="130" labels="${esc(bar([t('actual'), t('goal')]))}" :weeks="4" tag="${esc(t('manual'))}" ${query(measures, { weeks: 4, ...FINISHED })} />`,
  ].join('\n'), dark), [t('noteLive')]);
  const cover = slideText(`<MmmCover line-1="${esc(t('stakeMeeting'))}" />`, []);
  const summary = slideText(w.frame(t('memberPresent'), 'cyan', 'a', [
    `<MmmPair x="170" y="150" w="170" labels="${esc(bar([`${t('followUp')} (${t('actual')})`, t('goal')]))}" :weeks="4" ${query(['follow_up_lessons.actual', 'follow_up_lessons.goal'], { weeks: 4, ...FINISHED })} />`,
    `<MmmPair x="430" y="150" w="170" labels="${esc(bar([`${t('lessonsMember')} (${t('actual')})`, t('goal')]))}" :weeks="4" ${query(kpi('members_at_lessons'), { weeks: 4, ...FINISHED })} />`,
    w.gauge(690, 110, 330, 330, t('pctMember'), 'cyan', `mode="ratio" :target="0.55" ${query(['follow_up_lessons.actual', 'members_at_lessons.actual'], { weeks: 4, ...FINISHED })}`),
  ].join('\n'), dark), [t('noteLive'), t('noteManual')]);
  const hand = slideText(w.frame([t('dinner'), t('youth'), t('miniMissions')].join(' / '), 'cyan', 'a', [
    w.card(110, 130, t('dinner'), 'cyan', `mode="manual" placeholder no-bar no-pct value="" last="" goal=""`),
    w.card(480, 130, t('youth'), 'cyan', `mode="manual" placeholder no-bar no-pct value="" last="" goal=""`),
    w.card(850, 130, t('miniMissions'), 'cyan', `mode="manual" placeholder no-bar no-pct value="" last="" goal=""`),
  ].join('\n'), dark), [t('noteManual')]);
  const totals = slideText(w.frame(t('stakeTotal'), 'cyan', 'a',
    `<MmmTable x="40" y="95" w="1072" h="470" dense :top="16" :headers='${jsonAttr([t('area'), t('followUp'), t('lessonsMember'), t('baptisms'), t('baptismalDates'), t('churchAttendance'), t('pctMember')])}' ${query(['follow_up_lessons.actual', 'members_at_lessons.actual', 'baptisms_confirmations.actual', 'baptismal_dates.actual', 'sacrament_attendance.actual'], { level: 'area', by: 'unit', weeks: 4, ...FINISHED })} />`, dark), [t('noteLive')]);
  const hint = t('typeHere');
  const followRows = [0, 1, 2].map(() => bar([hint, hint, t('stake'), hint, hint, hint])).join(';');
  const members = slideText(w.frame(t('newMembers'), 'cyan', 'a',
    w.manual(30, 95, 1092, 470, [t('month'), t('nameHere'), t('stake'), t('howDoing'), t('gemiko'), t('support')], followRows, ':sorted="-1"'), dark), [t('noteManual')]);
  return deckText(title, lang, [
    cover,
    section(t('baptisms'), kpi('baptisms_confirmations')),
    section(t('followUp'), ['follow_up_lessons.actual', 'follow_up_lessons.goal']),
    section(t('lessonsMember'), kpi('members_at_lessons')),
    summary,
    hand,
    section(t('churchVisitors'), kpi('sacrament_attendance')),
    totals,
    members,
  ]);
}

// The blank presentation: what "+ New Presentation" always made (`heading` is the title written for a Markdown heading).
function blank(heading) {
  return `---\ntheme: default\n---\n\n# ${heading}\n\n---\n\n# New Slide\n\nStart building your presentation.\n`;
}

const BUILDERS = { 'mmm-main': mmmMain, 'mmm-media': mmmMedia, 'mmm-breakout': mmmBreakout, zoko, stake };

/** Is this the id of a template (any, also the blank one)? */
export function isTemplate(id) {
  return TEMPLATE_IDS.includes(id);
}

/** The language to use: the asked one when it is one of the 14, else English. */
export function pickLanguage(value) {
  const short = String(value || '').toLowerCase().split(/[-_]/)[0];
  return LANGUAGES.includes(short) ? short : 'en';
}

/**
 * The slides.md of a new presentation from a template.
 * @param {string} id a TEMPLATE_IDS entry
 * @param {{ title: string, heading?: string, lang?: string, now?: Date }} options `title`: the deck's name (already checked, safeTitle in deck-files.mjs); `heading`: the same for a Markdown heading (headingText), for the blank deck; `lang`: one of LANGUAGES; `now`: the date, for the year-to-date chart
 */
export function buildTemplate(id, { title, heading = title, lang = 'en', now = new Date() } = {}) {
  if (!isTemplate(id)) throw new Error('Choose one of the presentation templates.');
  if (id === 'blank') return blank(heading);
  return BUILDERS[id](pickLanguage(lang), title, now);
}

const UI_KEYS = { blank: ['tplBlankName', 'tplBlankText'], 'mmm-main': ['tplMainName', 'tplMainText'], 'mmm-media': ['tplMediaName', 'tplMediaText'], 'mmm-breakout': ['tplBreakoutName', 'tplBreakoutText'], zoko: ['tplZokoName', 'tplZokoText'], stake: ['tplStakeName', 'tplStakeText'] };

/**
 * What GET /api/presentation-templates answers: the list for the new presentation dialog, written in `lang` (one of
 * the 14, English otherwise): the names and descriptions of the templates, the dialog's own labels and the 14
 * languages under their own names. The dialog's words come from here, not from the portal's catalogs, so they sit in
 * the same table as the templates' own words (texts.mjs).
 */
export function templateList(lang = 'en') {
  const code = pickLanguage(lang);
  return {
    lang: code,
    dir: LANGUAGE_INFO[code].dir,
    templates: TEMPLATE_IDS.map(id => ({ id, name: text(code, UI_KEYS[id][0]), description: text(code, UI_KEYS[id][1]), language: TEMPLATE_INFO[id].language })),
    languages: LANGUAGES.map(c => ({ code: c, name: LANGUAGE_INFO[c].name })),
    labels: { startFrom: text(code, 'uiStartFrom'), language: text(code, 'uiLanguage'), languageNote: text(code, 'uiLanguageNote') },
  };
}
