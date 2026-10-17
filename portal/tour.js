/*
 * tour.js: the portal's guided tour (round 13). A short, self-written walk through the menu: it dims the page, lights
 * up one part of the portal at a time and says in a card what it is for, with Back / Next / Skip.
 *
 * WHO SEES WHAT
 *   The steps follow the menu from top to bottom (round 21: Overview, Weekly Planning, Call-ins, Calendar, Announcements,
 *   the Insights entries, Wiki, Mission drive, DA Management) and end on the Settings menu (language, theme, this tour).
 *   Call-ins only where the menu shows Call-ins (managers, DL, ZL); Office gets a step about the calendar and
 *   announcements; managers get Insights, Wiki and DA Management. A
 *   step whose part is not on screen for this person is left out, so the tour never points at something hidden. The
 *   tour grants no right and hides nothing: it only reads what the menu already shows.
 *
 * WHEN IT STARTS
 *   - "Tour" in the header (in the menu on phones) starts it any time.
 *   - Once on a person's first sign-in on a device: offerOnce() starts it when localStorage has no "done" mark for that
 *     person. The mark is written when the tour is offered, so closing the tab never makes it come back; Skip and
 *     Done keep it. A browser without storage (private window) simply offers it each time; nothing breaks.
 *
 * HOW IT LOOKS
 *   One layer over the shell (tour.css): a spotlight box (a big shadow around the lit part) and the card. On phones
 *   the menu is a drawer, so the tour opens it for the menu steps and closes it at the end; the card sits at the top
 *   or bottom of the screen, wherever the lit part is not. Right to left (Arabic, Persian) mirrors the card and puts
 *   it on the other side of the menu. Esc and the arrow keys work; focus stays on the card (role="dialog").
 *
 * TEXT
 *   Every text is a key tour.* (or an existing menu key) in portal/i18n/*.json, read with MissionI18n.t(). EN below
 *   is the English fallback (portal/tests/tour-check.cjs proves it equals en.json).
 *
 * Tests: portal/tests/tour-check.cjs (steps per role, every target exists in the shell, the memory, the catalogs in 14
 * languages).
 */
(() => {
  'use strict';

  const DONE_KEY = 'gfm_tour_done_v1';

  // English fallback, the same words as portal/i18n/en.json.
  const EN = {
    'tour.button': 'Tour',
    'tour.buttonHelp': 'Take a guided tour of the portal',
    'tour.label': 'Guided tour',
    'tour.next': 'Next',
    'tour.back': 'Back',
    'tour.skip': 'Skip tour',
    'tour.done': 'Done',
    'tour.step': 'Step {n} of {total}',
    'tour.welcomeTitle': 'Welcome to the portal',
    'tour.welcomeMissionary': 'A one-minute tour of the menu: where to plan your week, read announcements and check the calendar.',
    'tour.welcomeLeader': 'A one-minute tour of the menu: where to plan your week, report in Call-ins and follow your district or zone.',
    'tour.welcomeOffice': 'A one-minute tour of the menu, including where you keep the calendar and announcements up to date.',
    'tour.welcomeManager': 'A one-minute tour of the menu, the insights and the manager tools.',
    'tour.overview': 'Start here: your week at a glance, with the key indicators, the AP Tip of the Week, announcements and your plan.',
    'tour.planning': 'Plan your week here: key indicators first, then goals and action plans. Submit it when it is ready.',
    'tour.callins': 'Report and follow up on your district or zone here.',
    'tour.calendar': 'Meetings and events for your role and zone.',
    'tour.announcements': 'News from your leaders.',
    'tour.officeTitle': 'Office tools',
    'tour.office': 'As Office, you add and edit entries on the Calendar and Announcements pages.',
    'tour.insights': 'Charts and reports about the work in your stewardship.',
    'tour.insightsOffice': 'Lists for the office and mission leaders.',
    'tour.dashboards': 'Key indicators by mission, zone, district and area, with goals and trend lines.',
    'tour.archetypes': 'How each part of the work is going compared with similar areas.',
    'tour.vollzogen': 'Everyone who was baptized and confirmed. Read only.',
    'tour.whiteboard': 'Draw, plan and counsel together, with live mission charts.',
    'tour.presentations': 'Your slide library and presentation workspace.',
    'tour.wiki': 'How-to guides and help for the portal.',
    'tour.drive': 'Shared mission files.',
    'tour.manager': 'Accounts, roster data, imports and documentation. Only managers see this.',
    'tour.settings': 'Change your language or theme here, or start this tour again.',
    // Existing menu words, used as the titles of the steps.
    'overview.weeklyPlanning': 'Weekly Planning',
    'nav.callins': 'Call-ins',
    'nav.overview': 'Overview',
    'nav.calendar': 'Calendar',
    'announcements.title': 'Announcements',
    'shell.groupInsights': 'INSIGHTS',
    'nav.dashboards': 'Dashboards',
    'archetypes.title': 'Archetypal Health',
    'uploads.vollzogen.title': 'Vollzogen',
    'nav.whiteboard': 'Whiteboard',
    'nav.presentations': 'Presentations',
    'shell.wiki': 'Wiki',
    'drive.title': 'Mission drive',
    'nav.management': 'DA Management',
    'shell.settings': 'Settings',
  };

  // The roles that count as managers (portal-enhancements.js MANAGER_ROLES, portal-api/roles.py).
  const MANAGER_ROLES = ['AP', 'PRESIDENT', 'DATA_ADMIN'];

  // Which kind of person this is, for the welcome text and the Office step. roles: main role first, as personRoles().
  function kindOf(roles) {
    const list = Array.isArray(roles) ? roles : [];
    if (list.some(role => MANAGER_ROLES.includes(role))) return 'manager';
    if (list.includes('OFFICE')) return 'office';
    if (['DL', 'ZL', 'STL'].includes(list[0])) return 'leader';
    return 'missionary';
  }

  // The steps in order. target: a CSS selector of the part to light up (none: the card sits in the middle). title and
  // text: catalog keys (text may be a function of the kind). only: the kinds that get the step (default: all). A step
  // is left out when its target is not on screen, so the menu itself decides what each role sees.
  const STEPS = [
    { id: 'welcome', title: 'tour.welcomeTitle', text: kind => 'tour.welcome' + kind[0].toUpperCase() + kind.slice(1) },
    { id: 'overview', target: '#navOverview', title: 'nav.overview', text: () => 'tour.overview', menu: true },
    { id: 'planning', target: '#navPlanning', title: 'overview.weeklyPlanning', text: () => 'tour.planning', menu: true },
    { id: 'callins', target: '#navCallIns', title: 'nav.callins', text: () => 'tour.callins', menu: true },
    { id: 'calendar', target: '#navCalendar', title: 'nav.calendar', text: () => 'tour.calendar', menu: true },
    { id: 'announcements', target: '#navAnnouncements', title: 'announcements.title', text: () => 'tour.announcements', menu: true },
    { id: 'office', target: '#navAnnouncements', title: 'tour.officeTitle', text: () => 'tour.office', menu: true, only: ['office'] },
    { id: 'insights', target: '#insightsGroupTitle', title: 'shell.groupInsights', text: kind => (kind === 'office' ? 'tour.insightsOffice' : 'tour.insights'), menu: true },
    { id: 'dashboards', target: '#navInsights', title: 'nav.dashboards', text: () => 'tour.dashboards', menu: true },
    { id: 'archetypes', target: '#navArchetypes', title: 'archetypes.title', text: () => 'tour.archetypes', menu: true },
    { id: 'vollzogen', target: '#navVollzogen', title: 'uploads.vollzogen.title', text: () => 'tour.vollzogen', menu: true },
    { id: 'whiteboard', target: '#navWhiteboard', title: 'nav.whiteboard', text: () => 'tour.whiteboard', menu: true },
    { id: 'presentations', target: '#navPresentations', title: 'nav.presentations', text: () => 'tour.presentations', menu: true },
    { id: 'wiki', target: '#navWiki', title: 'shell.wiki', text: () => 'tour.wiki', menu: true },
    { id: 'drive', target: '#navDrive', title: 'drive.title', text: () => 'tour.drive', menu: true },
    { id: 'manager', target: '#navManagement', title: 'nav.management', text: () => 'tour.manager', menu: true },
    { id: 'settings', target: '#portalSettings > summary', title: 'shell.settings', text: () => 'tour.settings', menu: true },
  ];

  // Is the part on screen? A hidden entry (display none, the hidden attribute) has no size. isVisible is replaceable
  // so the test can stand in for a page.
  function defaultVisible(element) {
    if (!element) return false;
    if (element.hidden) return false;
    return !!(element.offsetWidth || element.offsetHeight || (element.getClientRects && element.getClientRects().length));
  }

  // The steps this person gets: [{ id, target, title, text, menu }] with the keys already chosen.
  function stepsFor(roles, options = {}) {
    const kind = kindOf(roles);
    const visible = options.isVisible || (selector => defaultVisible(document.querySelector(selector)));
    return STEPS
      .filter(step => !step.only || step.only.includes(kind))
      .filter(step => !step.target || visible(step.target))
      .map(step => ({ id: step.id, target: step.target || null, title: step.title, text: step.text(kind), menu: !!step.menu }));
  }

  // ---- The memory: "done" per person on this device -------------------------------------------------------------
  function memoryKey(person) {
    return DONE_KEY + (person ? ':' + person : '');
  }
  function isDone(person, storage) {
    try { return !!(storage || localStorage).getItem(memoryKey(person)); } catch { return false; }
  }
  function markDone(person, storage) {
    try { (storage || localStorage).setItem(memoryKey(person), new Date().toISOString()); return true; } catch { return false; }
  }

  // ---- Text ---------------------------------------------------------------------------------------------------
  function say(key, values) {
    let text;
    try {
      const i18n = window.MissionI18n;
      text = i18n && i18n.t ? i18n.t(key, values || {}) : undefined;
    } catch { text = undefined; }
    if (typeof text !== 'string' || !text || text === key) text = EN[key] || key;
    return text.replace(/\{(\w+)\}/g, (all, name) => (values && name in values ? values[name] : all));
  }

  // ---- The layer ----------------------------------------------------------------------------------------------
  let layer = null;       // { root, spot, card, title, body, count, back, next, skip, steps, index, person, onKey, onResize }
  let openedMenu = false; // the tour opened the phone drawer, so it closes it again

  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function phone() {
    try { return window.matchMedia('(max-width: 780px)').matches; } catch { return false; }
  }

  function setMenu(open) {
    const sidebar = document.getElementById('sidebar');
    const overlay = document.getElementById('overlay');
    if (!sidebar || !phone()) return false;
    const was = sidebar.classList.contains('open');
    if (open) { sidebar.classList.add('open'); overlay && overlay.classList.add('open'); if (!was) openedMenu = true; }
    else { sidebar.classList.remove('open'); overlay && overlay.classList.remove('open'); }
    return !was && open;
  }

  // Puts the spotlight on the step's part and the card beside it (or in the middle).
  function place() {
    if (!layer) return;
    const step = layer.steps[layer.index];
    const target = step.target ? document.querySelector(step.target) : null;
    const vw = window.innerWidth || 800, vh = window.innerHeight || 600;
    const rtl = document.documentElement.dir === 'rtl';
    const { spot, card } = layer;
    card.style.top = card.style.left = card.style.right = card.style.bottom = '';
    card.style.transform = '';
    if (!target) {
      spot.hidden = true;
      card.classList.add('tour-center');
      return;
    }
    card.classList.remove('tour-center');
    let r = target.getBoundingClientRect();
    // Round 21: a part below the fold (the Settings menu at the end of a long phone menu) is scrolled into view first.
    if ((r.top < 0 || r.bottom > vh) && target.scrollIntoView) {
      try { target.scrollIntoView({ block: 'center' }); } catch { /* old browser */ }
      r = target.getBoundingClientRect();
    }
    const pad = 6;
    spot.hidden = false;
    spot.style.top = (r.top - pad) + 'px';
    spot.style.left = (r.left - pad) + 'px';
    spot.style.width = (r.width + pad * 2) + 'px';
    spot.style.height = (r.height + pad * 2) + 'px';
    const cw = Math.min(card.offsetWidth || 340, vw - 24), ch = card.offsetHeight || 200;
    const gap = 14;
    let left, top;
    if (!phone() && !rtl && r.right + gap + cw <= vw) { left = r.right + pad + gap; top = r.top; }
    else if (!phone() && rtl && r.left - gap - cw >= 0) { left = r.left - pad - gap - cw; top = r.top; }
    else {
      left = Math.min(Math.max(12, r.left), vw - cw - 12);
      if (r.bottom + pad + gap + ch <= vh) top = r.bottom + pad + gap;
      else if (r.top - pad - gap - ch >= 0) top = r.top - pad - gap - ch;
      else top = phone() ? (r.top > vh / 2 ? 12 : vh - ch - 12) : 12;
    }
    top = Math.min(Math.max(12, top), Math.max(12, vh - ch - 12));
    card.style.left = Math.max(12, left) + 'px';
    card.style.top = top + 'px';
  }

  function show(index) {
    if (!layer) return;
    layer.index = Math.max(0, Math.min(layer.steps.length - 1, index));
    const step = layer.steps[layer.index];
    const last = layer.index === layer.steps.length - 1;
    // Menu steps need the drawer open on phones; the others need it closed.
    const changed = step.menu ? setMenu(true) : (setMenu(false), false);
    layer.title.textContent = say(step.title);
    layer.body.textContent = say(step.text);
    layer.count.textContent = say('tour.step', { n: layer.index + 1, total: layer.steps.length });
    layer.back.textContent = say('tour.back');
    layer.back.hidden = layer.index === 0;
    layer.next.textContent = say(last ? 'tour.done' : 'tour.next');
    layer.skip.textContent = say('tour.skip');
    layer.skip.hidden = last;
    layer.root.setAttribute('aria-label', say('tour.label'));
    const target = step.target ? document.querySelector(step.target) : null;
    try { target && target.scrollIntoView && target.scrollIntoView({ block: 'nearest' }); } catch { /* old browser */ }
    place();
    // The drawer slides in: measure again when it has arrived.
    if (changed) {
      const sidebar = document.getElementById('sidebar');
      if (sidebar) sidebar.addEventListener('transitionend', place, { once: true });
      setTimeout(place, 280);
      setTimeout(place, 700);
    }
    try { layer.next.focus(); } catch { /* not focusable yet */ }
  }

  function end() {
    if (!layer) return;
    const { root, onKey, onResize, person } = layer;
    document.removeEventListener('keydown', onKey, true);
    window.removeEventListener('resize', onResize);
    window.removeEventListener('mission-i18n-change', onResize);
    markDone(person);
    root.remove();
    layer = null;
    if (openedMenu || phone()) setMenu(false);
    openedMenu = false;
  }

  // Starts the tour for these roles. person: an id for the memory (never shown). Does nothing without steps.
  function start(roles, person) {
    if (layer) end();
    const steps = stepsFor(roles);
    if (!steps.length || !document.body) return false;
    const root = el('div', 'tour-root');
    root.setAttribute('role', 'dialog');
    root.setAttribute('aria-modal', 'true');
    const shade = el('div', 'tour-shade');
    const spot = el('div', 'tour-spot');
    const card = el('div', 'tour-card');
    const title = el('h2', 'tour-title');
    const body = el('p', 'tour-text');
    const count = el('div', 'tour-count');
    const buttons = el('div', 'tour-buttons');
    const skip = el('button', 'tour-skip'); skip.type = 'button';
    const back = el('button', 'tour-back'); back.type = 'button';
    const next = el('button', 'tour-next'); next.type = 'button';
    buttons.append(skip, back, next);
    card.append(title, body, count, buttons);
    root.append(shade, spot, card);
    document.body.append(root);
    const onResize = () => { if (layer) show(layer.index); };
    const onKey = event => {
      if (!layer) return;
      if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); end(); }
      else if (event.key === 'ArrowRight' || event.key === 'ArrowLeft') {
        const forward = (event.key === 'ArrowRight') !== (document.documentElement.dir === 'rtl');
        event.preventDefault();
        if (forward) { layer.index === layer.steps.length - 1 ? end() : show(layer.index + 1); } else show(layer.index - 1);
      }
    };
    layer = { root, spot, card, title, body, count, back, next, skip, steps, index: 0, person, onKey, onResize };
    next.addEventListener('click', () => { layer.index === layer.steps.length - 1 ? end() : show(layer.index + 1); });
    back.addEventListener('click', () => show(layer.index - 1));
    skip.addEventListener('click', end);
    document.addEventListener('keydown', onKey, true);
    window.addEventListener('resize', onResize);
    window.addEventListener('mission-i18n-change', onResize);
    show(0);
    return true;
  }

  // Offers the tour once per person and device: starts it unless it was offered before. Marks it at once.
  function offerOnce(roles, person, delay) {
    if (isDone(person)) return false;
    markDone(person);
    setTimeout(() => { if (!layer) start(roles, person); }, delay === undefined ? 1800 : delay);
    return true;
  }

  const api = { start, end, offerOnce, stepsFor, kindOf, isDone, markDone, memoryKey, say, STEPS, EN, DONE_KEY, isOpen: () => !!layer };
  window.GfmTour = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})();
