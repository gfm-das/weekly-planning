/*
 * shell-mock.js: the demo's stand-in for the sign-in and the account services the portal shell talks to. Loaded first in
 * the demo's index.html (built from portal/index.template.html by build-demo.mjs). FAKE data only: one made-up person,
 * "Elder Sample", signed in as an AP so the whole menu shows. Nothing leaves the browser.
 */
(() => {
  const LANGUAGES = ["en", "de", "es", "fr", "it", "pt", "ro", "ru", "uk", "sv", "da", "tr", "ar", "fa"];
  const encode = value => btoa(JSON.stringify(value)).replace(/=+$/, "");
  const token = "demo." + encode({ exp: Math.floor(Date.now() / 1000) + 10 * 365 * 86400, sub: "demo" }) + ".demo";
  const user = { id: "demo", email: "elder.sample@example.invalid" };
  const context = { profile_id: "demo", display_name: "Elder Sample", app_role: "", leadership_role: "AP", additional_roles: [] };
  try {
    localStorage.setItem("mission_access_token", token);
    localStorage.setItem("mission_refresh_token", "demo");
    localStorage.setItem("mission_user", JSON.stringify(user));
    localStorage.setItem("mission_user_context", JSON.stringify(context));
  } catch {}

  const answer = (body, status = 200) => Promise.resolve(new Response(body === null ? null : JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } }));
  const realFetch = window.fetch.bind(window);
  window.fetch = (input, init = {}) => {
    const url = typeof input === "string" ? input : input.url;
    const method = (init.method || "GET").toUpperCase();
    if (/\/auth\/v1\/token/.test(url)) return answer({ access_token: token, refresh_token: "demo", user });
    if (/\/auth\/v1\/user/.test(url)) return answer(user);
    if (/\/auth\/v1\/logout/.test(url)) return answer(null, 204);
    if (/\/rest\/v1\/current_user_context/.test(url)) return answer([context]);
    if (/\/api\/languages/.test(url)) {
      if (method === "PUT") {
        try { localStorage.setItem("demo_language", JSON.parse(init.body).language); } catch {}
        return answer({});
      }
      return answer({ allowed: LANGUAGES, selected: localStorage.getItem("demo_language") || "en" });
    }
    // The sign-ins of Dashboards and Presentations (their own addresses in the real system): all fine here, then the page opens "not in the demo".
    if (/\/api\/(dataease\/)?session/.test(url)) return answer({ ok: true, expires_at: Math.floor(Date.now() / 1000) + 3600 });
    if (/\/api\//.test(url)) return answer({ error: "This is a demo with fake data. Nothing is saved." }, 404);
    return realFetch(input, init);
  };
})();
