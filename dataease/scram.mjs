// scram.mjs: makes the SQL that sets the password of the read-only database login gfm_dashboard_reader, from dataease/.env.
// Only a SCRAM-SHA-256 hash of the password is printed (PostgreSQL's own stored form, RFC 5802 and 7677, 4096 rounds), so the
// password never reaches a command line or the database log. set-reader-password.sh pipes the output into psql.
//   node scram.mjs <path of dataease/.env>
import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

/** The SCRAM-SHA-256 verifier PostgreSQL stores for a password (salt: 16 bytes, given for the tests). */
export function verifier(password, salt = crypto.randomBytes(16), iterations = 4096) {
  const salted = crypto.pbkdf2Sync(Buffer.from(password, 'utf8'), salt, iterations, 32, 'sha256');
  const hmac = (key, text) => crypto.createHmac('sha256', key).update(text).digest();
  const clientKey = hmac(salted, 'Client Key');
  const serverKey = hmac(salted, 'Server Key');
  const storedKey = crypto.createHash('sha256').update(clientKey).digest();
  return `SCRAM-SHA-256$${iterations}:${salt.toString('base64')}$${storedKey.toString('base64')}:${serverKey.toString('base64')}`;
}

export function readerPassword(envText) {
  const line = envText.split(/\r?\n/).find(l => l.startsWith('GFM_DASHBOARD_READER_PASSWORD='));
  const password = line ? line.slice('GFM_DASHBOARD_READER_PASSWORD='.length).trim().replace(/^(["'])(.*)\1$/, '$2') : '';
  if (password.length < 20 || !/^[A-Za-z0-9_-]+$/.test(password)) {
    throw new Error('GFM_DASHBOARD_READER_PASSWORD must be a generated value of at least 20 letters, digits, - or _.');
  }
  return password;
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try {
    const password = readerPassword(fs.readFileSync(process.argv[2], 'utf8'));
    process.stdout.write(`\\set verifier '${verifier(password)}'\nALTER ROLE gfm_dashboard_reader PASSWORD :'verifier';\n`);
  } catch (e) {
    console.error(e.message);
    process.exit(1);
  }
}
