// The portal's theme (mission, light or dark) for every Dashboards page. The portal puts ?gfmTheme= on /gfm-start and
// tells the page again with a "portal-theme" message when the theme changes; the choice is kept here for the next page.
// Dark: the gate pages (data-gfm-gate) use page.css; DataEase's own pages are darkened by inverting the page and turning
// pictures and videos back, so the shell, the canvas and the charts all follow.
(function () {
  var KEY = 'gfm_theme', root = document.documentElement;
  function set(theme) {
    theme = theme === 'dark' || theme === 'light' ? theme : 'mission';
    root.setAttribute('data-gfm-theme', theme);
    try { localStorage.setItem(KEY, theme); } catch (e) {}
  }
  var wanted = null;
  try { wanted = new URLSearchParams(location.search).get('gfmTheme') || localStorage.getItem(KEY); } catch (e) {}
  set(wanted);
  addEventListener('message', function (e) {
    if (e.source === parent && e.data && e.data.type === 'portal-theme') set(e.data.theme);
  });
  var css = document.createElement('style');
  css.textContent =
    'html[data-gfm-theme="dark"]:not([data-gfm-gate]){background:#fff;filter:invert(.92) hue-rotate(180deg);color-scheme:dark}' +
    'html[data-gfm-theme="dark"]:not([data-gfm-gate]) :is(img,video,picture,iframe){filter:invert(1) hue-rotate(180deg)}';
  (document.head || root).appendChild(css);
})();
