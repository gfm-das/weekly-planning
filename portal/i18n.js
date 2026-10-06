/*
 * i18n.js: shows every page in the person's language (14 languages, right to left for Persian and Arabic).
 *
 * WHO USES IT
 *   Every portal page, and also DA Management (:8090) and Presentations (:3030), which load this same file from the
 *   portal. How to use it on a page and how to add texts: i18n/README.md.
 *
 * WHAT IT DOES
 *   Only interface text is translated: names, mission records and anything people wrote stay as written.
 *   Every text node, and every title, placeholder, aria-label and alt, whose English text is a catalog text
 *   (i18n/en.json) is replaced by the same key's text in the chosen language (i18n/<code>.json). A catalog text with
 *   {placeholders} also matches text with values in it ("Delete {name}?" matches "Delete Lena?"). Text a script adds
 *   later is translated too (MutationObserver), and so are alert(), confirm() and prompt().
 *
 * WHICH LANGUAGE (first match wins)
 *   ?lang= in the address (de, deu, German, fa, pes …: ISO codes, the Church's codes and names), the portal's choice
 *   for this tab (sessionStorage mission_language, set by the shell), the cookie gfm_lang (the same host on every
 *   port, so DA Management and Presentations follow the portal), then English. The shell also posts
 *   {type:'mission-language', language} to its frame when the language changes.
 *
 * HOW TO LOAD IT
 *   Synchronously in <head> (no defer): <script src="i18n.js?v=6"></script>. It sets lang and dir at once, and dates
 *   and numbers formatted without a locale follow the language.
 *
 * SECTIONS
 *   which language · catalog lookups (t, compile, whole, sentences, lookup, translate) · the page (text nodes,
 *   attributes, Church links, the "not available yet" notice, lang/dir, loading catalogs, setLanguage, watching for
 *   new text) · the public MissionI18n object.
 *
 * Tests: portal/tests/i18n-check.cjs (and i18n-scan, i18n-missing, i18n-keys for the catalogs).
 */
(() => {
  'use strict';
  if (window.MissionI18n) return;
  const sourceURL = document.currentScript?.src || new URL('i18n.js', location.href).href;
  // The 14 interface languages: their own names, the Church's language code (lang= on churchofjesuschrist.org,
  // each checked on the Church site on 28 Sep 2026) and right-to-left.
  const LANGUAGES = {
    en: { name: 'English', church: 'eng' },
    de: { name: 'Deutsch', church: 'deu' },
    es: { name: 'Español', church: 'spa' },
    fr: { name: 'Français', church: 'fra' },
    pt: { name: 'Português', church: 'por' },
    uk: { name: 'Українська', church: 'ukr' },
    ru: { name: 'Русский', church: 'rus' },
    it: { name: 'Italiano', church: 'ita' },
    tr: { name: 'Türkçe', church: 'tur' },
    fa: { name: 'فارسی', church: 'pes', rtl: true },
    ro: { name: 'Română', church: 'ron' },
    sv: { name: 'Svenska', church: 'swe' },
    da: { name: 'Dansk', church: 'dan' },
    ar: { name: 'العربية', church: 'ara', rtl: true },
  };
  // Church pages not offered in a language (checked 28 Sep 2026): these links open in English (eng) instead.
  const CHURCH_NOT_OFFERED = {
    pes: [/^\/study\/manual\/preach-my-gospel-2023\/(?!01-first-presidency-message|04-chapter-3)/],
    ara: [/^\/study\/scriptures\/dc-testament\//],
  };
  const aliases = {
    english: 'en', eng: 'en', deutsch: 'de', german: 'de', deu: 'de', ger: 'de', spanish: 'es', 'español': 'es', spa: 'es',
    french: 'fr', 'français': 'fr', fra: 'fr', fre: 'fr', portuguese: 'pt', 'português': 'pt', por: 'pt',
    ukrainian: 'uk', 'українська': 'uk', ukr: 'uk', russian: 'ru', 'русский': 'ru', rus: 'ru', italian: 'it', italiano: 'it', ita: 'it',
    turkish: 'tr', 'türkçe': 'tr', tur: 'tr', persian: 'fa', farsi: 'fa', 'فارسی': 'fa', pes: 'fa', fas: 'fa', per: 'fa',
    romanian: 'ro', 'română': 'ro', ron: 'ro', rum: 'ro', swedish: 'sv', svenska: 'sv', swe: 'sv',
    danish: 'da', dansk: 'da', dan: 'da', arabic: 'ar', 'العربية': 'ar', ara: 'ar', arb: 'ar',
  };
  // A placeholder's value is translated too when it is itself a catalog text (a status, a label, a reason …),
  // except for placeholders that always hold names, places, numbers or dates.
  const NUMBER_VALUES = /^(n|count|number|total)\d*$/;
  const DATA_VALUES = /^(name|names|first|last|person|people|email|file|files|filename|area|areas|district|zone|ward|unit|deck|slug|user|missionary|role|date|start|end|time|week|count|n|total|completed|number|value|position|address|code|id)\d*$/;
  // DA Management and portal-api write dates as "04 Oct 2026" or "04 Oct 2026 14:15" (the mission's time): shown in the
  // chosen language, as a value in a sentence or on their own (a table cell).
  const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  // The end of a sentence (a regular expression source, for the 'u' flag): ". ", "! " or "? " before a capital, a
  // quote or a bracket, but not after a day of one or two digits ("27. September", "1. Oktober" in German and Danish).
  const SENTENCE_END = '(?<!(?:^|\\D)\\d{1,2})[.!?]\\s+(?=[\\p{Lu}“"«(])';
  const ENGLISH_DATE = /^(\d{1,2}) (Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) (\d{4})(?:,? (\d{1,2}):(\d{2}))?(\.?)$/;
  // Never translated: written content and data (names, notes, plans, places). Pages mark more with data-i18n-ignore.
  const PROTECTED = 'script,style,textarea,input,code,pre,[data-i18n-ignore],[translate="no"],.notranslate,' +
    // The inspiration line is not protected: its fixed texts (our own words, the scripture excerpts and references) are
    // catalog texts; a mission focus someone typed is not, so it stays as written.
    '#assignment,#area,#district,#zone,#companions,#units,.plan-text,.plan-unit,.area-title,' +
    '#supportingPlans .item p,#events .event h2,#events .event p,#events .item h3,#events .item p,#announcements .item h3,' +
    '#announcements .item p,#announcements .announcement h3,#announcements .announcement > p,#list .announcement h2,#list .announcement > p,.attachments button,#attendees label,#reads p,' +
    // Call-ins: notes, plans and updates people wrote.
    'p.text,' +
    'select#zones option,select#districts option,select#areas option,select#users option,select.portal-language option,' +
    // Presentations: deck titles are deck content (the library cards, the access dialog, the /studio title button).
    '#grid .card h2,#accessTitle,#titleButton';
  // The English text a text node or attribute had before it was translated, so a language change starts from it.
  const nodeSources = new WeakMap(), attributeSources = new WeakMap();
  // messages: the catalogs by language code; loading: catalogs on their way.
  const messages = {}, loading = {};
  // Built from the English catalog by compile(): exact texts, texts with {placeholders} (found by their first or last
  // two letters, or tried one by one when they have neither), and the answers already worked out.
  let exact = new Map(), templates = { prefix: new Map(), suffix: new Map(), open: [] }, cache = new Map();
  // Texts this page already shows in the chosen language, each with the keys it came from ('*': several), and the
  // texts page code asked for itself (MissionI18n.t, .translate), which always stay as they are.
  const produced = new Map(), kept = new Set();
  const note = (text, key) => {
    if (produced.size >= 20000) return;
    const done = squash(text), keys = produced.get(done);
    if (keys) keys.add(key); else produced.set(done, new Set([key]));
  };
  const keep = text => { if (kept.size < 20000) kept.add(squash(text)); return text; };
  // scheduled, pendingRoots: new text waits for the next frame, then is translated in one go. languageSeq: only the
  // newest setLanguage() finishes. probing: > 0 while pieces of a longer text are tried (they are not reported).
  let scheduled = false, pendingRoots = new Set(), languageSeq = 0, probing = 0;
  // English texts on this page that no catalog has (MissionI18n.untranslated(), for the checks).
  const untranslated = new Set();
  // assignedLanguage: as it was asked for; language: normalized ("de", "pt-BR"); locale: its catalog ("de", "pt";
  // "en" when there is none: fallback); loaded: the catalogs are in; dir: ltr or rtl; church: the Church's language
  // code (lang= on churchofjesuschrist.org); source: where the language came from (address, portal, cookie, default).
  const state = { assignedLanguage: 'en', language: 'en', locale: 'en', fallback: false, loaded: false, dir: 'ltr', church: 'eng', source: 'default' };

  // ------------------------------------------------------------------ which language
  function normalize(language) {
    const raw = String(language || 'en').trim();
    if (!raw) return 'en';
    const lower = raw.toLowerCase();
    if (aliases[lower]) return aliases[lower];
    const base = lower.split(/[-_]/)[0];
    const resolved = (aliases[base] ? aliases[base] + raw.slice(base.length) : raw).replace(/_/g, '-');
    try { return new Intl.Locale(resolved).toString(); } catch { return raw; }
  }
  const baseOf = language => normalize(language).split('-')[0].toLowerCase();
  const known = language => Object.prototype.hasOwnProperty.call(LANGUAGES, baseOf(language));
  const quietly = fn => { try { return fn() || null; } catch { return null; } };
  const addressLanguage = quietly(() => new URLSearchParams(location.search).get('lang'));
  const cookieLanguage = () => quietly(() => { const m = document.cookie.match(/(?:^|;\s*)gfm_lang=([^;]+)/); return m && decodeURIComponent(m[1]); });
  const storedLanguage = () => quietly(() => sessionStorage.getItem('mission_language'));
  function remember(language) {
    quietly(() => sessionStorage.setItem('mission_language', language));
    // For the whole host (every port), so DA Management and Presentations open in the same language. On the public
    // address (round 10) they have names of their own (presentations., management. …), so the cookie is also set for
    // the whole domain there (the one of this host stays too, with the same language).
    quietly(() => { document.cookie = 'gfm_lang=' + encodeURIComponent(language) + ';path=/;max-age=31536000;SameSite=Lax'; });
    const publicDomain = ((window.GFM_SITE && window.GFM_SITE.publicDomain) || '').toLowerCase();
    const host = location.hostname.toLowerCase();
    if (publicDomain && (host === publicDomain || host.endsWith('.' + publicDomain))) {
      quietly(() => { document.cookie = 'gfm_lang=' + encodeURIComponent(language) + ';path=/;max-age=31536000;SameSite=Lax;domain=' + publicDomain + ';secure'; });
    }
  }
  function initialLanguage() {
    if (addressLanguage && known(addressLanguage)) { state.source = 'address'; return addressLanguage; }
    const stored = storedLanguage(); if (stored) { state.source = 'portal'; return stored; }
    const cookie = cookieLanguage(); if (cookie) { state.source = 'cookie'; return cookie; }
    // The mission's default language (site-config.js, written by the deploy from the database), else English.
    const mission = window.GFM_SITE && window.GFM_SITE.defaultLanguage;
    if (mission && known(mission)) { state.source = 'mission'; return mission; }
    return 'en';
  }

  // Dates and numbers formatted without a locale follow the chosen language, with Latin digits everywhere so they
  // match the numbers the pages print themselves, and the Gregorian calendar (the mission's weeks and meetings; Persian
  // would otherwise show the Solar Hijri calendar). Code that names a locale ("sv-SE", "en-CA" …) keeps it, except
  // that a Persian or Arabic one ("fa", "ar-EG", the page's lang that charts and the glimpse pass on) gets the same
  // Latin digits and Gregorian calendar, unless it asks for its own (-u-).
  const LATIN_GREGORIAN = '-u-ca-gregory-nu-latn';
  function formatLocale() {
    if (state.fallback) return 'en';
    return LANGUAGES[state.locale]?.rtl ? state.language + LATIN_GREGORIAN : state.language;
  }
  const latinDigits = locale => (typeof locale === 'string' && /^(fa|ar)(-|$)/i.test(locale) && !/-u-/i.test(locale) ? locale + LATIN_GREGORIAN : locale);
  (function followLanguageInFormats() {
    const pick = locales => (locales === undefined || locales === null ? formatLocale() : Array.isArray(locales) ? locales.map(latinDigits) : latinDigits(locales));
    for (const name of ['DateTimeFormat', 'NumberFormat']) {
      const Native = Intl[name];
      const Wrapped = function (locales, options) { return new Native(pick(locales), options); };
      Wrapped.prototype = Native.prototype;
      Wrapped.supportedLocalesOf = Native.supportedLocalesOf.bind(Native);
      Object.defineProperty(Wrapped, 'name', { value: name });
      Intl[name] = Wrapped;
    }
    for (const [proto, names] of [[Date.prototype, ['toLocaleString', 'toLocaleDateString', 'toLocaleTimeString']], [Number.prototype, ['toLocaleString']]]) {
      for (const name of names) {
        const native = proto[name];
        Object.defineProperty(proto, name, { configurable: true, writable: true, value: function (locales, options) { return native.call(this, pick(locales), options); } });
      }
    }
  })();

  // ------------------------------------------------------------------ catalog lookups
  function pluralCategory(count) {
    try { return new Intl.PluralRules(state.locale).select(Number(count)); } catch { return 'other'; }
  }
  function t(key, values = {}) {
    let text = messages[state.locale]?.[key] ?? messages.en?.[key];
    if (text && typeof text === 'object') {
      const count = values.count ?? values.n ?? Object.values(values).find(v => /^\d+$/.test(String(v)));
      text = text[pluralCategory(count)] ?? text.other ?? text.one;
    }
    if (text === undefined || text === null) return key;
    const done = String(text).replace(/\{([a-zA-Z0-9_]+)\}/g, (placeholder, name) => (values[name] === undefined ? placeholder : String(values[name])));
    note(done, key);
    return done;
  }
  const squash = text => String(text).replace(/\s+/g, ' ').trim();
  const PLACEHOLDER = /\{[a-zA-Z0-9_]+\}/;
  function compile(english) {
    exact = new Map(); templates = { prefix: new Map(), suffix: new Map(), open: [] }; cache = new Map();
    const push = (map, id, entry) => { const list = map.get(id) || []; list.push(entry); list.sort((a, b) => b.weight - a.weight); map.set(id, list); };
    const add = (key, text, lead = false) => {
      text = squash(text);
      if (!text) return;
      // A piece the code adds after another sentence (". Area: moves to {a} on {b}") also matches on its own, as
      // the sentence splitter below finds it ("Area: moves to …"); its translation then loses the lead too.
      if (!lead && /^[.,;·]\s+\S/.test(text)) add(key, text.replace(/^[.,;·]\s+/, ''), true);
      if (!PLACEHOLDER.test(text)) { if (!exact.has(text)) exact.set(text, lead ? { key, lead } : key); return; }
      const names = [];
      const parts = text.split(/(\{[a-zA-Z0-9_]+\})/);
      const pattern = parts.map(part => {
        const m = part.match(/^\{([a-zA-Z0-9_]+)\}$/);
        // {n}, {count}, {number} and {total} hold a number (or a dash for none), so "Section {n}" does not swallow
        // "Section saved. …". No value runs over a " · " between labels ("Baptized {date}" is only the first of
        // "Baptized 30 Aug · Confirmed 6 Sep · Found through …"; the rest are translated on their own). {role} holds a
        // role code (DL, ZL, AP …), so "{role} assignment for …" never takes "The current AP" for one, and a date
        // never runs over the end of a sentence (". Starting later: …"), though a date in the language may hold
        // ". " itself ("Sonntag, 27. September", "4. Okt. 2026").
        if (m) {
          names.push(m[1]);
          if (NUMBER_VALUES.test(m[1])) return '([-+−]?\\d[\\d\\s.,]*|[—–-])';
          if (/^role\d*$/.test(m[1])) return '([A-Z][A-Z_]{1,15})';
          return /^(date|start|end|time|week)\d*$/.test(m[1]) ? '((?:(?! · |' + SENTENCE_END + ')[\\s\\S])+?)' : '((?:(?! · )[\\s\\S])+?)';
        }
        return part.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
      }).join('');
      const prefix = parts[0], suffix = parts[parts.length - 1];
      const entry = { key, names, lead, leading: parts[0] === '', regex: new RegExp('^' + pattern + '$', 'su'), weight: text.replace(/\{[a-zA-Z0-9_]+\}/g, '').length };
      if (prefix.length >= 2) push(templates.prefix, prefix.slice(0, 2), entry);
      else if (suffix.length >= 2) push(templates.suffix, suffix.slice(-2), entry);
      else if (entry.weight >= 3) { entry.open = true; templates.open.push(entry); }
    };
    for (const [key, value] of Object.entries(english)) {
      if (value && typeof value === 'object') Object.values(value).forEach(text => add(key, text));
      else add(key, value);
    }
    templates.open.sort((a, b) => b.weight - a.weight);
  }
  const withoutLead = (text, lead) => (lead ? text.replace(/^\s*[.,;·،؛]\s*/, '') : text);
  const capitalise = text => text.charAt(0).toLocaleUpperCase(state.locale) + text.slice(1);
  function localDate(text) {
    const m = state.locale === 'en' || state.fallback ? null : ENGLISH_DATE.exec(text);
    if (!m) return null;
    const [, day, month, year, hour, minute, stop] = m;
    const options = { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' };
    if (hour) Object.assign(options, { hour: '2-digit', minute: '2-digit', hourCycle: 'h23' });
    try {
      return new Intl.DateTimeFormat(formatLocale(), options).format(new Date(Date.UTC(+year, MONTHS.indexOf(month), +day, hour ? +hour : 12, minute ? +minute : 0))) + stop;
    } catch { return null; }
  }
  // The end of a sentence and the start of the next ("… 2026. Recorded account role: …"); not the full stop of a day
  // in a date ("Sonntag, 27. September", "1. Oktober"). SENTENCE_END is defined with the other patterns above.
  const BOUNDARY = new RegExp(SENTENCE_END, 'u');
  // strict: no value runs over the end of a sentence, so a template does not swallow the sentences after it ("Area:
  // moves to {a} on {b}" and then the rest of a line); the text is then translated sentence by sentence. Only when
  // that finds nothing may a value hold several sentences (a server message inside a template).
  function whole(source, strict = true) {
    const found = exact.get(source);
    if (found) return typeof found === 'string' ? t(found) : withoutLead(t(found.key), true);
    const candidates = [...(templates.prefix.get(source.slice(0, 2)) || []), ...(templates.suffix.get(source.slice(-2)) || []), ...templates.open];
    for (const entry of candidates) {
      const m = source.match(entry.regex);
      if (!m || (strict && entry.names.some((_, i) => BOUNDARY.test(m[i + 1])))) continue;
      const values = {}, translated = [];
      let fits = true;
      entry.names.forEach((name, i) => {
        const raw = m[i + 1];
        if (DATA_VALUES.test(name)) { values[name] = localDate(raw) ?? raw; return; }
        probing++;
        try {
          values[name] = translatePlain(raw);
          // A value that opens the English sentence has a capital only for that ("The current ZL assignment … already
          // ends on …"): it is looked up as running text, and the sentence gets its capital back below.
          if (values[name] === raw && i === 0 && entry.leading && /^\p{Lu}\p{Ll}/u.test(raw)) {
            const lower = raw.charAt(0).toLowerCase() + raw.slice(1), done = translatePlain(lower);
            if (done !== lower) values[name] = done;
          }
        } finally { probing--; }
        if (values[name] !== raw) translated.push(values[name]);
        // A text that neither starts nor ends like the template ("{a} and {b}", "“{a}” is {b}") fits only when its
        // parts are catalog texts too (or numbers), so English that happens to contain " and " stays as it is.
        if (entry.open && values[name] === raw && /\p{L}{2}/u.test(raw)) fits = false;
      });
      if (!fits) continue;
      // A value that ends with a full stop (a date written "2026 р.") before the sentence's own: one full stop.
      const done = withoutLead(t(entry.key, values), entry.lead).replace(/(?<!\.)\.\.(?=\s|$)/g, '.');
      // A sentence that starts with a translated phrase ("призначення … більше не закінчується …") starts with a capital,
      // as the English does.
      return /^\p{Lu}/u.test(source) && /^\p{Ll}/u.test(done) && translated.some(value => done.startsWith(value)) ? capitalise(done) : done;
    }
    return null;
  }
  // A message built from several catalog messages ("Question retired: … Saved answers stay." plus a sentence about
  // the rules that look at it): the longest run of whole sentences the catalog knows, then the rest the same way.
  function sentences(source) {
    const parts = source.split(/(?<=[.!?])\s+(?=[\p{Lu}“"«(])/u);
    if (parts.length < 2 || parts.length > 12) return null;
    const out = [];
    let changed = false;
    for (let i = 0; i < parts.length;) {
      let j = parts.length;
      for (; j > i; j -= 1) {
        if (j - i === parts.length) continue;
        const done = sentence(parts.slice(i, j).join(' '));
        if (done !== null) { out.push(done); changed = true; break; }
      }
      if (j === i) { out.push(parts[i]); i += 1; } else i = j;
    }
    return changed ? out.join(' ') : null;
  }
  // A sentence, also when the catalog has it without its full stop (a piece the code ends with "." itself): that is
  // tried first, so a value at the end ("… on {b}") does not take the full stop.
  function sentence(source, strict = true) {
    if (/[^.]\.$/.test(source)) {
      const bare = whole(source.slice(0, -1), strict);
      if (bare !== null) return /[.!?؟]$/.test(bare) ? bare : bare + '.';
    }
    return whole(source, strict);
  }
  function lookup(source) {
    const done = sentence(source) ?? localDate(source);
    if (done !== null) return done;
    // A piece that follows a code or a name on the same line ("· Number · required"): the rest on its own.
    const lead = /^([·•|:]\s+)(\S[\s\S]*)$/.exec(source);
    if (lead) { const rest = translatePlain(lead[2]); return rest === lead[2] ? null : lead[1] + rest; }
    // Labels joined with " · " (a person's dates, a chip with a time): each part on its own.
    if (source.includes(' · ')) {
      const parts = source.split(' · '), done = parts.map(part => translatePlain(part));
      if (done.some((part, i) => part !== parts[i])) return done.join(' · ');
    }
    // A list joined with "; " (a leader's assignments): each part on its own.
    if (source.includes('; ')) {
      const parts = source.split('; '), done = parts.map(part => translatePlain(part));
      if (done.some((part, i) => part !== parts[i])) return done.join('; ');
    }
    return sentences(source) ?? sentence(source, false);
  }
  function translatePlain(value) {
    const source = squash(value);
    if (!source) return value;
    // Text this page already shows in the chosen language (a card a script copied, a label built from a translated
    // title) stays as it is, unless it is also, word for word, the English text of another key: Italian "Zone" (for
    // "Zones") is English "Zone", Arabic "←" (for "→") is English "←". That text is read as English.
    if (kept.has(source)) return value;
    const keys = produced.get(source);
    if (keys) {
      const english = exact.get(source), key = english && (typeof english === 'string' ? english : english.key);
      if (!key || keys.has(key)) return value;
    }
    if (!cache.has(source)) {
      const found = lookup(source);
      cache.set(source, found);
      if (found !== null) note(found, '*');
    }
    const result = cache.get(source);
    // Pieces tried while matching a longer text are not reported; the text itself is.
    if (result === null && !probing && /\p{L}{2}/u.test(source) && untranslated.size < 5000) untranslated.add(source);
    return result ?? value;
  }
  function translate(value) {
    const raw = String(value ?? '');
    if (!state.loaded || !raw.trim()) return raw;
    const result = translatePlain(raw);
    if (result === raw) return raw;
    return (raw.match(/^\s*/)?.[0] || '') + result + (raw.match(/\s*$/)?.[0] || '');
  }

  // ------------------------------------------------------------------ the page
  function sourceRecord(records, node, current) {
    const record = records.get(node);
    if (record && record.applied === current) return record;
    const next = { source: current, applied: current };
    records.set(node, next);
    return next;
  }
  const isProtected = element => !!element?.closest?.(PROTECTED);
  const within = (root, selector) => (root.matches?.(selector) ? [root, ...root.querySelectorAll(selector)] : [...root.querySelectorAll(selector)]);
  function explicitLabels(root) {
    within(root, '[data-i18n]').forEach(element => {
      const value = t(element.dataset.i18n);
      if (!element.children.length) { if (element.textContent !== value) element.textContent = value; return; }
      const text = Array.from(element.childNodes).find(node => node.nodeType === Node.TEXT_NODE && node.nodeValue.trim());
      if (text && text.nodeValue.trim() !== value) text.nodeValue = value;
    });
  }
  function translateNode(node) {
    const parent = node.parentElement;
    if (!parent || !node.nodeValue.trim() || isProtected(parent)) return;
    // An element with its own key (data-i18n) takes its text from the key, whatever it shows now.
    if (parent.hasAttribute('data-i18n')) { explicitLabels(parent); return; }
    const record = sourceRecord(nodeSources, node, node.nodeValue);
    const value = translate(record.source);
    if (value !== node.nodeValue) {
      // Options without a value would otherwise send their translated text with the form.
      if (parent.tagName === 'OPTION' && !parent.hasAttribute('value')) parent.value = record.source.trim();
      node.nodeValue = value;
    }
    record.applied = value;
  }
  function translateText(root) {
    if (root.nodeType === Node.TEXT_NODE) { translateNode(root); return; }
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
      acceptNode(node) { return !node.nodeValue.trim() || isProtected(node.parentElement) ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT; },
    });
    while (walker.nextNode()) translateNode(walker.currentNode);
  }
  const ATTRIBUTES = ['placeholder', 'title', 'aria-label', 'alt'];
  const ATTRIBUTE_SELECTOR = '[placeholder],[title],[aria-label],[alt],[data-i18n-placeholder],[data-i18n-title],[data-i18n-aria-label],input[type=submit][value]:not([name]),input[type=button][value]:not([name])';
  function translateAttributes(root) {
    within(root, ATTRIBUTE_SELECTOR).forEach(element => {
      if (element.closest('[data-i18n-ignore],[translate="no"],.notranslate')) return;
      let records = attributeSources.get(element);
      if (!records) { records = new Map(); attributeSources.set(element, records); }
      // A button-like input without a name shows its value and sends nothing, so its value is text too.
      const names = element.tagName === 'INPUT' && /^(submit|button)$/i.test(element.type) && !element.name ? [...ATTRIBUTES, 'value'] : ATTRIBUTES;
      names.forEach(attribute => {
        const explicit = element.getAttribute('data-i18n-' + attribute);
        const current = element.getAttribute(attribute);
        if (!explicit && current === null) return;
        let record = records.get(attribute);
        if (!record || record.applied !== current) { record = { source: current || '', applied: current }; records.set(attribute, record); }
        const value = explicit ? t(explicit) : translate(record.source);
        if (current !== value) element.setAttribute(attribute, value);
        record.applied = value;
      });
    });
  }
  // Links to churchofjesuschrist.org open in the reader's language (lang=deu, lang=pes …), or in English where the
  // Church does not offer that page in the language.
  function churchUrl(url, language = state.language) {
    try {
      const u = new URL(url, location.href);
      if (!/(^|\.)churchofjesuschrist\.org$/i.test(u.hostname)) return url;
      let code = LANGUAGES[baseOf(language)]?.church || 'eng';
      if ((CHURCH_NOT_OFFERED[code] || []).some(rule => rule.test(u.pathname))) code = 'eng';
      u.searchParams.set('lang', code);
      return u.href;
    } catch { return url; }
  }
  function churchLinks(root) {
    within(root, 'a[href*="churchofjesuschrist.org"]').forEach(link => {
      const next = churchUrl(link.getAttribute('href'));
      if (next !== link.getAttribute('href')) link.setAttribute('href', next);
    });
  }
  function fallbackNotice() {
    let notice = document.getElementById('mission-i18n-fallback');
    if (!state.fallback || !document.body) { notice?.remove(); return; }
    if (!notice) {
      notice = document.createElement('div'); notice.id = 'mission-i18n-fallback';
      notice.setAttribute('data-i18n-ignore', ''); notice.setAttribute('role', 'status');
      notice.style.cssText = 'margin:12px auto;padding:10px 14px;max-width:1220px;border-radius:10px;background:#e9f3f2;color:#34545f;font:12px/1.5 system-ui,sans-serif;';
      document.body.prepend(notice);
    }
    let name = state.assignedLanguage;
    try { name = new Intl.DisplayNames(['en'], { type: 'language' }).of(state.language) || name; } catch {}
    const text = 'Interface translation for ' + name + ' is not available yet. Showing English.';
    if (notice.textContent !== text) notice.textContent = text;
  }
  function apply(root = document.body) {
    if (!root) return;
    if (root.nodeType === Node.ELEMENT_NODE) churchLinks(root);
    if (!state.loaded) return;
    if (root.nodeType === Node.ELEMENT_NODE) { explicitLabels(root); translateAttributes(root); }
    translateText(root);
    if (root === document.body) { const title = document.querySelector('title'); if (title) translateText(title); fallbackNotice(); }
  }
  // Right-to-left: dir="rtl" mirrors most of a page; i18n/rtl.css fixes what uses left and right directly.
  function setDocument() {
    const html = document.documentElement;
    html.lang = state.fallback ? 'en' : state.language;
    html.dir = state.dir;
    html.dataset.assignedLanguage = state.assignedLanguage;
    html.dataset.i18nFallback = String(state.fallback);
    if (state.dir === 'rtl' && !document.getElementById('mission-i18n-rtl')) {
      const link = document.createElement('link');
      link.id = 'mission-i18n-rtl'; link.rel = 'stylesheet'; link.href = new URL('i18n/rtl.css', sourceURL).href;
      (document.head || document.documentElement).append(link);
    }
  }
  function load(code) {
    if (messages[code]) return Promise.resolve(messages[code]);
    // 'no-cache': the browser asks whether its copy is still current (a cheap 304), so a deploy arrives at once.
    loading[code] = loading[code] || fetch(new URL('i18n/' + code + '.json', sourceURL), { credentials: 'omit', cache: 'no-cache' })
      .then(response => { if (!response.ok) throw new Error('Translation catalog unavailable.'); return response.json(); })
      .then(catalog => { messages[code] = catalog; delete loading[code]; return catalog; }, error => { delete loading[code]; throw error; });
    return loading[code];
  }
  function setLanguage(language, options = {}) {
    const seq = ++languageSeq;
    state.assignedLanguage = String(language || 'en');
    state.language = normalize(language);
    const base = state.language.split('-')[0].toLowerCase();
    state.fallback = !LANGUAGES[base];
    state.locale = state.fallback ? 'en' : base;
    state.dir = LANGUAGES[state.locale].rtl ? 'rtl' : 'ltr';
    state.church = LANGUAGES[state.locale].church;
    if (options.remember !== false && !state.fallback) remember(state.language);
    cache = new Map(); produced.clear(); kept.clear(); untranslated.clear();
    setDocument();
    const ready = Promise.all([load('en'), state.locale === 'en' ? null : load(state.locale)]).then(() => {
      if (seq !== languageSeq) return api;
      if (!state.loaded) compile(messages.en);
      state.loaded = true;
      // Text shown while this catalog was on its way (the shell's reminder notice right after signing in) could only
      // fall back to English, and was noted as done: forget that, so the pass below shows it in the language.
      cache = new Map(); produced.clear(); kept.clear();
      apply(); window.dispatchEvent(new CustomEvent('mission-i18n-change', { detail: { ...state } }));
      return api;
    }).catch(error => { state.error = error.message; document.documentElement.dataset.i18nError = 'true'; console.warn(error.message); return api; });
    return options.wait ? ready : { ...state };
  }
  function schedule(root) {
    pendingRoots.add(root);
    if (scheduled) return;
    scheduled = true;
    requestAnimationFrame(() => {
      scheduled = false;
      const roots = [...pendingRoots]; pendingRoots = new Set();
      for (const root of roots) if (root.isConnected) apply(root);
    });
  }
  function watch() {
    new MutationObserver(records => {
      for (const record of records) {
        if (record.type === 'childList') record.addedNodes.forEach(node => { if (node.nodeType === Node.ELEMENT_NODE || node.nodeType === Node.TEXT_NODE) schedule(node); });
        else schedule(record.target);
      }
    }).observe(document.documentElement, { subtree: true, childList: true, characterData: true, attributes: true, attributeFilter: ['placeholder', 'title', 'aria-label', 'alt', 'href', 'value'] });
    apply();
  }
  // alert(), confirm() and prompt() show their text in the chosen language too, line by line, so a message that lists
  // one change per line (DA Management's "Save these changes?") keeps its lines.
  const dialogText = text => String(text).split('\n').map(line => translate(line)).join('\n');
  for (const name of ['alert', 'confirm', 'prompt']) {
    const native = window[name];
    if (typeof native === 'function') window[name] = function (text, ...rest) { return native.call(window, text === undefined ? text : dialogText(text), ...rest); };
  }

  const api = {
    apply, setLanguage, state, churchUrl, normalize,
    // A text a page asks for and puts on the page itself stays as it is there (once the catalogs are loaded: before,
    // the page gets the English, which is translated on the page as usual).
    t: (key, values) => { const out = t(key, values); if (state.loaded) keep(out); return out; },
    translate: value => { const out = translate(value); if (out !== String(value ?? '')) keep(out); return out; },
    languages: Object.fromEntries(Object.entries(LANGUAGES).map(([code, info]) => [code, { name: info.name, church: info.church, rtl: !!info.rtl }])),
    // ?lang= of this page's address, when it names one of the 14 languages.
    addressLanguage: addressLanguage && known(addressLanguage) ? normalize(addressLanguage) : null,
    number: (value, options) => new Intl.NumberFormat(formatLocale(), options).format(value),
    date: (value, options) => new Intl.DateTimeFormat(formatLocale(), options).format(new Date(value)),
    // The best of another tool's own languages (DataEase, …) for the chosen language, or the fallback.
    bestOf: (available, fallback = 'en') => available.find(code => code.toLowerCase() === state.language.toLowerCase()) || available.find(code => code.toLowerCase().split(/[-_]/)[0] === state.locale) || fallback,
    // A frame's address with the chosen language in it: withLanguage(src) adds ?lang=de (DA Management, Presentations,
    // a new page), withLanguage(src, 'gfmLang') what the DataEase front reads. English (or no catalog) leaves it out.
    withLanguage: (url, param = 'lang') => {
      try {
        const u = new URL(url, location.href);
        if (state.fallback || state.locale === 'en') u.searchParams.delete(param); else u.searchParams.set(param, state.locale);
        return u.href;
      } catch { return url; }
    },
    supported: () => Object.keys(LANGUAGES),
    untranslated: () => [...untranslated],
  };
  window.MissionI18n = api;
  // The portal shell, on this host (any port), says which language to show.
  window.addEventListener('message', event => {
    if (window.parent === window || event.source !== window.parent || event.data?.type !== 'mission-language') return;
    let sameHost = false;
    try { sameHost = event.origin === location.origin || new URL(event.origin).hostname === location.hostname; } catch {}
    if (sameHost && event.data.language && normalize(event.data.language) !== state.language) setLanguage(event.data.language);
  });
  window.addEventListener('storage', event => { if (event.key === 'mission_language' && event.newValue) setLanguage(event.newValue, { remember: false }); });
  const first = initialLanguage();
  // ?lang= and the portal's choice for this tab are written to the gfm_lang cookie too, so DA Management and
  // Presentations opened from this tab follow them; a language that only came from the cookie is left as it is.
  api.ready = setLanguage(first, { wait: true, remember: state.source === 'address' || state.source === 'portal' }).then(() => {
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', watch, { once: true }); else watch();
    return api;
  });
})();
