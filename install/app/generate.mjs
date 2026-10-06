// generate.mjs: writes the settings files (.env) of every part from the saved answers, with freshly made secrets.
// What it makes: supabase/.env, portal-api/.env, roster-importer/.env, slidev/.env, portal/.env, dataease/.env,
// nightly-backup/secrets/db-password, and install/.work/install.env (plain settings for the shell scripts: no secrets).
// It never replaces a file that exists: a computer that already runs the system keeps its own settings.
//
//   node generate.mjs <answers.json> <repository folder>        (GFM_HOST_IP in the environment: this computer's address)
// The pure parts (secret, makeJwt, buildEnvFiles, renderEnv) are tested in tests/generate.test.mjs.
import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const LETTERS = 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789';
const b64url = buffer => Buffer.from(buffer).toString('base64url');

/** A random text of `length` characters from `alphabet` (no modulo bias: values above the largest multiple are redrawn). */
export function secret(length, alphabet = LETTERS) {
  const limit = 256 - (256 % alphabet.length);
  let out = '';
  while (out.length < length) {
    for (const byte of crypto.randomBytes(length * 2)) {
      if (byte < limit && out.length < length) out += alphabet[byte % alphabet.length];
    }
  }
  return out;
}

/** A Supabase API key: a token signed with the JWT secret (HS256), for the role "anon" or "service_role", valid 10 years. */
export function makeJwt(jwtSecret, role, now = Math.floor(Date.now() / 1000)) {
  const head = b64url(JSON.stringify({ alg: 'HS256', typ: 'JWT' }));
  const body = b64url(JSON.stringify({ role, iss: 'supabase', iat: now, exp: now + 10 * 365 * 24 * 3600 }));
  const signature = crypto.createHmac('sha256', jwtSecret).update(`${head}.${body}`).digest();
  return `${head}.${body}.${b64url(signature)}`;
}

/** A VAPID key pair for push reminders: the public key (65 bytes, base64url) and the private key (32 bytes, base64url). */
export function makeVapid() {
  const { publicKey, privateKey } = crypto.generateKeyPairSync('ec', { namedCurve: 'prime256v1' });
  const pub = publicKey.export({ format: 'jwk' });
  const priv = privateKey.export({ format: 'jwk' });
  return { publicKey: b64url(Buffer.concat([Buffer.from([4]), Buffer.from(pub.x, 'base64url'), Buffer.from(pub.y, 'base64url')])), privateKey: priv.d };
}

/** DataEase's own rule for its admin password: 20 characters with a-z, A-Z, 0-9 and one of @ - _ . + */
export function dataeaseAdminPassword() {
  for (;;) {
    const password = secret(19) + secret(1, '@-_.+');
    if (/[a-z]/.test(password) && /[A-Z]/.test(password) && /[0-9]/.test(password)) return password;
  }
}

/** The text of an .env file from an ordered list of [name, value] pairs and comment lines (a string starts with "#"). */
export function renderEnv(entries) {
  const lines = entries.map(e => {
    if (typeof e === 'string') return e;
    const [name, value] = e;
    if (/[\r\n]/.test(String(value))) throw new Error(`${name} has a line break`);
    return `${name}=${value}`;
  });
  return lines.join('\n') + '\n';
}

/** A value for a shell file (single quotes, safe for `source`). */
export const shellQuote = value => `'${String(value).replace(/'/g, `'\\''`)}'`;

/**
 * answers: the saved answers (validate.mjs). host: this computer's address. Returns { files: { 'folder/.env': text, ... },
 * shell: { NAME: value } } with new secrets each call.
 */
export function buildEnvFiles(answers, { host = '127.0.0.1', random = { secret, makeJwt, makeVapid, dataeaseAdminPassword } } = {}) {
  const domain = answers.publicDomain || '';
  const siteUrl = domain ? `https://${domain}` : `http://${host}:8070`;
  const missionId = 1;
  const mail = answers.email;

  const jwtSecret = random.secret(48);
  const postgres = random.secret(32);
  const anon = random.makeJwt(jwtSecret, 'anon');
  const service = random.makeJwt(jwtSecret, 'service_role');
  const portalKey = random.secret(48);
  const dataeaseProxy = random.secret(48);
  const vapid = random.makeVapid();
  const dbUrl = `postgresql://postgres:${postgres}@gfm-beta-supabase-db-1:5432/postgres`;
  const kong = 'http://gfm-beta-supabase-kong-1:8000';
  const common = [['GFM_HOST_IP', host], ['GFM_PUBLIC_DOMAIN', domain]];

  const files = {};
  files['supabase/.env'] = renderEnv([
    '# Written by the installer (install/app/generate.mjs). Secret: never commit, copy into chats or print.',
    ...common, ['GFM_SITE_URL', siteUrl],
    // The database's own port (DBeaver) is open to this computer only; open it to the network by hand if the data analysts need it.
    ['GFM_DB_BIND', '127.0.0.1'],
    ['ADDITIONAL_REDIRECT_URLS', `http://localhost:8070/**,http://${host}:8070/**,http://localhost:8090,http://localhost:8090/**,http://${host}:8090/**`],
    ['DISABLE_SIGNUP', 'false'], ['ENABLE_ANONYMOUS_USERS', 'false'], ['ENABLE_EMAIL_AUTOCONFIRM', 'false'], ['ENABLE_EMAIL_SIGNUP', 'true'],
    ['ENABLE_PHONE_AUTOCONFIRM', 'false'], ['ENABLE_PHONE_SIGNUP', 'false'], ['FUNCTIONS_VERIFY_JWT', 'false'], ['JWT_EXPIRY', '3600'],
    ['MAILER_SUBJECTS_CONFIRMATION', 'Confirm your email'], ['MAILER_SUBJECTS_EMAIL_CHANGE', 'Confirm your new email'],
    ['MAILER_SUBJECTS_INVITE', `You are invited to ${answers.missionName}`], ['MAILER_SUBJECTS_MAGIC_LINK', 'Your sign-in link'],
    ['MAILER_SUBJECTS_RECOVERY', 'Set your password'],
    ['MAILER_TEMPLATES_CONFIRMATION', ''], ['MAILER_TEMPLATES_EMAIL_CHANGE', ''], ['MAILER_TEMPLATES_INVITE', ''],
    ['MAILER_TEMPLATES_MAGIC_LINK', ''], ['MAILER_TEMPLATES_RECOVERY', ''],
    ['MAILER_URLPATHS_CONFIRMATION', '/auth/v1/verify'], ['MAILER_URLPATHS_EMAIL_CHANGE', '/auth/v1/verify'],
    ['MAILER_URLPATHS_INVITE', '/auth/v1/verify'], ['MAILER_URLPATHS_RECOVERY', '/auth/v1/verify'],
    ['OPENAI_API_KEY', ''], ['POOLER_DB_POOL_SIZE', '5'], ['POSTGRES_DB', 'postgres'], ['POSTGRES_HOSTNAME', 'supabase-db'], ['POSTGRES_PORT', '5432'],
    ['SECRET_PASSWORD_REALTIME', random.secret(64)], ['SERVICE_PASSWORD_ADMIN', random.secret(24)], ['SERVICE_PASSWORD_JWT', jwtSecret],
    ['SERVICE_PASSWORD_LOGFLARE', random.secret(32)], ['SERVICE_PASSWORD_LOGFLAREPRIVATE', random.secret(32)], ['SERVICE_PASSWORD_MINIO', random.secret(32)],
    ['SERVICE_PASSWORD_PGMETACRYPTO', random.secret(32)], ['SERVICE_PASSWORD_POSTGRES', postgres], ['SERVICE_PASSWORD_SUPAVISORSECRET', random.secret(48)],
    ['SERVICE_PASSWORD_VAULTENC', random.secret(32)], ['SERVICE_ROLE_KEY_ASYMMETRIC', ''],
    ['SERVICE_SUPABASEANON_KEY', anon], ['SERVICE_SUPABASESERVICE_KEY', service], ['SERVICE_URL_SUPABASEKONG', 'http://localhost:18000'],
    ['SERVICE_USER_ADMIN', 'admin'], ['SERVICE_USER_MINIO', 'minio'],
    ['SMTP_ADMIN_EMAIL', mail ? mail.sender : answers.admin.email], ['SMTP_HOST', mail ? mail.host : ''], ['SMTP_PASS', mail ? mail.password : ''],
    ['SMTP_PORT', mail ? mail.port : 587], ['SMTP_SENDER_NAME', mail ? mail.senderName : answers.missionName], ['SMTP_USER', mail ? mail.user : ''],
    ['STORAGE_TENANT_ID', 'storage-single-tenant'], ['STUDIO_DEFAULT_ORGANIZATION', answers.missionName], ['STUDIO_DEFAULT_PROJECT', answers.missionName],
    ['SUPERSET_DASHBOARD_ID', ''], ['SUPERSET_PASSWORD', ''], ['SUPERSET_URL', ''], ['SUPERSET_USERNAME', ''],
  ]);
  files['portal-api/.env'] = renderEnv([
    '# Written by the installer. Secret: never commit, copy into chats or print.',
    ['DATABASE_URL', dbUrl], ['SUPABASE_URL', kong], ['SUPABASE_SERVICE_ROLE_KEY', service], ['PORTAL_SERVICE_KEY', portalKey],
    ['VAPID_PRIVATE_KEY', vapid.privateKey], ['VAPID_PUBLIC_KEY', vapid.publicKey], ['VAPID_SUBJECT', `mailto:${answers.admin.email}`],
    ['DATAEASE_PROXY_SECRET', dataeaseProxy], ['GFM_PUBLIC_DOMAIN', domain], ['GFM_TIME_ZONE', answers.timeZone],
    // The wiki (wiki/ is mounted by portal-api/compose.yml): managers may edit it in the browser; no Git commit from the container.
    ['WIKI_DIR', '/data/wiki'], ['WIKI_GIT_COMMIT', '0'],
  ]);
  files['roster-importer/.env'] = renderEnv([
    '# Written by the installer. Secret: never commit, copy into chats or print.',
    ['DATABASE_URL', dbUrl], ['MISSION_ID', missionId], ['IMPORTER_PASSWORD', random.secret(32)], ['SECRET_KEY', random.secret(64)],
    ['SUPABASE_AUTH_INTERNAL_URL', kong], ['SUPABASE_SERVICE_ROLE_KEY', service], ['PASSWORD_REDIRECT_URL', `${siteUrl}/`],
    ['PERSON_KEY_SECRET', random.secret(64, '0123456789abcdef')], ['GFM_PUBLIC_DOMAIN', domain], ['GFM_TIME_ZONE', answers.timeZone],
  ]);
  files['slidev/.env'] = renderEnv([
    '# Written by the installer. Secret: never commit, copy into chats or print.',
    ['SUPABASE_SERVICE_ROLE_KEY', service], ['PORTAL_SERVICE_KEY', portalKey], ['MISSION_ID', missionId],
    ['PRESENTATIONS_PORTAL_ORIGINS', `http://localhost:8070,http://127.0.0.1:8070,http://${host}:8070`],
    ['GFM_SLIDEV_CONTAINER', 'slidev'], ['GFM_SLIDEV_VOLUME', 'slidev-data'], ...common,
  ]);
  files['portal/.env'] = renderEnv([
    '# Written by the installer. No secrets: the names of the portal container and volume, and the public address.',
    ['GFM_PORTAL_CONTAINER', 'portal'], ['GFM_PORTAL_VOLUME', 'portal-data'], ['GFM_TIME_ZONE', answers.timeZone], ...common,
  ]);
  files['dataease/.env'] = renderEnv([
    '# Written by the installer. Secret: never commit, copy into chats or print.',
    ['GFM_TIME_ZONE', answers.timeZone], ['DE_MYSQL_ROOT_PASSWORD', random.secret(32)], ['DE_MYSQL_PASSWORD', random.secret(32)], ['DE_ADMIN_PASSWORD', random.dataeaseAdminPassword()],
    ['GFM_DATAEASE_PROXY_SECRET', dataeaseProxy], ['GFM_DASHBOARD_READER_PASSWORD', random.secret(32)], ...common,
  ]);
  if (answers.cloudflareToken) {
    files['cloudflared/.env'] = renderEnv([
      '# Written by the installer. Secret (the tunnel token): never commit, copy into chats or print.',
      ['TUNNEL_TOKEN', answers.cloudflareToken],
    ]);
  }
  files['nightly-backup/.env'] = renderEnv([
    '# Written by the installer. No secrets: the time zone of the mission, which is also the zone of the 02:30 backup.',
    ['GFM_TIME_ZONE', answers.timeZone],
  ]);
  files['nightly-backup/secrets/db-password'] = postgres;

  const shell = {
    GFM_MISSION_ID: missionId, GFM_MISSION_NAME: answers.missionName, GFM_MISSION_CODE: answers.missionCode, GFM_DEFAULT_LANGUAGE: answers.language,
    GFM_HOST_IP: host, GFM_PUBLIC_DOMAIN: domain, GFM_SITE_URL: siteUrl, GFM_TIME_ZONE: answers.timeZone,
    GFM_FIRST_EMAIL: answers.admin.email, GFM_FIRST_NAME: answers.admin.name, GFM_CLOUDFLARE: answers.cloudflareToken ? 'yes' : 'no',
  };
  return { files, shell };
}

function writeNew(repo, name, text) {
  const target = path.join(repo, name);
  if (fs.existsSync(target)) throw new Error(`${name} exists already. The installer never replaces settings: it is meant for a new computer.`);
  fs.mkdirSync(path.dirname(target), { recursive: true });
  fs.writeFileSync(target, text, { mode: 0o600 });
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const [answersFile, repo] = process.argv.slice(2);
  const answers = JSON.parse(fs.readFileSync(answersFile, 'utf8'));
  const { files, shell } = buildEnvFiles(answers, { host: process.env.GFM_HOST_IP || '127.0.0.1' });
  // Check every target first, so a refusal leaves nothing half written.
  for (const name of Object.keys(files)) {
    if (fs.existsSync(path.join(repo, name))) { console.error(`${name} exists already. The installer never replaces settings: it is meant for a new computer.`); process.exit(2); }
  }
  for (const [name, text] of Object.entries(files)) writeNew(repo, name, text);
  const work = path.dirname(answersFile);
  fs.writeFileSync(path.join(work, 'install.env'), Object.entries(shell).map(([k, v]) => `${k}=${shellQuote(v)}`).join('\n') + '\n', { mode: 0o600 });
  console.log(`Wrote ${Object.keys(files).length} settings files (secrets are not shown).`);
}
