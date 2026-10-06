// first-account.mjs: makes the first Data Analyst's sign-in in Supabase Auth, from the saved answers, and prints its id.
// install/run-install.sh then gives that sign-in its profile (role Data Analyst, home mission 1) in the database.
// The password is read from the answers file and sent only to Supabase Auth on this computer; it is never printed.
//
//   node first-account.mjs <answers.json> <supabase/.env>      AUTH_BASE=http://gfm-beta-supabase-kong-1:8000/auth/v1
// The sign-in is created already confirmed, so no email is needed. It waits up to two minutes for Auth to answer.
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

/** The value of NAME in an .env file's text, or ''. */
export function envValue(text, name) {
  const line = text.split(/\r?\n/).find(l => l.startsWith(`${name}=`));
  return line ? line.slice(name.length + 1).trim().replace(/^(["'])(.*)\1$/, '$2') : '';
}

export async function waitForAuth(base, key, { tries = 60, delay = 2000, fetchImpl = fetch } = {}) {
  for (let i = 0; i < tries; i++) {
    try {
      const response = await fetchImpl(`${base}/health`, { headers: { apikey: key } });
      if (response.ok) return;
    } catch { /* not up yet */ }
    await new Promise(resolve => setTimeout(resolve, delay));
  }
  throw new Error(`Supabase Auth did not answer at ${base} in time.`);
}

/** Creates the sign-in and returns its id. Throws with Auth's own reason (never with the password). */
export async function createSignIn({ base, key, email, password, name, fetchImpl = fetch }) {
  const response = await fetchImpl(`${base}/admin/users`, {
    method: 'POST',
    headers: { apikey: key, Authorization: `Bearer ${key}`, 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password, email_confirm: true, user_metadata: { display_name: name } }),
  });
  let body = {};
  try { body = await response.json(); } catch { /* no JSON */ }
  if (!response.ok) throw new Error(body.msg || body.message || body.error_description || `Auth answered HTTP ${response.status}.`);
  const id = body.id || body.user?.id;
  if (!id) throw new Error('Auth made the sign-in but did not say its id.');
  return id;
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try {
    const [answersFile, envFile] = process.argv.slice(2);
    const answers = JSON.parse(fs.readFileSync(answersFile, 'utf8'));
    const key = envValue(fs.readFileSync(envFile, 'utf8'), 'SERVICE_SUPABASESERVICE_KEY');
    const base = (process.env.AUTH_BASE || '').replace(/\/$/, '');
    if (!key || !base) throw new Error('The service key or AUTH_BASE is missing.');
    await waitForAuth(base, key);
    const id = await createSignIn({ base, key, email: answers.admin.email, password: answers.admin.password, name: answers.admin.name });
    console.log(id);
  } catch (e) {
    console.error(e.message);
    process.exit(1);
  }
}
