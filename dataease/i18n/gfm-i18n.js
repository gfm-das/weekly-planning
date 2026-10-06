/*
 * gfm-i18n.js: DataEase (v2.10.27 Community Edition) in the mission portal's 14 languages.
 *
 * The nginx front (gfm-dataease-web) adds this script to DataEase's app page (web/default.conf) and the front's
 * own sign-in pages load it too. DataEase itself stays in English; this script replaces its English interface
 * text in the page, by exact match of the trimmed text against /gfm-i18n/en.json, with the chosen language's
 * /gfm-i18n/<lang>.json. Three parts of each file: "messages" (DataEase's own words), "gfm" (our words: the
 * dashboards bar, the sign-in pages, and the three dashboards' titles, chart titles, filter labels and notes) and
 * "pmg" (key indicator names and Church terms in the Preach My Gospel wording; they win over the other two).
 *
 *  - Language: ?gfmLang=<code> (the portal adds it to the DataEase frame's address), remembered in this origin's
 *    localStorage ("gfm.dataease.language") for later pages without it. English, or no language: nothing is done.
 *  - Translates text nodes and the placeholder, title and aria-label attributes. Never the value of an input,
 *    and nothing inside contenteditable, code, pre, SQL/code editors (Monaco, CodeMirror, Ace), canvas or svg.
 *  - One MutationObserver, batched per animation frame; nodes already done are skipped by a WeakMap check.
 *  - Sets <html lang>. Persian and Arabic: text direction per paragraph only (unicode-bidi: plaintext); the
 *    DataEase layout is not mirrored.
 *  - Chart axis and legend text drawn on a canvas cannot be reached (see README.md).
 *
 * Also loads in Node (module.exports) for the unit tests; it then does nothing by itself.
 */
(function (root, factory) {
  'use strict';
  var api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else if (root && root.document) api.start(root);
})(typeof window !== 'undefined' ? window : this, function () {
  'use strict';

  var LANGS = ['en', 'de', 'es', 'fr', 'pt', 'uk', 'ru', 'it', 'tr', 'fa', 'ro', 'sv', 'da', 'ar'];
  var RTL = { fa: true, ar: true };
  var STORE_KEY = 'gfm.dataease.language';
  var BASE = '/gfm-i18n/';
  var ATTRS = ['placeholder', 'title', 'aria-label'];
  // Never read or change anything inside these (lower- and upper-case: svg elements keep their lower-case name).
  var SKIP_TAGS = {
    SCRIPT: 1, STYLE: 1, NOSCRIPT: 1, TEMPLATE: 1, CANVAS: 1, CODE: 1, PRE: 1, KBD: 1, SAMP: 1, IFRAME: 1,
    OBJECT: 1, EMBED: 1, VIDEO: 1, AUDIO: 1, SVG: 1, svg: 1, MATH: 1, math: 1,
  };
  // Form fields: only their placeholder, title and aria-label; never their value or content.
  var FIELD_TAGS = { INPUT: 1, TEXTAREA: 1, SELECT: 1 };
  var SKIP_CLASS = /(^|\s)(monaco-editor|CodeMirror|cm-editor|ace_editor|tox-edit-area|gfm-no-i18n)(\s|$)/;
  var PLACEHOLDER = /\{[^{}\s]+\}|%s/;
  var LETTER = /[A-Za-z]/;

  // ---------------------------------------------------------------- language
  function normalize(code) {
    if (typeof code !== 'string') return null;
    var c = code.trim().toLowerCase().split(/[-_]/)[0];
    return LANGS.indexOf(c) >= 0 ? c : null;
  }

  function paramFrom(query) {
    var m = /(?:^|[?&#])gfmLang=([^&#]*)/.exec(query || '');
    if (!m) return null;
    try { return decodeURIComponent(m[1]); } catch (e) { return m[1]; }
  }

  // The language for this page: ?gfmLang= (in the address or in the hash route), else the remembered one.
  // Returns { lang, remember } where remember is the code to store (null: leave the store alone).
  function pickLanguage(search, hash, stored) {
    var hashQuery = (hash || '').indexOf('?') >= 0 ? hash.slice(hash.indexOf('?')) : '';
    var asked = normalize(paramFrom(search)) || normalize(paramFrom(hashQuery));
    if (asked) return { lang: asked, remember: asked };
    return { lang: normalize(stored) || 'en', remember: null };
  }

  // ---------------------------------------------------------------- dictionary
  // vue-i18n literal interpolation ({'{'}, {'@'}) is shown as the bare character.
  function unescapeI18n(s) { return s.replace(/\{'([^']*)'\}/g, '$1'); }

  function escapeRegExp(s) { return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'); }

  function makeTemplate(src, dst) {
    var parts = src.split(/(\{[^{}\s]+\}|%s)/);
    var literal = parts.filter(function (p, i) { return i % 2 === 0; }).join('');
    if ((literal.match(/[A-Za-z]/g) || []).length < 3) return null; // "{0}" alone and the like: too loose
    var names = parts.filter(function (p, i) { return i % 2 === 1; });
    var re = new RegExp('^' + parts.map(function (p, i) { return i % 2 ? '(.+?)' : escapeRegExp(p); }).join('') + '$');
    return { prefix: parts[0], suffix: parts[parts.length - 1], re: re, names: names, dst: dst };
  }

  function fillTemplate(t, caps) {
    var sIndexes = [];
    t.names.forEach(function (n, i) { if (n === '%s') sIndexes.push(i); });
    var s = 0;
    return t.dst.replace(/\{[^{}\s]+\}|%s/g, function (ph) {
      if (ph === '%s') { var i = sIndexes[s++]; return i === undefined ? ph : caps[i]; }
      var j = t.names.indexOf(ph);
      return j >= 0 ? caps[j] : ph;
    });
  }

  // en: the parsed en.json, tr: the parsed <lang>.json. Both hold "messages" and "pmg" objects with the same keys.
  function buildDictionary(en, tr) {
    var exact = new Map();
    var pmgLower = new Map();
    var templates = [];
    var maxLen = 0;

    function addPair(src, dst, pmg) {
      src = src.trim(); dst = dst.trim();
      if (!src || !dst || src === dst) return;
      if (PLACEHOLDER.test(src)) { var t = makeTemplate(src, dst); if (t) templates.push(t); return; }
      exact.set(src, dst);
      if (pmg) pmgLower.set(src.toLowerCase(), dst);
      if (src.length > maxLen) maxLen = src.length;
    }

    function add(src, dst, pmg) {
      if (typeof src !== 'string' || typeof dst !== 'string') return;
      src = unescapeI18n(src); dst = unescapeI18n(dst);
      addPair(src, dst, pmg);
      // Plural forms ("{n} sample | {n} samples") and text broken by <br>: each piece is its own text node.
      [/\s\|\s/, /<br\s*\/?>/i].forEach(function (sep) {
        var a = src.split(sep), b = dst.split(sep);
        if (a.length > 1 && a.length === b.length) for (var i = 0; i < a.length; i++) addPair(a[i], b[i], pmg);
      });
    }

    // Later parts win for the same English text: our own words over DataEase's, Preach My Gospel over both.
    ['messages', 'gfm', 'pmg'].forEach(function (section) {
      var s = (en && en[section]) || {}, d = (tr && tr[section]) || {};
      Object.keys(s).forEach(function (k) { add(s[k], d[k], section === 'pmg'); });
    });
    templates.forEach(function (t) { var l = t.prefix.length + t.suffix.length + 40; if (l > maxLen) maxLen = l; });
    return { exact: exact, pmgLower: pmgLower, templates: templates, maxLen: maxLen + 2, cache: new Map() };
  }

  function lookup(dict, t) {
    var hit = dict.exact.get(t);
    if (hit !== undefined) return hit;
    // Key indicator names are written in more than one case (headings, sentences): case-insensitive for those.
    hit = dict.pmgLower.get(t.toLowerCase());
    if (hit !== undefined) return hit;
    // "Name:" is "Name" plus a colon.
    var last = t.charAt(t.length - 1);
    if ((last === ':' || last === '：') && t.length > 1) {
      hit = dict.exact.get(t.slice(0, -1).trim());
      if (hit !== undefined) return hit + ':';
    }
    // "· Calling:" (the second part of a line such as "At church: 3 · Calling: 1"): the dot, then the text.
    var first = t.charAt(0);
    if ((first === '·' || first === '•') && t.length > 2) {
      hit = lookup(dict, t.slice(1).trim());
      if (hit !== null && hit !== undefined) return first + ' ' + hit;
    }
    // "[Message," before a link and "]" after it (DataEase's chart error line): the bracket, then the text.
    if (first === '[' && t.length > 2 && t.charAt(t.length - 1) !== ']') {
      hit = lookup(dict, t.slice(1).trim());
      if (hit !== null && hit !== undefined) return '[' + hit;
    }
    if (!dict.templates.length) return null;
    if (dict.cache.has(t)) return dict.cache.get(t);
    var out = null;
    for (var i = 0; i < dict.templates.length; i++) {
      var tp = dict.templates[i];
      if (t.length <= tp.prefix.length + tp.suffix.length) continue;
      if (t.lastIndexOf(tp.prefix, 0) !== 0 || t.slice(t.length - tp.suffix.length) !== tp.suffix) continue;
      var m = tp.re.exec(t);
      if (m) { out = fillTemplate(tp, m.slice(1)); break; }
    }
    if (dict.cache.size > 5000) dict.cache.clear();
    dict.cache.set(t, out);
    return out;
  }

  // The translation of raw (surrounding white space kept), or null when there is none.
  function translateString(dict, raw) {
    if (!raw || raw.length > dict.maxLen + 40 || !LETTER.test(raw)) return null;
    var t = raw.trim();
    if (!t || t.length > dict.maxLen) return null;
    var hit = lookup(dict, t);
    if (hit === null || hit === undefined || hit === t) return null;
    if (t === raw) return hit;
    var lead = raw.slice(0, raw.indexOf(t.charAt(0)));
    var trail = raw.slice(raw.lastIndexOf(t.charAt(t.length - 1)) + 1);
    return lead + hit + trail;
  }

  // ---------------------------------------------------------------- DOM
  function skipElement(el) {
    if (SKIP_TAGS[el.nodeName]) return true;
    var ce = el.getAttribute('contenteditable');
    if (ce !== null && ce !== 'false') return true;
    if (el.getAttribute('translate') === 'no') return true;
    var cls = el.getAttribute('class');
    return !!(cls && SKIP_CLASS.test(cls));
  }

  function Translator(dict) {
    this.dict = dict;
    this.doneText = new WeakMap(); // text node -> the value it had after the last look (translated or not)
    this.doneAttr = new WeakMap(); // element -> { attribute: value after the last look }
  }

  Translator.prototype.text = function (node) {
    var v = node.nodeValue;
    if (!v || this.doneText.get(node) === v) return;
    var out = translateString(this.dict, v);
    if (out !== null && out !== v) node.nodeValue = out;
    this.doneText.set(node, out !== null ? out : v);
  };

  Translator.prototype.attributes = function (el) {
    if (el.hasAttributes && !el.hasAttributes()) return;
    var done = this.doneAttr.get(el);
    for (var i = 0; i < ATTRS.length; i++) {
      var a = ATTRS[i];
      var v = el.getAttribute(a);
      if (!v || (done && done[a] === v)) continue;
      var out = translateString(this.dict, v);
      if (out !== null && out !== v) el.setAttribute(a, out);
      if (!done) { done = {}; this.doneAttr.set(el, done); }
      done[a] = out !== null ? out : v;
    }
  };

  // Translate everything under node (node included).
  Translator.prototype.tree = function (node) {
    var stack = [node];
    while (stack.length) {
      var n = stack.pop();
      var type = n.nodeType;
      if (type === 3) { this.text(n); continue; }
      if (type === 1) {
        if (skipElement(n)) continue;
        this.attributes(n);
        if (FIELD_TAGS[n.nodeName]) continue;
      } else if (type !== 9 && type !== 11) continue;
      var kids = n.childNodes;
      for (var i = kids.length - 1; i >= 0; i--) stack.push(kids[i]);
    }
  };

  // Is node inside something never touched (an editor, a field's content, code, canvas...)? memo (a Map, one per
  // batch) remembers the answer for every ancestor seen, so a batch climbs each part of the page once.
  Translator.prototype.insideSkipped = function (node, memo) {
    var p = node.parentNode;
    if (node.nodeType === 3 && p && p.nodeType === 1 && FIELD_TAGS[p.nodeName]) return true;
    var path = [], result = false;
    for (; p && p.nodeType === 1; p = p.parentNode) {
      if (memo && memo.has(p)) { result = memo.get(p); break; }
      path.push(p);
      if (skipElement(p)) { result = true; break; }
    }
    if (memo) for (var i = 0; i < path.length; i++) memo.set(path[i], result);
    return result;
  };

  // ---------------------------------------------------------------- page
  var RTL_CSS =
    'html[data-gfm-rtl] body *:not(svg):not(canvas){unicode-bidi:plaintext}' +
    'html[data-gfm-rtl] input,html[data-gfm-rtl] textarea{unicode-bidi:plaintext}';

  // lang (optional): kept on <html>; DataEase sets its own ("en") while it starts, so it is put back after each batch.
  function watch(win, translator, lang) {
    var doc = win.document;
    var nodes = new Set(), attrs = new Set(), scheduled = false, full = false;
    var raf = win.requestAnimationFrame ? win.requestAnimationFrame.bind(win) : function (f) { return win.setTimeout(f, 16); };
    var observer;
    function flush() {
      scheduled = false;
      var root = doc.documentElement;
      if (lang && root && root.getAttribute('lang') !== lang) root.setAttribute('lang', lang);
      var n = nodes, a = attrs;
      nodes = new Set(); attrs = new Set();
      if (full) { full = false; translator.tree(doc.body || doc.documentElement); }
      else {
        var memo = new Map();
        n.forEach(function (node) {
          if (node.isConnected === false || translator.insideSkipped(node, memo)) return;
          translator.tree(node);
        });
        a.forEach(function (el) {
          if (el.isConnected === false || skipElement(el) || translator.insideSkipped(el, memo)) return;
          translator.attributes(el);
        });
      }
      observer.takeRecords(); // the records of our own changes
    }
    observer = new win.MutationObserver(function (records) {
      for (var i = 0; i < records.length && !full; i++) {
        var r = records[i];
        if (r.type === 'childList') for (var j = 0; j < r.addedNodes.length; j++) nodes.add(r.addedNodes[j]);
        else if (r.type === 'characterData') nodes.add(r.target);
        else attrs.add(r.target);
      }
      // A hidden frame gets no animation frames: past this many pending nodes, one full pass is cheaper.
      if (nodes.size + attrs.size > 4000) { full = true; nodes.clear(); attrs.clear(); }
      if (!scheduled) { scheduled = true; raf(flush); }
    });
    translator.tree(doc.body || doc.documentElement);
    observer.observe(doc.documentElement, {
      childList: true, subtree: true, characterData: true, attributes: true, attributeFilter: lang ? ATTRS.concat('lang') : ATTRS,
    });
    return observer;
  }

  function start(win) {
    var doc = win.document;
    var stored = null;
    try { stored = win.localStorage.getItem(STORE_KEY); } catch (e) { /* storage blocked: address only */ }
    var choice = pickLanguage(win.location.search, win.location.hash, stored);
    if (choice.remember && choice.remember !== stored) {
      try { win.localStorage.setItem(STORE_KEY, choice.remember); } catch (e) { /* ignore */ }
    }
    var lang = choice.lang;
    if (lang === 'en') return null;

    var html = doc.documentElement;
    html.setAttribute('lang', lang);
    if (RTL[lang]) {
      html.setAttribute('data-gfm-rtl', '');
      var style = doc.createElement('style');
      style.id = 'gfm-i18n-rtl';
      style.textContent = RTL_CSS;
      (doc.head || html).appendChild(style);
    }

    var get = function (code) {
      return win.fetch(BASE + code + '.json', { credentials: 'same-origin' }).then(function (r) {
        if (!r.ok) throw new Error(code + '.json: HTTP ' + r.status);
        return r.json();
      });
    };
    return Promise.all([get('en'), get(lang)]).then(function (files) {
      var translator = new Translator(buildDictionary(files[0], files[1]));
      var go = function () { html.setAttribute('lang', lang); return watch(win, translator, lang); };
      if (doc.body) return go();
      return new Promise(function (resolve) {
        doc.addEventListener('DOMContentLoaded', function () { resolve(go()); }, { once: true });
      });
    }).catch(function (e) {
      if (win.console) win.console.warn('[gfm-i18n] DataEase stays in English:', e && e.message);
      return null;
    });
  }

  return {
    LANGS: LANGS, RTL: RTL, STORE_KEY: STORE_KEY, ATTRS: ATTRS,
    normalize: normalize, pickLanguage: pickLanguage, buildDictionary: buildDictionary, lookup: lookup,
    translateString: translateString, skipElement: skipElement, Translator: Translator, watch: watch, start: start,
  };
});
