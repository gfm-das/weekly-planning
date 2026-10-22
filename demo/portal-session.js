/*
 * portal-session.js: keeps the portal sign-in fresh.
 *
 * Who uses it: the shell (index.html) loads it first. The shell's own script, the pages in its frame
 * (window.parent.ensureMissionSession) and the Whiteboard call window.ensureMissionSession().
 *
 * How it works: after signing in, the browser keeps two things from Supabase (the sign-in service on port 18000):
 *   mission_access_token   a short-lived pass (about an hour) that every request to portal-api carries
 *   mission_refresh_token  a one-time ticket that buys a new pass (and a new ticket)
 * ensureMissionSession() returns the pass while it has more than two minutes left, otherwise trades the ticket for a
 * new pass. It also checks once a minute, so a page left open never finds an expired pass.
 *
 * It uses SUPABASE_URL and SUPABASE_ANON_KEY from the shell's own script.
 */
(() => {
  // A trade already on its way: everyone who asks meanwhile waits for the same answer (a ticket works only once).
  let refreshing = null;

  // True while the token has more than two minutes left.
  function stillValid(token) {
    try {
      const raw = token.split(".")[1].replace(/-/g, "+").replace(/_/g, "/");
      const claims = JSON.parse(atob(raw + "=".repeat((4 - raw.length % 4) % 4)));
      return claims.exp * 1000 > Date.now() + 120000;
    } catch {
      return false;
    }
  }

  // Trades the refresh token for a new pair. A refused ticket (400/401/403) means the sign-in is over: both are
  // forgotten and the person signs in again. If another tab traded the same ticket meanwhile, this answer is not
  // stored; the next try uses that tab's new pair.
  async function renewSession() {
    const refresh = localStorage.getItem("mission_refresh_token");
    if (!refresh) throw Error("Your session expired. Sign in again.");
    const response = await fetch(`${SUPABASE_URL}/auth/v1/token?grant_type=refresh_token`, {
      method: "POST",
      headers: { apikey: SUPABASE_ANON_KEY, "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: refresh }),
    });
    if (!response.ok) {
      if ([400, 401, 403].includes(response.status)) {
        localStorage.removeItem("mission_access_token");
        localStorage.removeItem("mission_refresh_token");
        throw Error("Your session expired. Sign in again.");
      }
      throw Error("The sign-in service is unavailable. Please retry.");
    }
    const data = await response.json();
    if (localStorage.getItem("mission_refresh_token") !== refresh) throw Error("Your session changed. Please retry.");
    localStorage.setItem("mission_access_token", data.access_token);
    localStorage.setItem("mission_refresh_token", data.refresh_token);
    return data.access_token;
  }

  window.ensureMissionSession = async () => {
    const token = localStorage.getItem("mission_access_token");
    if (!token) throw Error("Sign in to continue.");
    if (stillValid(token)) return token;
    if (refreshing) return refreshing;
    refreshing = renewSession();
    try {
      return await refreshing;
    } finally {
      refreshing = null;
    }
  };

  setInterval(() => {
    if (localStorage.getItem("mission_access_token")) ensureMissionSession().catch(() => {});
  }, 60000);
})();
