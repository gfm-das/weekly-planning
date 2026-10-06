// The "Please open Dashboards from the mission portal" page (gfm-dataease-web, status 401).
(function () {
  // The portal: port 8070 of this host; on the public name (dashboards.<the public domain>, a Cloudflare
  // tunnel route) the portal's public address.
  var publicName = /^dashboards\.[^.]+\./i.test(location.hostname);
  var portal = (publicName ? 'https://' + location.hostname.replace(/^dashboards\./i, '') : location.protocol + '//' + location.hostname + ':8070') + '/#insights';
  document.getElementById('portal').href = portal;
  if (window.parent === window) return;
  // Inside the portal: ask it to renew the Dashboards sign-in, then load the page again. At most once in 20
  // seconds, so a sign-in that cannot be renewed does not loop.
  var key = 'gfm-dataease-retry', last = 0;
  try { last = Number(sessionStorage.getItem(key) || 0); } catch (e) {}
  if (Date.now() - last < 20000) {
    document.getElementById('text').textContent = 'Your Dashboards sign-in could not be renewed. Use Reload at the top of the portal, or sign in to the portal again.';
    return;
  }
  document.getElementById('text').textContent = 'Renewing your sign-in…';
  var done = false;
  window.addEventListener('message', function (event) {
    var data = event.data || {};
    if (event.source !== window.parent || done) return;
    if (data.type === 'dataease-session-refreshed') {
      done = true;
      try { sessionStorage.setItem(key, String(Date.now())); } catch (e) {}
      location.reload();
    } else if (data.type === 'dataease-session-error') {
      done = true;
      document.getElementById('text').textContent = data.message || 'Your Dashboards sign-in could not be renewed. Use Reload at the top of the portal.';
    }
  });
  window.parent.postMessage({ type: 'dataease-session-request' }, '*');
  setTimeout(function () {
    if (!done) document.getElementById('text').textContent = 'Dashboards open from the mission portal. Use Reload at the top of the portal to open them again.';
  }, 8000);
})();
