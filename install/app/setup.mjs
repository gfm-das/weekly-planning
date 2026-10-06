// setup.mjs: asks the setup questions and writes the answers to install/.work/answers.json.
// It runs in a small Node container started by install.sh (nothing else is installed on the computer). The web form is
// served on port 8099 of this computer only (127.0.0.1); the answers file holds the first password, so it is only
// readable by its owner and the installer deletes it when the installation is finished.
//
//   node setup.mjs --web [--port 8099]    the setup form in a browser (default)
//   node setup.mjs --cli                  the same questions in the terminal (a computer with no screen)
//   node setup.mjs --check answers.json   only checks an answers file (for a non-interactive install)
//
// Folders in the container: /install is the install/ folder of the repository (read and write), /i18n is portal/i18n.
import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import readline from 'node:readline';
import { Writable } from 'node:stream';
import { validate, shortCode, readLogo } from './validate.mjs';
import { runCli } from './cli.mjs';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const WORK = process.env.GFM_INSTALL_WORK || '/install/.work';
const I18N = process.env.GFM_INSTALL_I18N || '/i18n';
const MAX_BODY = 1024 * 1024;

/** The portal's languages from portal/i18n/catalogs.json: [{ code, name, english }] with English first. */
export function readLanguages(folder = I18N) {
  const catalogs = JSON.parse(fs.readFileSync(path.join(folder, 'catalogs.json'), 'utf8')).languages;
  return Object.entries(catalogs).map(([code, l]) => ({ code, name: l.name, english: l.english, rtl: l.dir === 'rtl' }));
}

export const timeZones = () => [...new Set(['UTC', ...Intl.supportedValuesOf('timeZone')])];

/** Writes the answers (and the logo) into the work folder. Returns the answers file's path. */
export function saveAnswers(result, work = WORK) {
  fs.mkdirSync(work, { recursive: true, mode: 0o700 });
  const answers = { ...result.answers, logo: null };
  if (result.logo) {
    answers.logo = `logo.${result.logo.ext}`;
    fs.writeFileSync(path.join(work, answers.logo), result.logo.data, { mode: 0o600 });
  }
  const file = path.join(work, 'answers.json');
  fs.writeFileSync(file, JSON.stringify(answers, null, 2) + '\n', { mode: 0o600 });
  if (answers.languageRequest) {
    const r = answers.languageRequest;
    fs.writeFileSync(path.join(work, 'language-request.txt'),
      `Language requested by ${answers.missionName} (${answers.missionCode}), ${new Date().toISOString().slice(0, 10)}\n` +
      `Language: ${r.name}\nContact: ${r.email || '(none given)'}\n`, { mode: 0o600 });
  }
  return file;
}

// ------------------------------------------------------------------------------------------------ the web form

function readBody(req) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    let size = 0;
    req.on('data', chunk => {
      size += chunk.length;
      if (size > MAX_BODY) { reject(Object.assign(new Error('too big'), { status: 413 })); req.destroy(); return; }
      chunks.push(chunk);
    });
    req.on('end', () => resolve(Buffer.concat(chunks).toString('utf8')));
    req.on('error', reject);
  });
}

/** Only this computer's own names may use the form: another website cannot send answers to it from a browser. */
function hostAllowed(req, port) {
  const own = new Set([`localhost:${port}`, `127.0.0.1:${port}`, `[::1]:${port}`]);
  if (!own.has(String(req.headers.host || '').toLowerCase())) return false;
  const origin = req.headers.origin;
  return !origin || own.has(origin.replace(/^https?:\/\//, '').toLowerCase());
}

export function makeServer({ port, languages, zones, onSaved, work = WORK }) {
  const form = fs.readFileSync(path.join(HERE, 'form.html'), 'utf8');
  const options = { languages: languages.map(l => l.code), timeZones: zones };
  const send = (res, status, body, type = 'application/json; charset=utf-8') => {
    res.writeHead(status, { 'Content-Type': type, 'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff',
      'Content-Security-Policy': "default-src 'self'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; img-src 'self' data:; frame-ancestors 'none'", 'Referrer-Policy': 'no-referrer' });
    res.end(typeof body === 'string' ? body : JSON.stringify(body));
  };
  return http.createServer(async (req, res) => {
    try {
      if (!hostAllowed(req, port)) return send(res, 403, { error: 'This page only answers on this computer.' });
      const url = new URL(req.url, 'http://x');
      if (req.method === 'GET' && url.pathname === '/') return send(res, 200, form, 'text/html; charset=utf-8');
      if (req.method === 'GET' && url.pathname === '/health') return send(res, 200, { ok: true });
      if (req.method === 'GET' && url.pathname === '/api/options') return send(res, 200, { languages, timeZones: zones });
      if (req.method === 'POST' && url.pathname === '/api/submit') {
        let input;
        try { input = JSON.parse(await readBody(req)); } catch (e) { if (e.status) return send(res, e.status, { error: 'That is too much data.' }); return send(res, 400, { error: 'The form could not be read.' }); }
        const result = validate(input || {}, options);
        if (!result.ok) return send(res, 400, { errors: result.errors });
        saveAnswers(result, work);
        send(res, 200, { ok: true, missionCode: result.answers.missionCode });
        res.on('finish', () => onSaved && onSaved(result));
        return;
      }
      send(res, 404, { error: 'Not found' });
    } catch (e) {
      console.error(e);
      send(res, 500, { error: 'Something went wrong in the installer.' });
    }
  });
}

// ------------------------------------------------------------------------------------------------ the terminal

/** Questions and answers on the terminal. Typing is not shown for secrets (also when the answers are piped in). */
export function terminalIo(input = process.stdin, output = process.stdout) {
  let hidden = false;
  const screen = new Writable({ write(chunk, encoding, done) { if (!hidden) output.write(chunk, encoding); done(); } });
  const rl = readline.createInterface({ input, output: screen, terminal: Boolean(input.isTTY) });
  // Lines are kept in a queue, so answers piped in all at once are not lost before their question is asked.
  const queue = [], waiting = [];
  let closed = false;
  const ended = () => new Error('The answers ended before the questions did.');
  rl.on('line', text => (waiting.length ? waiting.shift().resolve(text) : queue.push(text)));
  rl.on('close', () => { closed = true; for (const w of waiting.splice(0)) w.reject(ended()); });
  const line = prompt => {
    if (closed) screen.write(prompt);       // piped answers: the input has already ended, but its lines are in the queue
    else { rl.setPrompt(prompt); rl.prompt(); }
    if (queue.length) return Promise.resolve(queue.shift());
    if (closed) return Promise.reject(ended());
    return new Promise((resolve, reject) => waiting.push({ resolve, reject }));
  };
  return {
    say: text => output.write(text + '\n'),
    ask: (question, fallback) => line(`${question}${fallback ? ` [${fallback}]` : ''}: `).then(a => a.trim() || fallback || ''),
    async secret(question) {
      output.write(`${question}: `);
      hidden = true;
      try { return await line(''); } finally { hidden = false; output.write('\n'); }
    },
    close: () => rl.close(),
  };
}

async function cliMain(languages, zones) {
  const io = terminalIo();
  const readLogoFile = name => {
    const file = path.join('/install', path.basename(name));   // only files in the install folder
    if (!fs.existsSync(file)) return null;
    const type = { png: 'image/png', jpg: 'image/jpeg', jpeg: 'image/jpeg', svg: 'image/svg+xml' }[path.extname(file).slice(1).toLowerCase()];
    return type ? `data:${type};base64,${fs.readFileSync(file).toString('base64')}` : null;
  };
  try {
    const result = await runCli(io, { languages: languages.map(l => l.code), timeZones: zones },
      { languages, defaultTimeZone: zones.includes(process.env.GFM_TZ) ? process.env.GFM_TZ : 'UTC', readLogoFile });
    saveAnswers(result);
    io.say(`\nThe settings for ${result.answers.missionName} (${result.answers.missionCode}) are saved.`);
  } catch (e) {
    io.say(`\n${e.message}`);
    io.close();
    process.exit(1);
  }
  io.close();
}

// ------------------------------------------------------------------------------------------------ the command line

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const args = process.argv.slice(2);
  const flag = name => args.includes(name);
  const value = name => (args.includes(name) ? args[args.indexOf(name) + 1] : undefined);
  const languages = readLanguages();
  const zones = timeZones();
  if (flag('--check')) {
    const raw = JSON.parse(fs.readFileSync(value('--check'), 'utf8'));
    const result = validate({ ...raw, requestLanguageName: raw.languageRequest?.name, requestLanguageEmail: raw.languageRequest?.email,
      logo: raw.logo && fs.existsSync(raw.logo) ? 'data:' + (raw.logo.endsWith('png') ? 'image/png' : raw.logo.endsWith('svg') ? 'image/svg+xml' : 'image/jpeg') + ';base64,' + fs.readFileSync(raw.logo).toString('base64') : undefined },
      { languages: languages.map(l => l.code), timeZones: zones });
    if (!result.ok) { for (const [field, text] of Object.entries(result.errors)) console.error(`  ${field}: ${text}`); process.exit(1); }
    console.log('The answers file is fine.');
    process.exit(0);
  }
  if (flag('--cli')) {
    await cliMain(languages, zones);
    process.exit(0);
  }
  const port = Number(value('--port') || 8099);
  const server = makeServer({
    port, languages, zones,
    onSaved: result => {
      console.log(`\nThe settings for ${result.answers.missionName} (${result.answers.missionCode}) are saved.`);
      server.close(() => process.exit(0));
      setTimeout(() => process.exit(0), 2000).unref();
    },
  });
  server.listen(port, '0.0.0.0', () => console.log(`The setup form is ready: http://localhost:${port}`));
}

export { shortCode, readLogo };
