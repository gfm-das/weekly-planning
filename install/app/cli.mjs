// cli.mjs: the setup questions in the terminal, for a computer with no screen (same questions, same rules as the form).
// runCli(io, options) asks one group of questions at a time and asks again for any answer that does not pass
// validate.mjs. io = { ask(question, default) -> text, secret(question) -> text, say(text) }, so the tests can answer for it.
import { validate, shortCode, PASSWORD_MIN } from './validate.mjs';

/**
 * Asks the questions of a group in order. A question is { errors: [field names of validate.mjs it is checked by],
 * ask(input) }. An answer that does not pass is explained and asked again at once (up to 20 times).
 */
async function group(io, input, options, questions) {
  for (const q of questions) {
    for (let attempt = 1; ; attempt++) {
      await q.ask(input);
      const errors = validate(input, options).errors;
      const mine = q.errors.filter(key => errors[key]);
      if (!mine.length) break;
      for (const key of mine) io.say(`  ! ${errors[key]}`);
      if (attempt >= 20) throw new Error('Too many wrong answers. Run the installer again.');
    }
  }
}

export async function runCli(io, options, { languages, defaultTimeZone = 'UTC', readLogoFile = () => null } = {}) {
  const input = { admin: {}, email: {} };
  const plain = (errors, ask) => ({ errors, ask });

  io.say('\nWeekly Planning installer. Answer each question; press Enter to accept a [default] or to skip an optional one.\n');

  io.say('1. Your mission');
  await group(io, input, options, [
    plain(['missionName'], async i => { i.missionName = await io.ask('Mission name (for example Germany Frankfurt Mission)'); }),
    plain(['missionCode'], async i => { i.missionCode = await io.ask('Short code', shortCode(i.missionName)); }),
  ]);
  const logoName = await io.ask('Mission logo: the name of a PNG, JPG or SVG file you put in the install folder (Enter: use the short code)');
  if (logoName) {
    const logo = readLogoFile(logoName);
    if (logo) input.logo = logo; else io.say('  ! I could not read that file, so the short code is used as the icon. You can change it later.');
  }

  io.say('\n2. Default language for missionaries');
  languages.forEach((l, n) => io.say(`  ${String(n + 1).padStart(2)}. ${l.code}  ${l.name === l.english ? l.english : `${l.name} (${l.english})`}`));
  await group(io, input, options, [plain(['language'], async i => {
    const a = (await io.ask('Language: number or code', 'en')).trim().toLowerCase();
    i.language = /^\d+$/.test(a) ? (languages[Number(a) - 1]?.code ?? a) : a;
  })]);
  input.requestLanguageName = await io.ask('My language is not in the list: its name (Enter to skip)');
  if (input.requestLanguageName) {
    await group(io, input, options, [plain(['requestLanguageName', 'requestLanguageEmail'], async i => {
      if (!i.requestLanguageName) i.requestLanguageName = await io.ask('Its name');
      i.requestLanguageEmail = await io.ask('Your email, so we can tell you (optional)');
    })]);
  }

  io.say('\n3. First Data Analyst account (you sign in with it and create everyone else)');
  await group(io, input, options, [
    plain(['adminName'], async i => { i.admin.name = await io.ask('Display name'); }),
    plain(['adminEmail'], async i => { i.admin.email = await io.ask('Email (you sign in with it)'); }),
    plain(['adminPassword', 'adminPasswordAgain'], async i => {
      i.admin.password = await io.secret(`Password (at least ${PASSWORD_MIN} characters; typing is hidden)`);
      i.admin.passwordAgain = await io.secret('Password again');
    }),
  ]);

  io.say('\n4. Optional settings');
  if (/^y/i.test(await io.ask('Set up email for sign-in links and invitations now? y/N', 'n'))) {
    await group(io, input, options, [
      plain(['emailHost'], async i => { i.email.host = await io.ask('Mail server (for example smtp-relay.brevo.com)'); }),
      plain(['emailPort'], async i => { i.email.port = await io.ask('Port', '587'); }),
      plain([], async i => { i.email.user = await io.ask('User name'); i.email.password = await io.secret('Password or key (hidden)'); }),
      plain(['emailSender'], async i => { i.email.sender = await io.ask('Emails come from (address)'); }),
      plain([], async i => { i.email.senderName = await io.ask('Sender name (Enter: the mission name)'); }),
    ]);
  }
  await group(io, input, options, [
    plain(['publicDomain'], async i => { i.publicDomain = await io.ask('Public web name, for example example.org (Enter: office network only)'); }),
    plain(['timeZone'], async i => { i.timeZone = await io.ask('Time zone, for example Europe/Berlin', defaultTimeZone); }),
  ]);

  io.say('\n5. Cloudflare tunnel (optional)');
  await group(io, input, options, [
    plain(['cloudflareToken'], async i => { i.cloudflareToken = await io.secret('Tunnel token, or the whole install command from Cloudflare (hidden; needs the public web name; Enter to skip: local network only)'); }),
  ]);

  const result = validate(input, options);
  if (!result.ok) throw new Error('The answers are not complete: ' + Object.values(result.errors).join(' '));
  return result;
}
