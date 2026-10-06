/*
 * portal-enhancements.js: the portal shell's main script.
 *
 * WHAT IT IS
 *   index.html (made from index.template.html) draws the sign-in card, an empty menu, the header and one big frame
 *   (#appFrame) where every page opens. Its own small script signs people in. This file runs right after it and adds
 *   everything else: the full menu for each role, the header buttons, the language list, the theme, push reminders,
 *   and the extra sign-ins that Presentations and Dashboards need.
 *
 * WHO USES IT
 *   Everyone who opens the portal: missionaries, leaders (DL, ZL, STL, AP), the President, Office and Data Analysts.
 *
 * HOW IT FITS
 *   - The frame shows one page at a time: home.html (Overview), planning.html, callins.html, calendar.html,
 *     announcements.html, archetypes.html, whiteboard/, or another program on another port of the same computer:
 *     Presentations (3030 and 8089; on the public address https://presentations. and https://decks.), Dashboards
 *     (DataEase, 8088; https://dashboards.) and DA Management (8090; https://management.example.org).
 *   - portal-api (/api/...) answers the questions and checks every request. Hiding a menu entry here is only a
 *     convenience; it never gives or takes away a right.
 *   - i18n.js translates every English text the shell shows into the chosen language.
 *
 * WHAT IT BORROWS FROM index.html
 *   URLS, TITLES, PORTAL_HOST, PORTAL_PUBLIC_SITE, SUPABASE_URL, SUPABASE_ANON_KEY, frame, title, currentUserContext,
 *   allowedPages,
 *   setVisible, closeMenu and ensureMissionSession (from portal-session.js). It replaces three of the shell's
 *   functions with fuller versions: applyRoleNavigation (section 3), showLogin (section 12) and openPage (section 13).
 *
 * SECTIONS
 *   1 page addresses   2 the menu   3 who may open what   4 the header   5 theme   6 portal-api
 *   7 language   8 reminders   9 messages from the frame   10 Presentations sign-in   11 Dashboards sign-in
 *   12 signing out   13 opening a page   14 start
 *
 * Tests: portal/tests/portal-menu-check.cjs, dashboards-dataease-check.cjs and whiteboard-shell-check.cjs run this
 * file in Node; portal-api/tests/edge_known_issues.ps1 and edge_small_fixes.ps1 run it in a real browser.
 */
(() => {

    // ---- 1. Page addresses and titles --------------------------------------------------------------------------
    // index.html knows Weekly Planning, Call-ins, Dashboards and Presentations; the other pages are added here.
    // A title is the English name in the header; i18n.js shows it in the viewer's language.

    // The Overview. The managers' Overview starts with the mission glimpse (glimpse.js); '?glimpse=1' lets the page
    // show it before its own answer arrives. applyRoleNavigation picks one of the two at every sign-in.
    const OVERVIEW = '/home.html';
    const OVERVIEW_WITH_GLIMPSE = OVERVIEW + '?glimpse=1';
    URLS.overview = OVERVIEW;
    TITLES.overview = 'Overview';

    TITLES.planning = 'Weekly Planning';
    URLS.callins = '/callins.html';
    TITLES.callins = 'Call-ins';
    URLS.calendar = '/calendar.html?v=2';
    TITLES.calendar = 'Calendar';
    URLS.announcements = '/announcements.html?v=2';
    TITLES.announcements = 'Announcements';

    // Archetypal Health (docs/handoff/round7/archetypes.md): six archetypes per zone, district and area, each compared
    // with similar areas. portal-api archetypes.py decides what each person sees.
    URLS.archetypes = '/archetypes.html';
    TITLES.archetypes = 'Archetypal Health';

    // Whiteboard (docs/handoff/round6/whiteboard2.md): named boards for the managers, with live charts that
    // Presentations draws. The page asks the shell for the Presentations address.
    URLS.whiteboard = '/whiteboard/';
    TITLES.whiteboard = 'Whiteboard';
    window.portalPresentationsUrl = () => URLS.presentations;

    // The public address (https://example.org, index.template.html PORTAL_PUBLIC_SITE) carries only
    // the portal's own port. Since round 10 every program has its own public name there, a Cloudflare tunnel route to
    // its port (docs/handoff/round10/public-everything.md): Dashboards (DASHBOARDS_PUBLIC_ORIGIN below), Presentations
    // (URLS.presentations in index.template.html) and DA Management (MANAGEMENT_PUBLIC_ORIGIN). So everything opens
    // from everywhere. OFFICE_ONLY (pages that would show office-only.html instead) is empty now; it is kept for a
    // program that may one day open in the office only. On localhost and the LAN address nothing changes.
    const SITE_DOMAIN = ((window.GFM_SITE && window.GFM_SITE.publicDomain) || '').toLowerCase();
    const PUBLIC_SITE = typeof PORTAL_PUBLIC_SITE !== 'undefined' && PORTAL_PUBLIC_SITE === true;
    const OFFICE_ONLY = new Set([]);
    const OFFICE_ONLY_PAGE = '/office-only.html';

    // DA Management: the roster importer on port 8090; on the public address its own name (round 10). It signs in
    // with the portal's token in the address (index.template.html openPage) and keeps its own session cookie there.
    const MANAGEMENT_PUBLIC_ORIGIN = 'https://management.' + SITE_DOMAIN;
    const MANAGEMENT_ORIGIN = PUBLIC_SITE ? MANAGEMENT_PUBLIC_ORIGIN : PORTAL_HOST + ':8090';
    URLS.management = MANAGEMENT_ORIGIN + '/';
    TITLES.management = 'DA Management';

    // Dashboards: DataEase on port 8088 (docs/handoff/round6/dataease.md). /gfm-start opens the dashboard
    // "Key indicators" in the viewer's language (?gfmLang=de), read again each time Dashboards open.
    // On the public address DataEase has its own name, a Cloudflare tunnel route to port 8088
    // (docs/handoff/round10/public-dashboards.md). It is a subdomain of the portal's, so portal-api's Dashboards cookie
    // (set there for the whole domain) reaches it, and the sign-in, renewal and sign-out below work as on the LAN.
    const DASHBOARDS_PUBLIC_ORIGIN = 'https://dashboards.' + SITE_DOMAIN;
    const DATAEASE_ORIGIN = PUBLIC_SITE ? DASHBOARDS_PUBLIC_ORIGIN : PORTAL_HOST + ':8088';

    function viewerLanguage() {
        try { return sessionStorage.getItem('mission_language') || 'en'; } catch { return 'en'; }
    }

    Object.defineProperty(URLS, 'insights', {
        configurable: true,
        enumerable: true,
        get: () => DATAEASE_ORIGIN + '/gfm-start?gfmLang=' + encodeURIComponent(viewerLanguage())
    });
    TITLES.insights = 'Dashboards';

    // The short line under the page title in the header.
    const descriptions = {
        overview: 'Your mission week at a glance.',
        planning: 'Native dynamic weekly planning.',
        callins: 'Native leadership reporting.',
        archetypes: 'How each part of the work is going compared with similar areas.',
        insights: 'Key indicators, zones and districts, and the covenant path, with goals and trend lines.',
        calendar: 'Meetings and events for your role and zone.',
        announcements: 'Updates from the leaders in your stewardship.',
        presentations: 'Your presentation library and slide workspace.',
        whiteboard: 'Draw, plan and counsel together, with live mission charts.',
        management: 'Accounts, roster data, imports, and documentation.'
    };


    // ---- 2. The menu -----------------------------------------------------------------------------------------------
    // index.html has Weekly Planning, Call-ins, Dashboards and Presentations. This adds Overview (at the top), Calendar
    // and Announcements (after Weekly Planning), Archetypal Health (after Call-ins), Whiteboard (after Presentations)
    // and DA Management (at the bottom, above Sign Out). The entries not everyone has stay hidden until
    // applyRoleNavigation knows who signed in, then it shows only what the person may open.

    // A new menu entry: an icon, then its words. Clicking it opens its page.
    function menuButton(id, label, page, icon, hidden = false) {
        const item = document.createElement('button');
        item.className = 'nav-item';
        item.id = id;
        item.dataset.page = page;
        item.innerHTML = `<span class="nav-icon">${icon}</span>${label}`;
        item.addEventListener('click', () => openPage(page));
        if (hidden) item.style.display = 'none';
        return item;
    }

    function buildMenu() {
        document.querySelector('.nav-group-title')?.before(menuButton('navOverview', 'Overview', 'overview', '⌂'));
        document.getElementById('navPlanning')?.after(
            menuButton('navCalendar', 'Calendar', 'calendar', '▦'),
            menuButton('navAnnouncements', 'Announcements', 'announcements', '◉')
        );
        document.getElementById('navCallIns')?.after(menuButton('navArchetypes', 'Archetypal Health', 'archetypes', '◔', true));
        document.getElementById('navPresentations')?.after(menuButton('navWhiteboard', 'Whiteboard', 'whiteboard', '✎', true));
        const management = menuButton('navManagement', 'DA Management', 'management', '◇', true);
        management.classList.add('management');
        document.querySelector('.sidebar-bottom')?.prepend(management);
    }

    buildMenu();


    // ---- 3. Who may open what -----------------------------------------------------------------------------------------
    // The same rules as portal-api/roles.py (keep the two in step). A person has one main role and may also hold the
    // additional roles Data Analyst (DATA_ADMIN: manager rights) and Office (calendar editing and announcements). The calendar and
    // announcement pages follow the API's can_edit / can_publish answers.
    const LEADER_ORDER = ['AP', 'ZL', 'STL', 'DL'];
    const MANAGER_ROLES = ['AP', 'PRESIDENT', 'DATA_ADMIN'];
    const ROLE_LABELS = {
        MISSIONARY: 'Missionary', DL: 'DL', ZL: 'ZL', STL: 'STL', AP: 'AP',
        OFFICE: 'Office', PRESIDENT: 'President', DATA_ADMIN: 'Data Analyst'
    };

    // The main role: President (or an older Data Analyst / Office main role) set by hand, otherwise the highest current
    // leadership assignment, otherwise Missionary. A saved app_role DL/ZL/STL/AP alone counts for nothing.
    function mainRole(context) {
        const appRole = String(context?.app_role || '').toUpperCase();
        if (['PRESIDENT', 'DATA_ADMIN', 'OFFICE'].includes(appRole)) return appRole;
        const leader = String(context?.leadership_role || '').toUpperCase();
        return LEADER_ORDER.includes(leader) ? leader : 'MISSIONARY';
    }

    // Every role, main role first. Without migration 021 there is no additional_roles column: that means none.
    function personRoles(context) {
        const main = mainRole(context);
        const extra = new Set(
            (Array.isArray(context?.additional_roles) ? context.additional_roles : [])
                .map(value => String(value).toUpperCase())
        );
        return [main, ...['DATA_ADMIN', 'OFFICE'].filter(value => extra.has(value) && value !== main)];
    }

    // Which parts of the portal these roles open (besides Overview, Weekly Planning, Calendar and Announcements, which
    // everyone has).
    function partsFor(roles) {
        const main = roles[0];
        const manager = roles.some(role => MANAGER_ROLES.includes(role));
        return {
            // Dashboards, Whiteboard and DA Management: managers, also as an additional Data Analyst. Office gives none.
            manager,
            // Call-ins: managers, DLs and ZLs. STLs have no part in Call-ins.
            callins: manager || ['DL', 'ZL'].includes(main),
            // Presentations: managers; ZLs and STLs make decks for their own zone; DLs open the decks shared with them.
            presentations: manager || ['DL', 'ZL', 'STL'].includes(main),
            // Archetypal Health: APs, the President and Data Analysts (roles.archetype_scope).
            archetypes: manager
        };
    }

    function pagesFor(parts) {
        const pages = ['overview', 'planning', 'calendar', 'announcements'];
        if (parts.callins) pages.push('callins');
        if (parts.manager) pages.push('insights', 'management', 'whiteboard');
        if (parts.presentations) pages.push('presentations');
        if (parts.archetypes) pages.push('archetypes');
        return new Set(pages);
    }

    function showMenuFor(parts) {
        setVisible('navCallIns', parts.callins);
        setVisible('navArchetypes', parts.archetypes);
        setVisible('navInsights', parts.manager);
        setVisible('navPresentations', parts.presentations);
        setVisible('navWhiteboard', parts.manager);
        setVisible('insightsGroupTitle', parts.manager || parts.presentations);
        setVisible('navManagement', parts.manager);
    }

    // "Elder Example · DL · Data Analyst" at the bottom of the menu. Each role is its own element so i18n.js can
    // translate it; the name is never translated.
    function showSignedInPerson(context, roles) {
        const summary = document.getElementById('userSummary');
        if (!summary) return;
        const parts = [];
        if (context?.display_name) {
            const name = document.createElement('span');
            name.setAttribute('data-i18n-ignore', '');
            name.textContent = context.display_name;
            parts.push(name);
        }
        for (const role of roles) {
            const label = document.createElement('span');
            label.textContent = ROLE_LABELS[role] || role;
            parts.push(label);
        }
        summary.replaceChildren(
            ...parts.flatMap((part, index) => index ? [document.createTextNode(' · '), part] : [part])
        );
    }

    // Called by index.html after every sign-in.
    applyRoleNavigation = function (context) {
        const roles = personRoles(context);
        const parts = partsFor(roles);
        allowedPages = pagesFor(parts);
        // Set at every sign-in, so the next person on a shared device gets their own Overview.
        URLS.overview = parts.manager ? OVERVIEW_WITH_GLIMPSE : OVERVIEW;
        showMenuFor(parts);
        // On a shared computer a manager's Dashboards sign-in (the gfm_dataease cookie) may still be in this browser;
        // it must not stay with someone who may not open Dashboards.
        if (!parts.manager) Promise.resolve().then(endDataEaseSession).catch(() => {});
        showSignedInPerson(context, roles);
        setupPreferences();
        applyTheme();
    };


    // ---- 4. The header -----------------------------------------------------------------------------------------------
    // Left: the page title with a short description under it. Right: the buttons, in this order on a computer:
    // language list, Library, Customize, Full screen, Reload, Enable reminders / Turn off reminders.
    const header = document.querySelector('.topbar');

    const heading = document.createElement('div');
    heading.className = 'page-heading';
    title.replaceWith(heading);
    heading.append(title);

    const subtitle = document.createElement('div');
    subtitle.className = 'page-subtitle';
    heading.append(subtitle);

    const actions = document.createElement('div');
    actions.className = 'portal-actions';
    header.append(actions);

    function headerButton(label, action) {
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'portal-action';
        button.textContent = label;
        button.addEventListener('click', action);
        actions.append(button);
        return button;
    }

    // Library: back to the list of presentations. Shown only while Presentations is open.
    const library = headerButton('Library', () => openPage('presentations'));
    library.hidden = true;

    // Full screen: only while Dashboards are open. Where a page cannot go full screen (iPhone), Dashboards open in a new
    // tab instead; the sign-in is the same. Esc returns.
    const fullScreen = headerButton('Full screen', showDashboardsFullScreen);
    fullScreen.hidden = true;
    fullScreen.title = 'Show Dashboards on the whole screen';

    function showDashboardsFullScreen() {
        if (document.fullscreenEnabled && frame.requestFullscreen) {
            frame.requestFullscreen().catch(() => window.open(URLS.insights, '_blank', 'noopener'));
        } else {
            window.open(URLS.insights, '_blank', 'noopener');
        }
    }

    const customize = headerButton('Customize', showCustomizer);

    // Reload tries again a page that has not opened yet (the error messages say "use Reload"); otherwise it reloads the
    // page on screen.
    headerButton('Reload', () => openPage(pendingOpen ? pendingOpen.name : location.hash.slice(1) || 'planning'));

    const languages = document.createElement('select');
    languages.className = 'portal-language';
    languages.setAttribute('aria-label', 'Assigned mission language');
    languages.hidden = true;
    actions.prepend(languages);

    // Reminders on this device (section 8): one of the two buttons is shown.
    const notifications = headerButton('Enable reminders', enableReminders);
    notifications.hidden = true;
    const remindersOff = headerButton('Turn off reminders', disableReminders);
    remindersOff.hidden = true;

    // A message line under the header (reminders, a language that could not be saved).
    const notice = document.createElement('div');
    notice.className = 'portal-notice';
    notice.hidden = true;
    header.after(notice);

    function showNotice(text) {
        notice.textContent = text;
        notice.hidden = false;
    }

    // Phones: every control is at least 44px tall, and the header has room for only the menu button, Library and
    // Reload at that size. So the language list and Customize go into the menu (☰) above Sign Out, Turn off reminders
    // just above Sign Out too, and Enable reminders under the reminder notice, all full size. Wider screens keep
    // everything in the header, as compact as before. Their phone sizes are at the end of portal.css.
    const phoneLayout = window.matchMedia('(max-width: 780px)');

    function placeHeaderControls() {
        const phone = phoneLayout.matches;
        const signOut = document.getElementById('logoutButton');
        const inMenu = phone && !!signOut;
        customize.className = inMenu ? 'nav-item menu-control' : 'portal-action';
        if (inMenu) signOut.before(languages, customize);
        else { actions.prepend(languages); library.after(customize); }
        notifications.className = phone ? 'portal-action reminders-switch' : 'portal-action';
        remindersOff.className = inMenu ? 'nav-item reminders-switch' : 'portal-action';
        if (phone) notice.after(notifications); else actions.append(notifications);
        if (inMenu) signOut.before(remindersOff); else actions.append(remindersOff);
    }

    placeHeaderControls();
    phoneLayout.addEventListener('change', placeHeaderControls);

    // Customize from the phone menu: the menu closes, so the dialog is not hidden behind it.
    customize.addEventListener('click', () => {
        if (phoneLayout.matches) closeMenu();
    });


    // ---- 5. Theme (the Customize dialog) -------------------------------------------------------------------------------
    // Three looks: mission (navy and teal, the default), light and dark. The choice is kept in this browser and sent to
    // the page in the frame, which paints itself to match. Overview cards have their own Customize button on the
    // Overview.
    const THEME_KEY = 'gfm_portal_layout_v1';

    const customizer = document.createElement('dialog');
    customizer.className = 'portal-customizer';
    customizer.innerHTML =
        '<form method="dialog">' +
        '<h2>Customize portal</h2>' +
        '<p>Choose the portal theme. Overview cards are customized from the Overview page.</p>' +
        '<label>Theme' +
        '<select id="portalTheme">' +
        '<option value="mission">Mission navy & teal</option>' +
        '<option value="light">Light</option>' +
        '<option value="dark">Dark</option>' +
        '</select>' +
        '</label>' +
        '<div class="customizer-actions">' +
        '<button value="cancel" class="portal-action">Cancel</button>' +
        '<button value="save" class="portal-action primary">Save</button>' +
        '</div>' +
        '</form>';
    document.body.append(customizer);

    function savedTheme() {
        try { return JSON.parse(localStorage.getItem(THEME_KEY))?.theme || 'mission'; } catch { return 'mission'; }
    }

    // Tells the page in the frame something that is no secret (the theme, the language): any origin may hear it.
    function tellFrame(message) {
        frame.contentWindow?.postMessage(message, '*');
    }

    function applyTheme() {
        document.documentElement.dataset.theme = savedTheme();
        tellFrame({type: 'portal-theme', theme: savedTheme()});
    }

    function showCustomizer() {
        document.getElementById('portalTheme').value = savedTheme();
        customizer.showModal();
    }

    // Save keeps the chosen theme (Mission navy & teal is the default); Cancel (or Esc) changes nothing.
    customizer.addEventListener('close', () => {
        if (customizer.returnValue !== 'save') return;
        localStorage.setItem(THEME_KEY, JSON.stringify({theme: document.getElementById('portalTheme').value}));
        applyTheme();
    });


    // ---- 6. portal-api ---------------------------------------------------------------------------------------------------
    // A request to portal-api with the portal sign-in. body is sent as JSON. Throws the server's message on an error.
    async function api(path, options = {}) {
        const response = await fetch('/api/' + path, {
            ...options,
            headers: {
                Authorization: 'Bearer ' + await ensureMissionSession(),
                'Content-Type': 'application/json'
            },
            body: options.body ? JSON.stringify(options.body) : undefined
        });
        const body = await response.json();
        if (!response.ok) throw Error(body.error || 'Request failed.');
        return body;
    }


    // ---- 7. Language -------------------------------------------------------------------------------------------------------
    // The list in the header shows the languages DA Management assigned to this person, each in its own name. A choice
    // is saved (PUT /api/languages); i18n.js translates the shell, and the page in the frame is told. ?lang= in the
    // portal address (de, deu, fa, pes …) shows a language on this device without saving it.

    // i18n.js shows the shell in the language (every English text, the menu included, and right to left for Persian
    // and Arabic); the page in the frame hears it too.
    function applyLanguage(language) {
        sessionStorage.setItem('mission_language', language);
        window.MissionI18n?.setLanguage(language);
        tellFrame({type: 'mission-language', language});
    }

    // Choosing from the list replaces a language that came from ?lang= in the address.
    function forgetAddressLanguage() {
        if (!new URLSearchParams(location.search).has('lang')) return;
        const url = new URL(location.href);
        url.searchParams.delete('lang');
        history.replaceState(history.state, '', url.pathname + url.search + url.hash);
    }

    languages.onchange = async () => {
        try {
            // The extra entry for a ?lang= language is shown on this device only, never saved.
            const addressOnly = languages.selectedOptions[0]?.dataset.address === 'true';
            if (!addressOnly) {
                forgetAddressLanguage();
                await api('languages', {method: 'PUT', body: {language: languages.value}});
            }
            applyLanguage(languages.value);
            // Dashboards open again in the new language (their own copy of "Key indicators"). The Whiteboard follows
            // the language by itself (opening it again would close the open board).
            if (location.hash !== '#whiteboard') openPage(location.hash.slice(1) || 'overview');
        } catch (e) {
            showNotice(e.message);
        }
    };

    // Fills the list; returns the language to show now: ?lang= in the address first, then the saved one.
    function fillLanguageList(data) {
        const englishNames = new Intl.DisplayNames(['en'], {type: 'language'});
        const i18n = window.MissionI18n;
        const nameOf = code => {
            const own = i18n?.languages[code.split('-')[0]];
            if (own) return own.name;
            try { return englishNames.of(code) || code; } catch { return code; }
        };
        languages.replaceChildren(...data.allowed.map(code => {
            const option = document.createElement('option');
            option.value = code;
            option.textContent = nameOf(code);
            return option;
        }));
        const fromAddress = i18n?.addressLanguage;
        if (fromAddress && !data.allowed.includes(fromAddress)) {
            const option = document.createElement('option');
            option.value = fromAddress;
            option.dataset.address = 'true';
            option.textContent = i18n.languages[fromAddress.split('-')[0]]?.name || fromAddress;
            languages.append(option);
        }
        languages.value = fromAddress || data.selected;
        languages.hidden = false;
        return fromAddress || data.selected;
    }

    // After each sign-in: the language list, then the reminder buttons for this person on this device.
    async function setupPreferences() {
        try {
            applyLanguage(fillLanguageList(await api('languages')));
            await showReminderButtons();
        } catch (e) {
            console.warn('Portal preferences unavailable:', e.message);
        }
    }


    // ---- 8. Push reminders -----------------------------------------------------------------------------------------------
    // Reminders are per device: the Sunday planning reminder (18:00, while a plan is not submitted) and meeting reminders
    // (portal-api reminders.py). "Enable reminders" subscribes this browser; "Turn off reminders" stops them here only.
    const REMINDERS_ON = 'Reminders are on. You’ll get a reminder on Sunday at 18:00 if your plan is not submitted yet, and before mission meetings. If a companion is working on the plan right now, the Sunday reminder waits.';
    const REMINDERS_OFF = 'Reminders are off on this device. Sunday planning reminders help companionships finish together, so the mission asks everyone to keep them on.';
    const REMINDERS_BLOCKED = 'Notifications are blocked for this site. Allow them in your browser settings, then come back.';

    async function showReminderButtons() {
        const onThisDevice = await remindersOnThisDevice();
        notifications.hidden = !('Notification' in window) || onThisDevice;
        remindersOff.hidden = !onThisDevice;
        if (Notification.permission === 'denied') showNotice(REMINDERS_BLOCKED);
        else if (!onThisDevice) showNotice(REMINDERS_OFF);
    }

    // The server's public key (base64url text) as the bytes the browser's push service wants.
    function base64UrlBytes(text) {
        const base64 = text.replace(/-/g, '+').replace(/_/g, '/');
        const padded = base64 + '='.repeat((4 - base64.length % 4) % 4);
        return Uint8Array.from(atob(padded), c => c.charCodeAt(0));
    }

    async function enableReminders() {
        try {
            if (!('serviceWorker' in navigator) || !('PushManager' in window)) {
                throw Error('This browser can’t show reminders. On an iPhone, add the portal to your Home Screen first.');
            }
            if (await Notification.requestPermission() !== 'granted') throw Error(REMINDERS_BLOCKED);
            await navigator.serviceWorker.register('/service-worker.js');
            const registration = await navigator.serviceWorker.ready;
            const config = await api('push/config');
            const key = base64UrlBytes(config.public_key);
            const subscription = await registration.pushManager.getSubscription() ||
                await registration.pushManager.subscribe({userVisibleOnly: true, applicationServerKey: key});
            await api('push/subscriptions', {method: 'POST', body: subscription.toJSON()});
            showNotice(REMINDERS_ON);
            notifications.hidden = true;
            remindersOff.hidden = false;
        } catch (e) {
            showNotice(e.message);
        }
    }

    // This browser's push subscription, or null (no support, never enabled, or turned off).
    async function thisDeviceSubscription() {
        if (!('serviceWorker' in navigator) || !('PushManager' in window)) return null;
        const registration = await navigator.serviceWorker.getRegistration();
        return registration ? await registration.pushManager.getSubscription() : null;
    }

    // True when this browser gets the signed-in person's reminders. The server also removes a registration that still
    // belongs to someone who used this browser before (a shared phone or computer), so their reminders stop here.
    async function remindersOnThisDevice() {
        try {
            if (!('Notification' in window) || Notification.permission !== 'granted') return false;
            const subscription = await thisDeviceSubscription();
            if (!subscription) return false;
            const state = await api('push/device', {method: 'POST', body: {endpoint: subscription.endpoint}});
            return !!state.subscribed;
        } catch (e) {
            console.warn('Reminder state unavailable:', e.message);
            return false;
        }
    }

    // The off switch. Only this device stops getting reminders; other devices keep theirs.
    async function disableReminders() {
        remindersOff.disabled = true;
        try {
            const subscription = await thisDeviceSubscription();
            if (subscription) {
                let failed = null;
                await api('push/subscriptions', {method: 'DELETE', body: {endpoint: subscription.endpoint}})
                    .catch(e => { failed = e; });
                // Unsubscribing in the browser stops the reminders even if the portal could not be reached: the push
                // service then reports this device as gone and portal-reminders forgets it.
                if (!(await subscription.unsubscribe()) && failed) throw failed;
            }
            remindersOff.hidden = true;
            notifications.hidden = false;
            showNotice(REMINDERS_OFF);
        } catch (e) {
            showNotice('Reminders could not be turned off. Check your connection and try again.');
        } finally {
            remindersOff.disabled = false;
            // On phones the switch is in the menu: close it so the message under the header can be read.
            if (phoneLayout.matches) closeMenu();
        }
    }


    // ---- 9. Messages from the page in the frame --------------------------------------------------------------------------
    // A portal page asks to open another page: the Overview's Weekly Planning button and its "View calendar" and
    // "View all" links, the mission glimpse's links. Only this portal's own pages may ask, and only for pages this
    // person has.
    window.addEventListener('message', event => {
        if (event.origin !== location.origin || event.data?.type !== 'gfm-open-page') return;
        if (allowedPages.has(event.data.page)) openPage(event.data.page);
    });

    // A page in the frame (for example a deck in Presentations) asks for the theme once it listens: the frame's load
    // event, when the theme is sent anyway, may come before that. Only the frame's own page gets an answer.
    window.addEventListener('message', event => {
        if (event.data?.type !== 'portal-theme-request' || event.source !== frame.contentWindow) return;
        tellFrame({type: 'portal-theme', theme: savedTheme()});
    });


    // ---- 10. Presentations sign-in (port 3030) ---------------------------------------------------------------------------
    // Presentations keeps its own sign-in in a cookie that scripts cannot read (HttpOnly). The shell gets and renews it
    // with POST <Presentations>/api/session and the portal token. The token never goes into the frame's address or a
    // message, because deck scripts run there; the frame only asks ('presentations-session-request') and hears back.
    const presentationsSignIn = {
        timer: 0,          // the next renewal
        request: null,     // the request on its way, shared by everyone who asks meanwhile
        abort: null,       // cancels that request (sign-out)
        lastRefresh: 0,    // when the last answer came
        lastData: null,    // that answer ({expires_at})
        generation: 0      // changes at sign-out, so an answer that arrives afterwards is ignored
    };

    function presentationsOrigin() {
        return new URL(URLS.presentations).origin;
    }

    function presentationsActive() {
        const page = location.hash.slice(1);
        return page === 'presentations' && !!currentUserContext && allowedPages.has(page);
    }

    // The browser reports a refused portal address like a network error. A plain request that the server does answer
    // tells the two apart.
    function presentationsFetchError(timedOut) {
        if (timedOut) return Promise.reject(new Error('Presentations is taking too long to answer. Please use Reload in a moment.'));
        return fetch(presentationsOrigin() + '/health', {mode: 'no-cors', cache: 'no-store'}).then(
            () => { throw Object.assign(new Error('Presentations is not set up to open from this portal address (' + location.origin + '). Please tell the portal administrator.'), {portalRefused: true}); },
            () => { throw new Error('Presentations could not be reached. Check your connection, then use Reload.'); }
        );
    }

    // One request at a time, and a just-made answer is reused for a few seconds, so a page that keeps asking cannot
    // flood the sign-in service.
    function refreshPresentationsSession() {
        const signIn = presentationsSignIn;
        if (signIn.lastData && Date.now() - signIn.lastRefresh < 5000) return Promise.resolve(signIn.lastData);
        if (signIn.request) return signIn.request;
        const generation = signIn.generation;
        const controller = new AbortController();
        const signedOut = () => new Error('You signed out.');
        let timedOut = false;
        const timeout = setTimeout(() => { timedOut = true; controller.abort(); }, 25000);
        signIn.abort = controller;
        const request = signIn.request = ensureMissionSession()
            .then(token => {
                if (generation !== signIn.generation) throw signedOut();
                return fetch(presentationsOrigin() + '/api/session', {method: 'POST', credentials: 'include', headers: {Authorization: 'Bearer ' + token}, signal: controller.signal})
                    .catch(() => generation !== signIn.generation ? Promise.reject(signedOut()) : presentationsFetchError(timedOut));
            })
            .then(async response => {
                const data = await response.json().catch(() => ({}));
                if (generation !== signIn.generation) throw signedOut();
                if (!response.ok) throw new Error(data.error || 'Presentations are not available right now.');
                signIn.lastRefresh = Date.now();
                signIn.lastData = data;
                return data;
            })
            .finally(() => {
                clearTimeout(timeout);
                if (signIn.request === request) {
                    signIn.request = null;
                    signIn.abort = null;
                }
            });
        return request;
    }

    // Sign-out: cancel any renewal still on its way (a late answer would sign this browser back in), then end the
    // Presentations session and its cookie.
    function endPresentationsSession() {
        const signIn = presentationsSignIn;
        signIn.generation++;
        stopPresentationsKeepAlive();
        if (signIn.abort) signIn.abort.abort();
        signIn.request = null;
        signIn.abort = null;
        signIn.lastData = null;
        signIn.lastRefresh = 0;
        let origin;
        try { origin = presentationsOrigin(); } catch { return Promise.resolve(); }
        return fetch(origin + '/api/logout', {method: 'POST', credentials: 'include', mode: 'no-cors'}).catch(() => {});
    }

    function tellPresentations(message) {
        try { frame.contentWindow?.postMessage(message, presentationsOrigin()); } catch {}
    }

    function stopPresentationsKeepAlive() {
        clearTimeout(presentationsSignIn.timer);
        presentationsSignIn.timer = 0;
    }

    // Every 4 minutes, or sooner when the session ends earlier (it never outlives the portal token, which
    // ensureMissionSession renews).
    function schedulePresentationsKeepAlive(expiresAt) {
        stopPresentationsKeepAlive();
        const left = (Date.parse(expiresAt) || 0) - Date.now();
        presentationsSignIn.timer = setTimeout(() => keepPresentationsAlive().catch(() => {}), Math.min(240000, Math.max(15000, left - 90000)));
    }

    function keepPresentationsAlive() {
        if (!presentationsActive()) {
            stopPresentationsKeepAlive();
            return Promise.reject(new Error('Open Presentations in the portal to continue.'));
        }
        // No new timer once the person has signed out meanwhile.
        const generation = presentationsSignIn.generation;
        const stillHere = () => generation === presentationsSignIn.generation && presentationsActive();
        return refreshPresentationsSession().then(
            data => {
                if (stillHere()) {
                    schedulePresentationsKeepAlive(data.expires_at);
                    tellPresentations({type: 'presentations-session-refreshed', expires_at: data.expires_at});
                }
                return data;
            },
            error => {
                if (stillHere()) {
                    stopPresentationsKeepAlive();
                    presentationsSignIn.timer = setTimeout(() => keepPresentationsAlive().catch(() => {}), 30000);
                }
                throw error;
            }
        );
    }

    window.addEventListener('message', event => {
        if (event.data?.type !== 'presentations-session-request') return;
        let origin;
        try { origin = presentationsOrigin(); } catch { return; }
        if (event.origin !== origin || event.source !== frame.contentWindow || !presentationsActive()) return;
        keepPresentationsAlive().catch(error => tellPresentations({type: 'presentations-session-error', message: error.message}));
    });

    // Timers are slowed down while the tab is hidden or the laptop sleeps: renew when the tab is seen again.
    document.addEventListener('visibilitychange', () => {
        if (document.visibilityState === 'visible' && presentationsActive() && Date.now() - presentationsSignIn.lastRefresh > 60000) {
            keepPresentationsAlive().catch(() => {});
        }
    });


    // ---- 11. Dashboards sign-in (DataEase, port 8088) --------------------------------------------------------------------
    // portal-api's cookie gfm_dataease lasts 15 minutes, so the shell renews it every 10 minutes while Dashboards are
    // open, when the tab becomes visible again, and when DataEase's "Please open Dashboards" page in the frame asks
    // ('dataease-session-request'). Managers only: portal-api refuses everyone else.
    const dashboardsSignIn = {timer: 0, request: null, abort: null, lastRefresh: 0, generation: 0};

    function dataeaseActive() {
        return location.hash === '#insights' && !!currentUserContext && allowedPages.has('insights');
    }

    function refreshDataEaseSession() {
        const signIn = dashboardsSignIn;
        if (signIn.request) return signIn.request;
        const generation = signIn.generation;
        const controller = new AbortController();
        const timeout = setTimeout(() => controller.abort(), 25000);
        signIn.abort = controller;
        const request = signIn.request = ensureMissionSession()
            .then(token => fetch('/api/dataease/session', {method: 'POST', cache: 'no-store', headers: {Authorization: 'Bearer ' + token}, signal: controller.signal}))
            .catch(error => {
                if (generation !== signIn.generation) throw new Error('You signed out.');
                if (error.name === 'AbortError') throw new Error('Dashboards are taking too long to answer. Please use Reload in a moment.');
                throw error;
            })
            .then(async response => {
                const data = await response.json().catch(() => ({}));
                if (generation !== signIn.generation) throw new Error('You signed out.');
                if (!response.ok) throw Object.assign(new Error(data.error || 'Dashboards are not available right now.'), {status: response.status});
                signIn.lastRefresh = Date.now();
                return data;
            })
            .finally(() => {
                clearTimeout(timeout);
                if (signIn.request === request) {
                    signIn.request = null;
                    signIn.abort = null;
                }
            });
        return request;
    }

    function stopDataEaseKeepAlive() {
        clearTimeout(dashboardsSignIn.timer);
        dashboardsSignIn.timer = 0;
    }

    function tellDataEase(message) {
        try { frame.contentWindow?.postMessage(message, DATAEASE_ORIGIN); } catch {}
    }

    function keepDataEaseAlive() {
        stopDataEaseKeepAlive();
        if (!dataeaseActive()) return Promise.reject(new Error('Open Dashboards in the portal to continue.'));
        const generation = dashboardsSignIn.generation;
        const stillHere = () => generation === dashboardsSignIn.generation && dataeaseActive();
        return refreshDataEaseSession().then(
            data => {
                if (stillHere()) {
                    dashboardsSignIn.timer = setTimeout(() => keepDataEaseAlive().catch(() => {}), 600000);
                    tellDataEase({type: 'dataease-session-refreshed', expires_at: data.expires_at});
                }
                return data;
            },
            error => {
                if (stillHere()) dashboardsSignIn.timer = setTimeout(() => keepDataEaseAlive().catch(() => {}), 30000);
                throw error;
            }
        );
    }

    window.addEventListener('message', event => {
        if (event.data?.type !== 'dataease-session-request') return;
        if (event.origin !== DATAEASE_ORIGIN || event.source !== frame.contentWindow || !dataeaseActive()) return;
        keepDataEaseAlive().catch(error => tellDataEase({type: 'dataease-session-error', message: error.message}));
    });

    document.addEventListener('visibilitychange', () => {
        if (document.visibilityState === 'visible' && dataeaseActive() && Date.now() - dashboardsSignIn.lastRefresh > 60000) {
            keepDataEaseAlive().catch(() => {});
        }
    });

    // Sign-out: cancel a renewal still on its way, then clear the cookie. Cookies belong to the host name, not the
    // port, so DataEase's front (/gfm-signout) clears the one portal-api set; no token needed. On the public address the
    // cookie belongs to the whole domain, and dashboards.<domain>/gfm-signout clears that one.
    function endDataEaseSession() {
        const signIn = dashboardsSignIn;
        signIn.generation++;
        stopDataEaseKeepAlive();
        if (signIn.abort) signIn.abort.abort();
        signIn.request = null;
        signIn.abort = null;
        signIn.lastRefresh = 0;
        return fetch(DATAEASE_ORIGIN + '/gfm-signout', {credentials: 'include', mode: 'no-cors', cache: 'no-store'}).catch(() => {});
    }


    // ---- 12. Signing out -------------------------------------------------------------------------------------------------
    // Whenever the sign-in page shows (Sign Out, an expired portal session), the Dashboards sign-in ends too, so it never
    // outlasts the portal sign-in in this browser (a shared computer).
    const shellShowLogin = showLogin;
    showLogin = function () {
        endDataEaseSession();
        return shellShowLogin.apply(this, arguments);
    };

    // True while a sign-in token has more than 30 seconds left.
    function tokenFresh(token) {
        try {
            const raw = token.split('.')[1].replace(/-/g, '+').replace(/_/g, '/');
            return JSON.parse(atob(raw + '='.repeat((4 - raw.length % 4) % 4))).exp * 1000 > Date.now() + 30000;
        } catch {
            return false;
        }
    }

    // Ends the Supabase session (POST /auth/v1/logout, this session only), so the refresh token kept in this browser
    // stops working, and removes this device's reminders, so the next person on a shared device does not get them.
    async function endSignInSession(access, refresh) {
        let token = tokenFresh(access) ? access : null;
        if (!token && refresh) {
            // An expired access token cannot sign out; one refresh gives a current one.
            const response = await fetch(SUPABASE_URL + '/auth/v1/token?grant_type=refresh_token', {
                method: 'POST',
                headers: {apikey: SUPABASE_ANON_KEY, 'Content-Type': 'application/json'},
                body: JSON.stringify({refresh_token: refresh})
            }).catch(() => null);
            if (response && response.ok) token = (await response.json().catch(() => ({}))).access_token || null;
        }
        const subscription = await thisDeviceSubscription().catch(() => null);
        if (subscription) {
            if (token) {
                await fetch('/api/push/subscriptions', {
                    method: 'DELETE',
                    headers: {Authorization: 'Bearer ' + token, 'Content-Type': 'application/json'},
                    body: JSON.stringify({endpoint: subscription.endpoint})
                }).catch(() => {});
            }
            await subscription.unsubscribe().catch(() => {});
        }
        if (token) {
            await fetch(SUPABASE_URL + '/auth/v1/logout?scope=local', {
                method: 'POST',
                headers: {apikey: SUPABASE_ANON_KEY, Authorization: 'Bearer ' + token}
            }).catch(() => {});
        }
    }

    // This listens while the click travels down to Sign Out (capture), because index.html's own handler on the button
    // runs before this file's and clears the stored tokens.
    document.addEventListener('click', event => {
        if (!(event.target instanceof Element) || !event.target.closest('#logoutButton')) return;
        const access = localStorage.getItem('mission_access_token');
        const refresh = localStorage.getItem('mission_refresh_token');
        if (access || refresh) endSignInSession(access, refresh).catch(() => {});
    }, true);

    document.getElementById('logoutButton').addEventListener('click', () => {
        // Also signs out of Presentations and Dashboards; neither request needs the portal token.
        endPresentationsSession();
        endDataEaseSession();
        forgetPageBeingOpened();
        frame.src = 'about:blank';
        notice.hidden = true;
        languages.hidden = true;
        notifications.hidden = true;
        remindersOff.hidden = true;
        // DA Management ends its own session (on the public address at its own name, round 10).
        fetch(MANAGEMENT_ORIGIN + '/logout', {credentials: 'include', mode: 'no-cors'}).catch(() => {});
    });


    // ---- 13. Opening a page ---------------------------------------------------------------------------------------------
    // index.html's openPage only sets the frame's address. This fuller one first shows "Loading …", gets the Presentations
    // or Dashboards sign-in when that page needs it, and keeps the header in step. Only the latest click opens its page:
    // a sign-in takes a network round trip, and a slower, older request must not switch the person back afterwards.
    const loading = document.createElement('div');
    loading.className = 'portal-loading';
    loading.setAttribute('role', 'status');
    loading.hidden = true;
    document.querySelector('.frame-wrap').append(loading);

    let loadingTimer = 0;
    let openPageSeq = 0;
    // The page last asked for while it has not opened yet (still signing in, or that failed): Reload tries it again.
    let pendingOpen = null;

    function forgetPageBeingOpened() {
        openPageSeq++;
        pendingOpen = null;
        clearTimeout(loadingTimer);
        loading.hidden = true;
    }

    function showLoading(name) {
        clearTimeout(loadingTimer);
        loading.textContent = 'Loading ' + (name === 'insights' ? 'dashboard' : TITLES[name] || 'workspace') + '…';
        delete loading.dataset.state;
        loading.hidden = false;
    }

    // The header's description, the Library button and the frame's name for this page.
    function showHeadingFor(page) {
        subtitle.textContent = descriptions[page] || '';
        library.hidden = page !== 'presentations' || OFFICE_ONLY.has(page);
        frame.title = TITLES[page] || 'Mission workspace';
    }

    // Presentations and Dashboards need their own sign-in before their page loads. Resolves to when that sign-in ends
    // ('' for other pages).
    // - Presentations: if it fails, any older Presentations session in this browser is ended (it may be someone else's);
    //   Presentations then opens, and its library asks again and shows the reason. A portal address that Presentations
    //   refuses cannot be fixed by trying again, so that error is shown here.
    // - Dashboards: if it fails, the reason is shown here (Reload tries again) instead of DataEase's refusal.
    function signInFor(name, seq) {
        if (OFFICE_ONLY.has(name)) return '';
        if (name === 'presentations') {
            return refreshPresentationsSession().then(
                data => data.expires_at,
                error => {
                    if (error.portalRefused) throw error;
                    const ended = seq === openPageSeq ? endPresentationsSession() : Promise.resolve();
                    return ended.then(() => '');
                }
            );
        }
        if (name === 'insights') return refreshDataEaseSession().then(data => data.expires_at || 'ok');
        return '';
    }

    // While Presentations or Dashboards are open, their sign-in is renewed before it ends.
    function keepSignInAlive(name, expiresAt) {
        if (OFFICE_ONLY.has(name)) return;
        if (name === 'presentations') {
            if (expiresAt) schedulePresentationsKeepAlive(expiresAt);
            else presentationsSignIn.timer = setTimeout(() => keepPresentationsAlive().catch(() => {}), 30000);
        }
        if (name === 'insights') {
            fullScreen.hidden = false;
            dashboardsSignIn.timer = setTimeout(() => keepDataEaseAlive().catch(() => {}), 600000);
        }
    }

    function showOpenError(error) {
        clearTimeout(loadingTimer);
        loading.textContent = error.message;
        loading.dataset.state = 'error';
        loading.hidden = false;
        // A refusal will not change on Reload: Reload then reloads the page on screen instead.
        if (error.status === 403) pendingOpen = null;
        // The page shown before stays open (for example when Dashboards are refused): keep its heading with it.
        showHeadingFor(location.hash.slice(1));
    }

    const shellOpenPage = openPage;

    // On the public address: the notice page instead of a program on another port (section 1). Like the shell's own
    // openPage, without the sign-in token in the address.
    function openOfficeOnlyNotice(name) {
        frame.src = OFFICE_ONLY_PAGE + '?page=' + encodeURIComponent(name);
        document.querySelectorAll('.nav-item[data-page]').forEach(button => {
            button.classList.toggle('active', button.dataset.page === name);
        });
        history.replaceState(null, '', '#' + name);
    }

    openPage = function (name) {
        // A page this person does not have (an old link, a page for another role) opens the Overview.
        if (currentUserContext && !allowedPages.has(name)) name = 'overview';
        showLoading(name);
        // On phones, close the menu now: a sign-in takes a moment, and the loading chip is behind the menu.
        closeMenu();
        showHeadingFor(name);
        fullScreen.hidden = true;
        stopPresentationsKeepAlive();
        stopDataEaseKeepAlive();
        pendingOpen = {name};
        const seq = ++openPageSeq;
        ensureMissionSession()
            .then(() => signInFor(name, seq))
            .then(expiresAt => {
                if (seq !== openPageSeq) return;
                pendingOpen = null;
                if (OFFICE_ONLY.has(name)) openOfficeOnlyNotice(name);
                else shellOpenPage(name);
                keepSignInAlive(name, expiresAt);
                title.textContent = TITLES[name] || 'Mission System';
            })
            .catch(error => {
                if (seq === openPageSeq) showOpenError(error);
            });
        loadingTimer = setTimeout(() => {
            loading.textContent = 'Still loading — use Reload to try again.';
        }, 15000);
    };

    // A page has loaded in the frame: hide the chip, and tell the page the theme and the language.
    frame.addEventListener('load', () => {
        // An error message goes away with the next page in the frame; Reload then reloads the page on screen again.
        if (loading.dataset.state === 'error') pendingOpen = null;
        clearTimeout(loadingTimer);
        loading.hidden = true;
        tellFrame({type: 'portal-theme', theme: savedTheme()});
        tellFrame({type: 'mission-language', language: sessionStorage.getItem('mission_language') || 'en'});
    });


    // ---- 14. Start ------------------------------------------------------------------------------------------------------
    // The heading of the page in the address (#calendar …) until the first page opens.
    showHeadingFor(location.hash.slice(1));
})();
