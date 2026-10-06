// site-config.js: the mission's own web settings, read by the portal pages before anything else.
// This file is the safe default (no public address, English). The deploy (portal/deploy.sh or deploy.ps1) puts the real one in
// the running portal: publicDomain from GFM_PUBLIC_DOMAIN (portal/.env), for example example.org; defaultLanguage (deploy.sh
// only) from the mission in the database; timeZone from GFM_TIME_ZONE (portal/.env, default Europe/Berlin). Never put a secret here: every browser can read it.
window.GFM_SITE = { publicDomain: "", defaultLanguage: "en", timeZone: "Europe/Berlin" };
