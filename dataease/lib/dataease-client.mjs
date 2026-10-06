// A small client for DataEase v2's own web API (the same calls its pages make), with no packages. Plain Node 24.
// Used by the gate (gate/gate.mjs), seed-dashboards.mjs, translate-dashboards.mjs and the tests.
//
// Sign-in: DataEase Community Edition has one account, "admin". The page encrypts name and password with the
// server's RSA key, which /de2api/dekey hands out AES-wrapped (see DataEase's utils/encryption.ts and
// RsaUtils.java); this does exactly the same. The answer is a token that is sent as X-DE-TOKEN.
import crypto from 'node:crypto';

const SEPARATOR = Buffer.from('-pk_separator-').toString('base64'); // Base64.encodeURI(...) + '=' in the page

/** DataEase's published first password. The gate and seed-dashboards.mjs replace it on the very first start. */
export const DEFAULT_PASSWORD = 'DataEase@123456';

export class DataEaseError extends Error {}

/** Every node of one of DataEase's trees (dashboards, datasets, data sources), the children included. */
export function flattenTree(nodes) {
  return (nodes || []).flatMap(node => [node, ...flattenTree(node.children)]);
}

/** A text encrypted with DataEase's public key, as its sign-in page does it. */
export function encryptFor(pem, text) {
  return crypto.publicEncrypt({ key: pem, padding: crypto.constants.RSA_PKCS1_PADDING }, Buffer.from(text, 'utf8')).toString('base64');
}

/** Changes the password of the signed-in account (de: a signed-in DataEase, or a stand-in with publicKey and post). */
export async function changePassword(de, oldPassword, newPassword) {
  const pem = await de.publicKey();
  await de.post('/user/modifyPwd', { pwd: encryptFor(pem, oldPassword), newPwd: encryptFor(pem, newPassword) });
}

export class DataEase {
  constructor(base) {
    this.base = base.replace(/\/+$/, '');
    this.token = null;
  }

  /** One request to /de2api<path>: { status, json (or null), text }. Never throws for an HTTP error. */
  async raw(path, { method = 'GET', body, headers = {}, token = this.token } = {}) {
    const response = await fetch(this.base + '/de2api' + path, {
      method,
      headers: {
        'Accept': 'application/json',
        'Accept-Language': 'en-US',
        ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}),
        ...(token ? { 'X-DE-TOKEN': token } : {}),
        ...headers,
      },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    const text = await response.text();
    let json = null;
    try { json = JSON.parse(text); } catch { /* not JSON */ }
    return { status: response.status, json, text };
  }

  // The data part of a {code, msg, data} answer; anything else throws with DataEase's own message.
  async call(path, options = {}) {
    const answer = await this.raw(path, options);
    if (answer.status !== 200 || !answer.json || answer.json.code !== 0) {
      const message = answer.json?.msg || answer.text.slice(0, 300) || `HTTP ${answer.status}`;
      throw new DataEaseError(`${options.method || 'GET'} ${path}: ${message}`);
    }
    return answer.json.data;
  }

  /** DataEase's RSA public key (PEM), unwrapped from the AES wrapping /dekey sends it in. */
  async publicKey() {
    const dekey = await this.call('/dekey', { token: null });
    const [wrapped, secret] = String(dekey).split(SEPARATOR);
    if (!wrapped || !secret) throw new DataEaseError('DataEase gave an unexpected key.');
    const key = Buffer.from(secret, 'utf8');
    const iv = crypto.createHash('sha256').update(secret, 'utf8').digest().subarray(0, 16);
    const decipher = crypto.createDecipheriv(`aes-${key.length * 8}-cbc`, key, iv);
    const pk = Buffer.concat([decipher.update(Buffer.from(wrapped, 'base64')), decipher.final()]).toString('utf8');
    return `-----BEGIN PUBLIC KEY-----\n${pk.match(/.{1,64}/g).join('\n')}\n-----END PUBLIC KEY-----\n`;
  }

  /** Signs in (keeps the token in this object) and returns this object. Throws DataEaseError when refused. */
  async login(password, name = 'admin') {
    const pem = await this.publicKey();
    const body = { name: encryptFor(pem, name), pwd: encryptFor(pem, password) };
    const data = await this.call('/login/localLogin', { method: 'POST', body, token: null });
    if (!data?.token) throw new DataEaseError('DataEase did not sign in.');
    this.token = data.token;
    return this;
  }

  get(path) { return this.call(path); }
  post(path, body = {}) { return this.call(path, { method: 'POST', body }); }
}
