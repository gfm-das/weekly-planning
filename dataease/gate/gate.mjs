// The sign-in gate in front of DataEase (container gfm-dataease-gate). Plain Node 24, no packages.
//
// DataEase Community Edition has a single account ("admin") and no single sign-on, so people never sign in to
// DataEase themselves. Instead:
//  1. The portal asks portal-api POST /api/dataease/session (a signed-in AP, President or Data Analyst only).
//     portal-api answers with the cookie gfm_dataease: base64url(JSON {sub, exp}) + "." + base64url(HMAC-SHA256),
//     keyed with the secret that portal-api/.env holds as DATAEASE_PROXY_SECRET and dataease/.env as
//     GFM_DATAEASE_PROXY_SECRET. It lives 15 minutes; the portal renews it while Dashboards is open.
//  2. nginx (gfm-dataease-web) asks GET /check here for every request, with the browser's headers. A valid cookie
//     answers 200 with X-DE-TOKEN, DataEase's own sign-in, which nginx adds to the request it passes on. Anything
//     else answers 401 and nginx shows "Please open Dashboards from the mission portal".
//  3. This service signs in to DataEase with DE_ADMIN_PASSWORD, keeps that sign-in, checks it every few minutes
//     and signs in again before it runs out. On the very first start DataEase still has its published default
//     password; the gate replaces it with DE_ADMIN_PASSWORD at once.
//  4. GET /start (through nginx: /gfm-start, the address the portal opens) sends the browser on to the dashboard
//     "Key indicators" in the folder "Mission" (looked up by name, so it keeps working when the dashboard is made
//     again with new ids), else to the first dashboard of that folder, else to DataEase's dashboard list. Phones
//     get DataEase's phone page with the dashboard in its phone layout (its back arrow lists the dashboards),
//     computers and tablets DataEase's dashboard page with the list of dashboards and Edit.
//     Languages: the portal adds ?gfmLang=<code> (the viewer's portal language). When translate-dashboards.mjs has
//     made a copy of the dashboard in that language, that copy opens instead (lib/languages.mjs: the id rule), and
//     the language goes on in the address (/?gfmLang=de#/...) so i18n/gfm-i18n.js shows DataEase's own words in it.
// It prints no passwords, tokens or cookies. GET /health (through nginx: /gfm-gate-health) says whether DataEase
// answers and the gate holds a working sign-in; GET /alive only that this process runs (container health check).
import http from 'node:http';
import path from 'node:path';
import crypto from 'node:crypto';
import { fileURLToPath } from 'node:url';
import { DataEase, DataEaseError, DEFAULT_PASSWORD, changePassword, flattenTree } from '../lib/dataease-client.mjs';
import { copyInTree, isCopyId, normalizeLanguage } from '../lib/languages.mjs';

export const COOKIE_NAME = 'gfm_dataease';
export const MIN_SECRET_LENGTH = 32;
const MAX_COOKIE_LENGTH = 4096;
const RENEW_BEFORE_MS = 60 * 60 * 1000;     // sign in again an hour before DataEase's sign-in runs out
const CHECK_EVERY_MS = 3 * 60 * 1000;       // ask DataEase whether the sign-in still works
export const START_FOLDER = 'Mission';
export const START_DASHBOARD = 'Key indicators';
const DASHBOARD_LIST = '/#/panel/index';
// DataEase's own test for a phone (its utils isMobile), without tablets: those get the computer page.
const PHONE = /(phone|pod|iPhone|iPod|Android.*Mobile|Mobile|BlackBerry|IEMobile|Windows Phone)/i;
const TABLET = /(iPad|tablet|Android(?!.*Mobile))/i;
export const isPhone = userAgent => PHONE.test(String(userAgent || '')) && !TABLET.test(String(userAgent || ''));

/** The secret, or an Error when it is missing, too short or still the example value. */
export function signingKey(value) {
  const text = String(value || '');
  if (text.length < MIN_SECRET_LENGTH || /REPLACE/i.test(text)) {
    throw new Error('GFM_DATAEASE_PROXY_SECRET must be at least 32 generated characters (dataease/init-env.ps1).');
  }
  return Buffer.from(text, 'utf8');
}

const b64url = buffer => Buffer.from(buffer).toString('base64url');

/** The value of one cookie in a Cookie header (the first one with that name), or ''. */
export function cookieValue(header, name = COOKIE_NAME) {
  for (const part of String(header || '').split(';')) {
    const at = part.indexOf('=');
    if (at > 0 && part.slice(0, at).trim() === name) return part.slice(at + 1).trim();
  }
  return '';
}

/** Makes a cookie value exactly as portal-api's dataease_auth.sign does (tests and scripts only). */
export function sign(identity, key) {
  const body = b64url(JSON.stringify(sortKeys(identity)));
  return body + '.' + b64url(crypto.createHmac('sha256', key).update(body, 'ascii').digest());
}

function sortKeys(value) {
  return Object.fromEntries(Object.keys(value).sort().map(k => [k, value[k]]));
}

/** The identity in a cookie value, or null when it is missing, forged, malformed or expired. */
export function verify(value, key, now = Date.now()) {
  if (typeof value !== 'string' || !value || value.length > MAX_COOKIE_LENGTH) return null;
  const parts = value.split('.');
  if (parts.length !== 2 || !/^[A-Za-z0-9_-]+$/.test(parts[0]) || !/^[A-Za-z0-9_-]+$/.test(parts[1])) return null;
  const expected = crypto.createHmac('sha256', key).update(parts[0], 'ascii').digest();
  const given = Buffer.from(parts[1], 'base64url');
  if (given.length !== expected.length || !crypto.timingSafeEqual(given, expected)) return null;
  let identity;
  try { identity = JSON.parse(Buffer.from(parts[0], 'base64url').toString('utf8')); } catch { return null; }
  if (!identity || typeof identity !== 'object' || Array.isArray(identity)) return null;
  if (!Number.isInteger(identity.exp) || identity.exp * 1000 <= now) return null;
  if (typeof identity.sub !== 'string' || !identity.sub) return null;
  return identity;
}

/** When a DataEase sign-in runs out (ms), from its JWT, or null. */
export function tokenExpiry(token) {
  try {
    const exp = JSON.parse(Buffer.from(String(token).split('.')[1], 'base64url').toString('utf8')).exp;
    return Number.isFinite(exp) && exp > 0 ? exp * 1000 : null;
  } catch { return null; }
}

/** Holds DataEase's sign-in: one sign-in at a time, checked every few minutes, renewed before it runs out. */
export class Keeper {
  constructor({ base, password, log = console.log, now = () => Date.now(), client = url => new DataEase(url) }) {
    this.base = base;
    this.password = password;
    this.log = log;
    this.now = now;
    this.client = client;
    this.token = null;
    this.expires = null;
    this.checkedAt = 0;
    this.pending = null;
    this.lastError = null;
    this.signedInAt = null;
  }

  /** A working DataEase token; signs in when needed. Throws when DataEase cannot be reached or refuses. */
  async getToken() {
    const now = this.now();
    const fresh = this.token && (!this.expires || this.expires - now > RENEW_BEFORE_MS);
    if (fresh && now - this.checkedAt < CHECK_EVERY_MS) return this.token;
    if (!this.pending) {
      this.pending = (fresh ? this.stillValid().then(ok => (ok ? this.token : this.signIn())) : this.signIn())
        .then(token => { this.lastError = null; return token; },
          error => { this.lastError = error.message; throw error; })
        .finally(() => { this.pending = null; });
    }
    return this.pending;
  }

  async stillValid() {
    let answer = null;
    try { answer = await this.client(this.base).raw('/user/info', { token: this.token }); } catch { /* not reachable */ }
    const ok = answer?.status === 200 && answer.json?.code === 0;
    if (ok) this.checkedAt = this.now();
    else this.log('DataEase no longer accepts the gate\'s sign-in; signing in again.');
    return ok;
  }

  async signIn() {
    let de;
    try {
      de = await this.client(this.base).login(this.password);
    } catch (error) {
      if (!(error instanceof DataEaseError)) throw new Error('DataEase cannot be reached yet.');
      de = await this.replaceDefaultPassword(error);
    }
    this.token = de.token;
    this.expires = tokenExpiry(de.token);
    this.checkedAt = this.now();
    this.signedInAt = new Date(this.now()).toISOString();
    this.log('Signed in to DataEase' + (this.expires ? ` (until ${new Date(this.expires).toISOString()}).` : '.'));
    return this.token;
  }

  // First start: DataEase has its published default password. Replace it with DE_ADMIN_PASSWORD at once, so the
  // default never works on this server. Any other refusal is reported as it is.
  async replaceDefaultPassword(refusal) {
    let de;
    try {
      de = await this.client(this.base).login(DEFAULT_PASSWORD);
    } catch {
      throw new Error('DataEase refused the password in dataease/.env (DE_ADMIN_PASSWORD). ' + refusal.message);
    }
    await changePassword(de, DEFAULT_PASSWORD, this.password);
    this.log('First start: DataEase\'s default password was replaced by DE_ADMIN_PASSWORD from dataease/.env.');
    return this.client(this.base).login(this.password);
  }

  status() {
    return {
      dataease: this.token && !this.lastError ? 'signed-in' : 'not-signed-in',
      signed_in_at: this.signedInAt,
      problem: this.lastError,
    };
  }
}

/**
 * Where /start sends the browser, from DataEase's dashboard tree: on a computer the start dashboard on DataEase's
 * preview page, which gives the dashboard the whole portal frame (web/gfm/boot.js adds a slim bar with the other
 * dashboards and "All dashboards and Edit"); on a phone DataEase's phone page. No dashboard: DataEase's list.
 * lang (optional, 'de'...): open that language's copy when it exists, and keep ?gfmLang= in the address.
 */
export function startTarget(tree, phone = false, lang = null) {
  const code = normalizeLanguage(lang);
  const query = code ? `?gfmLang=${code}` : '';
  const folder = flattenTree(tree).find(n => !n.leaf && n.name === START_FOLDER);
  // The English dashboards only: the language folders inside "Mission" hold the translated copies.
  const leaves = flattenTree(folder?.children).filter(n => n.leaf && !isCopyId(n.id));
  const leaf = leaves.find(n => n.name === START_DASHBOARD) || leaves[0];
  if (!leaf || !/^[0-9]{1,20}$/.test(String(leaf.id))) return '/' + query + DASHBOARD_LIST.slice(1);
  const id = (code && copyInTree(tree, leaf.id, code)) || String(leaf.id);
  return phone ? `/mobile.html${query}#/panel/mobile?dvId=${id}` : `/${query}#/preview?dvId=${id}`;
}

// DataEase has one account, so it cannot say who changed a dashboard. The gate writes one line per change (the
// portal user id, never a name or e-mail) to its log: docker logs gfm-dataease-gate. Reads are not logged.
const CHANGE = /^\/de2api\/[A-Za-z]+\/[A-Za-z]*(save|update|delete|move|rename|publish|recover|copy|upload|modify|edit|create|import|sync)/i;
export function changeLine(method, uri, identity) {
  if (!method || method === 'HEAD' || method === 'OPTIONS' || !CHANGE.test(String(uri || ''))) return null;
  return `Change by portal user ${identity.sub}: ${method} ${String(uri).split('?')[0].slice(0, 200)}`;
}

/** The gate's HTTP handler (exported for the tests). */
export function handler({ key, keeper, log = () => {} }) {
  return async (req, res) => {
    const send = (status, body, headers = {}) => {
      res.writeHead(status, { 'Cache-Control': 'no-store', 'Content-Type': 'application/json', ...headers });
      res.end(body === undefined ? '' : JSON.stringify(body));
    };
    const url = new URL(req.url, 'http://gate');
    const path = url.pathname;
    if (req.method !== 'GET') return send(405, { error: 'GET only' });
    if (path === '/alive') return send(200, { ok: true });
    if (path === '/health') {
      try { await keeper.getToken(); } catch { /* reported in the status */ }
      const status = keeper.status();
      return send(status.dataease === 'signed-in' ? 200 : 503, status);
    }
    if (path !== '/check' && path !== '/start') return send(404, { error: 'not found' });
    const identity = verify(cookieValue(req.headers.cookie), key);
    if (!identity) return send(401);
    let token;
    try {
      token = await keeper.getToken();
    } catch {
      return send(503);
    }
    if (path === '/check') {
      const line = changeLine(req.headers['x-original-method'], req.headers['x-original-uri'], identity);
      if (line) log(line);
      return send(200, undefined, { 'X-DE-TOKEN': token });
    }
    log(`Dashboards opened by portal user ${identity.sub}.`);
    const lang = url.searchParams.get('gfmLang');
    let target = startTarget([], false, lang);
    try {
      const answer = await keeper.client(keeper.base).raw('/dataVisualization/tree', { method: 'POST', body: { busiFlag: 'dashboard' }, token });
      if (answer.status === 200 && answer.json?.code === 0) target = startTarget(answer.json.data, isPhone(req.headers['user-agent']), lang);
    } catch { /* DataEase's list instead */ }
    return send(302, undefined, { Location: target });
  };
}

// A log line with the time in front (docker logs gfm-dataease-gate).
const stamped = (...parts) => console.log(new Date().toISOString(), ...parts);

async function main() {
  const key = signingKey(process.env.GFM_DATAEASE_PROXY_SECRET);
  const password = process.env.DE_ADMIN_PASSWORD || '';
  if (!password || /REPLACE/i.test(password)) throw new Error('DE_ADMIN_PASSWORD is missing (dataease/init-env.ps1).');
  const keeper = new Keeper({ base: process.env.DE_BASE || 'http://dataease:8100', password, log: stamped });
  const server = http.createServer(handler({ key, keeper, log: stamped }));
  server.keepAliveTimeout = 65000;
  server.listen(Number(process.env.GATE_PORT || 8099), '0.0.0.0', () => stamped('DataEase gate listening on 8099.'));
  // Sign in as soon as DataEase answers (DataEase takes about a minute to start), so the default password is
  // replaced right away, then keep the sign-in fresh even when nobody opens Dashboards.
  let waiting = true;
  const warm = async () => {
    try {
      await keeper.getToken();
      waiting = false;
    } catch (error) {
      if (!waiting) stamped('DataEase sign-in failed:', error.message);
    }
  };
  await warm();
  const firstTry = setInterval(async () => { if (waiting) await warm(); else clearInterval(firstTry); }, 15000);
  setInterval(() => { warm(); }, CHECK_EVERY_MS).unref();
  for (const signal of ['SIGTERM', 'SIGINT']) process.on(signal, () => server.close(() => process.exit(0)));
}

if (process.argv[1] && fileURLToPath(import.meta.url) === path.resolve(process.argv[1])) {
  main().catch(error => { console.error(new Date().toISOString(), error.message); process.exit(1); });
}
