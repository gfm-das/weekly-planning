/*
 * demo-mock.js: the demo's stand-in for portal-api. No server, no sign-in, FAKE data only.
 *
 * What it is: it replaces window.portalAPI (portal-client.js) with a function that answers from the JSON files in
 * fixtures/. The real portal pages (home, call-ins, calendar, announcements) run unchanged on top
 * of it; demo/build-demo.mjs copies them from portal/ and adds this script right after portal-client.js.
 * Reading works; every save (PUT, POST, DELETE) answers "This is a demo ... nothing is saved" so nobody thinks a change
 * was made. The fixtures hold dates as tokens (@week-0, @dt+2@19:00); this file turns them into real dates, so the demo
 * is never out of date.
 */
(() => {
  const BASE = new URL("fixtures/", document.currentScript ? document.currentScript.src : location.href);
  const ZONE = "Europe/Berlin";
  const cache = new Map();

  // ---- Dates in the fixtures -------------------------------------------------------------------------------------
  const pad = (n) => String(n).padStart(2, "0");
  const addDays = (date, days) => {
    const copy = new Date(date.getFullYear(), date.getMonth(), date.getDate());
    copy.setDate(copy.getDate() + days);
    return copy;
  };
  const ymd = (date) => `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
  // The reporting week's key is a Sunday: the latest one that is today or earlier.
  const sunday = () => {
    const now = new Date();
    return addDays(now, -now.getDay());
  };
  // "2026-09-29T19:00" read as the mission's wall-clock time, as an exact moment (the same method as calendar.html).
  const wallToISO = (wall) => {
    const shown = (date) =>
      new Intl.DateTimeFormat("sv-SE", { timeZone: ZONE, year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false })
        .format(date)
        .replace(" ", "T");
    let guess = new Date(wall + ":00Z");
    for (let round = 0; round < 3; round++) guess = new Date(guess.getTime() + (new Date(wall + ":00Z") - new Date(shown(guess) + ":00Z")));
    return guess.toISOString();
  };
  function expand(text) {
    const week = sunday();
    const today = new Date();
    return text
      .replace(/@week-(\d+)/g, (m, n) => ymd(addDays(week, -7 * Number(n))))
      .replace(/@day([+-]\d+)(?!@)/g, (m, offset) => ymd(addDays(today, Number(offset))))
      .replace(/@dt([+-]\d+)@(\d\d):(\d\d)/g, (m, offset, hour, minute) => wallToISO(`${ymd(addDays(today, Number(offset)))}T${hour}:${minute}`));
  }

  async function fixture(name) {
    if (!cache.has(name)) {
      cache.set(
        name,
        fetch(new URL(name + ".json", BASE), { cache: "no-cache" }).then(async (response) => {
          if (!response.ok) throw Object.assign(Error(tr("demo.noData", "This part of the demo has no fake data.")), { status: 404 });
          return expand(await response.text());
        }),
      );
    }
    return JSON.parse(await cache.get(name));
  }

  function failure(message, status) {
    return Object.assign(Error(message), { status, fields: null });
  }

  // The text in the reader's language when the catalog (portal/i18n, keys demo.*) has it, else the English.
  const tr = (key, english) => {
    const text = window.MissionI18n && window.MissionI18n.state && window.MissionI18n.state.loaded ? window.MissionI18n.t(key) : key;
    return text !== key ? text : english;
  };
  const demoText = () => tr("demo.notSaved", "This is a demo with fake data. Nothing is saved.");

  // ---- The routes ------------------------------------------------------------------------------------------------
  async function route(path) {
    const [name, queryText = ""] = path.split("?");
    const query = new URLSearchParams(queryText);
    if (name === "overview") return fixture("overview");
    if (name === "announcements") return fixture("announcements");
    if (name === "options") return fixture("options");
    if (name === "events") return fixture("events");
    if (name === "callins/people") return fixture("callins_people");
    if (name === "callins/gemiko") return fixture("callins_gemiko");
    if (name === "callins") {
      const level = query.get("level") || "mission";
      const id = query.get("id") || (level === "mission" ? "1" : "");
      let data;
      try {
        data = await fixture(`callins_${level}_${id}`);
      } catch {
        throw failure(tr("demo.noDataGoUp", "This part of the demo has no fake data. Go back up and choose another."), 404);
      }
      const week = query.get("week");
      return week && /^\d{4}-\d{2}-\d{2}$/.test(week) ? { ...data, week: { ...data.week, sunday: week } } : data;
    }
    if (name === "planning/form") {
      const form = await fixture("planning_form");
      const unit = Number(query.get("unit_id"));
      return unit && form.units.some((u) => u.unit_id === unit) ? { ...form, report: { ...form.report, unit_id: unit } } : form;
    }
    if (name === "planning/transfer-targets") return fixture("planning_targets");
    if (name === "archetypes/settings") return fixture("archetype_settings");
    if (name === "archetypes") return archetypesPage(query);
    if (name === "vollzogen") return vollzogenList(query);
    throw failure(tr("demo.noData", "This part of the demo has no fake data."), 404);
  }

  // Archetypal Health: one prepared answer per "weeks to average" and compare choice (made by tools/make_portal_fixtures.py);
  // the week chosen on the page is written into it.
  async function archetypesPage(query) {
    const average = query.get("weeks") || "4";
    const compare = query.get("compare");
    if (!["1", "4", "8", "12"].includes(average) || (compare && !["prev4", "prev12", "year"].includes(compare)))
      throw failure(tr("demo.noData", "This part of the demo has no fake data."), 404);
    const data = await fixture(["archetypes_w", average, compare ? "_" + compare : ""].join(""));
    const week = query.get("week");
    return week && data.weeks.some((w) => w.week === week) ? { ...data, week } : data;
  }

  // Vollzogen: the list, filtered here the way portal-api filters it (week = the Sunday of the baptism, zone, text,
  // period = a month "2026-10", a year "2026", "month" for this month, or all).
  async function vollzogenList(query) {
    const data = await fixture("vollzogen");
    const sundayOf = (iso) => ymd(addDays(new Date(iso + "T12:00:00"), (7 - (new Date(iso + "T12:00:00").getDay() || 7))));
    const items = data.items.slice().sort((a, b) => b.baptism_date.localeCompare(a.baptism_date) || a.full_name.localeCompare(b.full_name));
    const week = query.get("week") || null;
    const zone = query.get("zone") || null;
    const text = (query.get("q") || "").trim().toLowerCase();
    const thisMonth = ymd(new Date()).slice(0, 7);
    const period = query.get("period") === "month" ? thisMonth : query.get("period") || "all";
    const inPeriod = (i) => period === "all" || i.baptism_date.startsWith(period);
    const months = [...new Set(items.map((i) => i.baptism_date.slice(0, 7)).concat(thisMonth))].sort().reverse();
    const fields = ["full_name", "found_how", "workers", "unit", "stake", "zone"];
    const found = items.filter(
      (i) => inPeriod(i) && (!week || sundayOf(i.baptism_date) === week) && (!zone || i.zone === zone) && (!text || fields.some((f) => String(i[f] || "").toLowerCase().includes(text))),
    );
    return {
      ...data,
      weeks: [...new Set(items.filter(inPeriod).map((i) => sundayOf(i.baptism_date)))].sort().reverse(),
      period, this_month: thisMonth, months, years: [...new Set(months.map((m) => m.slice(0, 4)))],
      this_week: { sunday: ymd(sunday()), saturday: ymd(addDays(sunday(), 6)) },
      zones: [...new Set(items.map((i) => i.zone))].sort(),
      filter: { week, zone, q: text || null },
      items: found,
      truncated: false,
    };
  }

  window.portalAPI = async (path, options = {}) => {
    const method = (options.method || "GET").toUpperCase();
    if (method !== "GET") throw failure(demoText(), 403);
    return route(path);
  };
  window.GFM_DEMO = true;

  // ---- A page opened on its own gets the banner (inside the demo's frame the shell shows it) ----------------------
  if (window.top === window) {
    addEventListener("DOMContentLoaded", () => {
      const bar = document.createElement("div");
      bar.style.cssText = "position:sticky;top:0;z-index:99;background:#b45309;color:#fff;padding:8px 14px;font:600 14px system-ui,sans-serif;text-align:center";
      bar.innerHTML = '<span>Demo, fake data</span> &middot; <a style="color:#fff" href="https://github.com/gfm-das/weekly-planning/releases/latest">Download</a>';
      document.body.prepend(bar);
    });
  }
})();
