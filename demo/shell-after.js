/*
 * shell-after.js: loaded last in the demo's index.html (after portal-enhancements.js). The pages the demo has open as they
 * are; the parts that need the full system (Weekly Planning, Dashboards, Presentations, DA Management ...) open a short
 * page that says so. A small "Demo, fake data" badge with a Download link sits in the corner.
 */
(() => {
  // Pages of the portal that the demo has as they are, and the parts that build.mjs found in demo/parts (the list is written in at build time).
  const HERE = ["overview", "callins", "calendar", "announcements", "planning", "archetypes", "vollzogen"];
  const PARTS = ["dashboards","management","presentations","whiteboard","wiki"];
  const PART_PAGES = { insights: "dashboards/index.html", whiteboard: "whiteboard/index.html", presentations: "presentations/index.html",
                       management: "management/index.html", wiki: "wiki/index.html?embed=1" };
  for (const key of Object.keys(URLS)) {
    if (HERE.includes(key)) continue;
    const part = PART_PAGES[key];
    const url = part && PARTS.includes(part.split("/")[0]) ? part : "demo-not-here.html";
    Object.defineProperty(URLS, key, { configurable: true, enumerable: true, get: () => url });
  }
  const badge = document.createElement("a");
  badge.href = "https://github.com/gfm-das/weekly-planning/releases/latest";
  badge.textContent = "Demo, fake data \u00b7 Download";
  badge.setAttribute("style", "position:fixed;left:12px;bottom:12px;z-index:60;background:#b45309;color:#fff;padding:6px 12px;border-radius:99px;font:700 12px system-ui,sans-serif;text-decoration:none;box-shadow:0 2px 8px #0004");
  document.body.append(badge);
})();
