// validate.mjs: checks the answers of the setup form (or of the terminal questions) and cleans them up.
// Used by setup.mjs (the form and the terminal mode) and by tests/validate.test.mjs. No packages, no network.

export const EMAIL = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;
export const DOMAIN = /^(?=.{4,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$/;
export const LOGO_TYPES = { 'image/png': 'png', 'image/jpeg': 'jpg', 'image/svg+xml': 'svg' };
export const LOGO_MAX_BYTES = 300 * 1024;
export const PASSWORD_MIN = 10;

/** "Germany Frankfurt Mission" gives "GFM": the first letter of each word, in capitals, at most 6. */
export function shortCode(name) {
  const letters = String(name || '').split(/[\s\-_/]+/).map(word => (word.match(/[\p{L}\p{N}]/u) || [''])[0]).join('');
  return letters.normalize('NFD').replace(/[^A-Za-z0-9]/g, '').toUpperCase().slice(0, 6);
}

const clean = value => String(value ?? '').normalize('NFC').trim().replace(/\s+/g, ' ');

/**
 * A Cloudflare tunnel token from what was pasted: {token} ('' when nothing was pasted) or {error}. A token is a long text that starts
 * with "eyJ" and is base64 of {"a": account, "t": tunnel id, "s": secret}. Cloudflare's page shows a whole command
 * ("cloudflared service install eyJ..."): then the token is the last long word of it.
 */
export function tunnelToken(text) {
  const raw = String(text ?? '').trim();
  if (!raw) return { token: '' };
  const bad = { error: 'This does not look like a tunnel token (a long text that starts with eyJ). Copy it again from Cloudflare, or leave the field empty.' };
  const word = raw.split(/\s+/).filter(w => /^eyJ[A-Za-z0-9_+=/-]{20,}$/.test(w)).pop();
  if (!word) return bad;
  let parsed;
  try { parsed = JSON.parse(Buffer.from(word.replace(/-/g, '+').replace(/_/g, '/'), 'base64').toString('utf8')); } catch { return bad; }
  if (!parsed || typeof parsed.a !== 'string' || typeof parsed.s !== 'string' || !/^[0-9a-f-]{36}$/i.test(String(parsed.t))) return bad;
  return { token: word };
}

/** The logo as {type, ext, data (a Buffer)} from a data URL, or {error}. */
export function readLogo(dataUrl) {
  const m = /^data:([a-z/+.-]+);base64,([A-Za-z0-9+/=]+)$/.exec(String(dataUrl || ''));
  if (!m || !LOGO_TYPES[m[1]]) return { error: 'The logo must be a PNG, JPG or SVG picture.' };
  const data = Buffer.from(m[2], 'base64');
  if (data.length > LOGO_MAX_BYTES) return { error: `The logo is too big (at most ${LOGO_MAX_BYTES / 1024} KB).` };
  if (!data.length) return { error: 'The logo file is empty.' };
  return { type: m[1], ext: LOGO_TYPES[m[1]], data };
}

/**
 * input: the raw answers. options: { languages: ['en', 'de', ...], timeZones: [...] }.
 * Returns { ok, errors: { field: text }, answers, logo } where answers is the cleaned set and logo is {type, ext, data}
 * (or null) for the caller to write to a file.
 */
export function validate(input, options) {
  const errors = {};
  const a = {};
  const fail = (field, text) => { errors[field] = text; };

  a.missionName = clean(input.missionName);
  if (a.missionName.length < 3 || a.missionName.length > 80 || !/\p{L}/u.test(a.missionName)) fail('missionName', 'Enter the mission name (3 to 80 characters).');

  a.missionCode = clean(input.missionCode).toUpperCase() || shortCode(a.missionName);
  if (!/^[A-Z0-9]{2,6}$/.test(a.missionCode)) fail('missionCode', 'The short code is 2 to 6 letters or digits (no spaces).');

  let logo = null;
  if (input.logo) {
    const read = readLogo(input.logo);
    if (read.error) fail('logo', read.error); else logo = read;
  }

  a.language = clean(input.language);
  if (!options.languages.includes(a.language)) fail('language', 'Choose one of the languages in the list.');

  a.languageRequest = null;
  if (clean(input.requestLanguageName) || clean(input.requestLanguageEmail)) {
    const name = clean(input.requestLanguageName), email = clean(input.requestLanguageEmail);
    if (name.length < 2 || name.length > 60) fail('requestLanguageName', 'Write the name of the language you would like (2 to 60 characters).');
    if (email && !EMAIL.test(email)) fail('requestLanguageEmail', 'That email address does not look right.');
    a.languageRequest = { name, email };
  }

  const admin = input.admin || {};
  a.admin = { name: clean(admin.name), email: clean(admin.email).toLowerCase(), password: String(admin.password ?? '') };
  if (a.admin.name.length < 1 || a.admin.name.length > 120) fail('adminName', 'Enter your name (at most 120 characters).');
  if (!EMAIL.test(a.admin.email) || a.admin.email.length > 254) fail('adminEmail', 'Enter a valid email address. You sign in with it.');
  if (a.admin.password.length < PASSWORD_MIN) fail('adminPassword', `The password needs at least ${PASSWORD_MIN} characters.`);
  else if (a.admin.password.length > 200) fail('adminPassword', 'The password is too long (at most 200 characters).');
  else if (a.admin.password.toLowerCase() === a.admin.email) fail('adminPassword', 'The password must not be your email address.');
  if (admin.passwordAgain !== undefined && admin.passwordAgain !== a.admin.password) fail('adminPasswordAgain', 'The two passwords are not the same.');

  a.email = null;
  const mail = input.email || {};
  if (['host', 'user', 'password', 'sender'].some(key => clean(mail[key]))) {
    const host = clean(mail.host), port = Number(clean(mail.port) || 587), sender = clean(mail.sender);
    if (!/^[A-Za-z0-9.-]{3,253}$/.test(host)) fail('emailHost', 'Enter the mail server name, for example smtp-relay.brevo.com.');
    if (!Number.isInteger(port) || port < 1 || port > 65535) fail('emailPort', 'The port is a number from 1 to 65535 (usually 587).');
    if (!EMAIL.test(sender)) fail('emailSender', 'Enter the address the emails come from.');
    a.email = { host, port, user: clean(mail.user), password: String(mail.password ?? ''), sender, senderName: clean(mail.senderName) || a.missionName };
  }

  a.publicDomain = clean(input.publicDomain).toLowerCase().replace(/^https?:\/\//, '').replace(/\/.*$/, '').replace(/^www\./, '');
  if (a.publicDomain && !DOMAIN.test(a.publicDomain)) fail('publicDomain', 'Enter the web name only, for example example.org (no http://, no path).');

  a.timeZone = clean(input.timeZone) || 'UTC';
  if (!options.timeZones.includes(a.timeZone)) fail('timeZone', 'Choose a time zone from the list.');

  const tunnel = tunnelToken(input.cloudflareToken);
  a.cloudflareToken = tunnel.token || '';
  if (tunnel.error) fail('cloudflareToken', tunnel.error);
  else if (a.cloudflareToken && !a.publicDomain) fail('cloudflareToken', 'A tunnel needs your public web name: fill it in under step 4 (for example example.org), or leave the tunnel out.');

  return { ok: Object.keys(errors).length === 0, errors, answers: a, logo };
}
