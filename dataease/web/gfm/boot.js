// Loaded first by DataEase's pages (gfm-dataease-web adds it to index.html and mobile.html). Only served to a
// browser that came through the portal's Dashboards sign-in.
//  - DataEase's page looks for its own sign-in in the browser before it loads anything. The real one never reaches
//    the browser: gfm-dataease-web adds it to every request. So a marker is stored where DataEase looks.
//  - English, before DataEase's page reads the language (DataEase CE offers English and Chinese only).
//  - DataEase's sign-in page cannot be used here (there is no separate sign-in). After DataEase's own "Log out", or
//    when it thinks its sign-in ended, the page goes back to where it was; at most twice a minute, else it says
//    what to do.
//  - On DataEase's preview page (where the portal opens a dashboard), a slim bar with the dashboards of the same
//    folder as the open one ("Mission" for English, "Deutsch" for the German copies, and so on) and "All dashboards
//    and Edit" (see the end of this file). Its words are English here; ../../i18n/gfm-i18n.js (added to the page
//    after this script) shows them in the viewer's language, like every other word on the page.
(function () {
  var PREFIX = 'de_v2_'; // DataEase keeps its "user." values under this prefix when it is served at /
  var FOREVER = 253402300799000;
  // DataEase's storage (web-storage-cache): {c: created, e: expires, v: the value as JSON text}.
  function put(key, value) {
    try { localStorage.setItem(PREFIX + key, JSON.stringify({ c: Date.now(), e: FOREVER, v: JSON.stringify(value) })); } catch (e) {}
  }
  function prepare() {
    put('user.token', 'gfm-portal-session');
    put('user.language', 'en');
  }
  prepare();

  // Loads the page again at `href`, an address of this page that differs only after '#'. Round 10 fix: a reload
  // straight after location.replace() reloaded the OLD address (Edge, office network and internet alike), so the
  // bar's dashboards and "All dashboards and Edit" did nothing. Now the page is loaded again once the new address is
  // in place (the browser's "hashchange"), or after 300 ms at the latest (the same address: no hashchange comes).
  function openAgain(href) {
    var done = false;
    function load() {
      if (done) return;
      done = true;
      window.removeEventListener('hashchange', load);
      location.reload();
    }
    window.addEventListener('hashchange', load);
    location.replace(href);
    setTimeout(load, 300);
  }

  function onLoginPage() {
    return /^#\/login(\?|$)/.test(location.hash);
  }
  function backIn() {
    if (!onLoginPage()) return;
    var key = 'gfm-dataease-back', times = [];
    try { times = JSON.parse(sessionStorage.getItem(key) || '[]'); } catch (e) {}
    times = times.filter(function (t) { return Date.now() - t < 60000; });
    if (times.length >= 2) {
      document.title = 'Dashboards';
      document.documentElement.innerHTML = '<head><meta name="viewport" content="width=device-width,initial-scale=1">' +
        '<link rel="stylesheet" href="/gfm/page.css"></head><body><div class="box"><h1>Dashboards</h1>' +
        '<p>Dashboards open from the mission portal, without a separate sign-in. Use Reload at the top of the portal ' +
        'to open them again.</p></div></body>';
      return;
    }
    times.push(Date.now());
    try { sessionStorage.setItem(key, JSON.stringify(times)); } catch (e) {}
    var target = '/workbranch/index';
    var match = /[?&]redirect=([^&]*)/.exec(location.hash);
    if (match) {
      try { target = decodeURIComponent(match[1]) || target; } catch (e) {}
    }
    if (target.charAt(0) !== '/' || /^\/login/.test(target)) target = '/workbranch/index';
    prepare();
    openAgain(location.pathname + location.search + '#' + target);
  }
  window.addEventListener('hashchange', backIn);
  backIn();

  // ---- The dashboards bar ----------------------------------------------------------------------------------------
  // The portal opens a dashboard on DataEase's preview page (/#/preview?dvId=...), which gives the dashboard the
  // whole frame: next to DataEase's list and menus its text was too small on a laptop. A slim bar on top goes to the
  // other dashboards of the same folder (English: "Mission"; a translated copy: its language's folder inside
  // "Mission") and to DataEase's own page, where the list and Edit are. Computers only: phones get DataEase's phone
  // page (mobile.html), which has no bar.
  var BAR = 34; // px
  // Our dashboards have ids 115 LL DD GG PPPP 000000 (dataease/lib/languages.mjs): DD puts them in their usual
  // order (01 Key indicators, 02 Zones & districts, 03 Covenant path) in every language.
  var OUR_ID = /^115\d\d(\d\d)\d\d0000000000$/;
  function previewId() {
    if (/mobile\.html$/.test(location.pathname)) return null;
    var match = /^#\/preview\?(?:[^#]*&)?dvId=(\d{1,20})(?:&|$)/.exec(location.hash);
    return match ? match[1] : null;
  }
  function style() {
    if (document.getElementById('gfm-bar-style')) return;
    var css = document.createElement('style');
    css.id = 'gfm-bar-style';
    css.textContent =
      '#gfm-bar{position:fixed;top:0;left:0;right:0;height:' + BAR + 'px;z-index:1500;display:flex;align-items:center;' +
      'gap:2px;padding:0 8px;box-sizing:border-box;background:#fff;border-bottom:1px solid #e3eaee;overflow-x:auto;' +
      "white-space:nowrap;font:13px/1.2 'Segoe UI',Roboto,Helvetica,Arial,sans-serif;color:#17394b}" +
      '#gfm-bar a{color:#17394b;text-decoration:none;padding:7px 10px;border-radius:6px}' +
      '#gfm-bar a:hover,#gfm-bar a:focus-visible{background:#eef5f7;outline:none}' +
      '#gfm-bar a[aria-current=page]{font-weight:600;border-radius:0;box-shadow:inset 0 -2px 0 #00869e}' +
      '#gfm-bar .gfm-bar-space{flex:1 1 auto}' +
      '#gfm-bar .gfm-bar-edit{color:#3d5866}' +
      // DataEase's preview fills the window (100vh): it starts below the bar instead.
      'html.gfm-bar-on #app>.content{margin-top:' + BAR + 'px;height:calc(100vh - ' + BAR + 'px)!important}';
    (document.head || document.documentElement).appendChild(css);
  }
  function go(event) {
    // DataEase's preview does not follow a changed dvId on the same page, so the page is loaded again.
    event.preventDefault();
    openAgain(this.getAttribute('href'));
  }
  function link(text, href, current, extra) {
    var a = document.createElement('a');
    a.textContent = text;
    a.href = href;
    if (current) a.setAttribute('aria-current', 'page');
    if (extra) a.className = extra;
    a.addEventListener('click', go);
    return a;
  }
  // The dashboards next to the open one (id): the other dashboards of its folder, in their usual order.
  function dashboards(tree, id) {
    var parent = null;
    (function walk(nodes, folder) {
      (nodes || []).forEach(function (n) {
        if (n.leaf && String(n.id) === id) parent = folder;
        else if (!n.leaf) walk(n.children, n);
      });
    })(tree, { children: tree });
    var leaves = (parent ? parent.children || [] : []).filter(function (n) { return n.leaf && /^\d{1,20}$/.test(String(n.id)); });
    var rank = function (n) { var m = OUR_ID.exec(String(n.id)); return m ? Number(m[1]) : 100; };
    return leaves.sort(function (a, b) { return rank(a) - rank(b) || String(a.name).localeCompare(String(b.name)); }).slice(0, 12);
  }
  function draw(id, list) {
    var old = document.getElementById('gfm-bar');
    if (old) old.parentNode.removeChild(old);
    var nav = document.createElement('nav');
    nav.id = 'gfm-bar';
    nav.setAttribute('aria-label', 'Dashboards');
    nav.setAttribute('data-for', id);
    list.forEach(function (n) { nav.appendChild(link(String(n.name), '/#/preview?dvId=' + n.id, String(n.id) === id)); });
    var space = document.createElement('span');
    space.className = 'gfm-bar-space';
    nav.appendChild(space);
    nav.appendChild(link('All dashboards and Edit', '/#/panel/index?dvId=' + id, false, 'gfm-bar-edit'));
    document.body.appendChild(nav);
  }
  function bar() {
    var id = previewId();
    var root = document.documentElement;
    if (!id) {
      root.classList.remove('gfm-bar-on');
      var old = document.getElementById('gfm-bar');
      if (old) old.parentNode.removeChild(old);
      return;
    }
    style();
    root.classList.add('gfm-bar-on');
    if (!document.body) { document.addEventListener('DOMContentLoaded', bar); return; }
    var drawn = document.getElementById('gfm-bar');
    if (drawn && drawn.getAttribute('data-for') === id) return;
    draw(id, []);
    fetch('/de2api/dataVisualization/tree', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ busiFlag: 'dashboard' }) })
      .then(function (r) { return r.json(); })
      .then(function (answer) { if (previewId() === id && answer && answer.code === 0) draw(id, dashboards(answer.data, id)); })
      .catch(function () { /* the bar keeps "All dashboards and Edit" */ });
  }
  window.addEventListener('hashchange', bar);
  bar();
})();
